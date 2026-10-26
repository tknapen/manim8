"""YAML loading and model dispatch with readable validation errors."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from scianim_core import AnimationSpec, FamilyManifest, GroupManifest, Storyboard, StyleSheet, WorkspaceManifest

SpecKind = Literal["animation", "storyboard", "style", "family", "group", "workspace"]

MODELS: dict[SpecKind, type[BaseModel]] = {
    "animation": AnimationSpec,
    "storyboard": Storyboard,
    "style": StyleSheet,
    "family": FamilyManifest,
    "group": GroupManifest,
    "workspace": WorkspaceManifest,
}

CANONICAL_NAMES: dict[str, SpecKind] = {f"{kind}.yaml": kind for kind in MODELS}

_yaml = YAML(typ="safe")


class SpecError(Exception):
    """A specification file failed to load or validate. `message` is user-facing."""

    def __init__(self, path: Path | None, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}" if path else message)


def format_validation_error(exc: ValidationError) -> str:
    lines = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "<root>"
        lines.append(f"  - {loc}: {err['msg']}")
    return "\n".join(lines)


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        data = _yaml.load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SpecError(path, "file not found") from None
    except YAMLError as exc:
        raise SpecError(path, f"YAML syntax error: {exc}") from None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise SpecError(path, "top level must be a mapping")
    return data


def detect_kind(data: dict[str, Any], path: Path | None = None) -> SpecKind:
    if path is not None and path.name in CANONICAL_NAMES:
        return CANONICAL_NAMES[path.name]
    keys = set(data)
    if {"project_id", "scenes"} <= keys:
        return "storyboard"
    if {"output", "objective"} <= keys:
        return "animation"
    if "palette" in keys or "inherits" in keys:
        return "style"
    if "environment" in keys or "system_requirements" in keys or "components" in keys:
        return "family"
    if "tags" in keys or "shared_assets" in keys:
        return "group"
    if keys <= {"schema_version", "id", "description"}:
        return "workspace"
    raise SpecError(
        path, "cannot tell which specification this is (animation, storyboard, style, family, group or workspace)"
    )


def validate_data(data: dict[str, Any], kind: SpecKind, path: Path | None = None) -> BaseModel:
    try:
        return MODELS[kind].model_validate(data)
    except ValidationError as exc:
        raise SpecError(path, f"invalid {kind} specification:\n{format_validation_error(exc)}") from None


def load_spec(path: Path, kind: SpecKind | None = None) -> tuple[SpecKind, BaseModel]:
    data = load_yaml(path)
    resolved_kind = kind or detect_kind(data, path)
    return resolved_kind, validate_data(data, resolved_kind, path)


def load_animation(path: Path) -> AnimationSpec:
    _, model = load_spec(path, "animation")
    assert isinstance(model, AnimationSpec)
    return model


def load_storyboard(path: Path) -> Storyboard:
    _, model = load_spec(path, "storyboard")
    assert isinstance(model, Storyboard)
    return model


def load_style_sheet(path: Path) -> StyleSheet:
    _, model = load_spec(path, "style")
    assert isinstance(model, StyleSheet)
    return model


def load_family(path: Path) -> FamilyManifest:
    _, model = load_spec(path, "family")
    assert isinstance(model, FamilyManifest)
    return model


def load_group(path: Path) -> GroupManifest:
    _, model = load_spec(path, "group")
    assert isinstance(model, GroupManifest)
    return model


def load_workspace_manifest(path: Path) -> WorkspaceManifest:
    _, model = load_spec(path, "workspace")
    assert isinstance(model, WorkspaceManifest)
    return model
