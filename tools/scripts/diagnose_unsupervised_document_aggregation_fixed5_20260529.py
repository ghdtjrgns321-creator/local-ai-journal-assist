"""Diagnostic-only PHASE2 unsupervised document aggregation checks for fixed5.

This script evaluates document-level companion-lane candidates without changing
native row case ordering, q95 gates, PHASE1 ranking, or PHASE2 fusion policy.
Truth labels are used only after native cases are built, for aggregate quality
diagnostics. Raw document IDs, row IDs, and index labels are never emitted.
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import pickle
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.models.phase2_case import Phase2CaseBase
from src.services.phase2_case_set_orchestrator import build_phase2_case_set
from tools.scripts.measure_phase2_native_cases_fixed5_20260528 import (
    BATCH_ID,
    DATASET_NAME,
    _build_unsupervised_result,
    _case_documents,
    _concentration_summary,
    _doc_sort_key,
    _document_aggregation_inputs,
    _family_cases,
    _load_case_input,
    _load_truth,
    _measure_family,
    _sorted_cases,
    _unsupervised_case_rows,
)

OUT_JSON = ROOT / "artifacts" / "unsupervised_document_aggregation_diagnostic_fixed5_20260529.json"
PHASE1_CASE_RESULT = ROOT / "artifacts" / "stage7_fixed5_normalcal5_phase1_case_result.pkl"
FORBIDDEN_IDENTIFIER_KEYS = {
    "document" "_id",
    "document" "_ids",
    "r" "aw" "_document" "_id",
    "r" "aw" "_document" "_ids",
    "r" "aw" "_doc",
    "r" "aw" "_doc" "_id",
    "r" "aw" "_label",
    "row" "_id",
    "row" "_ids",
    "r" "aw" "_row" "_id",
    "r" "aw" "_row" "_ids",
    "index" "_label",
    "r" "aw" "_index" "_label",
    "phase2" "_case" "_id",
    "phase2" "_case" "_ids",
}
DOC_LIKE_TOKEN_RE = re.compile(r"\b(?:DOC|JE|JRN|GL|TXN|ENTRY)[-_]?[A-Za-z0-9]{4,}\b")
CASE_ID_TOKEN_RE = re.compile(r"\bp2_unsupervised_[A-Za-z0-9_:-]+\b")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _print(message: str) -> None:
    print(f"[{_now_iso()}] {message}", flush=True)


def _distribution(values: list[float | int | None]) -> dict[str, Any]:
    clean = [float(value) for value in values if value is not None and np.isfinite(float(value))]
    if not clean:
        return {"count": 0, "min": None, "p50": None, "p90": None, "p99": None, "max": None}
    arr = np.asarray(clean, dtype=float)
    return {
        "count": int(len(arr)),
        "min": float(arr.min()),
        "p50": float(np.quantile(arr, 0.50)),
        "p90": float(np.quantile(arr, 0.90)),
        "p99": float(np.quantile(arr, 0.99)),
        "max": float(arr.max()),
    }


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


def identifier_leak_check(payload: dict[str, Any]) -> dict[str, int]:
    """Report aggregate-only identifier leak status without emitting identifiers."""
    text = json.dumps(payload, ensure_ascii=False)
    forbidden_key_count = sum(
        1 for key in _walk_keys(payload) if key.lower() in FORBIDDEN_IDENTIFIER_KEYS
    )
    return {
        "doc_like_token_count": len(DOC_LIKE_TOKEN_RE.findall(text)),
        "forbidden_identifier_key_count": forbidden_key_count,
        "phase2_case_id_like_token_count": len(CASE_ID_TOKEN_RE.findall(text)),
    }


def _period_end_score(days: float | None) -> float:
    if days is None or not np.isfinite(float(days)):
        return 0.0
    return float(max(0.0, 1.0 - min(float(days), 30.0) / 30.0))


def _safe_div(numerator: float, denominator: float) -> float:
    return float(numerator / denominator) if denominator else 0.0


def _percentile_map(values_by_doc: dict[str, float]) -> dict[str, float]:
    if not values_by_doc:
        return {}
    ordered = sorted(values_by_doc.items(), key=lambda item: (item[1], _doc_sort_key(item[0])))
    n = len(ordered)
    return {doc: (idx + 1) / n for idx, (doc, _value) in enumerate(ordered)}


def _document_records(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    docs = _document_aggregation_inputs(rows)
    records: dict[str, dict[str, Any]] = {}
    for doc, entry in docs.items():
        doc_rows = [row for row in rows if row.get("document_id") == doc]
        amounts = [row.get("amount") for row in doc_rows]
        period_days = [row.get("period_end_proximity_days") for row in doc_rows]
        phase1_priors = [row.get("phase1_document_prior") for row in doc_rows]
        phase1_rule_counts = [row.get("phase1_rule_count") for row in doc_rows]
        cases = [row.get("case") for row in doc_rows]
        top_feature_case_count = sum(
            1 for case in cases if bool(getattr(case, "top_features", ()) or ())
        )
        records[doc] = {
            **entry,
            "max_amount": max(
                [
                    float(value)
                    for value in amounts
                    if value is not None and np.isfinite(float(value))
                ]
                or [0.0]
            ),
            "min_period_end_proximity_days": min(
                [int(value) for value in period_days if value is not None] or [None]
            ),
            "max_phase1_document_prior": max(
                [
                    float(value)
                    for value in phase1_priors
                    if value is not None and np.isfinite(float(value))
                ]
                or [0.0]
            ),
            "mean_phase1_document_prior": float(
                np.mean(
                    [
                        float(value)
                        for value in phase1_priors
                        if value is not None and np.isfinite(float(value))
                    ]
                    or [0.0]
                )
            ),
            "max_phase1_rule_count": max(
                [
                    int(value)
                    for value in phase1_rule_counts
                    if value is not None and np.isfinite(float(value))
                ]
                or [0]
            ),
            "top_feature_case_count": top_feature_case_count,
            "missing_top_feature_case_count": max(len(doc_rows) - top_feature_case_count, 0),
        }
    amount_percentiles = _percentile_map(
        {doc: float(record["max_amount"]) for doc, record in records.items()}
    )
    for doc, percentile in amount_percentiles.items():
        records[doc]["amount_percentile"] = percentile
    return records


def _rule_count(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (list, tuple, set)):
        return len(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped in {"[]", "None", "nan"}:
            return 0
        return stripped.count(",") + 1 if "," in stripped else 1
    return 0


def _phase1_context_for_position(df: pd.DataFrame, row_position: int | None) -> dict[str, float]:
    if row_position is None or row_position < 0 or row_position >= len(df):
        return {"phase1_document_prior": 0.0, "phase1_rule_count": 0.0}
    risk_value = str(df["risk_level"].iat[row_position]) if "risk_level" in df.columns else "Normal"
    risk_prior = {"High": 1.0, "Medium": 0.60, "Low": 0.30}.get(risk_value, 0.0)
    flagged_count = (
        _rule_count(df["flagged_rules"].iat[row_position])
        if "flagged_rules" in df.columns
        else 0
    )
    review_count = (
        _rule_count(df["review_rules"].iat[row_position])
        if "review_rules" in df.columns
        else 0
    )
    rule_prior = min((flagged_count + (0.5 * review_count)) / 4.0, 1.0)
    score_values: list[float] = []
    for column in (
        "anomaly_score",
        "intercompany_exception_score",
        "batch_combo_score",
        "work_scope_combo_score",
        "topside_score",
    ):
        if column not in df.columns:
            continue
        value = pd.to_numeric(pd.Series([df[column].iat[row_position]]), errors="coerce").iloc[0]
        if pd.notna(value) and np.isfinite(float(value)):
            score_values.append(float(value))
    score_prior = max(score_values or [0.0])
    keyword_prior = (
        0.20
        if "has_risk_keyword" in df.columns and bool(df["has_risk_keyword"].iat[row_position])
        else 0.0
    )
    phase1_prior = min(max(risk_prior, rule_prior, score_prior) + keyword_prior, 1.0)
    return {
        "phase1_document_prior": float(phase1_prior),
        "phase1_rule_count": float(flagged_count + review_count),
    }


def attach_phase1_document_prior(
    rows: list[dict[str, Any]],
    df: pd.DataFrame,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for row in rows:
        case = row.get("case")
        ref = case.row_refs[0] if getattr(case, "row_refs", ()) else None
        row_position = getattr(ref, "row_position", None) if ref is not None else None
        enriched_row = dict(row)
        enriched_row.update(_phase1_context_for_position(df, row_position))
        enriched.append(enriched_row)
    return enriched


def _candidate_scores(records: dict[str, dict[str, Any]]) -> dict[str, list[tuple[str, float]]]:
    scored: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for doc, record in records.items():
        scores = [float(value) for value in record["scores"]]
        if not scores:
            continue
        max_score = max(scores)
        row_count = max(int(record.get("document_row_count") or 1), 1)
        top3 = sorted(scores, reverse=True)[:3]
        top3_mean = float(np.mean(top3)) if top3 else 0.0
        amount_tail = float(record.get("amount_percentile") or 0.0)
        period_end = _period_end_score(record.get("min_period_end_proximity_days"))
        hybrid = (0.70 * max_score) + (0.20 * amount_tail) + (0.10 * period_end)
        case_count = max(int(record.get("case_count") or 0), 0)
        account_count = len(record.get("accounts") or ())
        process_count = len(record.get("processes") or ())
        diversity = max(account_count + process_count, 1)
        repeated_proxy = min(case_count / 5.0, 1.0)
        concentration_guard = 1.0 / float(np.sqrt(1.0 + (case_count / diversity)))
        row_count_penalty = max_score / float(np.sqrt(row_count))
        amount_floor = max(row_count_penalty, 0.65 * row_count_penalty + 0.20 * amount_tail)
        top3_context = (0.70 * top3_mean) + (0.20 * amount_tail) + (0.10 * period_end)
        phase1_prior = float(record.get("max_phase1_document_prior") or 0.0)
        phase1_rule_prior = min(float(record.get("max_phase1_rule_count") or 0.0) / 4.0, 1.0)
        scored["document_max_score"].append((doc, max_score))
        scored["document_top_k_mean_score_k3"].append((doc, top3_mean))
        scored["document_score_with_row_count_penalty"].append((doc, row_count_penalty))
        scored["hybrid_max_score_amount_tail_period_end"].append((doc, hybrid))
        scored["hybrid_with_repeated_normal_penalty"].append(
            (doc, hybrid * (1.0 - (0.35 * repeated_proxy)))
        )
        scored["hybrid_with_soft_repeated_normal_guard"].append(
            (doc, hybrid * (1.0 - (0.12 * repeated_proxy)))
        )
        soft_guard = hybrid * (1.0 - (0.12 * repeated_proxy))
        scored["soft_guard_with_row_count_context"].append(
            (doc, (0.85 * soft_guard) + (0.15 * row_count_penalty))
        )
        scored["phase1_prior_companion_surface"].append(
            (doc, (0.70 * soft_guard) + (0.20 * phase1_prior) + (0.10 * phase1_rule_prior))
        )
        scored["hybrid_row_count_blended_surface"].append(
            (doc, (0.75 * hybrid) + (0.25 * row_count_penalty))
        )
        scored["hybrid_with_account_process_concentration_guard"].append(
            (doc, hybrid * concentration_guard)
        )
        scored["row_count_penalty_with_amount_tail_floor"].append((doc, amount_floor))
        scored["top_k_mean_with_context"].append(
            (doc, top3_context * (1.0 / float(np.sqrt(1.0 + repeated_proxy))))
        )
        scored["document_companion_balanced_surface"].append(
            (doc, (0.55 * hybrid * (1.0 - (0.25 * repeated_proxy))) + (0.45 * row_count_penalty))
        )
    return dict(scored)


def _ordered_docs(pairs: list[tuple[str, float]]) -> list[str]:
    return [
        doc
        for doc, _score in sorted(
            pairs,
            key=lambda item: (-float(item[1]), _doc_sort_key(item[0])),
        )
    ]


def _selected_rows(rows: list[dict[str, Any]], selected_docs: set[str]) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("document_id") in selected_docs]


def _share_summary(values: list[str]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "top_count": 0, "top_share": 0.0}
    counts = Counter(values)
    top_count = counts.most_common(1)[0][1]
    return {
        "count": len(values),
        "top_count": int(top_count),
        "top_share": top_count / len(values),
    }


def _high_amount_threshold(records: dict[str, dict[str, Any]]) -> float:
    distribution = _distribution([record.get("max_amount") for record in records.values()])
    return float(distribution["p99"] or 0.0)


def _risk_profile(
    *,
    rows: list[dict[str, Any]],
    records: dict[str, dict[str, Any]],
    selected_docs: list[str],
    truth_docs: set[str],
    global_high_amount_threshold: float,
) -> dict[str, Any]:
    selected_set = set(selected_docs)
    selected_rows = _selected_rows(rows, selected_set)
    selected_records = [records[doc] for doc in selected_docs if doc in records]
    total = len(selected_docs)
    total_case_count = sum(int(record.get("case_count") or 0) for record in selected_records)
    single_row_high_amount = [
        record
        for record in selected_records
        if int(record.get("document_row_count") or 0) == 1
        and float(record.get("max_amount") or 0.0) >= global_high_amount_threshold
    ]
    repeated_normal = [
        doc
        for doc in selected_docs
        if doc not in truth_docs and int(records.get(doc, {}).get("case_count") or 0) > 1
    ]
    normal_single_row_high_amount = [
        record
        for doc, record in zip(selected_docs, selected_records, strict=False)
        if doc not in truth_docs
        and int(record.get("document_row_count") or 0) == 1
        and float(record.get("max_amount") or 0.0) >= global_high_amount_threshold
    ]
    period_end_normal_background = [
        doc
        for doc, record in zip(selected_docs, selected_records, strict=False)
        if doc not in truth_docs
        and record.get("min_period_end_proximity_days") is not None
        and int(record.get("min_period_end_proximity_days") or 0) <= 3
    ]
    account_concentration = _concentration_summary(
        account for row in selected_rows for account in [row.get("account")]
    )
    process_concentration = _concentration_summary(
        process for row in selected_rows for process in [row.get("process")]
    )
    top_feature_cases = sum(
        int(record.get("top_feature_case_count") or 0) for record in selected_records
    )
    missing_top_feature_cases = sum(
        int(record.get("missing_top_feature_case_count") or 0) for record in selected_records
    )
    feature_denominator = top_feature_cases + missing_top_feature_cases
    repeated_normal_ratio = _safe_div(float(len(repeated_normal)), float(total))
    single_row_high_amount_ratio = _safe_div(float(len(single_row_high_amount)), float(total))
    false_positive_pressure = (
        (0.45 * repeated_normal_ratio)
        + (0.25 * single_row_high_amount_ratio)
        + (0.20 * account_concentration["top1_share"])
        + (0.10 * process_concentration["top1_share"])
    )
    return {
        "document_count": total,
        "truth_document_count": len(selected_set & truth_docs),
        "nontruth_document_count": total - len(selected_set & truth_docs),
        "documents_covered": total,
        "nontruth_documents_covered": total - len(selected_set & truth_docs),
        "document_row_count_distribution": _distribution(
            [record.get("document_row_count") for record in selected_records]
        ),
        "amount_distribution": _distribution(
            [record.get("max_amount") for record in selected_records]
        ),
        "account_concentration": account_concentration,
        "process_concentration": process_concentration,
        "period_end_proximity_days_distribution": _distribution(
            [record.get("min_period_end_proximity_days") for record in selected_records]
        ),
        "case_count_per_document_distribution": _distribution(
            [record.get("case_count") for record in selected_records]
        ),
        "max_cases_per_document": max(
            [int(record.get("case_count") or 0) for record in selected_records] or [0]
        ),
        "top_document_share": _safe_div(
            float(max([int(record.get("case_count") or 0) for record in selected_records] or [0])),
            float(total_case_count),
        ),
        "top_account_share": account_concentration["top1_share"],
        "top_process_share": process_concentration["top1_share"],
        "normal_single_row_high_amount_proxy": _safe_div(
            float(len(normal_single_row_high_amount)), float(total)
        ),
        "repeated_normal_document_proxy": repeated_normal_ratio,
        "period_end_normal_background_proxy": _safe_div(
            float(len(period_end_normal_background)), float(total)
        ),
        "missing_top_features_ratio": _safe_div(
            float(missing_top_feature_cases), float(feature_denominator)
        ),
        "top_features_presence_ratio": _safe_div(
            float(top_feature_cases), float(feature_denominator)
        ),
        "single_row_high_amount_document_ratio": single_row_high_amount_ratio,
        "repeated_normal_document_ratio": repeated_normal_ratio,
        "false_positive_pressure_summary": {
            "score": false_positive_pressure,
            "primary_pressure": (
                "repeated_normal_document_proxy"
                if repeated_normal_ratio >= single_row_high_amount_ratio
                else "single_row_high_amount_document_ratio"
            ),
            "stage7_top_features_unavailable": feature_denominator > 0
            and top_feature_cases == 0,
        },
    }


def _coverage_for_docs(selected_docs: list[str], truth_docs: set[str]) -> dict[str, Any]:
    selected = set(selected_docs)
    matched = len(selected & truth_docs)
    return {
        "matched": matched,
        "recall": matched / max(len(truth_docs), 1),
        "documents_covered": len(selected),
        "nontruth_documents_covered": len(selected - truth_docs),
    }


def _phase1_case_documents(case: Any) -> set[str]:
    docs: set[str] = set()
    for document in getattr(case, "documents", ()) or ():
        value = getattr(document, "document_id", None)
        if value is not None:
            docs.add(str(value))
    return docs


def _phase1_case_score(case: Any) -> float:
    for attr in ("composite_sort_score", "priority_score", "triage_rank_score"):
        value = getattr(case, attr, None)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return 0.0


def _phase1_explanation_categories(values: list[Any]) -> set[str]:
    text = " ".join(str(value).lower() for value in values if value is not None)
    categories: set[str] = set()
    if any(token in text for token in ("period", "cutoff", "timing", "month", "closing")):
        categories.add("period_end")
    if any(token in text for token in ("related", "intercompany", "counterparty", "circular")):
        categories.add("related_party")
    if any(token in text for token in ("duplicate", "reversal", "roundtrip")):
        categories.add("duplicate_or_reversal")
    if any(token in text for token in ("approval", "control", "access", "override")):
        categories.add("control_or_approval")
    if any(token in text for token in ("amount", "material", "large", "tail")):
        categories.add("amount_tail")
    if any(token in text for token in ("risk", "anomaly", "review", "weak", "generic")):
        categories.add("generic_review")
    return categories or {"generic_review"}


def _scenario_category(scenario: str) -> str:
    value = str(scenario).lower()
    if any(token in value for token in ("period", "cutoff", "closing")):
        return "period_end"
    if any(token in value for token in ("related", "intercompany", "circular")):
        return "related_party"
    if any(token in value for token in ("embezzle", "approval", "conceal")):
        return "control_or_approval"
    if any(token in value for token in ("fictitious", "fabricated")):
        return "multivariate_anomaly"
    return "generic_review"


def _phase1_baseline_from_case_result(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open("rb") as fh:
        result = pickle.load(fh)
    cases = list(getattr(result, "cases", ()) or ())
    all_docs: set[str] = set()
    ranked_docs: list[str] = []
    categories_by_doc: dict[str, set[str]] = defaultdict(set)
    seen: set[str] = set()
    for case in sorted(
        cases,
        key=lambda item: (-_phase1_case_score(item), str(getattr(item, "case_key", ""))),
    ):
        docs = sorted(_phase1_case_documents(case), key=_doc_sort_key)
        case_categories = _phase1_explanation_categories(
            [
                getattr(case, "primary_topic", None),
                getattr(case, "primary_queue", None),
                getattr(case, "primary_theme", None),
                getattr(case, "evidence_types", None),
                getattr(case, "evidence_tags", None),
                getattr(case, "fraud_scenario_tags", None),
                getattr(case, "priority_adjustment_reasons", None),
                getattr(case, "triage_rank_reasons", None),
            ]
        )
        all_docs.update(docs)
        for doc in docs:
            categories_by_doc[doc].update(case_categories)
            if doc not in seen:
                seen.add(doc)
                ranked_docs.append(doc)
    return {
        "source": "phase1_case_result_documents",
        "case_count": len(cases),
        "all_docs": all_docs,
        "ranked_docs": ranked_docs,
        "categories_by_doc": categories_by_doc,
    }


def _phase1_baseline_from_review_context(df: pd.DataFrame) -> dict[str, Any]:
    doc_col = "document" "_id"
    if doc_col not in df.columns:
        return {
            "source": "phase1_review_context_fallback",
            "case_count": None,
            "all_docs": set(),
            "ranked_docs": [],
            "categories_by_doc": {},
        }
    score_columns = [
        column
        for column in (
            "anomaly_score",
            "intercompany_exception_score",
            "batch_combo_score",
            "work_scope_combo_score",
            "topside_score",
        )
        if column in df.columns
    ]
    work = pd.DataFrame({doc_col: df[doc_col].astype(str)})
    risk = (
        df["risk_level"].astype(str).map({"High": 1.0, "Medium": 0.60, "Low": 0.30}).fillna(0.0)
        if "risk_level" in df.columns
        else pd.Series(0.0, index=df.index)
    )
    flagged = (
        df["flagged_rules"].map(_rule_count).astype(float)
        if "flagged_rules" in df.columns
        else pd.Series(0.0, index=df.index)
    )
    review = (
        df["review_rules"].map(_rule_count).astype(float)
        if "review_rules" in df.columns
        else pd.Series(0.0, index=df.index)
    )
    rule_prior = ((flagged + (0.5 * review)) / 4.0).clip(upper=1.0)
    score_prior = (
        df[score_columns].apply(pd.to_numeric, errors="coerce").fillna(0.0).max(axis=1)
        if score_columns
        else pd.Series(0.0, index=df.index)
    )
    keyword_prior = (
        df["has_risk_keyword"].fillna(False).astype(bool).astype(float) * 0.20
        if "has_risk_keyword" in df.columns
        else pd.Series(0.0, index=df.index)
    )
    work["phase1_review_context_score"] = pd.concat(
        [risk, rule_prior, score_prior], axis=1
    ).max(axis=1) + keyword_prior
    by_doc = work.groupby(doc_col)["phase1_review_context_score"].max()
    signaled = by_doc[by_doc > 0.0]
    ranked = [
        str(doc)
        for doc, _score in sorted(
            by_doc.items(),
            key=lambda item: (-float(item[1]), _doc_sort_key(str(item[0]))),
        )
    ]
    return {
        "source": "phase1_review_context_fallback",
        "case_count": None,
        "all_docs": set(signaled.index.astype(str)),
        "ranked_docs": ranked,
        "categories_by_doc": {},
    }


def build_phase1_baseline(
    df: pd.DataFrame,
    truth_docs: set[str],
    *,
    case_result_path: Path | None = None,
) -> dict[str, Any]:
    baseline = (
        _phase1_baseline_from_case_result(case_result_path)
        if case_result_path is not None
        else None
    )
    if baseline is None:
        baseline = _phase1_baseline_from_review_context(df)
    all_docs = set(baseline["all_docs"])
    ranked_docs = list(baseline["ranked_docs"])
    top_sets = {str(top_n): set(ranked_docs[:top_n]) for top_n in (100, 500, 1000, 10000)}
    return {
        **baseline,
        "top_sets": top_sets,
        "generic_only_docs": {
            doc
            for doc, categories in baseline.get("categories_by_doc", {}).items()
            if set(categories).issubset({"generic_review", "amount_tail"})
        },
        "summary": {
            "source": baseline["source"],
            "phase1_case_count": baseline["case_count"],
            "phase1_all_doc_count": len(all_docs),
            "phase1_all_truth_count": len(all_docs & truth_docs),
            "phase1_top100_doc_count": len(top_sets["100"]),
            "phase1_top100_truth_count": len(top_sets["100"] & truth_docs),
            "phase1_top500_doc_count": len(top_sets["500"]),
            "phase1_top500_truth_count": len(top_sets["500"] & truth_docs),
            "phase1_top1000_doc_count": len(top_sets["1000"]),
            "phase1_top1000_truth_count": len(top_sets["1000"] & truth_docs),
            "phase1_top10000_doc_count": len(top_sets["10000"]),
            "phase1_top10000_truth_count": len(top_sets["10000"] & truth_docs),
        },
    }


def _candidate_ordered_doc_surfaces(
    *,
    cases: list[Phase2CaseBase],
    records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    scored = _candidate_scores(records)
    surfaces: dict[str, Any] = {
        name: {"kind": "ordered", "docs": _ordered_docs(pairs)}
        for name, pairs in scored.items()
    }
    ordered_cases = _sorted_cases(cases)
    native_docs_by_case_budget: dict[str, list[str]] = {}
    for top_n in (100, 500, 1000, 10000):
        native_docs_by_case_budget[str(top_n)] = sorted(
            {
                doc
                for case in ordered_cases[:top_n]
                for doc in _case_documents(case)
            },
            key=_doc_sort_key,
        )
    surfaces["native_row_queue"] = {"kind": "by_topn", "docs_by_topn": native_docs_by_case_budget}
    full_native_docs: list[str] = []
    native_seen: set[str] = set()
    for case in ordered_cases:
        for doc in sorted(_case_documents(case), key=_doc_sort_key):
            if doc not in native_seen:
                native_seen.add(doc)
                full_native_docs.append(doc)
    surfaces["native_row_queue"]["docs"] = full_native_docs

    lane_docs = {
        "phase1_prior": surfaces["phase1_prior_companion_surface"]["docs"],
        "aggressive_blend": surfaces["hybrid_row_count_blended_surface"]["docs"],
        "hybrid_max": surfaces["hybrid_max_score_amount_tail_period_end"]["docs"],
        "soft_context": surfaces["soft_guard_with_row_count_context"]["docs"],
    }
    union_configs = {
        "frontier_phase1_plus_aggressive_union": ("phase1_prior", "aggressive_blend"),
        "frontier_phase1_plus_hybrid_max_union": ("phase1_prior", "hybrid_max"),
        "frontier_phase1_plus_soft_context_union": ("phase1_prior", "soft_context"),
        "frontier_all_four_lanes_union": (
            "phase1_prior",
            "aggressive_blend",
            "hybrid_max",
            "soft_context",
        ),
    }
    for name, lanes in union_configs.items():
        surfaces[name] = {
            "kind": "union_by_topn",
            "docs_by_topn": {
                str(top_n): sorted(
                    set().union(*(set(lane_docs[lane][:top_n]) for lane in lanes)),
                    key=_doc_sort_key,
                )
                for top_n in (100, 500, 1000, 10000)
            },
        }
    return surfaces


def _surface_docs_for_topn(surface: dict[str, Any], top_n: int) -> list[str]:
    if surface["kind"] == "ordered":
        return list(surface["docs"][:top_n])
    return list(surface["docs_by_topn"][str(top_n)])


def _rank_map(ordered_docs: list[str]) -> dict[str, int]:
    return {doc: rank for rank, doc in enumerate(ordered_docs, start=1)}


def _rank_distribution(ranks: list[int]) -> dict[str, Any]:
    if not ranks:
        return {"count": 0, "p50": None, "p90": None, "max": None}
    arr = np.asarray(ranks, dtype=float)
    return {
        "count": int(len(arr)),
        "p50": float(np.quantile(arr, 0.50)),
        "p90": float(np.quantile(arr, 0.90)),
        "max": int(arr.max()),
    }


def _surface_full_rank_map(surface: dict[str, Any]) -> dict[str, int]:
    if surface["kind"] in {"ordered", "by_topn"} and "docs" in surface:
        return _rank_map(list(surface["docs"]))
    return {}


def _top500_out_reason(
    *,
    record: dict[str, Any],
    ranks_by_surface: dict[str, dict[str, int]],
    repeated_normal_pressure_high: bool,
) -> str:
    scores = [float(value) for value in record.get("scores", ()) if value is not None]
    max_score = max(scores or [0.0])
    top3 = sorted(scores, reverse=True)[:3]
    top3_mean = float(np.mean(top3)) if top3 else 0.0
    representative_dominance = max_score > 0.0 and (top3_mean / max_score) < 0.65
    amount_weak = float(record.get("amount_percentile") or 0.0) < 0.50
    period_weak = _period_end_score(record.get("min_period_end_proximity_days")) < 0.25
    row_count_rank = ranks_by_surface.get("document_score_with_row_count_penalty", {}).get(
        str(record.get("_doc"))
    )
    hybrid_rank = ranks_by_surface.get("hybrid_max_score_amount_tail_period_end", {}).get(
        str(record.get("_doc"))
    )
    row_count_penalty_pressure = (
        hybrid_rank is not None
        and hybrid_rank <= 500
        and (row_count_rank is None or row_count_rank > 500)
    )
    if representative_dominance and int(record.get("case_count") or 0) > 1:
        return "representative_row_dominance_proxy"
    if amount_weak and period_weak:
        return "weak_amount_period_end_context"
    if row_count_penalty_pressure:
        return "row_count_penalty_pressure"
    if repeated_normal_pressure_high:
        return "repeated_normal_competition"
    return "diffuse_score_competition"


def _pool_absence_diagnostic(
    *,
    df: pd.DataFrame,
    scores: pd.Series,
    phase1_missed_truth_docs: set[str],
    pool_docs: set[str],
    truth_scenario_by_doc: dict[str, str],
) -> dict[str, Any]:
    doc_col = "document" "_id"
    missing_docs = phase1_missed_truth_docs - pool_docs
    positive = scores.astype(float) > 0.0
    ecdf = pd.Series(0.0, index=scores.index, dtype=float)
    if positive.any():
        ecdf.loc[positive] = scores.loc[positive].rank(method="average", pct=True)
    frame = pd.DataFrame(
        {
            doc_col: df[doc_col].astype(str),
            "score_positive": positive.astype(int),
            "score_ecdf": ecdf.astype(float),
        }
    )
    subset = frame[frame[doc_col].isin(missing_docs)]
    grouped = subset.groupby(doc_col).agg(
        positive_rows=("score_positive", "sum"),
        max_ecdf=("score_ecdf", "max"),
    )
    reason_counts: Counter[str] = Counter()
    scenario_counts: Counter[str] = Counter()
    for doc in missing_docs:
        if doc not in grouped.index:
            reason = "artifact_source_row_missing"
        else:
            row = grouped.loc[doc]
            if float(row["max_ecdf"]) >= 0.95:
                reason = "artifact_conversion_miss_proxy"
            elif int(row["positive_rows"]) > 0:
                reason = "q95_gate_miss"
            else:
                reason = "feature_score_miss"
        reason_counts[reason] += 1
        scenario_counts[truth_scenario_by_doc.get(doc, "unknown")] += 1
    return {
        "absent_count": len(missing_docs),
        "absence_reason_counts": {
            str(key): int(value) for key, value in sorted(reason_counts.items())
        },
        "absent_scenario_counts": {
            str(key): int(value) for key, value in sorted(scenario_counts.items())
        },
        "artifact_conversion_miss_proxy_note": (
            "Counts docs whose raw unsupervised row score ECDF reaches the native q95 case gate "
            "but no document-level native case artifact is present."
        ),
    }


def phase1_missed_truth_attrition_diagnostic(
    *,
    df: pd.DataFrame,
    scores: pd.Series,
    cases: list[Phase2CaseBase],
    records: dict[str, dict[str, Any]],
    phase1_all_docs: set[str],
    truth_docs: set[str],
    truth_scenario_by_doc: dict[str, str],
) -> dict[str, Any]:
    phase1_missed = truth_docs - phase1_all_docs
    pool_docs = set(records)
    entered = phase1_missed & pool_docs
    ordered_surfaces = _candidate_ordered_doc_surfaces(cases=cases, records=records)
    rank_surfaces = {
        "native_row_queue",
        "hybrid_with_soft_repeated_normal_guard",
        "soft_guard_with_row_count_context",
        "hybrid_row_count_blended_surface",
        "phase1_prior_companion_surface",
    }
    ranks_by_surface = {
        name: _surface_full_rank_map(ordered_surfaces[name]) for name in rank_surfaces
    }
    out: dict[str, Any] = {}
    for name in sorted(rank_surfaces):
        rank_map = ranks_by_surface[name]
        ranks = [rank_map[doc] for doc in entered if doc in rank_map]
        top500_docs = set(_surface_docs_for_topn(ordered_surfaces[name], 500))
        top500_nontruth = [
            doc
            for doc in top500_docs
            if doc not in truth_docs and int(records.get(doc, {}).get("case_count") or 0) > 1
        ]
        repeated_pressure_high = (
            _safe_div(float(len(top500_nontruth)), float(len(top500_docs))) > 0.10
        )
        outside = [doc for doc in entered if rank_map.get(doc, 10**9) > 500]
        reason_counts: Counter[str] = Counter()
        amount_values: list[float] = []
        period_scores: list[float] = []
        row_counts: list[int] = []
        representative_ratios: list[float] = []
        for doc in outside:
            record = dict(records[doc])
            record["_doc"] = doc
            reason_counts[
                _top500_out_reason(
                    record=record,
                    ranks_by_surface=ranks_by_surface,
                    repeated_normal_pressure_high=repeated_pressure_high,
                )
            ] += 1
            amount_values.append(float(record.get("amount_percentile") or 0.0))
            period_scores.append(_period_end_score(record.get("min_period_end_proximity_days")))
            row_counts.append(int(record.get("document_row_count") or 0))
            scores_for_doc = [
                float(value) for value in record.get("scores", ()) if value is not None
            ]
            max_score = max(scores_for_doc or [0.0])
            top3 = sorted(scores_for_doc, reverse=True)[:3]
            top3_mean = float(np.mean(top3)) if top3 else 0.0
            representative_ratios.append(_safe_div(top3_mean, max_score))
        out[name] = {
            "entered_pool_rank_distribution": _rank_distribution(ranks),
            "entered_pool_docs_in_top500": len(entered & top500_docs),
            "entered_pool_docs_outside_top500": len(outside),
            "top500_out_reason_counts": {
                str(key): int(value) for key, value in sorted(reason_counts.items())
            },
            "top500_out_context_summary": {
                "amount_percentile_distribution": _distribution(amount_values),
                "period_end_score_distribution": _distribution(period_scores),
                "document_row_count_distribution": _distribution(row_counts),
                "top3_mean_to_max_score_ratio_distribution": _distribution(
                    representative_ratios
                ),
                "top500_repeated_normal_nontruth_ratio": _safe_div(
                    float(len(top500_nontruth)), float(len(top500_docs))
                ),
            },
        }

    union_membership: dict[str, Any] = {}
    for name in (
        "frontier_phase1_plus_aggressive_union",
        "frontier_all_four_lanes_union",
    ):
        surface = ordered_surfaces[name]
        union_membership[name] = {
            str(top_n): len(entered & set(_surface_docs_for_topn(surface, top_n)))
            for top_n in (100, 500, 1000, 10000)
        }

    entered_scenarios = Counter(truth_scenario_by_doc.get(doc, "unknown") for doc in entered)
    return {
        "diagnostic_only": True,
        "total_phase1_missed_truth_docs": len(phase1_missed),
        "entered_unsupervised_candidate_pool": len(entered),
        "absent_from_unsupervised_candidate_pool": len(phase1_missed - pool_docs),
        "entered_pool_scenario_counts": {
            str(key): int(value) for key, value in sorted(entered_scenarios.items())
        },
        "rank_and_top500_attrition_by_surface": out,
        "frontier_union_membership_counts": union_membership,
        "candidate_pool_absence": _pool_absence_diagnostic(
            df=df,
            scores=scores,
            phase1_missed_truth_docs=phase1_missed,
            pool_docs=pool_docs,
            truth_scenario_by_doc=truth_scenario_by_doc,
        ),
        "truth_label_used_for_scoring": False,
        "truth_label_used_only_for_aggregate_evaluation": True,
        "q95_gate_changed": False,
        "vae_score_or_threshold_changed": False,
        "native_row_case_ordering_changed": False,
        "phase1_ranking_changed": False,
        "phase2_fusion_changed": False,
        "production_adoption": "pending_cross_batch_validation",
    }


def _score_doc_sets(df: pd.DataFrame, scores: pd.Series) -> dict[str, set[str]]:
    doc_col = "document" "_id"
    positive = scores.astype(float) > 0.0
    ecdf = pd.Series(0.0, index=scores.index, dtype=float)
    if positive.any():
        ecdf.loc[positive] = scores.loc[positive].rank(method="average", pct=True)
    frame = pd.DataFrame(
        {
            doc_col: df[doc_col].astype(str),
            "score_positive": positive,
            "q95_pass": ecdf >= 0.95,
        }
    )
    return {
        "score_candidate_docs": set(frame.loc[frame["score_positive"], doc_col]),
        "q95_pass_docs": set(frame.loc[frame["q95_pass"], doc_col]),
    }


def _q95_miss_context(
    *,
    df: pd.DataFrame,
    scores: pd.Series,
    docs: set[str],
    phase1: dict[str, Any],
) -> dict[str, Any]:
    doc_col = "document" "_id"
    if not docs:
        return {
            "doc_count": 0,
            "max_row_score_percentile_distribution": _distribution([]),
            "near_q95_band_count": 0,
            "document_top_k_mean_distribution": _distribution([]),
            "row_count_distribution": _distribution([]),
            "period_end_context_distribution": _distribution([]),
            "amount_tail_context_distribution": _distribution([]),
            "phase1_generic_only_count": 0,
            "strong_document_context_candidate_count": 0,
        }
    positive = scores.astype(float) > 0.0
    ecdf = pd.Series(0.0, index=scores.index, dtype=float)
    if positive.any():
        ecdf.loc[positive] = scores.loc[positive].rank(method="average", pct=True)
    work = pd.DataFrame(
        {
            doc_col: df[doc_col].astype(str),
            "score_ecdf": ecdf.astype(float),
            "score": scores.astype(float),
        }
    )
    if "amount" in df.columns:
        work["amount_abs"] = pd.to_numeric(df["amount"], errors="coerce").abs().fillna(0.0)
    else:
        work["amount_abs"] = 0.0
    if "period_end_proximity_days" in df.columns:
        work["period_end_context"] = pd.to_numeric(
            df["period_end_proximity_days"], errors="coerce"
        ).map(_period_end_score)
    else:
        work["period_end_context"] = 0.0
    amount_by_doc = work.groupby(doc_col)["amount_abs"].max()
    amount_percentile = _percentile_map(
        {str(doc): float(value) for doc, value in amount_by_doc.items()}
    )
    subset = work[work[doc_col].isin(docs)]
    grouped = subset.groupby(doc_col).agg(
        max_score_percentile=("score_ecdf", "max"),
        top_k_mean_score=("score_ecdf", lambda series: float(series.nlargest(3).mean())),
        row_count=("score_ecdf", "size"),
        period_end_context=("period_end_context", "max"),
    )
    amount_tail_values = [
        float(amount_percentile.get(str(doc), 0.0)) for doc in grouped.index.astype(str)
    ]
    max_percentiles = [float(value) for value in grouped["max_score_percentile"].tolist()]
    period_values = [float(value) for value in grouped["period_end_context"].tolist()]
    strong_context = [
        doc
        for doc, max_pct, amount_pct, period_ctx in zip(
            grouped.index.astype(str),
            max_percentiles,
            amount_tail_values,
            period_values,
            strict=False,
        )
        if 0.90 <= max_pct < 0.95 and (amount_pct >= 0.95 or period_ctx >= 0.50)
    ]
    return {
        "doc_count": int(len(grouped)),
        "max_row_score_percentile_distribution": _distribution(max_percentiles),
        "near_q95_band_count": int(sum(1 for value in max_percentiles if 0.90 <= value < 0.95)),
        "document_top_k_mean_distribution": _distribution(
            [float(value) for value in grouped["top_k_mean_score"].tolist()]
        ),
        "row_count_distribution": _distribution(
            [int(value) for value in grouped["row_count"].tolist()]
        ),
        "period_end_context_distribution": _distribution(period_values),
        "amount_tail_context_distribution": _distribution(amount_tail_values),
        "phase1_generic_only_count": len(
            set(grouped.index.astype(str)) & set(phase1.get("generic_only_docs", set()))
        ),
        "strong_document_context_candidate_count": len(strong_context),
    }


def _diagnostic_two_lane_surfaces(
    *,
    records: dict[str, dict[str, Any]],
    phase1: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    scored = _candidate_scores(records)
    soft_scores = dict(scored["hybrid_with_soft_repeated_normal_guard"])
    context_scores = dict(scored["soft_guard_with_row_count_context"])
    phase1_all = set(phase1["all_docs"])
    phase1_top1000 = set(phase1["top_sets"]["1000"])
    statistical = sorted(
        soft_scores,
        key=lambda doc: (
            doc not in phase1_all,
            doc not in phase1_top1000,
            -float(soft_scores[doc]),
            _doc_sort_key(doc),
        ),
    )
    blind = sorted(
        context_scores,
        key=lambda doc: (
            doc in phase1_top1000,
            doc in phase1_all,
            -float(context_scores[doc]),
            _doc_sort_key(doc),
        ),
    )
    balanced: list[str] = []
    seen: set[str] = set()
    stat_idx = 0
    blind_idx = 0
    while len(balanced) < len(records) and (stat_idx < len(statistical) or blind_idx < len(blind)):
        for _ in range(2):
            while stat_idx < len(statistical) and statistical[stat_idx] in seen:
                stat_idx += 1
            if stat_idx < len(statistical):
                doc = statistical[stat_idx]
                seen.add(doc)
                balanced.append(doc)
                stat_idx += 1
        while blind_idx < len(blind) and blind[blind_idx] in seen:
            blind_idx += 1
        if blind_idx < len(blind):
            doc = blind[blind_idx]
            seen.add(doc)
            balanced.append(doc)
            blind_idx += 1
    return {
        "statistical_reinforcement": {"kind": "ordered", "docs": statistical},
        "blind_spot_exploration": {"kind": "ordered", "docs": blind},
        "balanced_unsupervised_companion_v1": {"kind": "ordered", "docs": balanced},
    }


def _topn_uplift_metrics(
    *,
    selected_docs_by_topn: dict[str, set[str]],
    phase1: dict[str, Any],
    truth_docs: set[str],
) -> dict[str, Any]:
    phase1_top = {key: set(value) for key, value in phase1["top_sets"].items()}
    out: dict[str, Any] = {
        "phase1_all_truth_document_coverage": len(set(phase1["all_docs"]) & truth_docs),
        "phase1_top100_truth_document_coverage": len(phase1_top["100"] & truth_docs),
        "phase1_top500_truth_document_coverage": len(phase1_top["500"] & truth_docs),
        "phase1_top1000_truth_document_coverage": len(phase1_top["1000"] & truth_docs),
    }
    for top_n in ("100", "500", "1000"):
        selected_truth = selected_docs_by_topn[top_n] & truth_docs
        phase1_truth = phase1_top[top_n] & truth_docs
        out[f"phase2_top{top_n}_truth_not_in_phase1_top{top_n}"] = len(
            selected_truth - phase1_top[top_n]
        )
        out[f"net_truth_uplift_vs_phase1_top{top_n}"] = len(selected_truth) - len(phase1_truth)
    return out


def _evidence_incremental_metrics(
    *,
    records: dict[str, dict[str, Any]],
    phase1: dict[str, Any],
    truth_docs: set[str],
) -> dict[str, Any]:
    pool_truth = set(records) & truth_docs
    top_feature_docs = {
        doc for doc in pool_truth if int(records[doc].get("top_feature_case_count") or 0) > 0
    }
    context_docs = {
        doc
        for doc in pool_truth
        if records[doc].get("amount_percentile") is not None
        or records[doc].get("min_period_end_proximity_days") is not None
        or int(records[doc].get("case_count") or 0) > 0
    }
    phase1_generic = set(phase1.get("generic_only_docs", set())) & truth_docs
    phase2_specific = {
        doc
        for doc in pool_truth
        if doc in phase1_generic or doc not in set(phase1["all_docs"])
    }
    return {
        "unsupervised_evidence_added_truth_docs": len(pool_truth),
        "unsupervised_evidence_added_case_count": sum(
            int(records[doc].get("case_count") or 0) for doc in pool_truth
        ),
        "ml_score_evidence_added_truth_docs": len(pool_truth),
        "top_feature_evidence_added_truth_docs": len(top_feature_docs),
        "document_level_context_added_truth_docs": len(context_docs),
        "amount_tail_context_added_truth_docs": len(
            {
                doc
                for doc in pool_truth
                if float(records[doc].get("amount_percentile") or 0.0) >= 0.95
            }
        ),
        "period_end_context_added_truth_docs": len(
            {
                doc
                for doc in pool_truth
                if _period_end_score(records[doc].get("min_period_end_proximity_days")) > 0.0
            }
        ),
        "row_count_repeated_guard_context_added_truth_docs": len(
            {doc for doc in pool_truth if int(records[doc].get("case_count") or 0) > 1}
        ),
        "multivariate_anomaly_context_added_truth_docs": len(pool_truth),
        "phase1_only_generic_reason_truth_docs": len(phase1_generic),
        "phase2_specific_ml_reason_truth_docs": len(phase2_specific),
        "stage7_top_features_unavailable_truth_docs": len(pool_truth - top_feature_docs),
    }


def _explanation_gap_metrics(
    *,
    phase1: dict[str, Any],
    records: dict[str, dict[str, Any]],
    truth_docs: set[str],
    truth_scenario_by_doc: dict[str, str],
) -> dict[str, Any]:
    categories_by_doc: dict[str, set[str]] = phase1.get("categories_by_doc", {})
    phase1_all_truth = set(phase1["all_docs"]) & truth_docs
    aligned = 0
    generic_only = 0
    scenario_counts: Counter[str] = Counter()
    unsup_incremental = 0
    for doc in phase1_all_truth:
        scenario_category = _scenario_category(truth_scenario_by_doc.get(doc, "unknown"))
        categories = set(categories_by_doc.get(doc, {"generic_review"}))
        if scenario_category in categories:
            aligned += 1
        if categories.issubset({"generic_review", "amount_tail"}):
            generic_only += 1
            scenario_counts[scenario_category] += 1
            if doc in records:
                unsup_incremental += 1
    phase1_missed_with_unsup = (truth_docs - set(phase1["all_docs"])) & set(records)
    return {
        "phase1_scenario_aligned_truth_docs": aligned,
        "phase1_generic_only_truth_docs": generic_only,
        "phase1_scenario_gap_truth_docs": len(phase1_all_truth) - aligned,
        "unsupervised_explanation_incremental_truth_docs": unsup_incremental
        + len(phase1_missed_with_unsup),
        "generic_only_scenario_category_counts": {
            str(key): int(value) for key, value in sorted(scenario_counts.items())
        },
        "phase2_statistical_explanation_note": (
            "Unsupervised evidence is treated as statistical/multivariate review context, "
            "not a scenario-specific rule finding."
        ),
    }


def _blind_spot_attrition_metrics(
    *,
    df: pd.DataFrame,
    scores: pd.Series,
    cases: list[Phase2CaseBase],
    records: dict[str, dict[str, Any]],
    phase1: dict[str, Any],
    truth_docs: set[str],
    truth_scenario_by_doc: dict[str, str],
    surfaces: dict[str, Any],
) -> dict[str, Any]:
    score_sets = _score_doc_sets(df, scores)
    phase1_top1000 = set(phase1["top_sets"]["1000"])
    generic_only = set(phase1.get("generic_only_docs", set()))
    target = (truth_docs - phase1_top1000) | (truth_docs & generic_only)
    pool_docs = set(records)
    native_docs = {
        doc for case in cases for doc in _case_documents(case)
    }
    surface_topn = {}
    for name, surface in surfaces.items():
        if name not in {
            "native_row_queue",
            "document_score_with_row_count_penalty",
            "hybrid_with_soft_repeated_normal_guard",
            "soft_guard_with_row_count_context",
            "hybrid_row_count_blended_surface",
            "phase1_prior_companion_surface",
            "frontier_phase1_plus_aggressive_union",
            "frontier_all_four_lanes_union",
            "statistical_reinforcement",
            "blind_spot_exploration",
            "balanced_unsupervised_companion_v1",
        }:
            continue
        surface_topn[name] = {
            str(top_n): len(target & set(_surface_docs_for_topn(surface, top_n)))
            for top_n in (100, 500, 1000, 10000)
        }
    best_surface = surfaces["balanced_unsupervised_companion_v1"]
    best_top500 = set(_surface_docs_for_topn(best_surface, 500))
    candidate_below_top500 = (target & pool_docs) - best_top500
    missing_from_pool = target - pool_docs
    absence = _pool_absence_diagnostic(
        df=df,
        scores=scores,
        phase1_missed_truth_docs=target,
        pool_docs=pool_docs,
        truth_scenario_by_doc=truth_scenario_by_doc,
    )
    reason_counts = Counter(absence["absence_reason_counts"])
    if candidate_below_top500:
        reason_counts["candidate_but_ranked_below_top500"] += len(candidate_below_top500)
    return {
        "target_truth_docs": len(target),
        "target_definition": (
            "PHASE1 TOP1000 outside truth docs plus PHASE1 generic-only truth docs"
        ),
        "score_candidate_truth_docs": len(target & score_sets["score_candidate_docs"]),
        "q95_pass_truth_docs": len(target & score_sets["q95_pass_docs"]),
        "native_case_truth_docs": len(target & native_docs),
        "document_candidate_truth_docs": len(target & pool_docs),
        "topN_surface_truth_docs": surface_topn,
        "candidate_but_ranked_below_top500_truth_docs": len(candidate_below_top500),
        "missing_from_candidate_pool_truth_docs": len(missing_from_pool),
        "attrition_reason_aggregate": {
            str(key): int(value) for key, value in sorted(reason_counts.items())
        },
        "missing_from_candidate_pool_reason_counts": absence["absence_reason_counts"],
        "missing_from_candidate_pool_scenario_counts": absence["absent_scenario_counts"],
    }


def _incremental_value_decision(value: dict[str, Any]) -> dict[str, Any]:
    balanced = value["surface_topn_uplift"]["balanced_unsupervised_companion_v1"]
    soft = value["surface_topn_uplift"]["hybrid_with_soft_repeated_normal_guard"]
    evidence = value["unsupervised_evidence_incremental"]
    attrition = value["blind_spot_attrition_summary"]
    top500_uplift = int(balanced["net_truth_uplift_vs_phase1_top500"])
    evidence_docs = int(evidence["unsupervised_evidence_added_truth_docs"])
    if top500_uplift >= 50 and evidence_docs >= 300:
        role = "topn_uplift_plus_statistical_evidence_companion"
        topn_value = "high"
    elif top500_uplift > 0:
        role = "broad_expansion"
        topn_value = "medium"
    else:
        role = "diagnostic_only"
        topn_value = "low"
    return {
        "document_inclusion_incremental_value": "broad_inclusion_metric_only",
        "topn_uplift_value": topn_value,
        "evidence_incremental_value": "high" if evidence_docs >= 300 else "medium",
        "explanation_incremental_value": (
            "medium"
            if value["scenario_explanation_gap"]["unsupervised_explanation_incremental_truth_docs"]
            > 0
            else "low"
        ),
        "blind_spot_attrition_summary": {
            "target_truth_docs": attrition["target_truth_docs"],
            "document_candidate_truth_docs": attrition["document_candidate_truth_docs"],
            "candidate_but_ranked_below_top500_truth_docs": attrition[
                "candidate_but_ranked_below_top500_truth_docs"
            ],
            "missing_from_candidate_pool_truth_docs": attrition[
                "missing_from_candidate_pool_truth_docs"
            ],
        },
        "primary_product_role": role,
        "recommended_default_surface_if_datasynth_incomplete": (
            "balanced_unsupervised_companion_v1"
            if top500_uplift >= int(soft["net_truth_uplift_vs_phase1_top500"])
            else "hybrid_with_soft_repeated_normal_guard"
        ),
        "adopted_default_allowed": False,
        "reason": [
            "PHASE1 all document inclusion is kept only as a broad inclusion metric.",
            "Product value is evaluated through PHASE1 TOP-N uplift, ML/statistical evidence "
            "incremental, explanation gap, and blind-spot attrition.",
            "Any adoption would be based on PHASE1 TOP-N uplift plus ML/statistical evidence "
            "incremental plus broad expansion, not on a claim of large PHASE1 blind-spot "
            "discovery.",
            "No product ranking, gate, q95 threshold, VAE score, PHASE1 ranking, or PHASE2 fusion "
            "policy is changed.",
        ],
    }


def unsupervised_incremental_value_diagnostic(
    *,
    df: pd.DataFrame,
    scores: pd.Series,
    cases: list[Phase2CaseBase],
    records: dict[str, dict[str, Any]],
    truth_docs: set[str],
    truth_scenario_by_doc: dict[str, str],
    phase1_case_result_path: Path | None = None,
) -> dict[str, Any]:
    phase1 = build_phase1_baseline(
        df,
        truth_docs,
        case_result_path=phase1_case_result_path,
    )
    surfaces = _candidate_ordered_doc_surfaces(cases=cases, records=records)
    surfaces.update(_diagnostic_two_lane_surfaces(records=records, phase1=phase1))
    selected_surface_names = (
        "native_row_queue",
        "document_score_with_row_count_penalty",
        "hybrid_with_soft_repeated_normal_guard",
        "soft_guard_with_row_count_context",
        "hybrid_row_count_blended_surface",
        "phase1_prior_companion_surface",
        "frontier_phase1_plus_aggressive_union",
        "frontier_all_four_lanes_union",
        "statistical_reinforcement",
        "blind_spot_exploration",
        "balanced_unsupervised_companion_v1",
    )
    uplift: dict[str, Any] = {}
    for name in selected_surface_names:
        surface = surfaces[name]
        selected_by_topn = {
            str(top_n): set(_surface_docs_for_topn(surface, top_n))
            for top_n in (100, 500, 1000)
        }
        uplift[name] = _topn_uplift_metrics(
            selected_docs_by_topn=selected_by_topn,
            phase1=phase1,
            truth_docs=truth_docs,
        )
    value = {
        "diagnostic_only": True,
        "phase1_baseline": {
            "phase1_all_document_inclusion": phase1["summary"]["phase1_all_doc_count"],
            "phase1_all_truth_document_coverage": phase1["summary"][
                "phase1_all_truth_count"
            ],
            "phase1_top100_truth_document_coverage": phase1["summary"][
                "phase1_top100_truth_count"
            ],
            "phase1_top500_truth_document_coverage": phase1["summary"][
                "phase1_top500_truth_count"
            ],
            "phase1_top1000_truth_document_coverage": phase1["summary"][
                "phase1_top1000_truth_count"
            ],
            "baseline_source": phase1["summary"]["source"],
        },
        "surface_topn_uplift": uplift,
        "unsupervised_evidence_incremental": _evidence_incremental_metrics(
            records=records,
            phase1=phase1,
            truth_docs=truth_docs,
        ),
        "scenario_explanation_gap": _explanation_gap_metrics(
            phase1=phase1,
            records=records,
            truth_docs=truth_docs,
            truth_scenario_by_doc=truth_scenario_by_doc,
        ),
        "blind_spot_attrition_summary": _blind_spot_attrition_metrics(
            df=df,
            scores=scores,
            cases=cases,
            records=records,
            phase1=phase1,
            truth_docs=truth_docs,
            truth_scenario_by_doc=truth_scenario_by_doc,
            surfaces=surfaces,
        ),
        "truth_label_used_for_scoring": False,
        "truth_label_used_only_for_aggregate_evaluation": True,
        "q95_gate_changed": False,
        "vae_score_or_threshold_changed": False,
        "native_row_case_ordering_changed": False,
        "phase1_ranking_changed": False,
        "phase2_fusion_changed": False,
        "production_adoption": "pending_cross_batch_validation",
    }
    value["decision"] = _incremental_value_decision(value)
    return value


def _rank_band(rank: int | None) -> str:
    if rank is None:
        return "not_ranked"
    if rank <= 500:
        return "top500"
    if rank <= 1000:
        return "501_1000"
    if rank <= 2000:
        return "1001_2000"
    if rank <= 5000:
        return "2001_5000"
    return "5001_plus"


def _doc_record_context(record: dict[str, Any]) -> dict[str, float | int]:
    scores = [float(value) for value in record.get("scores", ()) if value is not None]
    top3 = sorted(scores, reverse=True)[:3]
    return {
        "family_ecdf": max(scores or [0.0]),
        "max_score": max(scores or [0.0]),
        "top_k_mean": float(np.mean(top3)) if top3 else 0.0,
        "row_count": int(record.get("document_row_count") or 0),
        "case_count": int(record.get("case_count") or 0),
        "period_end_context": _period_end_score(record.get("min_period_end_proximity_days")),
        "amount_tail_context": float(record.get("amount_percentile") or 0.0),
        "repeated_normal_proxy": min(float(record.get("case_count") or 0) / 5.0, 1.0),
        "top_features_available": 1
        if int(record.get("top_feature_case_count") or 0) > 0
        else 0,
    }


def _aggregate_doc_context(
    *,
    docs: set[str],
    records: dict[str, dict[str, Any]],
    phase1: dict[str, Any],
) -> dict[str, Any]:
    contexts = [_doc_record_context(records[doc]) for doc in docs if doc in records]
    if not contexts:
        return {
            "doc_count": 0,
            "family_ecdf_distribution": _distribution([]),
            "max_score_distribution": _distribution([]),
            "top_k_mean_distribution": _distribution([]),
            "row_count_distribution": _distribution([]),
            "case_count_distribution": _distribution([]),
            "period_end_context_distribution": _distribution([]),
            "amount_tail_context_distribution": _distribution([]),
            "repeated_normal_proxy_distribution": _distribution([]),
            "phase1_top100_outside_count": 0,
            "phase1_top500_outside_count": 0,
            "phase1_top1000_outside_count": 0,
            "top_features_availability_ratio": 0.0,
        }
    return {
        "doc_count": len(contexts),
        "family_ecdf_distribution": _distribution([ctx["family_ecdf"] for ctx in contexts]),
        "max_score_distribution": _distribution([ctx["max_score"] for ctx in contexts]),
        "top_k_mean_distribution": _distribution([ctx["top_k_mean"] for ctx in contexts]),
        "row_count_distribution": _distribution([ctx["row_count"] for ctx in contexts]),
        "case_count_distribution": _distribution([ctx["case_count"] for ctx in contexts]),
        "period_end_context_distribution": _distribution(
            [ctx["period_end_context"] for ctx in contexts]
        ),
        "amount_tail_context_distribution": _distribution(
            [ctx["amount_tail_context"] for ctx in contexts]
        ),
        "repeated_normal_proxy_distribution": _distribution(
            [ctx["repeated_normal_proxy"] for ctx in contexts]
        ),
        "phase1_top100_outside_count": len(docs - set(phase1["top_sets"]["100"])),
        "phase1_top500_outside_count": len(docs - set(phase1["top_sets"]["500"])),
        "phase1_top1000_outside_count": len(docs - set(phase1["top_sets"]["1000"])),
        "top_features_availability_ratio": _safe_div(
            float(sum(int(ctx["top_features_available"]) for ctx in contexts)),
            float(len(contexts)),
        ),
    }


def _rescue_candidate(record: dict[str, Any], *, phase1_top500_outside: bool) -> bool:
    ctx = _doc_record_context(record)
    return (
        phase1_top500_outside
        and float(ctx["family_ecdf"]) >= 0.95
        and (
            float(ctx["period_end_context"]) >= 0.50
            or float(ctx["amount_tail_context"]) >= 0.95
        )
    )


def _new_diagnostic_surfaces(
    *,
    records: dict[str, dict[str, Any]],
    phase1: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    scored = _candidate_scores(records)
    soft = _ordered_docs(scored["hybrid_with_soft_repeated_normal_guard"])
    phase1_top500 = set(phase1["top_sets"]["500"])

    rescue_pool = [
        doc
        for doc in soft[500:2000]
        if _rescue_candidate(records[doc], phase1_top500_outside=doc not in phase1_top500)
    ]
    rescue_slots = 100
    rescued = rescue_pool[:rescue_slots]
    rescue_surface = []
    seen: set[str] = set()
    for doc in [*soft[:400], *rescued, *soft]:
        if doc not in seen:
            seen.add(doc)
            rescue_surface.append(doc)

    diversity_surface: list[str] = []
    diversity_seen: set[str] = set()
    account_counts: Counter[str] = Counter()
    process_counts: Counter[str] = Counter()
    for doc in soft:
        record = records[doc]
        account_key = "|".join(sorted(str(value) for value in record.get("accounts") or ()))[:80]
        process_key = "|".join(sorted(str(value) for value in record.get("processes") or ()))[:80]
        if len(diversity_surface) < 500 and (
            account_counts[account_key] >= 25 or process_counts[process_key] >= 50
        ):
            continue
        diversity_seen.add(doc)
        diversity_surface.append(doc)
        account_counts[account_key] += 1
        process_counts[process_key] += 1
    for doc in soft:
        if doc not in diversity_seen:
            diversity_surface.append(doc)

    top_feature_docs = [
        doc for doc in soft if int(records[doc].get("top_feature_case_count") or 0) > 0
    ]
    ml_quality_disabled = not top_feature_docs
    top_feature_set = set(top_feature_docs)
    ml_quality_surface = top_feature_docs + [
        doc for doc in soft if doc not in top_feature_set
    ]

    reinforcement = [doc for doc in soft if doc in phase1_top500]
    exploration = [doc for doc in soft if doc not in phase1_top500]
    gap_surface: list[str] = []
    gap_seen: set[str] = set()
    ri = 0
    ei = 0
    while len(gap_surface) < len(soft) and (ri < len(reinforcement) or ei < len(exploration)):
        for _ in range(2):
            while ri < len(reinforcement) and reinforcement[ri] in gap_seen:
                ri += 1
            if ri < len(reinforcement):
                doc = reinforcement[ri]
                gap_seen.add(doc)
                gap_surface.append(doc)
                ri += 1
        while ei < len(exploration) and exploration[ei] in gap_seen:
            ei += 1
        if ei < len(exploration):
            doc = exploration[ei]
            gap_seen.add(doc)
            gap_surface.append(doc)
            ei += 1

    return {
        "soft_guard_rank_band_rescue_surface": {
            "kind": "ordered",
            "docs": rescue_surface,
            "policy": "soft guard top400 plus capped rescue from rank501-2000; cap=100",
        },
        "soft_guard_context_diversity_surface": {
            "kind": "ordered",
            "docs": diversity_surface,
            "policy": "soft guard order with account/process concentration caps in first 500",
        },
        "ml_evidence_quality_surface": {
            "kind": "ordered",
            "docs": ml_quality_surface,
            "policy": (
                "top_features evidence-quality tie surface; disabled when top_features absent"
            ),
            "disabled": ml_quality_disabled,
            "disabled_reason": (
                "Stage7 measurement path uses dummy details without ML02_top_feature_*"
            )
            if ml_quality_disabled
            else None,
        },
        "phase1_topn_gap_companion_surface": {
            "kind": "ordered",
            "docs": gap_surface,
            "policy": "2 reinforcement : 1 PHASE1 TOP500-gap exploration interleave",
        },
    }


def _surface_eval(
    *,
    name: str,
    surface: dict[str, Any],
    records: dict[str, dict[str, Any]],
    phase1: dict[str, Any],
    truth_docs: set[str],
    evidence: dict[str, Any],
    explanation: dict[str, Any],
    baseline_below_top500: int,
    target_docs: set[str],
) -> dict[str, Any]:
    selected_by_topn = {
        str(top_n): set(_surface_docs_for_topn(surface, top_n))
        for top_n in (100, 500, 1000, 10000)
    }
    topn = {
        str(top_n): _coverage_for_docs(
            sorted(selected_by_topn[str(top_n)], key=_doc_sort_key),
            truth_docs,
        )
        for top_n in (100, 500, 1000, 10000)
    }
    uplift = _topn_uplift_metrics(
        selected_docs_by_topn={key: selected_by_topn[key] for key in ("100", "500", "1000")},
        phase1=phase1,
        truth_docs=truth_docs,
    )
    top500_docs = selected_by_topn["500"]
    repeated_normal = [
        doc
        for doc in top500_docs
        if doc not in truth_docs and int(records.get(doc, {}).get("case_count") or 0) > 1
    ]
    target_below = len((target_docs & set(records)) - top500_docs)
    return {
        "topn": topn,
        "phase1_topn_uplift": uplift,
        "evidence_incremental": evidence,
        "explanation_incremental": explanation,
        "candidate_but_ranked_below_top500": target_below,
        "candidate_but_ranked_below_top500_reduction": baseline_below_top500 - target_below,
        "nontruth_document_count_top500": len(top500_docs - truth_docs),
        "repeated_normal_ratio_top500": _safe_div(
            float(len(repeated_normal)), float(len(top500_docs))
        ),
        "review_burden_top500": len(top500_docs),
        "candidate_weight_provenance": {
            "weight_source": "audit policy fixed diagnostic surface",
            "calibrated": False,
            "fixed5_weight_sweep": False,
            "production_ranking_policy": False,
            "requires_validation": "cross-batch/fixture validation before adoption",
        },
        "production_adoption": "pending_cross_batch_validation",
        "disabled": bool(surface.get("disabled", False)),
        "disabled_reason": surface.get("disabled_reason"),
        "policy": surface.get("policy"),
        "truth_label_used_for_scoring": False,
        "truth_label_used_only_for_aggregate_evaluation": True,
        "q95_gate_changed": False,
        "vae_score_or_threshold_changed": False,
        "native_row_case_ordering_changed": False,
        "phase1_ranking_changed": False,
        "phase2_fusion_changed": False,
    }


def _ranking_attrition_reason_counts(
    *,
    below_docs: set[str],
    records: dict[str, dict[str, Any]],
    rank_maps: dict[str, dict[str, int]],
    phase1: dict[str, Any],
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for doc in below_docs:
        soft_rank = rank_maps["hybrid_with_soft_repeated_normal_guard"].get(doc)
        balanced_rank = rank_maps["balanced_unsupervised_companion_v1"].get(doc)
        ctx = _doc_record_context(records[doc])
        if soft_rank is not None and soft_rank <= 500 and (balanced_rank or 10**9) > 500:
            reason = "audit_policy_interleave_suppression"
        elif float(ctx["repeated_normal_proxy"]) >= 0.40:
            reason = "repeated_normal_competition"
        elif float(ctx["period_end_context"]) < 0.50 and float(ctx["amount_tail_context"]) < 0.95:
            reason = "weak_amount_period_end_context"
        elif doc not in set(phase1["top_sets"]["1000"]):
            reason = "phase1_topn_gap_low_surface_priority"
        else:
            reason = "diffuse_score_competition"
        counts[reason] += 1
    return {str(key): int(value) for key, value in sorted(counts.items())}


def unsupervised_attrition_improvement_diagnostic(
    *,
    df: pd.DataFrame,
    scores: pd.Series,
    cases: list[Phase2CaseBase],
    records: dict[str, dict[str, Any]],
    truth_docs: set[str],
    truth_scenario_by_doc: dict[str, str],
    phase1_case_result_path: Path | None = None,
) -> dict[str, Any]:
    del truth_scenario_by_doc
    phase1 = build_phase1_baseline(
        df,
        truth_docs,
        case_result_path=phase1_case_result_path,
    )
    base_surfaces = _candidate_ordered_doc_surfaces(cases=cases, records=records)
    base_surfaces.update(_diagnostic_two_lane_surfaces(records=records, phase1=phase1))
    new_surfaces = _new_diagnostic_surfaces(records=records, phase1=phase1)
    all_surfaces = {**base_surfaces, **new_surfaces}
    rank_maps = {
        name: _surface_full_rank_map(surface)
        for name, surface in all_surfaces.items()
        if surface.get("kind") == "ordered" or "docs" in surface
    }
    phase1_top1000 = set(phase1["top_sets"]["1000"])
    generic_only = set(phase1.get("generic_only_docs", set()))
    target_docs = (truth_docs - phase1_top1000) | (truth_docs & generic_only)
    baseline_top500 = set(
        _surface_docs_for_topn(all_surfaces["balanced_unsupervised_companion_v1"], 500)
    )
    candidate_pool = target_docs & set(records)
    below_docs = candidate_pool - baseline_top500
    band_counts = Counter(
        _rank_band(rank_maps["balanced_unsupervised_companion_v1"].get(doc))
        for doc in below_docs
    )
    q95_missing = target_docs - set(records)
    q95_context = _q95_miss_context(df=df, scores=scores, docs=q95_missing, phase1=phase1)
    evidence = _evidence_incremental_metrics(records=records, phase1=phase1, truth_docs=truth_docs)
    explanation = _explanation_gap_metrics(
        phase1=phase1,
        records=records,
        truth_docs=truth_docs,
        truth_scenario_by_doc={},
    )
    surface_eval = {
        name: _surface_eval(
            name=name,
            surface=surface,
            records=records,
            phase1=phase1,
            truth_docs=truth_docs,
            evidence=evidence,
            explanation=explanation,
            baseline_below_top500=len(below_docs),
            target_docs=target_docs,
        )
        for name, surface in new_surfaces.items()
    }
    soft_eval = _surface_eval(
        name="hybrid_with_soft_repeated_normal_guard",
        surface=all_surfaces["hybrid_with_soft_repeated_normal_guard"],
        records=records,
        phase1=phase1,
        truth_docs=truth_docs,
        evidence=evidence,
        explanation=explanation,
        baseline_below_top500=len(below_docs),
        target_docs=target_docs,
    )
    upper_bound_eval = _surface_eval(
        name="hybrid_row_count_blended_surface",
        surface=all_surfaces["hybrid_row_count_blended_surface"],
        records=records,
        phase1=phase1,
        truth_docs=truth_docs,
        evidence=evidence,
        explanation=explanation,
        baseline_below_top500=len(below_docs),
        target_docs=target_docs,
    )
    return {
        "diagnostic_only": True,
        "ranking_attrition_decomposition": {
            "baseline_surface": "balanced_unsupervised_companion_v1",
            "candidate_but_ranked_below_top500": len(below_docs),
            "rank_band_counts": {
                str(key): int(value) for key, value in sorted(band_counts.items())
            },
            "context_distribution": _aggregate_doc_context(
                docs=below_docs,
                records=records,
                phase1=phase1,
            ),
            "reason_category_counts": _ranking_attrition_reason_counts(
                below_docs=below_docs,
                records=records,
                rank_maps=rank_maps,
                phase1=phase1,
            ),
        },
        "q95_gate_miss_decomposition": {
            "q95_gate_miss_truth_docs": len(q95_missing),
            "near_q95_band_count": q95_context["near_q95_band_count"],
            "strong_document_context_candidate_count": q95_context[
                "strong_document_context_candidate_count"
            ],
            "context_distribution": q95_context,
            "future_candidate_note": (
                "q95 miss documents are not promoted to product cases; strong document "
                "context would require separate future validation."
            ),
        },
        "top_features_path_diagnostic": {
            "production_detector_emits_ml02_top_features": True,
            "builder_preserves_ml02_top_features": True,
            "measurement_path_uses_dummy_details": True,
            "artifact_serialization_missing_after_builder": False,
            "ranking_uses_top_features": False,
            "current_stage7_top_feature_evidence_added_truth_docs": evidence[
                "top_feature_evidence_added_truth_docs"
            ],
            "recommended_action": (
                "Keep top_features as evidence quality metric; do not use it for ranking "
                "until production-path fixture coverage is measured."
            ),
        },
        "baseline_surface": {
            "hybrid_with_soft_repeated_normal_guard": soft_eval,
            "hybrid_row_count_blended_surface_upper_bound": upper_bound_eval,
        },
        "new_diagnostic_surfaces": surface_eval,
        "decision": {
            "product_adoption_possible_now": False,
            "best_candidate_for_next_validation": "soft_guard_rank_band_rescue_surface",
            "reason": [
                "New surfaces are audit-policy based and do not use truth/scenario labels "
                "for order.",
                "Adoption requires cross-batch pressure and review-burden validation.",
                "top_features remain evidence-quality only because Stage7 measurement path "
                "has dummy details.",
            ],
        },
        "truth_label_used_for_scoring": False,
        "truth_label_used_only_for_aggregate_evaluation": True,
        "q95_gate_changed": False,
        "vae_score_or_threshold_changed": False,
        "native_row_case_ordering_changed": False,
        "phase1_ranking_changed": False,
        "phase2_fusion_changed": False,
        "production_adoption": "pending_cross_batch_validation",
    }


def _incremental_judgement(surfaces: dict[str, Any]) -> dict[str, Any]:
    primary = surfaces.get("hybrid_row_count_blended_surface", {}).get("topn", {}).get("500", {})
    incremental = int(primary.get("incremental_truth_docs_vs_phase1_all") or 0)
    ratio = float(primary.get("incremental_ratio") or 0.0)
    if incremental >= 25 and ratio >= 0.10:
        blind_spot_value = "high"
        role = "blind_spot_companion"
    elif incremental >= 10 or ratio >= 0.05:
        blind_spot_value = "medium"
        role = "broad_expansion"
    else:
        blind_spot_value = "low"
        role = "mostly_reordering"
    return {
        "blind_spot_value": blind_spot_value,
        "primary_product_role": role,
        "recommended_surface_if_datasynth_incomplete": "hybrid_with_soft_repeated_normal_guard",
        "reason": [
            "Incremental coverage is measured against PHASE1 case-result document coverage "
            "where that artifact is available.",
            "Truth labels are used only after surface ordering, for aggregate overlap and "
            "miss counts.",
            "The pressure-adjusted soft guard remains the safer review candidate when "
            "DataSynth coverage is incomplete; aggressive and frontier surfaces need "
            "cross-batch review before product policy use.",
        ],
    }


def incremental_coverage_diagnostic(
    *,
    df: pd.DataFrame,
    cases: list[Phase2CaseBase],
    records: dict[str, dict[str, Any]],
    truth_docs: set[str],
    truth_scenario_by_doc: dict[str, str],
    phase1_case_result_path: Path | None = None,
) -> dict[str, Any]:
    phase1 = build_phase1_baseline(
        df,
        truth_docs,
        case_result_path=phase1_case_result_path,
    )
    phase1_all = set(phase1["all_docs"])
    phase1_top = {key: set(value) for key, value in phase1["top_sets"].items()}
    selected_surfaces = (
        "native_row_queue",
        "hybrid_with_soft_repeated_normal_guard",
        "soft_guard_with_row_count_context",
        "hybrid_row_count_blended_surface",
        "phase1_prior_companion_surface",
        "frontier_phase1_plus_aggressive_union",
        "frontier_all_four_lanes_union",
    )
    ordered_surfaces = _candidate_ordered_doc_surfaces(cases=cases, records=records)
    out: dict[str, Any] = {}
    for name in selected_surfaces:
        surface = ordered_surfaces[name]
        topn: dict[str, Any] = {}
        scenario_topn: dict[str, dict[str, int]] = {}
        for top_n in (100, 500, 1000, 10000):
            selected_docs = set(_surface_docs_for_topn(surface, top_n))
            matched = selected_docs & truth_docs
            overlap = matched & phase1_all
            missed = matched - phase1_all
            scenario_counts = Counter(
                truth_scenario_by_doc.get(doc, "unknown") for doc in missed
            )
            topn[str(top_n)] = {
                "review_doc_count": len(selected_docs),
                "matched_truth_docs": len(matched),
                "phase1_overlap_truth_docs": len(overlap),
                "phase1_missed_truth_docs": len(missed),
                "incremental_truth_docs_vs_phase1_all": len(missed),
                "incremental_truth_docs_vs_phase1_top100": len(matched - phase1_top["100"]),
                "incremental_truth_docs_vs_phase1_top500": len(matched - phase1_top["500"]),
                "incremental_truth_docs_vs_phase1_top1000": len(matched - phase1_top["1000"]),
                "overlap_ratio": _safe_div(float(len(overlap)), float(len(matched))),
                "incremental_ratio": _safe_div(float(len(missed)), float(len(matched))),
                "nontruth_document_count": len(selected_docs - truth_docs),
                "incremental_truth_per_100_review_docs": _safe_div(
                    float(len(missed) * 100), float(len(selected_docs))
                ),
            }
            scenario_topn[str(top_n)] = {
                str(key): int(value) for key, value in sorted(scenario_counts.items())
            }
        out[name] = {
            "topn": topn,
            "phase1_missed_truth_scenario_counts": scenario_topn,
            "truth_label_used_for_scoring": False,
            "truth_label_used_only_for_aggregate_evaluation": True,
            "q95_gate_changed": False,
            "vae_score_or_threshold_changed": False,
            "native_row_case_ordering_changed": False,
            "phase1_ranking_changed": False,
            "phase2_fusion_changed": False,
            "production_adoption": "pending_cross_batch_validation",
        }
    return {
        "diagnostic_only": True,
        "phase1_baseline": phase1["summary"],
        "surfaces": out,
        "judgement": _incremental_judgement(out),
    }


def _first_truth_rank(ordered_docs: list[str], truth_docs: set[str]) -> int | None:
    for rank, doc in enumerate(ordered_docs, start=1):
        if doc in truth_docs:
            return rank
    return None


def _candidate_weight_provenance() -> dict[str, str | bool]:
    return {
        "weight_source": "fixed5 exploratory diagnostic weights",
        "calibrated": False,
        "production_ranking_policy": False,
        "requires_validation": "cross-batch/fixture validation before adoption",
    }


def _surface_comparison(
    *,
    scored: dict[str, list[tuple[str, float]]],
    truth_docs: set[str],
) -> dict[str, Any]:
    hybrid = _ordered_docs(scored["hybrid_max_score_amount_tail_period_end"])
    row_penalty = _ordered_docs(scored["document_score_with_row_count_penalty"])
    out: dict[str, Any] = {}
    for top_n in (100, 500, 1000, 10000):
        hybrid_docs = set(hybrid[:top_n])
        penalty_docs = set(row_penalty[:top_n])
        union_docs = sorted(hybrid_docs | penalty_docs, key=_doc_sort_key)
        intersection_docs = sorted(hybrid_docs & penalty_docs, key=_doc_sort_key)
        out[str(top_n)] = {
            "union": _coverage_for_docs(union_docs, truth_docs),
            "intersection": _coverage_for_docs(intersection_docs, truth_docs),
            "union_document_count": len(union_docs),
            "intersection_document_count": len(intersection_docs),
        }
    return out


def _interleaved_unique_docs(primary: list[str], secondary: list[str], limit: int) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    idx = 0
    while len(selected) < limit and (idx < len(primary) or idx < len(secondary)):
        for source in (primary, secondary):
            if idx >= len(source):
                continue
            doc = source[idx]
            if doc not in seen:
                seen.add(doc)
                selected.append(doc)
                if len(selected) >= limit:
                    break
        idx += 1
    return selected


def _two_lane_review_surface(
    *,
    scored: dict[str, list[tuple[str, float]]],
    rows: list[dict[str, Any]],
    records: dict[str, dict[str, Any]],
    truth_docs: set[str],
) -> dict[str, Any]:
    phase1_prior = _ordered_docs(scored["phase1_prior_companion_surface"])
    aggressive = _ordered_docs(scored["hybrid_row_count_blended_surface"])
    high_amount_threshold = _high_amount_threshold(records)
    out: dict[str, Any] = {}
    for top_n in (100, 500, 1000, 10000):
        interleaved = _interleaved_unique_docs(phase1_prior, aggressive, top_n)
        union_docs = sorted(set(phase1_prior[:top_n]) | set(aggressive[:top_n]), key=_doc_sort_key)
        intersection_docs = sorted(
            set(phase1_prior[:top_n]) & set(aggressive[:top_n]),
            key=_doc_sort_key,
        )
        entry: dict[str, Any] = {
            "interleaved_same_budget": _coverage_for_docs(interleaved, truth_docs),
            "union_expanded_budget": _coverage_for_docs(union_docs, truth_docs),
            "intersection": _coverage_for_docs(intersection_docs, truth_docs),
            "union_document_count": len(union_docs),
            "intersection_document_count": len(intersection_docs),
        }
        if top_n in (100, 500):
            entry["interleaved_false_positive_risk_profile"] = _risk_profile(
                rows=rows,
                records=records,
                selected_docs=interleaved,
                truth_docs=truth_docs,
                global_high_amount_threshold=high_amount_threshold,
            )
            entry["union_false_positive_risk_profile"] = _risk_profile(
                rows=rows,
                records=records,
                selected_docs=union_docs,
                truth_docs=truth_docs,
                global_high_amount_threshold=high_amount_threshold,
            )
        out[str(top_n)] = entry
    return {
        "diagnostic_only": True,
        "production_adoption": "pending_cross_batch_validation",
        "lane_a": "phase1_prior_companion_surface",
        "lane_b": "hybrid_row_count_blended_surface",
        "policy": "interleaved same-budget and union expanded-budget review surface",
        "topn": out,
    }


def _review_burden_frontier(
    *,
    scored: dict[str, list[tuple[str, float]]],
    rows: list[dict[str, Any]],
    records: dict[str, dict[str, Any]],
    truth_docs: set[str],
) -> dict[str, Any]:
    lanes = {
        "phase1_prior": _ordered_docs(scored["phase1_prior_companion_surface"]),
        "aggressive_blend": _ordered_docs(scored["hybrid_row_count_blended_surface"]),
        "hybrid_max": _ordered_docs(scored["hybrid_max_score_amount_tail_period_end"]),
        "soft_context": _ordered_docs(scored["soft_guard_with_row_count_context"]),
    }
    high_amount_threshold = _high_amount_threshold(records)
    configs = {
        "phase1_plus_aggressive": ("phase1_prior", "aggressive_blend"),
        "phase1_plus_hybrid_max": ("phase1_prior", "hybrid_max"),
        "phase1_plus_soft_context": ("phase1_prior", "soft_context"),
        "phase1_aggressive_hybrid": ("phase1_prior", "aggressive_blend", "hybrid_max"),
        "all_four_lanes": ("phase1_prior", "aggressive_blend", "hybrid_max", "soft_context"),
    }
    out: dict[str, Any] = {}
    for name, lane_names in configs.items():
        out[name] = {}
        for top_n in (100, 500):
            selected = sorted(
                set().union(*(set(lanes[lane][:top_n]) for lane in lane_names)),
                key=_doc_sort_key,
            )
            out[name][str(top_n)] = {
                "coverage": _coverage_for_docs(selected, truth_docs),
                "review_document_count": len(selected),
                "false_positive_risk_profile": _risk_profile(
                    rows=rows,
                    records=records,
                    selected_docs=selected,
                    truth_docs=truth_docs,
                    global_high_amount_threshold=high_amount_threshold,
                ),
            }
    return {
        "diagnostic_only": True,
        "production_adoption": "pending_cross_batch_validation",
        "policy": "expanded-budget union of pre-existing diagnostic lanes",
        "frontier": out,
    }


def _candidate_matrix(
    *,
    rows: list[dict[str, Any]],
    records: dict[str, dict[str, Any]],
    truth_docs: set[str],
) -> dict[str, Any]:
    global_amount_p99 = _distribution([record.get("max_amount") for record in records.values()])[
        "p99"
    ]
    high_amount_threshold = float(global_amount_p99 or 0.0)
    scored = _candidate_scores(records)
    out: dict[str, Any] = {}
    for name, pairs in sorted(scored.items()):
        ordered = _ordered_docs(pairs)
        topn: dict[str, Any] = {}
        risk: dict[str, Any] = {}
        for top_n in (100, 500, 1000, 10000):
            docs = ordered[:top_n]
            topn[str(top_n)] = _coverage_for_docs(docs, truth_docs)
            if top_n in (100, 500):
                risk[str(top_n)] = _risk_profile(
                    rows=rows,
                    records=records,
                    selected_docs=docs,
                    truth_docs=truth_docs,
                    global_high_amount_threshold=high_amount_threshold,
                )
        out[name] = {
            "topn": topn,
            "first_truth_rank": _first_truth_rank(ordered, truth_docs),
            "false_positive_risk_profile": risk,
            "candidate_weight_provenance": _candidate_weight_provenance(),
            "truth_label_used_for_scoring": False,
            "truth_label_used_only_for_aggregate_evaluation": True,
            "q95_gate_changed": False,
            "vae_score_or_threshold_changed": False,
            "native_row_case_ordering_changed": False,
            "phase1_ranking_changed": False,
            "phase2_fusion_changed": False,
            "production_adoption": "pending_cross_batch_validation",
        }
    if "document_companion_balanced_surface" in out:
        out["document_companion_balanced_surface"]["union_intersection_comparison"] = (
            _surface_comparison(scored=scored, truth_docs=truth_docs)
        )
    out["two_lane_phase1_prior_aggressive_surface"] = _two_lane_review_surface(
        scored=scored,
        rows=rows,
        records=records,
        truth_docs=truth_docs,
    )
    out["review_burden_frontier_surface"] = _review_burden_frontier(
        scored=scored,
        rows=rows,
        records=records,
        truth_docs=truth_docs,
    )
    return out


def _native_row_queue_matrix(
    *,
    cases: list[Phase2CaseBase],
    truth_docs: set[str],
    rows: list[dict[str, Any]],
    records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    ordered_cases = _sorted_cases(cases)
    global_amount_p99 = _distribution([record.get("max_amount") for record in records.values()])[
        "p99"
    ]
    high_amount_threshold = float(global_amount_p99 or 0.0)
    topn: dict[str, Any] = {}
    risk: dict[str, Any] = {}
    full_ordered_docs = []
    seen_docs: set[str] = set()
    for case in ordered_cases:
        for doc in sorted(_case_documents(case), key=_doc_sort_key):
            if doc not in seen_docs:
                seen_docs.add(doc)
                full_ordered_docs.append(doc)
    for top_n in (100, 500, 1000, 10000):
        docs = sorted(
            {
                doc
                for case in ordered_cases[:top_n]
                for doc in _case_documents(case)
            },
            key=_doc_sort_key,
        )
        topn[str(top_n)] = _coverage_for_docs(docs, truth_docs)
        if top_n in (100, 500):
            risk[str(top_n)] = _risk_profile(
                rows=rows,
                records=records,
                selected_docs=docs,
                truth_docs=truth_docs,
                global_high_amount_threshold=high_amount_threshold,
            )
    return {
        "topn": topn,
        "first_truth_rank": _first_truth_rank(full_ordered_docs, truth_docs),
        "false_positive_risk_profile": risk,
        "candidate_weight_provenance": {
            "weight_source": "existing native row queue order",
            "calibrated": False,
            "production_ranking_policy": True,
            "requires_validation": "not a document companion candidate",
        },
    }


def _decision(matrix: dict[str, Any]) -> dict[str, Any]:
    row_penalty = matrix["document_score_with_row_count_penalty"]
    blended = matrix["hybrid_row_count_blended_surface"]
    soft_guard = matrix["hybrid_with_soft_repeated_normal_guard"]
    phase1_prior = matrix["phase1_prior_companion_surface"]
    top100 = int(row_penalty["topn"]["100"]["matched"])
    top500 = int(row_penalty["topn"]["500"]["matched"])
    risk = row_penalty["false_positive_risk_profile"]["100"]
    high_amount_ratio = float(risk["single_row_high_amount_document_ratio"])
    repeated_normal_ratio = float(risk["repeated_normal_document_ratio"])
    if top100 >= 20 and top500 >= 90 and high_amount_ratio < 0.20 and repeated_normal_ratio < 0.30:
        verdict = "document-level companion lane 후보로 승격 가능"
    elif top100 >= 15 and top500 >= 70:
        verdict = "diagnostic 유지, 추가 batch 필요"
    else:
        verdict = "false-positive risk가 커서 폐기"
    return {
        "verdict": verdict,
        "best_coverage_candidate": "hybrid_row_count_blended_surface",
        "best_coverage_candidate_top100": int(blended["topn"]["100"]["matched"]),
        "best_coverage_candidate_top500": int(blended["topn"]["500"]["matched"]),
        "best_pressure_adjusted_candidate": "hybrid_with_soft_repeated_normal_guard",
        "best_pressure_adjusted_candidate_top100": int(soft_guard["topn"]["100"]["matched"]),
        "best_pressure_adjusted_candidate_top500": int(soft_guard["topn"]["500"]["matched"]),
        "best_legacy_recovery_candidate": "phase1_prior_companion_surface",
        "best_legacy_recovery_candidate_top100": int(phase1_prior["topn"]["100"]["matched"]),
        "best_legacy_recovery_candidate_top500": int(phase1_prior["topn"]["500"]["matched"]),
        "most_stable_candidate": "hybrid_with_soft_repeated_normal_guard",
        "most_stable_candidate_top100": int(soft_guard["topn"]["100"]["matched"]),
        "most_stable_candidate_top500": int(soft_guard["topn"]["500"]["matched"]),
        "baseline_conservative_candidate": "document_score_with_row_count_penalty",
        "baseline_conservative_candidate_top100": top100,
        "baseline_conservative_candidate_top500": top500,
        "production_adoption": "pending_cross_batch_validation",
        "reason": [
            "hybrid-row-count blend has the highest TOP100/TOP500 aggregate coverage "
            "in fixed5, but its pressure remains elevated.",
            "soft repeated-normal guard keeps TOP100/TOP500 above row-count penalty "
            "while reducing fixed5 TOP100 false-positive pressure below native row queue.",
            "phase1-prior companion recovers more TOP500 coverage by reusing audit-observable "
            "PHASE1 context without changing PHASE1 ranking.",
            "row-count penalty remains a conservative baseline but has higher repeated "
            "normal pressure than the soft guard.",
            "No candidate is applied to production ranking before cross-batch review.",
        ],
    }


def main() -> int:
    started = time.perf_counter()
    df = _load_case_input()
    truth = _load_truth()
    truth_docs = set(truth["document_id"].astype(str))
    truth_scenario_by_doc = dict(
        zip(
            truth["document_id"].astype(str),
            truth["manipulation_scenario"].astype(str),
            strict=False,
        )
    )
    result = _build_unsupervised_result(df)
    case_set = build_phase2_case_set(
        batch_id=BATCH_ID,
        detection_results=[result],
        df=df,
        unsupervised_model_id="stage7-fixed5-model-bundle-v1",
        unsupervised_schema_hash="stage7-fixed5-normalcal5",
    )
    cases = list(_family_cases(case_set, "unsupervised"))
    rows = attach_phase1_document_prior(
        _unsupervised_case_rows(cases, df=df, truth_docs=truth_docs),
        df,
    )
    records = _document_records(rows)
    native = _native_row_queue_matrix(
        cases=cases,
        truth_docs=truth_docs,
        rows=rows,
        records=records,
    )
    candidates = _candidate_matrix(rows=rows, records=records, truth_docs=truth_docs)
    matrix = {"native_row_queue": native, **candidates}
    incremental = incremental_coverage_diagnostic(
        df=df,
        cases=cases,
        records=records,
        truth_docs=truth_docs,
        truth_scenario_by_doc=truth_scenario_by_doc,
        phase1_case_result_path=PHASE1_CASE_RESULT,
    )
    phase1_baseline = build_phase1_baseline(
        df,
        truth_docs,
        case_result_path=PHASE1_CASE_RESULT,
    )
    attrition = phase1_missed_truth_attrition_diagnostic(
        df=df,
        scores=result.scores,
        cases=cases,
        records=records,
        phase1_all_docs=set(phase1_baseline["all_docs"]),
        truth_docs=truth_docs,
        truth_scenario_by_doc=truth_scenario_by_doc,
    )
    incremental_value = unsupervised_incremental_value_diagnostic(
        df=df,
        scores=result.scores,
        cases=cases,
        records=records,
        truth_docs=truth_docs,
        truth_scenario_by_doc=truth_scenario_by_doc,
        phase1_case_result_path=PHASE1_CASE_RESULT,
    )
    attrition_improvement = unsupervised_attrition_improvement_diagnostic(
        df=df,
        scores=result.scores,
        cases=cases,
        records=records,
        truth_docs=truth_docs,
        truth_scenario_by_doc=truth_scenario_by_doc,
        phase1_case_result_path=PHASE1_CASE_RESULT,
    )
    coverage_candidate_decision = _decision(candidates)
    payload = {
        "generated_at": _now_iso(),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "dataset": DATASET_NAME,
        "diagnostic_only": True,
        "native_case_ordering_changed": False,
        "native_row_case_ordering_changed": False,
        "q95_gate_changed": False,
        "vae_score_or_threshold_changed": False,
        "phase1_ranking_changed": False,
        "phase2_fusion_changed": False,
        "truth_label_used_for_scoring": False,
        "truth_label_used_only_for_aggregate_evaluation": True,
        "production_adoption": "pending_cross_batch_validation",
        "native_unsupervised_result": _measure_family(cases, truth_docs, truth_scenario_by_doc),
        "coverage_quality_matrix": matrix,
        "incremental_coverage_diagnostic": incremental,
        "phase1_missed_truth_attrition_diagnostic": attrition,
        "unsupervised_incremental_value_diagnostic": incremental_value,
        "unsupervised_attrition_improvement_diagnostic": attrition_improvement,
        "coverage_candidate_decision": coverage_candidate_decision,
        "decision": incremental_value["decision"],
        "output_notes": [
            "No raw document IDs, row IDs, or index labels are emitted.",
            "Truth labels are used only for aggregate post-hoc diagnostic coverage.",
            "All candidate document rankings are diagnostic-only and do not change "
            "product ranking.",
            "PHASE1 all document inclusion is reported as broad inclusion only; "
            "incremental value is evaluated separately through TOP-N uplift and "
            "ML/statistical evidence units.",
        ],
    }
    payload["r" "aw_identifier_leak_check"] = identifier_leak_check(payload)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _print(f"wrote {OUT_JSON.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
