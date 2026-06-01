"""Diagnostic-only PHASE2 responsibility-map v3.1 from DataSynth owner metadata.

V3.1 reconciles the fixed5_ownermeta_ic metadata with the audit-rule-first
responsibility policy. Detector outputs are never used for owner assignment.
"""

# ruff: noqa: E402

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.scripts import measure_phase2_family_responsibility_recall_fixed5_20260530 as v1

CANDIDATE_NAME = "datasynth_manipulation_v7_candidate_fixed5_ownermeta_ic"
TRUTH_PATH = ROOT / "data" / "journal" / "primary" / CANDIDATE_NAME / "labels" / (
    "manipulated_entry_truth.csv"
)
OUT_JSON = (
    ROOT
    / "artifacts"
    / "phase2_family_responsibility_recall_v31_fixed5_ownermeta_ic_20260530.json"
)
V3_ARTIFACT = (
    ROOT
    / "artifacts"
    / "phase2_family_responsibility_recall_v3_fixed5_ownermeta_ic_20260530.json"
)
PHASE2_FAMILIES = ["intercompany", "relational", "duplicate", "timeseries", "unsupervised"]
OWNER_FAMILIES = ["phase1", *PHASE2_FAMILIES]
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
}


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _truth_hash(raw_id: str) -> str:
    return "truth_" + hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:24]


def _load_truth() -> pd.DataFrame:
    if not TRUTH_PATH.exists():
        raise FileNotFoundError(f"missing truth metadata: {TRUTH_PATH}")
    return pd.read_csv(TRUTH_PATH, dtype=str).fillna("")


def _bool_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(False, index=df.index)
    return df[column].astype(str).str.lower().eq("true")


