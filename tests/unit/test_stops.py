"""Stops (ADR-045): checkpoints where a player may hold one clip. The storyboard fields and their validation, the
fingerprints they leave alone, the job targets, `result.stops` derived from a recorded manifest, the render policy,
`scianim timing` and the review sheet. Nothing here renders; the real render is in the integration tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from scianim import cli
from scianim.codegen.generate import generate_scene_module
from scianim.planning.checks import Report, validate_project
from scianim.planning.dependencies import changed_scenes, scene_fingerprints
from scianim.project import Project
from scianim.render.jobs import snapshot_targets
from scianim.render.stops import apply_stops, derive_stops, parts, rest_frames_needed
from scianim.review.sheet import render_sheet
from scianim.workspace import EXAMPLE_FAMILY
from scianim_core import ArtifactManifest, PlayRecord, Snapshot, Storyboard

RECORDED = Path(__file__).resolve().parents[1] / "fixtures" / "stops" / "manifest.json"


def _board(project: Project) -> dict[str, Any]:
    report = validate_project(project)
    assert report.storyboard is not None
    return report.storyboard.model_dump(mode="json")


def _snapshot(data: dict[str, Any], snapshot_id: str) -> dict[str, Any]:
    return next(s for scene in data["scenes"] for s in scene["snapshots"] if s["id"] == snapshot_id)


def _scene(data: dict[str, Any], scene_id: str) -> dict[str, Any]:
    return next(scene for scene in data["scenes"] if scene["id"] == scene_id)


def _check(project: Project, data: dict[str, Any]) -> Report:
    return validate_project(project, storyboard=Storyboard.model_validate(data))


def _stop_errors(report: Report) -> list[str]:
    return [e for e in report.errors if "stop" in e]


def _stop(data: dict[str, Any], scene_id: str, snapshot_id: str, at: float, **fields: Any) -> None:
    _scene(data, scene_id)["snapshots"].append(
        {"id": snapshot_id, "at_seconds": at, "description": f"held at {at}", "stop": True, **fields}
    )


@pytest.fixture
def prf(workspace: Path) -> Project:
    """The prf_tuning example: one scene, an orbit from 0 to 16 s across everything."""
    return Project(workspace / "families" / EXAMPLE_FAMILY / "prf_tuning")


# --- the fields -------------------------------------------------------------------------------------------------


def test_stop_fields_default_off_and_belong_to_a_stop() -> None:
    plain = Snapshot(id="pool_raised", at_seconds=13, description="x")
    assert (plain.stop, plain.label, plain.stop_through) == (False, None, [])
    assert Snapshot(id="pool_raised", at_seconds=13, description="x", stop=True).stop_label == "pool raised"
    assert Snapshot(id="a", at_seconds=1, description="x", stop=True, label=" c = d'/2 ").stop_label == "c = d'/2"
    for fields in ({"label": "late"}, {"stop_through": ["orbit"]}):
        with pytest.raises(ValidationError, match="describe a stop"):
            Snapshot(id="a", at_seconds=1, description="x", **fields)
    for label in ("", "x" * 41, "two\nlines", "<b>bold</b>"):
        with pytest.raises(ValidationError):
            Snapshot(id="a", at_seconds=1, description="x", stop=True, label=label)
    with pytest.raises(ValidationError, match="give it a label"):
        Snapshot(id="a" * 41, at_seconds=1, description="x", stop=True)
    with pytest.raises(ValidationError, match="duplicate"):
        Snapshot(id="a", at_seconds=1, description="x", stop=True, stop_through=["o", "o"])
    with pytest.raises(ValidationError):
        Snapshot(id="a", at_seconds=1, description="x", stop=True, stop_through=["Not-a-slug"])


def test_the_two_example_stops_in_rests_validate(project_copy: Project) -> None:
    data = _board(project_copy)
    for snapshot_id in ("excitation_visible", "pool_raised"):
        _snapshot(data, snapshot_id)["stop"] = True
    report = _check(project_copy, data)
    assert _stop_errors(report) == [] and not [w for w in report.warnings if "stop" in w]
    assert [snap.id for _, snap in report.storyboard.stops()] == ["excitation_visible", "pool_raised"]


# --- the rest before a stop -------------------------------------------------------------------------------------


def test_a_reveal_or_an_action_in_the_rest_before_a_stop_is_refused(project_copy: Project) -> None:
    data = _board(project_copy)
    _snapshot(data, "pool_introduced")["stop"] = True  # the equation is revealed 7-7.85 s, the stop is at 8 s
    errors = _stop_errors(_check(project_copy, data))
    assert len(errors) == 1 and "the reveal of 'normalization_equation' runs 7-7.85s" in errors[0]
    assert "move the stop to 8.15s or later" in errors[0]

    data = _board(project_copy)
    _stop(data, "normalization", "too_soon", 12.7)  # raise_pool moves until 12.5 s
    errors = _stop_errors(_check(project_copy, data))
    assert len(errors) == 1 and "the motion of 'raise_pool' runs 8.5-12.5s" in errors[0]
    _scene(data, "normalization")["snapshots"][-1]["at_seconds"] = 12.8  # exactly 0.3 s of rest
    assert _stop_errors(_check(project_copy, data)) == []


def test_an_action_may_start_at_the_stop_but_its_lead_in_counts(project_copy: Project) -> None:
    data = _board(project_copy)
    _snapshot(data, "excitation_visible")["stop"] = True  # `gain` starts at 4 s, the stop's time
    assert _stop_errors(_check(project_copy, data)) == []
    gain = _scene(data, "excitation")["actions"][0]
    gain.update({"at_seconds": 3.8, "lead_in_seconds": 0.2})  # the value still moves from 4 s, the pulse from 3.8 s
    errors = _stop_errors(_check(project_copy, data))
    assert len(errors) == 1 and "the lead-in and motion of 'gain' runs 3.8-5.3s" in errors[0]


def test_a_stop_in_a_closing_fade_is_refused_with_a_clear_message(project_copy: Project) -> None:
    data = _board(project_copy)
    _stop(data, "excitation", "fading", 5.8)  # the scene fades from 5.35 s (transition 0.65 s)
    errors = _stop_errors(_check(project_copy, data))
    assert any("the closing fade of scene 'excitation' runs 5.35-6s" in e for e in errors)
    assert any("end the motion earlier, or put the stop where the scene rests" in e for e in errors)


# --- placement --------------------------------------------------------------------------------------------------


def test_a_stop_at_a_scene_start_or_on_the_last_frame_is_refused(project_copy: Project) -> None:
    for scene_id, at in (("excitation", 0), ("normalization", 6)):
        data = _board(project_copy)
        _stop(data, scene_id, "at_start", at)
        assert any(f"first frame of scene '{scene_id}'" in e for e in _stop_errors(_check(project_copy, data)))
    for at in (17.98, 18):  # 18 s at 30 fps is 540 frames: the last one is frame 539, at 17.967 s
        data = _board(project_copy)
        _stop(data, "normalization", "at_end", at)
        errors = _stop_errors(_check(project_copy, data))
        assert len(errors) == 1 and "last frame (frame 539 at 30 fps)" in errors[0]


def test_stops_are_half_a_second_apart_and_on_frames_of_their_own(project_copy: Project) -> None:
    data = _board(project_copy)
    _snapshot(data, "pool_raised")["stop"] = True
    _stop(data, "normalization", "soon_after", 13.4)
    errors = _stop_errors(_check(project_copy, data))
    assert errors == [
        "stops 'pool_raised' (13s) and 'soon_after' (13.4s) are 0.40s apart; a part needs at least 0.5s, "
        "so keep one or move them apart"
    ]
    _scene(data, "normalization")["snapshots"][-1]["at_seconds"] = 13.01  # frame 390, like 13 s
    assert "stops 'pool_raised' and 'soon_after' fall on one frame; keep one" in _check(project_copy, data).errors
    _scene(data, "normalization")["snapshots"][-1]["at_seconds"] = 13.5  # where stabilize starts: allowed
    assert _stop_errors(_check(project_copy, data)) == []


# --- orbits -----------------------------------------------------------------------------------------------------


def test_an_orbit_across_a_stop_is_refused_unless_the_stop_names_it(prf: Project) -> None:
    data = _board(prf)
    _snapshot(data, "moved")["stop"] = True  # the orbit runs 0-16 s; the sweeps end at 7 s
    errors = _stop_errors(_check(prf, data))
    assert len(errors) == 1 and "orbit 'orbit' (0-16s) turns the camera across the stop" in errors[0]
    assert "stop_through" in errors[0]

    _snapshot(data, "moved")["stop_through"] = ["orbit"]
    report = _check(prf, data)
    assert _stop_errors(report) == []
    frozen = [w for w in report.warnings if w.startswith("stop_freezes_camera:")]
    assert len(frozen) == 1 and "stop 'moved' at 7.5s: orbit 'orbit' (0-16s) keeps turning" in frozen[0]
    targets = snapshot_targets(report.storyboard)
    assert (targets["moved"].stop, targets["moved"].label, targets["moved"].frozen) == (True, "moved", ["orbit"])
    assert targets["grown"].stop is False and targets["grown"].frozen == []

    _snapshot(data, "moved")["stop_through"] = ["move_x"]  # not an orbit
    assert any("not orbit_camera actions" in e for e in _check(prf, data).errors)


def test_an_orbit_that_ends_in_the_rest_counts_and_an_idle_waiver_is_reported(prf: Project) -> None:
    data = _board(prf)
    orbit = _scene(data, "prf")["actions"][0]
    orbit["duration_seconds"] = 7.3  # ends 0.2 s before the stop at 7.5 s
    _snapshot(data, "moved")["stop"] = True
    errors = _stop_errors(_check(prf, data))
    assert len(errors) == 1 and "orbit 'orbit' (0-7.3s) runs 0-7.3s" in errors[0]
    orbit["duration_seconds"] = 7.2  # ends exactly 0.3 s before
    assert _stop_errors(_check(prf, data)) == []
    _snapshot(data, "moved")["stop_through"] = ["orbit"]
    report = _check(prf, data)
    assert _stop_errors(report) == []
    assert "stop 'moved' at 7.5s: stop_through names ['orbit'], which do not turn at the stop; remove them" in (
        report.warnings
    )


# --- approximate checkpoints ------------------------------------------------------------------------------------


BUILDER = """from manim import Dot


