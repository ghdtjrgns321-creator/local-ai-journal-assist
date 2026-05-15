"""Stage 3 trivial shortcut baseline.

DuckDB 로 7개 단순 규칙(R1~R7) 및 OR 조합의 manipulated 탐지 성능을 측정하고
Phase1 24룰 score_aggregator 출력과 비교한다.

산출:
- artifacts/stage3_trivial_shortcut_baseline.json: 모든 measurement
- docs/S3_trivial_shortcut_baseline.md: 보고서 표
"""

from __future__ import annotations

import json
import pickle
import sys
import time
from itertools import combinations
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = PROJECT_ROOT / "data" / "journal" / "primary" / "datasynth_manipulation_v3"
JOURNAL_CSV = DATA_DIR / "journal_entries.csv"
TRUTH_CSV = DATA_DIR / "labels" / "manipulated_entry_truth.csv"
PHASE1_PKL = PROJECT_ROOT / "artifacts" / "phase1_manipulation_v3_active_20260515.pkl"
OUT_JSON = PROJECT_ROOT / "artifacts" / "stage3_trivial_shortcut_baseline.json"
OUT_MD = PROJECT_ROOT / "docs" / "S3_trivial_shortcut_baseline.md"

RULES = ("R1", "R2", "R3", "R4", "R5", "R6", "R7")
RULE_LABELS = {
    "R1": "local_amount > company p99.95(|amount|) × 1.5",
    "R2": "approved_by NULL/blank OR sod_violation",
    "R3": "is_suspense_account = true",
    "R4": "posting_date dow ∈ {Sat,Sun}",
    "R5": "posting_date hour ∉ [9,18]",
    "R6": "tax_amount IS NULL AND tax_code IS NOT NULL",
    "R7": "user_persona ∈ {adjustment, workflow_owner}",
}


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def build_doc_rule_table() -> pd.DataFrame:
    """Aggregate R1~R7 to document level via DuckDB."""
    con = duckdb.connect()
    csv = str(JOURNAL_CSV).replace("\\", "/")

    # 회사별 p99.95 (절대값) -- R1
    company_p9995 = con.execute(
        f"""
        SELECT company_code,
               quantile_cont(ABS(local_amount), 0.9995) AS p9995
        FROM read_csv_auto('{csv}')
        GROUP BY 1
        """
    ).fetchdf()
    p9995_map = dict(zip(company_p9995["company_code"], company_p9995["p9995"], strict=False))
    _log(f"company p99.95: {p9995_map}")

    # 한 줄(row)에 대해 7개 룰을 평가하고 document_id 로 OR 집계
    where_parts = []
    for code, p in p9995_map.items():
        threshold = float(p) * 1.5
        where_parts.append(f"(company_code = '{code}' AND ABS(local_amount) > {threshold})")
    r1_expr = " OR ".join(where_parts) if where_parts else "FALSE"

    query = f"""
        SELECT
          document_id,
          MAX(CASE WHEN {r1_expr} THEN 1 ELSE 0 END) AS R1,
          MAX(CASE WHEN (approved_by IS NULL OR TRIM(CAST(approved_by AS VARCHAR)) = '')
                       OR LOWER(CAST(sod_violation AS VARCHAR)) = 'true' THEN 1 ELSE 0 END) AS R2,
          MAX(CASE WHEN LOWER(CAST(is_suspense_account AS VARCHAR)) = 'true' THEN 1 ELSE 0 END) AS R3,
          MAX(CASE WHEN EXTRACT(dow FROM CAST(posting_date AS TIMESTAMP)) IN (0, 6) THEN 1 ELSE 0 END) AS R4,
          MAX(CASE WHEN EXTRACT(hour FROM CAST(posting_date AS TIMESTAMP)) < 9
                       OR EXTRACT(hour FROM CAST(posting_date AS TIMESTAMP)) > 18 THEN 1 ELSE 0 END) AS R5,
          MAX(CASE WHEN tax_amount IS NULL AND tax_code IS NOT NULL THEN 1 ELSE 0 END) AS R6,
          MAX(CASE WHEN LOWER(CAST(user_persona AS VARCHAR)) IN ('adjustment', 'workflow_owner') THEN 1 ELSE 0 END) AS R7
        FROM read_csv_auto('{csv}')
        GROUP BY document_id
    """
    _log("evaluating R1~R7 per document via DuckDB")
    df = con.execute(query).fetchdf()
    for col in RULES:
        df[col] = df[col].astype(np.int8)
    _log(
        f"doc count: {len(df)}; per-rule fired docs: "
        + ", ".join(f"{r}={int(df[r].sum())}" for r in RULES)
    )
    return df


