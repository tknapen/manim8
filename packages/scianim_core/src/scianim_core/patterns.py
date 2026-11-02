"""The pattern library: named ways of making a mechanism move on screen, for an agent to choose from (ADR-040).

A pattern is a staging idiom with a purpose: a parameter sweep with a readout shows a dependence; a rewrite
whose matching terms glide shows that two equations are one. Each entry says when the idiom serves an
explanation and when it does not, the beats it is staged in, the time those beats usually take, which
registered components and storyboard actions realize it today, and what is still missing where they do not.
Its evidence is of two kinds, kept apart: how often one author's corpus uses the idiom (the survey of the
3Blue1Brown videos repository, docs/ANIMATION_PATTERNS.md), and what experiments on learning from animation
found. A recipe points at a scene of an example project that shows the pattern and is rendered with the
examples, so a recipe is never a claim that a picture exists.

The catalogue lives in `patterns/` of the control plane's data (one YAML file per pattern, with
`references.yaml` and the survey's output); these models are its contract. Scenes name the patterns they use
in `Scene.patterns`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from scianim_core.common import Slug, StrictModel, ensure_unique

PatternStatus = Literal["available", "partial", "planned"]
"""`available`: registered components and actions realize the pattern as described. `partial`: they realize
an approximation, and `needs` says what the full pattern lacks. `planned`: nothing realizes it yet without a
custom builder; `needs` names the missing capability."""

PatternGroup = Literal["change", "form", "attention", "viewpoint", "motion", "chance"]
"""What the pattern acts on: a quantity that changes, the form an expression or a picture takes, where the
viewer looks, where the viewer stands, how a thing moves through time, or a random process."""

ReferenceCheck = Literal["bibliographic", "abstract", "full_text"]
"""How far a reference was checked: its bibliographic record, its abstract, or the full text."""


class SecondsRange(StrictModel):
    min: float = Field(ge=0, allow_inf_nan=False)
    max: float = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def _ordered(self) -> SecondsRange:
        if self.max < self.min:
            raise ValueError(f"max ({self.max}) is smaller than min ({self.min})")
        return self


class PatternTiming(StrictModel):
    """Usual durations of the beats, in seconds of the clip. A guide drawn from the survey and the style's
    motion rules, not a constraint the validator enforces."""

    lead_in: SecondsRange | None = None
    """Before the change: the term lights up, the object appears."""
    change: SecondsRange | None = None
    """The change itself: the sweep, the move, the rewrite, the turn."""
    hold: SecondsRange | None = None
    """After the change, before the next thing moves."""
    note: str | None = None


class PatternRecipe(StrictModel):
    """A scene of an example project that shows the pattern."""

    project: str = Field(pattern=r"^[a-z][a-z0-9_]*(/[a-z][a-z0-9_]*)+$")
    """The project's path under `examples/families/`, e.g. `computational_neuroscience/gabor_filter`."""
    scene: Slug
    note: str | None = None
    """What in the scene shows the pattern, when the scene does more than that."""


class CorpusEvidence(StrictModel):
    """Where a corpus shows the idiom: counted by the survey, found by reading scenes, or both."""

    idioms: list[str] = []
    """Names of idiom flags in the survey output (`patterns/survey/*.json`, "scenes with idiom (%)")."""
    exemplars: list[str] = []
    """Scenes of the corpus that use the idiom, as `path::SceneClass` at the survey's commit."""
    note: str | None = None

    @model_validator(mode="after")
    def _some_evidence(self) -> CorpusEvidence:
        if not (self.idioms or self.exemplars):
            raise ValueError("corpus evidence names neither a surveyed idiom nor an exemplar scene")
        return self


class Pattern(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    id: Slug
    name: str = Field(min_length=1)
    group: PatternGroup
    summary: str = Field(min_length=1)
    """What the viewer sees and what it lets them understand, in a sentence or two."""
    use_when: list[str] = Field(min_length=1)
    """Signs in the brief or the science that the pattern fits."""
    avoid_when: list[str] = []
    beats: list[str] = Field(min_length=1)
    """The pattern's steps in the order the viewer sees them."""
    timing: PatternTiming = PatternTiming()
    status: PatternStatus
    components: list[str] = []
    """Registered component kinds that can carry the pattern."""
    actions: list[str] = []
    """Storyboard action kinds that realize it; `reveal` stands for an object's `reveal_at_seconds`."""
    needs: list[str] = []
    """What a full realization lacks: a component, an action or an option, in a phrase each."""
    recipes: list[PatternRecipe] = []
    corpus: CorpusEvidence | None = None
    research: list[Slug] = []
    """Keys of `references.yaml` entries whose findings bear on the pattern."""
    pitfalls: list[str] = []
    related: list[Slug] = []
    """Other patterns this one combines with or is confused with."""

    @model_validator(mode="after")
    def _status_consistency(self) -> Pattern:
        if self.status == "available" and self.needs:
            raise ValueError(f"pattern '{self.id}' is available but lists needs {self.needs}")
        if self.status != "available" and not self.needs:
            raise ValueError(f"pattern '{self.id}' is {self.status} but names nothing it needs")
        if self.status == "planned" and self.recipes:
            raise ValueError(f"pattern '{self.id}' is planned, so no example can show it yet")
        if self.status != "planned" and not (self.components or self.actions):
            raise ValueError(f"pattern '{self.id}' is {self.status} but names no component or action")
        if self.id in self.related:
            raise ValueError(f"pattern '{self.id}' lists itself as related")
        return self


class Reference(StrictModel):
    key: Slug
    citation: str = Field(min_length=1)
    doi: str | None = Field(default=None, pattern=r"^10\.\d{4,9}/\S+$")
    finding: str = Field(min_length=1)
    """What the work reports that bears on the library, in the library's words."""
    checked: ReferenceCheck
    """How far the citation and the finding were checked against the source."""


class ReferenceList(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    references: list[Reference] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> ReferenceList:
        ensure_unique((r.key for r in self.references), "reference")
        return self
