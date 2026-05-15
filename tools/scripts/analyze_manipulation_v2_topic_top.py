"""Topic별 Top N truth 진입 + scenario별 진입을 case artifact에서 계산한다.

v1 문서(DETECTION_RESULTS_MANIPULATION.md) 형식과 동일한 통계를 v2 산출물에서 재현하기 위한 단발성 분석 스크립트.

분류 규칙(v1 ranking_analysis와 동일):
- case의 `topic_scores[topic_id]` > 0 이면 그 topic에 포함 (한 case가 여러 topic에 동시 포함 가능)
- high case = `topic_scores[topic_id] >= 0.75`
- topic 내 정렬: topic_score desc, triage_rank_score desc, total_amount desc, rule_count desc
"""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

TOPIC_LABELS = {
    "ledger_integrity": "원장기록·데이터정합성",
    "approval_control": "승인·권한·업무분장 통제",
    "closing_timing": "결산·기간귀속·입력시점",
    "account_logic": "계정분류·거래실질 불일치",
    "duplicate_outflow": "중복·상계·자금유출",
    "intercompany_cycle": "관계사·내부거래·순환구조",
    "revenue_statistical": "수익·금액·모집단 통계 이상",
}

EXPECTED_TOPIC = {
    "approval_sod_bypass": "approval_control",
    "circular_related_party_transaction": "intercompany_cycle",
    "embezzlement_concealment": "duplicate_outflow",
    "fictitious_entry": "revenue_statistical",
    "period_end_adjustment_manipulation": "closing_timing",
    "unusual_timing_manipulation": "closing_timing",
}

TOP_NS = (10, 50, 100, 200)
HIGH_THRESHOLD = 0.75


def case_documents(case: dict) -> set[str]:
    docs: set[str] = set()
    for hit in case.get("raw_rule_hits", []):
        doc_id = hit.get("document_id")
        if doc_id:
            docs.add(str(doc_id))
    for d in case.get("documents", []) or []:
        if isinstance(d, str):
            docs.add(d)
        elif isinstance(d, dict) and d.get("document_id"):
            docs.add(str(d["document_id"]))
    return docs


