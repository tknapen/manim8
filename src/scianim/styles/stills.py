"""Stills for a style decision: the same checkpoints under the project's sheet and under a candidate (ADR-038).

A personal signature grows one reviewed token at a time. `scianim style stills` renders named checkpoints twice,
under the sheet the project pins and under an unpublished candidate sheet, and writes a two-column page with
the token differences above the pairs; `scianim style publish` copies an accepted candidate into the versioned
styles directory, where published sheets are never edited (ADR-010).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import html
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from scianim.config.loader import SpecError, load_yaml
from scianim.families.resolve import FamilyContext
from scianim.planning.checks import Report
from scianim.project import Project
from scianim.render.jobs import JobSources, build_snapshot_job, run_job, sources_from_report
from scianim.styles.resolve import resolve_style
from scianim_core import ArtifactManifest, ResolvedStyle, StyleSelection, StyleSheet, split_style_ref


def flatten_tokens(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in data.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(flatten_tokens(value, f"{path}."))
        else:
            flat[path] = value
    return flat


def token_diff(current: ResolvedStyle, candidate: ResolvedStyle) -> list[tuple[str, Any, Any]]:
    """Token paths whose values differ, with the current and the candidate value."""
    a = flatten_tokens(current.tokens.model_dump(mode="json"))
    b = flatten_tokens(candidate.tokens.model_dump(mode="json"))
    return [(path, a.get(path), b.get(path)) for path in sorted(set(a) | set(b)) if a.get(path) != b.get(path)]


def load_candidate(path: Path) -> StyleSheet:
    try:
        return StyleSheet.model_validate(load_yaml(path))
    except Exception as exc:  # every loader error reads the same to the user
        raise SpecError(path, f"candidate style sheet does not validate: {exc}") from None


def stage_candidate(sheet: StyleSheet, source: Path, into: Path) -> Path:
    """Lay a candidate out as `styles/<name>/<version>/style.yaml` under `into`, the layout the resolver reads."""
    target_dir = into / "styles" / sheet.name / sheet.version
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target_dir / "style.yaml")
    return into / "styles"


def resolve_with(project: Project, report: Report, selection: StyleSelection, extra_dirs: list[Path]) -> ResolvedStyle:
    """Resolve a selection the way the project's own style resolves (family and group layers included)."""
    family_manifest = report.family.manifest if report.family else None
    return resolve_style(
        selection,
        [*extra_dirs, *project.style_search_dirs()],
        family_manifest,
        [g.manifest for g in report.groups],
    )


def selection_for(ref: str, like: StyleSelection) -> StyleSelection:
    name, version = split_style_ref(ref)
    return StyleSelection(name=name, version=version, overrides=dict(like.overrides))


@dataclasses.dataclass
class Still:
    label: str
    style: ResolvedStyle
    manifest: ArtifactManifest


def render_stills(
    project: Project,
    report: Report,
    family: FamilyContext,
    styles: dict[str, ResolvedStyle],
    snapshot_ids: list[str],
    profile: str = "snapshot",
    tool_versions: dict[str, object] | None = None,
    timeout: float = 1800,
) -> list[Still]:
    """One snapshot job per style, same checkpoints; the style hash alone separates their cache keys."""
    base = sources_from_report(project, report)
    stills: list[Still] = []
    for label, style in styles.items():
        sources: JobSources = dataclasses.replace(base, style=style)
        job, paths, hashes = build_snapshot_job(
            project,
            sources,
            family,
            list(snapshot_ids),
            profile,  # type: ignore[arg-type]
            tool_versions or {},
        )
        manifest = run_job(project, family, job, paths, hashes, timeout=timeout)
        stills.append(Still(label, style, manifest))
    return stills


