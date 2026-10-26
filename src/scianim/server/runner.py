"""Non-blocking render jobs for the review server: one worker process at a time, cancelable.

The server never executes code from a request. A job request names a project, a revision and
snapshot ids; the runner validates the project, builds the typed job and launches the family
worker in a separate process exactly as the CLI does. Lifecycle goes to `status.json`, results to
`manifest.json`, and the index is refreshed on every transition.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from scianim.config.loader import SpecError
from scianim.index import Index
from scianim.planning.checks import validate_project
from scianim.project import Project
from scianim.render.jobs import (
    WORKING_REVISION,
    LaunchedJob,
    build_snapshot_job,
    cached_manifest,
    complete_job,
    launch_job,
    new_job_id,
    sources_from_report,
    sources_from_revision,
    tool_versions_for,
)
from scianim.render.manifests import JobStatus, manifest_relative_path, now_iso, write_status
from scianim.review.sheet import write_sheet
from scianim.revisions.store import load_revision

TERMINAL = frozenset({"succeeded", "failed", "canceled"})


@dataclass
class JobRequest:
    project_id: str
    revision_id: str = WORKING_REVISION
    snapshot_ids: list[str] = field(default_factory=list)
    profile: str = "snapshot"
    no_cache: bool = False


class JobRunner:
    def __init__(self, index: Index) -> None:
        self.index = index
        self._queue: queue.Queue[str] = queue.Queue()
        self._states: dict[str, JobStatus] = {}
        self._projects: dict[str, Project] = {}
        self._launched: dict[str, LaunchedJob] = {}
        self._cancel: set[str] = set()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="scianim-jobs")
        self._thread.start()

    # --- public -----------------------------------------------------------------------------
    def submit(self, project: Project, request: JobRequest) -> JobStatus:
        status = JobStatus(
            job_id=new_job_id(),
            project_id=request.project_id,
            revision_id=request.revision_id,
            profile=request.profile,
            snapshot_ids=list(request.snapshot_ids),
            no_cache=request.no_cache,
            status="queued",
            created_at=now_iso(),
            submitted_by="server",
        )
        with self._lock:
            self._states[status.job_id] = status
            self._projects[status.job_id] = project
        write_status(project, status)
        self.index.refresh_project(request.project_id)
        self._queue.put(status.job_id)
        return status

    def status(self, job_id: str) -> JobStatus | None:
        with self._lock:
            return self._states.get(job_id)

    def cancel(self, job_id: str) -> JobStatus | None:
        with self._lock:
            status = self._states.get(job_id)
            if status is None or status.status in TERMINAL:
                return status
            self._cancel.add(job_id)
            launched = self._launched.get(job_id)
        if launched is not None and launched.process.poll() is None:
            launched.process.terminate()
        if status.status == "queued":
            return self._set(job_id, status="canceled", finished_at=now_iso())
        return self.status(job_id)

    def wait(self, job_id: str, timeout: float = 600, poll: float = 0.2) -> JobStatus:
        """Block until the job reaches a terminal state (tests and scripts)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.status(job_id)
            if status is not None and status.status in TERMINAL:
                return status
            time.sleep(poll)
        raise TimeoutError(f"job {job_id} did not finish within {timeout:g}s")

    # --- internals --------------------------------------------------------------------------
    def _set(self, job_id: str, **changes: Any) -> JobStatus:
        with self._lock:
            status = self._states[job_id].model_copy(update=changes)
            self._states[job_id] = status
            project = self._projects[job_id]
        write_status(project, status)
        self.index.refresh_project(status.project_id)
        return status

    def _loop(self) -> None:
        while True:
            job_id = self._queue.get()
            if job_id in self._cancel:
                continue
            try:
                self._run(job_id)
            except SpecError as exc:
                self._set(job_id, status="failed", error=str(exc), finished_at=now_iso())
            except Exception as exc:
                self._set(job_id, status="failed", error=f"{type(exc).__name__}: {exc}", finished_at=now_iso())
            finally:
                with self._lock:
                    self._launched.pop(job_id, None)

    def _run(self, job_id: str) -> None:
        with self._lock:
            project = self._projects[job_id]
            request = self._states[job_id]
        self._set(job_id, status="preparing", started_at=now_iso())
        report = validate_project(project, require_family=True)
        if report.family is None:
            raise SpecError(project.root, "the project's family could not be resolved: " + "; ".join(report.errors))
        if request.revision_id == WORKING_REVISION and not report.ok:
            raise SpecError(project.root, "project does not validate: " + "; ".join(report.errors))
        family = report.family
        tool_versions = tool_versions_for(family)
        if not tool_versions:
            raise SpecError(
                family.path,
                f"family environment unavailable at {family.venv_dir}; run `scianim family env sync {family.root}`",
            )
        sources = (
            sources_from_revision(project, load_revision(project, request.revision_id), report)
            if request.revision_id != WORKING_REVISION
            else sources_from_report(project, report)
        )
        job, paths, hashes = build_snapshot_job(
            project,
            sources,
            family,
            list(request.snapshot_ids),
            request.profile,  # type: ignore[arg-type]
            tool_versions,
            job_id=job_id,
        )
        if not request.no_cache:
            hit = cached_manifest(project, job.cache_key)
            if hit is not None:
                self._set(
                    job_id,
                    status="succeeded",
                    finished_at=now_iso(),
                    cache_hit=True,
                    manifest=manifest_relative_path(project, hit),
                )
                return
        if job_id in self._cancel:
            self._set(job_id, status="canceled", finished_at=now_iso())
            return
        launched = launch_job(project, family, job, paths, hashes)
        with self._lock:
            self._launched[job_id] = launched
        self._set(job_id, status="running")
        while launched.process.poll() is None:
            time.sleep(0.25)
        if job_id in self._cancel:
            self._set(job_id, status="canceled", finished_at=now_iso(), error="canceled by the reviewer")
            return
        manifest = complete_job(project, launched)
        write_sheet(manifest, sources.storyboard, paths.output_dir / "review_sheet.html")
        self._set(
            job_id,
            status="succeeded" if manifest.result.status == "succeeded" else "failed",
            finished_at=now_iso(),
            manifest=manifest_relative_path(project, manifest),
            error="\n".join(manifest.result.errors) or None,
        )


__all__ = ["TERMINAL", "JobRequest", "JobRunner"]
