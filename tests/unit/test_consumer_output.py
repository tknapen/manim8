"""What another tool reads from a render (ADR-043): `--json` prints the manifest of the job just run or of the
cached one, and nothing else, on stdout; `--style` renders one job under another published style; `workspace init`
ignores what renders write. The worker is faked; the real one runs in the integration tests."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from scianim import cli
from scianim.codegen.generate import write_scene_module
from scianim.planning.checks import validate_project
from scianim.project import Project
from scianim.render.jobs import finish_manifest
from scianim.revisions.store import create_revision
from scianim.workspace import WORKSPACE_GITIGNORE, init_workspace
from scianim_core import ArtifactManifest, CheckpointRecord, VideoRecord, WorkerResult

TOOLS = {"available": True, "python": "3.12.0", "manim": "0.22.1", "scianim_bridge": "0.1.0a0"}
TOOLS["bridge_fingerprint"] = "f" * 64


def _sha(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


@pytest.fixture
def fake_worker(monkeypatch):
    """Stand in for the family environment: report tool versions, and write what a worker writes."""
    runs: list[str] = []

    def run_job(project, family, job, paths, hashes, timeout=1800):
        runs.append(job.job_id)
        root = project.root
        out_dir = job.output_dir
        checkpoints = []
        for index, (snapshot_id, target) in enumerate(job.snapshots.items()):
            png = f"{out_dir}/{snapshot_id}.png"
            kind = "manim_checkpoint" if job.operation == "render_snapshots" else "sampled_video_frame"
            checkpoints.append(
                CheckpointRecord(
                    snapshot_id=snapshot_id,
                    scene_id=target.scene_id,
                    kind=kind,
                    png=png,
                    width_px=job.manim.pixel_width,
                    height_px=job.manim.pixel_height,
                    sha256=_sha(root / png, f"{job.resolved_style.hash}{snapshot_id}".encode()),
                    animation_index=index,
                    expected_time_seconds=target.expected_time_seconds,
                    renderer_time_seconds=target.expected_time_seconds,
                )
            )
        videos = []
        if job.operation == "render_video":
            mp4 = f"{out_dir}/{job.job_id}.mp4"
            videos.append(
                VideoRecord(
                    path=mp4,
                    width_px=job.manim.pixel_width,
                    height_px=job.manim.pixel_height,
                    fps=job.manim.frame_rate,
                    duration_seconds=job.output.duration_seconds,
                    frame_count=round(job.output.duration_seconds * job.manim.frame_rate),
                    codec="h264",
                    sha256=_sha(root / mp4, job.cache_key.encode()),
                )
            )
        result = WorkerResult(
            job_id=job.job_id, status="succeeded", checkpoints=checkpoints, videos=videos, elapsed_seconds=0.5
        )
        return finish_manifest(project, job, paths, hashes, result)

    monkeypatch.setattr(cli, "tool_versions_for", lambda family: dict(TOOLS))
    monkeypatch.setattr(cli, "run_job", run_job)
    return runs


@pytest.fixture
def generated(project_copy: Project) -> Project:
    report = validate_project(project_copy, require_family=True)
    assert report.animation and report.storyboard and report.style
    write_scene_module(
        report.animation, report.storyboard, report.style, project_copy.scene_module_path(report.animation)
    )
    return project_copy


def _invoke(*args: str):
    return CliRunner().invoke(cli.app, [*args], catch_exceptions=False)


def _flat(text: str) -> str:
    """Human output as one line: rich wraps it at the console's width."""
    return " ".join(text.split())


def _manifest(stdout: str) -> ArtifactManifest:
    data = json.loads(stdout)  # exactly one JSON document, nothing around it
    return ArtifactManifest.model_validate(data)


