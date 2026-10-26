"""The review API (spec section 14.1) and the static UI.

Every write goes to the same files the CLI uses; the SQLite index is refreshed after each write.
Artifacts are served only from a project's `renders/` and `.scianim/compare/` directories, by
validated ids; no request can name an arbitrary path or run code.
"""

from __future__ import annotations

import json
import mimetypes
import re
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from scianim import __version__
from scianim.agent.proposals import list_applied, list_pending
from scianim.compare import compare_dir, compare_manifests
from scianim.config.loader import SpecError, format_validation_error
from scianim.feedback.store import build_record, list_feedback, resolve_target, write_feedback
from scianim.index import Index, IndexedProject
from scianim.planning.checks import validate_project
from scianim.project import Project
from scianim.render.manifests import (
    JOB_ID_PATTERN,
    REVISION_REF_PATTERN,
    find_manifest,
    job_log_text,
    list_manifests,
    manifest_for_ref,
)
from scianim.server.runner import JobRequest, JobRunner
from scianim_core import ArtifactManifest, CheckpointRecord
from scianim_core.feedback import FeedbackKind, Region, ReviewStatus, Severity

STATIC_DIR = Path(__file__).parent / "static"
SLUG = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
PROFILES = ("storyboard", "snapshot", "draft", "final")


class JobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["render_snapshots", "render_video"] = "render_snapshots"
    revision_id: str = Field(default="working", pattern=REVISION_REF_PATTERN.pattern)
    snapshot_ids: list[str] = []
    profile: Literal["storyboard", "snapshot", "draft", "final"] = "snapshot"
    no_cache: bool = False
    samples: dict[str, float] = {}
    """Extra video frames to extract, id -> seconds (video jobs)."""


class FeedbackCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision_id: str = Field(default="working", pattern=REVISION_REF_PATTERN.pattern)
    kind: FeedbackKind
    text: str = ""
    severity: Severity = "visual"
    status: ReviewStatus | None = None
    snapshot_id: str | None = None
    scene_id: str | None = None
    object_id: str | None = None
    region: Region | None = None
    job_id: str | None = Field(default=None, pattern=JOB_ID_PATTERN.pattern)
    author: str | None = None
    time_seconds: float | None = None


