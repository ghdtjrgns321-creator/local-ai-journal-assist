"""Relational v3.1 owned-recall improvement diagnostic.

This script reads existing aggregate artifacts only. It does not run detectors,
change relational ordering, or use truth/owner metadata as a selector.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RESPONSIBILITY_ARTIFACT = (
    ROOT
    / "artifacts"
    / "phase2_family_responsibility_recall_v31_fixed5_ownermeta_ic_20260530.json"
)
RANKING_ARTIFACT = ROOT / "artifacts" / "relational_ranking_candidates_fixed5_20260529.json"
OUT_JSON = ROOT / "artifacts" / "relational_v31_owned_improvement_fixed5_20260531.json"

PRIMARY_SCENARIO = "circular_related_party_transaction"
ADOPTED_SURFACE = "structural_moderate_audit_then_business_lane_split_surface"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _scenario_count(candidate: dict[str, Any], top_n: int, scenario: str) -> int:
    return int(
        candidate["topn"][str(top_n)].get("scenario_counts", {}).get(scenario, 0)
    )


def _candidate_summary(name: str, candidate: dict[str, Any]) -> dict[str, Any]:
    top500 = candidate["topn"]["500"]
    return {
        "surface": name,
        "top100_primary_docs": _scenario_count(candidate, 100, PRIMARY_SCENARIO),
        "top500_primary_docs": _scenario_count(candidate, 500, PRIMARY_SCENARIO),
        "top1000_primary_docs": _scenario_count(candidate, 1000, PRIMARY_SCENARIO),
        "top10000_primary_docs": _scenario_count(candidate, 10000, PRIMARY_SCENARIO),
        "top500_total_truth_docs": int(top500["matched"]),
        "top500_sub_rule_distribution": top500["sub_rule_distribution"],
        "top500_r05_r06_share": top500["r05_r06_share"],
        "top500_high_volume_nontruth_share": top500["false_positive_pressure_proxy"][
            "high_volume_nontruth_share"
        ],
    }


def _best_by_primary_top500(candidates: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [_candidate_summary(name, candidate) for name, candidate in candidates.items()]
    return sorted(
        rows,
        key=lambda row: (
            row["top500_primary_docs"],
            row["top500_total_truth_docs"],
            -row["top500_r05_r06_share"],
        ),
        reverse=True,
    )[:8]


def main() -> int:
    responsibility = _read_json(RESPONSIBILITY_ARTIFACT)
    ranking = _read_json(RANKING_ARTIFACT)
    candidates = ranking["candidate_rankings"]
    primary_denominator = int(
        responsibility["primary_denominators_v31"]["relational"]
    )

    current = _candidate_summary("current", candidates["current"])
    adopted = _candidate_summary(ADOPTED_SURFACE, candidates[ADOPTED_SURFACE])
    upper_bound = _candidate_summary(
        "structural_anchor_moderate_1_to_4_surface",
        candidates["structural_anchor_moderate_1_to_4_surface"],
    )
    account_partner = _candidate_summary(
        "account_partner_context_surface",
        candidates["account_partner_context_surface"],
    )

    best_primary = _best_by_primary_top500(candidates)
    best_top500_primary = best_primary[0]

    payload: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "diagnostic_only": True,
        "source_artifacts": {
            "responsibility": str(RESPONSIBILITY_ARTIFACT.relative_to(ROOT)).replace(
                "\\", "/"
            ),
            "ranking": str(RANKING_ARTIFACT.relative_to(ROOT)).replace("\\", "/"),
        },
        "production_detector_changed": False,
        "production_gate_changed": False,
        "production_fusion_changed": False,
        "phase1_ranking_changed": False,
        "truth_or_owner_metadata_used_as_selector": False,
        "truth_or_owner_metadata_used_only_for_aggregate_evaluation": True,
        "v31_relational_primary": {
            "primary_semantics": "circular_related_party_transaction co-primary with IC",
            "denominator": primary_denominator,
            "co_primary_with_intercompany": responsibility["primary_denominators_v31"][
                "overlap_summary"
            ]["intercompany_and_relational"],
        },
        "owned_recall_decomposition": {
            "current_native_top500_primary_docs": current["top500_primary_docs"],
            "adopted_surface_top500_primary_docs": adopted["top500_primary_docs"],
            "adopted_surface_top500_owned_recall": (
                adopted["top500_primary_docs"] / primary_denominator
                if primary_denominator
                else None
            ),
            "best_observed_top500_primary_docs": best_top500_primary[
                "top500_primary_docs"
            ],
            "best_observed_surface": best_top500_primary["surface"],
            "best_observed_recall": (
                best_top500_primary["top500_primary_docs"] / primary_denominator
                if primary_denominator
                else None
            ),
            "primary_headroom_after_best_observed": (
                primary_denominator - best_top500_primary["top500_primary_docs"]
            ),
        },
        "surface_snapshots": {
            "current": current,
            "adopted_product_default": adopted,
            "diagnostic_upper_bound_total_truth": upper_bound,
            "best_primary_docs_observed": account_partner,
        },
        "best_primary_top500_surfaces": best_primary,
        "root_cause": {
            "primary_denominator_is_ic_relational_circular_only": True,
            "adopted_surface_is_relationship_evidence_companion_not_circular_optimizer": True,
            "moderate_tail_surfaces_raise_total_truth_but_not_circular_primary": True,
            "r05_r06_context_surfaces_do_not_solve_owned_recall": True,
            "observed_primary_ceiling_without_new_features": best_top500_primary[
                "top500_primary_docs"
            ],
            "read": (
                "Relational owned recall is low because v3.1 primary target is the "
                "34 circular related-party documents, while the relational product "
                "surface is a broader relationship-evidence companion. Existing "
                "non-truth-tuned surfaces raise total relationship evidence but do "
                "not move circular primary beyond 10/34 at TOP500."
            ),
        },
        "decision": {
            "change_product_default_now": False,
            "reason": (
                "Best observed circular-primary TOP500 improvement is 9/34 to 10/34, "
                "and the 10/34 surface relies heavily on R05/R06 context lanes with "
                "lower total truth coverage. That is not enough to justify a product "
                "ordering change."
            ),
            "next_improvement_class": (
                "observable_ic_relational_bridge_or_circular_structural_feature"
            ),
            "next_prompt": (
                "Implement a diagnostic-only IC-relational bridge analysis: for the "
                "34 circular co-primary documents, compare IC reciprocal evidence "
                "presence with relational R03/R07 edge presence, then identify which "
                "aggregate observable fields are missing from relational edge "
                "construction. Do not use owner/truth metadata as a selector and do "
                "not change production ordering."
            ),
        },
        "raw_identifier_leak_check": ranking["raw_identifier_leak_check"],
    }

    OUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
