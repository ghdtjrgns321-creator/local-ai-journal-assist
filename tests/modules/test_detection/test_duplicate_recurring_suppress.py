"""L2-03 recurring duplicate suppress tests."""

from __future__ import annotations

import pandas as pd

from config.settings import AuditSettings
from src.detection.duplicate_detector import DuplicateDetector


def _base_settings() -> AuditSettings:
    return AuditSettings(
        duplicate_pair_artifact_max_rows=1000,
        duplicate_max_group_size=1000,
        duplicate_pair_artifact_top_n=1000,
        duplicate_pair_artifact_candidate_supplement_max_docs=0,
    )


def _detect(df: pd.DataFrame) -> dict:
    result = DuplicateDetector(_base_settings()).detect(df)
    return result.metadata["pair_artifact"]


def _rows(
    *,
    dates: list[str],
    references: list[str],
    source: str = "recurring",
    business_process: str = "P2P",
    line_text: str = "monthly rent",
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "document_id": [f"D-{i:03d}" for i in range(len(dates))],
            "posting_date": pd.to_datetime(dates),
            "document_date": pd.to_datetime(dates),
            "reference": references,
            "document_number": [f"JE-{i:03d}" for i in range(len(dates))],
            "trading_partner": ["V-RENT"] * len(dates),
            "gl_account": ["6100"] * len(dates),
            "debit_amount": [1_000_000.0] * len(dates),
            "credit_amount": [0.0] * len(dates),
            "line_text": [line_text] * len(dates),
            "business_process": [business_process] * len(dates),
            "source": [source] * len(dates),
        }
    )


def test_regular_monthly_different_reference_series_is_suppressed() -> None:
    artifact = _detect(
        _rows(
            dates=["2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30"],
            references=["INV-001", "INV-002", "INV-003", "INV-004"],
        )
    )

    assert artifact["total_candidate_pairs"] == 0
    assert artifact["coverage"]["recurring_suppressed_pairs"] > 0


def test_same_reference_pair_survives_recurring_suppress() -> None:
    artifact = _detect(
        _rows(
            dates=["2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30"],
            references=["INV-001", "INV-001", "INV-003", "INV-004"],
        )
    )

    assert artifact["total_candidate_pairs"] > 0
    assert any(pair["features"]["same_reference"] for pair in artifact["top_pairs"])


def test_manual_off_cycle_near_extra_payment_breaking_periodicity_survives() -> None:
    artifact = _detect(
        _rows(
            dates=["2026-01-31", "2026-02-28", "2026-03-31", "2026-04-05"],
            references=["INV-001", "INV-002", "INV-003", "INV-004"],
            source="manual",
            business_process="P2P",
        )
    )

    assert artifact["total_candidate_pairs"] > 0
    assert any(
        pair["features"].get("recurring_suppress_decision") == "near_extra_kept"
        for pair in artifact["top_pairs"]
    )


def test_automated_near_extra_payment_breaking_periodicity_is_suppressed() -> None:
    artifact = _detect(
        _rows(
            dates=["2026-01-31", "2026-02-28", "2026-03-31", "2026-04-05"],
            references=["INV-001", "INV-002", "INV-003", "INV-004"],
            source="automated",
            business_process="P2P",
        )
    )

    assert artifact["total_candidate_pairs"] == 0
    assert artifact["coverage"]["recurring_near_extra_context_suppressed_pairs"] > 0


def test_recurring_source_near_extra_payment_breaking_periodicity_is_suppressed() -> None:
    artifact = _detect(
        _rows(
            dates=["2026-01-31", "2026-02-28", "2026-03-31", "2026-04-05"],
            references=["INV-001", "INV-002", "INV-003", "INV-004"],
            source="recurring",
            business_process="P2P",
        )
    )

    assert artifact["total_candidate_pairs"] == 0
    assert artifact["coverage"]["recurring_near_extra_context_suppressed_pairs"] > 0


def test_closing_or_accrual_near_extra_payment_breaking_periodicity_is_suppressed() -> None:
    artifact = _detect(
        _rows(
            dates=["2026-01-31", "2026-02-28", "2026-03-31", "2026-04-05"],
            references=["INV-001", "INV-002", "INV-003", "INV-004"],
            source="manual",
            business_process="R2R",
            line_text="manual accrual closing entry",
        )
    )

    assert artifact["total_candidate_pairs"] == 0
    assert artifact["coverage"]["recurring_near_extra_context_suppressed_pairs"] > 0


def test_ambiguous_different_reference_pair_is_not_retained() -> None:
    artifact = _detect(
        _rows(
            dates=["2026-01-31", "2026-03-17"],
            references=["INV-001", "INV-002"],
            source="manual",
        )
    )

    assert artifact["total_candidate_pairs"] == 0
    assert artifact["coverage"]["recurring_ambiguous_dropped_pairs"] > 0
