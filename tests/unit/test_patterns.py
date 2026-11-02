"""The pattern library (ADR-040): its entries, its recipes, the checks on scenes that name patterns, the
context bundle's Patterns section, the commands, and the survey script whose counts the entries cite."""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from scianim.agent.context import export_context
from scianim.cli import app
from scianim.config.loader import SpecError
from scianim.patterns import load_library, patterns_root, recipe_problems, scene_pattern_findings
from scianim.planning.checks import validate_project
from scianim.planning.dependencies import scene_fingerprints
from scianim.project import Project
from scianim_core import Storyboard
from scianim_core.patterns import CorpusEvidence, Pattern

REPO = Path(__file__).resolve().parents[2]


def _minimal(**changes) -> dict:
    entry = {
        "id": "demo",
        "name": "Demo",
        "group": "change",
        "summary": "A demo.",
        "use_when": ["Always."],
        "beats": ["One."],
        "status": "available",
        "actions": ["vary_parameter"],
    }
    entry.update(changes)
    return entry


def test_the_library_loads_and_every_recipe_stages_its_pattern() -> None:
    library = load_library()
    statuses = {p.status for p in library.patterns.values()}
    assert statuses == {"available", "partial", "planned"}
    assert recipe_problems(library) == []
    assert all(p.recipes for p in library.patterns.values() if p.status == "available")
    survey = library.surveys["3b1b_videos"]
    assert len(survey["commit"]) == 40 and set(survey["eras"]) == {"2015-2019", "2020-2022", "2023-2026"}
    shares = library.idiom_shares(library.patterns["sweep_with_readout"])["3b1b_videos"]
    assert shares["parameter sweep"]["2023-2026"] > shares["parameter sweep"]["2015-2019"]


def test_entries_keep_status_and_evidence_consistent() -> None:
    assert Pattern.model_validate(_minimal()).status == "available"
    with pytest.raises(ValidationError, match="lists needs"):
        Pattern.model_validate(_minimal(needs=["a thing"]))
    with pytest.raises(ValidationError, match="names nothing it needs"):
        Pattern.model_validate(_minimal(status="partial"))
    with pytest.raises(ValidationError, match="no example can show it"):
        Pattern.model_validate(
            _minimal(status="planned", needs=["a thing"], recipes=[{"project": "a/b", "scene": "c"}])
        )
    with pytest.raises(ValidationError, match="neither"):
        CorpusEvidence.model_validate({"note": "seen somewhere"})
    with pytest.raises(ValidationError, match="extra"):
        Pattern.model_validate(_minimal(colour="red"))


def test_the_library_refuses_entries_that_point_nowhere(tmp_path: Path) -> None:
    root = tmp_path / "patterns"
    shutil.copytree(patterns_root(), root)
    entry = (root / "catalogue" / "sweep_with_readout.yaml").read_text()
    broken = entry.replace("components: [function_plot,", "components: [hologram, function_plot,").replace(
        "research: [ploetzner2020,", "research: [nobody2031, ploetzner2020,"
    )
    (root / "catalogue" / "sweep_with_readout.yaml").write_text(broken)
    (root / "catalogue" / "renamed.yaml").write_text(entry.replace("id: sweep_with_readout", "id: other_id"))
    with pytest.raises(SpecError) as caught:
        load_library(root)
    message = str(caught.value)
    assert "unknown component kind 'hologram'" in message and "unknown reference 'nobody2031'" in message
    assert "renamed.yaml: id 'other_id' differs from the file name" in message


def _with_patterns(storyboard: Storyboard, scene_id: str, patterns: list[str]) -> Storyboard:
    data = storyboard.model_dump(mode="json")
    next(s for s in data["scenes"] if s["id"] == scene_id)["patterns"] = patterns
    return Storyboard.model_validate(data)


def test_scenes_that_name_patterns_are_checked(project_copy: Project) -> None:
    storyboard = project_copy.load_storyboard()
    named = _with_patterns(storyboard, "normalization", ["sweep_with_readout"])
    report = validate_project(project_copy, storyboard=named)
    assert report.ok and not any("pattern" in w for w in report.warnings), report.warnings
    library = load_library()
    errors, warnings = scene_pattern_findings(
        _with_patterns(storyboard, "normalization", ["no_such_pattern", "derive_by_copy", "orbit_to_reveal_depth"]),
        library,
    )
    assert errors == ["scene 'normalization': unknown pattern 'no_such_pattern' (see `scianim patterns list`)"]
    assert any("'derive_by_copy' is planned" in w for w in warnings)
    assert any("'orbit_to_reveal_depth' but uses none of its actions (orbit_camera)" in w for w in warnings)
    unknown = validate_project(project_copy, storyboard=_with_patterns(storyboard, "normalization", ["nope"]))
    assert not unknown.ok and any("unknown pattern 'nope'" in e for e in unknown.errors)
    with pytest.raises(ValidationError, match="duplicate pattern"):
        _with_patterns(storyboard, "normalization", ["linked_views", "linked_views"])


