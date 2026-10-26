"""Source adapters for csv, markdown, text, pdf, image and project sources.

Every adapter fills `SourceExtract.says` with facts read from the file and leaves `inferred` empty:
units, meanings and conclusions are for people and agents to state, with attribution.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from scianim.config.loader import SpecError, load_animation, load_storyboard
from scianim.planning.checks import Report
from scianim.project import Project
from scianim_core import SourceExtract, SourceRef
from scianim_core.hashing import sha256_file
from scianim_core.sources import ColumnProfile, PageText

EXTRACT_DIR = ".scianim/sources"
TEXT_LIMIT = 20_000
PAGE_LIMIT = 4_000
EXAMPLES = 3


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _number(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def profile_csv(path: Path) -> dict[str, Any]:
    with path.open(newline="", encoding="utf-8") as handle:
        sample = handle.read(4096)
        handle.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            delimiter = dialect.delimiter
        except csv.Error:
            delimiter = ","
        reader = csv.reader(handle, delimiter=delimiter)
        header = next(reader, [])
        rows = [row for row in reader if any(cell.strip() for cell in row)]
    columns: list[ColumnProfile] = []
    for index, name in enumerate(header):
        values = [row[index].strip() if index < len(row) else "" for row in rows]
        present = [v for v in values if v != ""]
        numbers = [_number(v) for v in present]
        if not present:
            dtype = "empty"
        elif all(n is not None for n in numbers):
            dtype = "integer" if all(float(v).is_integer() and "." not in v for v in present) else "number"
        elif all(v.lower() in ("true", "false") for v in present):
            dtype = "boolean"
        else:
            dtype = "text"
        numeric = [n for n in numbers if n is not None] if dtype in ("integer", "number") else []
        distinct = sorted(set(present), key=present.index)
        columns.append(
            ColumnProfile(
                name=name,
                dtype=dtype,  # type: ignore[arg-type]
                missing=len(values) - len(present),
                distinct=len(set(present)),
                minimum=min(numeric) if numeric else None,
                maximum=max(numeric) if numeric else None,
                mean=sum(numeric) / len(numeric) if numeric else None,
                examples=distinct[:EXAMPLES],
            )
        )
    return {
        "delimiter": delimiter,
        "header": header,
        "rows": len(rows),
        "columns": [c.model_dump(mode="json") for c in columns],
    }


def profile_text(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    headings = [line.strip() for line in text.splitlines() if re.match(r"^#{1,6}\s", line)]
    return {
        "characters": len(text),
        "words": len(text.split()),
        "headings": headings,
        "text": text[:TEXT_LIMIT],
        "truncated": len(text) > TEXT_LIMIT,
    }


def profile_pdf(path: Path) -> tuple[dict[str, Any], list[str]]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages: list[PageText] = []
    for number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        pages.append(PageText(page=number, characters=len(text), text=text[:PAGE_LIMIT]))
    info = reader.metadata or {}
    says = {
        "page_count": len(reader.pages),
        "title": info.get("/Title"),
        "author": info.get("/Author"),
        "pages": [p.model_dump(mode="json") for p in pages],
    }
    notes = ["text per page only: equations, figures and tables are not extracted; cite them by page"]
    if all(p.characters == 0 for p in pages):
        notes.append("no extractable text (scanned pages?); page anchors still apply")
    return says, notes


def profile_image(path: Path) -> tuple[dict[str, Any], list[str]]:
    from PIL import Image

    with Image.open(path) as image:
        says = {"width_px": image.width, "height_px": image.height, "mode": image.mode, "format": image.format}
    return says, ["no visual description is produced; the role declared in animation.yaml applies"]


def profile_project(path: Path) -> tuple[dict[str, Any], list[str]]:
    project = Project(path if path.is_dir() else path.parent)
    says: dict[str, Any] = {}
    notes: list[str] = []
    try:
        spec = load_animation(project.animation_path)
        says["id"] = spec.id
        says["title"] = spec.title
        says["style"] = f"{spec.style.name}@{spec.style.version}"
        says["equations"] = [e.id for e in spec.equations]
    except SpecError as exc:
        notes.append(f"animation.yaml could not be read: {exc.message}")
    try:
        storyboard = load_storyboard(project.storyboard_path) if project.storyboard_path.exists() else None
        says["scenes"] = [s.id for s in storyboard.scenes] if storyboard else []
    except SpecError as exc:
        notes.append(f"storyboard.yaml could not be read: {exc.message}")
    says["revisions"] = (
        sorted(p.name for p in project.revisions_dir.glob("rev_*")) if project.revisions_dir.is_dir() else []
    )
    return says, notes


def probe_source(source: SourceRef, path: Path) -> SourceExtract:
    if not path.exists():
        raise SpecError(path, f"source '{source.id}' file not found")
    says: dict[str, Any] = {}
    notes: list[str] = []
    adapter = source.type
    if source.type == "csv":
        says = profile_csv(path)
        notes.append("column meanings and units are not inferred; declare them in the brief or the storyboard")
    elif source.type in ("markdown", "text"):
        says = profile_text(path)
    elif source.type == "pdf":
        says, notes = profile_pdf(path)
    elif source.type == "image":
        says, notes = profile_image(path)
    elif source.type == "project":
        says, notes = profile_project(path)
    digest = sha256_file(path) if path.is_file() else sha256_file(path / "animation.yaml")
    return SourceExtract(
        source_id=source.id,
        type=source.type,
        role=source.role,
        path=str(source.path),
        sha256=digest,
        size_bytes=path.stat().st_size if path.is_file() else 0,
        extracted_at=_now(),
        adapter=f"scianim.sources.{adapter}",
        says=says,
        notes=notes,
    )


def extract_path(project: Project, source_id: str) -> Path:
    return project.root / EXTRACT_DIR / f"{source_id}.json"


def write_extract(project: Project, extract: SourceExtract) -> Path:
    path = extract_path(project, extract.source_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(extract.model_dump_json(indent=2), encoding="utf-8")
    return path


def probe_all(project: Project, report: Report, write: bool = True) -> list[SourceExtract]:
    """Probe every declared source whose file resolved; unresolved ones are already errors in the report."""
    assert report.animation is not None
    extracts: list[SourceExtract] = []
    for source in report.animation.sources:
        path = report.source_paths.get(source.id)
        if path is None:
            continue
        extract = probe_source(source, path)
        if write:
            write_extract(project, extract)
        extracts.append(extract)
    return extracts


def load_extracts(project: Project) -> dict[str, SourceExtract]:
    directory = project.root / EXTRACT_DIR
    if not directory.is_dir():
        return {}
    found: dict[str, SourceExtract] = {}
    for path in sorted(directory.glob("*.json")):
        try:
            extract = SourceExtract.model_validate_json(path.read_text(encoding="utf-8"))
        except (ValidationError, ValueError, json.JSONDecodeError):
            continue
        found[extract.source_id] = extract
    return found


__all__ = ["EXTRACT_DIR", "extract_path", "load_extracts", "probe_all", "probe_source", "write_extract"]