def build(scene, object_id, tokens, arguments, **kwargs):
    dot = Dot()
    {updater}
    return dot
"""


@pytest.mark.parametrize(
    ("updater", "refused"),
    [
        ("dot.add_updater(lambda m, dt: m.shift(dt * [1, 0, 0]))", True),
        ("dot.add_updater(lambda m: m)", False),
    ],
)
def test_a_stop_where_the_checkpoint_would_be_approximate_is_refused(
    project_copy: Project, updater: str, refused: bool
) -> None:
    project_copy.code_dir.mkdir(parents=True, exist_ok=True)
    (project_copy.code_dir / "ticker.py").write_text(BUILDER.format(updater=updater), encoding="utf-8")
    data = _board(project_copy)
    _scene(data, "excitation")["objects"].append(
        {"id": "ticker", "kind": "custom", "params": {"builder": "ticker:build", "arguments": {}}}
    )
    _snapshot(data, "excitation_visible")["stop"] = True
    errors = _stop_errors(_check(project_copy, data))
    if refused:
        assert len(errors) == 1 and "custom object 'ticker'" in errors[0] and "a lambda (line 6)" in errors[0]
        assert "approximate" in errors[0]
    else:
        assert errors == []
    _snapshot(data, "excitation_visible")["stop"] = False  # without a stop, a time-based builder is no error
    assert _stop_errors(_check(project_copy, data)) == []


# --- fingerprints and staleness ---------------------------------------------------------------------------------


def test_flipping_a_stop_leaves_the_scene_fingerprints_and_the_pictures_alone(project_copy: Project) -> None:
    report = validate_project(project_copy)
    assert report.animation and report.storyboard and report.style
    data = report.storyboard.model_dump(mode="json")

    def prints(board: dict[str, Any]) -> dict[str, str]:
        return scene_fingerprints(
            report.animation,
            Storyboard.model_validate(board),
            style_hash=report.style.hash,
            data_hashes={"responses": "a" * 64},
            custom_hashes={},
        )

    stopped = copy.deepcopy(data)
    _snapshot(stopped, "pool_raised").update({"stop": True, "label": "pool raised to 4"})
    _snapshot(stopped, "excitation_visible").update({"stop": True})
    assert prints(stopped) == prints(data)
    module = generate_scene_module(report.animation, Storyboard.model_validate(data), report.style)
    assert generate_scene_module(report.animation, Storyboard.model_validate(stopped), report.style) == module
    moved = copy.deepcopy(stopped)
    _snapshot(moved, "pool_raised")["at_seconds"] = 13.2  # a snapshot's time is a breakpoint: that does count
    assert prints(moved)["normalization"] != prints(data)["normalization"]

    before, after = Storyboard.model_validate(data), Storyboard.model_validate(stopped)
    dependency = changed_scenes(
        before,
        after,
        before_spec=report.animation,
        after_spec=report.animation,
        data_changed=set(),
        style_changed=False,
        custom_code_changed=False,
    )
    assert dependency.stale_scene_ids == []
    assert "scene 'normalization': stops changed, which changes no picture" in dependency.notes


# --- result.stops from a recorded manifest ----------------------------------------------------------------------


@pytest.fixture
def recorded() -> ArtifactManifest:
    """The manifest of a final render of divisive_normalization with stops at excitation_visible (4 s) and
    pool_raised (13 s), as `scianim render --profile final --json` printed it, with `result.stops` removed: the
    derivation must rebuild them from the job and the worker's records alone."""
    data = json.loads(RECORDED.read_text(encoding="utf-8"))
    data["result"].pop("stops", None)
    return ArtifactManifest.model_validate(data)


