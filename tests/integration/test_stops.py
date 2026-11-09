"""Stops in a real render (ADR-045): divisive_normalization with two stops that sit in rests renders a final movie
whose `result.stops` name the frames the scene reached, each the first frame of a play and a keyframe."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scianim_core import ArtifactManifest

pytestmark = [pytest.mark.integration, pytest.mark.video]

KEYFRAMES = """
import json, sys
import av
with av.open(sys.argv[1]) as container:
    stream = container.streams.video[0]
    print(json.dumps([i for i, frame in enumerate(container.decode(stream)) if frame.key_frame]))
"""


def _add_stop(storyboard: Path, snapshot_id: str, label: str) -> None:
    """Mark a snapshot as a stop: two lines after its description, which is the line after its time."""
    lines = storyboard.read_text(encoding="utf-8").splitlines(keepends=True)
    at = lines.index(f"      - id: {snapshot_id}\n")
    assert lines[at + 2].lstrip().startswith("description:")
    lines[at + 3 : at + 3] = ["        stop: true\n", f'        label: "{label}"\n']
    storyboard.write_text("".join(lines), encoding="utf-8")


def test_a_final_render_holds_its_stops_on_keyframes(workspace: Path, scianim) -> None:
    family = workspace / "families" / "computational_neuroscience"
    project = family / "divisive_normalization"
    storyboard = project / "storyboard.yaml"
    original = storyboard.read_text(encoding="utf-8")
    try:
        _add_stop(storyboard, "pool_introduced", "pool introduced")  # the equation is still being revealed at 7.85 s
        refused = scianim("validate", str(project))
        assert refused.returncode == 1 and "stop 'pool_introduced' at 8s has no rest before it" in refused.stdout
        storyboard.write_text(original, encoding="utf-8")
        _add_stop(storyboard, "excitation_visible", "drive alone")
        _add_stop(storyboard, "pool_raised", "pool raised to 4")
        assert scianim("validate", str(project)).returncode == 0
        assert scianim("codegen", str(project)).returncode == 0

        run = scianim("render", str(project), "--profile", "final", "--json")
        assert run.returncode == 0, run.stderr
        manifest = ArtifactManifest.model_validate(json.loads(run.stdout))
        assert manifest.result.status == "succeeded" and manifest.job.quality_profile == "final"
        fps = manifest.job.manim.frame_rate
        stops = manifest.result.stops
        assert [(s.snapshot_id, s.label) for s in stops] == [
            ("excitation_visible", "drive alone"),
            ("pool_raised", "pool raised to 4"),
        ]
        for stop, at in zip(stops, (4.0, 13.0), strict=True):
            assert stop.frame_index == round(at * fps) and stop.time_seconds == pytest.approx(at)
            assert stop.rest_before_frames >= round(0.3 * fps)
            assert any(round(p.start_seconds * fps) == stop.frame_index for p in manifest.result.plays)
            sampled = next(c for c in manifest.result.checkpoints if c.snapshot_id == stop.snapshot_id)
            assert sampled.frame_index == stop.frame_index
        movie = project / manifest.result.videos[0].path
        decoded = subprocess.run(
            [str(family / ".venv" / "bin" / "python"), "-c", KEYFRAMES, str(movie)],
            capture_output=True,
            text=True,
            check=True,
        )
        keyframes = set(json.loads(decoded.stdout))
        assert {s.frame_index for s in stops} <= keyframes, sorted(keyframes)

        # The same request answers from the cache, stops included.
        again = ArtifactManifest.model_validate(
            json.loads(scianim("render", str(project), "--profile", "final", "--json").stdout)
        )
        assert again.cache_hit and again.result.stops == stops
        timing = scianim("timing", str(project))
        assert "2 stop(s) present the clip in 3 parts" in " ".join(timing.stdout.split())
    finally:
        storyboard.write_text(original, encoding="utf-8")
