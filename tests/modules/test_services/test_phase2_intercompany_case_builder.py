"""`build_intercompany_cases` 의 PHASE2 IntercompanyCase 변환 계약 검증 (S5 Phase B).

Why: v7-plan S5 invariant #54~57 — ic_pair_artifact 의 reciprocal_pairs +
mismatch_pairs 만 case 화. unmatched_rows / timing-only 단독은 case 화하지
않으며, evidence_signature 는 ic_role 만 (raw 금액/score 미포함).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.detection.base import DetectionResult
from src.models.phase2_case import IntercompanyCase
from src.services.phase2_intercompany_case_builder import build_intercompany_cases


def _make_df() -> pd.DataFrame:
    """3-row IC fixture — document_id / company_code / trading_partner 보유."""
    return pd.DataFrame(
        {
            "document_id": ["DOC100", "DOC100", "DOC200"],
            "gl_account": ["1150-001", "2050-001", "1150-002"],
            "debit_amount": [1_000_000.0, 0.0, 500_000.0],
            "credit_amount": [0.0, 1_000_000.0, 0.0],
            "company_code": ["C01", "C01", "C02"],
            "trading_partner": ["C02", "C02", "C01"],
        },
        index=pd.Index([10, 11, 12]),
    )


def _make_result(
    *,
    ic_pair_artifact: dict[str, Any] | None,
    track_name: str = "intercompany",
    extra_metadata: dict[str, Any] | None = None,
) -> DetectionResult:
    """IC detection result fixture — ic_pair_artifact 만 다르게 주입."""
    metadata: dict[str, Any] = {}
    if extra_metadata:
        metadata.update(extra_metadata)
    if ic_pair_artifact is not None:
        metadata["ic_pair_artifact"] = ic_pair_artifact
    return DetectionResult(
        track_name=track_name,
        flagged_indices=[],
        scores=pd.Series([0.0, 0.0, 0.0], index=[10, 11, 12]),
        rule_flags=[],
        details=pd.DataFrame(),
        metadata=metadata,
    )


def _reciprocal_artifact() -> dict[str, Any]:
    """S5 Followup (2026-05-27) schema — receivable + payable 양쪽 row 보유 (invariant #58)."""
    return {
        "schema_version": 1,
        "candidate_pairs": [],
        "unmatched_rows": [],
        "mismatch_pairs": [],
        "reciprocal_pairs": [
            {
                "document_id": "DOC100",
                # _make_df 의 doc=DOC100 인 row 는 label 10, 11 (position 0, 1).
                # rec=label 10 (1150-001 차변), pay=label 11 (2050-001 대변).
                "receivable_indices": [10],
                "receivable_positions": [0],
                "payable_indices": [11],
                "payable_positions": [1],
                "receivable_amount": 1_000_000.0,
                "payable_amount": 1_000_000.0,
                "amount_symmetry": 1.0,
                # legacy compat
                "row_index": 10,
                "row_position": 0,
            }
        ],
        "coverage": {},
    }


def _legacy_reciprocal_artifact() -> dict[str, Any]:
    """구 schema (row_index 만) — legacy fallback 회귀 가드."""
    return {
        "schema_version": 1,
        "candidate_pairs": [],
        "unmatched_rows": [],
        "mismatch_pairs": [],
        "reciprocal_pairs": [
            {
                "row_index": 10,
                "document_id": "DOC100",
                "receivable_amount": 1_000_000.0,
                "payable_amount": 1_000_000.0,
                "amount_symmetry": 1.0,
            }
        ],
        "coverage": {},
    }


def _mismatch_artifact() -> dict[str, Any]:
    """S5 Followup (2026-05-27) schema — left_position / right_position 포함 (invariant #59)."""
    return {
        "schema_version": 1,
        "candidate_pairs": [],
        "unmatched_rows": [],
        "mismatch_pairs": [
            {
                "left_index": 10,
                "right_index": 12,
                "left_position": 0,
                "right_position": 2,
                "amount_a": 1_000_000.0,
                "amount_b": 700_000.0,
                "ratio": 0.7,
                "mismatch_severity": 0.5,
            }
        ],
        "reciprocal_pairs": [],
        "coverage": {},
    }


# ---------------------------------------------------------------------------
# graceful fallback (invariant #57)
# ---------------------------------------------------------------------------


def test_empty_metadata_returns_empty_tuple():
    """metadata 빈 → 빈 tuple."""
    df = _make_df()
    result = _make_result(ic_pair_artifact=None)
    cases = build_intercompany_cases(batch_id="b1", detection_result=result, df=df)
    assert cases == ()
    assert isinstance(cases, tuple)


def test_ic_pair_artifact_missing_returns_empty_tuple():
    """다른 metadata key 만 있고 ic_pair_artifact 부재 → 빈 tuple."""
    df = _make_df()
    result = _make_result(
        ic_pair_artifact=None,
        extra_metadata={"other": "value"},
    )
    cases = build_intercompany_cases(batch_id="b1", detection_result=result, df=df)
    assert cases == ()


# ---------------------------------------------------------------------------
# ic_role 분기 (invariant #54)
# ---------------------------------------------------------------------------


def test_reciprocal_pairs_emit_ic_role_reciprocal_flow():
    """reciprocal_pairs entry → IntercompanyCase(ic_role='reciprocal_flow')."""
    df = _make_df()
    result = _make_result(ic_pair_artifact=_reciprocal_artifact())
    cases = build_intercompany_cases(batch_id="b1", detection_result=result, df=df)
    assert len(cases) == 1
    case = cases[0]
    assert isinstance(case, IntercompanyCase)
    assert case.family == "intercompany"
    assert case.unit_type == "pair"
    assert case.ic_role == "reciprocal_flow"
    assert case.evidence_tier == "strong"
    assert case.amount_symmetry == 1.0


def test_mismatch_pairs_emit_ic_role_amount_mismatch():
    """mismatch_pairs entry → IntercompanyCase(ic_role='amount_mismatch')."""
    df = _make_df()
    result = _make_result(ic_pair_artifact=_mismatch_artifact())
    cases = build_intercompany_cases(batch_id="b1", detection_result=result, df=df)
    assert len(cases) == 1
    case = cases[0]
    assert case.ic_role == "amount_mismatch"
    assert case.evidence_tier == "moderate"


def test_mismatch_pair_preserves_amount_evidence_payload():
    """amount_mismatch review candidate keeps auditor-visible pair evidence values."""
    df = _make_df()
    result = _make_result(ic_pair_artifact=_mismatch_artifact())
    cases = build_intercompany_cases(batch_id="b1", detection_result=result, df=df)

    case = cases[0]

    assert case.amount_a == 1_000_000.0
    assert case.amount_b == 700_000.0
    assert case.amount_symmetry == 0.7
    assert case.family_score == 0.5


# ---------------------------------------------------------------------------
# Gate (invariant #54)
# ---------------------------------------------------------------------------


def test_unmatched_rows_excluded_from_case_generation():
    """unmatched_rows 만 있으면 case 생성 안 함 (weak evidence)."""
    df = _make_df()
    artifact = {
        "schema_version": 1,
        "candidate_pairs": [],
        "unmatched_rows": [
            {
                "row_index": 12,
                "document_id": "DOC200",
                "evidence_level": "high",
                "review_reason": "",
            }
        ],
        "mismatch_pairs": [],
        "reciprocal_pairs": [],
        "coverage": {},
    }
    result = _make_result(ic_pair_artifact=artifact)
    cases = build_intercompany_cases(batch_id="b1", detection_result=result, df=df)
    assert cases == ()


def test_timing_only_pairs_excluded_from_case_generation():
    """candidate_pairs 의 timing-only (amount_prob 없음) 단독 → case 화 안 함."""
    df = _make_df()
    artifact = {
        "schema_version": 1,
        "candidate_pairs": [
            {
                "left_index": 10,
                "right_index": 11,
                "score": 0.7,
                "components": {"amount_prob": 0.0, "timing_prob": 0.7},
            }
        ],
        "unmatched_rows": [],
        "mismatch_pairs": [],
        "reciprocal_pairs": [],
        "coverage": {},
    }
    result = _make_result(ic_pair_artifact=artifact)
    cases = build_intercompany_cases(batch_id="b1", detection_result=result, df=df)
    assert cases == ()


# ---------------------------------------------------------------------------
# case_id / canonical_refs (invariant #54)
# ---------------------------------------------------------------------------


def test_case_id_uses_canonicalized_row_refs():
    """case_id 는 canonical row_ref 기반 — prefix 'p2_intercompany_pair_'."""
    df = _make_df()
    result = _make_result(ic_pair_artifact=_mismatch_artifact())
    cases = build_intercompany_cases(batch_id="b1", detection_result=result, df=df)
    assert len(cases) == 1
    assert cases[0].phase2_case_id.startswith("p2_intercompany_pair_")


# ---------------------------------------------------------------------------
# evidence_signature (invariant #55)
# ---------------------------------------------------------------------------


def test_evidence_signature_contains_only_ic_role():
    """signature 가 ic_role 만 — role 가 다르면 case_id 변경, role 같으면 동일."""
    df = _make_df()
    # 동일 row_index pair 에 대해 reciprocal vs mismatch 분기 — ic_role 만 다름.
    rec_artifact = _reciprocal_artifact()
    mis_artifact = {
        "schema_version": 1,
        "candidate_pairs": [],
        "unmatched_rows": [],
        "mismatch_pairs": [
            {
                "left_index": 10,
                "right_index": 10,  # reciprocal 과 같은 single label
                "amount_a": 1_000_000.0,
                "amount_b": 700_000.0,
                "ratio": 0.7,
                "mismatch_severity": 0.5,
            }
        ],
        "reciprocal_pairs": [],
        "coverage": {},
    }
    cases_rec = build_intercompany_cases(
        batch_id="b1",
        detection_result=_make_result(ic_pair_artifact=rec_artifact),
        df=df,
    )
    cases_mis = build_intercompany_cases(
        batch_id="b1",
        detection_result=_make_result(ic_pair_artifact=mis_artifact),
        df=df,
    )
    assert cases_rec[0].phase2_case_id != cases_mis[0].phase2_case_id


def test_evidence_signature_does_not_include_raw_amount():
    """raw 금액 / severity / ratio 만 다르고 ic_role 같으면 case_id 동일."""
    df = _make_df()
    artifact_a = _mismatch_artifact()
    artifact_b = {
        "schema_version": 1,
        "candidate_pairs": [],
        "unmatched_rows": [],
        "mismatch_pairs": [
            {
                "left_index": 10,  # 같은 row label
                "right_index": 12,
                "amount_a": 999_999.99,  # 다른 금액
                "amount_b": 1.0,
                "ratio": 0.0001,
                "mismatch_severity": 0.99,
            }
        ],
        "reciprocal_pairs": [],
        "coverage": {},
    }
    cases_a = build_intercompany_cases(
        batch_id="b1",
        detection_result=_make_result(ic_pair_artifact=artifact_a),
        df=df,
    )
    cases_b = build_intercompany_cases(
        batch_id="b1",
        detection_result=_make_result(ic_pair_artifact=artifact_b),
        df=df,
    )
    # signature 가 ic_role 만 — row_refs + role 이 같으면 case_id 동일.
    assert cases_a[0].phase2_case_id == cases_b[0].phase2_case_id
    # family_score 는 다름 (signature 와 무관, evidence payload).
    assert cases_a[0].family_score != cases_b[0].family_score


# ---------------------------------------------------------------------------
# phase1_case_refs (invariant #56)
# ---------------------------------------------------------------------------


def test_phase1_case_refs_empty_by_default():
    """builder 출력은 항상 phase1_case_refs = () — linker S4 가 부착."""
    df = _make_df()
    result = _make_result(ic_pair_artifact=_reciprocal_artifact())
    cases = build_intercompany_cases(batch_id="b1", detection_result=result, df=df)
    assert cases[0].phase1_case_refs == ()


# ---------------------------------------------------------------------------
# row_refs (df.index.get_loc 기반 row_position)
# ---------------------------------------------------------------------------


def test_row_refs_built_from_df_row_position():
    """row_refs 가 df.index.get_loc(label) 결과로 채워짐."""
    df = _make_df()
    # df.index = [10, 11, 12] → label=10 의 position=0, label=12 의 position=2.
    result = _make_result(ic_pair_artifact=_mismatch_artifact())
    cases = build_intercompany_cases(batch_id="b1", detection_result=result, df=df)
    case = cases[0]
    assert len(case.row_refs) == 2
    assert case.row_refs[0].row_position == 0
    assert case.row_refs[0].index_label == "i:10"
    assert case.row_refs[0].document_id == "DOC100"
    assert case.row_refs[1].row_position == 2
    assert case.row_refs[1].index_label == "i:12"


# ---------------------------------------------------------------------------
# return type contract (invariant #57)
# ---------------------------------------------------------------------------


def test_return_type_is_tuple_of_intercompany_case():
    """반환 타입은 항상 tuple[IntercompanyCase, ...]."""
    df = _make_df()
    result = _make_result(ic_pair_artifact=_reciprocal_artifact())
    cases = build_intercompany_cases(batch_id="b1", detection_result=result, df=df)
    assert isinstance(cases, tuple)
    assert all(isinstance(c, IntercompanyCase) for c in cases)


# ---------------------------------------------------------------------------
# S5 Followup (2026-05-27) — invariant #58 / #59 회귀 가드
# ---------------------------------------------------------------------------


def test_reciprocal_case_includes_both_receivable_and_payable_row_refs():
    """invariant #58: reciprocal_flow case 가 receivable + payable 양쪽 row 모두 포함.

    artifact entry 의 receivable_indices + payable_indices 양쪽 모두를 row_refs 로
    채워야 builder 단계에서 "무엇과 무엇이 reciprocal" 답이 가능하다. 구 schema 는
    단일 ref 만 보유하므로 PHASE1 cross-ref 에서 반대쪽 row hit 가 누락된다.
    """
    df = _make_df()
    # _reciprocal_artifact: rec=[label 10, pos 0], pay=[label 11, pos 1]
    result = _make_result(ic_pair_artifact=_reciprocal_artifact())
    cases = build_intercompany_cases(batch_id="b1", detection_result=result, df=df)
    assert len(cases) == 1
    case = cases[0]
    # 양쪽 row 가 모두 row_refs 에 포함되어야 함.
    assert len(case.row_refs) == 2
    positions = {ref.row_position for ref in case.row_refs}
    assert positions == {0, 1}
    # rec 측 ref 가 먼저, pay 측 ref 가 나중 (builder 순서 invariant).
    assert case.row_refs[0].row_position == 0  # rec=label 10
    assert case.row_refs[1].row_position == 1  # pay=label 11
    # case identity 는 ic_role 만 — amount_symmetry 는 evidence payload (회귀 가드).
    assert case.ic_role == "reciprocal_flow"
    assert case.amount_symmetry == 1.0


def test_reciprocal_case_with_multiline_doc_includes_all_rows():
    """invariant #58: 한 doc 안 여러 line 의 rec/pay 가 있어도 모두 row_refs 에 포함.

    한 doc 의 receivable 측이 2 line + payable 측이 2 line 일 때, row_refs 가 4개
    모두 채워져야 한다 (Wave5 build log 의 multi-line doc 정합).
    """
    df = pd.DataFrame(
        {
            "document_id": ["DOC500", "DOC500", "DOC500", "DOC500"],
            "gl_account": ["1150-001", "1150-002", "2050-001", "2050-002"],
            "debit_amount": [500_000.0, 500_000.0, 0.0, 0.0],
            "credit_amount": [0.0, 0.0, 500_000.0, 500_000.0],
            "company_code": ["C01", "C01", "C01", "C01"],
            "trading_partner": ["C02", "C02", "C02", "C02"],
        },
        index=pd.Index([100, 101, 102, 103]),
    )
    artifact = {
        "schema_version": 1,
        "candidate_pairs": [],
        "unmatched_rows": [],
        "mismatch_pairs": [],
        "reciprocal_pairs": [
            {
                "document_id": "DOC500",
                "receivable_indices": [100, 101],
                "receivable_positions": [0, 1],
                "payable_indices": [102, 103],
                "payable_positions": [2, 3],
                "receivable_amount": 1_000_000.0,
                "payable_amount": 1_000_000.0,
                "amount_symmetry": 1.0,
                "row_index": 100,
                "row_position": 0,
            }
        ],
        "coverage": {},
    }
    result = _make_result(ic_pair_artifact=artifact)
    cases = build_intercompany_cases(batch_id="b1", detection_result=result, df=df)
    assert len(cases) == 1
    case = cases[0]
    # 4 row 모두 포함.
    assert len(case.row_refs) == 4
    positions = [ref.row_position for ref in case.row_refs]
    assert positions == [0, 1, 2, 3]
    # rec 가 먼저, pay 가 나중.
    assert case.row_refs[0].row_position == 0
    assert case.row_refs[3].row_position == 3


def test_intercompany_case_resolves_multiindex_label_via_position():
    """invariant #59: MultiIndex df 에서 position 기반 lookup → builder 정상 동작.

    artifact 가 보존한 row_position 이 df.iloc[position] 으로 직접 사용 가능하므로,
    _ic_json_safe 가 tuple → str 평탄화한 label 로는 lookup 못 하는 환경에서도
    안전하게 case 생성. MultiIndex 환경에서 IC case 가 조용히 0건 되는 버그 회귀 방어.
    """
    # MultiIndex (doc_id, line) — _ic_json_safe 가 tuple → str("('DOC100', 0)") 평탄화.
    df = pd.DataFrame(
        {
            "document_id": ["DOC100", "DOC100", "DOC200"],
            "gl_account": ["1150-001", "2050-001", "1150-002"],
            "debit_amount": [1_000_000.0, 0.0, 500_000.0],
            "credit_amount": [0.0, 1_000_000.0, 0.0],
            "company_code": ["C01", "C01", "C02"],
            "trading_partner": ["C02", "C02", "C01"],
        },
        index=pd.MultiIndex.from_tuples(
            [("DOC100", 0), ("DOC100", 1), ("DOC200", 0)],
            names=["doc", "line"],
        ),
    )
    # artifact 의 index_label 은 _ic_json_safe 통과 결과 (str 평탄화) — builder 가
    # position 직접 사용 → label 의존성 없음.
    artifact = {
        "schema_version": 1,
        "candidate_pairs": [],
        "unmatched_rows": [],
        "mismatch_pairs": [
            {
                "left_index": "('DOC100', 0)",  # str 평탄화
                "right_index": "('DOC200', 0)",
                "left_position": 0,
                "right_position": 2,
                "amount_a": 1_000_000.0,
                "amount_b": 500_000.0,
                "ratio": 0.5,
                "mismatch_severity": 0.7,
            }
        ],
        "reciprocal_pairs": [
            {
                "document_id": "DOC100",
                "receivable_indices": ["('DOC100', 0)"],
                "receivable_positions": [0],
                "payable_indices": ["('DOC100', 1)"],
                "payable_positions": [1],
                "receivable_amount": 1_000_000.0,
                "payable_amount": 1_000_000.0,
                "amount_symmetry": 1.0,
                "row_index": "('DOC100', 0)",
                "row_position": 0,
            }
        ],
        "coverage": {},
    }
    result = _make_result(ic_pair_artifact=artifact)
    cases = build_intercompany_cases(batch_id="b1", detection_result=result, df=df)
    # MultiIndex 환경에서도 case 가 조용히 0건 되지 않음.
    assert len(cases) == 2
    # reciprocal_flow case — 양쪽 row 포함.
    rec_case = next(c for c in cases if c.ic_role == "reciprocal_flow")
    assert len(rec_case.row_refs) == 2
    assert {ref.row_position for ref in rec_case.row_refs} == {0, 1}
    assert rec_case.row_refs[0].document_id == "DOC100"
    # amount_mismatch case — position 기반 lookup 정상.
    mis_case = next(c for c in cases if c.ic_role == "amount_mismatch")
    assert len(mis_case.row_refs) == 2
    assert {ref.row_position for ref in mis_case.row_refs} == {0, 2}


def test_multiindex_position_ref_preserves_document_company_and_line_identity():
    """MultiIndex position lookup keeps canonical row identity and row-level fallback fields."""
    df = pd.DataFrame(
        {
            "document_id": ["DOC900", "DOC901"],
            "line_number": ["0001", "0002"],
            "gl_account": ["1150-001", "2050-001"],
            "debit_amount": [1_000_000.0, 0.0],
            "credit_amount": [0.0, 1_000_000.0],
            "company_code": ["C01", "C02"],
            "trading_partner": ["C02", "C01"],
        },
        index=pd.MultiIndex.from_tuples(
            [("DOC900", "0001"), ("DOC901", "0002")],
            names=["doc", "line"],
        ),
    )
    artifact = {
        "schema_version": 1,
        "candidate_pairs": [],
        "unmatched_rows": [],
        "mismatch_pairs": [
            {
                "left_index": "('DOC900', '0001')",
                "right_index": "('DOC901', '0002')",
                "left_position": 0,
                "right_position": 1,
                "amount_a": 1_000_000.0,
                "amount_b": 900_000.0,
                "ratio": 0.9,
                "mismatch_severity": 0.2,
            }
        ],
        "reciprocal_pairs": [],
        "coverage": {},
    }
    result = _make_result(ic_pair_artifact=artifact)
    cases = build_intercompany_cases(batch_id="b1", detection_result=result, df=df)

    case = cases[0]

    assert [ref.index_label for ref in case.row_refs] == [
        "t:(s:DOC900|s:0001)",
        "t:(s:DOC901|s:0002)",
    ]
    assert [ref.document_id for ref in case.row_refs] == ["DOC900", "DOC901"]
    assert [ref.line_number_key for ref in case.row_refs] == ["s:0001", "s:0002"]
    assert [ref.company_code for ref in case.row_refs] == ["C01", "C02"]


def test_intercompany_case_index_label_uses_actual_df_index_canonical_form():
    """invariant #60: row_refs[*].index_label 은 ``df.index[position]`` 의 canonical
    form 을 사용해야 한다 — artifact 의 _ic_json_safe 평탄화 결과를 사용하면 안 됨.

    Why: artifact 의 ``('DOC100', 0)`` 같은 str 평탄화 label 을 그대로 ``make_row_ref``
    에 주입하면 canonicalize 가 ``"s:('DOC100', 0)"`` 로 가공해 S1/S4 의 row_ref_map
    + label-based linker 의 expected canonical (``"t:(s:DOC100|i:0)"``) 와 어긋난다.
    이 테스트는 builder 가 ``df.index[position]`` 을 source of truth 로 사용함을 잠금.
    """
    df = pd.DataFrame(
        {
            "document_id": ["DOC100", "DOC100"],
            "gl_account": ["1150-001", "2050-001"],
            "debit_amount": [1_000_000.0, 0.0],
            "credit_amount": [0.0, 1_000_000.0],
            "company_code": ["C01", "C01"],
            "trading_partner": ["C02", "C02"],
        },
        index=pd.MultiIndex.from_tuples(
            [("DOC100", 0), ("DOC100", 1)],
            names=["doc", "line"],
        ),
    )
    # artifact 가 보유한 평탄화 label — builder 가 이걸 사용하지 않아야 한다.
    artifact = {
        "schema_version": 1,
        "candidate_pairs": [],
        "unmatched_rows": [],
        "mismatch_pairs": [],
        "reciprocal_pairs": [
            {
                "document_id": "DOC100",
                "receivable_indices": ["('DOC100', 0)"],  # 평탄화 — 무시되어야 함
                "receivable_positions": [0],
                "payable_indices": ["('DOC100', 1)"],
                "payable_positions": [1],
                "receivable_amount": 1_000_000.0,
                "payable_amount": 1_000_000.0,
                "amount_symmetry": 1.0,
                "row_index": "('DOC100', 0)",
                "row_position": 0,
            }
        ],
        "coverage": {},
    }
    result = _make_result(ic_pair_artifact=artifact)
    cases = build_intercompany_cases(batch_id="b1", detection_result=result, df=df)
    assert len(cases) == 1
    rec_case = cases[0]
    assert len(rec_case.row_refs) == 2

    # invariant #60 — row_refs[0].index_label 이 tuple canonical form (t:(...)) 이어야 한다.
    # 평탄화 ``"s:('DOC100', 0)"`` 형태가 나오면 invariant 위반.
    for ref in rec_case.row_refs:
        assert ref.index_label.startswith("t:("), (
            f"index_label must be tuple canonical (t:(...)), got: {ref.index_label!r}"
        )
        assert (
            "(" not in ref.index_label.split("t:", 1)[1].split(")", 1)[0] or "|" in ref.index_label
        ), f"index_label must contain pipe-separated tuple parts, got: {ref.index_label!r}"
        # raw stringified tuple ``s:('DOC100', 0)`` 같은 형태는 거부.
        assert "s:('" not in ref.index_label
        assert ", " not in ref.index_label  # tuple repr 의 ", " 흔적 거부


def test_legacy_reciprocal_artifact_falls_back_to_label_lookup():
    """row_position 없는 구 schema entry 도 legacy fallback path 통과.

    invariant #59 보강: 새 호출자는 position 사용 권장 (MultiIndex 안전).
    legacy 호출자 (구 schema 의 row_index 만 있음) 도 graceful — _make_ref 의
    label-based lookup 으로 처리. 단 MultiIndex 환경 보장은 새 호출자만 (#59).
    """
    df = _make_df()  # _make_df 의 index 가 단일 RangeIndex 이라 label==position
    result = _make_result(ic_pair_artifact=_legacy_reciprocal_artifact())
    cases = build_intercompany_cases(batch_id="b1", detection_result=result, df=df)
    assert len(cases) == 1
    rec_case = cases[0]
    assert rec_case.ic_role == "reciprocal_flow"
    # legacy entry 는 single row_index → row_refs 는 단일 ref tuple.
    assert len(rec_case.row_refs) == 1
