"""SQLite index of a workspace: projects, revisions, jobs, checkpoints and feedback.

Files remain canonical (`revision.json`, `manifest.json`, `status.json`, `feedback/*.yaml`); the index
is a cache that `rebuild()` recreates from them and `refresh_project()` updates for one project.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scianim.config.loader import SpecError, load_animation
from scianim.feedback.store import list_feedback
from scianim.project import Project
from scianim.render.manifests import (
    JobStatus,
    list_statuses,
    load_manifest,
    manifest_paths,
    manifest_relative_path,
    status_from_manifest,
)
from scianim.revisions.store import list_revisions
from scianim.workspace import scan_workspace

INDEX_VERSION = 2
"""Bump when the tables change; an index with another version is dropped and rebuilt (it is a cache)."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY, title TEXT, family_id TEXT, path TEXT, relative_path TEXT,
  has_storyboard INTEGER, groups TEXT, environment_ok INTEGER
);
CREATE TABLE IF NOT EXISTS revisions (
  project_id TEXT, id TEXT, created_at TEXT, parent TEXT, message TEXT, style_theme TEXT, style_version TEXT,
  PRIMARY KEY (project_id, id)
);
CREATE TABLE IF NOT EXISTS jobs (
  project_id TEXT, job_id TEXT PRIMARY KEY, revision_id TEXT, operation TEXT, profile TEXT, status TEXT,
  created_at TEXT, started_at TEXT, finished_at TEXT, elapsed_seconds REAL, cache_hit INTEGER,
  checkpoint_count INTEGER, manifest TEXT, output_dir TEXT, error TEXT, submitted_by TEXT, snapshot_ids TEXT
);
CREATE TABLE IF NOT EXISTS checkpoints (
  project_id TEXT, job_id TEXT, snapshot_id TEXT, scene_id TEXT, kind TEXT, png TEXT, sha256 TEXT, fidelity TEXT,
  width_px INTEGER, height_px INTEGER, warning_count INTEGER, expected_time_seconds REAL,
  PRIMARY KEY (project_id, job_id, snapshot_id)
);
CREATE TABLE IF NOT EXISTS feedback (
  project_id TEXT, id TEXT PRIMARY KEY, created_at TEXT, revision_id TEXT, job_id TEXT, scene_id TEXT, snapshot_id TEXT,
  object_id TEXT, kind TEXT, severity TEXT, status TEXT, text TEXT, image_sha256 TEXT, author TEXT
);
"""


@dataclass
class IndexedProject:
    id: str
    title: str
    family_id: str
    path: Path
    relative_path: str
    has_storyboard: bool
    groups: list[str] = field(default_factory=list)
    environment_ok: bool = False


class Index:
    def __init__(self, workspace_root: Path, path: Path | None = None) -> None:
        self.workspace_root = workspace_root.resolve()
        self.path = path or self.workspace_root / ".scianim" / "index.sqlite"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            version = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
            if version != INDEX_VERSION:
                tables = [row[0] for row in self._conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
                for table in tables:
                    self._conn.execute(f"DROP TABLE IF EXISTS {table}")
                self._conn.execute(f"PRAGMA user_version = {INDEX_VERSION}")
            self._conn.executescript(SCHEMA)
        self.problems: list[str] = []
        self.project_problems: dict[str, list[str]] = {}
        self.families: list[dict[str, Any]] = []

    # --- rebuilding --------------------------------------------------------------------------
    def rebuild(self) -> None:
        scan = scan_workspace(self.workspace_root)
        self.problems = list(scan.problems)
        self.families = [
            {
                "id": family.id,
                "path": str(family.path),
                "relative_path": family.path.relative_to(self.workspace_root).as_posix(),
                "environment_ok": family.has_environment,
                "has_lockfile": family.has_lockfile,
                "projects": [node.id for node in family.projects],
            }
            for family in scan.families
        ]
        seen: set[str] = set()
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM projects")
            for family in scan.families:
                for node in family.projects:
                    if node.id in seen:
                        continue  # scan_workspace already reported the duplicate
                    seen.add(node.id)
                    self._conn.execute(
                        "INSERT INTO projects VALUES (?,?,?,?,?,?,?,?)",
                        (
                            node.id,
                            node.title,
                            family.id,
                            str(node.path),
                            node.path.relative_to(self.workspace_root).as_posix(),
                            int(node.has_storyboard),
                            json.dumps(node.groups),
                            int(family.has_environment),
                        ),
                    )
            for table in ("revisions", "jobs", "checkpoints", "feedback"):
                self._conn.execute(f"DELETE FROM {table} WHERE project_id NOT IN (SELECT id FROM projects)")
        for project_id in seen:
            self.refresh_project(project_id)

    def refresh_project(self, project_id: str) -> None:
        """Re-read one project's revisions, jobs, checkpoints and feedback from disk."""
        indexed = self.project(project_id)
        if indexed is None:
            return
        project = Project(indexed.path)
        try:
            spec = load_animation(project.animation_path)
            title, has_storyboard = spec.title, project.storyboard_path.exists()
        except SpecError:
            title, has_storyboard = indexed.title, indexed.has_storyboard
        revisions = list_revisions(project)
        problems: list[str] = []
        manifests = {}
        for path in manifest_paths(project):
            manifest = load_manifest(path)
            if manifest is None:
                problems.append(
                    f"{path.relative_to(project.root).as_posix()}: unreadable manifest (written by an older contract?)"
                )
            else:
                manifests[manifest.job.job_id] = manifest
        statuses = list_statuses(project)
        feedback = list_feedback(project)
        self.project_problems[project_id] = problems
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE projects SET title = ?, has_storyboard = ? WHERE id = ?",
                (title, int(has_storyboard), project_id),
            )
            for table in ("revisions", "jobs", "checkpoints", "feedback"):
                self._conn.execute(f"DELETE FROM {table} WHERE project_id = ?", (project_id,))
            for rev in revisions:
                self._conn.execute(
                    "INSERT INTO revisions VALUES (?,?,?,?,?,?,?)",
                    (project_id, rev.id, rev.created_at, rev.parent, rev.message, rev.style_theme, rev.style_version),
                )
            for job_id in sorted(set(manifests) | set(statuses)):
                manifest = manifests.get(job_id)
                status = statuses.get(job_id)
                self._conn.execute(
                    "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    _job_row(project_id, project, manifest, status),
                )
                if manifest is not None:
                    for rec in manifest.result.checkpoints:
                        self._conn.execute(
                            "INSERT INTO checkpoints VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                            (
                                project_id,
                                job_id,
                                rec.snapshot_id,
                                rec.scene_id,
                                rec.kind,
                                rec.png,
                                rec.sha256,
                                rec.fidelity,
                                rec.width_px,
                                rec.height_px,
                                len(rec.warnings),
                                rec.expected_time_seconds,
                            ),
                        )
            for fb in feedback:
                self._conn.execute(
                    "INSERT INTO feedback VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        project_id,
                        fb.id,
                        fb.created_at,
                        fb.revision_id,
                        fb.job_id,
                        fb.scene_id,
                        fb.snapshot_id,
                        fb.object_id,
                        fb.kind,
                        fb.severity,
                        fb.status,
                        fb.text,
                        fb.image_sha256,
                        fb.author,
                    ),
                )

    # --- queries -----------------------------------------------------------------------------
    def projects(self) -> list[IndexedProject]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM projects ORDER BY family_id, id").fetchall()
        return [_project(row) for row in rows]

    def project(self, project_id: str) -> IndexedProject | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return _project(row) if row else None

    def revisions(self, project_id: str) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM revisions WHERE project_id = ? ORDER BY id", (project_id,))

    def jobs(self, project_id: str, limit: int = 100) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM jobs WHERE project_id = ? ORDER BY job_id DESC LIMIT ?", (project_id, limit))

    def job(self, project_id: str, job_id: str) -> dict[str, Any] | None:
        rows = self._rows("SELECT * FROM jobs WHERE project_id = ? AND job_id = ?", (project_id, job_id))
        return rows[0] if rows else None

    def checkpoints(self, project_id: str, job_id: str) -> list[dict[str, Any]]:
        return self._rows(
            "SELECT * FROM checkpoints WHERE project_id = ? AND job_id = ? ORDER BY expected_time_seconds",
            (project_id, job_id),
        )

    def feedback(self, project_id: str, **filters: str | None) -> list[dict[str, Any]]:
        clauses, values = ["project_id = ?"], [project_id]
        for column, value in filters.items():
            if value is not None and column in {
                "revision_id",
                "snapshot_id",
                "scene_id",
                "object_id",
                "kind",
                "job_id",
            }:
                clauses.append(f"{column} = ?")
                values.append(value)
        return self._rows(f"SELECT * FROM feedback WHERE {' AND '.join(clauses)} ORDER BY id", values)

    def counts(self, project_id: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for table in ("revisions", "jobs", "feedback"):
            with self._lock:
                row = self._conn.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id = ?", (project_id,)).fetchone()
            out[table] = int(row[0])
        return out

    def _rows(self, sql: str, params: Any) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(sql, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def _project(row: sqlite3.Row) -> IndexedProject:
    return IndexedProject(
        id=row["id"],
        title=row["title"],
        family_id=row["family_id"],
        path=Path(row["path"]),
        relative_path=row["relative_path"],
        has_storyboard=bool(row["has_storyboard"]),
        groups=json.loads(row["groups"] or "[]"),
        environment_ok=bool(row["environment_ok"]),
    )


def _job_row(project_id: str, project: Project, manifest: Any, status: JobStatus | None) -> tuple:
    if manifest is not None:
        lifecycle = status_from_manifest(manifest)
        if status is not None and status.status == "canceled":
            lifecycle = "canceled"
        return (
            project_id,
            manifest.job.job_id,
            manifest.job.revision_id,
            manifest.job.operation,
            manifest.job.quality_profile,
            lifecycle,
            status.created_at if status else manifest.created_at,
            status.started_at if status else None,
            status.finished_at if status else manifest.created_at,
            manifest.result.elapsed_seconds,
            int(manifest.cache_hit or bool(status and status.cache_hit)),
            len(manifest.result.checkpoints),
            manifest_relative_path(project, manifest),
            manifest.job.output_dir,
            "\n".join(manifest.result.errors) or (status.error if status else None),
            status.submitted_by if status else "cli",
            json.dumps(manifest.job.snapshot_ids),
        )
    assert status is not None
    return (
        project_id,
        status.job_id,
        status.revision_id,
        status.operation,
        status.profile,
        status.status,
        status.created_at,
        status.started_at,
        status.finished_at,
        None,
        int(status.cache_hit),
        0,
        status.manifest,
        None,
        status.error,
        status.submitted_by,
        json.dumps(status.snapshot_ids),
    )


__all__ = ["Index", "IndexedProject"]
