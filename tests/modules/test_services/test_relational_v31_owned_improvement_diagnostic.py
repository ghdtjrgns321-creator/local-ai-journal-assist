"""Smoke checks for relational v3.1 owned-improvement diagnostics."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "artifacts" / "relational_v31_owned_improvement_fixed5_20260531.json"


def _payload() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def test_relational_v31_owned_diagnostic_contract() -> None:
    payload = _payload()

    assert payload["diagnostic_only"] is True
    assert payload["production_detector_changed"] is False
    assert payload["production_gate_changed"] is False
    assert payload["production_fusion_changed"] is False
    assert payload["phase1_ranking_changed"] is False
    assert payload["truth_or_owner_metadata_used_as_selector"] is False
    assert payload["truth_or_owner_metadata_used_only_for_aggregate_evaluation"] is True


def test_relational_v31_owned_recall_and_best_surface_lock() -> None:
    payload = _payload()

    assert payload["v31_relational_primary"] == {
        "primary_semantics": "circular_related_party_transaction co-primary with IC",
        "denominator": 34,
        "co_primary_with_intercompany": 34,
    }
    owned = payload["owned_recall_decomposition"]
    assert owned["current_native_top500_primary_docs"] == 9
    assert owned["adopted_surface_top500_primary_docs"] == 9
    assert owned["adopted_surface_top500_owned_recall"] == 9 / 34
    assert owned["best_observed_top500_primary_docs"] == 10
    assert owned["best_observed_surface"] == "account_partner_context_surface"
    assert owned["primary_headroom_after_best_observed"] == 24


def test_relational_v31_decision_keeps_product_default() -> None:
    payload = _payload()

    decision = payload["decision"]
    assert decision["change_product_default_now"] is False
    assert (
        decision["next_improvement_class"]
        == "observable_ic_relational_bridge_or_circular_structural_feature"
    )
    best = payload["surface_snapshots"]["best_primary_docs_observed"]
    assert best["top500_primary_docs"] == 10
    assert best["top500_total_truth_docs"] == 12
    assert best["top500_r05_r06_share"] == 0.578


def test_relational_v31_diagnostic_does_not_emit_raw_identifiers() -> None:
    payload = _payload()
    assert payload["raw_identifier_leak_check"] == {
        "doc_like_token_count": 0,
        "forbidden_identifier_key_count": 0,
        "phase2_case_id_like_token_count": 0,
        "raw_edge_like_token_count": 0,
    }
    text = json.dumps(payload, ensure_ascii=False)
    assert not re.search(r"p2_relational_edge_[0-9a-f]{10}", text)

