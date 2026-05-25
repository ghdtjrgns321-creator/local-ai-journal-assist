"""Evaluate V7 fixed3 manipulation truth recovery with PHASE1-only case queue.

The script uses the cached PHASE1 detector output by default and rebuilds only
the case-level review queue. It does not tune detector thresholds or case
builder settings.
"""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config.settings import get_phase1_case  # noqa: E402
from src.detection.phase1_case_builder import build_phase1_case_result  # noqa: E402
from src.detection.rule_detail_metadata import canonicalize_rule_id  # noqa: E402
from src.models.phase1_case import CaseGroupResult, Phase1CaseResult  # noqa: E402

DATASET_VERSION = "datasynth_manipulation_v7_candidate_fixed3"
TOP_NS = (100, 500, 1_000, 2_000, 5_000, 10_000)
PHASE2_COMPARISON = {
    100: {"phase1": 104, "phase2": 55, "rrf": 103},
    500: {"phase1": 276, "phase2": 185, "rrf": 268},
    1_000: {"phase1": 317, "phase2": 241, "rrf": 324},
    2_000: {"phase1": 364, "phase2": 356, "rrf": 391},
    5_000: {"phase1": 449, "phase2": 433, "rrf": 456},
    10_000: {"phase1": 493, "phase2": 463, "rrf": 498},
}


def _pct(numerator: int | float, denominator: int | float) -> float:
    if not denominator:
        return 0.0
    return round((float(numerator) / float(denominator)) * 100.0, 2)


