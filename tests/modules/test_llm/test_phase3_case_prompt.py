from __future__ import annotations

from src.llm.phase3_case_prompt import (
    build_phase3_selected_case_inputs,
    phase3_fact_grounding_system_prompt,
)
from src.models.phase1_case import CaseDocumentRef
from tests.modules.test_services.test_phase2_case_contract import _phase1_result


def test_build_phase3_selected_case_inputs_uses_case_and_overlay_only():
    phase1 = _phase1_result()
    phase1.cases[0].is_top_case = True
    overlays = [
        {
            "phase1_case_id": "case_control_failure_00001",
            "phase2_family_scores": {"relational": 0.7},
            "phase2_inference_contract": {"required_models": ["relational"]},
            "phase2_training_report_id": "train_001",
        }
    ]

    payloads = build_phase3_selected_case_inputs(
        phase1,
        phase2_case_overlays=overlays,
        related_entity_risk_by_case={
            "case_control_failure_00001": {"counterparty_recent_case_count": 3}
        },
    )

    payload = payloads[0]
    assert payload["case_id"] == "case_control_failure_00001"
    assert payload["phase2_family_scores"] == {"relational": 0.7}
    assert payload["phase2_training_report_id"] == "train_001"
    assert "top_documents" in payload
    assert payload["related_entity_risk"] == {"counterparty_recent_case_count": 3}
    # Phase D 신규 필드 — 누락된 overlay 도 default 값으로 노출
    assert payload["phase2_family_contributions"] == []
    assert payload["phase2_top_family"] is None
    assert payload["phase2_coverage_breadth_q95"] == 0
    assert payload["phase2_max_family_ecdf"] is None
    assert payload["phase2_max_evidence_tier"] is None
    assert payload["phase2_lane_membership"] == []
    assert payload["phase2_coverage_gap_families"] == []


def test_phase3_payload_carries_family_contributions_and_lane_membership():
    """overlay 에 신규 필드가 채워져 있으면 prompt payload 가 그대로 노출."""
    phase1 = _phase1_result()
    phase1.cases[0].is_top_case = True
    overlays = [
        {
            "phase1_case_id": "case_control_failure_00001",
            "phase2_family_scores": {"unsupervised": 0.97, "duplicate": 0.6},
            "family_contributions": [
                {
                    "family": "duplicate",
                    "score": 0.6,
                    "ecdf": 0.95,
                    "role": "active-ranker",
                    "evidence_tier": "strong",
                    "evidence_tier_weight": 3,
                    "sub_detectors": [{"code": "L2-03a", "label": "exact_duplicate_amount"}],
                },
            ],
            "top_family": "duplicate",
            "coverage_breadth_q95": 2,
            "max_family_ecdf": 0.99,
            "max_evidence_tier": "strong",
            "lane_membership": ["duplicate", "unsupervised"],
            "coverage_gap_families": ["intercompany"],
        }
    ]

    payloads = build_phase3_selected_case_inputs(phase1, phase2_case_overlays=overlays)
    payload = payloads[0]

    assert payload["phase2_top_family"] == "duplicate"
    assert payload["phase2_max_evidence_tier"] == "strong"
    assert payload["phase2_coverage_breadth_q95"] == 2
    assert payload["phase2_max_family_ecdf"] == 0.99
    assert "duplicate" in payload["phase2_lane_membership"]
    assert "intercompany" in payload["phase2_coverage_gap_families"]
    # narrator 가 citation 으로 쓰는 contribution sub_detectors 보존
    assert payload["phase2_family_contributions"][0]["evidence_tier"] == "strong"
    assert payload["phase2_family_contributions"][0]["sub_detectors"][0]["code"] == "L2-03a"
    assert "priority_rank" not in payload
    assert "priority_score" not in payload
    assert "phase2_adjusted_priority" not in payload


def test_phase3_related_entity_risk_is_conditionally_omitted():
    phase1 = _phase1_result()
    phase1.cases[0].secondary_tags = []
    payloads = build_phase3_selected_case_inputs(
        phase1,
        phase2_case_overlays=[],
        related_entity_risk_by_case={
            "case_control_failure_00001": {"counterparty_recent_case_count": 3}
        },
    )

    assert "related_entity_risk" not in payloads[0]


def test_phase3_limits_and_ranks_case_documents():
    phase1 = _phase1_result()
    phase1.cases[0].documents = [
        CaseDocumentRef(
            document_id=f"D{i:02d}",
            amount=float(i * 1_000),
            matched_rules=["L1-05"] if i % 2 == 0 else [],
            evidence_tags=["control_failure"] if i % 3 == 0 else [],
        )
        for i in range(30)
    ]

    payloads = build_phase3_selected_case_inputs(
        phase1,
        max_documents_per_case=99,
    )

    documents = payloads[0]["top_documents"]
    assert len(documents) == 20
    assert [doc["document_id"] for doc in documents[:3]] == ["D29", "D28", "D27"]


