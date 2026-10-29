"""Layout geometry checks that need Manim (run inside the family environment)."""

from __future__ import annotations

import pytest

manim = pytest.importorskip("manim")


def test_normalized_bbox_of_centered_square() -> None:
    from manim import Square, config

    from scianim_bridge.layout import normalized_bbox

    with manim.tempconfig({"pixel_width": 1920, "pixel_height": 1080}):
        config.frame_width = config.frame_height * 16 / 9
        square = Square(side_length=2.0)  # centered, 2 units of an 8-unit-tall frame
        bbox = normalized_bbox(square)
        assert bbox.height == pytest.approx(0.25)
        assert bbox.y == pytest.approx(0.375)
        assert bbox.x + bbox.width / 2 == pytest.approx(0.5)


def test_tokens_convert_pixels_to_units() -> None:
    from manim import config

    from scianim_bridge.tokens import Tokens
    from scianim_core.style import ResolvedStyle, StyleTokens

    typeface = {"font_family": "DejaVu Sans", "font_fallbacks": [], "size_px_at_1080p": 32, "weight": "regular"}
    tokens = StyleTokens.model_validate(
        {
            "palette": {
                role: "#111111"
                for role in (
                    "background",
                    "foreground",
                    "secondary_text",
                    "muted",
                    "neutral",
                    "primary_signal",
                    "emphasis",
                    "warning",
                    "comparison",
                )
            },
            "typography": {
                "title": typeface,
                "body": typeface,
                "annotation": typeface,
                "axis_label": typeface,
                "tick_label": typeface,
                "caption": typeface,
                "equation": {"engine": "typst", "size_px_at_1080p": 46, "label_size_px_at_1080p": 38},
                "minimum_text_px_at_1080p": 26,
            },
            "layout": {"safe_margin_fraction": 0.05, "baseline_grid_px_at_1080p": 16, "panel_gap_px_at_1080p": 40},
            "geometry": {
                "axis_stroke_px_at_1080p": 2.0,
                "curve_stroke_px_at_1080p": 3.5,
                "annotation_stroke_px_at_1080p": 2.5,
            },
            "charts": {},
            "motion": {"transition_seconds": 0.65, "reveal_seconds": 0.85},
            "accessibility": {},
        }
    )
    style = ResolvedStyle(
        theme="default",
        theme_version="0.1.0",
        layers=["theme:default@0.1.0"],
        tokens=tokens,
        provenance={},
        hash="sha256:" + "0" * 64,
    )
    with manim.tempconfig({"pixel_width": 960, "pixel_height": 540}):
        config.frame_width = config.frame_height * 16 / 9
        t = Tokens(style)
        assert t.units(1080) == pytest.approx(config.frame_height)
        assert t.output_px(1080) == pytest.approx(540)
        assert t.stroke_width(1.35) == pytest.approx(1.0, rel=1e-3)
        assert t.color("background").to_hex().lower() == "#111111"
        with pytest.raises(KeyError, match="not in the palette"):
            t.color("nonexistent_role")


def _style(**charts):
    from scianim_core.style import ResolvedStyle, StyleTokens

    typeface = {"font_family": "DejaVu Sans", "font_fallbacks": [], "size_px_at_1080p": 32, "weight": "regular"}
    roles = (
        "background",
        "foreground",
        "secondary_text",
        "muted",
        "neutral",
        "primary_signal",
        "emphasis",
        "warning",
        "comparison",
    )
    tokens = StyleTokens.model_validate(
        {
            "palette": dict.fromkeys(roles, "#111111"),
            "typography": {
                **{role: typeface for role in ("title", "body", "annotation", "axis_label", "tick_label", "caption")},
                "equation": {"engine": "typst", "size_px_at_1080p": 46, "label_size_px_at_1080p": 38},
                "minimum_text_px_at_1080p": 26,
            },
            "layout": {"safe_margin_fraction": 0.05, "baseline_grid_px_at_1080p": 16, "panel_gap_px_at_1080p": 40},
            "geometry": {
                "axis_stroke_px_at_1080p": 2.0,
                "curve_stroke_px_at_1080p": 3.5,
                "annotation_stroke_px_at_1080p": 2.5,
            },
            "charts": charts,
            "motion": {"transition_seconds": 0.65, "reveal_seconds": 0.85},
            "accessibility": {},
        }
    )
    return ResolvedStyle(
        theme="t",
        theme_version="0.1.0",
        layers=["theme:t@0.1.0"],
        tokens=tokens,
        provenance={},
        hash="sha256:" + "0" * 64,
    )


