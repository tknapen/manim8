from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "scianim.cli", *args], capture_output=True, text=True, check=False, cwd=cwd
    )


@pytest.fixture
def scianim():
    """The CLI as a callable: scianim("validate", path) -> CompletedProcess."""
    return run_cli


@pytest.fixture(scope="module")
def workspace(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A temporary workspace with the example family synced (uv's cache makes repeat syncs fast)."""
    if shutil.which("uv") is None:
        pytest.skip("uv is not installed")
    root = tmp_path_factory.mktemp("integration") / "workspace"
    init = run_cli("workspace", "init", str(root), "--with-example")
    assert init.returncode == 0, init.stdout + init.stderr
    sync = run_cli("family", "env", "sync", str(root / "families" / "computational_neuroscience"))
    if sync.returncode != 0:
        pytest.skip(f"family environment could not be built here:\n{(sync.stdout + sync.stderr)[-1500:]}")
    return root
