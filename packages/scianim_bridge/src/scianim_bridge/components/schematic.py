"""Schematic kinds: a population of unit glyphs and a Gaussian receptive-field glyph.

Both are illustrations. A population's activity values are illustrative and must be labelled; a
receptive-field glyph draws the model (centre and width), not data.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from manim import DOWN, LEFT, RIGHT, UP, Circle, Dot, Ellipse, Line, Square, Text, VGroup

from scianim_bridge.components.base import Component, params_for, register

if TYPE_CHECKING:
    from scianim_bridge.scene import SnapshotScene


def _soft_role(tokens: Any, role: str) -> str:
    """The tint of a role when the palette has one (`<role>_soft`), else the role itself."""
    return f"{role}_soft" if f"{role}_soft" in tokens.t.palette else role


def schematic_population(
    scene: SnapshotScene,
    object_id: str,
    *,
    style_role: str = "primary_signal",
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    equation: dict[str, Any] | None = None,
) -> Component:
    p = params_for("schematic_population", params)
    tokens = scene.tokens
    ink = tokens.color(style_role)
    radius = tokens.units(p.unit_radius_px_at_1080p)
    stroke = tokens.stroke_width(tokens.t.geometry.annotation_stroke_px_at_1080p)
    units = VGroup()
    for index in range(p.count):
        activity = p.activity[index] if p.activity is not None else None
        unit = Circle(radius=radius, color=ink, stroke_width=stroke)
        if activity is not None:
            unit.set_fill(ink, opacity=activity)
        else:
            unit.set_fill(tokens.color("neutral"), opacity=1.0)
        units.add(unit)
    gap = tokens.baseline * 0.75
    if p.arrangement == "grid":
        columns = p.columns or max(1, round(p.count**0.5))
        units.arrange_in_grid(cols=columns, buff=gap)
    else:
        units.arrange(RIGHT, buff=gap)
    x0, _, x1, _ = tokens.safe_rect()
    max_width = (x1 - x0) * p.width_fraction
    if units.width > max_width:
        units.scale_to_fit_width(max_width)
    group = VGroup(units)
    smallest: list[Any] = []
    if p.label:
        annotation = tokens.typeface("annotation")
        label = Text(p.label, **tokens.text_kwargs(annotation, tokens.color("foreground")))
        label.next_to(units, UP, buff=tokens.baseline)
        group.add(label)
        smallest.append("annotation")
    if p.data_label:
        caption = tokens.typeface("caption")
        note = Text(p.data_label, **tokens.text_kwargs(caption, tokens.color("secondary_text")))
        note.next_to(units, DOWN, buff=tokens.baseline)
        group.add(note)
        smallest.append("caption")
    tokens.place(group, p.anchor)
    font_px = tokens.smallest_text_px(*smallest) if smallest else None
    return register(
        scene, Component(object_id, "schematic_population", group, text=p.label, font_px=font_px, text_like=False)
    )


def receptive_field_glyph(
    scene: SnapshotScene,
    object_id: str,
    *,
    style_role: str = "primary_signal",
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    equation: dict[str, Any] | None = None,
) -> Component:
    p = params_for("receptive_field_glyph", params)
    tokens = scene.tokens
    ink = tokens.color(style_role)
    tint = tokens.color(_soft_role(tokens, style_role))
    secondary = tokens.color("secondary_text")
    _, y0, _, y1 = tokens.safe_rect()
    side = (y1 - y0) * p.size_fraction
    scale = side / (2 * p.field_extent)  # frame units per visual-field unit
    axis_stroke = tokens.stroke_width(tokens.t.geometry.axis_stroke_px_at_1080p)
    box = Square(side_length=side, color=secondary, stroke_width=axis_stroke)
    group = VGroup(box)
    cx, cy = p.center[0] * scale, p.center[1] * scale
    # Contours at 2, 1 and 0.5 sigma; the tint deepens toward the centre.
    for factor, opacity in ((2.0, 0.25), (1.0, 0.45), (0.5, 0.7)):
        ring = Ellipse(width=2 * factor * p.sigma * scale, height=2 * factor * p.sigma * scale, color=ink)
        ring.set_stroke(ink, width=tokens.stroke_width(tokens.t.geometry.annotation_stroke_px_at_1080p), opacity=0.9)
        ring.set_fill(tint, opacity=opacity)
        ring.move_to(box.get_center() + RIGHT * cx + UP * cy)
        group.add(ring)
    centre = Dot(
        point=box.get_center() + RIGHT * cx + UP * cy,
        radius=tokens.units(tokens.t.geometry.marker_radius_px_at_1080p),
        color=ink,
    )
    group.add(centre)
    smallest: list[Any] = []
    if p.show_axes:
        tick_face = tokens.typeface("tick_label")
        tick = tokens.units(tokens.t.geometry.tick_length_px_at_1080p)
        for value in (-p.field_extent, 0.0, p.field_extent):
            foot = box.get_corner(DOWN + LEFT) + RIGHT * ((value + p.field_extent) * scale)
            group.add(Line(foot, foot + DOWN * tick, color=secondary, stroke_width=axis_stroke))
            label = Text(f"{value:g}", **tokens.text_kwargs(tick_face, secondary))
            label.next_to(foot + DOWN * tick, DOWN, buff=tokens.baseline * 0.35)
            group.add(label)
            side_foot = box.get_corner(DOWN + LEFT) + UP * ((value + p.field_extent) * scale)
            group.add(Line(side_foot, side_foot + LEFT * tick, color=secondary, stroke_width=axis_stroke))
            label_y = Text(f"{value:g}", **tokens.text_kwargs(tick_face, secondary))
            label_y.next_to(side_foot + LEFT * tick, LEFT, buff=tokens.baseline * 0.35)
            group.add(label_y)
        smallest.append("tick_label")
    if p.label:
        annotation = tokens.typeface("annotation")
        label = Text(p.label, **tokens.text_kwargs(annotation, tokens.color("foreground")))
        label.next_to(box, UP, buff=tokens.baseline)
        group.add(label)
        smallest.append("annotation")
    if p.data_label:
        caption = tokens.typeface("caption")
        note = Text(p.data_label, **tokens.text_kwargs(caption, secondary))
        note.next_to(group, DOWN, buff=tokens.baseline)
        group.add(note)
        smallest.append("caption")
    tokens.place(group, p.anchor)
    font_px = tokens.smallest_text_px(*smallest) if smallest else None
    return register(
        scene, Component(object_id, "receptive_field_glyph", group, text=p.label, font_px=font_px, text_like=False)
    )


__all__ = ["receptive_field_glyph", "schematic_population"]
