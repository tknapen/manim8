"""A play leaves the same state, bit for bit, whether Manim draws it frame by frame or applies it once (ADR-039).

Manim names a play's segment by a hash of the scene's state at its start. If a drawn play and a fast-forwarded
or cached one left different bits, every later play of a re-render, and of the parts of a parallel render,
would miss the segment store (ADR-033). The check here is Manim's own hash of the state after the play, taken
as at the start of a play that continues the same tracks, so it reaches everything they reach (their components
and the closures that redraw them), as the store's key does.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

manim = pytest.importorskip("manim")

from test_sweeps import FLAT_SURFACE, PLOT, _style  # noqa: E402  (the shared minimal style of the bridge tests)


def _state_hash(scene, tracks) -> str:
    from manim.utils.hashing import get_hash_from_play_call

    from scianim_bridge.scene import TrackSegment

    animations = [TrackSegment(track, track.fraction, track.fraction, 1) for track in tracks]
    return get_hash_from_play_call(
        scene,
        scene.renderer.camera,
        animations,
        scene.mobjects,
        backend="cairo",
        encoder_fingerprint="test",
        renderer_state=(),
    )


def _shown(scene, *components) -> None:
    for component in components:
        scene.add(component.group)
        component.visible = True


def markers(scene) -> list:
    """A sweep that carries both markers of a plot, their staggered labels and a readout."""
    from scianim_bridge import components as C

    plot = C.function_plot(scene, "plot", params=PLOT)
    _shown(scene, plot)
    shift = scene.begin_vary(plot, "x_0", to=-4.0, at_seconds=0, duration_seconds=1, action_id="shift")
    scene.run_until(1.0, [shift])
    return [shift]


def moves(scene) -> list:
    """A caption moved, and a plot moved while a sweep widens its curve and moves a marker."""
    from scianim_bridge import components as C

    plot = C.function_plot(scene, "plot", params=PLOT)
    note = C.text_caption(scene, "note", params={"text": "a note", "anchor": "top_right"})
    _shown(scene, plot, note)
    slide = scene.begin_move(note, by=[-0.3, -0.2], at_seconds=0, duration_seconds=1, action_id="slide")
    carry = scene.begin_move(plot, by=[0.1, 0.05], at_seconds=0, duration_seconds=1, action_id="carry")
    widen = scene.begin_vary(plot, "sigma", to=3.0, at_seconds=0, duration_seconds=1, action_id="widen")
    scene.run_until(1.0, [widen, slide, carry])  # the sweep listed first: the moves still apply first
    return [widen, slide, carry]


def sphere(scene) -> list:
    """A sphere falling through its surface's coordinates."""
    from scianim_bridge import components as C

    surface = C.surface_plot(scene, "surface", params=FLAT_SURFACE)
    ball = C.sphere(scene, "ball", params={"anchor": "surface", "position": [0, 0, 1], "radius_fraction": 0.04})
    _shown(scene, surface, ball)
    fall = scene.begin_move(
        ball, to_point=[1.5, -1.0, 0.0], at_seconds=0, duration_seconds=1, action_id="fall", easing="ease_in_quad"
    )
    scene.run_until(1.0, [fall])
    return [fall]


RIDGE = {**FLAT_SURFACE, "expression": "a * x * y / 9", "parameters": {"a": 0}}


def _surface(scene, renderer: str) -> list:
    """A surface reshaped by a sweep with a readout while the camera orbits and its axes fade out."""
    from scianim_bridge import components as C

    scene.surface_renderer = renderer
    surface = C.surface_plot(scene, "surface", params=RIDGE)
    _shown(scene, surface)
    lift = scene.begin_vary(surface, "a", to=1.0, at_seconds=0, duration_seconds=1, action_id="lift")
    turn = scene.begin_orbit(
        to_theta_degrees=-20, to_phi_degrees=55, at_seconds=0, duration_seconds=1, action_id="turn"
    )
    hide = scene.begin_fade_axes(surface, visible=False, at_seconds=0, duration_seconds=1, action_id="hide")
    scene.run_until(1.0, [lift, turn, hide])
    return [lift, turn, hide]


def cairo_surface(scene) -> list:
    return _surface(scene, "cairo")


def raster_surface(scene) -> list:
    return _surface(scene, "raster")


