"""Audit DataSynth manipulation-v3 fitting guards.

The hard checks here are raw-data accounting-substance checks and background
stability checks. Phase1 topic-entry rates are intentionally excluded.
"""

# ruff: noqa: E501,I001

from __future__ import annotations

import json
import argparse
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "data" / "journal" / "primary" / "datasynth_contract_v2"
V2 = ROOT / "data" / "journal" / "primary" / "datasynth_manipulation_v2"
V3 = ROOT / "data" / "journal" / "primary" / "datasynth_manipulation_v3"
OUT_MD = ROOT / "artifacts" / "manipulation_v3_mutation_recovery.md"
OUT_JSON = ROOT / "artifacts" / "manipulation_v3_mutation_recovery.json"
DEFAULT_V2_TOPIC = ROOT / "artifacts" / "phase1_manipulation_v2_after_circular_period_end_topic_analysis.json"
DEFAULT_V3_TOPIC = ROOT / "artifacts" / "manipulation_v3_topic_analysis.json"


def load_dataset(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    journal = pd.read_csv(path / "journal_entries.csv", dtype=str, low_memory=False)
    truth = pd.read_csv(path / "labels" / "manipulated_entry_truth.csv", dtype=str, low_memory=False)
    return journal, truth


def amounts(df: pd.DataFrame) -> pd.Series:
    cols = []
    for column in ("debit_amount", "credit_amount", "local_amount"):
        cols.append(pd.to_numeric(df[column], errors="coerce").fillna(0.0).abs())
    return pd.concat(cols, axis=1).max(axis=1)


def revenue_p95_by_company(contract: pd.DataFrame) -> dict[str, float]:
    work = contract.copy()
    work["_amount"] = amounts(work)
    work["_is_revenue"] = work["gl_account"].fillna("").astype(str).str.startswith("4")
    revenue = work.loc[work["_is_revenue"]]
    return {
        str(company): float(group["_amount"].quantile(0.95))
        for company, group in revenue.groupby("company_code")
    }


def doc_subset(journal: pd.DataFrame, truth: pd.DataFrame, scenario: str) -> pd.DataFrame:
    docs = set(truth.loc[truth["manipulation_scenario"].eq(scenario), "document_id"].astype(str))
    return journal.loc[journal["document_id"].astype(str).isin(docs)].copy()


def doc_level_flags(rows: pd.DataFrame) -> pd.DataFrame:
    work = rows.copy()
    work["_posting"] = pd.to_datetime(work["posting_date"], errors="coerce")
    work["_amount"] = amounts(work)
    work["_is_revenue"] = work["gl_account"].fillna("").astype(str).str.startswith("4")
    work["_offhour"] = work["_posting"].dt.hour.ge(22) | work["_posting"].dt.hour.le(5)
    work["_weekend"] = work["_posting"].dt.weekday.ge(5)
    work["_date"] = work["_posting"].dt.date.astype(str)
    work["_doc_prefix"] = work["document_number"].fillna("").astype(str).str.extract(r"^([A-Z]+[0-9]{7})", expand=False).fillna("")
    grouped = work.groupby("document_id", as_index=False).agg(
        company_code=("company_code", "first"),
        has_revenue_gl=("_is_revenue", "any"),
        max_amount=("_amount", "max"),
        offhour=("_offhour", "any"),
        weekend=("_weekend", "any"),
        source=("source", "first"),
        created_by=("created_by", "first"),
        posting_date=("_date", "first"),
        doc_prefix=("_doc_prefix", "first"),
    )
    grouped["source_manual"] = grouped["source"].fillna("").astype(str).str.lower().isin({"manual", "adjustment"})
    batch_key = grouped["created_by"].fillna("").astype(str) + "|" + grouped["posting_date"].fillna("").astype(str) + "|" + grouped["doc_prefix"].fillna("").astype(str)
    batch_counts = batch_key.map(batch_key.value_counts())
    grouped["batch_pattern"] = grouped["doc_prefix"].ne("") & batch_counts.ge(2)
    return grouped


def operational_noise_floor(rows: pd.DataFrame) -> dict[str, float | int]:
    posting = pd.to_datetime(rows["posting_date"], errors="coerce")
    approved_by = rows["approved_by"].fillna("").astype(str).str.strip()
    source = rows["source"].fillna("").astype(str).str.lower()
    total = max(len(rows), 1)
    return {
        "rows": int(len(rows)),
        "approved_by_null_pct": round(float(approved_by.eq("").sum()) / total, 6),
        "manual_entry_pct": round(float(source.isin({"manual", "adjustment"}).sum()) / total, 6),
        "weekend_posting_pct": round(float(posting.dt.weekday.ge(5).fillna(False).sum()) / total, 6),
    }


def pct(numerator: int, denominator: int) -> float:
    return 0.0 if denominator == 0 else round(numerator / denominator, 6)


def load_topic_regression(v2_topic_path: Path, v3_topic_path: Path) -> dict[str, Any]:
    if not v2_topic_path.exists() or not v3_topic_path.exists():
        return {
            "available": False,
            "reason": "v2/v3 topic analysis artifact missing",
        }
    v2_topic = json.loads(v2_topic_path.read_text(encoding="utf-8"))
    v3_topic = json.loads(v3_topic_path.read_text(encoding="utf-8"))
    v2_by_scenario = {row["scenario"]: row for row in v2_topic.get("scenario_metrics", [])}
    v3_by_scenario = {row["scenario"]: row for row in v3_topic.get("scenario_metrics", [])}
    protected = [
        "approval_sod_bypass",
        "circular_related_party_transaction",
        "embezzlement_concealment",
        "period_end_adjustment_manipulation",
    ]
    rows = []
    regression_pass = True
    for scenario in protected:
        before = v2_by_scenario.get(scenario, {})
        after = v3_by_scenario.get(scenario, {})
        before_docs = int(before.get("expected_topic_docs", 0))
        after_docs = int(after.get("expected_topic_docs", 0))
        threshold = before_docs * 0.95
        ok = after_docs >= threshold
        regression_pass = regression_pass and ok
        rows.append(
            {
                "scenario": scenario,
                "v2_expected_topic_docs": before_docs,
                "v3_expected_topic_docs": after_docs,
                "threshold_95pct": threshold,
                "pass": ok,
            }
        )
    measure_only = {
        scenario: {
            "truth_docs": int(row.get("truth_docs", 0)),
            "expected_topic_docs": int(row.get("expected_topic_docs", 0)),
            "high_truth": int(row.get("high_truth", 0)),
        }
        for scenario, row in v3_by_scenario.items()
    }
    return {
        "available": True,
        "protected_scenario_regression_pass": regression_pass,
        "protected_scenarios": rows,
        "measure_only_v3_expected_topic": measure_only,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=CONTRACT)
    parser.add_argument("--v2", type=Path, default=V2)
    parser.add_argument("--v3", type=Path, default=V3)
    parser.add_argument("--out-md", type=Path, default=OUT_MD)
    parser.add_argument("--out-json", type=Path, default=OUT_JSON)
    parser.add_argument("--v2-topic", type=Path, default=DEFAULT_V2_TOPIC)
    parser.add_argument("--v3-topic", type=Path, default=DEFAULT_V3_TOPIC)
    args = parser.parse_args()

    contract = pd.read_csv(args.contract / "journal_entries.csv", dtype=str, low_memory=False)
    v2_rows, v2_truth = load_dataset(args.v2)
    v3_rows, v3_truth = load_dataset(args.v3)
    refs = revenue_p95_by_company(contract)

    unusual = doc_level_flags(doc_subset(v3_rows, v3_truth, "unusual_timing_manipulation"))
    fictitious = doc_level_flags(doc_subset(v3_rows, v3_truth, "fictitious_entry"))
    fictitious["company_revenue_p95"] = fictitious["company_code"].astype(str).map(refs).fillna(0.0)
    fictitious["amount_to_p95_ratio"] = fictitious["max_amount"] / fictitious["company_revenue_p95"].where(
        fictitious["company_revenue_p95"].gt(0), 1.0
    )

    truth_same = (
        set(v2_truth["document_id"].astype(str)) == set(v3_truth["document_id"].astype(str))
        and v2_truth["manipulation_scenario"].value_counts().sort_index().to_dict()
        == v3_truth["manipulation_scenario"].value_counts().sort_index().to_dict()
    )

    v2_noise = operational_noise_floor(v2_rows)
    v3_noise = operational_noise_floor(v3_rows)
    noise_delta = {
        key: round(float(v3_noise[key]) - float(v2_noise[key]), 6)
        for key in ("approved_by_null_pct", "manual_entry_pct", "weekend_posting_pct")
    }

    guard_1 = {
        "unusual_offhour_doc_ratio": pct(int(unusual["offhour"].sum()), len(unusual)),
        "unusual_weekend_doc_ratio": pct(int(unusual["weekend"].sum()), len(unusual)),
        "unusual_manual_source_doc_ratio": pct(int(unusual["source_manual"].sum()), len(unusual)),
        "fictitious_revenue_gl_doc_ratio": pct(int(fictitious["has_revenue_gl"].sum()), len(fictitious)),
        "fictitious_amount_ge_1_5x_company_revenue_p95_doc_ratio": pct(
            int(fictitious["amount_to_p95_ratio"].ge(1.5).sum()), len(fictitious)
        ),
        "fictitious_batch_doc_ratio": pct(int(fictitious["batch_pattern"].sum()), len(fictitious)),
    }
    guard_1_pass = (
        guard_1["unusual_offhour_doc_ratio"] >= 0.80
        and guard_1["unusual_weekend_doc_ratio"] >= 0.60
        and guard_1["fictitious_revenue_gl_doc_ratio"] == 1.0
        and guard_1["fictitious_amount_ge_1_5x_company_revenue_p95_doc_ratio"] == 1.0
        and guard_1["fictitious_batch_doc_ratio"] >= 0.33
    )
    guard_2 = {
        "truth_doc_mapping_identical_to_v2": truth_same,
        "noise_floor_v2": v2_noise,
        "noise_floor_v3": v3_noise,
        "noise_floor_delta": noise_delta,
        "noise_floor_delta_within_10pct_points": all(abs(value) <= 0.10 for value in noise_delta.values()),
    }
    guard_3 = load_topic_regression(args.v2_topic, args.v3_topic)

    result: dict[str, Any] = {
        "dataset": str(args.v3.relative_to(ROOT)) if args.v3.is_relative_to(ROOT) else str(args.v3),
        "guard_1_accounting_substance_pass": guard_1_pass,
        "guard_1": guard_1,
        "guard_2_background_fitting_pass": bool(truth_same and guard_2["noise_floor_delta_within_10pct_points"]),
        "guard_2": guard_2,
        "guard_3_other_scenario_regression_pass": guard_3.get(
            "protected_scenario_regression_pass"
        )
        if guard_3.get("available")
        else None,
        "guard_3": guard_3,
        "measure_only": {
            "phase1_topic_entry_rates": "not computed by this raw-data guard; run profile_phase1_v126.py separately",
            "top10_top500_truth_capture": "measure-only, not a generation gate",
        },
    }
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    md = f"""# manipulation_v3 mutation recovery

이 보고서는 DataSynth v3 후보의 raw-data 회계 실체와 fitting 방지 가드만 기록한다. PHASE1 topic 진입률, Top10/Top500 capture는 measure-only이며 이 보고서의 pass/fail 조건이 아니다.

## Guard 1 — 회계 실체

| 항목 | 값 |
|---|---:|
| unusual offhour doc ratio | {guard_1['unusual_offhour_doc_ratio']:.1%} |
| unusual weekend doc ratio | {guard_1['unusual_weekend_doc_ratio']:.1%} |
| unusual manual/adjustment source ratio | {guard_1['unusual_manual_source_doc_ratio']:.1%} |
| fictitious revenue GL doc ratio | {guard_1['fictitious_revenue_gl_doc_ratio']:.1%} |
| fictitious amount >= 1.5x company revenue p95 | {guard_1['fictitious_amount_ge_1_5x_company_revenue_p95_doc_ratio']:.1%} |
| fictitious batch doc ratio | {guard_1['fictitious_batch_doc_ratio']:.1%} |

판정: **{'PASS' if guard_1_pass else 'FAIL'}**

## Guard 2 — 정상 배경 fitting 차단

| 항목 | 값 |
|---|---|
| truth doc mapping identical to v2 | `{truth_same}` |
| noise floor delta within 10pct points | `{guard_2['noise_floor_delta_within_10pct_points']}` |

```json
{json.dumps(noise_delta, ensure_ascii=False, indent=2)}
```

## Measure-only

- PHASE1 topic entry rate
- Top10 / Top500 truth capture
- expected topic 진입률

위 값들은 별도 Phase1 재측정 보고서에 쓰되, v3 생성 pass/fail gate로 사용하지 않는다.

## Guard 3 — 다른 시나리오 회귀 차단

```json
{json.dumps(guard_3, ensure_ascii=False, indent=2)}
```
"""
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text(md, encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
