"""approval_control:high / closing_timing:high 정렬 키 분포 + 보조 키 시뮬레이션.

v2 case artifact 안에서:
- 두 topic의 high(>=0.75) case를 추출
- truth(=case가 truth doc을 최소 1건 포함)와 비-truth 케이스로 분류
- 기존 정렬 키(topic_score, triage_rank_score, total_amount, rule_count, priority_score)의 분포 비교
- 보조 키 후보(evidence_count, evidence_type 다양도, secondary_topics 수, repeat/behavior score, macro_contexts, fraud_combo, approval_bypass tag,
  audit_evidence_score, has_fraud_combo, document_count) 분포 비교
- 보조 키 후보 조합으로 Top200 truth_docs 변화 시뮬레이션

§9.2 audit 산출물 생성.
"""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter
from pathlib import Path

import pandas as pd

HIGH_THRESHOLD = 0.75
TOP_N_SIMULATION = 200

TARGET_TOPICS = ("approval_control", "closing_timing")


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


def evidence_diversity(case: dict) -> int:
    types = {
        r.get("evidence_type")
        for r in case.get("rule_evidence_summary") or []
        if r.get("evidence_type")
    }
    return len(types)


def evidence_strength_count(case: dict, strength: str) -> int:
    return sum(
        1 for r in case.get("rule_evidence_summary") or [] if r.get("evidence_strength") == strength
    )


def primary_score_sum(case: dict) -> float:
    return sum(
        float(r.get("normalized_score") or 0.0)
        for r in case.get("rule_evidence_summary") or []
        if r.get("scoring_role") == "primary"
    )


def has_fraud_combo(case: dict, topic_id: str) -> bool:
    bd = topic_breakdown(case, topic_id)
    return bool(bd.get("fraud_combo_policy_ids"))


def has_combo_floor(case: dict, topic_id: str) -> bool:
    bd = topic_breakdown(case, topic_id)
    return bool(bd.get("has_combo_floor"))


def has_approval_bypass_tag(case: dict, topic_id: str) -> bool:
    bd = topic_breakdown(case, topic_id)
    tags = bd.get("fraud_combo_tags") or []
    return any("approval_bypass" in str(t) for t in tags)