def _role_series(df: pd.DataFrame, column: str, value: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(False, index=df.index)
    return df[column].astype(str).str.lower().eq(value)


def _owner_masks(df: pd.DataFrame) -> dict[str, dict[str, pd.Series]]:
    scenario = df["manipulation_scenario"].astype(str)
    approval = scenario.eq("approval_sod_bypass")
    circular = scenario.eq("circular_related_party_transaction")
    embezzlement = scenario.eq("embezzlement_concealment")
    expense = scenario.eq("expense_capitalization")
    period_end = scenario.eq("period_end_adjustment_manipulation")
    suspense = scenario.eq("suspense_account_abuse")
    fictitious = scenario.eq("fictitious_entry")
    return {
        "phase1": {
            "primary": expense | period_end | suspense | approval | embezzlement,
            "secondary": df["truth_owner_secondary"].astype(str).eq("phase1"),
            "context": df["truth_owner_context"].astype(str).eq("phase1"),
        },
        "intercompany": {
            "primary": _bool_series(df, "injected_intercompany_primary"),
            "secondary": pd.Series(False, index=df.index),
            "context": pd.Series(False, index=df.index),
        },
        "relational": {
            "primary": circular & _bool_series(df, "injected_relationship_edge_primary"),
            "secondary": approval | embezzlement,
            "context": _bool_series(df, "relational_context_target"),
        },
        "duplicate": {
            "primary": pd.Series(False, index=df.index),
            "secondary": pd.Series(False, index=df.index),
            "context": embezzlement,
        },
        "timeseries": {
            "primary": _bool_series(df, "injected_timing_primary"),
            "secondary": pd.Series(False, index=df.index),
            "context": _role_series(df, "timing_role", "context"),
        },
        "unsupervised": {
            "primary": fictitious & _bool_series(df, "broad_statistical_only_owner"),
            "secondary": pd.Series(False, index=df.index),
            "context": _role_series(df, "statistical_anomaly_role", "companion")
            | df["truth_owner_context"].astype(str).eq("unsupervised")
            | suspense,
        },
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator <= 0 else numerator / denominator


def _scenario_mask_counts(
    df: pd.DataFrame,
    masks: dict[str, dict[str, pd.Series]],
) -> dict[str, dict[str, dict[str, int]]]:
    out: dict[str, dict[str, dict[str, int]]] = {}
    for scenario, group in df.groupby("manipulation_scenario"):
        scenario_idx = group.index
        out[str(scenario)] = {
            family: {
                role: int(mask.loc[scenario_idx].sum())
                for role, mask in role_masks.items()
            }
            for family, role_masks in masks.items()
        }
    return out


def _native_top500_matches_by_role(
    native: dict[str, Any],
    df: pd.DataFrame,
    masks: dict[str, dict[str, pd.Series]],
    *,
    family: str,
    role: str,
) -> int:
    scenario_counts = _scenario_mask_counts(df, masks)
    matched = 0
    for scenario, values in native["top500_scenario_matrix"].items():
        scenario_total = int(values["truth_n"])
        role_count = scenario_counts.get(scenario, {}).get(family, {}).get(role, 0)
        if scenario_total:
            matched += round(int(values[family]["matched"]) * role_count / scenario_total)
    return int(matched)


def _phase1_sets() -> dict[str, set[str]]:
    truth_ids = set(_load_truth()["document_id"].astype(str))
    return v1._phase1_truth_sets(truth_ids)


def _primary_denominators(
    df: pd.DataFrame,
    masks: dict[str, dict[str, pd.Series]],
) -> dict[str, Any]:
    primary_sets = {
        family: set(df.loc[role_masks["primary"], "document_id"].astype(str))
        for family, role_masks in masks.items()
    }
    overlap_matrix: dict[str, dict[str, int]] = {}
    for left in OWNER_FAMILIES:
        overlap_matrix[left] = {}
        for right in OWNER_FAMILIES:
            overlap_matrix[left][right] = len(primary_sets[left] & primary_sets[right])
    return {
        "phase1": int(masks["phase1"]["primary"].sum()),
        "phase1_primary_source": (
            "audit_rule_first_reconciled_policy_from_datasynth_scenario_and_family_metadata"
        ),
        "intercompany": int(masks["intercompany"]["primary"].sum()),
        "relational": int(masks["relational"]["primary"].sum()),
        "duplicate": int(masks["duplicate"]["primary"].sum()),
        "duplicate_primary_status": "pending_pair_evidence_validation",
        "duplicate_primary_candidate_count": int(
            (
                _bool_series(df, "duplicate_primary_target")
                | _bool_series(df, "injected_duplicate_like")
            ).sum()
        ),
        "timeseries": int(masks["timeseries"]["primary"].sum()),
        "unsupervised": int(masks["unsupervised"]["primary"].sum()),
        "overlap_matrix": overlap_matrix,
        "overlap_summary": {
            "intercompany_and_relational": overlap_matrix["intercompany"]["relational"],
            "nonzero_pairwise_primary_overlaps": {
                f"{left}_and_{right}": overlap_matrix[left][right]
                for index, left in enumerate(OWNER_FAMILIES)
                for right in OWNER_FAMILIES[index + 1 :]
                if overlap_matrix[left][right]
            },
            "phase1_primary_and_relational_secondary": int(
                (masks["phase1"]["primary"] & masks["relational"]["secondary"]).sum()
            ),
            "phase1_primary_and_duplicate_companion": int(
                (masks["phase1"]["primary"] & masks["duplicate"]["context"]).sum()
            ),
            "phase1_primary_and_unsupervised_companion": int(
                (masks["phase1"]["primary"] & masks["unsupervised"]["context"]).sum()
            ),
        },
    }


def _phase1_primary_match_count(mask: pd.Series, df: pd.DataFrame, phase1_set: set[str]) -> int:
    return int(df.loc[mask, "document_id"].astype(str).isin(phase1_set).sum())


def _primary_owner_target_recall(
    native: dict[str, Any],
    df: pd.DataFrame,
    masks: dict[str, dict[str, pd.Series]],
    phase1_sets: dict[str, set[str]],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for family in OWNER_FAMILIES:
        denominator = int(masks[family]["primary"].sum())
        if family == "phase1":
            matched = _phase1_primary_match_count(
                masks[family]["primary"], df, phase1_sets["candidate_or_higher"]
            )
        else:
            matched = _native_top500_matches_by_role(
                native, df, masks, family=family, role="primary"
            )
        out[family] = {
            "primary_truth_docs": denominator,
            "status": (
                "pending_pair_evidence_validation"
                if family == "duplicate" and denominator == 0
                else "available"
            ),
            "native_top500_matched_docs": matched,
            "native_top500_primary_recall": _ratio(matched, denominator),
            "portfolio_620_matched_docs": matched,
            "portfolio_620_recall": _ratio(matched, 620),
        }
    return out


def _phase1_action_tier_comparison(
    action: dict[str, Any],
    primary_recall: dict[str, Any],
    df: pd.DataFrame,
    masks: dict[str, dict[str, pd.Series]],
    phase1_sets: dict[str, set[str]],
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "portfolio_note": (
            "Family rows may include co-primary overlap; portfolio totals must deduplicate "
            "hashed truth cases."
        )
    }
    tier_sets = {
        "immediate_high": phase1_sets["immediate"],
        "review_or_higher": phase1_sets["review_or_higher"],
        "candidate_or_higher": phase1_sets["candidate_or_higher"],
    }
    for family in OWNER_FAMILIES:
        mask = masks[family]["primary"]
        denominator = int(mask.sum())
        row: dict[str, Any] = {"primary_truth_docs": denominator}
        for tier_name, phase1_set in tier_sets.items():
            row[f"phase1_{tier_name}_covered_primary_docs"] = _phase1_primary_match_count(
                mask, df, phase1_set
            )
        if family in PHASE2_FAMILIES:
            family_action = action["incremental_vs_phase1_action_tiers"][family]
            surface = "top500" if family == "unsupervised" else "strong_or_moderate"
            aggregate = family_action[surface]
            matched_total = int(aggregate["vs_phase1_immediate"]["matched_truth_docs"])
            matched_primary = int(primary_recall[family]["native_top500_matched_docs"])
            scale = matched_primary / matched_total if matched_total else 0.0
            row["phase2_family_matched_primary_docs"] = matched_primary
            row["phase2_adds_outside_phase1_immediate_high_estimated"] = round(
                aggregate["vs_phase1_immediate"]["phase1_not_in_tier_truth_docs"] * scale
            )
            row["phase2_adds_outside_phase1_review_or_higher_estimated"] = round(
                aggregate["vs_phase1_review_or_higher"]["phase1_not_in_tier_truth_docs"]
                * scale
            )
            row["phase2_adds_outside_phase1_candidate_or_higher_estimated"] = round(
                aggregate["vs_phase1_candidate_or_higher"]["phase1_not_in_tier_truth_docs"]
                * scale
            )
            row["phase2_add_estimation_note"] = (
                "Aggregate-only estimate from existing action-tier artifact; owner "
                "assignment remains detector-blind."
            )
        out[family] = row
    return out


def _context_companion_contribution(
    native: dict[str, Any],
    df: pd.DataFrame,
    masks: dict[str, dict[str, pd.Series]],
) -> dict[str, Any]:
    specs = {
        "relational_secondary": ("relational", "secondary"),
        "duplicate_context": ("duplicate", "context"),
        "timeseries_context": ("timeseries", "context"),
        "unsupervised_companion": ("unsupervised", "context"),
    }
    out: dict[str, Any] = {
        "metric_role": "context_companion_lifecycle_not_primary_target_recall"
    }
    for label, (family, role) in specs.items():
        denominator = int(masks[family][role].sum())
        matched = _native_top500_matches_by_role(native, df, masks, family=family, role=role)
        out[label] = {
            "truth_docs": denominator,
            "matched_docs": matched,
            "recall": _ratio(matched, denominator),
            "product_role": "evidence_companion_not_primary_recall",
        }
    return out


def _v3_to_v31_policy_diff() -> dict[str, Any]:
    return {
        "approval_sod_bypass": {
            "v3_primary": ["relational"],
            "v31_primary": ["phase1"],
            "v31_secondary": ["relational"],
            "reason": (
                "approval/SOD is control-rule first unless R-family approval-edge "
                "primary product spec is locked"
            ),
        },
        "embezzlement_concealment": {
            "v3_primary": ["duplicate"],
            "v31_primary": ["phase1"],
            "v31_companion": ["duplicate", "relational", "unsupervised"],
            "reason": (
                "corporate card/private-use is policy/P2P review first; duplicate "
                "pair evidence is companion until pair validation is proven"
            ),
        },
        "suspense_account_abuse": {
            "v3_primary": ["unsupervised"],
            "v31_primary": ["phase1"],
            "v31_companion": ["unsupervised"],
            "reason": "suspense account abuse is account/policy review first",
        },
        "fictitious_entry": {
            "v3_primary": ["unsupervised"],
            "v31_primary": ["unsupervised"],
            "reason": "broad amount/account-pattern outlier can be VAE primary",
        },
        "circular_related_party_transaction": {
            "v3_primary": ["intercompany", "relational"],
            "v31_primary": ["intercompany", "relational"],
            "reason": (
                "reciprocal IC and related-party edge are both primary evidence semantics"
            ),
        },
        "unusual_timing": {
            "v3_primary": ["timeseries"],
            "v31_primary": ["timeseries"],
            "reason": "timing-window semantics remain timeseries primary",
        },
        "expense_capitalization": {
            "v3_primary": ["phase1"],
            "v31_primary": ["phase1"],
            "reason": "account classification review remains audit-rule first",
        },
        "period_end_adjustment_manipulation": {
            "v3_primary": ["phase1"],
            "v31_primary": ["phase1"],
            "v31_context": ["timeseries"],
            "reason": "period-end timing remains context, not timeseries primary",
        },
    }


def _owner_assignments(
    df: pd.DataFrame,
    masks: dict[str, dict[str, pd.Series]],
) -> list[dict[str, Any]]:
    assignments: list[dict[str, Any]] = []
    for idx, row in df.iterrows():
        roles: dict[str, list[str]] = {}
        for family, role_masks in masks.items():
            active_roles = [role for role, mask in role_masks.items() if bool(mask.loc[idx])]
            if active_roles:
                roles[family] = active_roles
        assignments.append(
            {
                "truth_case_hash": _truth_hash(str(row["document_id"])),
                "scenario": str(row["manipulation_scenario"]),
                "owner_roles": roles,
            }
        )
    return assignments


def _data_quality_and_policy_checks(
    payload: dict[str, Any],
    df: pd.DataFrame,
    masks: dict[str, dict[str, pd.Series]],
) -> dict[str, Any]:
    text = json.dumps(payload, ensure_ascii=False)
    raw_ids = set(df["document_id"].astype(str))
    key_count = sum(1 for key in _walk_keys(payload) if key.lower() in FORBIDDEN_IDENTIFIER_KEYS)
    raw_leak_count = sum(1 for raw_id in raw_ids if raw_id in text)
    circular = df["manipulation_scenario"].eq("circular_related_party_transaction")
    period_end = df["manipulation_scenario"].eq("period_end_adjustment_manipulation")
    v1_artifact = ROOT / "artifacts" / "phase2_family_responsibility_recall_fixed5_20260530.json"
    v2_artifact = (
        ROOT / "artifacts" / "phase2_family_responsibility_recall_v2_fixed5_20260530.json"
    )
    v21_artifact = (
        ROOT / "artifacts" / "phase2_family_responsibility_recall_v21_fixed5_20260530.json"
    )
    checks = {
        "truth_docs": int(len(df)),
        "anomaly_label_docs": int(len(df)),
        "v31_expected_denominator_counts_match": {
            "phase1": int(masks["phase1"]["primary"].sum()) == 397,
            "intercompany": int(masks["intercompany"]["primary"].sum()) == 34,
            "relational": int(masks["relational"]["primary"].sum()) == 34,
            "duplicate": int(masks["duplicate"]["primary"].sum()) == 0,
            "timeseries": int(masks["timeseries"]["primary"].sum()) == 21,
            "unsupervised": int(masks["unsupervised"]["primary"].sum()) == 168,
        },
        "non_circular_injected_intercompany_primary_count": int(
            (masks["intercompany"]["primary"] & ~circular).sum()
        ),
        "circular_injected_intercompany_primary_count": int(
            (masks["intercompany"]["primary"] & circular).sum()
        ),
        "timeseries_primary_count": int(masks["timeseries"]["primary"].sum()),
        "period_end_timeseries_primary_count": int(
            (masks["timeseries"]["primary"] & period_end).sum()
        ),
        "raw_identifier_leak_count": raw_leak_count,
        "forbidden_identifier_key_count": key_count,
        "detector_output_score_rank_topn_matched_used_for_owner_assignment": False,
        "owner_assignment_uses_detector_output_score_rank_topn_matched_result": False,
        "v1_v2_v21_v3_artifacts_retained": (
            v1_artifact.exists()
            and v2_artifact.exists()
            and v21_artifact.exists()
            and V3_ARTIFACT.exists()
        ),
    }
    return checks


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


def build_payload() -> dict[str, Any]:
    df = _load_truth()
    masks = _owner_masks(df)
    native = v1._load_json(v1.NATIVE_RECALL_ARTIFACT)
    action = v1._load_json(v1.ACTION_TIER_ARTIFACT)
    phase1_sets = _phase1_sets()
    primary_recall = _primary_owner_target_recall(native, df, masks, phase1_sets)
    action_comparison = _phase1_action_tier_comparison(
        action, primary_recall, df, masks, phase1_sets
    )
    for family in PHASE2_FAMILIES:
        primary_recall[family]["phase1_action_tier_outside_primary_capture"] = {
            "outside_phase1_immediate_high_estimated": action_comparison[family][
                "phase2_adds_outside_phase1_immediate_high_estimated"
            ],
            "outside_phase1_review_or_higher_estimated": action_comparison[family][
                "phase2_adds_outside_phase1_review_or_higher_estimated"
            ],
            "outside_phase1_candidate_or_higher_estimated": action_comparison[family][
                "phase2_adds_outside_phase1_candidate_or_higher_estimated"
            ],
            "basis": "aggregate_action_tier_estimate_not_owner_assignment_input",
        }
    payload: dict[str, Any] = {
        "metadata": {
            "generated_at": _now_iso(),
            "candidate_name": CANDIDATE_NAME,
            "v3_artifact_path": str(V3_ARTIFACT.relative_to(ROOT).as_posix()),
            "input_truth_path": str(TRUTH_PATH.relative_to(ROOT).as_posix()),
            "policy_model": "audit_rule_first_reconciled_with_datasynth_family_flags",
            "v3_status": "traceability_artifact_not_final_policy",
            "v31_status": "audit_rule_first_reconciled_diagnostic",
            "co_primary_allowed": True,
            "fixed4_used": False,
            "production_ranking_changed": False,
            "production_gate_changed": False,
            "production_fusion_changed": False,
            "detector_outputs_used_for_owner_assignment": False,
            "v1_v2_v21_v3_artifacts_retained": True,
        },
        "v3_to_v31_policy_diff": _v3_to_v31_policy_diff(),
        "primary_denominators_v31": _primary_denominators(df, masks),
        "companion_context_denominators_v31": {
            label: value["truth_docs"]
            for label, value in _context_companion_contribution(native, df, masks).items()
            if isinstance(value, dict) and "truth_docs" in value
        },
        "overlap_matrix": _primary_denominators(df, masks)["overlap_matrix"],
        "primary_owner_target_recall_v31": primary_recall,
        "phase1_action_tier_comparison_v31": action_comparison,
        "context_companion_contribution_v31": _context_companion_contribution(
            native, df, masks
        ),
        "owner_assignments": _owner_assignments(df, masks),
        "decision_summary": {
            "intercompany": (
                "Primary denominator is available; circular 34 are co-primary with "
                "relational by policy."
            ),
            "relational": (
                "Primary denominator is circular related-party only; approval and "
                "embezzlement relationship evidence are secondary."
            ),
            "duplicate": (
                "Primary denominator is pending pair evidence validation; current "
                "embezzlement duplicate-like metadata is companion evidence."
            ),
            "timeseries": (
                "Primary denominator is available through timing metadata; period-end "
                "remains context."
            ),
            "unsupervised": (
                "Fictitious-entry broad amount/account-pattern targets remain primary; "
                "suspense moves to PHASE1 primary with VAE companion context."
            ),
            "phase1": (
                "Phase1 primary is policy-derived because a family-specific "
                "phase1_primary_target boolean is not yet exposed."
            ),
        },
    }
    payload["data_quality_and_policy_checks"] = _data_quality_and_policy_checks(
        payload, df, masks
    )
    checks = payload["data_quality_and_policy_checks"]
    if checks["raw_identifier_leak_count"] != 0:
        raise ValueError("raw truth identifier leak detected")
    if checks["forbidden_identifier_key_count"] != 0:
        raise ValueError("forbidden identifier key detected")
    return payload


def main(_argv: list[str] | None = None) -> int:
    payload = build_payload()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT_JSON.relative_to(ROOT).as_posix()}")
    print(
        json.dumps(
            {
                "primary_denominators_v31": payload["primary_denominators_v31"],
                "primary_owner_target_recall_v31": payload[
                    "primary_owner_target_recall_v31"
                ],
                "context_companion_contribution_v31": payload[
                    "context_companion_contribution_v31"
                ],
                "data_quality_and_policy_checks": payload["data_quality_and_policy_checks"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
