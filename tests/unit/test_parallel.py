"""Parallel video renders without rendering: window planning, the split plan, the stage jobs, measured weights,
the checks on the parts, the API field."""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from scianim.codegen.generate import write_scene_module
from scianim.config.loader import SpecError
from scianim.planning.checks import validate_project
from scianim.project import Project
from scianim.render.jobs import build_video_job, sources_from_report
from scianim.render.parallel import (
    _check_parts_against_plan,
    _measured_plays,
    boundaries_of,
    estimated_weight,
    measured_weights,
    merge_job,
    part_job,
    plan_job,
    plan_parts,
    play_starts,
    renumber_checkpoints,
    resolve_workers,
    same_plays,
    split_plan,
    stage_paths,
    window_boundaries,
)
from scianim.server.app import create_app
from scianim_core import (
    ArtifactManifest,
    PartRange,
    PlayRecord,
    ReachedCheckpoint,
    RenderJob,
    SegmentRecord,
    WorkerResult,
)

FPS = 30


def _plays(
    frames: list[int],
    static: list[bool] | None = None,
    scene_id: str = "s",
    splittable: list[bool] | None = None,
) -> list[PlayRecord]:
    return [
        PlayRecord(
            index=i,
            scene_id=scene_id,
            start_seconds=sum(frames[:i]) / FPS,
            frames=f,
            static=bool(static[i]) if static else False,
            splittable=bool(splittable[i]) if splittable else True,
            source_index=i,
        )
        for i, f in enumerate(frames)
    ]


def _windows(parts: list[PartRange]) -> list[tuple[int, int]]:
    return [(p.first_frame, p.last_frame) for p in parts]


def _pieces(parts: list[PartRange]) -> list[tuple[int, int]]:
    return [(p.first_play, p.last_play) for p in parts]


def test_window_boundaries_cut_long_plays_at_even_cost() -> None:
    assert window_boundaries([], [], 3, min_piece_frames=15) == []
    one = _plays([300])
    assert window_boundaries(one, [300.0], 1, min_piece_frames=15) == []
    # One long play, uniform cost: the cuts are the quantile frames.
    assert window_boundaries(one, [300.0], 3, min_piece_frames=15) == [100, 200]
    assert window_boundaries(one, [300.0], 4, min_piece_frames=15) == [75, 150, 225]
    # Cost per frame is uniform within a play, so a heavy play draws the cuts into itself.
    plays = _plays([60, 90, 60])
    assert window_boundaries(plays, [60.0, 900.0, 60.0], 2, min_piece_frames=15) == [105]  # the heavy play's middle
    # The cut must leave half a second on either side: within the margin of an edge it goes to the edge or to
    # the half-second mark, whichever is nearer.
    assert window_boundaries(plays, [60.0, 900.0, 60.0], 3, min_piece_frames=15) == [
        88,
        122,
    ]  # 28 and 62 frames in, well clear of the edges
    assert window_boundaries(plays, [60.0, 900.0, 60.0], 5, min_piece_frames=15) == [
        75,
        95,
        115,
        135,
    ]  # ideal 74 and 136
    assert window_boundaries(plays, [60.0, 90.0, 60.0], 3, min_piece_frames=15) == [75, 135]  # ideal 70 and 142
    assert window_boundaries(_plays([30, 300]), [30.0, 3000.0], 2, min_piece_frames=15) == [178]
    # Nearer the edge than the margin mark: the edge.
    assert window_boundaries(_plays([60, 90, 60]), [600.0, 900.0, 60.0], 2, min_piece_frames=40) == [60]  # ideal 78
    # Never at the very start or end of the movie, and never two at the same frame.
    assert window_boundaries(_plays([10, 10]), [1.0, 1.0], 5, min_piece_frames=15) == [10]
    assert window_boundaries(_plays([10, 10, 10]), [1.0, 1.0, 1.0], 6, min_piece_frames=15) == [10, 20]


