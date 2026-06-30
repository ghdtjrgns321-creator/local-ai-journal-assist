from __future__ import annotations

import pandas as pd

from src.detection.anomaly_rules_simple import c01_period_end_large
from src.detection.boolean_utils import coerce_bool_series, coerce_bool_value


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
