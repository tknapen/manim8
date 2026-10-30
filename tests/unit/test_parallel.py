"""Parallel video renders without rendering: splitting plays, the stage jobs, measured weights, the API field."""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from scianim.codegen.generate import write_scene_module
from scianim.planning.checks import validate_project
from scianim.project import Project
from scianim.render.jobs import build_video_job, sources_from_report
from scianim.render.parallel import (
    estimated_weight,
    measured_weights,
    merge_job,
    part_job,
    part_ranges,
    plan_job,
    resolve_workers,
    same_plays,
    split_plays,
    stage_paths,
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


def _plays(frames: list[int], static: list[bool] | None = None, scene_id: str = "s") -> list[PlayRecord]:
    return [
        PlayRecord(
            index=i,
            scene_id=scene_id,
            start_seconds=sum(frames[:i]) / 30,
            frames=f,
            static=bool(static[i]) if static else False,
        )
        for i, f in enumerate(frames)
    ]


def test_split_plays_gives_contiguous_ranges_of_even_weight() -> None:
    assert split_plays([], 3) == []
    assert split_plays([10], 4) == [(0, 0)]
    assert split_plays([1, 1, 1, 1], 2) == [(0, 1), (2, 3)]
    assert split_plays([1, 1, 1, 1], 4) == [(0, 0), (1, 1), (2, 2), (3, 3)]
    assert split_plays([1, 1, 1], 5) == [(0, 0), (1, 1), (2, 2)]  # never more ranges than plays
    assert split_plays([1, 1, 50, 1, 1], 3) == [(0, 1), (2, 2), (3, 4)]  # a heavy play gets a range of its own
    weights = [5, 3, 8, 1, 1, 1, 9, 2, 4, 6, 7, 1]
    assert split_plays(weights, 3) == [(0, 2), (3, 8), (9, 11)]  # sums 16, 18, 14 of 48
    for count in range(1, 15):
        ranges = split_plays(weights, count)
        assert len(ranges) == min(count, len(weights))
        assert ranges[0][0] == 0 and ranges[-1][1] == len(weights) - 1
        assert all(first <= last for first, last in ranges)
        assert all(ranges[i][1] + 1 == ranges[i + 1][0] for i in range(len(ranges) - 1))


def test_part_ranges_weigh_static_waits_lightly_and_follow_measurements() -> None:
    plays = _plays([30, 30, 30, 30], static=[False, True, True, False])
    assert estimated_weight(plays[0]) == 30 and estimated_weight(plays[1]) == 4
    estimated = part_ranges(plays, 2)
    assert [(r.first_play, r.last_play) for r in estimated] == [(0, 1), (2, 3)]
    assert [r.frames for r in estimated] == [60, 60] and all(r.count == 2 for r in estimated)
    measured = part_ranges(plays, 2, [1.0, 1.0, 1.0, 30.0])
    assert [(r.first_play, r.last_play) for r in measured] == [(0, 2), (3, 3)]
    assert len(part_ranges(plays, 9)) == 4  # one play per part at most
    with pytest.raises(ValueError, match="one weight per play"):
        part_ranges(plays, 2, [1.0])
    assert same_plays(plays, _plays([30, 30, 30, 30], static=[False, True, True, False]))
    assert not same_plays(plays, _plays([30, 30, 30, 30]))  # a wait became a play: not the same scene
    assert not same_plays(plays, _plays([30, 30, 30]))
    assert resolve_workers(0) >= 1 and resolve_workers(-2) >= 1 and resolve_workers(3) == 3


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

    rng = PartRange(index=1, count=3, first_play=4, last_play=7, frames=120)
    part = part_job(project_copy, job, stage_paths(project_copy, paths, "parts/1"), rng)
    assert part.operation == "render_video_part" and part.part == rng
    assert part.manim.media_dir == ".scianim/media/working/parts/1" and not part.manim.save_sections
    assert part.output_dir == f".scianim/jobs/{job.job_id}/parts/1"

    plan_result = WorkerResult(
        job_id=job.job_id,
        status="succeeded",
        plays=_plays([30, 30, 30]),
        reached=[ReachedCheckpoint(snapshot_id="excitation_visible", animation_index=1, time_seconds=1.0)],
        subtitles=f"{plan.output_dir}/{job.job_id}.srt",
        elapsed_seconds=1,
    )
    parts = [
        WorkerResult(
            job_id=job.job_id,
            status="succeeded",
            segments=[SegmentRecord(play_index=i, scene_id="s", path=f"{part.manim.media_dir}/seg{i}.mp4", frames=30)],
            elapsed_seconds=1,
        )
        for i in (1, 0, 2)  # the parts finish in any order
    ]
    ranges = part_ranges(plan_result.plays, 3)
    merged = merge_job(job, plan_result, parts, ranges)
    assert merged.operation == "merge_video" and merged.merge is not None and merged.part is None
    assert [s.play_index for s in merged.merge.segments] == [0, 1, 2]
    assert merged.merge.subtitles == plan_result.subtitles and merged.merge.checkpoints == plan_result.reached
    assert (
        merged.merge.parts == ranges and merged.output_dir == job.output_dir
    )  # the movie lands where a serial one does

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
    assert [(r.first_play, r.last_play) for r in part_ranges(plays, 2, found[0])] == [(0, 0), (1, 2)]
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
