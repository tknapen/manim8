"""`animation.yaml`: immutable scientific intent per revision (spec section 5.1)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from scianim_core.common import (
    AssetUri,
    Kind,
    RelPath,
    SchemaVersion,
    SemVer,
    Sha256,
    Slug,
    StrictModel,
    ensure_unique,
)

SourceType = Literal["csv", "pdf", "image", "markdown", "text", "project"]
SourceRole = Literal[
    "illustrative_data",
    "empirical_data",
    "composition_reference",
    "style_reference",
    "scientific_reference",
    "target_keyframe",
    "explanatory_text",
]
Container = Literal["mp4", "mov", "webm", "gif"]
VideoCodec = Literal["h264", "h265", "vp9", "prores", "none"]

ASPECT_RATIO_TOLERANCE = 0.005
"""Relative tolerance when checking width:height against the declared aspect ratio."""


class SymbolDef(StrictModel):
    meaning: str = Field(min_length=1)
    units: str | None = None


class Equation(StrictModel):
    """A typed equation. The renderer typesets the stored string exactly."""

    id: Slug
    typst: str | None = Field(default=None, min_length=1)
    latex: str | None = Field(default=None, min_length=1)
    symbols: dict[str, SymbolDef] = {}
    source: str | None = None
    """Optional locator in a source, e.g. 'paper_a: eq. 1'."""

    @model_validator(mode="after")
    def _at_least_one_source(self) -> Equation:
        if self.typst is None and self.latex is None:
            raise ValueError(f"equation '{self.id}' needs a 'typst' or 'latex' source string")
        return self

    def source_for(self, engine: Literal["typst", "latex"]) -> str | None:
        return self.typst if engine == "typst" else self.latex


class SourceRef(StrictModel):
    id: Slug
    type: SourceType
    path: RelPath | AssetUri = Field(union_mode="left_to_right")
    """Project-relative path, or `asset://<id>` for a shared family or workspace asset."""
    role: SourceRole
    citation: str | None = None
    locators: list[str] = []
    sha256: Sha256 | None = None


class OutputSpec(StrictModel):
    """Exact delivery specification. Width:height must agree with `aspect_ratio`."""

    duration_seconds: float = Field(gt=0)
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    aspect_ratio: str = Field(pattern=r"^\d+:\d+$")
    fps: float = Field(gt=0)
    container: Container = "mp4"
    video_codec: VideoCodec = "h264"
    audio: Literal["none"] = "none"

    @model_validator(mode="after")
    def _aspect_ratio_matches(self) -> OutputSpec:
        a_str, b_str = self.aspect_ratio.split(":")
        a, b = int(a_str), int(b_str)
        if a == 0 or b == 0:
            raise ValueError("aspect_ratio terms must be positive")
        declared = a / b
        actual = self.width_px / self.height_px
        if abs(actual - declared) > ASPECT_RATIO_TOLERANCE * declared:
            raise ValueError(
                f"width_px:height_px = {self.width_px}:{self.height_px} "
                f"({actual:.4f}) does not match aspect_ratio {self.aspect_ratio} ({declared:.4f})"
            )
        return self

    @property
    def frame_count(self) -> int:
        return round(self.duration_seconds * self.fps)


class StyleSelection(StrictModel):
    name: Slug
    version: SemVer
    overrides: dict[str, Any] = {}
    """Dotted token paths to values, e.g. {'palette.primary_signal': '#AABBCC'}; allowlisted."""


class Constraint(StrictModel):
    id: Slug
    kind: Kind = "hard"
    text: str = Field(min_length=1)
    equation: Slug | None = None
    """Reference to `equations[].id` when the constraint concerns an equation."""
    source: str | None = None


class Milestone(StrictModel):
    id: Slug
    at_seconds: float = Field(ge=0)
    tolerance_seconds: float = Field(default=0, ge=0)
    kind: Kind = "preferred"
    instruction: str = Field(min_length=1)


class Direction(StrictModel):
    tone: str | None = None
    avoid: list[str] = []
    prefer: list[str] = []


class AnimationSpec(StrictModel):
    schema_version: SchemaVersion
    id: Slug
    title: str = Field(min_length=1)
    family: Slug | None = None
    """Optional: the nearest ancestor `family.yaml` is authoritative; when present this must match it."""
    sources: list[SourceRef] = []
    output: OutputSpec
    style: StyleSelection
    equations: list[Equation] = []
    audience: str | None = None
    objective: str = Field(min_length=1)
    scientific_constraints: list[Constraint] = []
    timeline: list[Milestone] = []
    direction: Direction = Direction()
    extensions: dict[str, dict[str, Any]] = {}
    """Namespaced add-ons; the only place unknown keys are tolerated."""

    @model_validator(mode="after")
    def _cross_checks(self) -> AnimationSpec:
        ensure_unique((s.id for s in self.sources), "source")
        ensure_unique((e.id for e in self.equations), "equation")
        ensure_unique((c.id for c in self.scientific_constraints), "constraint")
        ensure_unique((m.id for m in self.timeline), "milestone")
        equation_ids = {e.id for e in self.equations}
        for constraint in self.scientific_constraints:
            if constraint.equation is not None and constraint.equation not in equation_ids:
                raise ValueError(
                    f"constraint '{constraint.id}' references unknown equation "
                    f"'{constraint.equation}'; known: {sorted(equation_ids)}"
                )
        duration = self.output.duration_seconds
        for milestone in self.timeline:
            if milestone.at_seconds > duration:
                raise ValueError(
                    f"milestone '{milestone.id}' at {milestone.at_seconds}s lies beyond the "
                    f"output duration of {duration}s"
                )
        return self

    def equation_by_id(self) -> dict[str, Equation]:
        return {e.id: e for e in self.equations}

    def source_by_id(self) -> dict[str, SourceRef]:
        return {s.id: s for s in self.sources}

    def hard_milestones(self) -> list[Milestone]:
        return [m for m in self.timeline if m.kind == "hard"]
