from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from src.detection.base import DetectionResult
from src.models.phase2_case import Phase2CaseSet, UnsupervisedCase, make_row_ref
from src.services.phase2_case_family_aggregator import (
    build_phase2_case_family_overlay_inputs,
)
from tests.modules.test_services.test_phase2_case_contract import _phase1_result


def _result(
    track_name: str,
    scores: list[float],
    details: dict[str, list[Any]],
    *,
    metadata: dict | None = None,
) -> DetectionResult:
    score_series = pd.Series(scores, index=pd.RangeIndex(len(scores)), dtype=float)
    return DetectionResult(
        track_name=track_name,
        flagged_indices=score_series[score_series > 0].index.tolist(),
        scores=score_series,
        rule_flags=[],
        details=pd.DataFrame(details, index=score_series.index),
        metadata=metadata or {},
    )


def test_build_phase2_case_family_overlay_inputs_maps_unsupervised_to_vae_tier_code():
    df = pd.DataFrame({"document_id": ["D1", "D2", "D3"]})
    phase1 = _phase1_result()
    unsupervised = _result("ml_unsupervised", [0.1, 0.8, 0.0], {"ML02": [0.1, 0.8, 0.0]})

    inputs = build_phase2_case_family_overlay_inputs(df, [unsupervised], phase1)

    case_id = "case_control_failure_00001"
    assert inputs.family_scores_by_case[case_id]["unsupervised"] == 0.8
    assert inputs.family_top_subdetectors_by_case[case_id]["unsupervised"] == [
        ("VAE-01", "audit_vae_reconstruction")
    ]


def test_unsupervised_explanation_features_propagated_from_details():
    """ML02_top_feature_* details 가 case 의 max-score row 에서 reason tag 로 변환되어
    family_explanation_features_by_case 에 부착되어야 한다 (overlay surface 전용).
    """
    df = pd.DataFrame({"document_id": ["D1", "D2", "D3"]})
    phase1 = _phase1_result()
    # row 0 (D1) 이 max score (0.9), top feature 는 posting_date_weekend
    unsupervised = _result(
        "ml_unsupervised",
        [0.9, 0.4, 0.0],
        {
            "ML02": [0.9, 0.4, 0.0],
            "ML02_top_feature_1": ["num__posting_date_weekend", "num__amount_z", ""],
            "ML02_top_feature_1_contrib": [0.55, 0.21, 0.0],
            "ML02_top_feature_2": ["num__round_amount", "cat_low__counterparty", ""],
            "ML02_top_feature_2_contrib": [0.32, 0.18, 0.0],
            "ML02_top_feature_3": ["num__manual_entry_flag", "num__posting_lag_days", ""],
            "ML02_top_feature_3_contrib": [0.11, 0.09, 0.0],
        },
    )

    inputs = build_phase2_case_family_overlay_inputs(df, [unsupervised], phase1)

    case_id = "case_control_failure_00001"
    features = inputs.family_explanation_features_by_case[case_id]["unsupervised"]
    assert len(features) == 3
    # row 0 max score → posting_date_weekend / round_amount / manual_entry_flag
    assert features[0]["feature"] == "num__posting_date_weekend"
    assert features[0]["tag"] == "unusual_timing"
    assert features[0]["label_ko"] == "비정상 거래시점"
    assert features[0]["evidence_type"] == "statistical_outlier"
    assert features[0]["contrib"] == pytest.approx(0.55)
    assert features[1]["tag"] == "round_amount_deviation"
    assert features[2]["tag"] == "manual_entry_context"


def test_unsupervised_explanation_features_empty_when_no_details():
    """ML02_top_feature_* details 가 없으면 explanation_features 가 빈 dict 로 graceful fallback."""
    df = pd.DataFrame({"document_id": ["D1", "D2", "D3"]})
    phase1 = _phase1_result()
    unsupervised = _result("ml_unsupervised", [0.5, 0.2, 0.0], {"ML02": [0.5, 0.2, 0.0]})

    inputs = build_phase2_case_family_overlay_inputs(df, [unsupervised], phase1)

    # family_scores 는 정상, explanation 만 빈 상태.
    case_id = "case_control_failure_00001"
    assert inputs.family_scores_by_case[case_id]["unsupervised"] == 0.5
    assert case_id not in inputs.family_explanation_features_by_case


