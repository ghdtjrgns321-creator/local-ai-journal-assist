"""fixed4 — PHASE2 family 부분집합 31개 조합 recall 측정.

5 family (unsupervised, timeseries, relational, duplicate, intercompany) 의 모든
non-empty 부분집합 (2^5-1 = 31) 에 대해 PHASE2 단독 큐와 PHASE1+2 통합 큐의 TOP-N
document recall 을 측정한다. ranker 정의는 ``phase1_phase2_integration_stage7`` 와
동일하되, Noisy-OR 결합에 들어가는 family 만 부분집합으로 교체한다.
"""

# ruff: noqa: E402

from __future__ import annotations

import itertools
import json
import pickle
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import tools.scripts.phase1_phase2_integration_stage7 as stage7
from src.services.queue_fusion import (
    K_DEFAULT as RRF_K,
)
from src.services.queue_fusion import (
    compute_phase2_internal_noisy_or,
    compute_rrf_score,
)

FIXED4_PHASE1_CACHE = ROOT / "artifacts" / "stage7_fixed4_phase1_case_result.pkl"
FIXED4_PHASE2_FAMILY_CACHE = ROOT / "artifacts" / "stage7_fixed4_phase2_family_by_doc.parquet"
FIXED4_TRUTH = (
    ROOT
    / "data"
    / "journal"
    / "primary"
    / "datasynth_manipulation_v7_candidate_fixed4"
    / "labels"
    / "manipulated_entry_truth.csv"
)
OUT_JSON = ROOT / "artifacts" / "phase2_family_combination_audit_fixed4_20260523.json"
OUT_MD = ROOT / "artifacts" / "phase2_family_combination_audit_fixed4_20260523.md"

FAMILIES = ("unsupervised", "timeseries", "relational", "duplicate", "intercompany")
FAMILY_SHORT = {
    "unsupervised": "U",
    "timeseries": "T",
    "relational": "R",
    "duplicate": "D",
    "intercompany": "I",
}
TOP_NS = [100, 500, 1000, 2000, 5000, 10000]


def all_subsets() -> list[tuple[str, ...]]:
    subsets: list[tuple[str, ...]] = []
    for k in range(1, len(FAMILIES) + 1):
        for combo in itertools.combinations(FAMILIES, k):
            subsets.append(combo)
    return subsets


def build_phase2_queue_subset(base_df: pd.DataFrame, families: tuple[str, ...]) -> pd.DataFrame:
    base = stage7._ensure_base_phase2_columns(base_df).reset_index(drop=True)
    family_scores = {
        family: pd.Series(
            base[f"phase2_{family}_score_max"].astype(np.float64).to_numpy(),
            dtype=np.float64,
            name=family,
        )
        for family in families
    }
    noisy_or = compute_phase2_internal_noisy_or(family_scores)
    out = base.copy()
    out["phase2_subset_noisy_or"] = noisy_or.to_numpy()
    queue = out.sort_values(
        by=["phase2_subset_noisy_or", "total_amount", "rule_count"],
        ascending=False,
        kind="mergesort",
        na_position="last",
    ).reset_index(drop=True)
    queue.insert(0, "phase2_review_rank", queue.index + 1)
    return queue


def build_integrated_queue_subset(
    base_df: pd.DataFrame,
    families: tuple[str, ...],
    k: int = RRF_K,
) -> pd.DataFrame:
    base = stage7._ensure_base_phase2_columns(base_df).reset_index(drop=True)
    family_scores = {
        family: pd.Series(
            base[f"phase2_{family}_score_max"].astype(np.float64).to_numpy(),
            dtype=np.float64,
            name=family,
        )
        for family in families
    }
    noisy_or = compute_phase2_internal_noisy_or(family_scores)
    rankers = {
        "phase1_composite": pd.Series(
            base["phase1_composite_sort_score"].astype(np.float64).to_numpy(),
            dtype=np.float64,
        ),
        "phase2_internal_noisy_or": pd.Series(
            noisy_or.to_numpy(), dtype=np.float64, name="phase2_internal_noisy_or"
        ),
    }
    rrf = compute_rrf_score(rankers, k=k)
    merged = base.join(rrf)
    queue = merged.sort_values(
        by=["rrf_score", "phase1_composite_sort_score"],
        ascending=False,
        kind="mergesort",
    ).reset_index(drop=True)
    queue.insert(0, "review_rank", queue.index + 1)
    return queue


