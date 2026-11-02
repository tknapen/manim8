"""Scene actions: `vary_parameter` validation, generated sweep segments, timing, staleness and inspection."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from scianim.agent.inspect import expected_objects
from scianim.codegen.generate import generate_scene_module
from scianim.planning.checks import checkpoint_markers, validate_project
from scianim.planning.dependencies import changed_scenes
from scianim.planning.timing import propose_timing
from scianim.project import Project
from scianim_core import Storyboard
from scianim_core.components import FunctionPlotParams, validate_params
from scianim_core.storyboard import MoveObject, TransformEquation

PLOT: dict[str, Any] = {
    "x_label": "x",
    "y_label": "g(x)",
    "x_range": [-10, 10],
    "y_range": [0, 1.2],
    "parameters": {"x_0": 2, "sigma": 1.5},
    "series": [{"label": "g", "expression": "exp(-((x - x_0)^2) / (2 * sigma^2))"}],
    "markers": [{"x": "x_0", "label": "x0"}, {"x": "x_0 + sigma", "label": "x0 + sigma"}],
}


def _storyboard(
    *,
    actions: list[dict[str, Any]],
    objects: list[dict[str, Any]] | None = None,
    snapshots: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    objects = objects or [
        {"id": "plot", "kind": "function_plot", "params": copy.deepcopy(PLOT)},
        {
            "id": "label",
            "kind": "equation_label",
            "equation": {"id": "gaussian", "highlight": ["sigma"]},
            "params": {"text": "size"},
            "reveal_at_seconds": 2,
        },
    ]
    return {
        "schema_version": "1.0",
        "project_id": "p",
        "based_on_animation_revision": "working",
        "scenes": [
            {
                "id": "s",
                "start_seconds": 0,
                "end_seconds": 20,
                "purpose": "test",
                "objects": objects,
                "actions": actions,
                "snapshots": snapshots or [],
            }
        ],
    }


SWEEP: dict[str, Any] = {
    "id": "widen",
    "kind": "vary_parameter",
    "target": "plot",
    "parameter": "sigma",
    "to": 4,
    "at_seconds": 5,
    "duration_seconds": 6,
    "emphasize": ["label"],
}


def test_function_plot_parameters_and_marker_expressions() -> None:
    params = validate_params("function_plot", PLOT)
    assert isinstance(params, FunctionPlotParams)
    assert params.marker_x(params.markers[1]) == pytest.approx(3.5)
    assert params.marker_x(params.markers[1], {"sigma": 4}) == pytest.approx(6)
    with pytest.raises(ValueError, match="unknown name 'k'"):
        validate_params("function_plot", {**PLOT, "series": [{"label": "g", "expression": "k * x"}]})
    with pytest.raises(ValueError, match="other than"):
        validate_params("function_plot", {**PLOT, "parameters": {"x": 1}})
    with pytest.raises(ValueError, match="built-in function"):
        validate_params("function_plot", {**PLOT, "parameters": {"exp": 1}})
    with pytest.raises(ValueError, match="outside x_range"):
        validate_params("function_plot", {**PLOT, "markers": [{"x": "x_0 + 20"}]})


def test_vary_parameter_validation() -> None:
    assert Storyboard.model_validate(_storyboard(actions=[SWEEP])).actions()[0].end_seconds == 11

    def rejected(message: str, **changes: Any) -> None:
        with pytest.raises(ValueError, match=message):
            Storyboard.model_validate(_storyboard(actions=[{**SWEEP, **changes}]))

    rejected("not an object", target="nope")
    rejected("needs one of", target="label")
    rejected("declares no parameter 'tau'", parameter="tau")
    rejected("outside scene", at_seconds=16)
    rejected("starts before 'label' is revealed", at_seconds=1)
    rejected("must reference an equation whose highlight includes", emphasize=["plot"])
    rejected("not an object of scene", emphasize=["ghost"])
    # Concurrency: two actions may overlap unless they drive the same parameter; orbits need a surface.
    Storyboard.model_validate(
        _storyboard(actions=[SWEEP, {**SWEEP, "id": "shift", "parameter": "x_0", "to": 0, "emphasize": []}])
    )
    with pytest.raises(ValueError, match=r"both vary 'plot\.sigma'"):
        Storyboard.model_validate(_storyboard(actions=[SWEEP, {**SWEEP, "id": "again", "at_seconds": 8}]))
    orbit = {"id": "orbit", "kind": "orbit_camera", "to_theta_degrees": 40, "at_seconds": 0, "duration_seconds": 20}
    with pytest.raises(ValueError, match="needs a surface_plot"):
        Storyboard.model_validate(_storyboard(actions=[orbit]))
    with pytest.raises(ValueError, match="to_theta_degrees, to_phi_degrees or both"):
        Storyboard.model_validate(_storyboard(actions=[{**orbit, "to_theta_degrees": None}]))
    with pytest.raises(ValueError, match="y_range"):
        plot = {**PLOT}
        del plot["y_range"]
        Storyboard.model_validate(
            _storyboard(
                actions=[{**SWEEP, "emphasize": []}],
                objects=[{"id": "plot", "kind": "function_plot", "params": plot}],
            )
        )
    with pytest.raises(ValueError, match="object or action"):
        Storyboard.model_validate(_storyboard(actions=[{**SWEEP, "id": "plot"}]))


def test_codegen_splits_a_sweep_at_the_checkpoints_inside_it(project_copy: Project, tmp_path) -> None:
    report = validate_project(project_copy)
    assert report.animation and report.style
    storyboard = Storyboard.model_validate(
        _storyboard(
            actions=[SWEEP],
            snapshots=[
                {"id": "before", "at_seconds": 5, "description": "state before the sweep"},
                {"id": "halfway", "at_seconds": 8, "description": "inside"},
                {"id": "after", "at_seconds": 12, "description": "done"},
            ],
        )
    )
    code = generate_scene_module(report.animation, storyboard, report.style)
    lines = [line.strip() for line in code.splitlines() if line.strip()]
    begin = next(i for i, line in enumerate(lines) if line.startswith("widen = self.begin_vary(plot"))
    assert 'checkpoint(self, "before", expected_time=5)' in lines[:begin]
    assert lines[begin + 1] == "self.run_until(8, [widen])"
    assert lines[begin + 2] == "self.wait_until(8)"
    assert lines[begin + 3] == 'checkpoint(self, "halfway", expected_time=8)'
    assert lines[begin + 4] == "self.run_until(11, [widen])"
    assert "reveal_plot = self.begin_reveal(plot)" in lines and "self.run_until(0.85, [reveal_plot])" in lines
    assert 'checkpoint(self, "after", expected_time=12)' in lines[begin + 5 :]
    assert 'to=4.0, at_seconds=5, duration_seconds=6, action_id="widen", easing=None, emphasize=[label]' in lines[begin]
    module = tmp_path / "scene.py"
    module.write_text(code)
    assert checkpoint_markers(module) == ["before", "halfway", "after"]


def test_timing_staleness_and_inspection_notice_actions(project_copy: Project) -> None:
    report = validate_project(project_copy)
    assert report.animation and report.storyboard
    assert any(a.id == "raise_pool" for a in report.storyboard.actions())
    # A narration-based proposal that shortens the pool scene puts the sweep outside it.
    slow = propose_timing(report.animation, report.storyboard, 400.0)
    assert any("action 'raise_pool'" in c for s in slow.scenes for c in s.conflicts)
    # Changing the sweep marks the scene stale; nothing else moves.
    after = report.storyboard.model_copy(deep=True)
    after.scenes[1].actions[0].to = 6
    changes = changed_scenes(
        report.storyboard,
        after,
        before_spec=report.animation,
        after_spec=report.animation,
        data_changed=set(),
        style_changed=False,
        custom_code_changed=False,
    )
    by_id = {c.scene_id: c for c in changes.scenes}
    assert "actions changed" in by_id["normalization"].reasons and not by_id["excitation"].reasons
    # The readout counts as an expected object once the sweep has begun.
    assert "raise_pool" not in expected_objects(report.storyboard, "normalization", 8.5)
    assert "raise_pool" in expected_objects(report.storyboard, "normalization", 9)


def test_project_checks_warn_about_snapshots_in_reveals_and_unnamed_parameters(project_copy: Project) -> None:
    report = validate_project(project_copy)
    assert report.ok and not report.warnings, report.warnings
    storyboard = report.storyboard.model_copy(deep=True)
    assert storyboard is not None
    storyboard.scenes[1].snapshots[0].at_seconds = 7.4  # the equation is still fading in at 7.4 s
    fading = validate_project(project_copy, storyboard=Storyboard.model_validate(storyboard.model_dump(mode="json")))
    assert any("still fading in" in w for w in fading.warnings), fading.warnings
    storyboard = report.storyboard.model_copy(deep=True)
    plot = storyboard.scenes[1].objects[0]
    plot.params["parameters"] = {"sigma": 1, "P": 1, "gain": 2}
    plot.params["series"] = [{"label": "schematic response", "expression": "gain * x / (sigma + P)"}]
    renamed = validate_project(project_copy, storyboard=Storyboard.model_validate(storyboard.model_dump(mode="json")))
    assert any("parameters ['gain'] are not symbols" in w for w in renamed.warnings), renamed.warnings


SURFACE: dict[str, Any] = {
    "x_label": "x",
    "y_label": "y",
    "z_label": "g",
    "x_range": [-3, 3],
    "y_range": [-3, 3],
    "z_range": [0, 1],
    "expression": "exp(-(x^2 + y^2) / (2 * sigma^2))",
    "parameters": {"sigma": 1.5},
    "resolution": 8,
}
FADE: dict[str, Any] = {
    "id": "axes_away",
    "kind": "fade_axes",
    "target": "surface",
    "at_seconds": 3,
    "duration_seconds": 0.8,
}


def _surface_objects(**surface_extra: Any) -> list[dict[str, Any]]:
    return [
        {"id": "surface", "kind": "surface_plot", "params": copy.deepcopy(SURFACE), **surface_extra},
        {
            "id": "label",
            "kind": "equation_label",
            "equation": {"id": "gaussian", "highlight": ["sigma"], "highlight_mode": "active"},
            "params": {"text": "size"},
        },
    ]


def test_lead_in_and_highlight_mode() -> None:
    sweep = Storyboard.model_validate(_storyboard(actions=[{**SWEEP, "lead_in_seconds": 1.5}])).actions()[0]
    assert sweep.end_seconds == 12.5 and sweep.moves_at_seconds == 6.5
    with pytest.raises(ValueError, match="outside scene"):
        Storyboard.model_validate(_storyboard(actions=[{**SWEEP, "at_seconds": 13, "lead_in_seconds": 2}]))
    with pytest.raises(ValueError, match="lead_in_seconds"):
        Storyboard.model_validate(_storyboard(actions=[{**SWEEP, "lead_in_seconds": -1}]))
    # The lead-in is part of the window, so it counts towards the overlap of two actions on one parameter.
    with pytest.raises(ValueError, match=r"both vary 'plot\.sigma'"):
        Storyboard.model_validate(
            _storyboard(actions=[{**SWEEP, "lead_in_seconds": 3}, {**SWEEP, "id": "again", "at_seconds": 12}])
        )
    objects = _surface_objects()
    label = Storyboard.model_validate(_storyboard(actions=[], objects=objects)).objects()[1]
    assert label.equation is not None and label.equation.highlight_mode == "active"
    objects[1]["equation"]["highlight_mode"] = "sometimes"
    with pytest.raises(ValueError, match="highlight_mode"):
        Storyboard.model_validate(_storyboard(actions=[], objects=objects))


def test_fade_axes_validation() -> None:
    storyboard = Storyboard.model_validate(_storyboard(actions=[FADE], objects=_surface_objects()))
    fade = storyboard.actions()[0]
    assert fade.kind == "fade_axes" and fade.visible is False and fade.end_seconds == pytest.approx(3.8)

    def rejected(message: str, objects: list[dict[str, Any]] | None = None, **changes: Any) -> None:
        with pytest.raises(ValueError, match=message):
            Storyboard.model_validate(_storyboard(actions=[{**FADE, **changes}], objects=objects or _surface_objects()))

    rejected("not an object", target="nope")
    rejected("needs a surface_plot", target="label")
    rejected("starts before its target", objects=_surface_objects(reveal_at_seconds=5))
    rejected("outside scene", at_seconds=19.5)
    with pytest.raises(ValueError, match="overlap"):
        Storyboard.model_validate(
            _storyboard(
                actions=[FADE, {**FADE, "id": "back", "visible": True, "at_seconds": 3.5}], objects=_surface_objects()
            )
        )
    # A fade may run beside a sweep of the same surface, and a later fade may bring the axes back.
    Storyboard.model_validate(
        _storyboard(
            actions=[FADE, {**SWEEP, "target": "surface"}, {**FADE, "id": "back", "visible": True, "at_seconds": 12}],
            objects=_surface_objects(),
        )
    )


def test_codegen_emits_axes_fades_and_lead_ins(project_copy: Project, tmp_path) -> None:
    report = validate_project(project_copy)
    assert report.animation and report.style
    storyboard = Storyboard.model_validate(
        _storyboard(
            objects=_surface_objects(),
            actions=[FADE, {**SWEEP, "target": "surface", "lead_in_seconds": 1, "duration_seconds": 4}],
            snapshots=[
                {
                    "id": "lit",
                    "at_seconds": 5.5,
                    "description": "inside the lead-in: the term in colour, the value unchanged",
                },
                {"id": "halfway", "at_seconds": 8, "description": "inside the sweep"},
            ],
        )
    )
    code = generate_scene_module(report.animation, storyboard, report.style)
    lines = [line.strip() for line in code.splitlines() if line.strip()]
    assert (
        "axes_away = self.begin_fade_axes(surface, visible=False, at_seconds=3, duration_seconds=0.8, "
        'action_id="axes_away", easing=None)'
    ) in lines
    assert "self.run_until(3.8, [axes_away])" in lines
    begin = next(i for i, line in enumerate(lines) if line.startswith("widen = self.begin_vary(surface"))
    assert lines[begin].endswith("value_label=None, lead_in_seconds=1)")
    assert lines[begin + 1 : begin + 6] == [
        "self.run_until(5.5, [widen])",
        "self.wait_until(5.5)",
        'checkpoint(self, "lit", expected_time=5.5)',
        "self.run_until(8, [widen])",
        "self.wait_until(8)",
    ]
    assert 'checkpoint(self, "halfway", expected_time=8)' in lines and "self.run_until(10, [widen])" in lines
    module = tmp_path / "scene.py"
    module.write_text(code)
    assert checkpoint_markers(module) == ["lit", "halfway"]


# --- ADR-034: move, fade, transform an equation, data-bound sweeps, the sphere -------------------------------

SPHERE: dict[str, Any] = {"anchor": "surface", "position": [0, 0, 1.5], "radius_fraction": 0.03}
MOVE: dict[str, Any] = {
    "id": "fall",
    "kind": "move_object",
    "target": "ball",
    "to_point": [0, 0, 0],
    "at_seconds": 3,
    "duration_seconds": 2,
    "easing": "ease_in_quad",
}
FADE_OUT: dict[str, Any] = {
    "id": "vanish",
    "kind": "fade_object",
    "target": "ball",
    "at_seconds": 5,
    "duration_seconds": 0.3,
}
MORPH: dict[str, Any] = {
    "id": "morph",
    "kind": "transform_equation",
    "target": "label",
    "to": "wave",
    "at_seconds": 5,
    "duration_seconds": 0.8,
}


def _world_objects(**sphere_extra: Any) -> list[dict[str, Any]]:
    return [
        *_surface_objects(),
        {"id": "ball", "kind": "sphere", "params": copy.deepcopy(SPHERE), **sphere_extra},
        {"id": "note", "kind": "text_caption", "params": {"text": "note", "anchor": "top_left"}},
    ]


def test_sphere_anchor_rules() -> None:
    storyboard = Storyboard.model_validate(_storyboard(actions=[], objects=_world_objects()))
    ball = storyboard.objects()[2]
    assert ball.kind == "sphere" and ball.typed_params().position == (0, 0, 1.5)
    with pytest.raises(ValueError, match="must name a surface_plot declared earlier"):
        Storyboard.model_validate(_storyboard(actions=[], objects=_world_objects()[::-1]))
    with pytest.raises(ValueError, match="must name a surface_plot declared earlier"):
        objects = _world_objects()
        objects[2]["params"]["anchor"] = "label"
        Storyboard.model_validate(_storyboard(actions=[], objects=objects))
    with pytest.raises(ValueError, match="before its anchor"):
        objects = _world_objects()
        objects[0]["reveal_at_seconds"] = 4
        Storyboard.model_validate(_storyboard(actions=[], objects=objects))
    with pytest.raises(ValueError, match="radius_fraction"):
        validate_params("sphere", {**SPHERE, "radius_fraction": 0})


def test_move_fade_and_transform_validation() -> None:
    board = Storyboard.model_validate(_storyboard(actions=[MOVE, FADE_OUT, MORPH], objects=_world_objects()))
    fall, vanish, morph = board.actions()
    assert fall.end_seconds == 5 and vanish.target_ink == 0 and morph.match == "by_symbol" and morph.end_seconds == 5.8

    def rejected(message: str, *actions: dict[str, Any], objects: list[dict[str, Any]] | None = None) -> None:
        with pytest.raises(ValueError, match=message):
            Storyboard.model_validate(_storyboard(actions=list(actions), objects=objects or _world_objects()))

    rejected("exactly one of to_anchor, by or to_point", {**MOVE, "to_point": None})
    rejected("exactly one of to_anchor, by or to_point", {**MOVE, "by": [0.1, 0]})
    rejected("to_point moves an object anchored", {**MOVE, "target": "note"})
    rejected("turns with the camera", {**MOVE, "target": "surface", "to_point": None, "to_anchor": "center"})
    rejected(
        "turns with the camera; to_anchor and by move flat objects in the frame, a sphere moves to_point",
        {**MOVE, "to_point": None, "by": [0.1, 0]},
    )
    rejected("not an object", {**MOVE, "target": "ghost"})
    rejected("starts before its target", {**MOVE, "at_seconds": 1}, objects=_world_objects(reveal_at_seconds=2))
    rejected("starts before its target", {**FADE_OUT, "at_seconds": 1}, objects=_world_objects(reveal_at_seconds=2))
    rejected("outside scene", {**FADE_OUT, "at_seconds": 19.9})
    rejected("needs an equation_block or equation_label", {**MORPH, "target": "note"})
    rejected(
        "symbol definitions",
        {**MORPH, "target": "block"},
        objects=[
            *_world_objects(),
            {
                "id": "block",
                "kind": "equation_block",
                "equation": {"id": "gaussian"},
                "params": {"define_symbols": True},
            },
        ],
    )
    # Flat objects move by anchor or offset; a sphere by point. Easing names are checked.
    Storyboard.model_validate(
        _storyboard(
            actions=[
                {**MOVE, "id": "slide", "target": "note", "to_point": None, "to_anchor": "bottom_left"},
                {**MOVE, "id": "nudge", "target": "note", "to_point": None, "by": [0.1, -0.05], "at_seconds": 6},
            ],
            objects=_world_objects(),
        )
    )
    rejected("easing", {**MOVE, "easing": "parabolic"})
    # Overlaps: two moves, two fades or two transforms of one object; a sweep may not start inside a transform.
    rejected("moves 'fall' and 'again' of 'ball' overlap", MOVE, {**MOVE, "id": "again", "at_seconds": 4})
    rejected(
        "fades 'vanish' and 'back' of 'ball' overlap",
        FADE_OUT,
        {**FADE_OUT, "id": "back", "visible": True, "at_seconds": 5.2},
    )
    rejected("transforms 'morph' and 'twice' of 'label' overlap", MORPH, {**MORPH, "id": "twice", "at_seconds": 5.5})
    rejected(
        "starts at 5.4s, inside 'morph'",
        MORPH,
        {**SWEEP, "target": "surface", "at_seconds": 5.4, "duration_seconds": 3},
    )
    # A sweep already running when the transform begins, or starting when it ends, is fine; so is a move beside a fade.
    Storyboard.model_validate(
        _storyboard(
            actions=[MORPH, {**SWEEP, "target": "surface", "at_seconds": 4}, MOVE, FADE_OUT],
            objects=_world_objects(),
        )
    )
    Storyboard.model_validate(
        _storyboard(actions=[MORPH, {**SWEEP, "target": "surface", "at_seconds": 5.8}], objects=_world_objects())
    )


DATA_PLOT: dict[str, Any] = {
    "id": "curve",
    "kind": "scientific_plot",
    "data": {
        "source": "responses",
        "encoding": {"x": "excitation_E", "y": "response_r"},
        "transforms": [
            {"op": "filter", "column": "condition", "equals": "low_pool"},
            {"op": "scale", "column": "response_r", "by": {"parameter": "g", "default": 1}},
            {"op": "smooth", "column": "response_r", "window": {"parameter": "w", "default": 0}},
        ],
    },
    "params": {"x_label": "E", "y_label": "r", "y_range": [0, 8]},
}
GAIN: dict[str, Any] = {
    "id": "gain",
    "kind": "vary_parameter",
    "target": "curve",
    "parameter": "g",
    "to": 1.5,
    "at_seconds": 4,
    "duration_seconds": 1.3,
}


def test_data_bound_sweeps() -> None:
    board = Storyboard.model_validate(_storyboard(actions=[GAIN], objects=[DATA_PLOT]))
    curve = board.objects()[0]
    assert curve.data is not None and curve.data.parameters() == {"g": 1.0, "w": 0.0}
    with pytest.raises(ValueError, match="give 'curve' a y_range"):
        plot = copy.deepcopy(DATA_PLOT)
        del plot["params"]["y_range"]
        Storyboard.model_validate(_storyboard(actions=[GAIN], objects=[plot]))
    with pytest.raises(ValueError, match="declares no parameter 'k'"):
        Storyboard.model_validate(_storyboard(actions=[{**GAIN, "parameter": "k"}], objects=[DATA_PLOT]))
    with pytest.raises(ValueError, match="a data binding whose transforms name parameters"):
        plot = copy.deepcopy(DATA_PLOT)
        plot["data"]["transforms"] = plot["data"]["transforms"][:1]
        Storyboard.model_validate(_storyboard(actions=[GAIN], objects=[plot]))
    with pytest.raises(ValueError, match="two defaults"):
        plot = copy.deepcopy(DATA_PLOT)
        plot["data"]["transforms"][2]["window"] = {"parameter": "g", "default": 2}
        Storyboard.model_validate(_storyboard(actions=[], objects=[plot]))
    with pytest.raises(ValueError, match="built-in function"):
        plot = copy.deepcopy(DATA_PLOT)
        plot["data"]["transforms"][1]["by"] = {"parameter": "pi", "default": 2}
        Storyboard.model_validate(_storyboard(actions=[], objects=[plot]))
    # A plain number still works, and an unknown op is refused.
    plot = copy.deepcopy(DATA_PLOT)
    plot["data"]["transforms"][1]["by"] = 2
    assert Storyboard.model_validate(_storyboard(actions=[], objects=[plot])).objects()[0].data.parameters() == {
        "w": 0.0
    }
    with pytest.raises(ValueError, match="op"):
        plot["data"]["transforms"][1]["op"] = "square"
        Storyboard.model_validate(_storyboard(actions=[], objects=[plot]))


def test_codegen_emits_moves_fades_and_transforms(project_copy: Project, tmp_path) -> None:
    report = validate_project(project_copy)
    assert report.animation and report.style
    storyboard = Storyboard.model_validate(
        _storyboard(
            objects=_world_objects(),
            actions=[
                MOVE,
                FADE_OUT,
                MORPH,
                {
                    **MOVE,
                    "id": "slide",
                    "target": "note",
                    "to_point": None,
                    "to_anchor": "bottom_left",
                    "at_seconds": 10.1,
                    "duration_seconds": 1.2,
                    "easing": None,
                },
                {**FADE_OUT, "id": "note_away", "target": "note", "at_seconds": 11.3},
            ],
            snapshots=[{"id": "midfall", "at_seconds": 4, "description": "inside the fall"}],
        )
    )
    code = generate_scene_module(report.animation, storyboard, report.style)
    lines = [line.strip() for line in code.splitlines() if line.strip()]
    assert (
        "fall = self.begin_move(ball, to_anchor=None, by=None, to_point=[0.0, 0.0, 0.0], at_seconds=3, "
        "duration_seconds=2, action_id=\"fall\", easing='ease_in_quad')"
    ) in lines
    assert "self.run_until(4, [fall])" in lines and 'checkpoint(self, "midfall", expected_time=4)' in lines
    assert "self.run_until(5, [fall])" in lines
    assert (
        'vanish = self.begin_fade_object(ball, ink=0, at_seconds=5, duration_seconds=0.3, action_id="vanish", '
        "easing=None)"
    ) in lines
    assert (
        'morph = self.begin_transform(label, to="wave", at_seconds=5, duration_seconds=0.8, action_id="morph", '
        'match="by_symbol", easing=None)'
    ) in lines
    assert "self.run_until(5.3, [vanish, morph])" in lines and "self.run_until(5.8, [morph])" in lines
    assert (
        "slide = self.begin_move(note, to_anchor='bottom_left', by=None, to_point=None, at_seconds=10.1, "
        'duration_seconds=1.2, action_id="slide", easing=None)'
    ) in lines
    # 10.1 + 1.2 is not 11.3 in floating point; the two breakpoints collapse into one and the fade begins once.
    assert code.count("note_away = self.begin_fade_object(") == 1
    assert "self.run_until(11.6, [note_away])" in lines
    module = tmp_path / "scene.py"
    module.write_text(code)
    assert checkpoint_markers(module) == ["midfall"]


def test_project_checks_follow_the_equation_an_object_shows(project_copy: Project) -> None:
    """A transform changes which equation an emphasis resolves against; the message names both equations."""
    report = validate_project(project_copy)
    assert report.ok and report.animation and report.storyboard, report.errors
    animation = report.animation.model_copy(deep=True)
    animation.equations.append(
        animation.equations[0].model_copy(
            update={"id": "gain_only", "typst": "r = g E", "latex": "r = g E", "symbols": {}}
        )
    )
    storyboard = report.storyboard.model_copy(deep=True)
    scene = storyboard.scenes[1]  # the normalization scene: response_curve with P and sigma, the equation block
    scene.objects[1].reveal_at_seconds = None
    scene.actions = [
        scene.actions[0].model_copy(update={"at_seconds": 7, "duration_seconds": 2}),  # raise_pool, emphasizes P
        TransformEquation(
            id="to_gain",
            kind="transform_equation",
            target="normalization_equation",
            to="gain_only",
            at_seconds=9.5,
            duration_seconds=0.5,
        ),
        scene.actions[1].model_copy(update={"at_seconds": 10.5, "duration_seconds": 2}),  # stabilize, emphasizes sigma
    ]
    checked = validate_project(
        project_copy, animation=animation, storyboard=Storyboard.model_validate(storyboard.model_dump(mode="json"))
    )
    assert any(
        "action 'stabilize' emphasizes 'sigma' on 'normalization_equation', but at 10.5s that object shows equation "
        "'gain_only' (transformed from 'schematic_equation' by 'to_gain'), which has no symbol 'sigma'" in e
        for e in checked.errors
    ), checked.errors
    assert any("highlighted symbols ['P', 'sigma'] do not occur in 'gain_only'" in n for n in checked.notices)
    # An undeclared target equation is an error; transforming into the equation already shown is a warning.
    scene.actions[1] = scene.actions[1].model_copy(update={"to": "nowhere"})
    scene.actions.pop()
    missing = validate_project(
        project_copy, animation=animation, storyboard=Storyboard.model_validate(storyboard.model_dump(mode="json"))
    )
    assert any("equation 'nowhere' is not declared" in e for e in missing.errors), missing.errors
    scene.actions[1] = scene.actions[1].model_copy(update={"to": "schematic_equation"})
    same = validate_project(
        project_copy, animation=animation, storyboard=Storyboard.model_validate(storyboard.model_dump(mode="json"))
    )
    assert same.ok and any("which it already shows" in w for w in same.warnings), (same.errors, same.warnings)


def test_project_checks_rest_between_moves_and_large_tables(project_copy: Project) -> None:
    report = validate_project(project_copy)
    assert report.ok and report.animation and report.storyboard and report.style, report.errors
    # The example's data-bound gain sweep validates clean; a second move hard on the heels of the first does not rest.
    assert any(a.id == "gain" and a.kind == "vary_parameter" for a in report.storyboard.actions())
    storyboard = report.storyboard.model_copy(deep=True)
    scene = storyboard.scenes[0]
    scene.actions = [
        *scene.actions,
        MoveObject(
            id="slide", kind="move_object", target="drive_note", by=(0.1, 0), at_seconds=2.5, duration_seconds=1
        ),
        MoveObject(
            id="back", kind="move_object", target="drive_note", by=(-0.1, 0), at_seconds=3.6, duration_seconds=1
        ),
    ]
    hurried = validate_project(project_copy, storyboard=Storyboard.model_validate(storyboard.model_dump(mode="json")))
    assert any("action 'back' moves 'drive_note' 0.10s after 'slide' has finished" in w for w in hurried.warnings), (
        hurried.warnings
    )
    # A parameterised binding on a table above ten thousand rows is slow per frame; the checks say so.
    big = project_copy.root / "data" / "big.csv"
    big.write_text("excitation_E,response_r,condition\n" + "".join(f"{i},{i / 2},low_pool\n" for i in range(10_001)))
    animation = report.animation.model_copy(deep=True)
    animation.sources[0] = animation.sources[0].model_copy(update={"path": "data/big.csv"})
    slow = validate_project(project_copy, animation=animation)
    assert any("10001 rows" in w and "slow above 10000 rows" in w for w in slow.warnings), slow.warnings


def test_action_summaries_for_the_review_ui() -> None:
    from scianim.server.app import action_summary

    board = Storyboard.model_validate(
        _storyboard(
            actions=[
                MOVE,
                FADE_OUT,
                MORPH,
                {**MOVE, "id": "slide", "target": "note", "to_point": None, "to_anchor": "bottom_left"},
                {**MOVE, "id": "nudge", "target": "note", "to_point": None, "by": [0.1, -0.05], "at_seconds": 6},
            ],
            objects=_world_objects(),
        )
    )
    summaries = [action_summary(a) for a in board.actions()]
    assert summaries == [
        "ball moves to (0, 0, 0)",
        "ball fades out",
        "label becomes equation wave (by symbol)",
        "note moves to bottom left",
        "note moves by (0.1, -0.05) of the safe frame",
    ]


def test_tracks_reach_the_scene_end_instead_of_stopping_at_the_fade(project_copy: Project) -> None:
    """The last scene keeps its objects, so an orbit to its end runs to its end; a scene that fades out carries a
    track still moving at the fade's start into `end_scene`, which finishes it during the fade. Before this, both
    stopped `transition_seconds` early, at speed (the Gabor and drop_impact orbits stopped 0.65 s short)."""
    from scianim.codegen.generate import scene_block

    report = validate_project(project_copy)
    assert report.style
    motion = report.style.tokens.motion
    orbit = {"id": "orbit", "kind": "orbit_camera", "to_theta_degrees": 40, "at_seconds": 0, "duration_seconds": 20}
    scene = Storyboard.model_validate(_storyboard(objects=_surface_objects(), actions=[orbit])).scenes[0]
    last = [line.strip() for line in scene_block(scene, motion, is_last=True)]
    assert "self.run_until(20, [orbit])" in last and "self.end_scene(end_seconds=20, keep=True)" in last
    fading = [line.strip() for line in scene_block(scene, motion, is_last=False)]
    fade_start = 20 - motion.transition_seconds
    assert f"self.run_until({fade_start:g}, [orbit])" in fading
    assert "self.end_scene(end_seconds=20, keep=False, carry=[orbit])" in fading
    # A track that ends before the fade begins is not carried.
    short = {**orbit, "duration_seconds": 10}
    scene = Storyboard.model_validate(_storyboard(objects=_surface_objects(), actions=[short])).scenes[0]
    assert "self.end_scene(end_seconds=20, keep=False)" in [
        s.strip() for s in scene_block(scene, motion, is_last=False)
    ]
