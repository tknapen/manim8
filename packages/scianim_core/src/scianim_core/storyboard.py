"""`storyboard.yaml`: proposed visual implementation (spec section 5.2)."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from scianim_core.common import SchemaVersion, Slug, StrictModel, ensure_unique
from scianim_core.components import REGISTRY, ComponentKind, validate_params

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
    snapshots: list[Snapshot] = []

    @model_validator(mode="after")
    def _checks(self) -> Scene:
        if self.end_seconds <= self.start_seconds:
            raise ValueError(
                f"scene '{self.id}': end_seconds ({self.end_seconds}) must exceed start_seconds ({self.start_seconds})"
            )
        ensure_unique((o.id for o in self.objects), f"object (scene '{self.id}')")
        ensure_unique((s.id for s in self.snapshots), f"snapshot (scene '{self.id}')")
        for snapshot in self.snapshots:
            if not (self.start_seconds <= snapshot.at_seconds <= self.end_seconds):
                raise ValueError(
                    f"snapshot '{snapshot.id}' at {snapshot.at_seconds}s lies outside scene "
                    f"'{self.id}' [{self.start_seconds}, {self.end_seconds}]"
                )
        return self

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

    def scene_of_snapshot(self, snapshot_id: str) -> Scene:
        for scene in self.scenes:
            if any(s.id == snapshot_id for s in scene.snapshots):
                return scene
        raise KeyError(snapshot_id)
