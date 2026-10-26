"""`scianim compare`: pixel and layout differences between two renders of the same snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from PIL import Image, ImageChops

from scianim.project import Project
from scianim_core import ArtifactManifest, BBox, CheckpointRecord, LayoutItem

MOVE_TOLERANCE = 0.005
"""Normalized frame fraction below which an object counts as unmoved (about 5 px at 1080p)."""
PIXEL_THRESHOLD = 12
"""Per-channel difference below which two pixels count as equal (antialiasing noise)."""

ChangeKind = Literal["moved", "resized", "text_changed", "added", "removed"]


@dataclass
class ObjectChange:
    object_id: str
    kind: str
    change: ChangeKind
    before: BBox | None = None
    after: BBox | None = None
    detail: str = ""


@dataclass
class SnapshotComparison:
    snapshot_id: str
    a: CheckpointRecord | None
    b: CheckpointRecord | None
    identical: bool = False
    pixel_diff_fraction: float | None = None
    diff_png: Path | None = None
    changes: list[ObjectChange] = field(default_factory=list)
    note: str | None = None


def diff_images(path_a: Path, path_b: Path, out: Path | None) -> tuple[float, str | None]:
    """Fraction of pixels that differ beyond the threshold; optionally writes a diff image.

    The diff image shows A faded to grey with differing pixels in red.
    """
    with Image.open(path_a) as image_a, Image.open(path_b) as image_b:
        a = image_a.convert("RGB")
        b = image_b.convert("RGB")
        note = None
        if a.size != b.size:
            note = f"sizes differ ({a.size[0]}x{a.size[1]} vs {b.size[0]}x{b.size[1]}); B was resampled to A"
            b = b.resize(a.size)
        difference = ImageChops.difference(a, b).convert("L").point(lambda v: 255 if v > PIXEL_THRESHOLD else 0)
        histogram = difference.histogram()
        changed = histogram[255]
        fraction = changed / (a.size[0] * a.size[1])
        if out is not None:
            out.parent.mkdir(parents=True, exist_ok=True)
            faded = Image.blend(a.convert("L").convert("RGB"), Image.new("RGB", a.size, (255, 255, 255)), 0.6)
            red = Image.new("RGB", a.size, (208, 52, 44))
            faded.paste(red, mask=difference)
            faded.save(out)
        return fraction, note


def layout_changes(before: list[LayoutItem], after: list[LayoutItem]) -> list[ObjectChange]:
    changes: list[ObjectChange] = []
    by_id_before = {item.object_id: item for item in before}
    by_id_after = {item.object_id: item for item in after}
    for object_id, item in by_id_before.items():
        other = by_id_after.get(object_id)
        if other is None:
            changes.append(ObjectChange(object_id, item.kind, "removed", before=item.bbox))
            continue
        dx = (other.bbox.x + other.bbox.width / 2) - (item.bbox.x + item.bbox.width / 2)
        dy = (other.bbox.y + other.bbox.height / 2) - (item.bbox.y + item.bbox.height / 2)
        dw = other.bbox.width - item.bbox.width
        dh = other.bbox.height - item.bbox.height
        if abs(dx) > MOVE_TOLERANCE or abs(dy) > MOVE_TOLERANCE:
            changes.append(
                ObjectChange(
                    object_id, item.kind, "moved", item.bbox, other.bbox, f"centre moved by ({dx:+.3f}, {dy:+.3f})"
                )
            )
        if abs(dw) > MOVE_TOLERANCE or abs(dh) > MOVE_TOLERANCE:
            changes.append(
                ObjectChange(
                    object_id, item.kind, "resized", item.bbox, other.bbox, f"size changed by ({dw:+.3f}, {dh:+.3f})"
                )
            )
        if item.text != other.text:
            changes.append(
                ObjectChange(
                    object_id, item.kind, "text_changed", item.bbox, other.bbox, f"{item.text!r} -> {other.text!r}"
                )
            )
    for object_id, other in by_id_after.items():
        if object_id not in by_id_before:
            changes.append(ObjectChange(object_id, other.kind, "added", after=other.bbox))
    return changes


def compare_manifests(
    project: Project, a: ArtifactManifest, b: ArtifactManifest, out_dir: Path | None = None
) -> list[SnapshotComparison]:
    """Compare every snapshot present in either manifest; `out_dir` receives one diff PNG per snapshot."""
    records_a = {c.snapshot_id: c for c in a.result.checkpoints}
    records_b = {c.snapshot_id: c for c in b.result.checkpoints}
    results: list[SnapshotComparison] = []
    for snapshot_id in sorted(set(records_a) | set(records_b), key=_order(a, b)):
        rec_a, rec_b = records_a.get(snapshot_id), records_b.get(snapshot_id)
        comparison = SnapshotComparison(snapshot_id, rec_a, rec_b)
        if rec_a is None or rec_b is None:
            comparison.note = "only in A" if rec_b is None else "only in B"
            results.append(comparison)
            continue
        comparison.identical = rec_a.sha256 == rec_b.sha256
        comparison.changes = layout_changes(rec_a.layout, rec_b.layout)
        if comparison.identical:
            comparison.pixel_diff_fraction = 0.0
        else:
            diff_path = out_dir / f"{snapshot_id}.png" if out_dir is not None else None
            path_a, path_b = project.root / rec_a.png, project.root / rec_b.png
            if path_a.exists() and path_b.exists():
                comparison.pixel_diff_fraction, comparison.note = diff_images(path_a, path_b, diff_path)
                comparison.diff_png = diff_path
            else:
                comparison.note = "a PNG is missing on disk; pixel diff skipped"
        results.append(comparison)
    return results


def _order(a: ArtifactManifest, b: ArtifactManifest):
    position = {c.snapshot_id: i for i, c in enumerate([*a.result.checkpoints, *b.result.checkpoints])}
    return lambda snapshot_id: position.get(snapshot_id, 1_000_000)


def compare_dir(project: Project, ref_a: str, ref_b: str) -> Path:
    return project.scianim_dir / "compare" / f"{ref_a}__{ref_b}"


__all__ = [
    "MOVE_TOLERANCE",
    "ObjectChange",
    "SnapshotComparison",
    "compare_dir",
    "compare_manifests",
    "diff_images",
    "layout_changes",
]
