"""The component registry: the contract shared by storyboard, validator, codegen and renderer.

Each registered kind has a parameter model (validated at storyboard load), declared data and
equation requirements, the style roles it consumes, and a version that enters cache keys.
`custom` is the explicit escape hatch: it names a builder function in the project's `code/`
directory and never embeds code in YAML (spec section 10.4, ADR-003).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import Field, ValidationError, model_validator

from scianim_core.common import Slug, StrictModel
from scianim_core.expressions import ALLOWED_CONSTANTS, ALLOWED_FUNCTIONS, compile_expression, validate_expression
from scianim_core.style import Anchor

REGISTRY_VERSION = "0.4.0"

ComponentKind = Literal[
    "text_caption",
    "scientific_plot",
    "function_plot",
    "surface_plot",
    "function_image",
    "equation_block",
    "equation_label",
    "comparison_plot",
    "caption_with_citation",
    "schematic_population",
    "receptive_field_glyph",
    "network_graph",
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


PARAMETER_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PARAMETRIC_KINDS: frozenset[str] = frozenset({"function_plot", "surface_plot", "function_image"})
"""Kinds with named `parameters` that a `vary_parameter` action can sweep."""


def check_parameters(parameters: dict[str, float], reserved: tuple[str, ...]) -> None:
    for name, value in parameters.items():
        if not PARAMETER_NAME.match(name) or name in reserved or name in ALLOWED_FUNCTIONS or name in ALLOWED_CONSTANTS:
            raise ValueError(
                f"parameter name '{name}' must be an identifier other than {list(reserved)}, a built-in function "
                "or a constant"
            )
        if not math.isfinite(value):
            raise ValueError(f"parameter '{name}' must be a finite number")


class FunctionSeries(StrictModel):
    label: str = Field(min_length=1)
    expression: str = Field(min_length=1)
    """Arithmetic in x and the plot's `parameters`: operators + - * / ^ %, functions exp log log10 sqrt sin cos tan tanh abs min max pow, constants pi e tau."""
    style_role: Slug | None = None


class Marker(StrictModel):
    """A labelled vertical reference line at x: a number, or an expression in the plot's `parameters` (so the
    marker follows a parameter that a `vary_parameter` action animates)."""

    x: float | str = Field(union_mode="left_to_right")
    label: str | None = None
    style_role: Slug | None = None


class FunctionPlotParams(StrictModel):
    x_label: str = Field(min_length=1)
    y_label: str = Field(min_length=1)
    x_range: tuple[float, float]
    y_range: tuple[float, float] | None = None
    """Fixed vertical range. Required when a `vary_parameter` action targets the plot, so the axes stay put."""
    samples: int = Field(default=200, ge=2, le=5000)
    parameters: dict[str, float] = {}
    """Named constants used by `series[].expression` and `markers[].x`, e.g. {sigma: 1.5}. A scene action of kind
    `vary_parameter` animates one of them; name them after the equation's symbols so the emphasized term and the
    curve agree."""
    series: list[FunctionSeries] = Field(min_length=1)
    markers: list[Marker] = []
    show_legend: bool = True
    data_label: str | None = None
    """Caption such as 'analytic curve, not measurements'."""
    anchor: Anchor = "center"
    width_fraction: float = Field(default=0.62, gt=0, le=1)
    height_fraction: float = Field(default=0.62, gt=0, le=1)

    @model_validator(mode="after")
    def _checks(self) -> FunctionPlotParams:
        check_parameters(self.parameters, ("x",))
        variables = ("x", *self.parameters)
        for series in self.series:
            validate_expression(series.expression, variables)
        if self.x_range[0] >= self.x_range[1]:
            raise ValueError("x_range must be [low, high] with low < high")
        if self.y_range is not None and self.y_range[0] >= self.y_range[1]:
            raise ValueError("y_range must be [low, high] with low < high")
        for marker in self.markers:
            x = self.marker_x(marker)
            if not (self.x_range[0] <= x <= self.x_range[1]):
                raise ValueError(f"marker at x={marker.x!r} (= {x:g}) lies outside x_range {list(self.x_range)}")
        return self

    def marker_x(self, marker: Marker, parameters: dict[str, float] | None = None) -> float:
        """A marker's position for the given (default: declared) parameter values."""
        if isinstance(marker.x, int | float):
            return float(marker.x)
        values = dict(self.parameters)
        values.update(parameters or {})
        x = compile_expression(marker.x, tuple(self.parameters))(**values)
        if not math.isfinite(x):
            raise ValueError(f"marker expression {marker.x!r} is not finite for parameters {values}")
        return x


