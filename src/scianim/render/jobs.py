"""Build render jobs, compute cache keys, launch the worker and write manifests."""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from scianim.config.loader import SpecError, format_validation_error
from scianim.families.resolve import FamilyContext, probe_environment, run_command
from scianim.project import Project, scene_class_name
from scianim_core import (
    REGISTRY_VERSION,
    AnimationSpec,
    ArtifactManifest,
    InputHashes,
    ManimSettings,
    RenderJob,
    ResolvedStyle,
    SnapshotTarget,
    Storyboard,
    WorkerResult,
)
from scianim_core.hashing import sha256_file, sha256_json, sha256_text
from scianim_core.jobs import QualityProfile

WORKING_REVISION = "working"
"""Revision IDs arrive with the revision store (Milestone 3). Until then every job renders the
working copy and the manifest's input hashes identify what was rendered."""

QUALITY_SCALE: dict[QualityProfile, float] = {
    "storyboard": 0.25,
    "snapshot": 0.5,
    "draft": 2 / 3,
    "final": 1.0,
}


def _even(value: float) -> int:
    pixels = max(2, round(value))
    return pixels if pixels % 2 == 0 else pixels + 1


def manim_settings(spec: AnimationSpec, style: ResolvedStyle, profile: QualityProfile, media_dir: str) -> ManimSettings:
    scale = QUALITY_SCALE[profile]
    return ManimSettings(
        renderer="cairo",
        pixel_width=_even(spec.output.width_px * scale),
        pixel_height=_even(spec.output.height_px * scale),
        frame_rate=spec.output.fps,
        background_color=style.tokens.palette["background"],
        media_dir=media_dir,
        equation_engine=style.tokens.typography.equation.engine,
    )


def input_hashes(
    project: Project,
    spec: AnimationSpec,
    style: ResolvedStyle,
    scene_module: Path,
    family: FamilyContext | None,
) -> InputHashes:
    data_files = {s.id: sha256_file(project.root / s.path) for s in spec.sources if (project.root / s.path).is_file()}
    custom = {
        str(p.relative_to(project.root)): sha256_file(p)
        for p in sorted(project.code_dir.glob("*.py"))
        if p != scene_module
    }
    return InputHashes(
        animation_spec=sha256_file(project.animation_path),
        storyboard=sha256_file(project.storyboard_path),
        scene_code=sha256_file(scene_module),
        resolved_style=style.hash,
        data_files=data_files,
        custom_code=custom,
        lockfile=sha256_file(family.lockfile) if family and family.lockfile.exists() else None,
    )


def cache_key(
    inputs: InputHashes,
    manim: ManimSettings,
    snapshot_ids: list[str],
    operation: str,
    tool_versions: dict[str, object],
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


def build_snapshot_job(
    project: Project,
    spec: AnimationSpec,
    storyboard: Storyboard,
    style: ResolvedStyle,
    family: FamilyContext,
    snapshot_ids: list[str],
    profile: QualityProfile = "snapshot",
    tool_versions: dict[str, object] | None = None,
) -> tuple[RenderJob, JobPaths, InputHashes]:
    scene_module = project.scene_module_path(spec)
    if not scene_module.exists():
        raise SpecError(scene_module, "scene module missing; run `scianim codegen` first")
    job_id = f"job_{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:6]}"
    paths = job_paths(project, job_id, WORKING_REVISION)
    media_dir = (project.scianim_dir / "media" / WORKING_REVISION).relative_to(project.root).as_posix()
    manim = manim_settings(spec, style, profile, media_dir)
    hashes = input_hashes(project, spec, style, scene_module, family)
    wanted = snapshot_ids or storyboard.snapshot_ids()
    unknown = sorted(set(wanted) - set(storyboard.snapshot_ids()))
    if unknown:
        raise SpecError(
            project.storyboard_path,
            f"unknown snapshot id(s) {unknown}; known: {storyboard.snapshot_ids()}",
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
        revision_id=WORKING_REVISION,
        family_id=family.manifest.id,
        operation="render_snapshots",
        quality_profile=profile,
        scene_module=scene_module.relative_to(project.root).as_posix(),
        scene_class=scene_class_name(spec.id),
        snapshot_ids=wanted,
        snapshots=targets,
        output=spec.output,
        resolved_style=style,
        data_files={s.id: s.path for s in spec.sources if s.type == "csv"},
        equations=spec.equation_by_id(),
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
    return manifest


def record_cache(project: Project, key: str, manifest_file: Path) -> None:
    index = project.scianim_dir / "cache"
    index.mkdir(parents=True, exist_ok=True)
    (index / f"{key.split(':', 1)[1]}.json").write_text(
        json.dumps({"manifest": manifest_file.relative_to(project.root).as_posix()}, indent=2)
    )


def worker_env() -> dict[str, str]:
    """A minimal environment for the worker: no inherited credentials."""
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
    return env


def run_job(
    project: Project,
    family: FamilyContext,
    job: RenderJob,
    paths: JobPaths,
    hashes: InputHashes,
    timeout: float = 1800,
) -> ArtifactManifest:
    if not family.venv_python.exists():
        raise SpecError(
            family.path,
            f"family environment missing at {family.venv_dir}; run `scianim family env sync {family.root}`",
        )
    paths.job_dir.mkdir(parents=True, exist_ok=True)
    paths.output_dir.mkdir(parents=True, exist_ok=True)
    paths.job_file.write_text(job.model_dump_json(indent=2))
    argv = [str(family.venv_python), "-m", "scianim_bridge.worker", str(paths.job_file)]
    result = run_command(argv, cwd=project.root, timeout=timeout, env=worker_env())
    paths.log_file.write_text(
        f"$ {' '.join(argv)}\n(exit {result.returncode}, {result.elapsed_seconds:.1f}s)\n\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}\n"
    )
    result_file = paths.output_dir / "result.json"
    if not result_file.exists():
        tail = result.stderr.strip().splitlines()[-25:]
        raise SpecError(paths.log_file, "worker produced no result.json; last stderr lines:\n" + "\n".join(tail))
    try:
        worker_result = WorkerResult.model_validate_json(result_file.read_text())
    except ValidationError as exc:
        raise SpecError(
            result_file,
            f"worker result does not match the contract:\n{format_validation_error(exc)}",
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


def tool_versions_for(family: FamilyContext) -> dict[str, object]:
    probe = probe_environment(family)
    return probe if probe.get("available") else {}


def copy_tree_if(src: Path, dst: Path) -> None:
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)


__all__ = [
    "WORKING_REVISION",
    "build_snapshot_job",
    "cache_key",
    "cached_manifest",
    "input_hashes",
    "job_paths",
    "manim_settings",
    "run_job",
    "sha256_text",
    "tool_versions_for",
]
