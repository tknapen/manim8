"""SciAnim Studio contracts: Pydantic models shared by the control plane and the render bridge.

This package depends on Pydantic only. It never imports Manim.
"""

from scianim_core.animation import (
    AnimationSpec,
    Constraint,
    Equation,
    Milestone,
    OutputSpec,
    SourceRef,
    StyleSelection,
)
from scianim_core.common import SCHEMA_VERSION, RelPath, Slug, StrictModel
from scianim_core.components import REGISTRY, REGISTRY_VERSION, ComponentDefinition, validate_params
from scianim_core.family import FamilyManifest, SystemRequirement
from scianim_core.jobs import (
    ArtifactManifest,
    BBox,
    CheckpointRecord,
    InputHashes,
    LayoutItem,
    LayoutWarning,
    ManimSettings,
    RenderJob,
    SnapshotTarget,
    ToolVersions,
    WorkerResult,
)
from scianim_core.storyboard import Narration, Scene, SceneObject, Snapshot, Storyboard
from scianim_core.style import ResolvedStyle, StyleSheet, StyleTokens

__version__ = "0.1.0a0"

__all__ = [
    "REGISTRY",
    "REGISTRY_VERSION",
    "SCHEMA_VERSION",
    "AnimationSpec",
    "ArtifactManifest",
    "BBox",
    "CheckpointRecord",
    "ComponentDefinition",
    "Constraint",
    "Equation",
    "FamilyManifest",
    "InputHashes",
    "LayoutItem",
    "LayoutWarning",
    "ManimSettings",
    "Milestone",
    "Narration",
    "OutputSpec",
    "RelPath",
    "RenderJob",
    "ResolvedStyle",
    "Scene",
    "SceneObject",
    "Slug",
    "Snapshot",
    "SnapshotTarget",
    "SourceRef",
    "Storyboard",
    "StrictModel",
    "StyleSelection",
    "StyleSheet",
    "StyleTokens",
    "SystemRequirement",
    "ToolVersions",
    "WorkerResult",
    "__version__",
    "validate_params",
]
