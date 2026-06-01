"""`build_unsupervised_cases` 의 case 생성 계약 검증.

Why: VAE / ML02 unsupervised detector 의 anomaly score + top-feature 를
UnsupervisedCase tuple 로 변환하는 contract 를 invariant #11~17 기준으로 잠근다.
ecdf_gate, top_features 추출 규칙, evidence_signature 의 정체성 (model+schema)
세 가지가 핵심.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.detection.base import DetectionResult
from src.models.phase2_case import UnsupervisedCase
from src.services.phase2_ref_canonical import canonicalize_ref_key
from src.services.phase2_unsupervised_case_builder import build_unsupervised_cases

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_df(n: int = 8) -> pd.DataFrame:
    """N row GL frame — document_id / line_number / company_code 포함."""
    return pd.DataFrame(
        {
            "document_id": [f"DOC{i:03d}" for i in range(n)],
            "line_number": list(range(1, n + 1)),
            "company_code": ["C001"] * n,
            "amount": [1000.0 * (i + 1) for i in range(n)],
        }
    )


def _make_detection_result(
    *,
    scores: pd.Series,
    details: pd.DataFrame,
) -> DetectionResult:
    """ML02_top_feature_* 컬럼을 가진 가짜 unsupervised DetectionResult."""
    return DetectionResult(
        track_name="ml_unsupervised",
        flagged_indices=[int(label) for label, score in scores.items() if score > 0],  # type: ignore[arg-type]
        scores=scores,
        rule_flags=[],
        details=details,
        metadata={},
        warnings=[],
    )


def _make_details_for(
    df: pd.DataFrame,
    *,
    feature_rows: dict[int, list[tuple[str, float]]] | None = None,
) -> pd.DataFrame:
    """df.index 와 동일 인덱스의 details 생성.

    feature_rows = {idx: [(feature_name, contrib), ...]} — None/빈 entry 는
    NaN feature 로 채워 skip 분기를 자극한다.
    """
    rows = []
    for idx in df.index:
        row: dict[str, object] = {}
        triples = (feature_rows or {}).get(idx, [])
        for k in range(1, 4):
            if k <= len(triples):
                fname, contrib = triples[k - 1]
                row[f"ML02_top_feature_{k}"] = fname
                row[f"ML02_top_feature_{k}_contrib"] = contrib
            else:
                row[f"ML02_top_feature_{k}"] = np.nan
                row[f"ML02_top_feature_{k}_contrib"] = np.nan
        rows.append(row)
    return pd.DataFrame(rows, index=df.index)


# ---------------------------------------------------------------------------
# 1. graceful empty
# ---------------------------------------------------------------------------


def test_empty_details_returns_empty_tuple():
    df = _make_df(5)
    # scores 는 채워져 있지만 details 가 비어있는 경우 — 빈 tuple graceful.
    scores = pd.Series([0.1, 0.2, 0.3, 0.4, 0.5], index=df.index)
    result = _make_detection_result(scores=scores, details=pd.DataFrame())
    cases = build_unsupervised_cases(
        batch_id="batch001",
        detection_result=result,
        df=df,
        model_id="vae_v1",
        schema_hash="schema_abc",
    )
    assert cases == ()


def test_empty_scores_returns_empty_tuple():
    df = _make_df(5)
    details = _make_details_for(df)
    result = _make_detection_result(
        scores=pd.Series(dtype=float),
        details=details,
    )
    cases = build_unsupervised_cases(
        batch_id="batch001",
        detection_result=result,
        df=df,
        model_id="vae_v1",
        schema_hash="schema_abc",
    )
    assert cases == ()


# ---------------------------------------------------------------------------
# 2. ECDF gate
# ---------------------------------------------------------------------------


def test_row_below_ecdf_gate_excluded():
    df = _make_df(10)
    # scores 분포 — 가장 낮은 score row 는 ecdf < 0.95 라 제외되어야 한다.
    scores = pd.Series(
        [0.01, 0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.80, 0.99],
        index=df.index,
    )
    details = _make_details_for(
        df,
        feature_rows={i: [("amount", 0.7)] for i in df.index},
    )
    result = _make_detection_result(scores=scores, details=details)
    cases = build_unsupervised_cases(
        batch_id="batch001",
        detection_result=result,
        df=df,
        model_id="vae_v1",
        schema_hash="schema_abc",
        ecdf_gate=0.95,
    )
    # ecdf >= 0.95 (rank pct=True, method="max") 통과는 단 한 row (idx=9).
    assert len(cases) == 1
    assert cases[0].row_refs[0].index_label == "i:9"


def test_ecdf_q95_gate_creates_only_top_quantile_rows():
    """ECDF q95 gate 는 truth 가 아니라 score distribution 상위 row 만 case 화한다."""
    df = _make_df(20)
    scores = pd.Series(np.linspace(0.01, 1.0, num=20), index=df.index)
    details = _make_details_for(
        df,
        feature_rows={i: [("amount", 0.5)] for i in df.index},
    )
    result = _make_detection_result(scores=scores, details=details)

    cases = build_unsupervised_cases(
        batch_id="batch001",
        detection_result=result,
        df=df,
        model_id="vae_v1",
        schema_hash="schema_abc",
        ecdf_gate=0.95,
    )

    assert [case.row_refs[0].index_label for case in cases] == ["i:19", "i:18"]
    assert all(case.case_generation_reason["gate"] == "unsupervised_ecdf" for case in cases)
    assert all(case.family_ecdf >= 0.95 for case in cases)


def test_default_ordering_uses_soft_document_review_priority_without_changing_case_count():
    """기본 표시 순서는 row score 단독이 아니라 document review priority 를 따른다."""
    df = pd.DataFrame(
        {
            "document_id": ["DOC_REPEAT", "DOC_REPEAT", "DOC_FOCUSED"],
            "line_number": [1, 2, 3],
            "company_code": ["C001", "C001", "C001"],
            "amount": [1_000.0, 900.0, 10_000.0],
            "period_end_proximity_days": [30, 30, 0],
        }
    )
    scores = pd.Series([0.99, 0.98, 0.96], index=df.index)
    details = _make_details_for(
        df,
        feature_rows={i: [("amount", 0.5)] for i in df.index},
    )
    result = _make_detection_result(scores=scores, details=details)

    cases = build_unsupervised_cases(
        batch_id="batch001",
        detection_result=result,
        df=df,
        model_id="vae_v1",
        schema_hash="schema_abc",
        ecdf_gate=0.0,
    )

    assert len(cases) == 3
    assert cases[0].row_refs[0].document_id == "DOC_FOCUSED"
    assert [case.row_refs[0].document_id for case in cases[1:]] == [
        "DOC_REPEAT",
        "DOC_REPEAT",
    ]


def test_row_at_ecdf_gate_included():
    df = _make_df(4)
    # 모든 양수 score 가 동일 → 모두 rank pct=1.0 → 모두 통과.
    scores = pd.Series([0.5, 0.5, 0.5, 0.5], index=df.index)
    details = _make_details_for(
        df,
        feature_rows={i: [("amount", 0.5)] for i in df.index},
    )
    result = _make_detection_result(scores=scores, details=details)
    cases = build_unsupervised_cases(
        batch_id="batch001",
        detection_result=result,
        df=df,
        model_id="vae_v1",
        schema_hash="schema_abc",
        ecdf_gate=0.95,
    )
    assert len(cases) == 4
    for case in cases:
        assert case.family_ecdf >= 0.95


# ---------------------------------------------------------------------------
# 3. top_features 추출
# ---------------------------------------------------------------------------


def test_top_features_extracted_from_ml02_columns():
    df = _make_df(2)
    scores = pd.Series([0.9, 0.95], index=df.index)
    # row 1 (idx=1) 통과 — 3 개 feature 채움.
    details = _make_details_for(
        df,
        feature_rows={
            0: [("amount", 0.1)],
            1: [("amount", 0.7), ("counterparty_xxx", 0.2), ("post_hour", 0.05)],
        },
    )
    result = _make_detection_result(scores=scores, details=details)
    cases = build_unsupervised_cases(
        batch_id="batch001",
        detection_result=result,
        df=df,
        model_id="vae_v1",
        schema_hash="schema_abc",
        ecdf_gate=0.5,
    )
    # ecdf_gate=0.5 — 모두 통과 (양수 2 개, pct rank min=0.5).
    assert len(cases) >= 1
    top_features_by_label = {c.row_refs[0].index_label: c.top_features for c in cases}
    assert isinstance(top_features_by_label["i:1"], tuple)
    assert len(top_features_by_label["i:1"]) == 3
    # 첫 feature dict 의 필수 키 확인.
    first = top_features_by_label["i:1"][0]
    assert first["feature_id"] == "amount"
    assert first["contrib"] == 0.7
    assert "tag" in first
    assert "label_ko" in first


def test_production_ml02_top_feature_columns_flow_into_case_payload():
    """production detector details 의 ML02_top_feature_* 가 evidence payload 로 보존된다."""
    df = _make_df(3)
    scores = pd.Series([0.10, 0.20, 0.99], index=df.index)
    details = _make_details_for(
        df,
        feature_rows={
            2: [("amount_tail", 0.8), ("period_end_proximity", 0.4)],
        },
    )
    result = _make_detection_result(scores=scores, details=details)

    cases = build_unsupervised_cases(
        batch_id="batch001",
        detection_result=result,
        df=df,
        model_id="vae_v1",
        schema_hash="schema_abc",
        ecdf_gate=0.95,
    )

    assert len(cases) == 1
    assert cases[0].row_refs[0].index_label == "i:2"
    assert [feature["feature_id"] for feature in cases[0].top_features] == [
        "amount_tail",
        "period_end_proximity",
    ]


def test_top_features_skips_nan_or_empty_feature_name():
    df = _make_df(2)
    scores = pd.Series([0.6, 0.7], index=df.index)
    # 두 row 모두 통과(ecdf_gate=0.5), idx=1 은 feature_1 만 채우고 나머지는 NaN.
    details = _make_details_for(
        df,
        feature_rows={
            0: [("amount", 0.5)],
            1: [("amount", 0.6)],  # 2/3 슬롯은 NaN
        },
    )
    # 추가로 빈 문자열을 명시적으로 한 슬롯에 넣어 skip 동작 확인.
    # Why: float64 컬럼에 빈 문자열을 직접 대입하면 pandas FutureWarning 이 발생하므로
    # 해당 컬럼을 object 로 명시적으로 캐스팅한 뒤 대입한다.
    details["ML02_top_feature_2"] = details["ML02_top_feature_2"].astype(object)
    details.loc[1, "ML02_top_feature_2"] = ""
    details.loc[1, "ML02_top_feature_2_contrib"] = 0.0
    result = _make_detection_result(scores=scores, details=details)
    cases = build_unsupervised_cases(
        batch_id="batch001",
        detection_result=result,
        df=df,
        model_id="vae_v1",
        schema_hash="schema_abc",
        ecdf_gate=0.5,
    )
    top_by_label = {c.row_refs[0].index_label: c.top_features for c in cases}
    # idx=1 → canonical "i:1". 빈 문자열·NaN slot 제외하고 1 개만 남아야 한다.
    assert len(top_by_label["i:1"]) == 1
    assert top_by_label["i:1"][0]["feature_id"] == "amount"


def test_top_features_includes_resolve_tag_label_ko():
    df = _make_df(1)
    scores = pd.Series([0.99], index=df.index)
    details = _make_details_for(
        df,
        feature_rows={0: [("amount", 0.8)]},
    )
    result = _make_detection_result(scores=scores, details=details)
    cases = build_unsupervised_cases(
        batch_id="batch001",
        detection_result=result,
        df=df,
        model_id="vae_v1",
        schema_hash="schema_abc",
        ecdf_gate=0.5,
    )
    assert len(cases) == 1
    top = cases[0].top_features
    assert len(top) == 1
    # resolve_tag 가 호출되어 label_ko 가 비어있지 않음.
    assert isinstance(top[0]["label_ko"], str)
    assert top[0]["label_ko"] != ""
    assert isinstance(top[0]["tag"], str)
    assert top[0]["tag"] != ""


# ---------------------------------------------------------------------------
# 4. case_id / evidence_signature 계약
# ---------------------------------------------------------------------------


def test_case_id_includes_model_and_schema_in_signature():
    """evidence_signature 가 model_id 와 schema_hash 변경에 반응한다."""
    df = _make_df(1)
    scores = pd.Series([0.99], index=df.index)
    details = _make_details_for(df, feature_rows={0: [("amount", 0.8)]})
    result = _make_detection_result(scores=scores, details=details)

    cases_a = build_unsupervised_cases(
        batch_id="batch001",
        detection_result=result,
        df=df,
        model_id="vae_v1",
        schema_hash="schema_abc",
        ecdf_gate=0.5,
    )
    cases_b = build_unsupervised_cases(
        batch_id="batch001",
        detection_result=result,
        df=df,
        model_id="vae_v2",
        schema_hash="schema_abc",
        ecdf_gate=0.5,
    )
    cases_c = build_unsupervised_cases(
        batch_id="batch001",
        detection_result=result,
        df=df,
        model_id="vae_v1",
        schema_hash="schema_xyz",
        ecdf_gate=0.5,
    )
    assert cases_a[0].phase2_case_id != cases_b[0].phase2_case_id
    assert cases_a[0].phase2_case_id != cases_c[0].phase2_case_id
    # ID format 확인.
    assert cases_a[0].phase2_case_id.startswith("p2_unsupervised_row_")


def test_case_id_uses_canonicalized_row_label():
    """case_id 의 canonical_refs 는 canonicalize_ref_key 결과여야 한다.

    빌더 내부에서 raw 라벨이 그대로 흘러가면 make_phase2_case_id 가 ValueError
    를 던지므로, 정상 동작이 곧 canonicalize 통과의 증거.
    """
    df = _make_df(1)
    scores = pd.Series([0.99], index=df.index)
    details = _make_details_for(df, feature_rows={0: [("amount", 0.8)]})
    result = _make_detection_result(scores=scores, details=details)
    cases = build_unsupervised_cases(
        batch_id="batch001",
        detection_result=result,
        df=df,
        model_id="vae_v1",
        schema_hash="schema_abc",
        ecdf_gate=0.5,
    )
    # int label 0 → "i:0" canonical prefix.
    expected_ref = canonicalize_ref_key(0)
    assert expected_ref == "i:0"
    # 결과 case 가 정상 생성된 것 자체가 canonical 통과의 증거.
    assert len(cases) == 1
    assert isinstance(cases[0], UnsupervisedCase)


# ---------------------------------------------------------------------------
# 5. ECDF 값 기록
# ---------------------------------------------------------------------------


def test_family_ecdf_field_matches_computed_ecdf():
    """family_ecdf 가 zero_preserving ECDF 결과와 일치한다 (양수 score rank pct)."""
    df = _make_df(4)
    # 양수 score 4 개 — rank pct=True, method="max" 결과: 0.25 / 0.5 / 0.75 / 1.0.
    scores = pd.Series([0.1, 0.2, 0.3, 0.4], index=df.index)
    details = _make_details_for(
        df,
        feature_rows={i: [("amount", 0.5)] for i in df.index},
    )
    result = _make_detection_result(scores=scores, details=details)
    cases = build_unsupervised_cases(
        batch_id="batch001",
        detection_result=result,
        df=df,
        model_id="vae_v1",
        schema_hash="schema_abc",
        ecdf_gate=0.0,  # 모두 통과시켜 ecdf 값 직접 검사.
    )
    by_label = {c.row_refs[0].index_label: c.family_ecdf for c in cases}
    # canonical int label: 0→"i:0", 1→"i:1", 2→"i:2", 3→"i:3"
    assert by_label["i:0"] == 0.25
    assert by_label["i:1"] == 0.5
    assert by_label["i:2"] == 0.75
    assert by_label["i:3"] == 1.0


def test_family_score_preserves_detector_score_and_family_ecdf_is_queue_percentile():
    """family_score 는 detector score, family_ecdf 는 builder 의 zero-preserving ECDF."""
    df = _make_df(4)
    # Stage7 fixed5 path 의 unsupervised score 는 이미 train-distribution ECDF 점수다.
    # Builder 는 그 값을 family_score 로 보존하고, case gate/sort 설명용 queue ECDF 를 별도로 둔다.
    scores = pd.Series([0.20, 0.80, 0.60, 0.95], index=df.index)
    details = _make_details_for(
        df,
        feature_rows={i: [("amount", 0.5)] for i in df.index},
    )
    result = _make_detection_result(scores=scores, details=details)

    cases = build_unsupervised_cases(
        batch_id="batch001",
        detection_result=result,
        df=df,
        model_id="vae_v1",
        schema_hash="schema_abc",
        ecdf_gate=0.0,
    )

    by_label = {case.row_refs[0].index_label: case for case in cases}
    assert by_label["i:0"].family_score == 0.20
    assert by_label["i:0"].anomaly_score == 0.20
    assert by_label["i:0"].family_ecdf == 0.25
    assert by_label["i:3"].family_score == 0.95
    assert by_label["i:3"].family_ecdf == 1.0


def test_stage7_dummy_details_produces_case_without_top_features():
    """Stage7 dummy details 는 row evidence unit 은 만들지만 feature payload 는 비운다."""
    df = _make_df(2)
    scores = pd.Series([0.70, 0.99], index=df.index)
    details = pd.DataFrame({"_stage7_native_measurement": [1, 1]}, index=df.index)
    result = _make_detection_result(scores=scores, details=details)

    cases = build_unsupervised_cases(
        batch_id="batch001",
        detection_result=result,
        df=df,
        model_id="stage7-fixed5-model-bundle-v1",
        schema_hash="stage7-fixed5-normalcal5",
        ecdf_gate=0.5,
    )

    assert len(cases) == 2
    assert all(case.unit_type == "row" for case in cases)
    assert all(case.top_features == () for case in cases)


# ---------------------------------------------------------------------------
# 6. phase1_case_refs 기본값
# ---------------------------------------------------------------------------


def test_phase1_case_refs_empty_by_default():
    df = _make_df(1)
    scores = pd.Series([0.99], index=df.index)
    details = _make_details_for(df, feature_rows={0: [("amount", 0.8)]})
    result = _make_detection_result(scores=scores, details=details)
    cases = build_unsupervised_cases(
        batch_id="batch001",
        detection_result=result,
        df=df,
        model_id="vae_v1",
        schema_hash="schema_abc",
        ecdf_gate=0.5,
    )
    assert len(cases) == 1
    assert cases[0].phase1_case_refs == ()


# ---------------------------------------------------------------------------
# Wave 2 Followup — graceful fallback / null-safe identifier / custom gate
# ---------------------------------------------------------------------------


def test_row_with_label_only_in_details_skipped_when_missing_from_df():
    """details.index 에는 있지만 df.index 에 없는 label 은 graceful skip — invariant #16.

    df.index.get_loc(label) 의 KeyError 가 전파되어 builder 가 깨지지 않아야 한다.
    """
    df = pd.DataFrame(
        {
            "document_id": ["DOC001", "DOC002"],
            "line_number": [1, 2],
            "company_code": ["C01", "C01"],
        },
        index=pd.Index([10, 11]),
    )
    # scores / details 는 df 에 없는 label (99) 포함.
    scores = pd.Series([0.9, 0.95], index=pd.Index([10, 99]))
    details = pd.DataFrame(
        {
            "ML02_top_feature_1": ["feat_a", "feat_b"],
            "ML02_top_feature_1_contrib": [0.5, 0.6],
        },
        index=pd.Index([10, 99]),
    )
    result = DetectionResult(
        track_name="ml_unsupervised",
        flagged_indices=[int(label) for label, score in scores.items() if score > 0],  # type: ignore[arg-type]
        scores=scores,
        rule_flags=[],
        details=details,
        metadata={},
        warnings=[],
    )
    cases = build_unsupervised_cases(
        batch_id="batch-001",
        detection_result=result,
        df=df,
        model_id="vae_v1",
        schema_hash="schema_abc",
        ecdf_gate=0.5,
    )
    # label 99 는 df 부재 → skip. label 10 만 case 화.
    assert len(cases) == 1
    assert cases[0].row_refs[0].index_label == "i:10"


def test_document_id_nan_collapses_to_none_in_row_ref():
    """document_id 컬럼 값이 NaN 이면 Phase2RowRef.document_id 가 None — "nan" 문자열 방어."""
    import numpy as np

    df = pd.DataFrame(
        {
            "document_id": [np.nan, "DOC002"],
            "line_number": [1, 2],
            "company_code": ["C01", "C01"],
        },
        index=pd.Index([10, 11]),
    )
    df = df.astype({"document_id": "object"})
    scores = pd.Series([0.95, 0.96], index=pd.Index([10, 11]))
    details = pd.DataFrame(
        {
            "ML02_top_feature_1": ["feat_a", "feat_b"],
            "ML02_top_feature_1_contrib": [0.5, 0.6],
        },
        index=pd.Index([10, 11]),
    )
    result = DetectionResult(
        track_name="ml_unsupervised",
        flagged_indices=[int(label) for label, score in scores.items() if score > 0],  # type: ignore[arg-type]
        scores=scores,
        rule_flags=[],
        details=details,
        metadata={},
        warnings=[],
    )
    cases = build_unsupervised_cases(
        batch_id="batch-001",
        detection_result=result,
        df=df,
        model_id="vae_v1",
        schema_hash="schema_abc",
        ecdf_gate=0.5,
    )
    by_label = {case.row_refs[0].index_label: case for case in cases}
    assert by_label["i:10"].row_refs[0].document_id is None  # NaN → None
    assert by_label["i:11"].row_refs[0].document_id == "DOC002"


def test_company_code_pd_na_collapses_to_none_in_row_ref():
    """company_code 가 pd.NA 면 Phase2RowRef.company_code 가 None — "<NA>" 문자열 방어."""
    df = pd.DataFrame(
        {
            "document_id": ["DOC001", "DOC002"],
            "line_number": [1, 2],
            "company_code": [pd.NA, "C01"],
        },
        index=pd.Index([10, 11]),
    )
    df = df.astype({"company_code": "object"})
    scores = pd.Series([0.95, 0.96], index=pd.Index([10, 11]))
    details = pd.DataFrame(
        {
            "ML02_top_feature_1": ["feat_a", "feat_b"],
            "ML02_top_feature_1_contrib": [0.5, 0.6],
        },
        index=pd.Index([10, 11]),
    )
    result = DetectionResult(
        track_name="ml_unsupervised",
        flagged_indices=[int(label) for label, score in scores.items() if score > 0],  # type: ignore[arg-type]
        scores=scores,
        rule_flags=[],
        details=details,
        metadata={},
        warnings=[],
    )
    cases = build_unsupervised_cases(
        batch_id="batch-001",
        detection_result=result,
        df=df,
        model_id="vae_v1",
        schema_hash="schema_abc",
        ecdf_gate=0.5,
    )
    by_label = {case.row_refs[0].index_label: case for case in cases}
    assert by_label["i:10"].row_refs[0].company_code is None
    assert by_label["i:11"].row_refs[0].company_code == "C01"


def test_case_generation_reason_records_custom_threshold():
    """custom ecdf_gate (예: 0.5) 가 case_generation_reason.threshold 에 그대로 기록."""
    df = pd.DataFrame(
        {"document_id": ["DOC001"], "line_number": [1]},
        index=pd.Index([10]),
    )
    scores = pd.Series([0.7], index=pd.Index([10]))
    details = pd.DataFrame(
        {
            "ML02_top_feature_1": ["feat_a"],
            "ML02_top_feature_1_contrib": [0.5],
        },
        index=pd.Index([10]),
    )
    result = DetectionResult(
        track_name="ml_unsupervised",
        flagged_indices=[int(label) for label, score in scores.items() if score > 0],  # type: ignore[arg-type]
        scores=scores,
        rule_flags=[],
        details=details,
        metadata={},
        warnings=[],
    )
    cases = build_unsupervised_cases(
        batch_id="batch-001",
        detection_result=result,
        df=df,
        model_id="vae_v1",
        schema_hash="schema_abc",
        ecdf_gate=0.5,
    )
    assert len(cases) == 1
    reason = cases[0].case_generation_reason
    assert reason["gate"] == "unsupervised_ecdf"
    assert reason["threshold"] == 0.5
    assert "ecdf" in reason
    # 하드코딩된 q95 문자열은 사용하지 않음 (custom threshold 에서 부정확해짐).
    assert reason["gate"] != "unsupervised_ecdf_q95"
