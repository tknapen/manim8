"""Immutable revisions and the clean command."""

from __future__ import annotations

import json

import pytest

from scianim.clean import clean_project
from scianim.codegen.generate import write_scene_module
from scianim.config.loader import SpecError
from scianim.planning.checks import validate_project
from scianim.project import Project
from scianim.render.jobs import sources_from_revision
from scianim.revisions.store import create_revision, list_revisions, load_revision


def prepared(project: Project):
    report = validate_project(project, require_family=True)
    assert report.animation and report.storyboard and report.style
    write_scene_module(report.animation, report.storyboard, report.style, project.scene_module_path(report.animation))
    return validate_project(project, require_family=True)


def test_create_list_and_render_from_revision(project_copy: Project) -> None:
    report = prepared(project_copy)
    first = create_revision(project_copy, report, "initial storyboard")
    assert first.id == "rev_0001" and first.parent is None
    assert set(first.files) >= {
        "animation.yaml",
        "storyboard.yaml",
        "code/scene_divisive_normalization.py",
        "style.resolved.json",
    }
    rev_dir = project_copy.revisions_dir / "rev_0001"
    record = json.loads((rev_dir / "revision.json").read_text())
    assert record["hashes"]["data_files"]["responses"]
    with pytest.raises(SpecError, match="no changes since rev_0001"):
        create_revision(project_copy, report, "again")
    create_revision(project_copy, report, "forced", allow_empty=True)
    storyboard = project_copy.storyboard_path
    storyboard.write_text(storyboard.read_text().replace("at_seconds: 4\n", "at_seconds: 5\n"))
    report = prepared(project_copy)
    third = create_revision(project_copy, report, "move the first checkpoint")
    assert [r.id for r in list_revisions(project_copy)] == ["rev_0001", "rev_0002", "rev_0003"]
    assert third.parent == "rev_0002"
    sources = sources_from_revision(project_copy, load_revision(project_copy, "rev_0001"), report)
    assert sources.revision_id == "rev_0001"
    assert sources.scene_module == rev_dir / "code" / "scene_divisive_normalization.py"
    assert sources.storyboard.scenes[0].snapshots[0].at_seconds == 4  # the frozen copy, not the working one
    with pytest.raises(SpecError, match="no revision 'rev_0042'"):
        load_revision(project_copy, "rev_0042")


def test_changed_data_blocks_revision_render(project_copy: Project) -> None:
    report = prepared(project_copy)
    create_revision(project_copy, report, "initial")
    csv = project_copy.data_dir / "synthetic_responses.csv"
    csv.write_text(csv.read_text() + "11.0,1.0,1.0,5.5,low_pool,synthetic\n")
    report = validate_project(project_copy, require_family=True)
    with pytest.raises(SpecError, match="changed since rev_0001"):
        sources_from_revision(project_copy, load_revision(project_copy, "rev_0001"), report)


def test_clean_keeps_newest_job_and_revisions(project_copy: Project) -> None:
    jobs = project_copy.scianim_dir / "jobs"
    working = project_copy.renders_dir / "working"
    media = project_copy.scianim_dir / "media" / "working"
    for name in ("job_20260101T000000_aaaaaa", "job_20260102T000000_bbbbbb"):
        (jobs / name).mkdir(parents=True)
        (jobs / name / "worker.log").write_text("log")
        (working / name).mkdir(parents=True)
        (working / name / "manifest.json").write_text("{}")
    media.mkdir(parents=True)
    (media / "partial.mp4").write_bytes(b"0" * 1000)
    revision_render = project_copy.renders_dir / "rev_0001" / "job_20260101T000000_cccccc"
    revision_render.mkdir(parents=True)
    (revision_render / "manifest.json").write_text("{}")
    cache = project_copy.scianim_dir / "cache"
    cache.mkdir()
    (cache / "deadbeef.json").write_text(
        json.dumps({"manifest": "renders/working/job_20260101T000000_aaaaaa/manifest.json"})
    )
    dry = clean_project(project_copy, keep=1, dry_run=True)
    assert (working / "job_20260101T000000_aaaaaa").exists()
    assert len(dry.removed) == 3
    report = clean_project(project_copy, keep=1)
    assert not (working / "job_20260101T000000_aaaaaa").exists()
    assert (working / "job_20260102T000000_bbbbbb").exists()
    assert not media.exists()
    assert revision_render.exists()
    assert not (cache / "deadbeef.json").exists()
    assert report.bytes_freed >= 1000
