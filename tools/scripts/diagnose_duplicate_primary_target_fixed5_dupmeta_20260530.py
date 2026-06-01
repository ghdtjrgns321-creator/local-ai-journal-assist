"""Duplicate primary-target attrition diagnosis for fixed5_dupmeta.

Diagnostic-only script. It compares DataSynth duplicate-like primary metadata
against duplicate row score, candidate subset, generated pair evidence,
retained top_pairs, and DuplicateCase builder output. Raw identifiers are used
only in-memory for joins and are not written to the artifact.
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import pickle
import sys
import time
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import src.detection.duplicate_detector as duplicate_detector_module
from config.settings import get_settings
from src.detection.duplicate_detector import DuplicateDetector
from src.detection.duplicate_pair_features import (
    _select_large_input_candidate_frame,
    build_duplicate_pair_artifact,
)
from src.services.phase2_duplicate_case_builder import build_duplicate_cases
from tools.scripts.diagnose_duplicate_native_case_quality_fixed5_20260529 import (
    _copy_settings_with_top_n,
    _dist,
    _doc_set_from_pairs,
    _pair_docs,
    _quantiles,
    _tier,
    raw_identifier_leak_check,
)
from tools.scripts.phase2_family_correlation_audit import _fast_time_shifted_duplicate

DATASET_NAME = "datasynth_manipulation_v7_candidate_fixed5_dupmeta"
CASE_INPUT_PKL = ROOT / "artifacts" / "phase1_manipulation_v7_fixed5_normalcal5_case_input.pkl"
DUPMETA_LABEL_DIR = ROOT / "data" / "journal" / "primary" / DATASET_NAME / "labels"
TRUTH_CSV = DUPMETA_LABEL_DIR / "manipulated_entry_truth.csv"
DUPLICATE_PAIR_TRUTH_CSV = DUPMETA_LABEL_DIR / "duplicate_pair_truth.csv"
OUT_JSON = ROOT / "artifacts" / "duplicate_primary_target_fixed5_dupmeta_20260530.json"
BATCH_ID = "fixed5_dupmeta_duplicate_primary_target_20260530"
RETENTION_SIZES = (500, 2_000, 10_000, 50_000)


def _truth_bool_series(series: pd.Series) -> pd.Series:
    return series.fillna(False).astype(str).str.strip().str.lower().isin(
        {"true", "1", "yes", "y"}
    )


def _load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    with CASE_INPUT_PKL.open("rb") as fh:
        payload = pickle.load(fh)
    df = payload["df"].copy()
    df["document_id"] = df["document_id"].astype(str)
    truth = pd.read_csv(TRUTH_CSV)
    truth["document_id"] = truth["document_id"].astype(str)
    pair_truth = pd.read_csv(DUPLICATE_PAIR_TRUTH_CSV)
    pair_truth["document_id"] = pair_truth["document_id"].astype(str)
    return df, truth, pair_truth


def _primary_docs(truth: pd.DataFrame) -> set[str]:
    return set(
        truth.loc[_truth_bool_series(truth["duplicate_primary_target"]), "document_id"].astype(str)
    )


def _pair_groups(pair_truth: pd.DataFrame) -> dict[str, frozenset[str]]:
    groups: dict[str, frozenset[str]] = {}
    primary_pair_truth = pair_truth[_truth_bool_series(pair_truth["is_primary_target"])]
    for group_id, group in primary_pair_truth.groupby("duplicate_pair_group_id"):
        groups[str(group_id)] = frozenset(group["document_id"].astype(str))
    return groups


def _pair_group_coverage(
    pairs: Iterable[dict[str, Any]],
    truth_pair_groups: dict[str, frozenset[str]],
) -> dict[str, Any]:
    group_docs = set().union(*truth_pair_groups.values()) if truth_pair_groups else set()
    covered_groups: set[str] = set()
    partial_groups: set[str] = set()
    weak_only_groups: set[str] = set()
    case_grade_groups: set[str] = set()
    for pair in pairs:
        docs = frozenset(_pair_docs(pair))
        if not docs or not (set(docs) & group_docs):
            continue
        tier = _tier(pair)
        for group_id, target_docs in truth_pair_groups.items():
            overlap = set(docs) & set(target_docs)
            if docs == target_docs:
                covered_groups.add(group_id)
                if tier in {"strong", "moderate"}:
                    case_grade_groups.add(group_id)
                else:
                    weak_only_groups.add(group_id)
            elif overlap:
                partial_groups.add(group_id)
    return {
        "exact_pair_group_count": len(covered_groups),
        "partial_pair_group_count": len(partial_groups - covered_groups),
        "case_grade_exact_pair_group_count": len(case_grade_groups),
        "weak_exact_pair_group_count": len(weak_only_groups - case_grade_groups),
    }


def _case_docs(cases: Iterable[Any]) -> set[str]:
    docs: set[str] = set()
    for case in cases:
        for ref in getattr(case, "row_refs", ()):
            value = getattr(ref, "document_id", None)
            if value not in (None, ""):
                docs.add(str(value))
    return docs


def _profile_pairs(pairs: list[dict[str, Any]], primary_docs: set[str]) -> dict[str, Any]:
    primary_pairs = [pair for pair in pairs if _pair_docs(pair) & primary_docs]
    nonprimary_pairs = [pair for pair in pairs if not (_pair_docs(pair) & primary_docs)]
    return {
        "primary_pair_count": len(primary_pairs),
        "nonprimary_pair_count": len(nonprimary_pairs),
        "primary_rule_distribution": _dist(pair.get("rule_id") for pair in primary_pairs),
        "primary_tier_distribution": _dist(_tier(pair) for pair in primary_pairs),
        "nonprimary_rule_distribution": _dist(pair.get("rule_id") for pair in nonprimary_pairs),
        "nonprimary_tier_distribution": _dist(_tier(pair) for pair in nonprimary_pairs),
        "primary_pair_score_quantiles": _quantiles(
            pair.get("pair_score") for pair in primary_pairs
        ),
        "nonprimary_pair_score_quantiles": _quantiles(
            pair.get("pair_score") for pair in nonprimary_pairs
        ),
    }


def _row_score_profile(
    *,
    df: pd.DataFrame,
    result: Any,
    scores: pd.Series,
    primary_docs: set[str],
    selected_index: pd.Index,
) -> dict[str, Any]:
    primary_mask = df["document_id"].isin(primary_docs)
    row_hit_mask = scores > 0
    selected_scores = scores.reindex(selected_index).fillna(0.0).astype(float)
    primary_row_hit = primary_mask & row_hit_mask
    details = result.details.reindex(df.index).apply(pd.to_numeric, errors="coerce").fillna(0.0)
    primary_rule_doc_counts: dict[str, int] = {}
    primary_rule_row_counts: dict[str, int] = {}
    for rule_id in details.columns:
        rule_mask = primary_mask & (details[rule_id] > 0)
        primary_rule_doc_counts[str(rule_id)] = int(
            df.loc[rule_mask, "document_id"].astype(str).nunique()
        )
        primary_rule_row_counts[str(rule_id)] = int(rule_mask.sum())
    return {
        "all_row_score_hit_count": int(row_hit_mask.sum()),
        "all_row_score_quantiles": _quantiles(scores[row_hit_mask]),
        "selected_candidate_score_quantiles": _quantiles(selected_scores),
        "selected_candidate_min_score": float(selected_scores.min())
        if len(selected_scores)
        else None,
        "primary_row_count": int(primary_mask.sum()),
        "primary_row_score_hit_row_count": int(primary_row_hit.sum()),
        "primary_row_score_hit_doc_count": int(
            df.loc[primary_row_hit, "document_id"].astype(str).nunique()
        ),
        "primary_row_score_quantiles": _quantiles(scores[primary_row_hit]),
        "primary_rule_doc_counts": primary_rule_doc_counts,
        "primary_rule_row_counts": primary_rule_row_counts,
    }


def _retention_diagnostic(
    *,
    df: pd.DataFrame,
    result: Any,
    primary_docs: set[str],
    truth_pair_groups: dict[str, frozenset[str]],
) -> dict[str, Any]:
    settings = get_settings()
    out: dict[str, Any] = {}
    for size in RETENTION_SIZES:
        artifact = build_duplicate_pair_artifact(
            df,
            _copy_settings_with_top_n(settings, int(size)),
            candidate_scores=result.scores,
            candidate_details=result.details,
        ).to_dict()
        pairs = list(artifact.get("top_pairs", []))
        docs = _doc_set_from_pairs(pairs)
        primary_ranks = [
            rank
            for rank, pair in enumerate(pairs, start=1)
            if _pair_docs(pair) & primary_docs
        ]
        case_grade_pairs = [pair for pair in pairs if _tier(pair) in {"strong", "moderate"}]
        case_grade_docs = _doc_set_from_pairs(case_grade_pairs)
        out[str(size)] = {
            "top_pairs_count": len(pairs),
            "primary_doc_count": len(docs & primary_docs),
            "case_grade_primary_doc_count": len(case_grade_docs & primary_docs),
            "first_primary_pair_rank": min(primary_ranks) if primary_ranks else None,
            "primary_pair_rank_quantiles": _quantiles(primary_ranks),
            "evidence_tier_distribution": _dist(_tier(pair) for pair in pairs),
            "primary_pair_group_coverage": _pair_group_coverage(pairs, truth_pair_groups),
        }
    return out


def _reason_distribution(
    *,
    primary_docs: set[str],
    row_score_docs: set[str],
    candidate_docs: set[str],
    generated_docs: set[str],
    top_docs: set[str],
    case_grade_top_docs: set[str],
    case_docs: set[str],
) -> dict[str, int]:
    reasons: Counter[str] = Counter()
    for doc in primary_docs:
        if doc not in row_score_docs:
            reasons["no_duplicate_row_score"] += 1
        elif doc not in candidate_docs:
            reasons["candidate_subset_excluded"] += 1
        elif doc not in generated_docs:
            reasons["pair_generation_excluded"] += 1
        elif doc not in top_docs:
            reasons["top_pairs_retention_excluded"] += 1
        elif doc not in case_grade_top_docs:
            reasons["weak_or_non_case_grade_top_pair"] += 1
        elif doc not in case_docs:
            reasons["case_builder_excluded"] += 1
        else:
            reasons["duplicate_case_created"] += 1
    return dict(sorted((key, int(value)) for key, value in reasons.items()))


def build_payload() -> dict[str, Any]:
    started = time.perf_counter()
    df, truth, pair_truth = _load_inputs()
    primary_docs = _primary_docs(truth)
    truth_pair_groups = _pair_groups(pair_truth)
    settings = get_settings()
    duplicate_detector_module.b05d_time_shifted_duplicate = _fast_time_shifted_duplicate
    result = DuplicateDetector(settings).detect(df)
    top_pairs = list(result.metadata["pair_artifact"].get("top_pairs", []))
    cases = build_duplicate_cases(batch_id=BATCH_ID, detection_result=result, df=df)

    scores = result.scores.reindex(df.index).fillna(0.0).astype(float)
    row_hit_docs = set(df.loc[scores > 0, "document_id"].astype(str))
    primary_row_score_docs = row_hit_docs & primary_docs

    candidate_df, candidate_coverage = _select_large_input_candidate_frame(
        df,
        max_rows=int(settings.duplicate_pair_artifact_max_rows),
        candidate_scores=result.scores,
        candidate_details=result.details,
    )
    candidate_docs = (
        set()
        if candidate_df is None
        else set(candidate_df["document_id"].astype(str))
    )
    selected_index = pd.Index([]) if candidate_df is None else candidate_df.index

    generated_artifact = build_duplicate_pair_artifact(
        df,
        _copy_settings_with_top_n(settings, int(settings.duplicate_max_total_pairs)),
        candidate_scores=result.scores,
        candidate_details=result.details,
    ).to_dict()
    generated_pairs = list(generated_artifact.get("top_pairs", []))
    generated_docs = _doc_set_from_pairs(generated_pairs)
    top_docs = _doc_set_from_pairs(top_pairs)
    case_grade_top_pairs = [pair for pair in top_pairs if _tier(pair) in {"strong", "moderate"}]
    case_grade_top_docs = _doc_set_from_pairs(case_grade_top_pairs)
    duplicate_case_docs = _case_docs(cases)

    payload: dict[str, Any] = {
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "dataset": DATASET_NAME,
        "diagnostic_only": True,
        "production_first_review_ranking_changed": False,
        "phase1_ranking_changed": False,
        "phase2_fusion_changed": False,
        "threshold_changed": False,
        "row_scores_changed": False,
        "truth_label_used_for_scoring": False,
        "truth_label_used_only_for_aggregate_evaluation": True,
        "measurement_scope": (
            "Duplicate primary target metadata to pair evidence attrition; "
            "aggregate-only artifact"
        ),
        "duplicate_primary_target": {
            "primary_doc_count": len(primary_docs),
            "pair_group_count": len(truth_pair_groups),
            "pair_group_size_distribution": {
                str(size): int(count)
                for size, count in Counter(len(docs) for docs in truth_pair_groups.values())
                .items()
            },
            "scenario_distribution": {
                str(scenario): int(count)
                for scenario, count in truth.loc[
                    _truth_bool_series(truth["duplicate_primary_target"])
                ]
                .groupby("manipulation_scenario")["document_id"]
                .nunique()
                .sort_index()
                .items()
            },
            "period_end_primary_doc_count": int(
                truth.loc[
                    _truth_bool_series(truth["duplicate_primary_target"])
                    & truth["manipulation_scenario"].astype(str).eq(
                        "period_end_adjustment_manipulation"
                    ),
                    "document_id",
                ]
                .astype(str)
                .nunique()
            ),
        },
        "stage_attrition": {
            "primary_target_docs": len(primary_docs),
            "row_score_primary_docs": len(primary_row_score_docs),
            "candidate_subset_primary_docs": len(candidate_docs & primary_docs),
            "generated_pair_primary_docs": len(generated_docs & primary_docs),
            "top_pairs_primary_docs": len(top_docs & primary_docs),
            "case_grade_top_pairs_primary_docs": len(case_grade_top_docs & primary_docs),
            "duplicate_case_primary_docs": len(duplicate_case_docs & primary_docs),
        },
        "primary_pair_group_attrition": {
            "generated": _pair_group_coverage(generated_pairs, truth_pair_groups),
            "top_pairs": _pair_group_coverage(top_pairs, truth_pair_groups),
            "case_grade_top_pairs": _pair_group_coverage(
                case_grade_top_pairs,
                truth_pair_groups,
            ),
        },
        "reason_distribution": _reason_distribution(
            primary_docs=primary_docs,
            row_score_docs=primary_row_score_docs,
            candidate_docs=candidate_docs,
            generated_docs=generated_docs,
            top_docs=top_docs,
            case_grade_top_docs=case_grade_top_docs,
            case_docs=duplicate_case_docs,
        ),
        "candidate_subset": {
            "selected_candidate_rows": int(candidate_coverage.get("selected_candidate_rows", 0)),
            "primary_doc_count": len(candidate_docs & primary_docs),
            "coverage": candidate_coverage,
        },
        "row_score_selection_profile": _row_score_profile(
            df=df,
            result=result,
            scores=scores,
            primary_docs=primary_docs,
            selected_index=selected_index,
        ),
        "pair_artifact": {
            "generated_pair_count": len(generated_pairs),
            "top_pairs_count": len(top_pairs),
            "generated_primary_doc_count": len(generated_docs & primary_docs),
            "top_pairs_primary_doc_count": len(top_docs & primary_docs),
            "top_pairs_case_grade_primary_doc_count": len(case_grade_top_docs & primary_docs),
            "profile": {
                "generated": _profile_pairs(generated_pairs, primary_docs),
                "top_pairs": _profile_pairs(top_pairs, primary_docs),
            },
        },
        "duplicate_cases": {
            "case_count": len(cases),
            "docs_covered": len(duplicate_case_docs),
            "primary_doc_count": len(duplicate_case_docs & primary_docs),
            "case_grade_only": all(
                getattr(case, "pair_evidence_tier", "") in {"strong", "moderate"}
                for case in cases
            )
            if cases
            else True,
            "evidence_tier_distribution": _dist(
                getattr(case, "pair_evidence_tier", "") for case in cases
            ),
            "rule_id_distribution": _dist(getattr(case, "sub_rule", "") for case in cases),
        },
        "retention_diagnostic": _retention_diagnostic(
            df=df,
            result=result,
            primary_docs=primary_docs,
            truth_pair_groups=truth_pair_groups,
        ),
        "interpretation": {
            "primary_bottleneck": "row_score_or_pair_generation"
            if len(generated_docs & primary_docs) == 0
            else "top_pairs_or_builder_retention",
            "period_end_companion_not_duplicate_primary": True,
            "row_score_promoted_without_pair_evidence": False,
        },
        "raw_identifier_leak_check": {},
        "elapsed_seconds": None,
    }
    payload["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    payload["raw_identifier_leak_check"] = raw_identifier_leak_check(
        payload,
        forbidden_values=set(truth["document_id"].astype(str))
        | set(pair_truth["document_id"].astype(str)),
    )
    return payload


def main() -> int:
    payload = build_payload()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "out": OUT_JSON.relative_to(ROOT).as_posix(),
                "stage_attrition": payload["stage_attrition"],
                "primary_pair_group_attrition": payload["primary_pair_group_attrition"],
                "reason_distribution": payload["reason_distribution"],
                "raw_identifier_leak_check": payload["raw_identifier_leak_check"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
