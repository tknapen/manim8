"""Solids anchored in a surface's data coordinates: a sphere (ADR-034)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np
from manim import PI, Surface, VGroup

from scianim_bridge.components.base import Component, params_for, register

if TYPE_CHECKING:
    from scianim_bridge.scene import SnapshotScene


@dataclass
class SphereComponent(Component):
    """A sphere in the world, centred at `data_point` of its anchor surface. `place_at` moves it; the faces that
    turn away from the camera are hidden (`cull`, run after every camera move and every change of ink), so the
    painter's order never shows the back through the front. Faces stay in the mesh: the renderer keeps drawing
    the members it listed at the start of a play, so hiding is the only removal that holds mid-play."""

    anchor_id: str = ""
    data_point: np.ndarray = field(default_factory=lambda: np.zeros(3))
    faces: list[Any] = field(default_factory=list)
    normals: list[np.ndarray] = field(default_factory=list)
    mesh: VGroup | None = None

    def place_at(self, point: Sequence[float]) -> None:
        if self.to_world is None or self.mesh is None:
            return
        target = np.asarray(self.to_world(point), dtype=float)
        current = np.asarray(self.to_world(self.data_point), dtype=float)
        for face in self.faces:  # every face, culled ones included, so they return in the right place
            face.shift(target - current)
        self.data_point = np.asarray(point, dtype=float)

    full_opacity: float = 1.0

    def cull(self, camera: Any) -> None:
        """Show only the faces whose outward normal points toward the camera, at the object's current ink."""
        if self.mesh is None:
            return
        # The camera's cached matrix is refreshed only when a frame is captured; build it from the current angles.
        toward_camera = np.asarray(camera.generate_rotation_matrix())[2]
        shown = self.full_opacity * self.ink_factor
        for face, normal in zip(self.faces, self.normals, strict=True):
            opacity = shown if normal @ toward_camera > 0 else 0.0
            face.set_fill(opacity=opacity, family=False)
            face.set_stroke(opacity=opacity, family=False)

    def visible_faces(self) -> list[Any]:
        return [face for face in self.faces if float(face.get_fill_opacity()) > 0]


def sphere(
    scene: SnapshotScene,
    object_id: str,
    *,
    style_role: str = "primary_signal",
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    equation: dict[str, Any] | None = None,
) -> SphereComponent:
    """A small solid sphere at `position` in the data coordinates of the `anchor` surface, in the object's ink.

    It is lit like the surfaces of ADR-030: one soft light fixed in the world lightens the faces that turn
    toward it and darkens those turned away, and the renderer's own lamp is switched off; its faces carry a
    hairline stroke of their own wash so the mesh does not show. A `move_object` with `to_point` moves it.
    """
    p = params_for("sphere", params)
    tokens = scene.tokens
    t3 = tokens.t.three_d
    anchor = scene.objects.get(p.anchor)
    if anchor is None or anchor.to_world is None:
        raise ValueError(f"object '{object_id}': anchor '{p.anchor}' is not a surface of this scene")
    _, sy0, _, sy1 = tokens.safe_rect()
    radius = (sy1 - sy0) * p.radius_fraction
    centre = np.asarray(anchor.to_world(p.position), dtype=float)
    ink = tokens.color(style_role)
    page = tokens.color("background")
    fg = tokens.color("foreground")
    light = tokens.light_direction()

    def point(u: float, v: float) -> np.ndarray:
        return centre + radius * np.array([math.sin(u) * math.cos(v), math.sin(u) * math.sin(v), math.cos(u)])

    mesh = Surface(
        point,
        u_range=[0.0, PI],
        v_range=[0.0, 2 * PI],
        resolution=(p.resolution, 2 * p.resolution),
        fill_color=ink,
        fill_opacity=t3.surface_opacity,
        checkerboard_colors=False,
        stroke_color=ink,
        stroke_width=tokens.stroke_width(t3.mesh_stroke_px_at_1080p),
    )
    faces = list(mesh.submobjects)
    normals: list[np.ndarray] = []
    for face in faces:
        um, vm = (face.u1 + face.u2) / 2, (face.v1 + face.v2) / 2
        normal = np.array([math.sin(um) * math.cos(vm), math.sin(um) * math.sin(vm), math.cos(um)])
        normals.append(normal)
        wash = ink
        if light is not None:
            toward = float(normal @ light)
            strength = t3.shading_strength
            if toward >= 0:
                wash = wash.interpolate(page, 0.5 * strength * toward)
            else:
                wash = wash.interpolate(fg, strength * -toward)
            face.shade_in_3d = False
        face.set_fill(wash, opacity=t3.surface_opacity)
        face.set_stroke(wash, opacity=t3.surface_opacity)
    if light is not None:
        mesh.set_shade_in_3d(False)
    group = VGroup(mesh)
    component = SphereComponent(
        object_id,
        "sphere",
        group,
        text=None,
        font_px=None,
        text_like=False,
        three_d=True,
        anchor_id=p.anchor,
        data_point=np.asarray(p.position, dtype=float),
        faces=faces,
        normals=normals,
        mesh=mesh,
        to_world=anchor.to_world,
        full_opacity=t3.surface_opacity,
    )
    # Every face's full ink, so a fade restores faces that were culled when it began.
    component.ink_originals = [
        (
            face,
            face.get_fill_opacities().copy(),
            face.get_stroke_opacities().copy(),
            face.get_stroke_opacities(background=True).copy(),
        )
        for face in faces
    ]
    scene.ensure_camera()
    component.cull(scene.renderer.camera)
    component.on_camera = lambda: component.cull(scene.renderer.camera)
    component.on_ink = component.on_camera
    register(scene, component)
    return component
