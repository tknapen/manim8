from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np
from manim import DOWN, LEFT, ManimColor, Mobject, Text, VGroup

from scianim_bridge.components.base import Component, params_for, place, pretty_symbol, register
from scianim_bridge.tokens import Tokens
from scianim_core.animation import Equation
from scianim_core.storyboard import EquationRef

if TYPE_CHECKING:
    from scianim_bridge.scene import SnapshotScene


@dataclass
class EquationComponent(Component):
    """An equation object whose highlighted terms stay addressable, so a parameter sweep can emphasize one."""

    highlights: dict[str, Mobject] = field(default_factory=dict)
    """Highlighted symbol name to the glyphs that typeset it."""
    highlight_color: ManimColor | None = None
    base_color: ManimColor | None = None
    """The equation's own ink, which an `active`-mode term returns to when its action is over."""
    highlight_mode: str = "always"
    """`always`: highlighted terms keep the colour; `active`: only the term a running action emphasizes has it."""
    symbol_units: dict[str, str | None] = field(default_factory=dict)
    equation_id: str = ""
    """The equation shown now; a `transform_equation` action changes it (ADR-034)."""
    formula: Mobject | None = None
    """The typeset equation inside `group` (the label text, if any, is a separate member)."""
    highlight_names: list[str] = field(default_factory=list)
    """The symbols the storyboard asked to highlight; a transformed equation highlights those it mentions."""
    px_at_1080p: float = 0.0
    place_formula: Callable[[Mobject], None] | None = None
    """Puts a freshly typeset formula where this object's formula belongs."""
    text_is_formula: bool = False
    """True when `text` (the layout report's text) is the equation source rather than a label."""


def _group_symbols(source: str, symbols: list[str]) -> tuple[str, dict[str, list[str]]]:
    """Wrap every occurrence of each highlighted symbol in its own labelled Typst group (`{{ P : hl_P_1 }}`,
    `{{ P : hl_P_2 }}`, ...) and return the source with the labels per symbol, so each occurrence stays
    addressable on its own: a pulse scales occurrences about their own centres, not about the centre of all."""
    labels: dict[str, list[str]] = {}
    for symbol in symbols:
        pattern = rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])"

        def wrap(match: re.Match[str], symbol: str = symbol) -> str:
            label = f"hl_{symbol}_{len(labels.setdefault(symbol, [])) + 1}"
            labels[symbol].append(label)
            return "{{ " + symbol + " : " + label + " }}"

        source = re.sub(pattern, wrap, source)
    return source, labels


def build_equation(
    tokens: Tokens,
    equation: Equation,
    highlight: list[str],
    base_color: ManimColor,
    highlight_color: ManimColor,
    px_at_1080p: float,
) -> tuple[Mobject, dict[str, Mobject]]:
    """Typeset the stored source exactly; return the mobject and, per highlighted symbol, a group holding one
    sub-group per occurrence of that symbol."""
    engine = tokens.t.typography.equation.engine
    font_size = tokens.equation_font_size(px_at_1080p)
    source = equation.source_for(engine)
    if source is None:
        raise ValueError(f"equation '{equation.id}' has no '{engine}' source; the style uses the {engine} engine")
    parts: dict[str, Mobject] = {}
    if engine == "typst":
        from manim import MathTypst

        grouped, labels = _group_symbols(source, highlight)
        mobject = MathTypst(grouped, font_size=font_size, color=base_color, typst_preamble=tokens.typst_preamble())
        for symbol in highlight:
            occurrences = VGroup(*[mobject.select(label) for label in labels.get(symbol, [])])
            parts[symbol] = occurrences.set_color(highlight_color)
        return mobject, parts
    from manim import MathTex

    mobject = MathTex(
        source,
        substrings_to_isolate=highlight or None,
        font_size=font_size,
        color=base_color,
        tex_template=tokens.tex_template(),
    )
    for symbol in highlight:
        parts[symbol] = mobject.get_parts_by_tex(symbol).set_color(highlight_color)
    return mobject, parts


