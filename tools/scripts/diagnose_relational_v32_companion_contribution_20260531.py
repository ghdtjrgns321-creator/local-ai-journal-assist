"""Aggregate-only v3.2d relational companion contribution diagnostic.

This script does not rebuild or change relational case ordering. It re-reads
the adopted relational review-surface artifact and interprets it against the
v3.2d responsibility map where relational is a companion evidence lane.
"""

from __future__ import annotations

import csv
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RESPONSIBILITY_ARTIFACT = (
    ROOT
    / "artifacts"
    / "phase2_family_responsibility_recall_v32_fixed5_ownermeta_v32d_20260531.json"
)
RELATIONAL_CANDIDATE_ARTIFACT = (
    ROOT / "artifacts" / "relational_ranking_candidates_fixed5_20260529.json"
)
RELATIONAL_NATIVE_ARTIFACT = (
    ROOT / "artifacts" / "phase2_relational_native_case_diagnostic_fixed5_20260528.json"
)
TRUTH_CSV = (
    ROOT
    / "data"
    / "journal"
    / "primary"
    / "datasynth_manipulation_v7_candidate_fixed5_ownermeta_v32d"
    / "labels"
    / "manipulated_entry_truth.csv"
)
OUT_JSON = (
    ROOT / "artifacts" / "relational_v32_companion_contribution_20260531.json"
)

ADOPTED_SURFACE = "structural_moderate_audit_then_business_lane_split_surface"
COMPANION_SCENARIOS = {
    "approval_sod_bypass": "approval_sod",
    "circular_related_party_transaction": "ic_circular",
    "embezzlement_concealment": "embezzlement",
}
STRUCTURAL_RULES = {"R03", "R07"}
MODERATE_RULES = {"R01", "R02"}
CONTEXT_RULES = {"R05", "R06"}
FORBIDDEN_IDENTIFIER_KEYS = {
    "document_id",
    "document_ids",
    "raw_document_id",
    "raw_document_ids",
    "row_id",
    "row_ids",
    "raw_row_id",
    "raw_row_ids",
    "phase2_case_id",
    "phase2_case_ids",
    "relationship_group_id",
    "duplicate_pair_group_id",
    "relationship_source_entity",
    "relationship_target_entity",
}


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _truth_rows() -> list[dict[str, str]]:
    with TRUTH_CSV.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _is_true(value: str) -> bool:
    return str(value).strip().lower() == "true"


def _scenario_denominators(rows: list[dict[str, str]]) -> dict[str, int]:
    out = {"ic_circular": 0, "approval_sod": 0, "embezzlement": 0}
    for row in rows:
        scenario = row.get("manipulation_scenario", "")
        if scenario in COMPANION_SCENARIOS and _is_true(
            row.get("relationship_companion_target", "")
        ):
            out[COMPANION_SCENARIOS[scenario]] += 1
    return out


