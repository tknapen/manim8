"""Moving a workspace's generated files forward when a release renames or reshapes them (ADR-037).

Contracts carry a `schema_version`; a breaking change raises it and adds a migration here, applied by
`scianim migrate`. The first migration is not a schema change but a rename: the distributions became
`manim8`, `manim8-core` and `manim8-bridge`, and a family environment written before the rename depends on
`scianim-bridge` and `scianim-core`, which `uv` can no longer find under those names.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

OLD_NAMES = {"scianim-bridge": "manim8-bridge", "scianim-core": "manim8-core"}
_OLD = re.compile(r"(?<![\w.-])(scianim-bridge|scianim-core)(?![\w-])")


def stale_family_pyproject(text: str) -> bool:
    """A family environment definition that still names the distributions by their old names."""
    return bool(_OLD.search(text))


def migrate_family_pyproject(text: str) -> str:
    return _OLD.sub(lambda m: OLD_NAMES[m.group(1)], text)


@dataclass
class MigrationReport:
    changed: list[Path] = field(default_factory=list)
    current: list[Path] = field(default_factory=list)


def migrate_tree(root: Path, *, dry_run: bool = False) -> MigrationReport:
    """Rewrite every family `pyproject.toml` under `root` (a workspace, a family or a project's family) that uses
    the old distribution names. The next `scianim family env sync` updates the lockfile to match."""
    report = MigrationReport()
    root = root.resolve()
    candidates = [root] if (root / "family.yaml").exists() else []
    candidates += [p.parent for p in sorted(root.rglob("family.yaml")) if ".venv" not in p.parts]
    for family_dir in dict.fromkeys(candidates):
        pyproject = family_dir / "pyproject.toml"
        if not pyproject.exists():
            continue
        text = pyproject.read_text(encoding="utf-8")
        if stale_family_pyproject(text):
            if not dry_run:
                pyproject.write_text(migrate_family_pyproject(text), encoding="utf-8")
            report.changed.append(pyproject)
        else:
            report.current.append(pyproject)
    return report


__all__ = ["OLD_NAMES", "MigrationReport", "migrate_family_pyproject", "migrate_tree", "stale_family_pyproject"]
