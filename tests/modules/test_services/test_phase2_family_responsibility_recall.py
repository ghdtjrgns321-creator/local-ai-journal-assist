from __future__ import annotations

import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.scripts import measure_phase2_family_responsibility_recall_fixed5_20260530 as m

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "artifacts" / "phase2_family_responsibility_recall_fixed5_20260530.json"
TRUTH_CSV = ROOT.joinpath(
    "data",
    "journal",
    "primary",
    "datasynth_manipulation_v7_candidate_fixed5_normalcal5",
    "labels",
    "manipulated_entry_truth.csv",
)


def _payload() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def _truth_ids() -> list[str]:
    with TRUTH_CSV.open("r", encoding="utf-8", newline="") as fh:
        return [row["document_id"] for row in csv.DictReader(fh)]


def _walk_keys(value) -> list[str]:
    if isinstance(value, dict):
        keys = [str(key) for key in value]
        for child in value.values():
            keys.extend(_walk_keys(child))
        return keys
    if isinstance(value, list):
        keys: list[str] = []
        for child in value:
            keys.extend(_walk_keys(child))
        return keys
    return []


def test_responsibility_artifact_owner_distribution_and_policy_flags():
    payload = _payload()

    assert payload["diagnostic_only"] is True
    assert payload["production_ranking_gate_fusion_changed"] is False
    assert payload["portfolio_truth_case_count"] == 620
    assert payload["owner_distribution"] == {
        "phase1": 586,
        "intercompany": 34,
        "relational": 139,
        "duplicate": 92,
        "timeseries": 113,
        "unsupervised": 289,
        "no_clear_owner": 0,
    }
    assert payload["multi_owner_count"] == 520
    assert payload["no_clear_owner_count"] == 0
    assert payload["owner_confidence_distribution"] == {"high": 155, "medium": 465}
    assert len(payload["sanitized_truth_summaries"]) == 620
    assert len(payload["owner_assignments"]) == 620


def test_owner_assignment_allows_multi_owner_and_no_clear_owner_schema():
    multi = m.OwnerAssignmentModel(
        truth_case_hash="truth_test",
        expected_owners=["relational", "phase1"],
        scenario_groups=["mixed"],
        owner_confidence="medium",
        no_clear_owner_reason="multiple_equal_owners",
        assignment_basis=["scenario_metadata"],
        audit_rationale="semantic multi-owner assignment",
    )
    assert multi.expected_owners == ["phase1", "relational"]

    no_owner = m.OwnerAssignmentModel(
        truth_case_hash="truth_test",
        expected_owners=[],
        scenario_groups=["unmapped"],
        owner_confidence="low",
        no_clear_owner_reason="no_family_semantic_match",
        assignment_basis=["scenario_metadata"],
        audit_rationale="no clear owner",
    )
    assert no_owner.expected_owners == ["no_clear_owner"]

    with pytest.raises(ValueError):
        m.OwnerAssignmentModel(
            truth_case_hash="truth_test",
            expected_owners=["no_clear_owner", "phase1"],
            scenario_groups=["bad"],
            owner_confidence="low",
            no_clear_owner_reason="mixed_signal",
            assignment_basis=["scenario_metadata"],
            audit_rationale="invalid mixed no-owner assignment",
        )


def test_artifact_has_no_raw_identifier_leakage_or_forbidden_identifier_keys():
    payload = _payload()
    text = json.dumps(payload, ensure_ascii=False)
    forbidden_keys = {
        "document_id",
        "document_ids",
        "raw_document_id",
        "raw_document_ids",
        "row_id",
        "row_ids",
        "raw_row_id",
        "raw_row_ids",
        "index_label",
        "raw_index_label",
        "phase2_case_id",
        "phase2_case_ids",
    }

    assert all(raw_id not in text for raw_id in _truth_ids())
    assert forbidden_keys.isdisjoint({key.lower() for key in _walk_keys(payload)})
    assert payload["fitting_leakage_guard"] == {
        "owner_assignment_detector_output_inspection": "not_used_by_construction",
        "owner_assignment_score_rank_inspection": "not_used_by_construction",
        "owner_assignment_matched_result_inspection": "not_used_by_construction",
        "raw_identifier_leak_count": 0,
        "forbidden_identifier_key_count": 0,
        "forbidden_identifier_keys": [],
        "phase2_case_id_like_token_count": 0,
        "no_clear_owner_allowed": True,
        "multi_owner_assignment_allowed": True,
        "owner_assignment_artifact_independent_of_recall_result_artifact": True,
    }


