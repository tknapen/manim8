"""Workspace commands, the nearest-family rule, groups, assets and duplicate detection."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from scianim.config.loader import SpecError
from scianim.families.resolve import locate_family
from scianim.planning.checks import validate_project
from scianim.project import Project
from scianim.render.jobs import materialize_data_files, sources_from_report
from scianim.workspace import (
    EXAMPLE_FAMILY,
    EXAMPLE_PROJECT,
    find_workspace,
    init_family,
    init_project,
    init_workspace,
    scan_workspace,
)


def rewrite(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert text.count(old) == 1, old
    path.write_text(text.replace(old, new))


def test_workspace_init_layout(workspace: Path) -> None:
    assert (workspace / "workspace.yaml").exists()
    assert (workspace / "styles" / "default" / "0.1.0" / "style.yaml").exists()
    assert (workspace / "styles" / "tomas_scientific" / "0.1.0" / "style.yaml").exists()
    family = workspace / "families" / EXAMPLE_FAMILY
    assert (family / "family.yaml").exists() and (family / "pyproject.toml").exists()
    assert (family / "components").is_dir() and (family / "assets").is_dir()
    project = family / EXAMPLE_PROJECT
    assert (project / "animation.yaml").exists() and (project / "storyboard.yaml").exists()
    assert (project / "code").glob("*.py").__class__ is not None  # code is regenerated, not copied
    assert not list((project / "code").glob("*.py"))
    assert find_workspace(project) == workspace
    with pytest.raises(SpecError, match="already a workspace"):
        init_workspace(workspace)


def test_family_pyproject_points_at_source_packages(workspace: Path) -> None:
    text = (workspace / "families" / EXAMPLE_FAMILY / "pyproject.toml").read_text()
    assert 'scianim-bridge = { path = "' in text and text.count("packages/scianim_") == 2
    rel = text.split('scianim-core = { path = "')[1].split('"')[0]
    assert (workspace / "families" / EXAMPLE_FAMILY / rel / "pyproject.toml").exists()


def test_family_and_project_from_templates(workspace: Path) -> None:
    family_dir = init_family(workspace, "perception_lab", title="Perception lab")
    assert (family_dir / "family.yaml").exists()
    project_dir = init_project(workspace, "perception_lab", "retinotopy_intro", title="Retinotopy")
    report = validate_project(Project(project_dir), require_family=True)
    assert report.ok, report.errors
    assert report.family is not None and report.family.manifest.id == "perception_lab"
    assert report.storyboard is None
    with pytest.raises(SpecError, match="must be a slug"):
        init_project(workspace, "perception_lab", "Bad Name")
    with pytest.raises(SpecError, match="not in this workspace"):
        init_project(workspace, "nope", "x")


def test_nearest_family_is_authoritative(project_copy: Project) -> None:
    rewrite(project_copy.animation_path, "title:", "family: somewhere_else\ntitle:")
    report = validate_project(project_copy, require_family=True)
    assert any("lives under family 'computational_neuroscience'" in e for e in report.errors)


def test_project_outside_any_family_needs_a_declaration(workspace: Path, tmp_path: Path) -> None:
    orphan = tmp_path / "orphan"
    shutil.copytree(workspace / "families" / EXAMPLE_FAMILY / EXAMPLE_PROJECT, orphan)
    with pytest.raises(SpecError, match="no family"):
        locate_family(orphan, None, [workspace / "families"])
    lookup = locate_family(orphan, EXAMPLE_FAMILY, [workspace / "families"])
    assert lookup.via == "search_root" and lookup.groups == ()


def test_duplicate_family_ids_are_rejected(workspace: Path) -> None:
    shutil.copytree(
        workspace / "families" / EXAMPLE_FAMILY, workspace / "families" / "twin", ignore=shutil.ignore_patterns(".venv")
    )
    with pytest.raises(SpecError, match="more than one place"):
        locate_family(workspace.parent / "elsewhere", EXAMPLE_FAMILY, [workspace / "families"])
    scan = scan_workspace(workspace)
    assert any("family id 'computational_neuroscience' is declared at both" in p for p in scan.problems)


def test_groups_layer_into_the_cascade(workspace: Path) -> None:
    family = workspace / "families" / EXAMPLE_FAMILY
    group = family / "perception"
    group.mkdir()
    (group / "group.yaml").write_text(
        'schema_version: "1.0"\nid: perception\nstyle:\n  overrides:\n    palette.emphasis: "#ABCDEF"\n'
    )
    shutil.move(str(family / EXAMPLE_PROJECT), str(group / EXAMPLE_PROJECT))
    project = Project(group / EXAMPLE_PROJECT)
    report = validate_project(project, require_family=True)
    assert report.ok, report.errors
    assert [g.manifest.id for g in report.groups] == ["perception"]
    assert report.style is not None
    assert "group:perception" in report.style.layers
    assert report.style.tokens.palette["emphasis"] == "#ABCDEF"
    scan = scan_workspace(workspace)
    assert scan.problems == []
    moved = next(node for node in scan.families[0].projects if node.id == "divisive_normalization")
    assert moved.groups == ["perception"]


def test_duplicate_project_ids_are_reported(workspace: Path) -> None:
    family = workspace / "families" / EXAMPLE_FAMILY
    shutil.copytree(family / EXAMPLE_PROJECT, family / "copy_of_example")
    scan = scan_workspace(workspace)
    assert any("project id 'divisive_normalization' is used by both" in p for p in scan.problems)


def test_assets_resolve_from_family_then_workspace(project_copy: Project, workspace: Path) -> None:
    family_assets = workspace / "families" / EXAMPLE_FAMILY / "assets"
    shutil.copy(project_copy.data_dir / "synthetic_responses.csv", family_assets / "shared_responses.csv")
    rewrite(project_copy.animation_path, "path: data/synthetic_responses.csv", "path: asset://shared_responses.csv")
    report = validate_project(project_copy, require_family=True)
    assert report.ok, report.errors
    assert report.source_paths["responses"] == (family_assets / "shared_responses.csv").resolve()
    rewrite(project_copy.animation_path, "path: asset://shared_responses.csv", "path: asset://missing.csv")
    missing = validate_project(project_copy, require_family=True)
    assert any("asset 'asset://missing.csv' not found" in e for e in missing.errors)
    shutil.move(str(family_assets / "shared_responses.csv"), str(workspace / "assets" / "missing.csv"))
    assert validate_project(project_copy, require_family=True).ok


def test_assets_are_materialized_into_the_project(project_copy: Project, workspace: Path) -> None:
    from scianim.codegen.generate import write_scene_module

    shutil.copy(project_copy.data_dir / "synthetic_responses.csv", workspace / "assets" / "shared.csv")
    rewrite(project_copy.animation_path, "path: data/synthetic_responses.csv", "path: asset://shared.csv")
    report = validate_project(project_copy, require_family=True)
    assert report.ok, report.errors
    write_scene_module(
        report.animation, report.storyboard, report.style, project_copy.scene_module_path(report.animation)
    )
    report = validate_project(project_copy, require_family=True)
    files = materialize_data_files(project_copy, sources_from_report(project_copy, report))
    assert files == {"responses": ".scianim/assets/shared.csv"}
    assert (project_copy.root / ".scianim" / "assets" / "shared.csv").exists()
