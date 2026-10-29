"""Build render jobs, compute cache keys, launch the worker and write manifests."""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from scianim.config.loader import SpecError, format_validation_error, load_animation, load_storyboard
from scianim.families.resolve import FamilyContext, probe_environment
from scianim.planning.checks import Report
from scianim.project import Project, scene_class_name
from scianim.revisions.store import RevisionSources
from scianim_core import (
    REGISTRY_VERSION,
    AnimationSpec,
    ArtifactManifest,
    InputHashes,
    ManimSettings,
    RenderJob,
    ResolvedStyle,
    SceneTarget,
    SnapshotTarget,
    Storyboard,
    WorkerResult,
)
from scianim_core.hashing import sha256_file, sha256_json
from scianim_core.jobs import QualityProfile

WORKING_REVISION = "working"
"""Renders of the working copy. Immutable revisions have ids like `rev_0003`."""

FAMILY_ROOT_ENV = "SCIANIM_FAMILY_ROOT"
QUALITY_SCALE: dict[QualityProfile, float] = {"storyboard": 0.25, "snapshot": 0.5, "draft": 2 / 3, "final": 1.0}


@dataclass(frozen=True)
class JobSources:
    """Where a job's inputs come from: the working copy or an immutable revision."""

    revision_id: str
    animation: AnimationSpec
    storyboard: Storyboard
    style: ResolvedStyle
    animation_path: Path
    storyboard_path: Path
    scene_module: Path
    code_dir: Path
    data_paths: dict[str, Path]
    """Resolved absolute path per csv source id."""


def sources_from_report(project: Project, report: Report) -> JobSources:
    if report.animation is None or report.storyboard is None or report.style is None:
        raise SpecError(project.root, "project does not validate")
    scene_module = project.scene_module_path(report.animation)
    if not scene_module.exists():
        raise SpecError(scene_module, "scene module missing; run `scianim codegen` first")
    return JobSources(
        revision_id=WORKING_REVISION,
        animation=report.animation,
        storyboard=report.storyboard,
        style=report.style,
        animation_path=project.animation_path,
        storyboard_path=project.storyboard_path,
        scene_module=scene_module,
        code_dir=project.code_dir,
        data_paths=_csv_paths(report),
    )


def sources_from_revision(project: Project, revision: RevisionSources, report: Report) -> JobSources:
    animation = load_animation(revision.animation_path)
    if revision.storyboard_path is None:
        raise SpecError(revision.root, f"revision {revision.record.id} has no storyboard")
    storyboard = load_storyboard(revision.storyboard_path)
    scene_module = (revision.code_dir or revision.root / "code") / f"scene_{animation.id}.py"
    if not scene_module.exists():
        raise SpecError(
            revision.root,
            f"revision {revision.record.id} has no generated scene module; run codegen before creating a revision",
        )
    data_paths = _csv_paths(report)
    changed = [
        source_id
        for source_id, recorded in revision.record.hashes.data_files.items()
        if source_id in data_paths and sha256_file(data_paths[source_id]) != recorded
    ]
    if changed:
        raise SpecError(
            revision.root,
            f"data files {changed} changed since {revision.record.id}; create a new revision to render them",
        )
    return JobSources(
        revision_id=revision.record.id,
        animation=animation,
        storyboard=storyboard,
        style=revision.resolved_style,
        animation_path=revision.animation_path,
        storyboard_path=revision.storyboard_path,
        scene_module=scene_module,
        code_dir=scene_module.parent,
        data_paths=data_paths,
    )


def _csv_paths(report: Report) -> dict[str, Path]:
    assert report.animation is not None
    return {
        s.id: report.source_paths[s.id]
        for s in report.animation.sources
        if s.type == "csv" and s.id in report.source_paths
    }


def _even(value: float) -> int:
    pixels = max(2, round(value))
    return pixels if pixels % 2 == 0 else pixels + 1


VIDEO_CODECS = {"h264": "libx264", "vp9": "libvpx-vp9", "av1": "libaom-av1"}


def manim_settings(
    spec: AnimationSpec, style: ResolvedStyle, profile: QualityProfile, media_dir: str, video: bool = False
) -> ManimSettings:
    scale = QUALITY_SCALE[profile]
    return ManimSettings(
        renderer="cairo",
        pixel_width=_even(spec.output.width_px * scale),
        pixel_height=_even(spec.output.height_px * scale),
        frame_rate=spec.output.fps,
        background_color=style.tokens.palette["background"],
        media_dir=media_dir,
        equation_engine=style.tokens.typography.equation.engine,
        video_codec=VIDEO_CODECS.get(spec.output.video_codec, spec.output.video_codec),
        save_sections=video,
    )


