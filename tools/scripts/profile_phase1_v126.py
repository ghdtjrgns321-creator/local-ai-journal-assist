"""Profile PHASE1 execution on DataSynth v126 in explicit stages.

This runner is intentionally verbose and checkpointed. It avoids calling the
full pipeline as one opaque block so long-running stages can be identified.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import get_audit_rules, get_risk_keywords, get_settings
from src.detection.anomaly_layer import AnomalyDetector
from src.detection.benford_detector import BenfordDetector
from src.detection.fraud_layer import FraudLayer
from src.detection.fraud_rules_access import build_access_rule_cache
from src.detection.fraud_rules_groupby import (
    _flag_document_duplicate_entries,
    _flag_exact_duplicate_entries,
    _flag_ic_r2r_split_population,
    _flag_near_duplicate_entries,
    _flag_o2c_offset_duplicate_entries,
    _flag_reference_duplicate_entries,
    _flag_split_duplicate_entries,
    _prepare_duplicate_entry_work,
    _score_l203_duplicate_entries,
)
from src.detection.integrity_layer import IntegrityDetector
from src.detection.phase1_case_builder import build_phase1_case_result, save_phase1_case_result
from src.detection.score_aggregator import aggregate_scores
from src.feature.engine import FeatureCategory, _run_category
from src.ingest.datasynth_labels import apply_datasynth_label_mode, set_source_path
from src.services.analysis_service import make_phase_settings


DATE_COLUMNS = ("posting_date", "document_date", "entry_date", "approval_date", "created_at")
PHASE1_USECOLS = {
    "document_id",
    "company_code",
    "fiscal_year",
    "fiscal_period",
    "posting_date",
    "document_date",
    "document_type",
    "currency",
    "reference",
    "header_text",
    "created_by",
    "user_persona",
    "source",
    "business_process",
    "approved_by",
    "approval_date",
    "sod_violation",
    "sod_conflict_type",
    "document_number",
    "line_number",
    "gl_account",
    "debit_amount",
    "credit_amount",
    "local_amount",
    "cost_center",
    "profit_center",
    "line_text",
    "trading_partner",
    "auxiliary_account_number",
    "auxiliary_account_label",
    "lettrage",
    "lettrage_date",
    "amount_open",
    "is_cleared",
    "settlement_status",
    "settlement_date",
    "description_quality",
    "exceeds_threshold",
}
PHASE1_CATEGORIES = (
    FeatureCategory.TIME,
    FeatureCategory.AMOUNT,
    FeatureCategory.PATTERN,
    FeatureCategory.TEXT,
)


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _log(message: str) -> None:
    print(f"[{_now()}] {message}", flush=True)


def _write_checkpoint(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _elapsed(start: float) -> float:
    return round(time.perf_counter() - start, 3)


def _read_data(data_dir: Path, checkpoint: Path, summary: dict[str, Any]) -> pd.DataFrame:
    source = data_dir / "journal_entries.csv"
    t0 = time.perf_counter()
    _log(f"read_csv start: {source}")
    df = pd.read_csv(source, usecols=lambda column: column in PHASE1_USECOLS, low_memory=False)
    for column in DATE_COLUMNS:
        if column in df.columns:
            df[column] = pd.to_datetime(df[column], errors="coerce")
    df = set_source_path(df, source)
    summary["stages"]["read_csv"] = {
        "elapsed_sec": _elapsed(t0),
        "rows": int(len(df)),
        "documents": int(df["document_id"].nunique()) if "document_id" in df.columns else None,
    }
    _write_checkpoint(checkpoint, summary)
    _log(f"read_csv done: {summary['stages']['read_csv']}")
    return df


def _run_features(
    df: pd.DataFrame,
    *,
    settings,
    audit_rules: dict,
    risk_keywords: dict,
    checkpoint: Path,
    summary: dict[str, Any],
) -> pd.DataFrame:
    raw_rules = audit_rules
    pattern_rules = audit_rules.get("patterns", audit_rules)
    summary["stages"].setdefault("features", {})

    for category in PHASE1_CATEGORIES:
        warnings: list[str] = []
        t0 = time.perf_counter()
        _log(f"feature start: {category.value}")
        success = _run_category(
            df,
            category,
            settings=settings,
            rules=pattern_rules,
            raw_rules=raw_rules,
            risk_keywords=risk_keywords,
            include_morpheme_tokens=False,
            warnings_out=warnings,
        )
        summary["stages"]["features"][category.value] = {
            "elapsed_sec": _elapsed(t0),
            "success": bool(success),
            "warnings": warnings[:20],
            "columns": int(len(df.columns)),
        }
        _write_checkpoint(checkpoint, summary)
        _log(f"feature done: {category.value} {summary['stages']['features'][category.value]}")
    return df


def _run_detectors(
    df: pd.DataFrame,
    *,
    settings,
    audit_rules: dict,
    checkpoint: Path,
    summary: dict[str, Any],
):
    detectors = [
        IntegrityDetector(settings, audit_rules=audit_rules),
        FraudLayer(settings, audit_rules=audit_rules),
        AnomalyDetector(settings, audit_rules=audit_rules),
        BenfordDetector(settings),
    ]
    results = []
    summary["stages"].setdefault("detectors", {})
    for detector in detectors:
        t0 = time.perf_counter()
        _log(f"detector start: {detector.track_name}")
        if isinstance(detector, FraudLayer):
            result = _run_fraud_layer_rule_by_rule(
                detector,
                df,
                checkpoint=checkpoint,
                summary=summary,
            )
        elif isinstance(detector, AnomalyDetector):
            result = _run_anomaly_layer_rule_by_rule(
                detector,
                df,
                checkpoint=checkpoint,
                summary=summary,
            )
        else:
            result = detector.detect(df)
        results.append(result)
        summary["stages"]["detectors"][detector.track_name] = {
            "elapsed_sec": _elapsed(t0),
            "flagged_count": int(result.flagged_count),
            "rules_run": int(result.total_rules_run),
            "warnings": list(result.warnings or [])[:20],
        }
        _write_checkpoint(checkpoint, summary)
        _log(f"detector done: {detector.track_name} {summary['stages']['detectors'][detector.track_name]}")
    return results


def _run_anomaly_layer_rule_by_rule(
    detector: AnomalyDetector,
    df: pd.DataFrame,
    *,
    checkpoint: Path,
    summary: dict[str, Any],
):
    warnings: list[str] = []
    skipped: list[str] = []
    rule_results: dict[str, pd.Series] = {}
    layer_start = time.perf_counter()

    summary["stages"].setdefault("detector_rules", {}).setdefault("layer_c", {})
    for rule_id, func, kwargs in detector._build_registry():  # noqa: SLF001 - profiler only
        t0 = time.perf_counter()
        _log(f"layer_c rule start: {rule_id}")
        try:
            flagged = func(df, **kwargs)
            rule_results[rule_id] = flagged
            score_series = flagged.attrs.get("score_series") if hasattr(flagged, "attrs") else None
            max_score = float(pd.Series(score_series).max()) if score_series is not None else None
            summary["stages"]["detector_rules"]["layer_c"][rule_id] = {
                "elapsed_sec": _elapsed(t0),
                "status": "ok",
                "flagged_rows": int(pd.Series(flagged).fillna(False).astype(bool).sum()),
                "max_score": max_score,
            }
        except Exception as exc:
            skipped.append(rule_id)
            warnings.append(f"{rule_id} failed: {exc}")
            summary["stages"]["detector_rules"]["layer_c"][rule_id] = {
                "elapsed_sec": _elapsed(t0),
                "status": "failed",
                "error": repr(exc),
            }
        _write_checkpoint(checkpoint, summary)
        _log(f"layer_c rule done: {rule_id} {summary['stages']['detector_rules']['layer_c'][rule_id]}")

    elapsed = time.perf_counter() - layer_start
    return detector._build_result(df, rule_results, skipped, warnings, elapsed)  # noqa: SLF001


def _run_fraud_layer_rule_by_rule(
    detector: FraudLayer,
    df: pd.DataFrame,
    *,
    checkpoint: Path,
    summary: dict[str, Any],
):
    """Run FraudLayer internals one rule at a time for bottleneck isolation."""

    warnings: list[str] = []
    skipped: list[str] = []
    coverage_issues: list[dict[str, Any]] = []
    rule_results: dict[str, pd.Series] = {}
    access_cache = build_access_rule_cache(df)
    layer_start = time.perf_counter()

    summary["stages"].setdefault("detector_rules", {}).setdefault("layer_b", {})
    for rule_id, func, kwargs in detector._build_registry():  # noqa: SLF001 - profiler only
        missing_inputs = detector._missing_inputs(rule_id, df)  # noqa: SLF001 - profiler only
        if missing_inputs:
            skipped.append(rule_id)
            warnings.append(f"{rule_id} skipped: missing inputs {missing_inputs}")
            summary["stages"]["detector_rules"]["layer_b"][rule_id] = {
                "elapsed_sec": 0.0,
                "status": "skipped",
                "missing_inputs": missing_inputs,
            }
            _write_checkpoint(checkpoint, summary)
            continue

        t0 = time.perf_counter()
        _log(f"layer_b rule start: {rule_id}")
        try:
            if rule_id in {"L1-05", "L1-06", "L1-07", "L1-09"}:
                kwargs = {**kwargs, "cache": access_cache}
            if rule_id == "L2-03":
                flagged = _profile_l203_duplicate_entry(
                    df,
                    checkpoint=checkpoint,
                    summary=summary,
                    **kwargs,
                )
            else:
                flagged = func(df, **kwargs)
            rule_results[rule_id] = flagged
            coverage_issues.extend(detector._coverage_issues(rule_id, df))  # noqa: SLF001
            score_series = flagged.attrs.get("score_series") if hasattr(flagged, "attrs") else None
            max_score = float(pd.Series(score_series).max()) if score_series is not None else None
            summary["stages"]["detector_rules"]["layer_b"][rule_id] = {
                "elapsed_sec": _elapsed(t0),
                "status": "ok",
                "flagged_rows": int(pd.Series(flagged).fillna(False).astype(bool).sum()),
                "max_score": max_score,
            }
        except Exception as exc:
            skipped.append(rule_id)
            warnings.append(f"{rule_id} failed: {exc}")
            summary["stages"]["detector_rules"]["layer_b"][rule_id] = {
                "elapsed_sec": _elapsed(t0),
                "status": "failed",
                "error": repr(exc),
            }
        _write_checkpoint(checkpoint, summary)
        _log(f"layer_b rule done: {rule_id} {summary['stages']['detector_rules']['layer_b'][rule_id]}")

    elapsed = time.perf_counter() - layer_start
    return detector._build_result(  # noqa: SLF001 - profiler only
        df=df,
        rule_results=rule_results,
        skipped=skipped,
        warnings=warnings,
        elapsed=elapsed,
        coverage_issues=coverage_issues,
    )


def _profile_l203_duplicate_entry(
    df: pd.DataFrame,
    *,
    checkpoint: Path,
    summary: dict[str, Any],
    amount_tolerance: float = 0.02,
    fuzzy_threshold: int = 80,
    window_days: int = 7,
    split_window_days: int = 3,
    max_group_size: int = 1000,
) -> pd.Series:
    """Profile L2-03 duplicate-entry substeps and return a compatible Series."""

    summary["stages"].setdefault("detector_rule_steps", {}).setdefault("L2-03", {})

    def run_step(name: str, fn):
        t0 = time.perf_counter()
        _log(f"L2-03 step start: {name}")
        value = fn()
        if isinstance(value, pd.DataFrame):
            nonzero_rows = len(value)
            extra = {"columns": int(len(value.columns))}
        else:
            series = pd.Series(value, index=df.index)
            nonzero_rows = int(pd.to_numeric(series, errors="coerce").fillna(0.0).gt(0).sum())
            extra = {}
        summary["stages"]["detector_rule_steps"]["L2-03"][name] = {
            "elapsed_sec": _elapsed(t0),
            "nonzero_rows": nonzero_rows,
            **extra,
        }
        _write_checkpoint(checkpoint, summary)
        _log(f"L2-03 step done: {name} {summary['stages']['detector_rule_steps']['L2-03'][name]}")
        return value

    work = run_step("prepare_work", lambda: _prepare_duplicate_entry_work(df))
    document_scores = run_step(
        "document_duplicate",
        lambda: _flag_document_duplicate_entries(
            work,
            df,
            amount_tolerance=amount_tolerance,
            fuzzy_threshold=fuzzy_threshold,
            window_days=window_days,
            max_group_size=max_group_size,
        ),
    )
    exact_scores = run_step("exact_duplicate", lambda: _flag_exact_duplicate_entries(work))
    reference_scores = run_step(
        "reference_duplicate",
        lambda: _flag_reference_duplicate_entries(
            work,
            amount_tolerance=amount_tolerance,
            window_days=window_days,
        ),
    )
    near_scores = run_step(
        "near_duplicate",
        lambda: _flag_near_duplicate_entries(
            work,
            amount_tolerance=amount_tolerance,
            fuzzy_threshold=fuzzy_threshold,
            window_days=window_days,
            max_group_size=max_group_size,
        ),
    )
    split_scores = run_step(
        "split_duplicate",
        lambda: _flag_split_duplicate_entries(
            work,
            amount_tolerance=amount_tolerance,
            split_window_days=split_window_days,
            max_group_size=max_group_size,
        ),
    )
    o2c_offset_scores = run_step(
        "o2c_offset_duplicate",
        lambda: _flag_o2c_offset_duplicate_entries(work, df),
    )
    ic_split_scores = run_step(
        "ic_split_duplicate",
        lambda: _flag_ic_r2r_split_population(work, df, split_window_days=split_window_days),
    )

    t0 = time.perf_counter()
    _log("L2-03 step start: combine")
    score_frame = pd.DataFrame({
        "document_duplicate": document_scores,
        "exact_duplicate": exact_scores,
        "reference_duplicate": reference_scores,
        "near_duplicate": near_scores,
        "split_duplicate": split_scores,
        "o2c_offset_duplicate": o2c_offset_scores,
        "ic_split_duplicate": ic_split_scores,
    }, index=df.index)
    confidence = score_frame.max(axis=1).fillna(0.0)
    result = confidence > 0
    score_series = _score_l203_duplicate_entries(df, result, confidence, score_frame)

    reason_counts: dict[str, int] = {}
    confidence_band_counts = {"high": 0, "medium": 0, "low": 0, "population": 0}
    row_annotations: dict[object, dict[str, object]] = {}
    for idx in confidence[confidence > 0].index:
        row_scores = score_frame.loc[idx]
        matched = row_scores[row_scores > 0].sort_values(ascending=False)
        primary_reason = str(matched.index[0])
        primary_confidence = float(matched.iloc[0])
        score = float(score_series.loc[idx])
        if score >= 0.85:
            confidence_band = "high"
        elif score >= 0.35:
            confidence_band = "medium"
        elif score > 0:
            confidence_band = "low"
        else:
            confidence_band = "population"
        reason_counts[primary_reason] = reason_counts.get(primary_reason, 0) + 1
        confidence_band_counts[confidence_band] += 1
        row_annotations[idx] = {
            "reason_code": primary_reason,
            "matched_reason_codes": matched.index.tolist(),
            "raw_confidence": round(primary_confidence, 4),
            "confidence": round(score, 4),
            "confidence_band": confidence_band,
        }

    result.attrs["score_series"] = score_series
    result.attrs["breakdown"] = {
        "flagged_rows": int(result.sum()),
        "scored_rows": int(score_series.gt(0).sum()),
        "zero_score_rows": int((result & score_series.eq(0)).sum()),
        "reason_counts": reason_counts,
        "confidence_band_counts": confidence_band_counts,
    }
    result.attrs["row_annotations"] = row_annotations
    summary["stages"]["detector_rule_steps"]["L2-03"]["combine"] = {
        "elapsed_sec": _elapsed(t0),
        "nonzero_rows": int(result.sum()),
        "scored_rows": int(score_series.gt(0).sum()),
    }
    _write_checkpoint(checkpoint, summary)
    _log(f"L2-03 step done: combine {summary['stages']['detector_rule_steps']['L2-03']['combine']}")
    return result


def _aggregate_and_case(
    df: pd.DataFrame,
    results,
    *,
    settings,
    data_dir: Path,
    checkpoint: Path,
    summary: dict[str, Any],
) -> pd.DataFrame:
    t0 = time.perf_counter()
    _log("aggregate start")
    agg_df = aggregate_scores(df, results, settings=settings)
    for col in agg_df.columns:
        df[col] = agg_df[col].values
    summary["stages"]["aggregate"] = {
        "elapsed_sec": _elapsed(t0),
        "risk_summary": {
            str(k): int(v)
            for k, v in df["risk_level"].value_counts().to_dict().items()
        } if "risk_level" in df.columns else {},
    }
    _write_checkpoint(checkpoint, summary)
    _log(f"aggregate done: {summary['stages']['aggregate']}")

    t0 = time.perf_counter()
    _log("phase1 case builder start")
    phase1_result = build_phase1_case_result(
        df,
        results,
        company_id="_anonymous",
        batch_id="datasynth_v126_profiled_phase1",
        dataset_id=str(data_dir),
        phase1_case_config={"phase1_case": {}},
    )
    artifact_path = save_phase1_case_result(phase1_result)
    summary["stages"]["phase1_case_builder"] = {
        "elapsed_sec": _elapsed(t0),
        "case_count": len(phase1_result.cases),
        "macro_finding_count": int(phase1_result.metadata.get("macro_finding_count", 0) or 0),
        "artifact_path": str(artifact_path),
        "theme_summaries": [theme.model_dump() for theme in phase1_result.theme_summaries],
    }
    _write_checkpoint(checkpoint, summary)
    _log(f"phase1 case builder done: {summary['stages']['phase1_case_builder']}")
    return df


def _evaluate_manipulated(
    df: pd.DataFrame,
    *,
    data_dir: Path,
    checkpoint: Path,
    summary: dict[str, Any],
) -> None:
    truth_path = data_dir / "labels" / "manipulated_entry_truth.csv"
    if not truth_path.exists():
        summary["stages"]["manipulated_eval"] = {"error": f"missing {truth_path}"}
        _write_checkpoint(checkpoint, summary)
        return

    t0 = time.perf_counter()
    _log("manipulated eval start")
    truth = pd.read_csv(truth_path, dtype=str, low_memory=False)
    truth_docs = set(truth["document_id"].dropna().astype(str).unique())
    score = pd.to_numeric(df.get("anomaly_score", pd.Series(0.0, index=df.index)), errors="coerce").fillna(0.0)
    score_docs = set(df.loc[score.gt(0), "document_id"].dropna().astype(str).unique())
    rule_docs: set[str] = set()
    for column in ("flagged_rules", "review_rules"):
        if column in df.columns:
            rule_docs |= set(
                df.loc[df[column].fillna("").astype(str).str.len().gt(0), "document_id"]
                .dropna()
                .astype(str)
                .unique()
            )

    scenario_col = "scenario" if "scenario" in truth.columns else "fraud_scenario"
    scenarios = []
    if scenario_col in truth.columns:
        for scenario, group in truth.groupby(scenario_col):
            docs = set(group["document_id"].dropna().astype(str).unique())
            scenarios.append({
                "scenario": str(scenario),
                "total": len(docs),
                "score_gt0": len(docs & score_docs),
                "rule_or_review_hit": len(docs & rule_docs),
                "miss_score_gt0": len(docs - score_docs),
            })

    summary["stages"]["manipulated_eval"] = {
        "elapsed_sec": _elapsed(t0),
        "total_docs": len(truth_docs),
        "score_gt0_docs": len(truth_docs & score_docs),
        "rule_or_review_hit_docs": len(truth_docs & rule_docs),
        "miss_score_gt0_docs": len(truth_docs - score_docs),
        "scenarios": scenarios,
    }
    _write_checkpoint(checkpoint, summary)
    _log(f"manipulated eval done: {summary['stages']['manipulated_eval']}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "journal" / "primary" / "datasynth_v126_candidate",
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=PROJECT_ROOT / "artifacts" / "phase1_v126_profile.json",
    )
    args = parser.parse_args()

    total_start = time.perf_counter()
    summary: dict[str, Any] = {
        "data_dir": str(args.data_dir),
        "started_at": _now(),
        "stages": {},
    }
    _write_checkpoint(args.checkpoint, summary)

    settings = make_phase_settings(get_settings(), phase="phase1")
    audit_rules = get_audit_rules()
    risk_keywords = get_risk_keywords()

    df = _read_data(args.data_dir, args.checkpoint, summary)
    source = args.data_dir / "journal_entries.csv"
    df = apply_datasynth_label_mode(
        df,
        source_path=source,
        mode=getattr(settings, "datasynth_label_mode", "hidden"),
    )
    df = _run_features(
        df,
        settings=settings,
        audit_rules=audit_rules,
        risk_keywords=risk_keywords,
        checkpoint=args.checkpoint,
        summary=summary,
    )
    results = _run_detectors(
        df,
        settings=settings,
        audit_rules=audit_rules,
        checkpoint=args.checkpoint,
        summary=summary,
    )
    df = _aggregate_and_case(
        df,
        results,
        settings=settings,
        data_dir=args.data_dir,
        checkpoint=args.checkpoint,
        summary=summary,
    )
    _evaluate_manipulated(df, data_dir=args.data_dir, checkpoint=args.checkpoint, summary=summary)
    summary["total_elapsed_sec"] = _elapsed(total_start)
    summary["finished_at"] = _now()
    _write_checkpoint(args.checkpoint, summary)
    _log(f"all done: {summary['total_elapsed_sec']}s checkpoint={args.checkpoint}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
