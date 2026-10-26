"""The component registry: the contract shared by storyboard, validator, codegen and renderer.

Each registered kind has a parameter model (validated at storyboard load), declared data and
equation requirements, the style roles it consumes, and a version that enters cache keys.
`custom` is the explicit escape hatch: it names a builder function in the project's `code/`
directory and never embeds code in YAML (spec section 10.4, ADR-003).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from scianim_core.common import Slug, StrictModel
from scianim_core.expressions import validate_expression
from scianim_core.style import Anchor

REGISTRY_VERSION = "0.2.0"

ComponentKind = Literal[
    "text_caption",
    "scientific_plot",
    "function_plot",
    "equation_block",
    "equation_label",
    "comparison_plot",
    "custom",
]
TextRole = Literal["title", "body", "caption"]


class Placement(StrictModel):
    """Where a text-like object goes: an anchor, or relative to an earlier object in the scene."""

    anchor: Anchor = "top_left"
    below: Slug | None = None
    """Place under this object (same scene, declared earlier), left edges aligned."""
    right_of: Slug | None = None
    gap_px_at_1080p: float | None = Field(default=None, gt=0)
    """Gap for `below` and `right_of`; defaults to the style's baseline grid."""

    @model_validator(mode="after")
    def _one_reference(self) -> Placement:
        if self.below and self.right_of:
            raise ValueError("use either 'below' or 'right_of', not both")
        return self


class TextCaptionParams(Placement):
    text: str = Field(min_length=1)
    role: TextRole = "body"


class ScientificPlotParams(StrictModel):
    x_label: str = Field(min_length=1)
    y_label: str = Field(min_length=1)
    x_range: tuple[float, float] | None = None
    y_range: tuple[float, float] | None = None
    data_label: str | None = None
    """Caption shown with the plot, e.g. 'synthetic data'. Required for illustrative data."""
    show_points: bool = True
    show_legend: bool = True
    anchor: Anchor = "center"
    width_fraction: float = Field(default=0.62, gt=0, le=1)
    height_fraction: float = Field(default=0.62, gt=0, le=1)


class EquationBlockParams(StrictModel):
    define_symbols: bool = False
    """Also list each symbol's meaning beneath the equation."""
    anchor: Anchor = "center"
    scale: float = Field(default=1.0, gt=0)


class EquationLabelParams(Placement):
    text: str = Field(min_length=1)
    anchor: Anchor = "top_right"
    show_equation: bool = True
    """Show the referenced equation with the highlighted terms beneath the label."""


class ComparisonPlotParams(StrictModel):
    condition_roles: dict[str, Slug] = Field(min_length=2)
    """Group value (from `data.encoding.group`) to palette role."""
    shared_axes: bool = True
    show_points: bool = True
    x_label: str = Field(min_length=1)
    y_label: str = Field(min_length=1)
    x_range: tuple[float, float] | None = None
    y_range: tuple[float, float] | None = None
    data_label: str | None = None
    anchor: Anchor = "center"
    width_fraction: float = Field(default=0.86, gt=0, le=1)
    height_fraction: float = Field(default=0.6, gt=0, le=1)


class FunctionSeries(StrictModel):
    label: str = Field(min_length=1)
    expression: str = Field(min_length=1)
    """Arithmetic in x: operators + - * / ^ %, functions exp log log10 sqrt sin cos tan tanh abs min max pow, constants pi e tau."""
    style_role: Slug | None = None

    @field_validator("expression")
    @classmethod
    def _safe(cls, value: str) -> str:
        validate_expression(value, ("x",))
        return value


class Marker(StrictModel):
    """A labelled vertical reference line at x."""

    x: float
    label: str | None = None
    style_role: Slug | None = None


