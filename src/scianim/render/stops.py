"""Stops of a rendered movie (ADR-045): where a player may hold one clip, frame-exactly.

After a video job the control plane derives `result.stops` from what the job and the worker already record: the
job's snapshot targets (which carry `stop`, `label` and `frozen`), the checkpoints the scene reached with their
clock, the plays with their frames and whether anything moved, and the sampled frames. The bridge writes none of
it. The render policy follows: a stop whose frame is not the first frame of a play, or whose rest before it holds a
play that moves, fails a final render and is a warning in any other.
"""

from __future__ import annotations

import math
from itertools import pairwise

from scianim_core import PlayRecord, RenderJob, StopRecord, WorkerResult
from scianim_core.storyboard import STOP_REST_SECONDS


def rest_frames_needed(fps: float) -> int:
    """Whole frames of rest a stop needs before it at `fps`: the 0.3 s of the validation rule, rounded down so that
    a rest the storyboard gives exactly is not refused for a rounding of its ends."""
    return math.floor(STOP_REST_SECONDS * fps + 1e-9)


def _grid(plays: list[PlayRecord], fps: float) -> tuple[dict[int, PlayRecord], dict[int, PlayRecord]]:
    """The plays by the frame they start on and by the frame after their last."""
    starts: dict[int, PlayRecord] = {}
    ends: dict[int, PlayRecord] = {}
    for play in sorted(plays, key=lambda p: (p.start_seconds, p.index)):
        first = round(play.start_seconds * fps)
        starts.setdefault(first, play)
        ends[first + play.frames] = play
    return starts, ends


def derive_stops(job: RenderJob, result: WorkerResult) -> tuple[list[StopRecord], list[str], list[str]]:
    """The movie's stops in time order, the problems that make a player's hold inexact (an error in a final render,
    a warning otherwise), and notes that are warnings in any render."""
    fps = job.manim.frame_rate
    starts, ends = _grid(list(result.plays), fps)
    reached = {r.snapshot_id: r for r in result.reached}
    sampled = {c.snapshot_id: c for c in result.checkpoints}
    needed = rest_frames_needed(fps)
    stops: list[StopRecord] = []
    problems: list[str] = []
    notes: list[str] = []
    for snapshot_id, target in job.snapshots.items():
        if not target.stop:
            continue
        record = sampled.get(snapshot_id)
        if snapshot_id in reached:
            frame = round(reached[snapshot_id].time_seconds * fps)
        elif record is not None and record.frame_index is not None:
            frame = record.frame_index
        elif record is not None and record.renderer_time_seconds is not None:
            frame = round(record.renderer_time_seconds * fps)
        else:
            frame = round(target.expected_time_seconds * fps)
            notes.append(f"stop '{snapshot_id}': the render recorded no time for it; placed at its storyboard time")
        if record is not None and record.frame_index is not None and record.frame_index != frame:
            problems.append(
                f"stop '{snapshot_id}': the scene reached it on frame {frame} but the still was sampled from frame "
                f"{record.frame_index}"
            )
        before = 0
        cursor = frame
        while cursor in ends and ends[cursor].static:
            before += ends[cursor].frames
            cursor -= ends[cursor].frames
        after = 0
        cursor = frame
        while cursor in starts and starts[cursor].static:
            after += starts[cursor].frames
            cursor += starts[cursor].frames
        if frame in starts and not starts[frame].static:
            notes.append(
                f"stop '{snapshot_id}': a motion starts on its frame {frame}, so the hold shows that motion's first "
                "frame, which can differ from the rest before it (a sweep's readout appears there, for one)"
            )
        if result.plays and frame not in starts:
            problems.append(
                f"stop '{snapshot_id}' is on frame {frame}, which no play starts on; a player could not hold the "
                "frame the scene reached there"
            )
        if result.plays and before < needed:
            message = (
                f"stop '{snapshot_id}' has {before} static frames before frame {frame}, fewer than the {needed} "
                f"({STOP_REST_SECONDS:g}s at {fps:g} fps) a player needs to pause early unseen"
            )
            if target.frozen:
                notes.append(f"{message}; the camera turns through it ({', '.join(target.frozen)}, stop_through)")
            else:
                problems.append(message + "; something moves there that validation did not see")
        stops.append(
            StopRecord(
                snapshot_id=snapshot_id,
                label=target.label or snapshot_id.replace("_", " "),
                notes=target.description,
                frame_index=frame,
                time_seconds=frame / fps,
                rest_before_frames=before,
                rest_after_frames=after,
                frozen=list(target.frozen),
            )
        )
    stops.sort(key=lambda s: s.frame_index)
    return stops, problems, notes


def apply_stops(job: RenderJob, result: WorkerResult) -> WorkerResult:
    """`result` with its stops, under the render policy: a final render with a problem fails, any other warns.
    Returns `result` itself when the job has no stops or the render did not succeed."""
    if result.status != "succeeded" or not any(t.stop for t in job.snapshots.values()):
        return result
    stops, problems, notes = derive_stops(job, result)
    errors, warnings, status = list(result.errors), list(result.warnings), result.status
    if problems and job.quality_profile == "final":
        errors.extend(f"stops: {problem}" for problem in problems)
        status = "failed"
    else:
        warnings.extend(f"stops: {problem}" for problem in problems)
    warnings.extend(f"stops: {note}" for note in notes)
    return result.model_copy(update={"stops": stops, "errors": errors, "warnings": warnings, "status": status})


def parts(boundaries: list[tuple[str, float]], end_seconds: float) -> list[tuple[str, str, float, float]]:
    """The parts a player presents between stops: (from, to, start, end), from the clip's start to its end."""
    points = [("start", 0.0), *boundaries, ("end", end_seconds)]
    return [(a, b, t0, t1) for (a, t0), (b, t1) in pairwise(points)]


__all__ = ["apply_stops", "derive_stops", "parts", "rest_frames_needed"]
