"""Style tokens as Manim quantities. No hardcoded colors or sizes live outside this module."""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Any

import numpy as np
from manim import (
    DL,
    DOWN,
    DR,
    LEFT,
    ORIGIN,
    RIGHT,
    UL,
    UP,
    UR,
    CapStyleType,
    LineJointType,
    ManimColor,
    Mobject,
    Text,
    config,
)

from scianim_core import ResolvedStyle
from scianim_core.style import Anchor, TextRole, Typeface

CAIRO_LINE_WIDTH_MULTIPLE = 0.01
"""Manim's Cairo camera draws `stroke_width` 1 as 0.01 frame units (Camera default)."""

CAP_HEIGHT_RATIO = 0.72
"""Approximate capital height as a fraction of the em size for sans-serif faces; used only to
calibrate Manim's font_size against the style's pixel sizes."""

WEIGHTS: dict[str, str] = {
    "light": "LIGHT",
    "regular": "NORMAL",
    "medium": "MEDIUM",
    "semibold": "SEMIBOLD",
    "bold": "BOLD",
}

_ANCHORS: dict[str, tuple[tuple[float, float], np.ndarray | None]] = {
    "top_left": ((-1, 1), UL),
    "top_center": ((0, 1), UP),
    "top_right": ((1, 1), UR),
    "center_left": ((-1, 0), LEFT),
    "center": ((0, 0), None),
    "center_right": ((1, 0), RIGHT),
    "bottom_left": ((-1, -1), DL),
    "bottom_center": ((0, -1), DOWN),
    "bottom_right": ((1, -1), DR),
}


FONT_WARNINGS: list[str] = []
"""Human-readable notes about fonts that were substituted; the worker copies them into the result."""


@lru_cache(maxsize=1)
def installed_fonts() -> frozenset[str]:
    try:
        import manimpango

        return frozenset(name.lower() for name in manimpango.list_fonts())
    except Exception:
        return frozenset()


def resolve_font(typeface: Typeface) -> str:
    """The first installed family among the typeface's family and fallbacks; generic names pass through."""
    available = installed_fonts()
    candidates = [typeface.font_family, *typeface.font_fallbacks]
    generic = {"sans-serif", "sans", "serif", "monospace"}
    for candidate in candidates:
        if candidate.lower() in available:
            if candidate != typeface.font_family:
                _warn_font(f"font '{typeface.font_family}' is not installed; using fallback '{candidate}'")
            return candidate
        if candidate.lower() in generic:
            _warn_font(f"font '{typeface.font_family}' is not installed; using the generic '{candidate}' family")
            return "sans" if candidate == "sans-serif" else candidate
    _warn_font(
        f"font '{typeface.font_family}' and its fallbacks {typeface.font_fallbacks} are not installed; Pango will substitute"
    )
    return typeface.font_family


def _warn_font(message: str) -> None:
    if message not in FONT_WARNINGS:
        FONT_WARNINGS.append(message)


@lru_cache(maxsize=8)
def text_units_per_point(font: str, weight: str) -> float:
    """Measured height of a capital letter per font_size point, for this font."""
    probe = Text("H", font=font, weight=weight, font_size=100, warn_missing_font=False)
    return float(probe.height) / 100.0


@lru_cache(maxsize=4)
def typst_units_per_point(preamble: str = "") -> float:
    from manim import MathTypst

    probe = MathTypst("H", font_size=100, typst_preamble=preamble)
    return float(probe.height) / 100.0


@lru_cache(maxsize=2)
def tex_units_per_point() -> float:
    from manim import MathTex

    probe = MathTex("H", font_size=100)
    return float(probe.height) / 100.0


