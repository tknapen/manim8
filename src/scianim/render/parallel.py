"""Parallel video renders: plan the plays, draw ranges of them in several workers at once, join the segments.

A video job with `workers` above one runs in three stages, each a bridge worker in the family environment
(ADR-029). The planning pass fast-forwards through the scene and lists every play with its frames. The plays
are split into contiguous ranges holding about the same number of frames, and one worker per range renders
its plays through Manim's own animation-number window while fast-forwarding through the rest, so each part
begins from exactly the state a serial render would have reached. The merge joins the encoded segments
without re-encoding, then verifies the timing and samples the checkpoints as a serial render does. The
manifest, the cache key and the output layout are those of a serial render; the stages leave their job files,
logs and results under the job's directory.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from scianim.config.loader import SpecError
from scianim.families.resolve import FamilyContext
from scianim.project import Project
from scianim.render.jobs import (
    JobPaths,
    LaunchedJob,
    complete_stage,
    finish_manifest,
    launch_job,
)
from scianim_core import (
    ArtifactManifest,
    InputHashes,
    MergeInputs,
    PartRange,
    PartReport,
    PlayRecord,
    RenderJob,
    SegmentRecord,
    WorkerResult,
)

POLL_SECONDS = 0.25


class JobCanceled(Exception):
    """The caller asked to stop; every running worker was killed."""


def resolve_workers(requested: int) -> int:
    """`0` (or less) means one worker per CPU core; otherwise the number asked for."""
    return max(1, os.cpu_count() or 1) if requested <= 0 else requested


def split_plays(weights: Sequence[float], count: int) -> list[tuple[int, int]]:
    """Contiguous ranges of play indices (inclusive ends) whose summed weights are as even as possible.

    Each range holds at least one play, so there are never more ranges than plays. A range closes once
    adding the next play would take its cumulative weight further from the even share than it is."""
    n = len(weights)
    if n == 0:
        return []
    count = max(1, min(count, n))
    total = float(sum(weights))
    ranges: list[tuple[int, int]] = []
    start = 0
    accumulated = 0.0
    for k in range(1, count):
        last_allowed = n - (count - k) - 1  # leave one play for every range still to come
        target = total * k / count
        end = start
        accumulated += weights[start]
        while end < last_allowed and abs(accumulated + weights[end + 1] - target) <= abs(accumulated - target):
            end += 1
            accumulated += weights[end]
        ranges.append((start, end))
        start = end + 1
    ranges.append((start, n - 1))
    return ranges


def estimated_weight(play: PlayRecord) -> float:
    """What a play costs relative to the others before anything has been measured: a frame per frame, except
    that a static wait draws one frame and only encodes the repeats."""
    return 1.0 + play.frames / 10.0 if play.static else float(play.frames)


def same_plays(a: Sequence[PlayRecord], b: Sequence[PlayRecord]) -> bool:
    """The same scene structure: play for play the same frames, scene and kind (times may differ)."""
    return len(a) == len(b) and all(
        (x.index, x.frames, x.scene_id, x.static) == (y.index, y.frames, y.scene_id, y.static)
        for x, y in zip(sorted(a, key=lambda p: p.index), sorted(b, key=lambda p: p.index), strict=True)
    )


def measured_weights(project: Project, plays: Sequence[PlayRecord]) -> tuple[list[float], str] | None:
    """Per-play wall times from the most recent render of this project whose plays match the plan, if any.

    Every finished render records how long each play took (a serial render directly, a parallel one from the
    part that drew the play), so the second render of a clip balances its parts by measurement. A play that
    Manim served from its per-play cache was not drawn and its time says nothing about drawing; such a play
    gets the estimate, scaled to the seconds per estimated frame of the plays that were drawn."""
    manifests = sorted(project.renders_dir.glob("*/*/manifest.json"), key=lambda path: path.parent.name, reverse=True)
    for path in manifests:
        try:
            manifest = ArtifactManifest.model_validate_json(path.read_text())
        except (OSError, ValueError):
            continue
        if manifest.job.operation != "render_video" or manifest.result.status != "succeeded":
            continue
        recorded = sorted(manifest.result.plays, key=lambda p: p.index)
        drawn = [play for play in recorded if play.drawn and play.seconds > 0]
        if not recorded or not drawn or not same_plays(recorded, plays):
            continue
        rates = sorted(play.seconds / estimated_weight(play) for play in drawn)
        rate = rates[len(rates) // 2]
        floor = 1e-3
        weights = [
            max(floor, play.seconds) if play.drawn and play.seconds > 0 else max(floor, rate * estimated_weight(play))
            for play in recorded
        ]
        return weights, manifest.job.job_id
    return None


def part_ranges(plays: Sequence[PlayRecord], workers: int, weights: Sequence[float] | None = None) -> list[PartRange]:
    ordered = sorted(plays, key=lambda play: play.index)
    if [play.index for play in ordered] != list(range(len(ordered))):
        raise SpecError(Path("plan"), f"the plan's plays are not numbered 0..{len(ordered) - 1}")
    if weights is None:
        weights = [estimated_weight(play) for play in ordered]
    if len(weights) != len(ordered):
        raise ValueError("one weight per play")
    ranges = split_plays(weights, workers)
    return [
        PartRange(
            index=k,
            count=len(ranges),
            first_play=first,
            last_play=last,
            frames=sum(play.frames for play in ordered[first : last + 1]),
        )
        for k, (first, last) in enumerate(ranges)
    ]


# --- derived jobs -------------------------------------------------------------------------------
def stage_paths(project: Project, parent: JobPaths, name: str, output_dir: Path | None = None) -> JobPaths:
    """Where a stage keeps its job file, logs and result: under the parent job's directory."""
    stage_dir = parent.job_dir / name
    return JobPaths(
        job_dir=stage_dir,
        job_file=stage_dir / "job.json",
        log_file=stage_dir / "worker.log",
        output_dir=output_dir if output_dir is not None else stage_dir,
        manifest_file=stage_dir / "manifest.json",
        cache_index=parent.cache_index,
    )


