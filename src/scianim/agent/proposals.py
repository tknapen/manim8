"""Proposals: validate an agent's suggested spec or storyboard before writing it, then apply it with a diff.

The control plane never calls a model. An agent (a coding agent on the CLI, a hosted API behind an
adapter, or a person) writes `proposals/<id>.yaml`; `scianim propose validate` checks the resulting
documents against the contracts and the cross-file rules without touching the project, and
`scianim propose apply` writes them to the working copy and records the proposal with its unified diff
under `proposals/applied/`. A change to equations, sources, data bindings or scientific constraints is
flagged for human sign-off and is never approved by the tool.
"""

from __future__ import annotations

import copy
import datetime as dt
import difflib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from ruamel.yaml import YAML

from scianim.config.loader import SpecError, format_validation_error, load_yaml
from scianim.planning.checks import Report, validate_project
from scianim.project import ANIMATION_FILE, STORYBOARD_FILE, Project
from scianim.revisions.store import latest_revision
from scianim_core import AnimationSpec, AppliedProposal, Proposal, Storyboard
from scianim_core.proposals import PatchOperation

PROPOSALS_DIR = "proposals"
APPLIED_DIR = "proposals/applied"
MARKER_MESSAGES = ("checkpoint() marker", "markers not in the storyboard", "duplicate checkpoint()", "scene module")

_yaml = YAML()
_yaml.default_flow_style = False
_yaml.indent(mapping=2, sequence=4, offset=2)
_yaml.width = 110


def load_proposal(path: Path) -> Proposal:
    data = load_yaml(path)
    try:
        return Proposal.model_validate(data)
    except ValidationError as exc:
        raise SpecError(path, f"invalid proposal:\n{format_validation_error(exc)}") from None


def _pointer_parts(pointer: str) -> list[str]:
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer.split("/")[1:]]


def _descend(container: Any, parts: list[str], pointer: str) -> Any:
    node = container
    for part in parts:
        if isinstance(node, list):
            try:
                node = node[int(part)]
            except (ValueError, IndexError):
                raise SpecError(None, f"patch path {pointer}: no list index '{part}'") from None
        elif isinstance(node, dict):
            if part not in node:
                raise SpecError(None, f"patch path {pointer}: no key '{part}'")
            node = node[part]
        else:
            raise SpecError(None, f"patch path {pointer}: '{part}' is not inside a mapping or list")
    return node


def apply_patch(document: dict[str, Any], operations: list[PatchOperation]) -> dict[str, Any]:
    """RFC 6902 add/replace/remove on a deep copy; `-` appends to a list."""
    result = copy.deepcopy(document)
    for op in operations:
        parts = _pointer_parts(op.path)
        if not parts:
            raise SpecError(None, "a patch may not replace the whole document; use `document` instead")
        parent = _descend(result, parts[:-1], op.path)
        key = parts[-1]
        if isinstance(parent, list):
            if key == "-" and op.op == "add":
                parent.append(copy.deepcopy(op.value))
                continue
            try:
                index = int(key)
            except ValueError:
                raise SpecError(None, f"patch path {op.path}: list index expected") from None
            if op.op == "add":
                parent.insert(index, copy.deepcopy(op.value))
            elif op.op == "replace":
                if index >= len(parent):
                    raise SpecError(None, f"patch path {op.path}: index out of range")
                parent[index] = copy.deepcopy(op.value)
            else:
                if index >= len(parent):
                    raise SpecError(None, f"patch path {op.path}: index out of range")
                del parent[index]
        elif isinstance(parent, dict):
            if op.op == "remove":
                if key not in parent:
                    raise SpecError(None, f"patch path {op.path}: no key '{key}' to remove")
                del parent[key]
            elif op.op == "replace" and key not in parent:
                raise SpecError(None, f"patch path {op.path}: no key '{key}' to replace (use add)")
            else:
                parent[key] = copy.deepcopy(op.value)
        else:
            raise SpecError(None, f"patch path {op.path}: parent is neither a mapping nor a list")
    return result


@dataclass
class ResolvedProposal:
    proposal: Proposal
    documents: dict[str, dict[str, Any]]
    """Resulting content per target file."""
    before: dict[str, dict[str, Any] | None]
    report: Report
    touches_science: bool
    warnings: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[str]:
        return [e for e in self.report.errors if not any(m in e for m in MARKER_MESSAGES)]

    @property
    def ok(self) -> bool:
        return not self.errors


