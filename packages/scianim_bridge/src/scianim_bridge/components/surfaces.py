"""Surfaces in three dimensions and scalar fields sampled to images; both re-evaluate for new parameters.

A `surface_plot` has two renderers that are equals (ADR-032): `cairo` hands Manim one small polygon per cell,
`raster` paints the cells, the mesh and the floor frame into one image through the scene's own camera. The
job's `ManimSettings.surface_renderer` chooses; the geometry, the washes and the shading are shared.
"""

from __future__ import annotations

import itertools
import math
from typing import TYPE_CHECKING, Any

import numpy as np
from manim import ORIGIN, OUT, Group, ImageMobject, Line, Mobject, Rectangle, Surface, Text, ThreeDAxes, VGroup

from scianim_bridge.components.base import ParametricComponent, params_for, register
from scianim_bridge.components.plots import _caption, _fmt, nice_range
from scianim_bridge.layout import projected_bbox
from scianim_bridge.raster import PIECES_PER_EDGE, RasterImage, RasterSurface, split
from scianim_bridge.tokens import shaded_rgb
from scianim_core import BBox
from scianim_core.expressions import compile_expression

if TYPE_CHECKING:
    from scianim_bridge.scene import SnapshotScene

CAIRO_FRAME_PIECES = 20
"""Pieces each floor-frame edge is cut into on the Cairo path, so Manim's per-mobject depth sort can place
them among the cells when it sorts them (ADR-032)."""


def _rgb(color: Any) -> np.ndarray:
    return np.array(color.to_rgb(), dtype=float) * 255.0


def _rgb1(color: Any) -> np.ndarray:
    return np.array(color.to_rgb(), dtype=float)


def surface_renderer_for(scene: Any) -> str:
    """`raster` or `cairo`: an explicit `scene.surface_renderer` (tests), else the job's setting, else `cairo`."""
    explicit = getattr(scene, "surface_renderer", None)
    if explicit:
        return str(explicit)
    job = getattr(getattr(scene, "ctx", None), "job", None)
    return str(job.manim.surface_renderer) if job is not None else "cairo"


class RasterAxes(VGroup):
    """The labels of a raster surface; fading them (a `fade_axes` action) also fades the frame in the raster."""

    def __init__(self, *members: Mobject, on_opacity: Any = None) -> None:
        super().__init__(*members)
        self._on_opacity = on_opacity

    def set_opacity(self, opacity: float, family: bool = True) -> RasterAxes:  # type: ignore[override]
        super().set_opacity(opacity, family=family)
        if self._on_opacity is not None:
            self._on_opacity(float(opacity))
        return self

    def __deepcopy__(self, clone_from_id: dict[int, Any]) -> RasterAxes:
        on_opacity, self._on_opacity = self._on_opacity, None
        try:
            return super().__deepcopy__(clone_from_id)
        finally:
            self._on_opacity = on_opacity


