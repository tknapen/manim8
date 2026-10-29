"""`feedback/<id>.yaml`: one typed record per file, written by the CLI or the review server.

The UI and the agent read and write the same files; the SQLite index only caches them.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError
from ruamel.yaml import YAML

from scianim.config.loader import SpecError, format_validation_error, load_yaml
from scianim.project import Project
from scianim.render.manifests import manifest_for_ref
from scianim_core import ArtifactManifest, CheckpointRecord, FeedbackRecord, LayoutItem
from scianim_core.feedback import FeedbackKind, Region, ReviewStatus, Severity


def _dumper() -> YAML:
    """A fresh round-trip dumper per write: the review server writes records from several threads, and a
    ruamel `YAML` object is not safe to share between them."""
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


def new_feedback_id(now: dt.datetime | None = None) -> str:
    stamp = (now or dt.datetime.now(dt.UTC)).strftime("%Y%m%dT%H%M%S")
    return f"fb_{stamp}_{uuid.uuid4().hex[:6]}"


def feedback_path(project: Project, record_id: str) -> Path:
    return project.feedback_dir / f"{record_id}.yaml"


def write_feedback(project: Project, record: FeedbackRecord) -> Path:
    project.feedback_dir.mkdir(parents=True, exist_ok=True)
    path = feedback_path(project, record.id)
    if path.exists():
        raise SpecError(path, "feedback record already exists; records are write-once")
    with path.open("w", encoding="utf-8") as handle:
        _dumper().dump(record.model_dump(mode="json", exclude_none=True), handle)
    return path


def read_feedback(path: Path) -> FeedbackRecord:
    data = load_yaml(path)
    try:
        return FeedbackRecord.model_validate(data)
    except ValidationError as exc:
        raise SpecError(path, f"invalid feedback record:\n{format_validation_error(exc)}") from None


def list_feedback(project: Project, strict: bool = False) -> list[FeedbackRecord]:
    """Records in creation order (the id carries the timestamp). Invalid files are skipped unless strict."""
    if not project.feedback_dir.is_dir():
        return []
    records: list[FeedbackRecord] = []
    for path in sorted(project.feedback_dir.glob("fb_*.yaml")):
        try:
            records.append(read_feedback(path))
        except SpecError:
            if strict:
                raise
    return records


@dataclass(frozen=True)
class ResolvedTarget:
    """What a comment or status refers to, resolved from a render manifest."""

    manifest: ArtifactManifest
    checkpoint: CheckpointRecord
    item: LayoutItem | None

    @property
    def region(self) -> Region | None:
        if self.item is None:
            return None
        b = self.item.bbox
        x, y = max(0.0, b.x), max(0.0, b.y)
        return Region(x=x, y=y, width=max(1e-6, min(1 - x, b.x2 - x)), height=max(1e-6, min(1 - y, b.y2 - y)))


def resolve_target(
    project: Project, revision_id: str, snapshot_id: str, object_id: str | None = None, job_id: str | None = None
) -> ResolvedTarget:
    """Find the displayed checkpoint (and object) in the job's manifest, else the revision's latest render."""
    manifest = manifest_for_ref(project, job_id) if job_id else manifest_for_ref(project, revision_id)
    if manifest is None:
        where = f"job {job_id}" if job_id else f"revision {revision_id}"
        raise SpecError(project.renders_dir, f"no render manifest for {where}; run `scianim snapshot` first")
    if manifest.job.revision_id != revision_id:
        raise SpecError(
            project.renders_dir, f"job {manifest.job.job_id} rendered {manifest.job.revision_id}, not {revision_id}"
        )
    if manifest.result.status != "succeeded":
        raise SpecError(
            project.renders_dir,
            f"job {manifest.job.job_id} {manifest.result.status}; feedback needs a succeeded render",
        )
    checkpoint = next((c for c in manifest.result.checkpoints if c.snapshot_id == snapshot_id), None)
    if checkpoint is None:
        known = [c.snapshot_id for c in manifest.result.checkpoints]
        raise SpecError(
            project.renders_dir, f"job {manifest.job.job_id} has no checkpoint '{snapshot_id}'; it has {known}"
        )
    item = None
    if object_id is not None:
        item = next((i for i in checkpoint.layout if i.object_id == object_id), None)
        if item is None:
            known = [i.object_id for i in checkpoint.layout]
            raise SpecError(
                project.renders_dir,
                f"checkpoint '{snapshot_id}' has no object '{object_id}' in its layout; it has {known}",
            )
    return ResolvedTarget(manifest, checkpoint, item)


def build_record(
    project_id: str,
    *,
    revision_id: str,
    kind: FeedbackKind,
    text: str = "",
    severity: Severity = "visual",
    status: ReviewStatus | None = None,
    snapshot_id: str | None = None,
    scene_id: str | None = None,
    object_id: str | None = None,
    region: Region | None = None,
    target: ResolvedTarget | None = None,
    author: str | None = None,
    time_seconds: float | None = None,
) -> FeedbackRecord:
    """Assemble a record; a resolved target supplies the scene, the image hash and dimensions."""
    job_id = None
    image_sha256 = width = height = None
    if target is not None:
        job_id = target.manifest.job.job_id
        scene_id = scene_id or target.checkpoint.scene_id
        snapshot_id = snapshot_id or target.checkpoint.snapshot_id
        image_sha256 = target.checkpoint.sha256
        width, height = target.checkpoint.width_px, target.checkpoint.height_px
        if region is None and target.item is not None:
            region = target.region
    return FeedbackRecord(
        id=new_feedback_id(),
        created_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        author=author,
        project_id=project_id,
        revision_id=revision_id,
        job_id=job_id,
        scene_id=scene_id,
        snapshot_id=snapshot_id,
        object_id=object_id,
        kind=kind,
        region=region,
        text=text,
        severity=severity,
        status=status,
        image_sha256=image_sha256,
        image_width_px=width,
        image_height_px=height,
        time_seconds=time_seconds,
    )


__all__ = [
    "ResolvedTarget",
    "build_record",
    "feedback_path",
    "list_feedback",
    "new_feedback_id",
    "read_feedback",
    "resolve_target",
    "write_feedback",
]
