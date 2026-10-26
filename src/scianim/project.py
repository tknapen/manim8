"""Project directory layout and discovery."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from scianim.config.loader import SpecError, load_animation, load_storyboard
from scianim_core import AnimationSpec, Storyboard

ANIMATION_FILE = "animation.yaml"
STORYBOARD_FILE = "storyboard.yaml"


def env_paths(name: str) -> list[Path]:
    raw = os.environ.get(name, "")
    return [Path(p).expanduser() for p in raw.split(os.pathsep) if p]


@dataclass(frozen=True)
class Project:
    root: Path

    @property
    def animation_path(self) -> Path:
        return self.root / ANIMATION_FILE

    @property
    def storyboard_path(self) -> Path:
        return self.root / STORYBOARD_FILE

    @property
    def code_dir(self) -> Path:
        return self.root / "code"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def feedback_dir(self) -> Path:
        return self.root / "feedback"

    @property
    def renders_dir(self) -> Path:
        return self.root / "renders"

    @property
    def scianim_dir(self) -> Path:
        return self.root / ".scianim"

    def load_animation(self) -> AnimationSpec:
        return load_animation(self.animation_path)

    def load_storyboard(self) -> Storyboard | None:
        if not self.storyboard_path.exists():
            return None
        return load_storyboard(self.storyboard_path)

    def scene_module_path(self, spec: AnimationSpec) -> Path:
        return self.code_dir / f"scene_{spec.id}.py"

    def style_search_dirs(self) -> list[Path]:
        """SCIANIM_STYLES entries, then every `styles/` directory above the project."""
        dirs = env_paths("SCIANIM_STYLES")
        for parent in (self.root, *self.root.resolve().parents):
            candidate = parent / "styles"
            if candidate.is_dir() and candidate not in dirs:
                dirs.append(candidate)
        return dirs

    def family_search_roots(self) -> list[Path]:
        """SCIANIM_FAMILIES entries, then every `families/` directory above the project."""
        roots = env_paths("SCIANIM_FAMILIES")
        for parent in (self.root, *self.root.resolve().parents):
            candidate = parent / "families"
            if candidate.is_dir() and candidate not in roots:
                roots.append(candidate)
        return roots


def scene_class_name(project_id: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[^a-zA-Z0-9]+", project_id) if part)


def find_project(path: Path) -> Project:
    path = path.resolve()
    if path.is_file():
        path = path.parent
    if (path / ANIMATION_FILE).exists():
        return Project(path)
    raise SpecError(path, f"not a project directory (no {ANIMATION_FILE})")
