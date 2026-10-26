"""Control-plane isolation, narration estimates and cache keys."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scianim.codegen.generate import write_scene_module
from scianim.config.loader import SpecError
from scianim.planning.checks import validate_project
from scianim.project import Project
from scianim.render.jobs import build_snapshot_job, cache_key, input_hashes, manim_settings, sources_from_report
from scianim_core import Narration
from scianim_core.jobs import ManimSettings

REPO = Path(__file__).resolve().parents[2]


def test_control_plane_never_imports_manim() -> None:
    code = (
        "import sys, scianim.cli, scianim.render.jobs, scianim.planning.checks, scianim.doctor, scianim.workspace;"
        "bad = [m for m in sys.modules if m == 'manim' or m.startswith('manim.') or m.startswith('scianim_bridge')];"
        "print(bad); sys.exit(1 if bad else 0)"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_control_plane_sources_do_not_import_manim() -> None:
    import ast

    for path in (REPO / "src" / "scianim").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                root = name.split(".")[0]
                assert root not in {"manim", "scianim_bridge"}, f"{path} imports {name}"


def test_narration_estimate_and_marks() -> None:
    narration = Narration(text='One two <mark name="here"/> three four five six.')
    assert narration.marks == ["here"]
    assert narration.plain_text == "One two three four five six."
    assert narration.word_count == 6
    assert narration.estimated_seconds(120) == pytest.approx(3.0)


def test_manim_settings_use_even_pixel_dimensions(project_copy: Project) -> None:
    report = validate_project(project_copy)
    assert report.animation and report.style
    settings = manim_settings(report.animation, report.style, "snapshot", ".scianim/media/working")
    assert settings.pixel_width == 960 and settings.pixel_height == 540
    assert settings.equation_engine == "typst"
    assert settings.background_color == report.style.tokens.palette["background"]


def test_snapshot_job_requires_generated_code(project_copy: Project) -> None:
    report = validate_project(project_copy, require_family=True)
    with pytest.raises(SpecError, match="codegen"):
        sources_from_report(project_copy, report)


def _sources(project_copy: Project):
    report = validate_project(project_copy, require_family=True)
    assert report.animation and report.storyboard and report.style and report.family
    write_scene_module(
        report.animation, report.storyboard, report.style, project_copy.scene_module_path(report.animation)
    )
    report = validate_project(project_copy, require_family=True)
    return report, sources_from_report(project_copy, report)


def test_cache_key_tracks_style_data_code_and_settings(project_copy: Project) -> None:
    report, sources = _sources(project_copy)
    settings = manim_settings(report.animation, report.style, "snapshot", ".scianim/media/working")
    base_inputs = input_hashes(project_copy, sources, None)
    base = cache_key(base_inputs, settings, [], "render_snapshots", {})
    other_style = sources.style.model_copy(update={"hash": "sha256:" + "0" * 64})
    other = input_hashes(project_copy, sources.__class__(**{**sources.__dict__, "style": other_style}), None)
    assert cache_key(other, settings, [], "render_snapshots", {}) != base
    csv = project_copy.root / "data" / "synthetic_responses.csv"
    csv.write_text(csv.read_text() + "11.0,1.0,1.0,5.5,low_pool,synthetic\n")
    assert cache_key(input_hashes(project_copy, sources, None), settings, [], "render_snapshots", {}) != base
    assert cache_key(base_inputs, settings, ["excitation_visible"], "render_snapshots", {}) != base
    bigger = ManimSettings(**{**settings.model_dump(), "pixel_width": 1920, "pixel_height": 1080})
    assert cache_key(base_inputs, bigger, [], "render_snapshots", {}) != base


def test_snapshot_job_payload_is_self_contained(project_copy: Project) -> None:
    report, sources = _sources(project_copy)
    job, paths, hashes = build_snapshot_job(project_copy, sources, report.family, ["pool_raised"])
    assert job.snapshot_ids == ["pool_raised"]
    assert set(job.snapshots) == {"pool_raised"}
    assert job.snapshots["pool_raised"].scene_id == "normalization"
    assert job.revision_id == "working"
    assert job.equations["schematic_equation"].typst == "r = E / (sigma + P)"
    assert job.data_files == {"responses": "data/synthetic_responses.csv"}
    assert job.scene_module == "code/scene_divisive_normalization.py"
    assert job.resolved_style.hash == report.style.hash
    assert job.cache_key.startswith("sha256:")
    assert paths.manifest_file.name == "manifest.json"
    assert paths.output_dir == project_copy.renders_dir / "working" / job.job_id
    assert hashes.data_files["responses"]
    assert job.family_id == "computational_neuroscience"
