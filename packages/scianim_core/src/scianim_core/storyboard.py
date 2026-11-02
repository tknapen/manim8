"""`storyboard.yaml`: proposed visual implementation (spec section 5.2)."""

from __future__ import annotations

import math
import re
from itertools import combinations
from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from scianim_core.common import SchemaVersion, Slug, StrictModel, ensure_unique
from scianim_core.components import (
    ANCHORED_KINDS,
    PARAMETRIC_KINDS,
    REGISTRY,
    WORLD_KINDS,
    ComponentKind,
    EquationBlockParams,
    FunctionPlotParams,
    ScientificPlotParams,
    check_parameters,
    validate_params,
)
from scianim_core.style import Anchor, Easing

MARK_PATTERN = re.compile(r'<mark\s+name="([A-Za-z0-9_]+)"\s*/>')
SnapshotKind = Literal["manim_checkpoint", "sampled_video_frame"]


class DataEncoding(StrictModel):
    x: str = Field(min_length=1)
    y: str = Field(min_length=1)
    group: str | None = None
    error: str | None = None


class FilterTransform(StrictModel):
    op: Literal["filter"]
    column: str = Field(min_length=1)
    equals: str | float | int | bool


class NormalizeTransform(StrictModel):
    op: Literal["normalize"]
    column: str = Field(min_length=1)
    by: Literal["max", "sum", "first"] = "max"


class SortTransform(StrictModel):
    op: Literal["sort"]
    column: str = Field(min_length=1)
    descending: bool = False


class ParameterRef(StrictModel):
    """A transform setting that a `vary_parameter` action can sweep: `{parameter: w, default: 5}` names the
    parameter and the value it has until an action moves it (ADR-034)."""

    parameter: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    default: float = Field(allow_inf_nan=False)


class ScaleTransform(StrictModel):
    """Multiply a numeric column by a factor; a parameterised factor makes the plot sweepable."""

    op: Literal["scale"]
    column: str = Field(min_length=1)
    by: float | ParameterRef = Field(union_mode="left_to_right")


class SmoothTransform(StrictModel):
    """Gaussian smoothing of a numeric column along the row order, with the standard deviation `window` in
    rows; zero leaves the column as it is. Sort and filter first so the rows that are averaged belong together."""

    op: Literal["smooth"]
    column: str = Field(min_length=1)
    window: float | ParameterRef = Field(union_mode="left_to_right")


Transform = Annotated[
    FilterTransform | NormalizeTransform | SortTransform | ScaleTransform | SmoothTransform, Field(discriminator="op")
]


class DataBinding(StrictModel):
    source: Slug
    encoding: DataEncoding
    transforms: list[Transform] = []

    @model_validator(mode="after")
    def _parameter_names(self) -> DataBinding:
        check_parameters(self.parameters(), ())
        return self

    def parameters(self) -> dict[str, float]:
        """The parameters the transforms name, with their defaults; a name used twice must agree on its default."""
        found: dict[str, float] = {}
        for transform in self.transforms:
            for value in (getattr(transform, "by", None), getattr(transform, "window", None)):
                if isinstance(value, ParameterRef):
                    if value.parameter in found and found[value.parameter] != value.default:
                        raise ValueError(
                            f"parameter '{value.parameter}' is given two defaults ({found[value.parameter]:g} and "
                            f"{value.default:g}) in one data binding"
                        )
                    found[value.parameter] = value.default
        return found


class EquationRef(StrictModel):
    id: Slug
    highlight: list[str] = []
    """Symbol names (keys of `equations[].symbols`) typeset as addressable terms, so a `vary_parameter` action
    can emphasize one."""
    highlight_mode: Literal["always", "active"] = "always"
    """`always`: every highlighted term sits in the emphasis colour throughout. `active`: the terms sit in the
    equation's own ink and only the term that a running `vary_parameter` action emphasizes takes the colour; it
    keeps it until the next emphasized action on this object begins, when the colour passes to that term."""


