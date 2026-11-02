"""Fades to a level of ink and the `emphasize` cues: a box around a place, travelling from another, and a pulse of
named symbols (ADR-041)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

manim = pytest.importorskip("manim")

from test_sweeps import PLOT, _scene  # noqa: E402  (the shared minimal style of the bridge tests)

GAUSS = {
    "id": "gauss",
    "typst": "g(x) = exp(-(x - x_0)^2 / (2 sigma^2))",
    "symbols": {"sigma": {"meaning": "width"}, "x_0": {"meaning": "centre"}},
}


def _setup():
    from manim import config

    from scianim_bridge import components as C
    from scianim_core.animation import Equation

    config.frame_width = config.frame_height * 16 / 9
    scene = _scene()
    scene.ensure_camera()
    scene.ctx = SimpleNamespace(equations={"gauss": Equation.model_validate(GAUSS)})
    label = C.equation_label(
        scene,
        "label",
        equation={"id": "gauss", "highlight": ["sigma", "x_0"]},
        params={"text": "g", "anchor": "top_left"},
    )
    plot = C.function_plot(scene, "plot", params=PLOT)
    note = C.text_caption(scene, "note", params={"text": "a note", "anchor": "bottom_right"})
    for component in (label, plot, note):
        scene.add(component.group)
        component.visible = True
    return scene, label, plot, note


def _fill(component) -> list[float]:
    return [float(m.get_fill_opacity()) for m in component.group.family_members_with_points()]


def test_a_fade_dims_to_a_level_restores_and_fades_out_from_where_it_is() -> None:
    with manim.tempconfig({"pixel_width": 480, "pixel_height": 270}):
        scene, _, _, note = _setup()
        full = _fill(note)
        dim = scene.begin_fade_object(note, ink=0.3, at_seconds=0, duration_seconds=1, action_id="dim")
        dim.apply(1.0)
        dim.finish()
        assert _fill(note) == pytest.approx([0.3 * f for f in full])
        assert note.visible and note.group in scene.mobjects and note.ink_factor == pytest.approx(0.3)
        back = scene.begin_fade_object(note, visible=True, at_seconds=1, duration_seconds=1, action_id="back")
        assert _fill(note) == pytest.approx([0.3 * f for f in full])  # it starts where the dim left it
        back.apply(1.0)
        back.finish()
        assert _fill(note) == pytest.approx(full)
        dim = scene.begin_fade_object(note, ink=0.5, at_seconds=2, duration_seconds=1, action_id="dim2")
        dim.apply(1.0)
        dim.finish()
        out = scene.begin_fade(note, visible=False, duration_seconds=1)  # the end of a scene
        assert out.start_factor == pytest.approx(0.5)
        out.apply(1.0)
        out.finish()
        assert _fill(note) == pytest.approx([0.0 for _ in full]) and not note.visible


def _bounds(mobject) -> tuple[float, float, float, float]:
    from manim import DOWN, LEFT, RIGHT, UP

    (x0, y0, _), (x1, y1, _) = mobject.get_corner(DOWN + LEFT), mobject.get_corner(UP + RIGHT)
    return x0, y0, x1, y1


def _inside(inner, outer) -> bool:
    return outer[0] < inner[0] and outer[1] < inner[1] and inner[2] < outer[2] and inner[3] < outer[3]


def test_a_box_surrounds_its_target_and_travels_from_a_symbol() -> None:
    with manim.tempconfig({"pixel_width": 480, "pixel_height": 270}):
        scene, label, plot, _ = _setup()
        cue = scene.begin_emphasize(plot, at_seconds=0, duration_seconds=2, action_id="look")
        assert cue.box in scene.mobjects
        assert float(cue.box.get_stroke_opacity()) == pytest.approx(0.0)  # it appears from nothing
        cue.apply(0.5)
        assert float(cue.box.get_stroke_opacity()) == pytest.approx(1.0)
        assert _inside(_bounds(plot.group), _bounds(cue.box))
        cue.apply(1.0)
        cue.finish()
        assert cue.box not in scene.mobjects

        trip = scene.begin_emphasize(
            plot, from_target=label, from_symbols=["sigma"], at_seconds=0, duration_seconds=2, action_id="trip"
        )
        sigma = label.highlights["sigma"]
        first = sigma.submobjects[0] if sigma.submobjects else sigma
        trip.apply(trip.edge)  # fully inked, about to leave
        assert _inside(_bounds(first), _bounds(trip.box))
        assert not _inside(_bounds(plot.group), _bounds(trip.box))
        trip.apply(trip.edge + trip.travel)  # arrived
        assert _inside(_bounds(plot.group), _bounds(trip.box))


def test_a_pulse_grows_symbols_and_leaves_them_as_they_were() -> None:
    import numpy as np

    with manim.tempconfig({"pixel_width": 480, "pixel_height": 270}):
        scene, label, _, _ = _setup()
        sigma = label.highlights["sigma"]
        before = [m.points.copy() for m in sigma.family_members_with_points()]
        width = sigma.width
        pulse = scene.begin_emphasize(
            label, symbols=["sigma"], cue="pulse", at_seconds=0, duration_seconds=1, action_id="pulse"
        )
        assert pulse.box is None
        pulse.apply(0.5)
        assert sigma.width == pytest.approx(width * scene.tokens.t.motion.emphasis_scale, rel=1e-6)
        pulse.apply(1.0)
        pulse.finish()
        after = [m.points for m in sigma.family_members_with_points()]
        assert all(np.array_equal(a, b) for a, b in zip(before, after, strict=True))


def test_cues_refuse_places_that_show_no_such_symbol() -> None:
    with manim.tempconfig({"pixel_width": 480, "pixel_height": 270}):
        scene, label, plot, _ = _setup()
        with pytest.raises(ValueError, match="no symbols to point at"):
            scene.begin_emphasize(plot, symbols=["sigma"], at_seconds=0, duration_seconds=1, action_id="bad")
        with pytest.raises(ValueError, match="shows no highlighted"):
            scene.begin_emphasize(label, symbols=["mu"], at_seconds=0, duration_seconds=1, action_id="bad")
        with pytest.raises(ValueError, match="a pulse grows named symbols"):
            scene.begin_emphasize(plot, cue="pulse", at_seconds=0, duration_seconds=1, action_id="bad")
