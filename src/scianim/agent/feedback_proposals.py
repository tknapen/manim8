"""Feedback becomes proposals, by rules and without a model (ADR-036).

`scianim propose from-feedback` reads the open feedback records (comments and review statuses that no applied
proposal has answered) and the live inspection of the latest render, and writes one typed `Proposal` per item
a rule can address: a layout warning becomes a concrete storyboard patch, a comment that names a parameter and
a value becomes that change, a timing complaint moves the nearest action's duration. Everything the rules
cannot turn into a patch is listed as unresolved, with the question a person or an external agent must answer;
a scientific concern is never patched by a rule. A proposal names the feedback it answers in `in_response_to`,
and a feedback record counts as addressed once an applied proposal names it, so records stay write-once.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scianim.agent.inspect import Finding, inspect_manifest
from scianim.agent.proposals import list_applied, list_pending, load_proposal, resolve_proposal
from scianim.config.loader import SpecError, load_yaml, safe_yaml
from scianim.feedback.store import list_feedback
from scianim.planning.checks import Report
from scianim.project import Project
from scianim_core import ArtifactManifest, FeedbackRecord, PatchOperation, Proposal, ProposalTarget
from scianim_core.components import REGISTRY

AUTHOR = "agent:feedback"
SHRINK = 0.85
"""How much a rule shrinks a `size_fraction` that runs off the page or into a neighbour."""
SLOWER, FASTER = 1.25, 0.8
"""How a rule stretches or shortens an action called too fast or too slow."""

_NUMBER = re.compile(r"\b([a-z][a-z0-9_]*)\s*(?:=|:|to|→)\s*(-?\d+(?:\.\d+)?)\b")


@dataclass
class Unresolved:
    reason: str
    feedback_id: str | None = None
    snapshot_id: str | None = None
    object_id: str | None = None
    text: str = ""
    science: bool = False


@dataclass
class Generated:
    proposals: list[Proposal] = field(default_factory=list)
    unresolved: list[Unresolved] = field(default_factory=list)
    written: list[Path] = field(default_factory=list)


def addressed_ids(project: Project) -> dict[str, str]:
    """Feedback id to the applied proposal that answered it."""
    answered: dict[str, str] = {}
    for applied in list_applied(project):
        for feedback_id in applied.proposal.in_response_to:
            answered.setdefault(feedback_id, applied.proposal.id)
    for path in list_pending(project):
        try:
            pending = load_proposal(path)
        except Exception:  # a broken pending file is not an answer
            continue
        for feedback_id in pending.in_response_to:
            answered.setdefault(feedback_id, f"{pending.id} (pending)")
    return answered


def open_feedback(project: Project) -> list[FeedbackRecord]:
    """Comments, and statuses asking for revision, that no proposal has answered yet."""
    answered = addressed_ids(project)
    records = []
    for record in list_feedback(project):
        if record.id in answered:
            continue
        if record.kind == "status" and record.status == "approved":
            continue
        records.append(record)
    return records


# --- the storyboard document as rules see it -----------------------------------------------------
@dataclass
class _Located:
    scene_index: int
    object_index: int
    scene_id: str
    data: dict[str, Any]

    @property
    def params(self) -> dict[str, Any]:
        return self.data.setdefault("params", {})

    def pointer(self, *tail: str) -> str:
        return "/".join(["", "scenes", str(self.scene_index), "objects", str(self.object_index), *tail])


def _locate(storyboard: dict[str, Any], object_id: str, scene_id: str | None = None) -> _Located | None:
    for i, scene in enumerate(storyboard.get("scenes", [])):
        if scene_id is not None and scene.get("id") != scene_id:
            continue
        for j, obj in enumerate(scene.get("objects", [])):
            if obj.get("id") == object_id:
                return _Located(i, j, scene.get("id", ""), obj)
    return None


def _set(located: _Located, key: str, value: Any) -> PatchOperation:
    op = "replace" if key in located.params else "add"
    return PatchOperation(op=op, path=located.pointer("params", key), value=value)


def _actions_on(storyboard: dict[str, Any], object_id: str) -> list[tuple[int, int, dict[str, Any]]]:
    found = []
    for i, scene in enumerate(storyboard.get("scenes", [])):
        for k, action in enumerate(scene.get("actions", [])):
            if action.get("target") == object_id:
                found.append((i, k, action))
    return found


# --- rules ----------------------------------------------------------------------------------------
@dataclass
class _Rule:
    summary: str
    rationale: str
    patch: list[PatchOperation]
    uncertainties: list[str] = field(default_factory=list)
    file: str = "storyboard.yaml"


def _fields(located: _Located) -> set[str]:
    """The parameter names the object's kind accepts, so a rule may add a parameter the storyboard left to its
    default."""
    definition = REGISTRY.get(located.data.get("kind", ""))
    return set(definition.params_model.model_fields) if definition is not None else set(located.params)


def _off_page(located: _Located) -> _Rule | None:
    params = located.params
    fields = _fields(located)
    if "size_fraction" in fields:
        current = float(params.get("size_fraction", 0.6))
        value = round(current * SHRINK, 2)
        return _Rule(
            f"shrink '{located.data['id']}' from {current:g} to {value:g} of the frame so it stays on the page",
            "rule: an object outside the safe zone with a size_fraction is drawn smaller first; its anchor is kept",
            [_set(located, "size_fraction", value)],
            [f"{SHRINK:g} is a rule's step; the right size is a matter of looking at the still"],
        )
    if "anchor" in fields:
        current = params.get("anchor", "top_left")
        if current == "center":
            return None
        return _Rule(
            f"move '{located.data['id']}' from {current} to the centre so it stays on the page",
            "rule: a text-like object outside the safe zone is anchored where there is most room",
            [_set(located, "anchor", "center")],
            ["the centre is a rule's choice; another anchor may read better beside the other objects"],
        )
    return None


def _overlap(located: _Located, other: _Located | None) -> _Rule | None:
    candidates = [c for c in (located, other) if c is not None]
    sized = [c for c in candidates if "size_fraction" in _fields(c)]
    if sized:
        target = max(sized, key=lambda c: float(c.params.get("size_fraction", 0.6)))
        current = float(target.params.get("size_fraction", 0.6))
        value = round(current * SHRINK, 2)
        return _Rule(
            f"shrink '{target.data['id']}' from {current:g} to {value:g} of the frame so it clears its neighbour",
            "rule: of two overlapping objects, the larger sized one gives way",
            [_set(target, "size_fraction", value)],
            [f"{SHRINK:g} is a rule's step; moving an anchor may be the better answer"],
        )
    if (
        other is not None
        and located.params.get("anchor")
        and located.params.get("anchor") == other.params.get("anchor")
    ):
        anchor = str(other.params["anchor"])
        moved = {
            "top_left": "top_right",
            "top_right": "top_left",
            "bottom_left": "bottom_right",
            "bottom_right": "bottom_left",
        }.get(anchor)
        if moved:
            return _Rule(
                f"move '{other.data['id']}' from {anchor} to {moved}, away from '{located.data['id']}'",
                "rule: two text-like objects on one anchor part to opposite corners",
                [_set(other, "anchor", moved)],
            )
    return None


def _named_values(text: str, located: _Located) -> _Rule | None:
    """A comment that names one of the object's numeric parameters and a value: `set width_fraction to 0.5`,
    `sigma = 1.2`; the parameter may be one the storyboard left at its default."""
    fields = _fields(located)
    definition = REGISTRY.get(located.data.get("kind", ""))
    ops = []
    for name, number in _NUMBER.findall(text.lower()):
        current: Any = located.params.get(name)
        if current is None and definition is not None and name in fields:
            current = definition.params_model.model_fields[name].default
        if name in fields and isinstance(current, int | float) and not isinstance(current, bool):
            value = int(number) if isinstance(current, int) and "." not in number else float(number)
            ops.append(_set(located, name, value))
        elif name in located.params.get("parameters", {}):
            ops.append(
                PatchOperation(op="replace", path=located.pointer("params", "parameters", name), value=float(number))
            )
    if not ops:
        return None
    names = ", ".join(op.path.rsplit("/", 1)[-1] for op in ops)
    return _Rule(
        f"set {names} on '{located.data['id']}' as the comment asks",
        "rule: a comment that names a parameter and a value is taken at its word",
        ops,
    )


def _pace(storyboard: dict[str, Any], record: FeedbackRecord) -> _Rule | None:
    text = record.text.lower()
    if "too fast" in text or "too quick" in text:
        factor, word = SLOWER, "longer"
    elif "too slow" in text:
        factor, word = FASTER, "shorter"
    else:
        return None
    actions = _actions_on(storyboard, record.object_id) if record.object_id else []
    if not actions:
        for i, scene in enumerate(storyboard.get("scenes", [])):
            if record.scene_id is None or scene.get("id") == record.scene_id:
                actions += [(i, k, a) for k, a in enumerate(scene.get("actions", [])) if "duration_seconds" in a]
    if not actions:
        return None
    moment = record.time_seconds
    if moment is not None:
        actions.sort(key=lambda item: abs(float(item[2].get("at_seconds", 0)) - moment))
    i, k, action = actions[0]
    current = float(action.get("duration_seconds", 1.0))
    value = round(current * factor, 2)
    if factor > 1:
        # A longer motion may not run into the next action on the same object; leave half a second of rest.
        start = float(action.get("at_seconds", 0)) + float(action.get("lead_in_seconds", 0) or 0)
        later = [
            float(a.get("at_seconds", 0))
            for _, _, a in _actions_on(storyboard, str(action.get("target")))
            if float(a.get("at_seconds", 0)) > start + 1e-9
        ]
        if later:
            room = round(min(later) - start - 0.5, 2)
            if room <= current:
                return None
            value = min(value, room)
    return _Rule(
        f"make '{action.get('id')}' {word}: {current:g} s to {value:g} s",
        f"rule: a motion called {'too fast' if factor > 1 else 'too slow'} changes its duration by {factor:g}",
        [PatchOperation(op="replace", path=f"/scenes/{i}/actions/{k}/duration_seconds", value=value)],
        ["the factor is a rule's step; the storyboard's hold and lead-in rules still apply to the new duration"],
    )


def _rule_for_comment(storyboard: dict[str, Any], record: FeedbackRecord) -> _Rule | None:
    located = _locate(storyboard, record.object_id, record.scene_id) if record.object_id else None
    text = record.text.lower()
    if located is not None:
        named = _named_values(record.text, located)
        if named is not None:
            return named
        if any(key in text for key in ("safe zone", "off the page", "outside the frame", "runs off", "clipped")):
            return _off_page(located)
        if "overlap" in text or "collides" in text or "runs into" in text:
            return _overlap(located, None)
    return _pace(storyboard, record)


def _rule_for_finding(storyboard: dict[str, Any], finding: Finding, manifest: ArtifactManifest) -> _Rule | None:
    scene_id = (
        manifest.job.snapshots[finding.snapshot_id].scene_id if finding.snapshot_id in manifest.job.snapshots else None
    )
    located = _locate(storyboard, finding.object_id, scene_id) if finding.object_id else None
    if located is None:
        return None
    if finding.code == "outside_safe_zone":
        return _off_page(located)
    if finding.code == "overlap":
        others = (
            re.findall(r"\b([a-z][a-z0-9_]*)\b", finding.detail.rsplit("(", 1)[-1]) if "(" in finding.detail else []
        )
        other = next(
            (
                _locate(storyboard, o, scene_id)
                for o in others
                if o != finding.object_id and _locate(storyboard, o, scene_id)
            ),
            None,
        )
        return _overlap(located, other)
    return None


# --- generation -----------------------------------------------------------------------------------
def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", text.lower()).strip("_")[:40] or "x"


def _proposal(rule: _Rule, feedback_ids: list[str], stamp: str, index: int, revision: str) -> Proposal:
    return Proposal(
        id=f"prop_fb_{stamp}_{index:02d}_{_slug(rule.patch[0].path.rsplit('/', 1)[-1])}",
        kind="revise_storyboard" if rule.file == "storyboard.yaml" else "revise_spec",
        created_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        author=AUTHOR,
        summary=rule.summary,
        rationale=rule.rationale,
        based_on_revision=revision,  # type: ignore[arg-type]
        in_response_to=feedback_ids,
        uncertainties=rule.uncertainties,
        claims=[],
        targets=[ProposalTarget(file=rule.file, patch=rule.patch)],  # type: ignore[arg-type]
    )


def generate(
    project: Project,
    report: Report,
    manifest: ArtifactManifest | None,
    *,
    write: bool = True,
    now: dt.datetime | None = None,
) -> Generated:
    """Proposals for the open feedback and the live inspection findings; writes them under `proposals/`."""
    out = Generated()
    assert report.storyboard is not None
    storyboard = load_yaml(project.storyboard_path)
    stamp = (now or dt.datetime.now(dt.UTC)).strftime("%Y%m%dt%H%M%S")
    revision = "working"
    seen_paths: set[str] = set()
    items: list[tuple[_Rule | None, list[str], Unresolved]] = []

    for record in open_feedback(project):
        science = record.severity == "scientific" or record.status == "scientific_concern"
        if science:
            items.append(
                (
                    None,
                    [record.id],
                    Unresolved(
                        "a scientific concern is never patched by a rule; it needs a decision",
                        record.id,
                        record.snapshot_id,
                        record.object_id,
                        record.text,
                        True,
                    ),
                )
            )
            continue
        rule = _rule_for_comment(storyboard, record)
        reason = "no rule reads this comment; a person or an external agent must propose the change"
        items.append(
            (rule, [record.id], Unresolved(reason, record.id, record.snapshot_id, record.object_id, record.text))
        )

    if manifest is not None:
        for finding in inspect_manifest(project, manifest, report.storyboard):
            if finding.severity == "note":
                continue
            rule = _rule_for_finding(storyboard, finding, manifest)
            reason = (
                f"inspection finding '{finding.code}' has no rule"
                if finding.code not in ("outside_safe_zone", "overlap")
                else f"'{finding.code}' on an object without a size or an anchor to change"
            )
            items.append((rule, [], Unresolved(reason, None, finding.snapshot_id, finding.object_id, finding.detail)))

    index = 0
    for rule, feedback_ids, unresolved in items:
        if rule is None:
            out.unresolved.append(unresolved)
            continue
        key = "|".join(sorted(op.path for op in rule.patch))
        if key in seen_paths:
            continue  # the same change proposed twice (a comment and the inspection agree)
        seen_paths.add(key)
        index += 1
        proposal = _proposal(rule, feedback_ids, stamp, index, revision)
        try:
            resolved = resolve_proposal(project, proposal)
            problems = resolved.errors
        except SpecError as exc:
            problems = [str(exc)]
        if problems:
            out.unresolved.append(
                Unresolved(
                    "the rule's patch does not validate: " + "; ".join(problems),
                    feedback_ids[0] if feedback_ids else None,
                    unresolved.snapshot_id,
                    unresolved.object_id,
                    unresolved.text,
                )
            )
            continue
        out.proposals.append(proposal)
        if write:
            directory = project.root / "proposals"
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"{proposal.id}.yaml"
            with path.open("w", encoding="utf-8") as handle:
                safe_yaml().dump(proposal.model_dump(mode="json", exclude_none=True), handle)
            out.written.append(path)
    return out


__all__ = ["AUTHOR", "Generated", "Unresolved", "addressed_ids", "generate", "open_feedback"]