@pytest.mark.parametrize(
    ("spines", "expected_lines"),
    [
        (["left", "bottom"], 2 + 5 + 5),  # despined default: two spines plus one tick per label
        (["left", "bottom", "top", "right"], 4 + 5 + 5),
        ([], 0 + 5 + 5),
    ],
)
def test_axes_draw_only_the_listed_spines(spines, expected_lines) -> None:
    from manim import Line, config

    from scianim_bridge.components.plots import _axes_with_labels
    from scianim_bridge.tokens import Tokens

    with manim.tempconfig({"pixel_width": 960, "pixel_height": 540}):
        config.frame_width = config.frame_height * 16 / 9
        tokens = Tokens(_style(spines=spines, spine_offset_px_at_1080p=10))
        _, labels = _axes_with_labels(tokens, (0, 4, 1), (0, 2, 0.5), 6.0, 3.0, "x", "y")
        frame = labels.submobjects[0]
        assert sum(isinstance(m, Line) for m in frame.submobjects) == expected_lines


def test_smallest_text_px_mixes_roles_and_explicit_sizes() -> None:
    from manim import config

    from scianim_bridge.tokens import Tokens

    with manim.tempconfig({"pixel_width": 1920, "pixel_height": 1080}):
        config.frame_width = config.frame_height * 16 / 9
        tokens = Tokens(_style())
        assert tokens.smallest_text_px("tick_label", 46.0) == pytest.approx(32)
        assert tokens.smallest_text_px("body", 28.0) == pytest.approx(28)


def test_projected_bbox_measures_ink_only() -> None:
    """Invisible helper geometry (a surface's axes, stroke and fill at zero opacity) does not widen the box."""
    from manim import Square, VGroup, config

    from scianim_bridge.layout import projected_bbox
    from scianim_bridge.scene import SnapshotScene

    with manim.tempconfig({"pixel_width": 960, "pixel_height": 540}):
        config.frame_width = config.frame_height * 16 / 9
        scene = SnapshotScene()
        visible = Square(side_length=2.0, stroke_opacity=1.0, fill_opacity=0.0)
        helper = Square(side_length=6.0, stroke_opacity=0.0, fill_opacity=0.0)
        bbox = projected_bbox(scene.renderer.camera, VGroup(helper, visible))
        assert bbox.width == pytest.approx(2.0 / config.frame_width, abs=1e-6)
        assert bbox.height == pytest.approx(2.0 / config.frame_height, abs=1e-6)
        alone = projected_bbox(scene.renderer.camera, VGroup(helper))
        assert alone.width == pytest.approx(6.0 / config.frame_width, abs=1e-6)  # nothing visible: fall back to all


def test_surface_lift_raises_the_box_without_moving_it_sideways() -> None:
    from manim import config

    from scianim_bridge import components as C

    sys_path_helper = __import__("sys").path
    sys_path_helper.insert(0, str(__import__("pathlib").Path(__file__).parent))
    from test_sweeps import _scene

    params = {
        "x_label": "x",
        "y_label": "y",
        "z_label": "g",
        "x_range": [-1, 1],
        "y_range": [-1, 1],
        "z_range": [-1, 1],
        "expression": "x * y",
        "resolution": 4,
    }
    with manim.tempconfig({"pixel_width": 960, "pixel_height": 540}):
        config.frame_width = config.frame_height * 16 / 9
        scene = _scene()
        flat = C.surface_plot(scene, "flat", params=params)
        lifted = C.surface_plot(scene, "lifted", params={**params, "lift_fraction": 0.1})
        a, b = flat.group[1].get_center(), lifted.group[1].get_center()
        assert b[2] > a[2] + 0.5 and abs(b[0] - a[0]) < 1e-6 and abs(b[1] - a[1]) < 1e-6
