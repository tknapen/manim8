"""The manim8 skill and the tutorials (ADR-042): they name only commands that exist, the skill stays within
the limits agents read it under, and installing it works from a checkout and from a wheel."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest
import typer

from scianim import skill as skill_module
from scianim import workspace
from scianim.cli import app
from scianim.config.loader import SpecError, safe_yaml

REPO = Path(__file__).resolve().parents[2]
SKILL = REPO / ".claude" / "skills" / "manim8" / "SKILL.md"
TUTORIALS = sorted((REPO / "docs" / "tutorials").glob("[0-9][0-9]_*.md"))
CODE = re.compile(r"```[^\n]*\n(.*?)```|`([^`\n]+)`", re.DOTALL)
COMMAND = re.compile(r"\bscianim ([a-z][a-z-]*)(?: ([a-z][a-z-]*))?")


def _commands(text: str) -> set[tuple[str, str | None]]:
    """Every `scianim <command> [<subcommand>]` inside code in a Markdown text."""
    found: set[tuple[str, str | None]] = set()
    for match in CODE.finditer(text):
        for command in COMMAND.finditer(match.group(1) or match.group(2)):
            found.add((command.group(1), command.group(2)))
    return found


@pytest.mark.parametrize("path", [SKILL, *TUTORIALS], ids=lambda p: p.name)
def test_every_command_named_exists(path: Path) -> None:
    root = typer.main.get_command(app)
    assert hasattr(root, "commands")  # a group (Typer may carry its own copy of Click)
    named = _commands(path.read_text(encoding="utf-8"))
    assert named, f"{path.name} names no commands"
    for command, sub in sorted(named, key=str):
        assert command in root.commands, f"{path.name}: `scianim {command}` does not exist"
        subcommands = getattr(root.commands[command], "commands", None)
        if subcommands is not None and sub is not None:
            assert sub in subcommands, f"{path.name}: `scianim {command} {sub}` does not exist"


def test_the_skill_fits_how_agents_read_it() -> None:
    text = SKILL.read_text(encoding="utf-8")
    _, frontmatter, body = text.split("---", 2)
    meta = safe_yaml().load(frontmatter)
    assert meta["name"] == "manim8"
    # Claude Code shows the description (and when_to_use) in its skill listing, capped at 1,536 characters.
    assert 200 < len(meta["description"]) + len(meta.get("when_to_use", "")) <= 1536
    assert len(body.splitlines()) < 500  # the documented ceiling for SKILL.md
    for stage in ("Brief", "Context", "Specification and storyboard", "Keyframes", "Review", "Draft", "Approval"):
        assert f"**{stage}" in body, stage


def test_install_copies_the_skill_and_names_the_checkout(tmp_path: Path) -> None:
    target = skill_module.install_skill(tmp_path)
    assert (target / "SKILL.md").read_text() == SKILL.read_text()
    assert (target / "checkout.txt").read_text().strip() == str(REPO)
    with pytest.raises(SpecError, match="already installed"):
        skill_module.install_skill(tmp_path)
    assert skill_module.install_skill(tmp_path, force=True) == target


def test_an_installed_wheel_installs_its_own_copy(monkeypatch, tmp_path: Path) -> None:
    data = tmp_path / "_data"
    (data / "skill" / "manim8").mkdir(parents=True)
    (data / "skill" / "manim8" / "SKILL.md").write_text("---\nname: manim8\n---\n")
    monkeypatch.setattr(workspace, "repo_root", lambda: None)
    monkeypatch.setattr(workspace, "DATA_ROOT", data)
    target = skill_module.install_skill(tmp_path / "skills")
    assert (target / "SKILL.md").exists() and not (target / "checkout.txt").exists()  # `scianim` is on PATH


def test_tutorial_edits_come_in_pairs() -> None:
    spec = importlib.util.spec_from_file_location(
        "test_tutorials", REPO / "tests" / "integration" / "test_tutorials.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # its dataclass resolves annotations through the module
    spec.loader.exec_module(module)
    for path in TUTORIALS:
        blocks = module.blocks(path)
        assert any(b.lang == "bash" and not b.flags for b in blocks), path.name
        kinds = [b.flags[0] for b in blocks if b.lang == "yaml" and b.flags]
        assert kinds == ["before", "after"] * (len(kinds) // 2), (path.name, kinds)
