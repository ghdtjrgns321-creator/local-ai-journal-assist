"""Stage7 재측정 — TS 3-axis composite redesign 효과를 fixed5_normalcal5 PKL 로 측정.

cache 무시 fresh rerun. truth label 기준 threshold 재튜닝은 하지 않으며 결과는 사후
검증으로만 사용한다. 변경 대상:
  - src/detection/timeseries_rules.py
      after_hours_or_weekend_score / manual_or_adjustment_score / round_amount_score
      account_process_rarity_score / user_account_rarity_score / partner_account_rarity_score
      composite_temporal_anomaly (3-axis evidence_count 결합식)
  - src/detection/timeseries_detector.py _compute_sub_signals + _build_result row_score 결합
  - config/settings.py ts_composite_* 신규 키
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
OUT_PHASE2_PARQUET = OUT_DIR / "stage7_fixed5_ts_redesign_20260524_phase2_family_by_doc.parquet"
OUT_REPORT_JSON = OUT_DIR / "stage7_fixed5_ts_redesign_20260524_report.json"

TOP_NS = [100, 500, 1000, 2000, 5000, 10000]


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
) -> dict[str, dict[str, float]]:
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
        "truth_ge_normal_q95_count": int((truth >= np.quantile(normal, 0.95)).sum())
        if len(normal) and len(truth)
        else 0,
        "truth_ge_normal_q99_count": int((truth >= np.quantile(normal, 0.99)).sum())
        if len(normal) and len(truth)
        else 0,
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
    phase2_by_doc: pd.DataFrame, truth: pd.DataFrame
) -> dict[str, dict[str, float]]:
    if "phase2_timeseries_score_max" not in phase2_by_doc.columns:
        return {}
    truth_meta = truth.set_index(truth["document_id"].astype(str))
    score = phase2_by_doc[["document_id", "phase2_timeseries_score_max"]].copy()
    score["document_id"] = score["document_id"].astype(str)
    score["ts"] = pd.to_numeric(score["phase2_timeseries_score_max"], errors="coerce").fillna(0.0)
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
            "ts_mean": float(grp["ts"].mean()),
            "ts_q95": float(np.quantile(grp["ts"], 0.95)) if len(grp) else 0.0,
            "ts_q99": float(np.quantile(grp["ts"], 0.99)) if len(grp) else 0.0,
            "ts_max": float(grp["ts"].max()),
            "ts_nonzero_rate": float((grp["ts"] > 0).mean()),
        }
    return out


def main() -> int:
    t_start = time.perf_counter()

    print(f"[ts-redesign] loading PKL: {FIXED5_PKL.relative_to(ROOT)}")
    with FIXED5_PKL.open("rb") as fh:
        data = pickle.load(fh)
    df = data["df"]
    detection_results = data["results"]
    print(f"[ts-redesign]   df rows={len(df):,} results={len(detection_results)}")

    truth = pd.read_csv(FIXED5_TRUTH)
    truth["document_id"] = truth["document_id"].astype(str)
    truth_docs = set(truth["document_id"])
    print(f"[ts-redesign]   truth docs={len(truth_docs):,}")

    if FIXED5_PHASE1_CACHE.exists():
        print(f"[ts-redesign] loading phase1 case cache: {FIXED5_PHASE1_CACHE.relative_to(ROOT)}")
        with FIXED5_PHASE1_CACHE.open("rb") as fh:
            phase1_result = pickle.load(fh)
    else:
        print("[ts-redesign] running PHASE1 case_builder ...")
        phase1_result = build_phase1_case_result(
            df,
            detection_results,
            company_id="_ci_baseline",
            batch_id="v7_fixed5_normalcal5_2026-05-24",
            dataset_id="datasynth_manipulation_v7_candidate_fixed5_normalcal5",
        )
        with FIXED5_PHASE1_CACHE.open("wb") as fh:
            pickle.dump(phase1_result, fh, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"[ts-redesign]   phase1 cases={len(phase1_result.cases):,}")

    print("[ts-redesign] scoring PHASE2 5 families on full df (no cache) ...")
    t_p2 = time.perf_counter()
    phase2_by_doc = stage7.score_phase2_families_by_document(df)
    print(
        f"[ts-redesign]   phase2 scored docs={len(phase2_by_doc):,}  "
        f"elapsed={time.perf_counter() - t_p2:.1f}s"
    )
    OUT_PHASE2_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    phase2_by_doc.to_parquet(OUT_PHASE2_PARQUET, index=False)
    print(f"[ts-redesign]   wrote {OUT_PHASE2_PARQUET.relative_to(ROOT)}")

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

    print("[ts-redesign] building base review queue rows ...")
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
    timeseries_dominant_top100 = 0
    if "primary_family" in top100.columns:
        timeseries_dominant_top100 = int((top100["primary_family"] == "timeseries").sum())
    elif "top_family" in top100.columns:
        timeseries_dominant_top100 = int((top100["top_family"] == "timeseries").sum())

    scenario_summary = _scenario_score_summary(phase2_by_doc, truth)

    report = {
        "dataset_version": "datasynth_manipulation_v7_candidate_fixed5_normalcal5",
        "fix_label": "ts_3axis_composite_redesign_20260524",
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
        "scenario_ts_score_summary": scenario_summary,
        "timeseries_dominant_top100_phase2": timeseries_dominant_top100,
        "baseline_references": {
            "before_evidence_role_split": (
                "artifacts/phase1_phase2_integration_fixed5_normalcal5_20260524.json"
            ),
            "after_evidence_role_split_only": (
                "artifacts/stage7_fixed5_ts_design_fix_20260524_report.json"
            ),
            "diagnosis": "artifacts/timeseries_redesign_diagnosis_20260524.md",
        },
        "verification_principles": [
            "fixed5 truth recall은 사후 보고만, threshold 튜닝에 사용 금지",
            "phase2_subdetector_tiers.yaml tier 변경 없음 (TS01 moderate / TS02 weak 유지)",
            "TS01/TS02 rule_id 유지, TS03 추가 없음",
            "Phase1 columns (flagged_rules 등) / synthetic labels (mutation_* 등) 입력 미사용",
            "amount_tail / rarity / context 단독 row_score high 금지 (composite gate 통과 시만)",
            "UI 변경 없음 (dashboard/** 미수정)",
        ],
    }
    OUT_REPORT_JSON.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(f"[ts-redesign] wrote {OUT_REPORT_JSON.relative_to(ROOT)}")

    print("\n[ts-redesign] timeseries family distribution")
    if "timeseries" in family_distribution:
        for key, value in family_distribution["timeseries"].items():
            print(f"  {key}: {value}")
    print("\n[ts-redesign] timeseries truth split")
    if "timeseries" in family_truth_split:
        for key, value in family_truth_split["timeseries"].items():
            print(f"  {key}: {value}")
    print("\n[ts-redesign] timeseries single-family TOP recall")
    for top_n, item in family_single.get("timeseries", {}).get("phase2", {}).items():
        print(
            f"  TOP {int(top_n):>6}  matched {int(item['matched']):>4}  "
            f"recall {item['recall']:.4f}"
        )
    for queue_name, recalls in doc_recall_by_queue.items():
        print(f"\n[ts-redesign] {queue_name}")
        for item in recalls:
            print(
                f"  TOP {item['top_n']:>6}  matched {item['matched_truth_docs']:>4}  "
                f"recall {item['recall']:.4f}"
            )
    print(
        f"\n[ts-redesign] Noisy-OR PHASE2 TOP100 timeseries-dominant = {timeseries_dominant_top100}"
    )
    print("\n[ts-redesign] scenario ts score summary")
    for sc, stats in scenario_summary.items():
        print(
            f"  {sc:>45}  truth_n={stats['truth_doc_count']:>4}  mean={stats['ts_mean']:.4f}  "
            f"q95={stats['ts_q95']:.4f}  max={stats['ts_max']:.4f}  "
            f"nonzero_rate={stats['ts_nonzero_rate']:.4f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
