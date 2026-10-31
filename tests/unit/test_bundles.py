"""Milestone 6 without rendering: export, inspect and import of bundles; what goes in, what stays out."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from scianim.bundles import BundleError, ExportOptions, export_bundle, import_bundle, inspect_bundle
from scianim.bundles.archive import safe_member_name
from scianim.bundles.export import _absolute_path_hits, portable_pyproject
from scianim.codegen.generate import write_scene_module
from scianim.config.loader import SpecError
from scianim.planning.checks import validate_project
from scianim.project import Project
from scianim.revisions.store import create_revision
from scianim.workspace import init_workspace
from scianim_core.bundle import BUNDLE_ROOT


def _prepare(project: Project) -> None:
    report = validate_project(project, require_family=True)
    assert report.animation and report.storyboard and report.style
    write_scene_module(report.animation, report.storyboard, report.style, project.scene_module_path(report.animation))
    create_revision(project, validate_project(project, require_family=True), "frozen for export")


def test_export_inspect_and_import_round_trip(project_copy: Project, tmp_path: Path) -> None:
    _prepare(project_copy)
    (project_copy.root / ".scianim" / "cache").mkdir(parents=True)
    (project_copy.root / ".scianim" / "cache" / "x.json").write_text("{}")
    (project_copy.root / "renders" / "working" / "job_20260101T000000_aaaaaa").mkdir(parents=True)
    (project_copy.root / "renders" / "working" / "job_20260101T000000_aaaaaa" / "x.png").write_bytes(b"png")
    archive = tmp_path / "dn.scianim.zip"
    result = export_bundle(project_copy.root, archive)
    names = set(result.members)
    assert {"bundle.yaml", "README.md", "MANIFEST.sha256", "family.yaml", "environments/pyproject.toml"} <= names
    family_dir = project_copy.root.parent
    assert ("environments/uv.lock" in names) == (family_dir / "uv.lock").exists()
    assert "projects/divisive_normalization/animation.yaml" in names
    assert "projects/divisive_normalization/revisions/rev_0001/revision.json" in names
    assert "projects/divisive_normalization/data/synthetic_responses.csv" in names
    assert "styles/tomas_scientific/0.5.0/style.yaml" in names and "styles/default/0.5.0/style.yaml" in names
    assert "styles/default/0.4.0/style.yaml" in names
    assert (
        "styles/default/0.3.1/style.yaml" in names and "styles/default/0.3.0/style.yaml" in names
    )  # the chain's parents
    assert not any(
        ".scianim" in n or ".venv" in n or n.startswith("projects/divisive_normalization/renders") for n in names
    )
    manifest = result.manifest
    assert manifest.kind == "project" and manifest.projects[0].revisions == ["rev_0001"]
    assert manifest.environment.lockfile == (family_dir / "uv.lock").exists() and manifest.environment.packages_relative
    assert "cairo" in {r.name for r in manifest.environment.system_requirements}

    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            assert info.filename.startswith(f"{BUNDLE_ROOT}/") and info.date_time == (2020, 1, 1, 0, 0, 0)
        readme = zf.read(f"{BUNDLE_ROOT}/README.md").decode()
    assert "System requirements" in readme and "family env sync" in readme

    inspection = inspect_bundle(archive)
    assert inspection.ok and inspection.verified == len(names) - 1

    # Import into a fresh workspace: validates, styles present, no project overwrite.
    other = tmp_path / "other"
    init_workspace(other)
    report = import_bundle(archive, other)
    project = other / "families" / "computational_neuroscience" / "divisive_normalization"
    assert report.projects == [project] and (project / "revisions" / "rev_0001" / "revision.json").exists()
    assert (other / "styles" / "default" / "0.5.0" / "style.yaml").exists()
    assert (report.family_dir / "pyproject.toml").exists() and (report.family_dir / "family.yaml").exists()
    assert validate_project(Project(project), require_family=True).ok
    assert any("family env sync" in step for step in report.next_steps)
    with pytest.raises(SpecError, match="never overwrite"):
        import_bundle(archive, other)

    # Renders travel only on request.
    with_renders = export_bundle(
        project_copy.root, tmp_path / "dn_renders.scianim.zip", ExportOptions(include_renders=True)
    )
    assert "projects/divisive_normalization/renders/working/job_20260101T000000_aaaaaa/x.png" in with_renders.members


def test_omitted_sources_are_recorded_with_relink_steps(project_copy: Project, tmp_path: Path) -> None:
    _prepare(project_copy)
    refs = project_copy.root / "references"
    (refs / "paper.pdf").write_bytes(b"%PDF-1.4 fake")
    Image.new("RGB", (8, 8), "white").save(refs / "figure.png")
    animation = project_copy.animation_path
    text = animation.read_text()
    text = text.replace(
        "sources:\n",
        "sources:\n  - id: paper\n    type: pdf\n    path: references/paper.pdf\n    role: scientific_reference\n"
        "  - id: figure\n    type: image\n    path: references/figure.png\n    role: composition_reference\n",
        1,
    )
    animation.write_text(text)
    assert validate_project(project_copy).ok
    result = export_bundle(project_copy.root, tmp_path / "dn.scianim.zip")
    omitted = {o.source_id: o for o in result.manifest.omitted_sources}
    assert set(omitted) == {"paper", "figure"}
    assert "PDF" in omitted["paper"].reason and "copy the file" in omitted["paper"].relink
    assert "third-party" in omitted["figure"].reason
    assert not any(n.endswith(("paper.pdf", "figure.png")) for n in result.members)
    assert any("Omitted sources" in line for line in inspect_bundle(tmp_path / "dn.scianim.zip").readme.splitlines())
    everything = export_bundle(
        project_copy.root, tmp_path / "dn_all.scianim.zip", ExportOptions(include_source_assets=True)
    )
    assert everything.manifest.omitted_sources == []
    assert any(n.endswith("paper.pdf") for n in everything.members)
    other = tmp_path / "other"
    init_workspace(other)
    report = import_bundle(tmp_path / "dn.scianim.zip", other)
    assert any("relink divisive_normalization/paper" in w for w in report.warnings)


def test_absolute_paths_fail_unless_redacted(project_copy: Project, tmp_path: Path) -> None:
    _prepare(project_copy)
    (project_copy.root / "references" / "notes.md").write_text(f"see {project_copy.root} for details\n")
    with pytest.raises(SpecError, match="absolute path"):
        export_bundle(project_copy.root, tmp_path / "dn.scianim.zip")
    result = export_bundle(project_copy.root, tmp_path / "dn.scianim.zip", ExportOptions(redact_paths=True))
    with zipfile.ZipFile(tmp_path / "dn.scianim.zip") as zf:
        notes = zf.read(f"{BUNDLE_ROOT}/projects/divisive_normalization/references/notes.md").decode()
    assert str(project_copy.root) not in notes and "<redacted-path>" in notes
    assert any("redacted" in note for note in result.manifest.notes)


def test_tampered_and_unsafe_archives_are_refused(project_copy: Project, tmp_path: Path) -> None:
    _prepare(project_copy)
    archive = tmp_path / "dn.scianim.zip"
    export_bundle(project_copy.root, archive)
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(archive) as src, zipfile.ZipFile(tampered, "w") as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename.endswith("storyboard.yaml"):
                data = data.replace(b"excitation", b"excitement", 1)
            dst.writestr(info, data)
    report = inspect_bundle(tampered)
    assert not report.ok and any("checksum mismatch" in p for p in report.problems)
    other = tmp_path / "other"
    init_workspace(other)
    with pytest.raises(BundleError, match="does not verify"):
        import_bundle(tampered, other)

    escaping = tmp_path / "escape.zip"
    with zipfile.ZipFile(escaping, "w") as zf:
        zf.writestr(f"{BUNDLE_ROOT}/../etc/passwd", "x")
    with pytest.raises(BundleError, match="unsafe"):
        inspect_bundle(escaping)
    for bad in ("/abs/path", "elsewhere/bundle.yaml", f"{BUNDLE_ROOT}/a/../b"):
        with pytest.raises(BundleError):
            safe_member_name(bad)
    assert safe_member_name(f"{BUNDLE_ROOT}/projects/x/animation.yaml") == "projects/x/animation.yaml"
    assert not zipfile.is_zipfile(tmp_path / "missing.zip")
    with pytest.raises(BundleError, match="not a zip"):
        inspect_bundle(project_copy.animation_path)
    digest = hashlib.sha256(b"x").hexdigest()
    assert len(digest) == 64


def test_family_bundle_carries_every_project(workspace: Path, tmp_path: Path) -> None:
    family = workspace / "families" / "computational_neuroscience"
    for name in ("divisive_normalization", "prf_tuning", "orientation_tuning", "gabor_filter"):
        _prepare(Project(family / name))
    result = export_bundle(family, tmp_path / "family.scianim.zip")
    assert result.manifest.kind == "family"
    assert sorted(p.id for p in result.manifest.projects) == [
        "divisive_normalization",
        "gabor_filter",
        "orientation_tuning",
        "prf_tuning",
    ]
    assert all(p.revisions == ["rev_0001"] for p in result.manifest.projects)
    other = tmp_path / "other"
    init_workspace(other)
    report = import_bundle(tmp_path / "family.scianim.zip", other, family_id="neuro_copy")
    assert report.family_dir.name == "neuro_copy" and len(report.projects) == 4
    for project_dir in report.projects:
        assert validate_project(Project(project_dir), require_family=True).ok


def test_path_detector_and_portable_pyproject() -> None:
    # A relative path that happens to pass through a home directory is not an absolute path.
    assert _absolute_path_hits('path = "../../../../home/runner/work/x/packages"', ["/home/runner"]) == []
    assert _absolute_path_hits("see /home/runner/work/x for details", ["/home/runner"]) == ["/home/runner"]
    assert _absolute_path_hits('root: "/home/runner"', ["/home/runner"]) == ["/home/runner"]
    assert _absolute_path_hits("/home/runners/other", ["/home/runner"]) == []
    text = (
        '[project]\nname = "x"\n\n[tool.uv.sources]\nscianim-bridge = { path = "../../packages/scianim_bridge", editable = true }\n'
        'scianim-core = { path = "../../packages/scianim_core", editable = true }\n\n[tool.other]\nk = 1\n'
    )
    portable = portable_pyproject(text)
    assert "path =" not in "\n".join(line for line in portable.splitlines() if not line.startswith("#"))
    assert "[tool.other]\nk = 1" in portable and "bundle import" in portable


def test_exported_pyproject_has_no_path_sources(project_copy: Project, tmp_path: Path) -> None:
    _prepare(project_copy)
    archive = tmp_path / "dn.scianim.zip"
    export_bundle(project_copy.root, archive)
    with zipfile.ZipFile(archive) as zf:
        text = zf.read(f"{BUNDLE_ROOT}/environments/pyproject.toml").decode()
    active = [line for line in text.splitlines() if not line.strip().startswith("#")]
    assert not any("path =" in line for line in active)
