"""Cues (`emphasize`) and fades to a level of ink (ADR-041): their contracts, the rules that keep them honest, the
code generated for them, their summaries, and the rest the style asks for between motions."""

from __future__ import annotations

from typing import Any

import pytest
from test_actions import MORPH, SWEEP, _storyboard, _world_objects

from scianim.actions import action_summary
from scianim.agent.context import export_context
from scianim.codegen.generate import generate_scene_module
from scianim.planning.checks import validate_project
from scianim.project import Project
from scianim_core import Storyboard
from scianim_core.storyboard import FadeObject, MoveObject

TRIP: dict[str, Any] = {
    "id": "trip",
    "kind": "emphasize",
    "target": "plot",
    "from_target": "label",
    "from_symbols": ["sigma"],
    "at_seconds": 3,
    "duration_seconds": 2,
}
PULSE: dict[str, Any] = {
    "id": "pulse",
    "kind": "emphasize",
    "target": "label",
    "symbols": ["sigma"],
    "cue": "pulse",
    "at_seconds": 3,
    "duration_seconds": 1,
}
DIM: dict[str, Any] = {
    "id": "dim",
    "kind": "fade_object",
    "target": "plot",
    "ink": 0.3,
    "at_seconds": 1,
    "duration_seconds": 1,
}


def _fade(**fields: Any) -> FadeObject:
    return FadeObject.model_validate(
        {"kind": "fade_object", "id": "f", "target": "x", "at_seconds": 0, "duration_seconds": 1, **fields}
    )


def test_a_fade_names_its_level_once() -> None:
    assert _fade().target_ink == 0.0 and _fade(visible=True).target_ink == 1.0 and _fade(ink=0.3).target_ink == 0.3
    with pytest.raises(ValueError, match="give visible or ink, not both"):
        _fade(visible=True, ink=0.3)
    with pytest.raises(ValueError, match="less than or equal to 1"):
        _fade(ink=1.5)
    # A dump and a reload keep the meaning: an omitted `visible` stays omitted.
    assert FadeObject.model_validate(_fade(ink=0.3).model_dump(mode="json")).target_ink == 0.3


def test_cues_point_at_flat_places_and_named_symbols() -> None:
    board = Storyboard.model_validate(_storyboard(actions=[TRIP, {**PULSE, "at_seconds": 6}]))
    trip, pulse = board.actions()
    assert trip.places == [("plot", []), ("label", ["sigma"])] and pulse.cue == "pulse"
    for change, message in (
        ({"cue": "pulse", "symbols": []}, "a pulse grows symbols"),
        ({"cue": "pulse", "symbols": ["sigma"], "target": "label"}, "only a box travels"),
        ({"from_target": None}, "from_symbols needs from_target"),
        ({"from_symbols": ["mu"]}, r"highlight includes \['mu'\]"),
        ({"symbols": ["sigma"]}, r"'plot' must reference an equation"),
        ({"from_target": "nowhere"}, "'nowhere' is not an object"),
        ({"at_seconds": 1}, "points at 'label' before it is revealed at 2s"),
    ):
        with pytest.raises(ValueError, match=message):
            Storyboard.model_validate(_storyboard(actions=[{**TRIP, **change}]))
    with pytest.raises(ValueError, match="turns with the camera"):
        Storyboard.model_validate(
            _storyboard(objects=_world_objects(), actions=[{**TRIP, "target": "surface", "at_seconds": 3}])
        )


def test_cues_keep_out_of_the_way_of_glyphs_that_change() -> None:
    with pytest.raises(ValueError, match="pulses 'label' while 'widen' emphasizes it"):
        Storyboard.model_validate(_storyboard(actions=[SWEEP, {**PULSE, "at_seconds": 6}]))
    Storyboard.model_validate(_storyboard(actions=[SWEEP, {**TRIP, "at_seconds": 6}]))  # a box may sit beside a sweep
    with pytest.raises(ValueError, match="replaces its glyphs"):
        Storyboard.model_validate(
            _storyboard(objects=_world_objects(), actions=[{**MORPH, "at_seconds": 3}, {**TRIP, "target": "note"}])
        )
    with pytest.raises(ValueError, match="pulses 'pulse' and 'again' of 'label' overlap"):
        Storyboard.model_validate(_storyboard(actions=[PULSE, {**PULSE, "id": "again", "at_seconds": 3.5}]))