def test_result_stops_are_derived_from_the_recorded_manifest(recorded: ArtifactManifest) -> None:
    job, result = recorded.job, recorded.result
    assert job.quality_profile == "final" and job.manim.frame_rate == 30
    stops, problems, notes = derive_stops(job, result)
    assert problems == []
    # `gain` starts at excitation_visible: the hold shows the sweep's first frame, which draws its readout.
    assert notes == [
        "stop 'excitation_visible': a motion starts on its frame 120, so the hold shows that motion's first frame, "
        "which can differ from the rest before it (a sweep's readout appears there, for one)"
    ]
    assert [s.snapshot_id for s in stops] == ["excitation_visible", "pool_raised"]
    assert [s.label for s in stops] == ["drive alone", "pool raised to 4"]
    for stop in stops:
        target = job.snapshots[stop.snapshot_id]
        assert stop.frame_index == round(target.expected_time_seconds * 30)
        assert stop.time_seconds == pytest.approx(target.expected_time_seconds)
        assert stop.notes == target.description and stop.frozen == []
        sampled = next(c for c in result.checkpoints if c.snapshot_id == stop.snapshot_id)
        assert sampled.frame_index == stop.frame_index
        assert stop.rest_before_frames >= rest_frames_needed(30) == 9
    assert [s.frame_index for s in stops] == [120, 390]
    assert recorded.model_dump(mode="json")["result"]["videos"][0]["frame_count"] == 540
    applied = apply_stops(job, result)
    assert applied.status == "succeeded" and applied.stops == stops and applied.errors == []
    assert [w for w in applied.warnings if w.startswith("stops:")] == [f"stops: {notes[0]}"]
    with_stops = json.loads(RECORDED.read_text(encoding="utf-8"))["result"]["stops"]
    assert [s.model_dump(mode="json") for s in stops] == with_stops  # what the control plane wrote at render time


