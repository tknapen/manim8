"""`workspace.yaml`: marks the root of a user workspace."""

from __future__ import annotations

from scianim_core.common import SchemaVersion, Slug, StrictModel


class WorkspaceManifest(StrictModel):
    schema_version: SchemaVersion
    id: Slug
    description: str | None = None
