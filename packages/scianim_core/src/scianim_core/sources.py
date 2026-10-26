"""Source extracts: what a supplied file contains, separated from what anyone infers from it (spec 6.1).

An extract is produced by a source adapter in the control plane and stored under `.scianim/sources/`.
Its `says` section holds only facts read from the file (columns, counts, text with page anchors);
`inferred` is reserved for interpretations, which must name who made them.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from scianim_core.animation import SourceRole, SourceType
from scianim_core.common import SchemaVersion, Sha256, Slug, StrictModel


class ColumnProfile(StrictModel):
    name: str
    dtype: Literal["number", "integer", "text", "boolean", "empty"]
    missing: int = Field(ge=0)
    distinct: int = Field(ge=0)
    minimum: float | None = None
    maximum: float | None = None
    mean: float | None = None
    examples: list[str] = []


class PageText(StrictModel):
    page: int = Field(ge=1)
    characters: int = Field(ge=0)
    text: str


class Inference(StrictModel):
    """An interpretation of a source, attributed; never produced by an adapter."""

    by: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    locator: str | None = None


class SourceExtract(StrictModel):
    schema_version: SchemaVersion = "1.0"
    source_id: Slug
    type: SourceType
    role: SourceRole
    path: str
    sha256: Sha256
    size_bytes: int = Field(ge=0)
    extracted_at: str
    adapter: str
    says: dict[str, Any] = {}
    """Facts read from the file: columns, row counts, page texts, dimensions, headings."""
    inferred: list[Inference] = []
    notes: list[str] = []
    """Adapter limitations, e.g. equations not extracted from a PDF."""


__all__ = ["ColumnProfile", "Inference", "PageText", "SourceExtract"]
