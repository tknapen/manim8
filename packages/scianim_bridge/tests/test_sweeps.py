"""Parameter sweeps inside the family environment: re-evaluated curves, staggered marker labels, readouts."""

from __future__ import annotations

import math
from itertools import pairwise

import pytest

manim = pytest.importorskip("manim")

PALETTE = {
    "background": "#FFFFFF",
    "foreground": "#111111",
    "secondary_text": "#555555",
    "muted": "#999999",
    "neutral": "#777777",
    "primary_signal": "#1F5FBF",
    "emphasis": "#C8102E",
    "warning": "#D08000",
    "comparison": "#8B1A1A",
    "primary_signal_soft": "#9FBDE6",
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
    from scianim_bridge.scene import TrackSegment

    with manim.tempconfig({"pixel_width": 960, "pixel_height": 540}):
        config.frame_width = config.frame_height * 16 / 9
        scene = _scene()
        plot = C.function_plot(scene, "plot", params=PLOT)
        sweep = scene.begin_vary(
            plot, "sigma", to=4.0, at_seconds=10, duration_seconds=5, action_id="widen", easing="linear"
        )
        sigma = pretty_symbol("sigma")
        assert sweep.readout is not None and sweep.readout.component.text == f"{sigma} = 1.5"
        assert scene.objects["widen"].kind == "value_readout"
        sweep.apply(0.5)
        assert plot.parameters["sigma"] == pytest.approx(2.75)
        assert sweep.readout.component.text == f"{sigma} = 2.8"
        segment = TrackSegment(sweep, 0.5, 1.0)
        segment.interpolate_mobject(1.0)
        assert plot.parameters["sigma"] == pytest.approx(4.0) and sweep.readout.component.text == f"{sigma} = 4.0"
        # Smooth easing starts and ends at the end values and is monotone in between.
        smooth = scene.begin_vary(plot, "x_0", to=-2.0, at_seconds=20, duration_seconds=2, action_id="shift")
        values = [smooth.value_at(f / 10) for f in range(11)]
        assert values[0] == pytest.approx(2.0) and values[-1] == pytest.approx(-2.0)
        assert all(a >= b for a, b in pairwise(values))


def test_surface_image_orbit_and_reveal_tracks() -> None:
    from manim import config

    from scianim_bridge import components as C

    with manim.tempconfig({"pixel_width": 960, "pixel_height": 540}):
        config.frame_width = config.frame_height * 16 / 9
        scene = _scene()
        surface = C.surface_plot(
            scene,
            "surface",
            params={
                "x_label": "x",
                "y_label": "y",
                "z_label": "g",
                "x_range": [-3, 3],
                "y_range": [-3, 3],
                "z_range": [0, 1],
                "expression": "exp(-((x - x_0)^2 + y^2) / 2)",
                "parameters": {"x_0": 0},
                "resolution": 8,
            },
        )
        assert surface.three_d and surface.kind == "surface_plot"
        mesh = surface.group[1]
        assert len(mesh.submobjects) == 64
        top_before = max(float(face.get_center()[2]) for face in mesh.submobjects)
        peak_before = max(mesh.submobjects, key=lambda face: float(face.get_center()[2])).get_center()
        assert surface.set_parameters(x_0=2.0) == []
        peak_after = max(mesh.submobjects, key=lambda face: float(face.get_center()[2])).get_center()
        assert peak_after[0] > peak_before[0] + 0.3  # the hill moved along x
        assert abs(max(float(face.get_center()[2]) for face in mesh.submobjects) - top_before) < 0.2
        assert (
            any(
                "clipped" in w
                for w in surface.set_parameters(x_0=0.0)
                + C.surface_plot(
                    scene,
                    "tall",
                    params={
                        "x_label": "x",
                        "y_label": "y",
                        "z_label": "g",
                        "x_range": [-1, 1],
                        "y_range": [-1, 1],
                        "z_range": [0, 0.5],
                        "expression": "1.0 + 0 * x * y",
                        "parameters": {},
                        "resolution": 4,
                    },
                ).set_parameters()
            )
            or scene.render_warnings
        )

        image = C.function_image(
            scene,
            "grating",
            params={
                "expression": "cos(2 * pi * f * (x * cos(theta * pi / 180) + y * sin(theta * pi / 180)))",
                "parameters": {"theta": 0, "f": 1},
                "x_range": [-1, 1],
                "y_range": [-1, 1],
                "resolution": 16,
                "colors": "grey",
                "mask": "circle",
            },
        )
        pixels = image.group[0].pixel_array
        assert pixels.shape == (16, 16, 4) and pixels[0, 0, 3] == 0 and pixels[8, 8, 3] == 255
        before = pixels.copy()
        image.set_parameters(theta=90.0)
        assert not (image.group[0].pixel_array == before).all()

        scene.ensure_camera()
        camera = scene.renderer.camera
        orbit = scene.begin_orbit(
            to_theta_degrees=40,
            to_phi_degrees=None,
            at_seconds=0,
            duration_seconds=10,
            action_id="orbit",
            easing="linear",
        )
        orbit.apply(0.5)
        assert math.degrees(camera.get_theta()) == pytest.approx(-5.0, abs=1e-6)
        orbit.apply(1.0)
        assert math.degrees(camera.get_theta()) == pytest.approx(40.0, abs=1e-6)

        label = C.text_caption(scene, "note", params={"text": "note"})
        reveal = scene.begin_reveal(label, duration_seconds=1.0)
        assert label.visible and label.group in scene.mobjects
        reveal.apply(1.0)
        reveal.finish()
        assert label.group.get_family()[1].get_fill_opacity() == pytest.approx(1.0)


def test_lead_in_active_highlight_handover_and_axes_fade() -> None:
    from types import SimpleNamespace

    from manim import config

    from scianim_bridge import components as C
    from scianim_core.animation import Equation

    equation = Equation.model_validate(
        {
            "id": "gabor",
            "typst": "g(x, y) = exp(-(x^2 + y^2) / (2 sigma^2)) cos(theta), quad x' = x cos theta",
            "symbols": {
                "theta": {"meaning": "orientation", "units": "deg"},
                "sigma": {"meaning": "size", "units": "deg"},
            },
        }
    )
    base, accent, secondary = PALETTE["foreground"], PALETTE["emphasis"], PALETTE["secondary_text"]

    def ink(part) -> str:
        return part.get_family()[-1].get_fill_color().to_hex().upper()

    with manim.tempconfig({"pixel_width": 960, "pixel_height": 540}):
        config.frame_width = config.frame_height * 16 / 9
        scene = _scene()
        scene.ctx = SimpleNamespace(equations={"gabor": equation})
        surface = C.surface_plot(
            scene,
            "surface",
            params={
                "x_label": "x",
                "y_label": "y",
                "z_label": "g",
                "x_range": [-3, 3],
                "y_range": [-3, 3],
                "z_range": [-1, 1],
                "expression": "exp(-(x^2 + y^2) / (2 * sigma^2)) * cos(theta * pi / 180 + x)",
                "parameters": {"theta": 0, "sigma": 1.2},
                "resolution": 6,
            },
        )
        label = C.equation_label(
            scene,
            "label",
            style_role="emphasis",
            equation={"id": "gabor", "highlight": ["theta", "sigma"], "highlight_mode": "active"},
            params={"text": "Gabor", "anchor": "top_left"},
        )
        theta, sigma = label.highlights["theta"], label.highlights["sigma"]
        assert len(theta.submobjects) == 2 and len(sigma.submobjects) == 1  # one sub-group per occurrence
        assert ink(theta) == base and ink(sigma) == base  # active mode: the terms wait in the equation's ink
        centres = [occurrence.get_center().copy() for occurrence in theta.submobjects]

        # The axes fade out and leave the surface's group; a later fade brings them back.
        axes = surface.axes
        assert axes is not None and axes in surface.group.submobjects
        away = scene.begin_fade_axes(
            surface, visible=False, at_seconds=2, duration_seconds=1, action_id="away", easing="linear"
        )
        away.apply(0.5)
        assert axes[0][0].get_stroke_opacity() == pytest.approx(0.5)
        away.apply(1.0)
        away.finish()
        assert axes not in surface.group.submobjects
        back = scene.begin_fade_axes(
            surface, visible=True, at_seconds=5, duration_seconds=1, action_id="back", easing="linear"
        )
        assert axes in surface.group.submobjects
        back.apply(1.0)
        assert axes[0][0].get_stroke_opacity() == pytest.approx(1.0)

        # A lead-in: the term takes the colour and pulses while the value holds; then the value moves.
        rotate = scene.begin_vary(
            surface,
            "theta",
            to=90.0,
            at_seconds=10,
            duration_seconds=4,
            action_id="rotate",
            easing="linear",
            emphasize=[label],
            lead_in_seconds=1,
        )
        assert rotate.duration_seconds == 5 and rotate.lead_fraction == pytest.approx(0.2)
        rotate.apply(0.1)  # half a second in: the pulse is past its rise and the term is at its largest
        assert surface.parameters["theta"] == 0 and ink(theta) == accent and ink(sigma) == base
        for occurrence, centre in zip(theta.submobjects, centres, strict=True):
            assert occurrence.get_center() == pytest.approx(centre, abs=1e-3)  # grown about its own centre
        rotate.apply(0.2)
        assert surface.parameters["theta"] == 0
        rotate.apply(0.6)
        assert surface.parameters["theta"] == pytest.approx(45.0)
        rotate.apply(1.0)
        assert surface.parameters["theta"] == pytest.approx(90.0)
        assert rotate.readout is not None and rotate.readout.component.text == "θ = 90.0 deg"

        # The next action hands the colour over: sigma lights up, theta returns to the ink, its readout recedes.
        size = scene.begin_vary(
            surface,
            "sigma",
            to=0.6,
            at_seconds=16,
            duration_seconds=2,
            action_id="size",
            easing="linear",
            emphasize=[label],
            lead_in_seconds=0.5,
        )
        assert len(size.released) == 1
        size.apply(0.0)
        assert ink(theta) == accent and ink(sigma) == base
        size.apply(0.3)
        assert ink(sigma) == accent and ink(theta) == base
        assert size.readout is not None
        assert rotate.readout.color.to_hex().upper() == secondary and size.readout.color.to_hex().upper() == accent


def test_eased_linear_profile_camera_ramps_and_raised_cosine_pulse() -> None:
    from types import SimpleNamespace

    from manim import config

    from scianim_bridge import components as C
    from scianim_bridge.scene import eased_linear, rate_function
    from scianim_core.animation import Equation

    # Ramps of a quarter of the window: at rest at both ends, constant speed in between, symmetric.
    f = eased_linear(0.25)
    assert f(0.0) == 0.0 and f(1.0) == 1.0 and f(0.5) == pytest.approx(0.5)
    assert f(0.01) < 1e-3  # starts from rest, with no kick
    assert f(0.4) - f(0.3) == pytest.approx(f(0.7) - f(0.6))  # the constant part
    assert f(0.4) - f(0.3) > f(0.1) - f(0.0)  # faster than the ramp
    values = [f(i / 50) for i in range(51)]
    assert all(b >= a for a, b in pairwise(values))
    # Ramps of half the window or more leave no constant part: a plain ease, still symmetric.
    g = eased_linear(0.9)
    assert g(0.5) == pytest.approx(0.5) and g(0.25) < 0.25 and g(0.25) == pytest.approx(1 - g(0.75))
    assert rate_function("eased_linear", 26.0, 1.5)(0.5) == pytest.approx(0.5)
    assert rate_function("smooth", 1.0, 1.5)(0.5) == pytest.approx(0.5)

    equation = Equation.model_validate(
        {"id": "e", "typst": "r = exp(theta)", "symbols": {"theta": {"meaning": "angle", "units": "deg"}}}
    )
    with manim.tempconfig({"pixel_width": 960, "pixel_height": 540}):
        config.frame_width = config.frame_height * 16 / 9
        scene = _scene()
        scene.ctx = SimpleNamespace(equations={"e": equation})
        surface = C.surface_plot(
            scene,
            "surface",
            params={
                "x_label": "x",
                "y_label": "y",
                "z_label": "g",
                "x_range": [-1, 1],
                "y_range": [-1, 1],
                "z_range": [-1, 1],
                "expression": "cos(theta * pi / 180 + x)",
                "parameters": {"theta": 0},
                "resolution": 4,
            },
        )
        # The camera ramps: equal steps in the constant part, a smaller one at the start.
        scene.ensure_camera()
        camera = scene.renderer.camera
        start = math.degrees(camera.get_theta())
        orbit = scene.begin_orbit(
            to_theta_degrees=start + 100,
            to_phi_degrees=None,
            at_seconds=0,
            duration_seconds=10,
            action_id="o",
            easing="eased_linear",
        )

        def theta_at(fraction: float) -> float:
            orbit.apply(fraction)
            return math.degrees(camera.get_theta()) - start

        assert theta_at(0.5) == pytest.approx(50.0, abs=1e-6)
        middle = theta_at(0.4) - theta_at(0.3)
        assert middle == pytest.approx(theta_at(0.7) - theta_at(0.6), abs=1e-6)
        assert theta_at(0.1) - theta_at(0.0) < middle and theta_at(1.0) == pytest.approx(100.0, abs=1e-6)

        # The pulse is a raised cosine: almost no growth just after it begins, the full scale at its peak.
        label = C.equation_label(
            scene, "label", style_role="emphasis", equation={"id": "e", "highlight": ["theta"]}, params={"text": "t"}
        )
        glyph = label.highlights["theta"].submobjects[0]
        height = glyph.height
        sweep = scene.begin_vary(
            surface,
            "theta",
            to=90.0,
            at_seconds=0,
            duration_seconds=8,
            action_id="s",
            easing="linear",
            emphasize=[label],
        )
        pulse = sweep.pulse_fraction
        sweep.apply(0.05 * pulse)
        assert glyph.height / height < 1.02
        sweep.apply(0.5 * pulse)
        assert glyph.height / height == pytest.approx(1.3, abs=0.02)
        sweep.apply(1.0 * pulse)
        assert glyph.height / height == pytest.approx(1.0, abs=1e-3)


def test_a_segment_that_ends_on_the_breakpoint_completes_the_track() -> None:
    """(3.8 - 3) / 0.8 is one ulp short of 1 in floating point; the target fraction snaps to 1 so that a fade's
    `finish` runs and the faded axes leave the group instead of lingering, invisible, in the layout box."""
    from scianim_bridge.scene import Track

    scene = _scene()
    track = Track(scene=scene, track_id="t", at_seconds=3.0, duration_seconds=0.8)
    assert (3.8 - 3.0) / 0.8 < 1.0  # the rounding this guards against
    assert track.target_fraction(3.8) == 1.0
    assert track.target_fraction(3.4) == pytest.approx(0.5)
    assert track.target_fraction(2.0) == 0.0


def test_orbit_keeps_the_whole_scene_redrawing_and_segments_step_evenly() -> None:
    from manim import config

    from scianim_bridge import components as C
    from scianim_bridge.scene import TrackSegment

    with manim.tempconfig({"pixel_width": 960, "pixel_height": 540}):
        config.frame_width = config.frame_height * 16 / 9
        scene = _scene()
        surface = C.surface_plot(
            scene,
            "surface",
            params={
                "x_label": "x",
                "y_label": "y",
                "z_label": "g",
                "x_range": [-1, 1],
                "y_range": [-1, 1],
                "z_range": [-1, 1],
                "expression": "x * y",
                "resolution": 4,
            },
        )
        scene.add(surface.group)
        note = C.text_caption(scene, "note", params={"text": "note"})
        scene.add(note.group)
        orbit = scene.begin_orbit(
            to_theta_degrees=40, to_phi_degrees=None, at_seconds=0, duration_seconds=10, action_id="orbit"
        )
        # The orbit's animated mobject is first in draw order, so Manim treats every mobject as moving.
        assert scene.mobjects[0] is orbit.dummy
        moving = scene.get_moving_mobjects(TrackSegment(orbit, 0.0, 0.5, 30))
        assert set(map(id, moving)) >= set(map(id, scene.get_mobject_family_members()))
        # Manim renders frame k of n at alpha k / (n - 0.5); the segment maps that to k / n, so steps are even
        # within a segment and across the breakpoint into the next one.
        seen: list[float] = []
        orbit.apply = lambda fraction: seen.append(fraction)  # type: ignore[method-assign]
        first = TrackSegment(orbit, 0.0, 0.4, 4)
        for k in range(4):
            first.interpolate_mobject(k / 3.5)
        first.interpolate_mobject(1.0)  # the finish, not a rendered frame
        second = TrackSegment(orbit, 0.4, 0.8, 4)
        for k in range(4):
            second.interpolate_mobject(k / 3.5)
        rendered = seen[:4] + seen[5:]
        assert rendered == pytest.approx([0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7])
        assert seen[4] == pytest.approx(0.4)


def test_diverging_fill_is_grey_at_zero_and_coloured_at_the_extremes() -> None:
    from manim import config

    from scianim_bridge import components as C

    with manim.tempconfig({"pixel_width": 960, "pixel_height": 540}):
        config.frame_width = config.frame_height * 16 / 9
        scene = _scene()
        surface = C.surface_plot(
            scene,
            "ridge",
            params={
                "x_label": "x",
                "y_label": "y",
                "z_label": "g",
                "x_range": [-1, 1],
                "y_range": [-1, 1],
                "z_range": [-1, 1],
                "expression": "x",  # a plane from -1 to 1 along x: zero in the middle
                "resolution": 8,
                "fill": "diverging",
            },
        )
        faces = surface.group[1].submobjects

        def ink(face) -> str:
            return face.get_fill_color().to_hex().upper()

        def distance(face, role: str) -> float:
            a, b = face.get_fill_color().to_rgb(), manim.ManimColor(PALETTE[role]).to_rgb()
            return max(abs(x - y) for x, y in zip(a, b, strict=True))

        by_x = sorted(faces, key=lambda f: f.get_center()[0])
        # The extremes (cell centres at x = -0.875 and 0.875) are nearly the two inks; the middle is nearly grey.
        assert distance(by_x[0], "comparison") < 0.1 < distance(by_x[0], "muted")
        assert distance(by_x[-1], "primary_signal") < 0.1 < distance(by_x[-1], "muted")
        middle = sorted(faces, key=lambda f: abs(f.get_center()[0]))[0]
        assert distance(middle, "muted") < 0.15
        # Colour grows with |x|: the distance from the grey never shrinks as the cells move away from zero.
        strengths = [distance(f, "muted") for f in sorted(faces, key=lambda f: abs(f.get_center()[0]))]
        assert all(b >= a - 1e-6 for a, b in pairwise(strengths))
        assert ink(by_x[0]) != ink(by_x[-1])


def test_fade_track_scales_every_member_and_removes_the_group() -> None:
    """The seam for `end_scene` and `fade_object`: ink eases to nothing, then the group leaves the scene."""
    from manim import config

    from scianim_bridge import components as C

    with manim.tempconfig({"pixel_width": 960, "pixel_height": 540}):
        config.frame_width = config.frame_height * 16 / 9
        scene = _scene()
        plot = C.function_plot(scene, "plot", params=PLOT)
        scene.add(plot.group)
        plot.visible = True
        line = plot.group[2][0]["line_graph"]
        before = float(line.get_stroke_opacity())
        track = scene.begin_fade(plot, visible=False, duration_seconds=1.0, remove=True)
        assert track.mobject is plot.group and float(line.get_stroke_opacity()) == pytest.approx(before)
        track.apply(0.5)
        assert 0.0 < float(line.get_stroke_opacity()) < before
        track.apply(1.0)
        assert float(line.get_stroke_opacity()) == pytest.approx(0.0)
        track.finish()
        assert plot.visible is False and plot.group not in scene.mobjects
        back = scene.begin_fade(plot, visible=True, duration_seconds=1.0)
        back.apply(1.0)
        back.finish()
        assert plot.visible is True and plot.group in scene.mobjects
        assert float(line.get_stroke_opacity()) == pytest.approx(before)


def test_camera_hook_fires_on_every_orbit_step() -> None:
    from manim import config

    from scianim_bridge import components as C

    with manim.tempconfig({"pixel_width": 960, "pixel_height": 540}):
        config.frame_width = config.frame_height * 16 / 9
        scene = _scene()
        plot = C.function_plot(scene, "plot", params=PLOT)
        calls: list[int] = []
        plot.on_camera = lambda: calls.append(1)
        scene.ensure_camera()
        orbit = scene.begin_orbit(
            to_theta_degrees=10, to_phi_degrees=None, at_seconds=0, duration_seconds=2, action_id="o"
        )
        orbit.apply(0.5)
        orbit.apply(1.0)
        assert len(calls) >= 2


# --- ADR-034: moves, fades of objects, the sphere, equation transforms, data-bound sweeps -----------------------

FLAT_SURFACE = {
    "x_label": "x",
    "y_label": "y",
    "z_label": "h",
    "x_range": [-3, 3],
    "y_range": [-3, 3],
    "z_range": [-1, 1],
    "expression": "0 * x * y + a",
    "parameters": {"a": 0},
    "resolution": 4,
}


def test_move_track_flat_objects_and_an_anchored_sphere() -> None:
    import numpy as np
    from manim import config

    from scianim_bridge import components as C

    with manim.tempconfig({"pixel_width": 960, "pixel_height": 540}):
        config.frame_width = config.frame_height * 16 / 9
        scene = _scene()
        note = C.text_caption(scene, "note", params={"text": "note", "anchor": "top_left"})
        start = note.group.get_center().copy()
        slide = scene.begin_move(
            note, to_anchor="bottom_right", at_seconds=1, duration_seconds=2, action_id="slide", easing="linear"
        )
        slide.apply(0.5)
        probe = note.group.copy()
        scene.tokens.place(probe, "bottom_right")
        target = probe.get_center()
        assert note.group.get_center() == pytest.approx((start + target) / 2, abs=1e-6)
        slide.apply(1.0)
        assert note.group.get_center() == pytest.approx(target, abs=1e-6)
        x0, y0, x1, y1 = scene.tokens.safe_rect()
        nudge = scene.begin_move(
            note, by=[0.1, -0.05], at_seconds=4, duration_seconds=1, action_id="nudge", easing="linear"
        )
        nudge.apply(1.0)
        assert note.group.get_center() == pytest.approx(
            target + np.array([0.1 * (x1 - x0), -0.05 * (y1 - y0), 0.0]), abs=1e-6
        )
        # A parabola: the fall covers a quarter of the distance in the first half of its window.
        drop_easing = scene.begin_move(
            note, by=[0, -0.1], at_seconds=6, duration_seconds=1, action_id="g", easing="ease_in_quad"
        )
        before = note.group.get_center().copy()
        drop_easing.apply(0.5)
        assert (before - note.group.get_center())[1] == pytest.approx(0.25 * 0.1 * (y1 - y0), abs=1e-6)

        # A sphere lives in the anchor surface's coordinates and moves to a point in them.
        surface = C.surface_plot(scene, "surface", params=FLAT_SURFACE)
        ball = C.sphere(scene, "ball", params={"anchor": "surface", "position": [0, 0, 2], "radius_fraction": 0.04})
        assert ball.three_d and ball.kind == "sphere" and surface.to_world is not None
        axes = surface.group[0]
        assert ball.mesh is not None and len(ball.visible_faces()) < len(ball.faces)  # the back faces are culled
        kept = ball.visible_faces()
        toward_camera = np.asarray(scene.renderer.camera.generate_rotation_matrix())[2]
        assert all(n @ toward_camera > 0 for f, n in zip(ball.faces, ball.normals, strict=True) if f in kept)
        assert all(n @ toward_camera <= 0 for f, n in zip(ball.faces, ball.normals, strict=True) if f not in kept)
        centre = np.mean([f.get_center() for f in ball.faces], axis=0)
        assert centre == pytest.approx(axes.c2p(0, 0, 2), abs=0.05)
        fall = scene.begin_move(
            ball, to_point=[1, -1, 0], at_seconds=3, duration_seconds=2, action_id="fall", easing="linear"
        )
        fall.apply(0.5)
        assert ball.data_point == pytest.approx([0.5, -0.5, 1.0])
        fall.apply(1.0)
        fall.finish()
        centre = np.mean([f.get_center() for f in ball.faces], axis=0)  # every face moved, culled ones included
        assert centre == pytest.approx(axes.c2p(1, -1, 0), abs=0.05)
        # Culling follows the camera, and a fade restores every face's ink.
        scene.ensure_camera()
        orbit = scene.begin_orbit(
            to_theta_degrees=150, to_phi_degrees=None, at_seconds=0, duration_seconds=1, action_id="o"
        )
        orbit.apply(1.0)
        turned = set(map(id, ball.visible_faces()))
        assert turned != set(map(id, kept))
        scene.add(ball.group)
        ball.visible = True
        away = scene.begin_fade_object(
            ball, visible=False, at_seconds=5, duration_seconds=1, action_id="away", easing="linear"
        )
        away.apply(1.0)
        away.finish()
        assert ball.visible is False and ball.group not in scene.mobjects
        back = scene.begin_fade_object(
            ball, visible=True, at_seconds=7, duration_seconds=1, action_id="back", easing="linear"
        )
        back.apply(1.0)
        back.finish()
        assert ball.visible is True and ball.group in scene.mobjects
        full = scene.tokens.t.three_d.surface_opacity
        assert all(float(f.get_fill_opacity()) == pytest.approx(full) for f in ball.visible_faces())
        assert len(ball.visible_faces()) < len(ball.faces)  # a fade does not bring the back faces out
        halfway = scene.begin_fade_object(
            ball, visible=False, at_seconds=9, duration_seconds=1, action_id="half", easing="linear"
        )
        halfway.apply(0.5)
        assert all(float(f.get_fill_opacity()) == pytest.approx(full / 2) for f in ball.visible_faces())
        with pytest.raises(ValueError, match="to_point moves a sphere"):
            scene.begin_move(note, to_point=[0, 0, 0], at_seconds=0, duration_seconds=1, action_id="bad")
        with pytest.raises(ValueError, match="turns with the camera"):
            scene.begin_move(ball, to_anchor="center", at_seconds=0, duration_seconds=1, action_id="bad")


def test_transform_equation_pairs_symbols_by_name_and_the_rest_by_shape() -> None:
    from types import SimpleNamespace

    from manim import config

    from scianim_bridge import components as C
    from scianim_bridge.components.equations import match_equations
    from scianim_core.animation import Equation

    before = Equation.model_validate(
        {"id": "before", "typst": "g = cos(theta) + sin(theta) phi", "symbols": {"theta": {"meaning": "angle"}}}
    )
    after = Equation.model_validate(
        {"id": "after", "typst": "g = cos(theta) sin(theta) + 2 sigma", "symbols": {"theta": {"meaning": "angle"}}}
    )
    accent = PALETTE["emphasis"]

    def ink(part) -> str:
        return part.get_family()[-1].get_fill_color().to_hex().upper()

    with manim.tempconfig({"pixel_width": 960, "pixel_height": 540}):
        config.frame_width = config.frame_height * 16 / 9
        scene = _scene()
        scene.ctx = SimpleNamespace(equations={"before": before, "after": after})
        surface = C.surface_plot(
            scene,
            "surface",
            params={**FLAT_SURFACE, "expression": "0 * x * y * theta * phi", "parameters": {"theta": 0, "phi": 0}},
        )
        label = C.equation_label(
            scene,
            "label",
            style_role="emphasis",
            equation={"id": "before", "highlight": ["theta", "phi"], "highlight_mode": "active"},
            params={"text": "angles", "anchor": "top_left"},
        )
        assert label.equation_id == "before" and label.formula is not None
        old_formula, old_theta = label.formula, label.highlights["theta"]
        new_formula, new_parts = C.equations.typeset_equation(
            scene.tokens, after, ["theta", "phi"], label.base_color, label.highlight_color, label.px_at_1080p, "active"
        )
        match = match_equations(old_formula, label.highlights, new_formula, new_parts, "by_symbol")
        # Both thetas pair by name; phi has no partner in the target and fades out; the "=" and "+" pair by shape.
        assert match.matched_symbols == {"theta": 2}
        assert len(match.pairs) >= 2 + 2
        phi_glyphs = {id(g) for g in label.highlights["phi"].get_family() if len(g.points)}
        assert phi_glyphs <= {id(g) for g in match.vanishing}
        assert match.appearing, "sigma and the new glyphs fade in"
        shapes = match_equations(old_formula, label.highlights, new_formula, new_parts, "by_shape")
        assert shapes.matched_symbols == {}
        assert len(shapes.pairs) >= 2

        # A sweep lights theta; the transform runs while it holds the colour and hands the colour to the new glyphs.
        sweep = scene.begin_vary(
            surface,
            "theta",
            to=90.0,
            at_seconds=1,
            duration_seconds=8,
            action_id="turn",
            easing="linear",
            emphasize=[label],
        )
        sweep.apply(0.5)
        assert ink(old_theta) == accent
        morph = scene.begin_transform(label, to="after", at_seconds=5, duration_seconds=1, action_id="morph")
        assert old_formula not in label.group.submobjects and morph.transition in label.group.submobjects
        assert all(len(m.points) == 0 for m in old_theta.get_family())  # retired glyphs draw nothing
        sweep.apply(0.6)  # the running sweep holds a placeholder: the retired glyphs stay empty
        assert all(len(m.points) == 0 for m in old_theta.get_family())
        morph.apply(0.5)
        morph.apply(1.0)
        morph.finish()
        assert label.formula is morph.new_formula and morph.new_formula in label.group.submobjects
        assert morph.transition not in label.group.submobjects
        assert label.equation_id == "after" and label.text == "angles"
        assert set(label.highlights) == {"theta", "phi"} and len(label.highlights["theta"].submobjects) == 2
        assert len(label.highlights["phi"].submobjects) == 0
        assert ink(label.highlights["theta"]) == accent  # the running sweep now emphasizes the new occurrences
        assert sweep.emphasized[0][0] is label.highlights["theta"]
        sweep.apply(0.9)
        assert ink(label.highlights["theta"]) == accent and surface.parameters["theta"] == pytest.approx(81.0)
        # In fast-forward and frame by frame the object ends in the same state: a fresh typeset of the target.
        fixed = scene.renderer.camera.fixed_in_frame_mobjects
        assert morph.new_formula in fixed and old_formula not in fixed  # retired: out of the fixed set ...
        assert old_formula.family_members_with_points() == []  # ... and empty, so it draws nothing anywhere
        with pytest.raises(KeyError, match="not in the job"):
            scene.begin_transform(label, to="nowhere", at_seconds=7, duration_seconds=1, action_id="bad")
        assert ink(label.highlights["theta"]) == accent


def test_data_bound_plot_recomputes_its_series_from_the_table() -> None:
    from types import SimpleNamespace

    from manim import config

    from scianim_bridge import components as C
    from scianim_bridge.data import DataTable, apply_binding

    rows = tuple({"E": str(i), "r": str(i / 2), "c": "low"} for i in range(6))
    table = DataTable(("E", "r", "c"), rows, "toy.csv")
    binding = {
        "source": "toy",
        "encoding": {"x": "E", "y": "r"},
        "transforms": [
            {"op": "filter", "column": "c", "equals": "low"},
            {"op": "scale", "column": "r", "by": {"parameter": "g", "default": 1}},
            {"op": "smooth", "column": "r", "window": {"parameter": "w", "default": 0}},
        ],
    }
    [series] = apply_binding(table, binding)
    assert series.y == pytest.approx([0, 0.5, 1, 1.5, 2, 2.5])
    [doubled] = apply_binding(table, binding, {"g": 2})
    assert doubled.y == pytest.approx([0, 1, 2, 3, 4, 5])
    [smoothed] = apply_binding(table, binding, {"w": 1.0})
    assert smoothed.y[0] > 0 and smoothed.y[-1] < 2.5 and smoothed.y[2] == pytest.approx(1.0, abs=0.05)
    with manim.tempconfig({"pixel_width": 960, "pixel_height": 540}):
        config.frame_width = config.frame_height * 16 / 9
        scene = _scene()
        scene.ctx = SimpleNamespace(table=lambda source: table, equations={})
        plot = C.scientific_plot(
            scene,
            "plot",
            data=binding,
            params={"x_label": "E", "y_label": "r", "y_range": [0, 4], "show_points": False},
        )
        assert plot.parameters == {"g": 1.0, "w": 0.0}
        axes = plot.group[0]
        curve = plot.group[2]

        def height_at(x: float) -> float:
            line = plot.group[2][0]["line_graph"]
            nearest = min(line.points, key=lambda p: abs(p[0] - axes.c2p(x, 0)[0]))
            return float(axes.p2c(nearest)[1])

        assert height_at(4.0) == pytest.approx(2.0, abs=0.05)
        assert plot.set_parameters(g=1.5) == []
        assert plot.group[2] is not curve and height_at(4.0) == pytest.approx(3.0, abs=0.05)
        warnings = plot.set_parameters(g=2.0)  # 5 * 2 / 2 = 5 leaves the fixed range
        assert any("clipped" in w for w in warnings) and height_at(5.0) == pytest.approx(4.0, abs=0.05)
        with pytest.raises(ValueError, match="give it a y_range"):
            C.scientific_plot(scene, "bare", data=binding, params={"x_label": "E", "y_label": "r"})
