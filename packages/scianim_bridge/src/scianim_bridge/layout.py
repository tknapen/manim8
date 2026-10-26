"""Layout report: normalized bounding boxes per registered object and deterministic QA warnings."""

from __future__ import annotations

from typing import TYPE_CHECKING

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


def layout_report(scene: SnapshotScene) -> tuple[list[LayoutItem], list[LayoutWarning]]:
    tokens = scene.tokens
    items: list[LayoutItem] = []
    for component in scene.objects.values():
        if not component.visible or len(component.group.submobjects) == 0:
            continue
        items.append(
            LayoutItem(
                object_id=component.object_id,
                kind=component.kind,
                bbox=normalized_bbox(component.group),
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
