"""Registered components. Generated code calls these as `C.<kind>(scene, object_id, ...)`."""

from scianim_bridge.components.base import Component
from scianim_bridge.components.custom import custom
from scianim_bridge.components.equations import equation_block, equation_label
from scianim_bridge.components.plots import comparison_plot, scientific_plot
from scianim_bridge.components.text import text_caption

__all__ = [
    "Component",
    "comparison_plot",
    "custom",
    "equation_block",
    "equation_label",
    "scientific_plot",
    "text_caption",
]