def test_render_json_prints_the_manifest_of_a_fresh_and_of_a_cached_job(generated: Project, fake_worker) -> None:
    first = _invoke("render", str(generated.root), "--profile", "final", "--json")
    assert first.exit_code == 0, first.stderr
    fresh = _manifest(first.stdout)
    assert fresh.cache_hit is False and fresh.result.status == "succeeded"
    assert fresh.job.operation == "render_video" and fresh.job.quality_profile == "final"
    assert fresh.job.revision_id == "working"
    assert (generated.root / fresh.result.videos[0].path).exists()  # paths are relative to the project
    assert "rendering final video" in _flat(first.stderr) and "video:" in first.stderr  # human output on stderr
    on_disk = json.loads((generated.root / fresh.job.output_dir / "manifest.json").read_text())
    assert json.loads(first.stdout) == on_disk

    second = _invoke("render", str(generated.root), "--profile", "final", "--json")
    assert second.exit_code == 0, second.stderr
    cached = _manifest(second.stdout)
    assert cached.cache_hit is True and "cache hit" in _flat(second.stderr)
    assert cached.job.job_id == fresh.job.job_id and cached.job.cache_key == fresh.job.cache_key
    assert cached.result.videos == fresh.result.videos
    assert len(fake_worker) == 1

    # Without --json the same command prints for a person, on stdout.
    plain = _invoke("render", str(generated.root), "--profile", "final")
    assert plain.exit_code == 0 and "cache hit" in plain.stdout and not plain.stdout.lstrip().startswith("{")


def test_snapshot_json_prints_the_checkpoint_manifest(generated: Project, fake_worker) -> None:
    result = _invoke("snapshot", str(generated.root), "--all", "--json")
    assert result.exit_code == 0, result.stderr
    manifest = _manifest(result.stdout)
    assert manifest.job.operation == "render_snapshots"
    assert {c.snapshot_id for c in manifest.result.checkpoints} == set(manifest.job.snapshot_ids)
    again = _manifest(_invoke("snapshot", str(generated.root), "--all", "--json").stdout)
    assert again.cache_hit and again.job.job_id == manifest.job.job_id


def test_a_failed_job_prints_nothing_on_stdout(generated: Project, fake_worker, monkeypatch) -> None:
    missing = _invoke("render", str(generated.root), "--json", "--revision", "rev_0042")
    assert missing.exit_code == 1 and missing.stdout == "" and "rev_0042" in _flat(missing.stderr)

    def failing(project, family, job, paths, hashes, timeout=1800):
        result = WorkerResult(job_id=job.job_id, status="failed", elapsed_seconds=0.1, errors=["Manim [crashed]"])
        return finish_manifest(project, job, paths, hashes, result)

    monkeypatch.setattr(cli, "run_job", failing)
    failed = _invoke("render", str(generated.root), "--json")
    assert failed.exit_code == 1 and failed.stdout == ""
    assert "Manim [crashed]" in _flat(failed.stderr)  # rich markup in a message is printed as text
    monkeypatch.setattr(cli, "tool_versions_for", lambda family: {})
    no_env = _invoke("snapshot", str(generated.root), "--json")
    assert no_env.exit_code == 1 and no_env.stdout == "" and "family env sync" in _flat(no_env.stderr)


def test_style_renders_one_job_under_another_published_style(generated: Project, fake_worker) -> None:
    own = _manifest(_invoke("render", str(generated.root), "--profile", "draft", "--json").stdout)
    styled_run = _invoke("render", str(generated.root), "--profile", "draft", "--style", "default@0.5.0", "--json")
    assert styled_run.exit_code == 0, styled_run.stderr
    styled = _manifest(styled_run.stdout)
    assert (own.job.resolved_style.theme, own.job.resolved_style.theme_version) == ("tomas_scientific", "0.5.1")
    assert (styled.job.resolved_style.theme, styled.job.resolved_style.theme_version) == ("default", "0.5.0")
    assert styled.job.resolved_style.layers[-1] == "theme:default@0.5.0"
    assert styled.inputs.resolved_style == styled.job.resolved_style.hash != own.inputs.resolved_style
    assert styled.job.cache_key != own.job.cache_key and not styled.cache_hit
    assert "under default@0.5.0" in _flat(styled_run.stderr)
    # The project is not changed, and each style has its own cache entry.
    assert "tomas_scientific" in generated.animation_path.read_text()
    assert _manifest(_invoke("render", str(generated.root), "--profile", "draft", "--json").stdout).cache_hit
    again = _manifest(_invoke("render", str(generated.root), "--style", "default@0.5.0", "--json").stdout)
    assert again.cache_hit and again.job.cache_key == styled.job.cache_key


