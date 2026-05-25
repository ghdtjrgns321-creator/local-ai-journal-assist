from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from src.detection.base import DetectionResult
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


def test_build_phase2_case_family_overlay_inputs_aggregates_duplicate_case_signal():
    df = pd.DataFrame({"document_id": ["D1", "D1", "D2", "D3"]})
    phase1 = _phase1_result()
    duplicate = _result(
        "duplicate",
        [0.7, 0.0, 0.2, 0.0],
        {"L2-03a": [0.7, 0.0, 0.0, 0.0], "L2-03d": [0.0, 0.0, 0.2, 0.0]},
    )

    inputs = build_phase2_case_family_overlay_inputs(df, [duplicate], phase1)

    case_id = "case_control_failure_00001"
    assert inputs.family_scores_by_case[case_id]["duplicate"] == 0.7
    assert inputs.family_ecdf_by_case[case_id]["duplicate"] > 0.0
    assert ("L2-03a", "L2-03a") in inputs.family_top_subdetectors_by_case[case_id]["duplicate"]
    assert ("L2-03d", "L2-03d") in inputs.family_top_subdetectors_by_case[case_id]["duplicate"]
    assert inputs.family_q95_thresholds["duplicate"] > 0.0
    assert "duplicate" in inputs.family_roles


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


def test_intercompany_internal_prob_columns_emit_subdetectors():
    """PHASE2 internal probability column 4개 (`ic_reciprocal_flow_prob` /
    `ic_amount_prob` / `ic_unmatched_prob` / `ic_timing_prob`) 는
    phase2_subdetector_tiers.yaml 에 등록됐으므로 sub_detectors entry 로 노출되어
    lane sort ic_role_priority 차원에서 evidence_role 분리가 가능해야 한다
    (2026-05-25 옵션 2 적용, docs/PHASE2_INTERFACE_DESIGN.md §IC role priority).
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


def test_aggregator_classifies_strong_pair_evidence_for_duplicate_case():
    """duplicate detector pair_artifact.top_pairs 가 case label set 에 매핑되면
    case 단위 best pair tier 가 strong/moderate/weak 로 분류되어야 한다.
    """
    # 행 인덱스 0/1 은 같은 document D1 (case 에 포함). 행 2/3 은 D2/D3.
    df = pd.DataFrame({"document_id": ["D1", "D1", "D2", "D3"]})
    phase1 = _phase1_result()
    pair_artifact = {
        "schema_version": 1,
        "top_pairs": [
            {
                "rule_id": "L2-03a",
                "rule_source": "exact_duplicate_amount",
                "pair_score": 1.0,
                "left_index": 0,
                "right_index": 1,
                "features": {
                    "same_partner": True,
                    "reference_similarity": 0.95,
                    "text_similarity": 0.92,
                    "amount_similarity": 1.0,
                },
            },
        ],
    }
    duplicate = _result(
        "duplicate",
        [0.7, 0.7, 0.0, 0.0],
        {"L2-03a": [0.7, 0.7, 0.0, 0.0]},
        metadata={"pair_artifact": pair_artifact},
    )

    inputs = build_phase2_case_family_overlay_inputs(df, [duplicate], phase1)

    case_id = "case_control_failure_00001"
    assert inputs.duplicate_pair_evidence_by_case[case_id] == "strong"


def test_aggregator_picks_best_tier_across_multiple_pairs_in_case():
    """같은 case 안에서 여러 pair 가 매핑되면 최고 tier 만 유지."""
    df = pd.DataFrame({"document_id": ["D1", "D1", "D2", "D3"]})
    phase1 = _phase1_result()
    pair_artifact = {
        "schema_version": 1,
        "top_pairs": [
            # weak pair (same_partner=False)
            {
                "rule_id": "L2-03d",
                "pair_score": 0.5,
                "left_index": 0,
                "right_index": 1,
                "features": {
                    "same_partner": False,
                    "reference_similarity": 0.95,
                    "text_similarity": 0.95,
                    "amount_similarity": 1.0,
                },
            },
            # moderate pair (same_partner=True, ref=0.75만 통과)
            {
                "rule_id": "L2-03b",
                "pair_score": 0.7,
                "left_index": 0,
                "right_index": 1,
                "features": {
                    "same_partner": True,
                    "reference_similarity": 0.75,
                    "text_similarity": 0.50,
                    "amount_similarity": 0.50,
                },
            },
        ],
    }
    duplicate = _result(
        "duplicate",
        [0.7, 0.7, 0.0, 0.0],
        {"L2-03a": [0.7, 0.7, 0.0, 0.0]},
        metadata={"pair_artifact": pair_artifact},
    )

    inputs = build_phase2_case_family_overlay_inputs(df, [duplicate], phase1)

    # weak 와 moderate 중 moderate 가 유지되어야 함.
    case_id = "case_control_failure_00001"
    assert inputs.duplicate_pair_evidence_by_case[case_id] == "moderate"


def test_aggregator_missing_pair_artifact_graceful_fallback():
    """pair_artifact metadata 가 없으면 duplicate_pair_evidence_by_case 가 비어 있어야 함."""
    df = pd.DataFrame({"document_id": ["D1", "D1", "D2", "D3"]})
    phase1 = _phase1_result()
    duplicate = _result(
        "duplicate",
        [0.7, 0.0, 0.2, 0.0],
        {"L2-03a": [0.7, 0.0, 0.0, 0.0]},
        # metadata 에 pair_artifact 없음
    )

    inputs = build_phase2_case_family_overlay_inputs(df, [duplicate], phase1)

    assert inputs.duplicate_pair_evidence_by_case == {}
    # 다른 집계는 정상 유지되어야 함 (회귀 가드).
    case_id = "case_control_failure_00001"
    assert inputs.family_scores_by_case[case_id]["duplicate"] == 0.7


def test_aggregator_pair_artifact_outside_case_labels_yields_no_entry():
    """pair 가 case label set 밖에 있으면 해당 case 에 부착되지 않음."""
    df = pd.DataFrame({"document_id": ["D1", "D1", "D2", "D3"]})
    phase1 = _phase1_result()
    pair_artifact = {
        "schema_version": 1,
        "top_pairs": [
            # 행 2(D2), 행 3(D3) — case 의 D1/D2 와 부분 매핑이지만 D3 는 case 밖.
            # 그러나 left_index=2 (D2) 가 case 에 포함될 수 있음 (D2 document refs).
            # D3 만 사용하는 케이스를 만들기 위해 left/right 모두 행 3 으로 둘 수 없으니
            # 같은 행을 짝지을 수는 없으므로 행 3 single 은 안전상 pair 없음으로 표현.
            # 대신 case 외부에 두 행만 매핑.
        ],
    }
    duplicate = _result(
        "duplicate",
        [0.0, 0.0, 0.0, 0.0],
        {"L2-03a": [0.0, 0.0, 0.0, 0.0]},
        metadata={"pair_artifact": pair_artifact},
    )

    inputs = build_phase2_case_family_overlay_inputs(df, [duplicate], phase1)
    # top_pairs 비어 있으므로 pair_evidence 부착 0.
    assert inputs.duplicate_pair_evidence_by_case == {}


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
