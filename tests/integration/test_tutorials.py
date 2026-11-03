"""The tutorials run as written (docs/tutorials): their shell blocks in order, their edits, and the output they
quote. A page that stops matching the package fails here rather than on a reader's machine.

Conventions, from docs/tutorials/README.md: a `bash` block runs; `bash setup` and `bash notest` are shown but not
run; a `text output` block lists lines that must appear in the output of the `bash` block before it; a
`yaml before file=...` block followed by a `yaml after file=...` block is an edit, a replacement that must match
exactly once. `~/animations` becomes a temporary directory.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]
TUTORIALS = sorted((REPO / "docs" / "tutorials").glob("[0-9][0-9]_*.md"))
FENCE = re.compile(r"^```([^\n]*)\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)
WORKSPACE = "~/animations"


@dataclass
class Block:
    lang: str
    flags: list[str]
    attrs: dict[str, str]
    body: str


def blocks(path: Path) -> list[Block]:
    found = []
    for match in FENCE.finditer(path.read_text(encoding="utf-8")):
        words = match.group(1).split()
        flags = [word for word in words[1:] if "=" not in word]
        attrs = dict(word.split("=", 1) for word in words[1:] if "=" in word)
        found.append(Block(words[0] if words else "", flags, attrs, match.group(2)))
    return found


def _flat(text: str) -> str:
    return " ".join(text.split())


def run_tutorial(path: Path, root: Path) -> None:
    here = str(root / "animations")
    env = {**os.environ, "COLUMNS": "200"}
    output: str | None = None
    edit: tuple[str, str] | None = None
    for block in blocks(path):
        if block.lang == "bash" and not block.flags:
            script = block.body.replace(WORKSPACE, here)
            result = subprocess.run(
                ["bash", "-euo", "pipefail", "-c", script],
                cwd=REPO,
                env=env,
                capture_output=True,
                text=True,
                timeout=1800,
            )
            output = result.stdout + result.stderr
            assert result.returncode == 0, f"{path.name}: this block failed\n{block.body}\n{output[-4000:]}"
        elif block.lang == "text" and "output" in block.flags:
            assert output is not None, f"{path.name}: an output block comes before any command"
            for line in (line.strip() for line in block.body.splitlines()):
                if line:
                    assert _flat(line) in _flat(output), f"{path.name}: expected {line!r} in\n{output[-4000:]}"
        elif block.lang == "yaml" and "before" in block.flags:
            assert edit is None, f"{path.name}: two 'before' blocks in a row"
            edit = (block.attrs["file"], block.body)
        elif block.lang == "yaml" and "after" in block.flags:
            assert edit is not None and edit[0] == block.attrs["file"], f"{path.name}: an 'after' without its 'before'"
            target = Path(edit[0].replace(WORKSPACE, here))
            text = target.read_text(encoding="utf-8")
            assert text.count(edit[1]) == 1, (
                f"{path.name}: the 'before' text occurs {text.count(edit[1])} times in {target}"
            )
            target.write_text(text.replace(edit[1], block.body), encoding="utf-8")
            edit = None
    assert edit is None, f"{path.name}: an edit without its 'after' block"


def test_the_tutorials_run_as_written(tmp_path: Path) -> None:
    assert [p.name for p in TUTORIALS] == ["01_first_picture.md", "02_change_one_thing.md"]
    for path in TUTORIALS:  # in order: the second continues in the workspace of the first
        run_tutorial(path, tmp_path)
