"""Check DataSynth Phase 1 A-axis rule-truth alignment.

This is a guardrail against stale DataSynth truth files. It verifies selected
document-level L3 rule-truth files directly from the current yearly journals
and verifies D01/D02 A-axis truth uses macro review-universe files, not only
confirmed anomaly subsets.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config.settings import get_audit_rules, get_settings  # noqa: E402


YEARS = (2022, 2023, 2024)


def _read_rows(dataset: Path) -> pd.DataFrame:
    frames = []
    for year in YEARS:
        path = dataset / f"journal_entries_{year}.csv"
        if not path.exists():
            raise FileNotFoundError(path)
        frames.append(pd.read_csv(path, low_memory=False))
    return pd.concat(frames, ignore_index=True, sort=False)


def _truth_docs(dataset: Path, rule_id: str) -> set[str]:
    path = dataset / "labels" / f"rule_truth_{rule_id.replace('-', '_')}.csv"
    if not path.exists():
        return set()
    truth = pd.read_csv(path, usecols=lambda c: c == "document_id", low_memory=False)
    if "document_id" not in truth.columns:
        return set()
    return set(truth["document_id"].dropna().astype(str))


def _holiday_set(years: list[int]) -> set[date]:
    try:
        import holidays as hol

        return set(hol.KR(years=years).keys())
    except Exception:
        return {
            date(year, month, day)
            for year in years
            for month, day in (
                (1, 1),
                (3, 1),
                (5, 5),
                (6, 6),
                (8, 15),
                (10, 3),
                (10, 9),
                (12, 25),
            )
        }


def _business_day_diff(posting: pd.Series, delivery: pd.Series) -> pd.Series:
    posting_ts = pd.to_datetime(posting, errors="coerce")
    delivery_ts = pd.to_datetime(delivery, errors="coerce")
    valid = posting_ts.notna() & delivery_ts.notna()
    out = pd.Series(np.nan, index=posting.index, dtype="float64")
    if valid.any():
        p_np = posting_ts[valid].values.astype("datetime64[D]")
        d_np = delivery_ts[valid].values.astype("datetime64[D]")
        out.loc[valid] = np.abs(np.busday_count(d_np, p_np)).astype(float)
    return out


def _expected_l302(rows: pd.DataFrame) -> set[str]:
    source = rows["source"].fillna("").astype(str).str.strip().str.lower()
    return set(rows.loc[source.isin({"manual", "adjustment"}), "document_id"].dropna().astype(str))


def _expected_l304(rows: pd.DataFrame) -> set[str]:
    settings = get_settings()
    window_days = int(getattr(settings, "period_end_window_days", 5) or 5)
    parsed = pd.to_datetime(rows["posting_date"], errors="coerce")
    days_to_month_end = parsed.dt.days_in_month - parsed.dt.day
    mask = parsed.notna() & (parsed.dt.day.le(window_days) | days_to_month_end.le(window_days))
    return set(rows.loc[mask, "document_id"].dropna().astype(str))


def _expected_l305(rows: pd.DataFrame) -> set[str]:
    docs = rows.drop_duplicates("document_id")[["document_id", "posting_date"]].copy()
    parsed = pd.to_datetime(docs["posting_date"], errors="coerce")
    holidays = _holiday_set([int(year) for year in YEARS])
    mask = parsed.notna() & (parsed.dt.dayofweek.ge(5) | parsed.dt.date.isin(holidays))
    return set(docs.loc[mask, "document_id"].dropna().astype(str))


def _expected_l311(rows: pd.DataFrame) -> set[str]:
    settings = get_settings()
    audit_rules = get_audit_rules()
    evidence_cfg = audit_rules.get("evidence", {})
    patterns = audit_rules.get("patterns", {})
    revenue_prefixes = tuple(evidence_cfg.get("revenue_account_prefixes") or patterns.get("revenue_account_prefixes") or ["4"])
    expense_prefixes = tuple(evidence_cfg.get("expense_account_prefixes") or ["5"])
    gl = rows["gl_account"].fillna("").astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
    diff = _business_day_diff(rows["posting_date"], rows["delivery_date"])
    mask = (
        (gl.str.startswith(revenue_prefixes) & diff.gt(settings.ev_revenue_cutoff_days))
        | (gl.str.startswith(expense_prefixes) & diff.gt(settings.ev_expense_cutoff_days))
    )
    return set(rows.loc[mask, "document_id"].dropna().astype(str))


def _group_keys(path: Path) -> set[tuple[str, str, str]]:
    df = pd.read_csv(path, low_memory=False)
    if not {"fiscal_year", "company_code", "gl_account"}.issubset(df.columns):
        return set()
    return set(
        zip(
            pd.to_numeric(df["fiscal_year"], errors="coerce").astype("Int64").astype(str),
            df["company_code"].astype(str),
            df["gl_account"].astype(str),
        )
    )


def check(dataset: Path) -> dict[str, Any]:
    rows = _read_rows(dataset)
    expected_builders = {
        "L3-02": _expected_l302,
        "L3-04": _expected_l304,
        "L3-05": _expected_l305,
        "L3-11": _expected_l311,
    }
    l3: dict[str, Any] = {}
    failures: list[str] = []
    for rule_id, builder in expected_builders.items():
        expected = builder(rows)
        truth = _truth_docs(dataset, rule_id)
        extra = truth - expected
        missing = expected - truth
        l3[rule_id] = {
            "expected_docs": int(len(expected)),
            "truth_docs": int(len(truth)),
            "truth_minus_expected": int(len(extra)),
            "expected_minus_truth": int(len(missing)),
            "sample_truth_minus_expected": sorted(extra)[:10],
            "sample_expected_minus_truth": sorted(missing)[:10],
        }
        if extra or missing:
            failures.append(f"{rule_id}: truth/expected diff is not zero")

    d_checks: dict[str, Any] = {}
    macro_pairs = {
        "D01": ("rule_truth_D01.csv", "account_activity_variance_review_population.csv", "account_activity_variance_truth.csv"),
        "D02": ("rule_truth_D02.csv", "monthly_pattern_shift_review_population.csv", "monthly_pattern_shift_truth.csv"),
    }
    for rule_id, (truth_name, review_name, confirmed_name) in macro_pairs.items():
        labels = dataset / "labels"
        truth_keys = _group_keys(labels / truth_name)
        review_keys = _group_keys(labels / review_name)
        confirmed_keys = _group_keys(labels / confirmed_name)
        d_checks[rule_id] = {
            "a_axis_truth_groups": int(len(truth_keys)),
            "review_universe_groups": int(len(review_keys)),
            "confirmed_truth_groups": int(len(confirmed_keys)),
            "truth_vs_review_diff": int(len(truth_keys ^ review_keys)),
            "confirmed_not_in_truth": int(len(confirmed_keys - truth_keys)),
            "a_axis_truth_policy": "rule_truth macro review universe, not confirmed subset only",
        }
        if truth_keys != review_keys:
            failures.append(f"{rule_id}: rule_truth does not match review universe")
        if confirmed_keys - truth_keys:
            failures.append(f"{rule_id}: confirmed subset is missing from A-axis truth")

    return {
        "dataset": str(dataset),
        "l3_document_truth": l3,
        "d_macro_truth": d_checks,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    args = parser.parse_args()
    result = check(args.dataset)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
