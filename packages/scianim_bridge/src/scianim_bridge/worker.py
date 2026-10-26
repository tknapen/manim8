"""Worker entry point: `python -m scianim_bridge.worker job.json` inside a family environment.

Reads the job, configures Manim, runs the scene (fast-forwarded for snapshots), and writes
`result.json` into the job's output directory. Progress goes to stdout as JSON lines.
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

from scianim_bridge import __version__ as bridge_version
from scianim_bridge import context as _context
from scianim_core import ToolVersions, WorkerResult


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


def load_scene_class(module_path: Path, class_name: str):
    code_dir = str(module_path.parent)
    if code_dir not in sys.path:
        sys.path.insert(0, code_dir)
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
    try:
        from manim import ManimColor, tempconfig

        settings = {
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
            "save_sections": job.manim.save_sections,
            "format": "png" if ctx.mode == "snapshot" else "mp4",
        }
        emit(
            "start",
            job_id=job.job_id,
            mode=ctx.mode,
            settings={k: str(v) for k, v in settings.items()},
        )
        with tempconfig(settings):
            from manim import config

            config.frame_width = config.frame_height * job.manim.pixel_width / job.manim.pixel_height
            scene_class = load_scene_class(project_root / job.scene_module, job.scene_class)
            scene = scene_class()
            scene.ctx = ctx
            scene.render()
            warnings.extend(getattr(scene, "timing_warnings", []))
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
        tool_versions=tool_versions(),
        elapsed_seconds=time.monotonic() - start,
        errors=errors,
        warnings=warnings,
    )
    (ctx.output_dir / "result.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    emit(
        "done",
        status=status,
        checkpoints=len(result.checkpoints),
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
