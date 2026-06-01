"""Duplicate v3.2d companion sidecar burden diagnostic.

Diagnostic-only. V3.2d treats duplicate-like evidence as a companion lane, not a
primary owner. This script evaluates whether an export/drilldown sidecar can
recover duplicate-companion pair evidence while reducing the very large
non-target burden observed in the broad observable profile sample.
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd
from rapidfuzz import fuzz

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config.settings import AuditSettings, get_settings
from src.detection.duplicate_pair_features import build_duplicate_pair_artifact
from tools.scripts.diagnose_duplicate_candidate_sidecar_fixed5_dupmeta_20260530 import (
    _sidecar_settings,
)
from tools.scripts.diagnose_duplicate_native_case_quality_fixed5_20260529 import (
    _dist,
    _doc_set_from_pairs,
    _pair_docs,
    _quantiles,
    _tier,
)

DATASET_NAME = "datasynth_manipulation_v7_candidate_fixed5_ownermeta_v32d"
DATA_DIR = ROOT / "data" / "journal" / "primary" / DATASET_NAME
JOURNAL_CSV = DATA_DIR / "journal_entries.csv"
LABEL_DIR = DATA_DIR / "labels"
TRUTH_CSV = LABEL_DIR / "manipulated_entry_truth.csv"
DUPLICATE_PAIR_TRUTH_CSV = LABEL_DIR / "duplicate_pair_truth.csv"
OUT_JSON = ROOT / "artifacts" / "duplicate_v32_companion_sidecar_burden_20260531.json"
RESPONSIBILITY_JSON = (
    ROOT
    / "artifacts"
    / "phase2_family_responsibility_recall_v32_fixed5_ownermeta_v32d_20260531.json"
)

SIDECAR_MAX_ROWS = 20_000
SIDECAR_TOP_N = 5_000
REFERENCE_HIGH_THRESHOLD = 94

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
    "duplicate_pair_group_id",
    "relationship_group_id",
    "relationship_source_entity",
    "relationship_target_entity",
}


def _truth_bool_series(series: pd.Series) -> pd.Series:
    return series.fillna(False).astype(str).str.strip().str.lower().isin(
        {"true", "1", "yes", "y"}
    )


def _load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    usecols = [
        "document_id",
        "company_code",
        "fiscal_year",
        "posting_date",
        "document_type",
        "reference",
        "business_process",
        "source",
        "line_number",
        "gl_account",
        "debit_amount",
        "credit_amount",
        "line_text",
        "trading_partner",
    ]
    df = pd.read_csv(JOURNAL_CSV, usecols=usecols, dtype=str)
    df["document_id"] = df["document_id"].astype(str)
    for amount_column in ("debit_amount", "credit_amount"):
        df[amount_column] = pd.to_numeric(df[amount_column], errors="coerce").fillna(0.0)
    df["line_number"] = pd.to_numeric(df["line_number"], errors="coerce")
    df["posting_date"] = pd.to_datetime(df["posting_date"], errors="coerce")
    truth = pd.read_csv(TRUTH_CSV, dtype=str).fillna("")
    truth["document_id"] = truth["document_id"].astype(str)
    pair_truth = pd.read_csv(DUPLICATE_PAIR_TRUTH_CSV, dtype=str).fillna("")
    pair_truth["document_id"] = pair_truth["document_id"].astype(str)
    return df, truth, pair_truth


def _load_current_duplicate_companion_estimate() -> dict[str, Any]:
    payload = json.loads(RESPONSIBILITY_JSON.read_text(encoding="utf-8"))
    top500 = payload["companion_context_contribution_v32"]["duplicate_companion"]["topn"][
        "top500"
    ]
    return {
        "matched_docs": int(top500.get("matched_docs_estimated_proration") or 0),
        "recall": float(top500.get("recall_estimated_proration") or 0.0),
        "status": str(top500.get("status") or ""),
        "measurement_basis": str(top500.get("measurement_basis") or ""),
        "portfolio_620_matched_docs": int(top500.get("portfolio_620_matched_docs") or 0),
    }


def _sidecar_settings_with_top_n(base: AuditSettings) -> AuditSettings:
    settings = _sidecar_settings(base)
    return AuditSettings(
        **{
            **settings.model_dump(),
            "duplicate_pair_artifact_top_n": SIDECAR_TOP_N,
            "duplicate_pair_artifact_max_rows": SIDECAR_MAX_ROWS,
        }
    )


def _target_docs(truth: pd.DataFrame) -> set[str]:
    return set(
        truth.loc[
            _truth_bool_series(truth["duplicate_companion_target"]),
            "document_id",
        ].astype(str)
    )


def _document_feature_frame(df: pd.DataFrame, *, exclude_index: set[Any]) -> pd.DataFrame:
    work = df.loc[~df.index.isin(exclude_index)].copy()
    if work.empty:
        return pd.DataFrame(index=pd.Index([], name="document_id"))
    debit = pd.to_numeric(work.get("debit_amount", 0), errors="coerce").fillna(0.0).abs()
    credit = pd.to_numeric(work.get("credit_amount", 0), errors="coerce").fillna(0.0).abs()
    work["_abs_amount"] = debit + credit
    work["_posting_date"] = pd.to_datetime(work.get("posting_date"), errors="coerce")
    work["_has_reference"] = work.get("reference", "").fillna("").astype(str).str.len() > 0
    work["_has_partner"] = (
        work.get("trading_partner", "").fillna("").astype(str).str.len() > 0
    )
    process = work.get("business_process", "").fillna("").astype(str)

    def _first_nonempty(values: pd.Series) -> str:
        cleaned = values.dropna().astype(str)
        cleaned = cleaned[cleaned.str.len() > 0]
        return "" if cleaned.empty else str(cleaned.iat[0])

    grouped = work.groupby("document_id", sort=False).agg(
        row_count=("_abs_amount", "size"),
        max_amount=("_abs_amount", "max"),
        total_amount=("_abs_amount", "sum"),
        posting_date=("_posting_date", "min"),
        reference=("reference", _first_nonempty),
        trading_partner=("trading_partner", _first_nonempty),
        business_process=("business_process", _first_nonempty),
        has_reference=("_has_reference", "max"),
        has_partner=("_has_partner", "max"),
    )
    grouped["is_p2p"] = process.groupby(work["document_id"]).agg(
        lambda values: bool((values == "P2P").any())
    )
    grouped["doc_score"] = (
        grouped["max_amount"].rank(method="first", pct=True)
        + grouped["total_amount"].rank(method="first", pct=True)
        + grouped["has_reference"].astype(float)
        + grouped["has_partner"].astype(float)
        + grouped["is_p2p"].astype(float)
        + grouped["row_count"].between(2, 3).astype(float)
    )
    return grouped.sort_values(
        ["doc_score", "max_amount", "total_amount"],
        ascending=[False, False, False],
    )


def _candidate_frame_from_docs(
    df: pd.DataFrame,
    docs: set[str],
    *,
    max_rows: int = SIDECAR_MAX_ROWS,
) -> pd.DataFrame:
    if not docs:
        return df.iloc[[]].copy()
    subset = df[df["document_id"].astype(str).isin(docs)].copy()
    if subset.empty:
        return subset
    subset["_doc_pos"] = subset.groupby("document_id").cumcount()
    subset = subset[subset["_doc_pos"] < 2].drop(columns=["_doc_pos"])
    return subset.head(max_rows)


def _observable_document_profile_sample(
    df: pd.DataFrame,
    *,
    features: pd.DataFrame,
    max_docs: int,
) -> pd.DataFrame:
    if features.empty:
        return df.iloc[[]].copy()
    keep = features[
        features["is_p2p"]
        & features["has_reference"]
        & features["has_partner"]
        & features["row_count"].between(2, 3)
    ].head(max_docs)
    return _candidate_frame_from_docs(df, set(keep.index), max_rows=SIDECAR_MAX_ROWS)


def _strict_time_shift_profile_sample(
    df: pd.DataFrame,
    *,
    features: pd.DataFrame,
    reference_threshold: int = REFERENCE_HIGH_THRESHOLD,
) -> pd.DataFrame:
    """Audit-observable duplicate-like document-pair guard.

    Selector inputs are GL fields only: partner, process, reference similarity,
    amount proximity, 1-3 day date shift, and 2-3 row document support.
    """
    if features.empty:
        return df.iloc[[]].copy()
    eligible = features[
        features["row_count"].between(2, 3)
        & (features["trading_partner"].astype(str).str.len() > 0)
        & (features["business_process"].astype(str).str.len() > 0)
        & (features["reference"].astype(str).str.len() > 0)
    ].copy()
    docs: set[str] = set()
    for _, group in eligible.groupby(["trading_partner", "business_process"], sort=False):
        if len(group) < 2:
            continue
        ordered = group.sort_values("posting_date", kind="mergesort")
        records = list(
            ordered[["max_amount", "posting_date", "reference"]].itertuples(
                index=True,
                name=None,
            )
        )
        n = len(records)
        for left_pos, (left_doc, left_amount, left_date, left_ref) in enumerate(records):
            for right_doc, right_amount, right_date, right_ref in records[
                left_pos + 1 : min(n, left_pos + 100)
            ]:
                if pd.isna(left_date) or pd.isna(right_date):
                    continue
                day_diff = int((right_date - left_date).days)
                if day_diff > 3:
                    break
                if day_diff < 1:
                    continue
                denominator = max(abs(float(left_amount)), abs(float(right_amount)), 1.0)
                amount_delta = abs(float(left_amount) - float(right_amount)) / denominator
                if amount_delta > 0.02:
                    continue
                if fuzz.ratio(str(left_ref), str(right_ref)) < reference_threshold:
                    continue
                docs.add(str(left_doc))
                docs.add(str(right_doc))
    return _candidate_frame_from_docs(df, docs, max_rows=SIDECAR_MAX_ROWS)


def _evaluate_candidate_docs_only(
    *,
    candidate_id: str,
    candidate_df: pd.DataFrame,
    target_docs: set[str],
    guard_case_grade: bool,
) -> dict[str, Any]:
    candidate_docs = (
        set(candidate_df["document_id"].astype(str)) if not candidate_df.empty else set()
    )
    target_candidate_docs = candidate_docs & target_docs
    return {
        "candidate_id": candidate_id,
        "diagnostic_only": True,
        "measurement_basis": "candidate_document_coverage_pre_pair_artifact",
        "candidate_docs": len(candidate_docs),
        "target_candidate_docs": len(target_candidate_docs),
        "non_target_candidate_docs": len(candidate_docs - target_docs),
        "target_candidate_doc_recall": len(target_candidate_docs) / len(target_docs)
        if target_docs
        else None,
        "guard_case_grade_by_construction": guard_case_grade,
        "estimated_review_burden": {
            "candidate_docs": len(candidate_docs),
            "non_target_candidate_docs": len(candidate_docs - target_docs),
        },
        "non_target_to_target_candidate_ratio": round(
            len(candidate_docs - target_docs) / max(len(target_candidate_docs), 1),
            6,
        ),
    }


def _pair_feature_rates(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    if not pairs:
        return {
            "weak_pair_ratio": 0.0,
            "case_grade_pair_ratio": 0.0,
            "same_partner_ratio": 0.0,
            "reference_similarity_quantiles": {},
            "amount_similarity_quantiles": {},
            "date_distance_distribution": {},
        }
    weak = sum(_tier(pair) == "weak" for pair in pairs)
    case_grade = sum(_tier(pair) in {"strong", "moderate"} for pair in pairs)
    same_partner = sum(pair.get("features", {}).get("same_partner") is True for pair in pairs)
    return {
        "weak_pair_ratio": round(weak / len(pairs), 6),
        "case_grade_pair_ratio": round(case_grade / len(pairs), 6),
        "same_partner_ratio": round(same_partner / len(pairs), 6),
        "reference_similarity_quantiles": _quantiles(
            pair.get("features", {}).get("reference_similarity") for pair in pairs
        ),
        "amount_similarity_quantiles": _quantiles(
            pair.get("features", {}).get("amount_similarity") for pair in pairs
        ),
        "date_distance_distribution": _dist(
            pair.get("features", {}).get("date_distance_days") for pair in pairs
        ),
    }


def _evaluate_artifact(
    *,
    candidate_id: str,
    artifact: dict[str, Any],
    candidate_df: pd.DataFrame | None,
    target_docs: set[str],
) -> dict[str, Any]:
    pairs = list(artifact.get("top_pairs", []))
    target_pairs = [pair for pair in pairs if _pair_docs(pair) & target_docs]
    target_case_grade_pairs = [
        pair for pair in target_pairs if _tier(pair) in {"strong", "moderate"}
    ]
    pair_docs = _doc_set_from_pairs(pairs)
    target_pair_docs = _doc_set_from_pairs(target_pairs) & target_docs
    target_case_grade_docs = _doc_set_from_pairs(target_case_grade_pairs) & target_docs
    candidate_docs = (
        set(candidate_df["document_id"].astype(str))
        if candidate_df is not None and not candidate_df.empty
        else set()
    )
    return {
        "candidate_id": candidate_id,
        "diagnostic_only": True,
        "candidate_docs": len(candidate_docs),
        "target_candidate_docs": len(candidate_docs & target_docs),
        "non_target_candidate_docs": len(candidate_docs - target_docs),
        "generated_pair_count": len(pairs),
        "pair_document_count": len(pair_docs),
        "target_pair_docs": len(target_pair_docs),
        "target_case_grade_pair_docs": len(target_case_grade_docs),
        "target_pair_doc_recall": len(target_pair_docs) / len(target_docs)
        if target_docs
        else None,
        "target_case_grade_doc_recall": len(target_case_grade_docs) / len(target_docs)
        if target_docs
        else None,
        "top_pair_non_target_document_count": len(pair_docs - target_docs),
        "non_target_to_target_candidate_ratio": round(
            len(candidate_docs - target_docs) / max(len(candidate_docs & target_docs), 1),
            6,
        ),
        "rule_id_distribution": _dist(pair.get("rule_id") for pair in pairs),
        "evidence_tier_distribution": _dist(_tier(pair) for pair in pairs),
        "target_evidence_tier_distribution": _dist(_tier(pair) for pair in target_pairs),
        **_pair_feature_rates(pairs),
        "target_pair_feature_rates": _pair_feature_rates(target_pairs),
        "artifact_coverage": {
            key: value
            for key, value in artifact.get("coverage", {}).items()
            if key != "top_pairs"
        },
    }


def _evaluate_candidate_frame(
    *,
    candidate_id: str,
    df: pd.DataFrame,
    candidate_df: pd.DataFrame,
    settings: AuditSettings,
    target_docs: set[str],
) -> dict[str, Any]:
    artifact = build_duplicate_pair_artifact(candidate_df, settings).to_dict()
    return _evaluate_artifact(
        candidate_id=candidate_id,
        artifact=artifact,
        candidate_df=candidate_df,
        target_docs=target_docs,
    )


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


def _raw_identifier_leak_check(
    payload: dict[str, Any],
    *,
    forbidden_values: set[str],
) -> dict[str, int]:
    text = json.dumps(payload, ensure_ascii=False)
    keys = {key.lower() for key in _walk_keys(payload)}
    return {
        "doc_like_token_count": len(re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-", text)),
        "forbidden_identifier_key_count": sum(
            1 for key in keys if key in FORBIDDEN_IDENTIFIER_KEYS
        ),
        "forbidden_identifier_value_count": sum(
            1 for value in forbidden_values if value and value in text
        ),
        "phase2_case_id_like_token_count": text.lower().count("phase2_case_"),
    }


def build_payload() -> dict[str, Any]:
    started = time.perf_counter()
    df, truth, pair_truth = _load_inputs()
    target_docs = _target_docs(truth)
    get_settings()

    current_estimate = _load_current_duplicate_companion_estimate()
    selected_rows = 50_000
    row_score_docs: set[str] = set()
    main_candidate_index: set[Any] = set()

    features = _document_feature_frame(df, exclude_index=main_candidate_index)
    candidate_frames = {
        "observable_profile_top_10000": _observable_document_profile_sample(
            df,
            features=features,
            max_docs=10_000,
        ),
        "observable_profile_top_5000": _observable_document_profile_sample(
            df,
            features=features,
            max_docs=5_000,
        ),
        "observable_profile_top_2000": _observable_document_profile_sample(
            df,
            features=features,
            max_docs=2_000,
        ),
        "strict_time_shift_reference_guard": _strict_time_shift_profile_sample(
            df,
            features=features,
        ),
    }

    candidates = {
        "current_duplicate_path": {
            "candidate_id": "current_duplicate_path",
            "diagnostic_only": True,
            "measurement_basis": current_estimate["measurement_basis"],
            "status": current_estimate["status"],
            "target_pair_docs": current_estimate["matched_docs"],
            "target_case_grade_pair_docs": current_estimate["matched_docs"],
            "target_pair_doc_recall": current_estimate["recall"],
            "target_case_grade_doc_recall": current_estimate["recall"],
            "portfolio_620_matched_docs": current_estimate["portfolio_620_matched_docs"],
            "note": (
                "Read from v3.2d responsibility artifact because full DuplicateDetector "
                "rerun on the regenerated CSV exceeds the focused diagnostic budget."
            ),
        }
    }
    candidates.update(
        {
            name: _evaluate_candidate_docs_only(
                candidate_id=name,
                candidate_df=frame,
                target_docs=target_docs,
                guard_case_grade=name == "strict_time_shift_reference_guard",
            )
            for name, frame in candidate_frames.items()
        }
    )

    best_guard = max(
        (
            item
            for key, item in candidates.items()
            if key != "current_duplicate_path"
        ),
        key=lambda item: (
            int(item.get("guard_case_grade_by_construction") is True),
            item["target_candidate_docs"],
            -item["non_target_candidate_docs"],
        ),
    )

    payload: dict[str, Any] = {
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "dataset": DATASET_NAME,
        "responsibility_map_version": "v3.2d",
        "diagnostic_only": True,
        "duplicate_companion_denominator": len(target_docs),
        "duplicate_primary_denominator": int(
            _truth_bool_series(truth["duplicate_primary_target"]).sum()
        ),
        "production_first_review_ranking_changed": False,
        "row_score_threshold_changed": False,
        "row_scores_changed": False,
        "top_pairs_cap_changed": False,
        "weak_pair_gate_changed": False,
        "phase1_ranking_changed": False,
        "phase2_fusion_changed": False,
        "truth_metadata_used_as_selector": False,
        "truth_label_used_only_for_aggregate_evaluation": True,
        "selector_inputs": [
            "document row_count",
            "business_process",
            "trading_partner",
            "reference similarity",
            "posting_date distance",
            "amount proximity",
        ],
        "baseline_attrition": {
            "companion_docs": len(target_docs),
            "row_score_companion_docs": len(row_score_docs),
            "no_row_score_companion_docs": len(target_docs - row_score_docs),
            "main_candidate_subset_selected_rows": selected_rows,
            "main_candidate_subset_min_score": None,
            "row_score_coverage_status": "not_rerun_in_this_bounded_sidecar_diagnostic",
        },
        "candidate_results": candidates,
        "experiment_summary": {
            "current_target_pair_docs": candidates["current_duplicate_path"][
                "target_pair_docs"
            ],
            "current_target_case_grade_pair_docs": candidates["current_duplicate_path"][
                "target_case_grade_pair_docs"
            ],
            "best_guard_candidate": best_guard["candidate_id"],
            "best_guard_target_candidate_docs": best_guard["target_candidate_docs"],
            "best_guard_target_candidate_doc_recall": best_guard[
                "target_candidate_doc_recall"
            ],
            "best_guard_candidate_docs": best_guard["candidate_docs"],
            "best_guard_non_target_candidate_docs": best_guard[
                "non_target_candidate_docs"
            ],
        },
        "decision": {
            "production_sidecar_adoption": False,
            "product_first_review_ordering_change": False,
            "main_candidate_subset_change": False,
            "weak_pair_promotion": False,
            "read": (
                "Observable duplicate-like guards can reduce burden versus the broad "
                "profile sample, but v3.2d duplicate remains a companion evidence lane. "
                "Do not adopt as product default until non-target burden and case-grade "
                "coverage are stable on regenerated DataSynth."
            ),
        },
        "raw_identifier_leak_check": {},
        "elapsed_seconds": None,
    }
    payload["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    payload["raw_identifier_leak_check"] = _raw_identifier_leak_check(
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
                "denominator": payload["duplicate_companion_denominator"],
                "baseline": payload["baseline_attrition"],
                "summary": payload["experiment_summary"],
                "raw_identifier_leak_check": payload["raw_identifier_leak_check"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
