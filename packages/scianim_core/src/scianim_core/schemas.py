"""Deterministic JSON Schema export for every public contract."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from scianim_core.animation import AnimationSpec
from scianim_core.family import FamilyManifest
from scianim_core.feedback import FeedbackRecord
from scianim_core.group import GroupManifest
from scianim_core.jobs import ArtifactManifest, RenderJob, WorkerResult
from scianim_core.revisions import RevisionRecord
from scianim_core.storyboard import Storyboard
from scianim_core.style import ResolvedStyle, StyleSheet
from scianim_core.workspace import WorkspaceManifest

PUBLIC_SCHEMAS: dict[str, type[BaseModel]] = {
    "animation": AnimationSpec,
    "storyboard": Storyboard,
    "style": StyleSheet,
    "family": FamilyManifest,
    "group": GroupManifest,
    "workspace": WorkspaceManifest,
    "revision": RevisionRecord,
    "resolved_style": ResolvedStyle,
    "render_job": RenderJob,
    "worker_result": WorkerResult,
    "artifact_manifest": ArtifactManifest,
    "feedback": FeedbackRecord,
}


def schema_text(model: type[BaseModel]) -> str:
    return json.dumps(model.model_json_schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def render_schemas() -> dict[str, str]:
    return {f"{name}.schema.json": schema_text(model) for name, model in PUBLIC_SCHEMAS.items()}


def export_schemas(directory: Path, check: bool = False) -> list[str]:
    """Write schemas into `directory`. With `check`, write nothing and return stale file names."""
    directory.mkdir(parents=True, exist_ok=True)
    stale: list[str] = []
    for filename, text in render_schemas().items():
        target = directory / filename
        if check:
            if not target.exists() or target.read_text(encoding="utf-8") != text:
                stale.append(filename)
        else:
            target.write_text(text, encoding="utf-8")
    return stale
