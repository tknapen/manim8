"""The segment store and the honesty of caches (ADR-033), without rendering."""

from __future__ import annotations

import datetime as dt

from scianim.codegen.generate import write_scene_module
from scianim.planning.checks import validate_project
from scianim.planning.dependencies import scene_fingerprints
from scianim.project import Project
from scianim.render.jobs import (
    build_video_job,
    cache_key,
    media_directory,
    segment_store_directory,
    sources_from_report,
)
from scianim.render.parallel import predicted_reuse
from scianim_core import ArtifactManifest, PlayRecord, WorkerResult

TOOLS = {"manim": "0.22.0", "python": "3.12", "bridge_fingerprint": "f" * 64}


def _prepared(project: Project):
    report = validate_project(project, require_family=True)
    assert report.animation and report.storyboard and report.style and report.family
    write_scene_module(report.animation, report.storyboard, report.style, project.scene_module_path(report.animation))
    return validate_project(project, require_family=True)


def _fingerprints(report, style_hash: str | None = None) -> dict[str, str]:
    return scene_fingerprints(
        report.animation,
        report.storyboard,
        style_hash=style_hash or report.style.hash,
        data_hashes={"responses": "a" * 64},
        custom_hashes={},
    )


def test_scene_fingerprints_change_with_what_a_scene_shows(project_copy: Project) -> None:
    report = _prepared(project_copy)
    before = _fingerprints(report)
    assert list(before) == ["excitation", "normalization"]
    # A narration edit in the second scene changes that scene only.
    text = project_copy.storyboard_path.read_text()
    second = text.index("id: normalization")
    marker = text.index("text:", second)
    project_copy.storyboard_path.write_text(text[: marker + 5] + " Now, " + text[marker + 5 :].lstrip())
    edited = _fingerprints(validate_project(project_copy, require_family=True))
    assert edited["excitation"] == before["excitation"] and edited["normalization"] != before["normalization"]
    # The style is part of every scene's pictures.
    restyled = _fingerprints(report, style_hash="sha256:" + "0" * 64)
    assert all(restyled[s] != before[s] for s in before)
    # So is the data a scene binds, and only where it binds it.
    other_data = scene_fingerprints(
        report.animation,
        report.storyboard,
        style_hash=report.style.hash,
        data_hashes={"responses": "b" * 64},
        custom_hashes={},
    )
    bound = {s.id for s in report.storyboard.scenes if any(o.data and o.data.source == "responses" for o in s.objects)}
    assert bound and all((other_data[s] != before[s]) == (s in bound) for s in before)


def test_media_and_store_directories_follow_the_code_and_the_settings(project_copy: Project) -> None:
    report = _prepared(project_copy)
    sources = sources_from_report(project_copy, report)
    assert report.family
    assert media_directory(project_copy, "working", {}) == ".scianim/media/working"
    assert media_directory(project_copy, "working", TOOLS) == ".scianim/media/working/" + "f" * 12
    job, _, hashes = build_video_job(project_copy, sources, report.family, "storyboard", tool_versions=TOOLS)
    assert job.manim.media_dir.endswith("f" * 12) and job.segment_store is not None
    assert job.segment_store.startswith(".scianim/segments/") and hashes.scene_fingerprints
    draft, _, _ = build_video_job(project_copy, sources, report.family, "draft", tool_versions=TOOLS)
    assert draft.segment_store != job.segment_store  # another resolution, another store
    again, _, _ = build_video_job(project_copy, sources, report.family, "storyboard", tool_versions=TOOLS, workers=4)
    assert again.segment_store == job.segment_store  # workers do not change the pictures
    assert segment_store_directory(project_copy, job.manim, {}) is None
    newer = {**TOOLS, "bridge_fingerprint": "e" * 64}
    assert cache_key(hashes, job.manim, [], "render_video:storyboard", newer) != job.cache_key
    other, _, _ = build_video_job(project_copy, sources, report.family, "storyboard", tool_versions=newer)
    assert other.segment_store != job.segment_store and other.manim.media_dir != job.manim.media_dir


def test_reuse_is_predicted_for_unchanged_scenes(project_copy: Project) -> None:
    report = _prepared(project_copy)
    sources = sources_from_report(project_copy, report)
    assert report.family
    job, paths, hashes = build_video_job(project_copy, sources, report.family, "storyboard", tool_versions=TOOLS)
    plays = [
        PlayRecord(index=i, scene_id=scene, start_seconds=i, frames=frames)
        for i, (scene, frames) in enumerate([("excitation", 30), ("excitation", 60), ("normalization", 90)])
    ]
    assert predicted_reuse(project_copy, job, hashes, plays) == (frozenset(), None)  # nothing rendered yet
    earlier = hashes.model_copy(update={"scene_fingerprints": {**hashes.scene_fingerprints, "normalization": "0" * 64}})
    manifest = ArtifactManifest(
        created_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        job=job,
        result=WorkerResult(job_id=job.job_id, status="succeeded", plays=plays, elapsed_seconds=1),
        inputs=earlier,
    )
    paths.manifest_file.parent.mkdir(parents=True, exist_ok=True)
    paths.manifest_file.write_text(manifest.model_dump_json())
    reusable, source = predicted_reuse(project_copy, job, hashes, plays)
    assert reusable == frozenset({0, 1}) and source == job.job_id
    # Another play structure in a scene means another scene, whatever its fingerprint says.
    longer = [*plays[:1], plays[1].model_copy(update={"frames": 61}), plays[2]]
    assert predicted_reuse(project_copy, job, hashes, longer)[0] == frozenset()
    # Another store (other settings or other code) shares nothing.
    elsewhere = job.model_copy(update={"segment_store": ".scianim/segments/0000000000000000"})
    assert predicted_reuse(project_copy, elsewhere, hashes, plays) == (frozenset(), None)
