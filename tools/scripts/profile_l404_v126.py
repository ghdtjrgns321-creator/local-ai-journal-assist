"""Profile L4-04 rare account pair on DataSynth v126.

This isolates the suspected PHASE1 bottleneck/crash point without running the
full detector stack.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = PROJECT_ROOT / "data" / "journal" / "primary" / "datasynth_v126_candidate"
OUT = PROJECT_ROOT / "artifacts" / "phase1_v126_l404_profile.json"
USECOLS = ["document_id", "gl_account", "debit_amount", "credit_amount"]


def _elapsed(start: float) -> float:
    return round(time.perf_counter() - start, 3)


def _write(payload: dict[str, Any]) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def main() -> int:
    total = time.perf_counter()
    summary: dict[str, Any] = {
        "data_dir": str(DATA_DIR),
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "stages": {},
    }
    _write(summary)

    t0 = time.perf_counter()
    df = pd.read_csv(DATA_DIR / "journal_entries.csv", usecols=USECOLS, low_memory=False)
    summary["stages"]["read_csv"] = {
        "elapsed_sec": _elapsed(t0),
        "rows": int(len(df)),
        "documents": int(df["document_id"].nunique()),
    }
    _write(summary)

    t0 = time.perf_counter()
    debit_amt = pd.to_numeric(df["debit_amount"], errors="coerce").fillna(0)
    credit_amt = pd.to_numeric(df["credit_amount"], errors="coerce").fillna(0)
    debits = df.loc[debit_amt > 0, ["document_id", "gl_account"]]
    credits = df.loc[credit_amt > 0, ["document_id", "gl_account"]]
    debits = debits[debits["gl_account"].notna()]
    credits = credits[credits["gl_account"].notna()]
    doc_sizes = df.groupby("document_id").size()
    large_docs = doc_sizes[doc_sizes > 100].index
    large_debits = debits[debits["document_id"].isin(large_docs)].drop_duplicates(
        ["document_id", "gl_account"],
    )
    large_credits = credits[credits["document_id"].isin(large_docs)].drop_duplicates(
        ["document_id", "gl_account"],
    )
    normal_debits = debits[~debits["document_id"].isin(large_docs)]
    normal_credits = credits[~credits["document_id"].isin(large_docs)]

    normal_counts = (
        normal_debits.groupby("document_id").size().rename("dr").to_frame()
        .join(normal_credits.groupby("document_id").size().rename("cr"), how="inner")
    )
    large_counts = (
        large_debits.groupby("document_id").size().rename("dr").to_frame()
        .join(large_credits.groupby("document_id").size().rename("cr"), how="inner")
    )
    normal_pair_counts = normal_counts["dr"] * normal_counts["cr"]
    large_pair_counts = large_counts["dr"] * large_counts["cr"]
    summary["stages"]["pair_cardinality"] = {
        "elapsed_sec": _elapsed(t0),
        "debit_rows": int(len(debits)),
        "credit_rows": int(len(credits)),
        "large_document_count": int(len(large_docs)),
        "normal_doc_with_both_sides": int(len(normal_counts)),
        "large_doc_with_both_sides": int(len(large_counts)),
        "estimated_normal_pairs": int(normal_pair_counts.sum()),
        "estimated_large_pairs": int(large_pair_counts.sum()) if len(large_pair_counts) else 0,
        "max_normal_pairs_per_doc": int(normal_pair_counts.max()) if len(normal_pair_counts) else 0,
        "p99_normal_pairs_per_doc": float(normal_pair_counts.quantile(0.99)) if len(normal_pair_counts) else 0.0,
        "max_doc_lines": int(doc_sizes.max()),
    }
    _write(summary)

    t0 = time.perf_counter()
    normal_pairs = normal_debits.merge(
        normal_credits,
        on="document_id",
        suffixes=("_dr", "_cr"),
    )
    large_pairs = large_debits.merge(
        large_credits,
        on="document_id",
        suffixes=("_dr", "_cr"),
    )
    normal_pairs["_large_doc_pair"] = False
    large_pairs["_large_doc_pair"] = True
    pairs = pd.concat([normal_pairs, large_pairs], ignore_index=True)
    summary["stages"]["merge_pairs"] = {
        "elapsed_sec": _elapsed(t0),
        "normal_pairs": int(len(normal_pairs)),
        "large_pairs": int(len(large_pairs)),
        "all_pairs": int(len(pairs)),
        "memory_mb_pairs": round(float(pairs.memory_usage(deep=True).sum()) / 1024 / 1024, 1),
    }
    _write(summary)

    t0 = time.perf_counter()
    pair_counts = normal_pairs.groupby(["gl_account_dr", "gl_account_cr"]).size()
    threshold = max(pair_counts.quantile(0.01), 1)
    rare_idx = pair_counts[pair_counts <= threshold].reset_index()
    rare_idx.columns = ["gl_account_dr", "gl_account_cr", "_count"]
    rare_idx["_rare"] = True
    summary["stages"]["pair_counts"] = {
        "elapsed_sec": _elapsed(t0),
        "distinct_pair_count": int(len(pair_counts)),
        "threshold_count": float(threshold),
        "rare_pair_count": int(len(rare_idx)),
    }
    _write(summary)

    t0 = time.perf_counter()
    pairs = pairs.merge(
        rare_idx[["gl_account_dr", "gl_account_cr", "_rare"]],
        on=["gl_account_dr", "gl_account_cr"],
        how="left",
    )
    pairs["_rare"] = pairs["_rare"].where(
        pairs["_rare"].notna(),
        pairs["_large_doc_pair"],
    ).astype(bool)
    rare_docs = set(pairs.loc[pairs["_rare"] == True, "document_id"])  # noqa: E712
    summary["stages"]["rare_merge"] = {
        "elapsed_sec": _elapsed(t0),
        "rare_docs": int(len(rare_docs)),
        "rare_pair_rows": int(pairs["_rare"].sum()),
        "memory_mb_pairs_after_rare": round(float(pairs.memory_usage(deep=True).sum()) / 1024 / 1024, 1),
    }
    _write(summary)

    t0 = time.perf_counter()
    result = df["document_id"].isin(rare_docs)
    rare_pairs = pairs[pairs["_rare"] == True].copy()  # noqa: E712
    rare_doc_summary = rare_pairs.groupby("document_id").agg(
        rare_pair_count=("document_id", "size"),
        has_large_doc_pair=("_large_doc_pair", "max"),
    )
    summary["stages"]["rare_doc_summary"] = {
        "elapsed_sec": _elapsed(t0),
        "flagged_rows": int(result.sum()),
        "rare_pair_rows": int(len(rare_pairs)),
        "rare_doc_summary_rows": int(len(rare_doc_summary)),
        "memory_mb_rare_pairs": round(float(rare_pairs.memory_usage(deep=True).sum()) / 1024 / 1024, 1),
    }
    _write(summary)

    t0 = time.perf_counter()
    row_count = int(df.index[result].shape[0])
    doc_count = int(result.groupby(df["document_id"]).max().sum())
    summary["stages"]["annotation_cardinality"] = {
        "elapsed_sec": _elapsed(t0),
        "rows_to_annotate": row_count,
        "docs_to_annotate": doc_count,
    }
    summary["total_elapsed_sec"] = _elapsed(total)
    summary["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _write(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
