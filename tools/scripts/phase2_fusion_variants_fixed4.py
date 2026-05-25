"""fixed4 — PHASE1+2 통합 룰 변형 ablation.

현재 운영식 (PHASE1 composite ↔ PHASE2 Noisy-OR(UTRDI) 2-way RRF k=60) 을 baseline 으로
다음 변형을 측정한다:

  A. RRF k 변경 (10 / 30 / 60 / 120 / 240)
  B. weighted RRF (PHASE1 weight 2x / 0.5x)
  C. PHASE2 결합식 변경
     - max(ecdf_f)
     - mean(ecdf_f)
     - weighted Noisy-OR (R, I weight ↓)
  D. PHASE2 단독 결합 변경 후 통합 RRF 효과
"""

# ruff: noqa: E402

from __future__ import annotations

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
    to_ecdf,
)

FIXED4_PHASE1_CACHE = ROOT / "artifacts" / "stage7_fixed4_phase1_case_result.pkl"
FIXED4_PHASE2_FAMILY_CACHE = ROOT / "artifacts" / "stage7_fixed4_phase2_family_by_doc.parquet"
TRUTH = (
    ROOT
    / "data"
    / "journal"
    / "primary"
    / "datasynth_manipulation_v7_candidate_fixed4"
    / "labels"
    / "manipulated_entry_truth.csv"
)
OUT = ROOT / "artifacts" / "phase2_fusion_variants_fixed4_20260523.json"

FAMILIES = ("unsupervised", "timeseries", "relational", "duplicate", "intercompany")
TOP_NS = [100, 500, 1000, 2000, 5000, 10000]


