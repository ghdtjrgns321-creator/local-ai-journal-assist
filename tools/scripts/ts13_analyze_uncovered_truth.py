"""TS-13 analysis: PHASE1 uncovered truth documents in V7 fixed3.

This script reads the synthetic V7 fixed3 truth labels, existing PHASE1/PHASE2
artifacts, and writes aggregate TS-13 outputs. It does not modify PHASE1 code or
fit thresholds to truth labels.
"""

# ruff: noqa: E402, E501, I001

from __future__ import annotations

import argparse
import json
import pickle
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.detection.rule_detail_metadata import (
    CANONICAL_TRANSACTION_RULE_IDS,
    LOCKED_NO_STANDALONE_COPY_RULE_IDS,
)
from tools.scripts import phase1_phase2_integration_stage7 as stage7


OUT_JSON = ROOT / "artifacts" / "ts13_uncovered_truth_80_analysis.json"
OUT_MD = ROOT / "artifacts" / "ts13_recovery_path_evaluation.md"

DIMENSIONS = [
    "fiscal_year",
    "company_code",
    "business_process",
    "source",
    "user_persona",
]

AMOUNT_BINS = [-np.inf, 10_000_000, 50_000_000, 100_000_000, 500_000_000, np.inf]
AMOUNT_LABELS = ["<=10M", "10M-50M", "50M-100M", "100M-500M", ">500M"]


RULE_INPUT_COLUMNS: dict[str, list[str]] = {
    "L1-01": ["document_id", "debit_amount", "credit_amount"],
    "L1-02": ["document_id", "gl_account", "posting_date", "debit_amount", "credit_amount"],
    "L1-03": ["gl_account"],
    "L1-04": ["document_approval_amount", "approver_limit_amount", "approval_limit_resolved"],
    "L1-05": ["created_by", "approved_by", "source", "local_amount"],
    "L1-06": ["created_by", "approved_by", "business_process"],
    "L1-07": ["approval_date", "source"],
    "L1-08": ["posting_date", "fiscal_year", "fiscal_period"],
    "L1-09": ["approval_date", "document_approval_amount", "source"],
    "L2-01": ["document_approval_amount", "near_threshold_limit_amount", "near_threshold_gap_ratio"],
    "L2-02": ["reference", "local_amount", "auxiliary_account_number"],
    "L2-03": ["document_id", "reference", "local_amount", "posting_date"],
    "L2-04": ["gl_account", "business_process", "line_text", "local_amount"],
    "L2-05": ["document_id", "gl_account", "debit_amount", "credit_amount", "posting_date"],
    "L3-01": ["business_process", "gl_account"],
    "L3-02": ["source", "document_type"],
    "L3-03": ["company_code", "trading_partner", "gl_account", "is_intercompany"],
    "L3-04": ["posting_date", "source", "is_period_end"],
    "L3-05": ["posting_date", "is_weekend", "is_holiday"],
    "L3-06": ["posting_date", "is_after_hours", "source"],
    "L3-07": ["posting_date", "document_date", "days_backdated"],
    "L3-08": ["line_text", "header_text", "description_quality"],
    "L3-09": ["gl_account", "line_text", "is_suspense_account"],
    "L3-10": ["gl_account", "business_process", "line_text"],
    "L3-11": ["posting_date", "document_date", "delivery_date"],
    "L3-12": ["created_by", "business_process", "gl_account"],
    "L4-01": ["gl_account", "local_amount", "is_revenue_account"],
    "L4-02": ["gl_account", "local_amount", "first_digit"],
    "L4-03": ["gl_account", "local_amount", "amount_zscore", "amount_magnitude"],
    "L4-04": ["gl_account", "business_process", "auxiliary_account_number"],
    "L4-05": ["created_by", "posting_date", "is_after_hours"],
    "L4-06": ["local_amount", "is_round_number", "source"],
}

NOMINAL_RULE_THRESHOLDS: dict[str, float | str] = {
    rule_id: 0.45 for rule_id in CANONICAL_TRANSACTION_RULE_IDS
}
NOMINAL_RULE_THRESHOLDS.update(
    {
        "L1-01": "tolerance / imbalance ratio",
        "L1-02": "required field null",
        "L4-02": "macro-only account/month Benford finding",
        "L3-05": "booster-only, no standalone case seed",
        "L3-06": "booster-only, no standalone case seed",
        "L3-08": "booster-only, no standalone case seed",
        "L3-10": "booster-only unless priority context",
        "L3-12": "review-only work-scope context",
        "L4-05": "booster-only concentration signal",
        "L4-06": "combo-only round amount context",
    }
)


