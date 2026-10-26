"""`storyboard.yaml`: proposed visual implementation (spec section 5.2)."""

from __future__ import annotations

import re
from itertools import pairwise
from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from scianim_core.common import SchemaVersion, Slug, StrictModel, ensure_unique
from scianim_core.components import REGISTRY, ComponentKind, FunctionPlotParams, validate_params
from scianim_core.style import Easing

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


Transform = Annotated[FilterTransform | NormalizeTransform | SortTransform, Field(discriminator="op")]


class DataBinding(StrictModel):
    source: Slug
    encoding: DataEncoding
    transforms: list[Transform] = []


class EquationRef(StrictModel):
    id: Slug
    highlight: list[str] = []
    """Symbol names (keys of `equations[].symbols`) to emphasize."""


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
    """Vary one named parameter of a `function_plot` continuously while the viewer watches.

    The curve and its markers follow the value, the equation term named by `parameter` pulses once as the
    sweep begins, and a readout shows the running value. A checkpoint inside the window splits the sweep
    at that frame, so it is still reached by the real animation flow. One action plays at a time.
    """

    kind: Literal["vary_parameter"] = "vary_parameter"
    id: Slug
    target: Slug
    """A `function_plot` object in the same scene that declares `parameter` under `params.parameters`."""
    parameter: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    to: float = Field(allow_inf_nan=False)
    at_seconds: float = Field(ge=0)
    duration_seconds: float = Field(gt=0)
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
        return self.at_seconds + self.duration_seconds


SceneAction = VaryParameter
"""Further action kinds join a discriminated union on `kind`."""


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

    @model_validator(mode="after")
    def _checks(self) -> Scene:
        if self.end_seconds <= self.start_seconds:
            raise ValueError(
                f"scene '{self.id}': end_seconds ({self.end_seconds}) must exceed start_seconds ({self.start_seconds})"
            )
        ensure_unique((o.id for o in self.objects), f"object (scene '{self.id}')")
        ensure_unique((s.id for s in self.snapshots), f"snapshot (scene '{self.id}')")
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

        ordered = sorted(self.actions, key=lambda a: a.at_seconds)
        for earlier, later in pairwise(ordered):
            if later.at_seconds < earlier.end_seconds:
                raise ValueError(
                    f"action '{later.id}' at {later.at_seconds:g}s overlaps action '{earlier.id}' "
                    f"({earlier.at_seconds:g}-{earlier.end_seconds:g}s); one action plays at a time"
                )
        for action in self.actions:
            if action.at_seconds < self.start_seconds or action.end_seconds > self.end_seconds:
                raise ValueError(
                    f"action '{action.id}' ({action.at_seconds:g}-{action.end_seconds:g}s) lies outside scene "
                    f"'{self.id}' [{self.start_seconds}, {self.end_seconds}]"
                )
            target = objects.get(action.target)
            if target is None:
                raise ValueError(
                    f"action '{action.id}': target '{action.target}' is not an object of scene '{self.id}'"
                )
            if target.kind != "function_plot":
                raise ValueError(
                    f"action '{action.id}': target '{target.id}' is a {target.kind}; vary_parameter needs a function_plot"
                )
            params = target.typed_params()
            assert isinstance(params, FunctionPlotParams)
            if action.parameter not in params.parameters:
                raise ValueError(
                    f"action '{action.id}': '{target.id}' declares no parameter '{action.parameter}' "
                    f"(declared: {sorted(params.parameters) or 'none'})"
                )
            if params.y_range is None:
                raise ValueError(
                    f"action '{action.id}': give '{target.id}' a y_range so the axes stay fixed while "
                    f"'{action.parameter}' varies"
                )
            if reveal_time(target) > action.at_seconds:
                raise ValueError(
                    f"action '{action.id}' at {action.at_seconds:g}s starts before its target '{target.id}' "
                    f"is revealed at {reveal_time(target):g}s"
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
            for obj in self.objects:
                if obj.reveal_at_seconds is not None and action.at_seconds < obj.reveal_at_seconds < action.end_seconds:
                    raise ValueError(
                        f"object '{obj.id}' is revealed at {obj.reveal_at_seconds:g}s, inside action '{action.id}' "
                        f"({action.at_seconds:g}-{action.end_seconds:g}s); one thing plays at a time"
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
