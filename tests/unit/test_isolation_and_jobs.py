"""Control-plane isolation, narration estimates and cache keys."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scianim.families.resolve import find_family
from scianim.planning.checks import validate_project
from scianim.project import Project
from scianim.render.jobs import build_snapshot_job, cache_key, input_hashes, manim_settings
from scianim_core import Narration
from scianim_core.jobs import ManimSettings

REPO = Path(__file__).resolve().parents[2]


def test_control_plane_never_imports_manim() -> None:
    code = (
        "import sys, scianim.cli, scianim.render.jobs, scianim.planning.checks, scianim.doctor;"
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


def test_cache_key_tracks_style_data_and_code(project_copy: Project) -> None:
    report = validate_project(project_copy)
    assert report.animation and report.storyboard and report.style
    from scianim.codegen.generate import write_scene_module

    module = write_scene_module(
        report.animation,
        report.storyboard,
        report.style,
        project_copy.scene_module_path(report.animation),
    )
    settings = manim_settings(report.animation, report.style, "snapshot", ".scianim/media/working")
    base_inputs = input_hashes(project_copy, report.animation, report.style, module, None)
    base = cache_key(base_inputs, settings, [], "render_snapshots", {})
    other_style = report.style.model_copy(update={"hash": "sha256:" + "0" * 64})
    assert (
        cache_key(
            input_hashes(project_copy, report.animation, other_style, module, None),
            settings,
            [],
            "render_snapshots",
            {},
        )
        != base
    )
    csv = project_copy.root / "data" / "synthetic_responses.csv"
    csv.write_text(csv.read_text() + "11.0,1.0,1.0,5.5,low_pool,synthetic\n")
    assert (
        cache_key(
            input_hashes(project_copy, report.animation, report.style, module, None),
            settings,
            [],
            "render_snapshots",
            {},
        )
        != base
    )
    assert cache_key(base_inputs, settings, ["excitation_visible"], "render_snapshots", {}) != base
    assert (
        cache_key(
            base_inputs,
            ManimSettings(**{**settings.model_dump(), "pixel_width": 1920, "pixel_height": 1080}),
            [],
            "render_snapshots",
            {},
        )
        != base
    )


def test_snapshot_job_requires_generated_code(project_copy: Project) -> None:
    report = validate_project(project_copy, require_family=True)
    assert report.animation and report.storyboard and report.style and report.family
    from scianim.config.loader import SpecError

    with pytest.raises(SpecError, match="codegen"):
        build_snapshot_job(project_copy, report.animation, report.storyboard, report.style, report.family, [])


def test_snapshot_job_payload_is_self_contained(project_copy: Project) -> None:
    report = validate_project(project_copy, require_family=True)
    assert report.animation and report.storyboard and report.style and report.family
    from scianim.codegen.generate import write_scene_module

    write_scene_module(
        report.animation,
        report.storyboard,
        report.style,
        project_copy.scene_module_path(report.animation),
    )
    job, paths, hashes = build_snapshot_job(
        project_copy,
        report.animation,
        report.storyboard,
        report.style,
        report.family,
        ["equation_complete"],
    )
    assert job.snapshot_ids == ["equation_complete"]
    assert set(job.snapshots) == {"equation_complete"}
    assert job.snapshots["equation_complete"].scene_id == "equation"
    assert job.equations["schematic_equation"].typst == "r = E / (sigma + P)"
    assert job.data_files == {"responses": "data/synthetic_responses.csv"}
    assert job.resolved_style.hash == report.style.hash
    assert job.cache_key.startswith("sha256:")
    assert paths.manifest_file.name == "manifest.json"
    assert hashes.data_files["responses"]
    assert (
        find_family(project_copy.root, report.animation.family, project_copy.family_search_roots()).manifest.id
        == job.family_id
    )
