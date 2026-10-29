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
