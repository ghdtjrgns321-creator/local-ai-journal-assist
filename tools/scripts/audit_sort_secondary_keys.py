"""§9.3 — 7개 주제 공통 정렬 보조 키 audit.

§9.2가 approval_control/closing_timing에 집중했다면, 본 스크립트는 7개 topic 모두에서
보조 키가 일관된 분리력을 갖는지 측정한다.

분리력 측정 대상 보조 키
- independent_evidence_count : `rule_evidence_summary` 안에서 scoring_role='primary'인 distinct rule_id 수
- evidence_type_count        : distinct evidence_type 수
- secondary_topic_count      : secondary_topics 길이
- repeat_score / behavior_score / macro_context_count
- has_high_materiality / has_repeat_pattern / has_control_failure (binary)
- topic_breakdown 의 corroboration_score / audit_evidence_score / max_primary_rule_score (참조)

시뮬레이션 후보
- C0 : baseline (topic_score, triage_rank_score, total_amount, rule_count)
- C1 : + secondary_topic_count
- C2 : + independent_evidence_count + secondary_topic_count
- C3 : composite (topic_score + corroboration + max_primary_rule_score + audit_evidence)  ← PHASE1 한계
- C4 : ML-style composite (PHASE2 이관 후보, 본 audit에서는 단순 logistic-style 가중 합산으로 추정)
"""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd

HIGH_THRESHOLD = 0.75
TOP_NS = (10, 50, 100, 200)

TOPIC_LABELS = {
    "ledger_integrity": "원장기록·데이터정합성",
    "approval_control": "승인·권한·업무분장 통제",
    "closing_timing": "결산·기간귀속·입력시점",
    "account_logic": "계정분류·거래실질 불일치",
    "duplicate_outflow": "중복·상계·자금유출",
    "intercompany_cycle": "관계사·내부거래·순환구조",
    "revenue_statistical": "수익·금액·모집단 통계 이상",
}


def case_documents(case: dict) -> set[str]:
    docs: set[str] = set()
    for hit in case.get("raw_rule_hits", []) or []:
        d = hit.get("document_id")
        if d:
            docs.add(str(d))
    for d in case.get("documents", []) or []:
        if isinstance(d, str):
            docs.add(d)
        elif isinstance(d, dict) and d.get("document_id"):
            docs.add(str(d["document_id"]))
    return docs


def topic_score(case: dict, topic_id: str) -> float:
    sc = (case.get("topic_scores") or {}).get(topic_id, 0.0)
    try:
        return float(sc) if sc is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def topic_breakdown(case: dict, topic_id: str) -> dict:
    return (case.get("topic_score_breakdown") or {}).get(topic_id, {}) or {}


def fnum(x) -> float:
    try:
        return float(x) if x is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def independent_evidence_count(case: dict) -> int:
    """primary scoring_role 의 distinct rule_id 수."""
    rule_ids = {
        r.get("rule_id")
        for r in case.get("rule_evidence_summary") or []
        if r.get("scoring_role") == "primary" and r.get("rule_id")
    }
    return len(rule_ids)


def evidence_type_count(case: dict) -> int:
    return len(
        {
            r.get("evidence_type")
            for r in case.get("rule_evidence_summary") or []
            if r.get("evidence_type")
        }
    )


def extract_features(case: dict, topic_id: str) -> dict:
    bd = topic_breakdown(case, topic_id)
    return {
        "case_id": case.get("case_id"),
        "documents": case_documents(case),
        "topic_score": topic_score(case, topic_id),
        "triage_rank_score": fnum(case.get("triage_rank_score")),
        "total_amount": fnum(case.get("total_amount")),
        "rule_count": int(case.get("rule_count") or 0),
        "priority_score": fnum(case.get("priority_score")),
        "base_priority_score": fnum(case.get("base_priority_score")),
        "independent_evidence_count": independent_evidence_count(case),
        "evidence_type_count": evidence_type_count(case),
        "secondary_topic_count": len(case.get("secondary_topics") or []),
        "macro_context_count": len(case.get("macro_contexts") or []),
        "repeat_score": fnum(case.get("repeat_score")),
        "behavior_score": fnum(case.get("behavior_score")),
        "has_high_materiality": int(bool(case.get("has_high_materiality"))),
        "has_repeat_pattern": int(bool(case.get("has_repeat_pattern"))),
        "has_control_failure": int(bool(case.get("has_control_failure"))),
        "max_primary_rule_score": fnum(bd.get("max_primary_rule_score")),
        "corroboration_score": fnum(bd.get("corroboration_score")),
        "audit_evidence_score": fnum(bd.get("audit_evidence_score")),
        "secondary_evidence_score": fnum(bd.get("secondary_evidence_score")),
        "fraud_combo_count": len(bd.get("fraud_combo_policy_ids") or []),
        "has_fraud_combo": 1 if bd.get("fraud_combo_policy_ids") else 0,
        "topside_bonus": fnum(case.get("topside_bonus")),
        "batch_combo_bonus": fnum(case.get("batch_combo_bonus")),
        "weak_evidence_bonus": fnum(case.get("weak_evidence_bonus")),
    }


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] + (s[c] - s[f]) * (k - f)


