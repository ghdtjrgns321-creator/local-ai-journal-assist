"""Diagnostic-only PHASE2 responsibility-map v2.1 with owner roles.

V2.1 keeps the v2 owner_roles structure and applies the audit-rule-first
policy cleanup for relational and unsupervised responsibilities.
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field, field_validator

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.scripts import measure_phase2_family_responsibility_recall_fixed5_20260530 as v1

DATASET_NAME = v1.DATASET_NAME
OUT_JSON = ROOT / "artifacts" / "phase2_family_responsibility_recall_v21_fixed5_20260530.json"
OWNER_ENUM = v1.OWNER_ENUM
PHASE2_FAMILIES = v1.PHASE2_FAMILIES
ROLE_ENUM = (
    "primary",
    "secondary",
    "companion_context",
    "baseline_review",
    "no_clear_owner",
)
SCHEMA_VERSION = "phase2_family_responsibility_owner_role_schema_v21_20260530"
RULE_VERSION = "phase2_family_responsibility_owner_role_rules_v21_20260530"

Owner = Literal[
    "phase1",
    "intercompany",
    "relational",
    "duplicate",
    "timeseries",
    "unsupervised",
    "no_clear_owner",
]
OwnerRole = Literal[
    "primary",
    "secondary",
    "companion_context",
    "baseline_review",
    "no_clear_owner",
]
Confidence = Literal["high", "medium", "low"]
NoOwnerReason = Literal[
    "none",
    "mixed_signal",
    "insufficient_semantic_metadata",
    "normal_like_truth_label",
    "no_family_semantic_match",
    "multiple_equal_owners",
]
AssignmentBasis = Literal[
    "scenario_metadata",
    "injected_pattern_metadata",
    "semantic_transaction_attributes",
    "llm_semantic_label",
]


class OwnerAssignmentV2(BaseModel):
    truth_case_hash: str
    expected_owners: list[Owner]
    owner_roles: dict[Owner, OwnerRole]
    scenario_groups: list[str]
    owner_confidence: Confidence
    no_clear_owner_reason: NoOwnerReason
    assignment_basis: list[AssignmentBasis]
    audit_rationale: str = Field(min_length=1, max_length=700)

    @field_validator("expected_owners")
    @classmethod
    def _owners_are_set(cls, value: list[Owner]) -> list[Owner]:
        if not value:
            return ["no_clear_owner"]
        if "no_clear_owner" in value and len(value) > 1:
            raise ValueError("no_clear_owner cannot be combined with other owners")
        return sorted(set(value), key=OWNER_ENUM.index)

    @field_validator("owner_roles")
    @classmethod
    def _roles_are_consistent(cls, value: dict[Owner, OwnerRole]) -> dict[Owner, OwnerRole]:
        if not value:
            return {"no_clear_owner": "no_clear_owner"}
        if value.get("no_clear_owner") == "no_clear_owner" and len(value) > 1:
            raise ValueError("no_clear_owner role cannot be combined with other roles")
        for owner, role in value.items():
            if owner == "no_clear_owner" and role != "no_clear_owner":
                raise ValueError("no_clear_owner must use no_clear_owner role")
            if owner != "no_clear_owner" and role == "no_clear_owner":
                raise ValueError("only no_clear_owner may use no_clear_owner role")
        return dict(sorted(value.items(), key=lambda item: OWNER_ENUM.index(item[0])))


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _explicit_duplicate_like_metadata(summary: dict[str, Any]) -> bool:
    if "has_explicit_duplicate_like_metadata" in summary:
        return any(
            bool(summary.get(flag))
            for flag in (
                "has_explicit_duplicate_like_metadata",
                "duplicate_pair_semantic_group_present",
                "duplicate_similarity_intent_present",
                "duplicate_similarity_injection_source_present",
                "duplicate_primary_target_metadata",
            )
        )
    metadata_flags = (
        summary.get("has_explicit_duplicate_like_metadata"),
        summary.get("duplicate_pair_semantic_group_present"),
        summary.get("duplicate_similarity_intent_present"),
        summary.get("duplicate_similarity_injection_source_present"),
        summary.get("duplicate_primary_target_metadata"),
    )
    if any(bool(flag) for flag in metadata_flags):
        return True
    text = " ".join(
        [
            str(summary.get("datasynth_category", "")),
            str(summary.get("injected_pattern_summary", "")),
        ]
    ).lower()
    explicit_tokens = (
        "duplicate",
        "similarity_injection",
        "duplicate_pair",
        "same_invoice",
        "same_reference",
    )
    return any(token in text for token in explicit_tokens)


def _assignment_from_roles(
    summary: dict[str, Any],
    roles: dict[Owner, OwnerRole],
    *,
    scenario_groups: list[str],
    confidence: Confidence,
    reason: NoOwnerReason = "none",
    rationale: str,
) -> OwnerAssignmentV2:
    expected = list(roles)
    if not expected:
        expected = ["no_clear_owner"]
        roles = {"no_clear_owner": "no_clear_owner"}
        reason = "no_family_semantic_match"
    return OwnerAssignmentV2(
        truth_case_hash=str(summary["truth_case_hash"]),
        expected_owners=expected,
        owner_roles=roles,
        scenario_groups=scenario_groups,
        owner_confidence=confidence,
        no_clear_owner_reason=reason,
        assignment_basis=[
            "scenario_metadata",
            "injected_pattern_metadata",
            "semantic_transaction_attributes",
        ],
        audit_rationale=rationale,
    )


def assign_owner_roles_rule_v21(summary: dict[str, Any]) -> OwnerAssignmentV2:
    scenario = str(summary["datasynth_scenario"])
    duplicate_like = _explicit_duplicate_like_metadata(summary)
    if scenario == "circular_related_party_transaction":
        return _assignment_from_roles(
            summary,
            {
                "phase1": "baseline_review",
                "intercompany": "primary",
                "relational": "secondary",
            },
            scenario_groups=["intercompany_reciprocal", "relationship_edge_context"],
            confidence="high",
            rationale=(
                "Round-trip intercompany semantics make intercompany primary; relational "
                "is structural secondary evidence and PHASE1 is baseline review."
            ),
        )
    if scenario == "approval_sod_bypass":
        return _assignment_from_roles(
            summary,
            {"phase1": "primary", "relational": "secondary"},
            scenario_groups=["approval_control_context", "user_approval_relationship_context"],
            confidence="high",
            rationale=(
                "Approval/SOD bypass is PHASE1 policy evidence first; relational "
                "edges are secondary until the detector has explicit approver-edge "
                "primary semantics."
            ),
        )
    if scenario == "embezzlement_concealment":
        if duplicate_like:
            return _assignment_from_roles(
                summary,
                {
                    "phase1": "baseline_review",
                    "duplicate": "primary",
                    "relational": "secondary",
                },
                scenario_groups=[
                    "outflow_or_employee_context",
                    "explicit_duplicate_like_context",
                    "relationship_edge_context",
                ],
                confidence="high",
                rationale=(
                    "Generator metadata marks this as duplicate-like pair evidence, "
                    "so duplicate is the primary family target; PHASE1 remains "
                    "baseline review and relational remains secondary context."
                ),
            )
        return _assignment_from_roles(
            summary,
            {"phase1": "primary", "relational": "secondary"},
            scenario_groups=["outflow_or_employee_context", "relationship_edge_context"],
            confidence="medium",
            rationale=(
                "Concealment semantics are primarily PHASE1 review evidence; relational "
                "edges may support context but are not the primary denominator."
            ),
        )
    if scenario == "period_end_adjustment_manipulation":
        roles: dict[Owner, OwnerRole] = {
            "phase1": "primary",
            "timeseries": "companion_context",
        }
        confidence: Confidence = "medium"
        groups = ["manual_adjustment_context", "period_end_timing_context"]
        if duplicate_like:
            roles["duplicate"] = "primary"
            groups.append("explicit_duplicate_like_context")
        else:
            roles["duplicate"] = "companion_context"
            groups.append("duplicate_metadata_review_needed")
            confidence = "low"
        return _assignment_from_roles(
            summary,
            roles,
            scenario_groups=groups,
            confidence=confidence,
            reason="insufficient_semantic_metadata" if not duplicate_like else "none",
            rationale=(
                "Period-end adjustment is PHASE1 primary; timeseries is context lane per "
                "role lock. Duplicate is not primary without explicit duplicate-like metadata."
            ),
        )
    if scenario == "unusual_timing_manipulation":
        return _assignment_from_roles(
            summary,
            {
                "phase1": "baseline_review",
                "timeseries": "primary",
                "unsupervised": "companion_context",
            },
            scenario_groups=["timing_window_context", "broad_statistical_context"],
            confidence="high",
            rationale="After-hours/timing-window semantics make timeseries the primary target.",
        )
    if scenario == "fictitious_entry":
        return _assignment_from_roles(
            summary,
            {"phase1": "primary", "unsupervised": "companion_context"},
            scenario_groups=["broad_statistical_context", "revenue_or_activity_existence_context"],
            confidence="medium",
            rationale=(
                "Fictitious entry semantics are audit-rule-first PHASE1 primary; "
                "unsupervised remains companion context without an explicit "
                "broad-statistical-only owner label."
            ),
        )
    if scenario == "expense_capitalization":
        return _assignment_from_roles(
            summary,
            {"phase1": "primary", "unsupervised": "companion_context"},
            scenario_groups=["account_classification_context", "broad_statistical_context"],
            confidence="medium",
            rationale=(
                "Expense capitalization is account-classification evidence first; "
                "unsupervised is context, not automatic primary."
            ),
        )
    if scenario == "suspense_account_abuse":
        return _assignment_from_roles(
            summary,
            {"phase1": "primary"},
            scenario_groups=["account_classification_context", "manual_review_context"],
            confidence="medium",
            rationale="Suspense/account-classification abuse is PHASE1 primary evidence.",
        )
    return _assignment_from_roles(
        summary,
        {"no_clear_owner": "no_clear_owner"},
        scenario_groups=["unmapped_truth_semantics"],
        confidence="low",
        reason="no_family_semantic_match",
        rationale="No clear owner family semantic match in sanitized metadata.",
    )


def build_owner_role_assignments(
    summaries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    assignments = [assign_owner_roles_rule_v21(summary).model_dump() for summary in summaries]
    return assignments, {
        "mode": "deterministic_rule_only_v21",
        "schema_version": SCHEMA_VERSION,
        "rule_version": RULE_VERSION,
        "policy_model": "audit_rule_first_evidence_companion",
        "unsupervised_primary_policy": (
            "only explicit broad-statistical-only owner metadata may create an "
            "unsupervised primary denominator"
        ),
        "llm_used": False,
        "v1_artifact_retained_as_inclusive_baseline": True,
    }


def _roles_by_raw_case(
    truth: pd.DataFrame,
    hash_by_raw_id: dict[str, str],
    assignments: list[dict[str, Any]],
) -> dict[str, dict[str, str]]:
    by_hash = {str(item["truth_case_hash"]): item for item in assignments}
    return {
        raw_case_id: dict(by_hash[hash_by_raw_id[raw_case_id]]["owner_roles"])
        for raw_case_id in truth["document_id"].astype(str)
    }


def _role_distribution(assignments: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    counts: dict[str, Counter[str]] = {owner: Counter() for owner in OWNER_ENUM}
    for item in assignments:
        for owner, role in item["owner_roles"].items():
            counts[str(owner)][str(role)] += 1
    return {
        owner: {role: int(counts[owner].get(role, 0)) for role in ROLE_ENUM}
        for owner in OWNER_ENUM
    }


def _scenario_role_counts(
    truth: pd.DataFrame,
    roles_by_raw: dict[str, dict[str, str]],
) -> dict[str, dict[str, dict[str, int]]]:
    out: dict[str, dict[str, dict[str, int]]] = {}
    for scenario, group in truth.groupby("manipulation_scenario"):
        scenario_counts = {owner: {role: 0 for role in ROLE_ENUM} for owner in OWNER_ENUM}
        for raw_case_id in group["document_id"].astype(str):
            for owner, role in roles_by_raw[raw_case_id].items():
                scenario_counts[owner][role] += 1
        out[str(scenario)] = scenario_counts
    return out


def _role_total(roles_by_raw: dict[str, dict[str, str]], owner: str, role: str) -> int:
    return sum(1 for roles in roles_by_raw.values() if roles.get(owner) == role)


def _match_count_by_role(
    native: dict[str, Any],
    truth: pd.DataFrame,
    roles_by_raw: dict[str, dict[str, str]],
    *,
    family: str,
    owner: str,
    role: str,
) -> int:
    scenario_roles = _scenario_role_counts(truth, roles_by_raw)
    matched = 0
    for scenario, values in native["top500_scenario_matrix"].items():
        scenario_total = int(values["truth_n"])
        if scenario_total:
            matched += round(
                int(values[family]["matched"])
                * scenario_roles[scenario][owner][role]
                / scenario_total
            )
    return int(matched)


def _primary_owner_target_recall(
    native: dict[str, Any],
    truth: pd.DataFrame,
    roles_by_raw: dict[str, dict[str, str]],
    phase1_sets: dict[str, set[str]],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for owner in OWNER_ENUM:
        denominator = _role_total(roles_by_raw, owner, "primary")
        if owner == "phase1":
            matched = sum(
                1
                for raw_id, roles in roles_by_raw.items()
                if roles.get(owner) == "primary" and raw_id in phase1_sets["candidate_or_higher"]
            )
        elif owner in PHASE2_FAMILIES:
            matched = _match_count_by_role(
                native,
                truth,
                roles_by_raw,
                family=owner,
                owner=owner,
                role="primary",
            )
        else:
            matched = 0
        out[owner] = {
            "primary_truth_docs": denominator,
            "matched_primary_docs": matched,
            "primary_target_recall": _ratio(matched, denominator),
        }
    return out


def _inclusive_owner_recall(
    native: dict[str, Any],
    truth: pd.DataFrame,
    roles_by_raw: dict[str, dict[str, str]],
    phase1_sets: dict[str, set[str]],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for owner in OWNER_ENUM:
        denominator = sum(1 for roles in roles_by_raw.values() if owner in roles)
        if owner == "phase1":
            matched = sum(
                1
                for raw_id, roles in roles_by_raw.items()
                if owner in roles and raw_id in phase1_sets["candidate_or_higher"]
            )
        elif owner in PHASE2_FAMILIES:
            matched = 0
            scenario_roles = _scenario_role_counts(truth, roles_by_raw)
            for scenario, values in native["top500_scenario_matrix"].items():
                scenario_total = int(values["truth_n"])
                inclusive_count = sum(scenario_roles[scenario][owner].values())
                if scenario_total:
                    matched += round(
                        int(values[owner]["matched"]) * inclusive_count / scenario_total
                    )
        else:
            matched = 0
        out[owner] = {
            "inclusive_truth_docs": denominator,
            "matched_inclusive_docs": int(matched),
            "inclusive_recall": _ratio(int(matched), denominator),
        }
    return out


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def _evidence_contribution(
    native: dict[str, Any],
    truth: pd.DataFrame,
    roles_by_raw: dict[str, dict[str, str]],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for family in PHASE2_FAMILIES:
        secondary = _match_count_by_role(
            native,
            truth,
            roles_by_raw,
            family=family,
            owner=family,
            role="secondary",
        )
        context = _match_count_by_role(
            native,
            truth,
            roles_by_raw,
            family=family,
            owner=family,
            role="companion_context",
        )
        primary = _match_count_by_role(
            native,
            truth,
            roles_by_raw,
            family=family,
            owner=family,
            role="primary",
        )
        out[family] = {
            "matched_primary_docs": primary,
            "matched_secondary_docs": secondary,
            "matched_companion_context_docs": context,
            "secondary_or_context_contribution_docs": secondary + context,
        }
    return out


def _role_truth_count(
    truth: pd.DataFrame,
    roles_by_raw: dict[str, dict[str, str]],
    *,
    owner: str,
    role: str,
) -> int:
    return sum(
        roles_by_raw[raw_case_id].get(owner) == role
        for raw_case_id in truth["document_id"].astype(str)
    )


def _companion_lifecycle_recall(
    native: dict[str, Any],
    truth: pd.DataFrame,
    roles_by_raw: dict[str, dict[str, str]],
) -> dict[str, Any]:
    specs = {
        "relational_secondary": ("relational", "secondary"),
        "duplicate_companion": ("duplicate", "companion_context"),
        "timeseries_companion": ("timeseries", "companion_context"),
        "unsupervised_companion": ("unsupervised", "companion_context"),
    }
    out: dict[str, Any] = {
        "metric_role": "evidence_companion_lifecycle_not_primary_target_recall",
        "product_default_adoption_basis": "not_standalone",
    }
    for key, (family, role) in specs.items():
        truth_docs = _role_truth_count(
            truth,
            roles_by_raw,
            owner=family,
            role=role,
        )
        matched_docs = _match_count_by_role(
            native,
            truth,
            roles_by_raw,
            family=family,
            owner=family,
            role=role,
        )
        out[f"{key}_truth_docs"] = truth_docs
        out[f"{key}_matched_docs"] = matched_docs
        out[f"{key}_recall"] = matched_docs / truth_docs if truth_docs else None
    return out


def _phase1_primary_confidence_split(assignments: list[dict[str, Any]]) -> dict[str, Any]:
    primary = [
        item
        for item in assignments
        if item["owner_roles"].get("phase1") == "primary"
    ]
    low_confidence = [item for item in primary if item["owner_confidence"] == "low"]
    return {
        "phase1_primary_truth_docs": len(primary),
        "phase1_primary_high_medium_confidence_truth_docs": len(primary)
        - len(low_confidence),
        "phase1_primary_low_confidence_truth_docs": len(low_confidence),
        "phase1_primary_low_confidence_reason": (
            "period_end_adjustment companion/metadata uncertainty"
        ),
        "semantic_note": (
            "phase1 primary is responsibility taxonomy; portfolio cumulative "
            "recall is detector performance"
        ),
    }


def _primary_action_tier_outside_estimate(
    action: dict[str, Any],
    primary_recall: dict[str, Any],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for family in PHASE2_FAMILIES:
        family_action = action["incremental_vs_phase1_action_tiers"][family]
        surface = "top500" if family == "unsupervised" else "strong_or_moderate"
        aggregate = family_action[surface]
        matched_total = int(aggregate["vs_phase1_immediate"]["matched_truth_docs"])
        matched_primary = int(primary_recall[family]["matched_primary_docs"])
        scale = matched_primary / matched_total if matched_total else 0.0
        out[family] = {
            "matched_primary_docs": matched_primary,
            "outside_phase1_immediate_high_estimated": round(
                aggregate["vs_phase1_immediate"]["phase1_not_in_tier_truth_docs"] * scale
            ),
            "outside_phase1_review_or_higher_estimated": round(
                aggregate["vs_phase1_review_or_higher"]["phase1_not_in_tier_truth_docs"] * scale
            ),
            "outside_phase1_candidate_or_higher_estimated": round(
                aggregate["vs_phase1_candidate_or_higher"]["phase1_not_in_tier_truth_docs"]
                * scale
            ),
            "estimation_note": (
                "Aggregate-only estimate. Owner assignment remains detector-blind; "
                "existing action-tier artifact supplies matched totals."
            ),
        }
    return out


def _ambiguity_metrics(assignments: list[dict[str, Any]]) -> dict[str, Any]:
    role_sets = [set(item["owner_roles"].values()) for item in assignments]
    return {
        "no_clear_owner": sum("no_clear_owner" in roles for roles in role_sets),
        "review_needed": sum(
            "duplicate_metadata_review_needed" in item["scenario_groups"] for item in assignments
        ),
        "low_confidence": sum(item["owner_confidence"] == "low" for item in assignments),
        "multi_primary": sum(
            list(item["owner_roles"].values()).count("primary") > 1 for item in assignments
        ),
        "context_only": sum(
            roles <= {"companion_context", "baseline_review"} for roles in role_sets
        ),
    }


def _multi_primary_overlap_cases(assignments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    overlaps: list[dict[str, Any]] = []
    for item in assignments:
        primary_owners = [
            owner for owner, role in item["owner_roles"].items() if role == "primary"
        ]
        if len(primary_owners) > 1:
            overlaps.append(
                {
                    "truth_case_hash": item["truth_case_hash"],
                    "primary_owners": primary_owners,
                    "scenario_groups": item["scenario_groups"],
                    "owner_confidence": item["owner_confidence"],
                }
            )
    return overlaps


def _duplicate_gap(assignments: list[dict[str, Any]]) -> dict[str, Any]:
    duplicate_primary = sum(
        item["owner_roles"].get("duplicate") == "primary" for item in assignments
    )
    metadata_available = duplicate_primary > 0
    return {
        "duplicate_primary_denominator_status": (
            "available" if metadata_available else "metadata_insufficient"
        ),
        "duplicate_primary_count": duplicate_primary,
        "metadata_gap": []
        if metadata_available
        else [
            "injected_duplicate_like boolean needed",
            "duplicate_pair_semantic_group needed",
            "reference/amount/text similarity injection source needed",
        ],
    }


def _truth_bool_series(series: pd.Series) -> pd.Series:
    return series.fillna(False).astype(str).str.strip().str.lower().isin(
        {"true", "1", "yes", "y"}
    )


def _duplicate_truth_metadata(truth: pd.DataFrame, truth_csv: Path) -> dict[str, Any]:
    required = {
        "injected_duplicate_like",
        "duplicate_pair_semantic_group",
        "similarity_injection_source",
        "duplicate_primary_target",
        "duplicate_companion_target",
    }
    if not required.issubset(set(truth.columns)):
        return {
            "status": "metadata_unavailable",
            "primary_denominator_status": "metadata_insufficient",
            "required_columns": sorted(required),
            "missing_columns": sorted(required - set(truth.columns)),
        }

    primary_mask = _truth_bool_series(truth["duplicate_primary_target"])
    companion_mask = _truth_bool_series(truth["duplicate_companion_target"])
    injected_mask = _truth_bool_series(truth["injected_duplicate_like"])
    period_end_mask = truth["manipulation_scenario"].astype(str).eq(
        "period_end_adjustment_manipulation"
    )
    pair_sidecar = truth_csv.parent / "duplicate_pair_truth.csv"
    sidecar_status: dict[str, Any] = {
        "pair_sidecar_available": pair_sidecar.exists(),
    }
    if pair_sidecar.exists():
        pair_truth = pd.read_csv(pair_sidecar)
        group_sizes = (
            pair_truth.groupby("duplicate_pair_group_id")["document_id"]
            .nunique()
            .value_counts()
            .sort_index()
        )
        sidecar_status.update(
            {
                "pair_sidecar_row_count": int(len(pair_truth)),
                "pair_sidecar_truth_doc_count": int(
                    pair_truth["document_id"].astype(str).nunique()
                ),
                "pair_group_count": int(
                    pair_truth["duplicate_pair_group_id"].astype(str).nunique()
                ),
                "pair_group_size_distribution": {
                    str(int(size)): int(count)
                    for size, count in group_sizes.items()
                },
            }
        )
    return {
        "status": "available",
        "primary_denominator_status": "available",
        "injected_duplicate_like_doc_count": int(
            truth.loc[injected_mask, "document_id"].astype(str).nunique()
        ),
        "primary_target_doc_count": int(
            truth.loc[primary_mask, "document_id"].astype(str).nunique()
        ),
        "companion_target_doc_count": int(
            truth.loc[companion_mask, "document_id"].astype(str).nunique()
        ),
        "period_end_primary_target_doc_count": int(
            truth.loc[primary_mask & period_end_mask, "document_id"].astype(str).nunique()
        ),
        "primary_scenario_counts": {
            str(scenario): int(count)
            for scenario, count in truth.loc[primary_mask]
            .groupby("manipulation_scenario")["document_id"]
            .nunique()
            .sort_index()
            .items()
        },
        "companion_scenario_counts": {
            str(scenario): int(count)
            for scenario, count in truth.loc[companion_mask]
            .groupby("manipulation_scenario")["document_id"]
            .nunique()
            .sort_index()
            .items()
        },
        "policy": {
            "truth_label_used_for_detector_scoring": False,
            "truth_label_used_for_ranking": False,
            "truth_metadata_used_only_for_denominator": True,
            "period_end_promoted_to_duplicate_primary": False,
        },
        **sidecar_status,
    }


def _leakage_guard(payload: dict[str, Any], truth: pd.DataFrame) -> dict[str, Any]:
    return v1._leakage_guard_report(
        payload,
        truth_raw_ids=set(truth["document_id"].astype(str)),
    )


def build_payload(
    *,
    truth_csv: Path = v1.TRUTH_CSV,
    dataset_name: str = DATASET_NAME,
) -> dict[str, Any]:
    truth = v1._load_truth(truth_csv)
    summaries, hash_by_raw_id = v1.build_sanitized_truth_summaries(truth)
    assignments, labeling_metadata = build_owner_role_assignments(summaries)
    roles_by_raw = _roles_by_raw_case(truth, hash_by_raw_id, assignments)
    phase1_sets = v1._phase1_truth_sets(set(truth["document_id"].astype(str)))
    native = v1._load_json(v1.NATIVE_RECALL_ARTIFACT)
    action = v1._load_json(v1.ACTION_TIER_ARTIFACT)
    primary_recall = _primary_owner_target_recall(native, truth, roles_by_raw, phase1_sets)
    inclusive_recall = _inclusive_owner_recall(native, truth, roles_by_raw, phase1_sets)
    payload: dict[str, Any] = {
        "generated_at": _now_iso(),
        "dataset": dataset_name,
        "diagnostic_only": True,
        "production_ranking_gate_fusion_changed": False,
        "fixed4_used": False,
        "v1_artifact_retained": True,
        "v2_artifact_retained": True,
        "v1_artifact_path": "artifacts/phase2_family_responsibility_recall_fixed5_20260530.json",
        "v2_artifact_path": "artifacts/phase2_family_responsibility_recall_v2_fixed5_20260530.json",
        "portfolio_truth_case_count": int(len(truth)),
        "owner_enum": list(OWNER_ENUM),
        "role_enum": list(ROLE_ENUM),
        "labeling_metadata": labeling_metadata,
        "owner_assignments": assignments,
        "owner_role_distribution": _role_distribution(assignments),
        "primary_owner_target_recall": primary_recall,
        "inclusive_owner_recall": inclusive_recall,
        "evidence_contribution": _evidence_contribution(native, truth, roles_by_raw),
        "companion_context_recall": _companion_lifecycle_recall(
            native,
            truth,
            roles_by_raw,
        ),
        "phase1_action_tier_outside_primary_target_estimate": (
            _primary_action_tier_outside_estimate(action, primary_recall)
        ),
        "phase1_primary_confidence_split": _phase1_primary_confidence_split(assignments),
        "ambiguity": _ambiguity_metrics(assignments),
        "multi_primary_overlap_cases": _multi_primary_overlap_cases(assignments),
        "duplicate_metadata_gap": _duplicate_gap(assignments),
        "duplicate_truth_metadata": _duplicate_truth_metadata(truth, truth_csv),
        "relational_primary_denominator_status": (
            "pending_explicit_relationship_primary_semantics"
        ),
        "unsupervised_primary_denominator_status": (
            "available"
            if primary_recall["unsupervised"]["primary_truth_docs"]
            else "pending_explicit_broad_statistical_only_metadata"
        ),
        "timeseries_role_lock_alignment": {
            "period_end_adjustment_timeseries_primary_count": sum(
                item["owner_roles"].get("timeseries") == "primary"
                and "manual_adjustment_context" in item["scenario_groups"]
                for item in assignments
            ),
            "timeseries_primary_limited_to_timing_only": True,
            "period_end_adjustment_role": "companion_context",
        },
        "interpretation": {
            "intercompany": "IC remains locked on intercompany primary targets.",
            "relational": (
                "Relational primary denominator is pending explicit relationship-primary "
                "owner semantics; current role is secondary evidence."
            ),
            "duplicate": (
                "Duplicate primary denominator is available only when explicit "
                "duplicate-like truth metadata exists; otherwise duplicate remains "
                "companion/context evidence."
            ),
            "timeseries": "TS primary denominator is timing-only after-hours/window anomaly.",
            "unsupervised": (
                "VAE primary denominator is pending explicit broad-statistical-only "
                "owner metadata; current role is companion evidence."
            ),
        },
    }
    payload["fitting_leakage_guard"] = _leakage_guard(payload, truth)
    if payload["fitting_leakage_guard"]["raw_identifier_leak_count"] != 0:
        raise ValueError("raw truth identifier leak detected")
    if payload["fitting_leakage_guard"]["forbidden_identifier_key_count"] != 0:
        raise ValueError("forbidden identifier key detected")
    return payload


def main(_argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--truth-csv", type=Path, default=v1.TRUTH_CSV)
    parser.add_argument("--dataset-name", default=DATASET_NAME)
    parser.add_argument("--out-json", type=Path, default=OUT_JSON)
    args = parser.parse_args(_argv)
    payload = build_payload(truth_csv=args.truth_csv, dataset_name=args.dataset_name)
    out_json = args.out_json if args.out_json.is_absolute() else ROOT / args.out_json
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out_json.relative_to(ROOT).as_posix()}")
    print(
        json.dumps(
            {
                "owner_role_distribution": payload["owner_role_distribution"],
                "primary_owner_target_recall": payload["primary_owner_target_recall"],
                "companion_context_recall": payload["companion_context_recall"],
                "phase1_primary_confidence_split": payload[
                    "phase1_primary_confidence_split"
                ],
                "ambiguity": payload["ambiguity"],
                "duplicate_metadata_gap": payload["duplicate_metadata_gap"],
                "relational_primary_denominator_status": payload[
                    "relational_primary_denominator_status"
                ],
                "leakage_guard": payload["fitting_leakage_guard"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
