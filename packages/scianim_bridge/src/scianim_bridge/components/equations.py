from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from manim import DOWN, LEFT, ManimColor, Mobject, Text, VGroup

from scianim_bridge.components.base import Component, params_for, pretty_symbol, register
from scianim_bridge.tokens import Tokens
from scianim_core.animation import Equation
from scianim_core.storyboard import EquationRef

if TYPE_CHECKING:
    from scianim_bridge.scene import SnapshotScene

DEFINITION_SCALE = 0.8
LABEL_EQUATION_SCALE = 0.8


def _group_symbols(source: str, symbols: list[str]) -> str:
    """Wrap each highlighted symbol in a labelled Typst group: `{{ P : hl_P }}`."""
    for symbol in symbols:
        pattern = rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])"
        source = re.sub(pattern, "{{ " + symbol + " : hl_" + symbol + " }}", source)
    return source


def build_equation(
    tokens: Tokens,
    equation: Equation,
    highlight: list[str],
    base_color: ManimColor,
    highlight_color: ManimColor,
    px_at_1080p: float,
) -> Mobject:
    engine = tokens.t.typography.equation.engine
    font_size = tokens.equation_font_size(px_at_1080p)
    source = equation.source_for(engine)
    if source is None:
        raise ValueError(f"equation '{equation.id}' has no '{engine}' source; the style uses the {engine} engine")
    if engine == "typst":
        from manim import MathTypst

        mobject = MathTypst(_group_symbols(source, highlight), font_size=font_size, color=base_color)
        for symbol in highlight:
            mobject.select(f"hl_{symbol}").set_color(highlight_color)
        return mobject
    from manim import MathTex

    mobject = MathTex(source, substrings_to_isolate=highlight or None, font_size=font_size, color=base_color)
    for symbol in highlight:
        mobject.set_color_by_tex(symbol, highlight_color)
    return mobject


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
    main = build_equation(tokens, eq, ref.highlight, tokens.color(style_role), tokens.color("emphasis"), px)
    group = VGroup(main)
    if p.define_symbols and eq.symbols:
        body = tokens.typeface("body")
        def_px = body.size_px_at_1080p * DEFINITION_SCALE
        lines = VGroup()
        for name, definition in eq.symbols.items():
            text = f"{pretty_symbol(name)}: {definition.meaning}" + (
                f" ({definition.units})" if definition.units else ""
            )
            lines.add(Text(text, **tokens.text_kwargs(body, tokens.color("secondary_text"), def_px)))
        lines.arrange(DOWN, aligned_edge=LEFT, buff=tokens.baseline * 0.5)
        lines.next_to(main, DOWN, buff=tokens.panel_gap)
        lines.align_to(main, LEFT)
        group.add(lines)
    tokens.place(group, p.anchor)
    return register(
        scene,
        Component(
            object_id,
            "equation_block",
            group,
            text=eq.source_for(tokens.t.typography.equation.engine),
            font_px=tokens.output_px(px),
            text_like=True,
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
    label = Text(p.text, **tokens.text_kwargs(body, tokens.color(style_role)))
    group = VGroup(label)
    if p.show_equation:
        px = tokens.t.typography.equation.size_px_at_1080p * LABEL_EQUATION_SCALE
        formula = build_equation(tokens, eq, ref.highlight, tokens.color("foreground"), tokens.color(style_role), px)
        formula.next_to(label, DOWN, buff=tokens.baseline)
        formula.align_to(label, LEFT)
        group.add(formula)
    tokens.place(group, p.anchor)
    return register(
        scene,
        Component(
            object_id,
            "equation_label",
            group,
            text=p.text,
            font_px=tokens.output_px(body.size_px_at_1080p),
            text_like=True,
        ),
    )
