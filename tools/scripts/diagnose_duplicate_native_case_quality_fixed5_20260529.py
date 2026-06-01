"""Duplicate native case attrition diagnosis for fixed5.

Aggregate-only diagnostic for the duplicate family native evidence lane. The
script traces row-score truth coverage through candidate subset, generated pair
artifact, retained top_pairs, and DuplicateCase builder gates without writing raw
document identifiers.
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import pickle
import re
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
from config.settings import AuditSettings, get_settings
from src.detection.duplicate_detector import DuplicateDetector
from src.detection.duplicate_pair_features import (
    _select_large_input_candidate_frame,
    build_duplicate_pair_artifact,
)
from src.services.duplicate_pair_tier import classify_pair_evidence_tier
from src.services.phase2_duplicate_case_builder import build_duplicate_cases
from tools.scripts.phase2_family_correlation_audit import _fast_time_shifted_duplicate

DATASET_NAME = "datasynth_manipulation_v7_candidate_fixed5_normalcal5"
BATCH_ID = "fixed5_duplicate_quality_diagnosis_20260529"
CASE_INPUT_PKL = ROOT / "artifacts" / "phase1_manipulation_v7_fixed5_normalcal5_case_input.pkl"
TRUTH_CSV = (
    ROOT / "data" / "journal" / "primary" / DATASET_NAME / "labels" / "manipulated_entry_truth.csv"
)
OUT_JSON = ROOT / "artifacts" / "duplicate_native_case_quality_diagnosis_fixed5_20260529.json"
RETENTION_SIZES = (500, 2_000, 10_000, 50_000)
RAW_DOC_TOKEN_PATTERN = re.compile(r"\b(?:DOC-|TRUTH-)[A-Za-z0-9_-]*")
PHASE2_DUPLICATE_CASE_ID_PATTERN = re.compile(r"\bp2_duplicate_[A-Za-z0-9_-]*")
FORBIDDEN_IDENTIFIER_KEYS = frozenset(
    {
        "document_id",
        "document_ids",
        "left_document_id",
        "right_document_id",
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
)


def _doc_set_from_pairs(pairs: Iterable[dict[str, Any]]) -> set[str]:
    docs: set[str] = set()
    for pair in pairs:
        for key in ("left_document_id", "right_document_id"):
            value = pair.get(key)
            if value not in (None, ""):
                docs.add(str(value))
    return docs


def _pair_docs(pair: dict[str, Any]) -> set[str]:
    return _doc_set_from_pairs([pair])


def _case_docs(case: Any) -> set[str]:
    return {
        str(ref.document_id)
        for ref in getattr(case, "row_refs", ())
        if getattr(ref, "document_id", None) not in (None, "")
    }


def _tier(pair: dict[str, Any]) -> str:
    features = pair.get("features")
    return classify_pair_evidence_tier(features if isinstance(features, dict) else None)


def _dist(values: Iterable[Any]) -> dict[str, int]:
    return dict(sorted((str(k), int(v)) for k, v in Counter(values).items()))


def _quantiles(values: Iterable[float | int | None]) -> dict[str, float]:
    vals = sorted(float(v) for v in values if v is not None)
    if not vals:
        return {}

    def q(pct: float) -> float:
        return vals[int(round((len(vals) - 1) * pct))]

    return {
        "min": vals[0],
        "p25": q(0.25),
        "p50": q(0.50),
        "p75": q(0.75),
        "p90": q(0.90),
        "max": vals[-1],
    }


def _feature_values(pairs: Iterable[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for pair in pairs:
        value = pair.get("features", {}).get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            values.append(float(value))
    return values


def _rate(numerator: int, denominator: int) -> float:
    return float(numerator / denominator) if denominator else 0.0


def pair_feature_profile(pairs: list[dict[str, Any]], truth_docs: set[str]) -> dict[str, Any]:
    """Aggregate feature profile for a pair collection without raw identifiers."""
    doc_counts = Counter()
    doc_pair_counts = Counter()
    truth_pair_count = 0
    for pair in pairs:
        docs = sorted(_pair_docs(pair))
        if docs:
            for doc in docs:
                doc_counts[doc] += 1
            if len(docs) == 1:
                doc_pair_counts[(docs[0], docs[0])] += 1
            else:
                doc_pair_counts[(docs[0], docs[-1])] += 1
        if set(docs) & truth_docs:
            truth_pair_count += 1

    same_account_true = sum(1 for p in pairs if p.get("features", {}).get("same_account") is True)
    same_partner_true = sum(1 for p in pairs if p.get("features", {}).get("same_partner") is True)
    return {
        "pair_count": len(pairs),
        "truth_covering_pair_count": truth_pair_count,
        "doc_count": len(doc_counts),
        "truth_doc_count": len(set(doc_counts) & truth_docs),
        "rule_id_distribution": _dist(pair.get("rule_id") for pair in pairs),
        "evidence_tier_distribution": _dist(_tier(pair) for pair in pairs),
        "same_account_rate": _rate(same_account_true, len(pairs)),
        "same_partner_rate": _rate(same_partner_true, len(pairs)),
        "amount_similarity_quantiles": _quantiles(_feature_values(pairs, "amount_similarity")),
        "date_distance_days_quantiles": _quantiles(_feature_values(pairs, "date_distance_days")),
        "reference_similarity_quantiles": _quantiles(
            _feature_values(pairs, "reference_similarity")
        ),
        "text_similarity_quantiles": _quantiles(_feature_values(pairs, "text_similarity")),
        "pair_score_quantiles": _quantiles(pair.get("pair_score") for pair in pairs),
        "document_diversity": {
            "unique_document_count": len(doc_counts),
            "unique_document_pair_count": len(doc_pair_counts),
            "max_pairs_per_document": max(doc_counts.values()) if doc_counts else 0,
            "max_pairs_per_document_pair": max(doc_pair_counts.values()) if doc_pair_counts else 0,
        },
    }


def _copy_settings_with_top_n(settings: AuditSettings, top_n: int) -> AuditSettings:
    """Copy duplicate artifact settings, changing retention cap only."""
    return AuditSettings(
        duplicate_pair_artifact_top_n=int(top_n),
        duplicate_pair_artifact_max_rows=int(settings.duplicate_pair_artifact_max_rows),
        duplicate_max_pairs_per_row=int(settings.duplicate_max_pairs_per_row),
        duplicate_max_total_pairs=int(settings.duplicate_max_total_pairs),
        duplicate_max_group_size=int(settings.duplicate_max_group_size),
        duplicate_fuzzy_threshold=int(settings.duplicate_fuzzy_threshold),
        duplicate_amount_tolerance=float(settings.duplicate_amount_tolerance),
        duplicate_split_window_days=int(settings.duplicate_split_window_days),
        duplicate_time_window_days=int(settings.duplicate_time_window_days),
        duplicate_pair_artifact_max_pairs_per_document=int(
            settings.duplicate_pair_artifact_max_pairs_per_document
        ),
        duplicate_pair_artifact_max_pairs_per_document_pair=int(
            settings.duplicate_pair_artifact_max_pairs_per_document_pair
        ),
    )


def build_retention_diagnostic(
    *,
    df: pd.DataFrame,
    settings: AuditSettings,
    scores: pd.Series,
    details: pd.DataFrame,
    truth_docs: set[str],
    retention_sizes: Iterable[int] = RETENTION_SIZES,
) -> dict[str, Any]:
    """Build retention-cap diagnostics without changing detector thresholds."""
    out: dict[str, Any] = {}
    for size in retention_sizes:
        artifact = build_duplicate_pair_artifact(
            df,
            _copy_settings_with_top_n(settings, int(size)),
            candidate_scores=scores,
            candidate_details=details,
        ).to_dict()
        pairs = artifact.get("top_pairs", [])
        truth_ranks = [
            rank
            for rank, pair in enumerate(pairs, start=1)
            if _pair_docs(pair) & truth_docs
        ]
        case_grade_pairs = [pair for pair in pairs if _tier(pair) in {"strong", "moderate"}]
        case_grade_truth_docs = _doc_set_from_pairs(case_grade_pairs) & truth_docs
        out[str(size)] = {
            "top_pairs_count": len(pairs),
            "truth_doc_count": len(_doc_set_from_pairs(pairs) & truth_docs),
            "case_grade_truth_doc_count": len(case_grade_truth_docs),
            "first_truth_pair_rank": min(truth_ranks) if truth_ranks else None,
            "truth_pair_rank_quantiles": _quantiles(truth_ranks),
            "evidence_tier_distribution": _dist(_tier(pair) for pair in pairs),
            "rule_id_distribution": _dist(pair.get("rule_id") for pair in pairs),
            "top_pair_selection": artifact.get("coverage", {}).get("top_pair_selection", {}),
        }
    return out


def case_builder_gate_diagnostic(
    *,
    top_pairs: list[dict[str, Any]],
    cases: tuple[Any, ...],
    truth_docs: set[str],
    join_failed_pairs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Break down top-pair to DuplicateCase attrition for truth-covering pairs."""
    weak_truth_docs: set[str] = set()
    case_grade_top_pair_truth_docs: set[str] = set()
    for pair in top_pairs:
        docs = _pair_docs(pair)
        if not (docs & truth_docs):
            continue
        if _tier(pair) in {"strong", "moderate"}:
            case_grade_top_pair_truth_docs.update(docs & truth_docs)
        else:
            weak_truth_docs.update(docs & truth_docs)

    case_docs = set().union(*(_case_docs(case) for case in cases)) if cases else set()
    join_failed_truth_docs = set()
    for pair in join_failed_pairs or []:
        join_failed_truth_docs.update(_pair_docs(pair) & truth_docs)
    case_ids = [getattr(case, "phase2_case_id", "") for case in cases]
    duplicate_case_id_count = sum(count - 1 for count in Counter(case_ids).values() if count > 1)
    missing_doc_case_count = sum(1 for case in cases if not _case_docs(case))
    return {
        "case_grade_top_pairs_truth_docs": len(case_grade_top_pair_truth_docs),
        "duplicate_case_truth_docs": len(case_docs & truth_docs),
        "weak_pair_truth_docs": len(weak_truth_docs),
        "pair_join_failed_truth_docs": len(join_failed_truth_docs),
        "case_created_but_document_id_missing_count": int(missing_doc_case_count),
        "duplicate_case_id_collapse_count": int(duplicate_case_id_count),
        "case_builder_exclusion_reasons": {
            "weak_pair_truth_docs": len(weak_truth_docs),
            "pair_join_failed_truth_docs": len(join_failed_truth_docs),
            "case_created_but_document_id_missing_count": int(missing_doc_case_count),
            "duplicate_case_id_collapse_count": int(duplicate_case_id_count),
        },
    }


