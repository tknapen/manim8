"""The manim8 agent skill (ADR-042): where its files are, and installing them where an agent finds them.

The skill is a playbook (`SKILL.md`) for an agent that drives this package on a person's behalf. Its source lives
in the repository at `.claude/skills/manim8/`, so an agent working in a checkout, locally or in a cloud session,
finds it there; an installed wheel carries a copy in its data (ADR-037). `install_skill` copies it into a skills
directory (by default the personal `~/.claude/skills/`, or a repository's `.claude/skills/` to commit) and, when
it runs from a checkout, writes `checkout.txt` beside the playbook so the agent can run `uv run --project
<checkout> scianim` from anywhere.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from scianim import workspace
from scianim.config.loader import SpecError

SKILL_NAME = "manim8"
CHECKOUT_FILE = "checkout.txt"


def skill_source() -> Path:
    root = workspace.repo_root()
    if root is not None and (root / ".claude" / "skills" / SKILL_NAME / "SKILL.md").exists():
        return root / ".claude" / "skills" / SKILL_NAME
    packaged = workspace.DATA_ROOT / "skill" / SKILL_NAME
    if (packaged / "SKILL.md").exists():
        return packaged
    raise SpecError(None, "the manim8 skill is not in this installation; reinstall manim8")


def install_skill(skills_dir: Path, *, force: bool = False) -> Path:
    """Copy the skill into `skills_dir/manim8`; refuse to replace an installed copy unless `force`."""
    source = skill_source()
    target = skills_dir.expanduser().resolve() / SKILL_NAME
    if target.exists():
        if not force:
            raise SpecError(target, "the skill is already installed here; pass --force to replace it")
        shutil.rmtree(target)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(CHECKOUT_FILE))
    root = workspace.repo_root()
    if root is not None:
        (target / CHECKOUT_FILE).write_text(f"{root}\n", encoding="utf-8")
    return target
