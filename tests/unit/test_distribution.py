"""Distribution under the name manim8 (ADR-037): one version, release-mode families, the migration."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

import scianim
import scianim_core
from scianim import workspace as ws
from scianim.config.loader import SpecError
from scianim.families.resolve import load_family_context, sync_environment
from scianim.migrate import migrate_family_pyproject, migrate_tree, stale_family_pyproject
from scianim.patterns import patterns_root
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
    (data / "patterns" / "catalogue").mkdir(parents=True)
    monkeypatch.setattr(ws, "DATA_ROOT", data)
    assert ws.packages_root() is None and ws.packages_relative_to(tmp_path) is None
    assert ws.bundled_styles_root() == data / "styles" and ws.examples_root() == data / "examples"
    assert patterns_root() == data / "patterns"


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


# --- where a family environment takes the bridge from (ADR-043) ---------------------------------------------------

COMMIT = "0123456789abcdef0123456789abcdef01234567"


def _fake_distribution(monkeypatch, tmp_path: Path, direct_url: str | None) -> None:
    """An installed `manim8` distribution whose dist-info holds the given `direct_url.json` (PEP 610)."""
    from importlib import metadata

    info = tmp_path / "site" / "manim8-0.1.0a0.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text("Metadata-Version: 2.1\nName: manim8\nVersion: 0.1.0a0\n")
    if direct_url is not None:
        (info / "direct_url.json").write_text(direct_url)
    real = metadata.distribution
    monkeypatch.setattr(
        ws.metadata, "distribution", lambda name: metadata.PathDistribution(info) if name == "manim8" else real(name)
    )
    monkeypatch.setattr(ws, "repo_root", lambda: None)
    monkeypatch.delenv(ws.BRIDGE_SOURCE_ENV, raising=False)


def _sources(text: str) -> dict:
    return tomllib.loads(text).get("tool", {}).get("uv", {}).get("sources", {})


def test_a_checkout_writes_path_sources(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv(ws.BRIDGE_SOURCE_ENV, raising=False)
    source = ws.bridge_source(tmp_path / "ws" / "families" / "lab")
    assert (source.kind, source.origin) == ("path", "checkout")
    assert (tmp_path / "ws" / "families" / "lab" / source.path / "scianim_bridge").resolve() == (
        REPO / "packages" / "scianim_bridge"
    )


def test_a_git_install_pins_the_families_to_its_commit(monkeypatch, tmp_path: Path) -> None:
    record = {
        "url": "https://github.com/tknapen/manim8",
        "vcs_info": {"vcs": "git", "commit_id": COMMIT, "requested_revision": "v0.1.0a0"},
    }
    _fake_distribution(monkeypatch, tmp_path, json.dumps(record))
    assert ws.control_plane_direct_url() == record
    source = ws.bridge_source(tmp_path / "family")
    assert (source.kind, source.origin, source.url, source.ref) == (
        "git",
        "git install",
        "https://github.com/tknapen/manim8",
        COMMIT,
    )
    text = ws.family_pyproject_text("lab", source)
    data = tomllib.loads(text)
    assert data["project"]["dependencies"] == ["manim8-bridge", "manim8-core"]
    assert _sources(text) == {
        "manim8-bridge": {
            "git": "https://github.com/tknapen/manim8",
            "rev": COMMIT,
            "subdirectory": "packages/scianim_bridge",
        },
        "manim8-core": {
            "git": "https://github.com/tknapen/manim8",
            "rev": COMMIT,
            "subdirectory": "packages/scianim_core",
        },
    }


@pytest.mark.parametrize(
    "direct_url",
    [
        None,  # installed from an index (or a wheel found through --find-links): no PEP 610 record
        json.dumps({"url": "file:///tmp/dist/manim8-0.1.0a0-py3-none-any.whl", "archive_info": {}}),
        json.dumps({"url": "file:///home/me/manim8", "dir_info": {}}),
        "not json",
    ],
)
def test_any_other_install_takes_the_bridge_from_the_index(monkeypatch, tmp_path: Path, direct_url) -> None:
    _fake_distribution(monkeypatch, tmp_path, direct_url)
    source = ws.bridge_source(tmp_path / "family")
    assert source.kind == "index"
    text = ws.family_pyproject_text("lab", source)
    assert tomllib.loads(text)["project"]["dependencies"] == [
        f"manim8-bridge=={scianim.__version__}",
        f"manim8-core=={scianim.__version__}",
    ]
    assert _sources(text) == {}


@pytest.mark.parametrize(
    ("value", "url", "ref"),
    [
        ("git:https://github.com/tknapen/manim8@v0.1.0a0", "https://github.com/tknapen/manim8", "v0.1.0a0"),
        ("git:git+https://github.com/tknapen/manim8@" + COMMIT, "https://github.com/tknapen/manim8", COMMIT),
        ("git:file:///home/user/manim8@claude/a-branch", "file:///home/user/manim8", "claude/a-branch"),
        ("git:https://github.com/tknapen/manim8", "https://github.com/tknapen/manim8", None),
        ("git:ssh://git@github.com/tknapen/manim8", "ssh://git@github.com/tknapen/manim8", None),
        ("git:ssh://git@github.com/tknapen/manim8@main", "ssh://git@github.com/tknapen/manim8", "main"),
        ("git:git@github.com:tknapen/manim8.git", "git@github.com:tknapen/manim8.git", None),
        ("git:git@github.com:tknapen/manim8.git@main", "git@github.com:tknapen/manim8.git", "main"),
    ],
)
def test_the_environment_variable_names_a_git_source(monkeypatch, tmp_path: Path, value, url, ref) -> None:
    monkeypatch.setenv(ws.BRIDGE_SOURCE_ENV, value)
    source = ws.bridge_source(tmp_path)  # the variable wins over the checkout this test runs from
    assert (source.kind, source.origin, source.url, source.ref) == ("git", ws.BRIDGE_SOURCE_ENV, url, ref)
    entry = _sources(ws.family_pyproject_text("lab", source))["manim8-core"]
    assert entry["git"] == url and entry.get("rev") == ref and entry["subdirectory"] == "packages/scianim_core"


def test_the_environment_variable_names_the_index_or_a_packages_directory(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(ws.BRIDGE_SOURCE_ENV, "index")
    assert ws.bridge_source(tmp_path).kind == "index"
    monkeypatch.setenv(ws.BRIDGE_SOURCE_ENV, f"path:{REPO / 'packages'}")
    source = ws.bridge_source(tmp_path)
    assert (source.kind, source.path) == ("path", (REPO / "packages").as_posix())
    bridge = _sources(ws.family_pyproject_text("lab", source))["manim8-bridge"]
    assert bridge == {"path": f"{(REPO / 'packages').as_posix()}/scianim_bridge", "editable": True}
    for bad in (f"path:{tmp_path}", "pip:manim8", "git:", "nonsense"):
        monkeypatch.setenv(ws.BRIDGE_SOURCE_ENV, bad)
        with pytest.raises(SpecError, match=ws.BRIDGE_SOURCE_ENV):
            ws.bridge_source(tmp_path)


def test_family_init_writes_the_source_of_a_git_install(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "ws"
    ws.init_workspace(root)
    record = {"url": "file:///srv/manim8", "vcs_info": {"vcs": "git", "commit_id": COMMIT}}
    _fake_distribution(monkeypatch, tmp_path, json.dumps(record))
    monkeypatch.setattr(ws, "DATA_ROOT", REPO / "missing")  # examples still come from SCIANIM_EXAMPLES
    monkeypatch.setenv("SCIANIM_EXAMPLES", str(REPO / "examples"))
    report = ws.InitReport()
    family = ws.init_family(
        root, "computational_neuroscience", from_example="computational_neuroscience", report=report
    )
    text = (family / "pyproject.toml").read_text()
    assert _sources(text)["manim8-bridge"] == {
        "git": "file:///srv/manim8",
        "rev": COMMIT,
        "subdirectory": "packages/scianim_bridge",
    }
    assert not (family / "uv.lock").exists()  # the example's lockfile pins development paths
    assert any("file:///srv/manim8 at " + COMMIT in note for note in report.notes)


def _broken_family(workspace: Path, extra: bool = False) -> Path:
    family = workspace / "families" / "computational_neuroscience"
    pyproject = family / "pyproject.toml"
    text = pyproject.read_text().replace("../../../", "../../../elsewhere/")  # the checkout as seen from a clone
    if extra:
        text = text.replace(
            'dependencies = ["manim8-bridge", "manim8-core"]',
            'dependencies = ["manim8-bridge", "manim8-core", "scipy>=1.13"]',
        )
        text += 'labtools = { path = "vendor/labtools" }\n'
    pyproject.write_text(text)
    return family


def test_sync_rewrites_path_sources_that_do_not_resolve(monkeypatch, workspace: Path) -> None:
    from scianim.families import resolve

    monkeypatch.delenv(ws.BRIDGE_SOURCE_ENV, raising=False)
    family = _broken_family(workspace, extra=True)
    ctx = load_family_context(family)
    before = (family / "pyproject.toml").read_text()
    assert ws.unresolved_path_sources(ctx.env_root, before) == [
        f"{ws.packages_relative_to(family).replace('../../../', '../../../elsewhere/')}/{d}"
        for d in ("scianim_bridge", "scianim_core")
    ]
    with pytest.raises(SpecError, match="without --locked"):
        sync_environment(ctx, locked=True)
    assert (family / "pyproject.toml").read_text() == before
    calls: list[list[str]] = []

    def fake_run(argv, cwd, timeout=1800, env=None):
        calls.append(argv[1:])
        return resolve.CommandResult(argv, 0, "", "", 0.1)

    monkeypatch.setattr(resolve, "run_command", fake_run)
    result = sync_environment(ctx)
    after = (family / "pyproject.toml").read_text()
    data = tomllib.loads(after)
    assert data["project"]["dependencies"] == ["manim8-bridge", "manim8-core", "scipy>=1.13"]
    relative = ws.packages_relative_to(family)
    assert _sources(after) == {
        "manim8-bridge": {"path": f"{relative}/scianim_bridge", "editable": True},
        "manim8-core": {"path": f"{relative}/scianim_core", "editable": True},
        "labtools": {"path": "vendor/labtools"},
    }
    assert ws.unresolved_path_sources(ctx.env_root, after) == []
    assert result.ok and "rewrote the bridge sources" in (result.note or "")
    assert calls[-1] == ["sync", "--no-dev"]
    # Sources that resolve are left alone, unless a rewrite is asked for.
    assert resolve.repair_bridge_sources(ctx) is None
    monkeypatch.setenv(ws.BRIDGE_SOURCE_ENV, "git:https://github.com/tknapen/manim8@v0.1.0a0")
    note = resolve.repair_bridge_sources(ctx, rewrite=True)
    assert note is not None and ws.BRIDGE_SOURCE_ENV in note
    assert _sources((family / "pyproject.toml").read_text())["manim8-bridge"]["rev"] == "v0.1.0a0"


def test_rewriting_sources_moves_between_every_mode() -> None:
    git = ws.BridgeSource("git", "git install", url="https://github.com/tknapen/manim8", ref=COMMIT)
    path = ws.BridgeSource("path", "checkout", path="../../packages")
    index = ws.BridgeSource("index", "release")
    text = ws.family_pyproject_text("lab", index)
    for source in (git, path, git, index, path, index):
        text = ws.rewrite_bridge_sources(text, source)
        assert _sources(text) == _sources(ws.family_pyproject_text("lab", source))
        assert tomllib.loads(text)["project"]["dependencies"] == ws.bridge_dependencies(source)
    # The example family's own pyproject, with its comments, is rewritten the same way.
    example = (REPO / "examples" / "families" / "computational_neuroscience" / "pyproject.toml").read_text()
    rewritten = ws.rewrite_bridge_sources(example, git)
    assert _sources(rewritten) == _sources(ws.family_pyproject_text("lab", git))
    assert "Test-only" in rewritten  # comments outside the sources table survive


def test_uv_comes_from_path_or_from_the_uv_package(monkeypatch) -> None:
    import shutil as shutil_module
    import sys

    from scianim.families import resolve

    control = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]
    assert any(dep.split(">")[0].split("=")[0].strip() == "uv" for dep in control["dependencies"])
    real_which = shutil_module.which
    monkeypatch.setattr(resolve.shutil, "which", lambda name: None if name == "uv" else real_which(name))
    import uv

    assert resolve.uv_executable() == uv.find_uv_bin()
    monkeypatch.setitem(sys.modules, "uv", None)  # the package is absent too
    assert resolve.uv_executable() is None
    with pytest.raises(SpecError, match="`uv` is not on PATH"):
        sync_environment(load_family_context(REPO / "examples" / "families" / "computational_neuroscience"))
