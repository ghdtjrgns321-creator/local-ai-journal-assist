"""Run only L3 rules against a DataSynth candidate.

This runner is isolated from the main pipeline. It loads yearly journals,
generates only feature categories required by L3 rules, executes L3 rules only,
and compares them against labels/rule_truth_L3_*.csv.

L3-12 is evaluated at user-year level in two layers when the candidate sidecar
exists:

* L3-12: scored review truth (`rule_truth_L3_12.csv`)
* L3-12-CAND: raw candidate truth (`work_scope_raw_candidate_population.csv`)
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
from src.detection.anomaly_rules_simple import (
    c01_period_end_large,
    c02_weekend_entry,
    c03_after_hours_entry,
    c04_backdated_entry,
    c06_missing_or_corrupted_description,
    c10_suspense_account,
)
from src.detection.evidence_rules import ev02_cutoff_violation
from src.detection.fraud_rules_access import (
    b10_intercompany_review_signal,
    b13_high_risk_account_use,
    b14_work_scope_excess_review,
)
from src.detection.fraud_rules_feature import b08_manual_override
from src.detection.integrity_layer import IntegrityDetector
from src.feature.engine import feature_categories_for_rules, generate_all_features
from src.ingest.datasynth_labels import SOURCE_PATH_ATTR

YEARS = (2022, 2023, 2024)
L3_RULE_IDS = tuple(f"L3-{idx:02d}" for idx in range(1, 13))
RULE_NAMES = {
    "L3-01": "계정-업무분류 불일치",
    "L3-02": "수기/조정 전표",
    "L3-03": "관계사 전표",
    "L3-04": "기말/기초 전표",
    "L3-05": "주말/휴일 전기",
    "L3-06": "비업무시간 전기",
    "L3-07": "소급/지연 전기",
    "L3-08": "설명 누락/파손",
    "L3-09": "가수금 장기체류",
    "L3-10": "고위험 계정 사용",
    "L3-11": "컷오프 불일치",
    "L3-12": "업무범위 집중 검토(scored)",
    "L3-12-CAND": "업무범위 집중 검토(candidate)",
}


@dataclass(frozen=True)
class RuleMetric:
    rule_id: str
    rule_name: str
    year: int | None
    truth_count: int
    detected_count: int
    tp_count: int
    fp_count: int
    fn_count: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "journal" / "primary" / "datasynth_v104_candidate",
        help="DataSynth candidate directory containing yearly journal_entries CSV files.",
    )
    parser.add_argument("--years", nargs="+", type=int, default=list(YEARS))
    parser.add_argument("--rules", nargs="+", choices=L3_RULE_IDS, default=list(L3_RULE_IDS))
    parser.add_argument("--by-year", action="store_true")
    parser.add_argument("--timings", action="store_true")
    return parser.parse_args()


def load_candidate(data_dir: Path, years: list[int]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for year in years:
        path = data_dir / f"journal_entries_{year}.csv"
        if not path.exists():
            raise FileNotFoundError(path)
        frame = pd.read_csv(
            path,
            parse_dates=["posting_date", "document_date", "approval_date", "delivery_date"],
            low_memory=False,
        )
        frame["_eval_year"] = year
        frames.append(frame)
    df = pd.concat(frames, ignore_index=True)
    df.attrs[SOURCE_PATH_ATTR] = str((data_dir / "journal_entries.csv").resolve())
    return df


def add_l3_features(df: pd.DataFrame) -> None:
    settings = get_settings()
    audit_rules = get_audit_rules()
    categories = feature_categories_for_rules(["L3"])
    result = generate_all_features(
        df,
        settings=settings,
        rules=audit_rules,
        categories=categories,
        include_morpheme_tokens=False,
    )
    df[result.data.columns] = result.data


def run_l3_only(df: pd.DataFrame, rule_ids: set[str]) -> dict[str, pd.Series]:
    settings = get_settings()
    audit_rules = get_audit_rules()
    patterns = audit_rules.get("patterns", {})
    results: dict[str, pd.Series] = {}

    if "L3-01" in rule_ids:
        detector = IntegrityDetector(audit_rules=audit_rules)
        result = detector._l301_misclassified_account(df)
        results["L3-01"] = (
            pd.Series(False, index=df.index) if result is None else result.astype(bool)
        )
    if "L3-02" in rule_ids:
        results["L3-02"] = b08_manual_override(df, audit_rules=audit_rules)
    if "L3-03" in rule_ids:
        results["L3-03"] = b10_intercompany_review_signal(df)
    if "L3-04" in rule_ids:
        results["L3-04"] = c01_period_end_large(
            df,
            quantile=settings.period_end_amount_quantile,
            min_group_size=settings.c01_min_group_size,
            whitelist_patterns=patterns.get("period_end_whitelist", []),
        )
    if "L3-05" in rule_ids:
        results["L3-05"] = c02_weekend_entry(df)
    if "L3-06" in rule_ids:
        results["L3-06"] = c03_after_hours_entry(df)
    if "L3-07" in rule_ids:
        results["L3-07"] = c04_backdated_entry(df, threshold_days=settings.backdated_threshold_days)
    if "L3-08" in rule_ids:
        results["L3-08"] = c06_missing_or_corrupted_description(df)
    if "L3-09" in rule_ids:
        results["L3-09"] = c10_suspense_account(
            df,
            threshold_days=settings.suspense_aging_days,
            min_open_amount=settings.suspense_min_open_amount,
        )
    if "L3-10" in rule_ids:
        results["L3-10"] = b13_high_risk_account_use(df, audit_rules=audit_rules)
    if "L3-11" in rule_ids:
        evidence_cfg = audit_rules.get("evidence", {})
        results["L3-11"] = ev02_cutoff_violation(
            df,
            revenue_cutoff_days=settings.ev_revenue_cutoff_days,
            expense_cutoff_days=settings.ev_expense_cutoff_days,
            period_end_weight=settings.ev_cutoff_period_end_weight,
            max_day_diff=settings.ev_cutoff_max_day_diff,
            use_business_days=settings.ev_cutoff_use_business_days,
            custom_holidays=settings.custom_holidays or None,
            revenue_account_prefixes=(
                evidence_cfg.get("revenue_account_prefixes")
                or patterns.get("revenue_account_prefixes")
            ),
            expense_account_prefixes=evidence_cfg.get("expense_account_prefixes"),
        )
    if "L3-12" in rule_ids:
        results["L3-12"] = b14_work_scope_excess_review(df, audit_rules=audit_rules)
    return results


def truth_path(data_dir: Path, rule_id: str) -> Path:
    return data_dir / "labels" / f"rule_truth_{rule_id.replace('-', '_')}.csv"


def truth_doc_set(data_dir: Path, rule_id: str, years: set[int]) -> set[str]:
    path = truth_path(data_dir, rule_id)
    if not path.exists():
        return set()
    truth = pd.read_csv(
        path,
        usecols=lambda column: column in {"document_id", "expected_hit", "fiscal_year"},
        low_memory=False,
    )
    mask = pd.Series(True, index=truth.index)
    if "expected_hit" in truth.columns:
        mask = truth["expected_hit"].astype(str).str.lower().isin({"true", "1", "yes"})
    if "fiscal_year" in truth.columns:
        mask = mask & pd.to_numeric(truth["fiscal_year"], errors="coerce").isin(years)
    return set(truth.loc[mask, "document_id"].dropna().astype(str).unique())


def truth_user_year_set(data_dir: Path, years: set[int]) -> set[tuple[int, str]]:
    path = truth_path(data_dir, "L3-12")
    if not path.exists():
        return set()
    truth = pd.read_csv(
        path,
        usecols=lambda column: column in {"fiscal_year", "created_by", "expected_hit"},
        low_memory=False,
    )
    return _user_year_set_from_frame(truth, years)


def truth_l312_candidate_user_year_set(data_dir: Path, years: set[int]) -> set[tuple[int, str]]:
    path = data_dir / "labels" / "work_scope_raw_candidate_population.csv"
    if not path.exists():
        return set()
    truth = pd.read_csv(
        path,
        usecols=lambda column: column in {"fiscal_year", "created_by", "expected_hit"},
        low_memory=False,
    )
    return _user_year_set_from_frame(truth, years)


def _user_year_set_from_frame(truth: pd.DataFrame, years: set[int]) -> set[tuple[int, str]]:
    mask = pd.Series(True, index=truth.index)
    if "expected_hit" in truth.columns:
        mask = truth["expected_hit"].astype(str).str.lower().isin({"true", "1", "yes"})
    year = pd.to_numeric(truth["fiscal_year"], errors="coerce")
    mask = mask & year.isin(years)
    user = truth["created_by"].fillna("").astype(str).str.strip().str.lower()
    return set(zip(year.loc[mask].astype(int), user.loc[mask]))


def detected_doc_set(df: pd.DataFrame, result: pd.Series, year: int) -> set[str]:
    mask = pd.Series(result, index=df.index).fillna(False).astype(bool)
    if hasattr(result, "attrs"):
        score_series = result.attrs.get("score_series")
        review_score_series = result.attrs.get("review_score_series")
        if score_series is not None:
            mask |= pd.Series(score_series, index=df.index).fillna(0.0).astype(float).gt(0)
        if review_score_series is not None:
            mask |= (
                pd.Series(review_score_series, index=df.index)
                .fillna(0.0)
                .astype(float)
                .gt(0)
            )
    year_mask = pd.to_numeric(df["fiscal_year"], errors="coerce").eq(year)
    return set(df.loc[mask & year_mask, "document_id"].dropna().astype(str).unique())


def detected_user_year_set(
    df: pd.DataFrame,
    result: pd.Series,
    year: int,
    *,
    mode: str = "scored",
) -> set[tuple[int, str]]:
    score_series = result.attrs.get("score_series") if hasattr(result, "attrs") else None
    review_score_series = (
        result.attrs.get("review_score_series") if hasattr(result, "attrs") else None
    )
    if mode == "candidate":
        mask = pd.Series(result, index=df.index).fillna(False).astype(bool)
    elif mode == "scored":
        mask = pd.Series(False, index=df.index)
        if score_series is not None:
            mask |= pd.Series(score_series, index=df.index).fillna(0.0).astype(float).gt(0)
        if review_score_series is not None:
            mask |= (
                pd.Series(review_score_series, index=df.index)
                .fillna(0.0)
                .astype(float)
                .gt(0)
            )
    else:
        raise ValueError(f"unknown L3-12 detection mode: {mode}")
    year_values = pd.to_numeric(df["fiscal_year"], errors="coerce")
    year_mask = year_values.eq(year)
    users = df["created_by"].fillna("").astype(str).str.strip().str.lower()
    return set(zip(year_values.loc[mask & year_mask].astype(int), users.loc[mask & year_mask]))


def metric(rule_id: str, year: int | None, truth: set, detected: set) -> RuleMetric:
    tp = truth & detected
    fp = detected - truth
    fn = truth - detected
    return RuleMetric(
        rule_id=rule_id,
        rule_name=RULE_NAMES[rule_id],
        year=year,
        truth_count=len(truth),
        detected_count=len(detected),
        tp_count=len(tp),
        fp_count=len(fp),
        fn_count=len(fn),
    )


def evaluate(
    data_dir: Path,
    df: pd.DataFrame,
    results: dict[str, pd.Series],
    years: list[int],
) -> tuple[list[RuleMetric], list[RuleMetric]]:
    by_year: list[RuleMetric] = []
    totals: list[RuleMetric] = []
    for rule_id, result in results.items():
        if rule_id == "L3-12":
            all_scored_truth = truth_user_year_set(data_dir, set(years))
            all_scored_detected: set[tuple[int, str]] = set()
            all_candidate_truth = truth_l312_candidate_user_year_set(data_dir, set(years))
            all_candidate_detected: set[tuple[int, str]] = set()

            for year in years:
                scored_truth = {item for item in all_scored_truth if item[0] == year}
                scored_detected = detected_user_year_set(df, result, year, mode="scored")
                all_scored_detected.update(scored_detected)
                by_year.append(metric(rule_id, year, scored_truth, scored_detected))

                if all_candidate_truth:
                    candidate_truth = {item for item in all_candidate_truth if item[0] == year}
                    candidate_detected = detected_user_year_set(
                        df,
                        result,
                        year,
                        mode="candidate",
                    )
                    all_candidate_detected.update(candidate_detected)
                    by_year.append(
                        metric("L3-12-CAND", year, candidate_truth, candidate_detected)
                    )

            totals.append(metric(rule_id, None, all_scored_truth, all_scored_detected))
            if all_candidate_truth:
                totals.append(
                    metric("L3-12-CAND", None, all_candidate_truth, all_candidate_detected)
                )
            continue

        all_truth = truth_doc_set(data_dir, rule_id, set(years))
        all_detected: set[str] = set()
        for year in years:
            truth = truth_doc_set(data_dir, rule_id, {year})
            detected = detected_doc_set(df, result, year)
            all_detected.update(detected)
            by_year.append(metric(rule_id, year, truth, detected))
        totals.append(metric(rule_id, None, all_truth, all_detected))
    return by_year, totals


def print_metrics(metrics: list[RuleMetric]) -> None:
    print("룰      룰 이름                    정답    탐지    정탐    과탐    미탐")
    print("------  ------------------------  ------  ------  ------  ------  ------")
    for item in metrics:
        print(
            f"{item.rule_id:<6}  {item.rule_name:<24}  "
            f"{item.truth_count:>6}  {item.detected_count:>6}  "
            f"{item.tp_count:>6}  {item.fp_count:>6}  {item.fn_count:>6}"
        )


def main() -> int:
    args = parse_args()
    timings: dict[str, float] = {}

    start = time.perf_counter()
    df = load_candidate(args.data_dir, args.years)
    timings["load"] = time.perf_counter() - start

    start = time.perf_counter()
    add_l3_features(df)
    timings["features"] = time.perf_counter() - start

    start = time.perf_counter()
    results = run_l3_only(df, set(args.rules))
    timings["rules"] = time.perf_counter() - start

    start = time.perf_counter()
    by_year, totals = evaluate(args.data_dir, df, results, args.years)
    timings["evaluation"] = time.perf_counter() - start

    if args.by_year:
        for year in args.years:
            print(f"\n{year}")
            print_metrics([item for item in by_year if item.year == year])
    print("\nTOTAL")
    print_metrics(totals)

    if args.timings:
        print("\nTIMINGS")
        for name, elapsed in timings.items():
            print(f"{name}: {elapsed:.2f}s")
        print(f"total: {sum(timings.values()):.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
