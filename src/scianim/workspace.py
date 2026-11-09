"""Workspaces: `workspace init`, `family init`, `project init` and `workspace list` (spec section 4).

Examples under the repository's `examples/` directory are read-only templates; these commands copy
them into a workspace, where environments, revisions and renders live.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tomllib
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Literal

from scianim.config.loader import SpecError, load_animation, load_family, load_workspace_manifest
from scianim.families.resolve import FAMILY_FILE, GROUP_FILE, locate_family, nearest_family
from scianim.project import ANIMATION_FILE, STORYBOARD_FILE, WORKSPACE_FILE, Project, env_paths
from scianim_core import REGISTRY, WorkspaceManifest, split_style_ref

EXAMPLE_FAMILY = "computational_neuroscience"
EXAMPLE_PROJECT = "divisive_normalization"
DEFAULT_STYLE_REF = "tomas_scientific@0.1.0"
PROJECT_TEMPLATE_FILES = ("animation.yaml", "storyboard.yaml", "README.md")
PROJECT_TEMPLATE_DIRS = ("data", "references")
SKIP_DIRS = {".scianim", "renders", "revisions", ".venv", "__pycache__", "code", "node_modules"}

_SLUG = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def rewrite_top_level_keys(path: Path, updates: dict[str, str | None]) -> None:
    """Set or drop top-level scalar keys in a YAML file without reformatting anything else."""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    seen: set[str] = set()
    result: list[str] = []
    for line in lines:
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):", line)
        key = match.group(1) if match else None
        if key in updates:
            seen.add(key)
            value = updates[key]
            if value is None:
                continue
            result.append(f"{key}: {value}\n")
        else:
            result.append(line)
    for key, value in updates.items():
        if key not in seen and value is not None:
            result.insert(1, f"{key}: {value}\n")
    path.write_text("".join(result), encoding="utf-8")


def yaml_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def repo_root() -> Path | None:
    """The source checkout this package runs from, if it is one (editable install)."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists() and (parent / "packages").is_dir():
            return parent
    return None


DATA_ROOT = Path(__file__).resolve().parent / "_data"
"""The styles and examples an installed wheel carries (ADR-037); a source checkout uses its own directories."""


def examples_root() -> Path:
    for candidate in env_paths("SCIANIM_EXAMPLES"):
        if candidate.is_dir():
            return candidate
    root = repo_root()
    if root is not None and (root / "examples").is_dir():
        return root / "examples"
    if (DATA_ROOT / "examples").is_dir():
        return DATA_ROOT / "examples"
    raise SpecError(None, "no examples directory found; set SCIANIM_EXAMPLES or reinstall manim8")


def bundled_styles_root() -> Path | None:
    root = repo_root()
    if root is not None and (root / "styles").is_dir():
        return root / "styles"
    return DATA_ROOT / "styles" if (DATA_ROOT / "styles").is_dir() else None


def packages_root() -> Path | None:
    """The checkout's `packages/` directory, which family environments install the bridge from in development;
    None for an installed control plane, whose families take the bridge from the package index (ADR-037)."""
    root = repo_root()
    return root / "packages" if root is not None else None


def packages_relative_to(directory: Path) -> str | None:
    """The path from a family directory to the checkout's `packages/`, or None in release mode."""
    root = packages_root()
    return os.path.relpath(root, directory).replace(os.sep, "/") if root is not None else None


BRIDGE_SOURCE_ENV = "SCIANIM_BRIDGE_SOURCE"
"""Overrides where family environments take the bridge and the contracts from: `index`, `git:<url>@<ref>` or
`path:<packages dir>` (ADR-043)."""

BRIDGE_PACKAGES = {"manim8-bridge": "scianim_bridge", "manim8-core": "scianim_core"}
"""The two distributions a family environment installs, and their directories under the repository's `packages/`."""