def test_the_derivation_reads_sampled_frames_when_no_clock_was_recorded(recorded: ArtifactManifest) -> None:
    """A parallel render's merged result lists no reached checkpoints; the sampled frames carry the index."""
    result = recorded.result.model_copy(update={"reached": []})
    stops, problems, _ = derive_stops(recorded.job, result)
    assert problems == [] and [s.frame_index for s in stops] == [120, 390]


def _moving(plays: list[PlayRecord], frame: int, fps: float) -> list[PlayRecord]:
    """The plays with the one that ends on `frame` marked as moving."""
    return [
        p.model_copy(update={"static": False}) if round(p.start_seconds * fps) + p.frames == frame else p for p in plays
    ]


def test_a_final_render_fails_when_a_player_could_not_hold_a_stop(recorded: ArtifactManifest) -> None:
    job, result = recorded.job, recorded.result
    moving = result.model_copy(update={"plays": _moving(list(result.plays), 390, 30)})
    failed = apply_stops(job, moving)
    assert failed.status == "failed"
    assert any(
        e.startswith("stops: stop 'pool_raised' has 0 static frames before frame 390, fewer than the 9")
        for e in failed.errors
    )
    draft = apply_stops(job.model_copy(update={"quality_profile": "draft"}), moving)
    assert draft.status == "succeeded" and any("pool_raised" in w for w in draft.warnings)

    # A stop whose frame no play starts on (here: the clock moved a tenth of a second).
    reached = [
        r.model_copy(update={"time_seconds": r.time_seconds + 0.1}) if r.snapshot_id == "pool_raised" else r
        for r in result.reached
    ]
    off_grid = apply_stops(job, result.model_copy(update={"reached": reached}))
    assert off_grid.status == "failed"
    assert any("which no play starts on" in e for e in off_grid.errors)
    assert any("the still was sampled from frame 390" in e for e in off_grid.errors)


