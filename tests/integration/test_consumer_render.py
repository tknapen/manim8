"""What another tool reads from a real render (ADR-043): `--json` on stdout for a fresh and a cached job, and a job
rendered under another published style."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scianim_core import ArtifactManifest

pytestmark = [pytest.mark.integration, pytest.mark.video]


def _manifest(stdout: str) -> ArtifactManifest:
    return ArtifactManifest.model_validate(json.loads(stdout))


def test_render_and_snapshot_json_with_and_without_a_style(workspace: Path, scianim) -> None:
    project = workspace / "families" / "computational_neuroscience" / "divisive_normalization"
    assert scianim("codegen", str(project)).returncode == 0

    first = scianim("render", str(project), "--profile", "storyboard", "--json")
    assert first.returncode == 0, first.stderr
    fresh = _manifest(first.stdout)
    assert not fresh.cache_hit and fresh.result.status == "succeeded" and "rendering" in first.stderr
    [movie] = fresh.result.videos
    assert movie.duration_seconds == pytest.approx(18.0) and (movie.width_px, movie.height_px) == (480, 270)
    assert hashlib.sha256((project / movie.path).read_bytes()).hexdigest() == movie.sha256
    assert {c.snapshot_id for c in fresh.result.checkpoints} >= {"excitation_visible", "rebalanced"}
    assert all((project / c.png).exists() for c in fresh.result.checkpoints)

    second = scianim("render", str(project), "--profile", "storyboard", "--json")
    assert second.returncode == 0, second.stderr
    cached = _manifest(second.stdout)
    assert cached.cache_hit and cached.job.job_id == fresh.job.job_id and cached.result.videos == [movie]

    # A published style that changes the page, as a deck's dark preset would (the project selects tomas_scientific,
    # which differs from default@0.5.0 only in a validation rule, so that pair draws the same movie).
    sheet = workspace / "styles" / "paper_dark" / "0.1.0" / "style.yaml"
    sheet.parent.mkdir(parents=True, exist_ok=True)
    sheet.write_text(
        'schema_version: "1.0"\nname: paper_dark\nversion: 0.1.0\ninherits: default@0.5.0\ndescription: test\n'
        "palette: {background: '#101820', foreground: '#F2F4F7'}\n"
    )
    styled_run = scianim("render", str(project), "--profile", "storyboard", "--style", "paper_dark@0.1.0", "--json")
    assert styled_run.returncode == 0, styled_run.stderr
    styled = _manifest(styled_run.stdout)
    assert (styled.job.resolved_style.theme, styled.job.resolved_style.theme_version) == ("paper_dark", "0.1.0")
    assert styled.job.manim.background_color == "#101820"
    assert styled.job.cache_key != fresh.job.cache_key and styled.result.status == "succeeded"
    assert styled.result.videos[0].sha256 != movie.sha256  # another page, another movie
    assert "paper_dark" not in (project / "animation.yaml").read_text()

    snap = scianim("snapshot", str(project), "--id", "rebalanced", "--style", "paper_dark@0.1.0", "--json")
    assert snap.returncode == 0, snap.stderr
    snapshot = _manifest(snap.stdout)
    assert snapshot.job.operation == "render_snapshots" and snapshot.job.resolved_style.theme == "paper_dark"
    assert [c.snapshot_id for c in snapshot.result.checkpoints] == ["rebalanced"]

    failed = scianim("render", str(project), "--json", "--style", "missing@1.0.0")
    assert failed.returncode == 1 and failed.stdout == ""
