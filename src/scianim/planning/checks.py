"""Cross-file project validation (spec sections 5.2, 8.4, 15.1)."""

from __future__ import annotations

import ast
import csv
from dataclasses import dataclass, field
from pathlib import Path

from scianim.config.loader import SpecError
from scianim.families.resolve import FamilyContext, find_family
from scianim.project import Project, scene_class_name
from scianim.styles.resolve import resolve_style
from scianim_core import REGISTRY, AnimationSpec, FamilyManifest, ResolvedStyle, Storyboard
from scianim_core.components import ComparisonPlotParams

NARRATION_OVERRUN_FACTOR = 1.15
NARRATION_UNDERRUN_FACTOR = 0.4


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    animation: AnimationSpec | None = None
    storyboard: Storyboard | None = None
    family: FamilyContext | None = None
    style: ResolvedStyle | None = None

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def note(self, msg: str) -> None:
        self.notices.append(msg)


def checkpoint_markers(scene_module: Path) -> list[str]:
    """Literal snapshot IDs passed to `checkpoint(...)` in generated code."""
    tree = ast.parse(scene_module.read_text(encoding="utf-8"))
    markers: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if (
                name == "checkpoint"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
            ):
                markers.append(node.args[1].value)
    return markers


def csv_columns(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        return next(reader, [])


def check_storyboard(
    animation: AnimationSpec,
    storyboard: Storyboard,
    project: Project,
    style: ResolvedStyle | None,
    report: Report,
) -> None:
    if storyboard.project_id != animation.id:
        report.error(f"storyboard.project_id '{storyboard.project_id}' does not match animation id '{animation.id}'")
    duration = animation.output.duration_seconds
    if storyboard.total_end_seconds > duration + 1e-9:
        report.error(f"storyboard ends at {storyboard.total_end_seconds}s but output duration is {duration}s")
    elif duration - storyboard.total_end_seconds > 1.0 / animation.output.fps:
        report.warn(
            f"storyboard ends at {storyboard.total_end_seconds}s, leaving {duration - storyboard.total_end_seconds:.2f}s of the {duration}s output unplanned"
        )
    for milestone in animation.hard_milestones():
        inside = any(s.start_seconds <= milestone.at_seconds <= s.end_seconds for s in storyboard.scenes)
        if not inside:
            report.error(
                f"hard milestone '{milestone.id}' at {milestone.at_seconds}s falls outside every storyboard scene"
            )
    sources = animation.source_by_id()
    equations = animation.equation_by_id()
    palette = set(style.tokens.palette) if style else None
    wpm = style.tokens.motion.narration_words_per_minute if style else 150.0
    for scene in storyboard.scenes:
        if scene.narration:
            est = scene.narration.estimated_seconds(wpm)
            if est > scene.duration_seconds * NARRATION_OVERRUN_FACTOR:
                report.warn(
                    f"scene '{scene.id}': narration needs about {est:.1f}s at {wpm:g} words/min but the scene lasts {scene.duration_seconds:g}s"
                )
            elif est < scene.duration_seconds * NARRATION_UNDERRUN_FACTOR:
                report.note(f"scene '{scene.id}': narration covers about {est:.1f}s of {scene.duration_seconds:g}s")
        for obj in scene.objects:
            if obj.style_role is not None and palette is not None and obj.style_role not in palette:
                report.error(
                    f"object '{obj.id}': style_role '{obj.style_role}' is not a palette role of style '{style.theme}'; roles: {sorted(palette)}"
                )
            if obj.data is not None:
                source = sources.get(obj.data.source)
                if source is None:
                    report.error(
                        f"object '{obj.id}': data source '{obj.data.source}' is not declared in animation.yaml sources"
                    )
                elif source.type != "csv":
                    report.error(
                        f"object '{obj.id}': data source '{source.id}' has type '{source.type}'; plots need csv"
                    )
                else:
                    path = project.root / source.path
                    if not path.exists():
                        report.error(f"source '{source.id}': file {source.path} not found under {project.root}")
                    else:
                        columns = set(csv_columns(path))
                        wanted = {obj.data.encoding.x, obj.data.encoding.y}
                        if obj.data.encoding.group:
                            wanted.add(obj.data.encoding.group)
                        if obj.data.encoding.error:
                            wanted.add(obj.data.encoding.error)
                        wanted |= {t.column for t in obj.data.transforms}
                        missing = sorted(wanted - columns)
                        if missing:
                            report.error(
                                f"object '{obj.id}': columns {missing} not in {source.path} (has {sorted(columns)})"
                            )
            if obj.equation is not None:
                equation = equations.get(obj.equation.id)
                if equation is None:
                    report.error(
                        f"object '{obj.id}': equation '{obj.equation.id}' is not declared in animation.yaml equations"
                    )
                else:
                    unknown = [h for h in obj.equation.highlight if h not in equation.symbols]
                    if unknown:
                        report.warn(
                            f"object '{obj.id}': highlighted symbols {unknown} are not defined in equation '{equation.id}' symbols"
                        )
                    if style and equation.source_for(style.tokens.typography.equation.engine) is None:
                        report.error(
                            f"object '{obj.id}': equation '{equation.id}' has no '{style.tokens.typography.equation.engine}' source but the style uses that engine"
                        )
            if obj.kind == "comparison_plot" and palette is not None:
                params = obj.typed_params()
                assert isinstance(params, ComparisonPlotParams)
                for condition, role in params.condition_roles.items():
                    if role not in palette:
                        report.error(
                            f"object '{obj.id}': condition_roles['{condition}'] = '{role}' is not a palette role"
                        )
            if obj.kind == "custom":
                builder = obj.params["builder"]
                module_name = builder.split(":")[0].replace(".", "/")
                if not (project.code_dir / f"{module_name}.py").exists():
                    report.error(f"object '{obj.id}': custom builder module code/{module_name}.py not found")
    for constraint in animation.scientific_constraints:
        if constraint.equation and not any(
            o.equation and o.equation.id == constraint.equation for o in storyboard.objects()
        ):
            report.warn(
                f"constraint '{constraint.id}' concerns equation '{constraint.equation}' but no storyboard object shows it"
            )


def check_markers(storyboard: Storyboard, scene_module: Path, report: Report) -> None:
    if not scene_module.exists():
        report.note(f"no scene module at {scene_module}; run `scianim codegen` to generate it")
        return
    try:
        markers = checkpoint_markers(scene_module)
    except SyntaxError as exc:
        report.error(f"{scene_module}: syntax error: {exc}")
        return
    wanted = storyboard.snapshot_ids()
    missing = sorted(set(wanted) - set(markers))
    extra = sorted(set(markers) - set(wanted))
    if missing:
        report.error(f"{scene_module.name}: storyboard snapshots without a checkpoint() marker: {missing}")
    if extra:
        report.error(f"{scene_module.name}: checkpoint() markers not in the storyboard: {extra}")
    duplicates = sorted({m for m in markers if markers.count(m) > 1})
    if duplicates:
        report.error(f"{scene_module.name}: duplicate checkpoint() markers: {duplicates}")


def validate_project(project: Project, require_family: bool = False) -> Report:
    report = Report()
    try:
        animation = project.load_animation()
    except SpecError as exc:
        report.error(exc.message if exc.path is None else f"{exc.path}: {exc.message}")
        return report
    report.animation = animation
    for source in animation.sources:
        if not (project.root / source.path).exists():
            report.error(f"source '{source.id}': file {source.path} not found under {project.root}")
    try:
        report.family = find_family(project.root, animation.family, project.family_search_roots())
    except SpecError as exc:
        (report.error if require_family else report.warn)(exc.message)
    family_manifest: FamilyManifest | None = report.family.manifest if report.family else None
    if family_manifest and family_manifest.style.name != animation.style.name:
        report.note(
            f"project uses style '{animation.style.name}' while family '{family_manifest.id}' defaults to '{family_manifest.style.name}'"
        )
    try:
        report.style = resolve_style(animation.style, project.style_search_dirs(), family_manifest)
    except SpecError as exc:
        report.error(exc.message)
    try:
        storyboard = project.load_storyboard()
    except SpecError as exc:
        report.error(f"{exc.path}: {exc.message}")
        return report
    if storyboard is None:
        report.note("no storyboard.yaml yet")
        return report
    report.storyboard = storyboard
    check_storyboard(animation, storyboard, project, report.style, report)
    if family_manifest:
        unlisted = sorted({o.kind for o in storyboard.objects()} - set(family_manifest.components) - {"custom"})
        if unlisted:
            report.warn(
                f"component kinds {unlisted} are used but not listed in family '{family_manifest.id}' components"
            )
    check_markers(storyboard, project.scene_module_path(animation), report)
    unknown_kinds = sorted({o.kind for o in storyboard.objects()} - set(REGISTRY))
    if unknown_kinds:
        report.error(f"unknown component kinds: {unknown_kinds}")
    report.note(f"scene class: {scene_class_name(animation.id)}")
    return report
