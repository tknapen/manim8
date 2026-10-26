"""Milestone 5 without rendering: source adapters, context export, proposals, patches and inspection."""

from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

import pytest
from PIL import Image

from scianim.agent.context import describe_kind, export_context
from scianim.agent.inspect import Finding, expected_objects, inspect_manifest, record_findings
from scianim.agent.proposals import apply_patch, apply_proposal, list_applied, load_proposal, resolve_proposal
from scianim.codegen.generate import write_scene_module
from scianim.config.loader import SpecError, load_animation, load_storyboard
from scianim.feedback.store import list_feedback
from scianim.planning.checks import validate_project
from scianim.project import Project
from scianim.sources.adapters import load_extracts, probe_all, probe_source
from scianim_core import (
    ArtifactManifest,
    BBox,
    CheckpointRecord,
    LayoutItem,
    LayoutWarning,
    Proposal,
    SourceRef,
    WorkerResult,
)
from scianim_core.jobs import InputHashes, ManimSettings, RenderJob, SnapshotTarget
from scianim_core.proposals import PatchOperation

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "agent_loop"


def test_csv_markdown_and_image_adapters_report_facts_only(tmp_path: Path) -> None:
    csv_ref = SourceRef(id="tuning", type="csv", path="data/tuning.csv", role="illustrative_data")
    extract = probe_source(csv_ref, FIXTURES / "tuning.csv")
    assert extract.says["rows"] == 26 and extract.says["header"] == [
        "orientation_deg",
        "response_hz",
        "condition",
        "origin",
    ]
    columns = {c["name"]: c for c in extract.says["columns"]}
    assert columns["orientation_deg"]["dtype"] == "integer" and columns["orientation_deg"]["maximum"] == 180
    assert columns["response_hz"]["dtype"] == "number" and columns["condition"]["distinct"] == 2
    assert extract.inferred == [] and any("not inferred" in n for n in extract.notes)
    assert len(extract.sha256) == 64

    md = probe_source(
        SourceRef(id="brief", type="markdown", path="brief.md", role="explanatory_text"), FIXTURES / "brief.md"
    )
    assert md.says["headings"][0].startswith("# Brief") and md.says["words"] > 50 and not md.says["truncated"]

    png = tmp_path / "ref.png"
    Image.new("RGB", (320, 180), "white").save(png)
    image = probe_source(SourceRef(id="ref", type="image", path="ref.png", role="composition_reference"), png)
    assert image.says == {"width_px": 320, "height_px": 180, "mode": "RGB", "format": "PNG"}
    with pytest.raises(SpecError, match="not found"):
        probe_source(csv_ref, tmp_path / "missing.csv")


def test_pdf_adapter_extracts_page_text(tmp_path: Path) -> None:
    from pypdf import PdfWriter

    pdf = tmp_path / "paper.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_metadata({"/Title": "A blank paper"})
    with pdf.open("wb") as handle:
        writer.write(handle)
    extract = probe_source(SourceRef(id="paper", type="pdf", path="paper.pdf", role="scientific_reference"), pdf)
    assert extract.says["page_count"] == 1 and extract.says["title"] == "A blank paper"
    assert extract.says["pages"][0]["page"] == 1
    assert any("scanned" in n or "no extractable" in n for n in extract.notes)


def test_probe_all_and_context_export(project_copy: Project) -> None:
    report = validate_project(project_copy)
    extracts = probe_all(project_copy, report)
    assert [e.source_id for e in extracts] == ["responses"]
    assert set(load_extracts(project_copy)) == {"responses"}
    out = export_context(project_copy, report)
    text = (out / "CONTEXT.md").read_text()
    assert "## Brief" in text and "## Sources: what they say" in text and "`responses`" in text
    assert "### `function_plot`" in text and "### `network_graph`" in text and "### `caption_with_citation`" in text
    assert "## Storyboard (current)" in text and "excitation" in text
    assert (out / "proposal.template.yaml").exists() and (out / "schemas" / "proposal.schema.json").exists()
    assert (out / "sources" / "responses.json").exists()
    import json

    manifest = json.loads((out / "context.json").read_text())
    assert manifest["project"]["id"] == "divisive_normalization" and manifest["registry_version"]
    described = describe_kind("network_graph")
    names = {p["name"] for p in described["params"]}
    assert {"nodes", "edges", "layout"} <= names