def test_window_boundaries_stay_out_of_plays_that_cannot_be_split() -> None:
    plays = _plays([60, 90, 60], splittable=[True, False, True])
    # The heavy play is drawn whole: the cut goes to whichever of its edges is nearer the ideal frame.
    assert window_boundaries(plays, [60.0, 900.0, 60.0], 2, min_piece_frames=15) == [60]
    assert window_boundaries(plays, [60.0, 900.0, 60.0], 3, min_piece_frames=15) == [60, 150]
    # A static wait can be cut (two waits), an animated play of tracks too; a play with a zero weight is skipped.
    waits = _plays([60, 60], static=[True, True])
    assert window_boundaries(waits, [7.0, 7.0], 2, min_piece_frames=15) == [60]
    assert window_boundaries(waits, [7.0, 7.0], 4, min_piece_frames=15) == [30, 60, 90]
    assert window_boundaries(_plays([60, 60]), [0.0, 0.0], 2, min_piece_frames=15) == []
    with pytest.raises(ValueError, match="one weight per play"):
        window_boundaries(plays, [1.0], 2, min_piece_frames=15)


def test_window_boundaries_rebalance_after_a_cut_has_moved() -> None:
    # The light prefix weighs 357 and the two sweeps 1350 and 1215; a cut forced to the half-second mark of the
    # first sweep leaves the later windows to share the rest evenly rather than each missing its quantile.
    frames = [26, 20, 25, 50, 40, 15, 4, 26, 4, 26, 20, 15, 25, 20, 26, 15, 90, 81, 15, 3, 45, 45, 2, 19]
    plays = _plays(frames)
    weights = [f * (15.0 if f in (90, 81) else 1.0) for f in frames]
    starts = play_starts(plays)
    parts = plan_parts(plays, weights, 6, frame_rate=FPS)
    pieces = split_plan(plays, boundaries_of(parts), FPS)
    shares = [
        sum(weights[q.source_index] * q.frames / frames[q.source_index] for q in pieces[p.first_play : p.last_play + 1])  # type: ignore[index]
        for p in parts
    ]
    mean = sum(weights) / len(parts)
    assert len(parts) == 6 and all(abs(share - mean) / mean < 0.25 for share in shares), shares
    cuts = boundaries_of(parts)
    assert any(starts[16] < cut < starts[17] for cut in cuts) and any(starts[17] < cut < starts[18] for cut in cuts)


def test_split_plan_numbers_the_pieces_as_every_worker_will() -> None:
    plays = _plays([60, 90, 60])
    assert split_plan(plays, [], FPS) == plays
    pieces = split_plan(plays, [92, 118], FPS)
    assert [(p.index, p.source_index, p.piece, p.frames) for p in pieces] == [
        (0, 0, 0, 60),
        (1, 1, 0, 32),
        (2, 1, 1, 26),
        (3, 1, 2, 32),
        (4, 2, 0, 60),
    ]
    assert [p.start_seconds for p in pieces] == pytest.approx([0, 2, 92 / 30, 118 / 30, 5])
    assert play_starts(pieces) == [0, 60, 92, 118, 150, 210]  # every frame exactly once
    assert all(p.scene_id == "s" and p.static is False for p in pieces)
    # A boundary on a play's edge cuts nothing; one inside an unsplittable play is a planning error.
    assert split_plan(plays, [60, 150], FPS) == plays
    with pytest.raises(SpecError, match="cannot be split"):
        split_plan(_plays([60, 90, 60], splittable=[True, False, True]), [100], FPS)
    # Checkpoints sit between plays; their animation numbers follow the first piece of the play after them.
    reached = [
        ReachedCheckpoint(snapshot_id="a", animation_index=1, time_seconds=2.0),
        ReachedCheckpoint(snapshot_id="b", animation_index=2, time_seconds=5.0),
        ReachedCheckpoint(snapshot_id="end", animation_index=3, time_seconds=7.0),
    ]
    assert [c.animation_index for c in renumber_checkpoints(reached, plays, pieces)] == [1, 4, 5]
    assert [c.animation_index for c in renumber_checkpoints(reached, plays, plays)] == [1, 2, 3]


