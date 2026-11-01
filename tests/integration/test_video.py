"""Milestone 4 acceptance: a 720p draft and a 1920x1080, 30 fps, 60 s final with sections, SRT and sampled frames."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scianim.server.app import create_app
from scianim_core import ArtifactManifest

pytestmark = [pytest.mark.integration, pytest.mark.video]


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
    # The parallel renders below must draw, not take the serial render's plays from the segment store (ADR-033).
    shutil.rmtree(project / ".scianim" / "segments", ignore_errors=True)
    parallel = scianim("render", str(project), "--profile", "storyboard", "--no-cache", "--workers", "2")
    assert parallel.returncode == 0, parallel.stdout + parallel.stderr
    two = latest()
    assert two.job.job_id != one.job.job_id and two.job.workers == 2 and two.job.operation == "render_video"
    assert two.job.cache_key == one.job.cache_key and two.result.status == "succeeded"
    # A serial render reports its segments too, one per play, so a later render can splice them.
    assert [s.play_index for s in one.result.segments] == [p.index for p in one.result.plays]
    assert all((project / s.path).exists() for s in one.result.segments)

    # Part ranges count the pieces of cut plays (ADR-031); the windows cover the movie's frames once, in order.
    ranges = [(r.part.first_play, r.part.last_play) for r in two.result.parts]
    assert len(ranges) == 2 and ranges[0][0] == 0 and ranges[0][1] + 1 == ranges[1][0]
    windows = [(r.part.first_frame, r.part.last_frame) for r in two.result.parts]
    assert windows[0][0] == 0 and windows[0][1] + 1 == windows[1][0] and windows[1][1] == 719
    assert all(r.status == "succeeded" for r in two.result.parts)
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

    # Six workers on a clip whose measured cost sits in two sweeps of 90 and 81 frames: the windows cut those
    # plays, every part cuts them at the same frames, and the pieces render the frames of the serial render
    # (ADR-031). The boundaries are predicted here from the same measurements the planner will read.
    from scianim.project import Project
    from scianim.render.parallel import boundaries_of, measured_weights, plan_parts, play_starts, split_plan

    plays = sorted(two.result.plays, key=lambda p: p.index)  # the manifest keeps the planning pass's numbering
    weights = measured_weights(Project(project), plays)
    assert weights is not None and weights[1] == two.job.job_id
    expected = plan_parts(plays, weights[0], 6, frame_rate=30.0)
    cuts = boundaries_of(expected)
    starts = play_starts(plays)
    sweeps = [p for p in plays if p.frames in (90, 81)]
    inside = {p.index: [c for c in cuts if starts[p.index] < c < starts[p.index + 1]] for p in sweeps}
    assert len(sweeps) == 2 and all(inside.values()), (cuts, inside)
    cut_plays = sorted({p.source_index for p in split_plan(plays, cuts, 30.0) if p.piece})
    after_boundary = (inside[sweeps[0].index][0] + 1) / 30
    shutil.rmtree(project / ".scianim" / "segments", ignore_errors=True)  # windows are the subject here
    six = scianim(
        "render",
        str(project),
        "--profile",
        "storyboard",
        "--no-cache",
        "--workers",
        "6",
        "--sample",
        f"after_boundary={after_boundary!r}",
    )
    assert six.returncode == 0, six.stdout + six.stderr
    many = latest()
    assert many.job.workers == 6 and many.result.status == "succeeded" and len(many.result.parts) == 6
    assert [r.part for r in many.result.parts] == expected
    assert all(r.part.split_frames == cuts for r in many.result.parts)
    assert all(r.status == "succeeded" for r in many.result.parts)
    assert [(p.index, p.frames) for p in many.result.plays] == [(p.index, p.frames) for p in one.result.plays]
    # The cut plays are new pieces and were drawn; a whole play may come from Manim's per-play cache, filled by
    # the renders above, and is then honestly recorded as not drawn.
    assert all(p.drawn and p.seconds > 0 for p in many.result.plays if p.index in cut_plays)
    assert all(p.seconds >= 0 for p in many.result.plays)
    [movie_six] = many.result.videos
    assert (movie_six.frame_count, movie_six.width_px, movie_six.height_px) == (720, 480, 270)
    assert many.result.timing is not None and many.result.timing.within_tolerance
    assert [(s.name, s.metadata["frames"]) for s in many.result.sections] == [
        (s.name, s.metadata["frames"]) for s in one.result.sections
    ]
    six_log = (project / ".scianim" / "jobs" / many.job.job_id / "worker.log").read_text()
    assert f"cut play(s) {cut_plays}" in six_log
    # The pieces render the frames of the serial render, but a cut play is encoded as several x264 streams, so
    # inside it the lossy movie carries codec noise against the serial one (ADR-031: a few dozen levels at the
    # edges of glyphs and curves, mean well under one level). A checkpoint that opens an uncut play, and any
    # checkpoint that does not open a cut play's short first piece, is byte-identical; a checkpoint opening a
    # cut play may differ at that level, and so may the frame after a boundary. A piece applied to the wrong
    # frames would move the grating and the readout, which this bound does not admit.
    serial_frames = {c.snapshot_id: c for c in one.result.checkpoints}
    for record in many.result.checkpoints:
        if record.snapshot_id == "after_boundary":
            continue
        reference_record = serial_frames[record.snapshot_id]
        if reference_record.animation_index in cut_plays:
            assert _frame_difference(project / record.png, project / reference_record.png) <= 96, record.snapshot_id
        else:
            assert record.sha256 == reference_record.sha256, record.snapshot_id
    # The frame after a window boundary, inside the first sweep, against the same frame of a serial render.
    reference = scianim(
        "render",
        str(project),
        "--profile",
        "storyboard",
        "--no-cache",
        "--sample",
        f"after_boundary={after_boundary!r}",
    )
    assert reference.returncode == 0, reference.stdout + reference.stderr
    serial_sample = {c.snapshot_id: c for c in latest().result.checkpoints}["after_boundary"]
    six_sample = {c.snapshot_id: c for c in many.result.checkpoints}["after_boundary"]
    assert six_sample.renderer_time_seconds == serial_sample.renderer_time_seconds
    assert six_sample.scene_id == "model" and six_sample.fidelity == "exact"
    assert _frame_difference(project / six_sample.png, project / serial_sample.png) <= 96

    # The cache does not care how many workers drew the movie.
    again = scianim("render", str(project), "--profile", "storyboard", "--workers", "3")
    assert again.returncode == 0 and "cache hit" in again.stdout


def _frame_difference(a: Path, b: Path) -> int:
    """The largest difference of any channel of any pixel between two sampled frames."""
    from PIL import Image, ImageChops

    with Image.open(a) as first, Image.open(b) as second:
        assert first.size == second.size
        diff = ImageChops.difference(first.convert("RGB"), second.convert("RGB"))
        return max(high for _low, high in diff.getextrema())


def test_a_rerender_draws_only_what_changed(workspace: Path, scianim) -> None:
    """ADR-033: after a change to one action, a render takes every play the change did not touch from the segment
    store, whatever the number of workers, and the untouched scenes' sampled frames are the same bytes."""
    project = workspace / "families" / "computational_neuroscience" / "orientation_tuning"
    assert scianim("codegen", str(project)).returncode == 0

    def latest() -> ArtifactManifest:
        return ArtifactManifest.model_validate_json(
            sorted((project / "renders" / "working").glob("*/manifest.json"))[-1].read_text()
        )

    first_run = scianim("render", str(project), "--profile", "storyboard", "--no-cache")
    assert first_run.returncode == 0, first_run.stdout + first_run.stderr
    first = latest()
    assert first.job.segment_store and first.inputs.scene_fingerprints
    assert (project / first.job.segment_store).is_dir() and any((project / first.job.segment_store).iterdir())

    storyboard = project / "storyboard.yaml"
    text = storyboard.read_text()
    start = text.index("id: sharpen")
    target = text.index("to: 8", start)
    storyboard.write_text(text[:target] + "to: 6" + text[target + len("to: 8") :])
    assert scianim("codegen", str(project)).returncode == 0
    second_run = scianim("render", str(project), "--profile", "storyboard", "--no-cache", "--workers", "2")
    assert second_run.returncode == 0, second_run.stdout + second_run.stderr
    second = latest()
    assert second.job.job_id != first.job.job_id and second.result.status == "succeeded"
    changed = [s for s, f in second.inputs.scene_fingerprints.items() if first.inputs.scene_fingerprints.get(s) != f]
    assert changed == ["model"]
    by_scene: dict[str, list] = {}
    for play in second.result.plays:
        by_scene.setdefault(str(play.scene_id), []).append(play)
    assert not any(p.drawn for p in by_scene["circuit"] + by_scene["data"])  # all from the store
    assert any(p.drawn for p in by_scene["model"])  # the sharpening was drawn anew
    assert "came unchanged from the segment store" in second_run.stdout
    log = (project / ".scianim" / "jobs" / second.job.job_id / "worker.log").read_text()
    assert "expected from the segment store" in log and "['circuit', 'data']" in log
    before = {c.snapshot_id: c.sha256 for c in first.result.checkpoints}
    after = {c.snapshot_id: c.sha256 for c in second.result.checkpoints}
    for snapshot_id in ("circuit_shown", "curve_cited", "model_labelled"):
        assert after[snapshot_id] == before[snapshot_id], snapshot_id
    assert after["model_complete"] != before["model_complete"]  # kappa ends at 6 now
    assert second.result.timing is not None and second.result.timing.within_tolerance
