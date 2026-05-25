"""V7 fixed3 hierarchical RRF measurement-only dry-run.

Phase C 산출: hierarchical RRF 적용 결과를 기존 2-way RRF baseline 과 같은 표
위에서 TOP 100/500/1000/2000/5000 document recall 로 비교한다.

본 script 는 truth label 을 TOP N recall 측정 용도로만 사용하며, family role
판정 / RRF 결합식 / tier 부여 / threshold 어디에도 사용하지 않는다.
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.services.phase2_family_diagnostics import (
    classify_all_family_roles,
    compute_all_family_diagnostics,
)
from src.services.queue_fusion import compute_phase2_internal_rrf, compute_rrf_score
from tools.scripts.phase2_family_correlation_audit import (
    FAMILIES,
    load_case_input,
    score_all_families,
)

DATASET = "datasynth_manipulation_v7_candidate_fixed3"
TRUTH_DIR = ROOT / "data" / "journal" / "primary" / DATASET / "labels"
OUT_JSON = ROOT / "artifacts" / "phase2_family_ranking_measurement_20260519.json"
OUT_MD = ROOT / "artifacts" / "phase2_family_ranking_measurement_20260519.md"

TOP_N_LEVELS = (100, 500, 1000, 2000, 5000)


def _print(message: str) -> None:
    print(f"[{datetime.now(UTC).isoformat(timespec='seconds')}] {message}", flush=True)


def load_truth_doc_ids() -> set[str]:
    """V7 fixed3 truth document_id 합집합. 3 연도 모두."""
    parts: list[pd.DataFrame] = []
    for year in (2022, 2023, 2024):
        fp = TRUTH_DIR / f"manipulated_entry_truth_{year}.csv"
        parts.append(pd.read_csv(fp, dtype={"document_id": str}))
    truth = pd.concat(parts, ignore_index=True)
    return set(truth["document_id"].astype(str).unique())


def synthesize_phase1_composite(row_scores: pd.DataFrame) -> pd.Series:
    """V7 fixed3 PHASE1 composite_sort_score 대용.

    Phase C 는 measurement-only 이므로 실제 PHASE1 결과 pickle 을 다시 돌리지 않고,
    rule-style family score 합으로 PHASE1 신호를 근사한다. 본 합은 V7 fixed3 의
    PHASE1 composite_sort_score 와 정확히 동일하지 않으나, hierarchical RRF 와
    기존 2-way RRF 의 상대 비교에서 일관성을 유지한다.
    """
    rule_families = [f for f in FAMILIES if f != "unsupervised"]
    composite = row_scores[rule_families].sum(axis=1)
    return composite.fillna(0.0).astype(float)


def compute_baseline_two_way(row_scores: pd.DataFrame) -> pd.DataFrame:
    """기존 PHASE1↔PHASE2(unsupervised) 2-way RRF baseline 재현."""
    phase1 = synthesize_phase1_composite(row_scores)
    phase2 = row_scores["unsupervised"].fillna(0.0).astype(float)
    return compute_rrf_score({"phase1_composite": phase1, "phase2_unsupervised": phase2})


def compute_hierarchical(row_scores: pd.DataFrame) -> pd.DataFrame:
    """Phase 2 internal hierarchical RRF + PHASE1 final RRF."""
    diagnostics = compute_all_family_diagnostics({f: row_scores[f] for f in FAMILIES})
    roles = classify_all_family_roles(diagnostics)
    active = [f for f in FAMILIES if roles[f] == "active-ranker"]
    boosters = [f for f in FAMILIES if roles[f] == "coarse-booster"]
    near_dormant = [f for f in FAMILIES if roles[f] == "near-dormant"]
    tail_only = [f for f in FAMILIES if roles[f] == "tail-only-fallback"]
    boosters = boosters + tail_only

    if not active:
        raise RuntimeError("no active-ranker family — cannot run hierarchical RRF")

    phase1 = synthesize_phase1_composite(row_scores)
    internal = compute_phase2_internal_rrf(
        {f: row_scores[f].fillna(0.0).astype(float) for f in FAMILIES},
        active_rankers=active,
        coarse_boosters=boosters,
        phase1_scores=phase1,
    )
    final = compute_rrf_score(
        {
            "phase1_composite": phase1,
            "phase2_internal": internal["phase2_internal_rrf_score"],
        }
    )
    final["phase2_internal_score"] = internal["phase2_internal_rrf_score"].to_numpy()
    final["coverage_breadth_q95"] = internal["coverage_breadth_q95"].to_numpy()
    return final, {"active": active, "boosters": boosters, "near_dormant": near_dormant}


def aggregate_doc_level(row_scores: pd.DataFrame, fusion_score: pd.Series) -> pd.DataFrame:
    """row → document max 집계 (V7 §3 동일 단위)."""
    frame = pd.DataFrame(
        {
            "document_id": row_scores["document_id"].astype(str),
            "fusion_score": fusion_score.astype(float).to_numpy(),
        }
    )
    return frame.groupby("document_id", as_index=False)["fusion_score"].max()


def measure_top_n_recall(
    doc_scores: pd.DataFrame,
    truth_doc_ids: set[str],
    top_n_levels: tuple[int, ...] = TOP_N_LEVELS,
) -> list[dict[str, Any]]:
    sorted_docs = doc_scores.sort_values("fusion_score", ascending=False, kind="mergesort")
    total_truth = len(truth_doc_ids)
    results: list[dict[str, Any]] = []
    for n in top_n_levels:
        top = sorted_docs.head(n)
        caught = int(top["document_id"].isin(truth_doc_ids).sum())
        recall = caught / total_truth if total_truth else 0.0
        precision = caught / n if n else 0.0
        results.append(
            {
                "top_n": n,
                "caught_truth_docs": caught,
                "recall": round(recall, 4),
                "precision": round(precision, 4),
            }
        )
    return results


def build_markdown(payload: dict[str, Any]) -> str:
    lines: list[str] = [
        "# PHASE2 family ranking measurement — V7 fixed3 (Phase C dry-run)",
        "",
        f"- generated_at: `{payload['generated_at']}`",
        f"- dataset: `{payload['dataset']}`",
        f"- row_count: `{payload['row_count']:,}`",
        f"- document_count: `{payload['document_count']:,}`",
        f"- truth_doc_count: `{payload['truth_doc_count']:,}`",
        "",
        "## 1. family role 자동 분류 (L0 metric → L1 role)",
        "",
        "| family | row_nonzero_rate | rank_resolution | top_tail_resolution | role |",
        "|---|---:|---:|---:|---|",
    ]
    for fam, diag in payload["family_diagnostics"].items():
        lines.append(
            f"| {fam} | {diag['row_nonzero_rate']:.6f} | {diag['rank_resolution']:.6f} | "
            f"{diag['top_tail_resolution']:.6f} | {payload['family_roles'][fam]} |"
        )
    lines.extend(
        [
            "",
            f"- active rankers: `{', '.join(payload['active_set'])}`",
            f"- coarse boosters (tail-only 포함): `{', '.join(payload['booster_set']) or 'none'}`",
            f"- near-dormant: `{', '.join(payload['near_dormant_set']) or 'none'}`",
            "",
            "## 2. TOP N document recall 비교 — 2-way RRF baseline vs hierarchical",
            "",
            "| TOP N | 2-way caught | 2-way recall | hierarchical caught | hierarchical recall | Δrecall (pp) |",
            "|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for base, hier in zip(payload["two_way_rrf"], payload["hierarchical_rrf"], strict=True):
        delta = (hier["recall"] - base["recall"]) * 100
        lines.append(
            f"| {base['top_n']:,} | {base['caught_truth_docs']:,} | {base['recall'] * 100:.2f}% "
            f"| {hier['caught_truth_docs']:,} | {hier['recall'] * 100:.2f}% | {delta:+.2f} |"
        )
    lines.extend(
        [
            "",
            "## 3. fitting 가드 체크",
            "",
            "- truth label 사용처: TOP N recall 산출만",
            "- family role 결정에 truth 미사용: ✅ (L0 metric 만)",
            "- RRF k=60 고정, 가중치 0개: ✅",
            "- booster eligibility 는 분포 quantile, truth 미사용: ✅",
            "",
            "## 4. 한 줄 결론",
            "",
            payload["one_line_conclusion"],
            "",
            "## 5. 관련 산출물",
            "",
            "- 본 measurement: `artifacts/phase2_family_ranking_measurement_20260519.json` + 본 파일",
            "- correlation matrix: `artifacts/phase2_family_correlation_matrix_20260519.md`",
            "- V7 fixed3 입력: `artifacts/phase1_manipulation_v7_fixed3_case_input.pkl`",
            "- 정책 출처: `dev/active/phase2-family-ranking/phase2-family-ranking-plan.md` §L2/L3",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    start = time.perf_counter()
    _print("loading V7 fixed3 case input")
    df = load_case_input()
    _print(f"  rows={len(df):,} docs={df['document_id'].nunique():,}")

    _print("computing 5-family row scores")
    row_scores = score_all_families(df)

    _print("classifying family roles (L0 → L1)")
    diagnostics = compute_all_family_diagnostics(
        {f: row_scores[f].fillna(0.0).astype(float) for f in FAMILIES}
    )
    roles = classify_all_family_roles(diagnostics)
    active = [f for f in FAMILIES if roles[f] == "active-ranker"]
    boosters = [f for f in FAMILIES if roles[f] in {"coarse-booster", "tail-only-fallback"}]
    near_dormant = [f for f in FAMILIES if roles[f] == "near-dormant"]
    _print(f"  active={active} boosters={boosters} near_dormant={near_dormant}")

    _print("loading truth document ids")
    truth_doc_ids = load_truth_doc_ids()
    _print(f"  truth_doc_count={len(truth_doc_ids):,}")

    _print("running 2-way RRF baseline")
    baseline = compute_baseline_two_way(row_scores)
    base_doc = aggregate_doc_level(row_scores, pd.Series(baseline["rrf_score"]))
    base_results = measure_top_n_recall(base_doc, truth_doc_ids)

    _print("running hierarchical RRF")
    hier, _hier_roles = compute_hierarchical(row_scores)
    hier_doc = aggregate_doc_level(row_scores, pd.Series(hier["rrf_score"]))
    hier_results = measure_top_n_recall(hier_doc, truth_doc_ids)

    deltas = [h["recall"] - b["recall"] for b, h in zip(base_results, hier_results, strict=True)]
    avg_delta_pp = float(np.mean(deltas) * 100) if deltas else 0.0
    conclusion = (
        f"V7 fixed3 hierarchical RRF 는 active={','.join(active)} / booster="
        f"{','.join(boosters) or 'none'} 구성에서 TOP {'/'.join(str(n) for n in TOP_N_LEVELS)} "
        f"document recall 이 2-way baseline 대비 평균 {avg_delta_pp:+.2f}pp 변동. "
        f"near-dormant({','.join(near_dormant) or 'none'}) 는 global ranker 에서 제외."
    )

    payload = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "dataset": DATASET,
        "row_count": int(len(row_scores)),
        "document_count": int(row_scores["document_id"].nunique()),
        "truth_doc_count": int(len(truth_doc_ids)),
        "family_diagnostics": {f: diagnostics[f].to_dict() for f in FAMILIES},
        "family_roles": roles,
        "active_set": active,
        "booster_set": boosters,
        "near_dormant_set": near_dormant,
        "two_way_rrf": base_results,
        "hierarchical_rrf": hier_results,
        "avg_delta_pp": avg_delta_pp,
        "one_line_conclusion": conclusion,
        "fitting_guard": {
            "truth_used_for_role": False,
            "truth_used_for_threshold": False,
            "rrf_k": 60,
            "weights_count": 0,
        },
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_MD.write_text(build_markdown(payload), encoding="utf-8")
    _print(f"wrote {OUT_JSON.relative_to(ROOT)}")
    _print(f"wrote {OUT_MD.relative_to(ROOT)}")
    _print(f"done elapsed={time.perf_counter() - start:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