def test_plan_parts_expresses_windows_in_the_split_numbering() -> None:
    plays = _plays([60, 90, 60])
    parts = plan_parts(plays, [60.0, 900.0, 60.0], 3, frame_rate=FPS)
    assert _windows(parts) == [(0, 87), (88, 121), (122, 209)]
    assert _pieces(parts) == [(0, 1), (2, 2), (3, 4)]
    assert [p.frames for p in parts] == [88, 34, 88]
    assert all(p.split_frames == [88, 122] and p.count == 3 for p in parts)
    assert [p.index for p in parts] == [0, 1, 2]
    # One worker, or no boundary that can be placed: one part over everything, in the plan's own numbering.
    [whole] = plan_parts(plays, None, 1, frame_rate=FPS)
    assert whole == PartRange(
        index=0, count=1, first_play=0, last_play=2, frames=210, first_frame=0, last_frame=209, split_frames=[]
    )
    assert plan_parts([], None, 4) == []
    assert len(plan_parts(_plays([10]), None, 4, frame_rate=FPS)) == 1
    # Estimated weights before anything is measured: a static wait counts one frame and a tenth of its repeats.
    estimated = _plays([30, 30, 30, 30], static=[False, True, True, False])
    assert estimated_weight(estimated[0]) == 30 and estimated_weight(estimated[1]) == 4
    assert _windows(plan_parts(estimated, None, 2, frame_rate=FPS)) == [(0, 59), (60, 119)]
    # Half the cost sits 13.5 frames into the heavy last play: the cut moves to its half-second mark.
    assert _windows(plan_parts(estimated, [1.0, 1.0, 1.0, 30.0], 2, frame_rate=FPS)) == [(0, 104), (105, 119)]
    with pytest.raises(ValueError, match="one weight per play"):
        plan_parts(estimated, [1.0], 2)
    with pytest.raises(NotImplementedError, match="ADR-033"):
        plan_parts(plays, None, 2, reusable=frozenset({0}))
    assert same_plays(estimated, _plays([30, 30, 30, 30], static=[False, True, True, False]))
    assert not same_plays(estimated, _plays([30, 30, 30, 30]))  # a wait became a play: not the same scene
    assert not same_plays(estimated, _plays([30, 30, 30]))
    assert resolve_workers(0) >= 1 and resolve_workers(-2) >= 1 and resolve_workers(3) == 3


def _part_result(pieces: list[PlayRecord], rng: PartRange, *, drawn_seconds: float = 1.0) -> WorkerResult:
    """What a part reports: every piece up to the end of its range, segments for the ones in the range."""
    plays = [
        p.model_copy(
            update={"drawn": rng.first_play <= p.index, "seconds": drawn_seconds if rng.first_play <= p.index else 0.01}
        )
        for p in pieces
        if p.index <= rng.last_play
    ]
    segments = [
        SegmentRecord(play_index=p.index, scene_id=p.scene_id, path=f"m/{p.index}.mp4", frames=p.frames)
        for p in pieces
        if rng.first_play <= p.index <= rng.last_play
    ]
    return WorkerResult(job_id="j", status="succeeded", plays=plays, segments=segments, elapsed_seconds=1)