class SceneObject(StrictModel):
    id: Slug
    kind: ComponentKind
    style_role: Slug | None = None
    data: DataBinding | None = None
    equation: EquationRef | None = None
    params: dict[str, Any] = {}
    reveal_at_seconds: float | None = Field(default=None, ge=0)
    """When the object appears; omitted means at the scene start, in declaration order."""

    @model_validator(mode="after")
    def _registry_checks(self) -> SceneObject:
        definition = REGISTRY[self.kind]
        try:
            validate_params(self.kind, self.params)
        except ValueError as exc:
            raise ValueError(f"object '{self.id}': {exc}") from None
        if definition.requires_data and self.data is None:
            raise ValueError(f"object '{self.id}' of kind '{self.kind}' requires a 'data' binding")
        if definition.requires_equation and self.equation is None:
            raise ValueError(f"object '{self.id}' of kind '{self.kind}' requires an 'equation' reference")
        return self

    def typed_params(self) -> StrictModel:
        return validate_params(self.kind, self.params)


class Snapshot(StrictModel):
    id: Slug
    at_seconds: float = Field(ge=0)
    description: str = Field(min_length=1)
    kind: SnapshotKind = "manim_checkpoint"


class VaryParameter(StrictModel):
    """Vary one named parameter of a `function_plot`, `surface_plot` or `function_image` while the viewer watches.

    The picture follows the value, the equation term named by `parameter` pulses once as the action begins,
    and a readout shows the running value. With a `lead_in_seconds`, the term lights up first and the value
    moves only afterwards, which makes a clip of several such segments read as "this term, then this one". A
    checkpoint inside the window splits the sweep at that frame, so it is still reached by the real animation
    flow. Actions run concurrently unless they drive the same parameter.
    """

    kind: Literal["vary_parameter"]
    id: Slug
    target: Slug
    """A `function_plot`, `surface_plot` or `function_image` in the same scene that declares `parameter`."""
    parameter: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    to: float = Field(allow_inf_nan=False)
    at_seconds: float = Field(ge=0)
    duration_seconds: float = Field(gt=0)
    """How long the value takes to reach `to`, after the lead-in."""
    lead_in_seconds: float = Field(default=0, ge=0)
    """Time between the action's start and the first change of the value. During it the emphasized term takes
    the colour and pulses and the readout shows the starting value; the picture moves only afterwards. The
    action's window is `lead_in_seconds + duration_seconds` long."""
    easing: Easing | None = None
    """Rate profile; omitted means the style's `motion.easing`."""
    emphasize: list[Slug] = []
    """Equation objects in this scene whose `equation.highlight` names `parameter`; their term pulses."""
    show_value: bool = True
    value_decimals: int = Field(default=1, ge=0, le=6)
    value_label: str | None = None
    """Text before the value; the default is the symbol itself (Greek names become letters)."""

    @property
    def end_seconds(self) -> float:
        return self.at_seconds + self.lead_in_seconds + self.duration_seconds

    @property
    def moves_at_seconds(self) -> float:
        """When the value starts to change."""
        return self.at_seconds + self.lead_in_seconds


class OrbitCamera(StrictModel):
    """Turn the camera around the scene's surface over a window: the azimuth (`theta`) and the elevation (`phi`)
    move from where they are to the given angles with the easing. Flat objects stay fixed in the frame; only
    `surface_plot` objects turn, so a scene needs one. Orbits may run alongside parameter sweeps."""

    kind: Literal["orbit_camera"]
    id: Slug
    to_theta_degrees: float | None = Field(default=None, allow_inf_nan=False)
    to_phi_degrees: float | None = Field(default=None, ge=0, le=90)
    at_seconds: float = Field(ge=0)
    duration_seconds: float = Field(gt=0)
    easing: Easing | None = None

    @model_validator(mode="after")
    def _some_target(self) -> OrbitCamera:
        if self.to_theta_degrees is None and self.to_phi_degrees is None:
            raise ValueError("orbit_camera needs to_theta_degrees, to_phi_degrees or both")
        return self

    @property
    def end_seconds(self) -> float:
        return self.at_seconds + self.duration_seconds


