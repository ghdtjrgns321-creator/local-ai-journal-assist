"""PHASE1 case builder 의 engagement_salt + hash 산출 테스트 (S6.next Phase 1).

v7-plan §S6.next Phase 1 의 단일 출처 사양에 대응. 신규 hash 필드
(canonical_label_hash / doc_id_hash / line_number_key) 가
``engagement_salt`` 미수령 시 빈 값, 수령 시 PHASE2 row_ref_map 산출과
동일한 hash 값으로 채워지는지 검증한다.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from src.detection.base import DetectionResult, RuleFlag
from src.detection.phase1_case_builder import build_phase1_case_result
from src.services.phase2_ref_canonical import canonicalize_ref_key
from src.services.phase2_ref_pseudonymize import hash_ref_key

# ---------------------------------------------------------------------------
# 공통 fixture — 단일 row, L1-05 single rule hit.
# 회귀 영향을 최소화하기 위해 기존 single-rule 패턴과 동일한 dataframe 구조를 사용한다.
# ---------------------------------------------------------------------------


def _df_with_line_number() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "document_id": ["DOC-1"],
            "line_number": ["0001"],
            "posting_date": pd.to_datetime(["2026-04-30"]),
            "created_by": ["kim"],
            "business_process": ["R2R"],
            "gl_account": ["410000"],
            "debit_amount": [10_000_000.0],
            "credit_amount": [0.0],
            "company_code": ["kr01"],
            "trading_partner": ["kr02"],
            "document_type": ["SA"],
        }
    )


def _df_without_line_number() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "document_id": ["DOC-1"],
            "posting_date": pd.to_datetime(["2026-04-30"]),
            "created_by": ["kim"],
            "business_process": ["R2R"],
            "gl_account": ["410000"],
            "debit_amount": [10_000_000.0],
            "credit_amount": [0.0],
            "company_code": ["kr01"],
            "trading_partner": ["kr02"],
            "document_type": ["SA"],
        }
    )


def _detection_result(df: pd.DataFrame) -> DetectionResult:
    rule_id = "L1-05"
    details = pd.DataFrame({rule_id: [0.8]}, index=df.index)
    return DetectionResult(
        track_name="layer_b",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[RuleFlag(rule_id, "SelfApproval", 4, 1, len(df))],
        details=details,
        metadata={"elapsed": 0.01},
    )


def _build_result(df: pd.DataFrame, *, engagement_salt: str = ""):
    return build_phase1_case_result(
        df,
        [_detection_result(df)],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={
            "phase1_case": {
                "top_n_cases": 50,
                "top_n_per_theme": 10,
            }
        },
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
        engagement_salt=engagement_salt,
    )


def _first_hit(result):
    assert result.cases, "최소 1개 case 가 생성되어야 한다"
    case = result.cases[0]
    assert case.raw_rule_hits, "case 에 raw_rule_hit 이 1개 이상"
    return case.raw_rule_hits[0]


# ---------------------------------------------------------------------------
# Backward compat — salt 미수령 시 hash 필드 빈 값 (invariant #71)
# ---------------------------------------------------------------------------


def test_phase1_case_builder_without_salt_keeps_hash_fields_empty() -> None:
    df = _df_with_line_number()
    result = _build_result(df, engagement_salt="")
    hit = _first_hit(result)
    assert hit.canonical_label_hash == ""
    assert hit.doc_id_hash == ""
    assert hit.line_number_key is None
    # S6.next Phase 2 — company_code_hash 도 salt 미수령 시 빈 값 (invariant #74).
    assert hit.company_code_hash == ""


# ---------------------------------------------------------------------------
# salt 수령 시 각 필드 산출 — canonical_label_hash / doc_id_hash / line_number_key
# ---------------------------------------------------------------------------


def test_phase1_case_builder_with_salt_populates_canonical_label_hash() -> None:
    df = _df_with_line_number()
    salt = "engagement-A|batch42"
    result = _build_result(df, engagement_salt=salt)
    hit = _first_hit(result)
    expected = hash_ref_key(canonicalize_ref_key(df.index[0]), salt=salt)
    assert hit.canonical_label_hash == expected
    assert hit.canonical_label_hash != ""


def test_phase1_case_builder_with_salt_populates_doc_id_hash() -> None:
    df = _df_with_line_number()
    salt = "engagement-A|batch42"
    result = _build_result(df, engagement_salt=salt)
    hit = _first_hit(result)
    expected = hash_ref_key("DOC-1", salt=salt)
    assert hit.doc_id_hash == expected


def test_phase1_case_builder_with_salt_populates_line_number_key() -> None:
    df = _df_with_line_number()
    result = _build_result(df, engagement_salt="engagement-A|batch42")
    hit = _first_hit(result)
    # canonicalize_ref_key("0001") == "s:0001" → "n:" 아님 → 그대로 보존.
    assert hit.line_number_key == canonicalize_ref_key("0001")


def test_phase1_case_builder_line_number_key_none_when_column_absent() -> None:
    """line_number 컬럼 부재 시 line_number_key = None."""
    df = _df_without_line_number()
    result = _build_result(df, engagement_salt="engagement-A|batch42")
    hit = _first_hit(result)
    assert hit.line_number_key is None


# ---------------------------------------------------------------------------
# S6.next Phase 2 — company_code_hash 산출 (invariant #74)
# ---------------------------------------------------------------------------


def test_phase1_case_builder_with_salt_populates_company_code_hash() -> None:
    """salt 가용 + company_code 컬럼 존재 시 company_code_hash 산출."""
    df = _df_with_line_number()
    salt = "engagement-A|batch42"
    result = _build_result(df, engagement_salt=salt)
    hit = _first_hit(result)
    expected = hash_ref_key("kr01", salt=salt)
    assert hit.company_code_hash == expected
    assert hit.company_code_hash != ""


def test_phase1_case_builder_company_code_hash_empty_when_column_absent() -> None:
    """company_code 컬럼 부재 시 company_code_hash = "" (graceful fallback)."""
    df = _df_without_line_number().drop(columns=["company_code"])
    salt = "engagement-A|batch42"
    result = _build_result(df, engagement_salt=salt)
    hit = _first_hit(result)
    assert hit.company_code_hash == ""
    # 다른 hash 필드는 정상 산출 (df.index / doc_id 는 있으므로).
    assert hit.canonical_label_hash != ""
    assert hit.doc_id_hash != ""


def test_phase1_case_builder_company_code_hash_matches_phase2_row_ref_map_format() -> None:
    """PHASE2 row_ref_map 의 company_code_hash 와 동일 공식 — invariant #77.

    Why: row_ref_map fallback 과 hit hash 가 매칭되려면 두 source 가 동일 salt
    + 동일 input(원본 company_code 문자열) 으로 hash 한 값이어야 한다.
    """
    df = _df_with_line_number()
    salt = "engagement-A|batch42"
    result = _build_result(df, engagement_salt=salt)
    hit = _first_hit(result)
    # PHASE2 store/_serialize_row_ref 와 동일 공식 — str(company_code) 그대로 hash.
    phase2_hash = hash_ref_key(str(df["company_code"].iat[0]), salt=salt)
    assert hit.company_code_hash == phase2_hash


# ---------------------------------------------------------------------------
# engagement-scoped salt — 서로 다른 salt → 서로 다른 hash (invariant #70 보조)
# ---------------------------------------------------------------------------


def test_phase1_case_builder_hash_uses_engagement_scoped_salt() -> None:
    df = _df_with_line_number()
    salt_a = "engagement-A|batch42"
    salt_b = "engagement-B|batch42"
    result_a = _build_result(df, engagement_salt=salt_a)
    result_b = _build_result(df, engagement_salt=salt_b)
    hash_a = _first_hit(result_a).canonical_label_hash
    hash_b = _first_hit(result_b).canonical_label_hash
    assert hash_a != ""
    assert hash_b != ""
    assert hash_a != hash_b


# ---------------------------------------------------------------------------
# PHASE2 row_ref_map 의 같은 row position 산출 hash 와 일치 (invariant #70)
# ---------------------------------------------------------------------------


def test_phase1_case_builder_canonical_label_hash_matches_phase2_format() -> None:
    """PHASE2 store 의 row_ref_map 산출(canonical_label_hash) 와 동일 공식."""
    df = _df_with_line_number()
    salt = "engagement-A|batch42"
    result = _build_result(df, engagement_salt=salt)
    hit = _first_hit(result)

    # PHASE2 store/_serialize_row_ref 와 동일 공식 — index_label 은 canonicalize 결과.
    phase2_canonical = canonicalize_ref_key(df.index[0])
    phase2_hash = hash_ref_key(phase2_canonical, salt=salt)
    assert hit.canonical_label_hash == phase2_hash


# ---------------------------------------------------------------------------
# Wave 7 Followup — whitespace-only salt 가드 (PHASE2 store _is_valid_salt 와 정합)
# ---------------------------------------------------------------------------


def test_phase1_case_builder_whitespace_only_salt_treated_as_empty() -> None:
    """``engagement_salt`` 가 공백만 (``"   "`` / ``"\\t\\n"``) 이면 빈 salt 와 동일 처리.

    Why: 이전 ``bool(engagement_salt)`` 는 whitespace-only 도 truthy 로 인식 →
    ``hash_ref_key(..., salt="   ")`` 가 ValueError. PHASE2 store 의
    ``_is_valid_salt()`` 와 동일하게 strip() 후 truthy 검사. invariant #71 보강.
    """
    df = _df_with_line_number()
    for whitespace_salt in ("   ", "\t", "\n", " \t\n "):
        result = _build_result(df, engagement_salt=whitespace_salt)
        hit = _first_hit(result)
        # whitespace-only → 빈 salt 와 동일 처리 — 신규 hash 필드는 default.
        assert hit.canonical_label_hash == "", (
            f"whitespace salt {whitespace_salt!r} should be treated as empty"
        )
        assert hit.doc_id_hash == ""
        assert hit.line_number_key is None