def test_unsupervised_explanation_unknown_feature_falls_back_to_pattern_outlier():
    """매핑되지 않은 feature 명은 feature_pattern_outlier 로 fallback."""
    df = pd.DataFrame({"document_id": ["D1", "D2"]})
    phase1 = _phase1_result()
    unsupervised = _result(
        "ml_unsupervised",
        [0.7, 0.0],
        {
            "ML02": [0.7, 0.0],
            "ML02_top_feature_1": ["num__unmapped_xyz", ""],
            "ML02_top_feature_1_contrib": [0.4, 0.0],
        },
    )

    inputs = build_phase2_case_family_overlay_inputs(df, [unsupervised], phase1)

    case_id = "case_control_failure_00001"
    features = inputs.family_explanation_features_by_case[case_id]["unsupervised"]
    assert features[0]["tag"] == "feature_pattern_outlier"
    assert features[0]["label_ko"] == "피처 패턴 이상"


def test_unsupervised_document_case_context_overrides_row_surface_for_overlay():
    """P3: document-case context is the overlay source, not row-native ML02 details.

    The document case keeps family_score as raw max and exposes corroboration/context
    as display-only metadata.
    """
    df = pd.DataFrame({"document_id": ["D1", "D1", "D2"]})
    phase1 = _phase1_result()
    row0 = make_row_ref(
        row_position=0,
        index_label=0,
        document_id="D1",
        raw_line_number="1",
        company_code="C01",
    )
    row1 = make_row_ref(
        row_position=1,
        index_label=1,
        document_id="D1",
        raw_line_number="2",
        company_code="C01",
    )
    document_case = UnsupervisedCase(
        phase2_case_id="p2_unsupervised_document_d1",
        batch_id="bid-1",
        family="unsupervised",
        unit_type="document",
        row_refs=(row0, row1),
        evidence_tier="ml_quantile",
        case_generation_reason={"gate": "unsupervised_ecdf"},
        family_score=0.97,
        family_ecdf=0.99,
        anomaly_score=0.97,
        top_features=(
            {
                "feature_id": "num__posting_date_weekend",
                "contrib": 0.55,
                "tag": "unusual_timing",
                "label_ko": "비정상 거래시점",
                "evidence_type": "statistical_outlier",
            },
        ),
        max_score_top_features=(
            {
                "feature_id": "num__amount_z",
                "contrib": 0.44,
                "tag": "amount_tail",
                "label_ko": "금액 tail",
                "evidence_type": "statistical_outlier",
            },
        ),
        document_id="D1",
        evidence_row_count=2,
        top_score_mean=0.91,
        score_spread=0.12,
        max_score_row_ref=row1,
        amount_tail_context=0.8,
        period_end_context=0.7,
        account_rarity_context=0.25,
        process_rarity_context=0.5,
        repeated_normal_pressure=0.0,
    )
    case_set = Phase2CaseSet(unsupervised_cases=(document_case,))
    unsupervised = _result(
        "ml_unsupervised",
        [0.2, 0.3, 0.0],
        {
            "ML02": [0.2, 0.3, 0.0],
            "ML02_top_feature_1": ["row_native_should_not_win", "row_native_2", ""],
        },
    )

    inputs = build_phase2_case_family_overlay_inputs(
        df,
        [unsupervised],
        phase1,
        case_set=case_set,
    )

    case_id = "case_control_failure_00001"
    assert inputs.family_scores_by_case[case_id]["unsupervised"] == pytest.approx(0.97)
    assert inputs.family_ecdf_by_case[case_id]["unsupervised"] == pytest.approx(0.99)
    features = inputs.family_explanation_features_by_case[case_id]["unsupervised"]
    assert features[0]["feature_id"] == "num__posting_date_weekend"
    assert features[0]["feature"] == "num__posting_date_weekend"
    context = inputs.family_document_context_by_case[case_id]["unsupervised"]
    assert context["unit_type"] == "document"
    assert context["evidence_row_count"] == 2
    assert context["top_score_mean"] == pytest.approx(0.91)
    assert context["score_spread"] == pytest.approx(0.12)
    assert context["amount_tail_context"] == pytest.approx(0.8)
    assert context["period_end_context"] == pytest.approx(0.7)
    assert context["account_rarity_context"] == pytest.approx(0.25)
    assert context["process_rarity_context"] == pytest.approx(0.5)
    assert context["repeated_normal_pressure"] == pytest.approx(0.0)
    assert "document_id" not in context
    assert "max_score_row_ref" not in context
    assert context["reason_tags"] == ["unusual_timing"]


