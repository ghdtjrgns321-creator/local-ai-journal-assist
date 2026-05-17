"""Aggregate accounting-logic audit for DataSynth manipulation V7 fixed3."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = (
    ROOT / "data" / "journal" / "primary" / "datasynth_manipulation_v7_candidate_fixed3"
)
DEFAULT_OUT_JSON = ROOT / "artifacts" / "datasynth_v7_fixed3_accounting_logic_audit.json"
DEFAULT_OUT_MD = ROOT / "artifacts" / "datasynth_v7_fixed3_accounting_logic_audit.md"


def _rel(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _load_journal(dataset: Path) -> pd.DataFrame:
    return pd.concat(
        [
            pd.read_csv(dataset / f"journal_entries_{year}.csv", low_memory=False)
            for year in (2022, 2023, 2024)
        ],
        ignore_index=True,
    )


def _load_truth(dataset: Path) -> pd.DataFrame:
    return pd.read_csv(dataset / "labels" / "manipulated_entry_truth.csv", low_memory=False)


def _prepare(journal: pd.DataFrame, truth: pd.DataFrame) -> pd.DataFrame:
    df = journal.copy()
    truth_map = truth.set_index("document_id")["manipulation_scenario"].astype(str).to_dict()
    df["document_id"] = df["document_id"].astype(str)
    df["truth_scenario"] = df["document_id"].map(truth_map).fillna("")
    for col in ("debit_amount", "credit_amount", "local_amount"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    df["posting_dt"] = pd.to_datetime(df["posting_date"], errors="coerce")
    df["gl_text"] = df["gl_account"].astype(str)
    df["line_text_norm"] = df["line_text"].fillna("").astype(str)
    return df


def _doc_summary(df: pd.DataFrame) -> pd.DataFrame:
    grouped = df.groupby("document_id", sort=False)
    docs = grouped.agg(
        truth_scenario=("truth_scenario", "first"),
        debit=("debit_amount", "sum"),
        credit=("credit_amount", "sum"),
        business_process=("business_process", "first"),
        document_type=("document_type", "first"),
        min_hour=("posting_dt", lambda s: int(s.dt.hour.min()) if s.notna().any() else -1),
        max_hour=("posting_dt", lambda s: int(s.dt.hour.max()) if s.notna().any() else -1),
        has_accrual_liability=("gl_text", lambda s: s.astype(str).str.startswith("22").any()),
        has_expense=("gl_text", lambda s: s.astype(str).str.startswith(("6", "7")).any()),
        has_reversal_text=(
            "line_text_norm",
            lambda s: s.str.contains("역분개|환입|미지급|발생액", regex=True, na=False).any(),
        ),
        has_payroll_process=("business_process", lambda s: s.astype(str).eq("H2R").any()),
    )
    docs["balanced"] = docs["debit"].sub(docs["credit"]).abs().le(1.0)
    docs["is_truth"] = docs["truth_scenario"].ne("")
    return docs


def build_report(dataset: Path) -> dict[str, Any]:
    journal = _prepare(_load_journal(dataset), _load_truth(dataset))
    docs = _doc_summary(journal)
    balance_fail = docs.loc[~docs["balanced"]]
    period = docs.loc[docs["truth_scenario"].eq("period_end_adjustment_manipulation")]
    unusual = docs.loc[docs["truth_scenario"].eq("unusual_timing_manipulation")]
    period_ok = (
        period["balanced"]
        & period["has_accrual_liability"]
        & period["has_expense"]
        & period["has_reversal_text"]
    )
    unusual_ok = (
        unusual["balanced"]
        & unusual["business_process"].eq("TRE")
        & unusual["min_hour"].isin({0, 1, 5, 22, 23})
        & ~unusual["has_payroll_process"]
    )
    checks = {
        "balance_fail_docs": {
            "measured": int(len(balance_fail)),
            "target": 0,
            "pass": int(len(balance_fail)) == 0,
        },
        "period_end_alignment": {
            "ok": int(period_ok.sum()),
            "total": int(len(period)),
            "pass": bool(period_ok.all()) if len(period) else False,
        },
        "unusual_timing_alignment": {
            "ok": int(unusual_ok.sum()),
            "total": int(len(unusual)),
            "pass": bool(unusual_ok.all()) if len(unusual) else False,
        },
        "payroll_process_in_unusual_timing": {
            "measured": int(unusual["has_payroll_process"].sum()),
            "target": 0,
            "pass": int(unusual["has_payroll_process"].sum()) == 0,
        },
    }
    verdict = all(row["pass"] for row in checks.values())
    return {
        "dataset": _rel(dataset),
        "verdict": "PASS" if verdict else "FAIL",
        "journal_rows": int(len(journal)),
        "document_count": int(len(docs)),
        "truth_document_count": int(docs["is_truth"].sum()),
        "checks": checks,
    }


def write_md(report: dict[str, Any], out: Path) -> None:
    checks = report["checks"]
    lines = [
        "# DataSynth V7 fixed3 Accounting Logic Audit",
        "",
        f"- dataset: `{report['dataset']}`",
        f"- verdict: **{report['verdict']}**",
        "",
        "| Check | Measured | Target | Verdict |",
        "|---|---:|---:|---|",
        (
            "| BALANCE_FAIL docs | "
            f"{checks['balance_fail_docs']['measured']} | 0 | "
            f"{'PASS' if checks['balance_fail_docs']['pass'] else 'FAIL'} |"
        ),
        (
            "| period_end alignment | "
            f"{checks['period_end_alignment']['ok']} / "
            f"{checks['period_end_alignment']['total']} | all | "
            f"{'PASS' if checks['period_end_alignment']['pass'] else 'FAIL'} |"
        ),
        (
            "| unusual_timing alignment | "
            f"{checks['unusual_timing_alignment']['ok']} / "
            f"{checks['unusual_timing_alignment']['total']} | all | "
            f"{'PASS' if checks['unusual_timing_alignment']['pass'] else 'FAIL'} |"
        ),
        (
            "| unusual_timing H2R payroll process | "
            f"{checks['payroll_process_in_unusual_timing']['measured']} | 0 | "
            f"{'PASS' if checks['payroll_process_in_unusual_timing']['pass'] else 'FAIL'} |"
        ),
    ]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--out-json", default=str(DEFAULT_OUT_JSON))
    parser.add_argument("--out-md", default=str(DEFAULT_OUT_MD))
    args = parser.parse_args()
    report = build_report(Path(args.dataset))
    out_json = Path(args.out_json)
    out_md = Path(args.out_md)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_md(report, out_md)
    print(
        json.dumps(
            {"out_json": _rel(out_json), "out_md": _rel(out_md), "verdict": report["verdict"]},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
