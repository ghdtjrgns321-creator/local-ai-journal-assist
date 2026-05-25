"""Phase A doc-level ranking measurement for V7 fixed3.

Measurement-only script. It does not modify PHASE1/PHASE2 production code,
does not retrain models, and uses truth labels only as recall denominators.
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import math
import pickle
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.detection.rule_detail_metadata import get_rule_detail_metadata
from src.detection.rule_scoring import TOPIC_REGISTRY
from tools.scripts.phase2_family_correlation_audit import FAMILIES, score_all_families

DATASET_VERSION = "datasynth_manipulation_v7_candidate_fixed3"
PKL_PATH = ROOT / "artifacts" / "phase1_manipulation_v7_fixed3_case_input.pkl"
BUNDLE_PATH = (
    ROOT
    / "data"
    / "companies"
    / "_ci_baseline"
    / "engagements"
    / "2026"
    / "models"
    / "phase2_unsupervised"
    / "v1"
    / "model_bundle.pt"
)
PHASE2_JSONS = [
    ROOT / "artifacts" / "phase2_inference_v7_fixed3_year_2022.json",
    ROOT / "artifacts" / "phase2_inference_v7_fixed3_year_2023.json",
    ROOT / "artifacts" / "phase2_inference_v7_fixed3_year_2024.json",
]
QUEUE_DIR = ROOT / "data" / "companies" / "_ci_baseline" / "engagements" / "2026" / "review_queue" / "v1"
QUEUE_PHASE1_PATH = QUEUE_DIR / "queue_phase1.parquet"
QUEUE_PHASE2_PATH = QUEUE_DIR / "queue_phase2.parquet"
QUEUE_INTEGRATED_PATH = QUEUE_DIR / "queue_integrated.parquet"
TRUTH_PATH = (
    ROOT
    / "data"
    / "journal"
    / "primary"
    / DATASET_VERSION
    / "labels"
    / "manipulated_entry_truth.csv"
)
TS13_PATH = ROOT / "artifacts" / "ts13_uncovered_truth_80_analysis.json"
OUT_JSON = ROOT / "artifacts" / "doc_level_ranking_phase_a_20260519.json"
OUT_MD = ROOT / "artifacts" / "doc_level_ranking_phase_a_20260519.md"

TOP_NS = [100, 500, 1000, 2000]
TS_TOP_NS = [100, 500, 1000, 2000, 5000]
TOP_K = 3
CORROB_WEIGHT = 0.05


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _json_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if np.isfinite(out) else None


def _distribution(series: pd.Series) -> dict[str, float]:
    clean = pd.to_numeric(series, errors="coerce").fillna(0.0)
    return {
        "q50": float(clean.quantile(0.50)),
        "q95": float(clean.quantile(0.95)),
        "q99": float(clean.quantile(0.99)),
    }


def _topk_mean(values: pd.Series, k: int = TOP_K) -> float:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return 0.0
    return float(clean.nlargest(min(k, len(clean))).mean())


def _ranked_docs(scores: pd.Series) -> list[str]:
    frame = (
        scores.fillna(0.0)
        .rename("score")
        .reset_index()
        .rename(columns={scores.index.name or "index": "document_id"})
    )
    frame["document_id"] = frame["document_id"].astype(str)
    ranked = frame.sort_values(["score", "document_id"], ascending=[False, True], kind="mergesort")
    return ranked["document_id"].tolist()


def _doc_recall(ranked_docs: list[str], truth_docs: set[str]) -> list[dict[str, Any]]:
    denom = max(len(truth_docs), 1)
    out = []
    for top_n in TOP_NS:
        selected = set(ranked_docs[:top_n])
        matched = len(selected & truth_docs)
        out.append({"top_n": top_n, "matched": matched, "recall": matched / denom})
    return out


def _case_unfold_docs(queue_df: pd.DataFrame, top_n: int) -> list[str]:
    docs: list[str] = []
    seen: set[str] = set()
    for value in queue_df.head(top_n)["document_ids_joined"].fillna(""):
        for doc_id in str(value).split(";"):
            doc = doc_id.strip()
            if doc and doc not in seen:
                seen.add(doc)
                docs.append(doc)
    return docs


def _case_unfold_recall(queue_df: pd.DataFrame, truth_docs: set[str]) -> list[dict[str, Any]]:
    denom = max(len(truth_docs), 1)
    out = []
    for top_n in TOP_NS:
        docs = set(_case_unfold_docs(queue_df, top_n))
        matched = len(docs & truth_docs)
        out.append({"top_n": top_n, "matched": matched, "recall": matched / denom})
    return out


def load_inputs() -> dict[str, Any]:
    with PKL_PATH.open("rb") as fh:
        payload = pickle.load(fh)
    df = payload["df"].copy()
    df["document_id"] = df["document_id"].astype(str)
    df["fiscal_year"] = df["fiscal_year"].astype(int)

    truth = pd.read_csv(TRUTH_PATH)
    truth["document_id"] = truth["document_id"].astype(str)

    with TS13_PATH.open(encoding="utf-8") as fh:
        ts13 = json.load(fh)

    return {
        "df": df,
        "results": payload["results"],
        "truth": truth,
        "truth_docs": set(truth["document_id"]),
        "ts13_docs": {str(doc_id) for doc_id in ts13["uncovered_document_ids"]},
        "queues": {
            "phase1": pd.read_parquet(QUEUE_PHASE1_PATH),
            "phase2": pd.read_parquet(QUEUE_PHASE2_PATH),
            "integrated": pd.read_parquet(QUEUE_INTEGRATED_PATH),
        },
    }


def _topic_for_rule(rule_id: str) -> str | None:
    metadata = get_rule_detail_metadata(rule_id)
    if metadata is not None and metadata.final_topic in TOPIC_REGISTRY:
        return metadata.final_topic
    return None


def _doc_topic_counts(df: pd.DataFrame, results: list[Any]) -> pd.Series:
    doc_topics: dict[str, set[str]] = {}
    for result in results:
        details = getattr(result, "details", None)
        if not isinstance(details, pd.DataFrame):
            continue
        for rule_id in details.columns:
            topic = _topic_for_rule(str(rule_id))
            if topic is None:
                continue
            mask = pd.to_numeric(details[rule_id], errors="coerce").fillna(0.0) > 0
            if not mask.any():
                continue
            for doc_id in df.loc[mask, "document_id"].astype(str).unique():
                doc_topics.setdefault(doc_id, set()).add(topic)
    all_docs = pd.Index(df["document_id"].astype(str).unique(), name="document_id")
    return pd.Series({doc: len(doc_topics.get(doc, set())) for doc in all_docs}, dtype=float)


def compute_phase1_doc_scores(inputs: dict[str, Any]) -> tuple[dict[str, pd.Series], dict[str, Any], pd.Series]:
    df = inputs["df"]
    row_score = pd.to_numeric(df["anomaly_score"], errors="coerce").fillna(0.0)
    by_doc = pd.DataFrame({"document_id": df["document_id"], "row_score": row_score})
    base = by_doc.groupby("document_id")["row_score"]
    v1_max = base.max()
    v1_top3mean = base.apply(_topk_mean)
    hit_topic_count = _doc_topic_counts(df, inputs["results"]).reindex(v1_max.index).fillna(0.0)
    bonus = 1.0 + np.log1p(hit_topic_count) * CORROB_WEIGHT
    scores = {
        "v1_max": v1_max,
        "v1_top3mean": v1_top3mean,
        "v1_max_corrob": v1_max * bonus,
        "v1_top3mean_corrob": v1_top3mean * bonus,
    }
    summary = {
        name: {"distribution": _distribution(series), "nonzero_count": int((series.fillna(0) > 0).sum())}
        for name, series in scores.items()
    }
    return scores, summary, hit_topic_count


def _to_ecdf(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").fillna(0.0)
    return values.rank(method="average", pct=True).astype(float)


def compute_phase2_doc_scores(inputs: dict[str, Any]) -> tuple[dict[str, pd.Series], dict[str, Any], pd.DataFrame]:
    row_scores = score_all_families(inputs["df"])
    row_scores["document_id"] = inputs["df"]["document_id"].astype(str).to_numpy()
    for family in FAMILIES:
        row_scores[family] = _to_ecdf(row_scores[family])

    q95 = {family: float(row_scores[family].quantile(0.95)) for family in FAMILIES}
    stacked = row_scores.melt(
        id_vars=["document_id"],
        value_vars=list(FAMILIES),
        var_name="family",
        value_name="ecdf_score",
    )
    family_max = stacked.groupby("document_id")["ecdf_score"].max()
    family_top3mean = stacked.groupby("document_id")["ecdf_score"].apply(_topk_mean)

    family_hits = pd.DataFrame(
        {
            family: (row_scores[family] >= q95[family]).groupby(row_scores["document_id"]).any()
            for family in FAMILIES
        }
    )
    family_corroboration = family_hits.sum(axis=1).astype(float)
    bonus = 1.0 + np.log1p(family_corroboration) * CORROB_WEIGHT

    scores = {
        "family_max": family_max,
        "family_top3mean": family_top3mean,
        "family_max_corrob": family_max * bonus,
        "family_top3mean_corrob": family_top3mean * bonus,
    }
    summary = {
        name: {"distribution": _distribution(series), "nonzero_count": int((series.fillna(0) > 0).sum())}
        for name, series in scores.items()
    }
    return scores, summary, row_scores


def measure_doc_recall(
    phase1_scores: dict[str, pd.Series],
    phase2_scores: dict[str, pd.Series],
    queues: dict[str, pd.DataFrame],
    truth_docs: set[str],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    ranked_by_name: dict[str, list[str]] = {}
    for name, series in phase1_scores.items():
        key = f"phase1_{name}"
        ranked_by_name[key] = _ranked_docs(series)
        out[key] = _doc_recall(ranked_by_name[key], truth_docs)
    for name, series in phase2_scores.items():
        key = f"phase2_{name}"
        ranked_by_name[key] = _ranked_docs(series)
        out[key] = _doc_recall(ranked_by_name[key], truth_docs)

    out["baseline_phase1_case_unfold"] = _case_unfold_recall(queues["phase1"], truth_docs)
    out["baseline_phase2_case_unfold"] = _case_unfold_recall(queues["phase2"], truth_docs)
    out["baseline_rrf_2way_case_unfold"] = _case_unfold_recall(queues["integrated"], truth_docs)

    top1pct_n = max(1, math.ceil(len(phase1_scores["v1_top3mean_corrob"]) * 0.01))
    p1_set = set(ranked_by_name["phase1_v1_top3mean_corrob"][:top1pct_n])
    p2_set = set(ranked_by_name["phase2_family_top3mean_corrob"][:top1pct_n])
    union = p1_set | p2_set
    intersection = p1_set & p2_set
    out["union_top1pct"] = {
        "docs": len(union),
        "matched": len(union & truth_docs),
        "recall": len(union & truth_docs) / max(len(truth_docs), 1),
    }
    out["intersection_top1pct"] = {
        "docs": len(intersection),
        "matched": len(intersection & truth_docs),
        "precision": len(intersection & truth_docs) / max(len(intersection), 1),
    }
    return out


def _rank_distribution(scores: dict[str, pd.Series], docs: set[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, series in scores.items():
        ranked = _ranked_docs(series)
        ranks = {doc_id: rank for rank, doc_id in enumerate(ranked, start=1)}
        doc_ranks = [ranks[doc] for doc in docs if doc in ranks]
        entry = {f"top_{n}": int(sum(rank <= n for rank in doc_ranks)) for n in TS_TOP_NS}
        entry["rank_q50"] = _json_float(pd.Series(doc_ranks).quantile(0.50)) if doc_ranks else None
        entry["rank_q95"] = _json_float(pd.Series(doc_ranks).quantile(0.95)) if doc_ranks else None
        out[name] = entry
    return out


def measure_ts13_recovery(
    df: pd.DataFrame,
    ts13_docs: set[str],
    phase1_scores: dict[str, pd.Series],
    phase2_scores: dict[str, pd.Series],
) -> dict[str, Any]:
    rows_80 = df[df["document_id"].astype(str).isin(ts13_docs)]
    row_score = pd.to_numeric(rows_80["anomaly_score"], errors="coerce").fillna(0.0)
    phase2_ranked = _ranked_docs(phase2_scores["family_top3mean_corrob"])
    return {
        "row_score_distribution_of_80_docs": {
            "row_count": int(len(rows_80)),
            "doc_count": int(rows_80["document_id"].nunique()),
            "distribution": _distribution(row_score),
            "zero_row_count": int((row_score == 0).sum()),
        },
        "phase1_variant_rank_distribution": _rank_distribution(phase1_scores, ts13_docs),
        "phase2_variant_rank_distribution": _rank_distribution(phase2_scores, ts13_docs),
        "phase2_doc_queue_recovery_count": int(len(set(phase2_ranked[:2000]) & ts13_docs)),
    }


def _case_doc_mapping(queue_df: pd.DataFrame) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for row in queue_df[["case_id", "document_ids_joined"]].itertuples(index=False):
        for doc_id in str(row.document_ids_joined or "").split(";"):
            doc = doc_id.strip()
            if doc:
                mapping.setdefault(doc, str(row.case_id))
    return mapping


def measure_case_grouping(
    phase1_scores: dict[str, pd.Series],
    phase1_queue: pd.DataFrame,
    ts13_docs: set[str],
) -> dict[str, Any]:
    doc_to_case = _case_doc_mapping(phase1_queue)
    out: dict[str, Any] = {}
    for name, series in phase1_scores.items():
        ranked = _ranked_docs(series)
        top_rank_by_doc = {doc: rank for rank, doc in enumerate(ranked[:2000], start=1)}
        case_rank_ranges: dict[str, list[int]] = {}
        for doc, rank in top_rank_by_doc.items():
            case_id = doc_to_case.get(doc)
            if case_id:
                case_rank_ranges.setdefault(case_id, []).append(rank)
        dispersions = [max(ranks) - min(ranks) for ranks in case_rank_ranges.values() if len(ranks) > 1]
        out[f"phase1_{name}"] = {
            "doc_top_100_case_count": len({doc_to_case[d] for d in ranked[:100] if d in doc_to_case}),
            "doc_top_500_case_count": len({doc_to_case[d] for d in ranked[:500] if d in doc_to_case}),
            "doc_top_1000_case_count": len({doc_to_case[d] for d in ranked[:1000] if d in doc_to_case}),
            "rank_dispersion_within_case_mean": float(np.mean(dispersions)) if dispersions else 0.0,
            "rank_dispersion_within_case_median": float(np.median(dispersions)) if dispersions else 0.0,
            "doc_only_no_case_count_in_top_2000": int(
                sum(doc not in doc_to_case and doc in ts13_docs for doc in ranked[:2000])
            ),
        }
    return out


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value * 100:.2f}%"


def _recall_table(m3: dict[str, Any]) -> str:
    rows = ["| Queue | TOP-100 | TOP-500 | TOP-1000 | TOP-2000 |", "|---|---:|---:|---:|---:|"]
    for key, value in m3.items():
        if not isinstance(value, list):
            continue
        recalls = {int(item["top_n"]): item for item in value}
        cells = []
        for top_n in TOP_NS:
            item = recalls[top_n]
            cells.append(f"{item['matched']} ({_fmt_pct(item['recall'])})")
        rows.append(f"| {key} | " + " | ".join(cells) + " |")
    return "\n".join(rows)


def write_outputs(payload: dict[str, Any]) -> None:
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    m3 = payload["M3_doc_recall"]
    rrf_top500 = next(x for x in m3["baseline_rrf_2way_case_unfold"] if x["top_n"] == 500)["recall"]
    doc_top500 = max(
        next(x for x in m3[key] if x["top_n"] == 500)["recall"]
        for key in m3
        if key.startswith(("phase1_", "phase2_")) and isinstance(m3[key], list)
    )
    delta = doc_top500 - rrf_top500
    if delta >= 0.05:
        conclusion = "Phase B 진입 권고"
        reason = "doc-level 단독 큐 중 TOP-500 recall이 case-level RRF 대비 +5%p 이상입니다."
    elif abs(delta) <= 0.02:
        conclusion = "보류"
        reason = "doc-level 단독 큐 중 TOP-500 recall이 case-level RRF와 ±2%p 이내입니다."
    else:
        conclusion = "가설 재검토"
        reason = "doc-level 단독 큐 중 TOP-500 recall이 case-level RRF보다 -2%p 이상 낮습니다."

    m1_rows = _variant_distribution_table(payload["M1_phase1_doc_scores"])
    m2_rows = _variant_distribution_table(payload["M2_phase2_doc_scores"])
    recall_table = _recall_table(m3)
    ts13 = payload["M4_ts13_recovery"]
    m5 = payload["M5_case_grouping_inflation"]
    m5_rows = [
        "| Variant | TOP-100 cases | TOP-500 cases | TOP-1000 cases | mean dispersion | median dispersion | doc-only TOP-2000 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for key, value in m5.items():
        m5_rows.append(
            f"| {key} | {value['doc_top_100_case_count']} | {value['doc_top_500_case_count']} | "
            f"{value['doc_top_1000_case_count']} | {value['rank_dispersion_within_case_mean']:.2f} | "
            f"{value['rank_dispersion_within_case_median']:.2f} | {value['doc_only_no_case_count_in_top_2000']} |"
        )

    md = f"""# Phase A Doc-Level Ranking Measurement

