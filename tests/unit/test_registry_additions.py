"""Milestone 2.5 additions: safe expressions, function_plot, relational placement, timed reveals."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from scianim.cli import app
from scianim.codegen.generate import generate_scene_module
from scianim.planning.checks import validate_project
from scianim.project import Project
from scianim_core import Storyboard
from scianim_core.components import FunctionPlotParams, validate_params
from scianim_core.expressions import compile_expression, sample, validate_expression


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('true')",
        "x.real",
        "lambda: 1",
        "[1, 2]",
        "y + 1",
        "open('f')",
        "x if x else 0",
        "'a' * 3",
        "x ** -1 .__class__",
    ],
)
def test_unsafe_or_unknown_expressions_are_rejected(expression: str) -> None:
    with pytest.raises(ValueError):
        validate_expression(expression)


def test_expressions_evaluate_with_caret_power_and_nan_on_domain_errors() -> None:
    gaussian = compile_expression("exp(-((x - 2)^2) / (2 * 1.5^2))")
    assert gaussian(x=2.0) == pytest.approx(1.0)
    assert gaussian(x=3.5) == pytest.approx(math.exp(-0.5))
    assert math.isnan(compile_expression("1 / x")(x=0.0))
    assert math.isnan(compile_expression("sqrt(x)")(x=-1.0))
    assert sample("2 * x + pi", [0, 1]) == pytest.approx([math.pi, 2 + math.pi])


def test_function_plot_params_validate_expressions_and_ranges() -> None:
    params = validate_params(
        "function_plot",
        {"x_label": "x", "y_label": "y", "x_range": [-10, 10], "series": [{"label": "g", "expression": "exp(-x^2)"}]},
    )
    assert isinstance(params, FunctionPlotParams)
    with pytest.raises(ValueError, match="unknown name 'y'"):
        validate_params(
            "function_plot",
            {"x_label": "x", "y_label": "y", "x_range": [0, 1], "series": [{"label": "g", "expression": "y"}]},
        )
    with pytest.raises(ValueError, match="outside x_range"):
        validate_params(
            "function_plot",
            {
                "x_label": "x",
                "y_label": "y",
                "x_range": [0, 1],
                "series": [{"label": "g", "expression": "x"}],
                "markers": [{"x": 5}],
            },
        )
    with pytest.raises(ValueError, match="low < high"):
        validate_params(
            "function_plot",
            {"x_label": "x", "y_label": "y", "x_range": [1, 0], "series": [{"label": "g", "expression": "x"}]},
        )


def storyboard_with(objects: list[dict], snapshots: list[dict] | None = None) -> dict:
    return {
        "schema_version": "1.0",
        "project_id": "p",
        "based_on_animation_revision": "x",
        "scenes": [
            {
                "id": "s",
                "start_seconds": 0,
                "end_seconds": 10,
                "purpose": "p",
                "objects": objects,
                "snapshots": snapshots or [],
            }
        ],
    }


def test_relational_placement_must_reference_an_earlier_object() -> None:
    good = storyboard_with(
        [
            {"id": "a", "kind": "text_caption", "params": {"text": "A", "role": "title"}},
            {"id": "b", "kind": "text_caption", "params": {"text": "B", "below": "a"}},
        ]
    )
    Storyboard.model_validate(good)
    bad = storyboard_with([{"id": "b", "kind": "text_caption", "params": {"text": "B", "below": "a"}}])
    with pytest.raises(ValidationError, match="must name an object declared earlier"):
        Storyboard.model_validate(bad)
    both = storyboard_with(
        [
            {"id": "a", "kind": "text_caption", "params": {"text": "A"}},
            {"id": "b", "kind": "text_caption", "params": {"text": "B", "below": "a", "right_of": "a"}},
        ]
    )
    with pytest.raises(ValidationError, match="either 'below' or 'right_of'"):
        Storyboard.model_validate(both)


def test_reveal_time_must_lie_inside_the_scene() -> None:
    with pytest.raises(ValidationError, match="reveal_at_seconds=20"):
        Storyboard.model_validate(
            storyboard_with([{"id": "a", "kind": "text_caption", "params": {"text": "A"}, "reveal_at_seconds": 20}])
        )


def test_codegen_orders_timed_reveals_and_checkpoints(project_copy: Project) -> None:
    text = project_copy.storyboard_path.read_text()
    text = text.replace(
        "      - id: drive_curve\n        kind: scientific_plot\n",
        "      - id: drive_curve\n        kind: scientific_plot\n        reveal_at_seconds: 3\n",
    )
    project_copy.storyboard_path.write_text(text)
    report = validate_project(project_copy)
    assert report.ok, report.errors
    code = generate_scene_module(report.animation, report.storyboard, report.style)
    scene = code.split("# --- scene 'normalization'")[0]
    order = [
        line.strip()
        for line in scene.splitlines()
        if line.strip().startswith(("reveal_", "self.run_until(", "self.wait_until(", "checkpoint("))
    ]
    assert order == [
        "reveal_drive_caption = self.begin_reveal(drive_caption)",
        "self.run_until(0.85, [reveal_drive_caption])",
        "self.wait_until(0.85)",
        "self.wait_until(2)",
        "reveal_drive_note = self.begin_reveal(drive_note)",
        "self.run_until(2.85, [reveal_drive_note])",
        "self.wait_until(2.85)",
        "self.wait_until(3)",
        "reveal_drive_curve = self.begin_reveal(drive_curve)",
        "self.run_until(3.85, [reveal_drive_curve])",
        "self.wait_until(3.85)",
        "self.wait_until(4)",
        'checkpoint(self, "excitation_visible", expected_time=4)',
        "self.wait_until(5.35)",
    ]


def test_registry_command_lists_kinds_and_describes_parameters() -> None:
    runner = CliRunner()
    listing = runner.invoke(app, ["registry"])
    assert listing.exit_code == 0
    for kind in ("text_caption", "scientific_plot", "function_plot", "equation_block", "comparison_plot", "custom"):
        assert kind in listing.stdout
    detail = runner.invoke(app, ["registry", "function_plot"])
    assert detail.exit_code == 0 and "expression" in detail.stdout and "markers" in detail.stdout
    unknown = runner.invoke(app, ["registry", "hologram"])
    assert unknown.exit_code == 1


def test_orientation_tuning_template_validates_in_project_mode() -> None:
    """The Milestone 5 loop's output (cited caption, graph, population, glyph) validates as a template."""
    example = (
        Path(__file__).resolve().parents[2]
        / "examples"
        / "families"
        / "computational_neuroscience"
        / "orientation_tuning"
    )
    result = CliRunner().invoke(app, ["validate", str(example)])
    assert result.exit_code == 0, result.stdout
    assert "0 errors, 0 warnings" in result.stdout


def test_prf_tuning_template_validates_in_project_mode() -> None:
    """The dry-run storyboard (function_plot, markers, `below`, `reveal_at_seconds`) validates as a read-only template."""
    example = (
        Path(__file__).resolve().parents[2] / "examples" / "families" / "computational_neuroscience" / "prf_tuning"
    )
    result = CliRunner().invoke(app, ["validate", str(example)])
    assert result.exit_code == 0, result.stdout
    assert "0 errors, 0 warnings" in result.stdout
