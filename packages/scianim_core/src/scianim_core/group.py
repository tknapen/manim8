"""`group.yaml`: a topical folder between a family and its projects (spec section 4.1).

A group contributes style overrides, shared assets and tags. It never declares an environment;
the family's environment is inherited through it.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from scianim_core.common import SchemaVersion, Slug, StrictModel


class GroupStyle(StrictModel):
    overrides: dict[str, Any] = {}
    """Dotted token paths to values, applied after the family's overrides."""


class GroupManifest(StrictModel):
    schema_version: SchemaVersion
    id: Slug
    title: str | None = Field(default=None, min_length=1)
    style: GroupStyle = GroupStyle()
    shared_assets: list[str] = []
    tags: list[str] = []
