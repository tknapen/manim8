from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FAMILY = REPO / "examples" / "families" / "computational_neuroscience"


def family_ready() -> bool:
    return (FAMILY / ".venv" / "bin" / "python").exists() or (FAMILY / ".venv" / "Scripts" / "python.exe").exists()


@pytest.fixture
def ready_family() -> Path:
    if not family_ready():
        pytest.skip(
            "family environment not synced; run `scianim family env sync examples/families/computational_neuroscience`"
        )
    return FAMILY
