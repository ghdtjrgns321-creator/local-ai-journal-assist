from __future__ import annotations

import pandas as pd

from src.detection.anomaly_rules_simple import c01_period_end_large
from src.detection.boolean_utils import bool_column, coerce_bool_series, coerce_bool_value
from src.detection.graph_rules import _filter_edges


def test_coerce_bool_series_handles_string_false_values() -> None:
    values = pd.Series(["False", "false", "0", "", "true", "TRUE", "1", True, False, None])

    result = coerce_bool_series(values)

    assert result.tolist() == [False, False, False, False, True, True, True, True, False, False]


def test_coerce_bool_value_handles_string_false_values() -> None:
    assert coerce_bool_value("False") is False
    assert coerce_bool_value("true") is True
    assert coerce_bool_value("0") is False
    assert coerce_bool_value("1") is True


def test_l304_period_end_does_not_treat_false_string_as_true() -> None:
    df = pd.DataFrame(
        {
            "is_period_end": ["False", "true", False],
            "debit_amount": [100.0, 100.0, 100.0],
            "credit_amount": [0.0, 0.0, 0.0],
            "gl_account": ["4000", "4000", "4000"],
        }
    )

    result = c01_period_end_large(df)

    assert result.tolist() == [False, True, False]


def test_graph_filter_edges_does_not_treat_false_string_as_ic() -> None:
    df = pd.DataFrame(
        {
            "company_code": ["C001", "C001", "C002"],
            "trading_partner": ["C002", "C002", "C001"],
            "is_intercompany": ["False", "true", False],
            "debit_amount": [1000.0, 2000.0, 3000.0],
            "credit_amount": [0.0, 0.0, 0.0],
        }
    )

    filtered, _, _ = _filter_edges(df, min_amount=1.0, max_edges=10)

    assert filtered.index.tolist() == [1]
    assert bool_column(df, "is_intercompany").tolist() == [False, True, False]