def _union(a: BBox, b: BBox) -> BBox:
    x0, y0 = min(a.x, b.x), min(a.y, b.y)
    x1, y1 = max(a.x2, b.x2), max(a.y2, b.y2)
    return BBox(x=x0, y=y0, width=x1 - x0, height=y1 - y0)


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
    height of the value, or on a diverging scale from the muted ink at zero; the mesh lines carry the
    secondary ink. `set_parameters` rebuilds the mesh in place.
    The frame, ticks and labels form the component's `axes` group, which a `fade_axes` action can fade and
    take away, leaving the surface alone. On the Cairo path the group holds the hidden helper axes, the
    `Surface` and the axes group; on the raster path it holds the image and the labels.
    """
    p = params_for("surface_plot", params)
    tokens = scene.tokens
    t3 = tokens.t.three_d
    renderer = surface_renderer_for(scene)
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
    span = high - low
    variables = ("x", "y", *p.parameters)
    function = compile_expression(p.expression, variables)
    function_array = compile_expression(p.expression, variables, arrays=True)
    ink = tokens.color(style_role)
    other = tokens.color("comparison")
    zero_ink = tokens.color("muted")
    reach = max(abs(low), abs(high)) or 1.0  # a diverging scale saturates at the larger edge of the z range
    mesh = tokens.color(t3.mesh_role)
    fg = tokens.color("foreground")
    page = tokens.color("background")
    opacity = t3.surface_opacity if p.fill != "none" else 0.0
    clipped: list[str] = []
    light = tokens.light_direction()
    n = p.resolution

    def basis() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        origin = axes.c2p(0, 0, 0)
        return origin, axes.c2p(1, 0, 0) - origin, axes.c2p(0, 1, 0) - origin, axes.c2p(0, 0, 1) - origin

    def note_clipping(values: dict[str, float]) -> None:
        if not clipped:
            clipped.append(
                f"object '{object_id}': values leave z_range [{low:g}, {high:g}] for parameters {values}; "
                "they are clipped to the box"
            )
            scene.render_warnings.append(clipped[0])

    def wash_for(z: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Each cell's wash (m, 3) in 0..1 and alpha (m,) from the value at its centre, before the light."""
        z = np.asarray(z, dtype=float).reshape(-1)
        positive = (z >= 0)[:, None]
        alpha = np.full(len(z), opacity)
        if p.fill == "by_sign":
            rgb = np.where(positive, _rgb1(ink), _rgb1(other))
        elif p.fill == "diverging":
            strength = np.minimum(1.0, np.abs(z) / reach)[:, None]
            rgb = _rgb1(zero_ink) * (1 - strength) + np.where(positive, _rgb1(ink), _rgb1(other)) * strength
        else:
            rgb = np.broadcast_to(_rgb1(ink), (len(z), 3)).copy()
            if p.fill != "none":
                alpha = opacity * np.clip((z - low) / span, 0.0, 1.0)
        return rgb, alpha

    def shade(rgb: np.ndarray, normals: np.ndarray) -> np.ndarray:
        if light is None:
            return rgb
        return shaded_rgb(rgb, normals, light, t3.shading_strength, _rgb1(page), _rgb1(fg))

    # --- the Cairo path: one Manim polygon per cell -----------------------------------------
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
            resolution=(n, n),
            fill_color=ink,
            fill_opacity=opacity,
            checkerboard_colors=False,
            stroke_color=mesh,
            stroke_width=tokens.stroke_width(t3.mesh_stroke_px_at_1080p),
        )
        if p.fill != "none":
            for face in surface.submobjects:
                rgb, alpha = wash_for(np.array([value((face.u1 + face.u2) / 2, (face.v1 + face.v2) / 2)]))
                if light is not None:
                    # One soft light: the cell's normal against the light direction, from the four corners it
                    # was built from (`shaded_rgb`). The renderer's own lamp is switched off so the sheet alone
                    # decides the shade.
                    a = point(face.u1, face.v1)
                    normal = np.cross(point(face.u2, face.v1) - a, point(face.u1, face.v2) - a)
                    rgb = shade(rgb, normal[None, :])
                    face.shade_in_3d = False
                face.set_fill(type(ink).from_rgb(tuple(float(c) for c in rgb[0])), opacity=float(alpha[0]))
        if out_of_range:
            note_clipping(values)
        return surface

    # --- the raster path: the vertex grid and the washes in one array evaluation ------------
    us = np.linspace(p.x_range[0], p.x_range[1], n + 1)
    vs = np.linspace(p.y_range[0], p.y_range[1], n + 1)
    uu, vv = np.meshgrid(us, vs, indexing="ij")
    uc, vc = np.meshgrid((us[:-1] + us[1:]) / 2, (vs[:-1] + vs[1:]) / 2, indexing="ij")

    def heights(values: dict[str, float]) -> np.ndarray:
        """z at the vertices, clipped to the box (non-finite values sit on the floor); notes any clipping."""
        z = function_array(x=uu, y=vv, **values)
        z[~np.isfinite(z)] = low
        if np.any(z < low) or np.any(z > high):
            note_clipping(values)
        return np.clip(z, low, high)

    def vertices_of(z: np.ndarray) -> np.ndarray:
        origin, ux, uy, uz = basis()
        return origin + uu[..., None] * ux + vv[..., None] * uy + z[..., None] * uz

    def cells(values: dict[str, float]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Vertices (n+1, n+1, 3) in the world, and each cell's shaded wash (n, n, 3) and alpha (n, n)."""
        vertices = vertices_of(heights(values))
        centre = function_array(x=uc, y=vc, **values)
        centre[~np.isfinite(centre)] = low
        rgb, alpha = wash_for(centre)
        a = vertices[:-1, :-1]
        normals = np.cross(vertices[1:, :-1] - a, vertices[:-1, 1:] - a).reshape(-1, 3)
        rgb = shade(rgb, normals)
        return vertices, rgb.reshape(n, n, 3), alpha.reshape(n, n)

    # --- the frame in data coordinates, shared by both paths --------------------------------
    stroke = tokens.stroke_width(tokens.t.geometry.axis_stroke_px_at_1080p)
    tick = tokens.units(tokens.t.geometry.tick_length_px_at_1080p)
    xa, xb, xs = x_range
    ya, yb, ys = y_range
    za, zb, zs = z_range
    tick_x = tick / box * (xb - xa)  # tick length in data units along x and y
    tick_y = tick / box * (yb - ya)
    tick_z = tick / z_len * (zb - za)
    corners = [(xa, ya, za), (xb, ya, za), (xb, yb, za), (xa, yb, za)]
    edges: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = [
        *zip(corners, corners[1:] + corners[:1], strict=True),
        ((xa, ya, za), (xa, ya, zb)),
    ]
    ticks: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
    tick_face = tokens.typeface("tick_label")
    axis_face = tokens.typeface("axis_label")
    secondary = tokens.color("secondary_text")
    labels = VGroup()
    value = xa
    while value <= xb + 1e-9:  # x ticks along the front edge, pointing away from the box
        ticks.append(((value, ya, za), (value, ya - tick_y, za)))
        label = Text(_fmt(value), **tokens.text_kwargs(tick_face, secondary)).move_to(
            axes.c2p(value, ya - 3 * tick_y, za)
        )
        labels.add(label)
        value += xs
    value = ya
    while value <= yb + 1e-9:  # y ticks along the right edge
        ticks.append(((xb, value, za), (xb + tick_x, value, za)))
        label = Text(_fmt(value), **tokens.text_kwargs(tick_face, secondary)).move_to(
            axes.c2p(xb + 3 * tick_x, value, za)
        )
        labels.add(label)
        value += ys
    value = za
    while value <= zb + 1e-9:  # z ticks on the vertical edge
        ticks.append(((xa, ya, value), (xa - tick_x, ya, value)))
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

    def lift(group: Mobject) -> None:
        group.move_to(ORIGIN)
        if p.lift_fraction:
            # A world-z shift rises on the page by sin(phi) of its length, whatever the azimuth, so the orbit is unchanged.
            elevation = max(math.sin(math.radians(t3.camera_phi_degrees)), 1e-6)
            group.shift(OUT * (sy1 - sy0) * p.lift_fraction / elevation)

    caption: Text | None = None
    if p.data_label:
        caption = Text(p.data_label, **tokens.text_kwargs(tokens.typeface("caption"), secondary))
        tokens.place(caption, "bottom_center")
    font_px = tokens.smallest_text_px("tick_label", "axis_label", *(["caption"] if p.data_label else []))

    if renderer == "raster":
        component = _raster_surface(
            scene,
            object_id,
            axes=axes,
            labels=labels,
            caption=caption,
            edges=edges,
            ticks=ticks,
            cells=cells,
            vertices_of=vertices_of,
            heights=heights,
            initial=dict(p.parameters),
            lift=lift,
            inks=(page, mesh, fg),
            widths=(
                tokens.output_px(t3.mesh_stroke_px_at_1080p),
                tokens.output_px(tokens.t.geometry.axis_stroke_px_at_1080p),
            ),
            round_caps=tokens.t.geometry.line_cap == "round",
            font_px=font_px,
        )
        register(scene, component)
        return component

    surface = build(p.parameters)
    if light is not None:
        surface.set_shade_in_3d(False)
    # Despined frame: the floor rectangle and one vertical edge, with outward ticks and flat labels. Each edge
    # is cut into pieces that join Manim's depth sort when the cells are in it (the lamp on, ADR-030's light
    # off), so a piece behind a ridge is drawn before the ridge; under the sheet's light the cells leave the
    # sort and the frame stays on top, as before.
    sorted_with_cells = light is None
    frame = VGroup()
    for start, end in edges:
        points = split(axes.c2p(*start), axes.c2p(*end), CAIRO_FRAME_PIECES)
        for a, b in itertools.pairwise(points):
            piece = Line(a, b, color=fg, stroke_width=stroke, **tokens.line_kwargs())
            piece.shade_in_3d = sorted_with_cells
            frame.add(piece)
    for start, end in ticks:
        piece = Line(axes.c2p(*start), axes.c2p(*end), color=fg, stroke_width=stroke)
        piece.shade_in_3d = sorted_with_cells
        frame.add(piece)
    axes_group = VGroup(frame, labels)
    group = VGroup(axes, surface, axes_group)
    lift(group)
    # Labels follow their anchors in the world but keep facing the viewer; the caption belongs to the page.
    scene.renderer.camera.add_fixed_orientation_mobjects(*labels)
    if caption is not None:
        group.add(caption)
        scene.fix_in_frame(caption)

    def rebuild(values: dict[str, float]) -> list[str]:
        before = len(scene.render_warnings)
        fresh = build(values)
        surface.become(fresh)
        if light is not None:  # `become` copies points and colours, not this flag
            surface.set_shade_in_3d(False)
        return scene.render_warnings[before:]

    component = ParametricComponent(
        object_id,
        "surface_plot",
        group,
        text=None,
        font_px=font_px,
        text_like=False,
        three_d=True,
        axes=axes_group,
        parameters=dict(p.parameters),
        rebuild=rebuild,
    )
    register(scene, component)
    return component


def _raster_surface(
    scene: SnapshotScene,
    object_id: str,
    *,
    axes: ThreeDAxes,
    labels: VGroup,
    caption: Text | None,
    edges: list[tuple[tuple[float, float, float], tuple[float, float, float]]],
    ticks: list[tuple[tuple[float, float, float], tuple[float, float, float]]],
    cells: Any,
    vertices_of: Any,
    heights: Any,
    initial: dict[str, float],
    lift: Any,
    inks: tuple[Any, Any, Any],
    widths: tuple[float, float],
    round_caps: bool,
    font_px: float,
) -> ParametricComponent:
    """The raster path of `surface_plot`: the picture, its labels, and the hooks that repaint it."""
    page, mesh, fg = inks
    mesh_px, frame_px = widths
    image = RasterImage()
    raster = RasterSurface(
        scene.renderer.camera,
        image,
        page_rgb=_rgb1(page),
        mesh_rgb=_rgb1(mesh),
        mesh_px=mesh_px,
        frame_px=frame_px,
        frame_rgb=_rgb1(fg),
        round_caps=round_caps,
    )
    # Place everything as the Cairo path does: the helper axes, the labels and the initial mesh share one
    # bounding box, which is centred and lifted; the mesh stands in through a mobject with the vertices.
    stand_in = Mobject()
    stand_in.points = vertices_of(heights(initial)).reshape(-1, 3)
    lift(Group(axes, labels, stand_in))
    raster.set_cells(*cells(initial))
    strokes = [split(axes.c2p(*start), axes.c2p(*end), PIECES_PER_EDGE) for start, end in edges]
    strokes.extend(split(axes.c2p(*start), axes.c2p(*end), 1) for start, end in ticks)
    raster.set_strokes(strokes)
    axes_group = RasterAxes(labels, on_opacity=raster.set_frame_alpha)
    group = Group(image, axes_group)
    scene.fix_in_frame(image)
    scene.renderer.camera.add_fixed_orientation_mobjects(*labels)
    if caption is not None:
        group.add(caption)
        scene.fix_in_frame(caption)

    def rebuild(values: dict[str, float]) -> list[str]:
        before = len(scene.render_warnings)
        raster.set_cells(*cells(values))
        return scene.render_warnings[before:]

    def layout_bbox() -> BBox:
        box = raster.bbox()
        others = [m for m in group.submobjects if m is not image]
        if others:
            box = _union(box, projected_bbox(scene.renderer.camera, Group(*others)))
        return box

    component = ParametricComponent(
        object_id,
        "surface_plot",
        group,  # type: ignore[arg-type]
        text=None,
        font_px=font_px,
        text_like=False,
        three_d=True,
        axes=axes_group,
        parameters=dict(initial),
        rebuild=rebuild,
    )
    component.on_camera = raster.invalidate
    component.layout_bbox = layout_bbox
    component.raster = raster  # type: ignore[attr-defined]
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
    function = compile_expression(p.expression, ("x", "y", *p.parameters), arrays=True)
    n = p.resolution
    xs = np.linspace(p.x_range[0], p.x_range[1], n)
    ys = np.linspace(p.y_range[1], p.y_range[0], n)  # row 0 is the top of the image
    xx, yy = np.meshgrid(xs, ys, indexing="xy")
    lo, hi = p.value_range
    ink, other = _rgb(tokens.color(style_role)), _rgb(tokens.color("comparison"))
    paper, dark = _rgb(tokens.color("background")), _rgb(tokens.color("foreground"))
    cx, cy = (p.x_range[0] + p.x_range[1]) / 2, (p.y_range[0] + p.y_range[1]) / 2
    radius = min(p.x_range[1] - p.x_range[0], p.y_range[1] - p.y_range[0]) / 2
    alpha = np.full((n, n), 255, dtype=np.uint8)
    if p.mask == "circle":
        alpha[(xx - cx) ** 2 + (yy - cy) ** 2 > radius**2] = 0

    def array(values: dict[str, float]) -> np.ndarray:
        """The field at every pixel in one evaluation (ADR-032), mapped to the two inks or to grey."""
        v = function(x=xx, y=yy, **values)
        t = np.where(np.isfinite(v), np.clip((v - lo) / (hi - lo), 0.0, 1.0), 0.0)[..., None]
        if p.colors == "two_ink":
            s = 2.0 * t - 1.0
            rgb = paper * (1 - np.abs(s)) + np.where(s >= 0, ink, other) * np.abs(s)
        else:
            rgb = dark * (1 - t) + paper * t
        pixels = np.empty((n, n, 4), dtype=np.uint8)
        pixels[..., :3] = np.clip(rgb, 0, 255)
        pixels[..., 3] = alpha
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
