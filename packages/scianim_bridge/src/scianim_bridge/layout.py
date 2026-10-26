"""Layout report: normalized bounding boxes per registered object and deterministic QA warnings."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
from manim import DR, UL, Mobject, config

from scianim_core import BBox, LayoutItem, LayoutWarning

if TYPE_CHECKING:
    from scianim_bridge.scene import SnapshotScene


def normalized_bbox(mobject: Mobject) -> BBox:
    """Bounding box in normalized frame coordinates with origin at the top-left corner."""
    fw, fh = float(config.frame_width), float(config.frame_height)
    ul = mobject.get_corner(UL)
    dr = mobject.get_corner(DR)
    return BBox(
        x=(float(ul[0]) + fw / 2) / fw,
        y=(fh / 2 - float(ul[1])) / fh,
        width=max(0.0, float(dr[0] - ul[0]) / fw),
        height=max(0.0, float(ul[1] - dr[1]) / fh),
    )


def projected_bbox(camera: Any, mobject: Mobject) -> BBox:
    """Bounding box of a 3D object as the camera shows it: its points projected through the camera."""
    fw, fh = float(config.frame_width), float(config.frame_height)
    fixed_in_frame = getattr(camera, "fixed_in_frame_mobjects", set())
    fixed_orientation = getattr(camera, "fixed_orientation_mobjects", {})
    arrays = []
    for member in mobject.get_family():
        if not len(member.points):
            continue
        if member in fixed_in_frame:
            arrays.append(member.points)
        elif member in fixed_orientation:
            center = fixed_orientation[member]()
            arrays.append(member.points + (camera.project_point(center) - center))
        else:
            arrays.append(camera.project_points(member.points.copy()))
    if not arrays:
        return normalized_bbox(mobject)
    points = np.vstack(arrays)
    x0, y0 = float(points[:, 0].min()), float(points[:, 1].min())
    x1, y1 = float(points[:, 0].max()), float(points[:, 1].max())
    return BBox(
        x=(x0 + fw / 2) / fw, y=(fh / 2 - y1) / fh, width=max(0.0, (x1 - x0) / fw), height=max(0.0, (y1 - y0) / fh)
    )


def layout_report(scene: SnapshotScene) -> tuple[list[LayoutItem], list[LayoutWarning]]:
    tokens = scene.tokens
    items: list[LayoutItem] = []
    for component in scene.objects.values():
        if not component.visible or len(component.group.submobjects) == 0:
            continue
        bbox = (
            projected_bbox(scene.renderer.camera, component.group)
            if component.three_d
            else normalized_bbox(component.group)
        )
        items.append(
            LayoutItem(
                object_id=component.object_id,
                kind=component.kind,
                bbox=bbox,
                text=component.text,
                text_height_px=component.font_px,
            )
        )
    warnings: list[LayoutWarning] = []
    margin = tokens.t.layout.safe_margin_fraction
    for item in items:
        b = item.bbox
        if b.x < margin - 1e-6 or b.y < margin - 1e-6 or b.x2 > 1 - margin + 1e-6 or b.y2 > 1 - margin + 1e-6:
            warnings.append(
                LayoutWarning(
                    code="outside_safe_zone",
                    object_ids=[item.object_id],
                    detail=f"bbox x={b.x:.3f}..{b.x2:.3f} y={b.y:.3f}..{b.y2:.3f} exceeds safe margin {margin:g}",
                )
            )
    minimum_px = tokens.output_px(tokens.t.typography.minimum_text_px_at_1080p)
    text_items = [i for i in items if scene.objects[i.object_id].text_like]
    for item in items:  # every object that draws text reports its smallest size, plots included
        if item.text_height_px is not None and item.text_height_px < minimum_px - 1e-6:
            warnings.append(
                LayoutWarning(
                    code="text_too_small",
                    object_ids=[item.object_id],
                    detail=f"font size {item.text_height_px:.1f}px is below the minimum {minimum_px:.1f}px at this resolution",
                )
            )
    for index, first in enumerate(text_items):
        for second in text_items[index + 1 :]:
            if first.bbox.intersects(second.bbox):
                warnings.append(
                    LayoutWarning(
                        code="overlap",
                        object_ids=[first.object_id, second.object_id],
                        detail="text-like objects overlap",
                    )
                )
    return items, warnings
