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
    sheet = (
        workspace / "styles" / "default" / "0.3.0" / "style.yaml"
    )  # the root of the chain the example's theme inherits
    text = sheet.read_text()
    assert 'primary_signal: "#4E86C6"' in text
    sheet.write_text(text.replace('primary_signal: "#4E86C6"', 'primary_signal: "#FF3B30"'))
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
    """The pRF clip: a surface under an orbiting camera, two concurrent centre sweeps, then the size, with stacked
    readouts and a checkpoint inside the concurrent segment; plus relational placement in the other example."""
    project = workspace / "families" / "computational_neuroscience" / "prf_tuning"
    assert scianim("validate", str(project)).returncode == 0
    assert scianim("codegen", str(project)).returncode == 0
    generated = (project / "code" / "scene_prf_tuning.py").read_text()
    assert "self.run_until(0.85, [reveal_prf_surface, reveal_prf_label, orbit])" in generated
    assert "self.run_until(5, [orbit, move_x, move_y])" in generated
    assert generated.index('checkpoint(self, "moving", expected_time=5)') < generated.index(
        "self.run_until(7, [orbit, move_x, move_y])"
    )
    run = scianim("snapshot", str(project), "--all", "--no-cache")
    assert run.returncode == 0, run.stdout + run.stderr
    manifest = manifests(project, "working")[-1]
    assert manifest.result.status == "succeeded"
    records = {c.snapshot_id: c for c in manifest.result.checkpoints}
    assert list(records) == ["gaussian_visible", "moving", "moved", "grown"]
    for record in records.values():
        assert record.fidelity == "exact"
        assert record.warnings == [], (record.snapshot_id, record.warnings)
        assert (project / record.png).stat().st_size > 1000

    start = {item.object_id: item for item in records["gaussian_visible"].layout}
    assert set(start) == {"prf_surface", "prf_label"}
    assert 0 < start["prf_surface"].bbox.width < 1 and start["prf_surface"].kind == "surface_plot"
    moving = {item.object_id: item for item in records["moving"].layout}
    assert set(moving) == {"prf_surface", "prf_label", "move_x", "move_y"}
    assert moving["move_x"].text.startswith("x₀ = ") and moving["move_x"].text.endswith(" deg")
    assert moving["move_x"].text not in ("x₀ = 2.0 deg", "x₀ = -3.0 deg")
    moved = {item.object_id: item for item in records["moved"].layout}
    assert moved["move_x"].text == "x₀ = -3.0 deg" and moved["move_y"].text == "y₀ = 3.0 deg"
    grown = {item.object_id: item for item in records["grown"].layout}
    assert grown["grow"].text == "σ = 3.5 deg"  # noqa: RUF001
    assert grown["grow"].bbox.y > grown["move_y"].bbox.y > grown["move_x"].bbox.y > grown["prf_label"].bbox.y
    assert records["gaussian_visible"].sha256 != records["moved"].sha256 != records["grown"].sha256

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
    # Codegen first: the shared workspace may hold a scene module generated for the example's own storyboard.
    assert scianim("codegen", str(project)).returncode == 0
    assert scianim("validate", str(project)).returncode == 0
    run = scianim("snapshot", str(project), "--all", "--no-cache")
    assert run.returncode == 0, run.stdout + run.stderr
    [record] = manifests(project, "working")[-1].result.checkpoints
    assert {item.object_id for item in record.layout} == {"comparison", "field"}
    assert record.warnings == [], record.warnings


def test_gabor_filter_renders_in_segments(workspace: Path, scianim) -> None:
    """A surface mesh whose axes leave after the first checkpoint, a camera orbit through the whole clip, and
    four segments with a lead-in each (two sweeps concurrent in the third): every checkpoint exact, the surface's
    projected box inside the frame, the readouts stacked, the value held through the lead-in."""
    project = workspace / "families" / "computational_neuroscience" / "gabor_filter"
    assert scianim("validate", str(project)).returncode == 0
    assert scianim("codegen", str(project)).returncode == 0
    generated = (project / "code" / "scene_gabor_filter.py").read_text()
    assert "orbit = self.begin_orbit(to_theta_degrees=255.0" in generated
    assert (
        "axes_away = self.begin_fade_axes(gabor_surface, visible=False, at_seconds=3, duration_seconds=0.8" in generated
    )
    assert "self.run_until(3.8, [orbit, axes_away])" in generated
    assert generated.count("lead_in_seconds=1)") == 5
    assert (
        "self.run_until(4.6, [orbit, rotate])" in generated
        and "self.run_until(19.5, [orbit, shift_x, shift_y])" in generated
    )
    run = scianim("snapshot", str(project), "--all", "--no-cache")
    assert run.returncode == 0, run.stdout + run.stderr
    manifest = manifests(project, "working")[-1]
    records = {c.snapshot_id: c for c in manifest.result.checkpoints}
    assert list(records) == [
        "with_axes",
        "theta_emphasized",
        "rotating",
        "rotated",
        "higher_frequency",
        "moved",
        "smaller",
    ]
    for record in records.values():
        assert record.fidelity == "exact" and record.warnings == [], (record.snapshot_id, record.warnings)
    surface = next(i for i in records["rotating"].layout if i.object_id == "gabor_surface")
    assert surface.kind == "surface_plot" and surface.bbox.x >= 0 and surface.bbox.x + surface.bbox.width <= 1
    # Inside the lead-in the readout exists and the value has not moved; inside the sweep it is in between.
    lit = {i.object_id: i for i in records["theta_emphasized"].layout}
    assert lit["rotate"].text == "θ = 0.0 deg"
    rotating = {i.object_id: i for i in records["rotating"].layout}
    assert rotating["rotate"].text.startswith("θ = ") and rotating["rotate"].text not in ("θ = 0.0 deg", "θ = 90.0 deg")
    final = {i.object_id: i for i in records["smaller"].layout}
    assert final["rotate"].text == "θ = 90.0 deg" and final["frequency"].text == "f = 1.4 cycles/deg"
    assert final["shift_x"].text == "x₀ = 1.2 deg" and final["shift_y"].text == "y₀ = -1.0 deg"
    assert final["size"].text == "σ = 0.6 deg"  # noqa: RUF001
    assert (
        final["size"].bbox.y
        > final["shift_y"].bbox.y
        > final["shift_x"].bbox.y
        > final["frequency"].bbox.y
        > final["rotate"].bbox.y
    )
    # The camera moved on between the first and a later checkpoint. (That the axes group leaves the surface's
    # group once faded is asserted directly by the bridge test on the AxesFade track.)
    first = next(i for i in records["with_axes"].layout if i.object_id == "gabor_surface")
    assert first.bbox != surface.bbox