def pct(part: int | float, whole: int | float) -> float:
    return round(float(part) / float(whole) * 100.0, 2) if whole else 0.0


def split_queue_docs(queue: pd.DataFrame) -> set[str]:
    docs: set[str] = set()
    for value in queue["document_ids_joined"].dropna().astype(str):
        docs.update(piece for piece in value.split(";") if piece)
    return docs


def count_table(series: pd.Series, denominator: int) -> list[dict[str, Any]]:
    counts = series.fillna("<NULL>").astype(str).value_counts(dropna=False)
    return [
        {"value": idx, "count": int(count), "pct": pct(int(count), denominator)}
        for idx, count in counts.items()
    ]


def compare_distribution(
    total: pd.DataFrame,
    uncovered: pd.DataFrame,
    column: str,
) -> list[dict[str, Any]]:
    total_counts = total[column].fillna("<NULL>").astype(str).value_counts(dropna=False)
    uncovered_counts = uncovered[column].fillna("<NULL>").astype(str).value_counts(dropna=False)
    values = sorted(set(total_counts.index) | set(uncovered_counts.index))
    return [
        {
            column: value,
            "truth_total_count": int(total_counts.get(value, 0)),
            "truth_total_pct": pct(int(total_counts.get(value, 0)), len(total)),
            "uncovered_count": int(uncovered_counts.get(value, 0)),
            "uncovered_pct": pct(int(uncovered_counts.get(value, 0)), len(uncovered)),
            "uncovered_rate_within_value": pct(
                int(uncovered_counts.get(value, 0)), int(total_counts.get(value, 0))
            ),
        }
        for value in values
    ]


def amount_stats(series: pd.Series) -> dict[str, Any]:
    numeric = pd.to_numeric(series, errors="coerce").abs().dropna()
    if numeric.empty:
        return {"count": 0}
    binned = pd.cut(numeric, bins=AMOUNT_BINS, labels=AMOUNT_LABELS)
    return {
        "count": int(numeric.size),
        "mean": round(float(numeric.mean()), 2),
        "median": round(float(numeric.median()), 2),
        "p90": round(float(numeric.quantile(0.90)), 2),
        "p95": round(float(numeric.quantile(0.95)), 2),
        "min": round(float(numeric.min()), 2),
        "max": round(float(numeric.max()), 2),
        "bins": count_table(binned.astype(str), int(numeric.size)),
    }


def load_phase2_by_doc(df: pd.DataFrame, regenerate: bool) -> tuple[pd.DataFrame, str]:
    if regenerate:
        bundle = pickle.loads(stage7.BUNDLE_PATH.read_bytes())
        _, phase2_ecdf = stage7.score_phase2(df, bundle)
        return stage7.aggregate_phase2_by_document(phase2_ecdf, df["document_id"]), "score_phase2_regenerated"
    return pd.read_parquet(stage7.PHASE2_CACHE), "stage7_phase2_by_doc_cache"


def build_rule_scores_by_doc(df: pd.DataFrame, detection_results: list[Any]) -> pd.DataFrame:
    detail_frames: list[pd.DataFrame] = []
    for result in detection_results:
        details = result.details.copy()
        details = details.apply(pd.to_numeric, errors="coerce").fillna(0.0)
        detail_frames.append(details)
    rule_details = pd.concat(detail_frames, axis=1)
    # Canonicalize L2-03 internal detail columns if they are present in future artifacts.
    l203_cols = [c for c in ["L2-03", "L2-03a", "L2-03b", "L2-03c", "L2-03d"] if c in rule_details]
    if l203_cols:
        rule_details["L2-03"] = rule_details[l203_cols].max(axis=1)
        rule_details = rule_details.drop(columns=[c for c in l203_cols if c != "L2-03"])
    for rule_id in CANONICAL_TRANSACTION_RULE_IDS:
        if rule_id not in rule_details:
            rule_details[rule_id] = 0.0
    rule_details = rule_details[list(CANONICAL_TRANSACTION_RULE_IDS)]
    rule_details.insert(0, "document_id", df["document_id"].astype(str).to_numpy())
    return rule_details.groupby("document_id", as_index=True).max()


