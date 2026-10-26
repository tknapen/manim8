"""`scianim`: the canonical agent interface to the control plane."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from scianim.clean import clean_project
from scianim.codegen.generate import write_scene_module
from scianim.compare import compare_dir, compare_manifests
from scianim.config.loader import SpecError, load_spec
from scianim.doctor import Check, control_plane_checks, family_checks
from scianim.families.resolve import load_family_context, locate_family, probe_environment, sync_environment
from scianim.feedback.store import build_record, list_feedback, resolve_target, write_feedback
from scianim.index import Index
from scianim.planning.checks import Report, validate_project
from scianim.planning.dependencies import compare_with_revision
from scianim.planning.timing import propose_timing, write_proposed_storyboard
from scianim.project import Project, find_project
from scianim.render.jobs import (
    build_snapshot_job,
    build_video_job,
    cached_manifest,
    run_job,
    sources_from_report,
    sources_from_revision,
    tool_versions_for,
)
from scianim.render.manifests import manifest_for_ref
from scianim.review.sheet import write_sheet
from scianim.revisions.store import create_revision, latest_revision, list_revisions, load_revision
from scianim.styles.resolve import list_styles
from scianim.workspace import (
    DEFAULT_STYLE_REF,
    find_workspace,
    init_family,
    init_project,
    init_workspace,
    scan_workspace,
)
from scianim_core import REGISTRY, REGISTRY_VERSION, ArtifactManifest
from scianim_core.feedback import Region
from scianim_core.schemas import export_schemas

QUALITY_PROFILES = ("storyboard", "snapshot", "draft", "final")

app = typer.Typer(no_args_is_help=True, help="SciAnim Studio control plane. Never imports Manim.")
style_app = typer.Typer(no_args_is_help=True, help="Style token resolution.")
schemas_app = typer.Typer(no_args_is_help=True, help="JSON Schema export.")
workspace_app = typer.Typer(no_args_is_help=True, help="Workspaces hold styles, families and projects.")
family_app = typer.Typer(no_args_is_help=True, help="Families: environments, components and assets.")
env_app = typer.Typer(no_args_is_help=True, help="Family render environment (uv).")
project_app = typer.Typer(no_args_is_help=True, help="Projects (animations).")
revision_app = typer.Typer(no_args_is_help=True, help="Immutable project revisions.")
feedback_app = typer.Typer(no_args_is_help=True, help="Review feedback records (feedback/*.yaml).")
index_app = typer.Typer(no_args_is_help=True, help="The workspace SQLite index (a cache of the files).")
app.add_typer(style_app, name="style")
app.add_typer(schemas_app, name="schemas")
app.add_typer(workspace_app, name="workspace")
app.add_typer(family_app, name="family")
family_app.add_typer(env_app, name="env")
app.add_typer(project_app, name="project")
app.add_typer(revision_app, name="revision")
app.add_typer(feedback_app, name="feedback")
app.add_typer(index_app, name="index")

out = Console()
err = Console(stderr=True)


def fail(message: str, code: int = 1) -> None:
    err.print(f"[red]error:[/red] {message}")
    raise typer.Exit(code)


def print_report(report: Report, label: str) -> None:
    for message in report.errors:
        out.print(f"  [red]error[/red]   {message}")
    for message in report.warnings:
        out.print(f"  [yellow]warning[/yellow] {message}")
    for message in report.notices:
        out.print(f"  [dim]note    {message}[/dim]")
    status = "[green]valid[/green]" if report.ok else "[red]invalid[/red]"
    out.print(f"{label}: {status} ({len(report.errors)} errors, {len(report.warnings)} warnings)")


def workspace_or_fail(workspace: Path | None) -> Path:
    root = workspace.resolve() if workspace is not None else find_workspace(Path.cwd())
    if root is None:
        fail("not inside a workspace; pass --workspace or run `scianim workspace init <dir>`")
    if workspace is not None and not (root / "workspace.yaml").exists():
        fail(f"{root} is not a workspace (no workspace.yaml)")
    return root


# --- validation and diagnostics ----------------------------------------------------------------


@app.command()
def validate(
    paths: Annotated[list[Path], typer.Argument(help="Specification files or project directories.")],
    require_family: Annotated[bool, typer.Option(help="Fail when the project's family cannot be found.")] = False,
) -> None:
    """Validate specification files, or run the cross-file checks on a project directory."""
    failures = 0
    for path in paths:
        if path.is_dir():
            try:
                project = find_project(path)
            except SpecError as exc:
                failures += 1
                out.print(f"[red]error[/red] {exc}")
                continue
            report = validate_project(project, require_family=require_family)
            print_report(report, str(path))
            failures += 0 if report.ok else 1
        else:
            try:
                kind, model = load_spec(path)
            except SpecError as exc:
                failures += 1
                out.print(f"{path}: [red]invalid[/red]\n{exc.message}")
                continue
            ident = getattr(model, "id", None) or getattr(model, "project_id", None) or getattr(model, "name", "")
            out.print(f"{path}: [green]valid[/green] {kind} '{ident}'")
    raise typer.Exit(1 if failures else 0)


def _print_checks(checks: list[Check]) -> bool:
    table = Table(show_header=True, header_style="bold")
    table.add_column("check")
    table.add_column("status")
    table.add_column("detail", overflow="fold")
    for check in checks:
        if check.ok:
            status = "[green]ok[/green]"
        elif check.required:
            status = "[red]missing[/red]"
        else:
            status = "[yellow]absent[/yellow]"
        table.add_row(check.name, status, check.detail)
    out.print(table)
    return not any(c.blocking for c in checks)


@app.command()
def doctor(
    project: Annotated[Path | None, typer.Option(help="Project directory; its family is checked too.")] = None,
    family: Annotated[Path | None, typer.Option(help="Family directory or family.yaml to check.")] = None,
) -> None:
    """Check prerequisites for the control plane and, optionally, a family environment."""
    workspace = project or Path.cwd()
    checks = control_plane_checks(workspace)
    contexts = []
    try:
        if family is not None:
            contexts.append(load_family_context(family))
        if project is not None:
            proj = find_project(project)
            spec = proj.load_animation()
            contexts.append(locate_family(proj.root, spec.family, proj.family_search_roots()).context)
    except SpecError as exc:
        fail(str(exc))
    for ctx in contexts:
        checks.extend(family_checks(ctx))
    ok = _print_checks(checks)
    raise typer.Exit(0 if ok else 1)


# --- styles ------------------------------------------------------------------------------------


def _flatten(data: dict, prefix: str = "") -> dict[str, object]:
    flat: dict[str, object] = {}
    for key, value in data.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(_flatten(value, f"{path}."))
        else:
            flat[path] = value
    return flat


@style_app.command("resolve")
def style_resolve(
    project: Annotated[Path, typer.Argument(help="Project directory.")],
    as_json: Annotated[bool, typer.Option("--json", help="Print the ResolvedStyle document as JSON.")] = False,
) -> None:
    """Resolve the project's style cascade and show every token with its provenance."""
    try:
        proj = find_project(project)
    except SpecError as exc:
        fail(str(exc))
    report = validate_project(proj)
    if report.style is None:
        print_report(report, str(project))
        raise typer.Exit(1)
    style = report.style
    if as_json:
        out.print_json(style.model_dump_json())
        return
    out.print(f"[bold]{style.theme}@{style.theme_version}[/bold]  layers: {' -> '.join(style.layers)}")
    out.print(f"hash: {style.hash}")
    table = Table(show_header=True, header_style="bold")
    table.add_column("token")
    table.add_column("value")
    table.add_column("set by")
    flat = _flatten(style.tokens.model_dump(mode="json"))
    for key in sorted(flat):
        table.add_row(key, json.dumps(flat[key]), style.provenance.get(key, "?"))
    out.print(table)


