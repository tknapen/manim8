"""The YAML loader is safe to call from many threads at once, and a truncated file is a SpecError."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from scianim.config.loader import SpecError, load_animation, load_yaml
from scianim.project import Project


def test_concurrent_loads_do_not_corrupt_each_other(project_copy: Project) -> None:
    path = project_copy.root / "animation.yaml"

    def load_many(_: int) -> int:
        for _ in range(40):
            assert load_animation(path).id
        return 1

    with ThreadPoolExecutor(max_workers=16) as pool:
        assert sum(pool.map(load_many, range(16))) == 16


def test_truncated_yaml_is_a_spec_error(tmp_path: Path) -> None:
    broken = tmp_path / "animation.yaml"
    broken.write_text("schema_version: '1.0'\nid: \"x\nsources: [", encoding="utf-8")  # cut off mid-string
    with pytest.raises(SpecError, match=r"YAML syntax error|file"):
        load_yaml(broken)
