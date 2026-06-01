"""Diagnose fixed5 Intercompany incremental value against PHASE1.

This script is diagnostic-only. It does not change IC gates, native case
ordering, PHASE1 ranking, or PHASE2 fusion. Raw document and row identifiers are
used in memory only for aggregate evaluation and are not emitted.
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import pickle
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.models.phase2_case import IntercompanyCase
from src.services.phase2_case_set_orchestrator import build_phase2_case_set
from tools.scripts.measure_phase2_native_cases_fixed5_20260528 import (
    BATCH_ID,
    DATASET_NAME,
    _case_documents,
    _doc_sort_key,
    _load_case_input,
    _load_truth,
    _run_rule_detector,
    _sorted_cases,
)

OUT_JSON = ROOT / "artifacts" / "intercompany_incremental_value_fixed5_20260529.json"
PHASE1_CASE_RESULT = ROOT / "artifacts" / "stage7_fixed5_normalcal5_phase1_case_result.pkl"
TOP_NS = (100, 500, 1000)
FORBIDDEN_IDENTIFIER_KEYS = {
    "document" "_id",
    "document" "_ids",
    "raw" "_document" "_id",
    "raw" "_document" "_ids",
    "row" "_id",
    "row" "_ids",
    "raw" "_row" "_id",
    "raw" "_row" "_ids",
    "index" "_label",
    "raw" "_index" "_label",
    "phase2" "_case" "_id",
    "phase2" "_case" "_ids",
    "counterparty" "_id",
    "counterparty" "_ids",
    "raw" "_counterparty" "_id",
    "raw" "_counterparty" "_ids",
}
CASE_ID_TOKEN_RE = re.compile(r"\bp2_intercompany_pair_[A-Za-z0-9_:-]+\b")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _print(message: str) -> None:
    print(f"[{_now_iso()}] {message}", flush=True)


def _phase1_case_documents(case: Any) -> set[str]:
    docs: set[str] = set()
    for document in getattr(case, "documents", ()) or ():
        value = getattr(document, "document_id", None)
        if value is not None:
            docs.add(str(value))
    return docs


def _phase1_case_score(case: Any) -> float:
    for attr in ("composite_sort_score", "priority_score", "triage_rank_score"):
        value = getattr(case, attr, None)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def _phase1_explanation_categories(values: list[Any]) -> set[str]:
    text = " ".join(str(value).lower() for value in values if value is not None)
    categories: set[str] = set()
    if any(token in text for token in ("intercompany", "related", "counterparty", "circular")):
        categories.add("ic_or_related_party")
    if any(token in text for token in ("amount", "material", "large", "zscore", "tail")):
        categories.add("amount_or_statistical")
    if any(token in text for token in ("manual", "approval", "control", "access", "override")):
        categories.add("manual_control_or_approval")
    if any(token in text for token in ("period", "closing", "cutoff", "timing", "weekend")):
        categories.add("date_or_timing")
    if any(token in text for token in ("duplicate", "reversal", "outflow")):
        categories.add("duplicate_or_reversal")
    if any(token in text for token in ("risk", "anomaly", "review", "weak", "generic")):
        categories.add("generic_review")
    return categories or {"generic_review"}


def _phase1_baseline_from_case_result(path: Path, truth_docs: set[str]) -> dict[str, Any]:
    with path.open("rb") as fh:
        result = pickle.load(fh)
    cases = list(getattr(result, "cases", ()) or ())
    all_docs: set[str] = set()
    ranked_docs: list[str] = []
    seen: set[str] = set()
    categories_by_doc: dict[str, set[str]] = defaultdict(set)
    ordered_cases = sorted(
        cases,
        key=lambda item: (-_phase1_case_score(item), str(getattr(item, "case_key", ""))),
    )
    for case in ordered_cases:
        docs = sorted(_phase1_case_documents(case), key=_doc_sort_key)
        case_categories = _phase1_explanation_categories(
            [
                getattr(case, "primary_topic", None),
                getattr(case, "primary_queue", None),
                getattr(case, "primary_theme", None),
                getattr(case, "secondary_tags", None),
                getattr(case, "evidence_types", None),
                getattr(case, "evidence_tags", None),
                getattr(case, "fraud_scenario_tags", None),
                getattr(case, "review_focus", None),
                getattr(case, "priority_adjustment_reasons", None),
                getattr(case, "triage_rank_reasons", None),
            ]
        )
        all_docs.update(docs)
        for doc in docs:
            categories_by_doc[doc].update(case_categories)
            if doc not in seen:
                seen.add(doc)
                ranked_docs.append(doc)
    top_sets = {str(top_n): set(ranked_docs[:top_n]) for top_n in (*TOP_NS, 10000)}
    return {
        "source": "phase1_case_result_documents",
        "case_count": len(cases),
        "all_docs": all_docs,
        "top_sets": top_sets,
        "categories_by_doc": categories_by_doc,
        "summary": {
            "source": "phase1_case_result_documents",
            "case_count": len(cases),
            "all_review_document_count": len(all_docs),
            "all_truth_document_count": len(all_docs & truth_docs),
            "top100_review_document_count": len(top_sets["100"]),
            "top100_truth_document_count": len(top_sets["100"] & truth_docs),
            "top500_review_document_count": len(top_sets["500"]),
            "top500_truth_document_count": len(top_sets["500"] & truth_docs),
            "top1000_review_document_count": len(top_sets["1000"]),
            "top1000_truth_document_count": len(top_sets["1000"] & truth_docs),
            "top10000_review_document_count": len(top_sets["10000"]),
            "top10000_truth_document_count": len(top_sets["10000"] & truth_docs),
        },
    }


def _case_rows(cases: list[IntercompanyCase]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rank, case in enumerate(_sorted_cases(cases), start=1):
        has_pair_refs = len(case.row_refs) >= 2
        has_counterparty_pair = bool(case.counterparty_pair)
        has_symmetry = case.amount_symmetry is not None
        rows.append(
            {
                "rank": rank,
                "case": case,
                "ic_role": str(case.ic_role),
                "evidence_tier": str(case.evidence_tier),
                "family_score": float(case.family_score or 0.0),
                "doc_count": len(_case_documents(case)),
                "row_ref_count": len(case.row_refs),
                "has_pair_refs": has_pair_refs,
                "has_counterparty_pair": has_counterparty_pair,
                "has_amount_symmetry": has_symmetry,
            }
        )
    return rows


def _topn_docs(rows: list[dict[str, Any]], top_n: int) -> set[str]:
    docs: set[str] = set()
    for row in rows[:top_n]:
        docs.update(_case_documents(row["case"]))
    return docs


def _truth_case_count(rows: list[dict[str, Any]], truth_docs: set[str]) -> int:
    return sum(1 for row in rows if _case_documents(row["case"]) & truth_docs)


def _truth_docs_by_role(
    rows: list[dict[str, Any]],
    *,
    truth_docs: set[str],
    role: str,
) -> set[str]:
    docs: set[str] = set()
    for row in rows:
        if row["ic_role"] == role:
            docs.update(_case_documents(row["case"]) & truth_docs)
    return docs


def _truth_docs_with_predicate(
    rows: list[dict[str, Any]],
    *,
    truth_docs: set[str],
    field: str,
) -> set[str]:
    docs: set[str] = set()
    for row in rows:
        if bool(row.get(field)):
            docs.update(_case_documents(row["case"]) & truth_docs)
    return docs


def _topn_uplift(
    rows: list[dict[str, Any]],
    truth_docs: set[str],
    phase1: dict[str, Any],
) -> dict[str, int]:
    out = {
        "phase1_all_truth_document_coverage": len(phase1["all_docs"] & truth_docs),
        "phase1_top100_truth_document_coverage": len(phase1["top_sets"]["100"] & truth_docs),
        "phase1_top500_truth_document_coverage": len(phase1["top_sets"]["500"] & truth_docs),
        "phase1_top1000_truth_document_coverage": len(phase1["top_sets"]["1000"] & truth_docs),
    }
    for top_n in TOP_NS:
        matched = _topn_docs(rows, top_n) & truth_docs
        phase1_truth = phase1["top_sets"][str(top_n)] & truth_docs
        out[f"ic_top{top_n}_truth_not_in_phase1_top{top_n}"] = len(matched - phase1_truth)
        out[f"net_truth_uplift_vs_phase1_top{top_n}"] = len(matched) - len(phase1_truth)
    return out


def _evidence_incremental(
    rows: list[dict[str, Any]],
    truth_docs: set[str],
    phase1: dict[str, Any],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for top_n in TOP_NS:
        top_rows = rows[:top_n]
        matched = _topn_docs(rows, top_n) & truth_docs
        reciprocal_docs = _truth_docs_by_role(
            top_rows,
            truth_docs=truth_docs,
            role="reciprocal_flow",
        )
        mismatch_docs = _truth_docs_by_role(top_rows, truth_docs=truth_docs, role="amount_mismatch")
        paired_docs = _truth_docs_with_predicate(
            top_rows,
            truth_docs=truth_docs,
            field="has_pair_refs",
        )
        counterparty_docs = _truth_docs_with_predicate(
            top_rows,
            truth_docs=truth_docs,
            field="has_counterparty_pair",
        )
        symmetry_docs = _truth_docs_with_predicate(
            top_rows,
            truth_docs=truth_docs,
            field="has_amount_symmetry",
        )
        phase1_top_truth = phase1["top_sets"][str(top_n)] & truth_docs
        out[str(top_n)] = {
            "ic_evidence_added_truth_docs": len(matched),
            "ic_evidence_added_case_count": _truth_case_count(top_rows, truth_docs),
            "reciprocal_flow_evidence_added_truth_docs": len(reciprocal_docs),
            "amount_mismatch_evidence_added_truth_docs": len(mismatch_docs),
            "paired_row_ref_truth_docs": len(paired_docs),
            "counterparty_pair_truth_docs": len(counterparty_docs),
            "amount_symmetry_truth_docs": len(symmetry_docs),
            "ic_specific_pair_evidence_truth_docs": len(
                reciprocal_docs | mismatch_docs | paired_docs | counterparty_docs | symmetry_docs
            ),
            "phase1_only_generic_reason_truth_docs": len(phase1_top_truth - matched),
            "phase2_specific_ic_reason_truth_docs": len(matched),
            "ic_role_distribution": dict(
                sorted(Counter(str(row["ic_role"]) for row in top_rows).items())
            ),
            "evidence_tier_distribution": dict(
                sorted(Counter(str(row["evidence_tier"]) for row in top_rows).items())
            ),
        }
    return out


def _explanation_gap(
    rows: list[dict[str, Any]],
    *,
    truth_docs: set[str],
    truth_scenario_by_doc: dict[str, str],
    phase1: dict[str, Any],
) -> dict[str, Any]:
    categories_by_doc: dict[str, set[str]] = phase1.get("categories_by_doc", {})
    out: dict[str, Any] = {}
    for top_n in TOP_NS:
        matched = _topn_docs(rows, top_n) & truth_docs
        scenario_counts = Counter(
            truth_scenario_by_doc[doc]
            for doc in matched
            if doc in truth_scenario_by_doc
        )
        generic_categories = {"generic_review", "amount_or_statistical", "date_or_timing"}
        phase1_generic = {
            doc
            for doc in matched
            if set(categories_by_doc.get(doc, {"generic_review"})).issubset(generic_categories)
        }
        phase1_ic_like = {
            doc
            for doc in matched
            if "ic_or_related_party" in categories_by_doc.get(doc, set())
        }
        out[str(top_n)] = {
            "truth_scenario_counts": dict(sorted(scenario_counts.items())),
            "ic_truth_with_phase1_generic_or_non_ic_reason": len(phase1_generic),
            "ic_truth_with_phase1_ic_or_related_reason": len(phase1_ic_like),
            "ic_truth_with_phase2_specific_reason": len(matched),
            "phase1_topn_truth_docs_without_ic_surface": len(
                (phase1["top_sets"][str(top_n)] & truth_docs) - matched
            ),
            "ic_truth_docs_not_in_phase1_topn": len(
                matched - (phase1["top_sets"][str(top_n)] & truth_docs)
            ),
        }
    return out


def _decision_payload(
    topn: dict[str, int],
    evidence: dict[str, Any],
    explanation: dict[str, Any],
) -> dict[str, Any]:
    top100_uplift = int(topn.get("net_truth_uplift_vs_phase1_top100", 0))
    top500_uplift = int(topn.get("net_truth_uplift_vs_phase1_top500", 0))
    evidence_500 = evidence["500"]
    explanation_500 = explanation["500"]
    ic_docs = int(evidence_500["ic_specific_pair_evidence_truth_docs"])
    reciprocal_docs = int(evidence_500["reciprocal_flow_evidence_added_truth_docs"])
    mismatch_docs = int(evidence_500["amount_mismatch_evidence_added_truth_docs"])
    topn_value = "high" if top100_uplift >= 20 and top500_uplift > 0 else "medium"
    evidence_value = "high" if ic_docs >= 30 and reciprocal_docs > 0 else "medium"
    explanation_value = (
        "high" if int(explanation_500["ic_truth_with_phase2_specific_reason"]) >= 30 else "medium"
    )
    if topn_value == "high" and evidence_value == "high" and explanation_value == "high":
        role = "blind_spot_plus_evidence_incremental"
    elif evidence_value in {"high", "medium"}:
        role = "ic_specific_evidence_strengthening"
    else:
        role = "mostly_reordering"
    return {
        "document_inclusion_incremental_value": "reported_separately_not_decision_basis",
        "topn_uplift_value": topn_value,
        "evidence_incremental_value": evidence_value,
        "explanation_incremental_value": explanation_value,
        "primary_product_role": role,
        "broad_recall_expansion_family": False,
        "production_ranking_changed": False,
        "new_policy_adopted": False,
        "adopted_default_allowed": False,
        "production_adoption_interpretation": (
            "false means no new production ranking/gate policy was adopted; it does not "
            "disable the existing Intercompany native family."
        ),
        "reason": (
            "IC keeps the existing native lane and is evaluated as PHASE1 TOP-N uplift "
            "plus IC-specific reciprocal/mismatch evidence. TOP100 uplift="
            f"{top100_uplift}, TOP500 uplift={top500_uplift}, TOP500 IC evidence "
            f"truth docs={ic_docs}, reciprocal={reciprocal_docs}, mismatch={mismatch_docs}. "
            "Production gate, ranking, PHASE1 priority, and PHASE2 fusion remain unchanged."
        ),
    }


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
    keys = {key.lower() for key in _walk_keys(payload)}
    return {
        "doc_like_token_count": sum(1 for doc in truth_docs if doc and doc in text),
        "forbidden_identifier_key_count": sum(
            1 for key in keys if key in FORBIDDEN_IDENTIFIER_KEYS
        ),
        "phase2_case_id_like_token_count": len(CASE_ID_TOKEN_RE.findall(text)),
        "counterparty_raw_id_like_key_count": sum(
            1
            for key in keys
            if "counterparty" in key and ("_id" in key or key.startswith("raw"))
        ),
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
    phase1 = _phase1_baseline_from_case_result(PHASE1_CASE_RESULT, truth_docs)

    intercompany_result = _run_rule_detector("intercompany", df)
    case_set = build_phase2_case_set(
        batch_id=BATCH_ID,
        detection_results=[intercompany_result],
        df=df,
    )
    cases = [
        case
        for case in case_set.intercompany_cases
        if isinstance(case, IntercompanyCase)
    ]
    rows = _case_rows(cases)
    topn = _topn_uplift(rows, truth_docs, phase1)
    evidence = _evidence_incremental(rows, truth_docs, phase1)
    explanation = _explanation_gap(
        rows,
        truth_docs=truth_docs,
        truth_scenario_by_doc=truth_scenario_by_doc,
        phase1=phase1,
    )
    circular_docs = {
        doc
        for doc, scenario in truth_scenario_by_doc.items()
        if scenario == "circular_related_party_transaction"
    }
    payload = {
        "generated_at": _now_iso(),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "dataset": DATASET_NAME,
        "diagnostic_scope": (
            "intercompany incremental value against PHASE1 broad and TOP-N baselines"
        ),
        "measurement_contract": (
            "Diagnostic-only IC native case evaluation. Native cases are built with the "
            "existing IntercompanyMatcher and S3 case builder, sorted by the existing "
            "native case order. Truth/scenario labels are used only for aggregate "
            "evaluation after ordering."
        ),
        "non_scope": [
            "No Intercompany gate change.",
            "No Intercompany native ordering change.",
            "No PHASE1 priority_score/composite_sort_score/ranking change.",
            "No PHASE2 fusion/Noisy-OR/RRF change.",
            "No truth-label boosting; truth and scenario labels are evaluation-only aggregates.",
        ],
        "truth_document_count": len(truth_docs),
        "phase1_baseline": phase1["summary"],
        "ic_native_success_lock": {
            "case_count": len(rows),
            "top100_circular_truth_docs": len(_topn_docs(rows, 100) & circular_docs),
            "circular_scenario_truth_coverage": (
                f"{len(_topn_docs(rows, 100) & circular_docs)}/{len(circular_docs)}"
            ),
        },
        "topn_uplift": topn,
        "evidence_incremental": evidence,
        "explanation_incremental": explanation,
        "decision": _decision_payload(topn, evidence, explanation),
        "fitting_guard": {
            "truth_used_for_ordering": False,
            "scenario_used_for_ordering": False,
            "ic_gate_changed": False,
            "phase1_ranking_changed": False,
            "phase2_fusion_changed": False,
            "production_ranking_changed": False,
            "new_policy_adopted": False,
            "raw_identifiers_emitted": False,
        },
    }
    payload["raw_identifier_leak_check"] = _raw_identifier_leak_check(payload, truth_docs)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _print(f"wrote {OUT_JSON.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
