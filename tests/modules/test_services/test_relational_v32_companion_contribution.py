from __future__ import annotations

import json
from pathlib import Path

from tools.scripts import diagnose_relational_v32_companion_contribution_20260531 as diag

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "artifacts" / "relational_v32_companion_contribution_20260531.json"


def _payload() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def test_relational_v32_companion_contract_and_denominator():
    payload = _payload()

    assert payload["metadata"]["owner_metadata_version"] == "v3.2d"
    assert payload["metadata"]["adopted_surface"] == (
        "structural_moderate_audit_then_business_lane_split_surface"
    )
    assert payload["metadata"]["production_ordering_changed"] is False
    assert payload["metadata"]["production_gate_changed"] is False
    assert payload["metadata"]["phase1_ranking_changed"] is False
    assert payload["metadata"]["phase2_fusion_changed"] is False
    assert payload["metadata"]["truth_used_for_scoring"] is False

    role = payload["role_contract"]
    assert role["primary_denominator"] == 0
    assert role["primary_status"] == "no_primary_denominator"
    assert role["companion_denominator"] == 139
    assert role["by_segment_denominator"] == {
        "ic_circular": 34,
        "approval_sod": 29,
        "embezzlement": 76,
    }


def test_relational_v32_adopted_surface_companion_recall_exact_lock():
    topn = _payload()["adopted_surface_companion_recall"]

    assert topn["top100"]["matched_docs"] == 7
    assert topn["top100"]["by_segment"] == {
        "approval_sod": 6,
        "ic_circular": 0,
        "embezzlement": 1,
    }

    assert topn["top500"]["matched_docs"] == 33
    assert topn["top500"]["by_segment"] == {
        "approval_sod": 7,
        "ic_circular": 9,
        "embezzlement": 17,
    }
    assert topn["top500"]["all_truth_docs_matched_by_surface"] == 92

    assert topn["top1000"]["matched_docs"] == 81
    assert topn["top1000"]["by_segment"] == {
        "approval_sod": 7,
        "ic_circular": 9,
        "embezzlement": 65,
    }
    assert topn["top1000"]["all_truth_docs_matched_by_surface"] == 141


def test_relational_v32_rule_breakdown_keeps_r05_r06_out_of_adopted_surface():
    payload = _payload()
    breakdown = payload["adopted_surface_rule_breakdown"]

    assert breakdown["top500"] == {
        "structural_r03_r07": 250,
        "moderate_r01_r02": 250,
        "context_r05_r06": 0,
        "total": 500,
        "structural_share": 0.5,
        "moderate_share": 0.5,
        "context_share": 0.0,
    }
    assert payload["r05_r06_review_burden"]["case_counts"] == {
        "R05": 44404,
        "R06": 11874,
    }
    assert payload["r05_r06_review_burden"][
        "adopted_surface_top500_r05_r06_share"
    ] == 0.0


def test_relational_v32_native_baseline_and_raw_leak_guard():
    payload = _payload()
    native = payload["native_current_companion_baseline"]

    assert native["top100"]["matched_docs"] == 5
    assert native["top500"]["matched_docs"] == 17
    assert "top1000" not in native
    assert payload["raw_identifier_leak_check"] == {
        "doc_like_token_count": 0,
        "forbidden_identifier_key_count": 0,
        "phase2_case_id_like_token_count": 0,
    }


def test_relational_v32_script_build_payload_matches_artifact():
    payload = _payload()
    rebuilt = diag.build_payload()

    assert rebuilt["role_contract"] == payload["role_contract"]
    assert rebuilt["adopted_surface_companion_recall"] == payload[
        "adopted_surface_companion_recall"
    ]
