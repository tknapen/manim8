from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from manim import DOWN, LEFT, PI, RIGHT, UP, Axes, Line, ManimColor, Text, VGroup

from scianim_bridge.components.base import Component, params_for, pretty_condition, register
from scianim_bridge.data import Series, apply_binding
from scianim_bridge.tokens import Tokens
from scianim_core.storyboard import DataBinding

if TYPE_CHECKING:
    from scianim_bridge.scene import SnapshotScene

TICK_LABEL_SCALE = 0.6
AXIS_LABEL_SCALE = 0.8
CAPTION_SCALE = 0.7
FALLBACK_ROLES = ("comparison", "emphasis", "warning", "neutral", "muted")


def nice_range(values: list[float], include_zero: bool = True) -> tuple[float, float, float]:
    """A tidy [low, high, step] around the data with about five ticks."""
    low, high = min(values), max(values)
    if include_zero:
        low, high = min(low, 0.0), max(high, 0.0)
    if math.isclose(low, high):
        high = low + 1.0
    span = high - low
    raw_step = span / 5.0
    magnitude = 10 ** math.floor(math.log10(raw_step))
    step = next(c * magnitude for c in (1, 2, 2.5, 5, 10) if c * magnitude >= raw_step)
    low = math.floor(low / step) * step
    high = math.ceil(high / step) * step
    if math.isclose(high, max(values)) and max(values) != 0:
        high += step  # headroom so the top point does not sit on the frame
    return low, high, step


def _fmt(value: float) -> str:
    return f"{value:g}"


def _series(scene: SnapshotScene, data: dict[str, Any] | None, object_id: str) -> tuple[list[Series], DataBinding]:
    if data is None:
        raise ValueError(f"object '{object_id}' needs a data binding")
    if scene.ctx is None:
        raise RuntimeError("no job context")
    binding = DataBinding.model_validate(data)
    return apply_binding(scene.ctx.table(binding.source), binding), binding


def _axes_with_labels(
    tokens: Tokens,
    x_range: tuple[float, float, float],
    y_range: tuple[float, float, float],
    width: float,
    height: float,
    x_label: str,
    y_label: str,
) -> tuple[Axes, VGroup]:
    fg = tokens.color("foreground")
    secondary = tokens.color("secondary_text")
    body = tokens.typeface("body")
    axes = Axes(
        x_range=list(x_range),
        y_range=list(y_range),
        x_length=width,
        y_length=height,
        tips=False,
        axis_config={
            "stroke_width": tokens.stroke_width(tokens.t.geometry.axis_stroke_px_at_1080p),
            "color": fg,
            "include_numbers": False,
            "include_ticks": True,
            "tick_size": tokens.units(8),
        },
    )
    labels = VGroup()
    tick_px = body.size_px_at_1080p * TICK_LABEL_SCALE
    x0, x1, xs = x_range
    y0, y1, ys = y_range
    value = x0
    while value <= x1 + 1e-9:
        tick = Text(_fmt(value), **tokens.text_kwargs(body, secondary, tick_px))
        tick.next_to(axes.c2p(value, y0), DOWN, buff=tokens.baseline * 0.5)
        labels.add(tick)
        value += xs
    value = y0
    while value <= y1 + 1e-9:
        if value == y0 and x0 == y0:  # the origin label is already drawn on the x axis
            value += ys
            continue
        tick = Text(_fmt(value), **tokens.text_kwargs(body, secondary, tick_px))
        tick.next_to(axes.c2p(x0, value), LEFT, buff=tokens.baseline * 0.5)
        labels.add(tick)
        value += ys
    label_px = body.size_px_at_1080p * AXIS_LABEL_SCALE
    xlab = Text(x_label, **tokens.text_kwargs(body, fg, label_px))
    xlab.next_to(axes.x_axis, DOWN, buff=tokens.baseline * 2.2)
    ylab = Text(y_label, **tokens.text_kwargs(body, fg, label_px)).rotate(PI / 2)
    ylab.next_to(axes.y_axis, LEFT, buff=tokens.baseline * 2.6)
    labels.add(xlab, ylab)
    return axes, labels


def _curve(tokens: Tokens, axes: Axes, series: Series, color: ManimColor, show_points: bool) -> VGroup:
    graph = axes.plot_line_graph(
        series.x,
        series.y,
        line_color=color,
        add_vertex_dots=show_points,
        vertex_dot_radius=tokens.units(tokens.t.geometry.marker_radius_px_at_1080p),
        vertex_dot_style={"fill_color": color, "stroke_width": 0},
        stroke_width=tokens.stroke_width(tokens.t.geometry.curve_stroke_px_at_1080p),
    )
    return VGroup(graph)


def _caption(tokens: Tokens, text: str, anchor_mobject: VGroup) -> Text:
    body = tokens.typeface("body")
    caption = Text(
        text,
        **tokens.text_kwargs(body, tokens.color("secondary_text"), body.size_px_at_1080p * CAPTION_SCALE),
    )
    caption.next_to(anchor_mobject, DOWN, buff=tokens.baseline)
    caption.align_to(anchor_mobject, RIGHT)
    return caption


