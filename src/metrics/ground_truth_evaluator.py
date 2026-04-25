"""Ground-truth based performance evaluation helpers."""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from src.detection.base import DetectionResult
from src.metrics.models import PerformanceReport, RuleMetric
from src.metrics.rule_mapping import (
    RULE_TO_LABEL,
    RULE_TO_POPULATION_TRUTH,
    RULE_TO_TRACK,
    covered_label_types,
    get_action_layer,
    get_evaluation_note,
    get_truth_basis,
    get_truth_display,
)


def normalize_results_by_track(
    results: Mapping[str, DetectionResult] | list[DetectionResult],
) -> dict[str, DetectionResult]:
    """Normalize detector results into a track-name keyed dictionary."""
    if isinstance(results, Mapping):
        return {str(track): result for track, result in results.items()}
    return {result.track_name: result for result in results}


def per_rule_label_analysis(
    df: pd.DataFrame,
    results: Mapping[str, DetectionResult] | list[DetectionResult],
    labels: pd.DataFrame,
) -> list[dict]:
    """Compare each rule's flagged documents against ground-truth labels."""
    normalized = normalize_results_by_track(results)
    analysis: list[dict] = []

    for rule_id, label_types in RULE_TO_LABEL.items():
        track_name = RULE_TO_TRACK[rule_id]
        result = normalized.get(track_name)

        if result is None or rule_id not in result.details.columns:
            analysis.append({
                "rule_id": rule_id,
                "label_types": label_types,
                "truth_display": get_truth_display(rule_id),
                "truth_basis": get_truth_basis(rule_id),
                "status": "skipped",
                "reason": f"rule missing in track {track_name}",
                "label_docs": 0,
                "flagged_rows": 0,
                "flagged_docs": 0,
                "tp_docs": 0,
                "fp_docs": 0,
                "fn_docs": 0,
                "recall": 0.0,
                "precision": 0.0,
                "sample_fn": [],
                "sample_fp": [],
            })
            continue

        rule_mask = result.details[rule_id].reindex(df.index, fill_value=0.0) > 0
        flagged_rows = int(rule_mask.sum())
        flagged_doc_set = set(df.loc[rule_mask, "document_id"].dropna().unique())

        label_doc_set = _label_doc_set_for_rule(rule_id, df, labels)

        tp_docs = flagged_doc_set & label_doc_set
        fp_docs = flagged_doc_set - label_doc_set
        fn_docs = label_doc_set - flagged_doc_set

        tp = len(tp_docs)
        fp = len(fp_docs)
        fn = len(fn_docs)
        label_count = len(label_doc_set)
        recall = tp / label_count if label_count > 0 else None
        precision = tp / (tp + fp) if (tp + fp) > 0 else None

        status = "population" if rule_id in RULE_TO_POPULATION_TRUTH else ("no_label" if not label_types else "ok")
        analysis.append({
            "rule_id": rule_id,
            "label_types": label_types,
            "truth_display": get_truth_display(rule_id),
            "truth_basis": get_truth_basis(rule_id),
            "status": status,
            "reason": get_evaluation_note(rule_id),
            "label_docs": label_count,
            "flagged_rows": flagged_rows,
            "flagged_docs": len(flagged_doc_set),
            "tp_docs": tp,
            "fp_docs": fp,
            "fn_docs": fn,
            "recall": recall,
            "precision": precision,
            "sample_fn": sorted(fn_docs)[:5],
            "sample_fp": sorted(fp_docs)[:5],
        })

    return analysis


def _label_doc_set_for_rule(
    rule_id: str,
    df: pd.DataFrame,
    labels: pd.DataFrame,
) -> set[str]:
    """Return rule-specific ground-truth document ids.

    Why: L1-01 is a structural balance gate. Its ground truth should be every document
    whose debit-credit sum is actually unbalanced, regardless of sidecar label type.
    """
    if rule_id == "L1-01":
        required = {"document_id", "debit_amount", "credit_amount"}
        if not required.issubset(df.columns):
            return set()

        candidate_df = df.dropna(subset=["document_id"]).copy()
        if candidate_df.empty:
            return set()

        diff = candidate_df["debit_amount"].fillna(0.0) - candidate_df["credit_amount"].fillna(0.0)
        doc_diff = diff.groupby(candidate_df["document_id"]).sum()
        return set(doc_diff[doc_diff.abs() > 1.0].index)

    if rule_id == "L3-02":
        if not {"document_id", "source"}.issubset(df.columns):
            return set()
        source = df["source"].fillna("").astype(str).str.lower()
        return set(df.loc[source.isin({"manual", "adjustment"}), "document_id"].dropna().unique())

    if rule_id == "L3-03":
        if "document_id" not in df.columns:
            return set()
        if "is_intercompany" in df.columns:
            ic_mask = df["is_intercompany"].fillna(False).astype(bool)
            return set(df.loc[ic_mask, "document_id"].dropna().unique())
        if "gl_account" not in df.columns:
            return set()
        gl = df["gl_account"].fillna("").astype(str).str.replace(r"\.0$", "", regex=True)
        ic_mask = gl.str.startswith(("1150", "2050", "4500", "2700"))
        return set(df.loc[ic_mask, "document_id"].dropna().unique())

    if rule_id == "L3-10":
        if not {"document_id", "gl_account"}.issubset(df.columns):
            return set()
        gl = df["gl_account"].fillna("").astype(str).str.strip().str.lower().str.replace(r"\.0+$", "", regex=True)
        high_risk_mask = gl.isin({"1190", "2190"}) | gl.str.startswith(("111", "112", "113"))
        return set(df.loc[high_risk_mask, "document_id"].dropna().unique())

    label_types = RULE_TO_LABEL.get(rule_id, [])
    if not label_types:
        return set()

    label_mask = labels["anomaly_type"].isin(label_types)
    label_doc_set = set(labels.loc[label_mask, "document_id"].dropna().unique())
    return label_doc_set