def _companion_matched_from_scenarios(scenario_counts: dict[str, int]) -> dict[str, Any]:
    by_segment = {
        segment: int(scenario_counts.get(scenario, 0))
        for scenario, segment in COMPANION_SCENARIOS.items()
    }
    return {
        "matched_docs": sum(by_segment.values()),
        "by_segment": by_segment,
        "excluded_non_companion_scenario_counts": {
            scenario: int(count)
            for scenario, count in scenario_counts.items()
            if scenario not in COMPANION_SCENARIOS
        },
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator <= 0 else numerator / denominator


def _topn_companion_metrics(
    adopted: dict[str, Any],
    denominator: int,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for topn in ("100", "500", "1000"):
        row = adopted["topn"][topn]
        matched = _companion_matched_from_scenarios(row.get("scenario_counts", {}))
        out[f"top{topn}"] = {
            "matched_docs": matched["matched_docs"],
            "recall": _ratio(matched["matched_docs"], denominator),
            "by_segment": matched["by_segment"],
            "excluded_non_companion_scenario_counts": matched[
                "excluded_non_companion_scenario_counts"
            ],
            "all_truth_docs_matched_by_surface": int(row["matched"]),
            "sub_rule_distribution": {
                str(rule): int(count)
                for rule, count in row.get("sub_rule_distribution", {}).items()
            },
            "evidence_tier_distribution": {
                str(tier): int(count)
                for tier, count in row.get("evidence_tier_distribution", {}).items()
            },
            "r05_r06_share": float(row.get("r05_r06_share", 0.0)),
            "false_positive_pressure_proxy": row.get("false_positive_pressure_proxy", {}),
        }
    return out


def _rule_family_breakdown(sub_rule_counts: dict[str, int]) -> dict[str, Any]:
    structural = sum(int(sub_rule_counts.get(rule, 0)) for rule in STRUCTURAL_RULES)
    moderate = sum(int(sub_rule_counts.get(rule, 0)) for rule in MODERATE_RULES)
    context = sum(int(sub_rule_counts.get(rule, 0)) for rule in CONTEXT_RULES)
    total = sum(int(value) for value in sub_rule_counts.values())
    return {
        "structural_r03_r07": structural,
        "moderate_r01_r02": moderate,
        "context_r05_r06": context,
        "total": total,
        "structural_share": _ratio(structural, total),
        "moderate_share": _ratio(moderate, total),
        "context_share": _ratio(context, total),
    }


def _topn_rule_breakdown(adopted: dict[str, Any]) -> dict[str, Any]:
    return {
        f"top{topn}": _rule_family_breakdown(
            {
                str(rule): int(count)
                for rule, count in adopted["topn"][topn]
                .get("sub_rule_distribution", {})
                .items()
            }
        )
        for topn in ("100", "500", "1000")
    }


def _native_baseline(native: dict[str, Any], denominator: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for topn in ("100", "500", "1000"):
        scenario_key = f"top{topn}_truth_scenario_counts"
        if scenario_key not in native:
            continue
        matched = _companion_matched_from_scenarios(native[scenario_key])
        out[f"top{topn}"] = {
            "matched_docs": matched["matched_docs"],
            "recall": _ratio(matched["matched_docs"], denominator),
            "by_segment": matched["by_segment"],
            "excluded_non_companion_scenario_counts": matched[
                "excluded_non_companion_scenario_counts"
            ],
        }
    return out


def _walk_keys(value: Any) -> list[str]:
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


def _raw_leak_check(payload: dict[str, Any]) -> dict[str, int]:
    text = json.dumps(payload, ensure_ascii=False)
    keys = {key.lower() for key in _walk_keys(payload)}
    return {
        "doc_like_token_count": len(re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-", text)),
        "forbidden_identifier_key_count": sum(
            1 for key in keys if key in FORBIDDEN_IDENTIFIER_KEYS
        ),
        "phase2_case_id_like_token_count": text.lower().count("p2_relational_edge_"),
    }


def build_payload() -> dict[str, Any]:
    responsibility = _load_json(RESPONSIBILITY_ARTIFACT)
    ranking = _load_json(RELATIONAL_CANDIDATE_ARTIFACT)
    native = _load_json(RELATIONAL_NATIVE_ARTIFACT)
    rows = _truth_rows()
    denominator = int(
        responsibility["companion_context_denominators_v32"]["relational_companion"]
    )
    adopted = ranking["candidate_rankings"][ADOPTED_SURFACE]
    by_segment_denominator = _scenario_denominators(rows)
    payload: dict[str, Any] = {
        "metadata": {
            "generated_at": _now_iso(),
            "diagnostic_scope": "v3.2d relational companion evidence contribution",
            "owner_metadata_version": responsibility["metadata"]["owner_metadata_version"],
            "responsibility_artifact": RESPONSIBILITY_ARTIFACT.name,
            "relational_surface_artifact": RELATIONAL_CANDIDATE_ARTIFACT.name,
            "adopted_surface": ADOPTED_SURFACE,
            "production_ordering_changed": False,
            "production_gate_changed": False,
            "phase1_ranking_changed": False,
            "phase2_fusion_changed": False,
            "truth_used_for_scoring": False,
            "truth_used_for_denominator_and_aggregate_evaluation": True,
        },
        "role_contract": {
            "primary_denominator": int(
                responsibility["primary_denominators_v32"]["relational"]
            ),
            "primary_status": responsibility["primary_denominators_v32"]["status"][
                "relational"
            ],
            "companion_denominator": denominator,
            "by_segment_denominator": by_segment_denominator,
            "interpretation": (
                "Relational is measured as relationship companion evidence in v3.2d; "
                "primary recall tuning is out of scope."
            ),
        },
        "adopted_surface_companion_recall": _topn_companion_metrics(adopted, denominator),
        "native_current_companion_baseline": _native_baseline(native, denominator),
        "sub_rule_case_counts": native["sub_rule_case_counts"],
        "adopted_surface_rule_breakdown": _topn_rule_breakdown(adopted),
        "r05_r06_review_burden": {
            "case_counts": {
                "R05": int(native["sub_rule_case_counts"]["R05"]),
                "R06": int(native["sub_rule_case_counts"]["R06"]),
            },
            "share_of_all_relational_cases": _ratio(
                int(native["sub_rule_case_counts"]["R05"])
                + int(native["sub_rule_case_counts"]["R06"]),
                int(native["case_count"]),
            ),
            "adopted_surface_top500_r05_r06_share": adopted["topn"]["500"].get(
                "r05_r06_share"
            ),
            "policy": (
                "R05/R06 remain context/export burden lanes and are not mixed into "
                "the adopted primary review surface."
            ),
        },
        "evidence_contribution_top500": {
            "all_surface_truth_docs": int(adopted["topn"]["500"]["matched"]),
            "companion_truth_docs": _companion_matched_from_scenarios(
                adopted["topn"]["500"].get("scenario_counts", {})
            )["matched_docs"],
            "relationship_rule_evidence": adopted["relational_evidence_incremental"]["500"],
        },
        "decision_summary": {
            "product_default_ordering_changed": False,
            "relational_primary_recall_applicable": False,
            "companion_contribution": (
                "Adopted surface lifts relationship companion evidence without "
                "treating relational as a primary target family."
            ),
            "next_step": (
                "Use this as a monitoring artifact; do not tune relational primary "
                "recall until relationship-only primary scenarios exist."
            ),
        },
    }
    payload["raw_identifier_leak_check"] = _raw_leak_check(payload)
    if any(payload["raw_identifier_leak_check"].values()):
        raise ValueError(
            f"raw identifier leak check failed: {payload['raw_identifier_leak_check']}"
        )
    return payload


def main() -> int:
    payload = build_payload()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT_JSON.relative_to(ROOT).as_posix()}")
    print(
        json.dumps(
            {
                "role_contract": payload["role_contract"],
                "adopted_surface_companion_recall": payload[
                    "adopted_surface_companion_recall"
                ],
                "raw_identifier_leak_check": payload["raw_identifier_leak_check"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