def test_intercompany_internal_prob_columns_emit_subdetectors():
    """PHASE2 internal probability column 4개 (`ic_reciprocal_flow_prob` /
    `ic_amount_prob` / `ic_unmatched_prob` / `ic_timing_prob`) 는
    phase2_subdetector_tiers.yaml 에 등록됐으므로 sub_detectors entry 로 노출되어
    lane sort ic_role_priority 차원에서 evidence_role 분리가 가능해야 한다
    (2026-05-25 옵션 2 적용, docs/spec/PHASE2_INTERFACE_DESIGN.md §IC role priority).
    """
    df = pd.DataFrame({"document_id": ["D1", "D1", "D2"]})
    phase1 = _phase1_result()
    intercompany = _result(
        "intercompany",
        [0.6, 0.0, 0.0],
        {"ic_amount_prob": [0.6, 0.0, 0.0]},
    )

    inputs = build_phase2_case_family_overlay_inputs(df, [intercompany], phase1)

    case_id = "case_control_failure_00001"
    # family score 는 정상 기여
    assert inputs.family_scores_by_case[case_id]["intercompany"] == 0.6
    # sub_detectors 에 IC internal prob column 노출 (등록 후)
    family_codes = inputs.family_top_subdetectors_by_case.get(case_id, {}).get("intercompany", [])
    assert ("ic_amount_prob", "ic_amount_prob") in family_codes


def test_intercompany_registered_codes_emit_canonical_and_internal_subdetectors():
    """IC01~03 canonical code + IC internal prob column 이 모두 emit 되어야 한다 (회귀).

    옵션 2 적용 후 IC family 의 4개 internal prob column 도 tier registry 에 등록됨에
    따라 `_top_subdetectors_for_case` 화이트리스트를 통과한다.
    """
    df = pd.DataFrame({"document_id": ["D1", "D1", "D2"]})
    phase1 = _phase1_result()
    intercompany = _result(
        "intercompany",
        [0.6, 0.0, 0.0],
        {
            "IC01": [0.6, 0.0, 0.0],
            "ic_unmatched_prob": [0.3, 0.0, 0.0],
        },
    )

    inputs = build_phase2_case_family_overlay_inputs(df, [intercompany], phase1)

    case_id = "case_control_failure_00001"
    family_codes = inputs.family_top_subdetectors_by_case.get(case_id, {}).get("intercompany", [])
    assert ("IC01", "IC01") in family_codes
    assert ("ic_unmatched_prob", "ic_unmatched_prob") in family_codes


def test_build_phase2_case_family_overlay_inputs_keeps_ic01_review_only_sidecar():
    df = pd.DataFrame({"document_id": ["D1", "D1", "D2"]})
    phase1 = _phase1_result()
    intercompany = _result(
        "intercompany",
        [0.0, 0.0, 0.0],
        {"IC01": [0.0, 0.0, 0.0]},
        metadata={
            "row_sidecar": {
                "ic01_evidence_level": pd.Series(["review", "", ""], index=pd.RangeIndex(3)),
                "ic01_review_reason": pd.Series(
                    ["missing_partner", "", ""],
                    index=pd.RangeIndex(3),
                ),
            }
        },
    )

    inputs = build_phase2_case_family_overlay_inputs(df, [intercompany], phase1)

    case_id = "case_control_failure_00001"
    assert case_id not in inputs.family_scores_by_case
    assert inputs.family_review_only_by_case[case_id]["intercompany"] == {
        "review_only_count": 1,
        "review_reasons": ["missing_partner"],
    }
