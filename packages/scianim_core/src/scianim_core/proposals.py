"""Proposals: the provider-neutral form in which an agent suggests a spec or storyboard change (spec 7.3).

A proposal is a YAML file. It carries a human-readable summary and rationale, the agent's open
uncertainties, the scientific claims it relies on with their source locators, and for each target
file either a complete `document` or a `patch` (a small list of JSON-pointer operations). The control
plane validates the resulting files before anything is written, applies the change to the working
copy, and keeps the proposal with its unified diff; approval of scientific content stays with people.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from scianim_core.common import SchemaVersion, Slug, StrictModel

ProposalKind = Literal[
    "create_spec",
    "revise_spec",
    "create_storyboard",
    "revise_storyboard",
    "analyze_feedback",
]
TargetFile = Literal["animation.yaml", "storyboard.yaml"]
PROPOSAL_ID_PATTERN = r"^prop_[a-z0-9][a-z0-9_]{0,63}$"


class PatchOperation(StrictModel):
    """RFC 6902 subset: add, replace or remove at a JSON pointer."""

    op: Literal["add", "replace", "remove"]
    path: str = Field(pattern=r"^(/[^/]*)+$")
    value: Any = None

    @model_validator(mode="after")
    def _value_present(self) -> PatchOperation:
        if self.op in ("add", "replace") and self.value is None:
            raise ValueError(f"'{self.op}' at {self.path} needs a value")
        return self


class Claim(StrictModel):
    """A scientific statement the proposal relies on, tied to a source and a locator."""

    statement: str = Field(min_length=1)
    source_id: Slug | None = None
    locator: str | None = None
    """Page, figure, equation or column reference inside the source."""
    basis: Literal["source", "inference", "assumption"] = "source"


class ProposalTarget(StrictModel):
    file: TargetFile
    document: dict[str, Any] | None = None
    """The complete new content of the file."""
    patch: list[PatchOperation] | None = None
    """Targeted edits applied to the current file."""

    @model_validator(mode="after")
    def _one_form(self) -> ProposalTarget:
        if (self.document is None) == (self.patch is None):
            raise ValueError(f"target {self.file} needs exactly one of `document` or `patch`")
        return self


class Proposal(StrictModel):
    schema_version: SchemaVersion = "1.0"
    id: str = Field(pattern=PROPOSAL_ID_PATTERN)
    kind: ProposalKind
    created_at: str
    author: str = Field(min_length=1)
    """Who or what produced it, e.g. 'agent:claude-code' or a person."""
    summary: str = Field(min_length=1)
    rationale: str = ""
    based_on_revision: str | None = Field(default=None, pattern=r"^(working|rev_\d{4})$")
    in_response_to: list[str] = []
    """Feedback record ids this proposal answers."""
    uncertainties: list[str] = []
    """Open questions the agent could not resolve from the sources; asked, not invented."""
    claims: list[Claim] = []
    targets: list[ProposalTarget] = Field(min_length=1)
    touches_science: bool = False
    """Set when equations, data sources or scientific constraints change; such a change needs human sign-off."""

    @model_validator(mode="after")
    def _targets_unique(self) -> Proposal:
        files = [t.file for t in self.targets]
        if len(files) != len(set(files)):
            raise ValueError("each target file may appear once")
        return self


class AppliedProposal(StrictModel):
    """What the control plane recorded when a proposal was applied."""

    schema_version: SchemaVersion = "1.0"
    proposal: Proposal
    applied_at: str
    applied_to_revision: str
    """`working` plus the latest revision id at the time, so the diff has a known base."""
    latest_revision_before: str | None = None
    diffs: dict[str, str] = {}
    """Unified diff per target file."""
    scientific_review_required: bool = False
    validation_warnings: list[str] = []


SCIENTIFIC_PATHS = ("equations", "sources", "scientific_constraints", "data", "equation")
"""Top-level animation keys and storyboard object keys whose change touches scientific content."""


__all__ = [
    "PROPOSAL_ID_PATTERN",
    "SCIENTIFIC_PATHS",
    "AppliedProposal",
    "Claim",
    "PatchOperation",
    "Proposal",
    "ProposalKind",
    "ProposalTarget",
    "TargetFile",
]
