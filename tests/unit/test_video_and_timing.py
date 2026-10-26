"""Milestone 4 without rendering: frame accounting, timing proposals, video job building, stale scenes, the sheet."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from scianim.codegen.generate import write_scene_module
from scianim.config.loader import SpecError, load_storyboard
from scianim.planning.checks import validate_project
from scianim.planning.dependencies import changed_scenes, compare_with_revision
from scianim.planning.timing import propose_timing, write_proposed_storyboard
from scianim.project import Project
from scianim.render.jobs import build_snapshot_job, build_video_job, sources_from_report
from scianim.review.sheet import render_sheet
from scianim.revisions.store import create_revision, load_revision
from scianim_core import ArtifactManifest, SectionRecord, VideoRecord, WorkerResult, frames_for, verify_timing
from scianim_core.jobs import InputHashes


def test_frames_for_rounds_to_the_nearest_frame() -> None:
    assert frames_for(0.85, 30) == 26 and frames_for(0.65, 30) == 20 and frames_for(60, 30) == 1800
    assert frames_for(0.0166, 30) == 0 and frames_for(-1, 30) == 0
    assert frames_for(1 / 3, 24) == 8


def test_verify_timing_flags_scene_and_total_deviations() -> None:
    scenes = [("a", 0.0, 15.0), ("b", 15.0, 30.0)]
    good = verify_timing(scenes, [("a", 450), ("b", 450)], 900, 30, 30)
    assert good.within_tolerance and good.problems() == [] and good.actual_duration_seconds == 30
    off_by_one = verify_timing(scenes, [("a", 451), ("b", 450)], 901, 30, 30)
    assert off_by_one.within_tolerance  # one frame is the documented tolerance
    bad = verify_timing(scenes, [("a", 440), ("b", 450)], 890, 30, 30)
    assert not bad.within_tolerance
    assert any("scene 'a' lasts 440" in p for p in bad.problems()) and any("890 frames" in p for p in bad.problems())
    unprobed = verify_timing(scenes, [], None, 30, 30)
    assert not unprobed.within_tolerance and "could not be probed" in unprobed.problems()[0]
    extra = verify_timing(scenes, [("a", 450), ("b", 450), ("intro", 3)], 903, 30, 30)
    assert extra.notes == ["sections without a storyboard scene: ['intro']"]


def test_timing_proposal_from_narration_reports_conflicts(project_copy: Project, tmp_path: Path) -> None:
    report = validate_project(project_copy)
    assert report.animation and report.storyboard and report.style
    proposal = propose_timing(report.animation, report.storyboard, 150.0)
    assert [s.scene_id for s in proposal.scenes] == [s.id for s in report.storyboard.scenes]
    first = proposal.scenes[0]
    assert first.proposed_start == 0 and first.narration_seconds is not None
    assert first.proposed_duration == pytest.approx(
        max(3.0, frames_for(first.narration_seconds * 1.25, 30) / 30), abs=1 / 30
    )
    # The example's narration is shorter than its scenes, so snapshots placed late in each scene conflict.
    assert not proposal.ok
    assert any("snapshot" in c for s in proposal.scenes for c in s.conflicts)
    # A slow narrator makes every scene longer than the output allows.
    slow = propose_timing(report.animation, report.storyboard, 20.0)
    assert any("output lasts" in c for c in slow.conflicts)
    with pytest.raises(SpecError, match="conflicts"):
        write_proposed_storyboard(project_copy.storyboard_path, proposal, tmp_path / "refused.yaml")
    # A conflict-free proposal (here: keep every boundary) is written next to the original, never in place.
    for scene in proposal.scenes:
        scene.proposed_start, scene.proposed_end, scene.conflicts = scene.current_start, scene.current_end, []
    proposal.conflicts = []
    assert proposal.ok
    before = project_copy.storyboard_path.read_text()
    target = write_proposed_storyboard(project_copy.storyboard_path, proposal, tmp_path / "proposed.yaml")
    proposed = load_storyboard(target)
    assert [(s.start_seconds, s.end_seconds) for s in proposed.scenes] == [
        (s.proposed_start, s.proposed_end) for s in proposal.scenes
    ]
    assert project_copy.storyboard_path.read_text() == before


def _prepared(project: Project):
    report = validate_project(project, require_family=True)
    assert report.animation and report.storyboard and report.style and report.family
    write_scene_module(report.animation, report.storyboard, report.style, project.scene_module_path(report.animation))
    return validate_project(project, require_family=True)


def test_build_video_job_profiles_sections_and_samples(project_copy: Project) -> None:
    report = _prepared(project_copy)
    sources = sources_from_report(project_copy, report)
    assert report.family
    draft, paths, _ = build_video_job(project_copy, sources, report.family, "draft", {"mid": 22.5})
    assert draft.operation == "render_video" and draft.quality_profile == "draft"
    assert (draft.manim.pixel_width, draft.manim.pixel_height) == (1280, 720)
    assert draft.manim.frame_rate == 30 and draft.manim.save_sections and draft.manim.video_codec == "libx264"
    assert [s.scene_id for s in draft.scenes] == ["excitation", "normalization_pool", "equation", "pool_comparison"]
    assert draft.samples == {"mid": 22.5} and set(draft.snapshots) == set(report.storyboard.snapshot_ids())
    assert draft.manim.media_dir == ".scianim/media/working" and paths.output_dir.name == draft.job_id
    final, _, _ = build_video_job(project_copy, sources, report.family, "final")
    assert (final.manim.pixel_width, final.manim.pixel_height) == (1920, 1080)
    assert final.cache_key != draft.cache_key
    snapshots, _, _ = build_snapshot_job(project_copy, sources, report.family, [])
    assert snapshots.cache_key != draft.cache_key
    with pytest.raises(SpecError, match="draft or final"):
        build_video_job(project_copy, sources, report.family, "snapshot")  # type: ignore[arg-type]
    with pytest.raises(SpecError, match="collides"):
        build_video_job(project_copy, sources, report.family, "draft", {"excitation_visible": 1.0})
    with pytest.raises(SpecError, match="beyond"):
        build_video_job(project_copy, sources, report.family, "draft", {"late": 61.0})


def test_stale_scenes_against_a_revision(project_copy: Project) -> None:
    report = _prepared(project_copy)
    revision = create_revision(project_copy, report, "baseline")
    unchanged = compare_with_revision(project_copy, report, load_revision(project_copy, revision.id))
    assert unchanged.stale_scene_ids == [] and unchanged.removed_scenes == []
    storyboard = project_copy.storyboard_path
    storyboard.write_text(storyboard.read_text().replace("at_seconds: 24\n", "at_seconds: 25\n"))
    csv = project_copy.data_dir / "synthetic_responses.csv"
    csv.write_text(csv.read_text() + "11.0,1.0,1.0,5.5,low_pool,synthetic\n")
    report = _prepared(project_copy)
    changed = compare_with_revision(project_copy, report, load_revision(project_copy, revision.id))
    by_id = {s.scene_id: s.reasons for s in changed.scenes}
    assert by_id["normalization_pool"] == ["snapshots changed"]
    assert "data source 'responses' changed" in by_id["excitation"]
    assert "data source 'responses' changed" in by_id["pool_comparison"]
    assert by_id["equation"] == []
    none = compare_with_revision(project_copy, report, None)
    assert none.stale_scene_ids == [s.id for s in report.storyboard.scenes]
    # Style and custom code changes are reported through the generic path.
    assert report.storyboard and report.animation
    styled = changed_scenes(
        report.storyboard,
        report.storyboard,
        before_spec=report.animation,
        after_spec=report.animation,
        data_changed=set(),
        style_changed=True,
        custom_code_changed=False,
    )
    assert all(s.reasons == ["style tokens changed"] for s in styled.scenes)


def test_review_sheet_shows_video_sections_and_timing(project_copy: Project) -> None:
    report = _prepared(project_copy)
    sources = sources_from_report(project_copy, report)
    assert report.family and report.storyboard
    job, _, _ = build_video_job(project_copy, sources, report.family, "draft")
    video = VideoRecord(
        path=f"{job.output_dir}/{job.job_id}.mp4",
        width_px=1280,
        height_px=720,
        fps=30,
        duration_seconds=60,
        frame_count=1800,
        codec="h264",
        sha256="a" * 64,
    )
    sections = [
        SectionRecord(
            name=s.scene_id,
            type="default.normal",
            video=f"{job.output_dir}/sections/{s.scene_id}.mp4",
            metadata={"frames": 450, "duration_seconds": 15.0},
        )
        for s in job.scenes
    ]
    timing = verify_timing(
        [(s.scene_id, s.start_seconds, s.end_seconds) for s in job.scenes],
        [(s.name, 450) for s in sections],
        1800,
        30,
        60,
    )
    manifest = ArtifactManifest(
        created_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        job=job,
        result=WorkerResult(
            job_id=job.job_id,
            status="succeeded",
            videos=[video],
            sections=sections,
            subtitles=f"{job.output_dir}/{job.job_id}.srt",
            timing=timing,
            elapsed_seconds=1,
        ),
        inputs=InputHashes(
            animation_spec="a" * 64, storyboard="b" * 64, scene_code="c" * 64, resolved_style="sha256:" + "d" * 64
        ),
    )
    html = render_sheet(manifest, report.storyboard, Path("."))
    assert "<video" in html and f"{job.job_id}.mp4" in html and "subtitles (SRT)" in html
    assert "matches the storyboard" in html and "pool_comparison" in html
