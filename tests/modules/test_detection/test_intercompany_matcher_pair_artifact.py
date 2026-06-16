"""IntercompanyMatcher 의 ic_pair_artifact metadata 검증 (S5 Phase A).

Why: v7-plan S5 invariant #52~53 — IC matcher 가 row 단위 score/details 를
변경하지 않으면서 새 metadata key ``ic_pair_artifact`` 를 부착하는지 확인.
artifact 는 candidate_pairs / unmatched_rows / mismatch_pairs / reciprocal_pairs
+ coverage 5종 sanitized projection 으로 구성된다.

기존 IC matcher 의 scores / details / row_sidecar / probabilistic_reconciliation /
reciprocal_flow metadata 는 변경 0건 (회귀 보장).
"""

from __future__ import annotations

import pandas as pd
import pytest

from config.settings import AuditSettings
from src.detection.base import DetectionResult
from src.detection.intercompany_matcher import IntercompanyMatcher

AUDIT_RULES = {
    "patterns": {
        "intercompany": {
            "pairs": [
                {"receivable": "1150", "payable": "2050"},
            ],
            "partner_format": {
                "ic_partner_regex": r"^[A-Za-z]\d{3}$",
            },
        },
    },
}


def _detector(*, min_rows: int = 1) -> IntercompanyMatcher:
    settings = AuditSettings(ic_min_ic_rows=min_rows)
    return IntercompanyMatcher(settings=settings, audit_rules=AUDIT_RULES)


