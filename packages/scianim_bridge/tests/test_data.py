"""Pure-Python bridge tests: data binding and axis ranges. Run inside the family environment."""

from __future__ import annotations

from pathlib import Path

import pytest

from scianim_bridge.data import DataTable, apply_binding, load_csv

REPO = Path(__file__).resolve().parents[3]
CSV = REPO / "examples" / "divisive_normalization" / "data" / "synthetic_responses.csv"


def test_load_csv_and_columns() -> None:
    table = load_csv(CSV)
    assert table.columns[:2] == ("excitation_E", "pool_P")
    assert len(table) == 22
    assert table.numeric("sigma") == [1.0] * 22


def test_filter_group_and_series() -> None:
    table = load_csv(CSV)
    series = apply_binding(
        table,
        {
            "source": "responses",
            "encoding": {"x": "excitation_E", "y": "response_r", "group": "condition"},
            "transforms": [{"op": "filter", "column": "condition", "equals": "low_pool"}],
        },
    )
    assert [s.label for s in series] == ["low_pool"]
    assert series[0].x[:3] == [0.0, 1.0, 2.0]
    assert series[0].y[1] == pytest.approx(0.5)


def test_groups_without_filter() -> None:
    series = apply_binding(
        load_csv(CSV),
        {"source": "responses", "encoding": {"x": "excitation_E", "y": "response_r", "group": "condition"}},
    )
    assert {s.label for s in series} == {"low_pool", "high_pool"}


def test_normalize_and_sort() -> None:
    table = DataTable(("a", "b"), ({"a": "3", "b": "x"}, {"a": "1", "b": "y"}), "t")
    normalized = table.normalize("a", by="max")
    assert normalized.numeric("a") == [1.0, pytest.approx(1 / 3)]
    assert table.sort_by("a").column("b") == ["y", "x"]


def test_unknown_column_is_named() -> None:
    with pytest.raises(KeyError, match="no column 'zzz'"):
        load_csv(CSV).numeric("zzz")


def test_empty_result_after_filter_is_an_error() -> None:
    with pytest.raises(ValueError, match="no rows left"):
        apply_binding(
            load_csv(CSV),
            {
                "source": "responses",
                "encoding": {"x": "excitation_E", "y": "response_r"},
                "transforms": [{"op": "filter", "column": "condition", "equals": "nope"}],
            },
        )


def test_nice_range() -> None:
    from scianim_bridge.components.plots import nice_range

    low, high, step = nice_range([0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0])
    assert low == 0.0 and step == 1.0 and high >= 5.0
    low, high, step = nice_range([0.2, 0.4, 0.6])
    assert low == 0.0 and high > 0.6
