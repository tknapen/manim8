"""`scianim clean`: reclaim space from caches and superseded working renders, never from revisions."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from scianim.project import Project


@dataclass
class CleanReport:
    removed: list[Path] = field(default_factory=list)
    bytes_freed: int = 0
    kept: list[Path] = field(default_factory=list)


def dir_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def clean_project(project: Project, keep: int = 1, media: bool = True, dry_run: bool = False) -> CleanReport:
    """Remove Manim's media cache, old job directories and superseded `renders/working` jobs.

    The newest `keep` jobs are retained. Revision directories and `renders/rev_*` are never touched.
    """
    report = CleanReport()
    targets: list[Path] = []
    if media and (project.scianim_dir / "media").exists():
        targets.append(project.scianim_dir / "media")
    jobs = sorted((project.scianim_dir / "jobs").glob("job_*")) if (project.scianim_dir / "jobs").is_dir() else []
    working = (
        sorted((project.renders_dir / "working").glob("job_*")) if (project.renders_dir / "working").is_dir() else []
    )
    keep = max(keep, 0)
    for group in (jobs, working):
        old, kept = (group[:-keep], group[-keep:]) if keep else (group, [])
        targets.extend(old)
        report.kept.extend(kept)
    for target in targets:
        report.bytes_freed += dir_size(target)
        report.removed.append(target)
        if not dry_run:
            shutil.rmtree(target, ignore_errors=True)
    cache = project.scianim_dir / "cache"
    if cache.is_dir() and not dry_run:
        for pointer in cache.glob("*.json"):
            try:
                manifest = project.root / json.loads(pointer.read_text())["manifest"]
            except (OSError, KeyError, ValueError):
                pointer.unlink(missing_ok=True)
                continue
            if not manifest.exists():
                pointer.unlink(missing_ok=True)
    return report
