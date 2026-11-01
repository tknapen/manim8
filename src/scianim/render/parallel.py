"""Parallel video renders: plan the plays, draw ranges of them in several workers at once, join the segments.

A video job with `workers` above one runs in three stages, each a bridge worker in the family environment
(ADR-029). The planning pass fast-forwards through the scene and lists every play with its frames. The movie's
frames are split into contiguous windows holding about the same measured or estimated cost; a window may begin
or end inside a play that can be cut (ADR-031), in which case every part cuts that play at the same frame, so
Manim's animation numbers agree. One worker per window renders its pieces through Manim's own animation-number
window while fast-forwarding through the rest, so each part begins from exactly the state a serial render would
have reached. The merge joins the encoded segments without re-encoding, then verifies the timing and samples the
checkpoints as a serial render does. The manifest, the cache key and the output layout are those of a serial
render; the stages leave their job files, logs and results under the job's directory.
"""

from __future__ import annotations

import bisect
import os
import time
from collections.abc import Callable, Sequence
from itertools import pairwise
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
    ReachedCheckpoint,
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


MIN_PIECE_SECONDS = 0.5
"""A window boundary keeps at least this much of a play on either side of it; closer to a play's edge it snaps
to the edge, so no piece is shorter than half a second (ADR-031)."""


def ordered_plays(plays: Sequence[PlayRecord]) -> list[PlayRecord]:
    ordered = sorted(plays, key=lambda play: play.index)
    if [play.index for play in ordered] != list(range(len(ordered))):
        raise SpecError(Path("plan"), f"the plan's plays are not numbered 0..{len(ordered) - 1}")
    return ordered


def play_starts(plays: Sequence[PlayRecord]) -> list[int]:
    """The global frame at which each play begins, in play order, followed by the total frame count."""
    starts = [0]
    for play in plays:
        starts.append(starts[-1] + play.frames)
    return starts


def window_boundaries(
    plays: Sequence[PlayRecord], weights: Sequence[float], count: int, *, min_piece_frames: int
) -> list[int]:
    """The interior boundaries of `count` windows over the movie's frames, as increasing global frame indices.

    The cost of a play is spread evenly over its frames. Boundaries are placed in order, each at the frame
    where the cost since the previous boundary reaches an even share of what remains, so a boundary that had
    to move does not unbalance the windows after it. A boundary may fall on a play's edge, or inside a play
    that can be split as long as it leaves at least `min_piece_frames` on either side of it and after the
    previous boundary; it goes to the nearest such position (the edge when both are as near). Boundaries that
    would coincide, or sit at the very start or end of the movie, are dropped, so there may be fewer windows
    than asked for, never an empty one."""
    ordered = ordered_plays(plays)
    if not ordered or count <= 1:
        return []
    if len(weights) != len(ordered):
        raise ValueError("one weight per play")
    starts = play_starts(ordered)
    total_frames = starts[-1]
    cumulative = [0.0]
    for weight in weights:
        cumulative.append(cumulative[-1] + max(0.0, float(weight)))
    total_weight = cumulative[-1]
    if total_weight <= 0:
        return []
    margin = max(1, min_piece_frames)

    def weight_at(frame: int) -> float:
        i = min(len(ordered) - 1, bisect.bisect_right(starts, frame) - 1)
        return cumulative[i] + (cumulative[i + 1] - cumulative[i]) * (frame - starts[i]) / ordered[i].frames

    kept: list[int] = []
    last = 0
    consumed = 0.0
    for remaining_parts in range(count - 1, 0, -1):
        target = consumed + (total_weight - consumed) / (remaining_parts + 1)
        i = min(len(ordered) - 1, max(0, bisect.bisect_right(cumulative, target) - 1))
        lo, hi = starts[i], starts[i + 1]
        per_frame = (cumulative[i + 1] - cumulative[i]) / ordered[i].frames
        ideal = lo + (round((target - cumulative[i]) / per_frame) if per_frame > 0 else 0)
        ideal = min(hi, max(lo, ideal))
        allowed = [edge for edge in (lo, hi) if last < edge < total_frames]
        if ordered[i].splittable:
            first, final = max(lo, last) + margin, hi - margin
            if first <= final:
                allowed.append(min(final, max(first, ideal)))
        if not allowed:
            continue
        frame = min(allowed, key=lambda f: (abs(f - ideal), f not in starts))
        kept.append(frame)
        last, consumed = frame, weight_at(frame)
    return kept


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