def test_json_patch_operations() -> None:
    doc = {"a": {"b": [1, 2, 3]}, "c": "x"}
    patched = apply_patch(
        doc,
        [
            PatchOperation(op="replace", path="/c", value="y"),
            PatchOperation(op="add", path="/a/b/-", value=4),
            PatchOperation(op="remove", path="/a/b/0"),
            PatchOperation(op="add", path="/d", value={"e": 1}),
        ],
    )
    assert patched == {"a": {"b": [2, 3, 4]}, "c": "y", "d": {"e": 1}} and doc["c"] == "x"
    with pytest.raises(SpecError, match="no key"):
        apply_patch(doc, [PatchOperation(op="replace", path="/missing", value=1)])
    with pytest.raises(SpecError, match="out of range"):
        apply_patch(doc, [PatchOperation(op="remove", path="/a/b/9")])


def test_proposals_create_patch_and_record(workspace: Path) -> None:
    family = workspace / "families" / "computational_neuroscience"
    project_dir = family / "orientation_tuning"
    shutil.rmtree(project_dir, ignore_errors=True)  # the example copy; the loop starts from scratch
    project_dir.mkdir()
    (project_dir / "references").mkdir()
    (project_dir / "data").mkdir()
    shutil.copy(FIXTURES / "brief.md", project_dir / "references" / "brief.md")
    shutil.copy(FIXTURES / "tuning.csv", project_dir / "data" / "tuning.csv")
    project = Project(project_dir)

    spec_proposal = load_proposal(FIXTURES / "prop_create_spec.yaml")
    resolved = resolve_proposal(project, spec_proposal)
    assert resolved.ok and resolved.touches_science, resolved.errors
    applied = apply_proposal(project, spec_proposal)
    assert applied.scientific_review_required and applied.diffs["animation.yaml"].startswith("--- a/animation.yaml")
    assert load_animation(project.animation_path).id == "orientation_tuning"
    with pytest.raises(SpecError, match="applied before"):
        apply_proposal(project, spec_proposal)

    storyboard_proposal = load_proposal(FIXTURES / "prop_create_storyboard.yaml")
    # A new storyboard binds data and equations: that is scientific content, so sign-off is required.
    assert apply_proposal(project, storyboard_proposal).scientific_review_required is True
    storyboard = load_storyboard(project.storyboard_path)
    assert [s.id for s in storyboard.scenes] == ["introduction", "circuit", "tuning_curve", "model"]
    assert validate_project(project, require_family=True).ok

    revise = load_proposal(FIXTURES / "prop_revise_storyboard.yaml")
    applied_patch = apply_proposal(project, revise)
    assert applied_patch.scientific_review_required is False  # a caption rewording binds nothing new
    after = load_storyboard(project.storyboard_path)
    note = after.scenes[0].objects[1]
    assert note.params["text"] == "Synthetic von Mises tuning curves" and note.reveal_at_seconds == 1
    diff = applied_patch.diffs["storyboard.yaml"]
    assert "-        reveal_at_seconds: 2" in diff and "+        reveal_at_seconds: 1" in diff
    assert [a.proposal.id for a in list_applied(project)] == [
        "prop_create_spec",
        "prop_create_storyboard",
        "prop_revise_caption",
    ]

    # A proposal that breaks a contract is refused before anything is written.
    broken = Proposal.model_validate(
        {
            **revise.model_dump(mode="json"),
            "id": "prop_broken",
            "targets": [
                {
                    "file": "storyboard.yaml",
                    "patch": [{"op": "replace", "path": "/scenes/0/objects/1/params/source", "value": "nope"}],
                }
            ],
        }
    )
    with pytest.raises(SpecError, match="not declared"):
        apply_proposal(project, broken)
    assert load_storyboard(project.storyboard_path).scenes[0].objects[1].params["source"] == "tuning"


