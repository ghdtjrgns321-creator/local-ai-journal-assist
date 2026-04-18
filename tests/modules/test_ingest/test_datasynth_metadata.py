from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.ingest.datasynth_metadata import (
    default_validated_metadata_path,
    reconcile_reported_metadata,
    summarize_observed_metadata,
)


def test_summarize_observed_metadata_counts_observable_issues() -> None:
    df = pd.DataFrame(
        {
            "document_id": ["D1", "D1", "D2", "D2", "D3", "D3"],
            "company_code": ["C1", "C1", "C1", None, "C1", "C1"],
            "posting_date": pd.to_datetime(
                [
                    "2024-01-01",
                    "2024-01-01",
                    "2024-01-02",
                    "2024-01-02",
                    "2024-01-03",
                    "2024-01-03",
                ]
            ),
            "document_type": ["SA", "SA", "KR", "KR", "SA", "SA"],
            "gl_account": [1000, 2000, 3000, 3000, 1000, 2000],
            "line_number": [1, 2, 1, 1, 1, 2],
            "debit_amount": [100, 0, 50, 50, 70, 0],
            "credit_amount": [0, 100, 0, 0, 0, 60],
            "is_anomaly": [False, False, True, True, False, False],
        }
    )

    observed = summarize_observed_metadata(df)

    assert observed.generation_statistics["total_entries"] == 3
    assert observed.generation_statistics["total_line_items"] == 6
    assert observed.generation_statistics["anomalies_injected"] == 1
    assert observed.data_quality_stats["missing_values"]["total_missing"] == 1
    assert observed.data_quality_stats["duplicates"]["total_duplicates"] == 1
    assert observed.data_quality_stats["records_with_issues"] == 4
    assert observed.issue_breakdown == {
        "required_field_missing": 1,
        "duplicate_document_line_key": 2,
        "unbalanced_document": 4,
    }


def test_reconcile_reported_metadata_marks_critical_and_warning_mismatches() -> None:
    df = pd.DataFrame(
        {
            "document_id": ["D1", "D1"],
            "company_code": ["C1", "C1"],
            "posting_date": pd.to_datetime(["2024-01-01", "2024-01-01"]),
            "document_type": ["SA", "SA"],
            "gl_account": [1000, 2000],
            "line_number": [1, 2],
            "debit_amount": [100, 0],
            "credit_amount": [0, 100],
        }
    )
    observed = summarize_observed_metadata(df)

    reconciliation = reconcile_reported_metadata(
        observed=observed,
        generation_statistics={
            "total_entries": 0,
            "total_line_items": 2,
            "anomalies_injected": None,
        },
        data_quality_stats={
            "missing_values": {"total_records": 0, "total_missing": 99},
            "duplicates": {"total_processed": 2, "total_duplicates": 99},
            "total_records": 0,
            "records_with_issues": 99,
        },
    )

    assert reconciliation.status == "fail"
    assert "total_entries: reported=0, observed=1" in reconciliation.critical_mismatches
    assert "total_records: reported=0, observed=2" in reconciliation.critical_mismatches
    assert (
        "missing_values.total_missing: reported=99, observed=0"
        in reconciliation.warning_mismatches
    )


def test_default_validated_metadata_path_uses_year_specific_name() -> None:
    source = Path("data/journal/primary/datasynth/journal_entries_2024.csv")
    output = default_validated_metadata_path(source)

    assert output.name == "validated_metadata_2024.json"
    assert output.parent == source.parent
