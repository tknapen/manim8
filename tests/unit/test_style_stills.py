"""Stills for a style decision without rendering: candidate resolution, job separation, the sheet, publishing."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from scianim.codegen.generate import write_scene_module
from scianim.config.loader import SpecError
from scianim.planning.checks import validate_project
from scianim.project import Project
from scianim.render.jobs import build_snapshot_job, sources_from_report
from scianim.styles import stills
from scianim_core import ArtifactManifest, CheckpointRecord, StyleSelection, WorkerResult

CANDIDATE = """schema_version: "1.0"
name: tomas_scientific
version: "0.6.0"
description: a warmer accent, tried out
inherits: tomas_scientific@0.5.0
palette:
  emphasis: "#D9772A"
motion:
  ramp_seconds: 2.0
"""


def _prepared(project: Project):
    report = validate_project(project, require_family=True)
    assert report.animation and report.storyboard and report.style and report.family
    write_scene_module(report.animation, report.storyboard, report.style, project.scene_module_path(report.animation))
    return validate_project(project, require_family=True)


def test_candidate_resolves_beside_the_published_chain_and_separates_jobs(
    project_copy: Project, tmp_path: Path
) -> None:
    report = _prepared(project_copy)
    candidate = tmp_path / "candidate" / "style.yaml"
    candidate.parent.mkdir()
    candidate.write_text(CANDIDATE)
    sheet = stills.load_candidate(candidate)
    staged = stills.stage_candidate(sheet, candidate, stills.temporary_styles_root())
    assert (staged / "tomas_scientific" / "0.6.0" / "style.yaml").exists()
    own = report.animation.style
    wanted = stills.resolve_with(
        project_copy,
        report,
        StyleSelection(name=sheet.name, version=sheet.version, overrides=dict(own.overrides)),
        [staged],
    )
    current = report.style
    assert wanted.hash != current.hash and wanted.layers[-1] == "theme:tomas_scientific@0.6.0"
    diff = stills.token_diff(current, wanted)
    assert [(p, b) for p, _, b in diff] == [("motion.ramp_seconds", 2.0), ("palette.emphasis", "#D9772A")]
    # The two snapshot jobs differ only by the style, and so do their cache keys.
    import dataclasses

    base = sources_from_report(project_copy, report)
    assert report.family
    job_a, _, _ = build_snapshot_job(project_copy, base, report.family, ["pool_raised"])
    job_b, _, _ = build_snapshot_job(
        project_copy, dataclasses.replace(base, style=wanted), report.family, ["pool_raised"]
    )
    assert job_a.cache_key != job_b.cache_key and job_b.resolved_style.hash == wanted.hash
    assert job_a.snapshot_ids == job_b.snapshot_ids == ["pool_raised"]
    # `against` picks another published sheet with the project's overrides kept.
    against = stills.resolve_with(project_copy, report, stills.selection_for("tomas_scientific@0.4.0", own), [])
    assert against.theme_version == "0.4.0" and against.hash != current.hash


def test_stills_sheet_shows_pairs_and_differences(project_copy: Project, tmp_path: Path) -> None:
    report = _prepared(project_copy)
    assert report.family and report.style
    base = sources_from_report(project_copy, report)
    job, _paths, hashes = build_snapshot_job(project_copy, base, report.family, ["pool_raised"])

    def manifest(label: str, hash_hex: str) -> ArtifactManifest:
        png = project_copy.renders_dir / "working" / label / "pool_raised.png"
        png.parent.mkdir(parents=True, exist_ok=True)
        png.write_bytes(b"png")
        record = CheckpointRecord(
            snapshot_id="pool_raised",
            scene_id="normalization",
            kind="manim_checkpoint",
            png=png.relative_to(project_copy.root).as_posix(),
            width_px=960,
            height_px=540,
            sha256=hash_hex * 64,
            animation_index=3,
            expected_time_seconds=13,
        )
        return ArtifactManifest(
            created_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            job=job.model_copy(update={"job_id": f"job_20261031T000000_{label[:6]}"}),
            result=WorkerResult(job_id=job.job_id, status="succeeded", checkpoints=[record], elapsed_seconds=1),
            inputs=hashes,
        )

    other = report.style.model_copy(update={"hash": "sha256:" + "f" * 64, "theme_version": "0.6.0"})
    pair = [
        stills.Still("current", report.style, manifest("aaaaaa", "a")),
        stills.Still("candidate", other, manifest("bbbbbb", "b")),
    ]
    target = stills.write_stills_sheet(
        pair, project_copy, project_copy.renders_dir / "working" / "stills_x" / "stills.html"
    )
    text = target.read_text()
    assert text.count("<img") == 2 and "../aaaaaa/pool_raised.png" in text and "../bbbbbb/pool_raised.png" in text
    assert "candidate" in text and "Tokens that differ" in text
    with pytest.raises(ValueError):
        stills.write_stills_sheet(pair[:1], project_copy, target)


def test_publish_copies_a_candidate_once(tmp_path: Path) -> None:
    candidate = tmp_path / "next" / "style.yaml"
    candidate.parent.mkdir()
    candidate.write_text(CANDIDATE)
    (candidate.parent / "PHILOSOPHY.md").write_text("# why\n")
    styles_dir = tmp_path / "styles"
    written = stills.publish_candidate(candidate, "tomas_scientific@0.6.0", styles_dir)
    assert written == styles_dir / "tomas_scientific" / "0.6.0" / "style.yaml"
    text = written.read_text()
    assert "version: 0.6.0" in text or 'version: "0.6.0"' in text
    assert "name: tomas_scientific" in text and (written.parent / "PHILOSOPHY.md").exists()
    with pytest.raises(SpecError, match="never edited"):
        stills.publish_candidate(candidate, "tomas_scientific@0.6.0", styles_dir)
    orphan = tmp_path / "orphan.yaml"
    orphan.write_text(CANDIDATE.replace("inherits: tomas_scientific@0.5.0", "inherits: null"))
    with pytest.raises(SpecError, match="inherits"):
        stills.publish_candidate(orphan, "tomas_scientific@0.7.0", styles_dir)
