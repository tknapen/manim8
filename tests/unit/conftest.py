from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from scianim.project import Project
from scianim.workspace import EXAMPLE_FAMILY, EXAMPLE_PROJECT, init_workspace

REPO = Path(__file__).resolve().parents[2]
EXAMPLE = REPO / "examples" / "families" / EXAMPLE_FAMILY / EXAMPLE_PROJECT
STYLES = REPO / "styles"
CONSOLE_WIDTH = 400


@pytest.fixture(autouse=True)
def wide_cli_consoles() -> Iterator[None]:
    """The CLI's rich consoles at one wide width for every test. Without a terminal, rich wraps at COLUMNS or 80
    columns, so a message that names an absolute path (`<path>: valid (0 errors, 0 warnings)`) broke across lines
    in a checkout with a long path or under a narrow COLUMNS, and an assertion on it failed."""
    from scianim import cli

    saved = [(console, console._width) for console in (cli.out, cli.err)]
    for console, _ in saved:
        console.width = CONSOLE_WIDTH
    yield
    for console, width in saved:
        console._width = width


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