@dataclass(frozen=True)
class BridgeSource:
    """Where a family environment takes `manim8-bridge` and `manim8-core` from (ADR-043).

    `path`: a `packages/` directory, written as given (relative to the family directory, or absolute).
    `git`: the repository `url` at `ref` (a commit for a git-installed control plane), from `packages/<name>`.
    `index`: the package index at the control plane's version."""

    kind: Literal["path", "git", "index"]
    origin: str
    """Why this source: `checkout`, `git install`, `release` or the environment variable."""
    path: str | None = None
    url: str | None = None
    ref: str | None = None

    def describe(self) -> str:
        if self.kind == "path":
            return f"the packages at {self.path} ({self.origin})"
        if self.kind == "git":
            return f"{self.url} at {self.ref or 'its default branch'} ({self.origin})"
        from scianim import __version__

        return f"the package index at {__version__} ({self.origin})"


def control_plane_direct_url() -> dict[str, object] | None:
    """The installed `manim8` distribution's PEP 610 record (`direct_url.json`), or None for an install from an
    index or a wheel file found there, or when no distribution is installed."""
    try:
        text = metadata.distribution("manim8").read_text("direct_url.json")
    except metadata.PackageNotFoundError:
        return None
    if not text:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _split_git_ref(value: str) -> tuple[str, str | None]:
    """`<url>@<ref>` -> (url, ref); the `@` of a user name (`git@host:...`, `ssh://git@host/...`) is no ref."""
    head, at, tail = value.rpartition("@")
    if not at or not head or not tail or ":" in tail:  # a git ref never contains a colon
        return value, None
    if "://" in head and "/" not in head.split("://", 1)[1]:
        return value, None  # `scheme://user@host/path`: the `@` sits before the path
    if "/" not in head and ":" not in head:
        return value, None  # `user@host:path`
    return head, tail


def parse_bridge_source(value: str, base: Path | None = None) -> BridgeSource:
    """Read a `SCIANIM_BRIDGE_SOURCE` value: `index`, `git:<url>[@<ref>]` or `path:<packages dir>`. A relative
    packages directory is taken from `base` (default: the working directory) and written as an absolute path."""
    origin = BRIDGE_SOURCE_ENV
    value = value.strip()
    if value == "index":
        return BridgeSource("index", origin)
    kind, sep, rest = value.partition(":")
    if sep and kind == "git" and rest:
        url, ref = _split_git_ref(rest)
        return BridgeSource("git", origin, url=url.removeprefix("git+"), ref=ref)
    if sep and kind == "path" and rest:
        packages = Path(rest).expanduser()
        if not packages.is_absolute():
            packages = (base or Path.cwd()) / packages
        packages = packages.resolve()
        missing = [name for name in BRIDGE_PACKAGES.values() if not (packages / name / "pyproject.toml").exists()]
        if missing:
            raise SpecError(None, f"{BRIDGE_SOURCE_ENV}: {packages} holds no {', '.join(missing)} package")
        return BridgeSource("path", origin, path=packages.as_posix())
    raise SpecError(
        None, f"{BRIDGE_SOURCE_ENV} must be `index`, `git:<url>@<ref>` or `path:<packages dir>`, not {value!r}"
    )


def bridge_source(family_dir: Path) -> BridgeSource:
    """Where a family environment created at `family_dir` takes the bridge and the contracts from: the
    environment variable when set; a source checkout's own `packages/`; the commit a git-installed control plane
    came from; otherwise the package index at the control plane's version (ADR-043)."""
    override = os.environ.get(BRIDGE_SOURCE_ENV, "").strip()
    if override:
        return parse_bridge_source(override)
    relative = packages_relative_to(family_dir)
    if relative is not None:
        return BridgeSource("path", "checkout", path=relative)
    record = control_plane_direct_url()
    vcs = record.get("vcs_info") if record else None
    if record and isinstance(vcs, dict) and vcs.get("vcs") == "git" and vcs.get("commit_id"):
        url = str(record.get("url", "")).removeprefix("git+")
        subdirectory = str(record.get("subdirectory") or "").strip("/")
        if url and not subdirectory:
            return BridgeSource("git", "git install", url=url, ref=str(vcs["commit_id"]))
    return BridgeSource("index", "release")