def test_phase3_related_entity_risk_includes_duplicate_statistical_and_degree_context():
    phase1 = _phase1_result()
    phase1.cases[0].primary_theme = "duplicate_or_outflow"
    payloads = build_phase3_selected_case_inputs(
        phase1,
        related_entity_risk_by_case={
            "case_control_failure_00001": {"summary": "multi-process vendor"}
        },
    )
    assert "related_entity_risk" in payloads[0]

    phase1.cases[0].primary_theme = "control_failure"
    phase1.cases[0].secondary_tags = []
    payloads = build_phase3_selected_case_inputs(
        phase1,
        related_entity_risk_by_case={
            "case_control_failure_00001": {"degree": 2, "summary": "degree > 1"}
        },
    )
    assert "related_entity_risk" in payloads[0]


def test_phase3_fact_grounding_system_prompt_contains_constraints():
    prompt = phase3_fact_grounding_system_prompt()

    assert "Use only the selected case input" in prompt
    assert "Do not infer external accounting standards" in prompt
    assert "Do not conclude fraud" in prompt
    assert "Do not reorder cases" in prompt
    assert "Do not assign new priority" in prompt


def test_phase3_system_prompt_contains_unsupervised_guard():
    """unsupervised (VAE / ML02) 결과는 '통계적 이상치' 어휘만 허용."""
    prompt = phase3_fact_grounding_system_prompt()

    assert "PHASE2 unsupervised family" in prompt
    assert "통계적 이상치" in prompt
    assert "statistical outlier" in prompt
    # 어휘 금지 키워드들이 가드 문장에서 명시되어야 함
    assert "위반 확정" in prompt
    assert "부정 확정" in prompt
    assert "오류 확정" in prompt


def test_phase3_system_prompt_treats_data_quality_as_review_item_not_conclusion():
    prompt = phase3_fact_grounding_system_prompt()

    assert "Data quality and integrity blockers are not fraud or violation conclusions" in prompt
    assert "분석 제한" in prompt
    assert "데이터 품질 검토 항목" in prompt
    assert "evidence reliability/completeness review items" in prompt


def test_phase3_payload_carries_unsupervised_explanation_features():
    """family_contributions 의 unsupervised entry 에 explanation_features 가 있으면
    payload `phase2_unsupervised_explanation` 에 그대로 노출되어야 한다."""
    phase1 = _phase1_result()
    phase1.cases[0].is_top_case = True
    overlays = [
        {
            "phase1_case_id": "case_control_failure_00001",
            "phase2_family_scores": {"unsupervised": 0.97},
            "family_contributions": [
                {
                    "family": "unsupervised",
                    "score": 0.97,
                    "ecdf": 0.99,
                    "role": "active-ranker",
                    "evidence_tier": "ml_quantile",
                    "evidence_tier_weight": 0,
                    "evidence_type": "statistical_outlier",
                    "explanation_features": [
                        {
                            "feature": "num__posting_date_weekend",
                            "contrib": 0.55,
                            "tag": "unusual_timing",
                            "label_ko": "비정상 거래시점",
                            "evidence_type": "statistical_outlier",
                        }
                    ],
                    "sub_detectors": [],
                },
            ],
        }
    ]

    payloads = build_phase3_selected_case_inputs(phase1, phase2_case_overlays=overlays)
    payload = payloads[0]

    explanation = payload["phase2_unsupervised_explanation"]
    assert explanation["evidence_type"] == "statistical_outlier"
    assert explanation["features"][0]["tag"] == "unusual_timing"
    assert explanation["features"][0]["label_ko"] == "비정상 거래시점"


def test_phase3_payload_unsupervised_explanation_empty_when_no_unsupervised_entry():
    """unsupervised contribution 이 없으면 빈 dict 로 노출."""
    phase1 = _phase1_result()
    phase1.cases[0].is_top_case = True
    overlays = [
        {
            "phase1_case_id": "case_control_failure_00001",
            "family_contributions": [
                {
                    "family": "duplicate",
                    "score": 0.6,
                    "evidence_tier": "strong",
                    "sub_detectors": [{"code": "L2-03a"}],
                },
            ],
        }
    ]

    payloads = build_phase3_selected_case_inputs(phase1, phase2_case_overlays=overlays)

    assert payloads[0]["phase2_unsupervised_explanation"] == {}
