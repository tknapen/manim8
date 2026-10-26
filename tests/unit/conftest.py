from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from scianim.project import Project

REPO = Path(__file__).resolve().parents[2]
EXAMPLE = REPO / "examples" / "divisive_normalization"
STYLES = REPO / "styles"
FAMILIES = REPO / "examples" / "families"


@pytest.fixture
def repo_root() -> Path:
    return REPO


@pytest.fixture
def example_project() -> Project:
    return Project(EXAMPLE)


@pytest.fixture
def project_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Project:
    """A writable copy of the example project with styles and families discoverable."""
    target = tmp_path / "divisive_normalization"
    shutil.copytree(EXAMPLE, target, ignore=shutil.ignore_patterns(".scianim", "renders", "code", "__pycache__"))
    monkeypatch.setenv("SCIANIM_STYLES", str(STYLES))
    monkeypatch.setenv("SCIANIM_FAMILIES", str(FAMILIES))
    return Project(target)


@pytest.fixture
def styles_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "styles"
    shutil.copytree(STYLES, target)
    monkeypatch.setenv("SCIANIM_STYLES", str(target))
    return target
