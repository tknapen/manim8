"""Named checkpoints rendered by Manim inside a workspace family environment (Milestone 2 acceptance)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scianim_core import ArtifactManifest

pytestmark = pytest.mark.integration


def manifests(project: Path, revision: str) -> list[ArtifactManifest]:
    paths = sorted((project / "renders" / revision).glob("*/manifest.json"))
    return [ArtifactManifest.model_validate_json(p.read_text()) for p in paths]


@pytest.fixture
def project(workspace: Path) -> Path:
    return workspace / "families" / "computational_neuroscience" / "divisive_normalization"


def test_checkpoints_cache_style_change_revisions_and_clean(project: Path, workspace: Path, scianim) -> None:
    assert scianim("codegen", str(project)).returncode == 0
    run = scianim("snapshot", str(project), "--no-cache", "--id", "excitation_visible", "--id", "equation_complete")
    assert run.returncode == 0, run.stdout + run.stderr
    manifest = manifests(project, "working")[-1]
    assert manifest.result.status == "succeeded"
    assert manifest.job.revision_id == "working"
    assert [c.snapshot_id for c in manifest.result.checkpoints] == ["excitation_visible", "equation_complete"]
    for record in manifest.result.checkpoints:
        png = project / record.png
        assert png.exists() and png.stat().st_size > 1000
        assert record.kind == "manim_checkpoint"
        assert record.width_px == 960 and record.height_px == 540
        assert record.layout, "layout report is empty"
    first = manifest.result.checkpoints[0]
    assert {item.object_id for item in first.layout} == {"scene_title", "drive_curve"}
    assert manifest.result.tool_versions and manifest.result.tool_versions.manim
    assert (project / manifest.job.output_dir / "review_sheet.html").exists()

    # Same inputs again: cache hit, no new job directory.
    before = len(manifests(project, "working"))
    again = scianim("snapshot", str(project), "--id", "excitation_visible", "--id", "equation_complete")
    assert again.returncode == 0 and "cache hit" in again.stdout
    assert len(manifests(project, "working")) == before

    # Freeze a revision, then render it: outputs land under renders/rev_0001 from the frozen code.
    created = scianim("revision", "create", str(project), "-m", "first cut")
    assert created.returncode == 0 and "rev_0001" in created.stdout, created.stdout + created.stderr
    rev_run = scianim("snapshot", str(project), "--revision", "rev_0001", "--id", "equation_complete")
    assert rev_run.returncode == 0, rev_run.stdout + rev_run.stderr
    rev_manifest = manifests(project, "rev_0001")[-1]
    assert rev_manifest.job.revision_id == "rev_0001"
    assert rev_manifest.job.scene_module.startswith("revisions/rev_0001/code/")
    assert rev_manifest.result.status == "succeeded"

    # A changed palette token in the workspace's theme: new cache key and different pixels for the curve frame.
    sheet = workspace / "styles" / "default" / "0.2.0" / "style.yaml"  # the baseline the example's theme inherits
    text = sheet.read_text()
    assert 'primary_signal: "#1F5FBF"' in text
    sheet.write_text(text.replace('primary_signal: "#1F5FBF"', 'primary_signal: "#FF3B30"'))
    changed = scianim("snapshot", str(project), "--id", "excitation_visible", "--id", "equation_complete")
    assert changed.returncode == 0, changed.stdout + changed.stderr
    assert "cache hit" not in changed.stdout
    second = manifests(project, "working")[-1]
    assert second.job.cache_key != manifest.job.cache_key
    assert second.inputs.resolved_style != manifest.inputs.resolved_style
    by_id_before = {c.snapshot_id: c for c in manifest.result.checkpoints}
    by_id_after = {c.snapshot_id: c for c in second.result.checkpoints}
    assert by_id_after["excitation_visible"].sha256 != by_id_before["excitation_visible"].sha256
    assert json.loads((project / second.job.output_dir / "result.json").read_text())["status"] == "succeeded"

    # The revision still renders from its frozen style (cache hit on the same key).
    rev_again = scianim("snapshot", str(project), "--revision", "rev_0001", "--id", "equation_complete")
    assert rev_again.returncode == 0 and "cache hit" in rev_again.stdout

    listing = scianim("workspace", "list", str(workspace))
    assert listing.returncode == 0 and "divisive_normalization" in listing.stdout

    cleaned = scianim("clean", str(project), "--keep", "1")
    assert cleaned.returncode == 0, cleaned.stdout + cleaned.stderr
    assert not (project / ".scianim" / "media").exists()
    assert len(manifests(project, "working")) == 1
    assert len(manifests(project, "rev_0001")) == 1