def materialize_data_files(project: Project, sources: JobSources) -> dict[str, str]:
    """Project-relative paths for the worker; assets outside the project are copied into `.scianim/assets`."""
    result: dict[str, str] = {}
    root = project.root.resolve()
    for source_id, path in sources.data_paths.items():
        path = path.resolve()
        if root in path.parents:
            result[source_id] = path.relative_to(root).as_posix()
            continue
        target = project.assets_cache_dir / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or sha256_file(target) != sha256_file(path):
            shutil.copy2(path, target)
        result[source_id] = target.relative_to(root).as_posix()
    return result


def input_hashes(project: Project, sources: JobSources, family: FamilyContext | None) -> InputHashes:
    custom = (
        {
            p.relative_to(project.root).as_posix(): sha256_file(p)
            for p in sorted(sources.code_dir.glob("*.py"))
            if p != sources.scene_module
        }
        if sources.code_dir.is_dir()
        else {}
    )
    return InputHashes(
        animation_spec=sha256_file(sources.animation_path),
        storyboard=sha256_file(sources.storyboard_path),
        scene_code=sha256_file(sources.scene_module),
        resolved_style=sources.style.hash,
        data_files={source_id: sha256_file(path) for source_id, path in sources.data_paths.items()},
        custom_code=custom,
        lockfile=sha256_file(family.lockfile) if family and family.lockfile.exists() else None,
    )


def cache_key(
    inputs: InputHashes, manim: ManimSettings, snapshot_ids: list[str], operation: str, tool_versions: dict[str, object]
) -> str:
    payload = {
        "inputs": inputs.model_dump(mode="json"),
        "manim": manim.model_dump(mode="json"),
        "operation": operation,
        "snapshot_ids": sorted(snapshot_ids),
        "registry_version": REGISTRY_VERSION,
        "tools": {k: tool_versions.get(k) for k in ("manim", "scianim_bridge", "typst", "python")},
    }
    return f"sha256:{sha256_json(payload)}"


@dataclass
class JobPaths:
    job_dir: Path
    job_file: Path
    log_file: Path
    output_dir: Path
    manifest_file: Path
    cache_index: Path


def job_paths(project: Project, job_id: str, revision_id: str) -> JobPaths:
    job_dir = project.scianim_dir / "jobs" / job_id
    output_dir = project.renders_dir / revision_id / job_id
    return JobPaths(
        job_dir=job_dir,
        job_file=job_dir / "job.json",
        log_file=job_dir / "worker.log",
        output_dir=output_dir,
        manifest_file=output_dir / "manifest.json",
        cache_index=project.scianim_dir / "cache",
    )


def new_job_id() -> str:
    return f"job_{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:6]}"


def build_snapshot_job(
    project: Project,
    sources: JobSources,
    family: FamilyContext,
    snapshot_ids: list[str],
    profile: QualityProfile = "snapshot",
    tool_versions: dict[str, object] | None = None,
    job_id: str | None = None,
) -> tuple[RenderJob, JobPaths, InputHashes]:
    spec, storyboard, style = sources.animation, sources.storyboard, sources.style
    job_id = job_id or new_job_id()
    paths = job_paths(project, job_id, sources.revision_id)
    media_dir = (project.scianim_dir / "media" / sources.revision_id).relative_to(project.root).as_posix()
    manim = manim_settings(spec, style, profile, media_dir)
    hashes = input_hashes(project, sources, family)
    wanted = snapshot_ids or storyboard.snapshot_ids()
    unknown = sorted(set(wanted) - set(storyboard.snapshot_ids()))
    if unknown:
        raise SpecError(
            sources.storyboard_path, f"unknown snapshot id(s) {unknown}; known: {storyboard.snapshot_ids()}"
        )
    targets = {
        snap.id: SnapshotTarget(scene_id=scene.id, expected_time_seconds=snap.at_seconds, description=snap.description)
        for scene in storyboard.scenes
        for snap in scene.snapshots
        if snap.id in wanted
    }
    key = cache_key(hashes, manim, wanted, "render_snapshots", tool_versions or {})
    job = RenderJob(
        job_id=job_id,
        project_id=spec.id,
        revision_id=sources.revision_id,
        family_id=family.manifest.id,
        operation="render_snapshots",
        quality_profile=profile,
        scene_module=sources.scene_module.resolve().relative_to(project.root.resolve()).as_posix(),
        scene_class=scene_class_name(spec.id),
        snapshot_ids=wanted,
        snapshots=targets,
        output=spec.output,
        resolved_style=style,
        data_files=materialize_data_files(project, sources),
        equations=spec.equation_by_id(),
        citations={src.id: (src.citation or src.path) for src in spec.sources},
        manim=manim,
        output_dir=paths.output_dir.relative_to(project.root).as_posix(),
        cache_key=key,
    )
    return job, paths, hashes


