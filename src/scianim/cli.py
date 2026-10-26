"""`scianim`: the canonical agent interface to the control plane."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from scianim.codegen.generate import write_scene_module
from scianim.config.loader import SpecError, load_spec
from scianim.doctor import Check, control_plane_checks, family_checks
from scianim.families.resolve import (
    find_family,
    load_family_context,
    probe_environment,
    sync_environment,
)
from scianim.planning.checks import Report, validate_project
from scianim.project import Project, find_project
from scianim.render.jobs import (
    WORKING_REVISION,
    build_snapshot_job,
    cached_manifest,
    run_job,
    tool_versions_for,
)
from scianim.review.sheet import write_sheet
from scianim_core import ArtifactManifest
from scianim_core.schemas import export_schemas

QUALITY_PROFILES = ("storyboard", "snapshot", "draft", "final")

app = typer.Typer(no_args_is_help=True, help="SciAnim Studio control plane. Never imports Manim.")
style_app = typer.Typer(no_args_is_help=True, help="Style token resolution.")
schemas_app = typer.Typer(no_args_is_help=True, help="JSON Schema export.")
family_app = typer.Typer(no_args_is_help=True, help="Family environments.")
env_app = typer.Typer(no_args_is_help=True, help="Family render environment (uv).")
app.add_typer(style_app, name="style")
app.add_typer(schemas_app, name="schemas")
app.add_typer(family_app, name="family")
family_app.add_typer(env_app, name="env")

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
            contexts.append(find_family(proj.root, spec.family, proj.family_search_roots()))
    except SpecError as exc:
        fail(str(exc))
    for ctx in contexts:
        checks.extend(family_checks(ctx))
    ok = _print_checks(checks)
    raise typer.Exit(0 if ok else 1)


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
def family_env_probe(
    family: Annotated[Path, typer.Argument(help="Family directory or family.yaml.")],
) -> None:
    """Report interpreter and package versions inside the family environment."""
    try:
        ctx = load_family_context(family)
    except SpecError as exc:
        fail(str(exc))
    out.print_json(json.dumps(probe_environment(ctx)))


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
    marker_errors = (
        "checkpoint() marker",
        "markers not in the storyboard",
        "duplicate checkpoint()",
    )
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
    no_cache: Annotated[bool, typer.Option(help="Render even when a cached result matches the cache key.")] = False,
    timeout: Annotated[float, typer.Option(help="Worker timeout in seconds.")] = 1800,
) -> None:
    """Render named checkpoints from the real animation flow in the family environment."""
    if profile not in QUALITY_PROFILES:
        fail(f"profile must be one of {list(QUALITY_PROFILES)}")
    proj, report = _prepare(project, require_family=True)
    if (
        not report.ok
        or report.animation is None
        or report.storyboard is None
        or report.style is None
        or report.family is None
    ):
        print_report(report, str(project))
        fail("project does not validate; see above")
    family = report.family
    tool_versions = tool_versions_for(family)
    if not tool_versions:
        fail(f"family environment unavailable at {family.venv_dir}; run `scianim family env sync {family.root}`")
    try:
        job, paths, hashes = build_snapshot_job(
            proj,
            report.animation,
            report.storyboard,
            report.style,
            family,
            list(ids or []),
            profile,  # type: ignore[arg-type]
            tool_versions,
        )
    except SpecError as exc:
        fail(str(exc))
    if not no_cache:
        hit = cached_manifest(proj, job.cache_key)
        if hit is not None:
            out.print(f"[green]cache hit[/green] {job.cache_key[:23]}... -> {hit.job.output_dir}/manifest.json")
            _print_checkpoints(hit)
            return
    out.print(
        f"rendering {len(job.snapshot_ids)} checkpoint(s) in family '{family.manifest.id}' "
        f"({job.manim.pixel_width}x{job.manim.pixel_height}, cache {job.cache_key[:23]}...)"
    )
    try:
        manifest = run_job(proj, family, job, paths, hashes, timeout=timeout)
    except SpecError as exc:
        fail(str(exc))
    sheet = write_sheet(manifest, report.storyboard, paths.output_dir / "review_sheet.html")
    _print_checkpoints(manifest)
    out.print(f"manifest: {paths.manifest_file}\nreview sheet: {sheet}\nworker log: {paths.log_file}")
    if manifest.result.status != "succeeded":
        for line in manifest.result.errors:
            err.print(f"[red]{line}[/red]")
        raise typer.Exit(1)


@app.command("review-sheet")
def review_sheet(
    project: Annotated[Path, typer.Argument(help="Project directory.")],
    manifest: Annotated[Path | None, typer.Option(help="manifest.json to render; default: the latest.")] = None,
) -> None:
    """Write a static HTML contact sheet for a job's checkpoints."""
    proj, report = _prepare(project, require_family=False)
    if report.storyboard is None:
        fail("project has no storyboard")
    path = manifest
    if path is None:
        candidates = sorted((proj.renders_dir / WORKING_REVISION).glob("*/manifest.json"))
        if not candidates:
            fail("no manifests found; run `scianim snapshot` first")
        path = candidates[-1]
    doc = ArtifactManifest.model_validate_json(path.read_text())
    target = write_sheet(doc, report.storyboard, path.parent / "review_sheet.html")
    out.print(f"wrote {target}")


def main() -> None:
    try:
        app()
    except SpecError as exc:
        err.print(f"[red]error:[/red] {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