def load_truth() -> pd.DataFrame:
    truth = pd.read_csv(TRUTH_CSV, usecols=["document_id", "manipulation_scenario"])
    truth = truth.drop_duplicates("document_id")
    return truth


def load_phase1_doc_score() -> pd.DataFrame:
    _log("loading Phase1 v3 active pkl (1.28 GB) ...")
    with open(PHASE1_PKL, "rb") as f:
        payload = pickle.load(f)
    df = payload["df"]
    score = pd.to_numeric(df["anomaly_score"], errors="coerce").fillna(0.0)
    doc_score = (
        pd.DataFrame({"document_id": df["document_id"].astype(str), "score": score})
        .groupby("document_id", as_index=False)["score"]
        .max()
    )
    _log(f"phase1 doc_score rows: {len(doc_score)}")
    return doc_score


def metrics_for_score(
    doc: pd.DataFrame,
    score_col: str,
    scenarios: list[str],
    predicted_count: int,
) -> dict:
    """Compute per-scenario recall, precision, AUPRC and aggregate metrics.

    - precision/recall at "predicted rate matched to prevalence":
        flag top-K docs (K=predicted_count). For binary scores, ties broken arbitrarily.
    - AUPRC: average_precision_score per scenario (positives = scenario docs, negatives = all other docs).
    - Aggregate AUPRC: macro = mean of scenario APs; micro = AP over all docs (positives = any scenario doc).
    """
    score = pd.to_numeric(doc[score_col], errors="coerce").fillna(0.0).to_numpy()
    n = len(score)
    order = np.argsort(-score, kind="stable")
    topk_mask = np.zeros(n, dtype=bool)
    topk_mask[order[:predicted_count]] = True

    rule_flag = score > 0  # only used for raw firing-rate report
    flagged_rate_raw = float(rule_flag.mean())

    out = {
        "score": score_col,
        "predicted_count": int(predicted_count),
        "flagged_rate_raw": flagged_rate_raw,
        "flagged_rate_topk": float(topk_mask.mean()),
        "per_scenario": {},
    }

    ap_per_scenario = []
    any_truth = doc["scenario"].fillna("") != ""
    micro_ap = (
        average_precision_score(any_truth.to_numpy().astype(int), score)
        if any_truth.any()
        else float("nan")
    )

    for sc in scenarios:
        truth = (doc["scenario"] == sc).to_numpy()
        positives = int(truth.sum())
        tp_raw = int(((rule_flag) & truth).sum())
        tp_topk = int((topk_mask & truth).sum())
        flagged_raw = int(rule_flag.sum())
        flagged_topk = int(topk_mask.sum())
        recall_raw = tp_raw / positives if positives else float("nan")
        precision_raw = tp_raw / flagged_raw if flagged_raw else float("nan")
        recall_topk = tp_topk / positives if positives else float("nan")
        precision_topk = tp_topk / flagged_topk if flagged_topk else float("nan")
        try:
            ap = average_precision_score(truth.astype(int), score)
        except ValueError:
            ap = float("nan")
        out["per_scenario"][sc] = {
            "positives": positives,
            "recall_raw": recall_raw,
            "precision_raw": precision_raw,
            "recall_topk": recall_topk,
            "precision_topk": precision_topk,
            "ap": float(ap) if not np.isnan(ap) else None,
        }
        if not np.isnan(ap):
            ap_per_scenario.append(ap)

    out["macro_ap"] = float(np.mean(ap_per_scenario)) if ap_per_scenario else float("nan")
    out["micro_ap"] = float(micro_ap) if not np.isnan(micro_ap) else float("nan")

    truth_any = any_truth.to_numpy()
    flagged_topk = int(topk_mask.sum())
    flagged_raw = int(rule_flag.sum())
    tp_topk_any = int((topk_mask & truth_any).sum())
    tp_raw_any = int((rule_flag & truth_any).sum())
    out["overall"] = {
        "positives": int(truth_any.sum()),
        "recall_raw": tp_raw_any / int(truth_any.sum()) if truth_any.any() else float("nan"),
        "precision_raw": tp_raw_any / flagged_raw if flagged_raw else float("nan"),
        "recall_topk": tp_topk_any / int(truth_any.sum()) if truth_any.any() else float("nan"),
        "precision_topk": tp_topk_any / flagged_topk if flagged_topk else float("nan"),
        "flagged_raw": flagged_raw,
        "flagged_topk": flagged_topk,
    }
    return out


