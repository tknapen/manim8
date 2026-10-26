"""Named checkpoints rendered by Manim inside a workspace family environment (Milestone 2 acceptance)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scianim_core import ArtifactManifest

pytestmark = pytest.mark.integration
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def manifests(project: Path, revision: str) -> list[ArtifactManifest]:
    paths = sorted((project / "renders" / revision).glob("*/manifest.json"))
    return [ArtifactManifest.model_validate_json(p.read_text()) for p in paths]


@pytest.fixture
def project(workspace: Path) -> Path:
    return workspace / "families" / "computational_neuroscience" / "divisive_normalization"


def test_checkpoints_cache_style_change_revisions_and_clean(project: Path, workspace: Path, scianim) -> None:
    assert scianim("codegen", str(project)).returncode == 0
    run = scianim("snapshot", str(project), "--no-cache", "--id", "excitation_visible", "--id", "pool_raised")
    assert run.returncode == 0, run.stdout + run.stderr
    manifest = manifests(project, "working")[-1]
    assert manifest.result.status == "succeeded"
    assert manifest.job.revision_id == "working"
    assert [c.snapshot_id for c in manifest.result.checkpoints] == ["excitation_visible", "pool_raised"]
    for record in manifest.result.checkpoints:
        png = project / record.png
        assert png.exists() and png.stat().st_size > 1000
        assert record.kind == "manim_checkpoint"
        assert record.width_px == 960 and record.height_px == 540
        assert record.layout, "layout report is empty"
    first = manifest.result.checkpoints[0]
    assert {item.object_id for item in first.layout} == {"drive_caption", "drive_note", "drive_curve"}
    assert manifest.result.tool_versions and manifest.result.tool_versions.manim
    assert (project / manifest.job.output_dir / "review_sheet.html").exists()

    # Same inputs again: cache hit, no new job directory.
    before = len(manifests(project, "working"))
    again = scianim("snapshot", str(project), "--id", "excitation_visible", "--id", "pool_raised")
    assert again.returncode == 0 and "cache hit" in again.stdout
    assert len(manifests(project, "working")) == before

    # Freeze a revision, then render it: outputs land under renders/rev_0001 from the frozen code.
    created = scianim("revision", "create", str(project), "-m", "first cut")
    assert created.returncode == 0 and "rev_0001" in created.stdout, created.stdout + created.stderr
    rev_run = scianim("snapshot", str(project), "--revision", "rev_0001", "--id", "pool_raised")
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
    changed = scianim("snapshot", str(project), "--id", "excitation_visible", "--id", "pool_raised")
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
    rev_again = scianim("snapshot", str(project), "--revision", "rev_0001", "--id", "pool_raised")
    assert rev_again.returncode == 0 and "cache hit" in rev_again.stdout

    listing = scianim("workspace", "list", str(workspace))
    assert listing.returncode == 0 and "divisive_normalization" in listing.stdout

    cleaned = scianim("clean", str(project), "--keep", "1")
    assert cleaned.returncode == 0, cleaned.stdout + cleaned.stderr
    assert not (project / ".scianim" / "media").exists()
    assert len(manifests(project, "working")) == 1
    assert len(manifests(project, "rev_0001")) == 1


def test_prf_tuning_renders_timed_reveals_and_relational_placement(workspace: Path, scianim) -> None:
    """The pRF clip: one scene, two sweeps on the same plot, a checkpoint inside the second sweep, stacked readouts."""
    project = workspace / "families" / "computational_neuroscience" / "prf_tuning"
    assert scianim("validate", str(project)).returncode == 0
    assert scianim("codegen", str(project)).returncode == 0
    generated = (project / "code" / "scene_prf_tuning.py").read_text()
    assert (
        generated.index("self.reveal(profile_plot)")
        < generated.index("self.reveal(prf_label)")
        < generated.index("self.wait_until(2)")
        < generated.index("shift = self.begin_vary(profile_plot")
        < generated.index("self.vary_until(shift, 5.5)")
        < generated.index("widen = self.begin_vary(profile_plot")
        < generated.index("self.vary_until(widen, 8.5)")
        < generated.index('checkpoint(self, "half_widened", expected_time=8.5)')
        < generated.index("self.vary_until(widen, 10.5)")
    )
    run = scianim("snapshot", str(project), "--all", "--no-cache")
    assert run.returncode == 0, run.stdout + run.stderr
    manifest = manifests(project, "working")[-1]
    assert manifest.result.status == "succeeded"
    records = {c.snapshot_id: c for c in manifest.result.checkpoints}
    assert list(records) == ["gaussian_visible", "centre_shifted", "half_widened", "widened"]
    for record in records.values():
        assert record.fidelity == "exact"
        assert record.warnings == [], (record.snapshot_id, record.warnings)
        assert (project / record.png).stat().st_size > 1000

    # Before anything moves: the plot and the equation label, no readout.
    start = {item.object_id: item for item in records["gaussian_visible"].layout}
    assert set(start) == {"profile_plot", "prf_label"}
    # After the first sweep its readout shows the final centre; inside the second sweep a second readout
    # stacks under the first and carries the eased value; both stay to the end.
    shifted = {item.object_id: item for item in records["centre_shifted"].layout}
    assert set(shifted) == {"profile_plot", "prf_label", "shift"}
    assert shifted["shift"].kind == "value_readout" and shifted["shift"].text == "x₀ = -3.0 deg"
    halfway = {item.object_id: item for item in records["half_widened"].layout}
    assert set(halfway) == {"profile_plot", "prf_label", "shift", "widen"}
    assert halfway["widen"].text == "σ = 2.8 deg"  # noqa: RUF001
    assert halfway["widen"].bbox.y > halfway["shift"].bbox.y and halfway["shift"].bbox.y > halfway["prf_label"].bbox.y
    done = {item.object_id: item for item in records["widened"].layout}
    assert done["widen"].text == "σ = 4.0 deg" and done["shift"].text == "x₀ = -3.0 deg"  # noqa: RUF001
    assert records["gaussian_visible"].sha256 != records["centre_shifted"].sha256 != records["widened"].sha256

    # `below: drive_caption` in the other example puts the note under the caption, left edges aligned.
    dn = workspace / "families" / "computational_neuroscience" / "divisive_normalization"
    assert scianim("codegen", str(dn)).returncode == 0
    assert scianim("snapshot", str(dn), "--id", "excitation_visible").returncode == 0
    first = {item.object_id: item for item in manifests(dn, "working")[-1].result.checkpoints[0].layout}
    caption, note = first["drive_caption"].bbox, first["drive_note"].bbox
    assert note.y >= caption.y + caption.height
    assert abs(note.x - caption.x) < 0.01


def test_gallery_kinds_still_render(workspace: Path, scianim) -> None:
    """comparison_plot and receptive_field_glyph left the brief examples; this storyboard keeps them rendered."""
    project = workspace / "families" / "computational_neuroscience" / "divisive_normalization"
    (project / "storyboard.yaml").write_text((FIXTURES / "gallery_storyboard.yaml").read_text())
    assert scianim("validate", str(project)).returncode == 0
    assert scianim("codegen", str(project)).returncode == 0
    run = scianim("snapshot", str(project), "--all", "--no-cache")
    assert run.returncode == 0, run.stdout + run.stderr
    [record] = manifests(project, "working")[-1].result.checkpoints
    assert {item.object_id for item in record.layout} == {"comparison", "field"}
    assert record.warnings == [], record.warnings
