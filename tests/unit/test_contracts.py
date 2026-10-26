"""Schema basics, hard constraints and registry validation (test matrix rows 1 to 4)."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from pydantic import ValidationError

from scianim.config.loader import SpecError, detect_kind, load_spec, load_yaml
from scianim_core import AnimationSpec, FamilyManifest, GroupManifest, Storyboard, StyleSheet, WorkspaceManifest
from scianim_core.schemas import render_schemas

REPO = Path(__file__).resolve().parents[2]
EXAMPLE = REPO / "examples" / "families" / "computational_neuroscience" / "divisive_normalization"
ANIMATION = EXAMPLE / "animation.yaml"
STORYBOARD = EXAMPLE / "storyboard.yaml"


@pytest.fixture
def animation_data() -> dict:
    return load_yaml(ANIMATION)


@pytest.fixture
def storyboard_data() -> dict:
    return load_yaml(STORYBOARD)


@pytest.mark.parametrize(
    ("path", "kind", "model"),
    [
        (ANIMATION, "animation", AnimationSpec),
        (STORYBOARD, "storyboard", Storyboard),
        (REPO / "styles/default/0.1.0/style.yaml", "style", StyleSheet),
        (REPO / "styles/tomas_scientific/0.1.0/style.yaml", "style", StyleSheet),
        (REPO / "examples/families/computational_neuroscience/family.yaml", "family", FamilyManifest),
    ],
)
def test_examples_load(path: Path, kind: str, model: type) -> None:
    detected, loaded = load_spec(path)
    assert detected == kind
    assert isinstance(loaded, model)


def test_example_animation_has_no_family_key(animation_data: dict) -> None:
    assert "family" not in animation_data  # the nearest family.yaml is authoritative
    assert AnimationSpec.model_validate(animation_data).family is None


def test_kind_detection_by_content_and_name(tmp_path: Path) -> None:
    assert detect_kind({"schema_version": "1.0", "id": "x", "tags": ["a"]}) == "group"
    assert detect_kind({"schema_version": "1.0", "id": "x"}) == "workspace"
    assert detect_kind({"output": {}, "objective": "x"}) == "animation"
    assert detect_kind({}, tmp_path / "group.yaml") == "group"
    GroupManifest.model_validate(
        {"schema_version": "1.0", "id": "perception", "style": {"overrides": {"palette.emphasis": "#000000"}}}
    )
    WorkspaceManifest.model_validate({"schema_version": "1.0", "id": "lab"})
    with pytest.raises(ValidationError):
        GroupManifest.model_validate({"schema_version": "1.0", "id": "perception", "environment": {"manager": "uv"}})


def expect_error(model: type, data: dict, fragment: str) -> None:
    with pytest.raises(ValidationError) as info:
        model.model_validate(data)
    assert fragment in str(info.value)


def test_aspect_ratio_must_match_dimensions(animation_data: dict) -> None:
    animation_data["output"]["width_px"] = 1000
    expect_error(AnimationSpec, animation_data, "does not match aspect_ratio")


def test_negative_duration_rejected(animation_data: dict) -> None:
    animation_data["output"]["duration_seconds"] = -5
    expect_error(AnimationSpec, animation_data, "greater than 0")


def test_unknown_top_level_key_rejected(animation_data: dict) -> None:
    animation_data["narrative"] = "oops"
    expect_error(AnimationSpec, animation_data, "Extra inputs are not permitted")


def test_path_escape_rejected(animation_data: dict) -> None:
    animation_data["sources"][0]["path"] = "../elsewhere/data.csv"
    expect_error(AnimationSpec, animation_data, "escapes the project directory")


def test_absolute_path_rejected(animation_data: dict) -> None:
    animation_data["sources"][0]["path"] = "/tmp/data.csv"
    expect_error(AnimationSpec, animation_data, "relative to the project directory")


def test_asset_uri_accepted(animation_data: dict) -> None:
    animation_data["sources"][0]["path"] = "asset://shared/responses.csv"
    assert AnimationSpec.model_validate(animation_data).sources[0].path == "asset://shared/responses.csv"
    animation_data["sources"][0]["path"] = "asset://../escape.csv"
    with pytest.raises(ValidationError):
        AnimationSpec.model_validate(animation_data)


def test_milestone_beyond_duration_rejected(animation_data: dict) -> None:
    animation_data["timeline"][0]["at_seconds"] = 61
    expect_error(AnimationSpec, animation_data, "beyond the output duration")


def test_constraint_equation_must_exist(animation_data: dict) -> None:
    animation_data["scientific_constraints"][0]["equation"] = "missing_eq"
    expect_error(AnimationSpec, animation_data, "unknown equation")


def test_equation_needs_a_source(animation_data: dict) -> None:
    animation_data["equations"][0].pop("typst")
    animation_data["equations"][0].pop("latex")
    expect_error(AnimationSpec, animation_data, "needs a 'typst' or 'latex' source")


def test_duplicate_ids_rejected(animation_data: dict) -> None:
    animation_data["timeline"].append(copy.deepcopy(animation_data["timeline"][0]))
    expect_error(AnimationSpec, animation_data, "duplicate milestone")


def test_snapshot_outside_scene_rejected(storyboard_data: dict) -> None:
    storyboard_data["scenes"][0]["snapshots"][0]["at_seconds"] = 20
    expect_error(Storyboard, storyboard_data, "lies outside scene")


def test_overlapping_scenes_rejected(storyboard_data: dict) -> None:
    storyboard_data["scenes"][1]["start_seconds"] = 3
    expect_error(Storyboard, storyboard_data, "must not overlap")


def test_unknown_component_kind_rejected(storyboard_data: dict) -> None:
    storyboard_data["scenes"][0]["objects"][0]["kind"] = "hologram"
    with pytest.raises(ValidationError):
        Storyboard.model_validate(storyboard_data)


def test_bad_params_rejected(storyboard_data: dict) -> None:
    storyboard_data["scenes"][0]["objects"][2]["params"]["bogus"] = 1
    expect_error(Storyboard, storyboard_data, "invalid params for kind 'scientific_plot'")


def test_plot_requires_data_binding(storyboard_data: dict) -> None:
    storyboard_data["scenes"][0]["objects"][2].pop("data")
    expect_error(Storyboard, storyboard_data, "requires a 'data' binding")


def test_equation_block_requires_equation(storyboard_data: dict) -> None:
    storyboard_data["scenes"][1]["objects"][1].pop("equation")
    expect_error(Storyboard, storyboard_data, "requires an 'equation' reference")


def test_custom_requires_builder(storyboard_data: dict) -> None:
    storyboard_data["scenes"][0]["objects"].append({"id": "weird", "kind": "custom", "params": {}})
    expect_error(Storyboard, storyboard_data, "builder")
    storyboard_data["scenes"][0]["objects"][-1]["params"] = {"builder": "custom:build_weird"}
    Storyboard.model_validate(storyboard_data)


def test_narration_marks_unique(storyboard_data: dict) -> None:
    storyboard_data["scenes"][1]["narration"]["text"] = 'a <mark name="x"/> b <mark name="x"/>'
    expect_error(Storyboard, storyboard_data, "duplicate narration mark")


def test_invalid_color_token_rejected() -> None:
    data = load_yaml(REPO / "styles/default/0.1.0/style.yaml")
    data["palette"]["primary_signal"] = "blue"
    expect_error(StyleSheet, data, "String should match pattern")


def test_unknown_style_key_rejected() -> None:
    data = load_yaml(REPO / "styles/tomas_scientific/0.1.0/style.yaml")
    data["typography"]["title"]["kerning"] = 1
    expect_error(StyleSheet, data, "Extra inputs are not permitted")


def test_inherits_must_pin_a_version() -> None:
    data = load_yaml(REPO / "styles/tomas_scientific/0.1.0/style.yaml")
    assert data["inherits"] == "default@0.1.0"
    data["inherits"] = "default"
    expect_error(StyleSheet, data, "String should match pattern")


def test_loader_reports_readable_errors(tmp_path: Path) -> None:
    bad = tmp_path / "animation.yaml"
    bad.write_text((ANIMATION.read_text()).replace("fps: 30", "fps: -1"))
    with pytest.raises(SpecError) as info:
        load_spec(bad)
    assert "output.fps" in info.value.message


def test_schema_export_is_deterministic() -> None:
    first = render_schemas()
    second = render_schemas()
    assert first == second
    assert {
        "animation.schema.json",
        "storyboard.schema.json",
        "style.schema.json",
        "family.schema.json",
        "group.schema.json",
        "workspace.schema.json",
        "revision.schema.json",
        "render_job.schema.json",
        "artifact_manifest.schema.json",
    } <= set(first)
