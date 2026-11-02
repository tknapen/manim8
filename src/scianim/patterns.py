"""The pattern library on disk (ADR-040): load and cross-check it, find recipes, check a storyboard's use of it.

The library is data: `catalogue/<id>.yaml` (one `Pattern` each), `references.yaml` (a `ReferenceList`) and
`survey/*.json` (the output of `tools/survey_corpus.py`). A checkout reads it from the repository's
`patterns/`, an installed wheel from its own data (ADR-037), and `SCIANIM_PATTERNS` overrides both.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from io import StringIO
from pathlib import Path
from typing import Any, get_args

from pydantic import ValidationError
from ruamel.yaml import YAML

from scianim import workspace
from scianim.config.loader import SpecError, format_validation_error, load_yaml
from scianim.project import env_paths
from scianim_core import REGISTRY
from scianim_core.patterns import Pattern, Reference, ReferenceList
from scianim_core.storyboard import Scene, SceneAction, Storyboard

CATALOGUE_DIR = "catalogue"
REFERENCES_FILE = "references.yaml"
SURVEY_DIR = "survey"
REVEAL = "reveal"
"""The action name a pattern uses for an object's `reveal_at_seconds`."""
STATUS_ORDER = ("available", "partial", "planned")
GROUP_ORDER = ("change", "form", "attention", "viewpoint", "motion", "chance")
SHARE_KEY = "scenes with idiom (%)"


def patterns_root() -> Path:
    for candidate in env_paths("SCIANIM_PATTERNS"):
        if candidate.is_dir():
            return candidate
    root = workspace.repo_root()
    if root is not None and (root / "patterns" / CATALOGUE_DIR).is_dir():
        return root / "patterns"
    if (workspace.DATA_ROOT / "patterns" / CATALOGUE_DIR).is_dir():
        return workspace.DATA_ROOT / "patterns"
    raise SpecError(None, "no pattern library found; set SCIANIM_PATTERNS or reinstall manim8")


def action_kinds() -> set[str]:
    """Every storyboard action kind, and `reveal`."""
    union = get_args(SceneAction)[0]
    kinds = {get_args(model.model_fields["kind"].annotation)[0] for model in get_args(union)}
    return kinds | {REVEAL}


@dataclass(frozen=True)
class PatternLibrary:
    root: Path
    patterns: dict[str, Pattern]
    references: dict[str, Reference]
    surveys: dict[str, dict[str, Any]]
    """Survey outputs by file stem, e.g. `3b1b_videos`."""

    def ordered(self) -> list[Pattern]:
        """Available patterns first, then partial, then planned; by group and id within each."""
        return sorted(
            self.patterns.values(),
            key=lambda p: (STATUS_ORDER.index(p.status), GROUP_ORDER.index(p.group), p.id),
        )

    def idiom_shares(self, pattern: Pattern) -> dict[str, dict[str, dict[str, float]]]:
        """For each survey and each idiom the pattern names: the share of scenes using it, per era."""
        result: dict[str, dict[str, dict[str, float]]] = {}
        if pattern.corpus is None:
            return result
        for name, survey in self.surveys.items():
            shares = survey.get(SHARE_KEY, {})
            per_idiom = {
                idiom: {era: values[idiom] for era, values in shares.items() if idiom in values}
                for idiom in pattern.corpus.idioms
            }
            result[name] = {idiom: eras for idiom, eras in per_idiom.items() if eras}
        return result


def _validated(path: Path, model: type[Pattern] | type[ReferenceList]) -> Any:
    try:
        return model.model_validate(load_yaml(path))
    except ValidationError as exc:
        raise SpecError(path, "invalid:\n" + format_validation_error(exc)) from None


@cache
def _load(root: Path) -> PatternLibrary:
    problems: list[str] = []
    patterns: dict[str, Pattern] = {}
    for path in sorted((root / CATALOGUE_DIR).glob("*.yaml")):
        pattern = _validated(path, Pattern)
        if pattern.id != path.stem:
            problems.append(f"{path.name}: id '{pattern.id}' differs from the file name")
        patterns[pattern.id] = pattern
    references_path = root / REFERENCES_FILE
    references = {r.key: r for r in _validated(references_path, ReferenceList).references}
    surveys: dict[str, dict[str, Any]] = {}
    for path in sorted((root / SURVEY_DIR).glob("*.json")):
        try:
            surveys[path.stem] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"{SURVEY_DIR}/{path.name}: not JSON ({exc})")
    idioms = {idiom for survey in surveys.values() for values in survey.get(SHARE_KEY, {}).values() for idiom in values}
    actions = action_kinds()
    for pattern in patterns.values():
        where = f"pattern '{pattern.id}'"
        problems += [f"{where}: unknown component kind '{k}'" for k in pattern.components if k not in REGISTRY]
        problems += [f"{where}: unknown action kind '{k}'" for k in pattern.actions if k not in actions]
        problems += [f"{where}: unknown reference '{k}'" for k in pattern.research if k not in references]
        problems += [f"{where}: unknown related pattern '{k}'" for k in pattern.related if k not in patterns]
        if pattern.corpus is not None:
            problems += [
                f"{where}: idiom '{i}' is in no survey under {SURVEY_DIR}/"
                for i in pattern.corpus.idioms
                if i not in idioms
            ]
    if not patterns:
        problems.append(f"no patterns under {root / CATALOGUE_DIR}")
    if problems:
        raise SpecError(root, "pattern library is inconsistent:\n" + "\n".join(f"  - {p}" for p in problems))
    return PatternLibrary(root=root, patterns=patterns, references=references, surveys=surveys)


