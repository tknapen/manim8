"""Style sheets (partial, inheritable files) and resolved style tokens (spec section 5.3)."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, create_model

from scianim_core.common import HexColor, SchemaVersion, SemVer, Slug, StrictModel

Anchor = Literal[
    "top_left",
    "top_center",
    "top_right",
    "center_left",
    "center",
    "center_right",
    "bottom_left",
    "bottom_center",
    "bottom_right",
]
EquationEngine = Literal["typst", "latex"]
FontWeight = Literal["light", "regular", "medium", "semibold", "bold"]

REQUIRED_PALETTE_ROLES: frozenset[str] = frozenset(
    {
        "background",
        "foreground",
        "secondary_text",
        "muted",
        "neutral",
        "primary_signal",
        "emphasis",
        "warning",
        "comparison",
    }
)
"""Palette roles every resolved style must define. Themes may add more."""


class Typeface(StrictModel):
    font_family: str = Field(min_length=1)
    font_fallbacks: list[str] = []
    size_px_at_1080p: float = Field(gt=0)
    weight: FontWeight = "regular"


class EquationStyle(StrictModel):
    engine: EquationEngine = "typst"
    size_px_at_1080p: float = Field(gt=0)


class Typography(StrictModel):
    title: Typeface
    body: Typeface
    equation: EquationStyle
    minimum_body_px_at_1080p: float = Field(gt=0)


class Layout(StrictModel):
    safe_margin_fraction: float = Field(ge=0, lt=0.5)
    baseline_grid_px_at_1080p: float = Field(gt=0)
    panel_gap_px_at_1080p: float = Field(ge=0)
    preferred_alignment: Literal["left", "center", "right"] = "left"


class Geometry(StrictModel):
    axis_stroke_px_at_1080p: float = Field(gt=0)
    curve_stroke_px_at_1080p: float = Field(gt=0)
    annotation_stroke_px_at_1080p: float = Field(gt=0)
    marker_radius_px_at_1080p: float = Field(default=6.0, gt=0)


class Charts(StrictModel):
    grid_visible: bool = False
    use_shared_scales_for_comparison: bool = True
    legend_position: Literal["upper_right", "upper_left", "lower_right", "lower_left"] = "upper_right"
    show_units_when_provided: bool = True


class Motion(StrictModel):
    transition_seconds: float = Field(gt=0)
    reveal_seconds: float = Field(gt=0)
    easing: Literal["linear", "ease_in_out_sine", "smooth", "ease_out_cubic"] = "smooth"
    avoid_decorative_motion: bool = True
    narration_words_per_minute: float = Field(default=150, gt=0)


class Accessibility(StrictModel):
    do_not_rely_on_color_alone: bool = True
    warn_on_low_contrast: bool = True
    minimum_contrast_body: float = Field(default=4.5, gt=0)


class StyleTokens(StrictModel):
    """Fully resolved tokens. Every section is required; unknown keys are errors."""

    palette: dict[Slug, HexColor]
    typography: Typography
    layout: Layout
    geometry: Geometry
    charts: Charts
    motion: Motion
    accessibility: Accessibility

    def missing_palette_roles(self) -> list[str]:
        return sorted(REQUIRED_PALETTE_ROLES - set(self.palette))


def make_partial(model: type[BaseModel], prefix: str = "Partial") -> type[BaseModel]:
    """Return a copy of `model` with every field optional (recursively), still `extra='forbid'`.

    Partial models validate the structure of an inheriting style sheet without requiring it
    to restate every token.
    """
    fields: dict[str, Any] = {}
    for name, info in model.model_fields.items():
        annotation = info.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            annotation = make_partial(annotation, prefix)
        fields[name] = (Optional[annotation], None)  # noqa: UP045 - runtime construction
    return create_model(f"{prefix}{model.__name__}", __config__=ConfigDict(extra="forbid"), **fields)


PartialTypography = make_partial(Typography)
PartialLayout = make_partial(Layout)
PartialGeometry = make_partial(Geometry)
PartialCharts = make_partial(Charts)
PartialMotion = make_partial(Motion)
PartialAccessibility = make_partial(Accessibility)

TOKEN_SECTIONS: tuple[str, ...] = (
    "palette",
    "typography",
    "layout",
    "geometry",
    "charts",
    "motion",
    "accessibility",
)


class StyleSheet(StrictModel):
    """A `style.yaml` file. Sections may be partial when the sheet inherits from another."""

    schema_version: SchemaVersion
    name: Slug
    version: SemVer
    description: str | None = None
    inherits: Slug | None = None
    palette: dict[Slug, HexColor] = {}
    typography: PartialTypography | None = None  # type: ignore[valid-type]
    layout: PartialLayout | None = None  # type: ignore[valid-type]
    geometry: PartialGeometry | None = None  # type: ignore[valid-type]
    charts: PartialCharts | None = None  # type: ignore[valid-type]
    motion: PartialMotion | None = None  # type: ignore[valid-type]
    accessibility: PartialAccessibility | None = None  # type: ignore[valid-type]

    def tokens_dict(self) -> dict[str, Any]:
        """Nested dict of the tokens this sheet sets (None values removed)."""
        data = self.model_dump(include=set(TOKEN_SECTIONS), exclude_none=True)
        return {k: v for k, v in data.items() if v not in (None, {})}


class ResolvedStyle(StrictModel):
    """What the renderer receives: all tokens, where each came from, and a content hash."""

    schema_version: SchemaVersion = "1.0"
    theme: Slug
    theme_version: SemVer
    layers: list[str]
    """Layer names in application order, e.g. ['default@0.1.0', 'tomas_scientific@0.1.0', 'family:…']."""
    tokens: StyleTokens
    provenance: dict[str, str]
    """Dotted token path to the layer that set it."""
    hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    def px(self, px_at_1080p: float, output_height_px: int) -> float:
        """Scale a token given in pixels at 1080p to the actual output height."""
        return px_at_1080p * output_height_px / 1080.0
