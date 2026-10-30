"""Video outputs: locate Manim's artifacts, probe them with PyAV, sample frames, verify timing.

Runs inside the family environment (PyAV and Manim are available there, never in the control plane).
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Sequence
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any

import av

from scianim_core import CheckpointRecord, SectionRecord, SegmentRecord, VideoRecord, verify_timing
from scianim_core.timing import TimingReport

if TYPE_CHECKING:
    from scianim_bridge.context import JobContext
    from scianim_bridge.scene import SnapshotScene


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class Probe:
    width: int
    height: int
    fps: float
    frames: int
    duration_seconds: float
    codec: str | None
    pixel_format: str | None


def probe_video(path: Path) -> Probe:
    """Container metadata plus an exact frame count obtained by decoding (metadata counts can lie)."""
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        # The base rate is the nominal frame rate; the average rate is duration-derived and can be off by a
        # millisecond's rounding (30.0011 fps for an 18 s movie), which is not a frame-rate error.
        rate = stream.base_rate or stream.guessed_rate or stream.average_rate
        fps = float(rate) if rate else 0.0
        frames = 0
        last_time: float | None = None
        for frame in container.decode(stream):
            frames += 1
            if frame.time is not None:
                last_time = float(frame.time)
        if fps <= 0 and last_time is not None and frames > 1:
            fps = (frames - 1) / last_time
        duration = frames / fps if fps > 0 else 0.0
        codec = stream.codec_context.name if stream.codec_context else None
        pixel_format = getattr(stream.codec_context, "pix_fmt", None)
        return Probe(stream.width, stream.height, fps, frames, duration, codec, pixel_format)


def concat_segments(inputs: Sequence[Path], output: Path) -> None:
    """Join encoded segments into one movie by copying their packets, as Manim joins its partial movie files.

    Nothing is decoded or re-encoded, so the joined movie carries exactly the frames of the segments, in order.
    """
    if not inputs:
        raise ValueError("no segments to join")
    missing = [str(path) for path in inputs if not Path(path).exists()]
    if missing:
        raise FileNotFoundError(f"segment(s) missing: {missing[:5]}")
    manifest = BytesIO("".join(f"file 'file:{Path(path).resolve().as_posix()}'\n" for path in inputs).encode("utf-8"))
    output.parent.mkdir(parents=True, exist_ok=True)
    with av.open(manifest, options={"safe": "0", "an": "1"}, format="concat") as source:
        stream = source.streams.video[0]
        with av.open(str(output), mode="w") as target:
            out_stream = target.add_stream_from_template(template=stream)
            for packet in source.demux(stream):
                if packet.dts is None:  # the flushing packets `demux` generates
                    continue
                packet.dts = None  # each segment restarts its clock; libav recomputes the decode stamps
                packet.stream = out_stream
                target.mux(packet)


@dataclass
class VideoOutputs:
    videos: list[VideoRecord] = field(default_factory=list)
    sections: list[SectionRecord] = field(default_factory=list)
    subtitles: str | None = None
    samples: list[CheckpointRecord] = field(default_factory=list)
    timing: TimingReport | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _relative(ctx: JobContext, path: Path) -> str:
    return ctx.job.output_dir.rstrip("/") + "/" + path.relative_to(ctx.output_dir).as_posix()


def collect_video_outputs(scene: SnapshotScene, ctx: JobContext) -> VideoOutputs:
    """Copy the movie, section videos, index and subtitles into the job directory and describe them."""
    out = VideoOutputs()
    job = ctx.job
    writer = scene.renderer.file_writer
    plan = writer.output_plan
    movie = plan.primary_artifact
    if movie is None or not Path(movie).exists():
        out.errors.append(f"Manim produced no movie file (expected {movie})")
        return out
    movie = Path(movie)
    target = ctx.output_dir / f"{job.job_id}.mp4"
    shutil.copy2(movie, target)
    probe = _describe_movie(out, target, ctx)

    # Sections: Manim's index lists each saved section with its video path relative to the sections dir.
    section_frames: list[tuple[str, int]] = []
    index_path = plan.section_index
    if job.manim.save_sections and index_path is not None and Path(index_path).exists():
        sections_dir = ctx.output_dir / "sections"
        sections_dir.mkdir(exist_ok=True)
        entries = json.loads(Path(index_path).read_text(encoding="utf-8"))
        rewritten: list[dict[str, Any]] = []
        for entry in entries:
            source = Path(plan.sections_dir) / entry["video"]
            if not source.exists():
                out.warnings.append(f"section video missing: {source}")
                continue
            destination = sections_dir / source.name
            shutil.copy2(source, destination)
            section_probe = probe_video(destination)
            section_frames.append((entry["name"], section_probe.frames))
            metadata = {k: v for k, v in entry.items() if k not in ("name", "type", "video")}
            metadata.update(
                {
                    "frames": section_probe.frames,
                    "duration_seconds": section_probe.duration_seconds,
                    "width_px": section_probe.width,
                    "height_px": section_probe.height,
                    "fps": section_probe.fps,
                    "sha256": sha256_of(destination),
                }
            )
            record = SectionRecord(
                name=entry["name"],
                type=entry.get("type", "default.normal"),
                video=_relative(ctx, destination),
                metadata=metadata,
            )
            out.sections.append(record)
            rewritten.append(record.model_dump(mode="json"))
        (sections_dir / "index.json").write_text(json.dumps(rewritten, indent=2), encoding="utf-8")

    subtitle_source = plan.subcaption_file
    if subtitle_source is not None and Path(subtitle_source).exists():
        out.subtitles = _copy_subtitles(Path(subtitle_source), ctx)

    reached = {
        str(entry["snapshot_id"]): (float(entry["time"]), int(entry["animation_index"]))
        for entry in scene.checkpoint_log
    }
    _verify_and_sample(out, target, probe, section_frames, reached, ctx)
    return out


def merge_video_outputs(ctx: JobContext) -> VideoOutputs:
    """Join the segments the parts of a parallel render drew into the movie and its sections, then verify and
    sample exactly as after a serial render (ADR-029)."""
    out = VideoOutputs()
    job = ctx.job
    merge = job.merge
    if merge is None:
        out.errors.append("merge_video needs `merge` inputs")
        return out
    plays = sorted(merge.plays, key=lambda play: play.index)
    by_index = {segment.play_index: segment for segment in merge.segments}
    missing = [play.index for play in plays if play.index not in by_index]
    unplanned = sorted(set(by_index) - {play.index for play in plays})
    if missing or unplanned:
        if missing:
            out.errors.append(f"no segment for play(s) {missing}")
        if unplanned:
            out.errors.append(f"segment(s) for play(s) {unplanned} that the plan does not list")
        return out
    ordered = [by_index[play.index] for play in plays]
    absent = [segment.path for segment in ordered if not (ctx.project_root / segment.path).exists()]
    if absent:
        out.errors.append(f"segment file(s) missing: {absent[:5]}")
        return out

    target = ctx.output_dir / f"{job.job_id}.mp4"
    concat_segments([ctx.project_root / segment.path for segment in ordered], target)
    probe = _describe_movie(out, target, ctx)
    planned = sum(play.frames for play in plays)
    if probe.frames != planned:
        out.errors.append(f"the joined movie has {probe.frames} frames, the plan's plays add up to {planned}")

    # Sections: consecutive plays of one storyboard scene, joined the same way.
    section_frames: list[tuple[str, int]] = []
    if job.manim.save_sections:
        sections_dir = ctx.output_dir / "sections"
        sections_dir.mkdir(exist_ok=True)
        groups: list[tuple[str, list[SegmentRecord]]] = []
        for play, segment in zip(plays, ordered, strict=True):
            name = play.scene_id or "autocreated"
            if groups and groups[-1][0] == name:
                groups[-1][1].append(segment)
            else:
                groups.append((name, [segment]))
        rewritten: list[dict[str, Any]] = []
        for index, (name, segments) in enumerate(groups):
            destination = sections_dir / f"{job.job_id}_{index:04}_{name}.mp4"
            concat_segments([ctx.project_root / segment.path for segment in segments], destination)
            section_probe = probe_video(destination)
            section_frames.append((name, section_probe.frames))
            record = SectionRecord(
                name=name,
                type="default.normal",
                video=_relative(ctx, destination),
                metadata={
                    "frames": section_probe.frames,
                    "duration_seconds": section_probe.duration_seconds,
                    "width_px": section_probe.width,
                    "height_px": section_probe.height,
                    "fps": section_probe.fps,
                    "sha256": sha256_of(destination),
                },
            )
            out.sections.append(record)
            rewritten.append(record.model_dump(mode="json"))
        (sections_dir / "index.json").write_text(json.dumps(rewritten, indent=2), encoding="utf-8")

    if merge.subtitles is not None:
        source = ctx.project_root / merge.subtitles
        if source.exists():
            out.subtitles = _copy_subtitles(source, ctx)
        else:
            out.warnings.append(f"the plan's subtitle file is missing: {merge.subtitles}")

    reached = {c.snapshot_id: (c.time_seconds, c.animation_index) for c in merge.checkpoints}
    _verify_and_sample(out, target, probe, section_frames, reached, ctx)
    return out


def _describe_movie(out: VideoOutputs, target: Path, ctx: JobContext) -> Probe:
    """Probe the movie in the job directory, record it and check it against the job's settings."""
    job = ctx.job
    probe = probe_video(target)
    out.videos.append(
        VideoRecord(
            path=_relative(ctx, target),
            width_px=probe.width,
            height_px=probe.height,
            fps=probe.fps,
            duration_seconds=probe.duration_seconds,
            frame_count=probe.frames,
            codec=probe.codec,
            sha256=sha256_of(target),
        )
    )
    expected = (job.manim.pixel_width, job.manim.pixel_height)
    if (probe.width, probe.height) != expected:
        out.errors.append(f"movie is {probe.width}x{probe.height}, the job asked for {expected[0]}x{expected[1]}")
    if abs(probe.fps - job.manim.frame_rate) > 1e-2:
        out.errors.append(f"movie plays at {probe.fps:g} fps, the job asked for {job.manim.frame_rate:g}")
    return probe