@style_app.command("list")
def style_list(
    path: Annotated[
        Path | None, typer.Argument(help="Project or workspace directory (default: current directory).")
    ] = None,
) -> None:
    """List the style sheets visible from a project or workspace, by name and version."""
    start = (path or Path.cwd()).resolve()
    try:
        search_dirs = find_project(start).style_search_dirs()
    except SpecError:
        search_dirs = Project(start).style_search_dirs()
    found = list_styles(search_dirs)
    if not found:
        fail(f"no style sheets found; searched: {[str(d) for d in search_dirs]}")
    table = Table(show_header=True, header_style="bold")
    table.add_column("style")
    table.add_column("version")
    table.add_column("path", overflow="fold")
    for name, versions in sorted(found.items()):
        for version, sheet in sorted(versions.items()):
            table.add_row(name, version, str(sheet))
    out.print(table)


@app.command()
def registry(
    kind: Annotated[str | None, typer.Argument(help="A component kind to describe; omit to list all kinds.")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print the parameter JSON Schema.")] = False,
) -> None:
    """Describe the component registry: kinds, requirements and parameters."""
    if kind is None:
        table = Table(show_header=True, header_style="bold", title=f"component registry {REGISTRY_VERSION}")
        for column in ("kind", "needs data", "needs equation", "text-like", "params"):
            table.add_column(column)
        for name, definition in REGISTRY.items():
            fields = ", ".join(definition.params_model.model_fields)
            table.add_row(
                name,
                "yes" if definition.requires_data else "-",
                "yes" if definition.requires_equation else "-",
                "yes" if definition.text_like else "-",
                fields,
            )
        out.print(table)
        return
    definition = REGISTRY.get(kind)
    if definition is None:
        fail(f"unknown kind '{kind}'; known: {sorted(REGISTRY)}")
    schema = definition.params_model.model_json_schema()
    if as_json:
        out.print_json(json.dumps(schema))
        return
    out.print(
        f"[bold]{kind}[/bold]  needs data: {definition.requires_data}  needs equation: {definition.requires_equation}  consumes: {', '.join(definition.consumes)}"
    )
    table = Table(show_header=True, header_style="bold")
    for column in ("parameter", "type", "default", "description"):
        table.add_column(column, overflow="fold")
    defs = schema.get("$defs", {})

    def describe(prop: dict) -> str:
        if "$ref" in prop:
            return prop["$ref"].split("/")[-1]
        if "anyOf" in prop:
            return " | ".join(describe(p) for p in prop["anyOf"])
        if prop.get("type") == "array":
            return (
                f"list[{describe(prop.get('items', {})) or 'any'}]"
                if "prefixItems" not in prop
                else "tuple[" + ", ".join(describe(p) for p in prop["prefixItems"]) + "]"
            )
        if "enum" in prop:
            return " | ".join(repr(v) for v in prop["enum"])
        if "const" in prop:
            return repr(prop["const"])
        return str(prop.get("type", "any"))

    required = set(schema.get("required", []))
    for name, prop in schema.get("properties", {}).items():
        default = "required" if name in required else json.dumps(prop.get("default"))
        table.add_row(name, describe(prop), default, prop.get("description", ""))
    out.print(table)
    for name, sub in defs.items():
        out.print(
            f"[bold]{name}[/bold]: " + ", ".join(f"{k} ({describe(v)})" for k, v in sub.get("properties", {}).items())
        )


@schemas_app.command("export")
def schemas_export(
    directory: Annotated[Path, typer.Argument(help="Target directory.")] = Path("schemas"),
    check: Annotated[bool, typer.Option(help="Fail if the committed schemas differ from the models.")] = False,
) -> None:
    """Write JSON Schemas for every public contract (deterministic output)."""
    stale = export_schemas(directory, check=check)
    if check:
        if stale:
            fail(f"schemas out of date: {stale}; run `scianim schemas export {directory}`")
        out.print(f"schemas in {directory} are up to date")
    else:
        out.print(f"wrote schemas to {directory}")


# --- workspaces, families, projects --------------------------------------------------------------


@workspace_app.command("init")
def workspace_init(
    directory: Annotated[Path, typer.Argument(help="Workspace directory to create.")],
    workspace_id: Annotated[
        str | None, typer.Option("--id", help="Workspace id (default: from the directory name).")
    ] = None,
    styles_from: Annotated[Path | None, typer.Option(help="Directory of versioned style sheets to copy in.")] = None,
    with_example: Annotated[bool, typer.Option(help="Also copy the example family and project.")] = False,
) -> None:
    """Create a workspace: workspace.yaml, styles/, families/ and assets/."""
    try:
        report = init_workspace(directory, workspace_id, styles_from, with_example)
    except SpecError as exc:
        fail(str(exc))
    for created in report.created:
        out.print(f"  created {created}")
    for note in report.notes:
        out.print(f"[yellow]note:[/yellow] {note}")
    out.print(f"[green]workspace ready[/green] at {directory.resolve()}")


@workspace_app.command("list")
def workspace_list(
    directory: Annotated[Path | None, typer.Argument(help="Workspace directory (default: the enclosing one).")] = None,
) -> None:
    """Show families, groups and projects, and report duplicate ids or orphan projects."""
    root = workspace_or_fail(directory)
    scan = scan_workspace(root)
    tree = Tree(f"[bold]{root}[/bold]")
    for family in scan.families:
        env = "env ok" if family.has_environment else ("lock only" if family.has_lockfile else "no env")
        branch = tree.add(f"family [bold]{family.id}[/bold]  ({family.path.relative_to(root)}, {env})")
        for project in family.projects:
            groups = f" via {' / '.join(project.groups)}" if project.groups else ""
            storyboard = "storyboard" if project.has_storyboard else "no storyboard"
            branch.add(f"project [bold]{project.id}[/bold]  ({project.path.relative_to(root)}, {storyboard}{groups})")
    out.print(tree)
    for problem in scan.problems:
        out.print(f"  [red]problem[/red] {problem}")
    raise typer.Exit(1 if scan.problems else 0)


@family_app.command("init")
def family_init(
    family_id: Annotated[str, typer.Argument(help="Family id (slug).")],
    workspace: Annotated[Path | None, typer.Option(help="Workspace directory (default: the enclosing one).")] = None,
    style: Annotated[str, typer.Option(help="Default style as name@version.")] = DEFAULT_STYLE_REF,
    from_example: Annotated[
        str | None, typer.Option(help="Copy an example family (e.g. computational_neuroscience).")
    ] = None,
    title: Annotated[str | None, typer.Option(help="Display title.")] = None,
) -> None:
    """Create a family directory with family.yaml and a render-environment pyproject."""
    root = workspace_or_fail(workspace)
    try:
        dest = init_family(root, family_id, style, from_example, title)
    except SpecError as exc:
        fail(str(exc))
    out.print(f"[green]family created[/green] at {dest}\nnext: scianim family env sync {dest}")


@env_app.command("sync")
def family_env_sync(
    family: Annotated[Path, typer.Argument(help="Family directory or family.yaml.")],
    locked: Annotated[bool, typer.Option(help="Require an up-to-date lockfile instead of creating one.")] = False,
) -> None:
    """Create or update the family's isolated render environment with uv."""
    try:
        ctx = load_family_context(family)
        result = sync_environment(ctx, locked=locked)
    except SpecError as exc:
        fail(str(exc))
    if result.note:
        out.print(f"[yellow]note:[/yellow] {result.note}")
    stream = result.stderr.strip() or result.stdout.strip()
    if stream:
        out.print(stream[-3000:])
    if not result.ok:
        fail(f"`{' '.join(result.argv)}` exited {result.returncode} after {result.elapsed_seconds:.0f}s")
    out.print(f"[green]environment ready[/green] at {ctx.venv_dir} ({result.elapsed_seconds:.0f}s)")


@env_app.command("probe")
def family_env_probe(family: Annotated[Path, typer.Argument(help="Family directory or family.yaml.")]) -> None:
    """Report interpreter and package versions inside the family environment."""
    try:
        ctx = load_family_context(family)
    except SpecError as exc:
        fail(str(exc))
    out.print_json(json.dumps(probe_environment(ctx)))


@project_app.command("init")
def project_init(
    name: Annotated[str, typer.Argument(help="Project name; becomes its id (slug).")],
    family: Annotated[str, typer.Option(help="Family id the project belongs to.")],
    workspace: Annotated[Path | None, typer.Option(help="Workspace directory (default: the enclosing one).")] = None,
    from_example: Annotated[
        str | None, typer.Option(help="Copy an example project (e.g. divisive_normalization).")
    ] = None,
    title: Annotated[str | None, typer.Option(help="Display title.")] = None,
) -> None:
    """Create a project under its family, from a template or from an example."""
    root = workspace_or_fail(workspace)
    try:
        dest = init_project(root, family, name, from_example, title)
    except SpecError as exc:
        fail(str(exc))
    out.print(f"[green]project created[/green] at {dest}")


# --- generation and rendering --------------------------------------------------------------------


def _prepare(project_path: Path, require_family: bool) -> tuple[Project, Report]:
    try:
        project = find_project(project_path)
    except SpecError as exc:
        fail(str(exc))
    report = validate_project(project, require_family=require_family)
    return project, report


@app.command()
def codegen(project: Annotated[Path, typer.Argument(help="Project directory.")]) -> None:
    """Generate the scene module from the storyboard's registered components."""
    proj, report = _prepare(project, require_family=False)
    marker_errors = ("checkpoint() marker", "markers not in the storyboard", "duplicate checkpoint()")
    blocking = [e for e in report.errors if not any(m in e for m in marker_errors)]
    if blocking or report.animation is None or report.storyboard is None or report.style is None:
        print_report(report, str(project))
        fail("fix the errors above before generating code")
    target = proj.scene_module_path(report.animation)
    try:
        write_scene_module(report.animation, report.storyboard, report.style, target)
    except SyntaxError as exc:
        fail(f"generated code does not compile: {exc}")
    after = validate_project(proj)
    print_report(after, str(project))
    out.print(f"wrote {target}")
    raise typer.Exit(0 if after.ok else 1)


def _print_checkpoints(manifest: ArtifactManifest) -> None:
    table = Table(show_header=True, header_style="bold")
    for column in ("snapshot", "scene", "t (s)", "anim #", "fidelity", "png", "layout warnings"):
        table.add_column(column)
    for rec in manifest.result.checkpoints:
        warnings = ", ".join(f"{w.code}({','.join(w.object_ids)})" for w in rec.warnings) or "-"
        table.add_row(
            rec.snapshot_id,
            rec.scene_id,
            f"{rec.expected_time_seconds:g}",
            str(rec.animation_index),
            rec.fidelity,
            rec.png,
            warnings,
        )
    out.print(table)
    status = manifest.result.status
    color = "green" if status == "succeeded" else "red"
    out.print(
        f"status: [{color}]{status}[/{color}] in {manifest.result.elapsed_seconds:.1f}s; "
        f"{len(manifest.result.checkpoints)} checkpoint(s)"
    )


@app.command()
def snapshot(
    project: Annotated[Path, typer.Argument(help="Project directory.")],
    ids: Annotated[list[str] | None, typer.Option("--id", help="Snapshot ID to render (repeatable).")] = None,
    all_snapshots: Annotated[bool, typer.Option("--all", help="Render every snapshot (default when no --id).")] = False,
    profile: Annotated[str, typer.Option(help="Quality profile: storyboard, snapshot, draft or final.")] = "snapshot",
    revision: Annotated[
        str | None, typer.Option(help="Render an immutable revision (e.g. rev_0002) instead of the working copy.")
    ] = None,
    no_cache: Annotated[bool, typer.Option(help="Render even when a cached result matches the cache key.")] = False,
    timeout: Annotated[float, typer.Option(help="Worker timeout in seconds.")] = 1800,
) -> None:
    """Render named checkpoints from the real animation flow in the family environment."""
    if profile not in QUALITY_PROFILES:
        fail(f"profile must be one of {list(QUALITY_PROFILES)}")
    proj, report = _prepare(project, require_family=True)
    if report.family is None:
        print_report(report, str(project))
        fail("the project's family could not be resolved; see above")
    if revision is None and not report.ok:
        print_report(report, str(project))
        fail("project does not validate; see above")
    family = report.family
    tool_versions = tool_versions_for(family)
    if not tool_versions:
        fail(f"family environment unavailable at {family.venv_dir}; run `scianim family env sync {family.root}`")
    try:
        sources = (
            sources_from_revision(proj, load_revision(proj, revision), report)
            if revision
            else sources_from_report(proj, report)
        )
        job, paths, hashes = build_snapshot_job(proj, sources, family, list(ids or []), profile, tool_versions)  # type: ignore[arg-type]
    except SpecError as exc:
        fail(str(exc))
    if not no_cache:
        hit = cached_manifest(proj, job.cache_key)
        if hit is not None:
            out.print(f"[green]cache hit[/green] {job.cache_key[:23]}... -> {hit.job.output_dir}/manifest.json")
            _print_checkpoints(hit)
            return
    out.print(
        f"rendering {len(job.snapshot_ids)} checkpoint(s) of {sources.revision_id} in family '{family.manifest.id}' "
        f"({job.manim.pixel_width}x{job.manim.pixel_height}, cache {job.cache_key[:23]}...)"
    )
    try:
        manifest = run_job(proj, family, job, paths, hashes, timeout=timeout)
    except SpecError as exc:
        fail(str(exc))
    sheet = write_sheet(manifest, sources.storyboard, paths.output_dir / "review_sheet.html")
    _print_checkpoints(manifest)
    out.print(f"manifest: {paths.manifest_file}\nreview sheet: {sheet}\nworker log: {paths.log_file}")
    if manifest.result.status != "succeeded":
        for line in manifest.result.errors:
            err.print(f"[red]{line}[/red]")
        raise typer.Exit(1)


def _print_video(manifest: ArtifactManifest) -> None:
    for video in manifest.result.videos:
        out.print(
            f"video: {video.path} | {video.width_px}x{video.height_px} | {video.fps:g} fps | "
            f"{video.frame_count} frames | {video.duration_seconds:.3f}s | {video.codec}"
        )
    if manifest.result.subtitles:
        out.print(f"subtitles: {manifest.result.subtitles}")
    if manifest.result.sections:
        table = Table(show_header=True, header_style="bold")
        for column in ("section", "frames", "seconds", "video"):
            table.add_column(column)
        for section in manifest.result.sections:
            table.add_row(
                section.name,
                str(section.metadata.get("frames", "?")),
                f"{section.metadata.get('duration_seconds', 0):.3f}",
                section.video or "-",
            )
        out.print(table)
    timing = manifest.result.timing
    if timing is not None:
        verdict = (
            "[green]matches the storyboard[/green]"
            if timing.within_tolerance
            else "[red]differs from the storyboard[/red]"
        )
        out.print(
            f"timing: {verdict}; {timing.actual_total_frames} of {timing.expected_total_frames} frames at {timing.fps:g} fps"
        )
        for problem in timing.problems():
            out.print(f"  [red]{problem}[/red]")
        for note in timing.notes:
            out.print(f"  [dim]{note}[/dim]")
    samples = [c for c in manifest.result.checkpoints if c.kind == "sampled_video_frame"]
    if samples:
        out.print(f"sampled frames: {', '.join(f'{c.snapshot_id}@{c.renderer_time_seconds:.3f}s' for c in samples)}")


@app.command()
def render(
    project: Annotated[Path, typer.Argument(help="Project directory.")],
    profile: Annotated[str, typer.Option(help="draft (reduced resolution) or final (exact output).")] = "draft",
    revision: Annotated[
        str | None, typer.Option(help="Render an immutable revision (e.g. rev_0002) instead of the working copy.")
    ] = None,
    sample: Annotated[list[str] | None, typer.Option(help="Extra frame to extract as id=seconds (repeatable).")] = None,
    no_cache: Annotated[bool, typer.Option(help="Render even when a cached result matches the cache key.")] = False,
    timeout: Annotated[float, typer.Option(help="Worker timeout in seconds.")] = 3600,
) -> None:
    """Render the storyboard to video with per-scene sections, subtitles and sampled checkpoint frames."""
    if profile not in ("draft", "final"):
        fail("profile must be draft or final")
    proj, report = _prepare(project, require_family=True)
    if report.family is None:
        print_report(report, str(project))
        fail("the project's family could not be resolved; see above")
    if revision is None and not report.ok:
        print_report(report, str(project))
        fail("project does not validate; see above")
    family = report.family
    tool_versions = tool_versions_for(family)
    if not tool_versions:
        fail(f"family environment unavailable at {family.venv_dir}; run `scianim family env sync {family.root}`")
    samples: dict[str, float] = {}
    for item in sample or []:
        name, _, value = item.partition("=")
        try:
            samples[name] = float(value)
        except ValueError:
            fail(f"--sample expects id=seconds, got '{item}'")
    try:
        sources = (
            sources_from_revision(proj, load_revision(proj, revision), report)
            if revision
            else sources_from_report(proj, report)
        )
        job, paths, hashes = build_video_job(proj, sources, family, profile, samples, tool_versions)  # type: ignore[arg-type]
    except SpecError as exc:
        fail(str(exc))
    if not no_cache:
        hit = cached_manifest(proj, job.cache_key)
        if hit is not None:
            out.print(f"[green]cache hit[/green] {job.cache_key[:23]}... -> {hit.job.output_dir}/manifest.json")
            _print_video(hit)
            return
    out.print(
        f"rendering {profile} video of {sources.revision_id} in family '{family.manifest.id}' "
        f"({job.manim.pixel_width}x{job.manim.pixel_height} at {job.manim.frame_rate:g} fps, "
        f"{job.output.duration_seconds:g}s, cache {job.cache_key[:23]}...)"
    )
    try:
        manifest = run_job(proj, family, job, paths, hashes, timeout=timeout)
    except SpecError as exc:
        fail(str(exc))
    sheet = write_sheet(manifest, sources.storyboard, paths.output_dir / "review_sheet.html")
    _print_video(manifest)
    status = manifest.result.status
    out.print(
        f"status: [{'green' if status == 'succeeded' else 'red'}]{status}[/] in {manifest.result.elapsed_seconds:.1f}s"
    )
    out.print(f"manifest: {paths.manifest_file}\nreview sheet: {sheet}\nworker log: {paths.log_file}")
    for line in manifest.result.warnings:
        out.print(f"  [yellow]warning[/yellow] {line}")
    if status != "succeeded":
        for line in manifest.result.errors:
            err.print(f"[red]{line}[/red]")
        raise typer.Exit(1)


@app.command()
def timing(
    project: Annotated[Path, typer.Argument(help="Project directory.")],
    out: Annotated[
        Path | None, typer.Option(help="Write a storyboard with the proposed boundaries here (never in place).")
    ] = None,
    words_per_minute: Annotated[float | None, typer.Option(help="Override the style's narration rate.")] = None,
) -> None:
    """Propose scene durations from narration and report conflicts with milestones, snapshots and reveals."""
    proj, report = _prepare(project, require_family=False)
    if report.animation is None or report.storyboard is None:
        print_report(report, str(project))
        fail("the project needs a valid animation.yaml and storyboard.yaml")
    wpm = words_per_minute or (report.style.tokens.motion.narration_words_per_minute if report.style else 150.0)
    proposal = propose_timing(report.animation, report.storyboard, wpm)
    table = Table(show_header=True, header_style="bold")
    for column in ("scene", "now", "narration", "proposed", "conflicts"):
        table.add_column(column)
    for scene in proposal.scenes:
        table.add_row(
            scene.scene_id,
            f"{scene.current_start:g}-{scene.current_end:g}s ({scene.current_duration:g}s)",
            "-" if scene.narration_seconds is None else f"{scene.narration_seconds:.1f}s",
            f"{scene.proposed_start:g}-{scene.proposed_end:g}s ({scene.proposed_duration:g}s)",
            "; ".join(scene.conflicts) or "-",
        )
    out_console = out_console_for()
    out_console.print(
        f"narration at {wpm:g} words/min, padding x{proposal.padding_factor:g}, output {proposal.output_duration:g}s"
    )
    out_console.print(table)
    for conflict in proposal.conflicts:
        out_console.print(f"  [red]conflict[/red] {conflict}")
    if out is not None:
        target = write_proposed_storyboard(proj.storyboard_path, proposal, out)
        out_console.print(f"wrote proposed storyboard to {target}")
    if not proposal.ok:
        raise typer.Exit(1)


def out_console_for() -> Console:
    return out


@app.command()
def stale(
    project: Annotated[Path, typer.Argument(help="Project directory.")],
    since: Annotated[str | None, typer.Option(help="Revision to compare with (default: the latest).")] = None,
) -> None:
    """Which scenes the working copy changed relative to a revision (timing, narration, objects, data, equations, style)."""
    proj, report = _prepare(project, require_family=False)
    if not report.ok:
        print_report(report, str(project))
        fail("project does not validate; see above")
    try:
        revision = load_revision(proj, since) if since else None
        if revision is None:
            latest = latest_revision(proj)
            revision = load_revision(proj, latest.id) if latest else None
    except SpecError as exc:
        fail(str(exc))
    dependency = compare_with_revision(proj, report, revision)
    label = revision.record.id if revision else "no revision"
    out.print(f"working copy against {label}:")
    for scene in dependency.scenes:
        mark = "[yellow]stale[/yellow]" if scene.stale else "[green]unchanged[/green]"
        out.print(f"  {scene.scene_id}: {mark}" + (f" ({'; '.join(scene.reasons)})" if scene.reasons else ""))
    for scene_id in dependency.removed_scenes:
        out.print(f"  {scene_id}: [red]removed[/red]")
    for note in dependency.notes:
        out.print(f"  [dim]{note}[/dim]")


@revision_app.command("create")
def revision_create(
    project: Annotated[Path, typer.Argument(help="Project directory.")],
    message: Annotated[str, typer.Option("--message", "-m", help="What changed and why.")],
    allow_empty: Annotated[bool, typer.Option(help="Record a revision even if nothing changed.")] = False,
) -> None:
    """Freeze the working copy (specs, generated code, resolved style) as an immutable revision."""
    proj, report = _prepare(project, require_family=False)
    if not report.ok:
        print_report(report, str(project))
        fail("fix the errors above before creating a revision")
    try:
        record = create_revision(proj, report, message, allow_empty=allow_empty)
    except SpecError as exc:
        fail(str(exc))
    out.print(f"[green]{record.id}[/green] created (parent {record.parent or 'none'}): {record.message}")
    out.print(f"  files: {', '.join(record.files)}")


@revision_app.command("list")
def revision_list(project: Annotated[Path, typer.Argument(help="Project directory.")]) -> None:
    """List revisions with their parents and messages."""
    try:
        proj = find_project(project)
    except SpecError as exc:
        fail(str(exc))
    records = list_revisions(proj)
    if not records:
        out.print("no revisions yet; run `scianim revision create <project> -m <message>`")
        return
    table = Table(show_header=True, header_style="bold")
    for column in ("revision", "parent", "created", "style", "message"):
        table.add_column(column)
    for record in records:
        table.add_row(
            record.id,
            record.parent or "-",
            record.created_at,
            f"{record.style_theme}@{record.style_version}",
            record.message,
        )
    out.print(table)


@app.command("review-sheet")
def review_sheet(
    project: Annotated[Path, typer.Argument(help="Project directory.")],
    manifest: Annotated[Path | None, typer.Option(help="manifest.json to render; default: the latest job.")] = None,
) -> None:
    """Write a static HTML contact sheet for a job's checkpoints."""
    proj, report = _prepare(project, require_family=False)
    if report.storyboard is None:
        fail("project has no storyboard")
    path = manifest
    if path is None:
        candidates = sorted(proj.renders_dir.glob("*/job_*/manifest.json"), key=lambda p: p.parent.name)
        if not candidates:
            fail("no manifests found; run `scianim snapshot` first")
        path = candidates[-1]
    doc = ArtifactManifest.model_validate_json(path.read_text())
    target = write_sheet(doc, report.storyboard, path.parent / "review_sheet.html")
    out.print(f"wrote {target}")


@app.command()
def clean(
    project: Annotated[Path, typer.Argument(help="Project directory.")],
    keep: Annotated[int, typer.Option(help="Newest working jobs to keep.")] = 1,
    media: Annotated[bool, typer.Option(help="Also remove Manim's media cache under .scianim/media.")] = True,
    dry_run: Annotated[bool, typer.Option(help="Report what would be removed without deleting.")] = False,
) -> None:
    """Reclaim space: media cache, old job logs and superseded working renders. Revisions are never touched."""
    try:
        proj = find_project(project)
    except SpecError as exc:
        fail(str(exc))
    report = clean_project(proj, keep=keep, media=media, dry_run=dry_run)
    verb = "would remove" if dry_run else "removed"
    for path in report.removed:
        out.print(f"  {verb} {path.relative_to(proj.root)}")
    out.print(
        f"{verb} {len(report.removed)} item(s), {report.bytes_freed / 1e6:.1f} MB; kept {len(report.kept)} job(s)"
    )


# --- review: feedback, comparison, index and server -----------------------------------------------


def _parse_region(value: str | None) -> Region | None:
    if value is None:
        return None
    try:
        x, y, w, h = (float(part) for part in value.split(","))
    except ValueError:
        fail("--region must be x,y,width,height in normalized image coordinates, e.g. 0.2,0.36,0.25,0.14")
    return Region(x=x, y=y, width=w, height=h)


@feedback_app.command("add")
def feedback_add(
    project: Annotated[Path, typer.Argument(help="Project directory.")],
    text: Annotated[str, typer.Option("--text", "-t", help="The comment.")],
    revision: Annotated[str, typer.Option(help="working or rev_NNNN the comment refers to.")] = "working",
    snapshot: Annotated[str | None, typer.Option(help="Snapshot (checkpoint) id.")] = None,
    scene: Annotated[str | None, typer.Option(help="Scene id (derived from the snapshot when omitted).")] = None,
    object_id: Annotated[str | None, typer.Option("--object", help="Object id from the layout report.")] = None,
    region: Annotated[str | None, typer.Option(help="x,y,width,height normalized to the image.")] = None,
    severity: Annotated[str, typer.Option(help="visual, scientific, timing or other.")] = "visual",
    job: Annotated[
        str | None, typer.Option(help="Job whose image was reviewed (default: the revision's latest).")
    ] = None,
    author: Annotated[str | None, typer.Option(help="Who wrote it.")] = None,
) -> None:
    """Record a comment bound to a revision, a snapshot and optionally an object or a region."""
    try:
        proj = find_project(project)
        spec = proj.load_animation()
        target = resolve_target(proj, revision, snapshot, object_id, job) if snapshot else None
        parsed = _parse_region(region)
        kind = "object_comment" if object_id else ("region_comment" if parsed else "general_comment")
        record = build_record(
            spec.id,
            revision_id=revision,
            kind=kind,  # type: ignore[arg-type]
            text=text,
            severity=severity,  # type: ignore[arg-type]
            snapshot_id=snapshot,
            scene_id=scene,
            object_id=object_id,
            region=parsed,
            target=target,
            author=author,
        )
        path = write_feedback(proj, record)
    except SpecError as exc:
        fail(str(exc))
    except ValueError as exc:
        fail(str(exc))
    out.print(f"[green]{record.id}[/green] -> {path.relative_to(proj.root)}")


@feedback_app.command("status")
def feedback_status(
    project: Annotated[Path, typer.Argument(help="Project directory.")],
    snapshot: Annotated[str, typer.Option(help="Snapshot (checkpoint) id.")],
    status: Annotated[str, typer.Option(help="approved, needs_revision or scientific_concern.")],
    revision: Annotated[str, typer.Option(help="rev_NNNN (approval refuses the working copy).")] = "working",
    job: Annotated[
        str | None, typer.Option(help="Job whose image was reviewed (default: the revision's latest).")
    ] = None,
    text: Annotated[str, typer.Option(help="Optional note.")] = "",
    author: Annotated[str | None, typer.Option(help="Who decided.")] = None,
) -> None:
    """Mark a checkpoint of a revision; the record names the image hash that was displayed."""
    try:
        proj = find_project(project)
        spec = proj.load_animation()
        target = resolve_target(proj, revision, snapshot, None, job)
        record = build_record(
            spec.id,
            revision_id=revision,
            kind="status",
            status=status,  # type: ignore[arg-type]
            text=text,
            snapshot_id=snapshot,
            target=target,
            author=author,
        )
        path = write_feedback(proj, record)
    except SpecError as exc:
        fail(str(exc))
    except ValueError as exc:
        fail(str(exc))
    out.print(
        f"[green]{record.id}[/green] {status} {revision}/{snapshot} (image {record.image_sha256[:12]}...) -> {path.name}"
    )


@feedback_app.command("list")
def feedback_list(
    project: Annotated[Path, typer.Argument(help="Project directory.")],
    snapshot: Annotated[str | None, typer.Option(help="Only this snapshot.")] = None,
    revision: Annotated[str | None, typer.Option(help="Only this revision.")] = None,
) -> None:
    """List feedback records in creation order."""
    try:
        proj = find_project(project)
        records = list_feedback(proj, strict=True)
    except SpecError as exc:
        fail(str(exc))
    records = [
        r
        for r in records
        if (snapshot is None or r.snapshot_id == snapshot) and (revision is None or r.revision_id == revision)
    ]
    if not records:
        out.print("no feedback records")
        return
    table = Table(show_header=True, header_style="bold")
    for column in ("id", "revision", "snapshot", "object", "kind", "severity/status", "text"):
        table.add_column(column)
    for r in records:
        table.add_row(
            r.id, r.revision_id, r.snapshot_id or "-", r.object_id or "-", r.kind, r.status or r.severity, r.text[:80]
        )
    out.print(table)


@app.command()
def compare(
    project: Annotated[Path, typer.Argument(help="Project directory.")],
    a: Annotated[str, typer.Argument(help="Job id or revision id (its latest succeeded render).")],
    b: Annotated[str, typer.Argument(help="Job id or revision id.")],
    no_images: Annotated[bool, typer.Option(help="Skip writing diff PNGs.")] = False,
) -> None:
    """Pixel and layout differences between two renders; diff PNGs go to .scianim/compare/."""
    try:
        proj = find_project(project)
    except SpecError as exc:
        fail(str(exc))
    manifest_a, manifest_b = manifest_for_ref(proj, a), manifest_for_ref(proj, b)
    if manifest_a is None or manifest_b is None:
        fail(f"no succeeded render for '{a if manifest_a is None else b}'")
    out_dir = None if no_images else compare_dir(proj, manifest_a.job.job_id, manifest_b.job.job_id)
    results = compare_manifests(proj, manifest_a, manifest_b, out_dir)
    table = Table(show_header=True, header_style="bold")
    for column in ("snapshot", "identical", "pixels changed", "layout changes", "note"):
        table.add_column(column)
    for item in results:
        changes = "; ".join(f"{c.object_id} {c.change}" for c in item.changes) or "-"
        pixels = "-" if item.pixel_diff_fraction is None else f"{100 * item.pixel_diff_fraction:.2f}%"
        table.add_row(item.snapshot_id, "yes" if item.identical else "no", pixels, changes, item.note or "")
    out.print(
        f"A = {manifest_a.job.job_id} ({manifest_a.job.revision_id}); B = {manifest_b.job.job_id} ({manifest_b.job.revision_id})"
    )
    out.print(table)
    if out_dir is not None:
        out.print(f"diff images: {out_dir}")


@index_app.command("rebuild")
def index_rebuild(
    workspace: Annotated[Path | None, typer.Option(help="Workspace root (default: the one containing cwd).")] = None,
) -> None:
    """Recreate the SQLite index from the files; safe to run at any time."""
    root = workspace_or_fail(workspace)
    index = Index(root)
    index.rebuild()
    projects = index.projects()
    out.print(f"indexed {len(projects)} project(s) into {index.path}")
    for problem in index.problems:
        out.print(f"  [yellow]problem[/yellow] {problem}")
    index.close()


@app.command()
def serve(
    workspace: Annotated[Path | None, typer.Option(help="Workspace root (default: the one containing cwd).")] = None,
    host: Annotated[str, typer.Option(help="Bind address; keep it on loopback unless you know why not.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="TCP port.")] = 8765,
) -> None:
    """Run the local review server (API under /api, the UI at /)."""
    root = workspace_or_fail(workspace)
    if host not in ("127.0.0.1", "localhost", "::1"):
        err.print(
            "[yellow]warning:[/yellow] binding to a non-loopback address exposes a service that runs Manim code "
            "from your workspace; there is no authentication"
        )
    import uvicorn

    from scianim.server.app import create_app

    application = create_app(root)
    out.print(f"SciAnim Studio review server on http://{host}:{port}/ (workspace {root}); Ctrl+C stops it")
    uvicorn.run(application, host=host, port=port, log_level="warning")


def main() -> None:
    try:
        app()
    except SpecError as exc:
        err.print(f"[red]error:[/red] {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