def create_app(workspace_root: Path, index: Index | None = None) -> FastAPI:
    workspace_root = workspace_root.resolve()
    index = index or Index(workspace_root)
    index.rebuild()
    runner = JobRunner(index)
    app = FastAPI(title="SciAnim Studio review API", version=__version__)
    app.state.index = index
    app.state.runner = runner
    app.state.workspace_root = workspace_root

    # --- helpers ----------------------------------------------------------------------------
    def project_or_404(project_id: str) -> tuple[IndexedProject, Project]:
        if not SLUG.match(project_id):
            raise HTTPException(404, "unknown project")
        indexed = index.project(project_id)
        if indexed is None:
            raise HTTPException(404, f"unknown project '{project_id}'")
        return indexed, Project(indexed.path)

    def artifact_url(project_id: str, project_relative_png: str) -> str:
        relative = project_relative_png.removeprefix("renders/")
        return f"/api/projects/{project_id}/artifacts/{relative}"

    def checkpoint_json(project_id: str, manifest: ArtifactManifest, rec: CheckpointRecord) -> dict[str, Any]:
        data = rec.model_dump(mode="json")
        data["url"] = artifact_url(project_id, rec.png)
        target = manifest.job.snapshots.get(rec.snapshot_id)
        data["description"] = target.description if target else ""
        return data

    def job_json(project_id: str, project: Project, row: dict[str, Any]) -> dict[str, Any]:
        data = dict(row)
        data["cache_hit"] = bool(data.get("cache_hit"))
        data["snapshot_ids"] = json.loads(data.get("snapshot_ids") or "[]")
        data["checkpoints"] = []
        manifest_rel = data.get("manifest")
        if manifest_rel:
            manifest_path = project.root / manifest_rel
            manifest = find_manifest(project, Path(manifest_rel).parent.name) if manifest_path.exists() else None
            if manifest is not None:
                data["checkpoints"] = [checkpoint_json(project_id, manifest, c) for c in manifest.result.checkpoints]
                data["review_sheet_url"] = artifact_url(project_id, f"{manifest.job.output_dir}/review_sheet.html")
                data["manifest_url"] = artifact_url(project_id, manifest_rel)
                data["worker_warnings"] = manifest.result.warnings
                data["tool_versions"] = (
                    manifest.result.tool_versions.model_dump() if manifest.result.tool_versions else None
                )
                data["pixel_width"] = manifest.job.manim.pixel_width
                data["pixel_height"] = manifest.job.manim.pixel_height
                data["videos"] = [
                    {**v.model_dump(mode="json"), "url": artifact_url(project_id, v.path)}
                    for v in manifest.result.videos
                ]
                data["sections"] = [
                    {**sec.model_dump(mode="json"), "url": artifact_url(project_id, sec.video) if sec.video else None}
                    for sec in manifest.result.sections
                ]
                data["subtitles_url"] = (
                    artifact_url(project_id, manifest.result.subtitles) if manifest.result.subtitles else None
                )
                data["timing"] = (
                    {
                        **manifest.result.timing.model_dump(mode="json"),
                        "within_tolerance": manifest.result.timing.within_tolerance,
                        "problems": manifest.result.timing.problems(),
                    }
                    if manifest.result.timing
                    else None
                )
        return data

    def project_detail(indexed: IndexedProject, project: Project) -> dict[str, Any]:
        report = validate_project(project, require_family=True)
        animation = report.animation
        storyboard = report.storyboard
        detail: dict[str, Any] = {
            "id": indexed.id,
            "title": animation.title if animation else indexed.title,
            "family_id": indexed.family_id,
            "relative_path": indexed.relative_path,
            "groups": indexed.groups,
            "environment_ok": indexed.environment_ok,
            "validation": {
                "ok": report.ok,
                "errors": report.errors,
                "warnings": report.warnings,
                "notices": report.notices,
            },
            "animation": None,
            "storyboard": None,
            "style": None,
            "revisions": index.revisions(indexed.id),
            "jobs": [job_json(indexed.id, project, row) for row in index.jobs(indexed.id, limit=25)],
            "counts": index.counts(indexed.id),
            "latest_render": {},
            "problems": index.project_problems.get(indexed.id, []),
        }
        if animation is not None:
            detail["animation"] = {
                "id": animation.id,
                "title": animation.title,
                "objective": animation.objective,
                "audience": animation.audience,
                "output": animation.output.model_dump(mode="json"),
                "style": {"name": animation.style.name, "version": animation.style.version},
                "sources": [s.model_dump(mode="json") for s in animation.sources],
                "equations": [e.model_dump(mode="json") for e in animation.equations],
                "scientific_constraints": [c.model_dump(mode="json") for c in animation.scientific_constraints],
                "timeline": [m.model_dump(mode="json") for m in animation.timeline],
            }
        if storyboard is not None:
            detail["storyboard"] = {
                "project_id": storyboard.project_id,
                "total_end_seconds": storyboard.total_end_seconds,
                "scenes": [
                    {
                        "id": scene.id,
                        "title": scene.title,
                        "start_seconds": scene.start_seconds,
                        "end_seconds": scene.end_seconds,
                        "purpose": scene.purpose,
                        "narration": scene.narration.plain_text if scene.narration else None,
                        "objects": [
                            {
                                "id": o.id,
                                "kind": o.kind,
                                "style_role": o.style_role,
                                "reveal_at_seconds": o.reveal_at_seconds,
                            }
                            for o in scene.objects
                        ],
                        "snapshots": [s.model_dump(mode="json") for s in scene.snapshots],
                    }
                    for scene in storyboard.scenes
                ],
            }
        if report.style is not None:
            detail["style"] = {
                "theme": report.style.theme,
                "version": report.style.theme_version,
                "hash": report.style.hash,
                "layers": report.style.layers,
            }
        for manifest in list_manifests(project):
            if manifest.result.status == "succeeded" and manifest.job.operation == "render_snapshots":
                detail["latest_render"][manifest.job.revision_id] = manifest.job.job_id
            if manifest.result.status == "succeeded" and manifest.job.operation == "render_video":
                detail.setdefault("latest_video", {})[manifest.job.revision_id] = manifest.job.job_id
        detail.setdefault("latest_video", {})
        return detail

    def comparison_json(project_id: str, ref_a: str, ref_b: str, project: Project) -> dict[str, Any]:
        manifest_a, manifest_b = manifest_for_ref(project, ref_a), manifest_for_ref(project, ref_b)
        if manifest_a is None or manifest_b is None:
            missing = ref_a if manifest_a is None else ref_b
            raise HTTPException(404, f"no succeeded render for '{missing}' (give a job id or a revision id)")
        out_dir = compare_dir(project, manifest_a.job.job_id, manifest_b.job.job_id)
        results = compare_manifests(project, manifest_a, manifest_b, out_dir)
        snapshots = []
        for item in results:
            entry: dict[str, Any] = {
                "snapshot_id": item.snapshot_id,
                "identical": item.identical,
                "pixel_diff_fraction": item.pixel_diff_fraction,
                "note": item.note,
                "a": checkpoint_json(project_id, manifest_a, item.a) if item.a else None,
                "b": checkpoint_json(project_id, manifest_b, item.b) if item.b else None,
                "diff_url": (
                    f"/api/projects/{project_id}/compare/{manifest_a.job.job_id}/{manifest_b.job.job_id}/{item.snapshot_id}.png"
                    if item.diff_png is not None and item.diff_png.exists()
                    else None
                ),
                "changes": [
                    {
                        "object_id": c.object_id,
                        "kind": c.kind,
                        "change": c.change,
                        "detail": c.detail,
                        "before": c.before.model_dump() if c.before else None,
                        "after": c.after.model_dump() if c.after else None,
                    }
                    for c in item.changes
                ],
            }
            snapshots.append(entry)
        return {
            "a": {"job_id": manifest_a.job.job_id, "revision_id": manifest_a.job.revision_id},
            "b": {"job_id": manifest_b.job.job_id, "revision_id": manifest_b.job.revision_id},
            "snapshots": snapshots,
        }

    # --- workspace and projects -------------------------------------------------------------
    @app.get("/api/workspace")
    def get_workspace() -> dict[str, Any]:
        index.rebuild()
        return {
            "root": str(workspace_root),
            "families": index.families,
            "projects": [
                {
                    "id": p.id,
                    "title": p.title,
                    "family_id": p.family_id,
                    "relative_path": p.relative_path,
                    "groups": p.groups,
                    "has_storyboard": p.has_storyboard,
                    "environment_ok": p.environment_ok,
                }
                for p in index.projects()
            ],
            "problems": index.problems,
            "version": __version__,
        }

    @app.get("/api/projects")
    def get_projects() -> list[dict[str, Any]]:
        return [
            {
                "id": p.id,
                "title": p.title,
                "family_id": p.family_id,
                "relative_path": p.relative_path,
                "groups": p.groups,
                "has_storyboard": p.has_storyboard,
                "environment_ok": p.environment_ok,
                **index.counts(p.id),
            }
            for p in index.projects()
        ]

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str) -> dict[str, Any]:
        indexed, project = project_or_404(project_id)
        index.refresh_project(project_id)
        return project_detail(indexed, project)

    @app.get("/api/projects/{project_id}/revisions")
    def get_revisions(project_id: str) -> list[dict[str, Any]]:
        project_or_404(project_id)
        index.refresh_project(project_id)
        return index.revisions(project_id)

    # --- jobs -------------------------------------------------------------------------------
    @app.get("/api/projects/{project_id}/jobs")
    def get_jobs(project_id: str) -> list[dict[str, Any]]:
        _, project = project_or_404(project_id)
        index.refresh_project(project_id)
        return [job_json(project_id, project, row) for row in index.jobs(project_id)]

    @app.post("/api/projects/{project_id}/jobs", status_code=202)
    def post_job(project_id: str, body: JobCreate) -> dict[str, Any]:
        _, project = project_or_404(project_id)
        for snapshot_id in [*body.snapshot_ids, *body.samples]:
            if not SLUG.match(snapshot_id):
                raise HTTPException(422, f"invalid snapshot id '{snapshot_id}'")
        if body.operation == "render_video" and body.profile not in ("draft", "final"):
            raise HTTPException(422, "a video job needs profile draft or final")
        status = runner.submit(
            project,
            JobRequest(
                project_id,
                body.revision_id,
                list(body.snapshot_ids),
                body.profile,
                body.no_cache,
                body.operation,
                dict(body.samples),
            ),
        )
        return status.model_dump(mode="json")

    @app.get("/api/projects/{project_id}/jobs/{job_id}")
    def get_job(project_id: str, job_id: str) -> dict[str, Any]:
        _, project = project_or_404(project_id)
        if not JOB_ID_PATTERN.match(job_id):
            raise HTTPException(404, "unknown job")
        index.refresh_project(project_id)
        row = index.job(project_id, job_id)
        if row is None:
            raise HTTPException(404, f"unknown job '{job_id}'")
        return job_json(project_id, project, row)

    @app.get("/api/projects/{project_id}/jobs/{job_id}/log", response_class=PlainTextResponse)
    def get_job_log(project_id: str, job_id: str) -> str:
        _, project = project_or_404(project_id)
        text = job_log_text(project, job_id)
        if text is None:
            live = runner.status(job_id)
            if live is not None and live.status in ("queued", "preparing", "running"):
                return f"job {job_id} is {live.status}; the worker log appears when it finishes\n"
            raise HTTPException(404, "no log for this job")
        return text

    @app.post("/api/projects/{project_id}/jobs/{job_id}/cancel")
    def cancel_job(project_id: str, job_id: str) -> dict[str, Any]:
        project_or_404(project_id)
        status = runner.cancel(job_id)
        if status is None:
            raise HTTPException(404, "the job is not managed by this server (finished jobs cannot be canceled)")
        return status.model_dump(mode="json")

    # --- artifacts ---------------------------------------------------------------------------
    @app.get("/api/projects/{project_id}/artifacts/{path:path}")
    def get_artifact(project_id: str, path: str) -> FileResponse:
        _, project = project_or_404(project_id)
        renders = project.renders_dir.resolve()
        candidate = (renders / path).resolve()
        if renders not in candidate.parents or not candidate.is_file():
            raise HTTPException(404, "no such artifact")
        if candidate.suffix not in (".png", ".html", ".json", ".log", ".txt", ".mp4", ".srt"):
            raise HTTPException(404, "no such artifact")
        media_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        return FileResponse(candidate, media_type=media_type)

    # --- feedback ---------------------------------------------------------------------------
    @app.get("/api/projects/{project_id}/feedback")
    def get_feedback(
        project_id: str,
        revision_id: str | None = Query(default=None),
        snapshot_id: str | None = Query(default=None),
        scene_id: str | None = Query(default=None),
        object_id: str | None = Query(default=None),
        kind: str | None = Query(default=None),
    ) -> list[dict[str, Any]]:
        _, project = project_or_404(project_id)
        records = list_feedback(project)
        filters = {
            "revision_id": revision_id,
            "snapshot_id": snapshot_id,
            "scene_id": scene_id,
            "object_id": object_id,
            "kind": kind,
        }
        return [
            r.model_dump(mode="json")
            for r in records
            if all(value is None or getattr(r, key) == value for key, value in filters.items())
        ]

    @app.get("/api/projects/{project_id}/feedback/{feedback_id}")
    def get_feedback_record(project_id: str, feedback_id: str) -> dict[str, Any]:
        _, project = project_or_404(project_id)
        for record in list_feedback(project):
            if record.id == feedback_id:
                return record.model_dump(mode="json")
        raise HTTPException(404, f"unknown feedback record '{feedback_id}'")

    @app.post("/api/projects/{project_id}/feedback", status_code=201)
    def post_feedback(project_id: str, body: FeedbackCreate) -> dict[str, Any]:
        _, project = project_or_404(project_id)
        for value in (body.snapshot_id, body.scene_id, body.object_id):
            if value is not None and not SLUG.match(value):
                raise HTTPException(422, f"invalid id '{value}'")
        target = None
        try:
            if body.snapshot_id is not None and (body.kind != "general_comment" or body.job_id):
                target = resolve_target(project, body.revision_id, body.snapshot_id, body.object_id, body.job_id)
            record = build_record(
                project_id,
                revision_id=body.revision_id,
                kind=body.kind,
                text=body.text,
                severity=body.severity,
                status=body.status,
                snapshot_id=body.snapshot_id,
                scene_id=body.scene_id,
                object_id=body.object_id,
                region=body.region,
                target=target,
                author=body.author,
                time_seconds=body.time_seconds,
            )
            path = write_feedback(project, record)
        except SpecError as exc:
            raise HTTPException(400, exc.message) from None
        except ValidationError as exc:
            raise HTTPException(422, format_validation_error(exc)) from None
        index.refresh_project(project_id)
        data = record.model_dump(mode="json")
        data["path"] = path.relative_to(project.root).as_posix()
        return data

    # --- proposals (read-only: applying runs through the CLI, where the agent works) -------------
    @app.get("/api/projects/{project_id}/proposals")
    def get_proposals(project_id: str) -> dict[str, Any]:
        _, project = project_or_404(project_id)
        applied = list_applied(project)
        return {
            "pending": [p.name for p in list_pending(project)],
            "applied": [
                {
                    "id": a.proposal.id,
                    "kind": a.proposal.kind,
                    "author": a.proposal.author,
                    "summary": a.proposal.summary,
                    "rationale": a.proposal.rationale,
                    "applied_at": a.applied_at,
                    "latest_revision_before": a.latest_revision_before,
                    "scientific_review_required": a.scientific_review_required,
                    "uncertainties": a.proposal.uncertainties,
                    "claims": [c.model_dump(mode="json") for c in a.proposal.claims],
                    "in_response_to": a.proposal.in_response_to,
                    "diffs": a.diffs,
                }
                for a in applied
            ],
        }

    # --- comparison -------------------------------------------------------------------------
    @app.get("/api/projects/{project_id}/compare")
    def get_compare(project_id: str, a: str = Query(...), b: str = Query(...)) -> dict[str, Any]:
        _, project = project_or_404(project_id)
        for ref in (a, b):
            if not (JOB_ID_PATTERN.match(ref) or REVISION_REF_PATTERN.match(ref)):
                raise HTTPException(422, f"'{ref}' is neither a job id nor a revision id")
        return comparison_json(project_id, a, b, project)

    @app.get("/api/projects/{project_id}/compare/{job_a}/{job_b}/{snapshot_id}.png")
    def get_compare_image(project_id: str, job_a: str, job_b: str, snapshot_id: str) -> FileResponse:
        _, project = project_or_404(project_id)
        if not (JOB_ID_PATTERN.match(job_a) and JOB_ID_PATTERN.match(job_b) and SLUG.match(snapshot_id)):
            raise HTTPException(404, "no such comparison")
        path = compare_dir(project, job_a, job_b) / f"{snapshot_id}.png"
        if not path.is_file():
            raise HTTPException(404, "no such comparison image; request the comparison first")
        return FileResponse(path, media_type="image/png")

    # --- the UI -----------------------------------------------------------------------------
    if (STATIC_DIR / "index.html").is_file():
        if (STATIC_DIR / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False, response_class=HTMLResponse)
        def spa(full_path: str) -> HTMLResponse:
            if full_path.startswith("api/"):
                raise HTTPException(404, "unknown API route")
            return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))

    else:

        @app.get("/", include_in_schema=False, response_class=HTMLResponse)
        def no_ui() -> HTMLResponse:
            return HTMLResponse(
                "<p>The review UI is not built into this installation. The API is live under <code>/api</code> "
                "(<a href='/docs'>OpenAPI</a>). Build the UI with <code>npm run build</code> in <code>ui/</code>.</p>"
            )

    return app


__all__ = ["STATIC_DIR", "FeedbackCreate", "JobCreate", "create_app"]
