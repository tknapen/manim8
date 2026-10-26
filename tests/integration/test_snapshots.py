"""Named checkpoints rendered by Manim inside the family environment (Milestone 2 acceptance)."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scianim_core import ArtifactManifest

REPO = Path(__file__).resolve().parents[2]
EXAMPLE = REPO / "examples" / "divisive_normalization"

pytestmark = pytest.mark.integration


def scianim(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    import os

    merged = {**os.environ, **(env or {})}
    return subprocess.run(
        [sys.executable, "-m", "scianim.cli", *args],
        capture_output=True,
        text=True,
        env=merged,
        check=False,
    )


def latest_manifest(project: Path) -> ArtifactManifest:
    candidates = sorted((project / "renders" / "working").glob("*/manifest.json"))
    assert candidates, "no manifest written"
    return ArtifactManifest.model_validate_json(candidates[-1].read_text())


@pytest.fixture
def project(tmp_path: Path, ready_family: Path) -> Path:
    target = tmp_path / "divisive_normalization"
    shutil.copytree(EXAMPLE, target, ignore=shutil.ignore_patterns(".scianim", "renders", "code", "__pycache__"))
    return target


def test_two_named_checkpoints_and_manifest(project: Path, tmp_path: Path) -> None:
    styles = tmp_path / "styles"
    shutil.copytree(REPO / "styles", styles)
    env = {"SCIANIM_STYLES": str(styles), "SCIANIM_FAMILIES": str(REPO / "examples" / "families")}
    assert scianim("codegen", str(project), env=env).returncode == 0
    run = scianim(
        "snapshot",
        str(project),
        "--no-cache",
        "--id",
        "excitation_visible",
        "--id",
        "equation_complete",
        env=env,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    manifest = latest_manifest(project)
    assert manifest.result.status == "succeeded"
    assert [c.snapshot_id for c in manifest.result.checkpoints] == [
        "excitation_visible",
        "equation_complete",
    ]
    for record in manifest.result.checkpoints:
        png = project / record.png
        assert png.exists() and png.stat().st_size > 1000
        assert record.kind == "manim_checkpoint"
        assert record.width_px == 960 and record.height_px == 540
        assert record.layout, "layout report is empty"
    first = manifest.result.checkpoints[0]
    assert {item.object_id for item in first.layout} == {"scene_title", "drive_curve"}
    assert manifest.result.tool_versions and manifest.result.tool_versions.manim
    assert (project / manifest.job.output_dir / "review_sheet.html").exists()

    # Same inputs again: cache hit, no new job directory.
    before = len(list((project / "renders" / "working").iterdir()))
    again = scianim("snapshot", str(project), "--id", "excitation_visible", "--id", "equation_complete", env=env)
    assert again.returncode == 0 and "cache hit" in again.stdout
    assert len(list((project / "renders" / "working").iterdir())) == before

    # A changed palette token: new cache key, different pixels for the curve, same for the equation-only frame? The
    # equation frame also contains nothing in primary_signal, but the background is untouched either way; we only
    # assert the curve frame differs and the key changes.
    sheet = styles / "tomas_scientific" / "style.yaml"
    sheet.write_text(sheet.read_text().replace('primary_signal: "#56B4E9"', 'primary_signal: "#FF3B30"'))
    changed = scianim("snapshot", str(project), "--id", "excitation_visible", "--id", "equation_complete", env=env)
    assert changed.returncode == 0, changed.stdout + changed.stderr
    assert "cache hit" not in changed.stdout
    second = latest_manifest(project)
    assert second.job.cache_key != manifest.job.cache_key
    assert second.inputs.resolved_style != manifest.inputs.resolved_style
    by_id_before = {c.snapshot_id: c for c in manifest.result.checkpoints}
    by_id_after = {c.snapshot_id: c for c in second.result.checkpoints}
    assert by_id_after["excitation_visible"].sha256 != by_id_before["excitation_visible"].sha256
    assert json.loads((project / second.job.output_dir / "result.json").read_text())["status"] == "succeeded"
