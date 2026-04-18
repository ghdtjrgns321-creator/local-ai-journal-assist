from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.export.label_splitter import split_label_columns, split_label_csv


def test_split_label_columns_separates_body_and_document_labels():
    df = pd.DataFrame({
        "document_id": ["D1", "D1", "D2"],
        "line_number": [1, 2, 1],
        "amount": [100, 200, 300],
        "is_fraud": [True, True, False],
        "fraud_type": ["DuplicatePayment", "DuplicatePayment", None],
        "is_anomaly": [True, True, False],
        "anomaly_type": ["TimingAnomaly", "TimingAnomaly", None],
        "sod_violation": [False, False, True],
        "sod_conflict_type": [None, None, "preparer_approver"],
    })

    body_df, labels_df = split_label_columns(df)

    assert "is_fraud" not in body_df.columns
    assert "fraud_type" not in body_df.columns
    assert len(body_df) == 3

    assert list(labels_df.columns) == [
        "document_id",
        "is_fraud",
        "fraud_type",
        "is_anomaly",
        "anomaly_type",
        "sod_violation",
        "sod_conflict_type",
    ]
    assert len(labels_df) == 2
    d1 = labels_df.loc[labels_df["document_id"] == "D1"].iloc[0]
    assert bool(d1["is_fraud"]) is True
    assert d1["fraud_type"] == "DuplicatePayment"


def test_split_label_columns_raises_on_inconsistent_document_labels():
    df = pd.DataFrame({
        "document_id": ["D1", "D1"],
        "line_number": [1, 2],
        "is_fraud": [True, False],
    })

    with pytest.raises(ValueError, match="inconsistent label values"):
        split_label_columns(df)


def test_split_label_csv_writes_outputs():
    df = pd.DataFrame({
        "document_id": ["D1", "D1", "D2"],
        "amount": [10, 20, 30],
        "is_fraud": [False, False, True],
        "is_anomaly": [False, False, True],
    })
    calls: list[tuple[Path, list[str]]] = []

    original_read_csv = pd.read_csv
    original_to_csv = pd.DataFrame.to_csv

    def fake_read_csv(path, *args, **kwargs):
        assert Path(path) == Path("source.csv")
        return df.copy()

    def fake_to_csv(self, path, *args, **kwargs):
        calls.append((Path(path), list(self.columns)))
        return None

    pd.read_csv = fake_read_csv
    pd.DataFrame.to_csv = fake_to_csv
    try:
        split_label_csv(
            "source.csv",
            body_output_csv="body.csv",
            labels_output_csv="labels.csv",
        )
    finally:
        pd.read_csv = original_read_csv
        pd.DataFrame.to_csv = original_to_csv

    assert calls[0] == (Path("body.csv"), ["document_id", "amount"])
    assert calls[1] == (Path("labels.csv"), ["document_id", "is_fraud", "is_anomaly"])
