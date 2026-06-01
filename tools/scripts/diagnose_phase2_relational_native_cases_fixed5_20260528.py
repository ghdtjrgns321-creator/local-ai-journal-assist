"""Diagnose fixed5 PHASE2 relational native edge cases.

The output is aggregate-only: sub_rule distributions, TOP100/TOP500 composition,
and row-score-to-edge-case gap reasons. Raw document IDs stay in memory and are
not written to the artifact.
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import pickle
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.models.phase2_case import RelationalCase
from src.services.phase2_case_set_orchestrator import build_phase2_case_set
from src.services.phase2_family_policy import build_relational_policy_summary
from tools.scripts.measure_phase2_native_cases_fixed5_20260528 import (
    BATCH_ID,
    CASE_INPUT_PKL,
    DATASET_NAME,
    _case_documents,
    _load_case_input,
    _load_truth,
    _run_rule_detector,
    _sorted_cases,
)

OUT_JSON = ROOT / "artifacts" / "phase2_relational_native_case_diagnostic_fixed5_20260528.json"
FORBIDDEN_IDENTIFIER_KEYS = {
    "document_id",
    "document_ids",
    "raw_document_id",
    "raw_document_ids",
    "row_id",
    "row_ids",
    "raw_row_id",
    "raw_row_ids",
    "index_label",
    "raw_index_label",
    "edge_a",
    "edge_b",
    "raw_edge_a",
    "raw_edge_b",
    "phase2_case_id",
    "phase2_case_ids",
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _print(message: str) -> None:
    print(f"[{_now_iso()}] {message}", flush=True)


def _topn_sub_rule_counts(cases: list[RelationalCase], top_n: int) -> dict[str, int]:
    counts = Counter(case.sub_rule for case in cases[:top_n])
    return dict(sorted(counts.items()))


def _numeric_distribution(values: list[float | int]) -> dict[str, Any]:
    clean = [float(value) for value in values if np.isfinite(float(value))]
    if not clean:
        return {"count": 0, "min": None, "p50": None, "p90": None, "p95": None, "max": None}
    arr = np.asarray(clean, dtype=float)
    return {
        "count": int(len(arr)),
        "min": float(arr.min()),
        "p50": float(np.quantile(arr, 0.50)),
        "p90": float(np.quantile(arr, 0.90)),
        "p95": float(np.quantile(arr, 0.95)),
        "max": float(arr.max()),
    }


def _concentration(values: list[str]) -> dict[str, Any]:
    counts = Counter(value for value in values if value)
    total = sum(counts.values())
    if total == 0:
        return {
            "count": 0,
            "unique_count": 0,
            "top1_count": 0,
            "top1_share": 0.0,
            "hhi": 0.0,
        }
    top1 = counts.most_common(1)[0][1]
    return {
        "count": int(total),
        "unique_count": len(counts),
        "top1_count": int(top1),
        "top1_share": top1 / total,
        "hhi": float(sum((count / total) ** 2 for count in counts.values())),
    }


def _case_edge_key(case: RelationalCase) -> str:
    return f"{case.sub_rule}|{case.edge_a}|{case.edge_b}"


def _case_aggregate_rows(cases: list[RelationalCase]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        docs = _case_documents(case)
        reason = (
            case.case_generation_reason
            if isinstance(case.case_generation_reason, dict)
            else {}
        )
        user_count = len(
            {ref.company_code for ref in case.row_refs if ref.company_code}
        )
        rows.append(
            {
                "case": case,
                "sub_rule": case.sub_rule,
                "tier": case.evidence_tier,
                "edge_key": _case_edge_key(case),
                "subject_key": str(case.edge_a or ""),
                "account_key": str(case.edge_b or ""),
                "rows_per_edge": len(case.row_refs),
                "documents_per_edge": len(docs),
                "users_per_edge": user_count,
                "metric_value": float(case.metric_value or 0.0),
                "family_ecdf": float(case.family_ecdf or 0.0),
                "positive_metric_count": int(reason.get("positive_metric_count", 0)),
            }
        )
    return rows


def _edge_concentration(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(row["edge_key"]) for row in rows)
    values = list(counts.values())
    dist = _numeric_distribution(values)
    total = sum(values)
    max_cases = max(values) if values else 0
    return {
        "edge_count": len(counts),
        "max_cases_per_edge": int(max_cases),
        "top_edge_share": max_cases / max(total, 1),
        "p50_cases_per_edge": dist["p50"],
        "p90_cases_per_edge": dist["p90"],
    }


def _sub_rule_decomposition(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for rule in sorted({str(row["sub_rule"]) for row in rows}):
        rule_rows = [row for row in rows if row["sub_rule"] == rule]
        moderate_rows = [row for row in rule_rows if row["tier"] == "moderate"]
        out[rule] = {
            "case_count": len(rule_rows),
            "edge_count": len({row["edge_key"] for row in rule_rows}),
            "edge_support_distribution": _numeric_distribution(
                list(Counter(str(row["edge_key"]) for row in rule_rows).values())
            ),
            "rows_per_edge_distribution": _numeric_distribution(
                [int(row["rows_per_edge"]) for row in rule_rows]
            ),
            "documents_per_edge_distribution": _numeric_distribution(
                [int(row["documents_per_edge"]) for row in rule_rows]
            ),
            "users_per_edge_distribution": _numeric_distribution(
                [int(row["users_per_edge"]) for row in rule_rows]
            ),
            "accounts_per_partner_distribution": _numeric_distribution(
                list(
                    Counter(
                        str(row["account_key"])
                        for row in rule_rows
                        if str(row["subject_key"])
                    ).values()
                )
            ),
            "partners_per_account_distribution": _numeric_distribution(
                list(
                    Counter(
                        str(row["subject_key"])
                        for row in rule_rows
                        if str(row["account_key"])
                    ).values()
                )
            ),
            "metric_value_distribution": _numeric_distribution(
                [float(row["metric_value"]) for row in rule_rows]
            ),
            "family_ecdf_distribution": _numeric_distribution(
                [float(row["family_ecdf"]) for row in rule_rows]
            ),
            "positive_metric_count_distribution": _numeric_distribution(
                [int(row["positive_metric_count"]) for row in rule_rows]
            ),
            "moderate_edge_small_sample_guard": {
                "excluded_by_positive_metric_count_lt20": sum(
                    1 for row in moderate_rows if int(row["positive_metric_count"]) < 20
                ),
                "excluded_by_ecdf_below_q95": sum(
                    1
                    for row in moderate_rows
                    if int(row["positive_metric_count"]) >= 20
                    and float(row["family_ecdf"]) < 0.95
                ),
            },
            "evidence_tier_distribution": dict(
                sorted(Counter(str(row["tier"]) for row in rule_rows).items())
            ),
            "top_concentration": {
                **_edge_concentration(rule_rows),
                "top_subject_share": _concentration(
                    [str(row["subject_key"]) for row in rule_rows]
                )["top1_share"],
                "top_account_share": _concentration(
                    [str(row["account_key"]) for row in rule_rows]
                )["top1_share"],
            },
        }
    return out


def _topn_truth_scenario_counts(
    cases: list[RelationalCase],
    *,
    top_n: int,
    truth_docs: set[str],
    truth_scenario_by_doc: dict[str, str],
) -> dict[str, int]:
    docs: set[str] = set()
    for case in cases[:top_n]:
        docs.update(_case_documents(case))
    counts = Counter(
        truth_scenario_by_doc[doc]
        for doc in (docs & truth_docs)
        if doc in truth_scenario_by_doc
    )
    return dict(sorted(counts.items()))


def _edge_row_position_set(edges: list[dict[str, Any]], rule_id: str) -> set[int]:
    positions: set[int] = set()
    for edge in edges:
        if edge.get("rule_id") != rule_id:
            continue
        for raw_pos in edge.get("row_positions") or []:
            try:
                positions.add(int(raw_pos))
            except (TypeError, ValueError):
                continue
    return positions


def _case_row_position_set(cases: list[RelationalCase], rule_id: str) -> set[int]:
    positions: set[int] = set()
    for case in cases:
        if case.sub_rule != rule_id:
            continue
        positions.update(ref.row_position for ref in case.row_refs)
    return positions


def _rule_gap_summary(
    *,
    df: pd.DataFrame,
    result_metadata: dict[str, Any],
    details: pd.DataFrame,
    cases: list[RelationalCase],
) -> dict[str, dict[str, Any]]:
    artifact = result_metadata.get("relational_edge_artifact") or {}
    edges = artifact.get("edges") or []
    edge_counts = Counter(edge.get("rule_id") for edge in edges)
    case_counts = Counter(case.sub_rule for case in cases)

    by_rule: dict[str, dict[str, Any]] = {}
    for rule_id in sorted(set(details.columns) | set(edge_counts) | set(case_counts)):
        if not rule_id:
            continue
        row_hit_labels = set(details.index[details[rule_id] > 0]) if rule_id in details else set()
        row_hit_count = len(row_hit_labels)
        edge_positions = _edge_row_position_set(edges, rule_id)
        case_positions = _case_row_position_set(cases, rule_id)
        gate_filtered_positions = edge_positions - case_positions
        no_edge_identity_count = max(row_hit_count - len(edge_positions), 0)
        invalid_edge_positions = {
            pos for pos in edge_positions if pos < 0 or pos >= len(df)
        }
        by_rule[rule_id] = {
            "row_score_hit_count": row_hit_count,
            "artifact_edge_count": int(edge_counts.get(rule_id, 0)),
            "case_count": int(case_counts.get(rule_id, 0)),
            "rows_with_edge_artifact": len(edge_positions),
            "rows_with_case_grade_artifact": len(case_positions),
            "gap_reasons": {
                "row_score_hit_without_edge_identity": no_edge_identity_count,
                "edge_gate_filtered_or_below_tail": len(gate_filtered_positions),
                "edge_row_position_invalid": len(invalid_edge_positions),
            },
        }
    return by_rule


def _case_grade_distribution(cases: list[RelationalCase]) -> dict[str, dict[str, int]]:
    distribution: dict[str, Counter[str]] = defaultdict(Counter)
    for case in cases:
        distribution[case.sub_rule][case.evidence_tier] += 1
    return {
        rule_id: dict(sorted(counts.items()))
        for rule_id, counts in sorted(distribution.items())
    }


def _topn_matched_by_sub_rule(
    cases: list[RelationalCase],
    *,
    top_n: int,
    truth_docs: set[str],
) -> dict[str, int]:
    matched: dict[str, set[str]] = defaultdict(set)
    for case in cases[:top_n]:
        hits = _case_documents(case) & truth_docs
        if hits:
            matched[str(case.sub_rule)].update(hits)
    return {rule: len(docs) for rule, docs in sorted(matched.items())}


def _coverage_contribution_by_case_growth(
    cases: list[RelationalCase],
    truth_docs: set[str],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for rule in sorted({case.sub_rule for case in cases}):
        rule_cases = [case for case in cases if case.sub_rule == rule]
        truth_hits: set[str] = set()
        for case in rule_cases:
            truth_hits.update(_case_documents(case) & truth_docs)
        out[rule] = {
            "case_count": len(rule_cases),
            "matched_truth_count": len(truth_hits),
            "matched_truth_per_1000_cases": len(truth_hits) / max(len(rule_cases), 1) * 1000,
        }
    return out


def _load_phase1_detection_results() -> list[Any]:
    with CASE_INPUT_PKL.open("rb") as fh:
        payload = pickle.load(fh)
    results = payload.get("results", []) if isinstance(payload, dict) else []
    return list(results) if isinstance(results, list) else []


def _phase1_baseline_document_sets(
    *,
    df: pd.DataFrame,
    truth_docs: set[str],
) -> dict[str, Any]:
    flagged_positions: set[int] = set()
    best_score_by_position: dict[int, float] = {}
    for result in _load_phase1_detection_results():
        raw_positions = getattr(result, "flagged_indices", None) or []
        valid_positions: list[int] = []
        for raw_pos in raw_positions:
            try:
                pos = int(raw_pos)
            except (TypeError, ValueError):
                continue
            if 0 <= pos < len(df):
                valid_positions.append(pos)
                flagged_positions.add(pos)
        scores = getattr(result, "scores", None)
        if scores is None:
            for pos in valid_positions:
                best_score_by_position[pos] = max(best_score_by_position.get(pos, 0.0), 1.0)
            continue
        for pos in valid_positions:
            try:
                score = float(scores.iloc[pos])
            except (AttributeError, IndexError, TypeError, ValueError):
                score = 0.0
            best_score_by_position[pos] = max(best_score_by_position.get(pos, 0.0), score)

    all_docs = {
        str(value)
        for value in df.iloc[sorted(flagged_positions)]["document_id"].dropna().astype(str)
        if value
    }
    ordered_positions = sorted(
        flagged_positions,
        key=lambda pos: (-best_score_by_position.get(pos, 0.0), pos),
    )
    topn_docs: dict[str, set[str]] = {}
    for top_n in (100, 500, 1000, 10000):
        docs = {
            str(value)
            for value in df.iloc[ordered_positions[:top_n]]["document_id"].dropna().astype(str)
            if value
        }
        topn_docs[str(top_n)] = docs
    all_truth_docs = all_docs & truth_docs
    topn_truth_docs = {top_n: docs & truth_docs for top_n, docs in topn_docs.items()}
    return {
        "source": (
            "PHASE1 detector flagged row document_id aggregate; TOP-N uses "
            "read-only detector score proxy."
        ),
        "flagged_row_count": len(flagged_positions),
        "document_count": len(all_docs),
        "truth_document_count": len(all_truth_docs),
        "topn": {
            top_n: {
                "review_document_count": len(docs),
                "truth_document_count": len(topn_truth_docs[top_n]),
            }
            for top_n, docs in topn_docs.items()
        },
        "_all_truth_docs": all_truth_docs,
        "_topn_truth_docs": topn_truth_docs,
        "_truth_document_total": len(truth_docs),
    }


def _public_phase1_baseline(phase1_baseline: dict[str, Any]) -> dict[str, Any]:
    public = {
        key: value
        for key, value in phase1_baseline.items()
        if not key.startswith("_")
    }
    truth_total = int(phase1_baseline.get("_truth_document_total", 0))
    public["phase1_all_document_inclusion"] = {
        "truth_document_coverage": public["truth_document_count"],
        "truth_document_total": truth_total,
        "coverage_ratio": public["truth_document_count"] / max(truth_total, 1),
        "interpretation": (
            "Broad PHASE1 review universe inclusion only; this does not prove "
            "relational evidence or scenario explanation coverage."
        ),
    }
    public["phase1_topn_truth_document_coverage"] = {
        top_n: metrics["truth_document_count"]
        for top_n, metrics in public["topn"].items()
    }
    return public


def _incremental_sub_rule_breakdown(
    cases: list[RelationalCase],
    *,
    truth_docs: set[str],
    phase1_all_truth_docs: set[str],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for rule in sorted({case.sub_rule for case in cases}):
        docs: set[str] = set()
        for case in cases:
            if case.sub_rule == rule:
                docs.update(_case_documents(case))
        matched = docs & truth_docs
        overlap = matched & phase1_all_truth_docs
        missed = matched - phase1_all_truth_docs
        out[rule] = {
            "matched_truth_docs": len(matched),
            "phase1_overlap_truth_docs": len(overlap),
            "phase1_missed_truth_docs": len(missed),
            "incremental_truth_docs_vs_phase1_all": len(missed),
            "overlap_ratio": len(overlap) / max(len(matched), 1),
            "incremental_ratio": len(missed) / max(len(matched), 1),
        }
    return out


def _incremental_coverage_for_topn(
    cases: list[RelationalCase],
    *,
    top_n: int,
    truth_docs: set[str],
    truth_scenario_by_doc: dict[str, str],
    phase1_baseline: dict[str, Any],
) -> dict[str, Any]:
    docs: set[str] = set()
    for case in cases[:top_n]:
        docs.update(_case_documents(case))
    matched = docs & truth_docs
    phase1_all_truth = phase1_baseline["_all_truth_docs"]
    overlap = matched & phase1_all_truth
    missed = matched - phase1_all_truth
    return {
        "matched_truth_docs": len(matched),
        "phase1_overlap_truth_docs": len(overlap),
        "phase1_missed_truth_docs": len(missed),
        "incremental_truth_docs_vs_phase1_all": len(missed),
        "incremental_truth_docs_vs_phase1_top100": len(
            matched - phase1_baseline["_topn_truth_docs"]["100"]
        ),
        "incremental_truth_docs_vs_phase1_top500": len(
            matched - phase1_baseline["_topn_truth_docs"]["500"]
        ),
        "incremental_truth_docs_vs_phase1_top1000": len(
            matched - phase1_baseline["_topn_truth_docs"]["1000"]
        ),
        "overlap_ratio": len(overlap) / max(len(matched), 1),
        "incremental_ratio": len(missed) / max(len(matched), 1),
        "nontruth_document_count": len(docs - truth_docs),
        "incremental_truth_per_100_review_docs": len(missed) / max(len(docs), 1) * 100,
        "sub_rule_incremental_breakdown": _incremental_sub_rule_breakdown(
            cases[:top_n],
            truth_docs=truth_docs,
            phase1_all_truth_docs=phase1_all_truth,
        ),
        "scenario_incremental_counts": dict(
            sorted(
                Counter(
                    truth_scenario_by_doc[doc]
                    for doc in missed
                    if doc in truth_scenario_by_doc
                ).items()
            )
        ),
    }


def _incremental_coverage_metrics(
    cases: list[RelationalCase],
    *,
    truth_docs: set[str],
    truth_scenario_by_doc: dict[str, str],
    phase1_baseline: dict[str, Any],
) -> dict[str, Any]:
    return {
        str(top_n): _incremental_coverage_for_topn(
            cases,
            top_n=top_n,
            truth_docs=truth_docs,
            truth_scenario_by_doc=truth_scenario_by_doc,
            phase1_baseline=phase1_baseline,
        )
        for top_n in (100, 500, 1000, 10000)
    }


def _case_topn_docs(cases: list[RelationalCase], top_n: int) -> set[str]:
    docs: set[str] = set()
    for case in cases[:top_n]:
        docs.update(_case_documents(case))
    return docs


def _phase1_topn_uplift_metrics(
    cases: list[RelationalCase],
    *,
    truth_docs: set[str],
    phase1_baseline: dict[str, Any],
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "phase1_all_truth_document_coverage": len(phase1_baseline["_all_truth_docs"]),
        "phase1_top100_truth_document_coverage": len(
            phase1_baseline["_topn_truth_docs"]["100"]
        ),
        "phase1_top500_truth_document_coverage": len(
            phase1_baseline["_topn_truth_docs"]["500"]
        ),
        "phase1_top1000_truth_document_coverage": len(
            phase1_baseline["_topn_truth_docs"]["1000"]
        ),
    }
    for top_n in (100, 500, 1000):
        matched = _case_topn_docs(cases, top_n) & truth_docs
        phase1_truth = phase1_baseline["_topn_truth_docs"][str(top_n)]
        out[f"phase2_top{top_n}_truth_not_in_phase1_top{top_n}"] = len(
            matched - phase1_truth
        )
        out[f"net_truth_uplift_vs_phase1_top{top_n}"] = len(matched) - len(phase1_truth)
    return out


def _truth_docs_by_sub_rule(
    cases: list[RelationalCase],
    *,
    truth_docs: set[str],
    rules: set[str],
) -> set[str]:
    docs: set[str] = set()
    for case in cases:
        if case.sub_rule in rules:
            docs.update(_case_documents(case) & truth_docs)
    return docs


def _truth_case_count(cases: list[RelationalCase], truth_docs: set[str]) -> int:
    return sum(1 for case in cases if _case_documents(case) & truth_docs)


def _scenario_explanation_gap(
    cases: list[RelationalCase],
    *,
    truth_docs: set[str],
    truth_scenario_by_doc: dict[str, str],
    phase1_baseline: dict[str, Any],
    top_n: int,
) -> dict[str, Any]:
    top_cases = cases[:top_n]
    matched = _case_topn_docs(cases, top_n) & truth_docs
    phase1_top_truth = phase1_baseline["_topn_truth_docs"][str(top_n)]
    scenario_counts = Counter(
        truth_scenario_by_doc[doc]
        for doc in matched
        if doc in truth_scenario_by_doc
    )
    by_scenario_and_rule: dict[str, Counter[str]] = defaultdict(Counter)
    for case in top_cases:
        for doc in _case_documents(case) & truth_docs:
            scenario = truth_scenario_by_doc.get(doc)
            if scenario:
                by_scenario_and_rule[scenario][case.sub_rule] += 1
    return {
        "phase1_topn_truth_docs_without_relational_surface": len(phase1_top_truth - matched),
        "phase2_relational_truth_docs_not_in_phase1_topn": len(matched - phase1_top_truth),
        "phase2_specific_relational_reason_truth_docs": len(matched),
        "phase1_only_generic_reason_truth_docs": len(phase1_top_truth - matched),
        "truth_scenario_counts": dict(sorted(scenario_counts.items())),
        "relational_rule_explanation_by_scenario": {
            scenario: dict(sorted(counts.items()))
            for scenario, counts in sorted(by_scenario_and_rule.items())
        },
    }


def _relational_evidence_incremental_metrics(
    cases: list[RelationalCase],
    *,
    truth_docs: set[str],
    truth_scenario_by_doc: dict[str, str],
    phase1_baseline: dict[str, Any],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for top_n in (100, 500, 1000):
        top_cases = cases[:top_n]
        matched = _case_topn_docs(cases, top_n) & truth_docs
        structural = _truth_docs_by_sub_rule(
            top_cases,
            truth_docs=truth_docs,
            rules={"R03", "R07"},
        )
        moderate = _truth_docs_by_sub_rule(
            top_cases,
            truth_docs=truth_docs,
            rules={"R01", "R02"},
        )
        context = _truth_docs_by_sub_rule(
            top_cases,
            truth_docs=truth_docs,
            rules={"R05", "R06"},
        )
        out[str(top_n)] = {
            "relational_evidence_added_truth_docs": len(matched),
            "relational_evidence_added_case_count": _truth_case_count(top_cases, truth_docs),
            "structural_evidence_added_truth_docs": len(structural),
            "moderate_tail_evidence_added_truth_docs": len(moderate),
            "r05_r06_context_evidence_added_truth_docs": len(context),
            "phase1_only_generic_reason_truth_docs": len(
                phase1_baseline["_topn_truth_docs"][str(top_n)] - matched
            ),
            "phase2_specific_relational_reason_truth_docs": len(matched),
            "evidence_unit_distribution": dict(
                sorted(Counter(case.sub_rule for case in top_cases).items())
            ),
            "scenario_explanation_gap": _scenario_explanation_gap(
                cases,
                truth_docs=truth_docs,
                truth_scenario_by_doc=truth_scenario_by_doc,
                phase1_baseline=phase1_baseline,
                top_n=top_n,
            ),
        }
    return out


def _walk_keys(value: Any) -> list[str]:
    if isinstance(value, dict):
        keys = [str(key) for key in value]
        for child in value.values():
            keys.extend(_walk_keys(child))
        return keys
    if isinstance(value, list):
        keys: list[str] = []
        for child in value:
            keys.extend(_walk_keys(child))
        return keys
    return []


def _raw_identifier_leak_check(payload: dict[str, Any], truth_docs: set[str]) -> dict[str, int]:
    text = json.dumps(payload, ensure_ascii=False)
    keys = _walk_keys(payload)
    return {
        "doc_like_token_count": sum(1 for doc in truth_docs if doc and doc in text),
        "forbidden_identifier_key_count": sum(
            1 for key in keys if key in FORBIDDEN_IDENTIFIER_KEYS
        ),
        "phase2_case_id_like_token_count": text.count("p2_relational_edge_"),
        "raw_edge_like_token_count": text.count("raw_edge_"),
    }


def main() -> int:
    started = time.perf_counter()
    df = _load_case_input()
    truth = _load_truth()
    truth_docs = set(truth["document_id"].astype(str))
    truth_scenario_by_doc = dict(
        zip(
            truth["document_id"].astype(str),
            truth["manipulation_scenario"].astype(str),
            strict=False,
        )
    )

    relational_result = _run_rule_detector("relational", df)
    case_set = build_phase2_case_set(
        batch_id=BATCH_ID,
        detection_results=[relational_result],
        df=df,
    )
    ordered_cases = [
        case
        for case in _sorted_cases(case_set.relational_cases)
        if isinstance(case, RelationalCase)
    ]
    phase1_baseline = _phase1_baseline_document_sets(df=df, truth_docs=truth_docs)
    aggregate_rows = _case_aggregate_rows(ordered_cases)
    metadata = relational_result.metadata if isinstance(relational_result.metadata, dict) else {}
    details = relational_result.details if relational_result.details is not None else pd.DataFrame()

    payload = {
        "generated_at": _now_iso(),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "dataset": DATASET_NAME,
        "diagnostic_scope": "relational native edge review candidates only",
        "case_count": len(ordered_cases),
        "artifact_edge_count": len(
            (metadata.get("relational_edge_artifact") or {}).get("edges") or []
        ),
        "row_score_hit_count": int((relational_result.scores > 0).sum()),
        "case_grade_policy": (
            "strong edge artifacts pass; moderate edge artifacts pass only when "
            "positive_metric_count >= 20 and their edge metric_value is in the "
            "family-native ECDF q95+ tail. "
            "No DataSynth truth labels are used for gate or sort."
        ),
        "sort_contract": (
            "diagnostic TOP-N uses evidence_tier, family_score desc, phase2_case_id; "
            "PHASE1 priority_score/composite_sort_score and PHASE2 family fusion are not used."
        ),
        "adopted_relational_product_policy": build_relational_policy_summary(
            tuple(ordered_cases)
        ),
        "incremental_value_definition": {
            "phase1_all_document_inclusion": (
                "Broad review-universe inclusion only; not interpreted as relational "
                "evidence or scenario explanation coverage."
            ),
            "phase1_topn_uplift": (
                "Truth documents surfaced by relational TOP-N that were outside the "
                "PHASE1 TOP-N score-proxy set."
            ),
            "relational_evidence_incremental": (
                "Relationship-specific evidence units added by relational native cases "
                "after candidate ordering."
            ),
            "scenario_explanation_gap": (
                "Aggregate scenario counts and relational sub_rule explanation counts; "
                "raw identifiers are not emitted."
            ),
        },
        "sub_rule_case_counts": dict(sorted(Counter(c.sub_rule for c in ordered_cases).items())),
        "sub_rule_evidence_tier_counts": _case_grade_distribution(ordered_cases),
        "top100_sub_rule_counts": _topn_sub_rule_counts(ordered_cases, 100),
        "top500_sub_rule_counts": _topn_sub_rule_counts(ordered_cases, 500),
        "top1000_sub_rule_counts": _topn_sub_rule_counts(ordered_cases, 1000),
        "top100_matched_by_sub_rule": _topn_matched_by_sub_rule(
            ordered_cases,
            top_n=100,
            truth_docs=truth_docs,
        ),
        "top500_matched_by_sub_rule": _topn_matched_by_sub_rule(
            ordered_cases,
            top_n=500,
            truth_docs=truth_docs,
        ),
        "top1000_matched_by_sub_rule": _topn_matched_by_sub_rule(
            ordered_cases,
            top_n=1000,
            truth_docs=truth_docs,
        ),
        "top100_truth_scenario_counts": _topn_truth_scenario_counts(
            ordered_cases,
            top_n=100,
            truth_docs=truth_docs,
            truth_scenario_by_doc=truth_scenario_by_doc,
        ),
        "top500_truth_scenario_counts": _topn_truth_scenario_counts(
            ordered_cases,
            top_n=500,
            truth_docs=truth_docs,
            truth_scenario_by_doc=truth_scenario_by_doc,
        ),
        "sub_rule_decomposition": _sub_rule_decomposition(aggregate_rows),
        "case_count_growth_truth_coverage": _coverage_contribution_by_case_growth(
            ordered_cases,
            truth_docs,
        ),
        "phase1_baseline": _public_phase1_baseline(phase1_baseline),
        "phase1_topn_uplift": _phase1_topn_uplift_metrics(
            ordered_cases,
            truth_docs=truth_docs,
            phase1_baseline=phase1_baseline,
        ),
        "relational_evidence_incremental": _relational_evidence_incremental_metrics(
            ordered_cases,
            truth_docs=truth_docs,
            truth_scenario_by_doc=truth_scenario_by_doc,
            phase1_baseline=phase1_baseline,
        ),
        "incremental_coverage_vs_phase1": _incremental_coverage_metrics(
            ordered_cases,
            truth_docs=truth_docs,
            truth_scenario_by_doc=truth_scenario_by_doc,
            phase1_baseline=phase1_baseline,
        ),
        "rule_gap_summary": _rule_gap_summary(
            df=df,
            result_metadata=metadata,
            details=details,
            cases=ordered_cases,
        ),
        "output_notes": [
            "Raw document identifiers are used only in memory for aggregate scenario counts.",
            "row_score_hit_without_edge_identity means detector row score existed but "
            "no audit-reviewable edge identity was emitted.",
            "edge_gate_filtered_or_below_tail means an edge artifact existed but did "
            "not become a case-grade review candidate under the native gate.",
        ],
    }
    payload["raw_identifier_leak_check"] = _raw_identifier_leak_check(payload, truth_docs)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _print(f"wrote {OUT_JSON.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
