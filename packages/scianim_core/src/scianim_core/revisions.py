"""Immutable project revisions (spec section 5.5 and 11)."""

from __future__ import annotations

from pydantic import Field

from scianim_core.common import SchemaVersion, SemVer, Sha256, Slug, StrictModel

REVISION_ID_PATTERN = r"^rev_\d{4}$"


class RevisionHashes(StrictModel):
    animation_spec: Sha256
    storyboard: Sha256 | None = None
    scene_code: Sha256 | None = None
    custom_code: dict[str, Sha256] = {}
    resolved_style: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    data_files: dict[Slug, Sha256] = {}
    """Hashes of the data files at revision time; the files themselves stay in `data/`."""


class RevisionRecord(StrictModel):
    schema_version: SchemaVersion = "1.0"
    id: str = Field(pattern=REVISION_ID_PATTERN)
    created_at: str
    parent: str | None = Field(default=None, pattern=REVISION_ID_PATTERN)
    message: str = Field(min_length=1)
    style_theme: Slug
    style_version: SemVer
    hashes: RevisionHashes
    files: list[str] = []
    """Files copied into the revision directory, relative to it."""