def test_parts_are_checked_against_the_split_plan_and_measured_per_source_play() -> None:
    plays = _plays([60, 90, 60])
    parts = plan_parts(plays, [60.0, 900.0, 60.0], 3, frame_rate=FPS)
    pieces = split_plan(plays, boundaries_of(parts), FPS)
    results = [_part_result(pieces, rng, drawn_seconds=float(k + 1)) for k, rng in enumerate(parts)]
    _check_parts_against_plan(pieces, results, parts)
    measured = _measured_plays(plays, results)
    assert [p.index for p in measured] == [0, 1, 2] and all(p.drawn for p in measured)
    assert [p.seconds for p in measured] == pytest.approx([1.0, 1.0 + 2.0 + 3.0, 3.0])  # the cut play sums its pieces
    assert same_plays(measured, plays)  # the manifest keeps the planning pass's numbering
    # A piece served from Manim's cache leaves its source play unmeasured.
    cached = results[1].model_copy(
        update={"plays": [p.model_copy(update={"drawn": False}) if p.index == 2 else p for p in results[1].plays]}
    )
    assert [p.drawn for p in _measured_plays(plays, [results[0], cached, results[2]])] == [True, False, True]
    # A part whose scene cut a play differently from the plan is refused.
    wrong = results[1].model_copy(
        update={"plays": [p.model_copy(update={"frames": 27}) if p.index == 2 else p for p in results[1].plays]}
    )
    with pytest.raises(SpecError, match="piece 1 of play 1"):
        _check_parts_against_plan(pieces, [results[0], wrong, results[2]], parts)
    other = results[1].model_copy(
        update={"plays": [p.model_copy(update={"piece": 0}) if p.index == 2 else p for p in results[1].plays]}
    )
    with pytest.raises(SpecError, match="does not play the same way twice"):
        _check_parts_against_plan(pieces, [results[0], other, results[2]], parts)
    with pytest.raises(SpecError, match="no part drew"):
        _check_parts_against_plan(
            pieces, [results[0], results[1].model_copy(update={"segments": []}), results[2]], parts
        )
    with pytest.raises(SpecError, match="drawn by two parts"):
        _check_parts_against_plan(pieces, [results[0], results[0], results[2]], parts)


def _prepared(project: Project):
    report = validate_project(project, require_family=True)
    assert report.animation and report.storyboard and report.style and report.family
    write_scene_module(report.animation, report.storyboard, report.style, project.scene_module_path(report.animation))
    return validate_project(project, require_family=True)


def test_stage_jobs_derive_from_the_video_job(project_copy: Project) -> None:
    report = _prepared(project_copy)
    sources = sources_from_report(project_copy, report)
    assert report.family
    job, paths, _ = build_video_job(project_copy, sources, report.family, "storyboard", workers=3)
    serial, _, _ = build_video_job(project_copy, sources, report.family, "storyboard")
    assert job.workers == 3 and serial.workers == 1 and job.operation == "render_video"
    assert job.cache_key == serial.cache_key  # the same movie, so the same cache entry

    plan_paths = stage_paths(project_copy, paths, "plan")
    plan = plan_job(project_copy, job, plan_paths)
    assert plan.operation == "plan_video" and plan.part is None and plan.merge is None
    assert plan.output_dir == f".scianim/jobs/{job.job_id}/plan" and not plan.manim.save_sections
    assert plan.cache_key == job.cache_key and plan.manim.media_dir == job.manim.media_dir

    rng = PartRange(
        index=1,
        count=3,
        first_play=4,
        last_play=7,
        frames=120,
        first_frame=100,
        last_frame=219,
        split_frames=[100, 220],
    )
    part = part_job(project_copy, job, stage_paths(project_copy, paths, "parts/1"), rng)
    assert part.operation == "render_video_part" and part.part == rng
    assert part.manim.media_dir == ".scianim/media/working/parts/1" and not part.manim.save_sections
    assert part.output_dir == f".scianim/jobs/{job.job_id}/parts/1"

    plays = _plays([30, 90, 30])
    plan_result = WorkerResult(
        job_id=job.job_id,
        status="succeeded",
        plays=plays,
        reached=[ReachedCheckpoint(snapshot_id="excitation_visible", animation_index=2, time_seconds=4.0)],
        subtitles=f"{plan.output_dir}/{job.job_id}.srt",
        elapsed_seconds=1,
    )
    ranges = plan_parts(plan_result.plays, None, 3, frame_rate=FPS)
    assert _windows(ranges) == [(0, 49), (50, 99), (100, 149)]  # the long play is shared by all three
    pieces = split_plan(plays, boundaries_of(ranges), FPS)
    assert [(p.source_index, p.piece, p.frames) for p in pieces] == [
        (0, 0, 30),
        (1, 0, 20),
        (1, 1, 50),
        (1, 2, 20),
        (2, 0, 30),
    ]
    parts = [_part_result(pieces, ranges[k]) for k in (1, 0, 2)]  # the parts finish in any order
    merged = merge_job(job, plan_result, parts, ranges, pieces)
    assert merged.operation == "merge_video" and merged.merge is not None and merged.part is None
    assert [s.play_index for s in merged.merge.segments] == [0, 1, 2, 3, 4]
    assert merged.merge.plays == pieces and merged.merge.checkpoints[0].animation_index == 4
    assert merged.merge.subtitles == plan_result.subtitles
    assert (
        merged.merge.parts == ranges and merged.output_dir == job.output_dir
    )  # the movie lands where a serial one does
    assert merge_job(job, plan_result, parts, ranges).merge.plays == plays  # type: ignore[union-attr]

    # The contract ties the stage fields to their operations.
    with pytest.raises(ValidationError, match="render_video_part"):
        RenderJob.model_validate({**job.model_dump(mode="json"), "part": rng.model_dump(mode="json")})
    with pytest.raises(ValidationError, match="merge_video"):
        RenderJob.model_validate({**merged.model_dump(mode="json"), "operation": "render_video"})


