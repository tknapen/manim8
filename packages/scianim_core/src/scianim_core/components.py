"""The component registry: the contract shared by storyboard, validator, codegen and renderer.

Each registered kind has a parameter model (validated at storyboard load), declared data and
equation requirements, the style roles it consumes, and a version that enters cache keys.
`custom` is the explicit escape hatch: it names a builder function in the project's `code/`
directory and never embeds code in YAML (spec section 10.4, ADR-003).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import Field, ValidationError

from scianim_core.common import Slug, StrictModel
from scianim_core.style import Anchor

REGISTRY_VERSION = "0.1.0"

ComponentKind = Literal[
    "text_caption",
    "scientific_plot",
    "equation_block",
    "equation_label",
    "comparison_plot",
    "custom",
]
TextRole = Literal["title", "body", "caption"]


class TextCaptionParams(StrictModel):
    text: str = Field(min_length=1)
    role: TextRole = "body"
    anchor: Anchor = "top_left"


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


class EquationLabelParams(StrictModel):
    text: str = Field(min_length=1)
    anchor: Anchor = "top_right"
    show_equation: bool = True
    """Show the referenced equation with the highlighted terms beneath the label."""


class ComparisonPlotParams(StrictModel):
    condition_roles: dict[str, Slug] = Field(min_length=2)
    """Group value (from `data.encoding.group`) to palette role."""
    shared_axes: bool = True
    x_label: str = Field(min_length=1)
    y_label: str = Field(min_length=1)
    x_range: tuple[float, float] | None = None
    y_range: tuple[float, float] | None = None
    data_label: str | None = None
    anchor: Anchor = "center"
    width_fraction: float = Field(default=0.86, gt=0, le=1)
    height_fraction: float = Field(default=0.6, gt=0, le=1)


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