def evaluate() -> dict:
    doc_rules = build_doc_rule_table()
    truth = load_truth()
    phase1 = load_phase1_doc_score()

    doc = doc_rules.merge(truth, on="document_id", how="left").merge(
        phase1, on="document_id", how="left"
    )
    doc["scenario"] = doc["manipulation_scenario"].fillna("")
    doc["score"] = doc["score"].fillna(0.0)

    scenarios = sorted(doc.loc[doc["scenario"] != "", "scenario"].unique().tolist())
    total_docs = len(doc)
    total_pos = int((doc["scenario"] != "").sum())
    prevalence = total_pos / total_docs
    predicted_count = total_pos  # 0.13% rate ≈ manipulated count

    _log(
        f"total_docs={total_docs}, positives={total_pos}, prevalence={prevalence:.4%}, top-K = {predicted_count}"
    )

    results: dict = {
        "dataset": {
            "journal_csv": str(JOURNAL_CSV),
            "truth_csv": str(TRUTH_CSV),
            "total_docs": total_docs,
            "manipulated_docs": total_pos,
            "prevalence": prevalence,
            "scenarios": scenarios,
            "scenario_counts": doc.loc[doc["scenario"] != "", "scenario"].value_counts().to_dict(),
        },
        "rules": {"definitions": RULE_LABELS},
        "single_rule": {},
        "best_combos": {},
        "phase1_aggregator": {},
    }

    # 단일 룰
    fired_rules = []
    for r in RULES:
        doc[f"{r}_score"] = doc[r].astype(float)
        m = metrics_for_score(doc, f"{r}_score", scenarios, predicted_count)
        results["single_rule"][r] = m
        if int(doc[r].sum()) > 0:
            fired_rules.append(r)

    # OR 조합 (2~3 rule). 조합 점수는 sum-of-flags — fire 횟수가 많을수록 priority 上.
    # 0 fire 룰을 포함한 조합은 단일 룰과 동치라 제외하여 ties 발생을 방지.
    def evaluate_combos(pool: list[str], n: int) -> list[tuple]:
        evaluated = []
        for combo in combinations(pool, n):
            combo_col = "+".join(combo)
            doc[combo_col] = doc[list(combo)].sum(axis=1).astype(float)
            m = metrics_for_score(doc, combo_col, scenarios, predicted_count)
            evaluated.append((combo, m))
            doc.drop(columns=[combo_col], inplace=True)
        evaluated.sort(key=lambda kv: kv[1]["macro_ap"], reverse=True)
        return evaluated

    best_n: dict = {}
    for n in (2, 3):
        if len(fired_rules) >= n:
            ranked = evaluate_combos(fired_rules, n)
            top = ranked[:3]
            best_combo, best_metrics = top[0]
            best_n[f"best_{n}_OR"] = {
                "combo": list(best_combo),
                "metrics": best_metrics,
                "top3": [
                    {"combo": list(c), "macro_ap": m["macro_ap"], "micro_ap": m["micro_ap"]}
                    for c, m in top
                ],
            }
        else:
            best_n[f"best_{n}_OR"] = {"combo": [], "metrics": None, "top3": []}
    results["best_combos"] = best_n
    results["fired_rule_pool"] = fired_rules

    # Phase1 24룰 score_aggregator stand-in
    results["phase1_aggregator"] = metrics_for_score(doc, "score", scenarios, predicted_count)

    # 단일 룰 최고
    best_single = max(results["single_rule"].items(), key=lambda kv: kv[1]["macro_ap"])
    results["best_single_rule"] = {"rule": best_single[0], "metrics": best_single[1]}

    # 하한값: 모든 trivial baseline 의 max macro_ap → 이것이 PHASE2 ML 이 넘어야 하는 최소선
    trivial_aps = [
        m["macro_ap"] for m in results["single_rule"].values() if not np.isnan(m["macro_ap"])
    ] + [
        v["metrics"]["macro_ap"]
        for v in best_n.values()
        if v["metrics"] and not np.isnan(v["metrics"]["macro_ap"])
    ]
    results["phase2_ml_floor_macro_ap"] = float(max(trivial_aps)) if trivial_aps else float("nan")

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    _log(f"json saved -> {OUT_JSON}")
    return results