def measure(queue: pd.DataFrame, truth_docs: set[str]) -> dict[int, dict[str, float]]:
    out: dict[int, dict[str, float]] = {}
    for n in TOP_NS:
        result = stage7.measure_doc_recall(queue, truth_docs, n)
        out[n] = {
            "matched": int(result["matched_truth_docs"]),
            "recall": float(result["recall"]),
        }
    return out


def short_label(families: tuple[str, ...]) -> str:
    return "".join(FAMILY_SHORT[f] for f in families)


def main() -> int:
    t_start = time.perf_counter()

    print("[fc] loading phase1 case cache + phase2 family cache + truth ...")
    with FIXED4_PHASE1_CACHE.open("rb") as fh:
        phase1_result = pickle.load(fh)
    phase2_by_doc = stage7._ensure_phase2_family_columns(
        pd.read_parquet(FIXED4_PHASE2_FAMILY_CACHE)
    )
    truth = pd.read_csv(FIXED4_TRUTH)
    truth_docs = set(truth["document_id"].astype(str))

    print(
        f"[fc] cases={len(phase1_result.cases):,} "
        f"phase2_docs={len(phase2_by_doc):,} truth_docs={len(truth_docs)}"
    )

    print("[fc] building base review queue rows ...")
    base_df = stage7._build_base_rows(phase1_result, phase2_by_doc, [], truth_docs)

    subsets = all_subsets()
    print(f"[fc] {len(subsets)} non-empty family subsets to evaluate")

    rows: list[dict[str, Any]] = []
    for i, families in enumerate(subsets, start=1):
        print(f"[fc] {i:2d}/{len(subsets)} families={families}")
        queue_phase2 = build_phase2_queue_subset(base_df, families)
        queue_integrated = build_integrated_queue_subset(base_df, families)
        row = {
            "subset": list(families),
            "subset_label": short_label(families),
            "subset_size": len(families),
            "phase2": measure(queue_phase2, truth_docs),
            "integrated": measure(queue_integrated, truth_docs),
        }
        rows.append(row)

    report = {
        "dataset_version": "datasynth_manipulation_v7_candidate_fixed4",
        "elapsed_sec": round(time.perf_counter() - t_start, 2),
        "phase1_cases": len(phase1_result.cases),
        "phase2_scored_docs": int(len(phase2_by_doc)),
        "total_truth_docs": len(truth_docs),
        "rrf_k": int(RRF_K),
        "families": list(FAMILIES),
        "family_short": FAMILY_SHORT,
        "top_ns": TOP_NS,
        "combinations": rows,
    }
    OUT_JSON.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"[fc] wrote {OUT_JSON.relative_to(ROOT)}")

    md_lines: list[str] = []
    md_lines += [
        "# fixed4 PHASE2 family 부분집합 31개 조합 recall 보고서",
        "",
        f"- dataset: `{report['dataset_version']}`",
        f"- phase1 cases: `{report['phase1_cases']:,}`",
        f"- truth docs: `{report['total_truth_docs']}`",
        f"- RRF k: `{report['rrf_k']}` (PHASE1↔PHASE2 Noisy-OR 2-way)",
        f"- families: `{FAMILIES}` (short: `{FAMILY_SHORT}`)",
        f"- top-N measured: `{TOP_NS}`",
        f"- elapsed: `{report['elapsed_sec']}s`",
        "",
    ]
    for queue_name, queue_title in [
        ("phase2", "## PHASE2 단독 큐 — Noisy-OR(subset) 정렬"),
        ("integrated", "## PHASE1+2 통합 큐 — PHASE1 composite ↔ Noisy-OR(subset) RRF k=60"),
    ]:
        md_lines.append(queue_title)
        md_lines.append("")
        header = "| subset | size | " + " | ".join(f"TOP {n}" for n in TOP_NS) + " |"
        sep = "|---" + "|---:" * (len(TOP_NS) + 1) + "|"
        md_lines.append(header)
        md_lines.append(sep)
        rows_sorted = sorted(
            rows,
            key=lambda r: (r["subset_size"], r["subset_label"]),
        )
        for r in rows_sorted:
            cells = [
                f"`{r['subset_label']}`",
                str(r["subset_size"]),
            ]
            for n in TOP_NS:
                m = r[queue_name][n]
                cells.append(f"{m['matched']} ({m['recall'] * 100:.2f}%)")
            md_lines.append("| " + " | ".join(cells) + " |")
        md_lines.append("")
    OUT_MD.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"[fc] wrote {OUT_MD.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