def measure(queue: pd.DataFrame, truth_docs: set[str]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for n in TOP_NS:
        r = stage7.measure_doc_recall(queue, truth_docs, n)
        out[n] = {
            "matched": int(r["matched_truth_docs"]),
            "recall": float(r["recall"]),
        }
    return out


def family_scores_from_base(base_df: pd.DataFrame) -> dict[str, pd.Series]:
    return {
        f: pd.Series(
            base_df[f"phase2_{f}_score_max"].astype(np.float64).to_numpy(),
            dtype=np.float64,
            name=f,
        )
        for f in FAMILIES
    }


def weighted_noisy_or(
    family_scores: dict[str, pd.Series],
    weights: dict[str, float],
    epsilon: float = 1e-12,
) -> pd.Series:
    """ECDF^weight 형태 weighted Noisy-OR.

    weight < 1 → 영향 감소 (ecdf^w 가 더 1 에 가까워짐 → 1-ecdf^w 가 더 작음).
    weight > 1 → 영향 증가.
    """
    base_index = next(iter(family_scores.values())).index
    survival = pd.Series(1.0, index=base_index, dtype=np.float64)
    for name, scores in family_scores.items():
        weight = float(weights.get(name, 1.0))
        if weight <= 0:
            continue
        ecdf = to_ecdf(scores).clip(0.0, 1.0 - epsilon)
        survival *= np.power(1.0 - ecdf, weight)
    return 1.0 - survival


def max_combine(family_scores: dict[str, pd.Series]) -> pd.Series:
    base_index = next(iter(family_scores.values())).index
    out = pd.Series(0.0, index=base_index, dtype=np.float64)
    for scores in family_scores.values():
        ecdf = to_ecdf(scores)
        out = pd.concat([out, ecdf], axis=1).max(axis=1)
    return out


def mean_combine(family_scores: dict[str, pd.Series]) -> pd.Series:
    base_index = next(iter(family_scores.values())).index
    accum = pd.Series(0.0, index=base_index, dtype=np.float64)
    n = 0
    for scores in family_scores.values():
        accum = accum + to_ecdf(scores)
        n += 1
    return accum / max(n, 1)


def build_integrated_with_phase2_score(
    base_df: pd.DataFrame,
    phase2_score: pd.Series,
    k: int = RRF_K,
    phase1_weight: float = 1.0,
    phase2_weight: float = 1.0,
) -> pd.DataFrame:
    base = base_df.reset_index(drop=True).copy()
    phase1_series = pd.Series(
        base["phase1_composite_sort_score"].astype(np.float64).to_numpy(),
        dtype=np.float64,
    )
    rankers = {"phase1_composite": phase1_series, "phase2_internal": phase2_score}
    rrf = compute_rrf_score(rankers, k=k)
    # Weighted RRF: rrf_score_weighted = w1 * 1/(k+rank1) + w2 * 1/(k+rank2)
    if phase1_weight != 1.0 or phase2_weight != 1.0:
        rank_p1 = rrf["rank_phase1_composite"]
        rank_p2 = rrf["rank_phase2_internal"]
        rrf["rrf_score"] = phase1_weight / (k + rank_p1) + phase2_weight / (k + rank_p2)
    merged = base.join(rrf)
    queue = merged.sort_values(
        by=["rrf_score", "phase1_composite_sort_score"],
        ascending=False,
        kind="mergesort",
    ).reset_index(drop=True)
    queue.insert(0, "review_rank", queue.index + 1)
    return queue


def build_phase2_only_with_score(base_df: pd.DataFrame, phase2_score: pd.Series) -> pd.DataFrame:
    base = base_df.reset_index(drop=True).copy()
    base["phase2_subset_score"] = phase2_score.to_numpy()
    queue = base.sort_values(
        by=["phase2_subset_score", "total_amount", "rule_count"],
        ascending=False,
        kind="mergesort",
        na_position="last",
    ).reset_index(drop=True)
    queue.insert(0, "phase2_review_rank", queue.index + 1)
    return queue


def main() -> int:
    t0 = time.perf_counter()
    print("loading caches ...")
    with FIXED4_PHASE1_CACHE.open("rb") as fh:
        phase1_result = pickle.load(fh)
    phase2_by_doc = stage7._ensure_phase2_family_columns(
        pd.read_parquet(FIXED4_PHASE2_FAMILY_CACHE)
    )
    truth_docs = set(pd.read_csv(TRUTH)["document_id"].astype(str))
    base_df = stage7._build_base_rows(phase1_result, phase2_by_doc, [], truth_docs)
    fam_scores = family_scores_from_base(base_df)

    print(f"  cases={len(base_df):,}  truth={len(truth_docs)}")

    results: list[dict[str, Any]] = []

    # ── A. RRF k 변경 ────────────────────────────────────────────
    print("\n[A] RRF k variation")
    baseline_noisy = compute_phase2_internal_noisy_or(fam_scores)
    for k in [10, 30, 60, 120, 240]:
        queue = build_integrated_with_phase2_score(base_df, baseline_noisy, k=k)
        results.append(
            {
                "group": "A",
                "name": f"rrf_k={k}",
                "phase2": None,
                "integrated": measure(queue, truth_docs),
            }
        )

    # ── B. weighted RRF ─────────────────────────────────────────
    print("[B] weighted RRF")
    for p1w, p2w in [(2.0, 1.0), (1.0, 2.0), (3.0, 1.0), (1.0, 0.5)]:
        queue = build_integrated_with_phase2_score(
            base_df, baseline_noisy, k=60, phase1_weight=p1w, phase2_weight=p2w
        )
        results.append(
            {
                "group": "B",
                "name": f"weighted_rrf_p1={p1w}_p2={p2w}",
                "phase2": None,
                "integrated": measure(queue, truth_docs),
            }
        )

    # ── C. PHASE2 결합식 변경 ────────────────────────────────────
    print("[C] PHASE2 aggregator variants")
    aggregators: list[tuple[str, pd.Series]] = [
        ("noisy_or_baseline", baseline_noisy),
        ("max_ecdf", max_combine(fam_scores)),
        ("mean_ecdf", mean_combine(fam_scores)),
        (
            "weighted_noisy_or_R0.3_I0.3",
            weighted_noisy_or(
                fam_scores,
                {
                    "unsupervised": 1.0,
                    "timeseries": 1.0,
                    "relational": 0.3,
                    "duplicate": 1.0,
                    "intercompany": 0.3,
                },
            ),
        ),
        (
            "weighted_noisy_or_T0.5_R0.3_I0.3",
            weighted_noisy_or(
                fam_scores,
                {
                    "unsupervised": 1.0,
                    "timeseries": 0.5,
                    "relational": 0.3,
                    "duplicate": 1.0,
                    "intercompany": 0.3,
                },
            ),
        ),
        (
            "weighted_noisy_or_DU_only",
            weighted_noisy_or(
                fam_scores,
                {
                    "unsupervised": 1.0,
                    "timeseries": 0.0,
                    "relational": 0.0,
                    "duplicate": 1.0,
                    "intercompany": 0.0,
                },
            ),
        ),
        (
            "weighted_noisy_or_D2_U2",
            weighted_noisy_or(
                fam_scores,
                {
                    "unsupervised": 2.0,
                    "timeseries": 1.0,
                    "relational": 1.0,
                    "duplicate": 2.0,
                    "intercompany": 1.0,
                },
            ),
        ),
    ]
    for name, score in aggregators:
        p2_queue = build_phase2_only_with_score(base_df, score)
        in_queue = build_integrated_with_phase2_score(base_df, score, k=60)
        results.append(
            {
                "group": "C",
                "name": name,
                "phase2": measure(p2_queue, truth_docs),
                "integrated": measure(in_queue, truth_docs),
            }
        )

    OUT.write_text(
        json.dumps(
            {
                "dataset": "datasynth_manipulation_v7_candidate_fixed4",
                "elapsed_sec": round(time.perf_counter() - t0, 2),
                "total_truth_docs": len(truth_docs),
                "top_ns": TOP_NS,
                "variants": results,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    print(f"elapsed {time.perf_counter() - t0:.1f}s")

    # Console summary
    print("\n=== integrated TOP-N recall (key variants) ===")
    print(f"{'name':38s}  T100   T500  T1000  T2000  T5000 T10000")
    for r in results:
        m = r["integrated"]
        line = f"{r['name']:38s}  "
        for n in TOP_NS:
            line += f"{m[n]['recall'] * 100:5.2f}% "
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
