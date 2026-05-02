"""Ground-truth based performance evaluation helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pandas as pd

from src.detection.base import DetectionResult
from src.detection.constants import get_track_display_label
from src.ingest.datasynth_labels import get_source_path
from src.metrics.models import (
    AnalyticalReviewMetric,
    BenfordBenchmarkMetric,
    PerformanceReport,
    RuleMetric,
)
from src.metrics.rule_mapping import (
    RULE_TO_LABEL,
    RULE_TO_POPULATION_TRUTH,
    RULE_TO_TRACK,
    covered_label_types,
    get_action_layer,
    get_evaluation_note,
    get_rule_evaluation_profile,
    get_truth_basis,
    get_truth_display,
)


def _datasynth_candidate_dir(df: pd.DataFrame) -> Path | None:
    """Return the DataSynth candidate directory stored on the dataframe."""

    source_path = get_source_path(df)
    if source_path is None:
        return None
    if source_path.is_dir():
        return source_path
    return source_path.parent


def _rule_truth_sidecar_paths(rule_id: str, df: pd.DataFrame) -> list[Path]:
    data_dir = _datasynth_candidate_dir(df)
    if data_dir is None:
        return []

    paths: list[Path] = []
    configured = RULE_TO_POPULATION_TRUTH.get(rule_id)
    if configured:
        paths.append(data_dir / configured)

    paths.append(data_dir / "labels" / f"rule_truth_{rule_id.replace('-', '_')}.csv")

    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
    return unique


def _load_rule_truth_doc_set(rule_id: str, df: pd.DataFrame) -> set[str] | None:
    """Load preferred rule-truth sidecar docs when a DataSynth candidate provides one."""

    if "document_id" not in df.columns:
        return None
    available_docs = set(df["document_id"].dropna().astype(str).unique())
    for path in _rule_truth_sidecar_paths(rule_id, df):
        if not path.exists():
            continue
        truth = pd.read_csv(
            path,
            usecols=lambda column: column in {"document_id", "expected_hit", "rule_id"},
            low_memory=False,
        )
        if "document_id" not in truth.columns:
            continue
        mask = truth["document_id"].notna()
        if "rule_id" in truth.columns:
            mask = mask & truth["rule_id"].astype(str).eq(rule_id)
        if "expected_hit" in truth.columns:
            expected = truth["expected_hit"].astype(str).str.lower().isin({"true", "1", "yes"})
            mask = mask & expected
        return set(truth.loc[mask, "document_id"].astype(str).unique()) & available_docs
    return None


def normalize_results_by_track(
    results: Mapping[str, DetectionResult] | list[DetectionResult],
) -> dict[str, DetectionResult]:
    """Normalize detector results into a track-name keyed dictionary."""
    if isinstance(results, Mapping):
        return {str(track): result for track, result in results.items()}
    return {result.track_name: result for result in results}


_BENFORD_HOLDOUT_SIDECARS: tuple[tuple[str, str], ...] = (
    ("adversarial_holdout", "robustness holdout, not strict pass/fail"),
    ("weak_fraud_holdout", "weak fraud holdout coverage"),
    ("boundary_groups", "near-threshold groups"),
    ("broad_digit_findings", "broad digit distortion coverage"),
    ("business_skew_normal_groups", "normal-control hits should stay low"),
    ("company_specific_normals", "normal-control hits should stay low"),
    ("high_mad_normal_controls", "normal explanation required; hits are review flags"),
    ("small_sample_controls", "minimum-sample boundary controls"),
    ("skipped_small_groups", "groups below evaluation sample floor"),
)


def build_benford_population_benchmarks(
    df: pd.DataFrame,
    result: DetectionResult,
    labels_dir: str | Path,
    *,
    fiscal_year: int | str | None = None,
) -> list[BenfordBenchmarkMetric]:
    """Evaluate L4-02 against DataSynth Benford sidecars.

    These metrics are intentionally population-level. They should not replace
    document-label precision/recall because Benford findings are defined at
    fiscal_year + company_code + gl_account scope.
    """
    labels_path = Path(labels_dir)
    year = _resolve_benford_year(df, fiscal_year)
    if year is None:
        return [BenfordBenchmarkMetric(
            year="unknown",
            benchmark="sidecars_missing",
            note=(
                "Benford population benchmark unavailable: fiscal year could not "
                "be resolved. Do not interpret row-level L4-02 metrics as "
                "Benford pass/fail."
            ),
        )]

    findings = result.metadata.get("benford_findings", {}) if result.metadata else {}
    predicted_groups = _benford_predicted_group_keys(findings, str(year))
    metrics: list[BenfordBenchmarkMetric] = []

    truth_groups = _benford_sidecar_keys(labels_path, "benford_finding_truth", year)
    normal_groups = _benford_sidecar_keys(labels_path, "benford_normal_groups", year)

    if truth_groups:
        tp = len(predicted_groups & truth_groups)
        fp = len(predicted_groups - truth_groups)
        fn = len(truth_groups - predicted_groups)
        metrics.append(BenfordBenchmarkMetric(
            year=str(year),
            benchmark="contract_findings",
            truth_count=len(truth_groups),
            hit_count=tp,
            miss_count=fn,
            extra_count=fp,
            precision=tp / (tp + fp) if (tp + fp) else None,
            recall=tp / (tp + fn) if (tp + fn) else None,
            note="strict contract truth",
        ))

    if normal_groups:
        hits = len(predicted_groups & normal_groups)
        metrics.append(BenfordBenchmarkMetric(
            year=str(year),
            benchmark="normal_group_controls",
            truth_count=len(normal_groups),
            hit_count=hits,
            miss_count=max(len(normal_groups) - hits, 0),
            recall=hits / len(normal_groups),
            note="hit rate is false-finding pressure",
        ))

    candidate_metrics = _benford_candidate_metrics(df, result, labels_path, year)
    metrics.extend(candidate_metrics)

    for sidecar_name, note in _BENFORD_HOLDOUT_SIDECARS:
        groups = _benford_sidecar_keys(labels_path, f"benford_{sidecar_name}", year)
        if not groups:
            continue
        hits = len(predicted_groups & groups)
        metrics.append(BenfordBenchmarkMetric(
            year=str(year),
            benchmark=sidecar_name,
            truth_count=len(groups),
            hit_count=hits,
            miss_count=max(len(groups) - hits, 0),
            recall=hits / len(groups),
            note=note,
        ))

    if not metrics:
        metrics.append(BenfordBenchmarkMetric(
            year=str(year),
            benchmark="sidecars_missing",
            note=(
                "Benford population benchmark unavailable: no Benford sidecars "
                "found for this labels directory/year. Row-level L4-02 "
                "precision/recall is intentionally not the acceptance metric."
            ),
        ))

    return metrics


def build_analytical_review_metrics(
    df: pd.DataFrame,
    result: DetectionResult,
    labels_dir: str | Path,
    *,
    fiscal_year: int | str | None = None,
    all_results: Mapping[str, DetectionResult] | None = None,
) -> list[AnalyticalReviewMetric]:
    """Evaluate D01/D02 as account-level review populations, not document labels."""
    labels_path = Path(labels_dir)
    year = _resolve_benford_year(df, fiscal_year)
    if year is None:
        return []

    metrics: list[AnalyticalReviewMetric] = []
    predictions = {
        "D01": _d01_predicted_group_keys(result, year),
        "D02": _d02_predicted_group_keys(result, year),
    }
    sidecars = {
        "D01": (
            "account_activity_variance_truth",
            "account_activity_variance_normal_controls",
            "account_activity_variance_review_population",
        ),
        "D02": (
            "monthly_pattern_shift_confirmed_anomalies",
            "monthly_pattern_shift_normal_controls",
            "monthly_pattern_shift_review_population",
        ),
    }
    notes = {
        "D01": "Account activity variance review population; not row-level precision.",
        "D02": "Monthly pattern variance review population; not row-level precision.",
    }

    for rule_code, predicted_groups in predictions.items():
        truth_stem, normal_stem, review_stem = sidecars[rule_code]
        sidecar_available = any(
            _account_review_sidecar_exists(labels_path, stem, year)
            for stem in (truth_stem, normal_stem, review_stem)
        )
        truth_groups = _account_review_sidecar_keys(labels_path, truth_stem, year)
        normal_groups = _account_review_sidecar_keys(labels_path, normal_stem, year)
        review_population = _account_review_sidecar_keys(labels_path, review_stem, year)
        if not sidecar_available:
            metrics.append(AnalyticalReviewMetric(
                rule_code=rule_code,
                year=str(year),
                review_groups=len(predicted_groups),
                note=(
                    f"{rule_code} analytical review benchmark unavailable: "
                    "no account-level sidecars found for this labels directory/year."
                ),
            ))
            continue
        if not predicted_groups and not truth_groups and not review_population:
            continue

        truth_covered = len(predicted_groups & truth_groups)
        missed_truth = len(truth_groups - predicted_groups)
        normal_hits = len(predicted_groups & normal_groups)
        review_hits = len(predicted_groups & review_population)
        metrics.append(AnalyticalReviewMetric(
            rule_code=rule_code,
            year=str(year),
            review_groups=len(predicted_groups),
            truth_groups=len(truth_groups),
            truth_covered=truth_covered,
            missed_truth_groups=missed_truth,
            normal_control_groups=len(normal_groups),
            normal_control_review_groups=normal_hits,
            review_population_groups=len(review_population),
            review_population_covered=review_hits,
            overlap_docs=_analytical_overlap_docs(
                df,
                predicted_groups,
                all_results or {},
                rule_code,
            ),
            truth_coverage=(
                truth_covered / len(truth_groups) if truth_groups else None
            ),
            normal_control_hit_rate=(
                normal_hits / len(normal_groups) if normal_groups else None
            ),
            review_population_coverage=(
                review_hits / len(review_population) if review_population else None
            ),
            note=notes[rule_code],
        ))

    return metrics


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
                "reason": f"rule missing in {get_track_display_label(track_name, rule_id)}",
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

        rule_scores = result.details[rule_id].reindex(df.index, fill_value=0.0)
        review_scores = _rule_review_scores(rule_id, df, result)
        rule_mask = _rule_flag_mask(rule_id, df, result) | (rule_scores > 0) | (
            review_scores > 0
        )
        flagged_rows = int(rule_mask.sum())
        flagged_doc_set = set(df.loc[rule_mask, "document_id"].dropna().unique())
        overlap_docs = _count_overlap_docs(rule_id, df, normalized, flagged_doc_set)
        breakdown = _rule_breakdown(rule_id, result)
        score_bands = _rule_score_bands(rule_id, df, result, normalized)

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

        profile = get_rule_evaluation_profile(rule_id)
        if profile is not None:
            status = profile.status
        elif rule_id in RULE_TO_POPULATION_TRUTH:
            status = "population"
        elif not label_types:
            status = "no_label"
        else:
            status = "ok"
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
            "rule_objective": profile.rule_objective if profile else "",
            "broad_fraud_type": profile.broad_fraud_type if profile else "",
            "expected_coverage": profile.expected_coverage if profile else "",
            "overlap_docs": overlap_docs,
            "standalone_docs": max(len(flagged_doc_set) - overlap_docs, 0),
            "review_queue_docs": _review_queue_docs(rule_id, fp, score_bands),
            "breakdown": breakdown,
            "score_bands": score_bands,
        })

    return analysis


def _rule_breakdown(rule_id: str, result: DetectionResult) -> dict:
    """Return detector-provided breakdown metadata for a rule."""
    breakdowns = result.metadata.get("rule_breakdowns", {}) if result.metadata else {}
    breakdown = breakdowns.get(rule_id, {})
    return dict(breakdown) if isinstance(breakdown, dict) else {}


def _rule_review_scores(rule_id: str, df: pd.DataFrame, result: DetectionResult) -> pd.Series:
    """Return detector-provided review score series for operational evaluation."""

    empty = pd.Series(0.0, index=df.index, dtype="float64")
    if not result.metadata:
        return empty
    review_details = result.metadata.get("review_score_series")
    if isinstance(review_details, pd.DataFrame) and rule_id in review_details.columns:
        return review_details[rule_id].reindex(df.index, fill_value=0.0).astype(float)
    if isinstance(review_details, dict) and rule_id in review_details:
        return pd.Series(review_details[rule_id], index=df.index).fillna(0.0).astype(float)
    return empty


def _rule_flag_mask(rule_id: str, df: pd.DataFrame, result: DetectionResult) -> pd.Series:
    """Return raw detector flags when a rule separates detection from score."""

    empty = pd.Series(False, index=df.index, dtype="bool")
    if not result.metadata:
        return empty
    flag_details = result.metadata.get("rule_flag_series")
    if isinstance(flag_details, pd.DataFrame) and rule_id in flag_details.columns:
        return flag_details[rule_id].reindex(df.index, fill_value=False).astype(bool)
    if isinstance(flag_details, dict) and rule_id in flag_details:
        return pd.Series(flag_details[rule_id], index=df.index).fillna(False).astype(bool)
    return empty


def _rule_score_bands(
    rule_id: str,
    df: pd.DataFrame,
    result: DetectionResult,
    results: Mapping[str, DetectionResult],
) -> dict[str, int]:
    """Return document counts by score band for range-oriented rules."""
    if "document_id" not in df.columns or rule_id not in result.details.columns:
        return {}

    scores = result.details[rule_id].reindex(df.index, fill_value=0.0)
    review_scores = _rule_review_scores(rule_id, df, result)
    if rule_id == "L1-04":
        annotations = _rule_row_annotations(rule_id, result)
        if annotations:
            return {
                "boundary_docs": _annotation_doc_count_by_field(
                    df, annotations, "bucket", "boundary",
                ),
                "moderate_docs": _annotation_doc_count_by_field(
                    df, annotations, "bucket", "moderate",
                ),
                "severe_docs": _annotation_doc_count_by_field(
                    df, annotations, "bucket", "severe",
                ),
                "critical_docs": _annotation_doc_count_by_field(
                    df, annotations, "bucket", "critical",
                ),
                "non_approver_docs": _annotation_doc_count_by_field(
                    df, annotations, "bucket", "non_approver",
                ),
                "unresolved_limit_docs": _annotation_doc_count_by_field(
                    df, annotations, "bucket", "unresolved_limit",
                ),
            }
        return {
            "boundary_docs": int(
                df.loc[(scores > 0) & (scores < 0.60), "document_id"].dropna().nunique()
            ),
            "moderate_or_unresolved_docs": int(
                df.loc[(scores >= 0.60) & (scores < 0.75), "document_id"].dropna().nunique()
            ),
            "severe_docs": int(
                df.loc[(scores >= 0.75) & (scores < 0.90), "document_id"].dropna().nunique()
            ),
            "critical_or_non_approver_docs": int(
                df.loc[scores >= 0.90, "document_id"].dropna().nunique()
            ),
        }
    if rule_id == "L1-05":
        annotations = _rule_row_annotations(rule_id, result)
        if annotations:
            review_docs = _annotation_doc_count_by_field(df, annotations, "bucket", "review")
            immediate_docs = _annotation_doc_count_by_field(
                df, annotations, "bucket", "immediate",
            )
            escalated_docs = _annotation_doc_count_by_field_prefix(
                df,
                annotations,
                "bucket",
                "escalated_",
            )
            return {
                "review_docs": review_docs,
                "immediate_docs": immediate_docs,
                "escalated_docs": escalated_docs,
            }
        return {
            "review_docs": int(
                df.loc[(scores > 0) & (scores < 0.8), "document_id"].dropna().nunique()
            ),
            "immediate_docs": int(df.loc[scores >= 0.8, "document_id"].dropna().nunique()),
            "escalated_docs": 0,
        }
    if rule_id == "L2-01":
        annotations = _rule_row_annotations(rule_id, result)
        if annotations:
            return {
                "lower_band_docs": _annotation_doc_count_by_field(
                    df, annotations, "bucket", "lower_band",
                ),
                "close_band_docs": _annotation_doc_count_by_field(
                    df, annotations, "bucket", "close_band",
                ),
                "razor_band_docs": _annotation_doc_count_by_field(
                    df, annotations, "bucket", "razor_band",
                ),
            }
        doc_scores = _document_max_scores(df, scores)
        return {
            "lower_band_docs": int(((doc_scores > 0) & (doc_scores < 0.60)).sum()),
            "close_band_docs": int(((doc_scores >= 0.60) & (doc_scores < 0.75)).sum()),
            "razor_band_docs": int((doc_scores >= 0.75).sum()),
        }
    if rule_id == "L2-02":
        annotations = _rule_row_annotations(rule_id, result)
        if annotations:
            return {
                "reference_match_docs": _annotation_doc_count_by_field(
                    df, annotations, "reason_code", "reference_match",
                ),
                "mixed_reference_fallback_docs": _annotation_doc_count_by_field(
                    df, annotations, "reason_code", "mixed_reference_fallback",
                ),
                "blank_reference_fallback_docs": _annotation_doc_count_by_field(
                    df, annotations, "reason_code", "blank_reference_fallback",
                ),
            }
        doc_scores = _document_max_scores(df, scores)
        return {
            "reference_match_docs": int((doc_scores >= 0.85).sum()),
            "mixed_reference_fallback_docs": int(
                ((doc_scores >= 0.70) & (doc_scores < 0.85)).sum()
            ),
            "blank_reference_fallback_docs": int(
                ((doc_scores > 0) & (doc_scores < 0.70)).sum()
            ),
        }
    if rule_id == "L1-06":
        immediate_docs = df.loc[scores >= 0.8, "document_id"].dropna().nunique()
        return {
            "immediate_docs": int(immediate_docs),
        }
    if rule_id == "L1-07":
        immediate_docs = df.loc[scores >= 0.8, "document_id"].dropna().nunique()
        if review_scores.gt(0).any():
            review_mask = review_scores > 0
        else:
            review_mask = (scores > 0) & (scores < 0.8)
        review_docs = df.loc[review_mask, "document_id"].dropna().nunique()
        return {
            "immediate_docs": int(immediate_docs),
            "review_docs": int(review_docs),
        }
    if rule_id == "L3-02":
        l302_scores = scores.combine(review_scores, max)
        population_docs = df.loc[
            (l302_scores > 0) & (l302_scores < 0.60),
            "document_id",
        ].dropna().nunique()
        priority_docs = df.loc[
            (l302_scores >= 0.60) & (l302_scores < 0.75),
            "document_id",
        ].dropna().nunique()
        control_bypass_docs = df.loc[
            l302_scores >= 0.75,
            "document_id",
        ].dropna().nunique()
        return {
            "manual_population_docs": int(population_docs),
            "priority_docs": int(priority_docs),
            "control_bypass_docs": int(control_bypass_docs),
        }
    if rule_id == "L3-04":
        low_docs = df.loc[
            (scores > 0) & (scores < 0.60),
            "document_id",
        ].dropna().nunique()
        priority_docs = df.loc[
            (scores >= 0.60) & (scores < 0.75),
            "document_id",
        ].dropna().nunique()
        high_docs = df.loc[scores >= 0.75, "document_id"].dropna().nunique()
        return {
            "closing_low_docs": int(low_docs),
            "closing_priority_docs": int(priority_docs),
            "closing_high_docs": int(high_docs),
        }
    if rule_id == "L3-09":
        review_docs = df.loc[
            (scores > 0) & (scores < 0.60),
            "document_id",
        ].dropna().nunique()
        priority_docs = df.loc[
            (scores >= 0.60) & (scores < 0.75),
            "document_id",
        ].dropna().nunique()
        high_docs = df.loc[scores >= 0.75, "document_id"].dropna().nunique()
        return {
            "suspense_aging_review_docs": int(review_docs),
            "suspense_aging_priority_docs": int(priority_docs),
            "suspense_aging_high_docs": int(high_docs),
        }
    if rule_id == "L3-03":
        ic_docs = _docs_for_mask(df, scores > 0)
        ic_exception_docs = _docs_for_rules(df, results, {"IC01", "IC02", "IC03"})
        graph_docs = _docs_for_rules(df, results, {"GR01", "GR03"})
        return {
            "ic_population_docs": len(ic_docs),
            "ic_exception_overlap_docs": len(ic_docs & ic_exception_docs),
            "graph_overlap_docs": len(ic_docs & graph_docs),
        }
    if rule_id == "L3-05":
        weekend = _bool_column(df, "is_weekend")
        holiday = _bool_column(df, "is_holiday")
        calendar_review = scores > 0
        return {
            "calendar_review_docs": len(_docs_for_mask(df, calendar_review)),
            "weekend_docs": len(_docs_for_mask(df, calendar_review & weekend)),
            "weekday_holiday_docs": len(
                _docs_for_mask(df, calendar_review & holiday & ~weekend)
            ),
            "weekend_holiday_docs": len(
                _docs_for_mask(df, calendar_review & weekend & holiday)
            ),
        }
    if rule_id == "L2-04":
        doc_scores = _document_max_scores(df, scores)
        immediate_docs = int((doc_scores >= 0.75).sum())
        review_docs = int(((doc_scores > 0) & (doc_scores < 0.75)).sum())
        return {
            "immediate_docs": immediate_docs,
            "review_docs": review_docs,
        }
    if rule_id == "L3-01":
        exact_denied_docs = df.loc[scores >= 0.65, "document_id"].dropna().nunique()
        category_review_docs = df.loc[
            (scores > 0) & (scores < 0.65),
            "document_id",
        ].dropna().nunique()
        return {
            "exact_denied_docs": int(exact_denied_docs),
            "category_review_docs": int(category_review_docs),
        }
    if rule_id == "L2-03":
        doc_scores = _document_max_scores(df, scores)
        high_docs = int((doc_scores >= 0.85).sum())
        medium_docs = int(((doc_scores >= 0.70) & (doc_scores < 0.85)).sum())
        low_docs = int(((doc_scores > 0) & (doc_scores < 0.70)).sum())
        return {
            "high_confidence_docs": high_docs,
            "medium_confidence_docs": medium_docs,
            "low_confidence_docs": low_docs,
        }
    if rule_id == "L2-05":
        annotations = _rule_row_annotations(rule_id, result)
        high_docs = _annotation_doc_count(
            df,
            annotations,
            "high_confidence_reversal",
        )
        candidate_docs = _annotation_doc_count(
            df,
            annotations,
            "candidate_reversal_clearing_reclass",
        )
        return {
            "high_confidence_reversal_docs": high_docs,
            "candidate_clearing_reclass_docs": candidate_docs,
        }
    if rule_id == "L3-06":
        confirmed_docs = df.loc[scores >= 0.40, "document_id"].dropna().nunique()
        normal_context_docs = df.loc[
            (scores > 0) & (scores < 0.40),
            "document_id",
        ].dropna().nunique()
        return {
            "confirmed_after_hours_docs": int(confirmed_docs),
            "normal_system_context_docs": int(normal_context_docs),
        }
    if rule_id == "L3-07":
        annotations = _rule_row_annotations(rule_id, result)
        if annotations:
            return {
                "late_posting_docs": _annotation_doc_count_by_field(
                    df, annotations, "direction", "late_posting",
                ),
                "forward_date_gap_docs": _annotation_doc_count_by_field(
                    df, annotations, "direction", "forward_date_gap",
                ),
                "moderate_gap_docs": _annotation_doc_count_by_field_suffix(
                    df,
                    annotations,
                    "bucket",
                    "_moderate_gap",
                ),
                "large_gap_docs": _annotation_doc_count_by_field_suffix(
                    df,
                    annotations,
                    "bucket",
                    "_large_gap",
                ),
                "extreme_gap_docs": _annotation_doc_count_by_field_suffix(
                    df,
                    annotations,
                    "bucket",
                    "_extreme_gap",
                ),
            }
        return {
            "moderate_gap_docs": int(
                df.loc[(scores > 0) & (scores < 0.60), "document_id"].dropna().nunique()
            ),
            "large_gap_docs": int(
                df.loc[(scores >= 0.60) & (scores < 0.75), "document_id"].dropna().nunique()
            ),
            "extreme_gap_docs": int(df.loc[scores >= 0.75, "document_id"].dropna().nunique()),
        }
    if rule_id == "L3-08":
        if "description_quality" not in df.columns:
            return {}
        quality = df["description_quality"].fillna("").astype(str).str.strip().str.lower()
        flagged = scores > 0
        missing_docs = df.loc[flagged & quality.eq("missing"), "document_id"].dropna().nunique()
        corrupted_docs = df.loc[
            flagged & quality.eq("corrupted"),
            "document_id",
        ].dropna().nunique()
        poor_docs = df.loc[flagged & quality.eq("poor"), "document_id"].dropna().nunique()
        return {
            "missing_description_docs": int(missing_docs),
            "corrupted_description_docs": int(corrupted_docs),
            "poor_legacy_docs": int(poor_docs),
        }
    if rule_id == "L3-10":
        annotations = _rule_row_annotations(rule_id, result)
        if annotations:
            return {
                "raw_sensitive_touch_docs": _annotation_doc_count_by_field(
                    df,
                    annotations,
                    "signal_category",
                    "raw_signal",
                ),
                "priority_case_docs": _annotation_doc_count_by_field(
                    df,
                    annotations,
                    "signal_category",
                    "priority_case",
                ),
                "normal_control_docs": _annotation_doc_count_by_field(
                    df,
                    annotations,
                    "signal_category",
                    "normal_control_candidate",
                ),
            }
        raw_docs = df.loc[
            (scores >= 0.30) & (scores < 0.60),
            "document_id",
        ].dropna().nunique()
        priority_docs = df.loc[scores >= 0.60, "document_id"].dropna().nunique()
        normal_docs = df.loc[
            (scores > 0) & (scores < 0.30),
            "document_id",
        ].dropna().nunique()
        return {
            "raw_sensitive_touch_docs": int(raw_docs),
            "priority_case_docs": int(priority_docs),
            "normal_control_docs": int(normal_docs),
        }
    if rule_id == "L3-11":
        cutoff_review_docs = df.loc[scores > 0, "document_id"].dropna().nunique()
        cutoff_priority_docs = df.loc[
            scores >= 0.30,
            "document_id",
        ].dropna().nunique()
        cutoff_high_docs = df.loc[scores >= 0.60, "document_id"].dropna().nunique()
        return {
            "cutoff_review_docs": int(cutoff_review_docs),
            "cutoff_priority_docs": int(cutoff_priority_docs),
            "cutoff_high_docs": int(cutoff_high_docs),
        }
    if rule_id == "L4-03":
        annotations = _rule_row_annotations(rule_id, result)
        if annotations:
            return {
                "high_amount_review_docs": len(_docs_for_mask(df, scores > 0)),
                "review_zscore_docs": _annotation_doc_count_by_field(
                    df,
                    annotations,
                    "bucket",
                    "review_zscore",
                ),
                "strong_zscore_docs": _annotation_doc_count_by_field(
                    df,
                    annotations,
                    "bucket",
                    "strong_zscore",
                ),
                "extreme_zscore_docs": _annotation_doc_count_by_field(
                    df,
                    annotations,
                    "bucket",
                    "extreme_zscore",
                ),
            }
        return {
            "high_amount_review_docs": len(_docs_for_mask(df, scores > 0)),
            "strong_or_extreme_docs": len(_docs_for_mask(df, scores >= 0.60)),
        }
    if rule_id == "L4-04":
        annotations = _rule_row_annotations(rule_id, result)
        if annotations:
            return {
                "rare_pair_review_docs": len(_docs_for_mask(df, scores > 0)),
                "ordinary_rare_pair_docs": _annotation_doc_count_by_list_field(
                    df,
                    annotations,
                    "reason_codes",
                    "rare_account_pair",
                ),
                "large_doc_distinct_pair_docs": _annotation_doc_count_by_list_field(
                    df,
                    annotations,
                    "reason_codes",
                    "large_doc_distinct_pair",
                ),
            }
        return {"rare_pair_review_docs": len(_docs_for_mask(df, scores > 0))}
    if rule_id == "L4-05":
        annotations = _rule_row_annotations(rule_id, result)
        if annotations:
            return {
                "behavior_review_docs": len(_docs_for_mask(df, scores > 0)),
                "sigma_outlier_docs": _annotation_doc_count_by_list_field(
                    df,
                    annotations,
                    "reason_codes",
                    "sigma_outlier",
                ),
                "low_volume_midnight_docs": _annotation_doc_count_by_list_field(
                    df,
                    annotations,
                    "reason_codes",
                    "low_volume_midnight",
                ),
                "high_context_midnight_docs": _annotation_doc_count_by_list_field(
                    df,
                    annotations,
                    "reason_codes",
                    "high_context_midnight",
                ),
                "rapid_approval_docs": _annotation_doc_count_by_list_field(
                    df,
                    annotations,
                    "reason_codes",
                    "rapid_approval",
                ),
            }
        return {
            "behavior_review_docs": len(_docs_for_mask(df, scores > 0)),
            "higher_priority_behavior_docs": len(_docs_for_mask(df, scores >= 0.60)),
        }
    if rule_id == "L4-06":
        annotations = _rule_row_annotations(rule_id, result)
        if annotations:
            return {
                "batch_review_docs": len(_docs_for_mask(df, scores > 0)),
                "period_end_concentration_docs": _annotation_doc_count_by_list_field(
                    df,
                    annotations,
                    "reason_codes",
                    "period_end_concentration",
                ),
                "simultaneous_creation_docs": _annotation_doc_count_by_list_field(
                    df,
                    annotations,
                    "reason_codes",
                    "simultaneous_creation",
                ),
                "amount_outlier_docs": _annotation_doc_count_by_list_field(
                    df,
                    annotations,
                    "reason_codes",
                    "amount_outlier",
                ),
            }
        return {"batch_review_docs": len(_docs_for_mask(df, scores > 0))}
    return {}


def _review_queue_docs(rule_id: str, fp_docs: int, score_bands: dict[str, int]) -> int:
    """Prefer explicit review bands over treating all non-label hits as FP queue."""
    if rule_id == "L1-05" and "review_docs" in score_bands:
        return int(score_bands["review_docs"])
    if rule_id == "L1-06":
        return 0
    if rule_id in {"L1-07", "L2-04"} and "review_docs" in score_bands:
        return int(score_bands["review_docs"])
    if rule_id == "L3-02":
        return int(score_bands.get("priority_docs", 0)) + int(
            score_bands.get("control_bypass_docs", 0)
        )
    if rule_id == "L3-04":
        return int(score_bands.get("closing_priority_docs", 0)) + int(
            score_bands.get("closing_high_docs", 0)
        )
    if rule_id == "L3-09":
        return int(score_bands.get("suspense_aging_priority_docs", 0)) + int(
            score_bands.get("suspense_aging_high_docs", 0)
        )
    if rule_id == "L3-03" and "ic_population_docs" in score_bands:
        return int(score_bands["ic_population_docs"])
    if rule_id == "L3-05" and "calendar_review_docs" in score_bands:
        return int(score_bands["calendar_review_docs"])
    if rule_id == "L3-06" and "confirmed_after_hours_docs" in score_bands:
        return int(score_bands["confirmed_after_hours_docs"])
    if rule_id == "L3-07" and "moderate_gap_docs" in score_bands:
        return (
            int(score_bands.get("moderate_gap_docs", 0))
            + int(score_bands.get("large_gap_docs", 0))
            + int(score_bands.get("extreme_gap_docs", 0))
        )
    if rule_id == "L3-08" and "missing_description_docs" in score_bands:
        return (
            int(score_bands.get("missing_description_docs", 0))
            + int(score_bands.get("corrupted_description_docs", 0))
            + int(score_bands.get("poor_legacy_docs", 0))
        )
    if rule_id == "L3-10" and "priority_case_docs" in score_bands:
        return int(score_bands["priority_case_docs"])
    if rule_id == "L3-11" and "cutoff_review_docs" in score_bands:
        return int(score_bands["cutoff_review_docs"])
    if rule_id == "L4-03" and "high_amount_review_docs" in score_bands:
        return int(score_bands["high_amount_review_docs"])
    if rule_id == "L4-04" and "rare_pair_review_docs" in score_bands:
        return int(score_bands["rare_pair_review_docs"])
    if rule_id == "L2-01" and "close_band_docs" in score_bands:
        return int(score_bands.get("close_band_docs", 0)) + int(
            score_bands.get("razor_band_docs", 0)
        )
    if rule_id == "L2-02" and "mixed_reference_fallback_docs" in score_bands:
        return int(score_bands.get("mixed_reference_fallback_docs", 0)) + int(
            score_bands.get("blank_reference_fallback_docs", 0)
        )
    if rule_id == "L2-03":
        return int(score_bands.get("medium_confidence_docs", 0)) + int(
            score_bands.get("low_confidence_docs", 0)
        )
    if rule_id == "L2-05" and "candidate_clearing_reclass_docs" in score_bands:
        return int(score_bands["candidate_clearing_reclass_docs"])
    if rule_id == "L3-01" and "category_review_docs" in score_bands:
        return int(score_bands["category_review_docs"])
    if rule_id == "L4-05" and "behavior_review_docs" in score_bands:
        return int(score_bands["behavior_review_docs"])
    if rule_id == "L4-06" and "batch_review_docs" in score_bands:
        return int(score_bands["batch_review_docs"])
    return fp_docs


def _docs_for_mask(df: pd.DataFrame, mask: pd.Series) -> set[str]:
    if "document_id" not in df.columns:
        return set()
    return set(df.loc[mask.reindex(df.index, fill_value=False), "document_id"].dropna().unique())


def _document_max_scores(df: pd.DataFrame, scores: pd.Series) -> pd.Series:
    """Collapse row scores to one max score per document."""
    if "document_id" not in df.columns:
        return pd.Series(dtype="float64")
    frame = pd.DataFrame({
        "document_id": df["document_id"],
        "score": scores.reindex(df.index, fill_value=0.0),
    }).dropna(subset=["document_id"])
    if frame.empty:
        return pd.Series(dtype="float64")
    return frame.groupby("document_id", sort=False)["score"].max()


def _bool_column(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(False, index=df.index)
    return df[column].fillna(False).astype(bool)


def _docs_for_rules(
    df: pd.DataFrame,
    results: Mapping[str, DetectionResult],
    rule_ids: set[str],
) -> set[str]:
    docs: set[str] = set()
    if "document_id" not in df.columns:
        return docs
    for result in results.values():
        for other_rule_id in rule_ids:
            if other_rule_id not in result.details.columns:
                continue
            docs.update(_docs_for_mask(df, result.details[other_rule_id] > 0))
    return docs


def _rule_row_annotations(rule_id: str, result: DetectionResult) -> dict:
    """Return detector-provided row annotations for a rule."""
    annotations = result.metadata.get("row_annotations", {}) if result.metadata else {}
    rule_annotations = annotations.get(rule_id, {})
    return dict(rule_annotations) if isinstance(rule_annotations, dict) else {}


def _annotation_doc_count(
    df: pd.DataFrame,
    annotations: dict,
    interpretation_code: str,
) -> int:
    """Count distinct documents whose row annotation has the requested interpretation."""
    if not annotations or "document_id" not in df.columns:
        return 0

    indices = [
        index
        for index, annotation in annotations.items()
        if isinstance(annotation, dict)
        and annotation.get("interpretation_code") == interpretation_code
        and index in df.index
    ]
    if not indices:
        return 0
    return int(df.loc[indices, "document_id"].dropna().nunique())


def _annotation_doc_count_by_field(
    df: pd.DataFrame,
    annotations: dict,
    field_name: str,
    expected_value: str,
) -> int:
    """Count distinct documents whose row annotation field matches a value."""
    if not annotations or "document_id" not in df.columns:
        return 0

    indices = [
        index
        for index, annotation in annotations.items()
        if isinstance(annotation, dict)
        and annotation.get(field_name) == expected_value
        and index in df.index
    ]
    if not indices:
        return 0
    return int(df.loc[indices, "document_id"].dropna().nunique())


def _annotation_doc_count_by_field_prefix(
    df: pd.DataFrame,
    annotations: dict,
    field_name: str,
    expected_prefix: str,
) -> int:
    """Count distinct documents whose row annotation field starts with a prefix."""
    if not annotations or "document_id" not in df.columns:
        return 0

    indices = [
        index
        for index, annotation in annotations.items()
        if isinstance(annotation, dict)
        and str(annotation.get(field_name, "")).startswith(expected_prefix)
        and index in df.index
    ]
    if not indices:
        return 0
    return int(df.loc[indices, "document_id"].dropna().nunique())


def _annotation_doc_count_by_field_suffix(
    df: pd.DataFrame,
    annotations: dict,
    field_name: str,
    expected_suffix: str,
) -> int:
    """Count distinct documents whose row annotation field ends with a suffix."""
    if not annotations or "document_id" not in df.columns:
        return 0

    indices = [
        index
        for index, annotation in annotations.items()
        if isinstance(annotation, dict)
        and str(annotation.get(field_name, "")).endswith(expected_suffix)
        and index in df.index
    ]
    if not indices:
        return 0
    return int(df.loc[indices, "document_id"].dropna().nunique())


def _annotation_doc_count_by_list_field(
    df: pd.DataFrame,
    annotations: dict,
    field_name: str,
    expected_value: str,
) -> int:
    """Count distinct documents whose row annotation list contains a value."""
    if not annotations or "document_id" not in df.columns:
        return 0

    indices = []
    for index, annotation in annotations.items():
        if not isinstance(annotation, dict) or index not in df.index:
            continue
        value = annotation.get(field_name, [])
        if isinstance(value, str):
            values = {value}
        else:
            try:
                values = {str(item) for item in value}
            except TypeError:
                values = set()
        if expected_value in values:
            indices.append(index)
    if not indices:
        return 0
    return int(df.loc[indices, "document_id"].dropna().nunique())


def _count_overlap_docs(
    rule_id: str,
    df: pd.DataFrame,
    results: Mapping[str, DetectionResult],
    flagged_doc_set: set[str],
) -> int:
    """Count flagged documents that also hit at least one different rule."""
    if not flagged_doc_set or "document_id" not in df.columns:
        return 0

    other_rule_mask = pd.Series(False, index=df.index)
    for result in results.values():
        for other_rule_id in result.details.columns:
            if other_rule_id == rule_id:
                continue
            other_rule_mask = other_rule_mask | (
                result.details[other_rule_id].reindex(df.index, fill_value=0.0) > 0
            )

    other_docs = set(df.loc[other_rule_mask, "document_id"].dropna().unique())
    return len(flagged_doc_set & other_docs)


def _label_doc_set_for_rule(
    rule_id: str,
    df: pd.DataFrame,
    labels: pd.DataFrame,
) -> set[str]:
    """Return rule-specific ground-truth document ids.

    Why: L1-01 is a structural balance gate. Its ground truth should be every document
    whose debit-credit sum is actually unbalanced, regardless of sidecar label type.
    """
    sidecar_docs = _load_rule_truth_doc_set(rule_id, df)
    if sidecar_docs is not None:
        return sidecar_docs

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
        gl = (
            df["gl_account"]
            .fillna("")
            .astype(str)
            .str.strip()
            .str.lower()
            .str.replace(r"\.0+$", "", regex=True)
        )
        high_risk_mask = gl.isin({"1190", "2190"}) | gl.str.startswith(("111", "112", "113"))
        return set(df.loc[high_risk_mask, "document_id"].dropna().unique())

    if rule_id == "L4-01":
        if not {"document_id", "anomaly_type"}.issubset(labels.columns):
            return set()
        revenue = labels[labels["anomaly_type"].eq("RevenueManipulation")].copy()
        if revenue.empty:
            return set()
        if "metadata_json" not in revenue.columns:
            return set(revenue["document_id"].dropna().unique())

        def is_direct_l401(metadata_json: object) -> bool:
            if not isinstance(metadata_json, str) or not metadata_json.strip():
                return False
            try:
                metadata = json.loads(metadata_json)
            except json.JSONDecodeError:
                return False
            return (
                metadata.get("revenue_subtype") == "high_value_revenue_outlier"
                and bool(metadata.get("is_l401_direct_truth"))
            )

        direct_mask = revenue["metadata_json"].map(is_direct_l401)
        direct_docs = set(revenue.loc[direct_mask, "document_id"].dropna().unique())
        return direct_docs

    if rule_id == "L4-02":
        return set()

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
    labels_dir: str | Path | None = None,
    fiscal_year: int | str | None = None,
) -> PerformanceReport:
    """Build a unified ground-truth performance report."""
    per_rule = per_rule_label_analysis(df, results, labels)
    overall = overall_label_analysis(df, agg_df, labels)
    normalized_results = normalize_results_by_track(results)
    benford_benchmarks: list[BenfordBenchmarkMetric] = []
    if labels_dir is not None and "benford" in normalized_results:
        benford_benchmarks = build_benford_population_benchmarks(
            df,
            normalized_results["benford"],
            labels_dir,
            fiscal_year=fiscal_year,
        )
    analytical_review_metrics: list[AnalyticalReviewMetric] = []
    if labels_dir is not None and "layer_d" in normalized_results:
        analytical_review_metrics = build_analytical_review_metrics(
            df,
            normalized_results["layer_d"],
            labels_dir,
            fiscal_year=fiscal_year,
            all_results=normalized_results,
        )
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
        total_docs = (
            int(df["document_id"].dropna().nunique())
            if "document_id" in df.columns
            else int(len(df))
        )

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
                rule_objective=str(item["rule_objective"]),
                broad_fraud_type=str(item["broad_fraud_type"]),
                expected_coverage=str(item["expected_coverage"]),
                overlap_docs=int(item["overlap_docs"]),
                standalone_docs=int(item["standalone_docs"]),
                review_queue_docs=int(item["review_queue_docs"]),
                breakdown=dict(item["breakdown"]),
                score_bands=dict(item["score_bands"]),
            )
            for item in per_rule
            if item["status"] != "skipped"
        ],
        benford_benchmarks=benford_benchmarks,
        analytical_review_metrics=analytical_review_metrics,
    )


def _calc_f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None or (precision + recall) == 0:
        return None
    return 2 * precision * recall / (precision + recall)


def _resolve_benford_year(df: pd.DataFrame, fiscal_year: int | str | None) -> str | None:
    if fiscal_year is not None:
        return str(fiscal_year)
    if "fiscal_year" not in df.columns:
        return None
    years = sorted(df["fiscal_year"].dropna().astype(str).unique())
    return years[0] if len(years) == 1 else None


def _normalize_gl_account(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        return text[:-2]
    return text


def _account_review_group_key(
    year: str | int,
    company_code: object,
    gl_account: object,
) -> tuple[str, str, str]:
    return (str(year), str(company_code), _normalize_gl_account(gl_account))


def _d01_predicted_group_keys(
    result: DetectionResult,
    year: str | int,
) -> set[tuple[str, str, str]]:
    findings = result.metadata.get("account_activity_variance", []) if result.metadata else []
    if not isinstance(findings, list):
        return set()
    keys: set[tuple[str, str, str]] = set()
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        keys.add(_account_review_group_key(
            year,
            finding.get("company_code", ""),
            finding.get("gl_account", ""),
        ))
    return keys


def _d02_predicted_group_keys(
    result: DetectionResult,
    year: str | int,
) -> set[tuple[str, str, str]]:
    diagnostics = result.metadata.get("d02_account_diagnostics", []) if result.metadata else []
    if not isinstance(diagnostics, list):
        return set()
    keys: set[tuple[str, str, str]] = set()
    for item in diagnostics:
        if not isinstance(item, dict) or not item.get("flagged"):
            continue
        keys.add(_account_review_group_key(
            year,
            item.get("company_code", ""),
            item.get("gl_account", ""),
        ))
    return keys


def _account_review_sidecar_keys(
    labels_dir: Path,
    stem: str,
    year: str | int,
) -> set[tuple[str, str, str]]:
    path = labels_dir / f"{stem}_{year}.csv"
    if not path.exists():
        path = labels_dir / f"{stem}.csv"
    if not path.exists():
        return set()
    sidecar = pd.read_csv(path)
    required = {"fiscal_year", "company_code", "gl_account"}
    if not required.issubset(sidecar.columns):
        return set()
    year_text = str(year)
    if "fiscal_year" in sidecar.columns:
        sidecar = sidecar[sidecar["fiscal_year"].astype(str).eq(year_text)]
    return {
        _account_review_group_key(row.fiscal_year, row.company_code, row.gl_account)
        for row in sidecar.itertuples(index=False)
    }


def _account_review_sidecar_exists(labels_dir: Path, stem: str, year: str | int) -> bool:
    return (labels_dir / f"{stem}_{year}.csv").exists() or (labels_dir / f"{stem}.csv").exists()


def _analytical_overlap_docs(
    df: pd.DataFrame,
    predicted_groups: set[tuple[str, str, str]],
    results: Mapping[str, DetectionResult],
    rule_code: str,
) -> int:
    """Count docs inside D01/D02 groups that also hit row/document-level rules."""
    required = {"document_id", "fiscal_year", "company_code", "gl_account"}
    if not predicted_groups or not required.issubset(df.columns):
        return 0

    row_keys = pd.Series(
        [
            _account_review_group_key(row.fiscal_year, row.company_code, row.gl_account)
            for row in df.itertuples(index=False)
        ],
        index=df.index,
    )
    group_mask = row_keys.isin(predicted_groups)
    if not group_mask.any():
        return 0

    other_rule_mask = pd.Series(False, index=df.index)
    for result in results.values():
        for other_rule_id in result.details.columns:
            if other_rule_id in {rule_code, "D01", "D02"}:
                continue
            other_rule_mask = other_rule_mask | (
                result.details[other_rule_id].reindex(df.index, fill_value=0.0) > 0
            )

    return int(df.loc[group_mask & other_rule_mask, "document_id"].dropna().nunique())


def _benford_group_key(year: str, company_code: object, gl_account: object) -> tuple[str, str, str]:
    return (str(year), str(company_code), _normalize_gl_account(gl_account))


def _benford_predicted_group_keys(
    findings: object,
    year: str,
) -> set[tuple[str, str, str]]:
    if not isinstance(findings, list):
        return set()
    keys: set[tuple[str, str, str]] = set()
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        keys.add(_benford_group_key(
            year,
            finding.get("company_code"),
            finding.get("gl_account"),
        ))
    return keys


def _benford_sidecar_keys(
    labels_dir: Path,
    stem: str,
    year: str,
) -> set[tuple[str, str, str]]:
    path = labels_dir / f"{stem}_{year}.csv"
    if not path.exists():
        return set()
    sidecar = pd.read_csv(path)
    required = {"fiscal_year", "company_code", "gl_account"}
    if not required.issubset(sidecar.columns):
        return set()
    return {
        _benford_group_key(row.fiscal_year, row.company_code, row.gl_account)
        for row in sidecar.itertuples(index=False)
    }


def _benford_candidate_metrics(
    df: pd.DataFrame,
    result: DetectionResult,
    labels_dir: Path,
    year: str,
) -> list[BenfordBenchmarkMetric]:
    path = labels_dir / f"benford_drilldown_candidates_{year}.csv"
    if not path.exists() or not {"document_id", "line_number"}.issubset(df.columns):
        return []

    candidate_indices = (
        result.metadata.get("benford_candidate_indices", [])
        if result.metadata else []
    )
    predicted_line_keys: set[tuple[str, object]] = set()
    predicted_doc_keys: set[str] = set()
    if candidate_indices:
        candidate_rows = df.loc[candidate_indices, ["document_id", "line_number"]].copy()
        candidate_rows["document_id"] = candidate_rows["document_id"].astype(str)
        predicted_line_keys = set(
            candidate_rows[["document_id", "line_number"]].itertuples(index=False, name=None)
        )
        predicted_doc_keys = set(candidate_rows["document_id"])

    truth = pd.read_csv(path)
    if not {"document_id", "line_number"}.issubset(truth.columns):
        return []
    truth["document_id"] = truth["document_id"].astype(str)
    truth_line_keys = set(
        truth[["document_id", "line_number"]].itertuples(index=False, name=None)
    )
    truth_doc_keys = set(truth["document_id"])

    line_tp = len(predicted_line_keys & truth_line_keys)
    line_fp = len(predicted_line_keys - truth_line_keys)
    line_fn = len(truth_line_keys - predicted_line_keys)
    doc_tp = len(predicted_doc_keys & truth_doc_keys)
    doc_fp = len(predicted_doc_keys - truth_doc_keys)
    doc_fn = len(truth_doc_keys - predicted_doc_keys)

    return [
        BenfordBenchmarkMetric(
            year=str(year),
            benchmark="drilldown_candidate_rows",
            truth_count=len(truth_line_keys),
            hit_count=line_tp,
            miss_count=line_fn,
            extra_count=line_fp,
            precision=line_tp / (line_tp + line_fp) if (line_tp + line_fp) else None,
            recall=line_tp / (line_tp + line_fn) if (line_tp + line_fn) else None,
            note="candidate rows are review scope, not row-level fraud truth",
        ),
        BenfordBenchmarkMetric(
            year=str(year),
            benchmark="drilldown_candidate_docs",
            truth_count=len(truth_doc_keys),
            hit_count=doc_tp,
            miss_count=doc_fn,
            extra_count=doc_fp,
            precision=doc_tp / (doc_tp + doc_fp) if (doc_tp + doc_fp) else None,
            recall=doc_tp / (doc_tp + doc_fn) if (doc_tp + doc_fn) else None,
            note="candidate documents are review scope, not row-level fraud truth",
        ),
    ]

