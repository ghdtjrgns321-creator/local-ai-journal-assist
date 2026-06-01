from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "artifacts" / "unsupervised_v33_exact_owner_surface_fixed5_20260531.json"
TRUTH_CSV = ROOT.joinpath(
    "data",
    "journal",
    "primary",
    "datasynth_manipulation_v7_candidate_fixed5_ownermeta_v33b",
    "labels",
    "manipulated_entry_truth.csv",
)


def _payload() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


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


def test_unsupervised_v33_exact_owner_surface_contract() -> None:
    payload = _payload()

    assert payload["responsibility_map"] == "v3.3b"
    assert payload["dataset"] == "datasynth_manipulation_v7_candidate_fixed5_ownermeta_v33b"
    assert payload["measurement_basis"] == "exact_matched_doc_join"
    assert payload["diagnostic_only"] is True
    assert payload["truth_or_owner_metadata_used_as_selector"] is False
    assert payload["truth_or_owner_metadata_used_only_for_exact_matched_doc_join"] is True
    assert payload["q95_gate_changed"] is False
    assert payload["vae_score_or_threshold_changed"] is False
    assert payload["case_generation_changed"] is False
    assert payload["phase1_ranking_changed"] is False
    assert payload["phase2_fusion_changed"] is False
    assert payload["product_default_changed_by_this_diagnostic"] is False


def test_unsupervised_v33_primary_surface_exact_lock() -> None:
    payload = _payload()
    primary = payload["surface_metrics_by_role"]["primary"]

    assert payload["role_denominators"]["primary"]["truth_docs"] == 40
    assert payload["role_denominators"]["companion"]["truth_docs"] == 404

    soft = primary["hybrid_with_soft_repeated_normal_guard"]
    assert soft["topn"]["100"]["matched_docs"] == 2
    assert soft["topn"]["500"]["matched_docs"] == 10
    assert soft["topn"]["1000"]["matched_docs"] == 16
    assert soft["topn"]["10000"]["matched_docs"] == 16
    assert soft["top500_pressure"]["repeated_normal_pressure"] == 0.242

    assert primary["soft_guard_context_top100_probe"]["topn"]["500"]["matched_docs"] == 10
    assert primary["soft_guard_with_row_count_context"]["topn"]["500"]["matched_docs"] == 10
    assert primary["hybrid_row_count_blended_surface_upper_bound"]["topn"]["100"][
        "matched_docs"
    ] == 7
    assert primary["hybrid_row_count_blended_surface_upper_bound"][
        "top500_pressure"
    ]["repeated_normal_pressure"] == 0.74


def test_unsupervised_v33_selector_safe_probe_rejects() -> None:
    primary = _payload()["surface_metrics_by_role"]["primary"]

    signal = primary["v33_statistical_signal_probe"]
    assert signal["topn"]["100"]["matched_docs"] == 0
    assert signal["topn"]["500"]["matched_docs"] == 0
    assert signal["top500_pressure"]["repeated_normal_pressure"] == 0.586

    capped = primary["v33_pressure_capped_signal_probe"]
    assert capped["topn"]["100"]["matched_docs"] == 0
    assert capped["topn"]["500"]["matched_docs"] == 1
    assert capped["top500_pressure"]["repeated_normal_pressure"] == 0.218


def test_unsupervised_v33_capture_differential_and_gap() -> None:
    payload = _payload()

    differential = payload["primary_capture_differential"]
    assert differential["basis"] == "soft_guard_top500_capture_vs_miss"
    assert differential["captured_docs"] == 10
    assert differential["missed_docs"] == 30
    assert differential["captured_profile"]["max_score_distribution"]["count"] == 10
    assert differential["missed_profile"]["max_score_distribution"]["count"] == 6

    gap = payload["primary_top100_gap_analysis"]["default_rank_bands"]
    assert gap["top100"]["matched_docs"] == 2
    assert gap["rank251_500"]["matched_docs"] == 8
    assert gap["rank501_1000"]["matched_docs"] == 6
    assert gap["outside_top10000_or_not_candidate"]["matched_docs"] == 24


def test_unsupervised_v33_decision_and_leak_guard() -> None:
    payload = _payload()

    assert payload["decision"]["change_product_default_now"] is False
    assert payload["decision"]["probe_top100_lift_vs_adopted"] == 0
    assert payload["decision"]["probe_top500_lift_vs_adopted"] == 0
    assert payload["raw_identifier_leak_check"] == {
        "doc_like_token_count": 0,
        "forbidden_identifier_key_count": 0,
        "phase2_case_id_like_token_count": 0,
    }

    text = json.dumps(payload, ensure_ascii=False)
    with TRUTH_CSV.open("r", encoding="utf-8", newline="") as fh:
        truth_doc_ids = {row["document_id"] for row in csv.DictReader(fh)}
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
    assert all(doc_id not in text for doc_id in truth_doc_ids)
    assert forbidden_keys.isdisjoint({key.lower() for key in _walk_keys(payload)})
    assert "DOC-" not in text
    assert "TRUTH-" not in text
    assert "p2_unsupervised_" not in text
