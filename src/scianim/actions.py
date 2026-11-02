"""One-line descriptions of storyboard actions, shared by the review server and the agent's context bundle."""

from __future__ import annotations

from scianim_core.storyboard import (
    Emphasize,
    FadeAxes,
    FadeObject,
    MoveObject,
    OrbitCamera,
    SceneAction,
    TransformEquation,
    VaryParameter,
)


def _place(target: str, symbols: list[str]) -> str:
    return f"{', '.join(symbols)} in {target}" if symbols else target


def action_summary(action: SceneAction) -> str:
    if isinstance(action, OrbitCamera):
        parts = []
        if action.to_theta_degrees is not None:
            parts.append(f"azimuth to {action.to_theta_degrees:g} deg")
        if action.to_phi_degrees is not None:
            parts.append(f"elevation to {action.to_phi_degrees:g} deg")
        return "camera " + ", ".join(parts)
    if isinstance(action, FadeAxes):
        return f"axes of {action.target} fade {'in' if action.visible else 'out'}"
    if isinstance(action, MoveObject):
        if action.to_anchor is not None:
            return f"{action.target} moves to {action.to_anchor.replace('_', ' ')}"
        if action.by is not None:
            return f"{action.target} moves by ({action.by[0]:g}, {action.by[1]:g}) of the safe frame"
        assert action.to_point is not None
        return f"{action.target} moves to ({', '.join(f'{v:g}' for v in action.to_point)})"
    if isinstance(action, FadeObject):
        if action.ink is not None and 0 < action.ink < 1:
            return f"{action.target} dims to {action.ink:g} of its ink"
        return f"{action.target} fades {'in' if action.target_ink > 0 else 'out'}"
    if isinstance(action, TransformEquation):
        return f"{action.target} becomes equation {action.to} ({action.match.replace('_', ' ')})"
    if isinstance(action, Emphasize):
        where = _place(action.target, action.symbols)
        if action.cue == "pulse":
            return f"{where} pulses"
        if action.from_target is not None:
            return f"a box travels from {_place(action.from_target, action.from_symbols)} to {where}"
        return f"a box points at {where}"
    assert isinstance(action, VaryParameter)
    text = f"{action.target}.{action.parameter} to {action.to:g}"
    if action.emphasize:
        text += ", emphasizing " + ", ".join(action.emphasize)
    if action.lead_in_seconds:
        text += f", after a {action.lead_in_seconds:g} s lead-in"
    return text