def _roles_for(tokens: Tokens, primary: str, count: int) -> list[str]:
    roles = [primary] + [r for r in FALLBACK_ROLES if r in tokens.t.palette and r != primary]
    if count > len(roles):
        raise ValueError(
            f"{count} series but only {len(roles)} distinguishable palette roles; add roles or filter the data"
        )
    return roles[:count]


def scientific_plot(
    scene: SnapshotScene,
    object_id: str,
    *,
    style_role: str = "primary_signal",
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    equation: dict[str, Any] | None = None,
) -> Component:
    p = params_for("scientific_plot", params)
    tokens = scene.tokens
    series, _ = _series(scene, data, object_id)
    xs = [v for s in series for v in s.x]
    ys = [v for s in series for v in s.y]
    x_range = (*p.x_range, nice_range(list(p.x_range))[2]) if p.x_range else nice_range(xs)
    y_range = (*p.y_range, nice_range(list(p.y_range))[2]) if p.y_range else nice_range(ys)
    x0, y0, x1, y1 = tokens.safe_rect()
    axes, labels = _axes_with_labels(
        tokens,
        x_range,
        y_range,
        (x1 - x0) * p.width_fraction,
        (y1 - y0) * p.height_fraction,
        p.x_label,
        p.y_label,
    )
    group = VGroup(axes, labels)
    roles = _roles_for(tokens, style_role, len(series))
    for s, role in zip(series, roles, strict=True):
        group.add(_curve(tokens, axes, s, tokens.color(role), p.show_points))
    if p.show_legend and len(series) > 1:
        legend = VGroup()
        body = tokens.typeface("body")
        for s, role in zip(series, roles, strict=True):
            swatch = Line(
                LEFT * tokens.units(18),
                RIGHT * tokens.units(18),
                color=tokens.color(role),
                stroke_width=tokens.stroke_width(tokens.t.geometry.curve_stroke_px_at_1080p),
            )
            text = Text(
                pretty_condition(str(s.label)),
                **tokens.text_kwargs(body, tokens.color("foreground"), body.size_px_at_1080p * CAPTION_SCALE),
            )
            entry = VGroup(swatch, text).arrange(RIGHT, buff=tokens.baseline * 0.5)
            legend.add(entry)
        legend.arrange(DOWN, aligned_edge=LEFT, buff=tokens.baseline * 0.4)
        corner = {
            "upper_right": (UP + RIGHT),
            "upper_left": (UP + LEFT),
            "lower_right": (DOWN + RIGHT),
            "lower_left": (DOWN + LEFT),
        }[tokens.t.charts.legend_position]
        legend.move_to(axes.get_corner(corner) - corner * tokens.baseline * 2, aligned_edge=corner)
        group.add(legend)
    if p.data_label:
        group.add(_caption(tokens, p.data_label, VGroup(axes, labels)))
    tokens.place(group, p.anchor)
    return register(
        scene,
        Component(object_id, "scientific_plot", group, text=None, font_px=None, text_like=False),
    )


def comparison_plot(
    scene: SnapshotScene,
    object_id: str,
    *,
    style_role: str = "comparison",
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    equation: dict[str, Any] | None = None,
) -> Component:
    p = params_for("comparison_plot", params)
    tokens = scene.tokens
    series, binding = _series(scene, data, object_id)
    by_label = {str(s.label): s for s in series}
    missing = [c for c in p.condition_roles if c not in by_label]
    if missing:
        raise ValueError(
            f"object '{object_id}': conditions {missing} not found in column '{binding.encoding.group}'; available: {sorted(by_label)}"
        )
    chosen = [by_label[c] for c in p.condition_roles]
    xs = [v for s in chosen for v in s.x]
    ys = [v for s in chosen for v in s.y]
    x_range = (*p.x_range, nice_range(list(p.x_range))[2]) if p.x_range else nice_range(xs)
    y_range = (*p.y_range, nice_range(list(p.y_range))[2]) if p.y_range else nice_range(ys)
    x0, y0, x1, y1 = tokens.safe_rect()
    count = len(chosen)
    gap = tokens.panel_gap * 2.5
    panel_width = ((x1 - x0) * p.width_fraction - gap * (count - 1)) / count
    panel_height = (y1 - y0) * p.height_fraction
    panels = VGroup()
    body = tokens.typeface("body")
    for (condition, role), s in zip(p.condition_roles.items(), chosen, strict=True):
        if not p.shared_axes:
            x_range = nice_range(s.x)
            y_range = nice_range(s.y)
        axes, labels = _axes_with_labels(tokens, x_range, y_range, panel_width, panel_height, p.x_label, p.y_label)
        color = tokens.color(role)
        title = Text(pretty_condition(condition), **tokens.text_kwargs(body, color))
        title.next_to(axes, UP, buff=tokens.baseline)
        panels.add(VGroup(axes, labels, _curve(tokens, axes, s, color, True), title))
    panels.arrange(RIGHT, buff=gap, aligned_edge=DOWN)
    group = VGroup(panels)
    if p.data_label:
        group.add(_caption(tokens, p.data_label, panels))
    tokens.place(group, p.anchor)
    return register(
        scene,
        Component(object_id, "comparison_plot", group, text=None, font_px=None, text_like=False),
    )
