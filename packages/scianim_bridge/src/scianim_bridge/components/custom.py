"""`kind: custom`: the explicit escape hatch. The builder lives in the project's `code/` directory."""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING, Any

from manim import VGroup

from scianim_bridge.components.base import Component, params_for, register

if TYPE_CHECKING:
    from scianim_bridge.scene import SnapshotScene


def custom(
    scene: SnapshotScene,
    object_id: str,
    *,
    style_role: str | None = None,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    equation: dict[str, Any] | None = None,
) -> Component:
    p = params_for("custom", params)
    module_name, function_name = p.builder.split(":")
    if scene.ctx is not None:
        code_dir = str(scene.ctx.project_root / "code")
        if code_dir not in sys.path:
            sys.path.insert(0, code_dir)
    module = importlib.import_module(module_name)
    builder = getattr(module, function_name)
    result = builder(
        scene,
        object_id,
        scene.tokens,
        dict(p.arguments),
        style_role=style_role,
        data=data,
        equation=equation,
    )
    if isinstance(result, Component):
        component = result
    else:
        component = Component(object_id, "custom", result if isinstance(result, VGroup) else VGroup(result))
    component.kind = "custom"
    return register(scene, component)
