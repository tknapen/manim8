"""Milestone 4 acceptance: a 720p draft and a 1920x1080, 30 fps, 60 s final with sections, SRT and sampled frames."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scianim.server.app import create_app
from scianim_core import ArtifactManifest

pytestmark = pytest.mark.integration


def _manifest(project: Path, job_dir_text: str) -> ArtifactManifest:
    path = next(line for line in job_dir_text.splitlines() if line.strip().endswith("manifest.json"))
    return ArtifactManifest.model_validate_json(Path(path.strip()).read_text())


def test_draft_and_final_video_match_the_storyboard(workspace: Path, scianim) -> None:
    project = workspace / "families" / "computational_neuroscience" / "divisive_normalization"
    assert scianim("codegen", str(project)).returncode == 0

    draft = scianim("render", str(project), "--profile", "draft", "--sample", "mid_pool=10.5")
    assert draft.returncode == 0, draft.stdout + draft.stderr
    manifests = sorted((project / "renders" / "working").glob("*/manifest.json"))
    draft_manifest = ArtifactManifest.model_validate_json(manifests[-1].read_text())
    assert draft_manifest.job.operation == "render_video" and draft_manifest.result.status == "succeeded"
    [video] = draft_manifest.result.videos
    assert (video.width_px, video.height_px, video.fps) == (1280, 720, 30.0)
    assert video.frame_count == 540 and (project / video.path).stat().st_size > 10_000
    assert [s.name for s in draft_manifest.result.sections] == ["excitation", "normalization"]
    assert [s.metadata["frames"] for s in draft_manifest.result.sections] == [180, 360]
    index = json.loads((project / draft_manifest.job.output_dir / "sections" / "index.json").read_text())
    assert [entry["name"] for entry in index] == [s.name for s in draft_manifest.result.sections]
    assert draft_manifest.result.subtitles and (project / draft_manifest.result.subtitles).read_text().count("-->") == 2
    timing = draft_manifest.result.timing
    assert timing is not None and timing.within_tolerance and timing.actual_total_frames == 540
    samples = {c.snapshot_id: c for c in draft_manifest.result.checkpoints}
    assert set(samples) == {
        "excitation_visible",
        "pool_introduced",
        "pool_raised",
        "rebalanced",
        "mid_pool",
    }
    assert all(c.kind == "sampled_video_frame" and c.fidelity == "exact" for c in samples.values())
    assert samples["pool_introduced"].renderer_time_seconds == pytest.approx(8.0, abs=1 / 30)
    assert samples["mid_pool"].scene_id == "normalization"
    assert (project / samples["mid_pool"].png).exists()
    assert (project / draft_manifest.job.output_dir / "review_sheet.html").read_text().count("<video") == 1

    # The same request is a cache hit; a final render is a different job with the exact output dimensions.
    again = scianim("render", str(project), "--profile", "draft", "--sample", "mid_pool=10.5")
    assert again.returncode == 0 and "cache hit" in again.stdout
    final = scianim("render", str(project), "--profile", "final")
    assert final.returncode == 0, final.stdout + final.stderr
    final_manifest = ArtifactManifest.model_validate_json(
        sorted((project / "renders" / "working").glob("*/manifest.json"))[-1].read_text()
    )
    [movie] = final_manifest.result.videos
    assert (movie.width_px, movie.height_px, movie.fps, movie.frame_count) == (1920, 1080, 30.0, 540)
    assert movie.duration_seconds == pytest.approx(18.0)
    assert final_manifest.result.timing and final_manifest.result.timing.within_tolerance

    # The API lists both videos and serves the movie and the subtitles.
    client = TestClient(create_app(workspace))
    detail = client.get("/api/projects/divisive_normalization").json()
    assert detail["latest_video"]["working"] == final_manifest.job.job_id
    job = client.get(f"/api/projects/divisive_normalization/jobs/{final_manifest.job.job_id}").json()
    assert job["videos"][0]["frame_count"] == 540 and job["timing"]["within_tolerance"]
    assert client.get(job["videos"][0]["url"]).headers["content-type"] == "video/mp4"
    assert "-->" in client.get(job["subtitles_url"]).text
    # A time-stamped comment on the video binds to the scene at that moment.
    comment = client.post(
        "/api/projects/divisive_normalization/feedback",
        json={
            "revision_id": "working",
            "job_id": final_manifest.job.job_id,
            "kind": "general_comment",
            "text": "pause here",
            "time_seconds": 31.5,
            "scene_id": "equation",
        },
    )
    assert comment.status_code == 201, comment.text
    assert comment.json()["time_seconds"] == 31.5


def test_video_job_through_the_api_runner(workspace: Path, scianim) -> None:
    project = workspace / "families" / "computational_neuroscience" / "orientation_tuning"
    assert scianim("codegen", str(project)).returncode == 0
    client = TestClient(create_app(workspace))
    runner = client.app.state.runner
    rejected = client.post(
        "/api/projects/orientation_tuning/jobs", json={"operation": "render_video", "profile": "bogus"}
    )
    assert rejected.status_code == 422  # any of the four profiles is accepted for a video; an unknown one is not
    accepted = client.post(
        "/api/projects/orientation_tuning/jobs",
        json={"operation": "render_video", "profile": "draft", "samples": {"halfway": 12.0}},
    )
    assert accepted.status_code == 202, accepted.text
    final = runner.wait(accepted.json()["job_id"], timeout=900)
    assert final.status == "succeeded", final.error
    job = client.get(f"/api/projects/orientation_tuning/jobs/{final.job_id}").json()
    assert job["operation"] == "render_video" and job["videos"][0]["frame_count"] == 24 * 30
    assert {c["snapshot_id"] for c in job["checkpoints"]} >= {"circuit_shown", "model_complete", "halfway"}
    assert job["timing"]["within_tolerance"], job["timing"]["problems"]


def test_parallel_render_matches_the_serial_one(workspace: Path, scianim) -> None:
    """Two workers draw halves of the clip; the joined movie has the same frames as the one-process render."""
    project = workspace / "families" / "computational_neuroscience" / "orientation_tuning"
    assert scianim("codegen", str(project)).returncode == 0

    def latest() -> ArtifactManifest:
        return ArtifactManifest.model_validate_json(
            sorted((project / "renders" / "working").glob("*/manifest.json"))[-1].read_text()
        )

    serial = scianim("render", str(project), "--profile", "storyboard", "--no-cache")
    assert serial.returncode == 0, serial.stdout + serial.stderr
    one = latest()
    parallel = scianim("render", str(project), "--profile", "storyboard", "--no-cache", "--workers", "2")
    assert parallel.returncode == 0, parallel.stdout + parallel.stderr
    two = latest()
    assert two.job.job_id != one.job.job_id and two.job.workers == 2 and two.job.operation == "render_video"
    assert two.job.cache_key == one.job.cache_key and two.result.status == "succeeded"

    ranges = [(r.part.first_play, r.part.last_play) for r in two.result.parts]
    assert len(ranges) == 2 and ranges[0][0] == 0 and ranges[0][1] + 1 == ranges[1][0]
    assert ranges[1][1] == len(two.result.plays) - 1 and all(r.status == "succeeded" for r in two.result.parts)
    assert sum(p.frames for p in two.result.plays) == 720 and all(p.seconds >= 0 for p in two.result.plays)
    assert sum(p.seconds for p in two.result.plays) > 0  # the parts report how long each play took

    [movie_one], [movie_two] = one.result.videos, two.result.videos
    assert (
        (movie_two.frame_count, movie_two.width_px, movie_two.height_px, movie_two.fps)
        == (
            movie_one.frame_count,
            movie_one.width_px,
            movie_one.height_px,
            movie_one.fps,
        )
        == (720, 480, 270, 30.0)
    )
    assert [(s.name, s.metadata["frames"]) for s in two.result.sections] == [
        (s.name, s.metadata["frames"]) for s in one.result.sections
    ]
    assert two.result.timing is not None and two.result.timing.within_tolerance
    assert (
        two.result.subtitles
        and (project / two.result.subtitles).read_text()
        == (
            project / one.result.subtitles  # type: ignore[operator]
        ).read_text()
    )
    # Every sampled checkpoint frame is pixel-identical: the parts drew exactly what one process draws.
    assert {c.snapshot_id: c.sha256 for c in two.result.checkpoints} == {
        c.snapshot_id: c.sha256 for c in one.result.checkpoints
    }
    log = (project / ".scianim" / "jobs" / two.job.job_id / "worker.log").read_text()
    assert "balanced by the play times measured in" in log  # the serial render just before supplied them
    assert (project / ".scianim" / "jobs" / two.job.job_id / "parts" / "1" / "result.json").exists()
    # The cache does not care how many workers drew the movie.
    again = scianim("render", str(project), "--profile", "storyboard", "--workers", "3")
    assert again.returncode == 0 and "cache hit" in again.stdout