def fades_and_transform(scene) -> list:
    """An equation transformed into another while a caption fades out."""
    from types import SimpleNamespace

    from scianim_bridge import components as C
    from scianim_core.animation import Equation

    before = Equation.model_validate(
        {"id": "before", "typst": "g = cos(theta) + phi", "symbols": {"theta": {"meaning": "angle"}}}
    )
    after = Equation.model_validate(
        {"id": "after", "typst": "g = cos(theta) sin(theta)", "symbols": {"theta": {"meaning": "angle"}}}
    )
    scene.ctx = SimpleNamespace(equations={"before": before, "after": after})
    label = C.equation_label(scene, "label", equation={"id": "before"}, params={"text": "g", "anchor": "top_left"})
    note = C.text_caption(scene, "note", params={"text": "a note", "anchor": "bottom_right"})
    _shown(scene, label, note)
    change = scene.begin_transform(label, to="after", at_seconds=0, duration_seconds=1, action_id="change")
    away = scene.begin_fade_object(note, visible=False, at_seconds=0, duration_seconds=1, action_id="away")
    scene.run_until(1.0, [change, away])
    return [change, away]


def transform_beside_a_sweep(scene) -> list:
    """The clock and the impact of `drop_impact`: a sweep that emphasizes the time in an equation, in `active`
    mode, and shows its value under it, while the equation is midway through becoming a two-line one when the play
    ends. The readout is placed under the equation as the transform leaves it in that frame."""
    from types import SimpleNamespace

    from scianim_bridge import components as C
    from scianim_core.animation import Equation

    def symbols(*names: str) -> dict:
        return {name: {"meaning": name} for name in names}

    free_fall = Equation.model_validate(
        {"id": "free_fall", "typst": "z(t) = z_0 - 1/2 g t^2", "symbols": symbols("z", "z_0", "g", "t")}
    )
    splash = Equation.model_validate(
        {
            "id": "splash",
            "typst": "& h(r, t) = -A e^(-t / tau_0) cos(k (r - c t)) \\ & r = sqrt(x^2 + y^2), quad t_(+) = max(t, 0)",
            "symbols": symbols("h", "r", "t", "A"),
        }
    )
    scene.ctx = SimpleNamespace(equations={"free_fall": free_fall, "splash": splash})
    model = C.equation_block(
        scene,
        "model",
        equation={"id": "free_fall", "highlight": ["t"], "highlight_mode": "active"},
        params={"anchor": "top_left", "scale": 0.7},
    )
    wave = {**PLOT, "parameters": {"t": 0}, "series": [{"label": "h", "expression": "exp(-((x - t)^2) / 2)"}]}
    plot = C.function_plot(scene, "plot", params={**wave, "markers": []})
    _shown(scene, model, plot)
    clock = scene.begin_vary(
        plot, "t", to=2.0, at_seconds=0, duration_seconds=2, action_id="clock", emphasize=[model], show_value=True
    )
    impact = scene.begin_transform(model, to="splash", at_seconds=0, duration_seconds=0.8, action_id="impact")
    scene.run_until(0.3, [clock, impact])
    return [clock, impact]


def cues_and_dims(scene) -> list:
    """A caption dimmed while a box travels from a symbol of an equation to a plot whose curve a sweep widens, and
    another symbol pulses (ADR-041). The play ends inside every window, so the box is mid-travel and the symbol
    mid-pulse; the box follows the curve as the sweep leaves it in each frame."""
    from types import SimpleNamespace

    from scianim_bridge import components as C
    from scianim_core.animation import Equation

    gauss = Equation.model_validate(
        {
            "id": "gauss",
            "typst": "g(x) = exp(-(x - x_0)^2 / (2 sigma^2))",
            "symbols": {"sigma": {"meaning": "width"}, "x_0": {"meaning": "centre"}},
        }
    )
    scene.ctx = SimpleNamespace(equations={"gauss": gauss})
    label = C.equation_label(
        scene,
        "label",
        equation={"id": "gauss", "highlight": ["sigma", "x_0"]},
        params={"text": "g", "anchor": "top_left"},
    )
    plot = C.function_plot(scene, "plot", params=PLOT)
    note = C.text_caption(scene, "note", params={"text": "a note", "anchor": "bottom_right"})
    _shown(scene, label, plot, note)
    dim = scene.begin_fade_object(note, ink=0.3, at_seconds=0, duration_seconds=1, action_id="dim")
    widen = scene.begin_vary(plot, "sigma", to=3.0, at_seconds=0, duration_seconds=1, action_id="widen")
    trip = scene.begin_emphasize(
        plot, from_target=label, from_symbols=["sigma"], at_seconds=0, duration_seconds=1, action_id="trip"
    )
    pulse = scene.begin_emphasize(
        label, symbols=["x_0"], cue="pulse", at_seconds=0, duration_seconds=1, action_id="pulse"
    )
    scene.run_until(0.6, [dim, widen, trip, pulse])
    return [dim, widen, trip, pulse]


