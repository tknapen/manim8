"""`storyboard.yaml`: proposed visual implementation (spec section 5.2)."""

from __future__ import annotations

import math
import re
from itertools import combinations
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, model_validator

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


STOP_REST_SECONDS = 0.3
"""The rest a stop needs before it (ADR-045): no reveal, action or scene fade may run in the 0.3 s before a stop.
A player pauses up to this much early when it cannot watch frames, then seeks to the stop's exact frame; the rest
hides the jump. An action may start at the stop itself."""
STOP_SPACING_SECONDS = 0.5
"""The least time between two stops (ADR-045)."""
STOP_LABEL_MAX = 40

StopLabel = Annotated[str, StringConstraints(min_length=1, max_length=STOP_LABEL_MAX, pattern=r"^[^\x00-\x1f\x7f<>]*$")]
"""A stop's label: plain text on one line, 1 to 40 characters, no markup."""


class Snapshot(StrictModel):
    id: Slug
    at_seconds: float = Field(ge=0)
    description: str = Field(min_length=1)
    kind: SnapshotKind = "manim_checkpoint"
    stop: bool = False
    """A place where a player may hold the clip until the presenter's next key (ADR-045). The clip stays one movie;
    a stop changes no picture, since a snapshot is already a breakpoint of the generated scene. Validation asks a
    rest of 0.3 s before it (`STOP_REST_SECONDS`) and refuses it at a scene start, on the last frame, within 0.5 s
    of another stop, while an orbit turns the camera across it, and where its checkpoint would be approximate."""
    label: StopLabel | None = None
    """A short name for the hold, shown under its still (a stop only); omitted means the id with spaces."""
    stop_through: list[Slug] = []
    """Ids of `orbit_camera` actions of this scene allowed to keep turning through the stop (a stop only): a
    player holding there freezes the camera mid-turn, which validation then reports as a warning
    (`stop_freezes_camera`) instead of refusing the stop."""

    @model_validator(mode="after")
    def _stop_fields(self) -> Snapshot:
        if not self.stop and (self.label is not None or self.stop_through):
            raise ValueError(
                f"snapshot '{self.id}': label and stop_through describe a stop; set stop: true or remove them"
            )
        ensure_unique(self.stop_through, f"stop_through (snapshot '{self.id}')")
        if self.stop and self.label is None and len(self.id) > STOP_LABEL_MAX:
            raise ValueError(
                f"snapshot '{self.id}': a stop's label defaults to its id with spaces, which is longer than "
                f"{STOP_LABEL_MAX} characters; give it a label"
            )
        return self

    @property
    def stop_label(self) -> str:
        """The label a player shows for this stop: `label`, or the id with spaces."""
        return self.label if self.label is not None else self.id.replace("_", " ")


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
    """Fade an object out (`visible: false`, the default), back in (`visible: true`), or to a level of its full
    ink (`ink`, ADR-041) over a window (ADR-034).

    `ink: 0.3` dims the object to three tenths of its ink, so the context stays readable without competing with
    the subject; a later fade with `visible: true` or `ink: 1` restores it. Every fade starts from the ink the
    object has, so a dimmed object fades out from its dimmed level. A faded-out object stays registered but is
    absent from layout reports until a fade brings it back; a dimmed one stays in them. Two fades of one object
    may not overlap, and an object is not redrawn (swept, emphasized by a sweep, transformed or pulsed) while it
    is dimmed or a fade to or from a partial level runs, since its redrawn parts would show at full ink.
    `fade_axes` remains the special case for a surface's frame."""

    kind: Literal["fade_object"]
    id: Slug
    target: Slug
    visible: bool | None = None
    """True fades the object back to full ink, false (or omitting both this and `ink`) fades it out."""
    ink: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    """The fraction of its full ink the object ends at; give this or `visible`, not both."""
    at_seconds: float = Field(ge=0)
    duration_seconds: float = Field(gt=0)
    easing: Easing | None = None

    @model_validator(mode="after")
    def _one_level(self) -> FadeObject:
        if self.ink is not None and self.visible is not None:
            raise ValueError(f"fade_object '{self.id}': give visible or ink, not both")
        return self

    @property
    def target_ink(self) -> float:
        """The fraction of full ink the object has when the fade ends."""
        if self.ink is not None:
            return self.ink
        return 1.0 if self.visible else 0.0

    @property
    def end_seconds(self) -> float:
        return self.at_seconds + self.duration_seconds