def dist_summary(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "median": round(percentile(values, 0.5), 4),
        "p75": round(percentile(values, 0.75), 4),
        "p90": round(percentile(values, 0.90), 4),
        "mean": round(sum(values) / len(values), 4),
    }


def simulate_topN(
    rows: list[dict], sort_key, truth_docs: set[str], top_n_list: list[int]
) -> dict[int, dict[str, int]]:
    sorted_rows = sorted(rows, key=sort_key)
    out: dict[int, dict[str, int]] = {}
    seen: set[str] = set()
    idx_to_topn = {n: None for n in top_n_list}
    for i, r in enumerate(sorted_rows, start=1):
        seen |= r["documents"]
        if i in idx_to_topn:
            out[i] = {
                "top_n_case_docs": len(seen),
                "top_n_truth_docs": len(seen & truth_docs),
            }
    # 안전망 — 일부 N이 모집단보다 클 수 있음
    for n in top_n_list:
        if n not in out:
            out[n] = {"top_n_case_docs": len(seen), "top_n_truth_docs": len(seen & truth_docs)}
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-artifact", type=Path, required=True)
    parser.add_argument("--truth-csv", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    args = parser.parse_args()

    with args.case_artifact.open("r", encoding="utf-8") as fp:
        art = json.load(fp)
    cases = art.get("cases", [])

    truth_df = pd.read_csv(args.truth_csv, dtype=str, low_memory=False)
    truth_docs = set(truth_df["document_id"].dropna().astype(str).unique())

    AUX_KEYS = [
        "independent_evidence_count",
        "evidence_type_count",
        "secondary_topic_count",
        "macro_context_count",
        "repeat_score",
        "behavior_score",
        "has_high_materiality",
        "has_repeat_pattern",
        "has_control_failure",
        "max_primary_rule_score",
        "corroboration_score",
        "audit_evidence_score",
        "secondary_evidence_score",
        "fraud_combo_count",
        "has_fraud_combo",
        "topside_bonus",
        "base_priority_score",
        "priority_score",
        "rule_count",
    ]

    out: dict = {
        "case_artifact": str(args.case_artifact),
        "truth_csv": str(args.truth_csv),
        "case_total": len(cases),
        "truth_total": len(truth_docs),
        "topics": {},
        "consistency": {},
    }

    # 키별 분리 방향 일관성: truth_median > nontruth_median 이면 +1, < 이면 -1, == 이면 0
    consistency_table: dict[str, dict[str, int]] = {k: {} for k in AUX_KEYS}

    for topic_id, label in TOPIC_LABELS.items():
        topic_cases = [c for c in cases if topic_score(c, topic_id) >= HIGH_THRESHOLD]
        rows = [extract_features(c, topic_id) for c in topic_cases]
        truth_rows = [r for r in rows if r["documents"] & truth_docs]
        nontruth_rows = [r for r in rows if not (r["documents"] & truth_docs)]
        truth_docs_in_topic = set()
        for r in truth_rows:
            truth_docs_in_topic |= r["documents"] & truth_docs

        topic_out: dict = {
            "label": label,
            "high_case_count": len(rows),
            "truth_case_count": len(truth_rows),
            "nontruth_case_count": len(nontruth_rows),
            "truth_docs_in_high": len(truth_docs_in_topic),
        }

        # 보조 키 분포
        distributions: dict = {}
        for k in AUX_KEYS:
            t_vals = [r[k] for r in truth_rows]
            n_vals = [r[k] for r in nontruth_rows]
            t_dist = dist_summary(t_vals)
            n_dist = dist_summary(n_vals)
            distributions[k] = {"truth": t_dist, "nontruth": n_dist}
            t_med = t_dist.get("median", 0)
            n_med = n_dist.get("median", 0)
            if t_dist.get("n", 0) == 0 or n_dist.get("n", 0) == 0:
                direction = 0
            elif t_med > n_med:
                direction = 1
            elif t_med < n_med:
                direction = -1
            else:
                direction = 0
            consistency_table[k][topic_id] = direction
        topic_out["distributions"] = distributions

        # 정렬 후보별 Top N truth 진입률 (high band only)
        topic_out["candidates"] = {}
        candidates = {
            "C0_baseline": lambda r: (
                -r["topic_score"],
                -r["triage_rank_score"],
                -r["total_amount"],
                -r["rule_count"],
            ),
            "C1_secondary_topic": lambda r: (
                -r["topic_score"],
                -r["secondary_topic_count"],
                -r["triage_rank_score"],
                -r["total_amount"],
                -r["rule_count"],
            ),
            "C2_indep_evidence+secondary": lambda r: (
                -r["topic_score"],
                -r["independent_evidence_count"],
                -r["secondary_topic_count"],
                -r["triage_rank_score"],
                -r["total_amount"],
                -r["rule_count"],
            ),
            "C3_composite_phase1": lambda r: (
                -(
                    1.0 * r["topic_score"]
                    + 0.3 * r["max_primary_rule_score"]
                    + 0.3 * r["audit_evidence_score"]
                    + 0.3 * r["corroboration_score"]
                    + 0.1 * min(r["independent_evidence_count"] / 5.0, 1.0)
                ),
                -r["triage_rank_score"],
                -r["total_amount"],
                -r["rule_count"],
            ),
            "C4_composite_ml_proxy": lambda r: (
                # PHASE2 ML 분류기에서 출력될 truth-likelihood 를 PHASE1 피처로 근사
                -(
                    0.45 * r["topic_score"]
                    + 0.25 * r["max_primary_rule_score"]
                    + 0.20 * r["audit_evidence_score"]
                    + 0.20 * r["corroboration_score"]
                    + 0.15 * min(r["independent_evidence_count"] / 5.0, 1.0)
                    + 0.10 * min(r["rule_count"] / 10.0, 1.0)
                    + 0.05 * r["topside_bonus"]
                    + 0.05 * r["control_failure_flag" if False else "has_control_failure"]
                ),
                -r["triage_rank_score"],
                -r["total_amount"],
                -r["rule_count"],
            ),
        }
        cand_results = {}
        for name, key_fn in candidates.items():
            res_per_n = simulate_topN(rows, key_fn, truth_docs, list(TOP_NS))
            cand_results[name] = res_per_n
        topic_out["candidates"] = cand_results

        # all-band 추가 시뮬레이션 (topic_score > 0 인 모든 case)
        all_rows = [extract_features(c, topic_id) for c in cases if topic_score(c, topic_id) > 0]
        all_truth_docs_topic: set[str] = set()
        for r in all_rows:
            all_truth_docs_topic |= r["documents"] & truth_docs
        topic_out["all_band_case_count"] = len(all_rows)
        topic_out["all_band_truth_docs"] = len(all_truth_docs_topic)

        if all_rows and all_truth_docs_topic:
            all_band_candidates = {
                "AB_C0_baseline": lambda r: (
                    -r["topic_score"],
                    -r["triage_rank_score"],
                    -r["total_amount"],
                    -r["rule_count"],
                ),
                "AB_C3_composite_phase1": lambda r: (
                    -(
                        1.0 * r["topic_score"]
                        + 0.3 * r["max_primary_rule_score"]
                        + 0.3 * r["audit_evidence_score"]
                        + 0.3 * r["corroboration_score"]
                        + 0.1 * min(r["independent_evidence_count"] / 5.0, 1.0)
                    ),
                    -r["triage_rank_score"],
                    -r["total_amount"],
                    -r["rule_count"],
                ),
                "AB_C4_composite_ml_proxy": lambda r: (
                    -(
                        0.45 * r["topic_score"]
                        + 0.25 * r["max_primary_rule_score"]
                        + 0.20 * r["audit_evidence_score"]
                        + 0.20 * r["corroboration_score"]
                        + 0.15 * min(r["independent_evidence_count"] / 5.0, 1.0)
                        + 0.10 * min(r["rule_count"] / 10.0, 1.0)
                        + 0.05 * r["topside_bonus"]
                        + 0.05 * r["has_control_failure"]
                    ),
                    -r["triage_rank_score"],
                    -r["total_amount"],
                    -r["rule_count"],
                ),
            }
            ab_results = {}
            for name, key_fn in all_band_candidates.items():
                res = simulate_topN(all_rows, key_fn, truth_docs, list(TOP_NS))
                ab_results[name] = res
            topic_out["all_band_candidates"] = ab_results

        out["topics"][topic_id] = topic_out

    # 일관성 정리: 1이 7개면 모든 topic에서 truth가 더 큰 키
    out["consistency"] = consistency_table

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {args.out_json}")


if __name__ == "__main__":
    main()
