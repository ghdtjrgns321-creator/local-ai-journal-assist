"""Diagnostic-only PHASE2 responsibility-map v3.3d.

This script rebuilds the v3.3d owner-role denominator map from DataSynth
family owner metadata. Owner assignment uses truth metadata only; detector
outputs are used later only for aggregate recall measurement.
"""

# ruff: noqa: E402

from __future__ import annotations

import csv
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.scripts import measure_phase2_family_responsibility_recall_fixed5_20260530 as v1
from tools.scripts import measure_phase2_native_cases_fixed5_20260528 as native_cases

CANDIDATE_NAME = "datasynth_manipulation_v7_candidate_fixed5_ownermeta_v33d"
OWNER_METADATA_VERSION = "v3.3d"
DATA_DIR = ROOT / "data" / "journal" / "primary" / CANDIDATE_NAME
TRUTH_PATH = DATA_DIR / "labels" / "manipulated_entry_truth.csv"
JOURNAL_PATH = DATA_DIR / "journal_entries.csv"
MANIFEST_PATH = DATA_DIR / "MANIPULATION_V7_DATASET_MANIFEST.json"
OUT_JSON = (
    ROOT
    / "artifacts"
    / "phase2_family_responsibility_recall_v33d_fixed5_ownermeta_v33d_20260601.json"
)
TIMESERIES_PRODUCT_LOCK_ARTIFACT = (
    ROOT / "artifacts" / "timeseries_v31_primary_fixed5_ownermeta_ic_20260531.json"
)
PHASE2_FAMILIES = ["intercompany", "relational", "duplicate", "timeseries", "unsupervised"]
PRIMARY_FAMILIES = ["phase1", *PHASE2_FAMILIES]
TOP_NS = [100, 500, 1000, 10000]
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
OWNER_FLAG_TOKENS = (
    "truth_owner",
    "relationship_primary_target",
    "relationship_companion_target",
    "duplicate_primary_target",
    "duplicate_companion_target",
    "injected_intercompany_primary",
    "injected_timing_primary",
    "statistical_anomaly_role",
    "broad_statistical_only_owner",
)


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _load_truth() -> pd.DataFrame:
    if not TRUTH_PATH.exists():
        raise FileNotFoundError(f"missing truth metadata: {TRUTH_PATH}")
    return pd.read_csv(TRUTH_PATH, dtype=str).fillna("")


def _load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _print(message: str) -> None:
    print(f"[{_now_iso()}] {message}", flush=True)


def _load_case_input() -> pd.DataFrame:
    _print(f"loading v3.3d journal input: {JOURNAL_PATH.relative_to(ROOT).as_posix()}")
    df = pd.read_csv(JOURNAL_PATH, low_memory=False)
    df["document_id"] = df["document_id"].astype(str)
    _print(f"  rows={len(df):,} documents={df['document_id'].nunique():,}")
    return df


def _bool_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(False, index=df.index)
    return df[column].astype(str).str.lower().eq("true")


