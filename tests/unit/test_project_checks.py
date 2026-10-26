"""Cross-file checks, narration estimates, marker parity and code generation (workspace layout)."""

from __future__ import annotations

from pathlib import Path

from scianim.codegen.generate import generate_scene_module, write_scene_module
from scianim.planning.checks import checkpoint_markers, validate_project
from scianim.project import Project


def rewrite(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert text.count(old) == 1, f"anchor {old!r} not unique in {path}"
    path.write_text(text.replace(old, new))


def test_example_project_validates_by_ancestry(project_copy: Project) -> None:
    report = validate_project(project_copy, require_family=True)
    assert report.ok, report.errors
    assert report.style is not None and report.family is not None
    assert report.family.manifest.id == "computational_neuroscience"
    assert report.family_via == "ancestor"
    assert report.groups == []
    assert report.workspace == project_copy.root.parents[2]
    assert set(report.source_paths) == {"responses"}


def test_unknown_data_source_is_an_error(project_copy: Project) -> None:
    rewrite(
        project_copy.storyboard_path,
        "source: responses\n          encoding: {x: excitation_E, y: response_r, group: condition}\n          transforms",
        "source: nothing\n          encoding: {x: excitation_E, y: response_r, group: condition}\n          transforms",
    )
    report = validate_project(project_copy)
    assert any("data source 'nothing'" in e for e in report.errors)


def test_unknown_style_role_is_an_error(project_copy: Project) -> None:
    rewrite(project_copy.storyboard_path, "style_role: primary_signal", "style_role: neon")
    report = validate_project(project_copy)
    assert any("style_role 'neon'" in e for e in report.errors)


def test_missing_csv_column_is_an_error(project_copy: Project) -> None:
    rewrite(
        project_copy.storyboard_path,
        "encoding: {x: excitation_E, y: response_r, group: condition}\n          transforms",
        "encoding: {x: excitation_Q, y: response_r, group: condition}\n          transforms",
    )
    report = validate_project(project_copy)
    assert any("excitation_Q" in e for e in report.errors)


def test_unknown_equation_reference_is_an_error(project_copy: Project) -> None:
    rewrite(project_copy.storyboard_path, "equation: {id: schematic_equation}", "equation: {id: other_equation}")
    report = validate_project(project_copy)
    assert any("equation 'other_equation'" in e for e in report.errors)


def test_hard_milestone_outside_scenes_is_an_error(project_copy: Project) -> None:
    rewrite(
        project_copy.storyboard_path, "start_seconds: 15\n    end_seconds: 30", "start_seconds: 15\n    end_seconds: 29"
    )
    rewrite(
        project_copy.storyboard_path, "start_seconds: 30\n    end_seconds: 45", "start_seconds: 31\n    end_seconds: 45"
    )
    report = validate_project(project_copy)
    assert any("hard milestone 'equation'" in e for e in report.errors)


def test_storyboard_longer_than_output_is_an_error(project_copy: Project) -> None:
    rewrite(project_copy.storyboard_path, "end_seconds: 60", "end_seconds: 61")
    report = validate_project(project_copy)
    assert any("output duration" in e for e in report.errors)


def test_narration_overrun_is_a_warning(project_copy: Project) -> None:
    long_text = " ".join(["word"] * 120)
    rewrite(
        project_copy.storyboard_path, "With identical excitation, a stronger pool compresses the response.", long_text
    )
    report = validate_project(project_copy)
    assert report.ok, report.errors
    assert any("narration needs about" in w for w in report.warnings)


def test_custom_builder_found_in_family_components(project_copy: Project) -> None:
    rewrite(
        project_copy.storyboard_path,
        "    snapshots:\n      - id: excitation_visible",
        '      - id: sketch\n        kind: custom\n        params: {builder: "pool_sketch:build"}\n    snapshots:\n      - id: excitation_visible',
    )
    report = validate_project(project_copy)
    assert any("custom builder module 'pool_sketch' not found" in e for e in report.errors)
    components = project_copy.root.parents[0] / "components"
    components.mkdir(exist_ok=True)
    (components / "pool_sketch.py").write_text(
        "def build(scene, object_id, tokens, arguments, **kwargs):\n    raise NotImplementedError\n"
    )
    assert validate_project(project_copy).ok


def test_codegen_markers_match_storyboard(project_copy: Project) -> None:
    report = validate_project(project_copy)
    assert report.animation and report.storyboard and report.style
    target = write_scene_module(
        report.animation, report.storyboard, report.style, project_copy.scene_module_path(report.animation)
    )
    assert checkpoint_markers(target) == report.storyboard.snapshot_ids()
    assert validate_project(project_copy).ok


def test_codegen_is_deterministic_and_structured(project_copy: Project) -> None:
    report = validate_project(project_copy)
    assert report.animation and report.storyboard and report.style
    first = generate_scene_module(report.animation, report.storyboard, report.style)
    second = generate_scene_module(report.animation, report.storyboard, report.style)
    assert first == second
    assert first.count("self.begin_scene(") == len(report.storyboard.scenes)
    assert first.count("keep=True") == 1 and first.count("keep=False") == len(report.storyboard.scenes) - 1
    assert "import manim" not in first  # only the bridge API is used
    compile(first, "generated", "exec")


def test_removed_marker_is_detected(project_copy: Project) -> None:
    report = validate_project(project_copy)
    assert report.animation and report.storyboard and report.style
    target = write_scene_module(
        report.animation, report.storyboard, report.style, project_copy.scene_module_path(report.animation)
    )
    rewrite(target, 'checkpoint(self, "pool_introduced", expected_time=24)', "pass")
    after = validate_project(project_copy)
    assert any("without a checkpoint() marker: ['pool_introduced']" in e for e in after.errors)
