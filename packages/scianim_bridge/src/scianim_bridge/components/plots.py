from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from manim import DOWN, LEFT, PI, RIGHT, UP, Axes, DashedLine, Line, ManimColor, Text, VGroup

from scianim_bridge.components.base import Component, params_for, pretty_condition, register
from scianim_bridge.data import Series, apply_binding
from scianim_bridge.tokens import Tokens
from scianim_core.expressions import compile_expression
from scianim_core.storyboard import DataBinding
from scianim_core.style import TextRole

if TYPE_CHECKING:
    from scianim_bridge.scene import SnapshotScene

FALLBACK_ROLES = ("comparison", "emphasis", "warning", "neutral", "muted")


def nice_range(values: list[float], include_zero: bool = True, headroom: bool = True) -> tuple[float, float, float]:
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
    low = math.floor(low / step + 1e-9) * step
    high = math.ceil(high / step - 1e-9) * step
    if headroom and max(values) > 0 and max(values) > high - 0.25 * step:
        high += step  # so the top of the data does not sit on the frame
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
    """Despined scientific axes: only the spines in `charts.spines` are drawn (left and bottom by default),
    along the plot box edges and never through the origin, with outward ticks and labels in their own text roles.

    The returned `Axes` is invisible and only maps data coordinates to points.
    """
    fg = tokens.color("foreground")
    secondary = tokens.color("secondary_text")
    tick_face = tokens.typeface("tick_label")
    axis_face = tokens.typeface("axis_label")
    axes = Axes(
        x_range=list(x_range),
        y_range=list(y_range),
        x_length=width,
        y_length=height,
        tips=False,
        axis_config={"stroke_width": 0, "stroke_opacity": 0, "include_ticks": False, "include_numbers": False},
    )
    x0, x1, xs = x_range
    y0, y1, ys = y_range
    stroke = tokens.stroke_width(tokens.t.geometry.axis_stroke_px_at_1080p)
    tick = tokens.units(tokens.t.geometry.tick_length_px_at_1080p)
    offset = tokens.units(tokens.t.charts.spine_offset_px_at_1080p)
    spines = set(tokens.t.charts.spines)
    bottom_left, bottom_right = axes.c2p(x0, y0), axes.c2p(x1, y0)
    top_left, top_right = axes.c2p(x0, y1), axes.c2p(x1, y1)
    frame = VGroup()
    if "bottom" in spines:
        frame.add(Line(bottom_left + DOWN * offset, bottom_right + DOWN * offset, color=fg, stroke_width=stroke))
    if "left" in spines:
        frame.add(Line(bottom_left + LEFT * offset, top_left + LEFT * offset, color=fg, stroke_width=stroke))
    if "top" in spines:
        frame.add(Line(top_left + UP * offset, top_right + UP * offset, color=fg, stroke_width=stroke))
    if "right" in spines:
        frame.add(Line(bottom_right + RIGHT * offset, top_right + RIGHT * offset, color=fg, stroke_width=stroke))
    x_labels = VGroup()
    value = x0
    while value <= x1 + 1e-9:
        foot = axes.c2p(value, y0) + DOWN * offset
        frame.add(Line(foot, foot + DOWN * tick, color=fg, stroke_width=stroke))
        label = Text(_fmt(value), **tokens.text_kwargs(tick_face, secondary))
        label.next_to(foot + DOWN * tick, DOWN, buff=tokens.baseline * 0.35)
        x_labels.add(label)
        value += xs
    y_labels = VGroup()
    value = y0
    while value <= y1 + 1e-9:
        foot = axes.c2p(x0, value) + LEFT * offset
        frame.add(Line(foot, foot + LEFT * tick, color=fg, stroke_width=stroke))
        label = Text(_fmt(value), **tokens.text_kwargs(tick_face, secondary))
        label.next_to(foot + LEFT * tick, LEFT, buff=tokens.baseline * 0.35)
        y_labels.add(label)
        value += ys
    xlab = Text(x_label, **tokens.text_kwargs(axis_face, fg))
    xlab.next_to(x_labels, DOWN, buff=tokens.baseline * 0.9)
    xlab.set_x(float(axes.c2p((x0 + x1) / 2, y0)[0]))
    ylab = Text(y_label, **tokens.text_kwargs(axis_face, fg)).rotate(PI / 2)
    ylab.next_to(y_labels, LEFT, buff=tokens.baseline * 0.9)
    ylab.set_y(float(axes.c2p(x0, (y0 + y1) / 2)[1]))
    return axes, VGroup(frame, x_labels, y_labels, xlab, ylab)


