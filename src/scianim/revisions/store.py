"""Immutable project revisions: write-once directories under `revisions/` (spec sections 5.5 and 11).

A revision copies the specs, the generated code and the resolved style. Data files stay in `data/`
and are recorded by hash; rendering a revision verifies that they have not changed.
"""

from __future__ import annotations

import datetime as dt
import shutil
from dataclasses import dataclass
from pathlib import Path

from scianim.config.loader import SpecError
from scianim.planning.checks import Report
from scianim.project import Project
from scianim_core import ResolvedStyle, RevisionHashes, RevisionRecord
from scianim_core.hashing import sha256_file

REVISION_FILE = "revision.json"
STYLE_FILE = "style.resolved.json"


@dataclass(frozen=True)
class RevisionSources:
    record: RevisionRecord
    root: Path
    animation_path: Path
    storyboard_path: Path | None
    code_dir: Path | None
    resolved_style: ResolvedStyle


def list_revisions(project: Project) -> list[RevisionRecord]:
    records = []
    if not project.revisions_dir.is_dir():
        return records
    for directory in sorted(project.revisions_dir.glob("rev_*")):
        record_file = directory / REVISION_FILE
        if record_file.exists():
            records.append(RevisionRecord.model_validate_json(record_file.read_text(encoding="utf-8")))
    return records


def latest_revision(project: Project) -> RevisionRecord | None:
    records = list_revisions(project)
    return records[-1] if records else None


def next_revision_id(project: Project) -> str:
    numbers = [int(r.id.split("_")[1]) for r in list_revisions(project)]
    return f"rev_{(max(numbers) + 1 if numbers else 1):04d}"


def compute_hashes(project: Project, report: Report) -> RevisionHashes:
    assert report.animation is not None and report.style is not None
    scene_module = project.scene_module_path(report.animation)
    custom = (
        {p.name: sha256_file(p) for p in sorted(project.code_dir.glob("*.py")) if p != scene_module}
        if project.code_dir.is_dir()
        else {}
    )
    return RevisionHashes(
        animation_spec=sha256_file(project.animation_path),
        storyboard=sha256_file(project.storyboard_path) if project.storyboard_path.exists() else None,
        scene_code=sha256_file(scene_module) if scene_module.exists() else None,
        custom_code=custom,
        resolved_style=report.style.hash,
        data_files={source_id: sha256_file(path) for source_id, path in sorted(report.source_paths.items())},
    )


def create_revision(project: Project, report: Report, message: str, allow_empty: bool = False) -> RevisionRecord:
    if not report.ok or report.animation is None or report.style is None:
        raise SpecError(project.root, "the project does not validate; fix the errors before creating a revision")
    hashes = compute_hashes(project, report)
    parent = latest_revision(project)
    if parent is not None and parent.hashes == hashes and not allow_empty:
        raise SpecError(project.root, f"no changes since {parent.id}; use --allow-empty to record a revision anyway")
    rev_id = next_revision_id(project)
    target = project.revisions_dir / rev_id
    if target.exists():
        raise SpecError(target, "revision directory already exists; revisions are write-once")
    target.mkdir(parents=True)
    files: list[str] = []
    shutil.copy2(project.animation_path, target / project.animation_path.name)
    files.append(project.animation_path.name)
    if project.storyboard_path.exists():
        shutil.copy2(project.storyboard_path, target / project.storyboard_path.name)
        files.append(project.storyboard_path.name)
    if project.code_dir.is_dir():
        (target / "code").mkdir()
        for source in sorted(project.code_dir.glob("*.py")):
            shutil.copy2(source, target / "code" / source.name)
            files.append(f"code/{source.name}")
    (target / STYLE_FILE).write_text(report.style.model_dump_json(indent=2), encoding="utf-8")
    files.append(STYLE_FILE)
    record = RevisionRecord(
        id=rev_id,
        created_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        parent=parent.id if parent else None,
        message=message,
        style_theme=report.style.theme,
        style_version=report.style.theme_version,
        hashes=hashes,
        files=files,
    )
    (target / REVISION_FILE).write_text(record.model_dump_json(indent=2), encoding="utf-8")
    return record


def load_revision(project: Project, rev_id: str) -> RevisionSources:
    root = project.revisions_dir / rev_id
    record_file = root / REVISION_FILE
    if not record_file.exists():
        known = [r.id for r in list_revisions(project)]
        raise SpecError(project.revisions_dir, f"no revision '{rev_id}'; known: {known or 'none'}")
    record = RevisionRecord.model_validate_json(record_file.read_text(encoding="utf-8"))
    storyboard = root / "storyboard.yaml"
    code_dir = root / "code"
    return RevisionSources(
        record=record,
        root=root,
        animation_path=root / "animation.yaml",
        storyboard_path=storyboard if storyboard.exists() else None,
        code_dir=code_dir if code_dir.is_dir() else None,
        resolved_style=ResolvedStyle.model_validate_json((root / STYLE_FILE).read_text(encoding="utf-8")),
    )
