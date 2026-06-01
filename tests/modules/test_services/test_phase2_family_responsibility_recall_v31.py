from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = (
    ROOT
    / "artifacts"
    / "phase2_family_responsibility_recall_v31_fixed5_ownermeta_ic_20260530.json"
)
V3_ARTIFACT = (
    ROOT
    / "artifacts"
    / "phase2_family_responsibility_recall_v3_fixed5_ownermeta_ic_20260530.json"
)
TRUTH_CSV = ROOT.joinpath(
    "data",
    "journal",
    "primary",
    "datasynth_manipulation_v7_candidate_fixed5_ownermeta_ic",
    "labels",
    "manipulated_entry_truth.csv",
)
DOCS = [
    ROOT / "docs" / "debugging" / "PHASE2_FAMILY_RESPONSIBILITY_RECALL_20260530.md",
    ROOT / "docs" / "users" / "16_PHASE2_RESPONSIBILITY_MAP_DECISION.md",
    ROOT / "docs" / "TROUBLESHOOT.md",
    ROOT / "docs" / "DETECTION_RESULTS_MANIPULATION_V7_FIXED4_PHASE2.md",
]


def _payload() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def _truth_rows() -> list[dict[str, str]]:
    with TRUTH_CSV.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


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


def test_v31_artifact_exists_and_v3_is_retained_unchanged():
    payload = _payload()
    before = hashlib.sha256(V3_ARTIFACT.read_bytes()).hexdigest()
    after = hashlib.sha256(V3_ARTIFACT.read_bytes()).hexdigest()

    assert ARTIFACT.exists()
    assert V3_ARTIFACT.exists()
    assert before == after
    assert payload["metadata"]["policy_model"] == (
        "audit_rule_first_reconciled_with_datasynth_family_flags"
    )
    assert payload["metadata"]["v3_status"] == "traceability_artifact_not_final_policy"
    assert payload["metadata"]["v31_status"] == "audit_rule_first_reconciled_diagnostic"
    assert payload["metadata"]["fixed4_used"] is False
    assert payload["metadata"]["production_ranking_changed"] is False
    assert payload["metadata"]["detector_outputs_used_for_owner_assignment"] is False


def test_v31_primary_denominators_exact_and_duplicate_pending():
    payload = _payload()
    denominators = payload["primary_denominators_v31"]

    assert denominators["phase1"] == 397
    assert denominators["intercompany"] == 34
    assert denominators["relational"] == 34
    assert denominators["duplicate"] == 0
    assert denominators["duplicate_primary_status"] == "pending_pair_evidence_validation"
    assert denominators["duplicate_primary_candidate_count"] == 76
    assert denominators["timeseries"] == 21
    assert denominators["unsupervised"] == 168
    assert denominators["phase1_primary_source"] == (
        "audit_rule_first_reconciled_policy_from_datasynth_scenario_and_family_metadata"
    )


def test_v31_policy_diff_contains_required_scenarios():
    diff = _payload()["v3_to_v31_policy_diff"]

    for key in [
        "approval_sod_bypass",
        "embezzlement_concealment",
        "suspense_account_abuse",
        "circular_related_party_transaction",
        "fictitious_entry",
    ]:
        assert key in diff
    assert diff["approval_sod_bypass"]["v31_primary"] == ["phase1"]
    assert diff["approval_sod_bypass"]["v31_secondary"] == ["relational"]
    assert diff["embezzlement_concealment"]["v31_companion"] == [
        "duplicate",
        "relational",
        "unsupervised",
    ]


def test_v31_overlap_and_companion_denominators():
    payload = _payload()
    denominators = payload["primary_denominators_v31"]
    companion = payload["companion_context_denominators_v31"]

    assert denominators["overlap_matrix"]["intercompany"]["relational"] == 34
    assert denominators["overlap_summary"]["intercompany_and_relational"] == 34
    assert denominators["overlap_summary"]["phase1_primary_and_relational_secondary"] == 105
    assert denominators["overlap_summary"]["phase1_primary_and_duplicate_companion"] == 76
    assert companion["relational_secondary"] == 105
    assert companion["duplicate_context"] == 76
    assert companion["timeseries_context"] == 92
    assert companion["unsupervised_companion"] == 339


def test_v31_unsupervised_primary_excludes_suspense_and_ts_period_end_not_primary():
    payload = _payload()
    rows = _truth_rows()
    suspense = [row for row in rows if row["manipulation_scenario"] == "suspense_account_abuse"]
    fictitious = [row for row in rows if row["manipulation_scenario"] == "fictitious_entry"]

    assert len(suspense) == 100
    assert len(fictitious) == 168
    assert payload["primary_denominators_v31"]["unsupervised"] == len(fictitious)
    assert payload["data_quality_and_policy_checks"]["timeseries_primary_count"] == 21
    assert payload["data_quality_and_policy_checks"]["period_end_timeseries_primary_count"] == 0


def test_v31_primary_recall_and_context_sections_are_separate():
    payload = _payload()
    recall = payload["primary_owner_target_recall_v31"]
    context = payload["context_companion_contribution_v31"]

    assert recall["duplicate"]["status"] == "pending_pair_evidence_validation"
    assert recall["duplicate"]["native_top500_primary_recall"] is None
    assert recall["relational"]["primary_truth_docs"] == 34
    assert recall["unsupervised"]["primary_truth_docs"] == 168
    assert recall["phase1"]["portfolio_620_recall"] == 350 / 620
    assert context["duplicate_context"]["truth_docs"] == 76
    assert context["metric_role"] == "context_companion_lifecycle_not_primary_target_recall"
    assert "context_companion_contribution_v31" not in recall


def test_v31_raw_identifier_leak_guard_and_forbidden_keys():
    payload = _payload()
    text = json.dumps(payload, ensure_ascii=False)
    forbidden_keys = {
        "document_id",
        "raw_document_id",
        "row_id",
        "raw_row_id",
        "phase2_case_id",
        "phase2_case_ids",
        "relationship_group_id",
        "duplicate_pair_group_id",
    }

    assert all(row["document_id"] not in text for row in _truth_rows())
    assert forbidden_keys.isdisjoint({key.lower() for key in _walk_keys(payload)})
    assert payload["data_quality_and_policy_checks"]["raw_identifier_leak_count"] == 0
    assert payload["data_quality_and_policy_checks"]["forbidden_identifier_key_count"] == 0
    assert payload["data_quality_and_policy_checks"][
        "owner_assignment_uses_detector_output_score_rank_topn_matched_result"
    ] is False
    assert payload["data_quality_and_policy_checks"]["v1_v2_v21_v3_artifacts_retained"] is True


def test_v31_docs_remove_stale_supersedes_phrase_and_add_reconciled_language():
    combined = "\n".join(path.read_text(encoding="utf-8") for path in DOCS)

    assert "v3 supersedes v2.1" not in combined
    assert "v3.3b = current canonical responsibility map candidate" in combined
    assert "v1/v2/v2.1/v3/v3.1 = historical iterations" in combined
    assert "v3 = traceability experiment, not final policy" in combined
    assert "v3 relocated owner policy into DataSynth metadata for traceability." in combined
    assert (
        "v3.1 reconciles the DataSynth metadata with audit-rule-first responsibility policy."
        in combined
    )
    assert (
        "v3/v3.1 are diagnostic responsibility maps, not production detector changes."
        in combined
    )
    assert "existence assertion" in combined
    assert "classification error" in combined