class Tokens:
    """Resolved style tokens converted to Manim units for the current render configuration."""

    def __init__(self, style: ResolvedStyle) -> None:
        self.style = style
        self.t = style.tokens

    # --- colors -------------------------------------------------------------------------------
    def color(self, role: str) -> ManimColor:
        try:
            return ManimColor(self.t.palette[role])
        except KeyError:
            raise KeyError(f"style role '{role}' is not in the palette; roles: {sorted(self.t.palette)}") from None

    # --- geometry -----------------------------------------------------------------------------
    @property
    def frame_width(self) -> float:
        return float(config.frame_width)

    @property
    def frame_height(self) -> float:
        return float(config.frame_height)

    def units(self, px_at_1080p: float) -> float:
        """Frame units for a length given in pixels at 1080p (independent of render resolution)."""
        return px_at_1080p / 1080.0 * self.frame_height

    def output_px(self, px_at_1080p: float) -> float:
        return px_at_1080p * float(config.pixel_height) / 1080.0

    def stroke_width(self, px_at_1080p: float) -> float:
        return self.units(px_at_1080p) / CAIRO_LINE_WIDTH_MULTIPLE

    def line_kwargs(self) -> dict[str, Any]:
        """How lines end and bend, from `geometry.line_cap`: pass to any stroked Manim object."""
        if self.t.geometry.line_cap == "round":
            return {"cap_style": CapStyleType.ROUND, "joint_type": LineJointType.ROUND}
        return {}

    def dot_kwargs(self, fill: ManimColor) -> dict[str, Any]:
        """A filled dot in `fill`, with the page-coloured rim `geometry.marker_rim_px_at_1080p` asks for."""
        rim = self.t.geometry.marker_rim_px_at_1080p
        if rim > 0:
            return {
                "fill_color": fill,
                "fill_opacity": 1.0,
                "stroke_color": self.color("background"),
                "stroke_width": self.stroke_width(rim),
            }
        return {"fill_color": fill, "fill_opacity": 1.0, "stroke_width": 0}

    def light_direction(self) -> np.ndarray | None:
        """Unit vector toward the light of `three_d`, in world coordinates, or None when the wash stays flat.

        The azimuth is relative to the camera's starting azimuth, so a sheet says where the light stands
        for the viewer at the start; it then stays fixed in the world while the camera orbits."""
        t3 = self.t.three_d
        if t3.shading_strength <= 0:
            return None
        azimuth = math.radians(t3.camera_theta_degrees + t3.light_azimuth_degrees)
        elevation = math.radians(t3.light_elevation_degrees)
        return np.array(
            [math.cos(elevation) * math.cos(azimuth), math.cos(elevation) * math.sin(azimuth), math.sin(elevation)]
        )

    def safe_rect(self) -> tuple[float, float, float, float]:
        m = self.t.layout.safe_margin_fraction
        fw, fh = self.frame_width, self.frame_height
        return (-fw / 2 + m * fw, -fh / 2 + m * fh, fw / 2 - m * fw, fh / 2 - m * fh)

    def place(self, mobject: Mobject, anchor: Anchor) -> Mobject:
        (sx, sy), edge = _ANCHORS[anchor]
        x0, y0, x1, y1 = self.safe_rect()
        x = {-1: x0, 0: 0.0, 1: x1}[sx]
        y = {-1: y0, 0: 0.0, 1: y1}[sy]
        if edge is None:
            return mobject.move_to(ORIGIN)
        return mobject.move_to(np.array([x, y, 0.0]), aligned_edge=edge)

    # --- typography ---------------------------------------------------------------------------
    def typeface(self, role: TextRole) -> Typeface:
        """The typeface of a named text role; sizes are tokens, never multiples of another role."""
        return getattr(self.t.typography, role)

    def smallest_text_px(self, *roles_and_sizes: TextRole | float) -> float:
        """Output pixels of the smallest em size among text roles and explicit 1080p sizes (layout report)."""
        sizes = [
            item if isinstance(item, int | float) else self.typeface(item).size_px_at_1080p for item in roles_and_sizes
        ]
        return self.output_px(min(sizes))

    def font_size(self, typeface: Typeface, px_at_1080p: float | None = None) -> float:
        """Manim font_size whose capital height matches `px_at_1080p * CAP_HEIGHT_RATIO`."""
        px = px_at_1080p if px_at_1080p is not None else typeface.size_px_at_1080p
        cap_units = self.units(px) * CAP_HEIGHT_RATIO
        return cap_units / text_units_per_point(resolve_font(typeface), WEIGHTS[typeface.weight])

    def text_kwargs(self, typeface: Typeface, color: ManimColor, px_at_1080p: float | None = None) -> dict:
        return {
            "font": resolve_font(typeface),
            "weight": WEIGHTS[typeface.weight],
            "font_size": self.font_size(typeface, px_at_1080p),
            "color": color,
            "warn_missing_font": False,
        }

    def equation_font_size(self, px_at_1080p: float | None = None) -> float:
        px = px_at_1080p if px_at_1080p is not None else self.t.typography.equation.size_px_at_1080p
        cap_units = self.units(px) * CAP_HEIGHT_RATIO
        if self.t.typography.equation.engine == "typst":
            return cap_units / typst_units_per_point(self.typst_preamble())
        return cap_units / tex_units_per_point()

    def typst_preamble(self) -> str:
        """A `show` rule selecting the math font (and fallbacks) for Typst equations, or empty."""
        equation = self.t.typography.equation
        if not equation.math_font:
            return ""
        families = ", ".join(f'"{name}"' for name in [equation.math_font, *equation.math_font_fallbacks])
        return f"#show math.equation: set text(font: ({families},))"

    def tex_template(self):
        """A Manim TexTemplate carrying the style's extra LaTeX packages."""
        from manim import TexTemplate

        template = TexTemplate()
        for package in self.t.typography.equation.latex_packages:
            template.add_to_preamble(f"\\usepackage{{{package}}}")
        return template

    @property
    def panel_gap(self) -> float:
        return self.units(self.t.layout.panel_gap_px_at_1080p)

    @property
    def baseline(self) -> float:
        return self.units(self.t.layout.baseline_grid_px_at_1080p)
