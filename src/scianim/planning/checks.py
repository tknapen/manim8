"""Cross-file project validation (spec sections 4.1, 5.2, 8.4, 15.1)."""

from __future__ import annotations

import ast
import csv
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any

from scianim.config.loader import SpecError
from scianim.families.resolve import FamilyContext, GroupContext, locate_family, resolve_asset
from scianim.patterns import load_library, scene_pattern_findings
from scianim.project import Project, scene_class_name
from scianim.styles.resolve import resolve_style
from scianim_core import REGISTRY, AnimationSpec, FamilyManifest, ResolvedStyle, Storyboard
from scianim_core.animation import OutputSpec
from scianim_core.common import is_asset_uri
from scianim_core.components import (
    PARAMETRIC_KINDS,
    CaptionWithCitationParams,
    ComparisonPlotParams,
    FunctionPlotParams,
    NetworkGraphParams,
)
from scianim_core.storyboard import (
    STOP_REST_SECONDS,
    STOP_SPACING_SECONDS,
    Emphasize,
    MoveObject,
    OrbitCamera,
    Scene,
    SceneObject,
    Snapshot,
    TransformEquation,
    VaryParameter,
)
from scianim_core.timing import frames_for

NARRATION_OVERRUN_FACTOR = 1.15
NARRATION_UNDERRUN_FACTOR = 0.4
LARGE_TABLE_ROWS = 10_000
"""A data-bound sweep recomputes its series from the table on every frame; above this many rows it is slow."""


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    animation: AnimationSpec | None = None
    storyboard: Storyboard | None = None
    family: FamilyContext | None = None
    family_via: str | None = None
    groups: list[GroupContext] = field(default_factory=list)
    style: ResolvedStyle | None = None
    workspace: Path | None = None
    source_paths: dict[str, Path] = field(default_factory=dict)
    """Resolved absolute path per source id (project files and materialized assets alike)."""

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


def csv_row_count(path: Path) -> int:
    with path.open(newline="", encoding="utf-8") as handle:
        return max(0, sum(1 for _ in csv.reader(handle)) - 1)


def builder_module_path(module_name: str, project: Project, family: FamilyContext | None) -> Path | None:
    """The file a custom builder's module resolves to: the project's `code/` first, then the family's components."""
    relative = module_name.replace(".", "/") + ".py"
    for directory in (project.code_dir, family.components_dir if family is not None else None):
        if directory is not None and (directory / relative).exists():
            return directory / relative
    return None


def builder_module_exists(module_name: str, project: Project, family: FamilyContext | None) -> bool:
    return builder_module_path(module_name, project, family) is not None


