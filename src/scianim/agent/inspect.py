"""Self-inspection: compare rendered checkpoints and layout reports with the storyboard (spec 7.2, item 10).

Deterministic checks only. The result is a list of findings the agent must read before asking a
person to review, and may record as feedback so the discrepancies are visible in the UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PIL import Image

from scianim.feedback.store import ResolvedTarget, build_record, write_feedback
from scianim.project import Project
from scianim_core import ArtifactManifest, CheckpointRecord, FeedbackRecord, Storyboard

Severity = Literal["discrepancy", "warning", "note"]
BLANK_FRACTION = 0.0005
"""Below this fraction of non-background pixels a frame counts as blank."""


@dataclass
class Finding:
    snapshot_id: str
    severity: Severity
    code: str
    detail: str
    object_id: str | None = None


def expected_objects(storyboard: Storyboard, scene_id: str, at_seconds: float) -> list[str]:
    """Objects revealed by `at_seconds`, plus the readouts of actions that have begun (they carry the action id)."""
    scene = next((s for s in storyboard.scenes if s.id == scene_id), None)
    if scene is None:
        return []
    objects = [o.id for o in scene.objects if o.reveal_at_seconds is None or o.reveal_at_seconds <= at_seconds + 1e-9]
    readouts = [a.id for a in scene.actions if a.show_value and a.at_seconds <= at_seconds + 1e-9]
    return objects + readouts


def ink_fraction(path: Path, background_hex: str) -> float:
    """Fraction of pixels that differ from the background colour by more than antialiasing noise."""
    background = tuple(int(background_hex[i : i + 2], 16) for i in (1, 3, 5))
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        small = rgb.resize((max(1, rgb.width // 4), max(1, rgb.height // 4)))
        pixels = small.getdata()
        differing = sum(1 for p in pixels if max(abs(p[i] - background[i]) for i in range(3)) > 16)
        return differing / max(1, len(pixels))


def inspect_checkpoint(
    project: Project, manifest: ArtifactManifest, storyboard: Storyboard, record: CheckpointRecord
) -> list[Finding]:
    findings: list[Finding] = []
    present = {item.object_id for item in record.layout}
    if record.kind == "manim_checkpoint":
        expected = expected_objects(storyboard, record.scene_id, record.expected_time_seconds)
        for object_id in expected:
            if object_id not in present:
                findings.append(
                    Finding(
                        record.snapshot_id,
                        "discrepancy",
                        "object_missing",
                        f"object '{object_id}' should be visible at {record.expected_time_seconds:g}s but is not in the layout report",
                        object_id,
                    )
                )
        for object_id in sorted(present - set(expected)):
            findings.append(
                Finding(
                    record.snapshot_id,
                    "note",
                    "object_unexpected",
                    f"object '{object_id}' is visible but the storyboard does not reveal it by {record.expected_time_seconds:g}s",
                    object_id,
                )
            )
        description = manifest.job.snapshots.get(record.snapshot_id)
        if description is not None:
            for object_id in expected:
                if object_id in description.description and object_id not in present:
                    findings.append(
                        Finding(
                            record.snapshot_id,
                            "discrepancy",
                            "description_names_missing_object",
                            f"the description mentions '{object_id}', which is not in the frame",
                            object_id,
                        )
                    )
    for warning in record.warnings:
        findings.append(
            Finding(
                record.snapshot_id,
                "warning",
                warning.code,
                f"{warning.detail} ({', '.join(warning.object_ids)})",
                warning.object_ids[0] if warning.object_ids else None,
            )
        )
    if record.fidelity != "exact":
        findings.append(
            Finding(
                record.snapshot_id,
                "warning",
                "approximate",
                record.fidelity_note or "fast-forward may not reproduce this state; confirm with a sampled video frame",
            )
        )
    png = project.root / record.png
    if png.exists():
        fraction = ink_fraction(png, manifest.job.resolved_style.tokens.palette["background"])
        if fraction < BLANK_FRACTION and present:
            findings.append(
                Finding(
                    record.snapshot_id,
                    "discrepancy",
                    "blank_frame",
                    f"the frame is blank ({fraction:.5f} of pixels differ from the background) although {len(present)} object(s) are registered",
                )
            )
        elif fraction < BLANK_FRACTION and not present and record.kind == "manim_checkpoint":
            findings.append(
                Finding(record.snapshot_id, "note", "empty_frame", "nothing is drawn and nothing is expected")
            )
    else:
        findings.append(Finding(record.snapshot_id, "discrepancy", "png_missing", f"{record.png} is missing on disk"))
    return findings


def inspect_manifest(project: Project, manifest: ArtifactManifest, storyboard: Storyboard) -> list[Finding]:
    findings: list[Finding] = []
    for record in manifest.result.checkpoints:
        findings.extend(inspect_checkpoint(project, manifest, storyboard, record))
    rendered = {c.snapshot_id for c in manifest.result.checkpoints}
    wanted = set(manifest.job.snapshot_ids) if manifest.job.snapshot_ids else set(manifest.job.snapshots)
    for snapshot_id in sorted(wanted - rendered):
        findings.append(
            Finding(snapshot_id, "discrepancy", "not_rendered", "the checkpoint was requested but not rendered")
        )
    return findings


def record_findings(
    project: Project, manifest: ArtifactManifest, findings: list[Finding], author: str = "agent:inspect"
) -> list[FeedbackRecord]:
    """Write discrepancies and warnings as feedback so they are reviewable; notes are not recorded."""
    records: list[FeedbackRecord] = []
    by_snapshot = {c.snapshot_id: c for c in manifest.result.checkpoints}
    for finding in findings:
        if finding.severity == "note":
            continue
        checkpoint = by_snapshot.get(finding.snapshot_id)
        target = None
        if checkpoint is not None:
            item = next((i for i in checkpoint.layout if i.object_id == finding.object_id), None)
            target = ResolvedTarget(manifest, checkpoint, item)
        kind = "object_comment" if target is not None and target.item is not None else "general_comment"
        record = build_record(
            manifest.job.project_id,
            revision_id=manifest.job.revision_id,
            kind=kind,
            text=f"[{finding.code}] {finding.detail}",
            severity="visual",
            snapshot_id=finding.snapshot_id if checkpoint is not None else None,
            scene_id=checkpoint.scene_id if checkpoint is not None else None,
            object_id=finding.object_id if kind == "object_comment" else None,
            target=target,
            author=author,
        )
        write_feedback(project, record)
        records.append(record)
    return records


__all__ = ["BLANK_FRACTION", "Finding", "expected_objects", "ink_fraction", "inspect_manifest", "record_findings"]
