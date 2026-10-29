"""Shared component machinery."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
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
    three_d: bool = False
    """True for objects that live in the rotating world (surfaces); flat objects stay fixed in the frame."""
    axes: VGroup | None = None
    """The frame, ticks and labels that a `fade_axes` action fades, when the object draws them as a separable
    group (surfaces do); None for everything else."""

    def reveal_animation(self) -> Animation:
        return FadeIn(self.group)


@dataclass
class ParametricComponent(Component):
    """An object with named parameters that can be re-evaluated in place; `vary_parameter` drives it.

    `set_parameters` returns warnings (a value that leaves a fixed range is clipped, for instance).
    """

    parameters: dict[str, float] = field(default_factory=dict)
    rebuild: Callable[[dict[str, float]], list[str]] | None = None

    def set_parameters(self, **values: float) -> list[str]:
        self.parameters.update(values)
        return self.rebuild(dict(self.parameters)) if self.rebuild else []


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