WORKSPACE_GITIGNORE = """# Written by `scianim workspace init` (ADR-043). Renders, job records, caches and environments are rebuilt from
# the files that stay versioned: specs, styles, code/, data/, revisions/, feedback/ and each family's uv.lock.
renders/
.scianim/
.venv/
# Manim's own media folder, when Manim runs outside a job (a job keeps its media under .scianim/).
media/
!assets/**/media/
!families/**/assets/**/media/
__pycache__/
*.pyc
"""


def write_workspace_gitignore(root: Path) -> Path:
    """Write the workspace's `.gitignore`, or add the lines an existing one lacks."""
    target = root / ".gitignore"
    if not target.exists():
        target.write_text(WORKSPACE_GITIGNORE, encoding="utf-8")
        return target
    text = target.read_text(encoding="utf-8")
    present = {line.strip() for line in text.splitlines()}
    missing = [line for line in WORKSPACE_GITIGNORE.splitlines() if line.strip() and line.strip() not in present]
    if any(not line.startswith("#") for line in missing):
        target.write_text(text.rstrip("\n") + "\n\n" + "\n".join(missing) + "\n", encoding="utf-8")
    return target


def find_workspace(start: Path) -> Path | None:
    start = start.resolve()
    for candidate in (start, *start.parents):
        if (candidate / WORKSPACE_FILE).exists():
            return candidate
    return None


def load_workspace(root: Path) -> WorkspaceManifest:
    return load_workspace_manifest(root / WORKSPACE_FILE)


def require_slug(value: str, what: str) -> str:
    if not _SLUG.match(value):
        raise SpecError(
            None, f"{what} '{value}' must be a slug: lowercase letters, digits and underscores, starting with a letter"
        )
    return value


@dataclass
class InitReport:
    created: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def init_workspace(
    target: Path, workspace_id: str | None = None, styles_source: Path | None = None, with_example: bool = False
) -> InitReport:
    report = InitReport()
    target = target.resolve()
    if (target / WORKSPACE_FILE).exists():
        raise SpecError(target / WORKSPACE_FILE, "already a workspace")
    if find_workspace(target.parent) is not None:
        raise SpecError(target, f"nested inside another workspace ({find_workspace(target.parent)})")
    target.mkdir(parents=True, exist_ok=True)
    ident = require_slug(
        workspace_id or re.sub(r"[^a-z0-9_]+", "_", target.name.lower()).strip("_") or "workspace", "workspace id"
    )
    manifest = WorkspaceManifest(schema_version="1.0", id=ident)
    (target / WORKSPACE_FILE).write_text(
        f'schema_version: "1.0"\nid: {manifest.id}\ndescription: null\n', encoding="utf-8"
    )
    report.created.append(target / WORKSPACE_FILE)
    report.created.append(write_workspace_gitignore(target))
    for name in ("styles", "families", "assets"):
        (target / name).mkdir(exist_ok=True)
    source = styles_source or bundled_styles_root()
    if source is None:
        report.notes.append("no bundled styles found to copy; add sheets under styles/<name>/<version>/style.yaml")
    else:
        copied = copy_styles(source, target / "styles")
        report.created.extend(copied)
    if with_example:
        family_dir = init_family(target, EXAMPLE_FAMILY, from_example=EXAMPLE_FAMILY, report=report)
        for name in example_projects(EXAMPLE_FAMILY):
            init_project(target, EXAMPLE_FAMILY, name, from_example=name, report=report)
        report.notes.append(f"run `scianim family env sync {family_dir}` before rendering")
    return report


def example_projects(family: str) -> list[str]:
    """Names of the project templates nested under an example family, in sorted order."""
    family_dir = examples_root() / "families" / family
    return sorted(p.name for p in family_dir.iterdir() if p.is_dir() and (p / ANIMATION_FILE).exists())


def copy_styles(source: Path, destination: Path) -> list[Path]:
    copied: list[Path] = []
    for name_dir in sorted(p for p in source.iterdir() if p.is_dir()):
        for version_dir in sorted(p for p in name_dir.iterdir() if p.is_dir()):
            sheet = version_dir / "style.yaml"
            if not sheet.exists():
                continue
            target = destination / name_dir.name / version_dir.name / "style.yaml"
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(sheet, target)
            copied.append(target)
    return copied


