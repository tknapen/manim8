"""Parameter sweeps inside the family environment: re-evaluated curves, staggered marker labels, readouts."""

from __future__ import annotations

import math
from itertools import pairwise

import pytest

manim = pytest.importorskip("manim")

PALETTE = {
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
}
TYPEFACE = {"font_family": "DejaVu Sans", "font_fallbacks": [], "size_px_at_1080p": 32, "weight": "regular"}


def _style():
    from scianim_core.style import ResolvedStyle, StyleTokens

    tokens = StyleTokens.model_validate(
        {
            "palette": PALETTE,
            "typography": {
                "title": TYPEFACE,
                "body": TYPEFACE,
                "annotation": TYPEFACE,
                "axis_label": TYPEFACE,
                "tick_label": TYPEFACE,
                "caption": TYPEFACE,
                "equation": {"engine": "typst", "size_px_at_1080p": 46, "label_size_px_at_1080p": 38},
                "minimum_text_px_at_1080p": 26,
            },
            "layout": {"safe_margin_fraction": 0.05, "baseline_grid_px_at_1080p": 16, "panel_gap_px_at_1080p": 40},
            "geometry": {
                "axis_stroke_px_at_1080p": 2.0,
                "curve_stroke_px_at_1080p": 3.5,
                "annotation_stroke_px_at_1080p": 2.0,
                "marker_radius_px_at_1080p": 5,
                "tick_length_px_at_1080p": 8,
            },
            "charts": {"legend_position": "upper_right", "spines": ["left", "bottom"], "spine_offset_px_at_1080p": 6},
            "motion": {"transition_seconds": 0.5, "reveal_seconds": 0.5, "easing": "smooth"},
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


def _scene():
    from scianim_bridge.scene import SnapshotScene
    from scianim_bridge.tokens import Tokens

    scene = SnapshotScene()
    scene._tokens = Tokens(_style())
    return scene


PLOT = {
    "x_label": "x",
    "y_label": "g(x)",
    "x_range": [-10, 10],
    "y_range": [0, 1.2],
    "parameters": {"x_0": 2, "sigma": 1.5},
    "series": [{"label": "g", "expression": "exp(-((x - x_0)^2) / (2 * sigma^2))"}],
    "markers": [{"x": "x_0", "label": "x0"}, {"x": "x_0 + sigma", "label": "x0 + sigma"}],
    "anchor": "center_left",
}


def test_set_parameters_moves_the_curve_and_markers_in_the_axes_frame() -> None:
    from manim import config

    from scianim_bridge import components as C

    with manim.tempconfig({"pixel_width": 960, "pixel_height": 540}):
        config.frame_width = config.frame_height * 16 / 9
        scene = _scene()
        plot = C.function_plot(scene, "plot", params=PLOT)
        axes = plot.group[0]
        line = plot.group[2][0]["line_graph"]

        def height_at(x: float) -> float:
            points = line.points
            nearest = min(points, key=lambda p: abs(p[0] - axes.c2p(x, 0)[0]))
            return float(axes.p2c(nearest)[1])

        assert height_at(2.0) == pytest.approx(1.0, abs=0.02)
        assert height_at(5.0) == pytest.approx(math.exp(-9 / (2 * 1.5**2)), abs=0.02)
        marker_line = plot.group[3]
        assert axes.p2c(marker_line.get_center())[0] == pytest.approx(2.0, abs=0.05)
        warnings = plot.set_parameters(sigma=4.0)
        assert warnings == []
        assert height_at(2.0) == pytest.approx(1.0, abs=0.02)
        assert height_at(5.0) == pytest.approx(math.exp(-9 / (2 * 4.0**2)), abs=0.02)
        sigma_line = plot.group[5]
        assert axes.p2c(sigma_line.get_center())[0] == pytest.approx(6.0, abs=0.05)
        # Labels: apart at sigma = 4, staggered when the markers come close.
        x0_label, sigma_label = plot.group[4], plot.group[6]
        assert abs(x0_label.get_bottom()[1] - sigma_label.get_bottom()[1]) < 1e-6
        plot.set_parameters(sigma=0.3)
        assert sigma_label.get_bottom()[1] > x0_label.get_bottom()[1] + 0.1
        # A series that leaves the fixed range is clipped, and says so once.
        tall = C.function_plot(
            scene,
            "tall",
            params={
                **PLOT,
                "markers": [],
                "parameters": {"gain": 1},
                "series": [{"label": "g", "expression": "gain * exp(-(x^2) / 8)"}],
            },
        )
        assert tall.set_parameters(gain=1.1) == []
        assert any("clipped" in w for w in tall.set_parameters(gain=2.0))
        assert tall.set_parameters(gain=3.0) == []


def test_sweep_applies_eased_values_pulse_and_readout() -> None:
    from manim import config

    from scianim_bridge import components as C
    from scianim_bridge.components.base import pretty_symbol
    from scianim_bridge.scene import ParameterSweep

    with manim.tempconfig({"pixel_width": 960, "pixel_height": 540}):
        config.frame_width = config.frame_height * 16 / 9
        scene = _scene()
        plot = C.function_plot(scene, "plot", params=PLOT)
        sweep = scene.begin_vary(
            plot, "sigma", to=4.0, at_seconds=10, duration_seconds=5, action_id="widen", easing="linear"
        )
        sigma = pretty_symbol("sigma")
        assert sweep.readout is not None and sweep.readout.text == f"{sigma} = 1.5"
        assert scene.objects["widen"].kind == "value_readout"
        sweep.apply(0.5)
        assert plot.parameters["sigma"] == pytest.approx(2.75)
        assert sweep.readout.text == f"{sigma} = 2.8"
        segment = ParameterSweep(sweep, 0.5, 1.0)
        segment.interpolate_mobject(1.0)
        assert plot.parameters["sigma"] == pytest.approx(4.0) and sweep.readout.text == f"{sigma} = 4.0"
        # Smooth easing starts and ends at the end values and is monotone in between.
        smooth = scene.begin_vary(plot, "x_0", to=-2.0, at_seconds=20, duration_seconds=2, action_id="shift")
        values = [smooth.value_at(f / 10) for f in range(11)]
        assert values[0] == pytest.approx(2.0) and values[-1] == pytest.approx(-2.0)
        assert all(a >= b for a, b in pairwise(values))