def _scene_plays(plays: Sequence[PlayRecord]) -> dict[str | None, list[tuple[int, bool]]]:
    by_scene: dict[str | None, list[tuple[int, bool]]] = {}
    for play in sorted(plays, key=lambda p: p.index):
        by_scene.setdefault(play.scene_id, []).append((play.frames, play.static))
    return by_scene


def predicted_reuse(
    project: Project, job: RenderJob, hashes: InputHashes, plays: Sequence[PlayRecord]
) -> tuple[frozenset[int], str | None]:
    """The plays a render will find in the segment store: those of every scene whose fingerprint and plays equal
    the most recent succeeded video render's with the same store, and whose segments from that render are still
    in the store (ADR-033). The prediction steers the planner only; whether a play is drawn is decided by
    Manim's hash when the worker reaches it."""
    if not job.segment_store or not hashes.scene_fingerprints:
        return frozenset(), None
    now = _scene_plays(plays)
    manifests = sorted(project.renders_dir.glob("*/*/manifest.json"), key=lambda path: path.parent.name, reverse=True)
    for path in manifests:
        try:
            manifest = ArtifactManifest.model_validate_json(path.read_text())
        except (OSError, ValueError):
            continue
        if manifest.job.operation != "render_video" or manifest.result.status != "succeeded":
            continue
        if manifest.job.segment_store != job.segment_store or not manifest.inputs.scene_fingerprints:
            continue
        before = manifest.inputs.scene_fingerprints
        then = _scene_plays(manifest.result.plays)
        store = project.root / job.segment_store
        stored: dict[str | None, bool] = {}
        for segment in manifest.result.segments:
            present = (store / Path(segment.path).name).is_file()
            stored[segment.scene_id] = stored.get(segment.scene_id, True) and present
        unchanged = {
            scene_id
            for scene_id, fingerprint in hashes.scene_fingerprints.items()
            if before.get(scene_id) == fingerprint
            and now.get(scene_id) == then.get(scene_id)
            and stored.get(scene_id, False)  # the store still holds what that render drew for the scene
        }
        return frozenset(play.index for play in plays if play.scene_id in unchanged), manifest.job.job_id
    return frozenset(), None


def split_plan(plays: Sequence[PlayRecord], boundaries: Sequence[int], frame_rate: float) -> list[PlayRecord]:
    """The plan's plays as every part will play them: each play that a boundary falls inside becomes one piece
    per interval, numbered in order, carrying its `source_index` and `piece`; the others are unchanged apart
    from their index. This is the numbering Manim's animation numbers follow in every part (ADR-031)."""
    ordered = ordered_plays(plays)
    starts = play_starts(ordered)
    cuts = sorted(set(boundaries))
    pieces: list[PlayRecord] = []
    for i, play in enumerate(ordered):
        lo, hi = starts[i], starts[i + 1]
        inside = [cut for cut in cuts if lo < cut < hi]
        if inside and not play.splittable:
            raise SpecError(Path("plan"), f"boundary at frame {inside[0]} falls inside play {i}, which cannot be split")
        edges = [lo, *inside, hi]
        for piece, (a, b) in enumerate(pairwise(edges)):
            pieces.append(
                play.model_copy(
                    update={
                        "index": len(pieces),
                        "start_seconds": play.start_seconds + (a - lo) / frame_rate,
                        "frames": b - a,
                        "seconds": play.seconds * (b - a) / play.frames,
                        "source_index": play.index,
                        "piece": piece,
                    }
                )
            )
    return pieces


def renumber_checkpoints(
    reached: Sequence[ReachedCheckpoint], plays: Sequence[PlayRecord], pieces: Sequence[PlayRecord]
) -> list[ReachedCheckpoint]:
    """The plan's checkpoints with their animation numbers in the split plan's numbering. A checkpoint sits
    between plays, so its number is that of the first piece of the play that follows it."""
    first_piece: dict[int, int] = {}
    for piece in pieces:
        source = piece.source_index if piece.source_index is not None else piece.index
        first_piece.setdefault(source, piece.index)
    renumbered = []
    for checkpoint in reached:
        n = checkpoint.animation_index
        index = len(pieces) if n >= len(plays) else first_piece.get(n, n)
        renumbered.append(checkpoint.model_copy(update={"animation_index": index}))
    return renumbered


