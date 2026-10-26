"""`family.yaml`: scope, environment and system requirements (spec section 5.4)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from scianim_core.common import RelPath, SchemaVersion, SemVer, Sha256, Slug, StrictModel
from scianim_core.components import ComponentKind

EnvironmentManager = Literal["uv", "docker", "apptainer"]
RequirementKind = Literal["binary", "library", "font", "image", "python_module"]


class EnvironmentSpec(StrictModel):
    manager: EnvironmentManager = "uv"
    project_root: RelPath = "."
    lockfile: str = "uv.lock"
    install_policy: Literal["explicit"] = "explicit"
    image: str | None = None
    """Container image reference when manager is docker or apptainer."""


class SystemRequirement(StrictModel):
    kind: RequirementKind
    name: str = Field(min_length=1)
    min_version: str | None = None
    sha256: Sha256 | None = None
    optional: bool = False
    note: str | None = None


class FamilyStyle(StrictModel):
    name: Slug
    version: SemVer
    overrides: dict[str, Any] = {}


class FamilyManifest(StrictModel):
    schema_version: SchemaVersion
    id: Slug
    title: str = Field(min_length=1)
    style: FamilyStyle
    environment: EnvironmentSpec = EnvironmentSpec()
    system_requirements: list[SystemRequirement] = []
    shared_assets: list[str] = []
    components: list[ComponentKind] = []
    schema_extensions: list[str] = []