def test_measured_weights_come_from_the_latest_matching_render(project_copy: Project) -> None:
    report = _prepared(project_copy)
    sources = sources_from_report(project_copy, report)
    assert report.family
    job, paths, hashes = build_video_job(project_copy, sources, report.family, "storyboard")
    plays = _plays([30, 60, 30], static=[False, False, True])
    assert measured_weights(project_copy, plays) is None  # nothing rendered yet
    recorded = [p.model_copy(update={"seconds": s, "drawn": True}) for p, s in zip(plays, [0.5, 4.0, 0.1], strict=True)]
    manifest = ArtifactManifest(
        created_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        job=job,
        result=WorkerResult(job_id=job.job_id, status="succeeded", plays=recorded, elapsed_seconds=5),
        inputs=hashes,
    )
    paths.manifest_file.parent.mkdir(parents=True, exist_ok=True)
    paths.manifest_file.write_text(manifest.model_dump_json(indent=2))
    found = measured_weights(project_copy, plays)
    assert found is not None and found[1] == job.job_id and found[0] == [0.5, 4.0, 0.1]
    assert _windows(plan_parts(plays, found[0], 2, frame_rate=FPS)) == [
        (0, 56),
        (57, 119),
    ]  # half the cost sits at 56.5
    assert measured_weights(project_copy, _plays([30, 60, 30])) is None  # a different scene structure
    # A play Manim served from its cache measured as nearly free; it gets the estimate at the measured scale.
    cached = [recorded[0], recorded[1].model_copy(update={"seconds": 0.02, "drawn": False}), recorded[2]]
    manifest.result.plays = cached
    paths.manifest_file.write_text(manifest.model_dump_json(indent=2))
    weights, _ = measured_weights(project_copy, plays)  # type: ignore[misc]
    rate = sorted([0.5 / 30, 0.1 / 4.0])[1]  # median seconds per estimated frame of the drawn plays
    assert weights == pytest.approx([0.5, rate * 60, 0.1])
    manifest.result.plays = [p.model_copy(update={"drawn": False}) for p in recorded]
    paths.manifest_file.write_text(manifest.model_dump_json(indent=2))
    assert measured_weights(project_copy, plays) is None  # nothing was drawn: nothing was measured


def test_api_accepts_a_worker_count_for_videos(workspace) -> None:
    client = TestClient(create_app(workspace))
    refused = client.post(
        "/api/projects/divisive_normalization/jobs", json={"operation": "render_video", "workers": -1}
    )
    assert refused.status_code == 422
    accepted = client.post(
        "/api/projects/divisive_normalization/jobs",
        json={"operation": "render_video", "profile": "storyboard", "workers": 2},
    )
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["workers"] == 2
    all_cores = client.post(
        "/api/projects/divisive_normalization/jobs",
        json={"operation": "render_video", "profile": "storyboard", "workers": 0},
    )
    assert all_cores.status_code == 202 and all_cores.json()["workers"] >= 1
    stills = client.post("/api/projects/divisive_normalization/jobs", json={"workers": 4})
    assert stills.status_code == 202 and stills.json()["workers"] == 1  # stills render in one pass