def test_portfolio_and_owner_set_recall_are_separated():
    payload = _payload()
    portfolio = payload["portfolio_contribution"]
    owner_target = payload["owner_set_target_recall"]

    assert portfolio["denominator_truth_docs"] == 620
    assert portfolio["phase1"]["immediate"]["matched"] == 264
    assert portfolio["phase1"]["candidate_or_higher"]["matched"] == 544
    assert portfolio["phase2_native_top500"]["intercompany"] == {
        "matched": 34,
        "recall": 34 / 620,
    }
    assert owner_target["intercompany"]["owner_truth_docs"] == 34
    assert owner_target["intercompany"]["intercompany_matched_owner_docs"] == 34
    assert owner_target["intercompany"]["recall_by_matching_family_on_owner_set"] == 1.0
    assert owner_target["duplicate"]["owner_truth_docs"] == 92
    assert owner_target["duplicate"]["duplicate_matched_owner_docs"] == 22
    assert owner_target["duplicate"]["recall_by_matching_family_on_owner_set"] == 22 / 92
    assert owner_target["timeseries"]["owner_truth_docs"] == 113
    assert owner_target["timeseries"]["timeseries_matched_owner_docs"] == 0


def test_cross_owner_and_phase1_action_tier_uplift_sections_are_present():
    payload = _payload()
    cross = payload["cross_owner_evidence_contribution"]
    outside = payload["phase2_outside_phase1_action_tiers"]

    assert cross["intercompany"]["matched_docs_where_family_is_expected_owner"] == 34
    assert cross["relational"] == {
        "matched_docs_where_family_is_expected_owner": 17,
        "matched_docs_where_family_is_not_owner_secondary_evidence": 2,
        "matched_docs_with_no_clear_owner": 0,
    }
    assert outside["intercompany"]["outside_phase1_immediate_high"] == 32
    assert outside["relational"]["outside_phase1_review_or_higher_high_medium"] == 122
    assert outside["duplicate"]["outside_phase1_candidate_or_higher_high_medium_low"] == 0
    assert outside["unsupervised"]["outside_phase1_immediate_high"] == 13


def test_llm_assisted_path_uses_structured_output_and_validates_result():
    summary = {
        "truth_case_hash": "truth_fake",
        "datasynth_scenario": "circular_related_party_transaction",
    }
    parsed = m.OwnerAssignmentModel(
        truth_case_hash="truth_fake",
        expected_owners=["intercompany", "relational"],
        scenario_groups=["intercompany_reciprocal"],
        owner_confidence="high",
        no_clear_owner_reason="none",
        assignment_basis=["scenario_metadata"],
        audit_rationale="sanitized semantics only",
    )

    class FakeResponses:
        def __init__(self) -> None:
            self.calls = []

        def parse(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(
                output=[
                    SimpleNamespace(
                        type="message",
                        content=[SimpleNamespace(type="output_text", parsed=parsed)],
                    )
                ]
            )

    fake_responses = FakeResponses()
    fake_client = SimpleNamespace(responses=fake_responses)

    assignment = m.assign_owner_llm_assisted(summary, client=fake_client, model="fake-model")

    assert assignment.expected_owners == ["intercompany", "relational"]
    assert "llm_semantic_label" in assignment.assignment_basis
    assert fake_responses.calls[0]["text_format"] is m.OwnerAssignmentModel
    assert "detector output" in fake_responses.calls[0]["input"][0]["content"]


def test_llm_invalid_output_falls_back_to_deterministic_assignment():
    summary = {
        "truth_case_hash": "truth_fake",
        "datasynth_scenario": "period_end_adjustment_manipulation",
        "has_period_end_context": True,
    }
    invalid = m.OwnerAssignmentModel(
        truth_case_hash="truth_fake",
        expected_owners=["timeseries"],
        scenario_groups=["timing"],
        owner_confidence="high",
        no_clear_owner_reason="none",
        assignment_basis=["scenario_metadata"],
        audit_rationale="uses detector score",
    )

    class FakeResponses:
        def parse(self, **_kwargs):
            return SimpleNamespace(
                output=[
                    SimpleNamespace(
                        type="message",
                        content=[SimpleNamespace(type="output_text", parsed=invalid)],
                    )
                ]
            )

    assignments, meta = m.build_owner_assignments(
        [summary],
        mode="llm",
        client=SimpleNamespace(responses=FakeResponses()),
    )

    assert meta["actual_mode"] == "deterministic_rule_only"
    assert meta["llm_status"] == "fallback_after_error:ValueError"
    assert assignments[0]["expected_owners"] == ["phase1", "duplicate", "timeseries"]