class SurfacePlotParams(StrictModel):
    """A surface z = f(x, y) over a box, drawn as a fine mesh in three dimensions.

    The camera can orbit it (`orbit_camera`), its `parameters` can be swept (`vary_parameter`) and its frame,
    ticks and labels can leave once the shape is understood (`fade_axes`); the box never rescales. Flat objects
    in the same scene stay fixed in the frame while the surface turns.
    """

    x_label: str = Field(min_length=1)
    y_label: str = Field(min_length=1)
    z_label: str = Field(min_length=1)
    x_range: tuple[float, float]
    y_range: tuple[float, float]
    z_range: tuple[float, float]
    """Fixed vertical range; values outside it are clipped to the box and a warning is recorded."""
    expression: str = Field(min_length=1)
    """Arithmetic in x, y and `parameters`; the same whitelist as function_plot."""
    parameters: dict[str, float] = {}
    resolution: int = Field(default=40, ge=4, le=120)
    """Mesh cells per axis."""
    fill: Literal["by_sign", "by_height", "none"] = "by_sign"
    """`by_sign`: positive cells in the style role, negative cells in the comparison ink; `by_height`: opacity rises with height."""
    data_label: str | None = None
    size_fraction: float = Field(default=0.6, gt=0, le=1)
    """Footprint of the box as a fraction of the safe height."""

    @model_validator(mode="after")
    def _checks(self) -> SurfacePlotParams:
        check_parameters(self.parameters, ("x", "y"))
        validate_expression(self.expression, ("x", "y", *self.parameters))
        for name, (low, high) in (("x_range", self.x_range), ("y_range", self.y_range), ("z_range", self.z_range)):
            if low >= high:
                raise ValueError(f"{name} must be [low, high] with low < high")
        return self


class FunctionImageParams(StrictModel):
    """A scalar field f(x, y) sampled to an image: a grating, a kernel, a map. Two inks or grey."""

    expression: str = Field(min_length=1)
    parameters: dict[str, float] = {}
    x_range: tuple[float, float]
    y_range: tuple[float, float]
    resolution: int = Field(default=64, ge=8, le=512)
    """Pixels per axis."""
    value_range: tuple[float, float] = (-1.0, 1.0)
    """Values map onto the colour scale across this fixed range, so a sweep never rescales the image."""
    colors: Literal["two_ink", "grey"] = "two_ink"
    """`two_ink`: negative values in the comparison ink, positive in the style role, zero white; `grey`: dark to light."""
    mask: Literal["none", "circle"] = "none"
    label: str | None = None
    data_label: str | None = None
    anchor: Anchor = "center"
    size_fraction: float = Field(default=0.4, gt=0, le=1)
    """Height of the image as a fraction of the safe height."""

    @model_validator(mode="after")
    def _checks(self) -> FunctionImageParams:
        check_parameters(self.parameters, ("x", "y"))
        validate_expression(self.expression, ("x", "y", *self.parameters))
        for name, (low, high) in (
            ("x_range", self.x_range),
            ("y_range", self.y_range),
            ("value_range", self.value_range),
        ):
            if low >= high:
                raise ValueError(f"{name} must be [low, high] with low < high")
        return self


class CustomParams(StrictModel):
    builder: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_]*$")
    """'module:function' resolved inside the project's `code/` directory."""
    arguments: dict[str, Any] = {}


class CaptionWithCitationParams(Placement):
    """A caption whose second line cites a declared source, so a scientific claim stays traceable."""

    text: str = Field(min_length=1)
    source: Slug
    """Id of a source in animation.yaml; its citation (or path) is typeset under the text."""
    locator: str | None = None
    """Page, figure or table reference appended to the citation."""
    role: TextRole = "caption"


class SchematicPopulationParams(StrictModel):
    """A row or grid of unit glyphs whose fill encodes activity; a schematic, never a measurement."""

    count: int = Field(ge=1, le=64)
    arrangement: Literal["row", "grid"] = "row"
    columns: int | None = Field(default=None, ge=1)
    activity: list[float] | None = None
    """One value in [0, 1] per unit; requires `data_label` because the values are illustrative."""
    data_label: str | None = None
    label: str | None = None
    unit_radius_px_at_1080p: float = Field(default=18, gt=0)
    anchor: Anchor = "center"
    width_fraction: float = Field(default=0.6, gt=0, le=1)

    @model_validator(mode="after")
    def _activity_shape(self) -> SchematicPopulationParams:
        if self.activity is not None:
            if len(self.activity) != self.count:
                raise ValueError(f"activity has {len(self.activity)} values for {self.count} units")
            if any(not 0 <= value <= 1 for value in self.activity):
                raise ValueError("activity values must lie in [0, 1]")
            if not self.data_label:
                raise ValueError("activity values are illustrative; give a data_label that says so")
        return self


