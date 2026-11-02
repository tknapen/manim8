"""Named checkpoints rendered by Manim inside a workspace family environment (Milestone 2 acceptance)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scianim.workspace import rewrite_top_level_keys
from scianim_core import ArtifactManifest

pytestmark = [pytest.mark.integration, pytest.mark.surface]
REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures"


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


def _accent_pixels(png: Path, bbox, accent_hex: str) -> int:
    """Pixels inside a normalized bbox within a short distance of the accent colour."""
    from PIL import Image

    accent = tuple(int(accent_hex[i : i + 2], 16) for i in (1, 3, 5))
    with Image.open(png) as image:
        rgb = image.convert("RGB")
        w, h = rgb.size
        box = (
            int(bbox.x * w),
            int(bbox.y * h),
            int((bbox.x + bbox.width) * w) + 1,
            int((bbox.y + bbox.height) * h) + 1,
        )
        pixels = rgb.crop(box).getdata()
    return sum(1 for p in pixels if max(abs(p[i] - accent[i]) for i in range(3)) < 40)


def test_drop_impact_moves_fades_and_transforms(workspace: Path, scianim) -> None:
    """The fifth example (ADR-034): a sphere anchored to the surface falls (move_object by point) and vanishes
    (fade_object), the free-fall equation becomes the surface model at impact (transform_equation) while a sweep of
    model time keeps t emphasized, a smaller sphere rises and falls back, and the camera orbits: every checkpoint
    exact, the transformed equation shown with t in the accent colour, faded objects absent from the layout."""
    project = workspace / "families" / "computational_neuroscience" / "drop_impact"
    assert scianim("validate", str(project)).returncode == 0
    assert scianim("codegen", str(project)).returncode == 0
    generated = (project / "code" / "scene_drop_impact.py").read_text()
    assert "fall = self.begin_move(drop, to_anchor=None, by=None, to_point=[0.0, 0.0, 0.0]" in generated
    assert "vanish = self.begin_fade_object(drop, ink=0, at_seconds=5.5" in generated
    assert 'impact = self.begin_transform(model, to="splash", at_seconds=5.5, duration_seconds=0.8' in generated
    assert "self.run_until(5.8, [orbit, clock, vanish, impact])" in generated
    assert generated.count("merge = self.begin_fade_object(droplet") == 1
    run = scianim("snapshot", str(project), "--all", "--no-cache")
    assert run.returncode == 0, run.stdout + run.stderr
    manifest = manifests(project, "working")[-1]
    records = {c.snapshot_id: c for c in manifest.result.checkpoints}
    assert list(records) == ["still_water", "falling", "impact_done", "jet", "rings", "calm"]
    for record in records.values():
        assert record.fidelity == "exact" and record.warnings == [], (record.snapshot_id, record.warnings)
    still = {i.object_id: i for i in records["still_water"].layout}
    assert set(still) == {"water", "drop", "model", "caption"}
    assert still["drop"].kind == "sphere" and still["model"].text == "z(t) = z_0 - 1/2 g t^2"
    falling = {i.object_id: i for i in records["falling"].layout}
    assert falling["drop"].bbox.y > still["drop"].bbox.y + 0.05  # the drop has come down
    assert falling["clock"].text.startswith("t = -0.")
    done = {i.object_id: i for i in records["impact_done"].layout}
    assert "drop" not in done, "the faded drop stays registered but leaves the layout report"
    assert done["model"].text.startswith("& h(x, y, t) = -A Theta(t)")
    assert done["model"].bbox.height > still["model"].bbox.height  # two lines now
    assert done["clock"].text == "t = 0.09 s"
    # The transformed equation shows t in the accent colour: accent pixels inside the block's box, and more of
    # them than the one-line free-fall equation had with its single t.
    accent = manifest.job.resolved_style.tokens.palette["emphasis"]
    lit_after = _accent_pixels(project / records["impact_done"].png, done["model"].bbox, accent)
    lit_before = _accent_pixels(project / records["falling"].png, falling["model"].bbox, accent)
    assert lit_after > lit_before > 0, (lit_before, lit_after)
    jet = {i.object_id: i for i in records["jet"].layout}
    assert jet["droplet"].kind == "sphere" and jet["droplet"].bbox.y < jet["water"].bbox.y + 0.05
    rings = {i.object_id: i for i in records["rings"].layout}
    assert "droplet" not in rings and "drop" not in rings
    calm = {i.object_id: i for i in records["calm"].layout}
    assert calm["clock"].text == "t = 1.20 s"
    assert records["still_water"].sha256 != records["impact_done"].sha256 != records["rings"].sha256
    # The data-bound sweep of the other example: a checkpoint inside the gain sweep (4 to 5.3 s; at 4.6 s the eased
    # value is about 1.20, clear of both ends at the readout's one decimal) shows the readout and a curve
    # recomputed from the table (its series scaled by g), with the axes fixed.
    dn = workspace / "families" / "computational_neuroscience" / "divisive_normalization"
    example = (
        REPO / "examples" / "families" / "computational_neuroscience" / "divisive_normalization" / "storyboard.yaml"
    )
    text = example.read_text()
    assert "- {op: scale, column: response_r, by: {parameter: g, default: 1}}" in text
    previous = (dn / "storyboard.yaml").read_text()  # an earlier test may have put the gallery storyboard here
    (dn / "storyboard.yaml").write_text(
        text.replace(
            "      - id: excitation_visible\n",
            '      - id: gain_rising\n        at_seconds: 4.6\n        description: "inside the gain sweep"\n'
            "      - id: excitation_visible\n",
            1,
        )
    )
    rewrite_top_level_keys(dn / "storyboard.yaml", {"project_id": "divisive_normalization"})  # as workspace init does
    try:
        assert scianim("codegen", str(dn)).returncode == 0
        gain = scianim("snapshot", str(dn), "--no-cache", "--id", "excitation_visible", "--id", "gain_rising")
        assert gain.returncode == 0, gain.stdout + gain.stderr
        before, inside = manifests(dn, "working")[-1].result.checkpoints
        assert before.snapshot_id == "excitation_visible" and inside.snapshot_id == "gain_rising"
        assert {i.object_id for i in before.layout} == {"drive_caption", "drive_note", "drive_curve"}
        layout = {i.object_id: i for i in inside.layout}
        assert layout["gain"].kind == "value_readout" and layout["gain"].text.startswith("gain g = 1.")
        assert layout["gain"].text not in ("gain g = 1.0", "gain g = 1.5")
        assert layout["drive_curve"].bbox == {i.object_id: i for i in before.layout}["drive_curve"].bbox
        assert before.sha256 != inside.sha256 and inside.warnings == []
    finally:
        (dn / "storyboard.yaml").write_text(previous)


def test_style_stills_render_a_candidate_beside_the_pinned_sheet(workspace: Path, scianim) -> None:
    project = workspace / "families" / "computational_neuroscience" / "orientation_tuning"
    assert scianim("codegen", str(project)).returncode == 0
    candidate = workspace / "candidate" / "style.yaml"
    candidate.parent.mkdir(exist_ok=True)
    candidate.write_text(
        'schema_version: "1.0"\nname: tomas_scientific\nversion: "0.6.0"\ninherits: tomas_scientific@0.5.0\n'
        'palette:\n  emphasis: "#D9772A"\n'
    )
    result = scianim(
        "style",
        "stills",
        str(project),
        "--candidate",
        str(candidate),
        "--snapshot",
        "circuit_shown",
        "--profile",
        "storyboard",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "palette.emphasis" in result.stdout
    sheets = sorted((project / "renders" / "working").glob("stills_*/stills.html"))
    assert sheets and sheets[-1].read_text().count("<img") == 2
    published = scianim(
        "style", "publish", str(candidate), "tomas_scientific@0.6.0", "--styles-dir", str(workspace / "styles")
    )
    assert published.returncode == 0 and (workspace / "styles" / "tomas_scientific" / "0.6.0" / "style.yaml").exists()
    again = scianim(
        "style", "publish", str(candidate), "tomas_scientific@0.6.0", "--styles-dir", str(workspace / "styles")
    )
    assert again.returncode != 0


def test_gabor_filter_renders_the_same_under_the_raster_renderer(workspace: Path, scianim) -> None:
    """ADR-032: the raster path draws the same clip, its projected boxes within two percent of the frame of the
    Cairo path's, the floor frame hidden where the surface covers it, and the picture costs a fraction."""
    project = workspace / "families" / "computational_neuroscience" / "gabor_filter"
    assert scianim("codegen", str(project)).returncode == 0
    boxes: dict[str, dict[str, object]] = {}
    elapsed: dict[str, float] = {}
    for renderer in ("cairo", "raster"):
        run = scianim(
            "snapshot",
            str(project),
            "--no-cache",
            "--id",
            "with_axes",
            "--id",
            "rotating",
            "--surface-renderer",
            renderer,
        )
        assert run.returncode == 0, run.stdout + run.stderr
        manifest = manifests(project, "working")[-1]
        assert manifest.result.status == "succeeded" and manifest.job.manim.surface_renderer == renderer
        elapsed[renderer] = manifest.result.elapsed_seconds
        for record in manifest.result.checkpoints:
            assert record.fidelity == "exact" and record.warnings == []
            boxes[f"{renderer}:{record.snapshot_id}"] = next(
                i for i in record.layout if i.object_id == "gabor_surface"
            ).bbox
    for snapshot_id in ("with_axes", "rotating"):
        a, b = boxes[f"cairo:{snapshot_id}"], boxes[f"raster:{snapshot_id}"]
        for name in ("x", "y", "x2", "y2"):
            assert abs(getattr(a, name) - getattr(b, name)) < 0.02, (snapshot_id, name, a, b)
    # Two renderers, two cache keys; the raster job is the quicker by far.
    cairo_job, raster_job = manifests(project, "working")[-2:]
    assert cairo_job.job.cache_key != raster_job.job.cache_key
    assert elapsed["raster"] < elapsed["cairo"]
