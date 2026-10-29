from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

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
    main, parts = build_equation(tokens, eq, ref.highlight, base_color, highlight_color, px)
    if ref.highlight_mode == "active":  # the terms wait in the equation's ink until an action lights one
        for part in parts.values():
            part.set_color(base_color)
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
    if p.show_equation:
        px = tokens.t.typography.equation.label_size_px_at_1080p
        smallest.append(px)
        formula, parts = build_equation(tokens, eq, ref.highlight, base_color, highlight_color, px)
        if ref.highlight_mode == "active":
            for part in parts.values():
                part.set_color(base_color)
        formula.next_to(label, DOWN, buff=tokens.baseline)
        formula.align_to(label, LEFT)
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
        ),
    )
