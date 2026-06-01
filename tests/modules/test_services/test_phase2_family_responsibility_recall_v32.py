from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = (
    ROOT
    / "artifacts"
    / "phase2_family_responsibility_recall_v32_fixed5_ownermeta_v32d_20260531.json"
)
TRUTH_CSV = ROOT.joinpath(
    "data",
    "journal",
    "primary",
    "datasynth_manipulation_v7_candidate_fixed5_ownermeta_v32d",
    "labels",
    "manipulated_entry_truth.csv",
)
HISTORICAL_ARTIFACTS = [
    ROOT / "artifacts" / "phase2_family_responsibility_recall_fixed5_20260530.json",
    ROOT / "artifacts" / "phase2_family_responsibility_recall_v2_fixed5_20260530.json",
    ROOT / "artifacts" / "phase2_family_responsibility_recall_v21_fixed5_20260530.json",
    ROOT
    / "artifacts"
    / "phase2_family_responsibility_recall_v3_fixed5_ownermeta_ic_20260530.json",
    ROOT
    / "artifacts"
    / "phase2_family_responsibility_recall_v31_fixed5_ownermeta_ic_20260530.json",
]
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


def test_v32_artifact_exists_and_metadata_contract():
    payload = _payload()

    assert ARTIFACT.exists()
    assert payload["metadata"]["owner_metadata_version"] == "v3.2d"
    assert payload["metadata"]["candidate_name"] == (
        "datasynth_manipulation_v7_candidate_fixed5_ownermeta_v32d"
    )
    assert payload["metadata"]["current_canonical"] is True
    assert payload["metadata"]["canonical_status"] == (
        "canonical_after_suspense_override_and_exact_vae_join"
    )
    assert payload["metadata"]["fixed4_used"] is False
    assert payload["metadata"]["production_ranking_changed"] is False
    assert payload["metadata"]["production_gate_changed"] is False
    assert payload["metadata"]["production_fusion_changed"] is False
    assert payload["metadata"]["detector_outputs_used_for_owner_assignment"] is False


def test_v32_primary_denominator_exact_lock_and_pending_status():
    payload = _payload()
    denominators = payload["primary_denominators_v32"]

    assert denominators["phase1"] == 516
    assert denominators["intercompany"] == 34
    assert denominators["timeseries"] == 21
    assert denominators["unsupervised"] == 49
    assert denominators["relational"] == 0
    assert denominators["duplicate"] == 0
    assert denominators["status"]["relational"] == "no_primary_denominator"
    assert denominators["status"]["duplicate"] == "no_primary_denominator"

    recall = payload["primary_owner_target_recall_v32"]
    assert recall["relational"]["status"] == "no_primary_denominator"
    assert recall["relational"]["topn"]["top500"]["recall"] is None
    assert recall["duplicate"]["status"] == "no_primary_denominator"
    assert recall["duplicate"]["topn"]["top500"]["recall"] is None


def test_v32_companion_denominator_exact_lock():
    payload = _payload()
    denominators = payload["companion_context_denominators_v32"]

    assert denominators == {
        "relational_companion": 139,
        "duplicate_companion": 111,
        "timeseries_context": 92,
        "statistical_companion": 395,
    }
    context = payload["companion_context_contribution_v32"]
    assert context["relational_companion"]["denominator"] == 139
    assert context["duplicate_companion"]["denominator"] == 111
    assert context["timeseries_context"]["denominator"] == 92
    assert context["statistical_companion"]["denominator"] == 395


def test_v32_primary_overlap_is_zero():
    payload = _payload()
    overlap = payload["overlap_matrix"]

    assert overlap["primary_non_self_overlap_count"] == 0
    assert overlap["primary_non_self_overlaps"] == {}
    assert overlap["ic_relational_primary_overlap"] == 0


def test_v32_data_quality_and_flag_counts():
    payload = _payload()
    checks = payload["data_quality_and_policy_checks"]

    assert checks["truth_docs"] == 620
    assert checks["anomaly_label_docs"] == 620
    assert checks["journal_rows"] == 1_034_269
    assert checks["journal_docs"] == 318_653
    assert checks["journal_columns"] == 53
    assert checks["new_owner_truth_flags_in_journal_columns"] == []
    assert all(checks["expected_denominator_counts_match"].values())
    assert checks["relationship_primary_target_count"] == 0
    assert checks["relationship_companion_target_count"] == 139
    assert checks["duplicate_primary_target_count"] == 0
    assert checks["duplicate_companion_target_count"] == 111
    assert checks["statistical_primary_count"] == 49
    assert checks["statistical_companion_count"] == 395
    assert checks["injected_intercompany_primary_count"] == 34
    assert checks["injected_timing_primary_count"] == 21
    assert checks["circular_intercompany_primary_count"] == 34
    assert checks["non_circular_intercompany_primary_count"] == 0
    assert checks["period_end_timeseries_primary_count"] == 0
    assert checks["suspense_phase1_primary_count"] == 100
    assert checks["suspense_unsupervised_primary_count"] == 0
    assert checks["suspense_statistical_companion_count"] == 100
    assert checks["within_scenario_split_recall_requires_exact_join"] is True
    assert checks["exact_matched_doc_join_available"] is True


