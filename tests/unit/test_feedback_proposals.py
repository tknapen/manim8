"""Feedback becomes proposals by rules (ADR-036), without rendering."""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient

from scianim.agent.feedback_proposals import addressed_ids, generate, open_feedback
from scianim.agent.proposals import apply_proposal
from scianim.codegen.generate import write_scene_module
from scianim.config.loader import load_yaml
from scianim.feedback.store import build_record, new_feedback_id, write_feedback
from scianim.planning.checks import validate_project
from scianim.project import Project
from scianim.render.jobs import build_snapshot_job, sources_from_report
from scianim.server.app import create_app
from scianim_core import ArtifactManifest, CheckpointRecord, LayoutWarning, WorkerResult
from scianim_core.feedback import Region


def _prepared(project: Project):
    report = validate_project(project, require_family=True)
    assert report.animation and report.storyboard and report.style and report.family
    write_scene_module(report.animation, report.storyboard, report.style, project.scene_module_path(report.animation))
    return validate_project(project, require_family=True)


def _comment(
    project: Project,
    text: str,
    *,
    object_id: str | None,
    snapshot_id: str | None,
    scene_id: str | None,
    severity: str = "visual",
    seconds: float | None = None,
    stamp: int = 0,
):
    record = build_record(
        project.root.name,
        revision_id="working",
        kind="object_comment" if object_id else "general_comment",
        text=text,
        severity=severity,  # type: ignore[arg-type]
        snapshot_id=snapshot_id,
        scene_id=scene_id,
        object_id=object_id,
        region=Region(x=0.1, y=0.1, width=0.2, height=0.1) if object_id else None,
        author="reviewer",
        time_seconds=seconds,
    )
    record = record.model_copy(update={"id": new_feedback_id(dt.datetime(2026, 10, 31, 12, 0, stamp, tzinfo=dt.UTC))})
    write_feedback(project, record)
    return record


def test_rules_turn_comments_into_patches_and_leave_the_rest_open(project_copy: Project) -> None:
    report = _prepared(project_copy)
    before = load_yaml(project_copy.storyboard_path)
    note = next(o for s in before["scenes"] for o in s["objects"] if o["id"] == "drive_note")
    assert note["params"].get("anchor", "top_left") != "center"
    a = _comment(
        project_copy,
        "The note runs off the page at the top; it sits outside the safe zone.",
        object_id="drive_note",
        snapshot_id="excitation_visible",
        scene_id="excitation",
        stamp=1,
    )
    b = _comment(
        project_copy,
        "set width_fraction to 0.5 here",
        object_id="response_curve",
        snapshot_id="pool_raised",
        scene_id="normalization",
        stamp=2,
    )
    c = _comment(
        project_copy,
        "The pool rises too slow; it drags.",
        object_id="response_curve",
        snapshot_id="pool_raised",
        scene_id="normalization",
        severity="timing",
        stamp=3,
    )
    d = _comment(
        project_copy,
        "Is the exponent really one here?",
        object_id="normalization_equation",
        snapshot_id="pool_raised",
        scene_id="normalization",
        severity="scientific",
        stamp=4,
    )
    e = _comment(
        project_copy,
        "Looks odd somehow.",
        object_id="drive_curve",
        snapshot_id="excitation_visible",
        scene_id="excitation",
        stamp=5,
    )
    assert [r.id for r in open_feedback(project_copy)] == [a.id, b.id, c.id, d.id, e.id]

    generated = generate(project_copy, report, None, now=dt.datetime(2026, 10, 31, 12, 0, tzinfo=dt.UTC))
    by_feedback = {p.in_response_to[0]: p for p in generated.proposals}
    assert set(by_feedback) == {a.id, b.id, c.id}
    move = by_feedback[a.id].targets[0].patch[0]
    assert move.path.endswith("/params/anchor") and move.value == "center"
    size = by_feedback[b.id].targets[0].patch[0]
    assert size.path.endswith("/params/width_fraction") and size.value == 0.5
    pace = by_feedback[c.id].targets[0].patch[0]
    assert pace.path.endswith("/duration_seconds") and pace.value == 3.2  # raise_pool, 4 s, shortened by 0.8
    assert all(p.author == "agent:feedback" and p.kind == "revise_storyboard" for p in generated.proposals)
    assert [u.feedback_id for u in generated.unresolved] == [d.id, e.id]
    assert generated.unresolved[0].science and not generated.unresolved[1].science
    assert len(generated.written) == 3 and all(path.exists() for path in generated.written)

    # Pending proposals already answer their feedback; applying one records the answer permanently.
    assert set(addressed_ids(project_copy)) == {a.id, b.id, c.id}
    assert [r.id for r in open_feedback(project_copy)] == [d.id, e.id]
    applied = apply_proposal(project_copy, by_feedback[a.id])
    assert applied.scientific_review_required is False
    after = load_yaml(project_copy.storyboard_path)
    assert (
        next(o for s in after["scenes"] for o in s["objects"] if o["id"] == "drive_note")["params"]["anchor"]
        == "center"
    )
    assert addressed_ids(project_copy)[a.id] == by_feedback[a.id].id
    # Running the rules again proposes nothing new for the answered items.
    again = generate(project_copy, report, None, write=False)
    assert again.proposals == [] and [u.feedback_id for u in again.unresolved] == [d.id, e.id]


def test_inspection_warnings_become_patches_and_the_api_exposes_them(project_copy: Project, workspace) -> None:
    report = _prepared(project_copy)
    assert report.family
    job, paths, hashes = build_snapshot_job(
        project_copy, sources_from_report(project_copy, report), report.family, ["excitation_visible"]
    )
    from PIL import Image

    png = paths.output_dir / "excitation_visible.png"
    png.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (96, 54), (255, 255, 255)).save(png)
    record = CheckpointRecord(
        snapshot_id="excitation_visible",
        scene_id="excitation",
        kind="manim_checkpoint",
        png=png.relative_to(project_copy.root).as_posix(),
        width_px=960,
        height_px=540,
        sha256="a" * 64,
        animation_index=1,
        expected_time_seconds=4,
        layout=[],
        warnings=[
            LayoutWarning(
                code="outside_safe_zone", object_ids=["drive_note"], detail="drive_note leaves the safe zone at the top"
            )
        ],
    )
    manifest = ArtifactManifest(
        created_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        job=job,
        result=WorkerResult(job_id=job.job_id, status="succeeded", checkpoints=[record], elapsed_seconds=1),
        inputs=hashes,
    )
    generated = generate(project_copy, report, manifest, write=False)
    anchors = [p for p in generated.proposals if p.targets[0].patch[0].path.endswith("/params/anchor")]
    assert anchors and anchors[0].in_response_to == [] and "drive_note" in anchors[0].summary
    # A white frame with nothing registered is only a note; the inspection leaves nothing else open here.
    assert all(u.feedback_id is None for u in generated.unresolved)

    client = TestClient(create_app(workspace))
    _comment(
        project_copy,
        "this one sits outside the safe zone",
        object_id="drive_note",
        snapshot_id="excitation_visible",
        scene_id="excitation",
        stamp=7,
    )
    response = client.post("/api/projects/divisive_normalization/proposals/from-feedback")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["proposals"] and body["proposals"][0]["path"].startswith("proposals/")
    listed = client.get("/api/projects/divisive_normalization/feedback").json()
    assert listed and listed[-1]["addressed_by"].endswith("(pending)")
