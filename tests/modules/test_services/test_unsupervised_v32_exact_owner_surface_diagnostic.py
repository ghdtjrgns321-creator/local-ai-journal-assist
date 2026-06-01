from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "artifacts" / "unsupervised_v32_exact_owner_surface_fixed5_20260531.json"
TRUTH_CSV = ROOT.joinpath(
    "data",
    "journal",
    "primary",
    "datasynth_manipulation_v7_candidate_fixed5_ownermeta_v32d",
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


def test_unsupervised_v32_exact_owner_surface_contract() -> None:
    payload = _payload()

    assert payload["responsibility_map"] == "v3.2d"
    assert payload["dataset"] == "datasynth_manipulation_v7_candidate_fixed5_ownermeta_v32d"
    assert payload["detector_input_source"] == (
        "data/journal/primary/"
        "datasynth_manipulation_v7_candidate_fixed5_ownermeta_v32d/journal_entries.csv"
    )
    assert payload["diagnostic_only"] is True
    assert payload["measurement_basis"] == "exact_matched_doc_join"
    assert payload["truth_or_owner_metadata_used_as_selector"] is False
    assert payload["truth_or_owner_metadata_used_only_for_exact_matched_doc_join"] is True
    assert payload["q95_gate_changed"] is False
    assert payload["vae_score_or_threshold_changed"] is False
    assert payload["case_generation_changed"] is False
    assert payload["phase1_ranking_changed"] is False
    assert payload["phase2_fusion_changed"] is False
    assert payload["product_default_changed_by_this_diagnostic"] is False


def test_unsupervised_v32_role_denominators_exact_lock() -> None:
    denominators = _payload()["role_denominators"]

    assert denominators["primary"] == {
        "truth_docs": 49,
        "phase1_immediate_review_covered_docs": 0,
        "phase1_review_or_above_covered_docs": 9,
        "phase1_candidate_or_above_covered_docs": 9,
    }
    assert denominators["companion"] == {
        "truth_docs": 395,
        "phase1_immediate_review_covered_docs": 0,
        "phase1_review_or_above_covered_docs": 41,
        "phase1_candidate_or_above_covered_docs": 70,
    }


def test_unsupervised_v32_primary_surfaces_exact_lock() -> None:
    primary = _payload()["surface_metrics_by_role"]["primary"]

    native = primary["native_row_queue"]
    assert native["topn"]["100"]["matched_docs"] == 0
    assert native["topn"]["500"]["matched_docs"] == 0
    assert native["topn"]["1000"]["matched_docs"] == 0
    assert native["topn"]["10000"]["matched_docs"] == 1
    assert native["top500_pressure"]["repeated_normal_pressure"] == 1.0

    soft = primary["hybrid_with_soft_repeated_normal_guard"]
    assert soft["topn"]["100"]["matched_docs"] == 2
    assert soft["topn"]["500"]["matched_docs"] == 10
    assert soft["topn"]["1000"]["matched_docs"] == 13
    assert soft["topn"]["10000"]["matched_docs"] == 13
    assert soft["top500_pressure"]["repeated_normal_pressure"] == 0.244

    probe = primary["soft_guard_context_top100_probe"]
    assert probe["topn"]["100"]["matched_docs"] == 2
    assert probe["topn"]["500"]["matched_docs"] == 10
    assert probe["top500_pressure"]["repeated_normal_pressure"] == 0.244

    context = primary["soft_guard_with_row_count_context"]
    assert context["topn"]["100"]["matched_docs"] == 2
    assert context["topn"]["500"]["matched_docs"] == 10
    assert context["top500_pressure"]["repeated_normal_pressure"] == 0.284


def test_unsupervised_v32_companion_surfaces_exact_lock() -> None:
    companion = _payload()["surface_metrics_by_role"]["companion"]

    native = companion["native_row_queue"]
    assert native["topn"]["100"]["matched_docs"] == 3
    assert native["topn"]["500"]["matched_docs"] == 4
    assert native["topn"]["10000"]["matched_docs"] == 91

    soft = companion["hybrid_with_soft_repeated_normal_guard"]
    assert soft["topn"]["100"]["matched_docs"] == 16
    assert soft["topn"]["500"]["matched_docs"] == 55
    assert soft["topn"]["10000"]["matched_docs"] == 277
    assert soft["top500_pressure"]["repeated_normal_pressure"] == 0.182


def test_unsupervised_v32_probe_decision_and_leak_guard() -> None:
    payload = _payload()

    assert payload["decision"] == {
        "adopted_surface": "hybrid_with_soft_repeated_normal_guard",
        "probe_surface": "soft_guard_context_top100_probe",
        "change_product_default_now": False,
        "probe_top100_lift_vs_adopted": 0,
        "probe_top500_lift_vs_adopted": 0,
        "probe_repeated_normal_pressure_delta": 0.0,
        "probe_pressure_not_above_adopted": True,
        "read": (
            "v3.2d exact owner join keeps the adopted soft guard as the "
            "single VAE family-list ordering. The TOP100 probe is diagnostic "
            "only until pressure and review-burden guardrails are validated."
        ),
    }
    assert payload["scenario_proration_reference"]["status"] == (
        "historical_reference_not_official_for_v32_split_owner"
    )
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
