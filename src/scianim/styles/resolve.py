"""Token cascade: default -> theme chain -> family -> project -> scene (spec section 5.3)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from scianim.config.loader import SpecError, format_validation_error, load_style_sheet
from scianim_core import FamilyManifest, ResolvedStyle, StyleSelection, StyleSheet, StyleTokens
from scianim_core.hashing import sha256_json

OVERRIDE_ALLOWLIST: tuple[str, ...] = (
    "palette.",
    "charts.",
    "motion.transition_seconds",
    "motion.reveal_seconds",
    "layout.preferred_alignment",
)
"""Token paths a project or scene may override. Families may override any existing token."""


class StyleResolutionError(SpecError):
    pass


def find_style_sheet(name: str, search_dirs: list[Path]) -> Path:
    for directory in search_dirs:
        candidate = directory / name / "style.yaml"
        if candidate.exists():
            return candidate
    searched = ", ".join(str(d) for d in search_dirs) or "(no style directories)"
    raise StyleResolutionError(None, f"style sheet '{name}' not found; searched: {searched}")


def load_chain(name: str, search_dirs: list[Path]) -> list[tuple[Path, StyleSheet]]:
    """Return sheets from the root ancestor down to `name`."""
    chain: list[tuple[Path, StyleSheet]] = []
    seen: set[str] = set()
    current: str | None = name
    while current is not None:
        if current in seen:
            raise StyleResolutionError(None, f"style inheritance cycle at '{current}'")
        seen.add(current)
        path = find_style_sheet(current, search_dirs)
        sheet = load_style_sheet(path)
        if sheet.name != current:
            raise StyleResolutionError(path, f"sheet declares name '{sheet.name}' but lives under '{current}'")
        chain.append((path, sheet))
        current = sheet.inherits
    chain.reverse()
    return chain


def deep_merge(
    base: dict[str, Any],
    overlay: dict[str, Any],
    provenance: dict[str, str],
    layer: str,
    prefix: str = "",
) -> None:
    """Merge `overlay` into `base` in place, recording the layer that set each leaf."""
    for key, value in overlay.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value, provenance, layer, f"{path}.")
        elif isinstance(value, dict):
            base[key] = {}
            deep_merge(base[key], value, provenance, layer, f"{path}.")
        else:
            base[key] = copy.deepcopy(value)
            provenance[path] = layer


def apply_overrides(
    tokens: dict[str, Any],
    overrides: dict[str, Any],
    provenance: dict[str, str],
    layer: str,
    allowlist: tuple[str, ...] | None,
) -> None:
    """Apply dotted-path overrides. Paths must exist; palette may gain new roles."""
    for dotted, value in overrides.items():
        if allowlist is not None and not any(dotted.startswith(p) or dotted == p.rstrip(".") for p in allowlist):
            raise StyleResolutionError(
                None,
                f"{layer}: override '{dotted}' is not allowed; allowed prefixes: {list(allowlist)}",
            )
        parts = dotted.split(".")
        node: Any = tokens
        for part in parts[:-1]:
            if not isinstance(node, dict) or part not in node:
                raise StyleResolutionError(None, f"{layer}: override path '{dotted}' does not exist in the theme")
            node = node[part]
        leaf = parts[-1]
        is_new_palette_role = parts[0] == "palette" and len(parts) == 2
        if not isinstance(node, dict) or (leaf not in node and not is_new_palette_role):
            raise StyleResolutionError(None, f"{layer}: override path '{dotted}' does not exist in the theme")
        if isinstance(value, dict):
            raise StyleResolutionError(None, f"{layer}: override '{dotted}' must be a scalar, not a mapping")
        node[leaf] = value
        provenance[dotted] = layer


def resolve_style(
    selection: StyleSelection,
    search_dirs: list[Path],
    family: FamilyManifest | None = None,
    scene_overrides: dict[str, Any] | None = None,
    scene_id: str | None = None,
) -> ResolvedStyle:
    chain = load_chain(selection.name, search_dirs)
    _, leaf_sheet = chain[-1]
    if leaf_sheet.version != selection.version:
        raise StyleResolutionError(
            None,
            f"project pins style '{selection.name}' version {selection.version} but the sheet "
            f"on disk is version {leaf_sheet.version}; update the pin deliberately (ADR: themes are versioned)",
        )
    tokens: dict[str, Any] = {}
    provenance: dict[str, str] = {}
    layers: list[str] = []
    for _, sheet in chain:
        layer = f"theme:{sheet.name}@{sheet.version}"
        deep_merge(tokens, sheet.tokens_dict(), provenance, layer)
        layers.append(layer)
    if family is not None and family.style.overrides:
        layer = f"family:{family.id}"
        apply_overrides(tokens, family.style.overrides, provenance, layer, allowlist=None)
        layers.append(layer)
    if selection.overrides:
        layer = "project"
        apply_overrides(tokens, selection.overrides, provenance, layer, OVERRIDE_ALLOWLIST)
        layers.append(layer)
    if scene_overrides:
        layer = f"scene:{scene_id or '?'}"
        apply_overrides(tokens, scene_overrides, provenance, layer, OVERRIDE_ALLOWLIST)
        layers.append(layer)
    try:
        resolved_tokens = StyleTokens.model_validate(tokens)
    except ValidationError as exc:
        raise StyleResolutionError(
            None,
            f"style '{selection.name}' does not resolve to a complete token set:\n{format_validation_error(exc)}",
        ) from None
    missing = resolved_tokens.missing_palette_roles()
    if missing:
        raise StyleResolutionError(None, f"style '{selection.name}' lacks required palette roles: {missing}")
    digest = sha256_json(resolved_tokens.model_dump(mode="json"))
    return ResolvedStyle(
        theme=selection.name,
        theme_version=selection.version,
        layers=layers,
        tokens=resolved_tokens,
        provenance=dict(sorted(provenance.items())),
        hash=f"sha256:{digest}",
    )
