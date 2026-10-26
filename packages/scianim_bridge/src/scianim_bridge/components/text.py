from __future__ import annotations

from typing import TYPE_CHECKING, Any

from manim import DOWN, LEFT, Text, VGroup

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


def caption_with_citation(
    scene: SnapshotScene,
    object_id: str,
    *,
    style_role: str = "foreground",
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    equation: dict[str, Any] | None = None,
) -> Component:
    """A caption with the citation of a declared source typeset beneath it (spec 6.2: locators)."""
    p = params_for("caption_with_citation", params)
    tokens = scene.tokens
    if scene.ctx is None:
        raise RuntimeError("no job context")
    try:
        citation = scene.ctx.job.citations[p.source]
    except KeyError:
        raise KeyError(
            f"source '{p.source}' has no citation in the job; declared sources: {sorted(scene.ctx.job.citations)}"
        ) from None
    if p.locator:
        citation = f"{citation}, {p.locator}"
    typeface = tokens.typeface(p.role)
    caption_face = tokens.typeface("caption")
    text = Text(p.text, **tokens.text_kwargs(typeface, tokens.color(style_role)))
    cite = Text(citation, **tokens.text_kwargs(caption_face, tokens.color("secondary_text")))
    cite.next_to(text, DOWN, buff=tokens.baseline * 0.5, aligned_edge=LEFT)
    group = VGroup(text, cite)
    place(scene, group, p)
    return register(
        scene,
        Component(
            object_id,
            "caption_with_citation",
            group,
            text=f"{p.text} [{citation}]",
            font_px=tokens.smallest_text_px(p.role, "caption"),
            text_like=True,
        ),
    )