def boundaries_of(ranges: Sequence[PartRange]) -> list[int]:
    """The interior window boundaries a set of parts was planned with."""
    return [rng.first_frame for rng in ranges[1:]]


def plan_parts(
    plays: Sequence[PlayRecord],
    weights: Sequence[float] | None,
    workers: int,
    *,
    reusable: frozenset[int] = frozenset(),
    frame_rate: float = 30.0,
) -> list[PartRange]:
    """The one place that decides what each worker draws: windows of frames balanced by weight (ADR-031).

    A window may begin or end inside a play that can be split; its `first_play` and `last_play` count the
    pieces of `split_plan(plays, boundaries_of(parts), frame_rate)`, and every part carries the same
    `split_frames`, so all workers cut the same plays at the same frames. `frame_rate` sets the half-second
    minimum piece. `reusable` names plays whose segments an earlier render supplies, so no range has to draw
    them (ADR-033): they weigh next to nothing, because a worker links them from the segment store, and they
    are never cut, because a piece of a play has a new content hash and would miss the store."""
    ordered = ordered_plays(plays)
    if not ordered:
        return []
    if weights is None:
        weights = [estimated_weight(play) for play in ordered]
    if len(weights) != len(ordered):
        raise ValueError("one weight per play")
    if reusable:
        mean = sum(max(0.0, float(w)) for w in weights) / len(weights) or 1.0
        weights = [mean * 1e-6 if play.index in reusable else w for play, w in zip(ordered, weights, strict=True)]
        ordered = [
            play.model_copy(update={"splittable": False}) if play.index in reusable else play for play in ordered
        ]
    min_piece = max(1, round(MIN_PIECE_SECONDS * frame_rate))
    boundaries = window_boundaries(ordered, weights, workers, min_piece_frames=min_piece)
    pieces = split_plan(ordered, boundaries, frame_rate)
    piece_starts = play_starts(pieces)
    first_at = {start: k for k, start in enumerate(piece_starts[:-1])}
    last_at = {end: k for k, end in enumerate(piece_starts[1:])}
    edges = [0, *boundaries, piece_starts[-1]]
    return [
        PartRange(
            index=k,
            count=len(edges) - 1,
            first_play=first_at[a],
            last_play=last_at[b],
            frames=b - a,
            first_frame=a,
            last_frame=b - 1,
            split_frames=list(boundaries),
        )
        for k, (a, b) in enumerate(pairwise(edges))
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
    job: RenderJob,
    plan: WorkerResult,
    parts: Sequence[WorkerResult],
    ranges: Sequence[PartRange],
    pieces: Sequence[PlayRecord] | None = None,
) -> RenderJob:
    """The merge: every segment in play order, with the plan's checkpoints and subtitles. `pieces` is the split
    plan the parts played (every segment is one of its plays); without it the plan's plays stand as they are."""
    segments = sorted((segment for part in parts for segment in part.segments), key=lambda s: s.play_index)
    plays = list(plan.plays) if pieces is None else list(pieces)
    return job.model_copy(
        update={
            "operation": "merge_video",
            "merge": MergeInputs(
                plays=plays,
                segments=segments,
                checkpoints=renumber_checkpoints(plan.reached, plan.plays, plays),
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


def _describe(play: PlayRecord) -> str:
    piece = ""
    if play.source_index is not None and (play.piece or play.source_index != play.index):
        piece = f", piece {play.piece} of play {play.source_index}"
    return f"{play.frames} frames in scene '{play.scene_id}'{piece}"


def _check_parts_against_plan(
    pieces: Sequence[PlayRecord], parts: Sequence[WorkerResult], ranges: Sequence[PartRange]
) -> None:
    """Every part fast-forwarded through the plays before its range and logged them; the log must be the split
    plan, piece for piece (the scene is deterministic, or the segments would not fit together)."""
    planned = {play.index: play for play in pieces}
    for part, rng in zip(parts, ranges, strict=True):
        for play in part.plays:
            if play.index > rng.last_play:
                continue
            expected = planned.get(play.index)
            same = expected is not None and (expected.frames, expected.scene_id) == (play.frames, play.scene_id)
            if same and play.source_index is not None:
                assert expected is not None
                same = (expected.source_index, expected.piece) == (play.source_index, play.piece)
            if not same:
                raise SpecError(
                    Path(f"part {rng.index}"),
                    f"play {play.index} ran as {_describe(play)} but the plan has "
                    f"{_describe(expected) if expected else 'no such play'}; the scene does not play the same way "
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
    """The plan's plays with the wall time each took in the parts that produced its segments, whether they
    drew it or Manim served it from its cache, and its content hash, so the next render can balance by
    measurement and a reader can see which plays matched the store. A play cut into pieces sums its pieces,
    counts as drawn only when every piece was, and has no single hash; the manifest keeps the planning pass's
    numbering, so serial and parallel renders of a clip measure the same plays."""
    seconds: dict[int, float] = {}
    drawn: dict[int, bool] = {}
    hashes: dict[int, list[str | None]] = {}
    for part in parts:
        produced = {segment.play_index for segment in part.segments}
        for play in part.plays:
            if play.index in produced:
                source = play.source_index if play.source_index is not None else play.index
                seconds[source] = seconds.get(source, 0.0) + play.seconds
                drawn[source] = drawn.get(source, True) and play.drawn
                hashes.setdefault(source, []).append(play.content_hash)
    return [
        play.model_copy(
            update={
                "seconds": seconds[play.index],
                "drawn": drawn[play.index],
                "content_hash": hashes[play.index][0] if len(hashes[play.index]) == 1 else None,
            }
        )
        if play.index in seconds
        else play
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
    fps = job.manim.frame_rate
    reusable, reuse_source = predicted_reuse(project, job, hashes, plan.plays)
    ranges = plan_parts(plan.plays, measured[0] if measured else None, job.workers, reusable=reusable, frame_rate=fps)
    pieces = split_plan(plan.plays, boundaries_of(ranges), fps)
    cut = sorted({p.source_index for p in pieces if p.piece and p.source_index is not None})
    balance = f"balanced by the play times measured in {measured[1]}" if measured else "balanced by frames"
    total_frames = sum(play.frames for play in plan.plays)
    lines.append(
        f"plan: {len(plan.plays)} plays, {total_frames} frames, {len(plan.reached)} checkpoints "
        f"in {plan.elapsed_seconds:.1f}s -> {len(ranges)} part(s), {balance}"
    )
    if reusable:
        unchanged = sorted({str(p.scene_id) for p in plan.plays if p.index in reusable})
        note = (
            f"{len(reusable)} play(s) of unchanged scene(s) {unchanged} expected from the segment store "
            f"(fingerprints as in {reuse_source}); they are not cut and weigh next to nothing"
        )
        lines.append(note)
        say(note)
    if cut:
        lines.append(
            f"window boundaries at frames {boundaries_of(ranges)} cut play(s) {cut} into pieces; "
            f"the parts play {len(pieces)} pieces in all"
        )
    say(
        f"plan: {len(plan.plays)} plays and {total_frames} frames split into {len(ranges)} part(s), {balance}: "
        + ", ".join(f"frames {r.first_frame}-{r.last_frame} (pieces {r.first_play}-{r.last_play})" for r in ranges)
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
            f"part {rng.index}: frames {rng.first_frame}-{rng.last_frame} ({rng.frames} frames, "
            f"pieces {rng.first_play}-{rng.last_play}), {result.status} in {result.elapsed_seconds:.1f}s"
        )
    failed = [(rng, result) for rng, result in zip(ranges, results, strict=True) if result.status != "succeeded"]
    if failed:
        rng, result = failed[0]
        stage = stage_paths(project, paths, f"parts/{rng.index}")
        raise SpecError(
            stage.log_file,
            f"part {rng.index} (frames {rng.first_frame}-{rng.last_frame}, pieces {rng.first_play}-{rng.last_play}) "
            "failed:\n" + "\n".join(result.errors),
        )
    _check_parts_against_plan(pieces, results, ranges)

    # 3. The merge, into the job's own output directory.
    merge_paths = stage_paths(project, paths, "merge", output_dir=paths.output_dir)
    say("joining the segments, verifying the timing and sampling the checkpoints")
    merge_launched = launch_job(project, family, merge_job(job, plan, results, ranges, pieces), merge_paths, hashes)
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
    "MIN_PIECE_SECONDS",
    "JobCanceled",
    "boundaries_of",
    "estimated_weight",
    "measured_weights",
    "merge_job",
    "ordered_plays",
    "part_job",
    "plan_job",
    "plan_parts",
    "play_starts",
    "renumber_checkpoints",
    "resolve_workers",
    "run_parallel_video",
    "same_plays",
    "split_plan",
    "stage_paths",
    "window_boundaries",
]