def _science_keys(file: str, before: dict[str, Any] | None, after: dict[str, Any]) -> bool:
    if file == ANIMATION_FILE:
        keys = ("equations", "sources", "scientific_constraints")
        return any((before or {}).get(k) != after.get(k) for k in keys)
    bindings_before = _bindings(before or {})
    return bindings_before != _bindings(after)


def _bindings(storyboard: dict[str, Any]) -> list[tuple[str, Any, Any]]:
    out = []
    for scene in storyboard.get("scenes", []) or []:
        for obj in scene.get("objects", []) or []:
            out.append((obj.get("id"), obj.get("data"), obj.get("equation")))
    return sorted(out, key=lambda item: str(item[0]))


def resolve_proposal(project: Project, proposal: Proposal) -> ResolvedProposal:
    """Compute the documents a proposal produces and validate them without writing anything."""
    documents: dict[str, dict[str, Any]] = {}
    before: dict[str, dict[str, Any] | None] = {}
    for target in proposal.targets:
        path = project.root / target.file
        current = load_yaml(path) if path.exists() else None
        before[target.file] = current
        if target.document is not None:
            documents[target.file] = copy.deepcopy(target.document)
        else:
            if current is None:
                raise SpecError(path, f"{target.file} does not exist; a patch needs a document to patch")
            documents[target.file] = apply_patch(current, target.patch or [])
    animation_doc = documents.get(ANIMATION_FILE)
    storyboard_doc = documents.get(STORYBOARD_FILE)
    try:
        animation = AnimationSpec.model_validate(animation_doc) if animation_doc is not None else None
    except ValidationError as exc:
        raise SpecError(
            project.animation_path, f"proposed animation.yaml is invalid:\n{format_validation_error(exc)}"
        ) from None
    try:
        storyboard = Storyboard.model_validate(storyboard_doc) if storyboard_doc is not None else None
    except ValidationError as exc:
        raise SpecError(
            project.storyboard_path, f"proposed storyboard.yaml is invalid:\n{format_validation_error(exc)}"
        ) from None
    report = validate_project(project, require_family=True, animation=animation, storyboard=storyboard)
    touches = proposal.touches_science or any(_science_keys(file, before[file], documents[file]) for file in documents)
    return ResolvedProposal(proposal, documents, before, report, touches, warnings=list(report.warnings))


def _dump(document: dict[str, Any]) -> str:
    from io import StringIO

    buffer = StringIO()
    _yaml.dump(document, buffer)
    return buffer.getvalue()


def apply_proposal(project: Project, proposal: Proposal) -> AppliedProposal:
    resolved = resolve_proposal(project, proposal)
    if not resolved.ok:
        raise SpecError(project.root, "the proposal does not validate:\n  - " + "\n  - ".join(resolved.errors))
    applied_dir = project.root / APPLIED_DIR
    applied_dir.mkdir(parents=True, exist_ok=True)
    record_path = applied_dir / f"{proposal.id}.yaml"
    if record_path.exists():
        raise SpecError(record_path, "this proposal id was applied before; proposals are applied once")
    latest = latest_revision(project)
    diffs: dict[str, str] = {}
    for file, document in resolved.documents.items():
        path = project.root / file
        old_text = path.read_text(encoding="utf-8") if path.exists() else ""
        new_text = _dump(document)
        diffs[file] = "".join(
            difflib.unified_diff(
                old_text.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=f"a/{file}",
                tofile=f"b/{file}",
            )
        )
        path.write_text(new_text, encoding="utf-8")
    applied = AppliedProposal(
        proposal=proposal,
        applied_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        applied_to_revision="working",
        latest_revision_before=latest.id if latest else None,
        diffs=diffs,
        scientific_review_required=resolved.touches_science,
        validation_warnings=resolved.warnings,
    )
    with record_path.open("w", encoding="utf-8") as handle:
        _yaml.dump(applied.model_dump(mode="json", exclude_none=True), handle)
    return applied


def list_applied(project: Project) -> list[AppliedProposal]:
    directory = project.root / APPLIED_DIR
    if not directory.is_dir():
        return []
    records: list[AppliedProposal] = []
    for path in sorted(directory.glob("*.yaml")):
        try:
            records.append(AppliedProposal.model_validate(load_yaml(path)))
        except (ValidationError, SpecError):
            continue
    return records


def list_pending(project: Project) -> list[Path]:
    directory = project.root / PROPOSALS_DIR
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.glob("*.yaml"))


__all__ = [
    "APPLIED_DIR",
    "PROPOSALS_DIR",
    "ResolvedProposal",
    "apply_patch",
    "apply_proposal",
    "list_applied",
    "list_pending",
    "load_proposal",
    "resolve_proposal",
]
