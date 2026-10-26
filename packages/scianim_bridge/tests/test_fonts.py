"""Font resolution through fallbacks (needs manimpango, so this runs inside the family environment)."""

from __future__ import annotations

import pytest

manimpango = pytest.importorskip("manimpango")


def test_resolve_font_prefers_family_then_fallbacks_and_warns() -> None:
    from scianim_bridge import tokens
    from scianim_core.style import Typeface

    installed = {name.lower() for name in manimpango.list_fonts()}
    assert "dejavu sans" in installed, "DejaVu Sans is a documented prerequisite"
    tokens.FONT_WARNINGS.clear()
    exact = Typeface(font_family="DejaVu Sans", font_fallbacks=["sans-serif"], size_px_at_1080p=32)
    assert tokens.resolve_font(exact) == "DejaVu Sans"
    assert tokens.FONT_WARNINGS == []
    missing = Typeface(
        font_family="No Such Face", font_fallbacks=["Another Missing", "DejaVu Sans"], size_px_at_1080p=32
    )
    assert tokens.resolve_font(missing) == "DejaVu Sans"
    assert any("No Such Face" in w and "DejaVu Sans" in w for w in tokens.FONT_WARNINGS)
    generic = Typeface(font_family="No Such Face", font_fallbacks=["sans-serif"], size_px_at_1080p=32)
    assert tokens.resolve_font(generic) == "sans"


def test_typst_preamble_and_tex_template_from_tokens() -> None:
    from scianim_bridge.tokens import Tokens
    from scianim_core.style import ResolvedStyle, StyleTokens

    typeface = {"font_family": "DejaVu Sans", "font_fallbacks": [], "size_px_at_1080p": 32, "weight": "regular"}
    roles = (
        "background",
        "foreground",
        "secondary_text",
        "muted",
        "neutral",
        "primary_signal",
        "emphasis",
        "warning",
        "comparison",
    )
    tokens = StyleTokens.model_validate(
        {
            "palette": dict.fromkeys(roles, "#111111"),
            "typography": {
                "title": typeface,
                "body": typeface,
                "annotation": typeface,
                "axis_label": typeface,
                "tick_label": typeface,
                "caption": typeface,
                "equation": {
                    "engine": "typst",
                    "size_px_at_1080p": 46,
                    "label_size_px_at_1080p": 38,
                    "math_font": "TeX Gyre Pagella Math",
                    "math_font_fallbacks": ["New Computer Modern Math"],
                    "latex_packages": ["newpxmath"],
                },
                "minimum_text_px_at_1080p": 26,
            },
            "layout": {"safe_margin_fraction": 0.05, "baseline_grid_px_at_1080p": 16, "panel_gap_px_at_1080p": 40},
            "geometry": {
                "axis_stroke_px_at_1080p": 2.0,
                "curve_stroke_px_at_1080p": 3.5,
                "annotation_stroke_px_at_1080p": 2.5,
            },
            "charts": {},
            "motion": {"transition_seconds": 0.65, "reveal_seconds": 0.85},
            "accessibility": {},
        }
    )
    style = ResolvedStyle(
        theme="t",
        theme_version="0.1.0",
        layers=["theme:t@0.1.0"],
        tokens=tokens,
        provenance={},
        hash="sha256:" + "0" * 64,
    )
    t = Tokens(style)
    assert (
        t.typst_preamble()
        == '#show math.equation: set text(font: ("TeX Gyre Pagella Math", "New Computer Modern Math",))'
    )
    assert "\\usepackage{newpxmath}" in t.tex_template().preamble
