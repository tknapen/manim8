"""Import a bundle into a workspace: verify, then copy files; rebuilding the environment is a separate step."""

from __future__ import annotations

import os
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from scianim.bundles.archive import BundleError, inspect_bundle, safe_member_name
from scianim.config.loader import SpecError
from scianim.workspace import WORKSPACE_FILE, family_pyproject_text, packages_root
from scianim_core.bundle import BUNDLE_ROOT, CHECKSUM_FILE, BundleManifest


@dataclass
class ImportReport:
    manifest: BundleManifest
    family_dir: Path
    projects: list[Path] = field(default_factory=list)
    styles_added: list[str] = field(default_factory=list)
    styles_kept: list[str] = field(default_factory=list)
    lockfile_reused: bool = False
    next_steps: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def import_bundle(archive: Path, workspace: Path, family_id: str | None = None) -> ImportReport:
    workspace = workspace.resolve()
    if not (workspace / WORKSPACE_FILE).exists():
        raise SpecError(workspace, "not a workspace; run `scianim workspace init` first")
    inspection = inspect_bundle(archive)
    if not inspection.ok:
        raise BundleError("the bundle does not verify:\n  - " + "\n  - ".join(inspection.problems))
    manifest = inspection.manifest
    target_family = family_id or manifest.family.id
    family_dir = workspace / "families" / target_family
    for project in manifest.projects:
        if (family_dir / project.id).exists():
            raise SpecError(family_dir / project.id, "project directory already exists; imports never overwrite")
    report = ImportReport(manifest=manifest, family_dir=family_dir)
    with zipfile.ZipFile(archive) as zf:
        entries = {safe_member_name(info.filename): info for info in zf.infolist() if not info.is_dir()}

        def extract(relative: str, destination: Path) -> None:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(zf.read(entries[relative].filename))

        new_family = not (family_dir / "family.yaml").exists()
        if new_family:
            family_dir.mkdir(parents=True)
            text = zf.read(entries["family.yaml"].filename).decode("utf-8")
            if family_id and family_id != manifest.family.id:
                text = text.replace(f"\nid: {manifest.family.id}\n", f"\nid: {family_id}\n", 1)
            (family_dir / "family.yaml").write_text(text, encoding="utf-8")
            packages_relative = os.path.relpath(packages_root(), family_dir).replace(os.sep, "/")
            (family_dir / "pyproject.toml").write_text(
                family_pyproject_text(target_family, packages_relative), encoding="utf-8"
            )
            for name in ("components", "assets"):
                (family_dir / name).mkdir(exist_ok=True)
            if "environments/.python-version" in entries:
                extract("environments/.python-version", family_dir / ".python-version")
            lock_entry = next((e for e in entries if e.startswith("environments/") and e.endswith(".lock")), None)
            if lock_entry and manifest.environment.packages_relative == packages_relative:
                extract(lock_entry, family_dir / Path(lock_entry).name)
                report.lockfile_reused = True
            elif lock_entry:
                report.warnings.append(
                    f"lockfile not reused: packages/ was at {manifest.environment.packages_relative} at export and is at {packages_relative} here; `family env sync` will resolve afresh"
                )
        else:
            report.warnings.append(
                f"family '{target_family}' already exists; its family.yaml and environment were kept"
            )
        for relative in entries:
            if relative.startswith("components/"):
                destination = family_dir / relative
                if destination.exists():
                    report.warnings.append(f"kept existing {relative}")
                    continue
                extract(relative, destination)
            elif relative.startswith("assets/"):
                destination = family_dir / relative
                if not destination.exists():
                    extract(relative, destination)
        for relative in entries:
            if not relative.startswith("styles/"):
                continue
            destination = workspace / relative
            if destination.exists():
                if destination.read_bytes() == zf.read(entries[relative].filename):
                    report.styles_kept.append(relative)
                else:
                    raise SpecError(
                        destination,
                        f"style sheet differs from the bundle's {relative}; theme versions are immutable, bump the version instead",
                    )
            else:
                extract(relative, destination)
                report.styles_added.append(relative)
        for project in manifest.projects:
            prefix = f"{project.path}/"
            destination_root = family_dir / project.id
            for relative in entries:
                if relative.startswith(prefix):
                    extract(relative, destination_root / relative[len(prefix) :])
            for name in ("code", "data", "references", "feedback"):
                (destination_root / name).mkdir(exist_ok=True)
            report.projects.append(destination_root)
    report.next_steps.append(f"scianim family env sync {family_dir}")
    for project_dir in report.projects:
        report.next_steps.append(f"scianim validate {project_dir}")
    for item in manifest.omitted_sources:
        report.warnings.append(f"relink {item.project_id}/{item.source_id} ({item.type}): {item.relink}")
    return report


def cleanup_failed_import(report: ImportReport) -> None:
    for project_dir in report.projects:
        shutil.rmtree(project_dir, ignore_errors=True)


__all__ = ["BUNDLE_ROOT", "CHECKSUM_FILE", "ImportReport", "cleanup_failed_import", "import_bundle"]