def typeset_equation(
    tokens: Tokens,
    equation: Equation,
    highlight: list[str],
    base_color: ManimColor,
    highlight_color: ManimColor,
    px_at_1080p: float,
    highlight_mode: str,
) -> tuple[Mobject, dict[str, Mobject]]:
    """`build_equation` with the highlight mode applied: in `active` mode the terms wait in the equation's ink."""
    main, parts = build_equation(tokens, equation, highlight, base_color, highlight_color, px_at_1080p)
    if highlight_mode == "active":
        for part in parts.values():
            part.set_color(base_color)
    return main, parts


def shape_key(glyph: Mobject) -> bytes:
    """A glyph's outline, centred and scaled to unit height and rounded, so two glyphs of the same character at
    the same size share a key wherever they sit (the test Manim's shape matching uses)."""
    points = np.asarray(glyph.points, dtype=float)
    if not len(points):
        return b""
    centred = points - points.mean(axis=0)
    height = float(centred[:, 1].max() - centred[:, 1].min())
    if height > 1e-9:
        centred = centred / height
    return (np.round(centred, 3) + 0.0).tobytes()


@dataclass
class Correspondence:
    """How one typeset equation becomes another: pieces that glide into partners, pieces that fade out, pieces
    that fade in. `matched_symbols` counts the occurrences paired by name per symbol."""

    pairs: list[tuple[Mobject, Mobject]] = field(default_factory=list)
    vanishing: list[Mobject] = field(default_factory=list)
    appearing: list[Mobject] = field(default_factory=list)
    matched_symbols: dict[str, int] = field(default_factory=dict)


def match_equations(
    old: Mobject,
    old_parts: dict[str, Mobject],
    new: Mobject,
    new_parts: dict[str, Mobject],
    match: str = "by_symbol",
) -> Correspondence:
    """Pair the glyphs of `old` with those of `new`.

    With `by_symbol`, the occurrences of each highlighted symbol pair by name and in order (the first `theta` of
    the old equation goes to the first of the new, and so on; spare occurrences are left for the shape pass).
    Everything still unpaired pairs by shape, left to right, so an `=` glides to the new `=` and a `2` to a `2`.
    Glyphs without a partner fade: named symbols are matched by meaning, everything else only by looks.
    """
    result = Correspondence()
    used_old: set[int] = set()
    used_new: set[int] = set()

    def leaves(mobject: Mobject) -> list[Mobject]:
        return [m for m in mobject.get_family() if len(m.points) and not m.submobjects]

    if match == "by_symbol":
        for symbol, old_group in old_parts.items():
            new_group = new_parts.get(symbol)
            if new_group is None:
                continue
            count = 0
            for old_piece, new_piece in zip(old_group.submobjects, new_group.submobjects, strict=False):
                result.pairs.append((old_piece, new_piece))
                used_old.update(id(m) for m in leaves(old_piece))
                used_new.update(id(m) for m in leaves(new_piece))
                count += 1
            if count:
                result.matched_symbols[symbol] = count
    rest_old = sorted((m for m in leaves(old) if id(m) not in used_old), key=lambda m: float(m.get_center()[0]))
    rest_new = sorted((m for m in leaves(new) if id(m) not in used_new), key=lambda m: float(m.get_center()[0]))
    by_shape: dict[bytes, list[Mobject]] = {}
    for glyph in rest_new:
        by_shape.setdefault(shape_key(glyph), []).append(glyph)
    for glyph in rest_old:
        candidates = by_shape.get(shape_key(glyph))
        if candidates:
            partner = candidates.pop(0)
            result.pairs.append((glyph, partner))
            used_new.add(id(partner))
        else:
            result.vanishing.append(glyph)
    result.appearing = [m for m in rest_new if id(m) not in used_new]
    return result


def _equation_for(
    scene: SnapshotScene, equation: dict[str, Any] | None, object_id: str
) -> tuple[Equation, EquationRef]:
    if equation is None:
        raise ValueError(f"object '{object_id}' needs an equation reference")
    ref = EquationRef.model_validate(equation)
    if scene.ctx is None:
        raise RuntimeError("no job context")
    try:
        return scene.ctx.equations[ref.id], ref
    except KeyError:
        raise KeyError(f"equation '{ref.id}' is not in the job; known: {sorted(scene.ctx.equations)}") from None