class FunctionPlotParams(StrictModel):
    x_label: str = Field(min_length=1)
    y_label: str = Field(min_length=1)
    x_range: tuple[float, float]
    y_range: tuple[float, float] | None = None
    samples: int = Field(default=200, ge=2, le=5000)
    series: list[FunctionSeries] = Field(min_length=1)
    markers: list[Marker] = []
    show_legend: bool = True
    data_label: str | None = None
    """Caption such as 'analytic curve, not measurements'."""
    anchor: Anchor = "center"
    width_fraction: float = Field(default=0.62, gt=0, le=1)
    height_fraction: float = Field(default=0.62, gt=0, le=1)

    @model_validator(mode="after")
    def _ranges(self) -> FunctionPlotParams:
        if self.x_range[0] >= self.x_range[1]:
            raise ValueError("x_range must be [low, high] with low < high")
        if self.y_range is not None and self.y_range[0] >= self.y_range[1]:
            raise ValueError("y_range must be [low, high] with low < high")
        for marker in self.markers:
            if not (self.x_range[0] <= marker.x <= self.x_range[1]):
                raise ValueError(f"marker at x={marker.x} lies outside x_range {list(self.x_range)}")
        return self


class CustomParams(StrictModel):
    builder: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_]*$")
    """'module:function' resolved inside the project's `code/` directory."""
    arguments: dict[str, Any] = {}


@dataclass(frozen=True)
class ComponentDefinition:
    kind: str
    params_model: type[StrictModel]
    requires_data: bool
    requires_equation: bool
    text_like: bool
    """Text-like objects take part in `text_too_small` and `overlap` layout checks."""
    consumes: tuple[str, ...]
    """Token paths read by the bridge implementation, for documentation and cache precision."""
    version: str = REGISTRY_VERSION


REGISTRY: dict[str, ComponentDefinition] = {
    "text_caption": ComponentDefinition(
        kind="text_caption",
        params_model=TextCaptionParams,
        requires_data=False,
        requires_equation=False,
        text_like=True,
        consumes=("palette.<style_role>", "typography.title", "typography.body", "layout"),
    ),
    "scientific_plot": ComponentDefinition(
        kind="scientific_plot",
        params_model=ScientificPlotParams,
        requires_data=True,
        requires_equation=False,
        text_like=False,
        consumes=(
            "palette.<style_role>",
            "palette.foreground",
            "palette.secondary_text",
            "typography.body",
            "geometry",
            "charts",
            "layout",
        ),
    ),
    "function_plot": ComponentDefinition(
        kind="function_plot",
        params_model=FunctionPlotParams,
        requires_data=False,
        requires_equation=False,
        text_like=False,
        consumes=("palette.<style_role>", "palette.*", "typography.body", "geometry", "charts", "layout"),
    ),
    "equation_block": ComponentDefinition(
        kind="equation_block",
        params_model=EquationBlockParams,
        requires_data=False,
        requires_equation=True,
        text_like=True,
        consumes=("palette.<style_role>", "palette.secondary_text", "typography.equation"),
    ),
    "equation_label": ComponentDefinition(
        kind="equation_label",
        params_model=EquationLabelParams,
        requires_data=False,
        requires_equation=True,
        text_like=True,
        consumes=(
            "palette.<style_role>",
            "palette.foreground",
            "typography.body",
            "typography.equation",
        ),
    ),
    "comparison_plot": ComponentDefinition(
        kind="comparison_plot",
        params_model=ComparisonPlotParams,
        requires_data=True,
        requires_equation=False,
        text_like=False,
        consumes=("palette.*", "typography.body", "geometry", "charts", "layout"),
    ),
    "custom": ComponentDefinition(
        kind="custom",
        params_model=CustomParams,
        requires_data=False,
        requires_equation=False,
        text_like=False,
        consumes=("*",),
    ),
}


def validate_params(kind: str, params: dict[str, Any]) -> StrictModel:
    """Validate `params` for `kind`; raise ValueError with a readable message on failure."""
    definition = REGISTRY.get(kind)
    if definition is None:
        raise ValueError(f"unknown component kind '{kind}'; registered: {sorted(REGISTRY)}")
    try:
        return definition.params_model.model_validate(params)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or '<root>'}: {err['msg']}" for err in exc.errors()
        )
        raise ValueError(f"invalid params for kind '{kind}': {problems}") from None