def build_video_job(
    project: Project,
    sources: JobSources,
    family: FamilyContext,
    profile: QualityProfile = "draft",
    samples: dict[str, float] | None = None,
    tool_versions: dict[str, object] | None = None,
    job_id: str | None = None,
) -> tuple[RenderJob, JobPaths, InputHashes]:
    """A video of the whole storyboard with sections, subtitles and sampled checkpoints, at any profile:
    `storyboard` and `snapshot` for a quick look at a small size, `draft` for review, `final` for delivery."""
    spec, storyboard, style = sources.animation, sources.storyboard, sources.style
    job_id = job_id or new_job_id()
    paths = job_paths(project, job_id, sources.revision_id)
    media_dir = (project.scianim_dir / "media" / sources.revision_id).relative_to(project.root).as_posix()
    manim = manim_settings(spec, style, profile, media_dir, video=True)
    hashes = input_hashes(project, sources, family)
    targets = {
        snap.id: SnapshotTarget(scene_id=scene.id, expected_time_seconds=snap.at_seconds, description=snap.description)
        for scene in storyboard.scenes
        for snap in scene.snapshots
    }
    scenes = [
        SceneTarget(scene_id=s.id, start_seconds=s.start_seconds, end_seconds=s.end_seconds) for s in storyboard.scenes
    ]
    extra = dict(samples or {})
    for sample_id, seconds in extra.items():
        if sample_id in targets:
            raise SpecError(sources.storyboard_path, f"sample id '{sample_id}' collides with a storyboard snapshot")
        if seconds > spec.output.duration_seconds:
            raise SpecError(
                sources.storyboard_path,
                f"sample '{sample_id}' at {seconds:g}s lies beyond the {spec.output.duration_seconds:g}s output",
            )
    key = cache_key(hashes, manim, [*targets, *extra], f"render_video:{profile}", tool_versions or {})
    job = RenderJob(
        job_id=job_id,
        project_id=spec.id,
        revision_id=sources.revision_id,
        family_id=family.manifest.id,
        operation="render_video",
        quality_profile=profile,
        scene_module=sources.scene_module.resolve().relative_to(project.root.resolve()).as_posix(),
        scene_class=scene_class_name(spec.id),
        snapshot_ids=[],
        snapshots=targets,
        scenes=scenes,
        samples=extra,
        output=spec.output,
        resolved_style=style,
        data_files=materialize_data_files(project, sources),
        equations=spec.equation_by_id(),
        citations={src.id: (src.citation or src.path) for src in spec.sources},
        manim=manim,
        output_dir=paths.output_dir.relative_to(project.root).as_posix(),
        cache_key=key,
    )
    return job, paths, hashes


def cached_manifest(project: Project, key: str) -> ArtifactManifest | None:
    pointer = project.scianim_dir / "cache" / f"{key.split(':', 1)[1]}.json"
    if not pointer.exists():
        return None
    try:
        manifest_path = project.root / json.loads(pointer.read_text())["manifest"]
        manifest = ArtifactManifest.model_validate_json(manifest_path.read_text())
    except (OSError, KeyError, ValueError, ValidationError):
        return None
    for record in manifest.result.checkpoints:
        if not (project.root / record.png).exists():
            return None
    for video in manifest.result.videos:
        if not (project.root / video.path).exists():
            return None
    return manifest


def record_cache(project: Project, key: str, manifest_file: Path) -> None:
    index = project.scianim_dir / "cache"
    index.mkdir(parents=True, exist_ok=True)
    (index / f"{key.split(':', 1)[1]}.json").write_text(
        json.dumps({"manifest": manifest_file.relative_to(project.root).as_posix()}, indent=2)
    )


def worker_env(family: FamilyContext) -> dict[str, str]:
    """A minimal environment for the worker: no inherited credentials, plus the family root."""
    keep = (
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "FONTCONFIG_PATH",
        "FONTCONFIG_FILE",
        "XDG_CACHE_HOME",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
    )
    env = {k: v for k, v in os.environ.items() if k in keep}
    env["PYTHONUNBUFFERED"] = "1"
    env[FAMILY_ROOT_ENV] = str(family.root)
    return env


