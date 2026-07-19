"""Smoke checks for VAE/unsupervised v3.1 next-improvement diagnostics."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "artifacts" / "unsupervised_v31_improvement_next_fixed5_20260531.json"


def _payload() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def test_unsupervised_v31_next_improvement_contract() -> None:
    payload = _payload()

    assert payload["diagnostic_only"] is True
    assert payload["production_default_currently_adopted"] == (
        "hybrid_with_soft_repeated_normal_guard"
    )
    assert payload["q95_gate_changed"] is False
    assert payload["vae_score_or_threshold_changed"] is False
    assert payload["phase1_ranking_changed"] is False
    assert payload["phase2_fusion_changed"] is False
    assert payload["truth_or_owner_metadata_used_as_selector"] is False


def test_unsupervised_v31_primary_lift_and_pressure_tradeoff_locked() -> None:
    payload = _payload()
    primary = payload["primary_surface_comparison"]

    adopted = primary["adopted_soft_guard"]
    assert adopted["top100"] == 24
    assert adopted["top500"] == 110
    assert adopted["repeated_normal_pressure_top500"] == 0.336

    context = primary["row_count_context_candidate"]
    assert context["top100"] == 31
    assert context["top500"] == 114
    assert context["repeated_normal_pressure_top500"] == 0.4

    assert primary["row_count_context_lift_vs_adopted"] == {
        "top100": 7,
        "top500": 4,
        "pressure_delta": 0.064,
    }
    assert primary["upper_bound_lift_vs_adopted"] == {
        "top100": 35,
        "top500": 2,
        "pressure_delta": 0.34600000000000003,
    }


def test_unsupervised_v31_next_decision_keeps_current_default() -> None:
    payload = _payload()

    decision = payload["decision"]
    assert decision["change_product_default_now"] is False
    assert decision["next_improvement_class"] == "pressure_stable_primary_top100_lift"
    assert payload["raw_identifier_leak_check"] == {
        "doc_like_token_count": 0,
        "forbidden_identifier_key_count": 0,
        "phase2_case_id_like_token_count": 0,
    }