def test_naming_patterns_changes_no_scene_fingerprint(project_copy: Project) -> None:
    report = validate_project(project_copy)
    named = _with_patterns(report.storyboard, "normalization", ["sweep_with_readout", "staged_terms"])
    hashes = {"style_hash": report.style.hash, "data_hashes": {"responses": "a" * 64}, "custom_hashes": {}}
    assert scene_fingerprints(report.animation, named, **hashes) == scene_fingerprints(
        report.animation, report.storyboard, **hashes
    )


def test_the_context_bundle_offers_the_patterns(project_copy: Project) -> None:
    report = validate_project(project_copy)
    out = export_context(project_copy, report)
    text = (out / "CONTEXT.md").read_text()
    assert "## Patterns" in text and "### `sweep_with_readout`: Parameter sweep with a readout" in text
    assert "Planned, not stageable with registered components yet:" in text and "`derive_by_copy`" in text
    assert "name it in the scene's `patterns` list" in text
    document = json.loads((out / "patterns.json").read_text())
    scene = document["recipe_scenes"]["computational_neuroscience/divisive_normalization#normalization"]
    assert scene["id"] == "normalization" and any(a["id"] == "raise_pool" for a in scene["actions"])
    assert {r["key"] for r in document["references"]} >= {"ploetzner2020", "chevalier2014"}


def test_the_commands_list_show_and_check() -> None:
    runner = CliRunner()
    listing = runner.invoke(app, ["patterns", "list", "--json"])
    assert listing.exit_code == 0, listing.output
    assert "sweep_with_readout" in {entry["id"] for entry in json.loads(listing.output)}
    planned = runner.invoke(app, ["patterns", "list", "--status", "planned", "--json"])
    assert {entry["status"] for entry in json.loads(planned.output)} == {"planned"}
    shown = runner.invoke(app, ["patterns", "show", "sweep_with_readout"])
    assert shown.exit_code == 0 and "raise_pool" in shown.output and "Ploetzner" in shown.output
    assert "[abstract]" in shown.output  # entry text is printed as text, not read as console markup
    assert runner.invoke(app, ["patterns", "show", "hologram"]).exit_code == 1
    checked = runner.invoke(app, ["patterns", "check"])
    assert checked.exit_code == 0 and "ok" in checked.output


def _survey_module():
    spec = importlib.util.spec_from_file_location("survey_corpus", REPO / "tools" / "survey_corpus.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_survey_counts_idioms_in_a_corpus(tmp_path: Path) -> None:
    scenes = tmp_path / "_2024" / "demo"
    scenes.mkdir(parents=True)
    (scenes / "main.py").write_text(
        """
class Sweep(InteractiveScene):
    def construct(self):
        tracker = ValueTracker(0)
        label = always_redraw(lambda: DecimalNumber(tracker.get_value()))
        self.play(FadeIn(label), LaggedStartMap(FadeIn, dots, lag_ratio=0.2))
        self.play(tracker.animate.set_value(3), run_time=4)
        self.wait(2)
        self.play(TransformFromCopy(term, slot))
        self.play(self.frame.animate.reorient(20, 70), run_time=8)
        self.play(self.frame.animate.reorient(0, 0, 0, ORIGIN, 4))


class NoPlays(InteractiveScene):
    pass
"""
    )
    result = _survey_module().survey(tmp_path)
    recent = result["eras"]["2023-2026"]
    assert recent == {"files": 1, "unparsed": 0, "scenes": 1, "plays": 5}
    tokens = result["top tokens per 1000 plays"]["2023-2026"]
    assert {"FadeIn", "LaggedStartMap", "tracker.set_value", "TransformFromCopy", "camera.reorient"} <= set(tokens)
    assert "camera.reorient (flat)" in tokens
    shares = result["scenes with idiom (%)"]["2023-2026"]
    for idiom in ("parameter sweep", "staggered", "derive by copy", "camera 3d", "camera 2d"):
        assert shares[idiom] == 100.0, idiom
    assert result["lag ratios (all eras)"]["median"] == 0.2
