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
    with pytest.raises(ValueError, match="other than 'x'"):
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
    rejected("needs a function_plot", target="label")
    rejected("declares no parameter 'tau'", parameter="tau")
    rejected("outside scene", at_seconds=16)
    rejected("starts before 'label' is revealed", at_seconds=1)
    rejected("must reference an equation whose highlight includes", emphasize=["plot"])
    rejected("not an object of scene", emphasize=["ghost"])
    rejected("one thing plays at a time", at_seconds=1.5, emphasize=[])  # the label is revealed at 2 s, inside
    with pytest.raises(ValueError, match="one action plays at a time"):
        Storyboard.model_validate(_storyboard(actions=[SWEEP, {**SWEEP, "id": "again", "at_seconds": 8}]))
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
    assert lines[begin + 1] == "self.vary_until(widen, 8)"
    assert lines[begin + 2] == "self.wait_until(8)"
    assert lines[begin + 3] == 'checkpoint(self, "halfway", expected_time=8)'
    assert lines[begin + 4] == "self.vary_until(widen, 11)"
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
    assert "raise_pool" not in expected_objects(report.storyboard, "normalization", 8)
    assert "raise_pool" in expected_objects(report.storyboard, "normalization", 8.5)


def test_project_checks_warn_about_late_sweeps_and_unnamed_parameters(project_copy: Project) -> None:
    report = validate_project(project_copy)
    assert report.ok and not report.warnings, report.warnings
    storyboard = report.storyboard.model_copy(deep=True)
    assert storyboard is not None
    scene = storyboard.scenes[1]
    scene.actions[0].at_seconds = 7.5  # the equation is still fading in at 7.5 s
    late = validate_project(project_copy, storyboard=Storyboard.model_validate(storyboard.model_dump(mode="json")))
    assert any("will start late" in w for w in late.warnings), late.warnings
    storyboard = report.storyboard.model_copy(deep=True)
    plot = storyboard.scenes[1].objects[0]
    plot.params["parameters"] = {"sigma": 1, "P": 1, "gain": 2}
    plot.params["series"] = [{"label": "schematic response", "expression": "gain * x / (sigma + P)"}]
    renamed = validate_project(project_copy, storyboard=Storyboard.model_validate(storyboard.model_dump(mode="json")))
    assert any("parameters ['gain'] are not symbols" in w for w in renamed.warnings), renamed.warnings
