"""Worker entry point: `python -m scianim_bridge.worker job.json` inside a family environment.

Reads the job, configures Manim, runs the scene (fast-forwarded for snapshots and for the planning pass of a
parallel render, windowed to a range of plays for a part), or joins the segments of a parallel render, and
writes `result.json` into the job's output directory. Progress goes to stdout as JSON lines.
"""

from __future__ import annotations

import importlib.util
import json
import os
import platform
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from scianim_bridge import __version__ as bridge_version
from scianim_bridge import context as _context
from scianim_core import PlayRecord, ReachedCheckpoint, SegmentRecord, ToolVersions, WorkerResult
from scianim_core.timing import TimingReport


def _version(module: str) -> str | None:
    try:
        return importlib.import_module(module).__version__
    except Exception:
        return None


def tool_versions() -> ToolVersions:
    import scianim_core

    return ToolVersions(
        python=platform.python_version(),
        platform=platform.platform(),
        manim=_version("manim"),
        scianim_bridge=bridge_version,
        scianim_core=scianim_core.__version__,
        typst=_version("typst"),
        av=_version("av"),
    )


def emit(event: str, **data: object) -> None:
    print(json.dumps({"event": event, **data}), flush=True)


def _family_component_dirs() -> list[str]:
    family_root = os.environ.get("SCIANIM_FAMILY_ROOT")
    return [str(Path(family_root) / "components")] if family_root else []


