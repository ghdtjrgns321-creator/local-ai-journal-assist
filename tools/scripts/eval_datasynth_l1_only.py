"""Run only L1 rules against a DataSynth candidate.

This runner is intentionally isolated from the main pipeline. It loads only the
columns needed by L1 rules, computes only the amount/period features needed by
L1-04, L1-07, and L1-08, and reports document-level truth/detection counts.

Run:
    .venv\\Scripts\\python.exe tools/scripts/eval_datasynth_l1_only.py ^
        --data-dir data/journal/primary/datasynth_v79_candidate
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
from src.detection.anomaly_rules_simple import c05_fiscal_period_mismatch
from src.detection.fraud_rules_access import (
    b07_segregation_of_duties,
    build_access_rule_cache,
)
from src.detection.fraud_rules_feature import b03_exceeds_threshold
from src.detection.integrity_layer import IntegrityDetector
from src.feature.amount_features import _compute_base_amount, add_exceeds_threshold
from src.feature.time_features import add_fiscal_period_mismatch
from src.ingest.datasynth_labels import SOURCE_PATH_ATTR

YEARS = (2022, 2023, 2024)
L1_RULE_IDS = tuple(f"L1-{idx:02d}" for idx in range(1, 10))
RULE_NAMES = {
    "L1-01": "차대변 불일치",
    "L1-02": "필수필드 누락",
    "L1-03": "무효 계정",
    "L1-04": "승인한도 초과",
    "L1-05": "자기 승인",
    "L1-06": "직무분리 위반",
    "L1-07": "승인 생략",
    "L1-08": "회계기간 불일치",
    "L1-09": "승인일 누락",
}
L1_USECOLS = [
    "document_id",
    "company_code",
    "fiscal_year",
    "fiscal_period",
    "posting_date",
    "document_date",
    "document_type",
    "created_by",
    "user_persona",
    "source",
    "business_process",
    "approved_by",
    "approval_date",
    "sod_violation",
    "sod_conflict_type",
    "document_number",
    "gl_account",
    "debit_amount",
    "credit_amount",
]


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
        default=PROJECT_ROOT / "data" / "journal" / "primary" / "datasynth_v79_candidate",
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
        choices=L1_RULE_IDS,
        default=list(L1_RULE_IDS),
        help="L1 rules to run.",
    )
    parser.add_argument(
        "--timings",
        action="store_true",
        help="Print component timings.",
    )
    parser.add_argument(
        "--by-year",
        action="store_true",
        help="Print a separate metrics table for each requested fiscal year.",
    )
    return parser.parse_args()


def load_candidate(data_dir: Path, years: list[int]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for year in years:
        path = data_dir / f"journal_entries_{year}.csv"
        if not path.exists():
            raise FileNotFoundError(path)
        year_df = pd.read_csv(
            path,
            usecols=lambda column: column in L1_USECOLS,
            parse_dates=["posting_date", "document_date", "approval_date"],
            low_memory=False,
        )
        year_df["_eval_year"] = year
        frames.append(year_df)
    out = pd.concat(frames, ignore_index=True)
    out.attrs[SOURCE_PATH_ATTR] = str((data_dir / "journal_entries.csv").resolve())
    return out


def add_l1_features(df: pd.DataFrame, rule_ids: set[str]) -> None:
    settings = get_settings()
    audit_rules = get_audit_rules()
    if rule_ids & {"L1-04", "L1-07"}:
        add_exceeds_threshold(df, _compute_base_amount(df), settings.approval_thresholds)
    if "L1-08" in rule_ids:
        policy = audit_rules.get("patterns", {}).get("fiscal_period_mismatch_policy", {})
        fiscal_year_start = int(policy.get("fiscal_year_start", 1))
        add_fiscal_period_mismatch(df, fiscal_year_start=fiscal_year_start)


def load_truth_docs(data_dir: Path, rule_id: str, years: set[int] | None = None) -> set[str]:
    path = data_dir / "labels" / f"rule_truth_{rule_id.replace('-', '_')}.csv"
    if not path.exists():
        return set()
    truth = pd.read_csv(
        path,
        usecols=lambda column: column in {"document_id", "expected_hit", "fiscal_year"},
        low_memory=False,
    )
    expected = truth["expected_hit"].astype(str).str.lower().isin({"true", "1", "yes"})
    if years is not None and "fiscal_year" in truth.columns:
        truth_year = pd.to_numeric(truth["fiscal_year"], errors="coerce")
        expected = expected & truth_year.isin(years)
    return set(truth.loc[expected, "document_id"].dropna().astype(str).unique())


def docs_from_mask(df: pd.DataFrame, mask: pd.Series) -> set[str]:
    aligned = pd.Series(mask, index=df.index).fillna(False).astype(bool)
    return set(df.loc[aligned, "document_id"].dropna().astype(str).unique())


def docs_from_rule_result(df: pd.DataFrame, result: pd.Series) -> set[str]:
    mask = pd.Series(result, index=df.index).fillna(False).astype(bool)
    score_series = result.attrs.get("score_series") if hasattr(result, "attrs") else None
    if score_series is not None:
        mask = mask | pd.Series(score_series, index=df.index).fillna(0.0).astype(float).gt(0)
    review_score_series = (
        result.attrs.get("review_score_series") if hasattr(result, "attrs") else None
    )
    if review_score_series is not None:
        mask = mask | pd.Series(review_score_series, index=df.index).fillna(0.0).astype(float).gt(0)
    annotations = result.attrs.get("row_annotations") if hasattr(result, "attrs") else None
    if annotations:
        annotation_mask = pd.Series(False, index=df.index)
        valid_indices = [idx for idx in annotations if idx in annotation_mask.index]
        if valid_indices:
            annotation_mask.loc[valid_indices] = True
        mask = mask | annotation_mask
    return docs_from_mask(df, mask)


def normalized_text(df: pd.DataFrame, column: str) -> pd.Series:
    values = df[column].where(df[column].notna(), "").astype(str).str.strip().str.lower()
    return values.mask(values.isin({"nan", "nat", "none", "<na>"}), "")


def l105_candidate_mask(df: pd.DataFrame) -> pd.Series:
    if "created_by" not in df.columns or "approved_by" not in df.columns:
        return pd.Series(False, index=df.index)
    creator = normalized_text(df, "created_by")
    approver = normalized_text(df, "approved_by")
    return creator.ne("") & approver.ne("") & creator.eq(approver)


def l107_candidate_mask(df: pd.DataFrame) -> pd.Series:
    if "approved_by" not in df.columns:
        return pd.Series(False, index=df.index)
    return normalized_text(df, "approved_by").eq("")


def l109_candidate_mask(df: pd.DataFrame) -> pd.Series:
    if "approval_date" not in df.columns:
        return pd.Series(False, index=df.index)
    return normalized_text(df, "approval_date").eq("")


def run_l1_only(df: pd.DataFrame, rule_ids: set[str]) -> dict[str, set[str]]:
    audit_rules = get_audit_rules()
    results: dict[str, set[str]] = {}

    if rule_ids & {"L1-01", "L1-02", "L1-03"}:
        integrity = IntegrityDetector().detect(df)
        for rule_id in ("L1-01", "L1-02", "L1-03"):
            if rule_id in rule_ids and rule_id in integrity.details.columns:
                results[rule_id] = docs_from_mask(df, integrity.details[rule_id].gt(0))
            elif rule_id in rule_ids:
                results[rule_id] = set()

    if "L1-04" in rule_ids:
        results["L1-04"] = docs_from_rule_result(
            df,
            b03_exceeds_threshold(df, audit_rules=audit_rules),
        )

    access_cache = build_access_rule_cache(df)
    if "L1-05" in rule_ids:
        results["L1-05"] = docs_from_mask(df, l105_candidate_mask(df))
    if "L1-06" in rule_ids:
        results["L1-06"] = docs_from_rule_result(
            df,
            b07_segregation_of_duties(df, audit_rules=audit_rules, cache=access_cache),
        )
    if "L1-07" in rule_ids:
        results["L1-07"] = docs_from_mask(df, l107_candidate_mask(df))
    if "L1-08" in rule_ids:
        policy = audit_rules.get("patterns", {}).get("fiscal_period_mismatch_policy", {})
        results["L1-08"] = docs_from_rule_result(
            df,
            c05_fiscal_period_mismatch(df, policy=policy),
        )
    if "L1-09" in rule_ids:
        results["L1-09"] = docs_from_mask(df, l109_candidate_mask(df))
    return results


def build_metrics(
    data_dir: Path,
    detected: dict[str, set[str]],
    rule_ids: list[str],
    years: set[int] | None = None,
) -> list[RuleMetric]:
    metrics: list[RuleMetric] = []
    for rule_id in rule_ids:
        truth_docs = load_truth_docs(data_dir, rule_id, years=years)
        detected_docs = detected.get(rule_id, set())
        tp_docs = truth_docs & detected_docs
        fp_docs = detected_docs - truth_docs
        fn_docs = truth_docs - detected_docs
        metrics.append(
            RuleMetric(
                rule_id=rule_id,
                rule_name=RULE_NAMES[rule_id],
                truth_docs=len(truth_docs),
                detected_docs=len(detected_docs),
                tp_docs=len(tp_docs),
                fp_docs=len(fp_docs),
                fn_docs=len(fn_docs),
            )
        )
    return metrics


def render_metrics(metrics: list[RuleMetric]) -> str:
    lines = [
        f"{'룰':<7} {'룰 이름':<16} {'정답':>8} {'탐지':>8} {'정탐':>8} {'과탐':>8} {'미탐':>8}",
    ]
    for item in metrics:
        lines.append(
            f"{item.rule_id:<7} {item.rule_name:<16}"
            f"{item.truth_docs:>8}"
            f"{item.detected_docs:>8}"
            f"{item.tp_docs:>8}"
            f"{item.fp_docs:>8}"
            f"{item.fn_docs:>8}"
        )
    return "\n".join(lines)


def filter_detected_by_year(
    df: pd.DataFrame,
    detected: dict[str, set[str]],
    year: int,
) -> dict[str, set[str]]:
    year_docs = set(df.loc[df["_eval_year"].eq(year), "document_id"].dropna().astype(str))
    return {rule_id: docs & year_docs for rule_id, docs in detected.items()}


def main() -> None:
    args = parse_args()
    timings: dict[str, float] = {}

    start = time.perf_counter()
    df = load_candidate(args.data_dir, args.years)
    timings["load"] = time.perf_counter() - start

    rule_ids = set(args.rules)
    start = time.perf_counter()
    add_l1_features(df, rule_ids)
    timings["features"] = time.perf_counter() - start

    start = time.perf_counter()
    detected = run_l1_only(df, rule_ids)
    timings["rules"] = time.perf_counter() - start

    start = time.perf_counter()
    metrics = build_metrics(args.data_dir, detected, list(args.rules), years=set(args.years))
    timings["truth"] = time.perf_counter() - start

    if args.by_year:
        sections: list[str] = []
        for year in args.years:
            year_detected = filter_detected_by_year(df, detected, year)
            year_metrics = build_metrics(
                args.data_dir,
                year_detected,
                list(args.rules),
                years={year},
            )
            sections.append(f"[{year}]\n{render_metrics(year_metrics)}")
        print("\n\n".join(sections))
    else:
        print(render_metrics(metrics))
    if args.timings:
        print()
        for name, elapsed in timings.items():
            print(f"{name:<10} {elapsed:>8.3f}s")
        print(f"{'total':<10} {sum(timings.values()):>8.3f}s")


if __name__ == "__main__":
    main()
