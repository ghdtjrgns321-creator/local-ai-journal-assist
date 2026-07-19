from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
RELATIONAL = ROOT / "artifacts" / "relational_v31_improvement_options_20260531.json"
UNSUPERVISED = ROOT / "artifacts" / "unsupervised_v31_improvement_options_20260531.json"
DUPLICATE = ROOT / "artifacts" / "duplicate_v31_feature_gap_experiment_20260531.json"


def _payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_relational_v31_improvement_options_lock():
    payload = _payload(RELATIONAL)

    assert payload["diagnostic_only"] is True
    assert payload["production_ranking_changed"] is False
    assert payload["relational_gate_changed"] is False
    assert payload["phase1_ranking_changed"] is False
    assert payload["phase2_fusion_changed"] is False
    assert payload["truth_label_used_for_scoring"] is False

    assert payload["v31_primary_status"]["primary_truth_docs"] == 34
    assert payload["v31_primary_status"]["native_top500_matched_docs"] == 9
    assert payload["v31_secondary_status"]["secondary_truth_docs"] == 105
    assert payload["v31_secondary_status"]["native_top500_matched_docs"] == 8

    adopted = payload["surface_options"]["adopted_structural_moderate_audit_then_business"]
    upper = payload["surface_options"]["diagnostic_upper_bound_structural_anchor_1_to_4"]
    assert adopted["top100"]["matched"] == 51
    assert adopted["top500"]["matched"] == 92
    assert upper["top100"]["matched"] == 59
    assert upper["top500"]["matched"] == 100
    assert payload["decision"]["change_default_now"] is False
    assert payload["decision"]["primary_recall_tuning_recommended"] is False


def test_unsupervised_v31_improvement_options_lock():
    payload = _payload(UNSUPERVISED)

    assert payload["diagnostic_only"] is True
    assert payload["q95_gate_changed"] is False
    assert payload["vae_score_or_threshold_changed"] is False
    assert payload["phase1_ranking_changed"] is False
    assert payload["phase2_fusion_changed"] is False
    assert payload["truth_label_used_for_scoring"] is False
    assert payload["role_denominators"] == {"primary": 168, "companion": 339}

    primary = payload["primary_surface_options"]
    assert primary["hybrid_with_soft_repeated_normal_guard"]["top100_matched"] == 24
    assert primary["hybrid_with_soft_repeated_normal_guard"]["top500_matched"] == 110
    assert primary["soft_guard_with_row_count_context"]["top100_matched"] == 31
    assert primary["soft_guard_with_row_count_context"]["top500_matched"] == 114
    assert primary["hybrid_row_count_blended_surface_upper_bound"]["top100_matched"] == 59
    assert primary["hybrid_row_count_blended_surface_upper_bound"]["top500_matched"] == 112

    options = payload["incremental_options_vs_adopted_soft_guard"]
    assert options["soft_guard_with_row_count_context"]["top500_delta"] == 4
    assert options["hybrid_row_count_blended_surface_upper_bound"]["top100_delta"] == 35
    assert payload["decision"]["change_default_now"] is False


def test_duplicate_v31_feature_gap_experiment_lock():
    payload = _payload(DUPLICATE)

    assert payload["diagnostic_only"] is True
    assert payload["production_first_review_ranking_changed"] is False
    assert payload["row_score_threshold_changed"] is False
    assert payload["row_scores_changed"] is False
    assert payload["top_pairs_cap_changed"] is False
    assert payload["weak_pair_gate_changed"] is False
    assert payload["truth_metadata_used_as_selector"] is False

    assert payload["baseline_attrition"] == {
        "primary_docs": 76,
        "row_score_primary_docs": 28,
        "no_row_score_primary_docs": 48,
        "candidate_subset_primary_docs": 0,
        "candidate_subset_selected_rows": 50000,
        "candidate_subset_min_score": 0.5989857631894374,
    }
    summary = payload["experiment_summary"]
    assert summary["l2_03d_lower_score_floor_band_primary_docs"] == 0
    assert summary["l2_03d_lower_score_floor_band_case_grade_primary_docs"] == 0
    assert summary["observable_document_profile_primary_docs"] == 75
    assert summary["observable_document_profile_case_grade_primary_docs"] == 74
    assert summary["best_non_oracle_candidate"] == "observable_document_profile_sample"


def test_family_improvement_option_artifacts_do_not_leak_raw_identifiers():
    for path in (RELATIONAL, UNSUPERVISED, DUPLICATE):
        payload = _payload(path)
        text = json.dumps(payload, ensure_ascii=False)
        leak = payload["raw_identifier_leak_check"]
        assert leak["doc_like_token_count"] == 0
        assert leak["forbidden_identifier_key_count"] == 0
        assert "DOC-" not in text
        assert "TRUTH-" not in text
        assert "p2_" not in text
