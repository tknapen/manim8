"""Reading render manifests (`renders/<revision>/<job>/manifest.json`) and job status files."""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from scianim.project import Project
from scianim_core import ArtifactManifest

JOB_ID_PATTERN = re.compile(r"^job_\d{8}T\d{6}_[0-9a-f]{6}$")
REVISION_REF_PATTERN = re.compile(r"^(working|rev_\d{4})$")
STATUS_FILE = "status.json"

JobLifecycle = Literal["queued", "preparing", "running", "succeeded", "failed", "canceled"]


class JobStatus(BaseModel):
    """`.scianim/jobs/<job>/status.json`: the lifecycle of a job as seen by the control plane.

    The manifest is the record of what the worker produced; this file exists so that queued,
    running and canceled jobs (which have no manifest yet, or never will) are visible too.
    """

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(pattern=JOB_ID_PATTERN.pattern)
    project_id: str
    revision_id: str = Field(pattern=REVISION_REF_PATTERN.pattern)
    operation: str = "render_snapshots"
    profile: str = "snapshot"
    snapshot_ids: list[str] = []
    no_cache: bool = False
    workers: int = 1
    status: JobLifecycle
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    manifest: str | None = None
    """Project-relative path of the manifest this job produced or reused (cache hit)."""
    cache_hit: bool = False
    submitted_by: str = "cli"


def now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def status_path(project: Project, job_id: str) -> Path:
    return project.scianim_dir / "jobs" / job_id / STATUS_FILE


def write_status(project: Project, status: JobStatus) -> Path:
    path = status_path(project, status.job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(status.model_dump_json(indent=2), encoding="utf-8")
    return path


def read_status(path: Path) -> JobStatus | None:
    try:
        return JobStatus.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError):
        return None


def list_statuses(project: Project) -> dict[str, JobStatus]:
    jobs_dir = project.scianim_dir / "jobs"
    if not jobs_dir.is_dir():
        return {}
    found: dict[str, JobStatus] = {}
    for path in sorted(jobs_dir.glob(f"job_*/{STATUS_FILE}")):
        status = read_status(path)
        if status is not None:
            found[status.job_id] = status
    return found


def manifest_paths(project: Project, revision_id: str | None = None) -> list[Path]:
    if not project.renders_dir.is_dir():
        return []
    pattern = f"{revision_id}/job_*/manifest.json" if revision_id else "*/job_*/manifest.json"
    return sorted(project.renders_dir.glob(pattern), key=lambda p: p.parent.name)


def load_manifest(path: Path) -> ArtifactManifest | None:
    try:
        return ArtifactManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError):
        return None


def list_manifests(project: Project, revision_id: str | None = None) -> list[ArtifactManifest]:
    manifests = (load_manifest(path) for path in manifest_paths(project, revision_id))
    return [m for m in manifests if m is not None]


def find_manifest(project: Project, job_id: str) -> ArtifactManifest | None:
    if not JOB_ID_PATTERN.match(job_id) or not project.renders_dir.is_dir():
        return None
    for path in project.renders_dir.glob(f"*/{job_id}/manifest.json"):
        return load_manifest(path)
    return None


def manifest_for_ref(project: Project, ref: str) -> ArtifactManifest | None:
    """A manifest by job id, or the latest succeeded manifest of a revision (`working` or `rev_NNNN`)."""
    if JOB_ID_PATTERN.match(ref):
        return find_manifest(project, ref)
    if REVISION_REF_PATTERN.match(ref):
        succeeded = [m for m in list_manifests(project, ref) if m.result.status == "succeeded"]
        return succeeded[-1] if succeeded else None
    return None


def manifest_relative_path(project: Project, manifest: ArtifactManifest) -> str:
    return f"{manifest.job.output_dir}/manifest.json"


def job_log_text(project: Project, job_id: str) -> str | None:
    path = project.scianim_dir / "jobs" / job_id / "worker.log"
    if not JOB_ID_PATTERN.match(job_id) or not path.exists():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def status_from_manifest(manifest: ArtifactManifest) -> JobLifecycle:
    return "succeeded" if manifest.result.status == "succeeded" else manifest.result.status


def dump_json(data: dict) -> str:
    return json.dumps(data, indent=2, sort_keys=True)


__all__ = [
    "JOB_ID_PATTERN",
    "REVISION_REF_PATTERN",
    "JobLifecycle",
    "JobStatus",
    "find_manifest",
    "job_log_text",
    "list_manifests",
    "list_statuses",
    "load_manifest",
    "manifest_for_ref",
    "manifest_paths",
    "manifest_relative_path",
    "now_iso",
    "read_status",
    "status_from_manifest",
    "status_path",
    "write_status",
]