def _curve(
    tokens: Tokens, axes: Axes, xs: list[float], ys: list[float], color: ManimColor, show_points: bool
) -> VGroup:
    graph = axes.plot_line_graph(
        xs,
        ys,
        line_color=color,
        add_vertex_dots=show_points,
        vertex_dot_radius=tokens.units(tokens.t.geometry.marker_radius_px_at_1080p),
        vertex_dot_style={"fill_color": color, "stroke_width": 0},
        stroke_width=tokens.stroke_width(tokens.t.geometry.curve_stroke_px_at_1080p),
    )
    return VGroup(graph)


def _caption(tokens: Tokens, text: str, anchor_mobject: VGroup) -> Text:
    caption = Text(text, **tokens.text_kwargs(tokens.typeface("caption"), tokens.color("secondary_text")))
    caption.next_to(anchor_mobject, DOWN, buff=tokens.baseline)
    caption.align_to(anchor_mobject, RIGHT)
    return caption


def _legend(tokens: Tokens, axes: Axes, entries: list[tuple[str, ManimColor]]) -> VGroup:
    annotation = tokens.typeface("annotation")
    legend = VGroup()
    for label, color in entries:
        swatch = Line(
            LEFT * tokens.units(18),
            RIGHT * tokens.units(18),
            color=color,
            stroke_width=tokens.stroke_width(tokens.t.geometry.curve_stroke_px_at_1080p),
        )
        text = Text(label, **tokens.text_kwargs(annotation, tokens.color("foreground")))
        legend.add(VGroup(swatch, text).arrange(RIGHT, buff=tokens.baseline * 0.5))
    legend.arrange(DOWN, aligned_edge=LEFT, buff=tokens.baseline * 0.4)
    corner = {
        "upper_right": UP + RIGHT,
        "upper_left": UP + LEFT,
        "lower_right": DOWN + RIGHT,
        "lower_left": DOWN + LEFT,
    }[tokens.t.charts.legend_position]
    legend.move_to(axes.get_corner(corner) - corner * tokens.baseline * 2, aligned_edge=corner)
    return legend


def _text_roles(*, caption: bool, annotation: bool, body: bool = False) -> list[TextRole]:
    """The text roles a plot draws, for reporting its smallest text in the layout report."""
    roles: list[TextRole] = ["tick_label", "axis_label"]
    if caption:
        roles.append("caption")
    if annotation:
        roles.append("annotation")
    if body:
        roles.append("body")
    return roles


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
    x_range = (
        (*p.x_range, nice_range(list(p.x_range), include_zero=False, headroom=False)[2])
        if p.x_range
        else nice_range(xs, include_zero=False, headroom=False)
    )
    y_range = (*p.y_range, nice_range(list(p.y_range))[2]) if p.y_range else nice_range(ys)
    x0, y0, x1, y1 = tokens.safe_rect()
    axes, labels = _axes_with_labels(
        tokens, x_range, y_range, (x1 - x0) * p.width_fraction, (y1 - y0) * p.height_fraction, p.x_label, p.y_label
    )
    group = VGroup(labels)
    roles = _roles_for(tokens, style_role, len(series))
    for s, role in zip(series, roles, strict=True):
        group.add(_curve(tokens, axes, s.x, s.y, tokens.color(role), p.show_points))
    if p.show_legend and len(series) > 1:
        group.add(
            _legend(
                tokens,
                axes,
                [(pretty_condition(str(s.label)), tokens.color(role)) for s, role in zip(series, roles, strict=True)],
            )
        )
    if p.data_label:
        group.add(_caption(tokens, p.data_label, labels))
    tokens.place(group, p.anchor)
    font_px = tokens.smallest_text_px(
        *_text_roles(caption=bool(p.data_label), annotation=p.show_legend and len(series) > 1)
    )
    return register(scene, Component(object_id, "scientific_plot", group, text=None, font_px=font_px, text_like=False))