def _copy_subtitles(source: Path, ctx: JobContext) -> str:
    subtitle_target = ctx.output_dir / f"{ctx.job.job_id}.srt"
    shutil.copy2(source, subtitle_target)
    return _relative(ctx, subtitle_target)


def _verify_and_sample(
    out: VideoOutputs,
    target: Path,
    probe: Probe,
    section_frames: list[tuple[str, int]],
    reached: dict[str, tuple[float, int]],
    ctx: JobContext,
) -> None:
    """Compare the frame counts with the storyboard and sample every checkpoint at the time the scene reached it,
    plus the extra samples the job asks for."""
    job = ctx.job
    out.timing = verify_timing(
        [(s.scene_id, s.start_seconds, s.end_seconds) for s in job.scenes],
        section_frames,
        probe.frames,
        job.manim.frame_rate,
        job.output.duration_seconds,
    )
    if not job.manim.save_sections or not section_frames:
        out.timing.notes.append("sections were not saved; only the total was verified")

    targets: dict[str, tuple[float, float, str | None, int]] = {}
    for snapshot_id, snapshot in job.snapshots.items():
        entry = reached.get(snapshot_id)
        actual = entry[0] if entry else snapshot.expected_time_seconds
        targets[snapshot_id] = (
            snapshot.expected_time_seconds,
            actual,
            snapshot.scene_id,
            entry[1] if entry else 0,
        )
        if entry is None:
            out.warnings.append(
                f"checkpoint '{snapshot_id}' was not reached in video mode; sampled at its storyboard time"
            )
    for sample_id, seconds in job.samples.items():
        scene_id = next((s.scene_id for s in job.scenes if s.start_seconds <= seconds <= s.end_seconds), None)
        targets[sample_id] = (seconds, seconds, scene_id, 0)
    out.samples = sample_frames(target, targets, ctx, probe.fps)


