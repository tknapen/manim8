"""Which storyboard scenes a change touches (spec section 11.3, first step: scene-level invalidation).

Rendering itself reuses Manim's per-play cache under the revision's stable `media_dir`; this report
tells the reviewer and the agent which scenes to look at again, and never marks anything approved.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from scianim.planning.checks import Report
from scianim.project import Project
from scianim.revisions.store import RevisionSources, compute_hashes
from scianim_core import AnimationSpec, Storyboard
from scianim_core.hashing import sha256_json


@dataclass
class SceneChange:
    scene_id: str
    reasons: list[str] = field(default_factory=list)

    @property
    def stale(self) -> bool:
        return bool(self.reasons)


@dataclass
class DependencyReport:
    scenes: list[SceneChange]
    removed_scenes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def stale_scene_ids(self) -> list[str]:
        return [s.scene_id for s in self.scenes if s.stale]


def changed_scenes(
    before: Storyboard | None,
    after: Storyboard,
    *,
    before_spec: AnimationSpec | None,
    after_spec: AnimationSpec,
    data_changed: set[str],
    style_changed: bool,
    custom_code_changed: bool,
) -> DependencyReport:
    equations_before = {e.id: e for e in before_spec.equations} if before_spec else {}
    equations_after = {e.id: e for e in after_spec.equations}
    equations_changed = {eid for eid, eq in equations_after.items() if equations_before.get(eid) != eq}
    previous = {s.id: s for s in before.scenes} if before else {}
    report = DependencyReport(scenes=[])
    for scene in after.scenes:
        change = SceneChange(scene.id)
        old = previous.get(scene.id)
        if old is None:
            change.reasons.append("new scene" if before else "no earlier revision to compare with")
        else:
            if (old.start_seconds, old.end_seconds) != (scene.start_seconds, scene.end_seconds):
                change.reasons.append("timing changed")
            if old.narration != scene.narration:
                change.reasons.append("narration changed")
            if old.objects != scene.objects:
                change.reasons.append("objects changed")
            if old.actions != scene.actions:
                change.reasons.append("actions changed")
            if old.snapshots != scene.snapshots:
                change.reasons.append("snapshots changed")
        for obj in scene.objects:
            if obj.data is not None and obj.data.source in data_changed:
                change.reasons.append(f"data source '{obj.data.source}' changed")
            if obj.equation is not None and obj.equation.id in equations_changed:
                change.reasons.append(f"equation '{obj.equation.id}' changed")
            if obj.kind == "custom" and custom_code_changed:
                change.reasons.append("custom builder code changed")
        if style_changed:
            change.reasons.append("style tokens changed")
        report.scenes.append(change)
    report.removed_scenes = [sid for sid in previous if sid not in {s.id for s in after.scenes}]
    if before is None:
        report.notes.append("no revision to compare with: every scene counts as new")
    return report


def compare_with_revision(project: Project, report: Report, revision: RevisionSources | None) -> DependencyReport:
    """The working copy against a frozen revision (data by hash, style by hash, custom code by hash)."""
    assert report.animation is not None and report.storyboard is not None and report.style is not None
    if revision is None:
        return changed_scenes(
            None,
            report.storyboard,
            before_spec=None,
            after_spec=report.animation,
            data_changed=set(),
            style_changed=False,
            custom_code_changed=False,
        )
    from scianim.config.loader import load_animation, load_storyboard

    before_spec = load_animation(revision.animation_path)
    before = load_storyboard(revision.storyboard_path) if revision.storyboard_path else None
    current = compute_hashes(project, report)
    recorded = revision.record.hashes
    data_changed = {
        source_id for source_id, digest in current.data_files.items() if recorded.data_files.get(source_id) != digest
    }
    return changed_scenes(
        before,
        report.storyboard,
        before_spec=before_spec,
        after_spec=report.animation,
        data_changed=data_changed,
        style_changed=current.resolved_style != recorded.resolved_style,
        custom_code_changed=current.custom_code != recorded.custom_code,
    )


__all__ = ["DependencyReport", "SceneChange", "changed_scenes", "compare_with_revision"]


def _strings(value: Any) -> set[str]:
    """Every string anywhere in a JSON-like value (keys excluded)."""
    found: set[str] = set()
    if isinstance(value, str):
        found.add(value)
    elif isinstance(value, dict):
        for item in value.values():
            found |= _strings(item)
    elif isinstance(value, list | tuple):
        for item in value:
            found |= _strings(item)
    return found


def scene_fingerprints(
    spec: AnimationSpec,
    storyboard: Storyboard,
    *,
    style_hash: str,
    data_hashes: dict[str, str],
    custom_hashes: dict[str, str],
) -> dict[str, str]:
    """A hash per scene of everything that decides its pictures (ADR-033): the scene's own mapping, the
    equations and sources it names (with the data files' contents), the custom builders when it uses one, the
    resolved style, the output settings, and the camera moves of the scenes before it, which are the only
    state a scene hands to the next (earlier objects are faded out at a scene's end). A render compares them
    with the previous render's to predict which scenes it can take from the segment store; the store itself
    is keyed by Manim's hash of each play, so a wrong prediction costs balance, never correctness."""
    equations = {e.id: e.model_dump(mode="json") for e in spec.equations}
    sources = {s.id: s.model_dump(mode="json") for s in spec.sources}
    output = spec.output.model_dump(mode="json")
    camera: list[Any] = []
    prints: dict[str, str] = {}
    for scene in storyboard.scenes:
        mapping = scene.model_dump(mode="json")
        named = _strings(mapping)
        uses_custom = any(o.kind == "custom" for o in scene.objects)
        payload = {
            "scene": mapping,
            "equations": {eid: equations[eid] for eid in sorted(named & set(equations))},
            "sources": {sid: sources[sid] for sid in sorted(named & set(sources))},
            "data": {sid: data_hashes[sid] for sid in sorted(named & set(data_hashes))},
            "custom": dict(sorted(custom_hashes.items())) if uses_custom else {},
            "style": style_hash,
            "output": output,
            "camera_before": list(camera),
        }
        prints[scene.id] = sha256_json(payload)
        camera += [a.model_dump(mode="json") for a in scene.actions if a.kind == "orbit_camera"]
    return prints
