"""Run only L2 rules against a DataSynth candidate.

This runner is intentionally isolated from the main pipeline. It does not call
FraudLayer or AnomalyDetector because those layers execute non-L2 rules too.

Run:
    .venv\Scripts\python.exe tools/scripts/eval_datasynth_l2_only.py ^
        --data-dir data/journal/primary/datasynth_v77_candidate
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import get_audit_rules, get_settings
from src.detection.anomaly_rules_reversal import c11_reversal_entry
from src.detection.fraud_rules_feature import b02_near_threshold
from src.detection.fraud_rules_groupby import (
    b04_duplicate_payment,
    b05_duplicate_entry,
    b11_expense_capitalization,
)
from src.feature.amount_features import _compute_base_amount, add_is_near_threshold
from src.ingest.datasynth_labels import SOURCE_PATH_ATTR
from src.metrics.ground_truth_evaluator import _label_doc_set_for_rule

YEARS = (2022, 2023, 2024)
L2_RULE_IDS = ("L2-01", "L2-02", "L2-03", "L2-04", "L2-05")
RULE_NAMES = {
    "L2-01": "승인한도 근접",
    "L2-02": "중복 지급",
    "L2-03": "중복 전표",
    "L2-04": "비용 자본화",
    "L2-05": "역분개 패턴",
}


@dataclass(frozen=True)
class RuleMetric:
    rule_id: str
    rule_name: str
    truth_docs: int
    detected_docs: int
    tp_docs: int
    fp_docs: int
    fn_docs: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "journal" / "primary" / "datasynth_v77_candidate",
        help="DataSynth candidate directory containing yearly journal_entries CSV files.",
    )
    parser.add_argument(
        "--years",
        nargs="+",
        type=int,
        default=list(YEARS),
        help="Fiscal years to evaluate.",
    )
    parser.add_argument(
        "--rules",
        nargs="+",
        choices=L2_RULE_IDS,
        default=list(L2_RULE_IDS),
        help="L2 rules to run.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional report path. If omitted, nothing is written.",
    )
    parser.add_argument(
        "--timings",
        action="store_true",
        help="Print component timings.",
    )
    return parser.parse_args()


def load_candidate(data_dir: Path, years: list[int]) -> tuple[pd.DataFrame, pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    for year in years:
        path = data_dir / f"journal_entries_{year}.csv"
        if not path.exists():
            raise FileNotFoundError(path)
        year_df = pd.read_csv(
            path,
            parse_dates=["posting_date", "document_date"],
            dtype={"debit_amount": float, "credit_amount": float},
            low_memory=False,
        )
        year_df["_eval_year"] = year
        frames.append(year_df)

    df = pd.concat(frames, ignore_index=True)
    # Keep the ingest contract without copying the 1.1M-row dataframe.
    df.attrs[SOURCE_PATH_ATTR] = str((data_dir / "journal_entries.csv").resolve())

    labels_path = data_dir / "labels" / "anomaly_labels.csv"
    if not labels_path.exists():
        raise FileNotFoundError(labels_path)
    labels = pd.read_csv(labels_path, low_memory=False)
    labels["document_id"] = labels["document_id"].astype(str)
    return df, labels


def run_l2_only(df: pd.DataFrame, rule_ids: set[str]) -> tuple[dict[str, pd.Series], dict[str, float]]:
    settings = get_settings()
    audit_rules = get_audit_rules()
    results: dict[str, pd.Series] = {}
    timings: dict[str, float] = {}

    if "L2-01" in rule_ids:
        start = time.perf_counter()
        base = _compute_base_amount(df)
        add_is_near_threshold(
            df,
            base,
            settings.approval_thresholds,
            settings.near_threshold_ratio,
        )
        timings["L2-01 feature"] = time.perf_counter() - start

        start = time.perf_counter()
        results["L2-01"] = b02_near_threshold(df)
        timings["L2-01 rule"] = time.perf_counter() - start

    if "L2-02" in rule_ids:
        start = time.perf_counter()
        results["L2-02"] = b04_duplicate_payment(
            df,
            window_days=settings.duplicate_payment_window_days,
        )
        timings["L2-02 rule"] = time.perf_counter() - start

    if "L2-03" in rule_ids:
        start = time.perf_counter()
        results["L2-03"] = b05_duplicate_entry(
            df,
            amount_tolerance=settings.duplicate_amount_tolerance,
            fuzzy_threshold=settings.duplicate_fuzzy_threshold,
            window_days=settings.duplicate_time_window_days,
            split_window_days=settings.duplicate_split_window_days,
            max_group_size=settings.duplicate_max_group_size,
        )
        timings["L2-03 rule"] = time.perf_counter() - start

    if "L2-04" in rule_ids:
        start = time.perf_counter()
        flagged = b11_expense_capitalization(
            df,
            audit_rules=audit_rules,
            amount_tolerance=settings.expense_capitalization_amount_tolerance,
            min_amount=settings.expense_capitalization_min_amount,
            review_threshold=settings.expense_capitalization_review_threshold,
            immediate_threshold=settings.expense_capitalization_immediate_threshold,
        )
        score_series = flagged.attrs.get("score_series")
        if score_series is not None:
            flagged = pd.Series(score_series, index=df.index).fillna(0.0).gt(0)
        results["L2-04"] = flagged
        timings["L2-04 rule"] = time.perf_counter() - start

    if "L2-05" in rule_ids:
        start = time.perf_counter()
        flagged = c11_reversal_entry(
            df,
            match_window_days=settings.reversal_match_window_days,
            rolling_window_days=settings.reversal_rolling_window_days,
            zero_threshold=settings.reversal_zero_threshold,
            score_threshold=settings.reversal_score_threshold,
        )
        score_series = flagged.attrs.get("score_series")
        if score_series is not None:
            flagged = pd.Series(score_series, index=df.index).fillna(0.0).gt(0)
        results["L2-05"] = flagged
        timings["L2-05 rule"] = time.perf_counter() - start

    return results, timings


def metric_for_rule(
    df: pd.DataFrame,
    labels: pd.DataFrame,
    rule_id: str,
    flagged: pd.Series,
) -> RuleMetric:
    flagged_docs = set(df.loc[flagged, "document_id"].dropna().astype(str).unique())
    truth_docs = set(str(value) for value in _label_doc_set_for_rule(rule_id, df, labels))
    tp_docs = flagged_docs & truth_docs
    fp_docs = flagged_docs - truth_docs
    fn_docs = truth_docs - flagged_docs
    return RuleMetric(
        rule_id=rule_id,
        rule_name=RULE_NAMES[rule_id],
        truth_docs=len(truth_docs),
        detected_docs=len(flagged_docs),
        tp_docs=len(tp_docs),
        fp_docs=len(fp_docs),
        fn_docs=len(fn_docs),
    )


def evaluate_by_year(
    df: pd.DataFrame,
    labels: pd.DataFrame,
    results: dict[str, pd.Series],
    years: list[int],
) -> dict[str, list[RuleMetric]]:
    report: dict[str, list[RuleMetric]] = {}
    for year in years:
        year_mask = df["_eval_year"].eq(year)
        year_df = df.loc[year_mask]
        year_docs = set(year_df["document_id"].dropna().astype(str))
        year_labels = labels[labels["document_id"].isin(year_docs)]
        report[str(year)] = [
            metric_for_rule(
                year_df,
                year_labels,
                rule_id,
                flagged.reindex(df.index, fill_value=False) & year_mask,
            )
            for rule_id, flagged in results.items()
        ]
    report["전체"] = [
        metric_for_rule(df, labels, rule_id, flagged)
        for rule_id, flagged in results.items()
    ]
    return report


def render_section(title: str, metrics: list[RuleMetric]) -> str:
    lines = [
        f"- {title}",
        "룰      룰 이름            정답   탐지   정탐   과탐   미탐",
        "-----  ----------------  -----  -----  -----  -----  -----",
    ]
    for item in metrics:
        lines.append(
            f"{item.rule_id:<6} {item.rule_name:<16}"
            f"{item.truth_docs:>6}"
            f"{item.detected_docs:>7}"
            f"{item.tp_docs:>7}"
            f"{item.fp_docs:>7}"
            f"{item.fn_docs:>7}"
        )
    return "\n".join(lines)


def render_report(
    data_dir: Path,
    df: pd.DataFrame,
    labels: pd.DataFrame,
    metrics: dict[str, list[RuleMetric]],
    timings: dict[str, float],
    *,
    include_timings: bool,
) -> str:
    sections = [
        f"DataSynth L2-only evaluation: {data_dir}",
        f"rows={len(df):,} docs={df['document_id'].nunique():,} "
        f"labels={len(labels):,} label_docs={labels['document_id'].nunique():,}",
        "",
    ]
    sections.extend(render_section(title, items) for title, items in metrics.items())

    if include_timings:
        sections.append("- timings")
        sections.extend(f"{name}: {elapsed:.2f}s" for name, elapsed in timings.items())
    return "\n\n".join(sections)


def main() -> None:
    args = parse_args()
    data_dir = args.data_dir.resolve()
    total_start = time.perf_counter()

    load_start = time.perf_counter()
    df, labels = load_candidate(data_dir, args.years)
    timings = {"load": time.perf_counter() - load_start}

    results, run_timings = run_l2_only(df, set(args.rules))
    timings.update(run_timings)
    timings["total"] = time.perf_counter() - total_start

    metrics = evaluate_by_year(df, labels, results, args.years)
    report = render_report(
        data_dir,
        df,
        labels,
        metrics,
        timings,
        include_timings=args.timings,
    )
    print(report)

    if args.output is not None:
        output_path = args.output.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