def function_plot(
    scene: SnapshotScene,
    object_id: str,
    *,
    style_role: str = "primary_signal",
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    equation: dict[str, Any] | None = None,
) -> Component:
    """Analytic curves from whitelisted expressions in x, with optional labelled vertical markers."""
    p = params_for("function_plot", params)
    tokens = scene.tokens
    lo, hi = p.x_range
    xs = [lo + (hi - lo) * i / (p.samples - 1) for i in range(p.samples)]
    sampled: list[tuple[str, list[float], list[float], str]] = []
    roles = _roles_for(tokens, style_role, len(p.series))
    for series, fallback_role in zip(p.series, roles, strict=True):
        function = compile_expression(series.expression, ("x",))
        pairs = [(x, function(x=x)) for x in xs]
        pairs = [(x, y) for x, y in pairs if math.isfinite(y)]
        if not pairs:
            raise ValueError(f"object '{object_id}': series '{series.label}' has no finite values on {list(p.x_range)}")
        sampled.append((series.label, [x for x, _ in pairs], [y for _, y in pairs], series.style_role or fallback_role))
    ys = [y for _, _, yy, _ in sampled for y in yy]
    x_range = (lo, hi, nice_range([lo, hi], include_zero=False, headroom=False)[2])
    y_range = (*p.y_range, nice_range(list(p.y_range))[2]) if p.y_range else nice_range(ys)
    x0, y0, x1, y1 = tokens.safe_rect()
    axes, labels = _axes_with_labels(
        tokens, x_range, y_range, (x1 - x0) * p.width_fraction, (y1 - y0) * p.height_fraction, p.x_label, p.y_label
    )
    group = VGroup(labels)
    for _, sx, sy, role in sampled:
        group.add(_curve(tokens, axes, sx, sy, tokens.color(role), False))
    annotation = tokens.typeface("annotation")
    for marker in p.markers:
        color = tokens.color(marker.style_role or "secondary_text")
        line = DashedLine(
            axes.c2p(marker.x, y_range[0]),
            axes.c2p(marker.x, y_range[1]),
            color=color,
            stroke_width=tokens.stroke_width(tokens.t.geometry.annotation_stroke_px_at_1080p),
            dash_length=tokens.units(10),
        )
        group.add(line)
        if marker.label:
            text = Text(marker.label, **tokens.text_kwargs(annotation, color))
            text.next_to(axes.c2p(marker.x, y_range[1]), UP, buff=tokens.baseline * 0.5)
            group.add(text)
    if p.show_legend and len(sampled) > 1:
        group.add(_legend(tokens, axes, [(label, tokens.color(role)) for label, _, _, role in sampled]))
    if p.data_label:
        group.add(_caption(tokens, p.data_label, labels))
    tokens.place(group, p.anchor)
    labelled = (p.show_legend and len(sampled) > 1) or any(marker.label for marker in p.markers)
    font_px = tokens.smallest_text_px(*_text_roles(caption=bool(p.data_label), annotation=labelled))
    return register(scene, Component(object_id, "function_plot", group, text=None, font_px=font_px, text_like=False))


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
    x_range = (
        (*p.x_range, nice_range(list(p.x_range), include_zero=False, headroom=False)[2])
        if p.x_range
        else nice_range(xs, include_zero=False, headroom=False)
    )
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
            x_range = nice_range(s.x, include_zero=False, headroom=False)
            y_range = nice_range(s.y)
        axes, labels = _axes_with_labels(tokens, x_range, y_range, panel_width, panel_height, p.x_label, p.y_label)
        color = tokens.color(role)
        title = Text(pretty_condition(condition), **tokens.text_kwargs(body, color))
        title.next_to(labels, UP, buff=tokens.baseline)
        panels.add(VGroup(labels, _curve(tokens, axes, s.x, s.y, color, p.show_points), title))
    panels.arrange(RIGHT, buff=gap, aligned_edge=DOWN)
    group = VGroup(panels)
    if p.data_label:
        group.add(_caption(tokens, p.data_label, panels))
    tokens.place(group, p.anchor)
    font_px = tokens.smallest_text_px(*_text_roles(caption=bool(p.data_label), annotation=False, body=True))
    return register(scene, Component(object_id, "comparison_plot", group, text=None, font_px=font_px, text_like=False))
