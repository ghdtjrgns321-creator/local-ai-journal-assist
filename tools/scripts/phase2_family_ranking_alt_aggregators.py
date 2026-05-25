"""V7 fixed3 alt-aggregator measurement — RRF 외 결합식 비교.

8 결합식 × 분리/통합 적용 2 방식 + baseline 2 = 18 측정.
TOP 100/500/1000/2000/5000 document recall 산출.

본 script 는 truth label 을 TOP N recall 산출에만 사용한다. 결합식·tier_weight·
임계값 어디에도 truth 미사용.

설계 출처: dev/active/phase2-family-ranking/phase2-family-ranking-plan.md
거버넌스: docs/PHASE2_GOVERNANCE_DESIGN.md 결정 8 (재평가 입력)
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.services.queue_fusion import compute_rrf_score
from tools.scripts.phase2_family_correlation_audit import (
    FAMILIES,
    load_case_input,
    score_all_families,
)
from tools.scripts.phase2_family_ranking_dry_run import (
    load_truth_doc_ids,
    synthesize_phase1_composite,
)

OUT_JSON = ROOT / "artifacts" / "phase2_family_ranking_alt_aggregators_20260519.json"
OUT_MD = ROOT / "artifacts" / "phase2_family_ranking_alt_aggregators_20260519.md"
TOP_N_LEVELS = (100, 500, 1000, 2000, 5000)

# family + PHASE1 의 tier_weight — measurement 시 자명한 strong/moderate 매핑
# (governance lock 후보. config/phase2_subdetector_tiers.yaml 의 family 별 max
# sub-detector tier 와 정합. unsupervised 의 ml_quantile 은 V7 §3 AUROC 0.93
# 검증으로 strong 동치로 매핑.)
FAMILY_TIER_WEIGHTS: dict[str, float] = {
    "unsupervised": 3.0,
    "duplicate": 3.0,
    "relational": 3.0,
    "timeseries": 2.0,
    "intercompany": 3.0,
}
PHASE1_TIER_WEIGHT = 3.0
CASCADE_ANCHOR = "unsupervised"


def _print(message: str) -> None:
    print(f"[{datetime.now(UTC).isoformat(timespec='seconds')}] {message}", flush=True)


# ──────────────────────────────────────────────────────────────────────────────
# ECDF / rank 변환
# ──────────────────────────────────────────────────────────────────────────────


def to_ecdf(scores: pd.Series) -> pd.Series:
    """row-level ECDF 변환 — batch 분포 기준 rank percentile."""
    return scores.fillna(0.0).astype(float).rank(method="average", pct=True)


def to_rank(scores: pd.Series) -> pd.Series:
    """desc rank (rank 1 = 최고 점수). RRF / rank_product 에 사용."""
    return scores.fillna(0.0).astype(float).rank(method="min", ascending=False)


# ──────────────────────────────────────────────────────────────────────────────
# 8 결합식
# ──────────────────────────────────────────────────────────────────────────────


def agg_max(sources: dict[str, pd.Series]) -> pd.Series:
    return pd.concat(sources.values(), axis=1).max(axis=1)


def agg_tier_weighted_sum(
    sources: dict[str, pd.Series],
    weights: dict[str, float],
) -> pd.Series:
    base = next(iter(sources.values()))
    out = pd.Series(0.0, index=base.index, dtype=float)
    for name, series in sources.items():
        out = out + series.astype(float) * float(weights.get(name, 1.0))
    return out


def agg_cascade_boost(
    sources: dict[str, pd.Series],
    anchor: str,
    weights: dict[str, float],
    q: float = 0.95,
) -> pd.Series:
    if anchor not in sources:
        raise ValueError(f"cascade anchor {anchor} not in sources")
    base = sources[anchor].astype(float).copy()
    for name, series in sources.items():
        if name == anchor:
            continue
        threshold = float(series.quantile(q))
        if threshold <= 0:
            entered = (series > 0).astype(float)
        else:
            entered = (series >= threshold).astype(float)
        base = base + entered * float(weights.get(name, 1.0))
    return base


def agg_evidence_vote(sources: dict[str, pd.Series]) -> pd.Series:
    base = next(iter(sources.values()))
    out = pd.Series(0.0, index=base.index, dtype=float)
    for series in sources.values():
        q95 = float(series.quantile(0.95))
        q99 = float(series.quantile(0.99))
        vote95 = (series >= q95).astype(float) if q95 > 0 else (series > 0).astype(float)
        vote99 = (series >= q99).astype(float) if q99 > 0 else pd.Series(0.0, index=base.index)
        out = out + vote95 + vote99
    return out


def agg_noisy_or(sources: dict[str, pd.Series]) -> pd.Series:
    base = next(iter(sources.values()))
    survival = pd.Series(1.0, index=base.index, dtype=float)
    for series in sources.values():
        clipped = series.clip(0, 1).astype(float)
        survival = survival * (1.0 - clipped)
    return 1.0 - survival


def agg_rank_product(sources: dict[str, pd.Series]) -> pd.Series:
    base = next(iter(sources.values()))
    n = max(len(base), 1)
    log_sum = pd.Series(0.0, index=base.index, dtype=float)
    families = len(sources)
    for series in sources.values():
        rank = to_rank(series)
        log_sum = log_sum + np.log(rank.clip(lower=1) / n)
    return -(log_sum / families)


def agg_geometric_mean(sources: dict[str, pd.Series], epsilon: float = 1e-6) -> pd.Series:
    base = next(iter(sources.values()))
    log_sum = pd.Series(0.0, index=base.index, dtype=float)
    families = len(sources)
    for series in sources.values():
        log_sum = log_sum + np.log(series.clip(lower=epsilon, upper=1.0))
    return np.exp(log_sum / families)


def agg_top_k_mean(sources: dict[str, pd.Series], k: int = 3) -> pd.Series:
    frame = pd.concat(sources.values(), axis=1).fillna(0.0).astype(float)
    arr = frame.to_numpy()
    if arr.shape[1] == 0:
        return pd.Series(0.0, index=frame.index)
    sorted_arr = np.sort(arr, axis=1)
    k_eff = min(k, sorted_arr.shape[1])
    top_k = sorted_arr[:, -k_eff:]
    return pd.Series(top_k.mean(axis=1), index=frame.index)


# ──────────────────────────────────────────────────────────────────────────────
# 적용 방식: 분리 vs 통합
# ──────────────────────────────────────────────────────────────────────────────


def apply_phase2_only(
    family_ecdfs: dict[str, pd.Series],
    aggregator: Callable[[dict[str, pd.Series]], pd.Series],
) -> pd.Series:
    """PHASE2 internal 단독: 5 family 결합 결과 그대로 (PHASE1 미포함)."""
    return aggregator(family_ecdfs)


def apply_separated(
    phase1_score: pd.Series,
    family_ecdfs: dict[str, pd.Series],
    aggregator: Callable[[dict[str, pd.Series]], pd.Series],
) -> pd.Series:
    """분리 적용: PHASE2 internal 결합 → PHASE1 과 2-way RRF k=60."""
    phase2_internal = aggregator(family_ecdfs)
    rrf = compute_rrf_score(
        {
            "phase1": phase1_score.astype(np.float64),
            "phase2_internal": phase2_internal.astype(np.float64),
        }
    )
    return pd.Series(rrf["rrf_score"], index=phase1_score.index, dtype=float)


def apply_unified(
    phase1_ecdf: pd.Series,
    family_ecdfs: dict[str, pd.Series],
    aggregator: Callable[[dict[str, pd.Series]], pd.Series],
) -> pd.Series:
    """통합 적용: PHASE1 + 5 family 6 source 에 결합식 직접 적용."""
    sources: dict[str, pd.Series] = {"phase1": phase1_ecdf, **family_ecdfs}
    return aggregator(sources)


# ──────────────────────────────────────────────────────────────────────────────
# 측정
# ──────────────────────────────────────────────────────────────────────────────


def measure_top_n_recall(
    doc_scores: pd.DataFrame,
    truth_doc_ids: set[str],
) -> list[dict[str, Any]]:
    sorted_docs = doc_scores.sort_values("fusion_score", ascending=False, kind="mergesort")
    total_truth = len(truth_doc_ids)
    results: list[dict[str, Any]] = []
    for n in TOP_N_LEVELS:
        top = sorted_docs.head(n)
        caught = int(top["document_id"].isin(truth_doc_ids).sum())
        recall = caught / total_truth if total_truth else 0.0
        results.append({"top_n": n, "caught": caught, "recall": round(recall, 6)})
    return results


def aggregate_doc_level(row_scores: pd.DataFrame, fusion_score: pd.Series) -> pd.DataFrame:
    return (
        pd.DataFrame(
            {
                "document_id": row_scores["document_id"].astype(str),
                "fusion_score": fusion_score.astype(float).to_numpy(),
            }
        )
        .groupby("document_id", as_index=False)["fusion_score"]
        .max()
    )


def make_aggregator_callable(
    name: str,
    family_tier_weights: dict[str, float],
    phase1_tier_weight: float,
    cascade_anchor: str,
    unified: bool,
) -> Callable[[dict[str, pd.Series]], pd.Series]:
    """결합식 이름 → callable (적용 모드 인지)."""
    weights_for_unified = {"phase1": phase1_tier_weight, **family_tier_weights}
    weights_for_separated = family_tier_weights

    if name == "max":
        return agg_max
    if name == "tier_weighted_sum":
        weights = weights_for_unified if unified else weights_for_separated
        return lambda sources: agg_tier_weighted_sum(sources, weights)
    if name == "cascade_boost":
        weights = weights_for_unified if unified else weights_for_separated
        # 통합 적용 시 anchor 는 여전히 unsupervised — PHASE1 도 boost 대상으로 들어옴
        return lambda sources: agg_cascade_boost(sources, cascade_anchor, weights, q=0.95)
    if name == "evidence_vote":
        return agg_evidence_vote
    if name == "noisy_or":
        return agg_noisy_or
    if name == "rank_product":
        return agg_rank_product
    if name == "geometric_mean":
        return agg_geometric_mean
    if name == "top_k_mean":
        return agg_top_k_mean
    raise ValueError(f"unknown aggregator {name}")


AGGREGATORS: tuple[str, ...] = (
    "max",
    "tier_weighted_sum",
    "cascade_boost",
    "evidence_vote",
    "noisy_or",
    "rank_product",
    "geometric_mean",
    "top_k_mean",
)


def main() -> int:
    start = time.perf_counter()
    _print("loading V7 fixed3 case input")
    df = load_case_input()
    _print(f"  rows={len(df):,} docs={df['document_id'].nunique():,}")

    _print("computing 5-family row scores")
    row_scores = score_all_families(df)
    family_raw = {f: row_scores[f].fillna(0.0).astype(float) for f in FAMILIES}
    family_ecdfs = {f: to_ecdf(series) for f, series in family_raw.items()}
    _print("computing phase1 composite + ecdf")
    phase1_composite = synthesize_phase1_composite(row_scores)
    phase1_ecdf = to_ecdf(phase1_composite)

    _print("loading truth")
    truth_doc_ids = load_truth_doc_ids()
    _print(f"  truth_doc_count={len(truth_doc_ids):,}")

    results: list[dict[str, Any]] = []

    # baseline A — PHASE2 internal 단독 baseline = VAE ECDF (5 family 중 단일 voter)
    _print("baseline_phase2_only: VAE ECDF single")
    vae_only_doc = aggregate_doc_level(row_scores, family_ecdfs["unsupervised"])
    results.append(
        {
            "aggregator": "baseline_vae_only",
            "application": "phase2_only",
            "recall_by_top_n": measure_top_n_recall(vae_only_doc, truth_doc_ids),
        }
    )

    # baseline B — PHASE1 + VAE 2-way RRF (현 운영 통합 큐)
    _print("baseline_unified: PHASE1 + VAE 2-way RRF")
    baseline = compute_rrf_score(
        {
            "phase1_composite": phase1_composite.astype(np.float64),
            "phase2_unsupervised": family_raw["unsupervised"].astype(np.float64),
        }
    )
    base_doc = aggregate_doc_level(row_scores, pd.Series(baseline["rrf_score"]))
    results.append(
        {
            "aggregator": "baseline_phase1_vae_2way_rrf",
            "application": "phase1_plus_phase2",
            "recall_by_top_n": measure_top_n_recall(base_doc, truth_doc_ids),
        }
    )

    # reject 1 — hierarchical RRF 재기록 (이전 측정 인용용)
    from src.services.phase2_family_diagnostics import (
        classify_all_family_roles,
        compute_all_family_diagnostics,
    )
    from src.services.queue_fusion import compute_phase2_internal_rrf

    diagnostics = compute_all_family_diagnostics(family_raw)
    roles = classify_all_family_roles(diagnostics)
    active = [f for f in FAMILIES if roles[f] == "active-ranker"]
    boosters = [f for f in FAMILIES if roles[f] in {"coarse-booster", "tail-only-fallback"}]
    _print(f"hier RRF: active={active} boosters={boosters}")
    if active:
        hier_internal = compute_phase2_internal_rrf(
            family_raw,
            active_rankers=active,
            coarse_boosters=boosters,
            phase1_scores=phase1_composite,
        )
        hier_final = compute_rrf_score(
            {
                "phase1_composite": phase1_composite.astype(np.float64),
                "phase2_internal": hier_internal["phase2_internal_rrf_score"].astype(np.float64),
            }
        )
        hier_doc = aggregate_doc_level(row_scores, pd.Series(hier_final["rrf_score"]))
        results.append(
            {
                "aggregator": "hierarchical_rrf_reject",
                "application": "separated",
                "recall_by_top_n": measure_top_n_recall(hier_doc, truth_doc_ids),
            }
        )

    # 8 결합식 × {phase2_only, separated, unified} = 24
    for agg_name in AGGREGATORS:
        for application in ("phase2_only", "separated", "unified"):
            _print(f"measuring {agg_name} / {application}")
            unified = application == "unified"
            callable_ = make_aggregator_callable(
                agg_name,
                FAMILY_TIER_WEIGHTS,
                PHASE1_TIER_WEIGHT,
                CASCADE_ANCHOR,
                unified=unified,
            )
            if application == "phase2_only":
                fusion = apply_phase2_only(family_ecdfs, callable_)
            elif unified:
                fusion = apply_unified(phase1_ecdf, family_ecdfs, callable_)
            else:
                fusion = apply_separated(phase1_composite, family_ecdfs, callable_)
            doc = aggregate_doc_level(row_scores, fusion)
            results.append(
                {
                    "aggregator": agg_name,
                    "application": application,
                    "recall_by_top_n": measure_top_n_recall(doc, truth_doc_ids),
                }
            )

    # 산출
    payload = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "row_count": int(len(row_scores)),
        "document_count": int(row_scores["document_id"].nunique()),
        "truth_doc_count": int(len(truth_doc_ids)),
        "family_tier_weights": FAMILY_TIER_WEIGHTS,
        "phase1_tier_weight": PHASE1_TIER_WEIGHT,
        "cascade_anchor": CASCADE_ANCHOR,
        "results": results,
        "fitting_guard": {
            "truth_used_for_aggregator": False,
            "truth_used_for_threshold": False,
            "truth_used_for_weights": False,
        },
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_MD.write_text(build_markdown(payload), encoding="utf-8")
    _print(f"wrote {OUT_JSON.relative_to(ROOT)}")
    _print(f"wrote {OUT_MD.relative_to(ROOT)}")
    _print(f"done elapsed={time.perf_counter() - start:.1f}s")
    return 0


def build_markdown(payload: dict[str, Any]) -> str:
    lines: list[str] = [
        "# PHASE2 family ranking — alt aggregator measurement (V7 fixed3)",
        "",
        f"- generated_at: `{payload['generated_at']}`",
        f"- row_count: `{payload['row_count']:,}`",
        f"- document_count: `{payload['document_count']:,}`",
        f"- truth_doc_count: `{payload['truth_doc_count']:,}`",
        f"- family_tier_weights: `{payload['family_tier_weights']}`",
        f"- phase1_tier_weight: `{payload['phase1_tier_weight']}`",
        f"- cascade_anchor: `{payload['cascade_anchor']}`",
        "",
    ]

    p2_baseline = _baseline_recall(payload["results"], "phase2_only")
    final_baseline = _baseline_recall(payload["results"], "phase1_plus_phase2")

    lines.extend(_section_phase2_only(payload, p2_baseline))
    lines.append("")
    lines.extend(_section_phase1_plus_phase2(payload, final_baseline))

    lines.extend(
        [
            "",
            "## fitting 가드",
            "",
            "- truth label 사용: TOP N recall 산출에만",
            "- 결합식·tier_weight·임계값 결정에 truth 미사용: ✅",
            "- ECDF / rank / q95 / q99 는 모두 batch 분포 quantile",
            "",
            "## 해석 기준",
            "",
            "- baseline (PHASE1+VAE 2-way RRF) 의 TOP 1,000 recall 을 깨는 결합식이 있나?",
            "- 분리 vs 통합 어느 적용이 baseline 보존에 더 안전한가?",
            "- 어느 결합식도 baseline 못 깨면 → 결정 8 (lane/attribution) 강화",
            "",
            "## 관련 산출물",
            "",
            "- 분포 진단: `artifacts/phase2_family_correlation_matrix_20260519.md`",
            "- hierarchical RRF 측정 (reject): `artifacts/phase2_family_ranking_measurement_20260519.md`",
            "- 정책 출처: `docs/PHASE2_GOVERNANCE_DESIGN.md` 결정 8",
            "",
        ]
    )
    return "\n".join(lines)


def _baseline_recall(results: list[dict[str, Any]], application: str) -> dict[int, float]:
    """application 별 baseline recall lookup."""
    target_app = "phase2_only" if application == "phase2_only" else "phase1_plus_phase2"
    for item in results:
        if "baseline" not in item["aggregator"]:
            continue
        if item["application"] == target_app:
            return {entry["top_n"]: entry["recall"] for entry in item["recall_by_top_n"]}
    return {}


def _format_row(name: str, app: str, recall_entries: list[dict[str, Any]]) -> tuple[float, str]:
    cells: list[str] = []
    for level in TOP_N_LEVELS:
        recall = next(
            (entry["recall"] for entry in recall_entries if entry["top_n"] == level), None
        )
        cells.append(f"{recall * 100:.2f}%" if recall is not None else "-")
    top1k = next((entry["recall"] for entry in recall_entries if entry["top_n"] == 1000), 0.0)
    return top1k, f"| {name} | {app} | " + " | ".join(cells) + " |"


def _format_delta_row(
    name: str,
    app: str,
    recall_entries: list[dict[str, Any]],
    baseline: dict[int, float],
) -> tuple[float, str]:
    deltas: list[str] = []
    delta_1k = 0.0
    for level in TOP_N_LEVELS:
        recall = next(
            (entry["recall"] for entry in recall_entries if entry["top_n"] == level), None
        )
        base = baseline.get(level)
        if recall is None or base is None:
            deltas.append("-")
        else:
            delta = (recall - base) * 100
            deltas.append(f"{delta:+.2f}")
            if level == 1000:
                delta_1k = delta
    return delta_1k, f"| {name} | {app} | " + " | ".join(deltas) + " |"


def _section_phase2_only(payload: dict[str, Any], baseline: dict[int, float]) -> list[str]:
    """측정 1 — PHASE2 internal 단독 결합 (VAE 단독 vs 8 결합식)."""
    lines = [
        "## 측정 1 — PHASE2 internal 단독 (VAE 단독 baseline)",
        "",
        "PHASE1 미포함. 5 family 만으로 ranking 했을 때 TOP N document recall.",
        "baseline = VAE ECDF score 단독.",
        "",
        "### Recall",
        "",
        "| aggregator | application | TOP 100 | TOP 500 | TOP 1,000 | TOP 2,000 | TOP 5,000 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    base_rows: list[tuple[float, str]] = []
    body_rows: list[tuple[float, str]] = []
    for item in payload["results"]:
        if item["application"] != "phase2_only":
            continue
        row = _format_row(item["aggregator"], item["application"], item["recall_by_top_n"])
        if "baseline" in item["aggregator"]:
            base_rows.append(row)
        else:
            body_rows.append(row)
    body_rows.sort(key=lambda r: r[0], reverse=True)
    for _, row in base_rows:
        lines.append(row)
    for _, row in body_rows:
        lines.append(row)

    lines.extend(
        [
            "",
            "### Δrecall vs VAE 단독 baseline (pp) — TOP 1,000 기준 내림차순",
            "",
            "| aggregator | application | Δ TOP100 | Δ TOP500 | Δ TOP1000 | Δ TOP2000 | Δ TOP5000 |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    delta_rows: list[tuple[float, str]] = []
    for item in payload["results"]:
        if item["application"] != "phase2_only" or "baseline" in item["aggregator"]:
            continue
        delta_rows.append(
            _format_delta_row(
                item["aggregator"], item["application"], item["recall_by_top_n"], baseline
            )
        )
    delta_rows.sort(key=lambda r: r[0], reverse=True)
    for _, row in delta_rows:
        lines.append(row)
    return lines


def _section_phase1_plus_phase2(payload: dict[str, Any], baseline: dict[int, float]) -> list[str]:
    """측정 2 — PHASE1+PHASE2 통합 큐 (분리/통합 적용)."""
    lines = [
        "## 측정 2 — PHASE1+PHASE2 통합 큐 (PHASE1+VAE 2-way RRF baseline)",
        "",
        "최종 운영 큐 결합. baseline = PHASE1 composite + VAE ECDF 2-way RRF k=60 (현 운영).",
        "application:",
        "- `separated` — PHASE2 internal 결합 → PHASE1 과 2-way RRF",
        "- `unified` — PHASE1 + 5 family 6 source 한 번에 결합",
        "",
        "### Recall",
        "",
        "| aggregator | application | TOP 100 | TOP 500 | TOP 1,000 | TOP 2,000 | TOP 5,000 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    base_rows: list[tuple[float, str]] = []
    body_rows: list[tuple[float, str]] = []
    reject_rows: list[tuple[float, str]] = []
    for item in payload["results"]:
        app = item["application"]
        if app == "phase2_only":
            continue
        row = _format_row(item["aggregator"], app, item["recall_by_top_n"])
        if "baseline" in item["aggregator"]:
            base_rows.append(row)
        elif "hierarchical" in item["aggregator"]:
            reject_rows.append(row)
        else:
            body_rows.append(row)
    body_rows.sort(key=lambda r: r[0], reverse=True)
    for _, row in base_rows:
        lines.append(row)
    for _, row in reject_rows:
        lines.append(row)
    for _, row in body_rows:
        lines.append(row)

    lines.extend(
        [
            "",
            "### Δrecall vs PHASE1+VAE 2-way RRF baseline (pp) — TOP 1,000 기준 내림차순",
            "",
            "| aggregator | application | Δ TOP100 | Δ TOP500 | Δ TOP1000 | Δ TOP2000 | Δ TOP5000 |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    delta_rows: list[tuple[float, str]] = []
    for item in payload["results"]:
        app = item["application"]
        if app == "phase2_only" or "baseline" in item["aggregator"]:
            continue
        delta_rows.append(
            _format_delta_row(item["aggregator"], app, item["recall_by_top_n"], baseline)
        )
    delta_rows.sort(key=lambda r: r[0], reverse=True)
    for _, row in delta_rows:
        lines.append(row)
    return lines


if __name__ == "__main__":
    raise SystemExit(main())
