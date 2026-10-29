"""Style sheets (partial, inheritable files) and resolved style tokens (spec section 5.3)."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, create_model, model_validator

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
StyleRef = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}@\d+\.\d+\.\d+$")]
"""`name@version`, the only way one sheet may refer to another; inheritance is pinned."""
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
    """Em size of a displayed equation (`equation_block`)."""
    label_size_px_at_1080p: float = Field(gt=0)
    """Em size of the compact equation shown under an `equation_label`."""
    math_font: str | None = None
    """OpenType math font for the typst engine (e.g. 'TeX Gyre Pagella Math'); None keeps Typst's default."""
    math_font_fallbacks: list[str] = []
    latex_packages: list[str] = []
    """Packages added to the LaTeX preamble for the latex engine (e.g. 'newpxmath' for Palatino math)."""


TextRole = Literal["title", "body", "annotation", "axis_label", "tick_label", "caption"]
"""Every piece of text a component draws is set in one of these named roles; sizes are never derived
by multiplying another role's size."""


class Typography(StrictModel):
    title: Typeface
    """Scene titles."""
    body: Typeface
    """Running text: subtitles, panel titles, label text."""
    annotation: Typeface
    """Marker labels, legend entries, symbol definitions."""
    axis_label: Typeface
    """Axis titles."""
    tick_label: Typeface
    """Tick values."""
    caption: Typeface
    """Data labels and figure captions."""
    equation: EquationStyle
    minimum_text_px_at_1080p: float = Field(gt=0)
    """No role may be smaller than this, and the layout report warns when rendered text falls below it."""

    @model_validator(mode="after")
    def _roles_meet_the_minimum(self) -> Typography:
        minimum = self.minimum_text_px_at_1080p
        sizes = {role: getattr(self, role).size_px_at_1080p for role in TEXT_ROLES}
        sizes["equation"] = self.equation.size_px_at_1080p
        sizes["equation.label"] = self.equation.label_size_px_at_1080p
        small = {role: size for role, size in sizes.items() if size < minimum}
        if small:
            raise ValueError(
                f"text roles below minimum_text_px_at_1080p={minimum:g}: "
                + ", ".join(f"{role}={size:g}" for role, size in sorted(small.items()))
            )
        return self


TEXT_ROLES: tuple[str, ...] = ("title", "body", "annotation", "axis_label", "tick_label", "caption")


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
    tick_length_px_at_1080p: float = Field(default=8.0, gt=0)
    """Length of the outward tick marks on the spines."""


Spine = Literal["left", "bottom", "top", "right"]


class Charts(StrictModel):
    spines: list[Spine] = ["left", "bottom"]
    """Which axis lines are drawn. Every plot kind is despined by default: only the left and bottom
    spines exist, drawn along the plot box edges and never through the origin."""
    spine_offset_px_at_1080p: float = Field(default=0.0, ge=0)
    """How far the left and bottom spines (with their ticks and labels) sit outside the data box."""
    grid_visible: bool = False
    use_shared_scales_for_comparison: bool = True
    legend_position: Literal["upper_right", "upper_left", "lower_right", "lower_left"] = "upper_right"
    show_units_when_provided: bool = True


Easing = Literal["linear", "ease_in_out_sine", "smooth", "ease_out_cubic", "eased_linear"]
"""Rate profiles. `smooth` and `ease_in_out_sine` ease over the whole window; `eased_linear` is constant speed
with a slow-in and a slow-out of `motion.ramp_seconds` each, for long continuous motions such as a camera orbit;
`linear` moves at constant speed from the first frame to the last and reads as mechanical."""


class Motion(StrictModel):
    transition_seconds: float = Field(gt=0)
    reveal_seconds: float = Field(gt=0)
    easing: Easing = "smooth"
    """Rate profile of everything that moves between two states and does not choose its own: parameter sweeps,
    axes fades, the colour of a term. Slow in, slow out: motion begins and ends at rest."""
    camera_easing: Easing | None = None
    """Rate profile of camera orbits; None means `easing`. A long orbit wants `eased_linear`: it ramps up over
    `ramp_seconds`, turns at constant speed and ramps down, where an orbit eased over its whole length would
    race in the middle."""
    ramp_seconds: float = Field(default=1.5, gt=0)
    """Length of the slow-in and of the slow-out of an `eased_linear` motion; a motion shorter than two ramps
    eases over its whole length."""
    hold_seconds: float = Field(default=0.0, ge=0)
    """Rest asked for between the end of one motion of an object and the start of the next, so an end state is
    seen before it changes again; `scianim validate` warns when a storyboard allows less. Zero asks nothing."""
    emphasis_scale: float = Field(default=1.3, gt=1, le=2)
    """How much an emphasized equation term grows, once, as a parameter sweep begins."""
    emphasis_seconds: float = Field(default=0.8, gt=0)
    """Duration of that pulse, a raised cosine: the term grows and settles without a kick at either end."""
    avoid_decorative_motion: bool = True
    narration_words_per_minute: float = Field(default=150, gt=0)


class ThreeD(StrictModel):
    """Surfaces and the orbiting camera. Flat objects stay fixed in the frame; only 3D kinds turn."""

    camera_phi_degrees: float = Field(default=62, ge=0, le=90)
    """Elevation of the camera above the floor plane at the start of every scene."""
    camera_theta_degrees: float = Field(default=-50)
    """Azimuth of the camera at the start of every scene; `orbit_camera` actions change it."""
    mesh_stroke_px_at_1080p: float = Field(default=0.8, gt=0)
    """Line weight of a surface mesh."""
    surface_opacity: float = Field(default=0.5, ge=0, le=1)
    """Fill opacity of surface cells, so the mesh behind stays visible."""


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
    three_d: ThreeD = ThreeD()

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
PartialThreeD = make_partial(ThreeD)

TOKEN_SECTIONS: tuple[str, ...] = (
    "palette",
    "typography",
    "layout",
    "geometry",
    "charts",
    "motion",
    "accessibility",
    "three_d",
)


class StyleSheet(StrictModel):
    """A `style.yaml` file. Sections may be partial when the sheet inherits from another."""

    schema_version: SchemaVersion
    name: Slug
    version: SemVer
    description: str | None = None
    inherits: StyleRef | None = None
    palette: dict[Slug, HexColor] = {}
    typography: PartialTypography | None = None  # type: ignore[valid-type]
    layout: PartialLayout | None = None  # type: ignore[valid-type]
    geometry: PartialGeometry | None = None  # type: ignore[valid-type]
    charts: PartialCharts | None = None  # type: ignore[valid-type]
    motion: PartialMotion | None = None  # type: ignore[valid-type]
    accessibility: PartialAccessibility | None = None  # type: ignore[valid-type]
    three_d: PartialThreeD | None = None  # type: ignore[valid-type]

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


def split_style_ref(ref: str) -> tuple[str, str]:
    """'tomas_scientific@0.1.0' -> ('tomas_scientific', '0.1.0')."""
    name, _, version = ref.partition("@")
    if not name or not version:
        raise ValueError(f"style reference must look like name@version, got {ref!r}")
    return name, version
