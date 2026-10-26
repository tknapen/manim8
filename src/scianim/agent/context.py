"""Context export: everything an external agent needs to propose a spec or storyboard, as files.

No model is called. The bundle is provider-neutral Markdown plus JSON and the JSON Schemas, so a
coding agent, a hosted API behind an adapter, or a person can work from it and answer with proposals.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from scianim.feedback.store import list_feedback
from scianim.planning.checks import Report
from scianim.project import Project
from scianim.render.manifests import list_manifests
from scianim.revisions.store import list_revisions
from scianim.sources.adapters import load_extracts
from scianim_core import REGISTRY, REGISTRY_VERSION, SourceExtract
from scianim_core.hashing import sha256_file
from scianim_core.schemas import PUBLIC_SCHEMAS, schema_text

CONTEXT_DIR = ".scianim/context"

INSTRUCTIONS = """\
## How to work with this project

You are the agent for a SciAnim Studio project. The files in this directory are evidence and vocabulary; the
YAML in the project is the specification, and nothing you say in a conversation counts until it is in a file.

0. An animation here is a brief clip, typically 5 to 30 seconds and one or two scenes, that shows one
   mechanism moving: the equation beside the picture, no title cards, no scene that merely lists definitions,
   and at least one quantity that varies while the viewer watches. It is not a slide deck or a lecture.
1. Read the brief, the sources (what they *say*, below) and the storyboard if one exists. Inspect before you claim.
2. List the scientific assumptions you cannot settle from the sources under `uncertainties` in your proposal.
   Ask; do not invent numbers, citations or mechanisms.