def test_a_frozen_stop_warns_instead_of_failing(recorded: ArtifactManifest) -> None:
    job, result = recorded.job, recorded.result
    snapshots = dict(job.snapshots)
    snapshots["pool_raised"] = snapshots["pool_raised"].model_copy(update={"frozen": ["orbit"]})
    frozen_job = job.model_copy(update={"snapshots": snapshots})
    moving = result.model_copy(update={"plays": _moving(list(result.plays), 390, 30)})
    applied = apply_stops(frozen_job, moving)
    assert applied.status == "succeeded"
    assert any("the camera turns through it (orbit, stop_through)" in w for w in applied.warnings)
    assert applied.stops[1].frozen == ["orbit"]


def test_no_stops_leave_the_result_unchanged(recorded: ArtifactManifest) -> None:
    snapshots = {k: v.model_copy(update={"stop": False, "label": None}) for k, v in recorded.job.snapshots.items()}
    job = recorded.job.model_copy(update={"snapshots": snapshots})
    assert apply_stops(job, recorded.result) is recorded.result
    failed = recorded.result.model_copy(update={"status": "failed"})
    assert apply_stops(recorded.job, failed) is failed


# --- tooling ----------------------------------------------------------------------------------------------------


def test_parts_run_from_the_start_through_each_stop_to_the_end() -> None:
    assert parts([("a", 4.0), ("b", 13.0)], 18.0) == [
        ("start", "a", 0.0, 4.0),
        ("a", "b", 4.0, 13.0),
        ("b", "end", 13.0, 18.0),
    ]
    assert parts([], 6.0) == [("start", "end", 0.0, 6.0)]


def test_timing_lists_the_parts_between_stops(project_copy: Project) -> None:
    text = project_copy.storyboard_path.read_text(encoding="utf-8")
    anchor = "at_seconds: 13\n"
    project_copy.storyboard_path.write_text(text.replace(anchor, anchor + "        stop: true\n"), encoding="utf-8")
    result = CliRunner().invoke(cli.app, ["timing", str(project_copy.root)], catch_exceptions=False)
    assert result.exit_code == 0, result.stdout
    flat = " ".join(result.stdout.split())
    assert "1 stop(s) present the clip in 2 parts" in flat
    assert "│ 1 │ start (0s) │ pool_raised (13s) │ 13.00 │ 390 │" in flat
    assert "│ 2 │ pool_raised (13s) │ end (18s) │ 5.00 │ 150 │" in flat


