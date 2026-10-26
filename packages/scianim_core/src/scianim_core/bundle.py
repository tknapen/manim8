"""`bundle.yaml`: the manifest of a portable project or family bundle (spec section 12).

A bundle is a zip archive with a single `scianim-bundle/` root. It is inspectable without SciAnim:
the manifest lists what is inside, what was deliberately left out and how to put it back, and
`MANIFEST.sha256` lets anyone verify every file.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from scianim_core.animation import SourceRole, SourceType
from scianim_core.common import SchemaVersion, SemVer, Slug, StrictModel
from scianim_core.family import FamilyManifest, SystemRequirement

BUNDLE_ROOT = "scianim-bundle"
CHECKSUM_FILE = "MANIFEST.sha256"
BundleKind = Literal["project", "family"]


class InclusionPolicy(StrictModel):
    include_renders: bool = False
    include_source_assets: bool = False
    """Whether PDFs and third-party reference images were included (never by default)."""
    redact_paths: bool = False
    """Whether absolute paths found in text files were replaced instead of failing the export."""


class OmittedSource(StrictModel):
    project_id: Slug
    source_id: Slug
    type: SourceType
    role: SourceRole
    path: str
    reason: str
    relink: str
    """What to do after import so the project validates again."""


class BundleProject(StrictModel):
    id: Slug
    path: str
    """Directory inside the bundle, relative to its root (`projects/<id>`)."""
    title: str
    revisions: list[str] = []
    renders_included: bool = False
    feedback_records: int = 0
    applied_proposals: int = 0


class BundleEnvironment(StrictModel):
    manager: str = "uv"
    pyproject: bool = False
    lockfile: bool = False
    packages_relative: str | None = None
    """Where `packages/` sat relative to the family at export; the lock is reusable only at the same offset."""
    system_requirements: list[SystemRequirement] = []


class BundleManifest(StrictModel):
    schema_version: SchemaVersion = "1.0"
    bundle_id: Slug
    kind: BundleKind
    created_at: str
    scianim_version: str
    registry_version: SemVer
    family: FamilyManifest
    projects: list[BundleProject] = []
    styles: list[str] = []
    """`name@version` of every sheet included, the whole inheritance chain of each project's style."""
    components: list[str] = []
    """Python files copied from the family's shared `components/`; imported as files, never executed."""
    assets: list[str] = []
    environment: BundleEnvironment = BundleEnvironment()
    policy: InclusionPolicy = InclusionPolicy()
    omitted_sources: list[OmittedSource] = []
    checksum_file: str = CHECKSUM_FILE
    file_count: int = Field(ge=0, default=0)
    notes: list[str] = []


__all__ = [
    "BUNDLE_ROOT",
    "CHECKSUM_FILE",
    "BundleEnvironment",
    "BundleKind",
    "BundleManifest",
    "BundleProject",
    "InclusionPolicy",
    "OmittedSource",
]
