"""Milestone 3: feedback records, the SQLite index, comparison and the review API (no rendering)."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from pydantic import ValidationError

from scianim.codegen.generate import write_scene_module
from scianim.compare import compare_manifests, layout_changes
from scianim.feedback.store import build_record, list_feedback, read_feedback, resolve_target, write_feedback
from scianim.index import Index
from scianim.planning.checks import validate_project
from scianim.project import Project
from scianim.render.manifests import JobStatus, write_status
from scianim.revisions.store import create_revision
from scianim.server.app import create_app
from scianim_core import ArtifactManifest, BBox, CheckpointRecord, FeedbackRecord, LayoutItem, WorkerResult
from scianim_core.feedback import Region
from scianim_core.jobs import InputHashes, ManimSettings, RenderJob, SnapshotTarget


def _png(path: Path, width: int = 192, height: int = 108, box: tuple[int, int, int, int] | None = None) -> str:
    image = Image.new("RGB", (width, height), "white")
    if box is not None:
        ImageDraw.Draw(image).rectangle(box, fill=(31, 95, 191))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fake_manifest(
    project: Project,
    job_id: str,
    revision_id: str = "working",
    label_x: float = 0.1,
    box_shift: int = 0,
) -> ArtifactManifest:
    """A manifest with two checkpoints and PNGs, the shape a real worker produces."""
    report = validate_project(project)
    assert report.animation and report.storyboard and report.style
    output_dir = f"renders/{revision_id}/{job_id}"
    records = []
    for index, (snapshot_id, scene_id, t) in enumerate(
        [("excitation_visible", "excitation", 4.0), ("pool_raised", "normalization", 14.0)]
    ):
        png = f"{output_dir}/{snapshot_id}.png"
        sha = _png(project.root / png, box=(20 + box_shift, 30, 90 + box_shift, 70))
        records.append(
            CheckpointRecord(
                snapshot_id=snapshot_id,
                scene_id=scene_id,
                kind="manim_checkpoint",
                png=png,
                width_px=192,
                height_px=108,
                sha256=sha,
                animation_index=index,
                expected_time_seconds=t,
                renderer_time_seconds=t,
                layout=[
                    LayoutItem(
                        object_id="drive_caption",
                        kind="text_caption",
                        bbox=BBox(x=label_x, y=0.05, width=0.3, height=0.05),
                        text="Excitatory drive",
                        text_height_px=27,
                    ),
                    LayoutItem(
                        object_id="drive_curve",
                        kind="scientific_plot",
                        bbox=BBox(x=0.2, y=0.2, width=0.6, height=0.6),
                    ),
                ],
            )
        )
    job = RenderJob(
        job_id=job_id,
        project_id=report.animation.id,
        revision_id=revision_id,
        family_id="computational_neuroscience",
        operation="render_snapshots",
        quality_profile="snapshot",
        scene_module=f"code/scene_{report.animation.id}.py",
        scene_class="DivisiveNormalization",
        snapshot_ids=[r.snapshot_id for r in records],
        snapshots={
            r.snapshot_id: SnapshotTarget(
                scene_id=r.scene_id, expected_time_seconds=r.expected_time_seconds, description=f"{r.snapshot_id} shown"
            )
            for r in records
        },
        output=report.animation.output,
        resolved_style=report.style,
        manim=ManimSettings(
            pixel_width=192,
            pixel_height=108,
            frame_rate=30,
            background_color="#FFFFFF",
            media_dir=".scianim/media/working",
        ),
        output_dir=output_dir,
        cache_key="sha256:" + "0" * 64,
    )
    manifest = ArtifactManifest(
        created_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        job=job,
        result=WorkerResult(job_id=job_id, status="succeeded", checkpoints=records, elapsed_seconds=1.0),
        inputs=InputHashes(
            animation_spec="a" * 64, storyboard="b" * 64, scene_code="c" * 64, resolved_style=report.style.hash
        ),
    )
    (project.root / output_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2))
    return manifest


@pytest.fixture
def rendered_project(project_copy: Project) -> tuple[Project, ArtifactManifest, ArtifactManifest]:
    report = validate_project(project_copy, require_family=True)
    assert report.animation and report.storyboard and report.style
    write_scene_module(
        report.animation, report.storyboard, report.style, project_copy.scene_module_path(report.animation)
    )
    first = fake_manifest(project_copy, "job_20260101T000000_aaaaaa", label_x=0.1)
    second = fake_manifest(project_copy, "job_20260101T000100_bbbbbb", label_x=0.2, box_shift=12)
    return project_copy, first, second


# --- records ----------------------------------------------------------------------------------------


def test_feedback_record_shape_rules() -> None:
    base = {"id": "fb_20260101T000000_abcdef", "created_at": "2026-01-01T00:00:00+00:00", "project_id": "p"}
    with pytest.raises(ValidationError, match="needs `region`"):
        FeedbackRecord(**base, revision_id="working", kind="region_comment", snapshot_id="s", text="x")
    with pytest.raises(ValidationError, match="needs `text`"):
        FeedbackRecord(**base, revision_id="working", kind="general_comment")
    with pytest.raises(ValidationError, match="immutable revision"):
        FeedbackRecord(
            **base, revision_id="working", kind="status", status="approved", snapshot_id="s", image_sha256="f" * 64
        )
    with pytest.raises(ValidationError, match="beyond the image"):
        Region(x=0.9, y=0.0, width=0.2, height=0.1)
    ok = FeedbackRecord(
        **base, revision_id="rev_0001", kind="status", status="approved", snapshot_id="s", image_sha256="f" * 64
    )
    assert ok.status == "approved"
    needs = FeedbackRecord(
        **base, revision_id="working", kind="status", status="needs_revision", snapshot_id="s", image_sha256="f" * 64
    )
    assert needs.revision_id == "working"  # a change request may target the working copy


def test_feedback_store_resolves_objects_and_round_trips(rendered_project) -> None:
    project, first, second = rendered_project
    target = resolve_target(project, "working", "excitation_visible", "drive_caption")
    assert target.manifest.job.job_id == second.job.job_id  # the latest render of the revision
    assert target.region is not None and target.region.x == pytest.approx(0.2)
    record = build_record(
        "divisive_normalization",
        revision_id="working",
        kind="object_comment",
        text="Nudge the title",
        snapshot_id="excitation_visible",
        object_id="drive_caption",
        target=target,
    )
    path = write_feedback(project, record)
    assert path.parent == project.feedback_dir and path.suffix == ".yaml"
    again = read_feedback(path)
    assert again == record
    assert again.image_sha256 == second.result.checkpoints[0].sha256
    assert again.image_width_px == 192 and again.scene_id == "excitation" and again.job_id == second.job.job_id
    assert [r.id for r in list_feedback(project)] == [record.id]
    with pytest.raises(Exception, match="no object 'nope'"):
        resolve_target(project, "working", "excitation_visible", "nope")
    explicit = resolve_target(project, "working", "pool_raised", job_id=first.job.job_id)
    assert explicit.manifest.job.job_id == first.job.job_id


# --- index and comparison -----------------------------------------------------------------------


def test_index_rebuild_and_refresh(rendered_project, workspace: Path) -> None:
    project, first, second = rendered_project
    index = Index(workspace)
    index.rebuild()
    assert {p.id for p in index.projects()} == {"divisive_normalization", "prf_tuning", "orientation_tuning"}
    jobs = index.jobs("divisive_normalization")
    assert [j["job_id"] for j in jobs] == [second.job.job_id, first.job.job_id]
    assert jobs[0]["status"] == "succeeded" and jobs[0]["checkpoint_count"] == 2 and jobs[0]["submitted_by"] == "cli"
    assert len(index.checkpoints("divisive_normalization", first.job.job_id)) == 2
    # A queued job known only from status.json appears too, and a canceled status overrides a manifest.
    write_status(
        project,
        JobStatus(
            job_id="job_20260101T000200_cccccc",
            project_id="divisive_normalization",
            revision_id="working",
            status="queued",
            created_at="2026-01-01T00:02:00+00:00",
            submitted_by="server",
        ),
    )
    write_status(
        project,
        JobStatus(
            job_id=first.job.job_id,
            project_id="divisive_normalization",
            revision_id="working",
            status="canceled",
            created_at="2026-01-01T00:00:00+00:00",
        ),
    )
    index.refresh_project("divisive_normalization")
    by_id = {j["job_id"]: j for j in index.jobs("divisive_normalization")}
    assert by_id["job_20260101T000200_cccccc"]["status"] == "queued"
    assert by_id[first.job.job_id]["status"] == "canceled"
    report = validate_project(project)
    create_revision(project, report, "first")
    write_feedback(
        project, build_record("divisive_normalization", revision_id="working", kind="general_comment", text="hi")
    )
    index.refresh_project("divisive_normalization")
    assert index.counts("divisive_normalization") == {"revisions": 1, "jobs": 3, "feedback": 1}
    assert index.feedback("divisive_normalization", kind="general_comment")[0]["text"] == "hi"
    index.close()


def test_compare_reports_pixels_and_layout(rendered_project) -> None:
    project, first, second = rendered_project
    out_dir = project.scianim_dir / "compare" / "test"
    results = compare_manifests(project, first, second, out_dir)
    by_id = {r.snapshot_id: r for r in results}
    moved = by_id["excitation_visible"]
    assert not moved.identical and moved.pixel_diff_fraction is not None and moved.pixel_diff_fraction > 0
    assert moved.diff_png is not None and moved.diff_png.exists()
    assert [(c.object_id, c.change) for c in moved.changes] == [("drive_caption", "moved")]
    same = compare_manifests(project, first, first)
    assert all(r.identical and r.pixel_diff_fraction == 0.0 for r in same)
    before = [LayoutItem(object_id="a", kind="text_caption", bbox=BBox(x=0, y=0, width=0.1, height=0.1), text="x")]
    after = [
        LayoutItem(object_id="a", kind="text_caption", bbox=BBox(x=0, y=0, width=0.2, height=0.1), text="y"),
        LayoutItem(object_id="b", kind="text_caption", bbox=BBox(x=0.5, y=0.5, width=0.1, height=0.1)),
    ]
    kinds = sorted((c.object_id, c.change) for c in layout_changes(before, after))
    assert kinds == [("a", "moved"), ("a", "resized"), ("a", "text_changed"), ("b", "added")]


# --- the API ---------------------------------------------------------------------------------------


def test_review_api_end_to_end_without_rendering(rendered_project, workspace: Path) -> None:
    project, first, second = rendered_project
    client = TestClient(create_app(workspace))
    ws = client.get("/api/workspace").json()
    assert {p["id"] for p in ws["projects"]} == {"divisive_normalization", "prf_tuning", "orientation_tuning"} and ws[
        "problems"
    ] == []
    detail = client.get("/api/projects/divisive_normalization").json()
    assert detail["validation"]["ok"] and detail["storyboard"]["scenes"][0]["id"] == "excitation"
    assert detail["latest_render"] == {"working": second.job.job_id}
    assert client.get("/api/projects/nope").status_code == 404

    job = client.get(f"/api/projects/divisive_normalization/jobs/{second.job.job_id}").json()
    assert [c["snapshot_id"] for c in job["checkpoints"]] == ["excitation_visible", "pool_raised"]
    png = client.get(job["checkpoints"][0]["url"])
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    assert client.get("/api/projects/divisive_normalization/artifacts/../animation.yaml").status_code == 404
    assert client.get("/api/projects/divisive_normalization/artifacts/working/../../animation.yaml").status_code == 404

    # An object comment: the region and image hash come from the layout report of the displayed render.
    created = client.post(
        "/api/projects/divisive_normalization/feedback",
        json={
            "revision_id": "working",
            "kind": "object_comment",
            "snapshot_id": "excitation_visible",
            "object_id": "drive_caption",
            "text": "Lower the title",
        },
    )
    assert created.status_code == 201, created.text
    record = created.json()
    assert record["region"]["x"] == pytest.approx(0.2) and record["job_id"] == second.job.job_id
    assert record["image_sha256"] == second.result.checkpoints[0].sha256 and record["scene_id"] == "excitation"
    assert (project.feedback_dir / f"{record['id']}.yaml").exists()

    # Approval needs an immutable revision and binds to the image shown.
    refused = client.post(
        "/api/projects/divisive_normalization/feedback",
        json={"revision_id": "working", "kind": "status", "status": "approved", "snapshot_id": "excitation_visible"},
    )
    assert refused.status_code == 422 and "immutable revision" in refused.text
    report = validate_project(project)
    revision = create_revision(project, report, "freeze")
    frozen = fake_manifest(project, "job_20260101T000300_dddddd", revision_id=revision.id)
    approved = client.post(
        "/api/projects/divisive_normalization/feedback",
        json={"revision_id": revision.id, "kind": "status", "status": "approved", "snapshot_id": "excitation_visible"},
    )
    assert approved.status_code == 201, approved.text
    assert approved.json()["image_sha256"] == frozen.result.checkpoints[0].sha256

    # The records survive a server restart because the files are canonical.
    restarted = TestClient(create_app(workspace))
    listing = restarted.get(
        "/api/projects/divisive_normalization/feedback", params={"snapshot_id": "excitation_visible"}
    ).json()
    assert {r["kind"] for r in listing} == {"object_comment", "status"}
    assert (
        restarted.get(f"/api/projects/divisive_normalization/feedback/{record['id']}").json()["text"]
        == "Lower the title"
    )
    assert restarted.get("/api/projects/divisive_normalization/revisions").json()[0]["id"] == revision.id

    comparison = restarted.get(
        "/api/projects/divisive_normalization/compare", params={"a": first.job.job_id, "b": "working"}
    ).json()
    moved = next(s for s in comparison["snapshots"] if s["snapshot_id"] == "excitation_visible")
    assert not moved["identical"] and moved["changes"][0]["change"] == "moved"
    assert restarted.get(moved["diff_url"]).status_code == 200
    assert (
        restarted.get(
            "/api/projects/divisive_normalization/compare", params={"a": "rev_0042", "b": "working"}
        ).status_code
        == 404
    )

    # A job request is validated and queued without running code from the request.
    rejected = restarted.post("/api/projects/divisive_normalization/jobs", json={"revision_id": "../x"})
    assert rejected.status_code == 422
    queued = restarted.post("/api/projects/divisive_normalization/jobs", json={"snapshot_ids": ["excitation_visible"]})
    assert queued.status_code == 202 and queued.json()["status"] == "queued"
    job_id = queued.json()["job_id"]
    runner = restarted.app.state.runner
    final = runner.wait(job_id, timeout=120)
    assert final.status in ("failed", "succeeded")  # no family environment in unit tests: a clear failure, not a crash
    shown = restarted.get(f"/api/projects/divisive_normalization/jobs/{job_id}").json()
    assert shown["status"] == final.status and shown["submitted_by"] == "server"
    if final.status == "failed":
        assert "environment" in (shown["error"] or "")
    status_file = project.scianim_dir / "jobs" / job_id / "status.json"
    assert json.loads(status_file.read_text())["status"] == final.status


def test_index_with_another_schema_version_is_rebuilt(workspace: Path) -> None:
    import sqlite3

    path = workspace / ".scianim" / "index.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    stale = sqlite3.connect(path)
    stale.execute("CREATE TABLE jobs (only_one_column TEXT)")
    stale.execute("PRAGMA user_version = 1")
    stale.commit()
    stale.close()
    index = Index(workspace)  # recreates the tables instead of failing on the old shape
    index.rebuild()
    assert {p.id for p in index.projects()} == {"divisive_normalization", "prf_tuning", "orientation_tuning"}
    index.close()