def test_the_review_sheet_marks_stops(recorded: ArtifactManifest, project_copy: Project) -> None:
    storyboard = validate_project(project_copy).storyboard
    assert storyboard is not None
    manifest = recorded.model_copy(update={"result": apply_stops(recorded.job, recorded.result)})
    html = render_sheet(manifest, storyboard, Path("."))
    assert '<span class="kind stop">stop: drive alone | frame 120</span>' in html
    assert '<span class="kind stop">stop: pool raised to 4 | frame 390</span>' in html
    assert "2 stop(s): a player holds the movie at each until the next key, so it plays in 3 parts" in html
    assert html.count('class="kind stop"') == 2


def test_a_render_writes_its_stops_into_the_manifest_and_a_cache_hit_returns_them(
    project_copy: Project, monkeypatch
) -> None:
    """The worker is faked: it reports the frame each snapshot was sampled from and no plays."""
    from scianim.codegen.generate import write_scene_module
    from scianim.render.jobs import finish_manifest
    from scianim_core import CheckpointRecord, VideoRecord, WorkerResult

    text = project_copy.storyboard_path.read_text(encoding="utf-8")
    anchor = "at_seconds: 13\n"
    project_copy.storyboard_path.write_text(
        text.replace(anchor, anchor + '        stop: true\n        label: "pool raised"\n'), encoding="utf-8"
    )
    report = validate_project(project_copy, require_family=True)
    assert report.ok and report.animation and report.storyboard and report.style
    write_scene_module(
        report.animation, report.storyboard, report.style, project_copy.scene_module_path(report.animation)
    )
    runs: list[str] = []

    def run_job(project, family, job, paths, hashes, timeout=1800):
        runs.append(job.job_id)
        mp4 = project.root / job.output_dir / f"{job.job_id}.mp4"
        mp4.parent.mkdir(parents=True, exist_ok=True)
        mp4.write_bytes(b"movie")
        checkpoints = [
            CheckpointRecord(
                snapshot_id=sid,
                scene_id=target.scene_id,
                kind="sampled_video_frame",
                png=f"{job.output_dir}/{sid}.png",
                width_px=8,
                height_px=8,
                sha256="0" * 64,
                animation_index=0,
                expected_time_seconds=target.expected_time_seconds,
                renderer_time_seconds=target.expected_time_seconds,
                frame_index=round(target.expected_time_seconds * job.manim.frame_rate),
            )
            for sid, target in job.snapshots.items()
        ]
        for record in checkpoints:
            (project.root / record.png).write_bytes(b"png")
        video = VideoRecord(
            path=f"{job.output_dir}/{job.job_id}.mp4",
            width_px=8,
            height_px=8,
            fps=30,
            duration_seconds=18,
            frame_count=540,
            codec="h264",
            sha256="1" * 64,
        )
        result = WorkerResult(
            job_id=job.job_id, status="succeeded", checkpoints=checkpoints, videos=[video], elapsed_seconds=0.1
        )
        return finish_manifest(project, job, paths, hashes, result)

    tools = {"available": True, "python": "3.12.0", "manim": "0.22.1", "bridge_fingerprint": "f" * 64}
    monkeypatch.setattr(cli, "tool_versions_for", lambda family: dict(tools))
    monkeypatch.setattr(cli, "run_job", run_job)
    runner = CliRunner()
    first = runner.invoke(cli.app, ["render", str(project_copy.root), "--profile", "final", "--json"])
    assert first.exit_code == 0, first.stderr
    fresh = ArtifactManifest.model_validate_json(first.stdout)
    assert [(s.snapshot_id, s.label, s.frame_index) for s in fresh.result.stops] == [
        ("pool_raised", "pool raised", 390)
    ]
    assert "stop 1: pool_raised (pool raised) at frame 390" in " ".join(first.stderr.split())
    second = runner.invoke(cli.app, ["render", str(project_copy.root), "--profile", "final", "--json"])
    cached = ArtifactManifest.model_validate_json(second.stdout)
    assert cached.cache_hit and cached.result.stops == fresh.result.stops and len(runs) == 1
    on_disk = json.loads((project_copy.root / fresh.job.output_dir / "manifest.json").read_text())
    assert on_disk["result"]["stops"][0]["frame_index"] == 390
