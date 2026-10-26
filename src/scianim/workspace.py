"""Workspaces: `workspace init`, `family init`, `project init` and `workspace list` (spec section 4).

Examples under the repository's `examples/` directory are read-only templates; these commands copy
them into a workspace, where environments, revisions and renders live.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

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


def examples_root() -> Path:
    for candidate in env_paths("SCIANIM_EXAMPLES"):
        if candidate.is_dir():
            return candidate
    root = repo_root()
    if root is not None and (root / "examples").is_dir():
        return root / "examples"
    raise SpecError(None, "no examples directory found; set SCIANIM_EXAMPLES or run from a source checkout")


def bundled_styles_root() -> Path | None:
    root = repo_root()
    return root / "styles" if root is not None and (root / "styles").is_dir() else None


def packages_root() -> Path:
    root = repo_root()
    if root is None:
        raise SpecError(
            None, "cannot locate the `packages/` directory; family environments need a source checkout in this version"
        )
    return root / "packages"


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


def family_pyproject_text(family_id: str, packages_relative: str) -> str:
    rel = packages_relative.replace(os.sep, "/")
    return f'''# Render environment for the {family_id} family: `uv sync` here creates .venv with Manim and the
# SciAnim render bridge. The control plane (`scianim`) is deliberately absent. uv.lock is shareable; .venv is not.
[project]
name = "family-{family_id.replace("_", "-")}"
version = "0.1.0"
description = "Pinned render environment for the {family_id} family."
requires-python = ">=3.12"
# scianim-core is listed explicitly so that uv applies its path source (ADR-008).
dependencies = ["scianim-bridge", "scianim-core"]

[dependency-groups]
dev = ["pytest>=8"]

[tool.uv]
package = false

[tool.uv.sources]
# Development: editable path dependencies on the source checkout. Bundle export replaces these.
scianim-bridge = {{ path = "{rel}/scianim_bridge", editable = true }}
scianim-core = {{ path = "{rel}/scianim_core", editable = true }}
'''


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
    dest.mkdir(parents=True)
    packages_relative = os.path.relpath(packages_root(), dest)
    if from_example:
        source = examples_root() / "families" / from_example
        if not (source / FAMILY_FILE).exists():
            raise SpecError(source, f"example family '{from_example}' not found")
        shutil.copy2(source / FAMILY_FILE, dest / FAMILY_FILE)
        rewrite_top_level_keys(dest / FAMILY_FILE, {"id": family_id, **({"title": yaml_quote(title)} if title else {})})
        for extra in ("README.md", ".python-version"):
            if (source / extra).exists():
                shutil.copy2(source / extra, dest / extra)
        example_relative = os.path.relpath(packages_root(), source)
        if (source / "uv.lock").exists() and example_relative == packages_relative:
            shutil.copy2(source / "uv.lock", dest / "uv.lock")
        elif (source / "uv.lock").exists():
            report.notes.append(
                f"{dest}: lockfile not copied because the path to packages/ differs; `family env sync` will create one"
            )
    else:
        (dest / FAMILY_FILE).write_text(
            family_yaml_text(family_id, title or family_id.replace("_", " ").title(), style_ref), encoding="utf-8"
        )
        (dest / ".python-version").write_text("3.12\n", encoding="utf-8")
    (dest / "pyproject.toml").write_text(family_pyproject_text(family_id, packages_relative), encoding="utf-8")
    for name in ("components", "assets"):
        (dest / name).mkdir(exist_ok=True)
    report.created.append(dest / FAMILY_FILE)
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
    "DEFAULT_STYLE_REF",
    "EXAMPLE_FAMILY",
    "EXAMPLE_PROJECT",
    "FamilyNode",
    "InitReport",
    "ProjectNode",
    "WorkspaceScan",
    "example_projects",
    "examples_root",
    "find_workspace",
    "init_family",
    "init_project",
    "init_workspace",
    "load_workspace",
    "repo_root",
    "scan_workspace",
]
