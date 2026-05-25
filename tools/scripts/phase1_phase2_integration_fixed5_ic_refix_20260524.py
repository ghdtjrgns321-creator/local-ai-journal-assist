"""Stage7 재측정 — IC timing_prob 도메인 분리 효과를 fixed5_normalcal5 PKL 로 측정.

PHASE2 5-family 점수는 timing_prob 변경 반영을 위해 항상 재계산 (cache 무시).
산출물은 `_ic_refix_20260524` 접미사로 분리한다.

변경 대상:
  - src/detection/intercompany_rules.py compute_probabilistic_pair_scores
    (best_per_row carry 확장 + month-end grace + amount/cp/ref strong → weak_cap)
  - src/detection/intercompany_matcher.py _compute_probabilistic_scores
    (load_timing_domain 전달)
  - config/settings.py ic_timing_* 6 개 추가

acceptance criteria (사용자 명시):
  - normal score ≥0.99 docs 2,432 수준이면 실패 → 축소 확인
  - circular 34 건이 모두 0 으로 떨어지면 실패 → reciprocal helper 의 1.0 유지
  - IC single TOP100/500 이 0 이면 실패
  - 4500↔2700 accrual/revenue pair 가 period_end/self-balanced 만으로 1.0 만들면 실패
  - 1.0 bucket 이 수천 개로 생기면 실패
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
from src.detection.phase1_case_builder import build_phase1_case_result

FIXED5_PKL = ROOT / "artifacts" / "phase1_manipulation_v7_fixed5_normalcal5_case_input.pkl"
FIXED5_TRUTH = (
    ROOT
    / "data"
    / "journal"
    / "primary"
    / "datasynth_manipulation_v7_candidate_fixed5_normalcal5"
    / "labels"
    / "manipulated_entry_truth.csv"
)
FIXED5_PHASE1_CACHE = ROOT / "artifacts" / "stage7_fixed5_normalcal5_phase1_case_result.pkl"

OUT_DIR = ROOT / "artifacts"
OUT_PHASE2_PARQUET = OUT_DIR / "stage7_fixed5_ic_refix_20260524_phase2_family_by_doc.parquet"
OUT_REPORT_JSON = OUT_DIR / "stage7_fixed5_ic_refix_20260524_report.json"

TOP_NS = [100, 500, 1000, 2000, 5000, 10000]

BASELINE_REPORT = "artifacts/phase1_phase2_integration_fixed5_normalcal5_20260524.json"
BASELINE_PARQUET = "artifacts/stage7_fixed5_normalcal5_phase2_family_by_doc_20260524.parquet"
PREV_DESIGN_FIX_PARQUET = (
    "artifacts/stage7_fixed5_ic_design_fix_20260524_phase2_family_by_doc.parquet"
)


def _distribution_summary(series: pd.Series) -> dict[str, float]:
    clean = pd.to_numeric(series, errors="coerce").fillna(0.0).astype(float)
    nonzero = clean[clean > 0]
    return {
        "row_count": int(len(clean)),
        "nonzero_count": int(len(nonzero)),
        "nonzero_ratio": float(len(nonzero) / max(len(clean), 1)),
        "mean": float(clean.mean()) if len(clean) else 0.0,
        "nonzero_mean": float(nonzero.mean()) if len(nonzero) else 0.0,
        "q95": float(np.quantile(clean, 0.95)) if len(clean) else 0.0,
        "q99": float(np.quantile(clean, 0.99)) if len(clean) else 0.0,
        "max": float(clean.max()) if len(clean) else 0.0,
    }


def _truth_split_distribution(
    phase2_by_doc: pd.DataFrame, truth_docs: set[str], col: str
) -> dict[str, Any]:
    if col not in phase2_by_doc.columns:
        return {}
    docs = phase2_by_doc["document_id"].astype(str)
    series = pd.to_numeric(phase2_by_doc[col], errors="coerce").fillna(0.0)
    truth_mask = docs.isin(truth_docs)
    truth = series[truth_mask]
    normal = series[~truth_mask]
    return {
        "truth_doc_count": int(truth_mask.sum()),
        "normal_doc_count": int((~truth_mask).sum()),
        "truth_mean": float(truth.mean()) if len(truth) else 0.0,
        "normal_mean": float(normal.mean()) if len(normal) else 0.0,
        "truth_q95": float(np.quantile(truth, 0.95)) if len(truth) else 0.0,
        "normal_q95": float(np.quantile(normal, 0.95)) if len(normal) else 0.0,
    }


def _single_family_recall(
    phase2_by_doc: pd.DataFrame,
    truth_docs: set[str],
    col: str,
    top_ns: list[int],
) -> list[dict[str, Any]]:
    if col not in phase2_by_doc.columns:
        return []
    ranked = phase2_by_doc[["document_id", col]].copy()
    ranked[col] = pd.to_numeric(ranked[col], errors="coerce").fillna(0.0)
    ranked = ranked.sort_values(col, ascending=False, kind="mergesort")
    out: list[dict[str, Any]] = []
    for n in top_ns:
        top = ranked.head(n)
        matched = sum(1 for doc in top["document_id"].astype(str) if doc in truth_docs)
        out.append(
            {
                "top_n": int(n),
                "matched_truth_docs": int(matched),
                "recall": float(matched / max(len(truth_docs), 1)),
            }
        )
    return out


def _scenario_score_summary(
    phase2_by_doc: pd.DataFrame, truth: pd.DataFrame, family_col: str
) -> dict[str, dict[str, float]]:
    if family_col not in phase2_by_doc.columns:
        return {}
    truth_meta = truth.set_index(truth["document_id"].astype(str))
    score = phase2_by_doc[["document_id", family_col]].copy()
    score["document_id"] = score["document_id"].astype(str)
    score["fs"] = pd.to_numeric(score[family_col], errors="coerce").fillna(0.0)
    merged = score.merge(
        truth_meta[["manipulation_scenario"]],
        how="inner",
        left_on="document_id",
        right_index=True,
    )
    out: dict[str, dict[str, float]] = {}
    for scenario, grp in merged.groupby("manipulation_scenario", sort=False):
        out[str(scenario)] = {
            "truth_doc_count": int(len(grp)),
            "mean": float(grp["fs"].mean()),
            "q50": float(np.quantile(grp["fs"], 0.50)) if len(grp) else 0.0,
            "q90": float(np.quantile(grp["fs"], 0.90)) if len(grp) else 0.0,
            "q99": float(np.quantile(grp["fs"], 0.99)) if len(grp) else 0.0,
            "max": float(grp["fs"].max()),
            "nonzero_rate": float((grp["fs"] > 0).mean()),
        }
    return out


def _ic_top_threshold_split(
    phase2_by_doc: pd.DataFrame,
    truth_docs: set[str],
    col: str,
    thresholds: list[float],
) -> dict[str, Any]:
    if col not in phase2_by_doc.columns:
        return {}
    df = phase2_by_doc[["document_id", col]].copy()
    df["document_id"] = df["document_id"].astype(str)
    df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    df["is_truth"] = df["document_id"].isin(truth_docs)
    out: dict[str, Any] = {}
    for t in thresholds:
        above = df[df[col] >= t]
        out[f"ge_{t:.2f}"] = {
            "doc_count": int(len(above)),
            "truth_count": int(above["is_truth"].sum()),
            "normal_count": int((~above["is_truth"]).sum()),
        }
    return out


def main() -> int:
    t_start = time.perf_counter()

    print(f"[ic-refix] loading PKL: {FIXED5_PKL.relative_to(ROOT)}")
    with FIXED5_PKL.open("rb") as fh:
        data = pickle.load(fh)
    df = data["df"]
    detection_results = data["results"]
    print(f"[ic-refix]   df rows={len(df):,} results={len(detection_results)}")

    truth = pd.read_csv(FIXED5_TRUTH)
    truth["document_id"] = truth["document_id"].astype(str)
    truth_docs = set(truth["document_id"])
    print(f"[ic-refix]   truth docs={len(truth_docs):,}")

    if FIXED5_PHASE1_CACHE.exists():
        print(f"[ic-refix] loading phase1 case cache: {FIXED5_PHASE1_CACHE.relative_to(ROOT)}")
        with FIXED5_PHASE1_CACHE.open("rb") as fh:
            phase1_result = pickle.load(fh)
    else:
        print("[ic-refix] running PHASE1 case_builder ...")
        phase1_result = build_phase1_case_result(
            df,
            detection_results,
            company_id="_ci_baseline",
            batch_id="v7_fixed5_normalcal5_2026-05-25",
            dataset_id="datasynth_manipulation_v7_candidate_fixed5_normalcal5",
        )
        with FIXED5_PHASE1_CACHE.open("wb") as fh:
            pickle.dump(phase1_result, fh, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"[ic-refix]   phase1 cases={len(phase1_result.cases):,}")

    print("[ic-refix] scoring PHASE2 5 families on full df (no cache) ...")
    t_p2 = time.perf_counter()
    phase2_by_doc = stage7.score_phase2_families_by_document(df)
    print(
        f"[ic-refix]   phase2 scored docs={len(phase2_by_doc):,}  "
        f"elapsed={time.perf_counter() - t_p2:.1f}s"
    )
    OUT_PHASE2_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    phase2_by_doc.to_parquet(OUT_PHASE2_PARQUET, index=False)
    print(f"[ic-refix]   wrote {OUT_PHASE2_PARQUET.relative_to(ROOT)}")

    family_score_cols = {
        "unsupervised": "phase2_unsupervised_score_max",
        "timeseries": "phase2_timeseries_score_max",
        "relational": "phase2_relational_score_max",
        "duplicate": "phase2_duplicate_score_max",
        "intercompany": "phase2_intercompany_score_max",
    }
    family_distribution: dict[str, dict[str, Any]] = {}
    family_truth_split: dict[str, dict[str, Any]] = {}
    raw_document_family_recall: dict[str, list[dict[str, Any]]] = {}
    for fam, col in family_score_cols.items():
        if col in phase2_by_doc.columns:
            family_distribution[fam] = _distribution_summary(phase2_by_doc[col])
            family_truth_split[fam] = _truth_split_distribution(phase2_by_doc, truth_docs, col)
            raw_document_family_recall[fam] = _single_family_recall(
                phase2_by_doc, truth_docs, col, TOP_NS
            )

    print("[ic-refix] building base review queue rows ...")
    overlays: list[dict[str, Any]] = []
    base_df = stage7._build_base_rows(phase1_result, phase2_by_doc, overlays, truth_docs)
    family_single = stage7.measure_phase2_family_single_recall(base_df, truth_docs, TOP_NS)
    queue_phase1 = stage7.build_phase1_queue(base_df)
    queue_phase2 = stage7.build_phase2_queue(base_df)
    queue_integrated = stage7.build_integrated_queue(base_df, k=stage7.RRF_K)

    doc_recall_by_queue: dict[str, list[dict[str, Any]]] = {
        "phase1": [stage7.measure_doc_recall(queue_phase1, truth_docs, n) for n in TOP_NS],
        "phase2": [stage7.measure_doc_recall(queue_phase2, truth_docs, n) for n in TOP_NS],
        "integrated": [stage7.measure_doc_recall(queue_integrated, truth_docs, n) for n in TOP_NS],
    }
    family_rank_distribution = stage7.summarize_family_rank_distribution(queue_integrated)

    top100 = queue_phase2.head(100)
    intercompany_dominant_top100 = 0
    timeseries_dominant_top100 = 0
    family_col = (
        "primary_family"
        if "primary_family" in top100.columns
        else "top_family"
        if "top_family" in top100.columns
        else None
    )
    if family_col is not None:
        intercompany_dominant_top100 = int((top100[family_col] == "intercompany").sum())
        timeseries_dominant_top100 = int((top100[family_col] == "timeseries").sum())

    scenario_summary = _scenario_score_summary(
        phase2_by_doc, truth, "phase2_intercompany_score_max"
    )

    ic_top_split = _ic_top_threshold_split(
        phase2_by_doc,
        truth_docs,
        "phase2_intercompany_score_max",
        thresholds=[0.99, 0.90, 0.70, 0.50],
    )

    # circular_related_party_transaction 34건 IC score 분포
    circ_docs = set(
        truth[truth["manipulation_scenario"] == "circular_related_party_transaction"]["document_id"]
        .astype(str)
        .unique()
    )
    circ_series = phase2_by_doc[phase2_by_doc["document_id"].astype(str).isin(circ_docs)][
        "phase2_intercompany_score_max"
    ]
    circ_series = pd.to_numeric(circ_series, errors="coerce").fillna(0.0)
    circular_truth_summary = {
        "truth_count": int(len(circ_docs)),
        "matched_in_parquet": int(len(circ_series)),
        "mean": float(circ_series.mean()) if len(circ_series) else 0.0,
        "q50": float(np.quantile(circ_series, 0.50)) if len(circ_series) else 0.0,
        "q90": float(np.quantile(circ_series, 0.90)) if len(circ_series) else 0.0,
        "q99": float(np.quantile(circ_series, 0.99)) if len(circ_series) else 0.0,
        "max": float(circ_series.max()) if len(circ_series) else 0.0,
        "nonzero_count": int((circ_series > 0).sum()),
    }

    # score=1.0 bucket 분포 (acceptance: 수천 개로 생기면 실패)
    ic_series = pd.to_numeric(
        phase2_by_doc["phase2_intercompany_score_max"], errors="coerce"
    ).fillna(0.0)
    tie_buckets = ic_series.round(4).value_counts().head(20).to_dict()

    report = {
        "dataset_version": "datasynth_manipulation_v7_candidate_fixed5_normalcal5",
        "fix_label": "ic_timing_domain_split_20260525",
        "elapsed_sec": round(time.perf_counter() - t_start, 2),
        "phase1_cases": len(phase1_result.cases),
        "phase2_scored_docs": int(len(phase2_by_doc)),
        "total_truth_docs": len(truth_docs),
        "rrf_k": int(stage7.RRF_K),
        "family_distribution": family_distribution,
        "family_truth_split": family_truth_split,
        "family_single": family_single,
        "family_single_measurement_contract": (
            "canonical case-level queue: sort base_df by "
            "[phase2_<family>_score_max, total_amount, rule_count], then "
            "measure_doc_recall(document_ids_joined). Matches fixed5 baseline "
            "family_single[*].phase2."
        ),
        "raw_document_family_recall_deprecated": raw_document_family_recall,
        "doc_recall_by_queue": doc_recall_by_queue,
        "family_rank_distribution": family_rank_distribution,
        "scenario_intercompany_score_summary": scenario_summary,
        "intercompany_dominant_top100_phase2": intercompany_dominant_top100,
        "timeseries_dominant_top100_phase2": timeseries_dominant_top100,
        "ic_top_threshold_split": ic_top_split,
        "circular_truth_intercompany_summary": circular_truth_summary,
        "ic_score_tie_buckets_top20": tie_buckets,
        "baseline_reference": {
            "integration_report": BASELINE_REPORT,
            "phase2_family_by_doc": BASELINE_PARQUET,
            "previous_design_fix_parquet": PREV_DESIGN_FIX_PARQUET,
        },
        "verification_principles": [
            "fixed5 truth recall은 사후 보고만, threshold/grace 튜닝에 사용 금지",
            "기존 fixed4/fixed5 PHASE2 parquet cache 사용 금지 (full rerun)",
            "phase2_subdetector_tiers.yaml 변경 없음",
            "IC01/IC02/IC03 + reciprocal_flow + RuleFlag/sidecar 보존",
            "timing_prob 의 grace/cap 임계값은 audit evidence semantics 기준",
            "Phase1 결과 / synthetic label 입력 미사용",
        ],
    }
    OUT_REPORT_JSON.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(f"[ic-refix] wrote {OUT_REPORT_JSON.relative_to(ROOT)}")

    print("\n[ic-refix] intercompany family distribution")
    if "intercompany" in family_distribution:
        for key, value in family_distribution["intercompany"].items():
            print(f"  {key}: {value}")
    print("\n[ic-refix] intercompany single-family TOP recall")
    for top_n, item in family_single.get("intercompany", {}).get("phase2", {}).items():
        print(
            f"  TOP {int(top_n):>6}  matched {int(item['matched']):>4}  "
            f"recall {item['recall']:.4f}"
        )
    for queue_name, recalls in doc_recall_by_queue.items():
        print(f"\n[ic-refix] {queue_name} queue")
        for item in recalls:
            print(
                f"  TOP {item['top_n']:>6}  matched {item['matched_truth_docs']:>4}  "
                f"recall {item['recall']:.4f}"
            )
    print(
        "\n[ic-refix] Noisy-OR PHASE2 TOP100 intercompany-dominant = "
        f"{intercompany_dominant_top100}"
    )
    print(f"[ic-refix] circular truth (34) intercompany summary: {circular_truth_summary}")
    print(f"[ic-refix] ic_top threshold split: {ic_top_split}")
    print(f"[ic-refix] tie buckets (top20): {tie_buckets}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
