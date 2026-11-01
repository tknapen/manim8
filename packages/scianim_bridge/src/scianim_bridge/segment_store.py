"""A store of finished video segments shared across renders (ADR-033).

Manim keeps a per-play cache: before drawing a play it hashes the scene, the animations and the camera, and
skips the drawing when a segment of that name exists in its media directory. Each worker of a parallel render
draws into a directory of its own, because Manim writes a segment directly to its final path and another
process could take a half-written file for a finished one. The store lets every render benefit from every
other: a worker publishes each finished segment into the store by an atomic rename, and before drawing a play
it looks the play's hash up there as well as in its own directory, linking a hit into its own directory first.
A segment only ever enters the store complete, so a reader sees a finished file or none.

The store is keyed outside this module by the render settings and the bridge's code fingerprint, so a change of
resolution, renderer or drawing code never meets segments drawn under other conditions.
"""

from __future__ import annotations

import hashlib
import importlib
import os
import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import Any

FINGERPRINT_LIBRARIES = ("manim", "av", "typst", "cairo", "manimpango", "PIL", "numpy")


def code_fingerprint() -> str:
    """A hash of every source file of the installed bridge and the versions of the libraries that draw and
    encode: the code that turns a scene into pixels."""
    digest = hashlib.sha256()
    package = Path(__file__).resolve().parent
    for path in sorted(package.rglob("*.py")):
        digest.update(path.relative_to(package).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    for name in FINGERPRINT_LIBRARIES:
        try:
            module = importlib.import_module(name)
            version = getattr(module, "__version__", None) or getattr(module, "version", None) or "present"
        except Exception:  # a missing library is part of the fingerprint too
            version = "absent"
        digest.update(f"{name}={version}\0".encode())
    return digest.hexdigest()


def _place(source: Path, target: Path) -> None:
    """Put a complete copy of `source` at `target` atomically: link (or copy) to a temporary name beside the
    target, then rename over it."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.unlink(missing_ok=True)
    try:
        os.link(source, temporary)
    except OSError:
        shutil.copy2(source, temporary)
    os.replace(temporary, target)


def install(writer: Any, store: Path, hits: list[str] | None = None) -> None:
    """Make a Manim file writer consult the store when its own cache misses.

    On a hit the stored segment is linked into the writer's own segment directory under the name Manim expects,
    and Manim proceeds as for any cached play: it skips the drawing and joins the file at the end."""
    original = writer.is_already_cached

    def is_already_cached(hash_invocation: str) -> bool:
        if original(hash_invocation):
            return True
        if not writer.output_spec.is_video:
            return False
        target = Path(writer.output_plan.segment_path(hash_invocation))
        source = store / target.name
        if not source.is_file():
            return False
        _place(source, target)
        if hits is not None:
            hits.append(hash_invocation)
        return True

    writer.is_already_cached = is_already_cached


def publish(paths: Iterable[Path], store: Path) -> int:
    """Copy finished segments into the store under their own names; a name already there is left alone (the
    name is the content hash). Returns how many were added."""
    added = 0
    for path in paths:
        path = Path(path)
        target = store / path.name
        if target.exists() or not path.is_file():
            continue
        _place(path, target)
        added += 1
    return added


__all__ = ["FINGERPRINT_LIBRARIES", "code_fingerprint", "install", "publish"]
