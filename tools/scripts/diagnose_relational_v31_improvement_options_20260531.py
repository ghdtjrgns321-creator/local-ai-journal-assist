"""Relational v3.1 improvement option synthesis.

Diagnostic-only comparison of the adopted relationship-evidence surface against
remaining ranking candidates. Relational v3.1 primary is circular co-primary;
most value remains secondary relationship evidence, not primary recall tuning.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RESPONSIBILITY = (
    ROOT / "artifacts" / "phase2_family_responsibility_recall_v31_fixed5_ownermeta_ic_20260530.json"
)
RANKING = ROOT / "artifacts" / "relational_ranking_candidates_fixed5_20260529.json"
OUT_JSON = ROOT / "artifacts" / "relational_v31_improvement_options_20260531.json"


def _topn(row: dict[str, Any], n: str) -> dict[str, Any]:
    value = row["topn"][n]
    pressure = value["false_positive_pressure_proxy"]
    return {
        "matched": value["matched"],
        "scenario_counts": value["scenario_counts"],
        "sub_rule_distribution": value["sub_rule_distribution"],
        "r05_r06_share": value["r05_r06_share"],
        "cases_per_matched_case": pressure["cases_per_matched_case"],
        "high_volume_nontruth_share": pressure["high_volume_nontruth_share"],
    }


def _surface_summary(payload: dict[str, Any], name: str) -> dict[str, Any]:
    value = payload["candidate_rankings"][name]
    uplift = value["phase1_topn_uplift"]
    return {
        "top100": _topn(value, "100"),
        "top500": _topn(value, "500"),
        "top1000": _topn(value, "1000"),
        "phase1_top500_net_uplift": uplift["net_truth_uplift_vs_phase1_top500"],
        "phase2_top500_truth_not_in_phase1_top500": uplift[
            "phase2_top500_truth_not_in_phase1_top500"
        ],
    }


def build_payload() -> dict[str, Any]:
    responsibility = json.loads(RESPONSIBILITY.read_text(encoding="utf-8"))
    ranking = json.loads(RANKING.read_text(encoding="utf-8"))
    surfaces = {
        "current": _surface_summary(ranking, "current"),
        "adopted_structural_moderate_audit_then_business": _surface_summary(
            ranking, "structural_moderate_audit_then_business_lane_split_surface"
        ),
        "diagnostic_upper_bound_structural_anchor_1_to_4": _surface_summary(
            ranking, "structural_anchor_moderate_1_to_4_surface"
        ),
        "structural_only": _surface_summary(ranking, "r03_r07_structural_only_surface"),
        "moderate_tail_only": _surface_summary(ranking, "r01_r02_moderate_tail_surface"),
        "r05_r06_context_lane": _surface_summary(ranking, "r05_r06_context_lane_surface"),
    }
    v31_primary = responsibility["primary_owner_target_recall_v31"]["relational"]
    v31_secondary = responsibility["context_companion_contribution_v31"][
        "relational_secondary"
    ]
    adopted = surfaces["adopted_structural_moderate_audit_then_business"]
    upper = surfaces["diagnostic_upper_bound_structural_anchor_1_to_4"]
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source_artifacts": {
            "responsibility": str(RESPONSIBILITY.relative_to(ROOT)).replace("\\", "/"),
            "ranking": str(RANKING.relative_to(ROOT)).replace("\\", "/"),
        },
        "diagnostic_only": True,
        "responsibility_map": "v3.1",
        "production_ranking_changed": False,
        "relational_gate_changed": False,
        "phase1_ranking_changed": False,
        "phase2_fusion_changed": False,
        "truth_label_used_for_scoring": False,
        "truth_label_used_only_for_aggregate_evaluation": True,
        "v31_primary_status": {
            "primary_truth_docs": v31_primary["primary_truth_docs"],
            "native_top500_matched_docs": v31_primary["native_top500_matched_docs"],
            "native_top500_primary_recall": v31_primary["native_top500_primary_recall"],
            "read": (
                "Relational primary is circular co-primary; IC is the clean "
                "primary detector for reciprocal matching. Relational primary "
                "improvement would mostly duplicate IC value."
            ),
        },
        "v31_secondary_status": {
            "secondary_truth_docs": v31_secondary["truth_docs"],
            "native_top500_matched_docs": v31_secondary["matched_docs"],
            "native_top500_secondary_recall": v31_secondary["recall"],
        },
        "surface_options": surfaces,
        "remaining_improvement_options": {
            "upper_bound_vs_adopted": {
                "top100_delta": upper["top100"]["matched"] - adopted["top100"]["matched"],
                "top500_delta": upper["top500"]["matched"] - adopted["top500"]["matched"],
                "top500_net_uplift_delta": (
                    upper["phase1_top500_net_uplift"]
                    - adopted["phase1_top500_net_uplift"]
                ),
                "reason_not_default": (
                    "1:4 structural anchor is a review-surface policy choice "
                    "with weaker audit-rule-first rationale than the adopted 1:1 "
                    "audit-then-business split."
                ),
            },
            "structural_only": {
                "top500_matched": surfaces["structural_only"]["top500"]["matched"],
                "read": "Good structural explanation but loses moderate-tail uplift.",
            },
            "moderate_tail_only": {
                "top500_matched": surfaces["moderate_tail_only"]["top500"]["matched"],
                "read": "Higher standalone truth coverage, but loses structural anchor.",
            },
            "r05_r06_context_lane": {
                "top500_matched": surfaces["r05_r06_context_lane"]["top500"]["matched"],
                "read": "High-volume context lane remains unsuitable for primary surface.",
            },
        },
        "decision": {
            "current_default_surface": "structural_moderate_audit_then_business_lane_split_surface",
            "change_default_now": False,
            "best_next_experiment": (
                "document why 1:1 split is product policy and keep "
                "upper-bound diagnostic only"
            ),
            "primary_recall_tuning_recommended": False,
        },
        "raw_identifier_leak_check": ranking["raw_identifier_leak_check"],
    }


def main() -> int:
    payload = build_payload()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "out": OUT_JSON.relative_to(ROOT).as_posix(),
                "primary": payload["v31_primary_status"],
                "adopted_top500": payload["surface_options"][
                    "adopted_structural_moderate_audit_then_business"
                ]["top500"]["matched"],
                "upper_bound_top500": payload["surface_options"][
                    "diagnostic_upper_bound_structural_anchor_1_to_4"
                ]["top500"]["matched"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