def _toml_string(value: str) -> str:
    return json.dumps(value)  # a JSON string is a valid TOML basic string


def _as_source(source: BridgeSource | str | None) -> BridgeSource:
    if isinstance(source, BridgeSource):
        return source
    if source is None:
        return BridgeSource("index", "release")
    return BridgeSource("path", "checkout", path=source.replace(os.sep, "/"))


def bridge_dependencies(source: BridgeSource | str | None) -> list[str]:
    """The family's requirements on the bridge and the contracts. Both are listed, so that uv applies a source
    to `manim8-core` too (it is also a dependency of the bridge, ADR-008); from the index both are pinned at the
    control plane's version, so the two sides speak the same contracts (ADR-037)."""
    from scianim import __version__

    if _as_source(source).kind == "index":
        return [f"{name}=={__version__}" for name in BRIDGE_PACKAGES]
    return list(BRIDGE_PACKAGES)


def bridge_sources_block(source: BridgeSource | str | None) -> str:
    """The `[tool.uv.sources]` table for a path or git source; empty for the index."""
    source = _as_source(source)
    if source.kind == "index":
        return ""
    lines = ["[tool.uv.sources]"]
    if source.kind == "path":
        assert source.path is not None
        root = source.path.rstrip("/")
        lines.append(
            "# Development: editable path dependencies on a manim8 checkout. `family env sync` rewrites them when"
            "\n# they do not resolve (the workspace was moved or cloned elsewhere); bundle export removes them."
        )
        for name, directory in BRIDGE_PACKAGES.items():
            lines.append(f"{name} = {{ path = {_toml_string(f'{root}/{directory}')}, editable = true }}")
    else:
        assert source.url is not None
        what = "the commit the control plane was installed from" if source.origin == "git install" else source.origin
        lines.append(f"# The bridge and the contracts from git: {what} (ADR-043).")
        rev = f", rev = {_toml_string(source.ref)}" if source.ref else ""
        for name, directory in BRIDGE_PACKAGES.items():
            lines.append(
                f"{name} = {{ git = {_toml_string(source.url)}{rev}, "
                f"subdirectory = {_toml_string(f'packages/{directory}')} }}"
            )
    return "\n".join(lines) + "\n"


def family_pyproject_text(family_id: str, source: BridgeSource | str | None) -> str:
    """The family's environment definition. `source` says where the bridge and the contracts come from
    (`bridge_source`): from a source checkout, editable path dependencies on it; from a git-installed control
    plane, the same commit; otherwise the package index at the control plane's own version (ADR-037, ADR-043).
    A string is a path to the checkout's `packages/`; None is the index."""
    source = _as_source(source)
    deps = ", ".join(_toml_string(d) for d in bridge_dependencies(source))
    head = f"""# Render environment for the {family_id} family: `uv sync` here creates .venv with Manim and the
# manim8 render bridge. The control plane (`manim8`) is deliberately absent. uv.lock is shareable; .venv is not.
[project]
name = "family-{family_id.replace("_", "-")}"
version = "0.1.0"
description = "Pinned render environment for the {family_id} family."
requires-python = ">=3.12"
"""
    tail = """
[dependency-groups]
dev = ["pytest>=8"]

[tool.uv]
package = false
"""
    if source.kind == "index":
        return (
            head
            + "# Release: the bridge and the contracts at the control plane's version, from the package index.\n"
            + f"dependencies = [{deps}]\n"
            + tail
        )
    return (
        head
        + "# manim8-core is listed explicitly so that uv applies its source (ADR-008).\n"
        + f"dependencies = [{deps}]\n"
        + tail
        + "\n"
        + bridge_sources_block(source)
    )


def declared_bridge_sources(pyproject_text: str) -> dict[str, dict[str, object]]:
    """The `[tool.uv.sources]` entries a family environment declares for the bridge and the contracts."""
    try:
        data = tomllib.loads(pyproject_text)
    except tomllib.TOMLDecodeError:
        return {}
    sources = data.get("tool", {}).get("uv", {}).get("sources", {})
    return {name: dict(sources[name]) for name in BRIDGE_PACKAGES if isinstance(sources.get(name), dict)}