def missing_inputs_for_doc(rows: pd.DataFrame, rule_id: str) -> list[str]:
    missing: list[str] = []
    for column in RULE_INPUT_COLUMNS.get(rule_id, []):
        if column not in rows.columns:
            missing.append(column)
            continue
        values = rows[column]
        if values.isna().all() or values.astype(str).str.strip().replace({"": np.nan}).isna().all():
            missing.append(column)
    return missing


def classify_uncovered_doc(doc_id: str, rows: pd.DataFrame, scores: pd.Series) -> dict[str, Any]:
    nonzero = scores[scores > 0].sort_values(ascending=False)
    missing_by_rule = {
        rule_id: missing_inputs_for_doc(rows, rule_id)
        for rule_id in CANONICAL_TRANSACTION_RULE_IDS
    }
    material_missing = {
        rule_id: cols
        for rule_id, cols in missing_by_rule.items()
        if cols and len(cols) == len(RULE_INPUT_COLUMNS.get(rule_id, []))
    }
    if not nonzero.empty:
        classification = "threshold_below"
        reason = (
            "At least one PHASE1 raw/review score exists, but row/case seed priority "
            "remained below the case-builder entry threshold or the signal was non-seeding context."
        )
    elif material_missing:
        classification = "data_missing"
        reason = "One or more rules had all required inputs unavailable for this document."
    else:
        classification = "rule_absence"
        reason = "No active PHASE1 rule produced a positive row/detail score; required inputs were generally present."
    return {
        "document_id": doc_id,
        "classification": classification,
        "reason": reason,
        "max_rule_score": round(float(scores.max()), 6),
        "top_positive_rules": [
            {
                "rule_id": rule_id,
                "score": round(float(score), 6),
                "nominal_threshold": NOMINAL_RULE_THRESHOLDS.get(rule_id),
                "standalone_seed_excluded": rule_id in LOCKED_NO_STANDALONE_COPY_RULE_IDS,
            }
            for rule_id, score in nonzero.head(5).items()
        ],
        "material_missing_rule_inputs": material_missing,
    }


def phase2_recovery(phase2_by_doc: pd.DataFrame, uncovered_docs: set[str]) -> dict[str, Any]:
    scored = phase2_by_doc.sort_values(
        "phase2_unsupervised_selection_score", ascending=False, kind="mergesort"
    ).reset_index(drop=True)
    scored["rank"] = np.arange(1, len(scored) + 1)
    top_ns = [100, 500, 1000, 2000, 5000, 10000]
    counts = {
        f"top_{n}_docs": int(scored.head(n)["document_id"].astype(str).isin(uncovered_docs).sum())
        for n in top_ns
    }
    top_1pct_n = max(int(len(scored) * 0.01), 1)
    counts["top_1pct_docs_n"] = top_1pct_n
    counts["top_1pct_docs"] = int(
        scored.head(top_1pct_n)["document_id"].astype(str).isin(uncovered_docs).sum()
    )
    uncovered_ranked = scored[scored["document_id"].astype(str).isin(uncovered_docs)]
    return {
        "ranking_basis": "document-level PHASE2 ECDF max score, no truth label in score",
        "counts": counts,
        "rank_stats_for_uncovered_80": {
            "count": int(len(uncovered_ranked)),
            "min_rank": int(uncovered_ranked["rank"].min()) if len(uncovered_ranked) else None,
            "median_rank": float(uncovered_ranked["rank"].median()) if len(uncovered_ranked) else None,
            "p90_rank": float(uncovered_ranked["rank"].quantile(0.90)) if len(uncovered_ranked) else None,
            "max_rank": int(uncovered_ranked["rank"].max()) if len(uncovered_ranked) else None,
            "mean_score": round(float(uncovered_ranked["phase2_unsupervised_selection_score"].mean()), 6)
            if len(uncovered_ranked)
            else None,
        },
        "rrf_integrated_queue_recovery": 0,
        "rrf_note": "Current RRF integrates PHASE1 cases only; documents without a PHASE1 case have no case row to rank.",
    }