class FadeAxes(StrictModel):
    """Fade the frame, ticks and labels of a `surface_plot` out (or back in) over a window; the surface stays.

    Show the axes while the viewer learns the box, then let them go once the shape alone carries the meaning.
    A fade may run beside sweeps and orbits; two fades of the same object may not overlap.
    """

    kind: Literal["fade_axes"]
    id: Slug
    target: Slug
    """A `surface_plot` in the same scene."""
    visible: bool = False
    """False fades the axes out; True brings them back."""
    at_seconds: float = Field(ge=0)
    duration_seconds: float = Field(gt=0)
    easing: Easing | None = None

    @property
    def end_seconds(self) -> float:
        return self.at_seconds + self.duration_seconds


class MoveObject(StrictModel):
    """Move an object over a window (ADR-034).

    A flat object moves in the frame: to an `Anchor` of the safe area (`to_anchor`), or `by` an offset given as
    fractions of the safe frame's width and height. An object anchored in a surface's data coordinates (a
    `sphere`) moves `to_point`, a point in those coordinates. Exactly one of the three is given. The motion
    starts from wherever the object is when the window opens and ends at the absolute target, so a checkpoint
    inside the window is reached by the real flow; readouts and emphasis placed relative to the object follow
    it while their own actions run. Two moves of one object may not overlap.
    """

    kind: Literal["move_object"]
    id: Slug
    target: Slug
    to_anchor: Anchor | None = None
    by: tuple[float, float] | None = None
    """Offset as fractions of the safe frame: `[0.1, 0]` moves a tenth of the safe width to the right."""
    to_point: tuple[float, float, float] | None = None
    """Target centre in the anchor surface's data coordinates, for a `sphere`."""
    at_seconds: float = Field(ge=0)
    duration_seconds: float = Field(gt=0)
    easing: Easing | None = None
    """Rate profile; omitted means the style's `motion.easing`. `ease_in_quad` falls from rest, `ease_out_quad`
    rises to rest at the top: the two halves of a ballistic arc."""

    @model_validator(mode="after")
    def _one_destination(self) -> MoveObject:
        given = [name for name in ("to_anchor", "by", "to_point") if getattr(self, name) is not None]
        if len(given) != 1:
            raise ValueError(f"move_object needs exactly one of to_anchor, by or to_point (given: {given or 'none'})")
        for name in ("by", "to_point"):
            values = getattr(self, name)
            if values is not None and any(not math.isfinite(v) for v in values):
                raise ValueError(f"move_object {name} must be finite numbers")
        return self

    @property
    def end_seconds(self) -> float:
        return self.at_seconds + self.duration_seconds


class FadeObject(StrictModel):
    """Fade an object out (`visible: false`) or back in over a window (ADR-034). A faded object stays registered
    but is absent from layout reports until a fade brings it back; two fades of one object may not overlap.
    `fade_axes` remains the special case for a surface's frame."""

    kind: Literal["fade_object"]
    id: Slug
    target: Slug
    visible: bool = False
    at_seconds: float = Field(ge=0)
    duration_seconds: float = Field(gt=0)
    easing: Easing | None = None

    @property
    def end_seconds(self) -> float:
        return self.at_seconds + self.duration_seconds


class TransformEquation(StrictModel):
    """Turn the equation an `equation_block` or `equation_label` shows into another declared equation (ADR-034).

    The target equation is typeset with the same highlighted symbols; occurrences of a highlighted symbol pair
    by name (`by_symbol`, the default: the first occurrence in the old equation goes to the first in the new,
    and so on) and every other glyph pairs by shape, so an `=` or a `2` glides to its new place; glyphs without
    a partner fade out or in. Named symbols are the only parts matched by meaning; everything else is matched
    by shape, which can pair glyphs that merely look alike. Once the window closes the object shows the new
    equation, and later `vary_parameter` emphasis on it resolves symbols against that equation. A block that
    lists symbol definitions cannot be transformed; two transforms of one object may not overlap, and a sweep
    that emphasizes the object may not start inside the window (its pulse would play on glyphs being replaced).
    """

    kind: Literal["transform_equation"]
    id: Slug
    target: Slug
    to: Slug
    """Id of an equation in animation.yaml."""
    at_seconds: float = Field(ge=0)
    duration_seconds: float = Field(gt=0)
    match: Literal["by_symbol", "by_shape"] = "by_symbol"
    easing: Easing | None = None

    @property
    def end_seconds(self) -> float:
        return self.at_seconds + self.duration_seconds