def unresolved_path_sources(env_root: Path, pyproject_text: str) -> list[str]:
    """Path sources for the bridge or the contracts that point at no package from `env_root` (a workspace that
    was moved, or cloned onto another machine)."""
    broken: list[str] = []
    for entry in declared_bridge_sources(pyproject_text).values():
        path = entry.get("path")
        if isinstance(path, str) and not _path_source_resolves(env_root, path):
            broken.append(path)
    return broken


def _path_source_resolves(env_root: Path, path: str) -> bool:
    """Whether uv finds a package at `path` from `env_root`. uv joins the two lexically and refuses a relative path
    that climbs above the filesystem root, which the operating system would quietly read as the root itself."""
    relative = Path(path)
    if not relative.is_absolute():
        level = len(env_root.resolve().parts) - 1
        for part in relative.parts:
            level += -1 if part == ".." else 0 if part == "." else 1
            if level < 0:
                return False
    return (env_root / relative / "pyproject.toml").is_file()


_BRIDGE_KEY = re.compile(r"^\s*\"?(manim8-bridge|manim8-core)\"?\s*=")
_BRIDGE_SUBTABLE = re.compile(r"^\s*\[tool\.uv\.sources\.\"?(manim8-bridge|manim8-core)\"?\]\s*$")
_BRIDGE_REQUIREMENT = re.compile(r"([\"'])(manim8-bridge|manim8-core)(?![\w.-])[^\"']*\1")


def rewrite_bridge_sources(text: str, source: BridgeSource | str | None) -> str:
    """The family pyproject with its requirements on, and sources for, the bridge and the contracts set for
    `source`. Everything else (other dependencies, other sources, comments outside the sources table) is kept."""
    source = _as_source(source)
    wanted = dict(zip(BRIDGE_PACKAGES, bridge_dependencies(source), strict=True))
    text = _BRIDGE_REQUIREMENT.sub(lambda m: f"{m.group(1)}{wanted[m.group(2)]}{m.group(1)}", text)
    kept: list[tuple[str | None, str]] = []
    table: str | None = None
    skipping = False
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("[") and not stripped.startswith("[["):
            skipping = bool(_BRIDGE_SUBTABLE.match(line))
            table = None if skipping else stripped
            if skipping or stripped == "[tool.uv.sources]":
                continue  # the header is written again below when entries remain
        if skipping:
            continue
        if table == "[tool.uv.sources]" and (stripped.startswith("#") or _BRIDGE_KEY.match(line)):
            continue  # the comments in this table are the templates' own
        kept.append((table, line))
    others = [line for t, line in kept if t == "[tool.uv.sources]" and line.strip()]
    body = "".join(line for t, line in kept if t != "[tool.uv.sources]").rstrip("\n") + "\n"
    block = bridge_sources_block(source)
    if not block and not others:
        return body
    if not block:
        block = "[tool.uv.sources]\n"
    return body + "\n" + block + "".join(others)


def family_yaml_text(family_id: str, title: str, style_ref: str) -> str:
    name, version = split_style_ref(style_ref)
    kinds = "\n".join(f"  - {kind}" for kind in REGISTRY if kind != "custom")
    return f'''schema_version: "1.0"
id: {family_id}
title: {title}
style:
  name: {name}
  version: "{version}"
environment:
  manager: uv
  project_root: "."
  lockfile: "uv.lock"
  install_policy: explicit
system_requirements:
  - kind: library
    name: cairo
    note: "pycairo links against the system Cairo library on Linux."
  - kind: font
    name: "DejaVu Sans"
    optional: true
    note: "Falls back to the style's font_fallbacks when absent."
shared_assets: []
components:
{kinds}
schema_extensions: []
'''