def time_based_functions(path: Path) -> list[str]:
    """The functions and lambdas of a builder module that take a `dt` parameter. Manim treats an updater with one
    as time-based and advances it in one step when it fast-forwards a play, so a checkpoint reached while one runs
    is approximate (the bridge records `fidelity: approximate`)."""
    found: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            arguments = node.args
            names = [a.arg for a in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)]
            if "dt" in names:
                found.append(f"{getattr(node, 'name', 'a lambda')} (line {node.lineno})")
    return found


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
            f"storyboard ends at {storyboard.total_end_seconds}s, leaving "
            f"{duration - storyboard.total_end_seconds:.2f}s of the {duration}s output unplanned"
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
                    f"scene '{scene.id}': narration needs about {est:.1f}s at {wpm:g} words/min "
                    f"but the scene lasts {scene.duration_seconds:g}s"
                )
            elif est < scene.duration_seconds * NARRATION_UNDERRUN_FACTOR:
                report.note(f"scene '{scene.id}': narration covers about {est:.1f}s of {scene.duration_seconds:g}s")
        for obj in scene.objects:
            if obj.style_role is not None and palette is not None and obj.style_role not in palette:
                report.error(
                    f"object '{obj.id}': style_role '{obj.style_role}' is not a palette role of style "
                    f"'{style.theme}'; roles: {sorted(palette)}"  # type: ignore[union-attr]
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
                    path = report.source_paths.get(source.id)
                    if path is not None and path.exists():
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
                        if obj.data.parameters():
                            rows = csv_row_count(path)
                            if rows > LARGE_TABLE_ROWS:
                                report.warn(
                                    f"object '{obj.id}': its binding names parameters {sorted(obj.data.parameters())} "
                                    f"and {source.path} has {rows} rows; a sweep recomputes the series every frame, "
                                    f"which is slow above {LARGE_TABLE_ROWS} rows"
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
                            f"object '{obj.id}': equation '{equation.id}' has no "
                            f"'{style.tokens.typography.equation.engine}' source but the style uses that engine"
                        )
            if obj.kind == "comparison_plot" and palette is not None:
                params = obj.typed_params()
                assert isinstance(params, ComparisonPlotParams)
                for condition, role in params.condition_roles.items():
                    if role not in palette:
                        report.error(
                            f"object '{obj.id}': condition_roles['{condition}'] = '{role}' is not a palette role"
                        )
            if obj.kind == "function_plot" and palette is not None:
                params = obj.typed_params()
                assert isinstance(params, FunctionPlotParams)
                for role in [s.style_role for s in params.series] + [m.style_role for m in params.markers]:
                    if role is not None and role not in palette:
                        report.error(f"object '{obj.id}': style role '{role}' is not a palette role")
            if obj.kind in PARAMETRIC_KINDS:
                declared = getattr(obj.typed_params(), "parameters", {})
                equation = equations.get(obj.equation.id) if obj.equation is not None else None
                if equation is not None:
                    unnamed = sorted(set(declared) - set(equation.symbols))
                    if unnamed:
                        report.warn(
                            f"object '{obj.id}': parameters {unnamed} are not symbols of equation '{equation.id}'; "
                            "name them after the symbols so an emphasized term and the curve agree"
                        )
            if obj.kind == "caption_with_citation":
                params = obj.typed_params()
                assert isinstance(params, CaptionWithCitationParams)
                if params.source not in sources:
                    report.error(
                        f"object '{obj.id}': cites source '{params.source}' which is not declared in animation.yaml sources"
                    )
            if obj.kind == "network_graph" and palette is not None:
                params = obj.typed_params()
                assert isinstance(params, NetworkGraphParams)
                for role in [n.style_role for n in params.nodes] + [e.style_role for e in params.edges]:
                    if role is not None and role not in palette:
                        report.error(f"object '{obj.id}': style role '{role}' is not a palette role")
            if obj.kind == "custom":
                module_name = obj.params["builder"].split(":")[0]
                if not builder_module_exists(module_name, project, report.family):
                    where = f"code/ or {report.family.components_dir}" if report.family else "code/"
                    report.error(f"object '{obj.id}': custom builder module '{module_name}' not found in {where}")
        if style is not None:
            check_actions(scene, style, animation.output.fps, report)
            check_equation_transforms(scene, equations, style.tokens.typography.equation.engine, report)
    if style is not None:
        check_stops(storyboard, style, animation.output, project, report)
    if any(scene.patterns for scene in storyboard.scenes):
        check_patterns(storyboard, report)
    for constraint in animation.scientific_constraints:
        if constraint.equation and not any(
            o.equation and o.equation.id == constraint.equation for o in storyboard.objects()
        ):
            report.warn(
                f"constraint '{constraint.id}' concerns equation '{constraint.equation}' but no storyboard object shows it"
            )


def check_patterns(storyboard: Storyboard, report: Report) -> None:
    """The library patterns scenes name exist, and each scene uses something its patterns are realized with."""
    try:
        library = load_library()
    except SpecError as exc:
        report.error(f"the patterns scenes name cannot be checked: {exc}")
        return
    errors, warnings = scene_pattern_findings(storyboard, library)
    for message in errors:
        report.error(message)
    for message in warnings:
        report.warn(message)


def check_actions(scene: Scene, style: ResolvedStyle, fps: float, report: Report) -> None:
    """Warn about a checkpoint that falls while an object is still fading in, about a track that the scene's
    fade-out would cut short, and about motion that breaks the style's rules of smoothness: a linear profile,
    a lead-in shorter than the pulse, or a rest shorter than `motion.hold_seconds` between two motions of one
    object. A move that rises to rest (`ease_out_quad`) followed by one that falls from rest (`ease_in_quad`) is
    one ballistic arc, which does not pause at its apex, so no rest is asked between its halves. Tracks run
    concurrently, so nothing starts late because of a reveal."""
    motion = style.tokens.motion
    fade_start = scene.end_seconds - motion.transition_seconds
    frame = 1.0 / fps
    for obj in scene.objects:
        begins = scene.start_seconds if obj.reveal_at_seconds is None else obj.reveal_at_seconds
        until = begins + motion.reveal_seconds
        for snap in scene.snapshots:
            if begins + frame < snap.at_seconds < until - frame:
                report.warn(
                    f"snapshot '{snap.id}' at {snap.at_seconds:g}s falls while '{obj.id}' is still fading in "
                    f"(until {until:.2f}s); move the snapshot or the reveal"
                )
        if obj.reveal_at_seconds is not None and until > fade_start + 1e-9:
            report.warn(
                f"object '{obj.id}' is revealed at {begins:g}s and would still be fading in when scene "
                f"'{scene.id}' starts fading out at {fade_start:.2f}s"
            )
    for action in scene.actions:
        if action.kind != "orbit_camera" and action.end_seconds > fade_start + 1e-9:  # a camera may keep turning
            report.warn(
                f"action '{action.id}' ends at {action.end_seconds:g}s, inside the fade-out of scene "
                f"'{scene.id}' that begins at {fade_start:.2f}s"
            )
        if getattr(action, "easing", None) == "linear":
            preferred = (motion.camera_easing or motion.easing) if action.kind == "orbit_camera" else motion.easing
            report.warn(
                f"action '{action.id}' moves at constant speed from its first frame to its last (easing: linear); "
                f"the style asks for slow in, slow out: omit `easing` to use `{preferred}`, or keep linear only "
                "for a motion that should read as mechanical"
            )
        if (
            isinstance(action, VaryParameter)
            and action.emphasize
            and 0 < action.lead_in_seconds < motion.emphasis_seconds - 1e-9
        ):
            report.warn(
                f"action '{action.id}': its lead-in ({action.lead_in_seconds:g}s) is shorter than the term's pulse "
                f"({motion.emphasis_seconds:g}s), so the value starts moving while the term is still growing; "
                "give the lead-in at least the pulse"
            )
    if motion.hold_seconds > 0:
        motions = [a for a in scene.actions if isinstance(a, VaryParameter | MoveObject)]
        for earlier in motions:
            for later in motions:
                if later is earlier or later.target != earlier.target or type(later) is not type(earlier):
                    continue
                if (
                    isinstance(earlier, MoveObject)
                    and earlier.easing == "ease_out_quad"
                    and later.easing == "ease_in_quad"  # the halves of one arc
                ):
                    continue
                starts = later.moves_at_seconds if isinstance(later, VaryParameter) else later.at_seconds
                rest = starts - earlier.end_seconds
                if -1e-9 <= rest < motion.hold_seconds - 1e-9:
                    report.warn(
                        f"action '{later.id}' moves '{later.target}' {rest:.2f}s after '{earlier.id}' has finished; "
                        f"the style asks for a rest of {motion.hold_seconds:g}s so the end state is seen before it "
                        "changes again: start it later"
                        + (" or lengthen its lead-in" if isinstance(later, VaryParameter) else "")
                    )


def check_stops(
    storyboard: Storyboard, style: ResolvedStyle, output: OutputSpec, project: Project, report: Report
) -> None:
    """The rules a stop keeps (ADR-045), so that a player can hold the clip there on exactly the frame the scene
    reached. A stop needs a rest: nothing may reveal, move or fade in the 0.3 s before it (an action may start at
    the stop), because a player that cannot watch frames pauses up to that much early and then seeks to the stop.
    It may not sit on a scene's first frame or on the clip's last (the player's start and end holds show those),
    within 0.5 s of another stop, or where its checkpoint would be approximate. A camera orbit that turns across
    a stop, or in its rest, is refused unless the stop names it in `stop_through`, which accepts that a hold there
    freezes the camera mid-turn (the warning `stop_freezes_camera`)."""
    stops = storyboard.stops()
    if not stops:
        return
    motion = style.tokens.motion
    fps = output.fps
    total_frames = frames_for(output.duration_seconds, fps)
    fades = [
        (scene.id, max(scene.end_seconds - motion.transition_seconds, scene.start_seconds), scene.end_seconds)
        for scene in storyboard.scenes[:-1]
    ]
    time_based: dict[str, list[str]] = {}
    for scene, snap in stops:
        t = snap.at_seconds
        where = f"stop '{snap.id}' at {t:g}s"
        frame = frames_for(t, fps)
        first = next((s for s in storyboard.scenes if frames_for(s.start_seconds, fps) == frame), None)
        if first is not None:
            report.error(
                f"{where} is on the first frame of scene '{first.id}', before anything in it moves; a player holds "
                "the clip's start by itself, so put the stop where a part of the motion has ended"
            )
        if frame >= total_frames - 1:
            report.error(
                f"{where} is on the clip's last frame (frame {total_frames - 1} at {fps:g} fps); a player holds the "
                "end by itself, so remove the stop or put it where a part of the motion has ended"
            )
        orbits = {a.id: a for a in scene.actions if isinstance(a, OrbitCamera)}
        unknown = [name for name in snap.stop_through if name not in orbits]
        if unknown:
            report.error(
                f"{where}: stop_through names {unknown}, which are not orbit_camera actions of scene '{scene.id}'"
            )
        busy: list[tuple[str, float, float]] = []
        moving = scene.orbits_moving_at(t)
        for orbit in moving:
            span = f"orbit '{orbit.id}' ({orbit.at_seconds:g}-{orbit.end_seconds:g}s)"
            if orbit.id in snap.stop_through:
                report.warn(
                    f"stop_freezes_camera: {where}: {span} keeps turning through the stop, as its stop_through "
                    "allows; a player holding there freezes the camera mid-turn"
                )
            elif orbit.end_seconds > t + 1e-9:
                report.error(
                    f"{where}: {span} turns the camera across the stop, so a player holding there would freeze it "
                    f"mid-turn; split the orbit so that a piece ends {STOP_REST_SECONDS:g}s before the stop, or name "
                    "it in the stop's stop_through to accept the freeze"
                )
            else:
                busy.append((span, orbit.at_seconds, orbit.end_seconds))
        idle = [name for name in snap.stop_through if name in orbits and name not in {o.id for o in moving}]
        if idle:
            report.warn(f"{where}: stop_through names {idle}, which do not turn at the stop; remove them")
        for obj in scene.objects:
            begins = scene.start_seconds if obj.reveal_at_seconds is None else obj.reveal_at_seconds
            busy.append((f"the reveal of '{obj.id}'", begins, begins + motion.reveal_seconds))
        for action in scene.actions:
            if not isinstance(action, OrbitCamera):
                what = "lead-in and motion" if getattr(action, "lead_in_seconds", 0) else "motion"
                busy.append((f"the {what} of '{action.id}'", action.at_seconds, action.end_seconds))
        for scene_id, fade_start, fade_end in fades:
            busy.append((f"the closing fade of scene '{scene_id}'", fade_start, fade_end))
        clash = [
            (what, start, end) for what, start, end in busy if start < t - 1e-9 and end > t - STOP_REST_SECONDS + 1e-9
        ]
        if clash:
            listed = "; ".join(f"{what} runs {start:g}-{end:.4g}s" for what, start, end in clash)
            settled = max(end for _, _, end in clash) + STOP_REST_SECONDS
            fade_start = next((start for scene_id, start, _ in fades if scene_id == scene.id), scene.end_seconds)
            remedy = (
                f"move the stop to {settled:.4g}s or later, or end the motion earlier"
                if settled <= fade_start + 1e-9
                else "end the motion earlier, or put the stop where the scene rests"
            )
            report.error(
                f"{where} has no rest before it: {listed}. A player may pause up to {STOP_REST_SECONDS:g}s early, "
                f"so nothing may move in the {STOP_REST_SECONDS:g}s before a stop (an action may start at it); "
                f"{remedy}"
            )
        customs = [o for o in scene.objects if o.kind == "custom"]
        for obj in customs:
            module_name = obj.params["builder"].split(":")[0]
            if module_name not in time_based:
                path = builder_module_path(module_name, project, report.family)
                try:
                    time_based[module_name] = time_based_functions(path) if path is not None else []
                except (OSError, SyntaxError, UnicodeDecodeError) as exc:
                    time_based[module_name] = []
                    report.warn(f"{where}: builder module '{module_name}' could not be read for updaters: {exc}")
            if time_based[module_name]:
                report.error(
                    f"{where}: scene '{scene.id}' draws custom object '{obj.id}', whose builder module "
                    f"'{module_name}' has functions with a `dt` parameter ({', '.join(time_based[module_name])}), "
                    "Manim's time-based updaters; their checkpoint is approximate, so a hold could show a frame the "
                    "room did not see. Drive the motion with storyboard actions, or move the stop to another scene"
                )
    for (_, earlier), (_, later) in pairwise(stops):
        if frames_for(earlier.at_seconds, fps) == frames_for(later.at_seconds, fps):
            report.error(f"stops '{earlier.id}' and '{later.id}' fall on one frame; keep one")
        elif later.at_seconds - earlier.at_seconds < STOP_SPACING_SECONDS - 1e-9:
            report.error(
                f"stops '{earlier.id}' ({earlier.at_seconds:g}s) and '{later.id}' ({later.at_seconds:g}s) are "
                f"{later.at_seconds - earlier.at_seconds:.2f}s apart; a part needs at least "
                f"{STOP_SPACING_SECONDS:g}s, so keep one or move them apart"
            )


def stop_frozen_orbits(scene: Scene, snap: Snapshot) -> list[str]:
    """The orbits named in a stop's `stop_through` that turn at it: a hold there freezes them (ADR-045)."""
    if not snap.stop:
        return []
    return [orbit.id for orbit in scene.orbits_moving_at(snap.at_seconds) if orbit.id in snap.stop_through]


def active_equation(scene: Scene, obj: SceneObject, at_seconds: float) -> tuple[str, str | None]:
    """The equation `obj` shows at `at_seconds`, and the id of the transform that put it there (None when it is
    the one declared on the object): the last `transform_equation` of the object that has ended by then."""
    assert obj.equation is not None
    current, via = obj.equation.id, None
    for action in sorted(scene.actions, key=lambda a: a.at_seconds):
        if (
            isinstance(action, TransformEquation)
            and action.target == obj.id
            and action.end_seconds <= at_seconds + 1e-9
        ):
            current, via = action.to, action.id
    return current, via


def check_equation_transforms(scene: Scene, equations: dict[str, Any], engine: str, report: Report) -> None:
    """Every `transform_equation` names a declared equation with a source for the style's engine, and every
    emphasis resolves against the equation its object shows when the action begins (ADR-034)."""
    objects = {o.id: o for o in scene.objects}
    for action in scene.actions:
        if isinstance(action, TransformEquation):
            target = objects[action.target]
            equation = equations.get(action.to)
            if equation is None:
                report.error(
                    f"action '{action.id}': equation '{action.to}' is not declared in animation.yaml equations"
                )
                continue
            if equation.source_for(engine) is None:  # type: ignore[arg-type]
                report.error(
                    f"action '{action.id}': equation '{action.to}' has no '{engine}' source but the style uses that engine"
                )
            shown, _ = active_equation(scene, target, action.at_seconds)
            if shown == action.to:
                report.warn(f"action '{action.id}' transforms '{target.id}' into '{action.to}', which it already shows")
            assert target.equation is not None
            silent = [h for h in target.equation.highlight if not equation.mentions(h, engine)]  # type: ignore[arg-type]
            if silent:
                report.note(
                    f"action '{action.id}': highlighted symbols {silent} do not occur in '{action.to}', so they cannot be "
                    "emphasized after the transform"
                )
        elif isinstance(action, Emphasize):
            for object_id, symbols in action.places:
                obj = objects[object_id]
                if not symbols or obj.equation is None:
                    continue
                shown, via = active_equation(scene, obj, action.at_seconds)
                equation = equations.get(shown)
                absent = [name for name in symbols if equation is not None and not equation.mentions(name, engine)]  # type: ignore[arg-type]
                if absent:
                    how = f"transformed by '{via}'" if via is not None else "the equation declared on the object"
                    report.error(
                        f"action '{action.id}' points at {absent} on '{object_id}', but at {action.at_seconds:g}s that "
                        f"object shows equation '{shown}' ({how}), which does not contain them"
                    )
        elif isinstance(action, VaryParameter):
            for object_id in action.emphasize:
                obj = objects[object_id]
                assert obj.equation is not None
                shown, via = active_equation(scene, obj, action.at_seconds)
                equation = equations.get(shown)
                if equation is None or equation.mentions(action.parameter, engine):  # type: ignore[arg-type]
                    continue
                how = (
                    f"transformed from '{obj.equation.id}' by '{via}'"
                    if via is not None
                    else "the equation declared on the object"
                )
                report.error(
                    f"action '{action.id}' emphasizes '{action.parameter}' on '{object_id}', but at {action.at_seconds:g}s "
                    f"that object shows equation '{shown}' ({how}), which has no symbol '{action.parameter}'"
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
        report.error(
            f"{scene_module.name}: storyboard snapshots without a checkpoint() marker: {missing}; "
            "run `scianim codegen` to regenerate the scene module"
        )
    if extra:
        report.error(f"{scene_module.name}: checkpoint() markers not in the storyboard: {extra}")
    duplicates = sorted({m for m in markers if markers.count(m) > 1})
    if duplicates:
        report.error(f"{scene_module.name}: duplicate checkpoint() markers: {duplicates}")


def resolve_sources(project: Project, animation: AnimationSpec, report: Report) -> None:
    family_root = report.family.root if report.family else None
    for source in animation.sources:
        if is_asset_uri(source.path):
            try:
                report.source_paths[source.id] = resolve_asset(source.path, family_root, report.workspace)
            except SpecError as exc:
                report.error(f"source '{source.id}': {exc.message}")
        else:
            path = project.root / source.path
            if path.exists():
                report.source_paths[source.id] = path.resolve()
            else:
                report.error(f"source '{source.id}': file {source.path} not found under {project.root}")


def validate_project(
    project: Project,
    require_family: bool = False,
    animation: AnimationSpec | None = None,
    storyboard: Storyboard | None = None,
) -> Report:
    """Cross-file checks. `animation` and `storyboard` override the files on disk (proposal validation)."""
    report = Report()
    report.workspace = project.workspace_root()
    if animation is None:
        try:
            animation = project.load_animation()
        except SpecError as exc:
            report.error(exc.message if exc.path is None else f"{exc.path}: {exc.message}")
            return report
    report.animation = animation
    try:
        lookup = locate_family(project.root, animation.family, project.family_search_roots())
        report.family, report.family_via, report.groups = lookup.context, lookup.via, list(lookup.groups)
    except SpecError as exc:
        (report.error if require_family else report.warn)(exc.message)
    resolve_sources(project, animation, report)
    family_manifest: FamilyManifest | None = report.family.manifest if report.family else None
    if family_manifest and family_manifest.style.name != animation.style.name:
        report.note(
            f"project uses style '{animation.style.name}' while family '{family_manifest.id}' defaults to '{family_manifest.style.name}'"
        )
    try:
        report.style = resolve_style(
            animation.style, project.style_search_dirs(), family_manifest, [g.manifest for g in report.groups]
        )
    except SpecError as exc:
        report.error(exc.message)
    if storyboard is None:
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