def _relative(project: Project, path: Path) -> str:
    return path.resolve().relative_to(project.root.resolve()).as_posix()


def plan_job(project: Project, job: RenderJob, paths: JobPaths) -> RenderJob:
    """The planning pass: the scene in fast-forward, listing its plays and the checkpoints it reaches."""
    return job.model_copy(
        update={
            "operation": "plan_video",
            "output_dir": _relative(project, paths.output_dir),
            "manim": job.manim.model_copy(update={"save_sections": False}),
        }
    )


def part_job(project: Project, job: RenderJob, paths: JobPaths, part: PartRange) -> RenderJob:
    """One part: the plays in `part`, encoded into its own media directory so parts never share files."""
    return job.model_copy(
        update={
            "operation": "render_video_part",
            "part": part,
            "output_dir": _relative(project, paths.output_dir),
            "manim": job.manim.model_copy(
                update={"media_dir": f"{job.manim.media_dir.rstrip('/')}/parts/{part.index}", "save_sections": False}
            ),
        }
    )


def merge_job(
    job: RenderJob, plan: WorkerResult, parts: Sequence[WorkerResult], ranges: Sequence[PartRange]
) -> RenderJob:
    """The merge: every segment in play order, with the plan's checkpoints and subtitles."""
    segments = sorted((segment for part in parts for segment in part.segments), key=lambda s: s.play_index)
    return job.model_copy(
        update={
            "operation": "merge_video",
            "merge": MergeInputs(
                plays=list(plan.plays),
                segments=segments,
                checkpoints=list(plan.reached),
                subtitles=plan.subtitles,
                parts=list(ranges),
            ),
        }
    )


# --- orchestration ------------------------------------------------------------------------------
def _kill(launched: Sequence[LaunchedJob]) -> None:
    for item in launched:
        if item.process.poll() is None:
            item.process.kill()
    for item in launched:
        if item.process.poll() is None:
            item.process.wait()