SceneAction = Annotated[
    VaryParameter | OrbitCamera | FadeAxes | MoveObject | FadeObject | TransformEquation, Field(discriminator="kind")
]
"""Actions run concurrently; the validator refuses two that drive the same thing at once."""


class Narration(StrictModel):
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def _marks_unique(self) -> Narration:
        ensure_unique(self.marks, "narration mark")
        return self

    @property
    def marks(self) -> list[str]:
        return MARK_PATTERN.findall(self.text)

    @property
    def plain_text(self) -> str:
        return re.sub(r"\s+", " ", MARK_PATTERN.sub(" ", self.text)).strip()

    @property
    def word_count(self) -> int:
        return len(self.plain_text.split())

    def estimated_seconds(self, words_per_minute: float) -> float:
        return self.word_count / words_per_minute * 60.0


class Scene(StrictModel):
    id: Slug
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    title: str | None = None
    purpose: str = Field(min_length=1)
    narration: Narration | None = None
    objects: list[SceneObject] = []
    actions: list[SceneAction] = []
    """Things that happen to objects while the scene plays, in time order; see `VaryParameter`."""
    snapshots: list[Snapshot] = []
    patterns: list[Slug] = []
    """Ids of the library patterns the scene stages (ADR-040), e.g. `sweep_with_readout`. They record intent for
    the reviewer and the agent and change no picture; project validation checks that each id exists and that
    the scene uses something the pattern is realized with."""

    @model_validator(mode="after")
    def _checks(self) -> Scene:
        if self.end_seconds <= self.start_seconds:
            raise ValueError(
                f"scene '{self.id}': end_seconds ({self.end_seconds}) must exceed start_seconds ({self.start_seconds})"
            )
        ensure_unique((o.id for o in self.objects), f"object (scene '{self.id}')")
        ensure_unique((s.id for s in self.snapshots), f"snapshot (scene '{self.id}')")
        ensure_unique(self.patterns, f"pattern (scene '{self.id}')")
        ensure_unique(
            (*(o.id for o in self.objects), *(a.id for a in self.actions)), f"object or action (scene '{self.id}')"
        )
        self._check_actions()
        seen: list[str] = []
        for obj in self.objects:
            if obj.reveal_at_seconds is not None and not (
                self.start_seconds <= obj.reveal_at_seconds <= self.end_seconds
            ):
                raise ValueError(
                    f"object '{obj.id}' reveal_at_seconds={obj.reveal_at_seconds} lies outside scene "
                    f"'{self.id}' [{self.start_seconds}, {self.end_seconds}]"
                )
            for key in ("below", "right_of"):
                ref = obj.params.get(key)
                if ref is not None and ref not in seen:
                    raise ValueError(
                        f"object '{obj.id}': {key}='{ref}' must name an object declared earlier in scene '{self.id}'"
                    )
            if obj.kind in ANCHORED_KINDS:
                anchor = next((o for o in self.objects if o.id == obj.params.get("anchor")), None)
                if anchor is None or anchor.id not in seen or anchor.kind != "surface_plot":
                    raise ValueError(
                        f"object '{obj.id}': anchor='{obj.params.get('anchor')}' must name a surface_plot declared "
                        f"earlier in scene '{self.id}'"
                    )
                anchor_reveal = self.start_seconds if anchor.reveal_at_seconds is None else anchor.reveal_at_seconds
                own_reveal = self.start_seconds if obj.reveal_at_seconds is None else obj.reveal_at_seconds
                if anchor_reveal > own_reveal + 1e-9:
                    raise ValueError(
                        f"object '{obj.id}' is revealed at {own_reveal:g}s, before its anchor '{anchor.id}' "
                        f"at {anchor_reveal:g}s"
                    )
            seen.append(obj.id)
        for snapshot in self.snapshots:
            if not (self.start_seconds <= snapshot.at_seconds <= self.end_seconds):
                raise ValueError(
                    f"snapshot '{snapshot.id}' at {snapshot.at_seconds}s lies outside scene "
                    f"'{self.id}' [{self.start_seconds}, {self.end_seconds}]"
                )
        return self

    def _check_actions(self) -> None:
        objects = {o.id: o for o in self.objects}

        def reveal_time(obj: SceneObject) -> float:
            return self.start_seconds if obj.reveal_at_seconds is None else obj.reveal_at_seconds

        for action in self.actions:
            if action.at_seconds < self.start_seconds or action.end_seconds > self.end_seconds:
                raise ValueError(
                    f"action '{action.id}' ({action.at_seconds:g}-{action.end_seconds:g}s) lies outside scene "
                    f"'{self.id}' [{self.start_seconds}, {self.end_seconds}]"
                )
            if isinstance(action, OrbitCamera):
                if not any(o.kind == "surface_plot" for o in self.objects):
                    raise ValueError(
                        f"action '{action.id}': orbit_camera needs a surface_plot in scene '{self.id}'; flat objects "
                        "stay fixed in the frame"
                    )
                continue
            target = objects.get(action.target)
            if target is None:
                raise ValueError(
                    f"action '{action.id}': target '{action.target}' is not an object of scene '{self.id}'"
                )
            if reveal_time(target) > action.at_seconds:
                raise ValueError(
                    f"action '{action.id}' at {action.at_seconds:g}s starts before its target '{target.id}' "
                    f"is revealed at {reveal_time(target):g}s"
                )
            if isinstance(action, FadeAxes):
                if target.kind != "surface_plot":
                    raise ValueError(
                        f"action '{action.id}': target '{target.id}' is a {target.kind}; fade_axes needs a surface_plot"
                    )
                continue
            if isinstance(action, MoveObject):
                if action.to_point is not None and target.kind not in ANCHORED_KINDS:
                    raise ValueError(
                        f"action '{action.id}': target '{target.id}' is a {target.kind}; to_point moves an object "
                        f"anchored in a surface's coordinates ({sorted(ANCHORED_KINDS)}); use to_anchor or by"
                    )
                if action.to_point is None and target.kind in WORLD_KINDS:
                    raise ValueError(
                        f"action '{action.id}': target '{target.id}' is a {target.kind}, which turns with the camera; "
                        "to_anchor and by move flat objects in the frame"
                        + (", a sphere moves to_point" if target.kind in ANCHORED_KINDS else "")
                    )
                continue
            if isinstance(action, FadeObject):
                continue
            if isinstance(action, TransformEquation):
                if target.equation is None:
                    raise ValueError(
                        f"action '{action.id}': target '{target.id}' is a {target.kind} without an equation; "
                        "transform_equation needs an equation_block or equation_label"
                    )
                params = target.typed_params()
                if isinstance(params, EquationBlockParams) and params.define_symbols:
                    raise ValueError(
                        f"action '{action.id}': '{target.id}' lists symbol definitions (define_symbols), which would "
                        "describe the old equation after the transform; turn them off or use another object"
                    )
                continue
            params = target.typed_params()
            declared = dict(getattr(params, "parameters", {}))
            if target.data is not None:
                declared.update(target.data.parameters())
            if target.kind not in PARAMETRIC_KINDS and not (target.data is not None and target.data.parameters()):
                raise ValueError(
                    f"action '{action.id}': target '{target.id}' is a {target.kind}; vary_parameter needs one of "
                    f"{sorted(PARAMETRIC_KINDS)} or a data binding whose transforms name parameters"
                )
            if action.parameter not in declared:
                raise ValueError(
                    f"action '{action.id}': '{target.id}' declares no parameter '{action.parameter}' "
                    f"(declared: {sorted(declared) or 'none'})"
                )
            if isinstance(params, FunctionPlotParams | ScientificPlotParams) and params.y_range is None:
                raise ValueError(
                    f"action '{action.id}': give '{target.id}' a y_range so the axes stay fixed while "
                    f"'{action.parameter}' varies"
                )
            for object_id in action.emphasize:
                obj = objects.get(object_id)
                if obj is None:
                    raise ValueError(
                        f"action '{action.id}': emphasize names '{object_id}', not an object of scene '{self.id}'"
                    )
                if obj.equation is None or action.parameter not in obj.equation.highlight:
                    raise ValueError(
                        f"action '{action.id}': '{object_id}' must reference an equation whose highlight includes "
                        f"'{action.parameter}' to be emphasized"
                    )
                if reveal_time(obj) > action.at_seconds:
                    raise ValueError(
                        f"action '{action.id}' at {action.at_seconds:g}s starts before '{object_id}' is revealed "
                        f"at {reveal_time(obj):g}s"
                    )
        for first, second in combinations(self.actions, 2):
            overlapping = first.at_seconds < second.end_seconds and second.at_seconds < first.end_seconds
            if not overlapping:
                continue
            if isinstance(first, OrbitCamera) and isinstance(second, OrbitCamera):
                raise ValueError(f"camera orbits '{first.id}' and '{second.id}' overlap; one orbit at a time")
            if isinstance(first, FadeAxes) and isinstance(second, FadeAxes) and first.target == second.target:
                raise ValueError(f"axes fades '{first.id}' and '{second.id}' of '{first.target}' overlap")
            for cls, what in ((MoveObject, "moves"), (FadeObject, "fades"), (TransformEquation, "transforms")):
                if isinstance(first, cls) and isinstance(second, cls) and first.target == second.target:
                    raise ValueError(f"{what} '{first.id}' and '{second.id}' of '{first.target}' overlap")
            for transform, sweep in ((first, second), (second, first)):
                if (
                    isinstance(transform, TransformEquation)
                    and isinstance(sweep, VaryParameter)
                    and transform.target in sweep.emphasize
                    and transform.at_seconds <= sweep.at_seconds < transform.end_seconds - 1e-9
                ):
                    raise ValueError(
                        f"action '{sweep.id}' emphasizes '{transform.target}' and starts at {sweep.at_seconds:g}s, "
                        f"inside '{transform.id}' ({transform.at_seconds:g}-{transform.end_seconds:g}s), which is "
                        "replacing that equation's glyphs; start it when the transform has ended"
                    )
            if (
                isinstance(first, VaryParameter)
                and isinstance(second, VaryParameter)
                and (first.target, first.parameter) == (second.target, second.parameter)
            ):
                raise ValueError(
                    f"actions '{first.id}' and '{second.id}' both vary '{first.target}.{first.parameter}' at the "
                    "same time"
                )

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