3. Prefer registered component kinds (section "Registry"). Declare any bespoke object as `kind: custom` with a
   named builder in `code/`; never put executable code in YAML.
   Make the animation move where a figure could not: give a `function_plot` named `parameters` (named after the
   equation's symbols) and add a scene action of kind `vary_parameter` that sweeps one of them over a few
   seconds, with `emphasize` naming the equation object that highlights that symbol. The curve and its
   markers follow, the term pulses, and a readout shows the value. Keep `y_range` fixed on such a plot. Do
   not place two conditions side by side when one quantity can vary while the viewer watches.
4. Answer with proposal files under `proposals/` in the project (template in `proposal.template.yaml`):
   `create_spec` or `revise_spec` targets `animation.yaml`; `create_storyboard` or `revise_storyboard` targets
   `storyboard.yaml`. A `revise_*` proposal should be a small `patch` (JSON-pointer operations); a `create_*`
   proposal carries a whole `document`. Name the feedback ids you answer in `in_response_to`.
5. Every scientific statement your proposal relies on goes in `claims` with a `source_id` and a `locator`
   (page, figure, column). Synthetic or illustrative data must be labelled as such in the storyboard
   (`data_label`) and in the source `citation`.
6. Validate before you apply: `scianim propose validate <project> proposals/<id>.yaml`, then
   `scianim propose apply ...`, `scianim codegen`, `scianim snapshot --all`, `scianim inspect`. Read the
   inspection findings and the layout reports against each snapshot description, fix what you can, and only
   then ask for human review. A proposal that touches equations, sources or constraints is flagged for
   scientific sign-off; you cannot approve it.
7. Change the smallest scope after feedback; do not rewrite unrelated scenes.
"""


def describe_kind(kind: str) -> dict[str, Any]:
    definition = REGISTRY[kind]
    schema = definition.params_model.model_json_schema()
    defs = schema.get("$defs", {})

    def describe(props: dict[str, Any], required: list[str]) -> list[dict[str, Any]]:
        out = []
        for name, prop in props.items():
            entry = {"name": name, "required": name in required}
            if "$ref" in prop:
                ref = prop["$ref"].split("/")[-1]
                entry["type"] = ref
                entry["fields"] = describe(
                    defs.get(ref, {}).get("properties", {}), defs.get(ref, {}).get("required", [])
                )
            else:
                entry["type"] = prop.get("type") or (
                    "one of " + ", ".join(str(a.get("type", a.get("$ref", "?"))) for a in prop.get("anyOf", []))
                )
            if "enum" in prop:
                entry["choices"] = prop["enum"]
            if "default" in prop:
                entry["default"] = prop["default"]
            if "description" in prop:
                entry["description"] = prop["description"]
            if "items" in prop and "$ref" in prop["items"]:
                ref = prop["items"]["$ref"].split("/")[-1]
                entry["items"] = ref
                entry["fields"] = describe(
                    defs.get(ref, {}).get("properties", {}), defs.get(ref, {}).get("required", [])
                )
            out.append(entry)
        return out

    return {
        "kind": kind,
        "requires_data": definition.requires_data,
        "requires_equation": definition.requires_equation,
        "text_like": definition.text_like,
        "consumes": list(definition.consumes),
        "params": describe(schema.get("properties", {}), schema.get("required", [])),
    }


def _params_lines(params: list[dict[str, Any]], indent: int = 0) -> list[str]:
    lines = []
    pad = "  " * indent
    for entry in params:
        bits = [f"`{entry['name']}`", f"({entry['type']}{', required' if entry['required'] else ''}"]
        if "default" in entry:
            bits.append(f", default {json.dumps(entry['default'])}")
        if "choices" in entry:
            bits.append(f", one of {', '.join(map(str, entry['choices']))}")
        bits.append(")")
        line = f"{pad}- " + " ".join(bits[:2]) + "".join(bits[2:])
        if "description" in entry:
            line += f": {entry['description']}"
        lines.append(line)
        if entry.get("fields"):
            lines.extend(_params_lines(entry["fields"], indent + 1))
    return lines


def _source_summary(extract: SourceExtract) -> str:
    says = extract.says
    if extract.type == "csv":
        columns = ", ".join(
            f"`{c['name']}` ({c['dtype']}"
            + (f", {c['minimum']:g} to {c['maximum']:g}" if c.get("minimum") is not None else "")
            + (f", {c['distinct']} distinct" if c["dtype"] == "text" else "")
            + ")"
            for c in says.get("columns", [])
        )
        return f"{says.get('rows', 0)} rows; columns: {columns}"
    if extract.type in ("markdown", "text"):
        excerpt = (says.get("text") or "")[:1200].strip()
        return (
            f"{says.get('words', 0)} words; headings: {', '.join(says.get('headings', [])) or 'none'}\n\n> "
            + excerpt.replace("\n", "\n> ")
        )
    if extract.type == "pdf":
        first = next((p["text"][:600].strip() for p in says.get("pages", []) if p.get("characters")), "")
        return f"{says.get('page_count', 0)} pages; title: {says.get('title') or 'unknown'}\n\n> " + first.replace(
            "\n", "\n> "
        )
    if extract.type == "image":
        return f"{says.get('width_px')}x{says.get('height_px')} {says.get('format')}"
    return json.dumps(says)[:600]


def export_context(project: Project, report: Report, out_dir: Path | None = None) -> Path:
    out = out_dir or project.root / CONTEXT_DIR
    out.mkdir(parents=True, exist_ok=True)
    animation = report.animation
    storyboard = report.storyboard
    style = report.style
    extracts = load_extracts(project)
    feedback = list_feedback(project)
    revisions = list_revisions(project)
    manifests = [m for m in list_manifests(project) if m.result.status == "succeeded"]
    latest = manifests[-1] if manifests else None

    lines: list[str] = [
        f"# Context for project `{animation.id if animation else project.root.name}`",
        "",
        INSTRUCTIONS,
        "",
    ]
    lines += ["## Project", "", f"- path: `{project.root}`"]
    if report.family:
        lines.append(
            f"- family: `{report.family.manifest.id}` (components allowed: {', '.join(report.family.manifest.components)})"
        )
    if style:
        lines.append(f"- style: `{style.theme}@{style.theme_version}` (hash `{style.hash[7:19]}`)")
    lines.append(
        f"- validation: {'valid' if report.ok else 'invalid'}; errors: {len(report.errors)}, warnings: {len(report.warnings)}"
    )
    for message in report.errors:
        lines.append(f"  - error: {message}")
    for message in report.warnings:
        lines.append(f"  - warning: {message}")
    lines.append(f"- revisions: {', '.join(r.id for r in revisions) or 'none'}")
    lines.append("")
    if animation:
        lines += ["## Brief (animation.yaml)", "", f"**{animation.title}**", "", animation.objective, ""]
        if animation.audience:
            lines.append(f"- audience: {animation.audience}")
        o = animation.output
        lines.append(
            f"- output: {o.width_px}x{o.height_px} at {o.fps:g} fps, {o.duration_seconds:g} s ({o.aspect_ratio})"
        )
        for c in animation.scientific_constraints:
            lines.append(
                f"- constraint `{c.id}` ({c.kind}): {c.text}" + (f" [equation {c.equation}]" if c.equation else "")
            )
        for m in animation.timeline:
            lines.append(f"- milestone `{m.id}` at {m.at_seconds:g} s ({m.kind}): {m.instruction}")
        if animation.direction.tone or animation.direction.prefer or animation.direction.avoid:
            lines.append(
                f"- direction: tone {animation.direction.tone or '-'}; prefer {animation.direction.prefer}; avoid {animation.direction.avoid}"
            )
        lines.append("")
        lines += ["## Equations", ""]
        if not animation.equations:
            lines.append("none declared")
        for e in animation.equations:
            lines.append(f"- `{e.id}`: `{e.typst or e.latex}`")
            for name, definition in e.symbols.items():
                lines.append(
                    f"  - `{name}`: {definition.meaning}" + (f" ({definition.units})" if definition.units else "")
                )
        lines.append("")
        lines += ["## Sources: what they say", ""]
        if not animation.sources:
            lines.append("none declared")
        for source in animation.sources:
            lines.append(f"### `{source.id}` ({source.type}, role {source.role})")
            lines.append("")
            lines.append(f"- path: `{source.path}`" + (f"; citation: {source.citation}" if source.citation else ""))
            extract = extracts.get(source.id)
            if extract is None:
                lines.append("- not probed yet: run `scianim sources probe`")
            else:
                lines.append(f"- sha256 `{extract.sha256[:12]}`; extract: `{CONTEXT_DIR}/sources/{source.id}.json`")
                for note in extract.notes:
                    lines.append(f"- note: {note}")
                lines.append("")
                lines.append(_source_summary(extract))
            lines.append("")
    if storyboard:
        lines += ["## Storyboard (current)", ""]
        for scene in storyboard.scenes:
            lines.append(f"- `{scene.id}` {scene.start_seconds:g}-{scene.end_seconds:g} s: {scene.purpose}")
            if scene.narration:
                lines.append(f"  - narration: {scene.narration.plain_text}")
            for obj in scene.objects:
                lines.append(
                    f"  - object `{obj.id}` ({obj.kind}"
                    + (f", reveal at {obj.reveal_at_seconds:g} s" if obj.reveal_at_seconds is not None else "")
                    + ")"
                )
            for action in scene.actions:
                lines.append(
                    f"  - action `{action.id}` ({action.kind}): `{action.target}.{action.parameter}` to {action.to:g} "
                    f"over {action.at_seconds:g}-{action.end_seconds:g} s"
                    + (f", emphasizing {', '.join(f'`{e}`' for e in action.emphasize)}" if action.emphasize else "")
                )
            for snap in scene.snapshots:
                lines.append(f"  - snapshot `{snap.id}` at {snap.at_seconds:g} s: {snap.description}")
        lines.append("")
    else:
        lines += ["## Storyboard", "", "none yet: propose one with `create_storyboard`", ""]
    if style:
        lines += ["## Style roles and type", ""]
        lines.append(
            "Palette roles (use these as `style_role`): " + ", ".join(f"`{k}`" for k in sorted(style.tokens.palette))
        )
        t = style.tokens.typography
        lines.append(
            f"Text roles at 1080p: title {t.title.size_px_at_1080p:g}, body {t.body.size_px_at_1080p:g}, annotation {t.annotation.size_px_at_1080p:g}, "
            f"axis label {t.axis_label.size_px_at_1080p:g}, tick label {t.tick_label.size_px_at_1080p:g}, caption {t.caption.size_px_at_1080p:g}; "
            f"narration at {style.tokens.motion.narration_words_per_minute:g} words per minute."
        )
        lines.append("")
    lines += [f"## Registry (version {REGISTRY_VERSION})", ""]
    for kind in REGISTRY:
        described = describe_kind(kind)
        needs = []
        if described["requires_data"]:
            needs.append("needs `data`")
        if described["requires_equation"]:
            needs.append("needs `equation`")
        lines.append(f"### `{kind}`" + (f" ({', '.join(needs)})" if needs else ""))
        lines.append("")
        lines.extend(_params_lines(described["params"]))
        lines.append("")
    lines += ["## Feedback", ""]
    open_records = [f for f in feedback if f.kind != "status"]
    if not open_records:
        lines.append("no comments")
    for f in open_records:
        where = " / ".join(x for x in (f.revision_id, f.snapshot_id, f.object_id) if x)
        lines.append(f"- `{f.id}` ({f.severity}, {where}): {f.text}")
    lines.append("")
    if latest is not None:
        lines += [f"## Latest succeeded render: `{latest.job.job_id}` ({latest.job.revision_id})", ""]
        for c in latest.result.checkpoints:
            warnings = "; ".join(f"{w.code}: {w.detail}" for w in c.warnings) or "no layout warnings"
            lines.append(
                f"- `{c.snapshot_id}` ({c.kind}, {c.fidelity}) objects: {', '.join(i.object_id for i in c.layout) or 'none'}; {warnings}"
            )
        lines.append("")
    (out / "CONTEXT.md").write_text("\n".join(lines), encoding="utf-8")

    (out / "proposal.template.yaml").write_text(PROPOSAL_TEMPLATE, encoding="utf-8")
    schemas_dir = out / "schemas"
    schemas_dir.mkdir(exist_ok=True)
    for name in ("animation", "storyboard", "proposal", "feedback"):
        (schemas_dir / f"{name}.schema.json").write_text(schema_text(PUBLIC_SCHEMAS[name]), encoding="utf-8")
    sources_dir = out / "sources"
    sources_dir.mkdir(exist_ok=True)
    for extract in extracts.values():
        (sources_dir / f"{extract.source_id}.json").write_text(extract.model_dump_json(indent=2), encoding="utf-8")
    manifest = {
        "exported_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "project": {
            "id": animation.id if animation else None,
            "path": str(project.root),
            "family": report.family.manifest.id if report.family else None,
            "style": f"{style.theme}@{style.theme_version}" if style else None,
            "style_hash": style.hash if style else None,
            "animation_sha256": sha256_file(project.animation_path) if project.animation_path.exists() else None,
            "storyboard_sha256": sha256_file(project.storyboard_path) if project.storyboard_path.exists() else None,
            "revisions": [r.id for r in revisions],
        },
        "registry_version": REGISTRY_VERSION,
        "kinds": [describe_kind(k) for k in REGISTRY],
        "sources": {k: v.model_dump(mode="json") for k, v in extracts.items()},
        "feedback": [f.model_dump(mode="json") for f in feedback],
        "latest_render": (
            {
                "job_id": latest.job.job_id,
                "revision_id": latest.job.revision_id,
                "checkpoints": [c.model_dump(mode="json") for c in latest.result.checkpoints],
            }
            if latest
            else None
        ),
        "validation": {"ok": report.ok, "errors": report.errors, "warnings": report.warnings},
    }
    (out / "context.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return out


PROPOSAL_TEMPLATE = """\
# A proposal: validate with `scianim propose validate <project> <this file>`, apply with `scianim propose apply`.
schema_version: "1.0"
id: prop_example            # prop_<slug>, unique within the project
kind: revise_storyboard     # create_spec | revise_spec | create_storyboard | revise_storyboard | analyze_feedback
created_at: "2026-01-01T00:00:00+00:00"
author: "agent:example"
summary: "One line: what changes."
rationale: "Why, in terms of the brief, the sources and the feedback."
based_on_revision: working  # or rev_NNNN
in_response_to: []          # feedback record ids
uncertainties:
  - "Questions the sources do not answer; ask, do not invent."
claims:
  - statement: "A scientific statement the change relies on."
    source_id: some_source
    locator: "page 3, figure 2"
    basis: source           # source | inference | assumption
touches_science: false      # true when equations, sources, data bindings or constraints change
targets:
  - file: storyboard.yaml
    patch:                  # JSON-pointer operations (add | replace | remove), or `document:` with a whole file
      - op: replace
        path: /scenes/0/purpose
        value: "A better purpose."
"""


__all__ = ["CONTEXT_DIR", "PROPOSAL_TEMPLATE", "describe_kind", "export_context"]