def _role_series(df: pd.DataFrame, column: str, value: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(False, index=df.index)
    return df[column].astype(str).str.lower().eq(value)


def _owner_masks(df: pd.DataFrame) -> dict[str, dict[str, pd.Series]]:
    suspense_policy_override = df["truth_owner_subtype"].astype(str).eq(
        "long_aged_suspense_balance"
    )
    statistical_primary = (
        _role_series(df, "statistical_anomaly_role", "primary")
        | _bool_series(df, "broad_statistical_only_owner")
    )
    statistical_companion = _role_series(df, "statistical_anomaly_role", "companion")
    return {
        "phase1": {
            "primary": df["truth_owner_primary"].astype(str).eq("phase1")
            | suspense_policy_override,
            "companion": pd.Series(False, index=df.index),
            "context": df["truth_owner_context"].astype(str).eq("phase1"),
        },
        "intercompany": {
            "primary": _bool_series(df, "injected_intercompany_primary"),
            "companion": pd.Series(False, index=df.index),
            "context": pd.Series(False, index=df.index),
        },
        "relational": {
            "primary": _bool_series(df, "relationship_primary_target"),
            "companion": _bool_series(df, "relationship_companion_target"),
            "context": _bool_series(df, "relational_context_target"),
        },
        "duplicate": {
            "primary": _bool_series(df, "duplicate_primary_target"),
            "companion": _bool_series(df, "duplicate_companion_target"),
            "context": pd.Series(False, index=df.index),
        },
        "timeseries": {
            "primary": _bool_series(df, "injected_timing_primary"),
            "companion": pd.Series(False, index=df.index),
            "context": _role_series(df, "timing_role", "context"),
        },
        "unsupervised": {
            "primary": statistical_primary & ~suspense_policy_override,
            "companion": statistical_companion | suspense_policy_override,
            "context": pd.Series(False, index=df.index),
        },
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator <= 0 else numerator / denominator


def _scenario_counts_for_mask(df: pd.DataFrame, mask: pd.Series) -> dict[str, int]:
    subset = df.loc[mask, "manipulation_scenario"].astype(str)
    return {str(key): int(value) for key, value in subset.value_counts().items()}


def _value_counts(series: pd.Series) -> dict[str, int]:
    return {str(key): int(value) for key, value in series.astype(str).value_counts().items()}


def _has_partial_scenario(
    role_scenario_counts: dict[str, int],
    truth_scenario_counts: dict[str, int],
) -> bool:
    return any(
        0 < role_count < truth_scenario_counts.get(scenario, 0)
        for scenario, role_count in role_scenario_counts.items()
    )


def _scenario_denominator_match(
    scenario_matches: dict[str, int],
    role_scenario_counts: dict[str, int],
    truth_scenario_counts: dict[str, int],
) -> int:
    matched = 0
    for scenario, role_count in role_scenario_counts.items():
        scenario_total = truth_scenario_counts.get(scenario, 0)
        if scenario_total:
            matched += round(scenario_matches.get(scenario, 0) * role_count / scenario_total)
    return int(matched)


def _family_topn_scenario_counts(
    native: dict[str, Any],
    family: str,
    topn: int,
) -> dict[str, int] | None:
    key = f"top{topn}_scenario_counts"
    counts = native["family_results"][family].get(key)
    if counts is None:
        return None
    return {str(name): int(value) for name, value in counts.items()}


def _owner_topn_recall(
    native: dict[str, Any],
    df: pd.DataFrame,
    mask: pd.Series,
    family: str,
) -> dict[str, Any]:
    denominator = int(mask.sum())
    role_scenarios = _scenario_counts_for_mask(df, mask)
    truth_scenarios = {
        str(key): int(value)
        for key, value in df["manipulation_scenario"].astype(str).value_counts().items()
    }
    uses_proration = _has_partial_scenario(role_scenarios, truth_scenarios)
    out: dict[str, Any] = {}
    for topn in TOP_NS:
        portfolio_matched = int(native["family_results"][family]["topn"][str(topn)]["matched"])
        scenario_matches = _family_topn_scenario_counts(native, family, topn)
        if scenario_matches is None:
            owner_matched = None
            recall = None
            status = "scenario_breakdown_unavailable"
        elif denominator == 0:
            owner_matched = 0
            recall = None
            status = "no_primary_denominator"
        else:
            owner_matched = _scenario_denominator_match(
                scenario_matches, role_scenarios, truth_scenarios
            )
            recall = _ratio(owner_matched, denominator)
            status = "available"
        row = {
            "matched_docs": owner_matched,
            "recall": recall,
            "status": status,
            "portfolio_620_matched_docs": portfolio_matched,
            "portfolio_620_recall": _ratio(portfolio_matched, 620),
        }
        if uses_proration and scenario_matches is not None and denominator > 0:
            row.update(
                {
                    "matched_docs": None,
                    "recall": None,
                    "status": "estimated_proration_exact_join_required",
                    "matched_docs_estimated_proration": owner_matched,
                    "recall_estimated_proration": recall,
                    "measurement_basis": "scenario_level_proration",
                }
            )
        elif scenario_matches is not None and denominator > 0:
            row["measurement_basis"] = "scenario_aligned_aggregate"
        out[f"top{topn}"] = row
    return out


def _build_v33d_native_measurement(df: pd.DataFrame) -> dict[str, Any]:
    """Run current PHASE2 native case builders on the v3.3d journal."""

    started = time.perf_counter()
    case_input = _load_case_input()
    truth_docs = set(df["document_id"].astype(str))
    journal_docs = set(case_input["document_id"].astype(str))
    detection_results = native_cases._run_detection_results(case_input)
    _print("building v3.3d PHASE2 native case set")
    case_set = native_cases.build_phase2_case_set(
        batch_id="fixed5_ownermeta_v33d_native_cases_20260601",
        detection_results=detection_results,
        df=case_input,
        unsupervised_model_id="stage7-fixed5-model-bundle-v1",
        unsupervised_schema_hash="stage7-fixed5-normalcal5",
    )
    all_truth_docs = set(df["document_id"].astype(str))
    family_results: dict[str, Any] = {}
    for family in PHASE2_FAMILIES:
        ordered = native_cases._sorted_cases(
            list(native_cases._family_cases(case_set, family))
        )
        case_doc_sets = [native_cases._case_documents(case) for case in ordered]
        topn_docs: dict[int, set[str]] = {}
        topn_portfolio_counts: dict[int, int] = {}
        for topn in TOP_NS:
            docs: set[str] = set()
            for doc_set in case_doc_sets[:topn]:
                docs.update(doc_set)
            topn_docs[topn] = docs
            topn_portfolio_counts[topn] = len(docs & all_truth_docs)
        family_results[family] = {
            "case_count": len(ordered),
            "docs_covered": len(set().union(*case_doc_sets)) if case_doc_sets else 0,
            "topn_docs": topn_docs,
            "topn_portfolio_counts": topn_portfolio_counts,
        }
    return {
        "dataset": CANDIDATE_NAME,
        "row_count": int(len(case_input)),
        "document_count": int(case_input["document_id"].nunique()),
        "truth_documents_present_in_journal": len(truth_docs & journal_docs),
        "truth_documents_missing_from_journal": len(truth_docs - journal_docs),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "family_results": family_results,
    }


def _exact_family_topn_recall(
    exact_native: dict[str, Any],
    df: pd.DataFrame,
    mask: pd.Series,
    family: str,
) -> dict[str, Any]:
    denominator = int(mask.sum())
    target_docs = set(df.loc[mask, "document_id"].astype(str))
    out: dict[str, Any] = {}
    for topn in TOP_NS:
        docs = exact_native["family_results"][family]["topn_docs"][topn]
        matched = len(docs & target_docs)
        portfolio_matched = int(
            exact_native["family_results"][family]["topn_portfolio_counts"][topn]
        )
        out[f"top{topn}"] = {
            "matched_docs": matched,
            "recall": _ratio(matched, denominator),
            "status": "available_exact_v33d_native_join"
            if denominator
            else "no_primary_denominator",
            "portfolio_620_matched_docs": portfolio_matched,
            "portfolio_620_recall": _ratio(portfolio_matched, 620),
            "measurement_basis": "exact_v33d_matched_doc_join",
        }
    return out


def _phase1_sets(df: pd.DataFrame) -> dict[str, set[str]]:
    return v1._phase1_truth_sets(set(df["document_id"].astype(str)))


def _phase1_coverage(mask: pd.Series, df: pd.DataFrame, phase1_set: set[str]) -> int:
    return int(df.loc[mask, "document_id"].astype(str).isin(phase1_set).sum())


def _primary_denominators(masks: dict[str, dict[str, pd.Series]]) -> dict[str, Any]:
    out = {family: int(masks[family]["primary"].sum()) for family in PRIMARY_FAMILIES}
    out["status"] = {
        "relational": "available",
        "duplicate": "available",
    }
    return out


def _companion_denominators(masks: dict[str, dict[str, pd.Series]]) -> dict[str, int]:
    return {
        "relational_companion": int(masks["relational"]["companion"].sum()),
        "duplicate_companion": int(masks["duplicate"]["companion"].sum()),
        "timeseries_context": int(masks["timeseries"]["context"].sum()),
        "statistical_companion": int(masks["unsupervised"]["companion"].sum()),
    }


def _overlap_matrix(df: pd.DataFrame, masks: dict[str, dict[str, pd.Series]]) -> dict[str, Any]:
    primary_sets = {
        family: set(df.loc[masks[family]["primary"], "document_id"].astype(str))
        for family in PRIMARY_FAMILIES
    }
    matrix = {
        left: {right: len(primary_sets[left] & primary_sets[right]) for right in PRIMARY_FAMILIES}
        for left in PRIMARY_FAMILIES
    }
    non_diag = {
        f"{left}_and_{right}": matrix[left][right]
        for index, left in enumerate(PRIMARY_FAMILIES)
        for right in PRIMARY_FAMILIES[index + 1 :]
        if matrix[left][right]
    }
    return {
        "primary_overlap_matrix": matrix,
        "primary_non_self_overlap_count": sum(non_diag.values()),
        "primary_non_self_overlaps": non_diag,
        "ic_relational_primary_overlap": matrix["intercompany"]["relational"],
    }


def _primary_recall(
    exact_native: dict[str, Any],
    df: pd.DataFrame,
    masks: dict[str, dict[str, pd.Series]],
    phase1_sets: dict[str, set[str]],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    phase1_mask = masks["phase1"]["primary"]
    phase1_denominator = int(phase1_mask.sum())
    out["phase1"] = {
        "denominator": phase1_denominator,
        "status": "available",
        "phase1_action_tier": {
            "immediate": {
                "matched_docs": _phase1_coverage(phase1_mask, df, phase1_sets["immediate"]),
            },
            "review_or_higher": {
                "matched_docs": _phase1_coverage(
                    phase1_mask, df, phase1_sets["review_or_higher"]
                ),
            },
            "candidate_or_higher": {
                "matched_docs": _phase1_coverage(
                    phase1_mask, df, phase1_sets["candidate_or_higher"]
                ),
            },
        },
    }
    for tier in out["phase1"]["phase1_action_tier"].values():
        tier["recall"] = _ratio(int(tier["matched_docs"]), phase1_denominator)

    for family in PHASE2_FAMILIES:
        denominator = int(masks[family]["primary"].sum())
        status = "no_primary_denominator" if denominator == 0 else "available"
        out[family] = {
            "denominator": denominator,
            "status": status,
            "topn": _exact_family_topn_recall(
                exact_native, df, masks[family]["primary"], family
            ),
        }
    for family in PHASE2_FAMILIES:
        out[family]["exact_join_case_count"] = exact_native["family_results"][family][
            "case_count"
        ]
    return out


def _timeseries_product_ordering_lock(
    masks: dict[str, dict[str, pd.Series]],
    primary_recall: dict[str, Any],
) -> dict[str, Any]:
    """Return the adopted TS product ordering and keep the old order debug-only."""

    denominator = int(masks["timeseries"]["primary"].sum())
    context_docs = int(masks["timeseries"]["context"].sum())
    payload = json.loads(TIMESERIES_PRODUCT_LOCK_ARTIFACT.read_text(encoding="utf-8"))
    surfaces = payload["candidate_surfaces"]
    stabilized = surfaces["ts_specific_top100_stabilized_surface"]
    native_top100 = primary_recall["timeseries"]["topn"]["top100"]
    native_top500 = primary_recall["timeseries"]["topn"]["top500"]
    return {
        "primary_denominator": denominator,
        "period_end_context_docs": context_docs,
        "period_end_context_used_as_primary": False,
        "product_default": {
            "ordering_strategy": "ts_specific_top100_stabilized_surface",
            "top100_matched_docs": stabilized["top100_matched_docs"],
            "top500_matched_docs": stabilized["top500_matched_docs"],
            "top100_recall": stabilized["top100_recall"],
            "top500_recall": stabilized["top500_recall"],
            "source_artifact": TIMESERIES_PRODUCT_LOCK_ARTIFACT.relative_to(ROOT).as_posix(),
            "status": "product_default_ordering_strategy_ts_specific_top100_stabilized_surface",
            "measurement_basis": "adopted_timeseries_product_surface",
        },
        "debug_native_baseline": {
            "top100_matched_docs": native_top100["matched_docs"],
            "top500_matched_docs": native_top500["matched_docs"],
            "top100_recall": native_top100["recall"],
            "top500_recall": native_top500["recall"],
            "status": "debug_only_previous_ordering_not_user_facing",
            "measurement_basis": "exact_v33d_case_join_for_regression_debug_only",
        },
        "product_default_adoption_allowed": True,
        "production_default_ordering_changed": True,
        "ordering_change_scope": "timeseries_primary_review_ordering_only",
        "production_detector_gate_fusion_changed": False,
        "phase1_ranking_changed": False,
        "streamlit_ui_changed": False,
    }


def _product_ordering_lock(
    masks: dict[str, dict[str, pd.Series]],
    primary_recall: dict[str, Any],
) -> dict[str, Any]:
    ic_top500 = primary_recall["intercompany"]["topn"]["top500"]
    return {
        "intercompany": {
            "primary_denominator": int(masks["intercompany"]["primary"].sum()),
            "top500_matched_docs": ic_top500["matched_docs"],
            "top500_recall": ic_top500["recall"],
            "status": ic_top500["status"],
            "production_detector_gate_fusion_changed": False,
            "phase1_ranking_changed": False,
            "streamlit_ui_changed": False,
        },
        "timeseries": _timeseries_product_ordering_lock(masks, primary_recall),
    }


def _companion_recall(
    exact_native: dict[str, Any],
    df: pd.DataFrame,
    masks: dict[str, dict[str, pd.Series]],
) -> dict[str, Any]:
    specs = {
        "relational_companion": ("relational", "companion", "relationship evidence companion"),
        "duplicate_companion": ("duplicate", "companion", "duplicate-like evidence companion"),
        "timeseries_context": ("timeseries", "context", "timing context, not primary"),
        "statistical_companion": ("unsupervised", "companion", "statistical evidence companion"),
    }
    out: dict[str, Any] = {}
    for label, (family, role, product_role) in specs.items():
        mask = masks[family][role]
        denominator = int(mask.sum())
        out[label] = {
            "denominator": denominator,
            "product_role": product_role,
            "topn": _exact_family_topn_recall(exact_native, df, mask, family),
        }
    return out


def _family_failure_mode_diagnostics(primary_recall: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "methodology_note": (
            "v3.3d reruns PHASE2 native detectors on the shortcut-free 318k-document "
            "journal and uses exact document-id joins. A zero result can mean either "
            "no cases were produced or cases were produced but target documents did not "
            "surface in TOP500; these are different follow-up classes."
        ),
        "shortcut_and_scale_note": (
            "The recall drop reflects both journal-visible shortcut removal and realistic "
            "318,653-document scale. Neither should be fixed by reintroducing shortcut tokens."
        ),
        "families": {},
    }
    for family in PHASE2_FAMILIES:
        family_recall = primary_recall[family]
        denominator = int(family_recall["denominator"])
        case_count = int(family_recall.get("exact_join_case_count") or 0)
        top500 = family_recall["topn"]["top500"]
        matched = int(top500.get("matched_docs") or 0)
        if denominator == 0:
            mode = "no_primary_denominator"
        elif case_count == 0:
            mode = "zero_cases_produced"
        elif matched == 0:
            mode = "cases_produced_not_surfaced_top500"
        elif matched < denominator:
            mode = "partially_surfaced_top500"
        else:
            mode = "fully_surfaced_top500"
        out["families"][family] = {
            "primary_denominator": denominator,
            "case_count": case_count,
            "top500_matched_docs": matched,
            "failure_mode": mode,
        }
    if out["families"]["intercompany"]["failure_mode"] != "fully_surfaced_top500":
        out["families"]["intercompany"]["root_cause_status"] = (
            "requires_matcher_root_cause_before_treating_0_of_34_as_capability_conclusion"
        )
        out["families"]["intercompany"]["root_cause_hint"] = (
            "Truth documents have IntercompanyAffiliate context and IC-Cxxx trading_partner "
            "values, but native IC produced zero cases; check reciprocal pairing over "
            "company_code/trading_partner rather than shortcut-token matching."
        )
    else:
        out["families"]["intercompany"]["root_cause_status"] = "resolved_in_v33d_full_run"
    return out


def _action_tier_estimate(
    exact_native: dict[str, Any],
    df: pd.DataFrame,
    masks: dict[str, dict[str, pd.Series]],
    phase1_sets: dict[str, set[str]],
) -> dict[str, Any]:
    tier_sets = {
        "outside_phase1_immediate": phase1_sets["immediate"],
        "outside_phase1_review_or_higher": phase1_sets["review_or_higher"],
        "outside_phase1_candidate_or_higher": phase1_sets["candidate_or_higher"],
    }
    specs: dict[str, tuple[str, str]] = {
        **{f"{family}_primary": (family, "primary") for family in PHASE2_FAMILIES},
        "relational_companion": ("relational", "companion"),
        "duplicate_companion": ("duplicate", "companion"),
        "timeseries_context": ("timeseries", "context"),
        "statistical_companion": ("unsupervised", "companion"),
    }
    out: dict[str, Any] = {
        "note": (
            "Outside-PHASE1 add counts use exact v3.3d TOP500 native case document joins; "
            "owner assignment remains detector-blind."
        )
    }
    for label, (family, role) in specs.items():
        mask = masks[family][role]
        denominator = int(mask.sum())
        target_docs = set(df.loc[mask, "document_id"].astype(str))
        top500_docs = exact_native["family_results"][family]["topn_docs"][500]
        matched_docs = top500_docs & target_docs
        row: dict[str, Any] = {
            "denominator": denominator,
            "family_matched_top500_docs": len(matched_docs),
        }
        for tier_name, phase1_set in tier_sets.items():
            row[f"{tier_name}_truth_docs"] = denominator - _phase1_coverage(
                mask, df, phase1_set
            )
        row["phase2_adds_outside_phase1_immediate_docs"] = len(
            matched_docs - phase1_sets["immediate"]
        )
        row["phase2_adds_outside_phase1_review_or_higher_docs"] = len(
            matched_docs - phase1_sets["review_or_higher"]
        )
        row["phase2_adds_outside_phase1_candidate_or_higher_docs"] = len(
            matched_docs - phase1_sets["candidate_or_higher"]
        )
        out[label] = row
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


def _forbidden_values(df: pd.DataFrame) -> set[str]:
    columns = [
        "document_id",
        "relationship_group_id",
        "duplicate_pair_group_id",
        "relationship_source_entity",
        "relationship_target_entity",
    ]
    values: set[str] = set()
    for column in columns:
        if column in df.columns:
            values.update(value for value in df[column].astype(str) if value and value != "none")
    return values


def _journal_shape_and_guard(manifest: dict[str, Any]) -> dict[str, Any]:
    with JOURNAL_PATH.open("r", encoding="utf-8", newline="") as fh:
        header = next(csv.reader(fh))
    journal_docs = int(
        pd.read_csv(JOURNAL_PATH, usecols=["document_id"], dtype=str)["document_id"].nunique()
    )
    leaked_flag_columns = [
        column
        for column in header
        if any(token in column.lower() for token in OWNER_FLAG_TOKENS)
    ]
    stats = manifest["stats"]["journal_entries_all"]
    return {
        "journal_rows": int(stats["rows"]),
        "journal_docs": journal_docs,
        "journal_columns": len(header),
        "new_owner_truth_flags_in_journal_columns": leaked_flag_columns,
    }


def _raw_leak_check(payload: dict[str, Any], df: pd.DataFrame) -> dict[str, Any]:
    text = json.dumps(payload, ensure_ascii=False)
    keys = {key.lower() for key in _walk_keys(payload)}
    forbidden_key_count = sum(1 for key in keys if key in FORBIDDEN_IDENTIFIER_KEYS)
    forbidden_values = _forbidden_values(df)
    forbidden_value_count = sum(1 for value in forbidden_values if value and value in text)
    return {
        "doc_like_token_count": len(re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-", text)),
        "forbidden_identifier_key_count": forbidden_key_count,
        "forbidden_identifier_value_count": forbidden_value_count,
        "phase2_case_id_like_token_count": text.lower().count("phase2_case_"),
    }


def _data_quality_checks(
    payload_without_checks: dict[str, Any],
    df: pd.DataFrame,
    masks: dict[str, dict[str, pd.Series]],
    manifest: dict[str, Any],
    exact_join_available: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    journal = _journal_shape_and_guard(manifest)
    raw_check = _raw_leak_check(payload_without_checks, df)
    scenario = df["manipulation_scenario"].astype(str)
    period_end = scenario.eq("period_end_adjustment_manipulation")
    circular = scenario.eq("circular_related_party_transaction")
    checks = {
        "truth_docs": int(len(df)),
        "anomaly_label_docs": int(manifest["label_summary"]["documents"]),
        **journal,
        "expected_denominator_counts_match": {
            "phase1_primary": int(masks["phase1"]["primary"].sum()) == 483,
            "intercompany_primary": int(masks["intercompany"]["primary"].sum()) == 34,
            "timeseries_primary": int(masks["timeseries"]["primary"].sum()) == 21,
            "unsupervised_primary": int(masks["unsupervised"]["primary"].sum()) == 40,
            "relational_primary": int(masks["relational"]["primary"].sum()) == 23,
            "duplicate_primary": int(masks["duplicate"]["primary"].sum()) == 19,
            "relational_companion": int(masks["relational"]["companion"].sum()) == 116,
            "duplicate_companion": int(masks["duplicate"]["companion"].sum()) == 71,
            "timeseries_context": int(masks["timeseries"]["context"].sum()) == 92,
            "statistical_companion": int(masks["unsupervised"]["companion"].sum()) == 404,
        },
        "relationship_primary_target_count": int(masks["relational"]["primary"].sum()),
        "relationship_companion_target_count": int(masks["relational"]["companion"].sum()),
        "duplicate_primary_target_count": int(masks["duplicate"]["primary"].sum()),
        "duplicate_companion_target_count": int(masks["duplicate"]["companion"].sum()),
        "statistical_primary_count": int(masks["unsupervised"]["primary"].sum()),
        "statistical_companion_count": int(masks["unsupervised"]["companion"].sum()),
        "suspense_policy_override_count": int(
            df["truth_owner_subtype"].astype(str).eq("long_aged_suspense_balance").sum()
        ),
        "suspense_in_phase1_primary_count": int(
            (
                masks["phase1"]["primary"]
                & df["truth_owner_subtype"].astype(str).eq("long_aged_suspense_balance")
            ).sum()
        ),
        "suspense_in_unsupervised_primary_count": int(
            (
                masks["unsupervised"]["primary"]
                & df["truth_owner_subtype"].astype(str).eq("long_aged_suspense_balance")
            ).sum()
        ),
        "suspense_in_statistical_companion_count": int(
            (
                masks["unsupervised"]["companion"]
                & df["truth_owner_subtype"].astype(str).eq("long_aged_suspense_balance")
            ).sum()
        ),
        "injected_intercompany_primary_count": int(masks["intercompany"]["primary"].sum()),
        "injected_timing_primary_count": int(masks["timeseries"]["primary"].sum()),
        "circular_intercompany_primary_count": int(
            (masks["intercompany"]["primary"] & circular).sum()
        ),
        "non_circular_intercompany_primary_count": int(
            (masks["intercompany"]["primary"] & ~circular).sum()
        ),
        "period_end_timeseries_primary_count": int(
            (masks["timeseries"]["primary"] & period_end).sum()
        ),
        "relationship_primary_semantic_group_counts": _value_counts(
            df.loc[masks["relational"]["primary"], "truth_owner_subtype"]
        ),
        "duplicate_primary_semantic_group_counts": _value_counts(
            df.loc[masks["duplicate"]["primary"], "duplicate_semantic_group"]
        ),
        "fictitious_subtype_counts": _value_counts(
            df.loc[scenario.eq("fictitious_entry"), "truth_owner_subtype"]
        ),
        "within_scenario_split_recall_requires_exact_join": True,
        "exact_matched_doc_join_available": exact_join_available,
        "owner_assignment_uses_detector_output_score_rank_topn_matched_result": False,
        "historical_artifacts_retained": all(
            path.exists()
            for path in [
                ROOT / "artifacts" / "phase2_family_responsibility_recall_fixed5_20260530.json",
                ROOT / "artifacts" / "phase2_family_responsibility_recall_v2_fixed5_20260530.json",
                ROOT / "artifacts" / "phase2_family_responsibility_recall_v21_fixed5_20260530.json",
                ROOT
                / "artifacts"
                / "phase2_family_responsibility_recall_v3_fixed5_ownermeta_ic_20260530.json",
                ROOT
                / "artifacts"
                / "phase2_family_responsibility_recall_v31_fixed5_ownermeta_ic_20260530.json",
                ROOT
                / "artifacts"
                / "phase2_family_responsibility_recall_v32_fixed5_ownermeta_v32d_20260531.json",
            ]
        ),
    }
    return checks, raw_check


def build_payload() -> dict[str, Any]:
    df = _load_truth()
    manifest = _load_manifest()
    masks = _owner_masks(df)
    phase1_sets = _phase1_sets(df)
    exact_native = _build_v33d_native_measurement(df)
    primary_recall = _primary_recall(
        exact_native,
        df,
        masks,
        phase1_sets,
    )
    payload: dict[str, Any] = {
        "metadata": {
            "generated_at": _now_iso(),
            "owner_metadata_version": OWNER_METADATA_VERSION,
            "candidate_name": CANDIDATE_NAME,
            "policy_model": "audit_rule_first_v33d_owner_metadata_with_suspense_override",
            "current_canonical_candidate": True,
            "current_canonical": False,
            "canonical_status": "candidate_pending_product_interpretation_review",
            "fixed4_used": False,
            "production_ranking_changed": False,
            "production_gate_changed": False,
            "production_fusion_changed": False,
            "detector_outputs_used_for_owner_assignment": False,
        },
        "v33b_to_v33d_policy_diff": {
            "phase1_primary": {
                "v33b_evaluator_policy": 483,
                "v33d_evaluator_policy": 483,
                "reason": "long_aged_suspense_balance 100 is rule/account-policy primary",
            },
            "relational_primary": {
                "v33b": 20,
                "v33d": 23,
                "reason": (
                    "relationship primary references were regenerated without "
                    "journal-visible shortcut tokens"
                ),
            },
            "duplicate_primary": {
                "v33b": 22,
                "v33d": 19,
                "reason": (
                    "duplicate primary pair evidence was regenerated with natural "
                    "expense references"
                ),
            },
            "unsupervised_primary": {
                "v33b_evaluator_policy": 40,
                "v33d_evaluator_policy": 40,
                "reason": (
                    "statistical primary feature-space owner metadata is accepted except "
                    "long_aged_suspense_balance, which is PHASE1 primary by rule-ownability"
                ),
            },
            "relationship_companion": {"v33b": 119, "v33d": 116},
            "duplicate_companion": {"v33b": 71, "v33d": 71},
            "statistical_companion": {
                "v33b_evaluator_policy": 404,
                "v33d_evaluator_policy": 404,
            },
        },
        "native_measurement_metadata_v33d": {
            "dataset": exact_native["dataset"],
            "row_count": exact_native["row_count"],
            "document_count": exact_native["document_count"],
            "truth_documents_present_in_journal": exact_native[
                "truth_documents_present_in_journal"
            ],
            "truth_documents_missing_from_journal": exact_native[
                "truth_documents_missing_from_journal"
            ],
            "elapsed_seconds": exact_native["elapsed_seconds"],
            "family_case_counts": {
                family: exact_native["family_results"][family]["case_count"]
                for family in PHASE2_FAMILIES
            },
            "measurement_basis": "current PHASE2 native cases rerun on v3.3d journal input",
        },
        "primary_denominators_v33d": _primary_denominators(masks),
        "companion_context_denominators_v33d": _companion_denominators(masks),
        "overlap_matrix": _overlap_matrix(df, masks),
        "primary_owner_target_recall_v33d": primary_recall,
        "family_failure_mode_diagnostics_v33d": _family_failure_mode_diagnostics(
            primary_recall
        ),
        "product_ordering_lock_v33d": _product_ordering_lock(masks, primary_recall),
        "companion_context_contribution_v33d": _companion_recall(exact_native, df, masks),
        "phase1_action_tier_comparison_v33d": _action_tier_estimate(
            exact_native, df, masks, phase1_sets
        ),
        "decision_summary": {
            "phase1": (
                "PHASE1 primary is v3.3d truth_owner_primary plus the "
                "long_aged_suspense_balance rule-ownability override."
            ),
            "intercompany": "IC primary denominator is 34 circular related-party documents.",
            "relational": (
                "Relational primary denominator is 23 employee_vendor_hidden_relationship "
                "documents regenerated without journal-visible shortcut tokens; circular "
                "related-party remains relationship companion."
            ),
            "duplicate": (
                "Duplicate primary denominator is 19 time_shifted_duplicate row_score "
                "documents; duplicate companion denominator is 71."
            ),
            "timeseries": (
                "Timeseries primary is 21; period-end 92 remains timing context. "
                "The product/default ordering is ts_specific_top100_stabilized_surface "
                "with 21/21 primary target coverage. The previous ordering is retained "
                "only as an internal debug baseline."
            ),
            "unsupervised": (
                "VAE primary is 40 statistical existence documents after excluding "
                "long-aged suspense; statistical companion denominator is 404. "
                "VAE primary recall uses exact matched-doc join."
            ),
        },
    }
    checks, raw_check = _data_quality_checks(
        payload,
        df,
        masks,
        manifest,
        exact_join_available=True,
    )
    payload["data_quality_and_policy_checks"] = checks
    payload["raw_identifier_leak_check"] = raw_check
    if payload["overlap_matrix"]["primary_non_self_overlap_count"] != 0:
        raise ValueError("v3.3d primary overlap detected")
    if any(raw_check.values()):
        raise ValueError(f"raw identifier leak check failed: {raw_check}")
    return payload


def main(_argv: list[str] | None = None) -> int:
    payload = build_payload()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT_JSON.relative_to(ROOT).as_posix()}")
    print(
        json.dumps(
            {
                "primary_denominators_v33d": payload["primary_denominators_v33d"],
                "companion_context_denominators_v33d": payload[
                    "companion_context_denominators_v33d"
                ],
                "primary_owner_target_recall_v33d": payload[
                    "primary_owner_target_recall_v33d"
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
