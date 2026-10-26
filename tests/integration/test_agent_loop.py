"""Milestone 5 acceptance: brief + synthetic CSV -> proposed spec and storyboard -> code -> real snapshots ->
inspection -> a review comment -> a targeted revision -> a revision comparison, with provenance intact."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scianim.config.loader import load_yaml
from scianim_core import ArtifactManifest

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "agent_loop"


def _latest_manifest(project: Path, revision: str) -> ArtifactManifest:
    paths = sorted((project / "renders" / revision).glob("*/manifest.json"))
    return ArtifactManifest.model_validate_json(paths[-1].read_text())


def test_agent_loop_from_brief_to_revision_comparison(workspace: Path, scianim) -> None:
    family = workspace / "families" / "computational_neuroscience"
    # The finished loop is also shipped as an example; start from nothing but the brief and the table.
    shutil.rmtree(family / "orientation_tuning", ignore_errors=True)
    init = scianim(
        "project", "init", "orientation_tuning", "--family", "computational_neuroscience", "--workspace", str(workspace)
    )
    assert init.returncode == 0, init.stdout + init.stderr
    project = family / "orientation_tuning"
    shutil.copy(FIXTURES / "brief.md", project / "references" / "brief.md")
    shutil.copy(FIXTURES / "tuning.csv", project / "data" / "tuning.csv")
    (project / "proposals").mkdir()
    for name in ("prop_create_spec.yaml", "prop_create_storyboard.yaml"):
        shutil.copy(FIXTURES / name, project / "proposals" / name)

    # 1. The agent's spec proposal: validated, applied, flagged for scientific sign-off.
    check = scianim("propose", "validate", str(project), str(project / "proposals" / "prop_create_spec.yaml"))
    assert check.returncode == 0 and "touches scientific content" in check.stdout, check.stdout + check.stderr
    applied = scianim("propose", "apply", str(project), str(project / "proposals" / "prop_create_spec.yaml"))
    assert applied.returncode == 0, applied.stdout + applied.stderr
    assert "scientific content changed" in applied.stdout

    # 2. Sources are probed and the context bundle says what they say.
    probe = scianim("sources", "probe", str(project))
    assert probe.returncode == 0 and "orientation_deg" in probe.stdout, probe.stdout
    context = scianim("context", str(project))
    assert context.returncode == 0, context.stdout + context.stderr
    text = (project / ".scianim" / "context" / "CONTEXT.md").read_text()
    assert "26 rows" in text and "`response_hz`" in text and "Synthetic von Mises" in text
    assert "### `caption_with_citation`" in text

    # 3. The storyboard proposal, code generation and real Manim snapshots.
    applied = scianim("propose", "apply", str(project), str(project / "proposals" / "prop_create_storyboard.yaml"))
    assert applied.returncode == 0, applied.stdout + applied.stderr
    assert scianim("codegen", str(project)).returncode == 0
    render = scianim("snapshot", str(project), "--all", "--no-cache")
    assert render.returncode == 0, render.stdout + render.stderr
    manifest = _latest_manifest(project, "working")
    assert [c.snapshot_id for c in manifest.result.checkpoints] == [
        "intro_cited",
        "circuit_shown",
        "curve_visible",
        "model_labelled",
        "model_complete",
    ]
    by_id = {c.snapshot_id: c for c in manifest.result.checkpoints}
    assert {i.object_id for i in by_id["circuit_shown"].layout} == {"circuit_graph", "population"}
    assert {i.object_id for i in by_id["model_complete"].layout} == {"model_curve", "receptive_field"}
    assert "Synthetic von Mises tuning curves computed" in (by_id["intro_cited"].layout[1].text or "")
    assert all(not c.warnings for c in manifest.result.checkpoints), [
        (c.snapshot_id, c.warnings) for c in manifest.result.checkpoints
    ]

    # 4. Self-inspection before asking for review: no discrepancies.
    inspection = scianim("inspect", str(project))
    assert inspection.returncode == 0, inspection.stdout + inspection.stderr
    assert "no findings" in inspection.stdout or "discrepancy" not in inspection.stdout

    # 5. A human review comment on the data note, then a frozen revision.
    comment = scianim(
        "feedback",
        "add",
        str(project),
        "--snapshot",
        "intro_cited",
        "--object",
        "data_note",
        "--text",
        "Say plainly that these are synthetic von Mises curves.",
    )
    assert comment.returncode == 0, comment.stdout + comment.stderr
    feedback_id = next(p.stem for p in (project / "feedback").glob("fb_*.yaml"))
    assert scianim("revision", "create", str(project), "-m", "first storyboard").returncode == 0

    # 6. A targeted revision proposal answering that comment: a two-line patch, applied with a diff on record.
    revise = load_yaml(FIXTURES / "prop_revise_storyboard.yaml")
    revise["in_response_to"] = [feedback_id]
    (project / "proposals" / "prop_revise_caption.yaml").write_text(
        json.dumps(revise), encoding="utf-8"
    )  # YAML accepts JSON
    applied = scianim("propose", "apply", str(project), str(project / "proposals" / "prop_revise_caption.yaml"))
    assert applied.returncode == 0, applied.stdout + applied.stderr
    assert "storyboard.yaml: " in applied.stdout
    listing = scianim("propose", "list", str(project))
    assert listing.returncode == 0 and "pending:" in listing.stdout
    assert scianim("codegen", str(project)).returncode == 0
    assert scianim("snapshot", str(project), "--all").returncode == 0
    assert scianim("revision", "create", str(project), "-m", "reworded data note").returncode == 0
    assert scianim("snapshot", str(project), "--revision", "rev_0002", "--id", "intro_cited").returncode == 0
    assert scianim("snapshot", str(project), "--revision", "rev_0001", "--id", "intro_cited").returncode == 0

    # 7. The comparison shows the targeted change and nothing else moved.
    compare = scianim("compare", str(project), "rev_0001", "rev_0002")
    assert compare.returncode == 0, compare.stdout + compare.stderr
    assert "data_note text_changed" in compare.stdout.replace("\n", " ")

    # 8. Provenance survived: the applied proposals carry claims with source locators, the revision records the
    #    data hash that the source extract reported, and the citation names the data as synthetic.
    applied_dir = project / "proposals" / "applied"
    assert {p.stem for p in applied_dir.glob("*.yaml")} == {
        "prop_create_spec",
        "prop_create_storyboard",
        "prop_revise_caption",
    }
    spec_record = load_yaml(applied_dir / "prop_create_spec.yaml")
    assert spec_record["scientific_review_required"] is True
    assert (
        spec_record["proposal"]["claims"][0]["source_id"] == "tuning"
        and spec_record["proposal"]["claims"][0]["locator"] == "header row"
    )
    revise_record = load_yaml(applied_dir / "prop_revise_caption.yaml")
    assert revise_record["proposal"]["in_response_to"] == [feedback_id]
    extract = json.loads((project / ".scianim" / "sources" / "tuning.json").read_text())
    revision = json.loads((project / "revisions" / "rev_0002" / "revision.json").read_text())
    assert revision["hashes"]["data_files"]["tuning"] == extract["sha256"]
    assert "not measurements" in (project / "animation.yaml").read_text()
    stale = scianim("stale", str(project), "--since", "rev_0001")
    assert stale.returncode == 0 and "introduction: stale" in stale.stdout and "model: unchanged" in stale.stdout
