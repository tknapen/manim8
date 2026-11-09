"""ADR-044: the font families the family environment finds are part of every cache that holds pixels."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scianim.families.resolve import PROBE_SCRIPT
from scianim.planning.checks import validate_project
from scianim.project import Project
from scianim.render.jobs import build_video_job, cache_key, media_directory, sources_from_report

TOOLS = {"manim": "0.22.0", "python": "3.12", "bridge_fingerprint": "f" * 64}


def _probe(tmp_path: Path, families: list[str]) -> dict[str, object]:
    """The probe script against a stand-in manimpango that lists these families (run without -I, so that the
    stand-in in the working directory is the one imported)."""
    (tmp_path / "manimpango.py").write_text(f"__version__ = '0'\ndef list_fonts():\n    return {families!r}\n")
    proc = subprocess.run(
        [sys.executable, "-c", PROBE_SCRIPT], cwd=tmp_path, capture_output=True, text=True, check=True
    )
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_the_probe_names_the_fonts_pango_finds(tmp_path: Path) -> None:
    sans = _probe(tmp_path, ["DejaVu Sans", "DejaVu Serif"])
    same = _probe(tmp_path, ["DejaVu Serif", "DejaVu Sans", "DejaVu Sans"])  # order and repeats do not count
    more = _probe(tmp_path, ["DejaVu Sans", "DejaVu Serif", "TeX Gyre Heros"])
    assert isinstance(sans["fonts_fingerprint"], str) and len(sans["fonts_fingerprint"]) == 64
    assert sans["fonts_fingerprint"] == same["fonts_fingerprint"] != more["fonts_fingerprint"]


def test_caches_follow_the_fonts(project_copy: Project) -> None:
    from scianim.codegen.generate import write_scene_module

    report = validate_project(project_copy, require_family=True)
    assert report.animation and report.storyboard and report.style and report.family
    write_scene_module(
        report.animation, report.storyboard, report.style, project_copy.scene_module_path(report.animation)
    )
    report = validate_project(project_copy, require_family=True)
    assert report.family
    sources = sources_from_report(project_copy, report)
    plain, _, hashes = build_video_job(project_copy, sources, report.family, "storyboard", tool_versions=TOOLS)
    with_fonts = {**TOOLS, "fonts_fingerprint": "a" * 64}
    other_fonts = {**TOOLS, "fonts_fingerprint": "b" * 64}
    a, _, _ = build_video_job(project_copy, sources, report.family, "storyboard", tool_versions=with_fonts)
    b, _, _ = build_video_job(project_copy, sources, report.family, "storyboard", tool_versions=other_fonts)
    again, _, _ = build_video_job(project_copy, sources, report.family, "storyboard", tool_versions=dict(with_fonts))
    # a job rendered where Pango finds other faces is another job: its own cache entry, store and Manim media
    assert len({plain.cache_key, a.cache_key, b.cache_key}) == 3 and again.cache_key == a.cache_key
    assert len({plain.segment_store, a.segment_store, b.segment_store}) == 3 and again.segment_store == a.segment_store
    assert len({plain.manim.media_dir, a.manim.media_dir, b.manim.media_dir}) == 3
    # a probe that could not tell (no manimpango) keeps the keys of before
    unknown = {**TOOLS, "fonts_fingerprint": None}
    assert cache_key(hashes, plain.manim, [], "render_video:storyboard", unknown) == cache_key(
        hashes, plain.manim, [], "render_video:storyboard", TOOLS
    )
    assert media_directory(project_copy, "working", unknown) == media_directory(project_copy, "working", TOOLS)