def test_a_dimmed_object_is_not_redrawn_until_its_ink_is_restored() -> None:
    with pytest.raises(ValueError, match="'widen' redraws 'plot' while 'dim' dims it"):
        Storyboard.model_validate(_storyboard(actions=[DIM, SWEEP]))
    restore = {
        "id": "back",
        "kind": "fade_object",
        "target": "plot",
        "visible": True,
        "at_seconds": 2.5,
        "duration_seconds": 1,
    }
    Storyboard.model_validate(_storyboard(actions=[DIM, restore, SWEEP]))
    with pytest.raises(ValueError, match="'widen' redraws 'plot' while 'back' dims it or fades it from a partial ink"):
        Storyboard.model_validate(_storyboard(actions=[DIM, {**restore, "at_seconds": 4.5}, SWEEP]))
    dim_label = {**DIM, "id": "dim_label", "target": "label", "at_seconds": 2}
    with pytest.raises(ValueError, match="'widen' redraws 'label'"):
        Storyboard.model_validate(_storyboard(actions=[dim_label, SWEEP]))
    # Fading out and back in at full ink, and moving a dimmed object, stay allowed.
    out = {"id": "out", "kind": "fade_object", "target": "plot", "at_seconds": 1, "duration_seconds": 1}
    Storyboard.model_validate(_storyboard(actions=[out, {**restore, "at_seconds": 2.5}, SWEEP]))


def test_codegen_emits_cues_and_ink_levels(project_copy: Project) -> None:
    report = validate_project(project_copy)
    assert report.animation and report.style
    board = Storyboard.model_validate(_storyboard(actions=[DIM, TRIP, {**PULSE, "at_seconds": 6}]))
    lines = [line.strip() for line in generate_scene_module(report.animation, board, report.style).splitlines()]
    assert (
        'dim = self.begin_fade_object(plot, ink=0.3, at_seconds=1, duration_seconds=1, action_id="dim", easing=None)'
        in lines
    )
    assert (
        "trip = self.begin_emphasize(plot, symbols=[], cue=\"box\", from_target=label, from_symbols=['sigma'], "
        'at_seconds=3, duration_seconds=2, action_id="trip", easing=None)'
    ) in lines
    assert any(
        line.startswith("pulse = self.begin_emphasize(label, symbols=['sigma'], cue=\"pulse\", from_target=None")
        for line in lines
    )


def test_summaries_name_cues_and_dims() -> None:
    board = Storyboard.model_validate(
        _storyboard(
            actions=[
                DIM,
                TRIP,
                {**PULSE, "at_seconds": 6},
                {**TRIP, "id": "look", "from_target": None, "from_symbols": [], "at_seconds": 8},
            ]
        )
    )
    assert [action_summary(a) for a in board.actions()] == [
        "plot dims to 0.3 of its ink",
        "a box travels from sigma in label to plot",
        "sigma in label pulses",
        "a box points at plot",
    ]


def test_the_halves_of_a_ballistic_arc_ask_no_rest(project_copy: Project) -> None:
    report = validate_project(project_copy)
    assert report.ok and report.storyboard and report.style, report.errors
    assert report.style.tokens.motion.hold_seconds == 1.0  # tomas_scientific@0.5.1

    def warnings_for(first: str, second: str) -> list[str]:
        storyboard = report.storyboard.model_copy(deep=True)
        scene = storyboard.scenes[0]
        scene.actions = [
            *scene.actions,
            MoveObject(
                id="up",
                kind="move_object",
                target="drive_note",
                by=(0, 0.1),
                at_seconds=2.5,
                duration_seconds=1,
                easing=first,
            ),
            MoveObject(
                id="down",
                kind="move_object",
                target="drive_note",
                by=(0, -0.1),
                at_seconds=3.5,
                duration_seconds=1,
                easing=second,
            ),
        ]
        board = Storyboard.model_validate(storyboard.model_dump(mode="json"))
        return [w for w in validate_project(project_copy, storyboard=board).warnings if "'down' moves" in w]

    assert warnings_for("ease_out_quad", "ease_in_quad") == []
    assert any("a rest of 1s" in w for w in warnings_for("ease_in_quad", "ease_out_quad"))


def test_the_context_bundle_describes_every_kind_of_action(workspace) -> None:
    drop = Project(workspace / "families" / "computational_neuroscience" / "drop_impact")
    text = (export_context(drop, validate_project(drop)) / "CONTEXT.md").read_text()
    assert "drop moves to (0, 0, 0)" in text and "model becomes equation splash (by symbol)" in text