## 0. 한 줄 결론 — Phase B 진입 여부 판단
{conclusion} — {reason}

## 1. 측정 환경 (입력 산출물, fitting 가드)
- dataset_version: `{payload['dataset_version']}`
- generated_at: `{payload['generated_at']}`
- truth_used_for: evaluation_only
- weights_tuned_with_truth: false
- corroboration_weight: {CORROB_WEIGHT}
- top_k: {TOP_K}

## 2. PHASE1 doc score 4 variant 분포 표
{m1_rows}

## 3. PHASE2 doc score 4 variant 분포 표
{m2_rows}

## 4. M3 truth recall 비교 (16 큐 × TOP-N)
{recall_table}

## 5. TS-13 80 doc 회수 측정
- row score 분포: q50={ts13['row_score_distribution_of_80_docs']['distribution']['q50']:.6f}, q95={ts13['row_score_distribution_of_80_docs']['distribution']['q95']:.6f}, q99={ts13['row_score_distribution_of_80_docs']['distribution']['q99']:.6f}
- PHASE2 doc 큐 회수율: {ts13['phase2_doc_queue_recovery_count']} / 80
- 결론: PHASE2 doc 큐 TOP-2000 기준으로 ceiling 87.10% 돌파 가능성은 위 회수 수 기준으로 사용자 판단 대기.

