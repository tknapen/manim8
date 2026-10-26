"""Registered components. Generated code calls these as `C.<kind>(scene, object_id, ...)`."""

from scianim_bridge.components.base import Component
from scianim_bridge.components.custom import custom
from scianim_bridge.components.equations import equation_block, equation_label
from scianim_bridge.components.graph import network_graph
from scianim_bridge.components.plots import comparison_plot, function_plot, scientific_plot
from scianim_bridge.components.schematic import receptive_field_glyph, schematic_population
from scianim_bridge.components.surfaces import function_image, surface_plot
from scianim_bridge.components.text import caption_with_citation, text_caption

__all__ = [
    "Component",
    "caption_with_citation",
    "comparison_plot",
    "custom",
    "equation_block",
    "equation_label",
    "function_image",
    "function_plot",
    "network_graph",
    "receptive_field_glyph",
    "schematic_population",
    "scientific_plot",
    "surface_plot",
    "text_caption",
]