def _ratio(numerator: int | float, denominator: int | float) -> float:
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator), 2)


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _settings_hash(settings: dict[str, Any]) -> str:
    blob = json.dumps(settings, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _case_documents(case: CaseGroupResult) -> set[str]:
    return {str(doc.document_id) for doc in case.documents if doc.document_id}


def _sorted_cases(phase1: Phase1CaseResult) -> list[CaseGroupResult]:
    return sorted(
        phase1.cases,
        key=lambda case: (
            float(case.composite_sort_score or 0.0),
            float(case.triage_rank_score or 0.0),
            float(case.total_amount or 0.0),
            int(case.rule_count or 0),
        ),
        reverse=True,
    )


def _truth_by_scenario(truth_df: pd.DataFrame) -> dict[str, set[str]]:
    grouped: dict[str, set[str]] = {}
    for scenario, group in truth_df.groupby("manipulation_scenario", dropna=False):
        grouped[str(scenario)] = set(group["document_id"].dropna().astype(str).unique())
    return grouped


def _rank_maps(cases: list[CaseGroupResult]) -> tuple[dict[str, int], dict[str, list[int]]]:
    first_rank: dict[str, int] = {}
    all_ranks: dict[str, list[int]] = defaultdict(list)
    for rank, case in enumerate(cases, start=1):
        for doc_id in _case_documents(case):
            all_ranks[doc_id].append(rank)
            first_rank.setdefault(doc_id, rank)
    return first_rank, dict(all_ranks)


def _top_n_recovery(
    cases: list[CaseGroupResult],
    truth_docs: set[str],
    *,
    total_docs: int,
    covered_truth_count: int,
) -> list[dict[str, Any]]:
    prevalence = len(truth_docs) / total_docs if total_docs else 0.0
    rows: list[dict[str, Any]] = []
    top_values = [n for n in TOP_NS if n <= len(cases)]
    if len(cases) not in top_values:
        top_values.append(len(cases))
    for top_n in top_values:
        docs: set[str] = set()
        for case in cases[:top_n]:
            docs.update(_case_documents(case))
        caught = len(docs & truth_docs)
        precision = caught / len(docs) if docs else 0.0
        rows.append(
            {
                "top_n_cases": int(top_n),
                "covered_unique_documents": len(docs),
                "caught_truth_documents": caught,
                "doc_recall_original_pct": _pct(caught, len(truth_docs)),
                "doc_recall_queue_entered_pct": _pct(caught, covered_truth_count),
                "doc_precision_pct": round(precision * 100.0, 2),
                "random_enrichment_multiple": round(precision / prevalence, 2) if prevalence else 0.0,
            }
        )
    return rows


def _scenario_matrix(
    scenario_docs: dict[str, set[str]],
    covered_truth_docs: set[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scenario in sorted(scenario_docs):
        docs = scenario_docs[scenario]
        covered = len(docs & covered_truth_docs)
        uncovered = len(docs - covered_truth_docs)
        rows.append(
            {
                "manipulation_scenario": scenario,
                "truth_documents": len(docs),
                "queue_entered_documents": covered,
                "queue_unentered_documents": uncovered,
                "queue_unentered_rate_pct": _pct(uncovered, len(docs)),
            }
        )
    return rows


def _scenario_rank_distribution(
    scenario_docs: dict[str, set[str]],
    first_rank: dict[str, int],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scenario in sorted(scenario_docs):
        docs = scenario_docs[scenario]
        ranks = sorted(first_rank[doc_id] for doc_id in docs if doc_id in first_rank)
        row = {
            "manipulation_scenario": scenario,
            "truth_documents": len(docs),
            "ranked_truth_documents": len(ranks),
            "unranked_truth_documents": len(docs) - len(ranks),
            "mean_rank": round(sum(ranks) / len(ranks), 1) if ranks else None,
            "median_rank": ranks[len(ranks) // 2] if ranks else None,
            "min_rank": min(ranks) if ranks else None,
            "max_rank": max(ranks) if ranks else None,
        }
        for top_n in (100, 500, 1_000, 2_000):
            caught = sum(1 for rank in ranks if rank <= top_n)
            row[f"top_{top_n}_caught"] = caught
            row[f"top_{top_n}_recall_original_pct"] = _pct(caught, len(docs))
            row[f"top_{top_n}_recall_queue_entered_pct"] = _pct(caught, len(ranks))
        rows.append(row)
    return rows


def _rule_contribution_from_cases(
    cases: list[CaseGroupResult],
    truth_docs: set[str],
) -> list[dict[str, Any]]:
    by_rule: dict[str, set[str]] = defaultdict(set)
    for case in cases:
        case_truth_docs = _case_documents(case) & truth_docs
        if not case_truth_docs:
            continue
        for hit in case.raw_rule_hits:
            if str(hit.document_id) in truth_docs:
                by_rule[canonicalize_rule_id(hit.rule_id)].add(str(hit.document_id))
    return [
        {
            "rule_id": rule_id,
            "queue_truth_documents_hit": len(docs),
            "queue_truth_recall_original_pct": _pct(len(docs), len(truth_docs)),
        }
        for rule_id, docs in sorted(by_rule.items())
    ]


def _raw_rule_hits_from_details(
    df: pd.DataFrame,
    results: list[Any],
    truth_docs: set[str],
) -> list[dict[str, Any]]:
    truth_doc_series = df["document_id"].astype(str)
    truth_mask = truth_doc_series.isin(truth_docs)
    by_rule: dict[str, set[str]] = defaultdict(set)
    for result in results:
        details = getattr(result, "details", None)
        if details is None or not hasattr(details, "columns"):
            continue
        for col in details.columns:
            rule_id = canonicalize_rule_id(str(col))
            series = pd.to_numeric(details[col], errors="coerce").fillna(0)
            hit_docs = truth_doc_series[truth_mask & series.ne(0)]
            if not hit_docs.empty:
                by_rule[rule_id].update(hit_docs.astype(str).unique())
    return [
        {
            "rule_id": rule_id,
            "raw_truth_documents_hit": len(docs),
            "raw_truth_recall_original_pct": _pct(len(docs), len(truth_docs)),
        }
        for rule_id, docs in sorted(by_rule.items())
    ]


def _yearly_top_1000(
    truth_df: pd.DataFrame,
    first_rank: dict[str, int],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for year, group in truth_df.groupby("fiscal_year", dropna=False):
        docs = set(group["document_id"].dropna().astype(str).unique())
        caught = sum(1 for doc_id in docs if first_rank.get(doc_id, 10**12) <= 1_000)
        rows.append(
            {
                "fiscal_year": str(year),
                "truth_documents": len(docs),
                "top_1000_caught_truth_documents": caught,
                "doc_recall_original_pct": _pct(caught, len(docs)),
            }
        )
    return rows


def _load_ts13(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    truth_df = pd.read_csv(args.truth, dtype=str, low_memory=False)
    truth_docs = set(truth_df["document_id"].dropna().astype(str).unique())
    scenario_docs = _truth_by_scenario(truth_df)

    cache = pickle.loads(args.use_cache.read_bytes())
    df = cache["df"]
    results = cache["results"]
    settings = get_phase1_case()
    phase1_source = "rebuilt_from_detector_cache"
    if args.phase1_case_result and args.phase1_case_result.exists():
        phase1 = pickle.loads(args.phase1_case_result.read_bytes())
        phase1_source = _rel(args.phase1_case_result)
    else:
        phase1 = build_phase1_case_result(
            df,
            results,
            company_id="_anonymous",
            batch_id=None,
            dataset_id=DATASET_VERSION,
            phase1_case_config=settings,
        )
    cases = _sorted_cases(phase1)
    first_rank, all_ranks = _rank_maps(cases)
    covered_truth_docs = truth_docs & set(first_rank)
    uncovered_truth_docs = truth_docs - set(first_rank)
    total_docs = int(df["document_id"].nunique())

    top_n_recovery = _top_n_recovery(
        cases,
        truth_docs,
        total_docs=total_docs,
        covered_truth_count=len(covered_truth_docs),
    )
    ts13 = _load_ts13(args.ts13_json)
    false_positive_docs = len(set(first_rank) - truth_docs)
    queue_docs = len(set(first_rank))

    payload = {
        "metadata": {
            "dataset_version": DATASET_VERSION,
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "truth_labels_used_for": "coverage measurement only; not threshold fitting",
            "phase1_settings_source": "config/settings.py get_phase1_case default",
            "phase1_settings_hash": _settings_hash(settings),
            "cache_path": _rel(args.use_cache),
            "cache_sha256": _hash_file(args.use_cache),
            "truth_path": _rel(args.truth),
            "truth_sha256": _hash_file(args.truth),
            "ts13_json_path": _rel(args.ts13_json) if args.ts13_json else None,
            "phase1_case_result_source": phase1_source,
            "phase1_case_schema_version": phase1.schema_version,
            "phase1_case_run_id": phase1.run_id,
        },
        "inputs": {
            "journal_rows": int(len(df)),
            "journal_documents": total_docs,
            "truth_documents": len(truth_docs),
            "phase1_case_count": len(cases),
        },
        "validation": {
            "scenario_truth_sum": sum(len(docs) for docs in scenario_docs.values()),
            "queue_entered_truth_documents": len(covered_truth_docs),
            "queue_unentered_truth_documents": len(uncovered_truth_docs),
            "queue_entered_plus_unentered": len(covered_truth_docs) + len(uncovered_truth_docs),
            "recall_ceiling_pct": _pct(len(covered_truth_docs), len(truth_docs)),
            "top_n_monotonic_non_decreasing": all(
                left["caught_truth_documents"] <= right["caught_truth_documents"]
                for left, right in zip(top_n_recovery, top_n_recovery[1:], strict=False)
            ),
            "scenario_ranked_sum": sum(
                row["ranked_truth_documents"] for row in _scenario_rank_distribution(scenario_docs, first_rank)
            ),
            "phase1_top_100_recall_guard_pct": next(
                row["doc_recall_original_pct"] for row in top_n_recovery if row["top_n_cases"] == 100
            ),
            "phase1_top_1000_recall_guard_pct": next(
                row["doc_recall_original_pct"] for row in top_n_recovery if row["top_n_cases"] == 1_000
            ),
            "ts13_expected_uncovered_documents": (
                ts13.get("validation", {}).get("uncovered_truth_doc_count") if ts13 else None
            ),
        },
        "scenario_distribution": _scenario_matrix(scenario_docs, covered_truth_docs),
        "fn_diagnosis": {
            "uncovered_truth_documents": len(uncovered_truth_docs),
            "uncovered_document_ids": sorted(uncovered_truth_docs),
            "unapplied_rule_classification": ts13.get("unapplied_rule_classification") if ts13 else None,
            "common_characteristics": ts13.get("common_characteristics") if ts13 else None,
            "line_amount": ts13.get("line_amount") if ts13 else None,
            "summary": (
                "TS-13 corrected the initial no-rule-hit hypothesis: all 80 documents had some raw/review "
                "PHASE1 signal, but did not pass row/case seed priority into the review queue."
            ),
        },
        "top_n_recovery": top_n_recovery,
        "scenario_rank_distribution": _scenario_rank_distribution(scenario_docs, first_rank),
        "truth_rank_positions": [
            {
                "document_id": doc_id,
                "review_rank": first_rank.get(doc_id),
                "all_review_ranks": all_ranks.get(doc_id, []),
                "manipulation_scenario": str(
                    truth_df.loc[truth_df["document_id"].astype(str).eq(doc_id), "manipulation_scenario"].iloc[0]
                ),
            }
            for doc_id in sorted(truth_docs)
        ],
        "rule_contribution": {
            "queue_case_raw_rule_hits": _rule_contribution_from_cases(cases, truth_docs),
            "detector_raw_detail_hits": _raw_rule_hits_from_details(df, results, truth_docs),
        },
        "false_positive_volume": {
            "queue_unique_documents": queue_docs,
            "queue_truth_documents": len(covered_truth_docs),
            "potential_false_positive_documents": false_positive_docs,
            "potential_false_positive_rate_pct": _pct(false_positive_docs, queue_docs),
            "interpretation": (
                "Informational only. Normal documents in the PHASE1 review queue are audit review candidates, "
                "not fraud allegations."
            ),
        },
        "yearly_top_1000": _yearly_top_1000(truth_df, first_rank),
        "phase2_comparison": [
            {
                "top_n_cases": top_n,
                "phase1_only_caught": values["phase1"],
                "phase1_only_recall_pct": _pct(values["phase1"], len(truth_docs)),
                "phase2_only_caught": values["phase2"],
                "phase2_only_recall_pct": _pct(values["phase2"], len(truth_docs)),
                "rrf_caught": values["rrf"],
                "rrf_recall_pct": _pct(values["rrf"], len(truth_docs)),
                "rrf_minus_phase1_pct_points": round(
                    _pct(values["rrf"], len(truth_docs)) - _pct(values["phase1"], len(truth_docs)),
                    2,
                ),
            }
            for top_n, values in PHASE2_COMPARISON.items()
        ],
    }
    _validate(payload)
    return payload


def _validate(payload: dict[str, Any]) -> None:
    checks = payload["validation"]
    if checks["scenario_truth_sum"] != 620:
        raise ValueError(f"scenario truth sum mismatch: {checks['scenario_truth_sum']}")
    if checks["queue_entered_plus_unentered"] != 620:
        raise ValueError("queue entered + unentered truth count must equal 620")
    if checks["queue_entered_truth_documents"] != 540 or checks["queue_unentered_truth_documents"] != 80:
        raise ValueError("queue truth split must match TS-13 540/80")
    if not checks["top_n_monotonic_non_decreasing"]:
        raise ValueError("TOP N recovery is not monotonic")
    if checks["scenario_ranked_sum"] != 540:
        raise ValueError(f"scenario ranked sum mismatch: {checks['scenario_ranked_sum']}")
    top100 = checks["phase1_top_100_recall_guard_pct"]
    if not 16.27 <= float(top100) <= 17.27:
        raise ValueError(f"TOP 100 recall guard failed: {top100}")
    top1000 = checks["phase1_top_1000_recall_guard_pct"]
    if round(float(top1000), 2) != 51.13:
        raise ValueError(f"TOP 1000 recall guard failed: {top1000}")


def _md_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(value) for value in row) + " |")
    return "\n".join(lines)


def _write_doc(payload: dict[str, Any], path: Path) -> None:
    top_rows = payload["top_n_recovery"]
    validation = payload["validation"]
    inputs = payload["inputs"]
    scenario_rows = payload["scenario_distribution"]
    rank_rows = payload["scenario_rank_distribution"]
    rule_rows = payload["rule_contribution"]["queue_case_raw_rule_hits"]
    raw_rule_rows = payload["rule_contribution"]["detector_raw_detail_hits"]
    fp = payload["false_positive_volume"]

    doc = [
        "# Phase1 Detection 결과 - V7 fixed3 manipulation truth",
        "",
        "> **PHASE1 역할 원칙**: PHASE1은 `fraud` 확정 단계가 아니라 감사인이 검토할 review queue를 만드는 단계다. 이 문서의 truth 기반 수치는 합성 데이터(DataSynth) 한정의 informational 측정이며, PHASE1 설정 변경이나 threshold fitting에 사용하지 않는다.",
        "",
        "> **단위 정책 (TS-12)**: 외부 KPI는 전표(document) 단위로만 보고한다. case 수는 감사인 검토 UI의 운영 단위이며 recall/precision의 분모로 쓰지 않는다.",
        "",
        "## 0. 한눈에 보는 결론",
        "",
        f"- Truth 전표: **{inputs['truth_documents']:,}** / 전체 전표: **{inputs['journal_documents']:,}** / 전체 row: **{inputs['journal_rows']:,}**",
        f"- PHASE1 review queue case: **{inputs['phase1_case_count']:,}**",
        f"- 큐 진입 truth 전표: **{validation['queue_entered_truth_documents']:,}** / 큐 미진입 truth 전표: **{validation['queue_unentered_truth_documents']:,}**",
        f"- PHASE1 단독 recall ceiling: **{validation['recall_ceiling_pct']:.2f}%**",
        f"- TOP 100 recall: **{validation['phase1_top_100_recall_guard_pct']:.2f}%** / TOP 1,000 recall: **{validation['phase1_top_1000_recall_guard_pct']:.2f}%**",
        "",
        "## 1. 데이터 / 입력 / 실행 환경",
        "",
        _md_table(
            ["항목", "값"],
            [
                ["데이터셋", payload["metadata"]["dataset_version"]],
                ["cache", f"`{payload['metadata']['cache_path']}`"],
                ["truth", f"`{payload['metadata']['truth_path']}`"],
                ["settings", "`config/settings.py` default `get_phase1_case()`"],
                ["settings hash", f"`{payload['metadata']['phase1_settings_hash'][:16]}`"],
                ["run timestamp", f"`{payload['metadata']['generated_at']}`"],
            ],
        ),
        "",
        "Detector는 재실행하지 않았다. PHASE2 문서 작성 때 보존된 `stage7_phase1_case_result.pkl` case builder output을 우선 재사용했고, 없을 때만 기존 cache의 PHASE1 detector output으로 case builder를 재구성한다.",
        "",
        "## 2. 시나리오별 truth 분포",
        "",
        _md_table(
            ["시나리오", "truth", "큐 진입", "큐 미진입", "미진입률"],
            [
                [
                    row["manipulation_scenario"],
                    row["truth_documents"],
                    row["queue_entered_documents"],
                    row["queue_unentered_documents"],
                    f"{row['queue_unentered_rate_pct']:.2f}%",
                ]
                for row in scenario_rows
            ],
        ),
        "",
        "## 3. 미탐(FN) 진단",
        "",
        "TS-13 기준과 동일하게 큐 미진입 truth 전표는 **80건**이다. 다만 최초의 \"어떤 룰도 hit하지 않음\" 가설은 TS-13에서 정정되었다. 80건 모두 raw/review PHASE1 신호는 있었지만, row risk band 또는 case seed priority가 낮아 case builder 진입 조건을 넘지 못했다.",
        "",
        _md_table(
            ["분류", "건수", "해석"],
            [
                ["(a) 룰 부재", 0, "80건 모두 어떤 형태로든 PHASE1 raw/review score가 있었다."],
                ["(b) 임계값/seed 미달", 80, "raw 신호는 있으나 case seed 조건을 넘지 못했다."],
                ["(c) 데이터 결손", 0, "주요 입력 컬럼 전체 결손으로 평가 불가능한 패턴은 확인되지 않았다."],
            ],
        ),
        "",
        "TS-13 공통 특성 요약: P2P/O2C, automated/recurring source, 고액 전표에 미진입 80건이 집중된다. 특히 5억원 초과 전표가 71건(88.75%)이다. 원문 raw 분석은 `artifacts/ts13_uncovered_truth_80_analysis.json`과 `artifacts/ts13_recovery_path_evaluation.md`를 참조한다.",
        "",
        "## 4. PHASE1 단독 큐 TOP N 회수율",
        "",
        _md_table(
            ["검토 case", "cover 전표", "잡은 truth", "recall/620", "recall/540", "precision", "무작위 대비"],
            [
                [
                    row["top_n_cases"],
                    row["covered_unique_documents"],
                    row["caught_truth_documents"],
                    f"{row['doc_recall_original_pct']:.2f}%",
                    f"{row['doc_recall_queue_entered_pct']:.2f}%",
                    f"{row['doc_precision_pct']:.2f}%",
                    f"{row['random_enrichment_multiple']:.2f}배",
                ]
                for row in top_rows
            ],
        ),
        "",
        "## 5. 시나리오별 회수 위치 분포",
        "",
        _md_table(
            ["시나리오", "ranked", "unranked", "평균 rank", "중앙값", "최소", "최대", "TOP100", "TOP500", "TOP1000", "TOP2000"],
            [
                [
                    row["manipulation_scenario"],
                    row["ranked_truth_documents"],
                    row["unranked_truth_documents"],
                    row["mean_rank"],
                    row["median_rank"],
                    row["min_rank"],
                    row["max_rank"],
                    row["top_100_caught"],
                    row["top_500_caught"],
                    row["top_1000_caught"],
                    row["top_2000_caught"],
                ]
                for row in rank_rows
            ],
        ),
        "",
        "상위권에 가장 잘 잡히는 축은 suspense account abuse와 expense capitalization 쪽이다. fictitious entry는 일부가 TOP 100에 강하게 잡히지만 32건이 큐 미진입이고, embezzlement concealment와 unusual timing은 큐 진입 후에도 상대적으로 하위 rank에 묻힌다.",
        "",
        "## 6. 룰별 truth 기여도 (보조)",
        "",
        "아래 표는 queue case 안의 `raw_rule_hits` 기준이다. detector raw detail 기준은 JSON의 `rule_contribution.detector_raw_detail_hits`에 별도 보존했다.",
        "",
        _md_table(
            ["룰", "queue truth hit", "recall/620"],
            [
                [row["rule_id"], row["queue_truth_documents_hit"], f"{row['queue_truth_recall_original_pct']:.2f}%"]
                for row in sorted(rule_rows, key=lambda item: (-item["queue_truth_documents_hit"], item["rule_id"]))
            ],
        ),
        "",
        f"Detector raw detail 기준으로는 {len(raw_rule_rows)}개 rule id가 truth 전표에 하나 이상 hit했다. 이 수치는 case seed 진입 전 raw 신호 측정이므로 운영 queue 기여도와 구분해야 한다.",
        "",
        "## 7. 과탐 양 추정 (보조)",
        "",
        _md_table(
            ["항목", "값"],
            [
                ["큐 진입 unique 전표", f"{fp['queue_unique_documents']:,}"],
                ["그 중 truth 전표", f"{fp['queue_truth_documents']:,}"],
                ["잠재 과탐 전표", f"{fp['potential_false_positive_documents']:,}"],
                ["잠재 과탐률", f"{fp['potential_false_positive_rate_pct']:.2f}%"],
            ],
        ),
        "",
        "이는 운영 부담 지표일 뿐이다. 정상 전표가 PHASE1 큐에 있다고 곧장 부정 의심이나 확정 위반을 뜻하지 않는다. 감사인은 review 후 정상 dismiss를 수행한다.",
        "",
        "## 8. 연도별 비교",
        "",
        _md_table(
            ["연도", "truth", "TOP 1,000 회수", "doc recall"],
            [
                [
                    row["fiscal_year"],
                    row["truth_documents"],
                    row["top_1000_caught_truth_documents"],
                    f"{row['doc_recall_original_pct']:.2f}%",
                ]
                for row in payload["yearly_top_1000"]
            ],
        ),
        "",
        "## 9. PHASE2 / RRF 와 비교",
        "",
        "비교 기준은 `docs/DETECTION_RESULTS_MANIPULATION_V7_FIXED3_PHASE2.md` §3의 3개 큐 비교 표다. 본 문서는 PHASE1 단독 큐 detail을 전표 단위로 확장한 별도 산출물이다.",
        "",
        _md_table(
            ["TOP N", "PHASE1 단독", "PHASE2 단독", "통합 RRF", "RRF-PHASE1"],
            [
                [
                    row["top_n_cases"],
                    f"{row['phase1_only_caught']} ({row['phase1_only_recall_pct']:.2f}%)",
                    f"{row['phase2_only_caught']} ({row['phase2_only_recall_pct']:.2f}%)",
                    f"{row['rrf_caught']} ({row['rrf_recall_pct']:.2f}%)",
                    f"{row['rrf_minus_phase1_pct_points']:+.2f}%p",
                ]
                for row in payload["phase2_comparison"]
            ],
        ),
        "",
        "RRF는 TOP 1,000 이후부터 PHASE1 단독보다 약간 우세하며, TOP 2,000에서 차이가 가장 크다. 다만 현재 RRF는 PHASE1 case-bound queue이므로 TS-13의 큐 미진입 80건 자체는 회수하지 못한다.",
        "",
        "## 10. CONTRACT_V3 와의 의미 차이",
        "",
        "`docs/DETECTION_RESULTS_CONTRACT_V3.md`는 `rule_truth_*`를 기준으로 detector가 계약 spec대로 작동하는지 검증한다. 그 문서의 PASS는 룰 계약 기준의 recall 100%, FP 0, FN 0을 의미한다.",
        "",
        "반면 본 문서는 `manipulated_entry_truth.csv`의 의도 주입 부정 전표 620건이 PHASE1 review queue에서 얼마나 회수되는지 측정한다. 이 truth는 특정 룰의 정답이 아니라 시나리오형 조작 전표이므로, 현재 PHASE1 단독 ceiling은 540/620 = 87.10%다. 두 척도는 서로 모순되지 않는다.",
        "",
        "## 11. 한계 + 다음 단계",
        "",
        "- 본 결과는 V7 fixed3 합성 데이터 한정 측정이다. 실데이터 일반화는 보장하지 않는다.",
        "- truth label은 측정에만 사용했고 PHASE1 detector threshold, case builder, 32 룰 카탈로그, `config/phase1_case.yaml`은 변경하지 않았다.",
        "- 미진입 80건 회수 경로 결정은 TS-13 별도 sprint 범위다. 본 문서는 현재 PHASE1 단독 설정의 회수 가능 ceiling을 명시하는 데 그친다.",
        "- 다음 검증은 PHASE2 단독 document queue와 RRF 통합 큐의 운영 비용/효익 비교다.",
        "",
    ]
    path.write_text("\n".join(doc), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--use-cache", type=Path, required=True)
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--output-doc", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument(
        "--phase1-case-result",
        type=Path,
        default=ROOT / "artifacts" / "stage7_phase1_case_result.pkl",
    )
    parser.add_argument(
        "--ts13-json",
        type=Path,
        default=ROOT / "artifacts" / "ts13_uncovered_truth_80_analysis.json",
    )
    args = parser.parse_args()

    payload = evaluate(args)
    args.output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_doc(payload, args.output_doc)
    print(json.dumps(payload["validation"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