## 6. case grouping 인플레이션
{chr(10).join(m5_rows)}

## 7. fitting 가드 체크리스트
- [x] truth는 평가 분모/분자로만 사용
- [x] truth 기반 weight grid search 미수행
- [x] corroboration_weight=0.05 고정
- [x] top_k=3 고정
- [x] model_bundle.pt 재학습 없음
- [x] production src/dashboard/config/docs 변경 없음

## 8. 다음 단계 — Phase B 진입 결정 분기
사용자 승인 대기.
"""
    OUT_MD.write_text(md, encoding="utf-8")


def _variant_distribution_table(summary: dict[str, Any]) -> str:
    rows = ["| Variant | q50 | q95 | q99 | nonzero_count |", "|---|---:|---:|---:|---:|"]
    for key, value in summary.items():
        dist = value["distribution"]
        rows.append(
            f"| {key} | {dist['q50']:.6f} | {dist['q95']:.6f} | {dist['q99']:.6f} | {value['nonzero_count']} |"
        )
    return "\n".join(rows)


def main() -> None:
    inputs = load_inputs()
    phase1_scores, phase1_summary, _ = compute_phase1_doc_scores(inputs)
    phase2_scores, phase2_summary, _ = compute_phase2_doc_scores(inputs)
    m3 = measure_doc_recall(phase1_scores, phase2_scores, inputs["queues"], inputs["truth_docs"])
    m4 = measure_ts13_recovery(inputs["df"], inputs["ts13_docs"], phase1_scores, phase2_scores)
    m5 = measure_case_grouping(phase1_scores, inputs["queues"]["phase1"], inputs["ts13_docs"])

    payload = {
        "generated_at": _now_iso(),
        "dataset_version": DATASET_VERSION,
        "input_sources": [
            str(PKL_PATH.relative_to(ROOT)),
            str(BUNDLE_PATH.relative_to(ROOT)),
            *[str(path.relative_to(ROOT)) for path in PHASE2_JSONS],
            str(QUEUE_PHASE1_PATH.relative_to(ROOT)),
            str(QUEUE_PHASE2_PATH.relative_to(ROOT)),
            str(QUEUE_INTEGRATED_PATH.relative_to(ROOT)),
            str(TRUTH_PATH.relative_to(ROOT)),
        ],
        "fitting_guard": {
            "truth_used_for": "evaluation_only",
            "weights_tuned_with_truth": False,
            "corroboration_weight": CORROB_WEIGHT,
            "top_k": TOP_K,
        },
        "counts": {
            "total_docs": int(inputs["df"]["document_id"].nunique()),
            "truth_docs": int(len(inputs["truth_docs"])),
            "phase1_case_count": int(len(inputs["queues"]["phase1"])),
            "ts13_uncovered_truth_docs": int(len(inputs["ts13_docs"])),
        },
        "M1_phase1_doc_scores": phase1_summary,
        "M2_phase2_doc_scores": phase2_summary,
        "M3_doc_recall": m3,
        "M4_ts13_recovery": m4,
        "M5_case_grouping_inflation": m5,
    }
    write_outputs(payload)


if __name__ == "__main__":
    main()