def _wait_all(
    launched: Sequence[LaunchedJob], deadline: float | None, cancel: Callable[[], bool] | None, what: str
) -> None:
    while any(item.process.poll() is None for item in launched):
        if cancel is not None and cancel():
            _kill(launched)
            raise JobCanceled(what)
        if deadline is not None and time.monotonic() > deadline:
            _kill(launched)
            raise SpecError(launched[0].paths.job_file, f"{what} exceeded the timeout and was killed")
        time.sleep(POLL_SECONDS)


def _check_parts_against_plan(plan: WorkerResult, parts: Sequence[WorkerResult], ranges: Sequence[PartRange]) -> None:
    """Every part fast-forwarded through the plays before its range and logged them; the log must be the plan's
    (the scene is deterministic, or the segments would not fit together)."""
    planned = {play.index: play for play in plan.plays}
    for part, rng in zip(parts, ranges, strict=True):
        for play in part.plays:
            if play.index > rng.last_play:
                continue
            expected = planned.get(play.index)
            if expected is None or (expected.frames, expected.scene_id) != (play.frames, play.scene_id):
                raise SpecError(
                    Path(f"part {rng.index}"),
                    f"play {play.index} ran as {play.frames} frames in scene '{play.scene_id}' but the planning pass "
                    f"saw {expected.frames if expected else 'no such play'}"
                    f"{f' in scene {expected.scene_id!r}' if expected else ''}; the scene does not play the same way "
                    "twice, so it cannot be rendered in parts",
                )
    drawn: dict[int, SegmentRecord] = {}
    for part in parts:
        for segment in part.segments:
            if segment.play_index in drawn:
                raise SpecError(Path("parts"), f"play {segment.play_index} was drawn by two parts")
            drawn[segment.play_index] = segment
    missing = sorted(set(planned) - set(drawn))
    if missing:
        raise SpecError(Path("parts"), f"no part drew play(s) {missing}")


def _measured_plays(plan: Sequence[PlayRecord], parts: Sequence[WorkerResult]) -> list[PlayRecord]:
    """The plan's plays with the wall time each took in the part that produced its segment, and whether that
    part drew it or Manim served it from its cache, so the next render can balance by measurement."""
    measured: dict[int, PlayRecord] = {}
    for part in parts:
        produced = {segment.play_index for segment in part.segments}
        for play in part.plays:
            if play.index in produced:
                measured[play.index] = play
    return [
        play.model_copy(update={"seconds": m.seconds, "drawn": m.drawn}) if (m := measured.get(play.index)) else play
        for play in plan
    ]


def _dedupe(*groups: Sequence[str]) -> list[str]:
    seen: list[str] = []
    for group in groups:
        for item in group:
            if item not in seen:
                seen.append(item)
    return seen


