"""Reading bundles safely: entry names, checksums and the manifest, with nothing executed."""

from __future__ import annotations

import hashlib
import posixpath
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from pydantic import ValidationError
from ruamel.yaml import YAML

from scianim_core.bundle import BUNDLE_ROOT, CHECKSUM_FILE, BundleManifest

_yaml = YAML(typ="safe")


class BundleError(Exception):
    """The archive is not a usable bundle; the message says why."""


def safe_member_name(name: str) -> str:
    """The member path relative to the bundle root, or raise for anything that could escape."""
    if name.startswith(("/", "\\")) or "\\" in name:
        raise BundleError(f"unsafe archive entry {name!r}")
    parts = PurePosixPath(name).parts
    if any(part in ("..", "") for part in parts) or (parts and ":" in parts[0]):
        raise BundleError(f"unsafe archive entry {name!r}")
    if not parts or parts[0] != BUNDLE_ROOT:
        raise BundleError(f"entry {name!r} is outside {BUNDLE_ROOT}/")
    return posixpath.join(*parts[1:]) if len(parts) > 1 else ""


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return (info.external_attr >> 16) & 0o170000 == 0o120000


def parse_checksums(text: str) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        digest, _, path = line.partition("  ")
        if len(digest) != 64 or not path:
            raise BundleError(f"malformed checksum line: {line!r}")
        checksums[path] = digest
    return checksums


@dataclass
class InspectReport:
    manifest: BundleManifest
    files: list[str] = field(default_factory=list)
    verified: int = 0
    problems: list[str] = field(default_factory=list)
    readme: str = ""

    @property
    def ok(self) -> bool:
        return not self.problems


def inspect_bundle(archive: Path) -> InspectReport:
    """Validate the layout, the manifest and every checksum. Reads bytes; never imports or runs anything."""
    if not zipfile.is_zipfile(archive):
        raise BundleError(f"{archive} is not a zip archive")
    with zipfile.ZipFile(archive) as zf:
        members = [info for info in zf.infolist() if not info.is_dir()]
        names: dict[str, zipfile.ZipInfo] = {}
        for info in members:
            if _is_symlink(info):
                raise BundleError(f"symbolic link in archive: {info.filename}")
            names[safe_member_name(info.filename)] = info
        if "bundle.yaml" not in names:
            raise BundleError(f"no {BUNDLE_ROOT}/bundle.yaml in the archive")
        try:
            manifest = BundleManifest.model_validate(_yaml.load(zf.read(names["bundle.yaml"].filename)))
        except (ValidationError, Exception) as exc:
            raise BundleError(f"bundle.yaml is invalid: {exc}") from None
        report = InspectReport(manifest=manifest, files=sorted(names))
        if CHECKSUM_FILE not in names:
            report.problems.append(f"{CHECKSUM_FILE} is missing")
            return report
        checksums = parse_checksums(zf.read(names[CHECKSUM_FILE].filename).decode("utf-8"))
        for relative, info in sorted(names.items()):
            if relative == CHECKSUM_FILE:
                continue
            expected = checksums.get(relative)
            if expected is None:
                report.problems.append(f"{relative}: not listed in {CHECKSUM_FILE}")
                continue
            digest = hashlib.sha256(zf.read(info.filename)).hexdigest()
            if digest != expected:
                report.problems.append(f"{relative}: checksum mismatch")
            else:
                report.verified += 1
        for listed in checksums:
            if listed not in names:
                report.problems.append(f"{listed}: listed in {CHECKSUM_FILE} but missing from the archive")
        if "README.md" in names:
            report.readme = zf.read(names["README.md"].filename).decode("utf-8", errors="replace")
        if manifest.file_count and manifest.file_count != len(names):
            report.problems.append(f"manifest says {manifest.file_count} files, archive has {len(names)}")
    return report


__all__ = ["BundleError", "InspectReport", "inspect_bundle", "parse_checksums", "safe_member_name"]