def test_v32_intercompany_and_timeseries_product_lock_smoke():
    payload = _payload()
    lock = payload["product_ordering_lock_v32"]

    intercompany = lock["intercompany"]
    assert intercompany["primary_denominator"] == 34
    assert intercompany["top500_matched_docs"] == 34
    assert intercompany["top500_recall"] == 1.0
    assert intercompany["status"] == "available"
    assert intercompany["production_detector_gate_fusion_changed"] is False
    assert intercompany["phase1_ranking_changed"] is False
    assert intercompany["streamlit_ui_changed"] is False

    timeseries = lock["timeseries"]
    assert timeseries["primary_denominator"] == 21
    assert timeseries["period_end_context_docs"] == 92
    assert timeseries["period_end_context_used_as_primary"] is False
    assert timeseries["default_ordering_strategy"] == (
        "ts_specific_top100_stabilized_surface"
    )
    assert timeseries["native_baseline"] == {
        "top100_matched_docs": 0,
        "top500_matched_docs": 0,
    }
    assert timeseries["product_default_ordering"]["top100_matched_docs"] == 21
    assert timeseries["product_default_ordering"]["top500_matched_docs"] == 21
    assert timeseries["product_default_ordering"]["top100_recall"] == 1.0
    assert timeseries["product_default_ordering"]["top500_recall"] == 1.0
    assert timeseries["production_default_ordering_changed"] is True
    assert timeseries["production_detector_gate_fusion_changed"] is False
    assert timeseries["phase1_ranking_changed"] is False
    assert timeseries["streamlit_ui_changed"] is False


def test_v32_fictitious_subtype_taxonomy():
    rows = _truth_rows()
    counts: dict[str, int] = {}
    for row in rows:
        subtype = row["truth_owner_subtype"]
        counts[subtype] = counts.get(subtype, 0) + 1

    assert counts["fictitious_existence_statistical"] == 49
    assert counts["fictitious_account_policy"] == 44
    assert counts["fictitious_period_end_like"] == 40
    assert counts["fictitious_duplicate_like"] == 35
    assert _payload()["primary_denominators_v32"]["unsupervised"] == 49


def test_v32_suspense_override_and_exact_vae_join():
    payload = _payload()
    top500 = payload["primary_owner_target_recall_v32"]["unsupervised"]["topn"]["top500"]

    assert payload["policy_overrides_v32d"]["suspense_account_abuse"] == {
        "primary_owner": "phase1",
        "companion_owner": "unsupervised",
        "reason": (
            "long_aged_suspense_balance is rule/account-policy primary "
            "unless a statistical-only suspense subtype is explicitly defined"
        ),
    }
    assert top500["matched_docs"] == 5
    assert top500["recall"] == 5 / 49
    assert top500["status"] == "available_exact_native_join"
    assert top500["measurement_basis"] == "exact_matched_doc_join"


def test_v32_raw_identifier_leak_guard_and_forbidden_keys():
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
        "relationship_source_entity",
        "relationship_target_entity",
    }

    assert all(row["document_id"] not in text for row in _truth_rows())
    assert forbidden_keys.isdisjoint({key.lower() for key in _walk_keys(payload)})
    assert payload["raw_identifier_leak_check"] == {
        "doc_like_token_count": 0,
        "forbidden_identifier_key_count": 0,
        "forbidden_identifier_value_count": 0,
        "phase2_case_id_like_token_count": 0,
    }
    assert payload["data_quality_and_policy_checks"][
        "owner_assignment_uses_detector_output_score_rank_topn_matched_result"
    ] is False


def test_v32_historical_artifacts_are_retained_and_docs_are_canonical():
    payload = _payload()
    combined = "\n".join(path.read_text(encoding="utf-8") for path in DOCS)

    assert all(path.exists() for path in HISTORICAL_ARTIFACTS)
    assert payload["data_quality_and_policy_checks"]["historical_artifacts_retained"] is True
    assert "v3.2d = historical responsibility map" in combined
    assert "v3.3d = current canonical responsibility map candidate" in combined
    assert "v3.3b = historical responsibility map" in combined
    assert "v1/v2/v2.1/v3/v3.1 = historical iterations" in combined
    assert "relational primary 0" in combined
    assert "duplicate primary 0" in combined
    assert "VAE primary 49" in combined
    assert "suspense는 rule-first로 lock" in combined
    assert "within-scenario split recall은 exact join 없으면 estimate" in combined
    assert "VAE 49 exact TOP500 recall = 5 / 49" in combined
