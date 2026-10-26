"""`network_graph`: a small network with weighted, optionally directed edges."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import numpy as np
from manim import Arrow, Circle, DashedLine, Line, Text, VGroup

from scianim_bridge.components.base import Component, params_for, register

if TYPE_CHECKING:
    from scianim_bridge.scene import SnapshotScene

MAX_EDGE_STROKE_FACTOR = 2.5


def _positions(count: int, layout: str, columns: int | None, radius: float, spacing: float) -> list[np.ndarray]:
    if layout == "row":
        return [np.array([(i - (count - 1) / 2) * spacing, 0.0, 0.0]) for i in range(count)]
    if layout == "grid":
        cols = columns or max(1, round(math.sqrt(count)))
        rows = math.ceil(count / cols)
        return [
            np.array([(i % cols - (cols - 1) / 2) * spacing, -((i // cols) - (rows - 1) / 2) * spacing, 0.0])
            for i in range(count)
        ]
    return [
        np.array(
            [
                radius * math.cos(2 * math.pi * i / count + math.pi / 2),
                radius * math.sin(2 * math.pi * i / count + math.pi / 2),
                0.0,
            ]
        )
        for i in range(count)
    ]


def network_graph(
    scene: SnapshotScene,
    object_id: str,
    *,
    style_role: str = "primary_signal",
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    equation: dict[str, Any] | None = None,
) -> Component:
    p = params_for("network_graph", params)
    tokens = scene.tokens
    x0, y0, x1, y1 = tokens.safe_rect()
    # A row spans a fraction of the safe width; a circle or grid fits a fraction of the smaller safe dimension.
    extent = ((x1 - x0) if p.layout == "row" else min(x1 - x0, y1 - y0)) * p.size_fraction
    node_radius = tokens.units(p.node_radius_px_at_1080p)
    count = len(p.nodes)
    slots = count if p.layout == "row" else math.ceil(math.sqrt(count))
    spacing = max(3 * node_radius, extent / max(1, slots - 1))
    positions = dict(
        zip([n.id for n in p.nodes], _positions(count, p.layout, p.columns, extent / 2, spacing), strict=True)
    )
    annotation = tokens.typeface("annotation")
    base_stroke = tokens.stroke_width(tokens.t.geometry.annotation_stroke_px_at_1080p)
    heaviest = max((abs(e.weight) for e in p.edges), default=1.0) or 1.0
    edges = VGroup()
    for edge in p.edges:
        color = tokens.color(edge.style_role or style_role)
        start, end = positions[edge.source], positions[edge.target]
        direction = end - start
        length = float(np.linalg.norm(direction))
        if length < 1e-9:
            continue
        unit = direction / length
        start_point = start + unit * node_radius
        end_point = end - unit * node_radius
        width = base_stroke * (0.6 + MAX_EDGE_STROKE_FACTOR * abs(edge.weight) / heaviest)
        if edge.weight < 0:
            line = DashedLine(start_point, end_point, color=color, stroke_width=width, dash_length=tokens.units(10))
        elif edge.directed:
            line = Arrow(
                start_point, end_point, color=color, stroke_width=width, buff=0, max_tip_length_to_length_ratio=0.18
            )
        else:
            line = Line(start_point, end_point, color=color, stroke_width=width)
        edges.add(line)
    nodes = VGroup()
    labels = VGroup()
    for node in p.nodes:
        color = tokens.color(node.style_role or style_role)
        circle = Circle(radius=node_radius, color=color, stroke_width=base_stroke)
        soft = f"{node.style_role or style_role}_soft"
        circle.set_fill(tokens.color(soft) if soft in tokens.t.palette else tokens.color("background"), opacity=1.0)
        circle.move_to(positions[node.id])
        nodes.add(circle)
        text = Text(node.label or node.id, **tokens.text_kwargs(annotation, tokens.color("foreground")))
        if text.width > 1.6 * node_radius:
            text.next_to(circle, direction=np.array([0.0, -1.0, 0.0]), buff=tokens.baseline * 0.4)
        else:
            text.move_to(circle.get_center())
        labels.add(text)
    group = VGroup(edges, nodes, labels)
    tokens.place(group, p.anchor)
    return register(
        scene,
        Component(
            object_id, "network_graph", group, text=None, font_px=tokens.smallest_text_px("annotation"), text_like=False
        ),
    )


__all__ = ["network_graph"]