def run_parallel_video(
    project: Project,
    family: FamilyContext,
    job: RenderJob,
    paths: JobPaths,
    hashes: InputHashes,
    *,
    timeout: float | None = 3600,
    cancel: Callable[[], bool] | None = None,
    log: Callable[[str], None] | None = None,
) -> ArtifactManifest:
    """Plan, render the parts at once, merge; then write the job's manifest as for a serial render.

    `timeout` bounds the whole pipeline; `cancel` is polled while workers run and, when it returns true, the
    workers are killed and `JobCanceled` is raised."""
    started = time.monotonic()
    deadline = None if timeout is None else started + timeout
    say = log or (lambda _message: None)
    paths.job_dir.mkdir(parents=True, exist_ok=True)
    paths.job_file.write_text(job.model_dump_json(indent=2))
    lines: list[str] = [f"parallel render with up to {job.workers} workers"]

    # 1. The planning pass.
    plan_paths = stage_paths(project, paths, "plan")
    plan_launched = launch_job(project, family, plan_job(project, job, plan_paths), plan_paths, hashes)
    say("planning: fast-forwarding through the scene to list its plays")
    _wait_all([plan_launched], deadline, cancel, "the planning pass")
    plan = complete_stage(plan_launched)
    if plan.status != "succeeded":
        raise SpecError(plan_paths.log_file, "the planning pass failed:\n" + "\n".join(plan.errors))
    measured = measured_weights(project, plan.plays)
    ranges = part_ranges(plan.plays, job.workers, measured[0] if measured else None)
    balance = f"balanced by the play times measured in {measured[1]}" if measured else "balanced by frames"
    total_frames = sum(play.frames for play in plan.plays)
    lines.append(
        f"plan: {len(plan.plays)} plays, {total_frames} frames, {len(plan.reached)} checkpoints "
        f"in {plan.elapsed_seconds:.1f}s -> {len(ranges)} part(s), {balance}"
    )
    say(
        f"plan: {len(plan.plays)} plays and {total_frames} frames split into {len(ranges)} part(s), {balance}: "
        + ", ".join(f"{r.first_play}-{r.last_play} ({r.frames} frames)" for r in ranges)
    )

    # 2. The parts, all at once.
    launched: list[LaunchedJob] = []
    for rng in ranges:
        stage = stage_paths(project, paths, f"parts/{rng.index}")
        launched.append(launch_job(project, family, part_job(project, job, stage, rng), stage, hashes))
    say(f"rendering {len(launched)} part(s) in parallel")
    _wait_all(launched, deadline, cancel, "the parts")
    results = [complete_stage(item) for item in launched]
    reports = [
        PartReport(part=rng, status=result.status, elapsed_seconds=result.elapsed_seconds)
        for rng, result in zip(ranges, results, strict=True)
    ]
    for rng, result in zip(ranges, results, strict=True):
        lines.append(
            f"part {rng.index}: plays {rng.first_play}-{rng.last_play}, {rng.frames} frames, "
            f"{result.status} in {result.elapsed_seconds:.1f}s"
        )
    failed = [(rng, result) for rng, result in zip(ranges, results, strict=True) if result.status != "succeeded"]
    if failed:
        rng, result = failed[0]
        stage = stage_paths(project, paths, f"parts/{rng.index}")
        raise SpecError(
            stage.log_file,
            f"part {rng.index} (plays {rng.first_play}-{rng.last_play}) failed:\n" + "\n".join(result.errors),
        )
    _check_parts_against_plan(plan, results, ranges)

    # 3. The merge, into the job's own output directory.
    merge_paths = stage_paths(project, paths, "merge", output_dir=paths.output_dir)
    say("joining the segments, verifying the timing and sampling the checkpoints")
    merge_launched = launch_job(project, family, merge_job(job, plan, results, ranges), merge_paths, hashes)
    _wait_all([merge_launched], deadline, cancel, "the merge")
    merged = complete_stage(merge_launched)
    lines.append(f"merge: {merged.status} in {merged.elapsed_seconds:.1f}s")
    elapsed = time.monotonic() - started
    result = merged.model_copy(
        update={
            "parts": reports,
            "plays": _measured_plays(plan.plays, results),
            "warnings": _dedupe(plan.warnings, *(r.warnings for r in results), merged.warnings),
            "elapsed_seconds": elapsed,
        }
    )
    # The job directory's `result.json` is the final result, as after a serial render (the merge wrote its own).
    (paths.output_dir / "result.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    paths.log_file.write_text(
        "\n".join(lines)
        + f"\ntotal {elapsed:.1f}s\n\nstage logs: {plan_paths.log_file}, "
        + ", ".join(str(stage_paths(project, paths, f"parts/{r.index}").log_file) for r in ranges)
        + f", {merge_paths.log_file}\n"
    )
    return finish_manifest(project, job, paths, hashes, result)


__all__ = [
    "JobCanceled",
    "estimated_weight",
    "measured_weights",
    "merge_job",
    "part_job",
    "part_ranges",
    "plan_job",
    "resolve_workers",
    "run_parallel_video",
    "same_plays",
    "split_plays",
    "stage_paths",
]