class Storyboard(StrictModel):
    schema_version: SchemaVersion
    project_id: Slug
    based_on_animation_revision: str = Field(min_length=1)
    scenes: list[Scene] = Field(min_length=1)

    @model_validator(mode="after")
    def _checks(self) -> Storyboard:
        ensure_unique((s.id for s in self.scenes), "scene")
        ensure_unique((o.id for s in self.scenes for o in s.objects), "object")
        ensure_unique((a.id for s in self.scenes for a in s.actions), "action")
        ensure_unique(
            (i for s in self.scenes for i in (*(o.id for o in s.objects), *(a.id for a in s.actions))),
            "object or action",
        )
        ensure_unique((snap.id for s in self.scenes for snap in s.snapshots), "snapshot")
        previous: Scene | None = None
        for scene in self.scenes:
            if previous is not None and scene.start_seconds < previous.end_seconds:
                raise ValueError(
                    f"scene '{scene.id}' starts at {scene.start_seconds}s before scene "
                    f"'{previous.id}' ends at {previous.end_seconds}s; scenes must be ordered "
                    "and must not overlap (declare transitions explicitly)"
                )
            previous = scene
        return self

    @property
    def total_end_seconds(self) -> float:
        return max(s.end_seconds for s in self.scenes)

    def snapshot_ids(self) -> list[str]:
        return [snap.id for s in self.scenes for snap in s.snapshots]

    def objects(self) -> list[SceneObject]:
        return [o for s in self.scenes for o in s.objects]

    def actions(self) -> list[SceneAction]:
        return [a for s in self.scenes for a in s.actions]

    def scene_of_snapshot(self, snapshot_id: str) -> Scene:
        for scene in self.scenes:
            if any(s.id == snapshot_id for s in scene.snapshots):
                return scene
        raise KeyError(snapshot_id)
