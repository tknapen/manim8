"""Canonical JSON and SHA-256 helpers shared by the control plane and the bridge."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def canonical_dumps(data: Any) -> str:
    """Deterministic JSON: sorted keys, compact separators, UTF-8 preserved."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_json(data: Any) -> str:
    return sha256_text(canonical_dumps(data))


def sha256_file(path: Path | str, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()
