"""Token cascade: default -> theme chain -> family -> groups -> project -> scene (spec section 5.3).

Sheets live at `<styles dir>/<name>/<version>/style.yaml`; inheritance is pinned (`name@version`).
"""

from __future__ import annotations

import copy
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from scianim.config.loader import SpecError, format_validation_error, load_style_sheet
from scianim_core import (
    FamilyManifest,
    GroupManifest,
    ResolvedStyle,
    StyleSelection,
    StyleSheet,
    StyleTokens,
    split_style_ref,
)
from scianim_core.hashing import sha256_json

STYLE_FILE = "style.yaml"

OVERRIDE_ALLOWLIST: tuple[str, ...] = (
    "palette.",
    "charts.",
    "motion.transition_seconds",
    "motion.reveal_seconds",
    "layout.preferred_alignment",
)
"""Token paths a project or scene may override. Families and groups may override any existing token."""


class StyleResolutionError(SpecError):
    pass


def list_styles(search_dirs: Sequence[Path]) -> dict[str, dict[str, Path]]:
    """`{name: {version: path}}` for every versioned sheet; the first directory wins per name and version."""
    found: dict[str, dict[str, Path]] = {}
    for directory in search_dirs:
        if not directory.is_dir():
            continue
        for name_dir in sorted(p for p in directory.iterdir() if p.is_dir()):
            for version_dir in sorted(p for p in name_dir.iterdir() if p.is_dir()):
                sheet = version_dir / STYLE_FILE
                if sheet.exists():
                    found.setdefault(name_dir.name, {}).setdefault(version_dir.name, sheet)
    return found


def find_style_sheet(name: str, version: str, search_dirs: Sequence[Path]) -> Path:
    for directory in search_dirs:
        candidate = directory / name / version / STYLE_FILE
        if candidate.exists():
            return candidate
    hints: list[str] = []
    available = list_styles(search_dirs).get(name, {})
    if available:
        hints.append(f"available versions of '{name}': {sorted(available)}")
    flat = [d / name / STYLE_FILE for d in search_dirs if (d / name / STYLE_FILE).exists()]
    if flat:
        hints.append(f"found an unversioned sheet at {flat[0]}; move it to {flat[0].parent / version / STYLE_FILE}")
    searched = ", ".join(str(d) for d in search_dirs) or "(no style directories)"
    suffix = f" ({'; '.join(hints)})" if hints else ""
    raise StyleResolutionError(None, f"style '{name}@{version}' not found; searched: {searched}{suffix}")


def load_chain(name: str, version: str, search_dirs: Sequence[Path]) -> list[tuple[Path, StyleSheet]]:
    """Sheets from the root ancestor down to `name@version`."""
    chain: list[tuple[Path, StyleSheet]] = []
    seen: set[tuple[str, str]] = set()
    current: tuple[str, str] | None = (name, version)
    while current is not None:
        if current in seen:
            raise StyleResolutionError(None, f"style inheritance cycle at '{current[0]}@{current[1]}'")
        seen.add(current)
        path = find_style_sheet(current[0], current[1], search_dirs)
        sheet = load_style_sheet(path)
        if (sheet.name, sheet.version) != current:
            raise StyleResolutionError(
                path,
                f"sheet declares {sheet.name}@{sheet.version} but lives at a path for {current[0]}@{current[1]}",
            )
        chain.append((path, sheet))
        current = split_style_ref(sheet.inherits) if sheet.inherits else None
    chain.reverse()
    return chain


def deep_merge(
    base: dict[str, Any], overlay: dict[str, Any], provenance: dict[str, str], layer: str, prefix: str = ""
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
    """Apply dotted-path overrides. Paths must exist; the palette may gain new roles."""
    for dotted, value in overrides.items():
        if allowlist is not None and not any(dotted.startswith(p) or dotted == p.rstrip(".") for p in allowlist):
            raise StyleResolutionError(
                None, f"{layer}: override '{dotted}' is not allowed; allowed prefixes: {list(allowlist)}"
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
    search_dirs: Sequence[Path],
    family: FamilyManifest | None = None,
    groups: Sequence[GroupManifest] = (),
    scene_overrides: dict[str, Any] | None = None,
    scene_id: str | None = None,
) -> ResolvedStyle:
    chain = load_chain(selection.name, selection.version, search_dirs)
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
    for group in groups:
        if group.style.overrides:
            layer = f"group:{group.id}"
            apply_overrides(tokens, group.style.overrides, provenance, layer, allowlist=None)
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
            f"style '{selection.name}@{selection.version}' does not resolve to a complete token set:\n"
            f"{format_validation_error(exc)}",
        ) from None
    missing = resolved_tokens.missing_palette_roles()
    if missing:
        raise StyleResolutionError(
            None, f"style '{selection.name}@{selection.version}' lacks required palette roles: {missing}"
        )
    digest = sha256_json(resolved_tokens.model_dump(mode="json"))
    return ResolvedStyle(
        theme=selection.name,
        theme_version=selection.version,
        layers=layers,
        tokens=resolved_tokens,
        provenance=dict(sorted(provenance.items())),
        hash=f"sha256:{digest}",
    )
