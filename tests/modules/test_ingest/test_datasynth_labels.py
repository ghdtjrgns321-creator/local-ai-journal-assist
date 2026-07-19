from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.ingest.datasynth_labels import (
    apply_datasynth_label_mode,
    load_document_labels,
    set_source_path,
)


def test_hidden_mode_drops_embedded_labels():
    df = pd.DataFrame({
        "document_id": ["D1"],
        "amount": [100],
        "is_fraud": [True],
        "fraud_type": ["DuplicatePayment"],
    })

    result = apply_datasynth_label_mode(df, mode="hidden")

    assert list(result.columns) == ["document_id", "amount"]


def test_visible_mode_attaches_sidecar_labels(monkeypatch):
    body_df = pd.DataFrame({
        "document_id": ["D1", "D1", "D2"],
        "amount": [10, 20, 30],
    })
    labels_df = pd.DataFrame({
        "document_id": ["D1", "D2"],
        "is_fraud": [True, False],
        "is_anomaly": [True, False],
    })

    monkeypatch.setattr(
        "src.ingest.datasynth_labels.find_sidecar_label_csv",
        lambda _: Path("labels/document_labels.csv"),
    )
    monkeypatch.setattr("pandas.read_csv", lambda *args, **kwargs: labels_df.copy())

    result = apply_datasynth_label_mode(
        set_source_path(body_df, "data/journal/primary/datasynth/journal_entries_body.csv"),
        mode="visible",
    )

    assert "is_fraud" in result.columns
    assert result["is_fraud"].tolist() == [True, True, False]


def test_apply_label_mode_refreshes_validated_metadata(monkeypatch):
    body_df = pd.DataFrame({
        "document_id": ["D1"],
        "amount": [10],
    })
    calls: list[str] = []

    monkeypatch.setattr(
        "src.ingest.datasynth_metadata.ensure_validated_metadata_json",
        lambda path: calls.append(str(path)) or None,
    )

    result = apply_datasynth_label_mode(
        set_source_path(body_df, "data/journal/primary/datasynth/journal_entries_2024.csv"),
        mode="hidden",
    )

    assert result.columns.tolist() == ["document_id", "amount"]
    assert calls and calls[0].endswith("journal_entries_2024.csv")


def test_create_labels_path_can_recover_sidecar_ground_truth(monkeypatch):
    from src.preprocessing.label_strategy import create_labels

    body_df = pd.DataFrame({
        "document_id": ["D1", "D1", "D2"],
        "amount": [10, 20, 30],
    })
    labels_df = pd.DataFrame({
        "document_id": ["D1", "D2"],
        "is_fraud": [True, False],
        "is_anomaly": [False, True],
    })

    monkeypatch.setattr(
        "src.ingest.datasynth_labels.find_sidecar_label_csv",
        lambda _: Path("labels/document_labels.csv"),
    )
    monkeypatch.setattr("pandas.read_csv", lambda *args, **kwargs: labels_df.copy())

    result = create_labels(
        set_source_path(body_df, "data/journal/primary/datasynth/journal_entries_body.csv"),
        strategy="datasynth",
    )

    assert result.label_source == "ground_truth"
    assert result.y.tolist() == [1, 1, 1]


def test_load_document_labels_falls_back_to_embedded_source(monkeypatch):
    source_df = pd.DataFrame({
        "document_id": ["D1", "D1", "D2"],
        "amount": [10, 20, 30],
        "is_fraud": [True, True, False],
        "is_anomaly": [False, False, True],
    })

    monkeypatch.setattr(
        "src.ingest.datasynth_labels.ensure_sidecar_label_csv",
        lambda _: None,
    )
    monkeypatch.setattr("pandas.read_csv", lambda *args, **kwargs: source_df.copy())

    labels_df = load_document_labels("journal_entries_2022.csv")

    assert labels_df is not None
    assert list(labels_df.columns) == ["document_id", "is_fraud", "is_anomaly"]
    assert labels_df["document_id"].tolist() == ["D1", "D2"]