def _load_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    with CASE_INPUT_PKL.open("rb") as fh:
        payload = pickle.load(fh)
    df = payload["df"].copy()
    df["document_id"] = df["document_id"].astype(str)
    truth = pd.read_csv(TRUTH_CSV)
    truth["document_id"] = truth["document_id"].astype(str)
    return df, truth


def raw_identifier_leak_check(
    payload: dict[str, Any],
    *,
    forbidden_values: Iterable[str] | None = None,
) -> dict[str, int]:
    """Return aggregate-only raw identifier leak counts for diagnostic payload."""
    text = json.dumps(payload, ensure_ascii=False)
    forbidden_value_count = 0
    if forbidden_values is not None:
        forbidden_value_count = sum(1 for value in forbidden_values if value and value in text)
    return {
        "doc_like_token_count": len(RAW_DOC_TOKEN_PATTERN.findall(text)),
        "forbidden_identifier_key_count": _count_forbidden_identifier_keys(payload),
        "forbidden_identifier_value_count": int(forbidden_value_count),
        "phase2_case_id_like_token_count": len(PHASE2_DUPLICATE_CASE_ID_PATTERN.findall(text)),
    }


def _count_forbidden_identifier_keys(value: Any) -> int:
    if isinstance(value, dict):
        count = sum(1 for key in value if str(key) in FORBIDDEN_IDENTIFIER_KEYS)
        return count + sum(_count_forbidden_identifier_keys(item) for item in value.values())
    if isinstance(value, list):
        return sum(_count_forbidden_identifier_keys(item) for item in value)
    return 0


