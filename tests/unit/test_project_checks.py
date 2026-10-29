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
    rewrite(
        project_copy.storyboard_path,
        "style_role: primary_signal\n        equation:",
        "style_role: neon\n        equation:",
    )
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
    rewrite(
        project_copy.storyboard_path,
        "equation: {id: schematic_equation, highlight: [P, sigma]}",
        "equation: {id: other_equation, highlight: [P, sigma]}",
    )
    report = validate_project(project_copy)
    assert any("equation 'other_equation'" in e for e in report.errors)


def test_hard_milestone_outside_scenes_is_an_error(project_copy: Project) -> None:
    rewrite(
        project_copy.storyboard_path, "start_seconds: 0\n    end_seconds: 6", "start_seconds: 1\n    end_seconds: 6"
    )
    report = validate_project(project_copy)
    assert any("hard milestone 'introduction'" in e for e in report.errors)


def test_storyboard_longer_than_output_is_an_error(project_copy: Project) -> None:
    rewrite(project_copy.storyboard_path, "end_seconds: 18", "end_seconds: 19")
    report = validate_project(project_copy)
    assert any("output duration" in e for e in report.errors)


def test_narration_overrun_is_a_warning(project_copy: Project) -> None:
    long_text = " ".join(["word"] * 120)
    rewrite(
        project_copy.storyboard_path,
        "The response begins with excitatory drive: as the drive grows, so does the response.",
        long_text,
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
    rewrite(target, 'checkpoint(self, "pool_introduced", expected_time=8)', "pass")
    after = validate_project(project_copy)
    assert any("without a checkpoint() marker: ['pool_introduced']" in e for e in after.errors)


def test_motion_rules_are_warnings(project_copy: Project) -> None:
    """The theme's rules of smoothness: linear easing, a lead-in shorter than the pulse, and a rest shorter than
    `motion.hold_seconds` between two motions of one object each draw a warning; the example draws none."""
    from scianim_core import Storyboard

    report = validate_project(project_copy)
    assert report.ok and not report.warnings, report.warnings
    assert report.storyboard is not None and report.style is not None
    motion = report.style.tokens.motion
    assert motion.hold_seconds > 0 and motion.camera_easing == "eased_linear"

    def action(storyboard: Storyboard, action_id: str):
        return next(a for s in storyboard.scenes for a in s.actions if a.id == action_id)

    def warnings_after(change) -> list[str]:
        storyboard = report.storyboard.model_copy(deep=True)
        change(storyboard)
        again = validate_project(project_copy, storyboard=Storyboard.model_validate(storyboard.model_dump(mode="json")))
        return again.warnings

    def linear(storyboard: Storyboard) -> None:
        action(storyboard, "raise_pool").easing = "linear"

    def short_lead_in(storyboard: Storyboard) -> None:
        action(storyboard, "raise_pool").lead_in_seconds = 0.3  # the pulse lasts 0.8 s

    def no_rest(storyboard: Storyboard) -> None:
        action(storyboard, "stabilize").at_seconds = 12.7  # raise_pool ends at 12.5 s

    assert any("constant speed" in w for w in warnings_after(linear))
    assert any("shorter than the term's pulse" in w for w in warnings_after(short_lead_in))
    assert any("the style asks for a rest" in w for w in warnings_after(no_rest))
