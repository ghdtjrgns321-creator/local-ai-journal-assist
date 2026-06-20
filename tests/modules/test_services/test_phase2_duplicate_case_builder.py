"""`build_duplicate_cases` 의 PHASE2 DuplicateCase 변환 계약 검증.

Why: v7-plan S2 invariant #11~17 — pair_artifact.top_pairs 를 DuplicateCase
tuple 로 변환할 때 evidence tier gate (strong/moderate) 통과 + canonical_refs
검증 + evidence_signature 가 case identity 만 포함하는지 확인.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from src.detection.base import DetectionResult
from src.models.phase2_case import DuplicateCase
from src.services.phase2_duplicate_case_builder import build_duplicate_cases
from src.services.phase2_ref_canonical import canonicalize_ref_key


def _make_df(*, with_optional_columns: bool = True) -> pd.DataFrame:
    """3-row GL fixture. optional column 포함/미포함 두 케이스 지원."""
    data: dict[str, list[Any]] = {
        "amount": [1000.0, 1000.0, 500.0],
    }
    if with_optional_columns:
        data["document_id"] = ["DOC001", "DOC002", "DOC003"]
        data["line_number"] = ["0001", "0002", "0003"]
        data["company_code"] = ["C01", "C01", "C02"]
    return pd.DataFrame(data, index=pd.Index([10, 11, 12]))


def _strong_features() -> dict[str, Any]:
    """strong tier 통과: same_partner + ref>=0.90 + amount>=0.98."""
    return {
        "same_partner": True,
        "reference_similarity": 0.95,
        "text_similarity": 0.50,
        "amount_similarity": 0.99,
    }


def _moderate_features() -> dict[str, Any]:
    """moderate tier 통과: same_partner + ref>=0.70 (text/amount strong 미달)."""
    return {
        "same_partner": True,
        "reference_similarity": 0.75,
        "text_similarity": 0.50,
        "amount_similarity": 0.50,
    }


def _weak_features() -> dict[str, Any]:
    """weak tier: same_partner=False → 무조건 weak."""
    return {
        "same_partner": False,
        "reference_similarity": 0.99,
        "text_similarity": 0.99,
        "amount_similarity": 0.99,
    }


def _make_result(
    *,
    top_pairs: list[dict[str, Any]] | None,
    include_pair_artifact: bool = True,
    metadata_extra: dict[str, Any] | None = None,
) -> DetectionResult:
    """duplicate track DetectionResult fixture."""
    metadata: dict[str, Any] = {}
    if metadata_extra:
        metadata.update(metadata_extra)
    if include_pair_artifact:
        metadata["pair_artifact"] = {
            "schema_version": 1,
            "top_pairs": top_pairs or [],
        }
    return DetectionResult(
        track_name="duplicate",
        flagged_indices=[],
        scores=pd.Series([0.0, 0.0, 0.0], index=[10, 11, 12]),
        rule_flags=[],
        details=pd.DataFrame(),
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# graceful fallback — 빈 입력
# ---------------------------------------------------------------------------


def test_empty_metadata_returns_empty_tuple():
    """metadata 자체가 비어도 (pair_artifact 없음) graceful fallback."""
    df = _make_df()
    result = _make_result(top_pairs=None, include_pair_artifact=False)
    cases = build_duplicate_cases(batch_id="b1", detection_result=result, df=df)
    assert cases == ()
    assert isinstance(cases, tuple)


def test_pair_artifact_missing_returns_empty_tuple():
    """metadata 에 다른 key 만 있고 pair_artifact 부재."""
    df = _make_df()
    result = _make_result(
        top_pairs=None,
        include_pair_artifact=False,
        metadata_extra={"other_key": "value"},
    )
    cases = build_duplicate_cases(batch_id="b1", detection_result=result, df=df)
    assert cases == ()


def test_top_pairs_empty_returns_empty_tuple():
    """pair_artifact 존재하지만 top_pairs 가 빈 list."""
    df = _make_df()
    result = _make_result(top_pairs=[])
    cases = build_duplicate_cases(batch_id="b1", detection_result=result, df=df)
    assert cases == ()
    diagnostics = result.metadata["duplicate_case_builder_diagnostics"]
    assert diagnostics["no_case_reason"] == "empty_pair_artifact_top_pairs"


# ---------------------------------------------------------------------------
# evidence tier gate (invariant #15)
# ---------------------------------------------------------------------------


def test_weak_tier_pairs_excluded():
    """weak tier 는 case 화하지 않음."""
    df = _make_df()
    result = _make_result(
        top_pairs=[
            {
                "rule_id": "L2-03a",
                "rule_source": "exact_duplicate_amount",
                "pair_score": 0.85,
                "left_index": 10,
                "right_index": 11,
                "features": _weak_features(),
            }
        ]
    )
    cases = build_duplicate_cases(batch_id="b1", detection_result=result, df=df)
    assert cases == ()
    diagnostics = result.metadata["duplicate_case_builder_diagnostics"]
    assert diagnostics["case_count"] == 0
    assert diagnostics["skipped_pair_counts"] == {"weak_pair_evidence_tier": 1}
    assert diagnostics["no_case_reason"] == "weak_pair_evidence_tier"


def test_strong_tier_pair_included():
    """strong tier 통과 시 DuplicateCase 1개 생성."""
    df = _make_df()
    result = _make_result(
        top_pairs=[
            {
                "rule_id": "L2-03a",
                "rule_source": "exact_duplicate_amount",
                "pair_score": 0.85,
                "left_index": 10,
                "right_index": 11,
                "features": _strong_features(),
            }
        ]
    )
    cases = build_duplicate_cases(batch_id="b1", detection_result=result, df=df)
    assert len(cases) == 1
    case = cases[0]
    assert isinstance(case, DuplicateCase)
    assert case.family == "duplicate"
    assert case.unit_type == "pair"
    assert case.pair_evidence_tier == "strong"
    assert case.evidence_tier == "strong"
    assert case.sub_rule == "L2-03a"
    assert case.family_score == pytest.approx(0.85)


def test_moderate_tier_pair_included():
    """moderate tier 도 case 화."""
    df = _make_df()
    result = _make_result(
        top_pairs=[
            {
                "rule_id": "L2-03b",
                "rule_source": "reference_duplicate",
                "pair_score": 0.70,
                "left_index": 10,
                "right_index": 12,
                "features": _moderate_features(),
            }
        ]
    )
    cases = build_duplicate_cases(batch_id="b1", detection_result=result, df=df)
    assert len(cases) == 1
    assert cases[0].pair_evidence_tier == "moderate"
    assert cases[0].sub_rule == "L2-03b"


# ---------------------------------------------------------------------------
# case_id / canonical_refs (invariant #12)
# ---------------------------------------------------------------------------


def test_case_id_uses_canonicalized_refs():
    """case_id 는 canonicalize_ref_key 결과 기반이며 ref 순서 무관 stable."""
    df = _make_df()
    pair_lr = {
        "rule_id": "L2-03a",
        "pair_score": 0.85,
        "left_index": 10,
        "right_index": 11,
        "features": _strong_features(),
    }
    pair_rl = {
        "rule_id": "L2-03a",
        "pair_score": 0.85,
        "left_index": 11,  # left/right 뒤집어도
        "right_index": 10,
        "features": _strong_features(),
    }
    cases_lr = build_duplicate_cases(
        batch_id="b1",
        detection_result=_make_result(top_pairs=[pair_lr]),
        df=df,
    )
    cases_rl = build_duplicate_cases(
        batch_id="b1",
        detection_result=_make_result(top_pairs=[pair_rl]),
        df=df,
    )
    # canonical_refs sorted → 동일 case_id (invariant #7)
    assert cases_lr[0].phase2_case_id == cases_rl[0].phase2_case_id
    # prefix 형식 확인
    assert cases_lr[0].phase2_case_id.startswith("p2_duplicate_pair_")


# ---------------------------------------------------------------------------
# evidence_signature (invariant #13)
# ---------------------------------------------------------------------------


def test_evidence_signature_contains_only_sub_rule():
    """evidence_signature 는 sub_rule 만 포함 — case identity 만."""
    df = _make_df()
    result = _make_result(
        top_pairs=[
            {
                "rule_id": "L2-03c",
                "pair_score": 0.99,
                "left_index": 10,
                "right_index": 11,
                "features": _strong_features(),
            }
        ]
    )
    cases = build_duplicate_cases(batch_id="b1", detection_result=result, df=df)
    # reason payload 에 signature 가 노출되지는 않지만, case_id 가 sub_rule 의존성을 가져야 함.
    # 별도 sub_rule 로 다시 만들면 case_id 변경 → signature 가 sub_rule 만 가지는 증거.
    case_a = cases[0]
    result_b = _make_result(
        top_pairs=[
            {
                "rule_id": "L2-03d",
                "pair_score": 0.99,
                "left_index": 10,
                "right_index": 11,
                "features": _strong_features(),
            }
        ]
    )
    cases_b = build_duplicate_cases(batch_id="b1", detection_result=result_b, df=df)
    case_b = cases_b[0]
    assert case_a.phase2_case_id != case_b.phase2_case_id


def test_evidence_signature_does_not_include_pair_score():
    """pair_score 만 다르고 다른 모든 값 동일하면 case_id 동일 — signature 에 score 부재."""
    df = _make_df()
    pair_low = {
        "rule_id": "L2-03a",
        "pair_score": 0.50,
        "left_index": 10,
        "right_index": 11,
        "features": _strong_features(),
    }
    pair_high = dict(pair_low)
    pair_high["pair_score"] = 0.95
    cases_low = build_duplicate_cases(
        batch_id="b1",
        detection_result=_make_result(top_pairs=[pair_low]),
        df=df,
    )
    cases_high = build_duplicate_cases(
        batch_id="b1",
        detection_result=_make_result(top_pairs=[pair_high]),
        df=df,
    )
    # signature 가 sub_rule 만 — pair_score 가 ID 에 영향 없어야 함.
    assert cases_low[0].phase2_case_id == cases_high[0].phase2_case_id
    # family_score 는 다름 (signature 와 무관, evidence payload).
    assert cases_low[0].family_score != cases_high[0].family_score


# ---------------------------------------------------------------------------
# phase1_case_refs default (invariant #17)
# ---------------------------------------------------------------------------


def test_phase1_case_refs_empty_by_default():
    """builder 출력은 항상 phase1_case_refs = () — linker S4 가 부착."""
    df = _make_df()
    result = _make_result(
        top_pairs=[
            {
                "rule_id": "L2-03a",
                "pair_score": 0.85,
                "left_index": 10,
                "right_index": 11,
                "features": _strong_features(),
            }
        ]
    )
    cases = build_duplicate_cases(batch_id="b1", detection_result=result, df=df)
    assert cases[0].phase1_case_refs == ()


# ---------------------------------------------------------------------------
# row_refs (df.index.get_loc 기반 row_position)
# ---------------------------------------------------------------------------


def test_row_refs_built_from_df_row_position():
    """left_ref / right_ref 가 df.index.get_loc(label) 결과로 채워짐."""
    df = _make_df(with_optional_columns=True)
    # df.index = [10, 11, 12] → label=11 의 position=1.
    result = _make_result(
        top_pairs=[
            {
                "rule_id": "L2-03a",
                "pair_score": 0.85,
                "left_index": 10,
                "right_index": 11,
                "features": _strong_features(),
            }
        ]
    )
    cases = build_duplicate_cases(batch_id="b1", detection_result=result, df=df)
    case = cases[0]
    assert case.left_ref is not None
    assert case.right_ref is not None
    assert case.left_ref.row_position == 0
    assert case.left_ref.index_label == "i:10"
    assert case.left_ref.document_id == "DOC001"
    assert case.left_ref.company_code == "C01"
    assert case.left_ref.line_number_key == canonicalize_ref_key("0001")
    assert case.right_ref.row_position == 1
    assert case.right_ref.index_label == "i:11"
    assert case.right_ref.document_id == "DOC002"
    # row_refs tuple 도 동일하게 채워져 있어야 함 (Phase2CaseBase contract).
    assert len(case.row_refs) == 2
    assert case.row_refs[0] is case.left_ref
    assert case.row_refs[1] is case.right_ref


# ---------------------------------------------------------------------------
# top_pairs 순서 무관 (invariant #7 의 일반화)
# ---------------------------------------------------------------------------


def test_id_stable_under_pair_order_in_top_pairs():
    """top_pairs 내 pair 순서가 바뀌어도 각 case 의 ID 는 동일."""
    df = _make_df()
    pair_a = {
        "rule_id": "L2-03a",
        "pair_score": 0.85,
        "left_index": 10,
        "right_index": 11,
        "features": _strong_features(),
    }
    pair_b = {
        "rule_id": "L2-03b",
        "pair_score": 0.70,
        "left_index": 10,
        "right_index": 12,
        "features": _moderate_features(),
    }
    cases_ab = build_duplicate_cases(
        batch_id="b1",
        detection_result=_make_result(top_pairs=[pair_a, pair_b]),
        df=df,
    )
    cases_ba = build_duplicate_cases(
        batch_id="b1",
        detection_result=_make_result(top_pairs=[pair_b, pair_a]),
        df=df,
    )
    ids_ab = {c.phase2_case_id for c in cases_ab}
    ids_ba = {c.phase2_case_id for c in cases_ba}
    assert ids_ab == ids_ba
    assert len(ids_ab) == 2