def main() -> int:
    started = time.perf_counter()
    df, truth = _load_inputs()
    truth_docs = set(truth["document_id"])
    settings = get_settings()
    duplicate_detector_module.b05d_time_shifted_duplicate = _fast_time_shifted_duplicate
    result = DuplicateDetector(settings).detect(df)
    top_artifact = result.metadata["pair_artifact"]
    top_pairs = list(top_artifact.get("top_pairs", []))
    cases = build_duplicate_cases(batch_id=BATCH_ID, detection_result=result, df=df)

    scores = result.scores.reindex(df.index).fillna(0.0).astype(float)
    row_hit_mask = scores > 0
    truth_row_mask = df["document_id"].isin(truth_docs)
    truth_hit_mask = row_hit_mask & truth_row_mask
    row_score_truth_docs = set(df.loc[truth_hit_mask, "document_id"])

    candidate_df, candidate_coverage = _select_large_input_candidate_frame(
        df,
        max_rows=int(settings.duplicate_pair_artifact_max_rows),
        candidate_scores=result.scores,
        candidate_details=result.details,
    )
    candidate_docs = set() if candidate_df is None else set(candidate_df["document_id"].astype(str))

    generated_artifact = build_duplicate_pair_artifact(
        df,
        _copy_settings_with_top_n(settings, int(settings.duplicate_max_total_pairs)),
        candidate_scores=result.scores,
        candidate_details=result.details,
    ).to_dict()
    generated_pairs = list(generated_artifact.get("top_pairs", []))
    generated_docs = _doc_set_from_pairs(generated_pairs)
    top_docs = _doc_set_from_pairs(top_pairs)
    case_docs = set().union(*(_case_docs(case) for case in cases)) if cases else set()

    top_case_gate = case_builder_gate_diagnostic(
        top_pairs=top_pairs,
        cases=cases,
        truth_docs=truth_docs,
    )
    generated_truth_pairs = [pair for pair in generated_pairs if _pair_docs(pair) & truth_docs]
    generated_nontruth_pairs = [
        pair for pair in generated_pairs if not (_pair_docs(pair) & truth_docs)
    ]
    top_truth_pairs = [pair for pair in top_pairs if _pair_docs(pair) & truth_docs]
    top_nontruth_pairs = [pair for pair in top_pairs if not (_pair_docs(pair) & truth_docs)]

    generated_pair_truth_docs_by_rule: dict[str, set[str]] = {}
    for pair in generated_truth_pairs:
        generated_pair_truth_docs_by_rule.setdefault(str(pair.get("rule_id")), set()).update(
            _pair_docs(pair) & truth_docs
        )
    generated_pair_truth_docs_by_rule_id = {
        rule_id: len(docs) for rule_id, docs in sorted(generated_pair_truth_docs_by_rule.items())
    }

    retention = build_retention_diagnostic(
        df=df,
        settings=settings,
        scores=result.scores,
        details=result.details,
        truth_docs=truth_docs,
    )
    retention_500 = retention.get("500", {})

    payload: dict[str, Any] = {
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "dataset": DATASET_NAME,
        "measurement_scope": (
            "duplicate native case candidate-to-case attrition; aggregate only; "
            "raw document identifiers omitted"
        ),
        "row_count": len(df),
        "document_count": int(df["document_id"].nunique()),
        "row_score_hit_count": int(row_hit_mask.sum()),
        "truth_doc_count": len(truth_docs),
        "truth_row_count": int(truth_row_mask.sum()),
        "truth_row_score_hit_count": int(truth_hit_mask.sum()),
        "row_score_truth_docs": len(row_score_truth_docs),
        "truth_docs_with_duplicate_row_score": len(row_score_truth_docs),
        "candidate_subset_size": int(candidate_coverage.get("selected_candidate_rows", 0)),
        "candidate_subset_truth_docs": len(candidate_docs & truth_docs),
        "candidate_subset_truth_doc_count": len(candidate_docs & truth_docs),
        "generated_pair_truth_docs": len(generated_docs & truth_docs),
        "generated_pair_truth_docs_by_rule_id": generated_pair_truth_docs_by_rule_id,
        "top_pairs_truth_docs": len(top_docs & truth_docs),
        "top_pairs_truth_doc_count": len(top_docs & truth_docs),
        "case_grade_top_pairs_truth_docs": top_case_gate["case_grade_top_pairs_truth_docs"],
        "duplicate_case_truth_docs": len(case_docs & truth_docs),
        "duplicate_case_truth_doc_count": len(case_docs & truth_docs),
        "weak_pair_truth_docs": top_case_gate["weak_pair_truth_docs"],
        "pair_join_failed_truth_docs": top_case_gate["pair_join_failed_truth_docs"],
        "top_pairs_outside_retention_truth_docs": len((generated_docs & truth_docs) - top_docs),
        "case_builder_exclusion_reasons": top_case_gate["case_builder_exclusion_reasons"],
        "candidate_subset_coverage": candidate_coverage,
        "pair_artifact": {
            "top_pairs_count": len(top_pairs),
            "retained_pairs": int(top_artifact.get("retained_pairs", 0)),
            "total_candidate_pairs": int(top_artifact.get("total_candidate_pairs", 0)),
            "candidate_pairs_after_caps": int(top_artifact.get("candidate_pairs_after_caps", 0)),
            "truncated": bool(top_artifact.get("truncated")),
            "truncation_reason": top_artifact.get("truncation_reason"),
            "rule_pair_counts": top_artifact.get("rule_pair_counts", {}),
            "coverage": top_artifact.get("coverage", {}),
        },
        "top_pairs_count": len(top_pairs),
        "rule_id_distribution": _dist(pair.get("rule_id") for pair in top_pairs),
        "evidence_tier_distribution": _dist(_tier(pair) for pair in top_pairs),
        "top_pairs_doc_coverage": {
            "doc_count": len(top_docs),
            "truth_doc_count": len(top_docs & truth_docs),
            "nontruth_doc_count": len(top_docs - truth_docs),
        },
        "duplicate_case_count": len(cases),
        "duplicate_cases": {
            "duplicate_case_count": len(cases),
            "duplicate_case_docs_covered": len(case_docs),
            "duplicate_case_truth_doc_count": len(case_docs & truth_docs),
            "duplicate_case_nontruth_doc_count": len(case_docs - truth_docs),
            "rule_id_distribution": _dist(getattr(case, "sub_rule", "") for case in cases),
            "evidence_tier_distribution": _dist(
                getattr(case, "pair_evidence_tier", "") for case in cases
            ),
            "builder_diagnostics": result.metadata.get("duplicate_case_builder_diagnostics", {}),
        },
        "feature_profile": {
            "generated_truth_pairs": pair_feature_profile(generated_truth_pairs, truth_docs),
            "generated_nontruth_pairs": pair_feature_profile(generated_nontruth_pairs, truth_docs),
            "top_truth_pairs": pair_feature_profile(top_truth_pairs, truth_docs),
            "top_nontruth_pairs": pair_feature_profile(top_nontruth_pairs, truth_docs),
        },
        "retention_diagnostic": retention,
        "stage_attrition": {
            "row_score_truth_docs": len(row_score_truth_docs),
            "candidate_subset_truth_docs": len(candidate_docs & truth_docs),
            "generated_pair_truth_docs": len(generated_docs & truth_docs),
            "top_pairs_truth_docs": len(top_docs & truth_docs),
            "case_grade_top_pairs_truth_docs": top_case_gate["case_grade_top_pairs_truth_docs"],
            "duplicate_case_truth_docs": len(case_docs & truth_docs),
            "loss_candidate_subset_to_generated_pair": len(candidate_docs & truth_docs)
            - len(generated_docs & truth_docs),
            "loss_generated_pair_to_top_pairs": len(generated_docs & truth_docs)
            - len(top_docs & truth_docs),
            "loss_top_pairs_to_case_grade": len(top_docs & truth_docs)
            - top_case_gate["case_grade_top_pairs_truth_docs"],
            "loss_case_grade_to_duplicate_case": top_case_gate["case_grade_top_pairs_truth_docs"]
            - len(case_docs & truth_docs),
        },
        "stage_diagnosis": {
            "primary_bottleneck": (
                "top_pairs_retention"
                if retention_500.get("truth_doc_count", 0) < len(generated_docs & truth_docs)
                else "case_builder_gate"
            ),
            "weak_tier_is_major_top_pair_gate": top_case_gate["weak_pair_truth_docs"]
            > top_case_gate["case_grade_top_pairs_truth_docs"],
            "join_or_canonical_issue_detected": top_case_gate["pair_join_failed_truth_docs"] > 0,
            "document_id_mapping_issue_detected": top_case_gate[
                "case_created_but_document_id_missing_count"
            ]
            > 0,
        },
        "interpretation": {
            "truth_labels_used_for_diagnosis_only": True,
            "detector_scores_or_thresholds_changed": False,
            "phase1_priority_or_phase2_family_fusion_changed": False,
            "row_score_promoted_without_pair_evidence": False,
        },
        "raw_identifier_leak_check": {},
        "elapsed_seconds": None,
    }
    payload["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    payload["raw_identifier_leak_check"] = raw_identifier_leak_check(
        payload,
        forbidden_values=truth_docs,
    )
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "out": OUT_JSON.as_posix(),
                "stage_attrition": payload["stage_attrition"],
                "retention_500": retention.get("500", {}),
                "retention_10000": retention.get("10000", {}),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
