"""Trace fictitious_entry truth docs that did not enter revenue_statistical topic.

Reads:
- truth CSV: data/journal/primary/datasynth_manipulation_v2/labels/manipulated_entry_truth.csv
- case artifact JSON (430 MB): streamed via ijson
- journal CSVs: data/journal/primary/datasynth_manipulation_v2/journal_*.csv

Writes:
- artifacts/fictitious_missing_24_trace.json (raw)
- summary printed to stdout
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import ijson
import pandas as pd

ROOT = Path(r"C:\Users\ghdtj\workspace\portfolio\local-ai-assist")
TRUTH_CSV = (
    ROOT / "data/journal/primary/datasynth_manipulation_v2/labels/manipulated_entry_truth.csv"
)
CASE_JSON = (
    ROOT
    / "artifacts/phase1_cases/_anonymous/phase1case__anonymous_datasynth_v126_profiled_phase1_20260514T093051Z.json"
)
JOURNAL_DIR = ROOT / "data/journal/primary/datasynth_manipulation_v2"
OUT_JSON = ROOT / "artifacts/fictitious_missing_24_trace.json"


def load_fictitious_truth() -> pd.DataFrame:
    df = pd.read_csv(TRUTH_CSV, low_memory=False)
    return df.loc[df["manipulation_scenario"] == "fictitious_entry"].copy()


def stream_cases_for_docs(target_doc_ids: set[str]) -> dict[str, list[dict]]:
    """For each target document_id, return list of (case_id, topic_scores, primary_topic, matched_rules)."""
    doc_to_cases: dict[str, list[dict]] = defaultdict(list)
    with CASE_JSON.open("rb") as fh:
        for case in ijson.items(fh, "cases.item"):
            documents = case.get("documents", []) or []
            doc_ids_in_case = {str(d.get("document_id")) for d in documents}
            hit = doc_ids_in_case & target_doc_ids
            if not hit:
                continue
            topic_scores = case.get("topic_scores") or {}
            primary_topic = case.get("primary_topic")
            case_id = case.get("case_id")
            priority_band = case.get("priority_band")
            rule_ids_in_case = sorted(
                {
                    str(ev.get("rule_id"))
                    for ev in (case.get("rule_evidence_summary") or [])
                    if ev.get("rule_id")
                }
            )
            for doc_id in hit:
                matched = next(
                    (
                        d.get("matched_rules", [])
                        for d in documents
                        if str(d.get("document_id")) == doc_id
                    ),
                    [],
                )
                doc_to_cases[doc_id].append(
                    {
                        "case_id": case_id,
                        "primary_topic": primary_topic,
                        "priority_band": priority_band,
                        "topic_scores": dict(topic_scores),
                        "matched_rules_doc": list(matched),
                        "case_rule_ids": rule_ids_in_case,
                    }
                )
    return doc_to_cases


def classify_entry(doc_to_cases: dict[str, list[dict]], target_ids: set[str]) -> dict[str, dict]:
    """For each truth doc, determine if any case has revenue_statistical > 0."""
    out: dict[str, dict] = {}
    for doc_id in target_ids:
        cases = doc_to_cases.get(doc_id, [])
        max_rev = 0.0
        any_rev_in_topic = False
        for c in cases:
            score = float(c["topic_scores"].get("revenue_statistical") or 0.0)
            if score > 0:
                any_rev_in_topic = True
            if score > max_rev:
                max_rev = score
        out[doc_id] = {
            "case_count": len(cases),
            "max_revenue_statistical_score": max_rev,
            "entered_revenue_statistical": any_rev_in_topic,
            "cases": cases,
        }
    return out


def load_journal_rows(target_doc_ids: set[str]) -> pd.DataFrame:
    """Load all rows belonging to the target docs from journal CSVs."""
    journal_files = sorted(JOURNAL_DIR.glob("journal_entries_*.csv"))
    pieces: list[pd.DataFrame] = []
    keep_cols = None
    for f in journal_files:
        if "labels" in str(f):
            continue
        # only need a subset of columns to keep memory low
        if keep_cols is None:
            sample = pd.read_csv(f, nrows=1)
            keep_cols = [
                c
                for c in sample.columns
                if c
                in {
                    "document_id",
                    "fiscal_year",
                    "company_code",
                    "posting_date",
                    "document_date",
                    "business_process",
                    "source",
                    "document_type",
                    "created_by",
                    "approved_by",
                    "approval_date",
                    "gl_account",
                    "debit_amount",
                    "credit_amount",
                    "local_amount",
                    "header_text",
                    "line_text",
                    "counterparty_type",
                    "trading_partner",
                    "reference",
                    "user_persona",
                    "auxiliary_account_label",
                    "mutation_type",
                    "mutation_mutated_field",
                    "mutation_mutated_value",
                    "detection_surface_hints",
                }
            ]
        chunks = pd.read_csv(f, usecols=keep_cols, low_memory=False, chunksize=200_000)
        for chunk in chunks:
            sub = chunk.loc[chunk["document_id"].astype(str).isin(target_doc_ids)]
            if not sub.empty:
                pieces.append(sub.copy())
    if not pieces:
        return pd.DataFrame()
    return pd.concat(pieces, ignore_index=True)


def summarize_groups(rows: pd.DataFrame, label: str) -> dict:
    if rows.empty:
        return {"label": label, "row_count": 0}
    by_doc = rows.groupby("document_id")
    summary = {
        "label": label,
        "doc_count": rows["document_id"].nunique(),
        "row_count": int(len(rows)),
        "gl_account_top": Counter(rows["gl_account"].astype(str).tolist()).most_common(15),
        "business_process_top": Counter(
            rows["business_process"].astype(str).tolist()
        ).most_common(),
        "source_top": Counter(
            rows.get("source", pd.Series(dtype=str)).astype(str).tolist()
        ).most_common(),
        "document_type_top": Counter(
            rows.get("document_type", pd.Series(dtype=str)).astype(str).tolist()
        ).most_common(),
        "counterparty_type_top": Counter(
            rows.get("counterparty_type", pd.Series(dtype=str)).astype(str).tolist()
        ).most_common(),
        "created_by_top": Counter(
            rows.get("created_by", pd.Series(dtype=str)).astype(str).tolist()
        ).most_common(10),
        "header_text_top": Counter(
            rows.get("header_text", pd.Series(dtype=str)).astype(str).tolist()
        ).most_common(10),
    }
    # period end / weekend buckets
    posting = pd.to_datetime(rows["posting_date"], errors="coerce")
    summary["posting_month_top"] = Counter(posting.dt.month.astype(str).tolist()).most_common()
    summary["posting_day_top"] = Counter(posting.dt.day.astype(str).tolist()).most_common()
    is_dec = posting.dt.month == 12
    summary["dec_doc_count"] = int(rows.loc[is_dec, "document_id"].nunique())
    summary["dec_30_31_doc_count"] = int(
        rows.loc[is_dec & posting.dt.day.isin([30, 31]), "document_id"].nunique()
    )
    # debit/credit amount distribution (per document max)
    for col in ("debit_amount", "credit_amount", "line_amount", "amount_local"):
        if col in rows.columns:
            doc_max = (
                by_doc[col].apply(lambda s: pd.to_numeric(s, errors="coerce").abs().max()).dropna()
            )
            if not doc_max.empty:
                summary[f"doc_{col}_max_describe"] = {
                    "n": int(doc_max.size),
                    "min": float(doc_max.min()),
                    "p25": float(doc_max.quantile(0.25)),
                    "p50": float(doc_max.quantile(0.50)),
                    "p75": float(doc_max.quantile(0.75)),
                    "p95": float(doc_max.quantile(0.95)),
                    "max": float(doc_max.max()),
                }
    return summary


def main() -> None:
    truth = load_fictitious_truth()
    target_ids = set(truth["document_id"].astype(str).tolist())
    print(f"fictitious truth docs: {len(target_ids)}")

    print("streaming case JSON ...")
    doc_to_cases = stream_cases_for_docs(target_ids)
    print(f"docs found in cases: {len(doc_to_cases)}")

    classification = classify_entry(doc_to_cases, target_ids)
    entered = [d for d, info in classification.items() if info["entered_revenue_statistical"]]
    missed = [d for d, info in classification.items() if not info["entered_revenue_statistical"]]
    print(f"entered revenue_statistical: {len(entered)}")
    print(f"missed: {len(missed)}")

    print("loading journal rows for entered + missed ...")
    rows_missed = load_journal_rows(set(missed))
    rows_entered = load_journal_rows(set(entered))

    summary_missed = summarize_groups(rows_missed, "missed_24")
    summary_entered = summarize_groups(rows_entered, "entered_144")

    # Per-missed doc detail (rule hits + case info)
    missed_detail: list[dict] = []
    for doc_id in sorted(missed):
        info = classification[doc_id]
        rows_for_doc = rows_missed.loc[rows_missed["document_id"] == doc_id]
        # collect union of matched_rules across cases (per doc)
        rules_union: set[str] = set()
        case_rules_union: set[str] = set()
        case_topic_score_max: dict[str, float] = {}
        for c in info["cases"]:
            for r in c.get("matched_rules_doc", []) or []:
                rules_union.add(str(r))
            for r in c.get("case_rule_ids", []) or []:
                case_rules_union.add(str(r))
            for t, s in (c.get("topic_scores") or {}).items():
                if float(s or 0) > case_topic_score_max.get(t, 0.0):
                    case_topic_score_max[t] = float(s or 0)
        truth_row = truth.loc[truth["document_id"].astype(str) == doc_id].iloc[0]
        missed_detail.append(
            {
                "document_id": doc_id,
                "fiscal_year": int(truth_row["fiscal_year"]),
                "manipulation_subtype": str(truth_row.get("manipulation_subtype", "")),
                "case_count": info["case_count"],
                "case_ids": [c["case_id"] for c in info["cases"]],
                "case_topic_score_max": case_topic_score_max,
                "matched_rules_doc_union": sorted(rules_union),
                "case_rule_ids_union": sorted(case_rules_union),
                "row_count": int(len(rows_for_doc)),
                "gl_accounts": sorted(set(rows_for_doc["gl_account"].astype(str).tolist())),
                "business_process": sorted(
                    set(rows_for_doc["business_process"].astype(str).tolist())
                ),
                "source": sorted(
                    set(rows_for_doc.get("source", pd.Series(dtype=str)).astype(str).tolist())
                ),
                "document_type": sorted(
                    set(
                        rows_for_doc.get("document_type", pd.Series(dtype=str)).astype(str).tolist()
                    )
                ),
                "posting_dates": sorted(set(rows_for_doc["posting_date"].astype(str).tolist())),
                "max_debit": float(
                    pd.to_numeric(rows_for_doc.get("debit_amount", pd.Series([0])), errors="coerce")
                    .abs()
                    .max()
                    or 0
                ),
                "max_credit": float(
                    pd.to_numeric(
                        rows_for_doc.get("credit_amount", pd.Series([0])), errors="coerce"
                    )
                    .abs()
                    .max()
                    or 0
                ),
                "header_text": sorted(
                    set(rows_for_doc.get("header_text", pd.Series(dtype=str)).astype(str).tolist())
                ),
            }
        )

    out = {
        "fictitious_truth_total": len(target_ids),
        "entered_revenue_statistical": len(entered),
        "missed_revenue_statistical": len(missed),
        "summary_entered_144": summary_entered,
        "summary_missed_24": summary_missed,
        "missed_docs_detail": missed_detail,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with OUT_JSON.open("w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2, default=str)
    print(f"wrote {OUT_JSON}")


if __name__ == "__main__":
    main()
