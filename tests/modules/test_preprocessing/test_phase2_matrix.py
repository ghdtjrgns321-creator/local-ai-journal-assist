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
    # 2026-07-29: __count 는 폐지. count = freq × 학습 행수 라 정보가 같은데 원값이라
    # 스케일이 폭주했다(실측 approved_by__count std 15,842 대 수치형 기준 1.0).
    assert calibration_matrix.filter(like="vendor_name__count").shape[1] == 0


def test_phase2_matrix_flags_numeric_missing_as_information():
    """수치형 결측도 정보다 — 0 으로 채우면 "없음"과 "0"이 같아진다.

    2026-07-29: 불리언에만 결측 표식을 세워 반쪽이었다. 새 PHASE2 파생 중
    `p2_days_approval_minus_posting`(승인 없으면 빔, 실측 72%)이 정확히 이 함정에
    걸렸다 — "승인 없음"과 "당일 승인(간격 0)"이 같은 0 이 된다.
    """
    df = pd.DataFrame(
        {
            "days_approval_minus_posting": pd.array([0, 3, None, None, 5], dtype="Int64"),
            "approver_limit_amount": [1e7, 5e7, None, None, 1e8],
            "days_posting_minus_document": [0, 1, 2, 0, 3],
        }
    )
    builder = _fit_builder(df)
    matrix = builder.transform(df)

    assert set(builder.numeric_missing_columns) == {
        "days_approval_minus_posting",
        "approver_limit_amount",
    }
    # 결측이 없는 칸에는 표식을 세우지 않는다 — 상수 0 칸이 늘 뿐이다.
    assert "days_posting_minus_document__missing" not in matrix.columns

    flag = matrix["days_approval_minus_posting__missing"]
    assert list(flag) == [0.0, 0.0, 1.0, 1.0, 0.0]


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
    assert "vendor_name__count" not in groups
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

    assert (
        builder.to_metadata()["numeric_transform_policies"] == before["numeric_transform_policies"]
    )
    assert "line_count__standard_scaled" in calibration_matrix.columns
    assert "line_count__robust_scaled" not in calibration_matrix.columns
