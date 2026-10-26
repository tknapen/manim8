"""Surfaces in three dimensions and scalar fields sampled to images; both re-evaluate for new parameters."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import numpy as np
from manim import ORIGIN, Group, ImageMobject, Line, Rectangle, Surface, Text, ThreeDAxes, VGroup

from scianim_bridge.components.base import ParametricComponent, params_for, register
from scianim_bridge.components.plots import _caption, _fmt, nice_range
from scianim_core.expressions import compile_expression

if TYPE_CHECKING:
    from scianim_bridge.scene import SnapshotScene


def _rgb(color: Any) -> np.ndarray:
    return np.array(color.to_rgb(), dtype=float) * 255.0


def surface_plot(
    scene: SnapshotScene,
    object_id: str,
    *,
    style_role: str = "primary_signal",
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    equation: dict[str, Any] | None = None,
) -> ParametricComponent:
    """z = f(x, y) over a box as a fine mesh, with a despined floor frame and one vertical edge for z.

    The box is centred on the world origin, which the camera orbits. Cells are filled by the sign or the
    height of the value; the mesh lines carry the secondary ink. `set_parameters` rebuilds the mesh in place.
    """
    p = params_for("surface_plot", params)
    tokens = scene.tokens
    t3 = tokens.t.three_d
    _, sy0, _, sy1 = tokens.safe_rect()
    box = (sy1 - sy0) * p.size_fraction
    z_len = box * 0.55
    x_range = (*p.x_range, nice_range(list(p.x_range), include_zero=False, headroom=False)[2])
    y_range = (*p.y_range, nice_range(list(p.y_range), include_zero=False, headroom=False)[2])
    z_range = (*p.z_range, nice_range(list(p.z_range), include_zero=False, headroom=False)[2])
    invisible = {"stroke_width": 0, "stroke_opacity": 0, "include_ticks": False, "include_numbers": False}
    axes = ThreeDAxes(
        x_range=list(x_range),
        y_range=list(y_range),
        z_range=list(z_range),
        x_length=box,
        y_length=box,
        z_length=z_len,
        tips=False,
        axis_config=invisible,
        z_axis_config=invisible,
    )
    low, high = p.z_range
    function = compile_expression(p.expression, ("x", "y", *p.parameters))
    ink = tokens.color(style_role)
    other = tokens.color("comparison")
    mesh = tokens.color("secondary_text")
    fg = tokens.color("foreground")
    opacity = t3.surface_opacity if p.fill != "none" else 0.0
    clipped: list[str] = []

    def basis() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        origin = axes.c2p(0, 0, 0)
        return origin, axes.c2p(1, 0, 0) - origin, axes.c2p(0, 1, 0) - origin, axes.c2p(0, 0, 1) - origin

    def build(values: dict[str, float]) -> Surface:
        grid: dict[tuple[float, float], float] = {}
        origin, ux, uy, uz = basis()
        out_of_range = False

        def value(u: float, v: float) -> float:
            key = (u, v)
            if key not in grid:
                z = function(x=u, y=v, **values)
                grid[key] = z if math.isfinite(z) else low
            return grid[key]

        def point(u: float, v: float) -> np.ndarray:
            nonlocal out_of_range
            z = value(u, v)
            if z < low or z > high:
                out_of_range = True
            z = min(max(z, low), high)
            return origin + u * ux + v * uy + z * uz

        surface = Surface(
            point,
            u_range=p.x_range,
            v_range=p.y_range,
            resolution=(p.resolution, p.resolution),
            fill_color=ink,
            fill_opacity=opacity,
            checkerboard_colors=False,
            stroke_color=mesh,
            stroke_width=tokens.stroke_width(t3.mesh_stroke_px_at_1080p),
        )
        if p.fill != "none":
            span = high - low
            for face in surface.submobjects:
                z = value((face.u1 + face.u2) / 2, (face.v1 + face.v2) / 2)
                if p.fill == "by_sign":
                    face.set_fill(ink if z >= 0 else other, opacity=opacity)
                else:
                    face.set_fill(ink, opacity=opacity * min(1.0, max(0.0, (z - low) / span)))
        if out_of_range and not clipped:
            clipped.append(
                f"object '{object_id}': values leave z_range [{low:g}, {high:g}] for parameters {values}; "
                "they are clipped to the box"
            )
            scene.render_warnings.append(clipped[0])
        return surface

    surface = build(p.parameters)
    # Despined frame: the floor rectangle and one vertical edge, with outward ticks and flat labels.
    stroke = tokens.stroke_width(tokens.t.geometry.axis_stroke_px_at_1080p)
    tick = tokens.units(tokens.t.geometry.tick_length_px_at_1080p)
    xa, xb, xs = x_range
    ya, yb, ys = y_range
    za, zb, zs = z_range
    tick_x = tick / box * (xb - xa)  # tick length in data units along x and y
    tick_y = tick / box * (yb - ya)
    tick_z = tick / z_len * (zb - za)
    corners = [axes.c2p(xa, ya, za), axes.c2p(xb, ya, za), axes.c2p(xb, yb, za), axes.c2p(xa, yb, za)]
    frame = VGroup(
        *[Line(a, b, color=fg, stroke_width=stroke) for a, b in zip(corners, corners[1:] + corners[:1], strict=True)]
    )
    frame.add(Line(axes.c2p(xa, ya, za), axes.c2p(xa, ya, zb), color=fg, stroke_width=stroke))
    tick_face = tokens.typeface("tick_label")
    axis_face = tokens.typeface("axis_label")
    secondary = tokens.color("secondary_text")
    labels = VGroup()
    value = xa
    while value <= xb + 1e-9:  # x ticks along the front edge, pointing away from the box
        frame.add(Line(axes.c2p(value, ya, za), axes.c2p(value, ya - tick_y, za), color=fg, stroke_width=stroke))
        label = Text(_fmt(value), **tokens.text_kwargs(tick_face, secondary)).move_to(
            axes.c2p(value, ya - 3 * tick_y, za)
        )
        labels.add(label)
        value += xs
    value = ya
    while value <= yb + 1e-9:  # y ticks along the right edge
        frame.add(Line(axes.c2p(xb, value, za), axes.c2p(xb + tick_x, value, za), color=fg, stroke_width=stroke))
        label = Text(_fmt(value), **tokens.text_kwargs(tick_face, secondary)).move_to(
            axes.c2p(xb + 3 * tick_x, value, za)
        )
        labels.add(label)
        value += ys
    value = za
    while value <= zb + 1e-9:  # z ticks on the vertical edge
        frame.add(Line(axes.c2p(xa, ya, value), axes.c2p(xa - tick_x, ya, value), color=fg, stroke_width=stroke))
        label = Text(_fmt(value), **tokens.text_kwargs(tick_face, secondary))
        label.move_to(axes.c2p(xa - 4 * tick_x, ya, value))
        labels.add(label)
        value += zs
    x_label = Text(p.x_label, **tokens.text_kwargs(axis_face, fg)).move_to(axes.c2p((xa + xb) / 2, ya - 8 * tick_y, za))
    y_label = Text(p.y_label, **tokens.text_kwargs(axis_face, fg))
    y_label.move_to(axes.c2p(xb + 8 * tick_x, (ya + yb) / 2, za))
    z_label = Text(p.z_label, **tokens.text_kwargs(axis_face, fg))
    z_label.move_to(axes.c2p(xa - 4 * tick_x, ya, zb + 2 * tick_z))
    labels.add(x_label, y_label, z_label)
    group = VGroup(axes, surface, frame, labels)
    group.move_to(ORIGIN)
    # Labels follow their anchors in the world but keep facing the viewer; the caption belongs to the page.
    scene.renderer.camera.add_fixed_orientation_mobjects(*labels)
    if p.data_label:
        caption = Text(p.data_label, **tokens.text_kwargs(tokens.typeface("caption"), secondary))
        tokens.place(caption, "bottom_center")
        group.add(caption)
        scene.fix_in_frame(caption)

    def rebuild(values: dict[str, float]) -> list[str]:
        before = len(scene.render_warnings)
        surface.become(build(values))
        return scene.render_warnings[before:]

    component = ParametricComponent(
        object_id,
        "surface_plot",
        group,
        text=None,
        font_px=tokens.smallest_text_px("tick_label", "axis_label", *(["caption"] if p.data_label else [])),
        text_like=False,
        three_d=True,
        parameters=dict(p.parameters),
        rebuild=rebuild,
    )
    register(scene, component)
    return component


def function_image(
    scene: SnapshotScene,
    object_id: str,
    *,
    style_role: str = "primary_signal",
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    equation: dict[str, Any] | None = None,
) -> ParametricComponent:
    """A scalar field sampled to pixels: two inks around white, or dark to light grey; optionally a disc."""
    p = params_for("function_image", params)
    tokens = scene.tokens
    function = compile_expression(p.expression, ("x", "y", *p.parameters))
    n = p.resolution
    xs = np.linspace(p.x_range[0], p.x_range[1], n)
    ys = np.linspace(p.y_range[1], p.y_range[0], n)  # row 0 is the top of the image
    lo, hi = p.value_range
    ink, other = _rgb(tokens.color(style_role)), _rgb(tokens.color("comparison"))
    paper, dark = _rgb(tokens.color("background")), _rgb(tokens.color("foreground"))
    cx, cy = (p.x_range[0] + p.x_range[1]) / 2, (p.y_range[0] + p.y_range[1]) / 2
    radius = min(p.x_range[1] - p.x_range[0], p.y_range[1] - p.y_range[0]) / 2

    def array(values: dict[str, float]) -> np.ndarray:
        pixels = np.empty((n, n, 4), dtype=np.uint8)
        for i, y in enumerate(ys):
            for j, x in enumerate(xs):
                v = function(x=float(x), y=float(y), **values)
                t = 0.0 if not math.isfinite(v) else min(1.0, max(0.0, (v - lo) / (hi - lo)))
                if p.colors == "two_ink":
                    s = 2.0 * t - 1.0
                    rgb = paper * (1 - abs(s)) + (ink if s >= 0 else other) * abs(s)
                else:
                    rgb = dark * (1 - t) + paper * t
                alpha = 255
                if p.mask == "circle" and (x - cx) ** 2 + (y - cy) ** 2 > radius**2:
                    alpha = 0
                pixels[i, j, :3] = np.clip(rgb, 0, 255)
                pixels[i, j, 3] = alpha
        return pixels

    image = ImageMobject(array(p.parameters))
    _, sy0, _, sy1 = tokens.safe_rect()
    image.height = (sy1 - sy0) * p.size_fraction
    fg = tokens.color("foreground")
    group = Group(image)
    if p.mask == "none":
        border = Rectangle(
            width=image.width,
            height=image.height,
            color=fg,
            stroke_width=tokens.stroke_width(tokens.t.geometry.axis_stroke_px_at_1080p),
        ).move_to(image)
        group.add(border)
    smallest: list[Any] = []
    if p.label:
        label = Text(p.label, **tokens.text_kwargs(tokens.typeface("annotation"), fg))
        label.next_to(image, direction=np.array([0.0, 1.0, 0.0]), buff=tokens.baseline * 0.5)
        label.align_to(image, np.array([-1.0, 0.0, 0.0]))
        group.add(label)
        smallest.append("annotation")
    if p.data_label:
        group.add(_caption(tokens, p.data_label, image))
        smallest.append("caption")
    tokens.place(group, p.anchor)

    def rebuild(values: dict[str, float]) -> list[str]:
        image.pixel_array = array(values)
        return []

    component = ParametricComponent(
        object_id,
        "function_image",
        group,  # type: ignore[arg-type]
        text=p.label,
        font_px=tokens.smallest_text_px(*smallest) if smallest else None,
        text_like=False,
        parameters=dict(p.parameters),
        rebuild=rebuild,
    )
    register(scene, component)
    return component
