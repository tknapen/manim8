"""Export a project or a whole family as a portable bundle (spec 12.1 and 12.2).

Rules enforced here: no `.venv`, `.scianim`, caches, secrets or symlinks; no absolute paths in text
files (fail, or redact on request); PDFs and third-party reference images omitted by default and
recorded with relink instructions; a lockfile and install notes included; deterministic member order and
fixed timestamps so the checksums mean something.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import os
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from ruamel.yaml import YAML

from scianim import __version__
from scianim.config.loader import SpecError, load_animation, load_family
from scianim.families.resolve import FamilyContext, load_family_context, nearest_family
from scianim.planning.checks import validate_project
from scianim.project import Project
from scianim.revisions.store import list_revisions
from scianim.workspace import packages_root
from scianim_core import REGISTRY_VERSION
from scianim_core.bundle import (
    BUNDLE_ROOT,
    CHECKSUM_FILE,
    BundleEnvironment,
    BundleManifest,
    BundleProject,
    InclusionPolicy,
    OmittedSource,
)
from scianim_core.style import split_style_ref

SKIP_DIRS = {".venv", ".scianim", "__pycache__", ".git", ".pytest_cache", ".ruff_cache", "node_modules"}
SKIP_FILES = {".env", ".DS_Store"}
SECRET_PATTERNS = re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]")
TEXT_SUFFIXES = {".yaml", ".yml", ".json", ".md", ".txt", ".py", ".html", ".srt", ".csv", ".toml", ".typ"}
PROJECT_DIRS = ("data", "references", "code", "revisions", "feedback", "proposals")
DISTRIBUTABLE_IMAGE_ROLES = {"illustrative_data", "empirical_data", "explanatory_text"}
FIXED_TIME = (2020, 1, 1, 0, 0, 0)


@dataclass
class ExportOptions:
    include_renders: bool = False
    include_source_assets: bool = False
    redact_paths: bool = False


@dataclass
class _Member:
    relative: str
    data: bytes


@dataclass
class ExportResult:
    archive: Path
    manifest: BundleManifest
    members: list[str] = field(default_factory=list)


def _iter_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            if name in SKIP_FILES:
                continue
            path = Path(dirpath) / name
            if path.is_symlink():
                raise SpecError(path, "symbolic links are not exported")
            found.append(path)
    return found


def _style_chain(project: Project, name: str, version: str) -> list[tuple[str, Path]]:
    """Every sheet from the selected theme up its `inherits` chain, with its file."""
    chain: list[tuple[str, Path]] = []
    yaml = YAML(typ="safe")
    ref: str | None = f"{name}@{version}"
    seen: set[str] = set()
    while ref and ref not in seen:
        seen.add(ref)
        sheet_name, sheet_version = split_style_ref(ref)
        found = next(
            (
                d / sheet_name / sheet_version / "style.yaml"
                for d in project.style_search_dirs()
                if (d / sheet_name / sheet_version / "style.yaml").exists()
            ),
            None,
        )
        if found is None:
            raise SpecError(None, f"style sheet {ref} not found in {project.style_search_dirs()}")
        chain.append((ref, found))
        data = yaml.load(found.read_text(encoding="utf-8")) or {}
        ref = data.get("inherits")
    return chain


def _absolute_path_hits(text: str, roots: list[str]) -> list[str]:
    return [root for root in roots if root and root in text]


def export_bundle(target: Path, archive: Path, options: ExportOptions | None = None) -> ExportResult:
    """Bundle one project (a project directory) or a whole family (a family directory)."""
    options = options or ExportOptions()
    target = target.resolve()
    family_ctx: FamilyContext
    projects: list[Project]
    if (target / "family.yaml").exists():
        family_ctx = load_family_context(target)
        kind = "family"
        projects = [
            Project(p.parent)
            for p in sorted(target.rglob("animation.yaml"))
            if not any(part in SKIP_DIRS or part in ("revisions", "renders") for part in p.relative_to(target).parts)
        ]
    elif (target / "animation.yaml").exists():
        nearest = nearest_family(target)
        if nearest is None:
            raise SpecError(target, "the project is not inside a family directory; bundles carry their family")
        family_ctx = nearest
        kind = "project"
        projects = [Project(target)]
    else:
        raise SpecError(target, "neither a project (animation.yaml) nor a family (family.yaml)")
    if not projects:
        raise SpecError(target, "the family has no projects")

    members: list[_Member] = []
    manifest_projects: list[BundleProject] = []
    omitted: list[OmittedSource] = []
    styles: dict[str, Path] = {}
    notes: list[str] = []
    workspace_root = projects[0].workspace_root()
    roots = [str(workspace_root) if workspace_root else "", str(Path.home())]

    def add_file(relative: str, path: Path) -> None:
        data = path.read_bytes()
        if path.suffix.lower() in TEXT_SUFFIXES:
            text = data.decode("utf-8", errors="replace")
            hits = _absolute_path_hits(text, roots)
            if hits:
                if not options.redact_paths:
                    raise SpecError(
                        path, f"contains an absolute path ({hits[0]}); re-run with --redact-paths or remove it"
                    )
                for hit in hits:
                    text = text.replace(hit, "<redacted-path>")
                data = text.encode("utf-8")
                notes.append(f"redacted absolute paths in {relative}")
            if path.suffix in (".env",) or (
                SECRET_PATTERNS.search(text) and path.name.lower().endswith((".env", ".ini", ".cfg", "secrets.yaml"))
            ):
                raise SpecError(path, "looks like a credentials file; bundles never carry secrets")
        members.append(_Member(relative, data))

    for project in projects:
        spec = load_animation(project.animation_path)
        base = f"projects/{spec.id}"
        report = validate_project(project)
        included_sources: set[str] = set()
        for source in spec.sources:
            resolved = report.source_paths.get(source.id)
            distributable = source.type in ("csv", "markdown", "text") or (
                source.type == "image" and source.role in DISTRIBUTABLE_IMAGE_ROLES
            )
            if source.type == "project":
                omitted.append(
                    OmittedSource(
                        project_id=spec.id,
                        source_id=source.id,
                        type=source.type,
                        role=source.role,
                        path=str(source.path),
                        reason="references another project",
                        relink="import that project too, or point the source at a copy",
                    )
                )
                continue
            if resolved is None:
                omitted.append(
                    OmittedSource(
                        project_id=spec.id,
                        source_id=source.id,
                        type=source.type,
                        role=source.role,
                        path=str(source.path),
                        reason="file not found at export",
                        relink=f"place the file at {source.path} inside the project",
                    )
                )
                continue
            if distributable or options.include_source_assets:
                included_sources.add(str(source.path))
            else:
                why = (
                    "source PDF"
                    if source.type == "pdf"
                    else f"{source.type} with role {source.role} (third-party reference)"
                )
                omitted.append(
                    OmittedSource(
                        project_id=spec.id,
                        source_id=source.id,
                        type=source.type,
                        role=source.role,
                        path=str(source.path),
                        reason=f"{why}: not redistributed by default",
                        relink=f"copy the file to projects/{spec.id}/{source.path} after import, or export with --include-source-assets",
                    )
                )
        for path in _iter_files(project.root):
            relative = path.relative_to(project.root).as_posix()
            top = relative.split("/")[0]
            if relative in ("animation.yaml", "storyboard.yaml", "README.md"):
                add_file(f"{base}/{relative}", path)
                continue
            if top == "renders":
                if options.include_renders:
                    add_file(f"{base}/{relative}", path)
                continue
            if top not in PROJECT_DIRS:
                continue
            if top in ("data", "references"):
                declared = {str(s.path) for s in spec.sources}
                if relative in included_sources:
                    add_file(f"{base}/{relative}", path)
                elif relative in declared:
                    continue  # an omitted source, recorded above with relink instructions
                elif top == "data" or path.suffix.lower() in (".md", ".txt"):
                    add_file(f"{base}/{relative}", path)  # undeclared data travels; undeclared references only as text
                continue
            add_file(f"{base}/{relative}", path)
        for ref, sheet in _style_chain(project, spec.style.name, spec.style.version):
            styles.setdefault(ref, sheet)
        manifest_projects.append(
            BundleProject(
                id=spec.id,
                path=base,
                title=spec.title,
                revisions=[r.id for r in list_revisions(project)],
                renders_included=options.include_renders,
                feedback_records=len(list(project.feedback_dir.glob("fb_*.yaml")))
                if project.feedback_dir.is_dir()
                else 0,
                applied_proposals=len(list((project.root / "proposals" / "applied").glob("*.yaml")))
                if (project.root / "proposals" / "applied").is_dir()
                else 0,
            )
        )

    family_manifest = load_family(family_ctx.path)
    add_file("family.yaml", family_ctx.path)
    for name, sheet in sorted(styles.items()):
        sheet_name, sheet_version = split_style_ref(name)
        add_file(f"styles/{sheet_name}/{sheet_version}/style.yaml", sheet)
    components: list[str] = []
    if family_ctx.components_dir.is_dir():
        for path in _iter_files(family_ctx.components_dir):
            relative = path.relative_to(family_ctx.components_dir).as_posix()
            add_file(f"components/{relative}", path)
            components.append(relative)
    assets: list[str] = []
    if family_ctx.assets_dir.is_dir():
        for path in _iter_files(family_ctx.assets_dir):
            if path.suffix.lower() == ".pdf" and not options.include_source_assets:
                notes.append(f"family asset {path.name} (PDF) left out; use --include-source-assets")
                continue
            relative = path.relative_to(family_ctx.assets_dir).as_posix()
            add_file(f"assets/{relative}", path)
            assets.append(relative)
    env = BundleEnvironment(
        manager=family_manifest.environment.manager, system_requirements=family_manifest.system_requirements
    )
    pyproject = family_ctx.env_root / "pyproject.toml"
    if pyproject.exists():
        add_file("environments/pyproject.toml", pyproject)
        env.pyproject = True
        env.packages_relative = os.path.relpath(packages_root(), family_ctx.env_root).replace(os.sep, "/")
    if family_ctx.lockfile.exists():
        add_file(f"environments/{family_ctx.lockfile.name}", family_ctx.lockfile)
        env.lockfile = True
    python_version = family_ctx.env_root / ".python-version"
    if python_version.exists():
        add_file("environments/.python-version", python_version)

    bundle_id = family_manifest.id if kind == "family" else manifest_projects[0].id
    manifest = BundleManifest(
        bundle_id=bundle_id,
        kind=kind,  # type: ignore[arg-type]
        created_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        scianim_version=__version__,
        registry_version=REGISTRY_VERSION,
        family=family_manifest,
        projects=manifest_projects,
        styles=sorted(styles),
        components=components,
        assets=assets,
        environment=env,
        policy=InclusionPolicy(
            include_renders=options.include_renders,
            include_source_assets=options.include_source_assets,
            redact_paths=options.redact_paths,
        ),
        omitted_sources=omitted,
        notes=sorted(set(notes)),
    )
    readme = _readme(manifest)
    members.append(_Member("README.md", readme.encode("utf-8")))
    manifest = manifest.model_copy(update={"file_count": len(members) + 2})  # + bundle.yaml + checksums
    yaml = YAML()
    yaml.default_flow_style = False
    buffer = io.StringIO()
    yaml.dump(manifest.model_dump(mode="json", exclude_none=True), buffer)
    members.append(_Member("bundle.yaml", buffer.getvalue().encode("utf-8")))
    members.sort(key=lambda m: m.relative)
    checksums = "\n".join(f"{hashlib.sha256(m.data).hexdigest()}  {m.relative}" for m in members) + "\n"
    members.append(_Member(CHECKSUM_FILE, checksums.encode("utf-8")))

    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for member in members:
            info = zipfile.ZipInfo(f"{BUNDLE_ROOT}/{member.relative}", date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, member.data)
    return ExportResult(archive, manifest, [m.relative for m in members])


def _readme(manifest: BundleManifest) -> str:
    lines = [
        f"# SciAnim bundle `{manifest.bundle_id}` ({manifest.kind})",
        "",
        f"Exported {manifest.created_at} by scianim {manifest.scianim_version} (registry {manifest.registry_version}).",
        "Inspectable without SciAnim: every file is listed with its SHA-256 in `MANIFEST.sha256`.",
        "",
        "## Contents",
        "",
        f"- family `{manifest.family.id}`: {manifest.family.title}; style `{manifest.family.style.name}@{manifest.family.style.version}`",
    ]
    for project in manifest.projects:
        lines.append(
            f"- project `{project.id}` ({project.title}) at `{project.path}`; revisions: {', '.join(project.revisions) or 'none'}; "
            f"feedback records: {project.feedback_records}; applied proposals: {project.applied_proposals}; renders included: {'yes' if project.renders_included else 'no'}"
        )
    lines.append(f"- styles: {', '.join(manifest.styles) or 'none'}")
    lines.append(
        f"- shared components: {', '.join(manifest.components) or 'none'} (Python files; copied on import, never executed by the tool)"
    )
    lines.append(f"- shared assets: {', '.join(manifest.assets) or 'none'}")
    lines += ["", "## System requirements of the family", ""]
    if not manifest.environment.system_requirements:
        lines.append("none declared")
    for req in manifest.environment.system_requirements:
        lines.append(
            f"- {req.kind} `{req.name}`"
            + (f" >= {req.min_version}" if req.min_version else "")
            + (" (optional)" if req.optional else "")
            + (f": {req.note}" if req.note else "")
        )
    lines += [
        "",
        "## After import",
        "",
        "```bash",
        "scianim bundle import <this archive> --into /path/to/workspace",
        f"scianim family env sync /path/to/workspace/families/{manifest.family.id}   # rebuilds .venv from the lockfile",
    ]
    for project in manifest.projects:
        lines.append(f"scianim validate /path/to/workspace/families/{manifest.family.id}/{project.id}")
    lines.append("```")
    lines.append("")
    lines.append(
        "The lockfile is reused only when `packages/` sits at the same relative place as at export"
        + (f" (`{manifest.environment.packages_relative}`)" if manifest.environment.packages_relative else "")
        + "; otherwise `family env sync` resolves afresh and reports it."
    )
    if manifest.omitted_sources:
        lines += ["", "## Omitted sources: relink after import", ""]
        for item in manifest.omitted_sources:
            lines.append(
                f"- `{item.project_id}` / `{item.source_id}` ({item.type}, {item.role}) at `{item.path}`: {item.reason}. {item.relink}."
            )
    if manifest.notes:
        lines += ["", "## Notes", ""] + [f"- {note}" for note in manifest.notes]
    lines.append("")
    return "\n".join(lines)


__all__ = ["ExportOptions", "ExportResult", "export_bundle"]
