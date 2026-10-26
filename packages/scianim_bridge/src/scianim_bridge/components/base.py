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


def pretty_symbol(name: str) -> str:
    return GREEK.get(name, name)


def pretty_condition(value: str) -> str:
    return value.replace("_", " ")


@dataclass
class Component:
    object_id: str
    kind: str
    group: VGroup
    text: str | None = None
    font_px: float | None = None
    """Font em size in output pixels for text-like objects (drives `text_too_small`)."""
    text_like: bool = False
    visible: bool = False

    def reveal_animation(self) -> Animation:
        return FadeIn(self.group)


def params_for(kind: str, params: dict[str, Any] | None) -> Any:
    return validate_params(kind, params or {})


def register(scene: SnapshotScene, component: Component) -> Component:
    scene.register(component)
    return component
