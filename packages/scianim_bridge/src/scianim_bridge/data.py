"""CSV tables, explicit transforms and encodings (spec section 5.2, ADR-003).

Every transformation is declared in the storyboard; nothing here infers semantics.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scianim_core.storyboard import DataBinding, ParameterRef


@dataclass(frozen=True)
class DataTable:
    columns: tuple[str, ...]
    rows: tuple[dict[str, str], ...]
    source: str = ""

    def __len__(self) -> int:
        return len(self.rows)

    def column(self, name: str) -> list[str]:
        self._require(name)
        return [row[name] for row in self.rows]

    def numeric(self, name: str) -> list[float]:
        values = []
        for index, raw in enumerate(self.column(name)):
            try:
                values.append(float(raw))
            except ValueError:
                raise ValueError(f"{self.source}: column '{name}' row {index + 1} is not numeric: {raw!r}") from None
        return values

    def _require(self, name: str) -> None:
        if name not in self.columns:
            raise KeyError(f"{self.source}: no column '{name}'; columns: {list(self.columns)}")

    def filter_equals(self, name: str, value: Any) -> DataTable:
        self._require(name)
        wanted = str(value)
        rows = tuple(row for row in self.rows if row[name] == wanted or _num_equal(row[name], value))
        return DataTable(self.columns, rows, self.source)

    def sort_by(self, name: str, descending: bool = False) -> DataTable:
        values = self.numeric(name)
        order = sorted(range(len(self.rows)), key=lambda i: values[i], reverse=descending)
        return DataTable(self.columns, tuple(self.rows[i] for i in order), self.source)

    def normalize(self, name: str, by: str = "max") -> DataTable:
        values = self.numeric(name)
        if not values:
            return self
        divisor = {"max": max(values), "sum": sum(values), "first": values[0]}[by]
        if divisor == 0:
            raise ValueError(f"{self.source}: cannot normalize column '{name}' by {by} = 0")
        rows = tuple({**row, name: repr(v / divisor)} for row, v in zip(self.rows, values, strict=True))
        return DataTable(self.columns, rows, self.source)

    def scale(self, name: str, by: float) -> DataTable:
        values = self.numeric(name)
        rows = tuple({**row, name: repr(v * by)} for row, v in zip(self.rows, values, strict=True))
        return DataTable(self.columns, rows, self.source)

    def smooth(self, name: str, window: float) -> DataTable:
        """Gaussian smoothing along the row order with standard deviation `window` in rows; zero is the identity."""
        values = self.numeric(name)
        if window <= 1e-9 or len(values) < 2:
            return self
        smoothed = []
        for i in range(len(values)):
            weights = [math.exp(-((j - i) ** 2) / (2.0 * window * window)) for j in range(len(values))]
            total = sum(weights)
            smoothed.append(sum(w * v for w, v in zip(weights, values, strict=True)) / total)
        rows = tuple({**row, name: repr(v)} for row, v in zip(self.rows, smoothed, strict=True))
        return DataTable(self.columns, rows, self.source)

    def group_by(self, name: str) -> dict[str, DataTable]:
        self._require(name)
        groups: dict[str, list[dict[str, str]]] = {}
        for row in self.rows:
            groups.setdefault(row[name], []).append(row)
        return {key: DataTable(self.columns, tuple(rows), self.source) for key, rows in groups.items()}


def _num_equal(cell: str, value: Any) -> bool:
    try:
        return float(cell) == float(value)
    except (TypeError, ValueError):
        return False


def load_csv(path: Path) -> DataTable:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        columns = tuple(name.strip() for name in (reader.fieldnames or []))
        rows = tuple({k.strip(): (v or "").strip() for k, v in row.items() if k is not None} for row in reader)
    if not columns:
        raise ValueError(f"{path}: CSV has no header row")
    return DataTable(columns, rows, source=path.name)


@dataclass(frozen=True)
class Series:
    label: str | None
    x: list[float]
    y: list[float]
    error: list[float] | None = None


def _setting(value: float | ParameterRef, parameters: dict[str, float]) -> float:
    if isinstance(value, ParameterRef):
        return float(parameters.get(value.parameter, value.default))
    return float(value)


def apply_binding(
    table: DataTable, binding: DataBinding | dict[str, Any], parameters: dict[str, float] | None = None
) -> list[Series]:
    """Apply the declared transforms, then split into one series per group value. `parameters` gives the current
    values of the parameters the transforms name (a `vary_parameter` sweep); their defaults otherwise."""
    bound = binding if isinstance(binding, DataBinding) else DataBinding.model_validate(binding)
    values = {**bound.parameters(), **(parameters or {})}
    for transform in bound.transforms:
        if transform.op == "filter":
            table = table.filter_equals(transform.column, transform.equals)
        elif transform.op == "normalize":
            table = table.normalize(transform.column, transform.by)
        elif transform.op == "sort":
            table = table.sort_by(transform.column, transform.descending)
        elif transform.op == "scale":
            table = table.scale(transform.column, _setting(transform.by, values))
        elif transform.op == "smooth":
            table = table.smooth(transform.column, _setting(transform.window, values))
    enc = bound.encoding
    groups = table.group_by(enc.group) if enc.group else {None: table}
    series: list[Series] = []
    for label, sub in groups.items():
        if len(sub) == 0:
            continue
        series.append(
            Series(
                label=label,
                x=sub.numeric(enc.x),
                y=sub.numeric(enc.y),
                error=sub.numeric(enc.error) if enc.error else None,
            )
        )
    if not series:
        raise ValueError(f"{table.source}: no rows left after transforms {[t.model_dump() for t in bound.transforms]}")
    return series
