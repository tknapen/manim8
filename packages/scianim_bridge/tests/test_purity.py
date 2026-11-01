"""A play leaves the same state, bit for bit, whether Manim draws it frame by frame or applies it once (ADR-039).

Manim names a play's segment by a hash of the scene's state at its start. If a drawn play and a fast-forwarded
or cached one left different bits, every later play of a re-render, and of the parts of a parallel render,
would miss the segment store (ADR-033). The check here is Manim's own hash of the state after the play.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

manim = pytest.importorskip("manim")

from test_sweeps import FLAT_SURFACE, PLOT, _style  # noqa: E402  (the shared minimal style of the bridge tests)


def _state_hash(scene) -> str:
    from manim.utils.hashing import get_hash_from_play_call

    return get_hash_from_play_call(
        scene, scene.renderer.camera, [], scene.mobjects, backend="cairo", encoder_fingerprint="test", renderer_state=()
    )


def _shown(scene, *components) -> None:
    for component in components:
        scene.add(component.group)
        component.visible = True


def markers(scene) -> None:
    """A sweep that carries both markers of a plot, their staggered labels and a readout."""
    from scianim_bridge import components as C

    plot = C.function_plot(scene, "plot", params=PLOT)
    _shown(scene, plot)
    shift = scene.begin_vary(plot, "x_0", to=-4.0, at_seconds=0, duration_seconds=1, action_id="shift")
    scene.run_until(1.0, [shift])


def moves(scene) -> None:
    """A caption moved, and a plot moved while a sweep widens its curve and moves a marker."""
    from scianim_bridge import components as C

    plot = C.function_plot(scene, "plot", params=PLOT)
    note = C.text_caption(scene, "note", params={"text": "a note", "anchor": "top_right"})
    _shown(scene, plot, note)
    slide = scene.begin_move(note, by=[-0.3, -0.2], at_seconds=0, duration_seconds=1, action_id="slide")
    carry = scene.begin_move(plot, by=[0.1, 0.05], at_seconds=0, duration_seconds=1, action_id="carry")
    widen = scene.begin_vary(plot, "sigma", to=3.0, at_seconds=0, duration_seconds=1, action_id="widen")
    scene.run_until(1.0, [widen, slide, carry])  # the sweep listed first: the moves still apply first


def sphere(scene) -> None:
    """A sphere falling through its surface's coordinates."""
    from scianim_bridge import components as C

    surface = C.surface_plot(scene, "surface", params=FLAT_SURFACE)
    ball = C.sphere(scene, "ball", params={"anchor": "surface", "position": [0, 0, 1], "radius_fraction": 0.04})
    _shown(scene, surface, ball)
    fall = scene.begin_move(
        ball, to_point=[1.5, -1.0, 0.0], at_seconds=0, duration_seconds=1, action_id="fall", easing="ease_in_quad"
    )
    scene.run_until(1.0, [fall])


def _run(tmp_path: Path, build: Callable, *, skip: bool) -> str:
    """The scene drawn (every frame interpolated and captured) or fast-forwarded (each play applied once); the
    state hash after the last play."""
    from manim import config

    from scianim_bridge.scene import SnapshotScene
    from scianim_bridge.tokens import Tokens

    class One(SnapshotScene):
        def construct(self) -> None:
            self.begin_scene("one", 0.0)
            build(self)
            self.final_hash = _state_hash(self)

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


@pytest.mark.parametrize("build", [markers, moves, sphere], ids=lambda f: f.__name__)
def test_drawn_and_fast_forwarded_plays_leave_the_same_state(tmp_path: Path, build: Callable) -> None:
    assert _run(tmp_path, build, skip=False) == _run(tmp_path, build, skip=True)
