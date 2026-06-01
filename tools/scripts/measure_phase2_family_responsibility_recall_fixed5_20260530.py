"""Diagnostic-only PHASE2 family responsibility-map recall measurement."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import pickle
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field, field_validator

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

DATASET_NAME = "datasynth_manipulation_v7_candidate_fixed5_normalcal5"
TRUTH_CSV = ROOT.joinpath(
    "data",
    "journal",
    "primary",
    DATASET_NAME,
    "labels",
    "manipulated_entry_truth.csv",
)
PHASE1_CASE_RESULT = ROOT / "artifacts" / "stage7_fixed5_normalcal5_phase1_case_result.pkl"
NATIVE_RECALL_ARTIFACT = ROOT / "artifacts" / "phase2_native_case_remeasure_fixed5_20260528.json"
ACTION_TIER_ARTIFACT = ROOT / "artifacts" / "action_tier_phase1_phase2_fixed5_20260530.json"
OUT_JSON = ROOT / "artifacts" / "phase2_family_responsibility_recall_fixed5_20260530.json"

OWNER_ENUM = (
    "phase1",
    "intercompany",
    "relational",
    "duplicate",
    "timeseries",
    "unsupervised",
    "no_clear_owner",
)
PHASE2_FAMILIES = ("intercompany", "relational", "duplicate", "timeseries", "unsupervised")
PROMPT_VERSION = "phase2_family_responsibility_owner_prompt_v1_20260530"
SCHEMA_VERSION = "phase2_family_responsibility_owner_schema_v1_20260530"

Owner = Literal[
    "phase1",
    "intercompany",
    "relational",
    "duplicate",
    "timeseries",
    "unsupervised",
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


class OwnerAssignmentModel(BaseModel):
    truth_case_hash: str
    expected_owners: list[Owner]
    scenario_groups: list[str]
    owner_confidence: Confidence
    no_clear_owner_reason: NoOwnerReason
    assignment_basis: list[AssignmentBasis]
    audit_rationale: str = Field(min_length=1, max_length=500)

    @field_validator("expected_owners")
    @classmethod
    def _owners_are_consistent(cls, value: list[Owner]) -> list[Owner]:
        if not value:
            return ["no_clear_owner"]
        if "no_clear_owner" in value and len(value) > 1:
            raise ValueError("no_clear_owner cannot be combined with other owners")
        return sorted(set(value), key=OWNER_ENUM.index)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _truth_hash(raw_case_id: str) -> str:
    digest = hashlib.sha256(
        f"phase2-family-responsibility-v1:{raw_case_id}".encode()
    ).hexdigest()
    return f"truth_{digest[:24]}"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _clean(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def _load_truth(truth_csv: Path = TRUTH_CSV) -> pd.DataFrame:
    truth = pd.read_csv(truth_csv)
    required = {
        "document_id",
        "manipulation_scenario",
        "manipulation_subtype",
        "reference_pattern",
        "business_process",
        "source",
        "document_type",
        "posting_date",
        "line_amount",
        "line_count",
    }
    missing = sorted(required - set(truth.columns))
    if missing:
        raise ValueError(f"truth metadata missing required columns: {missing}")
    truth["document_id"] = truth["document_id"].astype(str)
    return truth


def _scenario_flags(row: pd.Series) -> dict[str, bool]:
    scenario = _clean(row["manipulation_scenario"])
    subtype = _clean(row["manipulation_subtype"])
    process = _clean(row["business_process"]).lower()
    source = _clean(row["source"]).lower()
    posting_date = pd.to_datetime(row["posting_date"], errors="coerce")
    period_end = bool(pd.notna(posting_date) and int(posting_date.day) >= 25)
    amount = pd.to_numeric(pd.Series([row["line_amount"]]), errors="coerce").iloc[0]
    amount_tail = bool(pd.notna(amount) and abs(float(amount)) >= 1_000_000)
    return {
        "has_intercompany_context": scenario == "circular_related_party_transaction"
        or process == "intercompany",
        "has_reciprocal_flow_context": subtype == "round_trip_intercompany",
        "has_duplicate_or_similarity_context": scenario == "period_end_adjustment_manipulation",
        "has_timing_window_context": scenario
        in {"period_end_adjustment_manipulation", "unusual_timing_manipulation"},
        "has_relationship_edge_context": scenario
        in {
            "circular_related_party_transaction",
            "embezzlement_concealment",
            "approval_sod_bypass",
        },
        "has_broad_statistical_anomaly_context": scenario
        in {"fictitious_entry", "expense_capitalization", "unusual_timing_manipulation"},
        "has_manual_adjustment_context": source in {"manual", "adjustment"}
        or scenario == "period_end_adjustment_manipulation",
        "has_period_end_context": period_end
        or scenario == "period_end_adjustment_manipulation",
        "has_amount_tail_context": amount_tail,
    }


def _truth_bool(value: Any) -> bool:
    if pd.isna(value):
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _metadata_present(value: Any) -> bool:
    if pd.isna(value):
        return False
    return str(value).strip().lower() not in {"", "none", "null", "nan"}


def _duplicate_metadata_flags(row: pd.Series) -> dict[str, Any]:
    if "injected_duplicate_like" not in row.index:
        return {
            "has_explicit_duplicate_like_metadata": False,
            "duplicate_pair_semantic_group_present": False,
            "duplicate_similarity_intent_present": False,
            "duplicate_similarity_injection_source_present": False,
            "duplicate_primary_target_metadata": False,
            "duplicate_companion_target_metadata": False,
        }
    return {
        "has_explicit_duplicate_like_metadata": _truth_bool(
            row.get("injected_duplicate_like")
        ),
        "duplicate_pair_semantic_group_present": _metadata_present(
            row.get("duplicate_pair_semantic_group")
        ),
        "duplicate_similarity_intent_present": _metadata_present(
            row.get("duplicate_similarity_intent")
        ),
        "duplicate_similarity_injection_source_present": _metadata_present(
            row.get("similarity_injection_source")
        ),
        "duplicate_primary_target_metadata": _truth_bool(
            row.get("duplicate_primary_target")
        ),
        "duplicate_companion_target_metadata": _truth_bool(
            row.get("duplicate_companion_target")
        ),
    }


def build_sanitized_truth_summaries(
    truth: pd.DataFrame,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    summaries: list[dict[str, Any]] = []
    hash_by_raw_id: dict[str, str] = {}
    for row in truth.sort_values("document_id").itertuples(index=False):
        raw_case_id = str(getattr(row, "document_id"))
        row_series = pd.Series(row._asdict())
        case_hash = _truth_hash(raw_case_id)
        hash_by_raw_id[raw_case_id] = case_hash
        flags = _scenario_flags(row_series)
        duplicate_flags = _duplicate_metadata_flags(row_series)
        scenario = _clean(row_series["manipulation_scenario"])
        subtype = _clean(row_series["manipulation_subtype"])
        summaries.append(
            {
                "truth_case_hash": case_hash,
                "datasynth_scenario": scenario,
                "datasynth_category": subtype,
                "injected_pattern_summary": _clean(row_series["reference_pattern"]),
                "sanitized_attributes": {
                    "business_process": _clean(row_series["business_process"]),
                    "source_type": _clean(row_series["source"]),
                    "document_type": _clean(row_series["document_type"]),
                    "line_count_bucket": _bucket_int(row_series["line_count"]),
                    "amount_bucket": _bucket_amount(row_series["line_amount"]),
                },
                **flags,
                **duplicate_flags,
                "case_summary": _case_summary(row_series, flags),
            }
        )
    return summaries, hash_by_raw_id


def _bucket_int(value: Any) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "unknown"
    if numeric <= 1:
        return "single_line"
    if numeric <= 3:
        return "two_to_three_lines"
    return "four_or_more_lines"


def _bucket_amount(value: Any) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "unknown"
    amount = abs(float(numeric))
    if amount >= 10_000_000:
        return "very_high"
    if amount >= 1_000_000:
        return "high"
    if amount >= 100_000:
        return "medium"
    return "low"


def _case_summary(row: pd.Series, flags: dict[str, bool]) -> str:
    scenario = _clean(row["manipulation_scenario"])
    subtype = _clean(row["manipulation_subtype"])
    process = _clean(row["business_process"])
    contexts = [
        name.removeprefix("has_").removesuffix("_context")
        for name, enabled in flags.items()
        if enabled
    ]
    suffix = ", ".join(contexts[:4]) if contexts else "general audit review context"
    return f"{scenario}/{subtype} in {process}; semantic contexts: {suffix}."


def assign_owner_rule_only(summary: dict[str, Any]) -> OwnerAssignmentModel:
    scenario = str(summary["datasynth_scenario"])
    flags = {key: bool(summary.get(key)) for key in summary if key.startswith("has_")}
    confidence: Confidence = "high"
    reason: NoOwnerReason = "none"
    if scenario == "circular_related_party_transaction":
        owners: list[Owner] = ["intercompany", "relational"]
        groups = ["intercompany_reciprocal", "relationship_edge_context"]
    elif scenario == "approval_sod_bypass":
        owners = ["phase1", "relational"]
        groups = ["approval_control_context", "user_approval_relationship_context"]
    elif scenario == "embezzlement_concealment":
        owners = ["phase1", "relational"]
        groups = ["outflow_or_employee_context", "relationship_edge_context"]
        confidence = "medium"
    elif scenario == "period_end_adjustment_manipulation":
        owners = ["phase1", "duplicate", "timeseries"]
        groups = ["manual_adjustment_context", "period_end_timing_context", "similarity_context"]
    elif scenario == "unusual_timing_manipulation":
        owners = ["phase1", "timeseries", "unsupervised"]
        groups = ["timing_window_context", "broad_statistical_context"]
        confidence = "medium"
    elif scenario == "fictitious_entry":
        owners = ["phase1", "unsupervised"]
        groups = ["broad_statistical_context", "revenue_or_activity_existence_context"]
        confidence = "medium"
    elif scenario == "expense_capitalization":
        owners = ["phase1", "unsupervised"]
        groups = ["account_classification_context", "broad_statistical_context"]
        confidence = "medium"
    elif scenario == "suspense_account_abuse":
        owners = ["phase1"]
        groups = ["account_classification_context", "manual_review_context"]
        confidence = "medium"
    else:
        owners = ["no_clear_owner"]
        groups = ["unmapped_truth_semantics"]
        confidence = "low"
        reason = "no_family_semantic_match"
    if not any(flags.values()) and owners != ["no_clear_owner"]:
        confidence = "low"
        reason = "insufficient_semantic_metadata"
    return OwnerAssignmentModel(
        truth_case_hash=str(summary["truth_case_hash"]),
        expected_owners=owners,
        scenario_groups=groups,
        owner_confidence=confidence,
        no_clear_owner_reason=reason,
        assignment_basis=[
            "scenario_metadata",
            "injected_pattern_metadata",
            "semantic_transaction_attributes",
        ],
        audit_rationale=(
            f"{scenario} assigned from scenario/injected-pattern semantics and "
            "sanitized transaction context only."
        ),
    )


def _validate_assignment(assignment: OwnerAssignmentModel, summary: dict[str, Any]) -> None:
    if assignment.truth_case_hash != summary["truth_case_hash"]:
        raise ValueError("LLM assignment hash does not match sanitized summary hash")
    text = json.dumps(assignment.model_dump(), ensure_ascii=False)
    if any(token in text.lower() for token in ("score", "rank", "matched", "detector")):
        raise ValueError("assignment contains detector/score/rank/match reference")
    _assert_no_forbidden_identifier_keys(assignment.model_dump())


def assign_owner_llm_assisted(
    summary: dict[str, Any],
    *,
    client: Any,
    model: str,
) -> OwnerAssignmentModel:
    prompt = (
        "Assign audit responsibility owner families. Use only the sanitized JSON summary. "
        "Return all plausible owners as a set. Never infer from detector output, score, "
        "rank, match status, or raw identifiers."
    )
    response = client.responses.parse(
        model=model,
        input=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(summary, ensure_ascii=False, sort_keys=True)},
        ],
        text_format=OwnerAssignmentModel,
    )
    for output in getattr(response, "output", []):
        if getattr(output, "type", None) != "message":
            continue
        for item in getattr(output, "content", []):
            if getattr(item, "type", None) == "refusal":
                raise ValueError("LLM refused owner assignment")
            parsed = getattr(item, "parsed", None)
            if parsed is None:
                continue
            assignment = (
                parsed
                if isinstance(parsed, OwnerAssignmentModel)
                else OwnerAssignmentModel.model_validate(parsed)
            )
            _validate_assignment(assignment, summary)
            if "llm_semantic_label" not in assignment.assignment_basis:
                assignment.assignment_basis.append("llm_semantic_label")
            return assignment
    raise ValueError("LLM response did not include a parsed owner assignment")


def build_owner_assignments(
    summaries: list[dict[str, Any]],
    *,
    mode: str = "deterministic",
    model: str = "gpt-4o-mini",
    client: Any | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    metadata: dict[str, Any] = {
        "requested_mode": mode,
        "actual_mode": "deterministic_rule_only",
        "prompt_version": PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "model": None,
        "llm_status": "not_requested",
    }
    if mode == "llm" and client is not None:
        metadata.update({"actual_mode": "llm_assisted", "model": model, "llm_status": "used"})
    elif mode == "llm":
        try:
            sdk = importlib.import_module("openai")
            client = sdk.OpenAI()
            metadata.update(
                {"actual_mode": "llm_assisted", "model": model, "llm_status": "used"}
            )
        except Exception as exc:  # pragma: no cover
            metadata["llm_status"] = f"skipped_client_unavailable:{type(exc).__name__}"
    assignments: list[dict[str, Any]] = []
    for summary in summaries:
        if metadata["actual_mode"] == "llm_assisted":
            try:
                assignment = assign_owner_llm_assisted(summary, client=client, model=model)
            except Exception as exc:
                metadata["actual_mode"] = "deterministic_rule_only"
                metadata["llm_status"] = f"fallback_after_error:{type(exc).__name__}"
                assignment = assign_owner_rule_only(summary)
        else:
            assignment = assign_owner_rule_only(summary)
        assignments.append(assignment.model_dump())
    return assignments, metadata


def _owners_by_raw_case(
    truth: pd.DataFrame,
    hash_by_raw_id: dict[str, str],
    assignments: list[dict[str, Any]],
) -> dict[str, set[str]]:
    by_hash = {str(item["truth_case_hash"]): item for item in assignments}
    return {
        raw_case_id: set(by_hash[hash_by_raw_id[raw_case_id]]["expected_owners"])
        for raw_case_id in truth["document_id"].astype(str)
    }


def _phase1_truth_sets(truth_ids: set[str]) -> dict[str, set[str]]:
    with PHASE1_CASE_RESULT.open("rb") as fh:
        result = pickle.load(fh)
    sets = {
        "immediate": set(),
        "review_or_higher": set(),
        "candidate_or_higher": set(),
        "top100": set(),
        "top500": set(),
    }
    for rank, case in enumerate(getattr(result, "cases", []), start=1):
        case_ids = {
            str(hit.document_id)
            for hit in getattr(case, "raw_rule_hits", [])
            if getattr(hit, "document_id", None) in truth_ids
        }
        if not case_ids:
            continue
        band = str(getattr(case, "priority_band", "")).lower()
        if band == "high":
            sets["immediate"].update(case_ids)
            sets["review_or_higher"].update(case_ids)
            sets["candidate_or_higher"].update(case_ids)
        elif band == "medium":
            sets["review_or_higher"].update(case_ids)
            sets["candidate_or_higher"].update(case_ids)
        elif band == "low":
            sets["candidate_or_higher"].update(case_ids)
        if rank <= 100:
            sets["top100"].update(case_ids)
        if rank <= 500:
            sets["top500"].update(case_ids)
    return sets


def _count_owner_cases(raw_ids: set[str], owners_by_raw: dict[str, set[str]], owner: str) -> int:
    if owner == "no_clear_owner":
        return sum(1 for raw_id in raw_ids if owners_by_raw[raw_id] == {"no_clear_owner"})
    return sum(1 for raw_id in raw_ids if owner in owners_by_raw[raw_id])


def _owner_distribution_from_raw(owners_by_raw: dict[str, set[str]]) -> dict[str, int]:
    counts = Counter()
    for owners in owners_by_raw.values():
        for owner in owners:
            counts[owner] += 1
    return {owner: int(counts.get(owner, 0)) for owner in OWNER_ENUM}


def _owner_distribution(assignments: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter()
    for item in assignments:
        for owner in item["expected_owners"]:
            counts[str(owner)] += 1
    return {owner: int(counts.get(owner, 0)) for owner in OWNER_ENUM}


def _scenario_owner_counts(
    truth: pd.DataFrame,
    owners_by_raw: dict[str, set[str]],
) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for scenario, group in truth.groupby("manipulation_scenario"):
        raw_ids = set(group["document_id"].astype(str))
        out[str(scenario)] = {
            owner: _count_owner_cases(raw_ids, owners_by_raw, owner) for owner in OWNER_ENUM
        }
    return out


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def _phase1_owner_recall(
    phase1_sets: dict[str, set[str]],
    owners_by_raw: dict[str, set[str]],
) -> dict[str, Any]:
    owner_totals = _owner_distribution_from_raw(owners_by_raw)
    out: dict[str, Any] = {}
    for owner in OWNER_ENUM:
        row = {
            "owner_truth_docs": owner_totals[owner],
            "immediate_matched_owner_docs": _count_owner_cases(
                phase1_sets["immediate"], owners_by_raw, owner
            ),
            "review_or_higher_matched_owner_docs": _count_owner_cases(
                phase1_sets["review_or_higher"], owners_by_raw, owner
            ),
            "candidate_or_higher_matched_owner_docs": _count_owner_cases(
                phase1_sets["candidate_or_higher"], owners_by_raw, owner
            ),
            "top100_matched_owner_docs": _count_owner_cases(
                phase1_sets["top100"], owners_by_raw, owner
            ),
            "top500_matched_owner_docs": _count_owner_cases(
                phase1_sets["top500"], owners_by_raw, owner
            ),
        }
        for key in list(row):
            if key.endswith("_matched_owner_docs"):
                row[key.replace("_matched_owner_docs", "_recall")] = _ratio(
                    int(row[key]), owner_totals[owner]
                )
        out[owner] = row
    return out


def _phase2_owner_target_recall(
    native: dict[str, Any],
    truth: pd.DataFrame,
    owners_by_raw: dict[str, set[str]],
) -> dict[str, Any]:
    scenario_owner_counts = _scenario_owner_counts(truth, owners_by_raw)
    owner_totals = _owner_distribution_from_raw(owners_by_raw)
    matrix = native["top500_scenario_matrix"]
    out: dict[str, Any] = {}
    for owner in OWNER_ENUM:
        row: dict[str, Any] = {"owner_truth_docs": owner_totals[owner]}
        for family in PHASE2_FAMILIES:
            matched = 0
            for scenario, values in matrix.items():
                scenario_total = int(values["truth_n"])
                if scenario_total:
                    matched += round(
                        int(values[family]["matched"])
                        * scenario_owner_counts.get(scenario, {}).get(owner, 0)
                        / scenario_total
                    )
            row[f"{family}_matched_owner_docs"] = int(matched)
            if family == owner:
                row["recall_by_matching_family_on_owner_set"] = _ratio(
                    matched, owner_totals[owner]
                )
        if owner in {"phase1", "no_clear_owner"}:
            row["recall_by_matching_family_on_owner_set"] = None
        out[owner] = row
    return out


def _cross_owner_evidence_contribution(
    native: dict[str, Any],
    truth: pd.DataFrame,
    owners_by_raw: dict[str, set[str]],
) -> dict[str, Any]:
    scenario_owner_counts = _scenario_owner_counts(truth, owners_by_raw)
    out: dict[str, Any] = {}
    for family in PHASE2_FAMILIES:
        expected_owner = 0
        secondary = 0
        no_clear = 0
        for scenario, values in native["top500_scenario_matrix"].items():
            matched = int(values[family]["matched"])
            if matched <= 0:
                continue
            scenario_total = int(values["truth_n"])
            matched_expected = round(
                matched * scenario_owner_counts[scenario][family] / scenario_total
            )
            matched_no_clear = round(
                matched * scenario_owner_counts[scenario]["no_clear_owner"] / scenario_total
            )
            expected_owner += matched_expected
            no_clear += matched_no_clear
            secondary += max(matched - matched_expected - matched_no_clear, 0)
        out[family] = {
            "matched_docs_where_family_is_expected_owner": int(expected_owner),
            "matched_docs_where_family_is_not_owner_secondary_evidence": int(secondary),
            "matched_docs_with_no_clear_owner": int(no_clear),
        }
    return out


def _phase2_outside_phase1_action_tiers(
    action: dict[str, Any],
    owner_target_recall: dict[str, Any],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for family in PHASE2_FAMILIES:
        family_action = action["incremental_vs_phase1_action_tiers"][family]
        surface = "top500" if family == "unsupervised" else "strong_or_moderate"
        aggregate = family_action[surface]
        owner_row = owner_target_recall.get(family, {})
        out[family] = {
            "owner_set_target": family,
            "owner_truth_docs": owner_row.get("owner_truth_docs", 0),
            "matched_owner_docs": owner_row.get(f"{family}_matched_owner_docs", 0),
            "outside_phase1_immediate_high": aggregate["vs_phase1_immediate"][
                "phase1_not_in_tier_truth_docs"
            ],
            "outside_phase1_review_or_higher_high_medium": aggregate[
                "vs_phase1_review_or_higher"
            ]["phase1_not_in_tier_truth_docs"],
            "outside_phase1_candidate_or_higher_high_medium_low": aggregate[
                "vs_phase1_candidate_or_higher"
            ]["phase1_not_in_tier_truth_docs"],
            "outside_phase1_top100": None,
            "outside_phase1_top500": None,
            "note": (
                "Action-tier outside counts come from the existing aggregate artifact; "
                "owner-set matched_owner_docs is measured separately."
            ),
        }
    return out


def _portfolio_contribution(action: dict[str, Any], native: dict[str, Any]) -> dict[str, Any]:
    denominator = int(action["truth_document_count"])
    return {
        "denominator_truth_docs": denominator,
        "phase1": {
            key: {
                "matched": int(value["truth_docs"]),
                "recall": int(value["truth_docs"]) / denominator,
            }
            for key, value in action["phase1"]["cumulative_bands"].items()
        },
        "phase2_native_top500": {
            family: {
                "matched": int(native["family_results"][family]["topn"]["500"]["matched"]),
                "recall": int(native["family_results"][family]["topn"]["500"]["matched"])
                / denominator,
            }
            for family in PHASE2_FAMILIES
        },
    }


def _leakage_guard_report(payload: dict[str, Any], *, truth_raw_ids: set[str]) -> dict[str, Any]:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    keys = list(_walk_json_keys(payload))
    forbidden_key_hits = [
        key
        for key in keys
        if key.lower()
        in {
            "document_id",
            "document_ids",
            "raw_document_id",
            "raw_document_ids",
            "row_id",
            "row_ids",
            "raw_row_id",
            "raw_row_ids",
            "index_label",
            "raw_index_label",
            "phase2_case_id",
            "phase2_case_ids",
        }
    ]
    return {
        "owner_assignment_detector_output_inspection": "not_used_by_construction",
        "owner_assignment_score_rank_inspection": "not_used_by_construction",
        "owner_assignment_matched_result_inspection": "not_used_by_construction",
        "raw_identifier_leak_count": sum(1 for raw_id in truth_raw_ids if raw_id in text),
        "forbidden_identifier_key_count": len(forbidden_key_hits),
        "forbidden_identifier_keys": sorted(set(forbidden_key_hits)),
        "phase2_case_id_like_token_count": len(re.findall(r"phase2_case_id|p2_[a-z_]+_", text)),
        "no_clear_owner_allowed": True,
        "multi_owner_assignment_allowed": True,
        "owner_assignment_artifact_independent_of_recall_result_artifact": True,
    }


def _walk_json_keys(value: Any) -> list[str]:
    if isinstance(value, dict):
        keys = [str(key) for key in value]
        for child in value.values():
            keys.extend(_walk_json_keys(child))
        return keys
    if isinstance(value, list):
        keys: list[str] = []
        for child in value:
            keys.extend(_walk_json_keys(child))
        return keys
    return []


def _assert_no_forbidden_identifier_keys(payload: dict[str, Any]) -> None:
    report = _leakage_guard_report(payload, truth_raw_ids=set())
    if report["forbidden_identifier_key_count"]:
        raise ValueError(f"forbidden identifier keys found: {report['forbidden_identifier_keys']}")


def build_payload(*, mode: str = "deterministic", llm_client: Any | None = None) -> dict[str, Any]:
    truth = _load_truth()
    summaries, hash_by_raw_id = build_sanitized_truth_summaries(truth)
    assignments, labeling_metadata = build_owner_assignments(
        summaries,
        mode=mode,
        client=llm_client,
    )
    owners_by_raw = _owners_by_raw_case(truth, hash_by_raw_id, assignments)
    phase1_sets = _phase1_truth_sets(set(truth["document_id"].astype(str)))
    native = _load_json(NATIVE_RECALL_ARTIFACT)
    action = _load_json(ACTION_TIER_ARTIFACT)
    owner_target = _phase2_owner_target_recall(native, truth, owners_by_raw)
    phase1_owner = _phase1_owner_recall(phase1_sets, owners_by_raw)
    for owner, row in owner_target.items():
        row["phase1_matched_owner_docs"] = phase1_owner[owner][
            "candidate_or_higher_matched_owner_docs"
        ]
        row["phase1_candidate_or_higher_recall"] = phase1_owner[owner][
            "candidate_or_higher_recall"
        ]
    assignment_counts = _owner_distribution(assignments)
    payload: dict[str, Any] = {
        "generated_at": _now_iso(),
        "dataset": DATASET_NAME,
        "diagnostic_only": True,
        "production_ranking_gate_fusion_changed": False,
        "portfolio_truth_case_count": int(len(truth)),
        "owner_enum": list(OWNER_ENUM),
        "labeling_metadata": labeling_metadata,
        "sanitized_truth_summaries": summaries,
        "owner_assignments": assignments,
        "owner_distribution": assignment_counts,
        "multi_owner_count": sum(
            1
            for item in assignments
            if len(item["expected_owners"]) > 1
            and "no_clear_owner" not in item["expected_owners"]
        ),
        "no_clear_owner_count": assignment_counts["no_clear_owner"],
        "owner_confidence_distribution": dict(
            sorted(Counter(item["owner_confidence"] for item in assignments).items())
        ),
        "no_clear_owner_reason_distribution": dict(
            sorted(Counter(item["no_clear_owner_reason"] for item in assignments).items())
        ),
        "portfolio_contribution": _portfolio_contribution(action, native),
        "phase1_owner_set_recall": phase1_owner,
        "owner_set_target_recall": owner_target,
        "cross_owner_evidence_contribution": _cross_owner_evidence_contribution(
            native,
            truth,
            owners_by_raw,
        ),
        "phase2_outside_phase1_action_tiers": _phase2_outside_phase1_action_tiers(
            action,
            owner_target,
        ),
        "family_interpretation": {
            "intercompany": (
                "Interpret IC on intercompany-owned targets, not the full 620 portfolio."
            ),
            "relational": (
                "Separate relationship-owned target performance from PHASE1 uplift and "
                "structural evidence companion value."
            ),
            "duplicate": "Interpret duplicate on duplicate-owned period-end/similarity targets.",
            "timeseries": (
                "Interpret TOP100 failure against timeseries-owned timing-window targets, "
                "not all synthetic truth cases."
            ),
            "unsupervised": (
                "Separate unsupervised-owned broad-statistical targets from document "
                "companion evidence role."
            ),
        },
    }
    payload["fitting_leakage_guard"] = _leakage_guard_report(
        payload,
        truth_raw_ids=set(truth["document_id"].astype(str)),
    )
    if payload["fitting_leakage_guard"]["raw_identifier_leak_count"] != 0:
        raise ValueError("raw truth identifier leak detected")
    if payload["fitting_leakage_guard"]["forbidden_identifier_key_count"] != 0:
        raise ValueError("forbidden identifier key detected")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["deterministic", "llm"], default="deterministic")
    args = parser.parse_args(argv)
    payload = build_payload(mode=args.mode)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT_JSON.relative_to(ROOT).as_posix()}")
    print(
        json.dumps(
            {
                "owner_distribution": payload["owner_distribution"],
                "multi_owner_count": payload["multi_owner_count"],
                "no_clear_owner_count": payload["no_clear_owner_count"],
                "labeling_mode": payload["labeling_metadata"]["actual_mode"],
                "leakage_guard": payload["fitting_leakage_guard"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
