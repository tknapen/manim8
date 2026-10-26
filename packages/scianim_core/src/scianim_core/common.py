"""Shared primitives for every SciAnim contract model."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints

SCHEMA_VERSION = "1.0"
SchemaVersion = Literal["1.0"]

Kind = Literal["hard", "preferred"]
"""Whether a constraint or milestone must be met (hard) or should be met (preferred)."""

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
"""Stable lowercase identifier: letters, digits and underscores, starting with a letter."""

SemVer = Annotated[str, StringConstraints(pattern=r"^\d+\.\d+\.\d+$")]
HexColor = Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

_DRIVE_LETTER = re.compile(r"^[A-Za-z]:")


class StrictModel(BaseModel):
    """Base model: unknown keys are errors, strings are stripped, defaults are validated."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, validate_default=True)


def check_relative_path(value: str) -> str:
    """Accept only forward-slash paths that stay inside the project directory."""
    if not value:
        raise ValueError("path must not be empty")
    if "\\" in value:
        raise ValueError("use forward slashes in paths")
    if value.startswith("/") or _DRIVE_LETTER.match(value):
        raise ValueError("path must be relative to the project directory, not absolute")
    parts = value.split("/")
    if any(part == ".." for part in parts):
        raise ValueError("path escapes the project directory ('..' is not allowed)")
    if any(part == "" for part in parts):
        raise ValueError("path has an empty segment (double or trailing slash)")
    return value


RelPath = Annotated[str, AfterValidator(check_relative_path)]
"""Project-relative path. '.' is allowed; '..', absolute paths and backslashes are not."""

ASSET_SCHEME = "asset://"
AssetUri = Annotated[str, StringConstraints(pattern=r"^asset://[a-z][a-z0-9_./-]*[a-z0-9]$")]
"""Reference to a shared asset by id, resolved against family and workspace `assets/` directories."""


def is_asset_uri(value: str) -> bool:
    return value.startswith(ASSET_SCHEME)


def asset_id(value: str) -> str:
    if not is_asset_uri(value):
        raise ValueError(f"not an asset URI: {value!r}")
    return value[len(ASSET_SCHEME) :]


def ensure_unique(ids: Iterable[str], what: str) -> None:
    """Raise ValueError naming duplicate identifiers."""
    seen: set[str] = set()
    duplicates: set[str] = set()
    for item in ids:
        if item in seen:
            duplicates.add(item)
        seen.add(item)
    if duplicates:
        raise ValueError(f"duplicate {what} id(s): {sorted(duplicates)}")