def _ic_df(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if "posting_date" in df.columns:
        df["posting_date"] = pd.to_datetime(df["posting_date"])
    if "is_intercompany" not in df.columns:
        df["is_intercompany"] = df["gl_account"].astype(str).str.startswith(("1150", "2050"))
    for col in ("debit_amount", "credit_amount"):
        if col not in df.columns:
            df[col] = 0.0
    return df


def _reciprocal_df() -> pd.DataFrame:
    """단일 document 안에 receivable + payable 동시 존재 (amount symmetry ≈ 1.0)."""
    return _ic_df(
        [
            {
                "document_id": "DOC100",
                "gl_account": "1150-001",
                "debit_amount": 1_000_000.0,
                "credit_amount": 0.0,
                "company_code": "C01",
                "trading_partner": "C02",
                "posting_date": "2024-01-15",
                "reference": "REF100",
                "currency": "KRW",
            },
            {
                "document_id": "DOC100",
                "gl_account": "2050-001",
                "debit_amount": 0.0,
                "credit_amount": 1_000_000.0,
                "company_code": "C01",
                "trading_partner": "C02",
                "posting_date": "2024-01-15",
                "reference": "REF100",
                "currency": "KRW",
            },
        ]
    )


def _mismatch_df() -> pd.DataFrame:
    """매칭됐으나 amount mismatch 10% 초과."""
    return _ic_df(
        [
            {
                "document_id": "DOC200",
                "gl_account": "1150-001",
                "debit_amount": 1_000_000.0,
                "credit_amount": 0.0,
                "company_code": "C01",
                "trading_partner": "C02",
                "posting_date": "2024-02-10",
                "reference": "REF200",
                "currency": "KRW",
            },
            {
                "document_id": "DOC201",
                "gl_account": "2050-001",
                "debit_amount": 0.0,
                "credit_amount": 1_500_000.0,
                "company_code": "C02",
                "trading_partner": "C01",
                "posting_date": "2024-02-11",
                "reference": "REF200",
                "currency": "KRW",
            },
        ]
    )


def _cross_company_reciprocal_df() -> pd.DataFrame:
    return _ic_df(
        [
            {
                "document_id": "DOC-REC",
                "gl_account": "1150-001",
                "debit_amount": 1_000_000.0,
                "credit_amount": 0.0,
                "company_code": "C01",
                "trading_partner": "C02",
                "posting_date": "2024-02-10",
                "reference": "REF-XCO",
                "currency": "KRW",
            },
            {
                "document_id": "DOC-PAY",
                "gl_account": "2050-001",
                "debit_amount": 0.0,
                "credit_amount": 1_000_000.0,
                "company_code": "C02",
                "trading_partner": "C01",
                "posting_date": "2024-02-10",
                "reference": "REF-XCO",
                "currency": "KRW",
            },
        ]
    )


def _unmatched_df() -> pd.DataFrame:
    """IC01 unmatched (partner master 에 없는 high evidence row)."""
    return _ic_df(
        [
            {
                "document_id": "DOC300",
                "gl_account": "1150-002",
                "debit_amount": 500_000.0,
                "credit_amount": 0.0,
                "company_code": "C01",
                "trading_partner": "Z999",  # master 에 없는 IC-format 상대방
                "posting_date": "2024-03-05",
                "reference": "REF300",
                "currency": "KRW",
            },
        ]
    )


# ---------------------------------------------------------------------------
# invariant #52~53 — artifact 구조 / json safety
# ---------------------------------------------------------------------------


def test_artifact_contains_all_four_artifact_lists_when_ic_rows_present():
    """IC rows 존재하는 정상 경로에서 4종 list + coverage + schema_version 모두 존재."""
    df = _reciprocal_df()
    result = _detector().detect(df)
    artifact = result.metadata.get("ic_pair_artifact")
    assert isinstance(artifact, dict)
    assert artifact["schema_version"] == 1
    for key in (
        "candidate_pairs",
        "unmatched_rows",
        "mismatch_pairs",
        "reciprocal_pairs",
        "coverage",
    ):
        assert key in artifact, f"missing key: {key}"
    assert isinstance(artifact["candidate_pairs"], list)
    assert isinstance(artifact["unmatched_rows"], list)
    assert isinstance(artifact["mismatch_pairs"], list)
    assert isinstance(artifact["reciprocal_pairs"], list)
    assert isinstance(artifact["coverage"], dict)


def test_artifact_empty_when_ic_rows_below_threshold():
    """ic_min_ic_rows 미달 → empty result. artifact 미부착(_empty_result) 도 graceful."""
    df = _ic_df(
        [
            {
                "document_id": "DOC400",
                "gl_account": "9999-001",  # IC 아님
                "debit_amount": 100.0,
                "credit_amount": 0.0,
            },
        ]
    )
    # ic_min_ic_rows=5 로 강제 미달
    settings = AuditSettings(ic_min_ic_rows=5)
    det = IntercompanyMatcher(settings=settings, audit_rules=AUDIT_RULES)
    result = det.detect(df)
    artifact = result.metadata.get("ic_pair_artifact")
    # _empty_result 도 빈 artifact 부착 (graceful, builder 호환).
    assert isinstance(artifact, dict)
    assert artifact["candidate_pairs"] == []
    assert artifact["unmatched_rows"] == []
    assert artifact["mismatch_pairs"] == []
    assert artifact["reciprocal_pairs"] == []


def test_reciprocal_pairs_extracted_for_single_document_with_receivable_payable():
    """단일 doc 내 rec+pay 동시 + amount symmetry ≈ 1.0 → reciprocal_pairs entry."""
    df = _reciprocal_df()
    result = _detector().detect(df)
    artifact = result.metadata["ic_pair_artifact"]
    reciprocal = artifact["reciprocal_pairs"]
    assert len(reciprocal) >= 1
    entry = reciprocal[0]
    assert entry["document_id"] == "DOC100"
    assert entry["receivable_amount"] == pytest.approx(1_000_000.0)
    assert entry["payable_amount"] == pytest.approx(1_000_000.0)
    assert 0.0 <= entry["amount_symmetry"] <= 1.0
    assert entry["amount_symmetry"] >= 0.95


def test_reciprocal_pairs_extracted_for_cross_company_reference_pair():
    """별도 회사 전표 rec/pay 가 reference+상대회사+금액으로 맞으면 reciprocal artifact."""
    df = _cross_company_reciprocal_df()
    result = _detector().detect(df)
    artifact = result.metadata["ic_pair_artifact"]
    reciprocal = artifact["reciprocal_pairs"]

    assert len(reciprocal) == 1
    entry = reciprocal[0]
    assert entry["flow_scope"] == "cross_company_reference"
    assert entry["receivable_document_ids"] == ["DOC-REC"]
    assert entry["payable_document_ids"] == ["DOC-PAY"]
    assert entry["amount_symmetry"] == pytest.approx(1.0)
    assert artifact["coverage"]["reciprocal_pair_count"] == 1


def test_mismatch_pairs_extracted_for_amount_mismatch_with_ratio():
    """IC02 score > 0 인 row → mismatch_pairs entry. ratio ∈ [0,1], severity ∈ [0,1]."""
    df = _mismatch_df()
    result = _detector().detect(df)
    artifact = result.metadata["ic_pair_artifact"]
    mismatch = artifact["mismatch_pairs"]
    assert len(mismatch) >= 1
    entry = mismatch[0]
    assert "left_index" in entry and "right_index" in entry
    assert entry["amount_a"] > 0
    assert entry["amount_b"] > 0
    assert 0.0 <= entry["ratio"] <= 1.0
    assert 0.0 <= entry["mismatch_severity"] <= 1.0


def test_unmatched_rows_extracted_from_ic01_evidence_level():
    """row_sidecar.ic01_evidence_level 가 truthy 인 row → unmatched_rows entry."""
    df = _unmatched_df()
    result = _detector().detect(df)
    artifact = result.metadata["ic_pair_artifact"]
    unmatched = artifact["unmatched_rows"]
    # IC01 high evidence row 가 1건 이상 잡혀야 함.
    assert len(unmatched) >= 1
    entry = unmatched[0]
    assert "row_index" in entry
    assert entry["evidence_level"] in {"high", "review"}
    # review_reason 은 string (빈 문자열도 허용 — high 분기는 reason 비어 있음).
    assert isinstance(entry["review_reason"], str)


def test_candidate_pairs_index_labels_are_json_safe():
    """candidate_pairs 의 left_index/right_index 는 _json_safe 통과 (primitive 또는 str)."""
    df = _mismatch_df()
    result = _detector().detect(df)
    artifact = result.metadata["ic_pair_artifact"]
    # mismatch_pairs 의 left/right index 도 동일한 sanitization 통과.
    primitives = (str, int, bool, type(None))
    for entry in artifact["mismatch_pairs"]:
        assert isinstance(entry["left_index"], primitives)
        assert isinstance(entry["right_index"], primitives)
    for entry in artifact["candidate_pairs"]:
        assert isinstance(entry["left_index"], primitives)
        assert isinstance(entry["right_index"], primitives)


def test_artifact_schema_version_pinned_to_1():
    """schema_version 은 1 — 후속 변경 시 명시적 bump 필요."""
    df = _reciprocal_df()
    result = _detector().detect(df)
    artifact = result.metadata["ic_pair_artifact"]
    assert artifact["schema_version"] == 1


def test_artifact_metadata_does_not_change_row_scores_or_details():
    """기존 row 단위 scores / details / row_sidecar 4종 metadata key 변경 0건 (회귀 가드)."""
    df = _reciprocal_df()
    result = _detector().detect(df)
    # 기존 metadata key 4종 모두 존재해야 함 (Phase A 회귀 보장 invariant #52).
    expected_keys = {
        "elapsed",
        "skipped_rules",
        "row_sidecar",
        "probabilistic_reconciliation",
        "reciprocal_flow",
        "ic_pair_artifact",  # 새 key
    }
    assert expected_keys.issubset(set(result.metadata.keys()))
    # scores / details / rule_flags 가 정상 형태로 존재 (값 비교는 기존 테스트가 담당).
    assert isinstance(result, DetectionResult)
    assert isinstance(result.scores, pd.Series)
    assert isinstance(result.details, pd.DataFrame)
    assert isinstance(result.rule_flags, list)


# ---------------------------------------------------------------------------
# S5 Followup (2026-05-27) — invariant #58 / #59 회귀 가드
# ---------------------------------------------------------------------------


def test_reciprocal_pairs_include_both_receivable_and_payable_row_lists():
    """invariant #58: reciprocal_pairs entry 는 receivable + payable 양쪽 row 정보 보유.

    구 schema 의 단일 row_index 만으로는 "무엇과 무엇이 reciprocal" 답이 불가능.
    artifact 가 양쪽 row 의 label + position list 를 모두 보존하여 builder 가
    PHASE1 cross-ref 양쪽 hit 회수 가능하게 한다.
    """
    df = _reciprocal_df()
    result = _detector().detect(df)
    artifact = result.metadata["ic_pair_artifact"]
    reciprocal = artifact["reciprocal_pairs"]
    assert len(reciprocal) >= 1
    entry = reciprocal[0]
    # 양쪽 row 정보 보유.
    assert "receivable_indices" in entry
    assert "receivable_positions" in entry
    assert "payable_indices" in entry
    assert "payable_positions" in entry
    assert isinstance(entry["receivable_indices"], list)
    assert isinstance(entry["payable_indices"], list)
    assert isinstance(entry["receivable_positions"], list)
    assert isinstance(entry["payable_positions"], list)
    # _reciprocal_df 는 doc 안 rec 1행 + pay 1행 → 각각 최소 1개.
    assert len(entry["receivable_indices"]) >= 1
    assert len(entry["payable_indices"]) >= 1
    # label-position 1:1 길이 매칭.
    assert len(entry["receivable_indices"]) == len(entry["receivable_positions"])
    assert len(entry["payable_indices"]) == len(entry["payable_positions"])
    # position 은 int + 0-based valid range.
    for pos in entry["receivable_positions"] + entry["payable_positions"]:
        assert isinstance(pos, int)
        assert 0 <= pos < len(df)
    # legacy compat 도 유지.
    assert "row_index" in entry
    assert "row_position" in entry


def test_each_artifact_entry_includes_row_position():
    """invariant #59: 4종 artifact entry 가 row_position (또는 left/right_position) 보유."""
    # reciprocal — _reciprocal_df 사용
    df_rec = _reciprocal_df()
    artifact_rec = _detector().detect(df_rec).metadata["ic_pair_artifact"]
    for entry in artifact_rec["reciprocal_pairs"]:
        assert "row_position" in entry
        assert isinstance(entry["row_position"], int)

    # mismatch — _mismatch_df 사용
    df_mis = _mismatch_df()
    artifact_mis = _detector().detect(df_mis).metadata["ic_pair_artifact"]
    for entry in artifact_mis["mismatch_pairs"]:
        assert "left_position" in entry
        assert "right_position" in entry
        assert isinstance(entry["left_position"], int)
        assert isinstance(entry["right_position"], int)
    for entry in artifact_mis["candidate_pairs"]:
        assert "left_position" in entry
        assert "right_position" in entry
        assert isinstance(entry["left_position"], int)
        assert isinstance(entry["right_position"], int)

    # unmatched — _unmatched_df 사용
    df_un = _unmatched_df()
    artifact_un = _detector().detect(df_un).metadata["ic_pair_artifact"]
    for entry in artifact_un["unmatched_rows"]:
        assert "row_position" in entry
        assert isinstance(entry["row_position"], int)


def test_reciprocal_extraction_works_with_multiindex_df():
    """MultiIndex df 에서도 reciprocal_pairs entry 가 position 정보 보존.

    Why (invariant #59): tuple label 이 `_ic_json_safe` 에서 str 로 평탄화되더라도
    artifact 의 row_position 이 보존되어 있어 builder 가 df.iloc[position] 으로
    안전 lookup 할 수 있는지 검증.
    """
    df = _reciprocal_df()
    # MultiIndex 로 강제 변환 (document_id, line_no) 형태.
    df = df.copy()
    df.index = pd.MultiIndex.from_tuples(
        [(doc, i) for i, doc in enumerate(df["document_id"].astype(str))],
        names=["doc", "line"],
    )
    result = _detector().detect(df)
    artifact = result.metadata["ic_pair_artifact"]
    reciprocal = artifact["reciprocal_pairs"]
    # MultiIndex 라도 reciprocal entry 가 정상 추출 + position 정보 유효.
    assert len(reciprocal) >= 1
    entry = reciprocal[0]
    rec_positions = entry["receivable_positions"]
    pay_positions = entry["payable_positions"]
    assert len(rec_positions) >= 1
    assert len(pay_positions) >= 1
    # position 은 모두 df 의 0-based valid range 안.
    for pos in rec_positions + pay_positions:
        assert 0 <= pos < len(df)
    # legacy row_index / row_position 도 보유.
    assert "row_position" in entry
    assert 0 <= entry["row_position"] < len(df)
