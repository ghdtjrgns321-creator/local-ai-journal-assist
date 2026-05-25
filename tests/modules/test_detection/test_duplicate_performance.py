from __future__ import annotations

import time

import numpy as np
import pandas as pd

from src.detection.duplicate_detector import DuplicateDetector


def _large_unique_duplicate_input(rows: int = 100_000) -> pd.DataFrame:
    row_ids = np.arange(rows, dtype=np.int64)
    return pd.DataFrame(
        {
            "gl_account": 10_000 + (row_ids % 50),
            "debit_amount": (row_ids * 10_000 + 100).astype(float),
            "credit_amount": np.zeros(rows, dtype=float),
            "posting_date": pd.Timestamp("2025-01-01")
            + pd.to_timedelta(row_ids % 365, unit="D"),
            "line_text": np.where(row_ids % 2 == 0, "standard purchase", "cash payment"),
        }
    )


def test_duplicate_detector_scores_100k_rows_under_one_second() -> None:
    df = _large_unique_duplicate_input()

    start = time.perf_counter()
    result = DuplicateDetector().detect(df)
    elapsed = time.perf_counter() - start

    assert elapsed < 1.0
    assert len(result.scores) == len(df)


def test_duplicate_detector_preserves_representative_subrule_hits() -> None:
    df = pd.DataFrame(
        {
            "gl_account": [1000, 1000, 2000, 2000, 3000, 3000, 3000, 4000, 4000],
            "debit_amount": [
                500.0,
                500.0,
                1_000_000.0,
                998_000.0,
                1_000.0,
                490.0,
                510.0,
                700.0,
                700.0,
            ],
            "credit_amount": [0.0] * 9,
            "posting_date": pd.to_datetime(
                [
                    "2025-03-01",
                    "2025-03-01",
                    "2025-04-01",
                    "2025-04-02",
                    "2025-06-01",
                    "2025-06-02",
                    "2025-06-03",
                    "2025-05-01",
                    "2025-05-04",
                ]
            ),
            "line_text": [
                "office supply",
                "office supply",
                "Samsung card payment",
                "Samsung card payment detail",
                "target invoice",
                "alpha",
                "omega",
                "rent",
                "rent",
            ],
        }
    )

    result = DuplicateDetector().detect(df)
    hits = {rule_id: int((result.details[rule_id] > 0).sum()) for rule_id in result.details}

    assert hits == {
        "L2-03a": 2,
        "L2-03b": 6,
        "L2-03c": 3,
        "L2-03d": 2,
    }
