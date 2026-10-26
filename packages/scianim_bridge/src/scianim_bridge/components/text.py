from __future__ import annotations

from typing import TYPE_CHECKING, Any

from manim import Text, VGroup

from scianim_bridge.components.base import Component, params_for, place, register

if TYPE_CHECKING:
    from scianim_bridge.scene import SnapshotScene


def text_caption(
    scene: SnapshotScene,
    object_id: str,
    *,
    style_role: str = "foreground",
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    equation: dict[str, Any] | None = None,
) -> Component:
    p = params_for("text_caption", params)
    tokens = scene.tokens
    typeface = tokens.typeface(p.role)  # title, body or caption: each a named role with its own size token
    color = tokens.color(style_role)
    mobject = Text(p.text, **tokens.text_kwargs(typeface, color))
    group = VGroup(mobject)
    place(scene, group, p)
    return register(
        scene,
        Component(
            object_id,
            "text_caption",
            group,
            text=p.text,
            font_px=tokens.output_px(typeface.size_px_at_1080p),
            text_like=True,
        ),
    )
