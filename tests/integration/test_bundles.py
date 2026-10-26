"""Milestone 6 acceptance: a bundle imported into a fresh workspace rebuilds its environment and reproduces a checkpoint."""

from __future__ import annotations

from pathlib import Path

import pytest

from scianim_core import ArtifactManifest

pytestmark = pytest.mark.integration


def _latest(project: Path) -> ArtifactManifest:
    paths = sorted((project / "renders" / "working").glob("*/manifest.json"))
    return ArtifactManifest.model_validate_json(paths[-1].read_text())


def test_bundle_round_trip_reproduces_a_checkpoint(workspace: Path, tmp_path: Path, scianim) -> None:
    project = workspace / "families" / "computational_neuroscience" / "prf_tuning"
    assert scianim("codegen", str(project)).returncode == 0
    assert scianim("snapshot", str(project), "--id", "gaussian_visible").returncode == 0
    original = {c.snapshot_id: c.sha256 for c in _latest(project).result.checkpoints}

    archive = tmp_path / "prf.scianim.zip"
    exported = scianim("bundle", "export", str(project), "-o", str(archive))
    assert exported.returncode == 0, exported.stdout + exported.stderr
    inspected = scianim("bundle", "inspect", str(archive))
    assert inspected.returncode == 0 and "checksums verified" in inspected.stdout

    fresh = tmp_path / "fresh"
    assert scianim("workspace", "init", str(fresh)).returncode == 0
    imported = scianim("bundle", "import", str(archive), "--into", str(fresh))
    assert imported.returncode == 0, imported.stdout + imported.stderr
    copy = fresh / "families" / "computational_neuroscience" / "prf_tuning"
    assert (copy / "storyboard.yaml").exists() and not (copy / "renders").exists()
    assert scianim("validate", str(copy)).returncode == 0

    # The explicit post-import step: rebuild the environment, then render the same checkpoint.
    sync = scianim("family", "env", "sync", str(fresh / "families" / "computational_neuroscience"))
    assert sync.returncode == 0, (sync.stdout + sync.stderr)[-1500:]
    assert scianim("codegen", str(copy)).returncode == 0
    render = scianim("snapshot", str(copy), "--id", "gaussian_visible")
    assert render.returncode == 0, render.stdout + render.stderr
    reproduced = {c.snapshot_id: c.sha256 for c in _latest(copy).result.checkpoints}
    assert reproduced["gaussian_visible"] == original["gaussian_visible"]