def load_library(root: Path | None = None) -> PatternLibrary:
    return _load((root or patterns_root()).resolve())


def realization_gap(pattern: Pattern, scene: Scene) -> str | None:
    """Why `scene` does not stage `pattern` with what the pattern is realized with, or None when it does."""
    used_actions = {action.kind for action in scene.actions}
    if any(obj.reveal_at_seconds is not None for obj in scene.objects):
        used_actions.add(REVEAL)
    if pattern.actions and not used_actions & set(pattern.actions):
        return f"uses none of its actions ({', '.join(pattern.actions)})"
    if pattern.components and not {obj.kind for obj in scene.objects} & set(pattern.components):
        return f"uses none of its components ({', '.join(pattern.components)})"
    return None


def scene_pattern_findings(storyboard: Storyboard, library: PatternLibrary) -> tuple[list[str], list[str]]:
    """Errors (unknown pattern ids) and warnings (a planned pattern, a pattern the scene does not realize)."""
    errors: list[str] = []
    warnings: list[str] = []
    for scene in storyboard.scenes:
        for pattern_id in scene.patterns:
            pattern = library.patterns.get(pattern_id)
            if pattern is None:
                errors.append(f"scene '{scene.id}': unknown pattern '{pattern_id}' (see `scianim patterns list`)")
            elif pattern.status == "planned":
                warnings.append(
                    f"scene '{scene.id}': pattern '{pattern_id}' is planned, so registered components cannot "
                    f"stage it yet (needs: {'; '.join(pattern.needs)})"
                )
            elif (gap := realization_gap(pattern, scene)) is not None:
                warnings.append(f"scene '{scene.id}' names pattern '{pattern_id}' but {gap}")
    return errors, warnings


@dataclass(frozen=True)
class RecipeScene:
    project_dir: Path
    scene: Scene | None
    mapping: dict[str, Any] | None
    """The scene's mapping as written in the example's storyboard.yaml."""
    problem: str | None


def recipe_scene(project: str, scene_id: str) -> RecipeScene:
    """The example scene a recipe points at, loaded and validated as a storyboard scene."""
    project_dir = workspace.examples_root() / "families" / project
    path = project_dir / "storyboard.yaml"
    if not path.exists():
        return RecipeScene(project_dir, None, None, f"no storyboard at {path}")
    data = load_yaml(path)
    mapping = next((s for s in data.get("scenes", []) if s.get("id") == scene_id), None)
    if mapping is None:
        return RecipeScene(project_dir, None, None, f"{path} has no scene '{scene_id}'")
    try:
        storyboard = Storyboard.model_validate(data)
    except ValidationError as exc:
        return RecipeScene(project_dir, None, mapping, f"{path} is invalid:\n{format_validation_error(exc)}")
    scene = next(s for s in storyboard.scenes if s.id == scene_id)
    return RecipeScene(project_dir, scene, mapping, None)


def yaml_text(data: Any) -> str:
    """Block YAML in the mapping's own key order, as a storyboard is written."""
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 110
    buffer = StringIO()
    yaml.dump(data, buffer)
    return buffer.getvalue()


def recipe_problems(library: PatternLibrary) -> list[str]:
    """Recipes that point nowhere, or at a scene that does not stage their pattern."""
    problems: list[str] = []
    for pattern in library.ordered():
        for recipe in pattern.recipes:
            found = recipe_scene(recipe.project, recipe.scene)
            where = f"pattern '{pattern.id}', recipe {recipe.project}#{recipe.scene}"
            if found.problem is not None:
                problems.append(f"{where}: {found.problem}")
            elif found.scene is not None and (gap := realization_gap(pattern, found.scene)) is not None:
                problems.append(f"{where}: the scene {gap}")
    return problems
