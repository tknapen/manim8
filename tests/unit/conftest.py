from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from scianim.project import Project
from scianim.workspace import EXAMPLE_FAMILY, EXAMPLE_PROJECT, init_workspace

REPO = Path(__file__).resolve().parents[2]
EXAMPLE = REPO / "examples" / "families" / EXAMPLE_FAMILY / EXAMPLE_PROJECT
STYLES = REPO / "styles"


@pytest.fixture
def repo_root() -> Path:
    return REPO


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A fresh workspace holding the bundled styles plus the example family and project."""
    root = tmp_path / "ws"
    init_workspace(root, with_example=True)
    return root


@pytest.fixture
def project_copy(workspace: Path) -> Project:
    """The example project inside a workspace: styles and family resolve by ancestry, no env vars."""
    return Project(workspace / "families" / EXAMPLE_FAMILY / EXAMPLE_PROJECT)


@pytest.fixture
def styles_copy(tmp_path: Path) -> Path:
    target = tmp_path / "styles"
    shutil.copytree(STYLES, target)
    return target