def load_scene_class(module_path: Path, class_name: str):
    for directory in [str(module_path.parent), *_family_component_dirs()]:
        if directory not in sys.path:
            sys.path.insert(0, directory)
    spec = importlib.util.spec_from_file_location(module_path.stem, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load scene module {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_path.stem] = module
    spec.loader.exec_module(module)
    try:
        return getattr(module, class_name)
    except AttributeError:
        raise ImportError(f"{module_path} defines no class {class_name}") from None


def manim_settings(ctx: _context.JobContext, project_root: Path) -> dict[str, Any]:
    """Manim's configuration for this job: the job's settings, plus the mode's output format and, for a part of
    a parallel render, the window of animation numbers it draws (Manim's own `-n` option)."""
    from manim import ManimColor

    job = ctx.job
    settings: dict[str, Any] = {
        "renderer": job.manim.renderer,
        "pixel_width": job.manim.pixel_width,
        "pixel_height": job.manim.pixel_height,
        "frame_rate": job.manim.frame_rate,
        "background_color": ManimColor(job.manim.background_color),
        "media_dir": str(project_root / job.manim.media_dir),
        "disable_caching": job.manim.disable_caching,
        "preview": False,
        "progress_bar": "none",
        "verbosity": "WARNING",
        "log_to_file": False,
        "output_file": job.job_id,
        "save_sections": job.manim.save_sections and ctx.mode == "video",
        # A still output makes Manim skip every play: snapshots and the planning pass run the scene that way.
        "format": "png" if ctx.mode in ("snapshot", "plan") else "mp4",
    }
    if ctx.mode == "part":
        part = job.part
        assert part is not None
        settings["output_file"] = f"{job.job_id}.part{part.index}"
        settings["from_animation_number"] = part.first_play
        settings["upto_animation_number"] = part.last_play
        # The merge reads the segments after this process has ended; Manim must not prune them.
        settings["max_files_cached"] = -1
    return settings


def play_records(scene: Any) -> list[PlayRecord]:
    return [
        PlayRecord(
            index=e["index"],
            scene_id=e["scene_id"],
            start_seconds=e["time"],
            frames=e["frames"],
            static=bool(e.get("static", False)),
            drawn=bool(e.get("drawn", False)),
            seconds=max(0.0, float(e.get("seconds", 0.0))),
        )
        for e in scene.play_log
    ]


def reached_checkpoints(scene: Any) -> list[ReachedCheckpoint]:
    return [
        ReachedCheckpoint(snapshot_id=e["snapshot_id"], animation_index=e["animation_index"], time_seconds=e["time"])
        for e in scene.checkpoint_log
    ]


def write_subtitles(scene: Any, ctx: _context.JobContext) -> str | None:
    """The subcaptions the scene added, as an SRT file (Manim writes one only for a video output)."""
    subcaptions = list(getattr(scene.renderer.file_writer, "subcaptions", None) or [])
    if not subcaptions:
        return None
    import srt

    path = ctx.output_dir / f"{ctx.job.job_id}.srt"
    path.write_text(srt.compose(subcaptions), encoding="utf-8")
    return ctx.job.output_dir.rstrip("/") + "/" + path.name


def collect_segments(scene: Any, ctx: _context.JobContext, errors: list[str]) -> list[SegmentRecord]:
    """The segment Manim encoded for each play in this part's range (`None` marks a fast-forwarded play)."""
    part = ctx.job.part
    assert part is not None
    by_index = {e["index"]: e for e in scene.play_log}
    root = ctx.project_root.resolve()
    segments: list[SegmentRecord] = []
    for index, path in enumerate(scene.renderer.file_writer.partial_movie_files):
        if path is None:
            continue
        entry = by_index.get(index)
        if entry is None:
            errors.append(f"Manim encoded a segment for play {index}, which the scene did not log")
            continue
        file = Path(path)
        if not file.exists():
            errors.append(f"Manim left no segment for play {index} at {file}")
            continue
        try:
            relative = file.resolve().relative_to(root).as_posix()
        except ValueError:
            errors.append(f"segment {file} lies outside the project")
            continue
        segments.append(
            SegmentRecord(play_index=index, scene_id=entry["scene_id"], path=relative, frames=int(entry["frames"]))
        )
    drawn = {segment.play_index for segment in segments}
    wanted = set(range(part.first_play, part.last_play + 1))
    if drawn != wanted:
        errors.append(
            f"part {part.index} was to draw plays {part.first_play}-{part.last_play} but drew {sorted(drawn)}; "
            "the scene did not play the same way as in the planning pass"
        )
    return segments


def _timing_verdict(
    ctx: _context.JobContext, timing: TimingReport | None, errors: list[str], warnings: list[str]
) -> None:
    if timing is None or timing.within_tolerance:
        return
    problems = "; ".join(timing.problems())
    if ctx.job.quality_profile == "final":
        errors.append(f"timing does not match the storyboard: {problems}")
    else:
        warnings.append(f"timing differs from the storyboard: {problems}")


def run(job_file: Path, project_root: Path) -> WorkerResult:
    ctx = _context.JobContext.from_file(job_file, project_root)
    _context.set_current(ctx)
    os.environ[_context.JOB_FILE_ENV] = str(job_file)
    os.environ[_context.PROJECT_ROOT_ENV] = str(project_root)
    job = ctx.job
    start = time.monotonic()
    errors: list[str] = []
    warnings: list[str] = []
    status = "failed"
    videos: list = []
    sections: list = []
    subtitles = None
    timing = None
    plays: list[PlayRecord] = []
    reached: list[ReachedCheckpoint] = []
    segments: list[SegmentRecord] = []
    try:
        if ctx.mode == "merge":
            assert job.merge is not None
            emit("start", job_id=job.job_id, mode=ctx.mode, segments=len(job.merge.segments))
            from scianim_bridge.video import merge_video_outputs

            outputs = merge_video_outputs(ctx)
            videos, sections, subtitles, timing = outputs.videos, outputs.sections, outputs.subtitles, outputs.timing
            ctx.records.extend(outputs.samples)
            warnings.extend(outputs.warnings)
            errors.extend(outputs.errors)
            _timing_verdict(ctx, timing, errors, warnings)
            plays, segments = list(job.merge.plays), list(job.merge.segments)
            if not errors:
                status = "succeeded"
        else:
            from manim import tempconfig

            settings = manim_settings(ctx, project_root)
            emit("start", job_id=job.job_id, mode=ctx.mode, settings={k: str(v) for k, v in settings.items()})
            with tempconfig(settings):
                from manim import config

                config.frame_width = config.frame_height * job.manim.pixel_width / job.manim.pixel_height
                scene_class = load_scene_class(project_root / job.scene_module, job.scene_class)
                scene = scene_class()
                scene.ctx = ctx
                scene.render()
                warnings.extend(getattr(scene, "timing_warnings", []))
                warnings.extend(getattr(scene, "render_warnings", []))
                from scianim_bridge.tokens import FONT_WARNINGS

                warnings.extend(FONT_WARNINGS)
                plays = play_records(scene)
                reached = reached_checkpoints(scene)
                if ctx.mode == "video":
                    from scianim_bridge.video import collect_video_outputs

                    outputs = collect_video_outputs(scene, ctx)
                    videos, sections, subtitles, timing = (
                        outputs.videos,
                        outputs.sections,
                        outputs.subtitles,
                        outputs.timing,
                    )
                    ctx.records.extend(outputs.samples)
                    warnings.extend(outputs.warnings)
                    errors.extend(outputs.errors)
                    _timing_verdict(ctx, timing, errors, warnings)
                    if not errors:
                        status = "succeeded"
                elif ctx.mode == "plan":
                    subtitles = write_subtitles(scene, ctx)
                    if plays:
                        status = "succeeded"
                    else:
                        errors.append(f"{job.scene_class}.construct plays nothing; there is nothing to render")
                elif ctx.mode == "part":
                    segments = collect_segments(scene, ctx, errors)
                    if not errors:
                        status = "succeeded"
                else:
                    wanted = set(job.snapshot_ids) if job.snapshot_ids else set(job.snapshots)
                    unreached = sorted(wanted - ctx.captured)
                    if unreached:
                        errors.append(f"checkpoint(s) never reached in {job.scene_class}.construct: {unreached}")
                    else:
                        status = "succeeded"
    except Exception:
        errors.append(traceback.format_exc())
    result = WorkerResult(
        job_id=job.job_id,
        status=status,
        checkpoints=list(ctx.records),
        videos=videos,
        sections=sections,
        subtitles=subtitles,
        timing=timing,
        plays=plays,
        reached=reached,
        segments=segments,
        tool_versions=tool_versions(),
        elapsed_seconds=time.monotonic() - start,
        errors=errors,
        warnings=warnings,
    )
    (ctx.output_dir / "result.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    emit(
        "done",
        status=status,
        mode=ctx.mode,
        checkpoints=len(result.checkpoints),
        videos=len(result.videos),
        plays=len(result.plays),
        segments=len(result.segments),
        elapsed=round(result.elapsed_seconds, 2),
    )
    return result


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m scianim_bridge.worker <job.json>", file=sys.stderr)
        return 2
    job_file = Path(args[0]).resolve()
    project_root = Path(os.environ.get(_context.PROJECT_ROOT_ENV) or Path.cwd()).resolve()
    result = run(job_file, project_root)
    if result.status != "succeeded":
        for line in result.errors:
            print(line, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