def topic_score(case: dict, topic_id: str) -> float:
    scores = case.get("topic_scores") or {}
    val = scores.get(topic_id, 0.0)
    try:
        return float(val) if val is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def topic_sort_key(case: dict, topic_id: str) -> tuple:
    # §9.3 composite_sort_score 우선. case JSON 에 composite_sort_score 가 없으면
    # baseline (topic_score) 으로 폴백.
    composite = case.get("composite_sort_score")
    if composite is None:
        composite = topic_score(case, topic_id)
    triage = case.get("triage_rank_score") or 0.0
    amount = case.get("total_amount") or 0.0
    rule_count = case.get("rule_count") or 0
    return (-float(composite), -float(triage), -float(amount), -int(rule_count))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-artifact", type=Path, required=True)
    parser.add_argument("--truth-csv", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    artifact = json.loads(args.case_artifact.read_text(encoding="utf-8"))
    cases = artifact.get("cases", [])

    truth_df = pd.read_csv(args.truth_csv, dtype=str, low_memory=False)
    truth_docs = set(truth_df["document_id"].dropna().astype(str).unique())

    scenario_col = (
        "manipulation_scenario"
        if "manipulation_scenario" in truth_df.columns
        else ("scenario" if "scenario" in truth_df.columns else "fraud_scenario")
    )
    scenario_truth: dict[str, set[str]] = defaultdict(set)
    if scenario_col in truth_df.columns:
        for scenario, group in truth_df.groupby(scenario_col):
            scenario_truth[str(scenario)] = set(group["document_id"].dropna().astype(str).unique())

    # topic별 분류 (topic_scores > 0 인 모든 topic에 포함)
    by_topic: dict[str, list[dict]] = defaultdict(list)
    for c in cases:
        for topic_id in TOPIC_LABELS:
            if topic_score(c, topic_id) > 0:
                by_topic[topic_id].append(c)

    topic_metrics = []
    sorted_by_topic: dict[str, list[dict]] = {}
    for topic_id, label in TOPIC_LABELS.items():
        topic_cases = by_topic.get(topic_id, [])
        topic_cases = sorted(topic_cases, key=lambda c: topic_sort_key(c, topic_id))
        sorted_by_topic[topic_id] = topic_cases

        topic_docs: set[str] = set()
        for c in topic_cases:
            topic_docs |= case_documents(c)

        high_cases = [c for c in topic_cases if topic_score(c, topic_id) >= HIGH_THRESHOLD]
        high_docs: set[str] = set()
        for c in high_cases:
            high_docs |= case_documents(c)

        row = {
            "topic_id": topic_id,
            "label": label,
            "topic_case_count": len(topic_cases),
            "topic_truth_docs": len(topic_docs & truth_docs),
            "high_case_count": len(high_cases),
            "high_truth_docs": len(high_docs & truth_docs),
        }
        for n in TOP_NS:
            cum_docs: set[str] = set()
            for c in topic_cases[:n]:
                cum_docs |= case_documents(c)
            row[f"top{n}_truth_docs"] = len(cum_docs & truth_docs)
        topic_metrics.append(row)

    scenario_metrics = []
    for scenario, docs in scenario_truth.items():
        exp_topic = EXPECTED_TOPIC.get(scenario)
        exp_label = TOPIC_LABELS.get(exp_topic, exp_topic or "-")
        tcases = sorted_by_topic.get(exp_topic, []) if exp_topic else []

        topic_docs_total: set[str] = set()
        for c in tcases:
            topic_docs_total |= case_documents(c)
        high_topic_docs: set[str] = set()
        if exp_topic:
            for c in tcases:
                if topic_score(c, exp_topic) >= HIGH_THRESHOLD:
                    high_topic_docs |= case_documents(c)

        row = {
            "scenario": scenario,
            "expected_topic": exp_topic,
            "expected_topic_label": exp_label,
            "truth_docs": len(docs),
            "expected_topic_docs": len(topic_docs_total & docs),
            "high_truth": len(high_topic_docs & docs),
        }
        for n in TOP_NS:
            cum_docs: set[str] = set()
            for c in tcases[:n]:
                cum_docs |= case_documents(c)
            row[f"top{n}"] = len(cum_docs & docs)
        scenario_metrics.append(row)

    # 전체 case 누적 Top N (exposure_rank 기준)
    cases_sorted = sorted(
        cases,
        key=lambda c: (
            c.get("exposure_rank") if c.get("exposure_rank") is not None else 10**9,
            -float(c.get("priority_score") or 0.0),
        ),
    )
    global_top = []
    for n in (10, 50, 100, 500, 1000):
        docs_set: set[str] = set()
        for c in cases_sorted[:n]:
            docs_set |= case_documents(c)
        global_top.append(
            {
                "top_n_cases": n,
                "case_docs": len(docs_set),
                "truth_docs": len(docs_set & truth_docs),
            }
        )

    # priority_band 분포 (전체 case 기준)
    band_metrics = []
    for band in ("high", "medium", "low"):
        bcases = [c for c in cases if (c.get("priority_band") or "").lower() == band]
        bdocs: set[str] = set()
        for c in bcases:
            bdocs |= case_documents(c)
        band_metrics.append(
            {
                "band": band,
                "case_count": len(bcases),
                "case_docs": len(bdocs),
                "truth_docs": len(bdocs & truth_docs),
            }
        )

    # topic_id:band 기준 score band (v1 문서의 closing_timing:low 등)
    score_band_summary = []
    for topic_id in TOPIC_LABELS:
        for level, lo, hi in (
            ("high", HIGH_THRESHOLD, 1.01),
            ("medium", 0.4, HIGH_THRESHOLD),
            ("low", 0.0, 0.4),
        ):
            members = [
                c
                for c in cases
                if lo < topic_score(c, topic_id) < hi
                or (level == "high" and topic_score(c, topic_id) >= lo)
            ]
            # 위 조건이 헷갈리니 다시: high=score>=0.75, medium=0.4<=score<0.75, low=0<score<0.4
            members = [
                c
                for c in cases
                if (
                    (level == "high" and topic_score(c, topic_id) >= HIGH_THRESHOLD)
                    or (level == "medium" and 0.4 <= topic_score(c, topic_id) < HIGH_THRESHOLD)
                    or (level == "low" and 0.0 < topic_score(c, topic_id) < 0.4)
                )
            ]
            if not members:
                continue
            mdocs: set[str] = set()
            for c in members:
                mdocs |= case_documents(c)
            score_band_summary.append(
                {
                    "band": f"{topic_id}:{level}",
                    "case_count": len(members),
                    "truth_docs": len(mdocs & truth_docs),
                }
            )

    # exposure_rank 기준 상위 truth case 20개
    top_truth_cases = []
    for c in cases_sorted:
        docs = case_documents(c) & truth_docs
        if not docs:
            continue
        top_truth_cases.append(
            {
                "exposure_rank": c.get("exposure_rank"),
                "case_id": c.get("case_id"),
                "primary_topic": c.get("primary_topic"),
                "primary_theme": c.get("primary_theme"),
                "priority_band": c.get("priority_band"),
                "priority_score": c.get("priority_score"),
                "truth_doc_count": len(docs),
                "truth_docs_sample": sorted(docs)[:5],
            }
        )
        if len(top_truth_cases) >= 20:
            break

    out = {
        "case_artifact": str(args.case_artifact),
        "truth_csv": str(args.truth_csv),
        "case_count": len(cases),
        "truth_total": len(truth_docs),
        "global_top_capture": global_top,
        "priority_band_metrics": band_metrics,
        "topic_metrics": topic_metrics,
        "scenario_metrics": scenario_metrics,
        "score_band_summary": score_band_summary,
        "top_truth_cases": top_truth_cases,
    }
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