def _units_of(equation: Equation) -> dict[str, str | None]:
    return {name: definition.units for name, definition in equation.symbols.items()}


def equation_block(
    scene: SnapshotScene,
    object_id: str,
    *,
    style_role: str = "foreground",
    params: dict[str, Any] | None = None,
    equation: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
) -> Component:
    p = params_for("equation_block", params)
    tokens = scene.tokens
    eq, ref = _equation_for(scene, equation, object_id)
    px = tokens.t.typography.equation.size_px_at_1080p * p.scale
    highlight_color = tokens.color("emphasis")
    base_color = tokens.color(style_role)
    main, parts = typeset_equation(tokens, eq, ref.highlight, base_color, highlight_color, px, ref.highlight_mode)
    group = VGroup(main)
    smallest = [px]
    if p.define_symbols and eq.symbols:
        annotation = tokens.typeface("annotation")
        smallest.append(annotation.size_px_at_1080p)
        lines = VGroup()
        for name, definition in eq.symbols.items():
            text = f"{pretty_symbol(name)}: {definition.meaning}" + (
                f" ({definition.units})" if definition.units else ""
            )
            lines.add(Text(text, **tokens.text_kwargs(annotation, tokens.color("secondary_text"))))
        lines.arrange(DOWN, aligned_edge=LEFT, buff=tokens.baseline * 0.5)
        lines.next_to(main, DOWN, buff=tokens.panel_gap)
        lines.align_to(main, LEFT)
        group.add(lines)
    tokens.place(group, p.anchor)
    return register(
        scene,
        EquationComponent(
            object_id,
            "equation_block",
            group,
            text=eq.source_for(tokens.t.typography.equation.engine),
            font_px=tokens.smallest_text_px(*smallest),
            text_like=True,
            highlights=parts,
            highlight_color=highlight_color,
            base_color=base_color,
            highlight_mode=ref.highlight_mode,
            symbol_units=_units_of(eq),
            equation_id=eq.id,
            formula=main,
            highlight_names=list(ref.highlight),
            px_at_1080p=px,
            place_formula=lambda formula: tokens.place(formula, p.anchor),
            text_is_formula=True,
        ),
    )


def equation_label(
    scene: SnapshotScene,
    object_id: str,
    *,
    style_role: str = "foreground",
    params: dict[str, Any] | None = None,
    equation: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
) -> Component:
    p = params_for("equation_label", params)
    tokens = scene.tokens
    eq, ref = _equation_for(scene, equation, object_id)
    body = tokens.typeface("body")
    highlight_color = tokens.color(style_role)
    label = Text(p.text, **tokens.text_kwargs(body, highlight_color))
    group = VGroup(label)
    smallest = [body.size_px_at_1080p]
    parts: dict[str, Mobject] = {}
    base_color = tokens.color("foreground")
    formula: Mobject | None = None
    px = tokens.t.typography.equation.label_size_px_at_1080p

    def under_label(mobject: Mobject) -> None:
        mobject.next_to(label, DOWN, buff=tokens.baseline)
        mobject.align_to(label, LEFT)

    if p.show_equation:
        smallest.append(px)
        formula, parts = typeset_equation(
            tokens, eq, ref.highlight, base_color, highlight_color, px, ref.highlight_mode
        )
        under_label(formula)
        group.add(formula)
    place(scene, group, p)
    return register(
        scene,
        EquationComponent(
            object_id,
            "equation_label",
            group,
            text=p.text,
            font_px=tokens.smallest_text_px(*smallest),
            text_like=True,
            highlights=parts,
            highlight_color=highlight_color,
            base_color=base_color,
            highlight_mode=ref.highlight_mode,
            symbol_units=_units_of(eq),
            equation_id=eq.id,
            formula=formula,
            highlight_names=list(ref.highlight),
            px_at_1080p=px,
            place_formula=under_label if p.show_equation else None,
        ),
    )