def overall_label_analysis(
    df: pd.DataFrame,
    agg_df: pd.DataFrame,
    labels: pd.DataFrame,
) -> dict:
    """Compute overall document-level ground-truth metrics."""
    labeled_docs = set(labels["document_id"].dropna().unique())
    labeled_docs.update(_label_doc_set_for_rule("L1-01", df, labels))
    labeled_docs.update(_label_doc_set_for_rule("L3-02", df, labels))
    labeled_docs.update(_label_doc_set_for_rule("L3-03", df, labels))
    labeled_docs.update(_label_doc_set_for_rule("L3-10", df, labels))
    flagged_mask = agg_df["anomaly_score"] > 0
    flagged_docs = set(df.loc[flagged_mask, "document_id"].dropna().unique())

    total_tp = len(labeled_docs & flagged_docs)
    total_labeled = len(labeled_docs)
    total_flagged_docs = len(flagged_docs)

    phase1_types = covered_label_types()
    phase1_mask = labels["anomaly_type"].isin(phase1_types)
    phase1_docs = set(labels.loc[phase1_mask, "document_id"].dropna().unique())
    phase1_docs.update(_label_doc_set_for_rule("L1-01", df, labels))
    phase1_docs.update(_label_doc_set_for_rule("L3-02", df, labels))
    phase1_docs.update(_label_doc_set_for_rule("L3-03", df, labels))
    phase1_docs.update(_label_doc_set_for_rule("L3-10", df, labels))
    phase23_docs = labeled_docs - phase1_docs

    phase1_tp = len(phase1_docs & flagged_docs)
    phase23_tp = len(phase23_docs & flagged_docs)

    return {
        "total_labeled": total_labeled,
        "total_flagged_docs": total_flagged_docs,
        "total_tp": total_tp,
        "total_recall": total_tp / total_labeled if total_labeled > 0 else 0.0,
        "total_precision": total_tp / total_flagged_docs if total_flagged_docs > 0 else 0.0,
        "phase1_labeled": len(phase1_docs),
        "phase1_tp": phase1_tp,
        "phase1_recall": phase1_tp / len(phase1_docs) if phase1_docs else 0.0,
        "phase23_labeled": len(phase23_docs),
        "phase23_tp": phase23_tp,
        "phase23_recall": phase23_tp / len(phase23_docs) if phase23_docs else 0.0,
    }


def uncovered_label_analysis(labels: pd.DataFrame) -> list[dict]:
    """Return label types not yet covered by Phase 1 rule mappings."""
    covered_types = covered_label_types()
    uncovered = [
        {"anomaly_type": anomaly_type, "count": int(count)}
        for anomaly_type, count in labels["anomaly_type"].value_counts().items()
        if anomaly_type not in covered_types
    ]
    return sorted(uncovered, key=lambda item: -item["count"])


def build_ground_truth_report(
    df: pd.DataFrame,
    agg_df: pd.DataFrame,
    results: Mapping[str, DetectionResult] | list[DetectionResult],
    labels: pd.DataFrame,
    *,
    upload_batch_id: str,
    phase_scope: str = "phase2_included",
    metric_confidence: str = "complete",
) -> PerformanceReport:
    """Build a unified ground-truth performance report."""
    per_rule = per_rule_label_analysis(df, results, labels)
    overall = overall_label_analysis(df, agg_df, labels)
    high_risk_docs = 0
    high_risk_ratio = 0.0
    if "risk_level" in agg_df.columns and "document_id" in df.columns:
        high_risk_docs = int(
            df.loc[agg_df["risk_level"].fillna("Normal").eq("High"), "document_id"]
            .dropna()
            .nunique()
        )
        total_docs = int(df["document_id"].dropna().nunique())
        high_risk_ratio = high_risk_docs / total_docs if total_docs > 0 else 0.0
    else:
        total_docs = int(df["document_id"].dropna().nunique()) if "document_id" in df.columns else int(len(df))

    precision = overall["total_precision"]
    recall = overall["total_recall"]
    f1 = None
    if precision + recall > 0:
        f1 = 2 * precision * recall / (precision + recall)

    return PerformanceReport(
        report_id=f"gtr_{upload_batch_id}",
        upload_batch_id=upload_batch_id,
        source_kind="ground_truth",
        phase_scope=phase_scope,
        metric_confidence=metric_confidence,
        total_docs=total_docs,
        flagged_docs=overall["total_flagged_docs"],
        high_risk_docs=high_risk_docs,
        high_risk_ratio=high_risk_ratio,
        precision=precision,
        recall=recall,
        f1=f1,
        rule_metrics=[
            RuleMetric(
                track_name=RULE_TO_TRACK[item["rule_id"]],
                action_layer=get_action_layer(item["rule_id"]),
                rule_code=item["rule_id"],
                evaluation_status=str(item["status"]),
                evaluation_reason=str(item["reason"]),
                label_docs=int(item["label_docs"]),
                flagged_docs=int(item["flagged_docs"]),
                tp_docs=int(item["tp_docs"]),
                fp_docs=int(item["fp_docs"]),
                fn_docs=int(item["fn_docs"]),
                precision=item["precision"],
                recall=item["recall"],
                f1=_calc_f1(item["precision"], item["recall"]),
            )
            for item in per_rule
            if item["status"] != "skipped"
        ],
    )


def _calc_f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None or (precision + recall) == 0:
        return None
    return 2 * precision * recall / (precision + recall)

