from __future__ import annotations

import pandas as pd

from src.eda.profiler import profile_dataframe
from src.preprocessing.phase2_matrix import Phase2AutoencoderMatrixBuilder
from src.preprocessing.phase2_plan import build_phase2_preprocessing_plan


def _fit_builder(df: pd.DataFrame) -> Phase2AutoencoderMatrixBuilder:
    plan = build_phase2_preprocessing_plan(profile_dataframe(df), high_card_threshold=3)
    return Phase2AutoencoderMatrixBuilder(plan).fit(df)


def test_phase2_matrix_transform_handles_unseen_category_without_state_change():
    train_df = pd.DataFrame(
        {
            "document_id": ["d1", "d2", "d3", "d4"],
            "amount": [100.0, -50.0, 0.0, 25.0],
            "vendor_name": ["A", "A", "B", "C"],
            "cost_center": ["CC1", "CC1", "CC2", "CC2"],
        }
    )
    calibration_df = pd.DataFrame(
        {
            "document_id": ["d5", "d6"],
            "amount": [10.0, -20.0],
            "vendor_name": ["D", "A"],
            "cost_center": ["CC3", "CC1"],
        }
    )
    builder = _fit_builder(train_df)
    before = builder.to_metadata()

    train_matrix = builder.transform(train_df)
    calibration_matrix = builder.transform(calibration_df)

    assert list(calibration_matrix.columns) == list(train_matrix.columns)
    assert builder.to_metadata() == before
    assert builder.to_metadata()["schema_hash"] == before["schema_hash"]
    assert calibration_matrix.filter(like="vendor_name__freq").shape[1] == 1
    assert calibration_matrix.filter(like="vendor_name__count").shape[1] == 1


def test_phase2_matrix_drops_sparse_raw_and_keeps_has_indicator():
    df = pd.DataFrame(
        {
            "document_id": ["d1", "d2", "d3", "d4", "d5"],
            "amount": [100.0, 200.0, -50.0, 0.0, 80.0],
            "cost_center": [None, None, None, None, "CC1"],
            "source": ["manual", "manual", "batch", "manual", "batch"],
        }
    )
    builder = _fit_builder(df)
    matrix = builder.transform(df)

    assert "has_cost_center" in matrix.columns
    assert matrix["has_cost_center"].tolist() == [0.0, 0.0, 0.0, 0.0, 1.0]
    assert not any(column.startswith("cost_center__") for column in matrix.columns)
    assert "cost_center" in builder.to_metadata()["sparse_dropped_columns"]
    assert builder.to_metadata()["output_feature_groups"]["has_cost_center"] == "indicator"


def test_phase2_matrix_signed_log_amount_preserves_sign():
    df = pd.DataFrame(
        {
            "document_id": ["d1", "d2", "d3"],
            "amount": [-99.0, 0.0, 99.0],
            "source": ["manual", "batch", "manual"],
        }
    )
    builder = _fit_builder(df)
    matrix = builder.transform(df)

    assert matrix["amount__signed_log"].iloc[0] < 0
    assert matrix["amount__signed_log"].iloc[1] == 0
    assert matrix["amount__signed_log"].iloc[2] > 0


def test_phase2_matrix_metadata_records_output_feature_groups():
    df = pd.DataFrame(
        {
            "document_id": ["d1", "d2", "d3", "d4"],
            "amount": [100.0, -50.0, 0.0, 25.0],
            "vendor_name": ["A", "A", "B", "C"],
            "approved": [True, False, True, False],
            "tax_amount": [None, None, None, 7.0],
        }
    )

    builder = _fit_builder(df)
    metadata = builder.to_metadata()
    groups = metadata["output_feature_groups"]

    assert groups["amount__signed_log"] == "amount"
    assert groups["vendor_name__freq"] == "categorical"
    assert groups["vendor_name__count"] == "categorical"
    assert groups["approved"] == "boolean"
    assert set(groups) == set(metadata["feature_names"])


def test_phase2_matrix_selects_robust_policy_for_skewed_numeric():
    df = pd.DataFrame(
        {
            "document_id": [f"d{i}" for i in range(20)],
            "amount": [float(i) for i in range(20)],
            "unit_count": [1.0] * 18 + [1000.0, 2000.0],
        }
    )

    builder = _fit_builder(df)
    metadata = builder.to_metadata()

    assert metadata["numeric_transform_policies"]["unit_count"]["policy"] == "robust"
    assert "unit_count__robust_scaled" in metadata["feature_names"]


def test_phase2_matrix_selects_standard_policy_for_regular_numeric():
    df = pd.DataFrame(
        {
            "document_id": [f"d{i}" for i in range(20)],
            "amount": [float(i) for i in range(20)],
            "line_count": [float((i % 5) + 1) for i in range(20)],
        }
    )

    builder = _fit_builder(df)
    metadata = builder.to_metadata()

    assert metadata["numeric_transform_policies"]["line_count"]["policy"] == "standard"
    assert "line_count__standard_scaled" in metadata["feature_names"]


def test_phase2_matrix_reuses_train_time_numeric_policy_on_calibration():
    train_df = pd.DataFrame(
        {
            "document_id": [f"d{i}" for i in range(20)],
            "amount": [float(i) for i in range(20)],
            "line_count": [float((i % 5) + 1) for i in range(20)],
        }
    )
    calibration_df = pd.DataFrame(
        {
            "document_id": [f"c{i}" for i in range(10)],
            "amount": [float(i) for i in range(10)],
            "line_count": [1.0] * 9 + [5000.0],
        }
    )
    builder = _fit_builder(train_df)
    before = builder.to_metadata()

    calibration_matrix = builder.transform(calibration_df)

    assert builder.to_metadata()["numeric_transform_policies"] == before[
        "numeric_transform_policies"
    ]
    assert "line_count__standard_scaled" in calibration_matrix.columns
    assert "line_count__robust_scaled" not in calibration_matrix.columns