def sample_frames(
    movie: Path, targets: dict[str, tuple[float, float, str | None, int]], ctx: JobContext, fps: float
) -> list[CheckpointRecord]:
    """Decode the movie once and save the first frame at or after each requested time."""
    from PIL import Image

    if not targets:
        return []
    pending = sorted(targets.items(), key=lambda item: item[1][1])
    records: list[CheckpointRecord] = []
    half_frame = 0.5 / fps if fps > 0 else 0.0
    with av.open(str(movie)) as container:
        stream = container.streams.video[0]
        last_frame = None
        index = -1
        for frame in container.decode(stream):
            index += 1
            last_frame = frame
            time = float(frame.time) if frame.time is not None else index / fps
            while pending and time >= pending[0][1][1] - half_frame:
                sample_id, (expected, _wanted, scene_id, animation_index) = pending.pop(0)
                records.append(
                    _save_sample(frame, index, time, sample_id, expected, scene_id, animation_index, ctx, Image)
                )
        # Targets at or beyond the end of the movie get the last frame, flagged as approximate.
        for sample_id, (expected, wanted, scene_id, animation_index) in pending:
            if last_frame is None:
                break
            time = float(last_frame.time) if last_frame.time is not None else index / fps
            record = _save_sample(last_frame, index, time, sample_id, expected, scene_id, animation_index, ctx, Image)
            record = record.model_copy(
                update={
                    "fidelity": "approximate",
                    "fidelity_note": f"requested {wanted:g}s lies beyond the last frame at {time:.3f}s",
                }
            )
            records.append(record)
    return records


def _save_sample(
    frame: Any,
    index: int,
    time: float,
    sample_id: str,
    expected: float,
    scene_id: str | None,
    animation_index: int,
    ctx: JobContext,
    Image: Any,
) -> CheckpointRecord:
    image = frame.to_image()
    png_path = ctx.output_dir / f"{sample_id}.png"
    image.save(png_path, format="PNG")
    return CheckpointRecord(
        snapshot_id=sample_id,
        scene_id=scene_id or "unknown",
        kind="sampled_video_frame",
        png=_relative(ctx, png_path),
        width_px=image.width,
        height_px=image.height,
        sha256=sha256_of(png_path),
        animation_index=animation_index,
        expected_time_seconds=expected,
        renderer_time_seconds=time,
        fidelity="exact",
        fidelity_note=f"frame {index} of the rendered video",
        layout=[],
        warnings=[],
    )


__all__ = [
    "Probe",
    "VideoOutputs",
    "collect_video_outputs",
    "concat_segments",
    "merge_video_outputs",
    "probe_video",
    "sample_frames",
    "sha256_of",
]