@dataclass
class LaunchedJob:
    """A worker process that is running (or has run) for a job."""

    job: RenderJob
    paths: JobPaths
    hashes: InputHashes
    argv: list[str]
    process: subprocess.Popen[str]
    started: float
    stdout_path: Path
    stderr_path: Path


def _check_family_env(family: FamilyContext) -> None:
    if not family.venv_python.exists():
        raise SpecError(
            family.path, f"family environment missing at {family.venv_dir}; run `scianim family env sync {family.root}`"
        )


def launch_job(
    project: Project, family: FamilyContext, job: RenderJob, paths: JobPaths, hashes: InputHashes
) -> LaunchedJob:
    """Start the worker without waiting for it. `complete_job` collects the result."""
    _check_family_env(family)
    paths.job_dir.mkdir(parents=True, exist_ok=True)
    paths.output_dir.mkdir(parents=True, exist_ok=True)
    paths.job_file.write_text(job.model_dump_json(indent=2))
    argv = [str(family.venv_python), "-m", "scianim_bridge.worker", str(paths.job_file)]
    stdout_path = paths.job_dir / "stdout.txt"
    stderr_path = paths.job_dir / "stderr.txt"
    with stdout_path.open("w", encoding="utf-8") as out_handle, stderr_path.open("w", encoding="utf-8") as err_handle:
        process = subprocess.Popen(
            argv, cwd=project.root, env=worker_env(family), stdout=out_handle, stderr=err_handle, text=True
        )
    return LaunchedJob(job, paths, hashes, argv, process, time.monotonic(), stdout_path, stderr_path)


def complete_job(project: Project, launched: LaunchedJob) -> ArtifactManifest:
    """Wait for a launched worker, write the log and the manifest, and record the cache pointer."""
    returncode = launched.process.wait()
    elapsed = time.monotonic() - launched.started
    stdout = launched.stdout_path.read_text(encoding="utf-8", errors="replace")
    stderr = launched.stderr_path.read_text(encoding="utf-8", errors="replace")
    return _finish_job(
        project, launched.job, launched.paths, launched.hashes, launched.argv, returncode, stdout, stderr, elapsed
    )


def _finish_job(
    project: Project,
    job: RenderJob,
    paths: JobPaths,
    hashes: InputHashes,
    argv: list[str],
    returncode: int,
    stdout: str,
    stderr: str,
    elapsed: float,
) -> ArtifactManifest:
    paths.log_file.write_text(
        f"$ {' '.join(argv)}\n(exit {returncode}, {elapsed:.1f}s)\n\n--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}\n"
    )
    result_file = paths.output_dir / "result.json"
    if not result_file.exists():
        tail = stderr.strip().splitlines()[-25:]
        raise SpecError(paths.log_file, "worker produced no result.json; last stderr lines:\n" + "\n".join(tail))
    try:
        worker_result = WorkerResult.model_validate_json(result_file.read_text())
    except ValidationError as exc:
        raise SpecError(
            result_file, f"worker result does not match the contract:\n{format_validation_error(exc)}"
        ) from None
    manifest = ArtifactManifest(
        created_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        job=job,
        result=worker_result,
        inputs=hashes,
    )
    paths.manifest_file.write_text(manifest.model_dump_json(indent=2))
    if worker_result.status == "succeeded":
        record_cache(project, job.cache_key, paths.manifest_file)
    return manifest


def run_job(
    project: Project, family: FamilyContext, job: RenderJob, paths: JobPaths, hashes: InputHashes, timeout: float = 1800
) -> ArtifactManifest:
    """Launch the worker and wait for it (the CLI path)."""
    launched = launch_job(project, family, job, paths, hashes)
    try:
        launched.process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        launched.process.kill()
        launched.process.wait()
        raise SpecError(paths.job_file, f"worker exceeded the timeout of {timeout:g}s and was killed") from None
    return complete_job(project, launched)


def tool_versions_for(family: FamilyContext) -> dict[str, object]:
    probe = probe_environment(family)
    return probe if probe.get("available") else {}


__all__ = [
    "FAMILY_ROOT_ENV",
    "WORKING_REVISION",
    "JobSources",
    "LaunchedJob",
    "build_snapshot_job",
    "build_video_job",
    "cache_key",
    "cached_manifest",
    "complete_job",
    "input_hashes",
    "job_paths",
    "launch_job",
    "manim_settings",
    "materialize_data_files",
    "new_job_id",
    "run_job",
    "sources_from_report",
    "sources_from_revision",
    "tool_versions_for",
]
