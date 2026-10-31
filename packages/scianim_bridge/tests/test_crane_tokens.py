"""The tokens of `default@0.5.0`: one soft light on surfaces, a quiet mesh, round line ends, rimmed dots."""

from __future__ import annotations

import numpy as np
import pytest

manim = pytest.importorskip("manim")

from test_sweeps import _scene, _style  # noqa: E402  (the shared minimal style of the bridge tests)

SURFACE = {
    "x_label": "x",
    "y_label": "y",
    "z_label": "g",
    "x_range": [-1, 1],
    "y_range": [-1, 1],
    "z_range": [-1, 1],
    "expression": "0.8 * x",  # a plane tilted about y: one slope faces the light, the other does not
    "parameters": {},
    "resolution": 4,
    "fill": "by_sign",
}


def _scene_with(**three_d):
    from scianim_bridge.tokens import Tokens

    scene = _scene()
    style = _style()
    tokens = style.tokens.model_copy(update={"three_d": style.tokens.three_d.model_copy(update=three_d)})
    scene._tokens = Tokens(style.model_copy(update={"tokens": tokens}))
    return scene


def _fill_rgb(face) -> np.ndarray:
    return np.array(face.get_fill_color().to_rgb())


def test_shading_models_a_surface_against_the_light() -> None:
    from manim import config

    from scianim_bridge import components as C

    with manim.tempconfig({"pixel_width": 960, "pixel_height": 540}):
        config.frame_width = config.frame_height * 16 / 9
        flat = C.surface_plot(_scene_with(shading_strength=0.0), "flat", params=SURFACE)
        lit = C.surface_plot(
            _scene_with(shading_strength=0.6, light_azimuth_degrees=-60, light_elevation_degrees=50),
            "lit",
            params=SURFACE,
        )
        flat_faces, lit_faces = flat.group[1].submobjects, lit.group[1].submobjects
        assert len(flat_faces) == len(lit_faces) == 16
        # Unlit: every cell of one sign carries the same wash, and Manim's own lamp stays on.
        positive = [f for f in flat_faces if f.u1 >= 0]
        assert all(np.allclose(_fill_rgb(f), _fill_rgb(positive[0])) for f in positive)
        assert all(f.shade_in_3d for f in flat_faces)
        # Lit: the sheet's lamp replaces Manim's, and the plane's cells (all one normal) differ from the flat wash
        # by a shade that is the same for every cell of one sign.
        assert not any(f.shade_in_3d for f in lit_faces)
        shades = {tuple(np.round(_fill_rgb(f), 4)) for f in lit_faces if f.u1 >= 0}
        assert len(shades) == 1 and not np.allclose(_fill_rgb(lit_faces[0]), _fill_rgb(flat_faces[0]))
        # Turning the light to the other side changes the shade: the normal is read against the light.
        other = C.surface_plot(
            _scene_with(shading_strength=0.6, light_azimuth_degrees=120, light_elevation_degrees=50),
            "other",
            params=SURFACE,
        )
        assert not np.allclose(_fill_rgb(other.group[1].submobjects[-1]), _fill_rgb(lit_faces[-1]))
        # A rebuild keeps the lamp off.
        lit.set_parameters()
        assert not any(f.shade_in_3d for f in lit.group[1].submobjects)


def test_mesh_role_line_cap_and_marker_rim_follow_the_tokens() -> None:
    from manim import CapStyleType, LineJointType, config

    from scianim_bridge import components as C
    from scianim_bridge.tokens import Tokens

    plot = {
        "x_label": "x",
        "y_label": "y",
        "x_range": [0, 1],
        "y_range": [0, 1],
        "parameters": {},
        "series": [{"label": "f", "expression": "x"}],
        "markers": [{"x": "0.5", "label": "half"}],
        "anchor": "center",
    }
    with manim.tempconfig({"pixel_width": 960, "pixel_height": 540}):
        config.frame_width = config.frame_height * 16 / 9
        square = _scene()
        assert (
            square.tokens.line_kwargs() == {}
            and square.tokens.dot_kwargs(square.tokens.color("foreground"))["stroke_width"] == 0
        )
        rounded = _scene()
        style = _style()
        geometry = style.tokens.geometry.model_copy(update={"line_cap": "round", "marker_rim_px_at_1080p": 2.0})
        three_d = style.tokens.three_d.model_copy(update={"mesh_role": "muted"})
        rounded._tokens = Tokens(
            style.model_copy(
                update={"tokens": style.tokens.model_copy(update={"geometry": geometry, "three_d": three_d})}
            )
        )
        assert rounded.tokens.line_kwargs() == {"cap_style": CapStyleType.ROUND, "joint_type": LineJointType.ROUND}
        rim = rounded.tokens.dot_kwargs(rounded.tokens.color("foreground"))
        assert rim["stroke_width"] == pytest.approx(rounded.tokens.stroke_width(2.0)) and rim["fill_opacity"] == 1.0
        curve = C.function_plot(rounded, "curve", params=plot)
        line = curve.group[2][0]["line_graph"]
        assert line.cap_style == CapStyleType.ROUND and line.joint_type == LineJointType.ROUND
        spine = curve.group[1][0][0]
        assert spine.cap_style == CapStyleType.ROUND
        surface = C.surface_plot(rounded, "surface", params=SURFACE)
        face = surface.group[1].submobjects[0]
        assert np.allclose(np.array(face.get_stroke_color().to_rgb()), np.array(rounded.tokens.color("muted").to_rgb()))