def _manifest_with_frames(project: Project, blank_second: bool) -> ArtifactManifest:
    report = validate_project(project)
    assert report.animation and report.storyboard and report.style
    job_id = "job_20260101T000000_abcdef"
    output_dir = f"renders/working/{job_id}"
    (project.root / output_dir).mkdir(parents=True, exist_ok=True)
    records = []
    for snapshot_id, scene_id, t, blank in (
        ("excitation_visible", "excitation", 9.0, False),
        ("equation_complete", "equation", 40.0, blank_second),
    ):
        image = Image.new("RGB", (96, 54), "white")
        if not blank:
            image.putpixel((10, 10), (0, 0, 0))
            for x in range(20, 60):
                image.putpixel((x, 20), (31, 95, 191))
        png = f"{output_dir}/{snapshot_id}.png"
        image.save(project.root / png)
        layout = [
            LayoutItem(
                object_id="scene_title",
                kind="text_caption",
                bbox=BBox(x=0.05, y=0.05, width=0.3, height=0.05),
                text="t",
                text_height_px=27,
            )
        ]
        if snapshot_id == "excitation_visible":
            layout.append(
                LayoutItem(
                    object_id="drive_curve", kind="scientific_plot", bbox=BBox(x=0.2, y=0.2, width=0.6, height=0.6)
                )
            )
        records.append(
            CheckpointRecord(
                snapshot_id=snapshot_id,
                scene_id=scene_id,
                kind="manim_checkpoint",
                png=png,
                width_px=96,
                height_px=54,
                sha256="a" * 64,
                animation_index=1,
                expected_time_seconds=t,
                layout=layout,
                warnings=[]
                if snapshot_id == "excitation_visible"
                else [
                    LayoutWarning(
                        code="text_too_small", object_ids=["scene_title"], detail="font size 9px is below the minimum"
                    )
                ],
            )
        )
    job = RenderJob(
        job_id=job_id,
        project_id=report.animation.id,
        revision_id="working",
        family_id="computational_neuroscience",
        operation="render_snapshots",
        quality_profile="snapshot",
        scene_module="code/x.py",
        scene_class="X",
        snapshot_ids=[r.snapshot_id for r in records],
        snapshots={
            r.snapshot_id: SnapshotTarget(
                scene_id=r.scene_id,
                expected_time_seconds=r.expected_time_seconds,
                description=f"{r.snapshot_id}: shows normalization_equation",
            )
            for r in records
        },
        output=report.animation.output,
        resolved_style=report.style,
        manim=ManimSettings(
            pixel_width=96,
            pixel_height=54,
            frame_rate=30,
            background_color="#FFFFFF",
            media_dir=".scianim/media/working",
        ),
        output_dir=output_dir,
        cache_key="sha256:" + "0" * 64,
    )
    return ArtifactManifest(
        created_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        job=job,
        result=WorkerResult(job_id=job_id, status="succeeded", checkpoints=records, elapsed_seconds=1),
        inputs=InputHashes(
            animation_spec="a" * 64, storyboard="b" * 64, scene_code="c" * 64, resolved_style=report.style.hash
        ),
    )


def test_inspection_finds_missing_objects_and_blank_frames(project_copy: Project) -> None:
    report = validate_project(project_copy)
    assert report.storyboard
    assert expected_objects(report.storyboard, "excitation", 9.0) == ["scene_title", "drive_curve"]
    manifest = _manifest_with_frames(project_copy, blank_second=True)
    findings = inspect_manifest(project_copy, manifest, report.storyboard)
    codes = {(f.snapshot_id, f.code) for f in findings}
    # The equation checkpoint lacks its equation object (the layout only has a stray title) and the frame is blank.
    assert ("equation_complete", "object_missing") in codes and ("equation_complete", "blank_frame") in codes
    assert ("equation_complete", "description_names_missing_object") in codes
    assert ("equation_complete", "object_unexpected") in codes
    assert not any(f.snapshot_id == "excitation_visible" and f.severity == "discrepancy" for f in findings)
    recorded = record_findings(project_copy, manifest, findings)
    assert recorded and all(r.author == "agent:inspect" for r in recorded)
    # A warning about a present object becomes an object comment with its region; a missing object a general one.
    assert any(r.kind == "object_comment" and r.object_id == "scene_title" and r.region is not None for r in recorded)
    assert any(r.kind == "general_comment" and "[object_missing]" in r.text for r in recorded)
    assert len(list_feedback(project_copy)) == len(recorded)
    assert isinstance(findings[0], Finding)


def test_codegen_handles_new_kinds(workspace: Path) -> None:
    project_dir = workspace / "families" / "computational_neuroscience" / "orientation_tuning"
    shutil.rmtree(project_dir, ignore_errors=True)
    project_dir.mkdir()
    (project_dir / "references").mkdir()
    (project_dir / "data").mkdir()
    shutil.copy(FIXTURES / "brief.md", project_dir / "references" / "brief.md")
    shutil.copy(FIXTURES / "tuning.csv", project_dir / "data" / "tuning.csv")
    project = Project(project_dir)
    apply_proposal(project, load_proposal(FIXTURES / "prop_create_spec.yaml"))
    apply_proposal(project, load_proposal(FIXTURES / "prop_create_storyboard.yaml"))
    report = validate_project(project, require_family=True)
    assert report.ok and report.animation and report.storyboard and report.style
    target = write_scene_module(
        report.animation, report.storyboard, report.style, project.scene_module_path(report.animation)
    )
    code = target.read_text()
    for kind in (
        "caption_with_citation",
        "network_graph",
        "schematic_population",
        "receptive_field_glyph",
        "function_plot",
    ):
        assert f"C.{kind}(" in code
    assert validate_project(project, require_family=True).ok