def _run(tmp_path: Path, build: Callable, *, skip: bool) -> str:
    """The scene drawn (every frame interpolated and captured) or fast-forwarded (each play applied once); the
    state hash after the last play."""
    from manim import config

    from scianim_bridge.scene import SnapshotScene
    from scianim_bridge.tokens import Tokens

    class One(SnapshotScene):
        def construct(self) -> None:
            self.begin_scene("one", 0.0)
            self.final_hash = _state_hash(self, build(self))

    settings = {
        "media_dir": str(tmp_path / ("skip" if skip else "draw")),
        "format": "png",
        "write_to_movie": False,
        "save_last_frame": False,
        "disable_caching": True,
        "preview": False,
        "progress_bar": "none",
        "verbosity": "WARNING",
        "log_to_file": False,
        "frame_rate": 30,
        "pixel_width": 128,
        "pixel_height": 72,
        "output_file": "one",
    }
    with manim.tempconfig(settings):
        config.frame_width = config.frame_height * 16 / 9
        scene = One()
        scene._tokens = Tokens(_style())
        if skip:
            scene.renderer._original_skipping_status = True
        scene.render()
    drawn = [entry["drawn"] for entry in scene.play_log]
    assert drawn and (not any(drawn) if skip else all(drawn)), drawn
    return scene.final_hash


@pytest.mark.parametrize(
    "build",
    [
        markers,
        moves,
        sphere,
        cairo_surface,
        raster_surface,
        fades_and_transform,
        transform_beside_a_sweep,
        cues_and_dims,
    ],
    ids=lambda f: f.__name__,
)
def test_drawn_and_fast_forwarded_plays_leave_the_same_state(tmp_path: Path, build: Callable) -> None:
    assert _run(tmp_path, build, skip=False) == _run(tmp_path, build, skip=True)


def test_an_object_revealed_while_it_moves_ends_where_the_move_puts_it() -> None:
    """A reveal changes ink only, so a `move_object` that runs during it carries the object all the way: a sphere
    rising out of the surface as it appears (the droplet of `drop_impact`) and a caption sliding in."""
    import numpy as np
    from manim import config

    from scianim_bridge import components as C
    from scianim_bridge.scene import SnapshotScene
    from scianim_bridge.tokens import Tokens

    with manim.tempconfig({"pixel_width": 128, "pixel_height": 72, "frame_rate": 30}):
        config.frame_width = config.frame_height * 16 / 9
        scene = SnapshotScene()
        scene._tokens = Tokens(_style())
        scene.begin_scene("one", 0.0)
        surface = C.surface_plot(scene, "surface", params=FLAT_SURFACE)
        _shown(scene, surface)
        ball = C.sphere(scene, "ball", params={"anchor": "surface", "position": [0, 0, 0], "radius_fraction": 0.04})
        note = C.text_caption(scene, "note", params={"text": "a note", "anchor": "top_right"})
        start = note.group.get_center().copy()
        appear = scene.begin_reveal(ball, duration_seconds=0.6)
        rise = scene.begin_move(ball, to_point=[0, 0, 1], at_seconds=0, duration_seconds=1, action_id="rise")
        enter = scene.begin_reveal(note, duration_seconds=0.6)
        slide = scene.begin_move(note, by=[-0.2, 0.0], at_seconds=0, duration_seconds=1, action_id="slide")
        scene.run_until(0.6, [appear, rise, enter, slide])
        scene.run_until(1.0, [rise, slide])
        centre = np.mean([face.get_center() for face in ball.faces], axis=0)
        assert centre == pytest.approx(surface.to_world([0, 0, 1]), abs=1e-6)
        x0, _, x1, _ = scene.tokens.safe_rect()
        assert note.group.get_center() == pytest.approx(start + np.array([-0.2 * (x1 - x0), 0.0, 0.0]), abs=1e-6)
        assert all(float(face.get_fill_opacity()) > 0 for face in ball.visible_faces())