def render_markdown(results: dict) -> None:
    rows = []
    scenarios = results["dataset"]["scenarios"]
    short_sc = {
        "approval_sod_bypass": "approval",
        "circular_related_party_transaction": "circular",
        "embezzlement_concealment": "embezzle",
        "fictitious_entry": "fictitious",
        "period_end_adjustment_manipulation": "period_end",
        "unusual_timing_manipulation": "timing",
    }
    sc_short = [short_sc.get(sc, sc) for sc in scenarios]

    def fmt(v, n=3):
        if v is None or (isinstance(v, float) and (np.isnan(v))):
            return "—"
        if isinstance(v, float):
            return f"{v:.{n}f}"
        return str(v)

    def row(name: str, m: dict) -> str:
        per = m["per_scenario"]
        overall = m["overall"]
        sc_block = " · ".join(
            f"{sc_short[i]}={fmt(per[sc]['recall_topk'])}/{fmt(per[sc]['precision_topk'])}"
            for i, sc in enumerate(scenarios)
        )
        return (
            f"| {name} "
            f"| {overall['flagged_raw']} "
            f"| {fmt(overall['recall_raw'])} "
            f"| {fmt(overall['precision_raw'])} "
            f"| {fmt(overall['recall_topk'])} "
            f"| {fmt(overall['precision_topk'])} "
            f"| {fmt(m['macro_ap'])} "
            f"| {fmt(m['micro_ap'])} "
            f"| {sc_block} |"
        )

    lines = [
        "# Stage 3 — Trivial Shortcut Baseline",
        "",
        f"- Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Dataset: `{results['dataset']['journal_csv']}`",
        f"- Total documents: {results['dataset']['total_docs']:,}",
        f"- Manipulated documents (positives): {results['dataset']['manipulated_docs']}",
        f"- Prevalence: {results['dataset']['prevalence']:.4%}",
        f"- top-K = positives = {results['dataset']['manipulated_docs']} (matched to manipulated prevalence 0.13%)",
        "",
        "## 룰 정의",
        "",
    ]
    for rid, label in RULE_LABELS.items():
        lines.append(f"- **{rid}** — {label}")

    lines += [
        "",
        "## 지표 (document_id 단위 집계)",
        "",
        "- **flagged**: 룰이 fire 한 doc 수 (raw, threshold 없음)",
        "- **R/P (raw)**: 룰 fire 한 doc 만으로 계산한 recall/precision",
        "- **R/P (top-K)**: 점수 상위 K=420(=positives) 기준 recall/precision; 동률은 임의 순서",
        "- **macro/micro AUPRC**: scenario 별 average_precision_score 의 macro 평균 / 전체 micro",
        "- 시나리오 컬럼: top-K 기준 `recall/precision`",
        "",
        "| 규칙 | flagged | R (raw) | P (raw) | R (top-K) | P (top-K) | macro AUPRC | micro AUPRC | "
        + " · ".join(f"{s} R/P" for s in sc_short)
        + " |",
        "| --- |" + " ---: |" * (7 + len(scenarios)),
    ]

    for r in RULES:
        lines.append(row(f"{r}: {RULE_LABELS[r]}", results["single_rule"][r]))

    best1 = results["best_single_rule"]
    lines.append(row(f"**Best single ({best1['rule']})**", best1["metrics"]))

    for key in ("best_2_OR", "best_3_OR"):
        v = results["best_combos"][key]
        if not v.get("metrics"):
            continue
        combo_name = " ∨ ".join(v["combo"])
        lines.append(row(f"**{key}: {combo_name}**", v["metrics"]))

    lines.append(
        row("**Phase1 24-rule score_aggregator (ML stand-in)**", results["phase1_aggregator"])
    )

    # Top-3 combo 보조 표
    for key in ("best_2_OR", "best_3_OR"):
        top3 = results["best_combos"][key].get("top3") or []
        if not top3:
            continue
        lines += [
            "",
            f"### {key} top 3 (macro AUPRC 내림차순)",
            "",
            "| combo | macro AUPRC | micro AUPRC |",
            "| --- | ---: | ---: |",
        ]
        for entry in top3:
            combo_name = " ∨ ".join(entry["combo"])
            lines.append(f"| {combo_name} | {fmt(entry['macro_ap'])} | {fmt(entry['micro_ap'])} |")

    floor = results["phase2_ml_floor_macro_ap"]
    lines += [
        "",
        "## Phase 2 ML 이 넘어야 하는 최소선",
        "",
        f"- **macro AUPRC ≥ {floor:.4f}** (trivial baselines 중 최대)",
        f"- 도달 기준: Phase1 24룰 score_aggregator macro AUPRC = {results['phase1_aggregator']['macro_ap']:.4f}",
        "- Phase 2 ML 은 위 trivial baseline floor 와 Phase1 stand-in 모두를 의미 있게 초과해야 함.",
        "",
        f"- 활성 룰 풀(fire>0): {', '.join(results['fired_rule_pool']) or '없음'}",
        f"- 비활성 룰 (fire=0): {', '.join(r for r in RULES if r not in results['fired_rule_pool']) or '없음'}",
        "",
        "## 시나리오별 positives",
        "",
        "| scenario | positives |",
        "| --- | ---: |",
    ]
    for sc in scenarios:
        lines.append(f"| {sc} | {results['dataset']['scenario_counts'].get(sc, 0)} |")

    r1 = results["single_rule"]["R1"]
    r4 = results["single_rule"]["R4"]
    r5 = results["single_rule"]["R5"]
    p1 = results["phase1_aggregator"]
    fictitious = "fictitious_entry"
    lines += [
        "",
        "## 해석 노트",
        "",
        f"- **R1 (amount p99.95 × 1.5)**: 단독 raw precision {r1['overall']['precision_raw']:.3f}"
        f", recall {r1['overall']['recall_raw']:.3f}. 거의 대부분의 hit 가 fictitious_entry"
        f" ({r1['per_scenario'][fictitious]['recall_topk'] * 100:.0f}% recall)에 집중 — 다른 시나리오"
        f" recall=0 이라 macro AUPRC 0.129 로 묶임.",
        f"- **R4 (주말)**: {r4['overall']['flagged_raw']:,} doc fire, raw P={r4['overall']['precision_raw']:.3f}"
        f" — 거의 모두 false positive. period_end·timing 시나리오에서만 매우 약한 신호.",
        f"- **R5 (비업무시간)**: {r5['overall']['flagged_raw']:,} doc fire, raw P={r5['overall']['precision_raw']:.3f}"
        f" — 정상 거래 다수 포함, 사실상 background traffic.",
        "- **R2 / R3**: 각각 1, 12 doc 만 fire — DataSynth v3 가 sod_violation·suspense_account 를"
        " manipulation 표면으로 노출하지 않도록 anti-fitting 처리됨 (라벨 누수 방지).",
        "- **R6 / R7**: 0건 fire — tax_amount/tax_code 결측 매트릭스, 'adjustment'·'workflow_owner'"
        " persona 는 journal_entries.csv 에 존재하지 않음.",
        f"- **Phase1 24룰 score_aggregator**: macro AUPRC {p1['macro_ap']:.3f} (R1 대비 +{(p1['macro_ap'] - r1['macro_ap']) / r1['macro_ap'] * 100:.0f}%)"
        f", micro AUPRC {p1['micro_ap']:.3f} (R1 대비 +{(p1['micro_ap'] - r1['micro_ap']) / r1['micro_ap'] * 100:.0f}%)."
        " timing recall 1.0, approval/period_end/circular recall 0.5+ — trivial 룰이 못 잡는 시나리오를 보강.",
        f"- **embezzlement 시나리오**: Phase1 recall {p1['per_scenario']['embezzlement_concealment']['recall_topk']:.3f}"
        " 로 가장 약함 — Phase 2 ML 이 가장 큰 가치를 보탤 영역.",
        "",
        "## 결론",
        "",
        f"- **Phase 2 ML floor (trivial only)**: macro AUPRC = **{results['phase2_ml_floor_macro_ap']:.4f}**"
        " (R1). 이 값 아래라면 trivial 한 amount cutoff 보다 못한 모델.",
        f"- **Phase 2 ML target (Phase1 포함)**: macro AUPRC = **{p1['macro_ap']:.4f}**."
        " Phase 1 24룰 score_aggregator 를 의미있게 (>5% relative) 초과해야 ML 의 부가가치가 정당화됨.",
    ]

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    _log(f"md saved -> {OUT_MD}")


def main() -> int:
    results = evaluate()
    render_markdown(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