def make_recovery_md(analysis: dict[str, Any]) -> str:
    phase2_counts = analysis["recovery_path_evaluation"]["phase2_standalone_queue"]["counts"]
    threshold = analysis["recovery_path_evaluation"]["threshold_relaxation"]
    recommended = analysis["recovery_path_evaluation"]["recommended_path"]
    lines = [
        "# TS-13 Recovery Path Evaluation",
        "",
        "> V7 fixed3 synthetic dataset only. Truth labels were used to measure coverage, not to tune PHASE1 thresholds.",
        "",
        "## Summary",
        "",
        f"- Truth documents: {analysis['validation']['truth_doc_count']}",
        f"- Review queue covered truth documents: {analysis['validation']['covered_truth_doc_count']}",
        f"- Uncovered truth documents: {analysis['validation']['uncovered_truth_doc_count']}",
        f"- Recall ceiling: {analysis['validation']['recall_ceiling_pct']}%",
        "",
        "## Options",
        "",
        "| Option | Measured recovery | False-positive / policy risk | Assessment |",
        "|---|---:|---|---|",
        (
            "| (a) Relax existing PHASE1 thresholds | "
            f"{threshold['recoverable_uncovered_docs']} / 80 from existing positive raw scores | "
            f"{threshold['estimated_normal_fp_increase_docs']} normal docs if every positive raw score were allowed to seed a case | "
            "Not recommended for V1. It would require admitting Normal/low-priority raw hits into PHASE1 cases. |"
        ),
        (
            "| (b) Add new PHASE1 rule | Not executed | "
            "Conflicts with 32-rule V1 lock and needs DECISION.md lock revision | "
            "Possible only as a future governance decision, supported by K-SA 240 / FSS / PCAOB AS 2401 / K-SOX domain grounds, not V7 recall. |"
        ),
        (
            "| (c) PHASE2 standalone queue | "
            f"{phase2_counts['top_1000_docs']} in top 1,000 docs; {phase2_counts['top_1pct_docs']} in top 1% docs | "
            "Requires a separate PHASE2-only document queue; current RRF recovers 0 because no PHASE1 case exists | "
            "Best near-term complement without touching PHASE1 lock. |"
        ),
        (
            "| (d) Accept unrecovered ceiling | 0 change | "
            "Operational ceiling remains 87.10% on this synthetic dataset | "
            "Acceptable as a policy fallback, but document the ceiling clearly. |"
        ),
        "",
        "## Recommendation",
        "",
        f"**Recommended path: {recommended['option']}**",
        "",
        recommended["rationale"],
        "",
        "Do not change PHASE1 case builder, permanent thresholds, or the 32-rule catalog in this sprint.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--regenerate-phase2",
        action="store_true",
        help="Regenerate PHASE2 ECDF scores by calling stage7.score_phase2.",
    )
    args = parser.parse_args()

    truth = pd.read_csv(stage7.TRUTH_PATH)
    queue = pd.read_parquet(stage7.QUEUE_PATH)
    with stage7.PKL_PATH.open("rb") as fh:
        pkl = pickle.load(fh)
    df: pd.DataFrame = pkl["df"]
    detection_results = pkl["results"]

    truth["document_id"] = truth["document_id"].astype(str)
    df["document_id"] = df["document_id"].astype(str)
    truth_docs = set(truth["document_id"])
    queue_docs = split_queue_docs(queue)
    covered_truth_docs = truth_docs & queue_docs
    uncovered_docs = truth_docs - queue_docs
    uncovered_truth = truth[truth["document_id"].isin(uncovered_docs)].copy()

    rule_scores_by_doc = build_rule_scores_by_doc(df, detection_results)
    uncovered_rows_by_doc = {
        doc_id: df[df["document_id"] == doc_id].copy() for doc_id in sorted(uncovered_docs)
    }

    classification_rows: list[dict[str, Any]] = []
    for doc_id, rows in uncovered_rows_by_doc.items():
        scores = rule_scores_by_doc.loc[doc_id] if doc_id in rule_scores_by_doc.index else pd.Series(0.0, index=CANONICAL_TRANSACTION_RULE_IDS)
        row = classify_uncovered_doc(doc_id, rows, scores)
        scenario = uncovered_truth.set_index("document_id").loc[doc_id, "manipulation_scenario"]
        row["manipulation_scenario"] = str(scenario)
        classification_rows.append(row)

    classifications = Counter(row["classification"] for row in classification_rows)
    phase2_by_doc, phase2_source = load_phase2_by_doc(df, regenerate=args.regenerate_phase2)
    phase2_eval = phase2_recovery(phase2_by_doc, uncovered_docs)

    any_positive = [
        row for row in classification_rows if row["classification"] == "threshold_below"
    ]
    nontruth_docs = set(df["document_id"]) - truth_docs
    normal_with_any_positive = int(
        rule_scores_by_doc.loc[list(nontruth_docs & set(rule_scores_by_doc.index))]
        .max(axis=1)
        .gt(0)
        .sum()
    )

    amount_column = "line_amount" if "line_amount" in truth.columns else "local_amount"

    analysis: dict[str, Any] = {
        "metadata": {
            "task": "TS-13 PHASE1 rule coverage gap",
            "dataset": "datasynth_manipulation_v7_candidate_fixed3",
            "phase2_score_source": phase2_source,
            "truth_labels_used_for": "coverage measurement only; not threshold fitting",
        },
        "validation": {
            "truth_doc_count": len(truth_docs),
            "covered_truth_doc_count": len(covered_truth_docs),
            "uncovered_truth_doc_count": len(uncovered_docs),
            "expected_uncovered_truth_doc_count": 80,
            "scenario_distribution_sum": int(uncovered_truth["manipulation_scenario"].notna().sum()),
            "classification_sum": int(sum(classifications.values())),
            "recall_ceiling_pct": round(len(covered_truth_docs) / len(truth_docs) * 100.0, 2),
        },
        "uncovered_document_ids": sorted(uncovered_docs),
        "scenario_distribution": compare_distribution(
            truth, uncovered_truth, "manipulation_scenario"
        ),
        "common_characteristics": {
            column: compare_distribution(truth, uncovered_truth, column)
            for column in DIMENSIONS
            if column in truth.columns
        },
        "line_amount": {
            "column": amount_column,
            "truth_total": amount_stats(truth[amount_column]),
            "uncovered_80": amount_stats(uncovered_truth[amount_column]),
        },
        "rule_catalog": {
            rule_id: {
                "input_columns": RULE_INPUT_COLUMNS.get(rule_id, []),
                "nominal_threshold": NOMINAL_RULE_THRESHOLDS.get(rule_id, 0.45),
                "standalone_seed_excluded": rule_id in LOCKED_NO_STANDALONE_COPY_RULE_IDS,
            }
            for rule_id in CANONICAL_TRANSACTION_RULE_IDS
        },
        "unapplied_rule_classification": {
            "counts": dict(classifications),
            "matrix": classification_rows,
        },
        "recovery_path_evaluation": {
            "threshold_relaxation": {
                "recoverable_uncovered_docs": len(any_positive),
                "basis": "uncovered documents with any positive active-rule raw/detail score",
                "estimated_normal_fp_increase_docs": normal_with_any_positive,
                "note": "This is a stress upper bound, not a proposed threshold. Truth recall was not used to tune thresholds.",
            },
            "new_rule_addition": {
                "executed": False,
                "requires_lock_revision": True,
                "governance_note": "Any new/changed PHASE1 rule conflicts with PHASE1_TOPIC_SCORING_V1_LOCK.md and needs a future docs/DECISION.md item.",
            },
            "phase2_standalone_queue": phase2_eval,
            "accept_ceiling": {
                "recall_ceiling_pct": round(len(covered_truth_docs) / len(truth_docs) * 100.0, 2),
                "scope_note": "Synthetic V7 fixed3 only; real-data bypass rate is not implied.",
            },
            "recommended_path": {
                "option": "(c) PHASE2 standalone document queue + explicit ceiling disclosure",
                "rationale": (
                    "PHASE1 threshold relaxation can recover the 80 documents only by admitting low-priority raw "
                    "hits, with a very large normal-document expansion, and PHASE1 rule/catalog changes are locked. "
                    "A PHASE2-only document queue can surface some "
                    "documents without altering PHASE1 V1 lock, while current RRF remains case-bound and cannot "
                    "rank documents with no PHASE1 case."
                ),
            },
        },
    }

    assert analysis["validation"]["truth_doc_count"] == 620
    assert analysis["validation"]["uncovered_truth_doc_count"] == 80
    assert analysis["validation"]["scenario_distribution_sum"] == 80
    assert analysis["validation"]["classification_sum"] == 80

    OUT_JSON.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_MD.write_text(make_recovery_md(analysis), encoding="utf-8")
    print(json.dumps(analysis["validation"], ensure_ascii=False, indent=2))
    print(f"wrote {OUT_JSON.relative_to(ROOT)}")
    print(f"wrote {OUT_MD.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
