"""Shared component machinery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from manim import Animation, FadeIn, VGroup

from scianim_core.components import validate_params

if TYPE_CHECKING:
    from scianim_bridge.scene import SnapshotScene

GREEK = {
    "alpha": "α",
    "beta": "β",
    "gamma": "γ",
    "delta": "δ",
    "epsilon": "ε",
    "zeta": "ζ",
    "eta": "η",
    "theta": "θ",
    "iota": "ι",
    "kappa": "κ",
    "lambda": "λ",
    "mu": "μ",
    "nu": "ν",
    "xi": "ξ",
    "pi": "π",
    "rho": "ρ",
    "sigma": "σ",
    "tau": "τ",
    "upsilon": "υ",
    "phi": "φ",
    "chi": "χ",
    "psi": "ψ",
    "omega": "ω",
    "Gamma": "Γ",
    "Delta": "Δ",
    "Theta": "Θ",
    "Lambda": "Λ",
    "Xi": "Ξ",
    "Pi": "Π",
    "Sigma": "Σ",
    "Phi": "Φ",
    "Psi": "Ψ",
    "Omega": "Ω",
}


SUBSCRIPT_DIGITS = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")


def pretty_symbol(name: str) -> str:
    """Map a symbol name to display form: a Greek name becomes the Greek letter and a trailing
    ``_<digits>`` suffix becomes Unicode subscript digits ('sigma', 'x_0', 'tau_1'); anything else is unchanged."""
    base, _, suffix = name.partition("_")
    base = GREEK.get(base, base)
    if suffix and suffix.isdigit():
        return base + suffix.translate(SUBSCRIPT_DIGITS)
    return base + ("_" + suffix if suffix else "")


def pretty_condition(value: str) -> str:
    return value.replace("_", " ")


@dataclass
class Component:
    object_id: str
    kind: str
    group: VGroup
    text: str | None = None
    font_px: float | None = None
    """Em size in output pixels of the smallest text the object draws, tick labels included; None when it
    draws no text. Drives `text_too_small`."""
    text_like: bool = False
    visible: bool = False

    def reveal_animation(self) -> Animation:
        return FadeIn(self.group)


def params_for(kind: str, params: dict[str, Any] | None) -> Any:
    return validate_params(kind, params or {})


def register(scene: SnapshotScene, component: Component) -> Component:
    scene.register(component)
    return component


def place(scene: SnapshotScene, group: VGroup, params: Any) -> None:
    """Anchor placement, or `below` / `right_of` an earlier object with the style's baseline gap."""
    from manim import DOWN, LEFT, RIGHT

    tokens = scene.tokens
    gap = tokens.units(params.gap_px_at_1080p or tokens.t.layout.baseline_grid_px_at_1080p)
    reference = params.below or params.right_of
    if reference is None:
        tokens.place(group, params.anchor)
        return
    try:
        target = scene.objects[reference].group
    except KeyError:
        raise ValueError(f"placement refers to unknown object '{reference}'") from None
    if params.below:
        group.next_to(target, DOWN, buff=gap, aligned_edge=LEFT)
    else:
        group.next_to(target, RIGHT, buff=gap, aligned_edge=DOWN)