_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>
body{{font:15px/1.45 -apple-system,Helvetica,Arial,sans-serif;margin:32px;color:#22304A;background:#fff}}
h1{{font-weight:600;font-size:22px}} h2{{font-weight:600;font-size:16px;margin:28px 0 8px}}
table{{border-collapse:collapse;margin:8px 0 20px}} td,th{{text-align:left;padding:3px 12px 3px 0;border-bottom:1px solid #EEF1F5;font-size:13px}}
.pair{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:28px}}
.pair img{{width:100%;height:auto;border:1px solid #D9DFE7}} .cap{{font-size:13px;color:#6E7B8F}}
.warn{{color:#C9A227;font-size:13px}} code{{font-size:13px}}
</style></head><body>
<h1>{title}</h1>
<p class="cap">{meta}</p>
<h2>Tokens that differ</h2>
{diff}
{pairs}
</body></html>
"""


def write_stills_sheet(stills: list[Still], project: Project, target: Path) -> Path:
    """A two-column page: each checkpoint under the first style beside the same under the second."""
    if len(stills) != 2:
        raise ValueError("a stills sheet compares exactly two styles")
    left, right = stills
    target.parent.mkdir(parents=True, exist_ok=True)
    diff = token_diff(left.style, right.style)
    rows = (
        "".join(
            f"<tr><td><code>{html.escape(path)}</code></td><td>{html.escape(json.dumps(a))}</td>"
            f"<td>{html.escape(json.dumps(b))}</td></tr>"
            for path, a, b in diff
        )
        or "<tr><td colspan=3>none</td></tr>"
    )
    table = f"<table><tr><th>token</th><th>{html.escape(left.label)}</th><th>{html.escape(right.label)}</th></tr>{rows}</table>"
    by_id = {still.label: {c.snapshot_id: c for c in still.manifest.result.checkpoints} for still in stills}
    pairs = []
    for snapshot_id in [c.snapshot_id for c in left.manifest.result.checkpoints]:
        cells = []
        for still in stills:
            record = by_id[still.label].get(snapshot_id)
            if record is None:
                cells.append(f"<div><p class='warn'>{html.escape(snapshot_id)} was not rendered</p></div>")
                continue
            src = Path(os.path.relpath(project.root / record.png, target.parent)).as_posix()
            warnings = "".join(
                f"<p class='warn'>{html.escape(w.code)}: {html.escape(w.detail)}</p>" for w in record.warnings
            )
            cells.append(
                f"<div><img src='{html.escape(src)}' alt='{html.escape(snapshot_id)}'>"
                f"<p class='cap'>{html.escape(still.label)} · {html.escape(still.style.theme)}@"
                f"{html.escape(still.style.theme_version)} · {html.escape(still.style.hash[:19])}</p>{warnings}</div>"
            )
        pairs.append(f"<h2>{html.escape(snapshot_id)}</h2><div class='pair'>{''.join(cells)}</div>")
    meta = (
        f"{html.escape(left.label)}: job {html.escape(left.manifest.job.job_id)} · "
        f"{html.escape(right.label)}: job {html.escape(right.manifest.job.job_id)} · "
        f"{len(diff)} token(s) differ · {dt.datetime.now(dt.UTC).isoformat(timespec='seconds')}"
    )
    target.write_text(
        _PAGE.format(
            title=f"Style stills: {html.escape(project.root.name)}", meta=meta, diff=table, pairs="\n".join(pairs)
        ),
        encoding="utf-8",
    )
    return target


def stills_dir(project: Project) -> Path:
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S")
    return project.renders_dir / "working" / f"stills_{stamp}"


def publish_candidate(candidate: Path, ref: str, styles_dir: Path) -> Path:
    """Copy a candidate into `styles/<name>/<version>/`, rewriting its name and version to the reference and
    refusing to touch a version that exists; a PHILOSOPHY.md beside the candidate travels with it."""
    sheet = load_candidate(candidate)
    name, version = split_style_ref(ref)
    target_dir = styles_dir / name / version
    if target_dir.exists():
        raise SpecError(target_dir, f"{name}@{version} is published already; published sheets are never edited")
    if sheet.inherits is None:
        raise SpecError(candidate, "a candidate must pin `inherits` to a published sheet")
    data = load_yaml(candidate)
    data["name"], data["version"] = name, version
    StyleSheet.model_validate(data)
    target_dir.mkdir(parents=True)
    from scianim.config.loader import safe_yaml

    with (target_dir / "style.yaml").open("w", encoding="utf-8") as handle:
        safe_yaml().dump(data, handle)
    philosophy = candidate.parent / "PHILOSOPHY.md"
    if philosophy.exists():
        shutil.copy2(philosophy, target_dir / "PHILOSOPHY.md")
    return target_dir / "style.yaml"


def temporary_styles_root() -> Path:
    return Path(tempfile.mkdtemp(prefix="scianim-candidate-"))


__all__ = [
    "Still",
    "flatten_tokens",
    "load_candidate",
    "publish_candidate",
    "render_stills",
    "resolve_with",
    "selection_for",
    "stage_candidate",
    "stills_dir",
    "temporary_styles_root",
    "token_diff",
    "write_stills_sheet",
]