class ReceptiveFieldGlyphParams(StrictModel):
    """A Gaussian receptive field drawn as contour rings inside a square visual-field box."""

    center: tuple[float, float] = (0.0, 0.0)
    sigma: float = Field(gt=0)
    field_extent: float = Field(default=10.0, gt=0)
    """Half-width of the visual field box, in the same units as `center` and `sigma`."""
    label: str | None = None
    show_axes: bool = True
    data_label: str | None = None
    anchor: Anchor = "center"
    size_fraction: float = Field(default=0.5, gt=0, le=1)

    @model_validator(mode="after")
    def _inside_the_field(self) -> ReceptiveFieldGlyphParams:
        if any(abs(c) > self.field_extent for c in self.center):
            raise ValueError("center lies outside the field box; enlarge field_extent")
        return self


class GraphNode(StrictModel):
    id: Slug
    label: str | None = None
    style_role: Slug | None = None


class GraphEdge(StrictModel):
    source: Slug
    target: Slug
    weight: float = 1.0
    """Sign and magnitude: negative weights are drawn dashed (inhibitory), thickness scales with |weight|."""
    style_role: Slug | None = None
    directed: bool = True


class NetworkGraphParams(StrictModel):
    """A small network: nodes on a circle, a row or a grid with weighted, optionally directed edges."""

    nodes: list[GraphNode] = Field(min_length=1, max_length=32)
    edges: list[GraphEdge] = []
    layout: Literal["circle", "row", "grid"] = "circle"
    columns: int | None = Field(default=None, ge=1)
    node_radius_px_at_1080p: float = Field(default=28, gt=0)
    anchor: Anchor = "center"
    size_fraction: float = Field(default=0.6, gt=0, le=1)

    @model_validator(mode="after")
    def _consistent(self) -> NetworkGraphParams:
        ids = [n.id for n in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("node ids must be unique")
        known = set(ids)
        for edge in self.edges:
            for end in (edge.source, edge.target):
                if end not in known:
                    raise ValueError(f"edge {edge.source}->{edge.target} references unknown node '{end}'")
        return self


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
    "surface_plot": ComponentDefinition(
        kind="surface_plot",
        params_model=SurfacePlotParams,
        requires_data=False,
        requires_equation=False,
        text_like=False,
        consumes=("palette.<style_role>", "palette.comparison", "palette.*", "typography.body", "geometry", "three_d"),
    ),
    "function_image": ComponentDefinition(
        kind="function_image",
        params_model=FunctionImageParams,
        requires_data=False,
        requires_equation=False,
        text_like=False,
        consumes=(
            "palette.<style_role>",
            "palette.comparison",
            "palette.background",
            "typography.annotation",
            "geometry",
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
    "caption_with_citation": ComponentDefinition(
        kind="caption_with_citation",
        params_model=CaptionWithCitationParams,
        requires_data=False,
        requires_equation=False,
        text_like=True,
        consumes=("palette.<style_role>", "palette.secondary_text", "typography.caption", "typography.body"),
    ),
    "schematic_population": ComponentDefinition(
        kind="schematic_population",
        params_model=SchematicPopulationParams,
        requires_data=False,
        requires_equation=False,
        text_like=False,
        consumes=("palette.<style_role>", "palette.neutral", "typography.annotation", "typography.caption", "geometry"),
    ),
    "receptive_field_glyph": ComponentDefinition(
        kind="receptive_field_glyph",
        params_model=ReceptiveFieldGlyphParams,
        requires_data=False,
        requires_equation=False,
        text_like=False,
        consumes=(
            "palette.<style_role>",
            "palette.*_soft",
            "palette.secondary_text",
            "typography.tick_label",
            "typography.annotation",
            "geometry",
        ),
    ),
    "network_graph": ComponentDefinition(
        kind="network_graph",
        params_model=NetworkGraphParams,
        requires_data=False,
        requires_equation=False,
        text_like=False,
        consumes=("palette.<style_role>", "palette.*", "typography.annotation", "geometry"),
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
