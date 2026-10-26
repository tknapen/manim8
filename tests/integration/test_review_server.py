"""Milestone 3 acceptance through the API: render, annotate an object, approve a revision, restart."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scianim.server.app import create_app

pytestmark = pytest.mark.integration


def test_render_annotate_and_approve_through_the_api(workspace: Path, scianim) -> None:
    project = workspace / "families" / "computational_neuroscience" / "prf_tuning"
    assert scianim("codegen", str(project)).returncode == 0
    client = TestClient(create_app(workspace))
    runner = client.app.state.runner

    # A non-blocking render request: accepted immediately, finished by the worker process.
    accepted = client.post(
        "/api/projects/prf_tuning/jobs", json={"snapshot_ids": ["gaussian_visible", "size_labelled"]}
    )
    assert accepted.status_code == 202, accepted.text
    job_id = accepted.json()["job_id"]
    final = runner.wait(job_id, timeout=600)
    assert final.status == "succeeded", final.error
    job = client.get(f"/api/projects/prf_tuning/jobs/{job_id}").json()
    assert [c["snapshot_id"] for c in job["checkpoints"]] == ["gaussian_visible", "size_labelled"]
    assert job["checkpoints"][0]["kind"] == "manim_checkpoint" and job["submitted_by"] == "server"
    assert client.get(job["checkpoints"][1]["url"]).headers["content-type"] == "image/png"
    assert client.get(job["review_sheet_url"]).status_code == 200
    assert "exit 0" in client.get(f"/api/projects/prf_tuning/jobs/{job_id}/log").text

    # The same request again is a cache hit: no second worker run, same manifest.
    again = client.post("/api/projects/prf_tuning/jobs", json={"snapshot_ids": ["gaussian_visible", "size_labelled"]})
    hit = runner.wait(again.json()["job_id"], timeout=120)
    assert hit.status == "succeeded" and hit.cache_hit and hit.manifest == f"renders/working/{job_id}/manifest.json"

    # Click an object: the region comes from the layout report of the image that was shown.
    comment = client.post(
        "/api/projects/prf_tuning/feedback",
        json={
            "revision_id": "working",
            "job_id": job_id,
            "kind": "object_comment",
            "snapshot_id": "size_labelled",
            "object_id": "size_label",
            "text": "The label crowds the equation.",
        },
    )
    assert comment.status_code == 201, comment.text
    record = comment.json()
    assert record["scene_id"] == "gaussian" and record["region"]["width"] > 0
    assert record["image_sha256"] == next(
        c["sha256"] for c in job["checkpoints"] if c["snapshot_id"] == "size_labelled"
    )

    # Approval needs an immutable revision; render it through the API, then approve the displayed image.
    assert scianim("revision", "create", str(project), "-m", "review candidate").returncode == 0
    rev_job = client.post(
        "/api/projects/prf_tuning/jobs", json={"revision_id": "rev_0001", "snapshot_ids": ["size_labelled"]}
    )
    assert runner.wait(rev_job.json()["job_id"], timeout=600).status == "succeeded"
    approval = client.post(
        "/api/projects/prf_tuning/feedback",
        json={"revision_id": "rev_0001", "kind": "status", "status": "approved", "snapshot_id": "size_labelled"},
    )
    assert approval.status_code == 201, approval.text
    assert approval.json()["job_id"] == rev_job.json()["job_id"]

    # After a restart everything is read back from the files.
    restarted = TestClient(create_app(workspace))
    records = restarted.get("/api/projects/prf_tuning/feedback", params={"snapshot_id": "size_labelled"}).json()
    assert {(r["kind"], r["revision_id"]) for r in records} == {("object_comment", "working"), ("status", "rev_0001")}
    detail = restarted.get("/api/projects/prf_tuning").json()
    assert detail["latest_render"]["rev_0001"] == rev_job.json()["job_id"]
    comparison = restarted.get("/api/projects/prf_tuning/compare", params={"a": job_id, "b": "rev_0001"}).json()
    labelled = next(s for s in comparison["snapshots"] if s["snapshot_id"] == "size_labelled")
    assert labelled["identical"]  # same inputs, same pixels