def test_style_applies_to_a_revision_without_touching_it(generated: Project, fake_worker) -> None:
    report = validate_project(generated, require_family=True)
    record = create_revision(generated, report, "first")
    frozen = (generated.revisions_dir / record.id / "style.resolved.json").read_text()
    result = _invoke("snapshot", str(generated.root), "--revision", record.id, "--style", "default@0.5.0", "--json")
    assert result.exit_code == 0, result.stderr
    manifest = _manifest(result.stdout)
    assert manifest.job.revision_id == record.id and manifest.job.resolved_style.theme == "default"
    assert manifest.job.output_dir.startswith(f"renders/{record.id}/")
    assert (generated.revisions_dir / record.id / "style.resolved.json").read_text() == frozen
    plain = _manifest(_invoke("snapshot", str(generated.root), "--revision", record.id, "--json").stdout)
    assert plain.job.resolved_style.theme == "tomas_scientific" and plain.job.cache_key != manifest.job.cache_key


def test_style_refuses_bad_references_and_styles_that_change_the_timing(generated: Project, fake_worker) -> None:
    bad = _invoke("render", str(generated.root), "--style", "lecturekit-dark@0.1.0", "--json")
    assert bad.exit_code == 1 and bad.stdout == ""
    assert "^[a-z][a-z0-9_]{0,63}$" in _flat(bad.stderr)  # the pattern survives rich's markup parser
    unknown = _invoke("render", str(generated.root), "--style", "nowhere@1.0.0", "--json")
    assert unknown.exit_code == 1 and unknown.stdout == "" and "nowhere@1.0.0" in _flat(unknown.stderr)
    # A published style whose motion tokens would make codegen write other times.
    styles = generated.root.parents[2] / "styles"
    sheet = styles / "slow_paper" / "0.1.0" / "style.yaml"
    sheet.parent.mkdir(parents=True)
    sheet.write_text(
        'schema_version: "1.0"\nname: slow_paper\nversion: 0.1.0\ninherits: default@0.5.0\n'
        "description: test\nmotion: {transition_seconds: 1.5}\n"
    )
    slow = _invoke("render", str(generated.root), "--style", "slow_paper@0.1.0", "--json")
    assert slow.exit_code == 1 and slow.stdout == "" and "not timing" in _flat(slow.stderr)
    assert fake_worker == []


def test_workspace_init_ignores_what_renders_write(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    init_workspace(root)
    text = (root / ".gitignore").read_text()
    assert text == WORKSPACE_GITIGNORE
    for pattern in ("renders/", ".scianim/", ".venv/", "media/"):
        assert pattern in text.splitlines()
    git = shutil.which("git")
    if git is None:
        return
    import subprocess

    subprocess.run([git, "init", "-q", str(root)], check=True)
    for path in (
        "families/lab/.venv/bin/python",
        "families/lab/demo/renders/working/job_1/manifest.json",
        "families/lab/demo/.scianim/cache/x.json",
        "families/lab/demo/media/videos/x.mp4",
        "families/lab/demo/code/__pycache__/scene_demo.cpython-312.pyc",
    ):
        ignored = subprocess.run([git, "-C", str(root), "check-ignore", "-q", path])
        assert ignored.returncode == 0, path
    for path in ("families/lab/uv.lock", "families/lab/demo/animation.yaml", "families/lab/demo/code/scene_demo.py"):
        kept = subprocess.run([git, "-C", str(root), "check-ignore", "-q", path])
        assert kept.returncode == 1, path
    # An existing .gitignore is extended, never replaced.
    other = tmp_path / "other"
    other.mkdir()
    (other / ".gitignore").write_text("*.log\n")
    init_workspace(other)
    lines = (other / ".gitignore").read_text().splitlines()
    assert lines[0] == "*.log" and "renders/" in lines


def test_validation_messages_print_patterns_intact(tmp_path: Path) -> None:
    """Rich would read `[a-z]` in pydantic's message as markup and drop it (the audit's I6 note)."""
    sheet = tmp_path / "styles" / "lecturekit-paper" / "0.1.0" / "style.yaml"
    sheet.parent.mkdir(parents=True)
    sheet.write_text(
        'schema_version: "1.0"\nname: lecturekit-paper\nversion: 0.1.0\ninherits: default@0.5.0\n'
        "description: bridged\npalette: {DoG: '#112233'}\n"
    )
    result = _invoke("validate", str(sheet))
    assert result.exit_code == 1
    text = _flat(result.stdout)
    assert text.count("^[a-z][a-z0-9_]{0,63}$") >= 2, text  # the name and the palette key
    assert "^{0,63}$" not in text
