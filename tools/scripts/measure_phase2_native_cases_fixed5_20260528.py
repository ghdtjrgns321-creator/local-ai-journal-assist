"""Measure PHASE2 native-case recall for fixed5_normalcal5.

This is the native-case counterpart to
``docs/DETECTION_RESULTS_MANIPULATION_V7_FIXED4_PHASE2.md``.  The legacy
document measured PHASE2 family lanes on PHASE1 case rows.  This script runs
current PHASE2 family detectors, builds ``Phase2CaseSet`` via the S3.next
orchestrator, and measures recall on family-native units:

- duplicate / intercompany: pair cases
- relational: edge cases
- unsupervised: outlier row cases
- timeseries: window cases

Only aggregate counts are written. Raw document IDs are used in-memory for
synthetic-truth matching and are not emitted.
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import pickle
import re
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config.settings import get_settings
from src.detection.base import DetectionResult
from src.detection.duplicate_detector import DuplicateDetector
from src.detection.intercompany_matcher import IntercompanyMatcher
from src.detection.relational_detector import RelationalDetector
from src.detection.timeseries_detector import TimeseriesDetector
from src.models.phase2_case import Phase2CaseBase, Phase2CaseSet
from src.services.phase2_case_set_orchestrator import build_phase2_case_set
from tools.scripts.phase2_family_correlation_audit import (
    _fast_time_shifted_duplicate,
    load_audit_rules,
    load_model_bundle,
    score_unsupervised,
)

DATASET_NAME = "datasynth_manipulation_v7_candidate_fixed5_normalcal5"
BATCH_ID = "fixed5_normalcal5_native_cases_20260528"
TOP_NS = (100, 500, 1000, 2000, 5000, 10000)
FAMILIES = ("unsupervised", "timeseries", "relational", "duplicate", "intercompany")

CASE_INPUT_PKL = ROOT / "artifacts" / "phase1_manipulation_v7_fixed5_normalcal5_case_input.pkl"
TRUTH_CSV = (
    ROOT
    / "data"
    / "journal"
    / "primary"
    / DATASET_NAME
    / "labels"
    / "manipulated_entry_truth.csv"
)
OUT_JSON = ROOT / "artifacts" / "phase2_native_case_remeasure_fixed5_20260528.json"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _print(message: str) -> None:
    print(f"[{_now_iso()}] {message}", flush=True)


def _load_case_input() -> pd.DataFrame:
    _print(f"loading case input: {_rel(CASE_INPUT_PKL)}")
    with CASE_INPUT_PKL.open("rb") as fh:
        payload = pickle.load(fh)
    df = payload["df"].copy()
    df["document_id"] = df["document_id"].astype(str)
    _print(f"  rows={len(df):,} documents={df['document_id'].nunique():,}")
    return df


def _load_truth() -> pd.DataFrame:
    truth = pd.read_csv(TRUTH_CSV)
    truth["document_id"] = truth["document_id"].astype(str)
    truth["manipulation_scenario"] = truth["manipulation_scenario"].astype(str)
    _print(f"  truth documents={truth['document_id'].nunique():,}")
    return truth


def _build_unsupervised_result(df: pd.DataFrame) -> DetectionResult:
    _print("scoring unsupervised")
    bundle = load_model_bundle()
    scores = score_unsupervised(df, bundle).reindex(df.index).fillna(0.0).astype(float)
    # The native-case builder requires a non-empty details frame. Top features are
    # unavailable in this Stage7 artifact path, so a dummy column preserves the
    # row-level gate while producing empty top_features.
    details = pd.DataFrame({"_stage7_native_measurement": 1}, index=df.index)
    return DetectionResult(
        track_name="ml_unsupervised",
        flagged_indices=[int(i) for i in np.flatnonzero(scores.to_numpy() > 0.0)],
        scores=scores,
        rule_flags=[],
        details=details,
        metadata={"display_name": "Unsupervised native-case measurement"},
    )


def _run_rule_detector(family: str, df: pd.DataFrame) -> DetectionResult:
    settings = get_settings()
    audit_rules = load_audit_rules()
    if family == "timeseries":
        detector = TimeseriesDetector(settings)
    elif family == "relational":
        detector = RelationalDetector(settings, audit_rules=audit_rules)
    elif family == "duplicate":
        import src.detection.duplicate_detector as duplicate_detector_module

        duplicate_detector_module.b05d_time_shifted_duplicate = _fast_time_shifted_duplicate
        detector = DuplicateDetector(settings)
    elif family == "intercompany":
        detector = IntercompanyMatcher(settings, audit_rules=audit_rules)
    else:
        raise ValueError(f"unknown family: {family}")
    _print(f"running detector: {family}")
    t0 = time.perf_counter()
    result = detector.detect(df)
    _print(
        f"  {family}: flagged={len(result.flagged_indices):,} "
        f"elapsed={time.perf_counter() - t0:.1f}s"
    )
    return result


def _run_detection_results(df: pd.DataFrame) -> list[DetectionResult]:
    return [
        _build_unsupervised_result(df),
        _run_rule_detector("timeseries", df),
        _run_rule_detector("relational", df),
        _run_rule_detector("duplicate", df),
        _run_rule_detector("intercompany", df),
    ]


def _tier_rank(case: Phase2CaseBase) -> int:
    return {"strong": 3, "moderate": 2, "ml_quantile": 1, "weak": 0}.get(
        str(case.evidence_tier).lower(),
        -1,
    )


def _sorted_cases(cases: Iterable[Phase2CaseBase]) -> list[Phase2CaseBase]:
    return sorted(
        cases,
        key=lambda c: (-_tier_rank(c), -float(c.family_score or 0.0), c.phase2_case_id),
    )


def _case_documents(case: Phase2CaseBase) -> set[str]:
    docs = {
        str(ref.document_id)
        for ref in case.row_refs
        if getattr(ref, "document_id", None) not in (None, "")
    }
    return docs


def _measure_family(
    cases: list[Phase2CaseBase],
    truth_docs: set[str],
    truth_scenario_by_doc: dict[str, str],
) -> dict[str, Any]:
    ordered = _sorted_cases(cases)
    case_doc_sets = [_case_documents(case) for case in ordered]
    out: dict[str, Any] = {
        "case_count": len(ordered),
        "docs_covered": len(set().union(*case_doc_sets)) if case_doc_sets else 0,
        "topn": {},
    }
    for top_n in TOP_NS:
        docs: set[str] = set()
        for doc_set in case_doc_sets[:top_n]:
            docs.update(doc_set)
        matched_docs = docs & truth_docs
        out["topn"][str(top_n)] = {
            "matched": len(matched_docs),
            "recall": len(matched_docs) / max(len(truth_docs), 1),
        }
    top100_docs: set[str] = set()
    top500_docs: set[str] = set()
    for doc_set in case_doc_sets[:100]:
        top100_docs.update(doc_set)
    for doc_set in case_doc_sets[:500]:
        top500_docs.update(doc_set)
    top100_counts = Counter(
        truth_scenario_by_doc[doc]
        for doc in (top100_docs & truth_docs)
        if doc in truth_scenario_by_doc
    )
    top500_counts = Counter(
        truth_scenario_by_doc[doc]
        for doc in (top500_docs & truth_docs)
        if doc in truth_scenario_by_doc
    )
    out["top100_scenario_counts"] = dict(sorted(top100_counts.items()))
    out["top500_scenario_counts"] = dict(sorted(top500_counts.items()))
    out["top100_type_count"] = len(top100_counts)
    out["top500_type_count"] = len(top500_counts)
    if top100_counts:
        scenario, count = top100_counts.most_common(1)[0]
        out["top100_primary_scenario"] = scenario
        out["top100_primary_share"] = count / max(sum(top100_counts.values()), 1)
    else:
        out["top100_primary_scenario"] = None
        out["top100_primary_share"] = 0.0
    if top500_counts:
        total = sum(top500_counts.values())
        shares = np.array([count / total for count in top500_counts.values()], dtype=float)
        hhi = float(np.square(shares).sum())
        out["top500_primary_share"] = float(shares.max())
        out["top500_hhi"] = hhi
        out["top500_effective_type_count"] = float(1.0 / hhi) if hhi else 0.0
    else:
        out["top500_primary_share"] = 0.0
        out["top500_hhi"] = 0.0
        out["top500_effective_type_count"] = 0.0
    return out


def _case_rank_diagnostics(
    cases: list[Phase2CaseBase],
    truth_docs: set[str],
) -> dict[str, Any]:
    """Aggregate rank placement diagnostics without emitting raw document IDs."""
    ordered = _sorted_cases(cases)
    first_truth_rank: int | None = None
    truth_ranks: list[int] = []
    truth_case_count = 0
    for rank, case in enumerate(ordered, start=1):
        if _case_documents(case) & truth_docs:
            truth_case_count += 1
            truth_ranks.append(rank)
            if first_truth_rank is None:
                first_truth_rank = rank
    if truth_ranks:
        rank_array = np.asarray(truth_ranks, dtype=float)
        rank_distribution = {
            "min": int(rank_array.min()),
            "p50": float(np.quantile(rank_array, 0.50)),
            "p90": float(np.quantile(rank_array, 0.90)),
            "max": int(rank_array.max()),
            "count": len(truth_ranks),
        }
        rank_buckets = {
            "top100": sum(1 for rank in truth_ranks if rank <= 100),
            "top500": sum(1 for rank in truth_ranks if rank <= 500),
            "top1000": sum(1 for rank in truth_ranks if rank <= 1000),
            "after1000": sum(1 for rank in truth_ranks if rank > 1000),
        }
    else:
        rank_distribution = {"min": None, "p50": None, "p90": None, "max": None, "count": 0}
        rank_buckets = {"top100": 0, "top500": 0, "top1000": 0, "after1000": 0}
    return {
        "first_truth_case_rank": first_truth_rank,
        "truth_covering_case_count": truth_case_count,
        "truth_rank_distribution": rank_distribution,
        "truth_rank_buckets": rank_buckets,
        "top100_gap_reason": "ranking_gap" if first_truth_rank and first_truth_rank > 100 else None,
        "top500_gap_reason": "ranking_gap" if first_truth_rank and first_truth_rank > 500 else None,
    }


def _window_kind(entry: dict[str, Any]) -> str:
    return (
        "single_day"
        if str(entry.get("window_start") or "") == str(entry.get("window_end") or "")
        else "trailing_window"
    )


def _case_window_kind(case: Phase2CaseBase) -> str:
    return (
        "single_day"
        if str(getattr(case, "window_start", "")) == str(getattr(case, "window_end", ""))
        else "trailing_window"
    )


def _ts_gap_reason(case: Phase2CaseBase) -> str:
    if getattr(case, "expected_count", None) is None:
        return "baseline_unavailable"
    robust_z = getattr(case, "robust_z", None)
    if robust_z is None or float(robust_z) <= 1.0:
        return "low_deviation_score"
    if bool(getattr(case, "period_end_context", False)):
        return "period_end_normalized_downrank"
    return "other"


def _numeric_distribution(values: list[float | int | None]) -> dict[str, Any]:
    clean = [float(value) for value in values if value is not None and np.isfinite(float(value))]
    if not clean:
        return {"count": 0, "min": None, "p50": None, "p90": None, "max": None}
    arr = np.asarray(clean, dtype=float)
    return {
        "count": int(len(arr)),
        "min": float(arr.min()),
        "p50": float(np.quantile(arr, 0.50)),
        "p90": float(np.quantile(arr, 0.90)),
        "max": float(arr.max()),
    }


def _document_frequency_distribution(counts: Iterable[int]) -> dict[str, Any]:
    return _numeric_distribution([int(count) for count in counts])


def _concentration_summary(values: Iterable[Any]) -> dict[str, Any]:
    cleaned = [str(value).strip() for value in values if str(value).strip()]
    if not cleaned:
        return {
            "count": 0,
            "unique_count": 0,
            "top1_count": 0,
            "top5_count": 0,
            "top10_count": 0,
            "top1_share": 0.0,
            "top5_share": 0.0,
            "top10_share": 0.0,
        }
    counts = Counter(cleaned)
    total = len(cleaned)
    top = counts.most_common(10)
    top1 = top[0][1] if top else 0
    top5 = sum(count for _value, count in top[:5])
    top10 = sum(count for _value, count in top[:10])
    return {
        "count": total,
        "unique_count": len(counts),
        "top1_count": top1,
        "top5_count": top5,
        "top10_count": top10,
        "top1_share": top1 / total,
        "top5_share": top5 / total,
        "top10_share": top10 / total,
    }


def _doc_sort_key(document_id: str) -> str:
    # Stable tie-break without emitting raw document identifiers.
    import hashlib

    return hashlib.sha256(document_id.encode("utf-8")).hexdigest()


def _case_single_doc(case: Phase2CaseBase) -> str | None:
    docs = sorted(_case_documents(case))
    return docs[0] if docs else None


def _row_amount(df: pd.DataFrame, row_position: int | None) -> float | None:
    if row_position is None or row_position < 0 or row_position >= len(df):
        return None
    candidates = []
    for column in ("debit_amount", "credit_amount", "amount", "local_amount"):
        if column in df.columns:
            value = pd.to_numeric(pd.Series([df[column].iat[row_position]]), errors="coerce").iloc[
                0
            ]
            if pd.notna(value):
                candidates.append(abs(float(value)))
    return max(candidates) if candidates else None


def _row_value(df: pd.DataFrame, row_position: int | None, column: str) -> Any:
    if (
        row_position is None
        or row_position < 0
        or row_position >= len(df)
        or column not in df.columns
    ):
        return None
    value = df[column].iat[row_position]
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _period_end_proximity_days(df: pd.DataFrame, row_position: int | None) -> int | None:
    value = _row_value(df, row_position, "posting_date")
    if value is None:
        return None
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    month_end = ts + pd.offsets.MonthEnd(0)
    return int(abs((month_end.normalize() - ts.normalize()).days))


def _group_row_count_by_document(df: pd.DataFrame) -> dict[str, int]:
    if "document_id" not in df.columns:
        return {}
    docs = df["document_id"].fillna("").astype(str).str.strip()
    return docs[docs != ""].value_counts().astype(int).to_dict()


def _unsupervised_case_rows(
    cases: list[Phase2CaseBase],
    *,
    df: pd.DataFrame,
    truth_docs: set[str],
) -> list[dict[str, Any]]:
    ordered = _sorted_cases(cases)
    rows: list[dict[str, Any]] = []
    doc_row_counts = _group_row_count_by_document(df)
    for rank, case in enumerate(ordered, start=1):
        doc = _case_single_doc(case)
        ref = case.row_refs[0] if case.row_refs else None
        row_position = getattr(ref, "row_position", None) if ref is not None else None
        rows.append(
            {
                "rank": rank,
                "case": case,
                "document_id": doc,
                "is_truth_doc": doc in truth_docs if doc is not None else False,
                "family_score": float(case.family_score or 0.0),
                "family_ecdf": float(case.family_ecdf or 0.0),
                "amount": _row_amount(df, row_position),
                "fiscal_period": _row_value(df, row_position, "fiscal_period"),
                "period_end_proximity_days": _period_end_proximity_days(df, row_position),
                "account": _row_value(df, row_position, "gl_account"),
                "process": _row_value(df, row_position, "business_process"),
                "document_row_count": doc_row_counts.get(str(doc), 0) if doc else 0,
            }
        )
    return rows


def _case_group_distribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "case_rank_distribution": _numeric_distribution([row["rank"] for row in rows]),
        "family_score_quantiles": _numeric_distribution([row["family_score"] for row in rows]),
        "family_ecdf_quantiles": _numeric_distribution([row["family_ecdf"] for row in rows]),
        "row_amount_quantiles": _numeric_distribution([row["amount"] for row in rows]),
        "fiscal_period_distribution": {
            str(period): int(count)
            for period, count in sorted(
                Counter(
                    int(row["fiscal_period"])
                    for row in rows
                    if row.get("fiscal_period") is not None
                    and str(row.get("fiscal_period")).strip() != ""
                ).items()
            )
        },
        "period_end_proximity_days_quantiles": _numeric_distribution(
            [row["period_end_proximity_days"] for row in rows]
        ),
        "account_concentration": _concentration_summary(row["account"] for row in rows),
        "process_concentration": _concentration_summary(row["process"] for row in rows),
        "document_row_count_distribution": _numeric_distribution(
            [row["document_row_count"] for row in rows]
        ),
    }


def _document_aggregation_inputs(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    docs: dict[str, dict[str, Any]] = {}
    for row in rows:
        doc = row.get("document_id")
        if not doc:
            continue
        entry = docs.setdefault(
            str(doc),
            {
                "scores": [],
                "ecdfs": [],
                "case_count": 0,
                "document_row_count": int(row.get("document_row_count") or 0),
                "accounts": set(),
                "processes": set(),
                "is_truth_doc": bool(row.get("is_truth_doc")),
            },
        )
        entry["scores"].append(float(row["family_score"]))
        entry["ecdfs"].append(float(row["family_ecdf"]))
        entry["case_count"] += 1
        if row.get("account") is not None:
            entry["accounts"].add(str(row["account"]))
        if row.get("process") is not None:
            entry["processes"].add(str(row["process"]))
        entry["is_truth_doc"] = bool(entry["is_truth_doc"] or row.get("is_truth_doc"))
    return docs


def _top_k_mean(values: list[float], k: int) -> float:
    if not values:
        return 0.0
    top = sorted(values, reverse=True)[:k]
    return float(np.mean(top)) if top else 0.0


def _score_document_aggregations(
    docs: dict[str, dict[str, Any]],
) -> dict[str, list[tuple[str, float]]]:
    scored: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for doc, entry in docs.items():
        scores = [float(value) for value in entry["scores"]]
        ecdfs = [float(value) for value in entry["ecdfs"]]
        case_count = int(entry["case_count"])
        row_count = max(int(entry["document_row_count"] or 1), 1)
        diversity = max(len(entry["accounts"]) + len(entry["processes"]), 1)
        max_score = max(scores) if scores else 0.0
        max_ecdf = max(ecdfs) if ecdfs else 0.0
        scored["document_max_score"].append((doc, max_score))
        scored["document_top_k_mean_score_k3"].append((doc, _top_k_mean(scores, 3)))
        scored["document_top_k_mean_score_k5"].append((doc, _top_k_mean(scores, 5)))
        scored["document_case_count_weighted_score"].append(
            (doc, max_score * float(np.log1p(case_count)))
        )
        scored["document_ecdf_max"].append((doc, max_ecdf))
        scored["document_score_with_row_count_penalty"].append(
            (doc, max_score / float(np.sqrt(row_count)))
        )
        scored["document_score_with_diversity_penalty"].append(
            (doc, max_score / float(np.sqrt(diversity)))
        )
    return dict(scored)


def _document_aggregation_diagnostic(
    rows: list[dict[str, Any]],
    *,
    truth_docs: set[str],
) -> dict[str, Any]:
    docs = _document_aggregation_inputs(rows)
    scored = _score_document_aggregations(docs)
    out: dict[str, Any] = {
        "diagnostic_only": True,
        "native_case_ordering_changed": False,
        "candidate_rankings": {},
    }
    for name, pairs in sorted(scored.items()):
        ordered = sorted(pairs, key=lambda item: (-item[1], _doc_sort_key(item[0])))
        topn: dict[str, Any] = {}
        for top_n in (100, 500, 1000, 10000):
            selected = {doc for doc, _score in ordered[:top_n]}
            matched = len(selected & truth_docs)
            topn[str(top_n)] = {
                "matched": matched,
                "recall": matched / max(len(truth_docs), 1),
            }
        out["candidate_rankings"][name] = {
            "topn": topn,
            "document_count": len(ordered),
        }
    return out


def _unsupervised_native_diagnostics(
    *,
    cases: list[Phase2CaseBase],
    truth_docs: set[str],
    df: pd.DataFrame,
) -> dict[str, Any]:
    rows = _unsupervised_case_rows(cases, df=df, truth_docs=truth_docs)
    docs_by_rank: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        doc = row.get("document_id")
        if doc:
            docs_by_rank[str(doc)].append(int(row["rank"]))

    docs_covered = set(docs_by_rank)
    truth_docs_covered = docs_covered & truth_docs
    truth_case_ranks = [int(row["rank"]) for row in rows if row["is_truth_doc"]]
    truth_doc_best_ranks = [min(docs_by_rank[doc]) for doc in truth_docs_covered]
    truth_rows = [row for row in rows if row["is_truth_doc"]]
    nontruth_rows = [row for row in rows if not row["is_truth_doc"]]
    case_counts_per_doc = {doc: len(ranks) for doc, ranks in docs_by_rank.items()}
    truth_counts = [case_counts_per_doc[doc] for doc in truth_docs_covered]
    nontruth_counts = [
        count for doc, count in case_counts_per_doc.items() if doc not in truth_docs
    ]

    truth_docs_in_topn: dict[str, int] = {}
    for top_n in TOP_NS:
        docs = {str(row["document_id"]) for row in rows[:top_n] if row.get("document_id")}
        truth_docs_in_topn[str(top_n)] = len(docs & truth_docs)

    return {
        "total_unsupervised_cases": len(rows),
        "unique_docs_covered_by_cases": len(docs_covered),
        "truth_docs_covered_by_all_cases": len(truth_docs_covered),
        "truth_docs_in_topn": truth_docs_in_topn,
        "first_truth_case_rank": min(truth_case_ranks) if truth_case_ranks else None,
        "truth_case_rank_distribution": _numeric_distribution(truth_case_ranks),
        "truth_doc_best_rank_distribution": _numeric_distribution(truth_doc_best_ranks),
        "cases_per_document_distribution": _document_frequency_distribution(
            case_counts_per_doc.values()
        ),
        "truth_cases_per_document_distribution": _document_frequency_distribution(truth_counts),
        "nontruth_cases_per_document_distribution": _document_frequency_distribution(
            nontruth_counts
        ),
        "score_rank_distribution_comparison": {
            "truth_covering_row_cases": _case_group_distribution(truth_rows),
            "nontruth_row_cases": _case_group_distribution(nontruth_rows),
        },
        "document_aggregation_experiment": _document_aggregation_diagnostic(
            rows,
            truth_docs=truth_docs,
        ),
        "diagnostic_notes": [
            "Truth labels are used only after native cases are built, for aggregate diagnostics.",
            "Document-level candidate rankings are offline diagnostics and do not alter "
            "native row case ordering.",
            "No raw document identifiers are emitted.",
        ],
    }


def _top500_period_end_comparison(
    cases: list[Phase2CaseBase],
    truth_docs: set[str],
) -> dict[str, Any]:
    ordered = _sorted_cases(cases)
    top500_period_end = [
        case for case in ordered[:500] if bool(getattr(case, "period_end_context", False))
    ]
    truth_cases = [case for case in ordered if _case_documents(case) & truth_docs]
    first_truth_case = truth_cases[0] if truth_cases else None
    robust_dist = _numeric_distribution(
        [getattr(case, "robust_z", None) for case in top500_period_end]
    )
    lift_dist = _numeric_distribution(
        [getattr(case, "period_end_lift", None) for case in top500_period_end]
    )
    context_dist = _numeric_distribution(
        [getattr(case, "context_evidence_count", None) for case in top500_period_end]
    )
    subject_rank_dist = _numeric_distribution(
        [getattr(case, "subject_activity_rank", None) for case in top500_period_end]
    )
    reason = None
    if first_truth_case is not None:
        truth_robust = getattr(first_truth_case, "robust_z", None)
        truth_lift = getattr(first_truth_case, "period_end_lift", None)
        truth_context = getattr(first_truth_case, "context_evidence_count", None)
        truth_subject_rank = getattr(first_truth_case, "subject_activity_rank", None)
        robust_above_top500_p50 = (
            truth_robust is not None
            and robust_dist["p50"] is not None
            and float(truth_robust) > float(robust_dist["p50"])
        )
        context_above_top500_p50 = (
            truth_context is not None
            and context_dist["p50"] is not None
            and float(truth_context) > float(context_dist["p50"])
        )
        if (
            bool(getattr(first_truth_case, "period_end_context", False))
            and truth_lift is not None
            and lift_dist["p50"] is not None
            and float(truth_lift) <= float(lift_dist["p50"])
        ):
            reason = (
                "mixed_period_end_context"
                if robust_above_top500_p50 or context_above_top500_p50
                else "period_end_lift_below_top500_median"
            )
        elif (
            truth_context is not None
            and context_dist["p50"] is not None
            and float(truth_context) < float(context_dist["p50"])
        ):
            reason = "insufficient_context_evidence"
        elif (
            truth_robust is not None
            and robust_dist["p50"] is not None
            and float(truth_robust) < float(robust_dist["p50"])
        ):
            reason = "lower_robust_z_than_top_windows"
        elif (
            truth_subject_rank is not None
            and subject_rank_dist["p50"] is not None
            and float(truth_subject_rank) <= float(subject_rank_dist["p50"])
        ):
            reason = "more_active_subject_background"
        else:
            reason = "other"
    return {
        "top500_period_end_case_count": len(top500_period_end),
        "robust_z_distribution": robust_dist,
        "period_end_lift_distribution": lift_dist,
        "context_evidence_count_distribution": context_dist,
        "subject_activity_rank_distribution": subject_rank_dist,
        "truth_case_lower_rank_reason": reason,
    }


def _top_truth_covering_ts_cases(
    cases: list[Phase2CaseBase],
    truth_docs: set[str],
    *,
    limit: int = 10,
) -> tuple[list[dict[str, Any]], Counter[str]]:
    ordered = _sorted_cases(cases)
    top_cases: list[dict[str, Any]] = []
    gap_reasons: Counter[str] = Counter()
    for rank, case in enumerate(ordered, start=1):
        if not (_case_documents(case) & truth_docs):
            continue
        reason = _ts_gap_reason(case)
        if rank > 500:
            gap_reasons[reason] += 1
        if len(top_cases) < limit:
            top_cases.append(
                {
                    "rank": rank,
                    "rule_id": str(getattr(case, "sub_rule", "")),
                    "window_kind": _case_window_kind(case),
                    "subject": str(getattr(case, "subject", "")),
                    "daily_count": int(getattr(case, "daily_count", 0) or 0),
                    "window_count": getattr(case, "window_count", None),
                    "expected_count": getattr(case, "expected_count", None),
                    "robust_z": getattr(case, "robust_z", None),
                    "period_end_context": bool(getattr(case, "period_end_context", False)),
                    "period_end_day_offset": getattr(case, "period_end_day_offset", None),
                    "subject_period_end_historical_ratio": getattr(
                        case,
                        "subject_period_end_historical_ratio",
                        None,
                    ),
                    "subject_non_period_end_baseline_count": getattr(
                        case,
                        "subject_non_period_end_baseline_count",
                        None,
                    ),
                    "period_end_expected_count": getattr(case, "period_end_expected_count", None),
                    "period_end_lift": getattr(case, "period_end_lift", None),
                    "amount_tail_context": getattr(case, "amount_tail_context", None),
                    "manual_or_adjustment_context": getattr(
                        case,
                        "manual_or_adjustment_context",
                        None,
                    ),
                    "after_hours_or_weekend_context": getattr(
                        case,
                        "after_hours_or_weekend_context",
                        None,
                    ),
                    "round_amount_context": getattr(case, "round_amount_context", None),
                    "rarity_context_count": getattr(case, "rarity_context_count", None),
                    "context_evidence_count": getattr(case, "context_evidence_count", None),
                    "subject_activity_rank": getattr(case, "subject_activity_rank", None),
                    "family_score": float(getattr(case, "family_score", 0.0) or 0.0),
                    "top500_gap_reason": reason if rank > 500 else None,
                }
            )
    return top_cases, gap_reasons


def _timeseries_native_diagnostics(
    *,
    detection_result: DetectionResult,
    cases: list[Phase2CaseBase],
    truth_docs: set[str],
    df_len: int,
) -> dict[str, Any]:
    """Explain TS native evidence-unit creation and ranking gaps.

    The output is aggregate-only: no raw document IDs, amounts, score thresholds, or
    raw score values are written. It separates artifact creation shortage from
    lane ranking placement.
    """
    metadata = getattr(detection_result, "metadata", None) or {}
    artifact = metadata.get("timeseries_window_artifact")
    windows = artifact.get("windows", []) if isinstance(artifact, dict) else []
    valid_windows = [entry for entry in windows if isinstance(entry, dict)]

    by_rule: Counter[str] = Counter()
    by_kind: Counter[str] = Counter()
    by_rule_kind: dict[str, Counter[str]] = defaultdict(Counter)
    by_subject: Counter[str] = Counter()
    sub_signal_high_counts: Counter[str] = Counter()
    evidence_tiers: Counter[str] = Counter()
    expected_count_states: Counter[str] = Counter()
    expected_count_case_states: Counter[str] = Counter()
    baseline_window_count = 0
    excluded_reasons: Counter[str] = Counter()
    represented_positions: set[int] = set()

    for entry in valid_windows:
        rule_id = str(entry.get("rule_id") or "unknown")
        kind = _window_kind(entry)
        subject = str(entry.get("subject") or "unknown")
        tier = str(entry.get("evidence_tier") or "unknown")
        sub_signal_high = bool(entry.get("sub_signal_high"))
        positions = entry.get("row_positions") or []

        by_rule[rule_id] += 1
        by_kind[kind] += 1
        by_rule_kind[rule_id][kind] += 1
        by_subject[subject] += 1
        sub_signal_high_counts[str(sub_signal_high)] += 1
        evidence_tiers[tier] += 1
        if entry.get("expected_count") is None:
            expected_count_states["none"] += 1
        else:
            expected_count_states["provided"] += 1
            baseline_window_count += 1

        for position in positions:
            try:
                represented_positions.add(int(position))
            except (TypeError, ValueError):
                pass

        if tier not in {"strong", "moderate"}:
            excluded_reasons["tier_not_case_grade"] += 1
        elif not sub_signal_high:
            excluded_reasons["sub_signal_high_false"] += 1
        elif not positions:
            excluded_reasons["missing_row_positions"] += 1

    case_counts_by_rule = Counter(
        str(getattr(case, "sub_rule", "unknown") or "unknown") for case in cases
    )
    case_counts_by_kind = Counter(
        "single_day"
        if str(getattr(case, "window_start", "")) == str(getattr(case, "window_end", ""))
        else "trailing_window"
        for case in cases
    )
    for case in cases:
        expected_count_case_states[
            "none" if getattr(case, "expected_count", None) is None else "provided"
        ] += 1

    flagged_positions = {
        int(pos)
        for pos in getattr(detection_result, "flagged_indices", [])
        if isinstance(pos, (int, np.integer)) and 0 <= int(pos) < df_len
    }
    flagged_without_window = max(len(flagged_positions - represented_positions), 0)

    rank_diag = _case_rank_diagnostics(cases, truth_docs)
    top_truth_cases, truth_gap_reasons = _top_truth_covering_ts_cases(cases, truth_docs)
    period_end_comparison = _top500_period_end_comparison(cases, truth_docs)
    if not cases:
        primary_gap = "artifact_generation_gap"
    elif rank_diag["first_truth_case_rank"] is None:
        primary_gap = "artifact_truth_coverage_gap"
    elif rank_diag["first_truth_case_rank"] > 500:
        primary_gap = "ranking_gap"
    else:
        primary_gap = "top500_covered"

    return {
        "raw_flagged_rows": len(getattr(detection_result, "flagged_indices", []) or []),
        "artifact_window_count": len(valid_windows),
        "case_count": len(cases),
        "artifact_windows_by_rule": dict(sorted(by_rule.items())),
        "artifact_windows_by_kind": dict(sorted(by_kind.items())),
        "artifact_windows_by_rule_kind": {
            rule: dict(sorted(kind_counts.items()))
            for rule, kind_counts in sorted(by_rule_kind.items())
        },
        "case_count_by_rule": dict(sorted(case_counts_by_rule.items())),
        "case_count_by_kind": dict(sorted(case_counts_by_kind.items())),
        "subject_top10": dict(by_subject.most_common(10)),
        "sub_signal_high_counts": dict(sorted(sub_signal_high_counts.items())),
        "evidence_tier_counts": dict(sorted(evidence_tiers.items())),
        "expected_count_state_windows": dict(sorted(expected_count_states.items())),
        "expected_count_state_cases": dict(sorted(expected_count_case_states.items())),
        "baseline_available_window_count": baseline_window_count,
        "baseline_available_case_count": expected_count_case_states.get("provided", 0),
        "expected_count_none_ratio_windows": (
            expected_count_states.get("none", 0) / len(valid_windows) if valid_windows else None
        ),
        "expected_count_none_ratio_cases": (
            expected_count_case_states.get("none", 0) / len(cases) if cases else None
        ),
        "builder_excluded_window_reasons": dict(sorted(excluded_reasons.items())),
        "flagged_rows_without_artifact_window": flagged_without_window,
        "primary_gap_classification": primary_gap,
        "top_truth_covering_cases": top_truth_cases,
        "top500_truth_miss_reasons": dict(sorted(truth_gap_reasons.items())),
        "period_end_disambiguation_comparison": period_end_comparison,
        **rank_diag,
        "diagnostic_notes": [
            "expected_count=None means no baseline was calculated; it is not a zero fallback.",
            "sub_signal_high=False windows are not promoted to native review candidate cases.",
            "Only aggregate evidence-unit diagnostics are emitted.",
        ],
    }


def _family_cases(case_set: Phase2CaseSet, family: str) -> tuple[Phase2CaseBase, ...]:
    return tuple(getattr(case_set, f"{family}_cases"))


def _scenario_matrix(
    measured: dict[str, dict[str, Any]],
    truth: pd.DataFrame,
) -> dict[str, dict[str, Any]]:
    scenario_truth_counts = (
        truth.groupby("manipulation_scenario")["document_id"].nunique().to_dict()
    )
    matrix: dict[str, dict[str, Any]] = {}
    for scenario, truth_n in sorted(scenario_truth_counts.items()):
        row: dict[str, Any] = {"truth_n": int(truth_n)}
        for family in FAMILIES:
            count = int(measured[family]["top500_scenario_counts"].get(scenario, 0))
            row[family] = {
                "matched": count,
                "scenario_recall": count / max(int(truth_n), 1),
            }
        matrix[str(scenario)] = row
    return matrix


def _walk_json_keys(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from _walk_json_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json_keys(child)


def _raw_identifier_leak_report(
    payload: dict[str, Any],
    *,
    truth_docs: set[str],
) -> dict[str, int]:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    forbidden_keys = {
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
    return {
        "doc_like_token_count": sum(1 for document_id in truth_docs if document_id in text),
        "forbidden_identifier_key_count": sum(
            1 for key in _walk_json_keys(payload) if str(key) in forbidden_keys
        ),
        "phase2_case_id_like_token_count": len(re.findall(r"p2_timeseries_window_", text)),
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
    detection_results = _run_detection_results(df)
    detection_result_by_track = {
        getattr(result, "track_name", ""): result for result in detection_results
    }
    _print("building PHASE2 native case set")
    case_set = build_phase2_case_set(
        batch_id=BATCH_ID,
        detection_results=detection_results,
        df=df,
        unsupervised_model_id="stage7-fixed5-model-bundle-v1",
        unsupervised_schema_hash="stage7-fixed5-normalcal5",
    )
    measured = {
        family: _measure_family(
            list(_family_cases(case_set, family)),
            truth_docs,
            truth_scenario_by_doc,
        )
        for family in FAMILIES
    }
    family_diagnostics = {
        "unsupervised": _unsupervised_native_diagnostics(
            cases=list(_family_cases(case_set, "unsupervised")),
            truth_docs=truth_docs,
            df=df,
        ),
        "timeseries": _timeseries_native_diagnostics(
            detection_result=detection_result_by_track["timeseries"],
            cases=list(_family_cases(case_set, "timeseries")),
            truth_docs=truth_docs,
            df_len=len(df),
        )
    }
    payload = {
        "generated_at": _now_iso(),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "dataset": DATASET_NAME,
        "measurement_contract": (
            "PHASE2 native case family queues. Cases sorted by evidence_tier "
            "(strong > moderate > ml_quantile > weak), family_score desc, "
            "phase2_case_id. Recall counts unique synthetic truth document_id covered "
            "by row_refs in TOP-N native cases."
        ),
        "top_ns": list(TOP_NS),
        "truth_document_count": len(truth_docs),
        "row_count": len(df),
        "document_count": int(df["document_id"].nunique()),
        "family_results": measured,
        "family_diagnostics": family_diagnostics,
        "top500_scenario_matrix": _scenario_matrix(measured, truth),
        "case_counts": {family: measured[family]["case_count"] for family in FAMILIES},
        "output_notes": [
            "No raw document identifiers are written to this aggregate JSON.",
            "Unsupervised top_features are unavailable in the Stage7 measurement path; "
            "native unsupervised cases are measured by row score and ECDF gate.",
            "Unsupervised score remeasurement uses deterministic posterior-mean VAE "
            "reconstruction, not stochastic latent sampling; q95-boundary aggregate "
            "counts may still drift slightly across environments/runs, so smoke checks "
            "use a bounded measurement band for unsupervised.",
        ],
    }
    payload["raw_identifier_leak_check"] = _raw_identifier_leak_report(
        payload,
        truth_docs=truth_docs,
    )
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _print(f"wrote {_rel(OUT_JSON)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
