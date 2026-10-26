"""Style tokens as Manim quantities. No hardcoded colors or sizes live outside this module."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

import numpy as np
from manim import DL, DOWN, DR, LEFT, ORIGIN, RIGHT, UL, UP, UR, ManimColor, Mobject, Text, config

from scianim_core import ResolvedStyle
from scianim_core.style import Anchor, Typeface

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


@lru_cache(maxsize=8)
def text_units_per_point(font: str, weight: str) -> float:
    """Measured height of a capital letter per font_size point, for this font."""
    probe = Text("H", font=font, weight=weight, font_size=100, warn_missing_font=False)
    return float(probe.height) / 100.0


@lru_cache(maxsize=2)
def typst_units_per_point() -> float:
    from manim import MathTypst

    probe = MathTypst("H", font_size=100)
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
    def typeface(self, kind: Literal["title", "body"]) -> Typeface:
        return self.t.typography.title if kind == "title" else self.t.typography.body

    def font_size(self, typeface: Typeface, px_at_1080p: float | None = None) -> float:
        """Manim font_size whose capital height matches `px_at_1080p * CAP_HEIGHT_RATIO`."""
        px = px_at_1080p if px_at_1080p is not None else typeface.size_px_at_1080p
        cap_units = self.units(px) * CAP_HEIGHT_RATIO
        return cap_units / text_units_per_point(typeface.font_family, WEIGHTS[typeface.weight])

    def text_kwargs(self, typeface: Typeface, color: ManimColor, px_at_1080p: float | None = None) -> dict:
        return {
            "font": typeface.font_family,
            "weight": WEIGHTS[typeface.weight],
            "font_size": self.font_size(typeface, px_at_1080p),
            "color": color,
            "warn_missing_font": False,
        }

    def equation_font_size(self, px_at_1080p: float | None = None) -> float:
        px = px_at_1080p if px_at_1080p is not None else self.t.typography.equation.size_px_at_1080p
        cap_units = self.units(px) * CAP_HEIGHT_RATIO
        per_point = typst_units_per_point() if self.t.typography.equation.engine == "typst" else tex_units_per_point()
        return cap_units / per_point

    @property
    def panel_gap(self) -> float:
        return self.units(self.t.layout.panel_gap_px_at_1080p)

    @property
    def baseline(self) -> float:
        return self.units(self.t.layout.baseline_grid_px_at_1080p)