def init_family(
    workspace: Path,
    family_id: str,
    style_ref: str = DEFAULT_STYLE_REF,
    from_example: str | None = None,
    title: str | None = None,
    report: InitReport | None = None,
) -> Path:
    report = report if report is not None else InitReport()
    require_slug(family_id, "family id")
    workspace = workspace.resolve()
    if not (workspace / WORKSPACE_FILE).exists():
        raise SpecError(workspace, "not a workspace; run `scianim workspace init` first")
    dest = workspace / "families" / family_id
    if dest.exists():
        raise SpecError(dest, "family directory already exists")
    source = bridge_source(dest)
    dest.mkdir(parents=True)
    if from_example:
        example = examples_root() / "families" / from_example
        if not (example / FAMILY_FILE).exists():
            raise SpecError(example, f"example family '{from_example}' not found")
        shutil.copy2(example / FAMILY_FILE, dest / FAMILY_FILE)
        rewrite_top_level_keys(dest / FAMILY_FILE, {"id": family_id, **({"title": yaml_quote(title)} if title else {})})
        for extra in ("README.md", ".python-version"):
            if (example / extra).exists():
                shutil.copy2(example / extra, dest / extra)
        example_relative = packages_relative_to(example)
        if (example / "uv.lock").exists() and source.origin == "checkout" and example_relative == source.path:
            shutil.copy2(example / "uv.lock", dest / "uv.lock")
        elif (example / "uv.lock").exists():
            report.notes.append(
                f"{dest}: the example's lockfile pins development paths and was not copied; "
                "`family env sync` will create one"
            )
    else:
        (dest / FAMILY_FILE).write_text(
            family_yaml_text(family_id, title or family_id.replace("_", " ").title(), style_ref), encoding="utf-8"
        )
        (dest / ".python-version").write_text("3.12\n", encoding="utf-8")
    (dest / "pyproject.toml").write_text(family_pyproject_text(family_id, source), encoding="utf-8")
    for name in ("components", "assets"):
        (dest / name).mkdir(exist_ok=True)
    report.created.append(dest / FAMILY_FILE)
    if source.origin != "checkout":
        report.notes.append(f"{dest}: the render environment takes the bridge from {source.describe()}")
    return dest


def _find_example_project(name: str) -> Path:
    for candidate in sorted(examples_root().glob(f"families/*/{name}")):
        if (candidate / ANIMATION_FILE).exists():
            return candidate
    raise SpecError(examples_root(), f"example project '{name}' not found")


def init_project(
    workspace: Path,
    family_id: str,
    name: str,
    from_example: str | None = None,
    title: str | None = None,
    report: InitReport | None = None,
) -> Path:
    report = report if report is not None else InitReport()
    require_slug(name, "project name")
    workspace = workspace.resolve()
    family_dir = workspace / "families" / family_id
    if not (family_dir / FAMILY_FILE).exists():
        raise SpecError(
            family_dir, f"family '{family_id}' is not in this workspace; run `scianim family init {family_id}` first"
        )
    dest = family_dir / name
    if dest.exists():
        raise SpecError(dest, "project directory already exists")
    dest.mkdir(parents=True)
    if from_example:
        source = _find_example_project(from_example)
        for filename in PROJECT_TEMPLATE_FILES:
            if (source / filename).exists():
                shutil.copy2(source / filename, dest / filename)
        for dirname in PROJECT_TEMPLATE_DIRS:
            if (source / dirname).is_dir():
                shutil.copytree(source / dirname, dest / dirname, ignore=shutil.ignore_patterns(*SKIP_DIRS))
        rewrite_top_level_keys(
            dest / ANIMATION_FILE,
            {"id": name, "family": None, **({"title": yaml_quote(title)} if title else {})},
        )
        if (dest / STORYBOARD_FILE).exists():
            rewrite_top_level_keys(dest / STORYBOARD_FILE, {"project_id": name})
    else:
        family = load_family(family_dir / FAMILY_FILE)
        (dest / ANIMATION_FILE).write_text(
            f'''schema_version: "1.0"
id: {name}
title: "{title or name.replace("_", " ").capitalize()}"
sources: []
output:
  duration_seconds: 15
  width_px: 1920
  height_px: 1080
  aspect_ratio: "16:9"
  fps: 30
  container: mp4
  video_codec: h264
  audio: none
style:
  name: {family.style.name}
  version: "{family.style.version}"
  overrides: {{}}
equations: []
objective: "One mechanism in a brief clip: say what moves, and what the viewer should see it do."
scientific_constraints: []
timeline: []
direction:
  tone: null
  avoid: []
extensions: {{}}
''',
            encoding="utf-8",
        )
    for dirname in ("code", "data", "references", "feedback"):
        (dest / dirname).mkdir(exist_ok=True)
    report.created.append(dest / ANIMATION_FILE)
    return dest