SymbolName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]

CueKind = Literal["box", "pulse"]


class Emphasize(StrictModel):
    """Point at an object, or at named symbols of the equation it shows, without changing it (ADR-041).

    With `cue: box` (the default) a box in the style's emphasis ink appears around the place, holds and fades
    out. With `from_target` (and `from_symbols`) the box appears at another place first and travels to the
    target, so the cue itself shows what a symbol names: the sigma in the equation, then the curve it widens. With
    `cue: pulse` the named symbols grow, take the emphasis ink and settle once over the window, as a sweep's
    lead-in does, while no value moves. A box surrounds the first occurrence of each named symbol. Cues are
    drawn in the frame, so their places are flat objects, not a surface or a sphere that turns with the camera.
    """

    kind: Literal["emphasize"]
    id: Slug
    target: Slug
    symbols: list[SymbolName] = []
    """Symbols of the target's equation (each in its `equation.highlight`); omitted means the whole object."""
    cue: CueKind = "box"
    from_target: Slug | None = None
    """Where a box appears before it travels to `target`; omitted means it appears around the target."""
    from_symbols: list[SymbolName] = []
    """Symbols of `from_target`'s equation the box starts around."""
    at_seconds: float = Field(ge=0)
    duration_seconds: float = Field(gt=0)
    easing: Easing | None = None
    """Profile of the box's travel; omitted means the style's `motion.easing`."""

    @model_validator(mode="after")
    def _consistent(self) -> Emphasize:
        ensure_unique(self.symbols, f"symbol (action '{self.id}')")
        ensure_unique(self.from_symbols, f"from symbol (action '{self.id}')")
        if self.cue == "pulse" and not self.symbols:
            raise ValueError(f"emphasize '{self.id}': a pulse grows symbols; name them in `symbols`")
        if self.cue == "pulse" and self.from_target is not None:
            raise ValueError(f"emphasize '{self.id}': only a box travels; a pulse has no from_target")
        if self.from_symbols and self.from_target is None:
            raise ValueError(f"emphasize '{self.id}': from_symbols needs from_target")
        if self.from_target == self.target and self.from_symbols == self.symbols:
            raise ValueError(f"emphasize '{self.id}': the box would travel from its target to itself")
        return self

    @property
    def places(self) -> list[tuple[str, list[str]]]:
        """The objects the cue sits on, with the symbols named on each."""
        places = [(self.target, self.symbols)]
        if self.from_target is not None:
            places.append((self.from_target, self.from_symbols))
        return places

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
    VaryParameter | OrbitCamera | FadeAxes | MoveObject | FadeObject | TransformEquation | Emphasize,
    Field(discriminator="kind"),
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
            if isinstance(action, Emphasize):
                for place_id, symbols in action.places:
                    place = objects.get(place_id)
                    if place is None:
                        raise ValueError(f"action '{action.id}': '{place_id}' is not an object of scene '{self.id}'")
                    if reveal_time(place) > action.at_seconds:
                        raise ValueError(
                            f"action '{action.id}' at {action.at_seconds:g}s points at '{place_id}' before it is "
                            f"revealed at {reveal_time(place):g}s"
                        )
                    if place.kind in WORLD_KINDS:
                        raise ValueError(
                            f"action '{action.id}': '{place_id}' is a {place.kind}, which turns with the camera; a cue "
                            "is drawn in the frame, so point at a flat object"
                        )
                    missing = [
                        name for name in symbols if place.equation is None or name not in place.equation.highlight
                    ]
                    if missing:
                        raise ValueError(
                            f"action '{action.id}': '{place_id}' must reference an equation whose highlight includes "
                            f"{missing} to point at them"
                        )
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
            for cue, other in ((first, second), (second, first)):
                if not isinstance(cue, Emphasize):
                    continue
                if isinstance(other, TransformEquation) and other.target in {place for place, _ in cue.places}:
                    raise ValueError(
                        f"emphasize '{cue.id}' points at '{other.target}' while '{other.id}' replaces its glyphs; "
                        "let the transform end first"
                    )
                if cue.cue != "pulse":
                    continue
                if isinstance(other, VaryParameter) and cue.target in other.emphasize:
                    raise ValueError(
                        f"emphasize '{cue.id}' pulses '{cue.target}' while '{other.id}' emphasizes it; one pulse at a time"
                    )
                if isinstance(other, Emphasize) and other.cue == "pulse" and other.target == cue.target:
                    raise ValueError(f"pulses '{first.id}' and '{second.id}' of '{cue.target}' overlap")
        self._check_ink()

    def _check_ink(self) -> None:
        """No object is redrawn while it is dimmed or while a fade to or from a partial ink level runs: a redraw
        (a sweep, a sweep's emphasis, a transform, a pulse) builds parts at full ink (ADR-041)."""
        fades = sorted((a for a in self.actions if isinstance(a, FadeObject)), key=lambda a: a.at_seconds)
        unsettled: dict[str, list[tuple[float, float, str]]] = {}
        level: dict[str, float] = {}
        for index, fade in enumerate(fades):
            start, end = level.get(fade.target, 1.0), fade.target_ink
            later = next((f.at_seconds for f in fades[index + 1 :] if f.target == fade.target), self.end_seconds)
            windows = unsettled.setdefault(fade.target, [])
            if 0 < start < 1 or 0 < end < 1:
                windows.append((fade.at_seconds, fade.end_seconds, fade.id))
            if 0 < end < 1:
                windows.append((fade.end_seconds, later, fade.id))
            level[fade.target] = end
        for action in self.actions:
            if isinstance(action, VaryParameter):
                redrawn = [action.target, *action.emphasize]
            elif isinstance(action, TransformEquation) or (isinstance(action, Emphasize) and action.cue == "pulse"):
                redrawn = [action.target]
            else:
                continue
            for object_id in redrawn:
                for start, end, fade_id in unsettled.get(object_id, []):
                    if action.at_seconds < end - 1e-9 and start < action.end_seconds - 1e-9:
                        raise ValueError(
                            f"action '{action.id}' redraws '{object_id}' while '{fade_id}' dims it or fades it from a "
                            f"partial ink ({start:g}-{end:g}s); redrawn parts would show at full ink, so restore its "
                            "ink first or move the action"
                        )

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds

    def orbits_moving_at(self, seconds: float, rest_seconds: float = STOP_REST_SECONDS) -> list[OrbitCamera]:
        """The camera orbits that turn in the `rest_seconds` before `seconds` or across it: the ones a player
        holding the clip at `seconds` would freeze (ADR-045). An orbit that starts at `seconds` is not one."""
        return [
            action
            for action in self.actions
            if isinstance(action, OrbitCamera)
            and action.at_seconds < seconds - 1e-9
            and action.end_seconds > seconds - rest_seconds + 1e-9
        ]


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

    def stops(self) -> list[tuple[Scene, Snapshot]]:
        """The snapshots marked `stop`, with their scenes, in time order (ADR-045)."""
        found = [(scene, snap) for scene in self.scenes for snap in scene.snapshots if snap.stop]
        return sorted(found, key=lambda item: item[1].at_seconds)

    def objects(self) -> list[SceneObject]:
        return [o for s in self.scenes for o in s.objects]

    def actions(self) -> list[SceneAction]:
        return [a for s in self.scenes for a in s.actions]

    def scene_of_snapshot(self, snapshot_id: str) -> Scene:
        for scene in self.scenes:
            if any(s.id == snapshot_id for s in scene.snapshots):
                return scene
        raise KeyError(snapshot_id)