def audit_evidence_score(case: dict, topic_id: str) -> float:
    bd = topic_breakdown(case, topic_id)
    try:
        return float(bd.get("audit_evidence_score") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def max_primary_rule_score(case: dict, topic_id: str) -> float:
    bd = topic_breakdown(case, topic_id)
    try:
        return float(bd.get("max_primary_rule_score") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def secondary_evidence_score(case: dict, topic_id: str) -> float:
    bd = topic_breakdown(case, topic_id)
    try:
        return float(bd.get("secondary_evidence_score") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def corroboration_score(case: dict, topic_id: str) -> float:
    bd = topic_breakdown(case, topic_id)
    try:
        return float(bd.get("corroboration_score") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def repeat_score_topic(case: dict, topic_id: str) -> float:
    bd = topic_breakdown(case, topic_id)
    try:
        return float(bd.get("repeat_score") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def macro_score(case: dict, topic_id: str) -> float:
    bd = topic_breakdown(case, topic_id)
    try:
        return float(bd.get("macro_context_score") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def fnum(x) -> float:
    try:
        return float(x) if x is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def quantiles(values: list[float], n: int = 4) -> list[float]:
    if not values:
        return []
    if all(v == values[0] for v in values):
        return [values[0]] * (n - 1)
    return statistics.quantiles(values, n=n)


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


def distribution_summary(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "mean": round(sum(values) / len(values), 6),
        "median": round(percentile(values, 0.5), 6),
        "p10": round(percentile(values, 0.10), 6),
        "p25": round(percentile(values, 0.25), 6),
        "p75": round(percentile(values, 0.75), 6),
        "p90": round(percentile(values, 0.90), 6),
        "p99": round(percentile(values, 0.99), 6),
        "min": round(min(values), 6),
        "max": round(max(values), 6),
    }


def extract_features(case: dict, topic_id: str) -> dict:
    """case에서 분석용 피처를 단일 dict로 추출."""
    docs = case_documents(case)
    secondary_topics = case.get("secondary_topics") or []
    macro_ctx = case.get("macro_contexts") or []
    bd = topic_breakdown(case, topic_id)
    return {
        "case_id": case.get("case_id"),
        "primary_theme": case.get("primary_theme"),
        "primary_topic": case.get("primary_topic"),
        "documents": docs,
        "topic_score": topic_score(case, topic_id),
        "triage_rank_score": fnum(case.get("triage_rank_score")),
        "priority_score": fnum(case.get("priority_score")),
        "base_priority_score": fnum(case.get("base_priority_score")),
        "total_amount": fnum(case.get("total_amount")),
        "rule_count": int(case.get("rule_count") or 0),
        "evidence_count": int(case.get("evidence_count") or 0),
        "document_count": int(case.get("document_count") or 0),
        "row_count": int(case.get("row_count") or 0),
        "repeat_months": int(case.get("repeat_months") or 0),
        "amount_score": fnum(case.get("amount_score")),
        "control_score": fnum(case.get("control_score")),
        "duplicate_or_outflow_score": fnum(case.get("duplicate_or_outflow_score")),
        "logic_score": fnum(case.get("logic_score")),
        "data_integrity_score": fnum(case.get("data_integrity_score")),
        "intercompany_score": fnum(case.get("intercompany_score")),
        "timing_score": fnum(case.get("timing_score")),
        "behavior_score": fnum(case.get("behavior_score")),
        "repeat_score": fnum(case.get("repeat_score")),
        "evidence_diversity": evidence_diversity(case),
        "strong_evidence_count": evidence_strength_count(case, "strong"),
        "medium_evidence_count": evidence_strength_count(case, "medium"),
        "weak_evidence_count": evidence_strength_count(case, "weak"),
        "primary_score_sum": round(primary_score_sum(case), 6),
        "secondary_topic_count": len(secondary_topics),
        "macro_context_count": len(macro_ctx),
        "fraud_scenario_tag_count": len(case.get("fraud_scenario_tags") or []),
        "has_fraud_combo": int(has_fraud_combo(case, topic_id)),
        "has_combo_floor": int(has_combo_floor(case, topic_id)),
        "has_approval_bypass_tag": int(has_approval_bypass_tag(case, topic_id)),
        "audit_evidence_score": round(audit_evidence_score(case, topic_id), 6),
        "max_primary_rule_score": round(max_primary_rule_score(case, topic_id), 6),
        "secondary_evidence_score": round(secondary_evidence_score(case, topic_id), 6),
        "corroboration_score": round(corroboration_score(case, topic_id), 6),
        "topic_repeat_score": round(repeat_score_topic(case, topic_id), 6),
        "macro_context_score": round(macro_score(case, topic_id), 6),
        "has_control_failure": int(bool(case.get("has_control_failure"))),
        "has_high_materiality": int(bool(case.get("has_high_materiality"))),
        "has_repeat_pattern": int(bool(case.get("has_repeat_pattern"))),
        "topside_bonus": fnum(case.get("topside_bonus")),
        "batch_combo_bonus": fnum(case.get("batch_combo_bonus")),
        "weak_evidence_bonus": fnum(case.get("weak_evidence_bonus")),
    }


def simulate_topN(
    rows: list[dict], sort_key, *, top_n: int = TOP_N_SIMULATION, truth_docs: set[str] | None = None
) -> dict:
    """rows를 sort_key로 정렬해 상위 top_n 까지 truth docs 누적."""
    if truth_docs is None:
        truth_docs = set()
    sorted_rows = sorted(rows, key=sort_key)
    seen_docs: set[str] = set()
    truth_hits = 0
    for r in sorted_rows[:top_n]:
        new_docs = r["documents"] - seen_docs
        seen_docs |= r["documents"]
        truth_hits = len(seen_docs & truth_docs)
    return {
        "top_n_case_docs": len(seen_docs),
        "top_n_truth_docs": truth_hits,
    }


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
    scenario_col = "manipulation_scenario"
    truth_by_doc = (
        truth_df.set_index("document_id")[scenario_col].to_dict()
        if scenario_col in truth_df.columns
        else {}
    )

    out: dict = {
        "case_artifact": str(args.case_artifact),
        "truth_csv": str(args.truth_csv),
        "case_total": len(cases),
        "truth_total": len(truth_docs),
        "topics": {},
    }

    # 보조 키 후보: distribution 비교와 simulation 양쪽에 사용
    AUX_FIELDS = [
        "max_primary_rule_score",
        "secondary_evidence_score",
        "audit_evidence_score",
        "corroboration_score",
        "topic_repeat_score",
        "macro_context_score",
        "evidence_count",
        "evidence_diversity",
        "strong_evidence_count",
        "medium_evidence_count",
        "primary_score_sum",
        "secondary_topic_count",
        "macro_context_count",
        "fraud_scenario_tag_count",
        "has_fraud_combo",
        "has_combo_floor",
        "has_approval_bypass_tag",
        "amount_score",
        "control_score",
        "duplicate_or_outflow_score",
        "logic_score",
        "data_integrity_score",
        "intercompany_score",
        "timing_score",
        "behavior_score",
        "repeat_score",
        "base_priority_score",
        "topside_bonus",
        "batch_combo_bonus",
        "weak_evidence_bonus",
        "has_control_failure",
        "has_high_materiality",
        "has_repeat_pattern",
        "rule_count",
        "document_count",
        "row_count",
        "repeat_months",
    ]
    PRIMARY_FIELDS = [
        "topic_score",
        "triage_rank_score",
        "total_amount",
        "rule_count",
        "priority_score",
    ]

    for topic_id in TARGET_TOPICS:
        high_cases = [c for c in cases if topic_score(c, topic_id) >= HIGH_THRESHOLD]
        rows = [extract_features(c, topic_id) for c in high_cases]
        truth_rows = [r for r in rows if r["documents"] & truth_docs]
        nontruth_rows = [r for r in rows if not (r["documents"] & truth_docs)]

        # 전체 truth 문서 (high case에 포함된)
        truth_in_high = set()
        for r in truth_rows:
            truth_in_high |= r["documents"] & truth_docs

        topic_out: dict = {
            "case_count": len(rows),
            "truth_case_count": len(truth_rows),
            "nontruth_case_count": len(nontruth_rows),
            "truth_docs_in_high": len(truth_in_high),
        }

        # 1) 기본 + 보조 키 distribution 비교
        dist: dict = {}
        for field in PRIMARY_FIELDS + AUX_FIELDS:
            tvals = [r[field] for r in truth_rows]
            nvals = [r[field] for r in nontruth_rows]
            dist[field] = {
                "truth": distribution_summary(tvals),
                "nontruth": distribution_summary(nvals),
            }
        topic_out["distributions"] = dist

        # 2) 정렬 키 시뮬레이션
        baseline_key = lambda r: (
            -r["topic_score"],
            -r["triage_rank_score"],
            -r["total_amount"],
            -r["rule_count"],
        )
        sims: list[dict] = []
        baseline = simulate_topN(rows, baseline_key, truth_docs=truth_docs)
        sims.append(
            {
                "label": "baseline (topic_score, triage_rank_score, total_amount, rule_count)",
                "result": baseline,
            }
        )

        # 단일 보조 키를 가장 앞 tiebreaker로 끼우는 경우 (topic_score 다음에 들어감)
        single_aux_candidates = [
            "has_fraud_combo",
            "has_approval_bypass_tag",
            "audit_evidence_score",
            "max_primary_rule_score",
            "evidence_diversity",
            "strong_evidence_count",
            "secondary_topic_count",
            "evidence_count",
            "primary_score_sum",
            "behavior_score",
            "has_control_failure",
            "rule_count",
        ]
        for aux in single_aux_candidates:

            def key_factory(aux_field):
                def k(r):
                    return (
                        -r["topic_score"],
                        -r[aux_field],
                        -r["triage_rank_score"],
                        -r["total_amount"],
                        -r["rule_count"],
                    )

                return k

            res = simulate_topN(rows, key_factory(aux), truth_docs=truth_docs)
            sims.append({"label": f"+{aux} (top tiebreaker)", "result": res})

        # 2-tier 조합
        combo_candidates = [
            ["has_fraud_combo", "audit_evidence_score"],
            ["has_fraud_combo", "max_primary_rule_score"],
            ["has_fraud_combo", "evidence_diversity"],
            ["max_primary_rule_score", "audit_evidence_score"],
            ["audit_evidence_score", "evidence_diversity"],
            ["audit_evidence_score", "secondary_topic_count"],
            ["evidence_diversity", "secondary_topic_count"],
            ["has_fraud_combo", "audit_evidence_score", "evidence_diversity"],
            ["has_fraud_combo", "max_primary_rule_score", "audit_evidence_score"],
            [
                "has_fraud_combo",
                "max_primary_rule_score",
                "audit_evidence_score",
                "evidence_diversity",
            ],
        ]
        for combo in combo_candidates:

            def combo_key_factory(fields):
                def k(r):
                    base = tuple(-r[f] for f in fields)
                    return (
                        (-r["topic_score"],)
                        + base
                        + (-r["triage_rank_score"], -r["total_amount"], -r["rule_count"])
                    )

                return k

            res = simulate_topN(rows, combo_key_factory(combo), truth_docs=truth_docs)
            sims.append({"label": "+" + " + ".join(combo) + " (tiebreakers)", "result": res})

        # 3) 가중 합산 시뮬레이션 (composite score)
        composite_specs = [
            {
                "name": "composite_combo_first",
                "weights": {
                    "has_fraud_combo": 1.0,
                    "audit_evidence_score": 0.6,
                    "max_primary_rule_score": 0.3,
                    "evidence_diversity": 0.05,
                },
            },
            {
                "name": "composite_audit_heavy",
                "weights": {
                    "audit_evidence_score": 1.0,
                    "has_fraud_combo": 0.5,
                    "max_primary_rule_score": 0.3,
                    "evidence_diversity": 0.05,
                },
            },
            {
                "name": "composite_diversity_heavy",
                "weights": {
                    "evidence_diversity": 1.0,
                    "has_fraud_combo": 0.5,
                    "audit_evidence_score": 0.3,
                },
            },
            {
                "name": "composite_balanced",
                "weights": {
                    "has_fraud_combo": 0.5,
                    "audit_evidence_score": 0.3,
                    "max_primary_rule_score": 0.1,
                    "evidence_diversity": 0.05,
                    "secondary_topic_count": 0.03,
                },
            },
        ]
        for spec in composite_specs:
            weights = spec["weights"]

            def make_key(weights):
                def k(r):
                    cs = sum(weights[f] * r[f] for f in weights)
                    return (
                        -r["topic_score"],
                        -cs,
                        -r["triage_rank_score"],
                        -r["total_amount"],
                        -r["rule_count"],
                    )

                return k

            res = simulate_topN(rows, make_key(weights), truth_docs=truth_docs)
            sims.append({"label": f"composite::{spec['name']}", "weights": weights, "result": res})

        topic_out["simulations"] = sims

        # 4) Top200 안에서의 case 분포 (label / scenario coverage)
        sorted_rows_baseline = sorted(rows, key=baseline_key)[:TOP_N_SIMULATION]
        top_scenario_counter: Counter = Counter()
        top_truth_cases = 0
        for r in sorted_rows_baseline:
            inter = r["documents"] & truth_docs
            if inter:
                top_truth_cases += 1
                for d in inter:
                    top_scenario_counter[truth_by_doc.get(d, "?")] += 1
        topic_out["baseline_top200_truth_scenario_counter"] = dict(top_scenario_counter)
        topic_out["baseline_top200_truth_cases"] = top_truth_cases

        # 5) truth case가 baseline Top200 밖에 있는 이유 진단:
        #    같은 topic_score에서 truth vs nontruth가 얼마나 분포하는지
        bucket: dict[float, dict[str, int]] = {}
        for r in rows:
            bucket.setdefault(r["topic_score"], {"truth": 0, "nontruth": 0})
            if r["documents"] & truth_docs:
                bucket[r["topic_score"]]["truth"] += 1
            else:
                bucket[r["topic_score"]]["nontruth"] += 1
        topic_out["topic_score_bucket_counts"] = {
            f"{k:.4f}": v for k, v in sorted(bucket.items(), reverse=True)
        }

        # 6) 전 topic_score 범위 (high+medium+low) cross-band 진단
        #    closing_timing 처럼 high 에 truth 0개일 때 어디서 truth가 발견되는지 확인
        all_topic_cases = [
            (c, topic_score(c, topic_id)) for c in cases if topic_score(c, topic_id) > 0
        ]
        band_counter = {
            "high(>=0.75)": {"truth": 0, "nontruth": 0, "truth_docs": set()},
            "medium(0.4-0.75)": {"truth": 0, "nontruth": 0, "truth_docs": set()},
            "low(0-0.4)": {"truth": 0, "nontruth": 0, "truth_docs": set()},
        }
        for c, ts in all_topic_cases:
            docs = case_documents(c)
            t_inter = docs & truth_docs
            band = (
                "high(>=0.75)" if ts >= 0.75 else "medium(0.4-0.75)" if ts >= 0.4 else "low(0-0.4)"
            )
            if t_inter:
                band_counter[band]["truth"] += 1
                band_counter[band]["truth_docs"] |= t_inter
            else:
                band_counter[band]["nontruth"] += 1
        topic_out["band_distribution"] = {
            k: {
                "truth_cases": v["truth"],
                "nontruth_cases": v["nontruth"],
                "truth_docs": len(v["truth_docs"]),
            }
            for k, v in band_counter.items()
        }

        # 7) high 외 band 에서도 보조 키 시뮬레이션 (전 band 합쳐서 Top200)
        all_rows = [extract_features(c, topic_id) for c, _ in all_topic_cases]
        all_truth_rows = [r for r in all_rows if r["documents"] & truth_docs]
        topic_out["all_band_case_count"] = len(all_rows)
        topic_out["all_band_truth_case_count"] = len(all_truth_rows)

        # baseline: topic_score 우선 (현재 정렬과 동일)
        baseline_all_key = lambda r: (
            -r["topic_score"],
            -r["triage_rank_score"],
            -r["total_amount"],
            -r["rule_count"],
        )
        all_band_sims: list[dict] = []
        all_band_sims.append(
            {
                "label": "baseline (all band, topic_score 우선)",
                "result": simulate_topN(all_rows, baseline_all_key, truth_docs=truth_docs),
            }
        )

        # 보조 키를 'topic_score 가중'에서 분리한 composite (band 무시)
        composite_all_band_specs = [
            {
                "name": "all_band_max_primary_only",
                "weights": {"max_primary_rule_score": 1.0},
            },
            {
                "name": "all_band_audit_only",
                "weights": {"audit_evidence_score": 1.0},
            },
            {
                "name": "all_band_max_primary_+_audit",
                "weights": {"max_primary_rule_score": 1.0, "audit_evidence_score": 0.5},
            },
            {
                "name": "all_band_topic_+_max_primary",
                "weights": {"topic_score": 1.0, "max_primary_rule_score": 0.5},
            },
            {
                "name": "all_band_topic_+_audit",
                "weights": {"topic_score": 1.0, "audit_evidence_score": 0.5},
            },
            {
                "name": "all_band_topic_+_max_primary_+_audit",
                "weights": {
                    "topic_score": 1.0,
                    "max_primary_rule_score": 0.5,
                    "audit_evidence_score": 0.3,
                },
            },
            {
                "name": "all_band_topic_+_combo_+_audit",
                "weights": {
                    "topic_score": 1.0,
                    "has_fraud_combo": 0.3,
                    "audit_evidence_score": 0.3,
                    "max_primary_rule_score": 0.2,
                },
            },
            {
                "name": "all_band_corroboration_heavy",
                "weights": {
                    "topic_score": 0.6,
                    "corroboration_score": 0.5,
                    "audit_evidence_score": 0.3,
                    "max_primary_rule_score": 0.2,
                },
            },
            {
                "name": "all_band_control_corroboration_primary",
                "weights": {
                    "topic_score": 0.4,
                    "control_score": 0.4,
                    "corroboration_score": 0.4,
                    "primary_score_sum_norm": 0.2,  # 정규화 필요 — 코드에서 처리
                },
            },
            {
                "name": "all_band_priority_topic",
                "weights": {
                    "topic_score": 0.5,
                    "base_priority_score": 0.5,
                    "corroboration_score": 0.3,
                },
            },
            {
                "name": "all_band_recall_oriented",
                "weights": {
                    "topic_score": 0.3,
                    "control_score": 0.3,
                    "corroboration_score": 0.4,
                    "topside_bonus": 0.2,
                    "max_primary_rule_score": 0.1,
                    "audit_evidence_score": 0.1,
                },
            },
            {
                "name": "all_band_rule_count_corroboration",
                "weights": {
                    "topic_score": 0.4,
                    "corroboration_score": 0.5,
                    "control_score": 0.3,
                    "base_priority_score": 0.3,
                    "rule_count_norm": 0.2,
                },
            },
        ]
        for spec in composite_all_band_specs:
            weights = spec["weights"]

            def make_key_all(weights):
                def k(r):
                    cs = 0.0
                    for f, w in weights.items():
                        if f == "primary_score_sum_norm":
                            # primary_score_sum 을 0-1 로 클립 (10 이상이면 1)
                            cs += w * min(r["primary_score_sum"] / 10.0, 1.0)
                        elif f == "rule_count_norm":
                            cs += w * min(r["rule_count"] / 10.0, 1.0)
                        else:
                            cs += w * r[f]
                    return (
                        -cs,
                        -r["triage_rank_score"],
                        -r["total_amount"],
                        -r["rule_count"],
                    )

                return k

            res = simulate_topN(all_rows, make_key_all(weights), truth_docs=truth_docs)
            all_band_sims.append(
                {"label": f"composite::{spec['name']}", "weights": weights, "result": res}
            )

        topic_out["all_band_simulations"] = all_band_sims

        # 8) all band distribution: truth vs nontruth (탑band이 비어있는 closing_timing 등)
        if len(all_truth_rows) > 0:
            dist_all: dict = {}
            nontruth_all_rows = [r for r in all_rows if not (r["documents"] & truth_docs)]
            for field in PRIMARY_FIELDS + AUX_FIELDS:
                tvals = [r[field] for r in all_truth_rows]
                nvals = [r[field] for r in nontruth_all_rows]
                dist_all[field] = {
                    "truth": distribution_summary(tvals),
                    "nontruth": distribution_summary(nvals),
                }
            topic_out["all_band_distributions"] = dist_all

        out["topics"][topic_id] = topic_out

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {args.out_json}")


if __name__ == "__main__":
    main()