@dataclass
class ProjectNode:
    id: str
    path: Path
    title: str
    has_storyboard: bool
    groups: list[str]


@dataclass
class FamilyNode:
    id: str
    path: Path
    has_environment: bool
    has_lockfile: bool
    projects: list[ProjectNode] = field(default_factory=list)


@dataclass
class WorkspaceScan:
    root: Path
    families: list[FamilyNode] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def _iter_files(root: Path, filename: str) -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        if filename in filenames:
            found.append(Path(dirpath) / filename)
    return sorted(found)


def scan_workspace(root: Path) -> WorkspaceScan:
    """Inventory families, groups and projects; report duplicate ids and orphan projects."""
    root = root.resolve()
    scan = WorkspaceScan(root=root)
    families_by_path: dict[Path, FamilyNode] = {}
    ids_seen: dict[str, Path] = {}
    for family_file in _iter_files(root, FAMILY_FILE):
        from scianim.families.resolve import load_family_context

        try:
            ctx = load_family_context(family_file)
        except SpecError as exc:
            scan.problems.append(str(exc))
            continue
        if ctx.manifest.id in ids_seen:
            scan.problems.append(
                f"family id '{ctx.manifest.id}' is declared at both {ids_seen[ctx.manifest.id]} and {family_file}"
            )
        ids_seen.setdefault(ctx.manifest.id, family_file)
        node = FamilyNode(ctx.manifest.id, ctx.root, ctx.venv_python.exists(), ctx.lockfile.exists())
        families_by_path[ctx.root] = node
        scan.families.append(node)
    project_ids: dict[str, Path] = {}
    for animation_file in _iter_files(root, ANIMATION_FILE):
        project = Project(animation_file.parent)
        try:
            spec = load_animation(animation_file)
        except SpecError as exc:
            scan.problems.append(str(exc))
            continue
        if spec.id in project_ids:
            scan.problems.append(f"project id '{spec.id}' is used by both {project_ids[spec.id]} and {project.root}")
        project_ids.setdefault(spec.id, project.root)
        try:
            lookup = locate_family(project.root, spec.family, [root / "families"])
        except SpecError as exc:
            scan.problems.append(f"{project.root}: {exc.message}")
            continue
        node = families_by_path.get(lookup.context.root)
        if node is None:
            scan.problems.append(f"{project.root}: family at {lookup.context.root} is outside the workspace")
            continue
        node.projects.append(
            ProjectNode(
                spec.id,
                project.root,
                spec.title,
                project.storyboard_path.exists(),
                [g.manifest.id for g in lookup.groups],
            )
        )
    for group_file in _iter_files(root, GROUP_FILE):
        if nearest_family(group_file.parent) is None:
            scan.problems.append(f"{group_file}: group is not inside a family directory")
    return scan


__all__ = [
    "BRIDGE_SOURCE_ENV",
    "DEFAULT_STYLE_REF",
    "EXAMPLE_FAMILY",
    "EXAMPLE_PROJECT",
    "WORKSPACE_GITIGNORE",
    "BridgeSource",
    "FamilyNode",
    "InitReport",
    "ProjectNode",
    "WorkspaceScan",
    "bridge_source",
    "example_projects",
    "examples_root",
    "family_pyproject_text",
    "find_workspace",
    "init_family",
    "init_project",
    "init_workspace",
    "load_workspace",
    "repo_root",
    "rewrite_bridge_sources",
    "scan_workspace",
    "write_workspace_gitignore",
]
