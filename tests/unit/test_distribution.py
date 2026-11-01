"""Distribution under the name manim8 (ADR-037): one version, release-mode families, the migration."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

import scianim
import scianim_core
from scianim import workspace as ws
from scianim.config.loader import SpecError
from scianim.families.resolve import load_family_context, sync_environment
from scianim.migrate import migrate_family_pyproject, migrate_tree, stale_family_pyproject
from scianim_core.components import REGISTRY_VERSION

REPO = Path(__file__).resolve().parents[2]


def _project(path: Path) -> dict:
    return tomllib.loads(path.read_text())["project"]


def test_the_three_distributions_share_one_version() -> None:
    control = _project(REPO / "pyproject.toml")
    core = _project(REPO / "packages" / "scianim_core" / "pyproject.toml")
    bridge = _project(REPO / "packages" / "scianim_bridge" / "pyproject.toml")
    assert (control["name"], core["name"], bridge["name"]) == ("manim8", "manim8-core", "manim8-bridge")
    assert control["version"] == core["version"] == bridge["version"] == scianim.__version__ == scianim_core.__version__
    bridge_init = (REPO / "packages" / "scianim_bridge" / "src" / "scianim_bridge" / "__init__.py").read_text()
    assert f'__version__ = "{control["version"]}"' in bridge_init
    # Each side pins the contracts at the release's version, so a family never mixes two versions of them.
    assert f"manim8-core=={control['version']}" in control["dependencies"]
    assert f"manim8-core=={control['version']}" in bridge["dependencies"]
    scripts = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]["scripts"]
    assert scripts["manim8"] == scripts["scianim"] == "scianim.cli:app"


def test_release_mode_family_takes_the_bridge_from_the_index(monkeypatch, tmp_path: Path) -> None:
    development = ws.family_pyproject_text("lab", "../../packages")
    assert 'manim8-bridge = { path = "../../packages/scianim_bridge"' in development
    release = ws.family_pyproject_text("lab", None)
    assert f'"manim8-bridge=={scianim.__version__}"' in release and "[tool.uv.sources]" not in release
    assert tomllib.loads(release)["tool"]["uv"]["package"] is False
    # An installed control plane: no checkout, styles and examples from the wheel's data.
    monkeypatch.setattr(ws, "repo_root", lambda: None)
    data = tmp_path / "_data"
    (data / "styles" / "default" / "0.5.0").mkdir(parents=True)
    (data / "examples").mkdir(parents=True)
    monkeypatch.setattr(ws, "DATA_ROOT", data)
    assert ws.packages_root() is None and ws.packages_relative_to(tmp_path) is None
    assert ws.bundled_styles_root() == data / "styles" and ws.examples_root() == data / "examples"


def test_migration_renames_old_family_environments(workspace: Path) -> None:
    family = workspace / "families" / "computational_neuroscience"
    pyproject = family / "pyproject.toml"
    current = pyproject.read_text()
    assert not stale_family_pyproject(current)
    old = current.replace("manim8-bridge", "scianim-bridge").replace("manim8-core", "scianim-core")
    assert stale_family_pyproject(old) and migrate_family_pyproject(old) == current
    pyproject.write_text(old)
    with pytest.raises(SpecError, match="scianim migrate"):
        sync_environment(load_family_context(family))
    preview = migrate_tree(workspace, dry_run=True)
    assert preview.changed == [pyproject] and pyproject.read_text() == old
    report = migrate_tree(workspace)
    assert report.changed == [pyproject] and pyproject.read_text() == current
    assert migrate_tree(workspace).changed == []


def test_jobs_carry_the_registry_they_were_written_for(project_copy) -> None:
    from scianim.codegen.generate import write_scene_module
    from scianim.planning.checks import validate_project
    from scianim.render.jobs import build_snapshot_job, sources_from_report

    report = validate_project(project_copy, require_family=True)
    assert report.animation and report.storyboard and report.style and report.family
    write_scene_module(
        report.animation, report.storyboard, report.style, project_copy.scene_module_path(report.animation)
    )
    report = validate_project(project_copy, require_family=True)
    job, _, _ = build_snapshot_job(project_copy, sources_from_report(project_copy, report), report.family, [])
    assert job.registry_version == REGISTRY_VERSION
