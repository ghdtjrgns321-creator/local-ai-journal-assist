from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = (
    ROOT
    / "artifacts"
    / "phase2_family_responsibility_recall_v3_fixed5_ownermeta_ic_20260530.json"
)
V1_ARTIFACT = ROOT / "artifacts" / "phase2_family_responsibility_recall_fixed5_20260530.json"
V2_ARTIFACT = ROOT / "artifacts" / "phase2_family_responsibility_recall_v2_fixed5_20260530.json"
V21_ARTIFACT = (
    ROOT / "artifacts" / "phase2_family_responsibility_recall_v21_fixed5_20260530.json"
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
    ROOT / "docs" / "spec" / "debugging" / "PHASE2_FAMILY_RESPONSIBILITY_RECALL_20260530.md",
    ROOT / "docs" / "guide" / "users" / "16_PHASE2_RESPONSIBILITY_MAP_DECISION.md",
    ROOT / "docs" / "spec" / "TROUBLESHOOT.md",
    ROOT / "docs" / "guide" / "DETECTION_RESULTS_MANIPULATION_V7_FIXED4_PHASE2.md",
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


def test_v3_artifact_exists_and_metadata_contract():
    payload = _payload()

    assert ARTIFACT.exists()
    assert V1_ARTIFACT.exists()
    assert V2_ARTIFACT.exists()
    assert V21_ARTIFACT.exists()
    assert payload["metadata"]["candidate_name"] == (
        "datasynth_manipulation_v7_candidate_fixed5_ownermeta_ic"
    )
    assert payload["metadata"]["policy_model"] == (
        "family_specific_primary_flags_with_co_primary"
    )
    assert payload["metadata"]["truth_owner_primary_is_legacy_summary"] is True
    assert payload["metadata"]["co_primary_allowed"] is True
    assert payload["metadata"]["fixed4_used"] is False
    assert payload["metadata"]["production_ranking_changed"] is False


def test_v3_primary_denominator_counts_and_overlap():
    payload = _payload()
    denominators = payload["primary_denominators"]

    assert denominators["intercompany"] == 34
    assert denominators["relational"] == 63
    assert denominators["duplicate"] == 76
    assert denominators["timeseries"] == 21
    assert denominators["unsupervised"] == 268
    assert denominators["phase1"] == 192
    assert denominators["phase1_primary_source"] == "legacy_truth_owner_primary"
    assert denominators["overlap_matrix"]["intercompany"]["relational"] == 34
    assert denominators["overlap_summary"]["intercompany_and_relational"] == 34


def test_v3_uses_family_specific_flags_for_non_phase1_denominators():
    payload = _payload()
    checks = payload["data_quality_and_policy_checks"]

    assert checks["truth_owner_primary_used_for_non_phase1_family_denominators"] is False
    assert checks["expected_primary_counts_match"] == {
        "intercompany": True,
        "relational": True,
        "duplicate": True,
        "timeseries": True,
        "unsupervised": True,
    }


def test_v3_circular_ic_primary_and_non_circular_ic_zero():
    payload = _payload()
    rows = _truth_rows()
    circular_ic = [
        row
        for row in rows
        if row["manipulation_scenario"] == "circular_related_party_transaction"
        and row["injected_intercompany_primary"].lower() == "true"
    ]
    non_circular_ic = [
        row
        for row in rows
        if row["manipulation_scenario"] != "circular_related_party_transaction"
        and row["injected_intercompany_primary"].lower() == "true"
    ]

    assert len(circular_ic) == 34
    assert len(non_circular_ic) == 0
    assert payload["data_quality_and_policy_checks"][
        "circular_injected_intercompany_primary_count"
    ] == 34
    assert payload["data_quality_and_policy_checks"][
        "non_circular_injected_intercompany_primary_count"
    ] == 0


def test_v3_primary_recall_and_action_tier_sections_exist():
    payload = _payload()
    recall = payload["primary_owner_target_recall"]

    assert recall["intercompany"]["native_top500_primary_recall"] == 1.0
    assert recall["relational"]["primary_truth_docs"] == 63
    assert recall["duplicate"]["native_top500_primary_recall"] == 0.0
    assert recall["timeseries"]["primary_truth_docs"] == 21
    assert recall["unsupervised"]["primary_truth_docs"] == 268
    for family in ["intercompany", "relational", "duplicate", "timeseries", "unsupervised"]:
        assert "phase1_action_tier_outside_primary_capture" in recall[family]
        assert family in payload["phase1_action_tier_comparison"]


def test_v3_context_companion_contribution_is_separate():
    payload = _payload()
    context = payload["context_companion_contribution"]

    assert context["metric_role"] == "context_companion_lifecycle_not_primary_target_recall"
    assert context["relational_secondary"]["truth_docs"] == 76
    assert context["timeseries_context"]["truth_docs"] == 92
    assert context["unsupervised_companion"]["truth_docs"] == 239
    assert "context_companion_contribution" not in payload["primary_owner_target_recall"]


def test_v3_raw_identifier_leak_guard():
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
        "detector_output_score_rank_topn_matched_used_for_owner_assignment"
    ] is False


def test_v3_docs_mark_traceability_and_v31_reconciliation():
    combined = "\n".join(path.read_text(encoding="utf-8") for path in DOCS)

    assert "v3 supersedes v2.1" not in combined
    assert "v3 relocated owner policy into DataSynth metadata for traceability." in combined
    assert (
        "v3.1 reconciles the DataSynth metadata with audit-rule-first responsibility policy."
        in combined
    )
    assert "legacy representative summary" in combined
    assert "family-specific primary flags" in combined
