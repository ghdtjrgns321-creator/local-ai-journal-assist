"""Duplicate Phase2 uplift diagnostic against the existing PHASE1 review surface.

This script evaluates whether Duplicate native case surfaces add review
candidate coverage beyond the PHASE1 TOP100 surface. It does not change
detector thresholds, row scores, PHASE1 ranking, PHASE2 family fusion, or the
production default duplicate selector. Truth labels are used only for aggregate
evaluation after candidate construction.
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import pickle
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import src.detection.duplicate_detector as duplicate_detector_module
from config.settings import get_settings
from src.detection.duplicate_detector import DuplicateDetector
from src.detection.duplicate_pair_features import build_duplicate_pair_artifact
from tools.scripts.diagnose_duplicate_native_case_quality_fixed5_20260529 import (
    _copy_settings_with_top_n,
    raw_identifier_leak_check,
)
from tools.scripts.diagnose_duplicate_retention_candidates_fixed5_20260529 import (
    _case_docs,
    _case_result_for_pairs,
    _default_order_cases,
    _doc_set_from_pairs,
    _measure_ordered_cases,
    _order_current_top100_case_anchor_plus_diversity_fill,
    _pair_docs,
    _select_pair_diversity_score,
    _select_score_order,
    _tier,
)
from tools.scripts.phase2_family_correlation_audit import _fast_time_shifted_duplicate

OUT_JSON = ROOT / "artifacts" / "duplicate_phase1_uplift_fixed5_20260529.json"


@dataclass(frozen=True)
class BatchSpec:
    name: str
    dataset: str
    case_input: Path
    phase1_result: Path
    truth_csv: Path
    retention_batch_prefix: str


SPEC = BatchSpec(
    name="fixed5_normalcal5",
    dataset="datasynth_manipulation_v7_candidate_fixed5_normalcal5",
    case_input=ROOT / "artifacts" / "phase1_manipulation_v7_fixed5_normalcal5_case_input.pkl",
    phase1_result=ROOT / "artifacts" / "stage7_fixed5_normalcal5_phase1_case_result.pkl",
    truth_csv=ROOT
    / "data"
    / "journal"
    / "primary"
    / "datasynth_manipulation_v7_candidate_fixed5_normalcal5"
    / "labels"
    / "manipulated_entry_truth.csv",
    retention_batch_prefix="fixed5_duplicate_phase1_uplift",
)

PHASE1_BUCKETS = (
    "phase1_top100",
    "phase1_101_500",
    "phase1_501_1000",
    "phase1_1001_plus",
    "phase1_not_in_cases",
)


def _load_case_input(path: Path) -> pd.DataFrame:
    with path.open("rb") as fh:
        payload = pickle.load(fh)
    df = payload["df"].copy()
    df["document_id"] = df["document_id"].astype(str)
    return df


def _load_phase1_result(path: Path) -> Any:
    with path.open("rb") as fh:
        return pickle.load(fh)


def _load_truth(path: Path) -> pd.DataFrame:
    truth = pd.read_csv(path)
    truth["document_id"] = truth["document_id"].astype(str)
    return truth


def _phase1_doc_rank_map(phase1_result: Any) -> dict[str, int]:
    """Return first PHASE1 case rank per document using stored case order."""
    rank_by_doc: dict[str, int] = {}
    for rank, case in enumerate(getattr(phase1_result, "cases", ()), start=1):
        for ref in getattr(case, "documents", ()):
            doc = getattr(ref, "document_id", None)
            if doc in (None, ""):
                continue
            rank_by_doc.setdefault(str(doc), rank)
    return rank_by_doc


def _phase1_bucket(rank: int | None) -> str:
    if rank is None:
        return "phase1_not_in_cases"
    if rank <= 100:
        return "phase1_top100"
    if rank <= 500:
        return "phase1_101_500"
    if rank <= 1000:
        return "phase1_501_1000"
    return "phase1_1001_plus"


def _bucket_distribution(docs: set[str], rank_by_doc: dict[str, int]) -> dict[str, int]:
    counts = Counter(_phase1_bucket(rank_by_doc.get(doc)) for doc in docs)
    return {bucket: int(counts.get(bucket, 0)) for bucket in PHASE1_BUCKETS}


def _truth_bucket_distribution(
    docs: set[str],
    *,
    truth_docs: set[str],
    rank_by_doc: dict[str, int],
) -> dict[str, int]:
    return _bucket_distribution(docs & truth_docs, rank_by_doc)


def _incremental_counts(
    docs: set[str],
    *,
    truth_docs: set[str],
    rank_by_doc: dict[str, int],
) -> dict[str, int]:
    truth = docs & truth_docs
    phase1_top100 = {doc for doc, rank in rank_by_doc.items() if rank <= 100}
    phase1_top500 = {doc for doc, rank in rank_by_doc.items() if rank <= 500}
    phase1_top1000 = {doc for doc, rank in rank_by_doc.items() if rank <= 1000}
    return {
        "truth_docs_outside_phase1_top100": len(truth - phase1_top100),
        "truth_docs_outside_phase1_top500": len(truth - phase1_top500),
        "truth_docs_outside_phase1_top1000": len(truth - phase1_top1000),
        "all_docs_outside_phase1_top100": len(docs - phase1_top100),
        "all_docs_outside_phase1_top500": len(docs - phase1_top500),
        "all_docs_outside_phase1_top1000": len(docs - phase1_top1000),
    }


def _pair_surface_summary(
    *,
    pairs: list[dict[str, Any]],
    truth_docs: set[str],
    rank_by_doc: dict[str, int],
) -> dict[str, Any]:
    docs = _doc_set_from_pairs(pairs)
    truth_covering_pairs = [pair for pair in pairs if _pair_docs(pair) & truth_docs]
    return {
        "pair_count": len(pairs),
        "docs_covered": len(docs),
        "truth_doc_count": len(docs & truth_docs),
        "truth_phase1_bucket_distribution": _truth_bucket_distribution(
            docs,
            truth_docs=truth_docs,
            rank_by_doc=rank_by_doc,
        ),
        "incremental_vs_phase1": _incremental_counts(
            docs,
            truth_docs=truth_docs,
            rank_by_doc=rank_by_doc,
        ),
        "evidence_tier_distribution": dict(
            sorted(Counter(_tier(pair) for pair in pairs).items())
        ),
        "truth_covering_pair_tier_distribution": dict(
            sorted(Counter(_tier(pair) for pair in truth_covering_pairs).items())
        ),
        "rule_id_distribution": dict(
            sorted(Counter(str(pair.get("rule_id") or "unknown") for pair in pairs).items())
        ),
        "case_grade_pair_ratio": round(
            sum(1 for pair in pairs if _tier(pair) in {"strong", "moderate"}) / len(pairs),
            6,
        )
        if pairs
        else 0.0,
    }


def _tier_weight(pair: dict[str, Any]) -> int:
    return {"strong": 3, "moderate": 2, "weak": 1}.get(_tier(pair), 0)


def _pair_score(pair: dict[str, Any]) -> float:
    try:
        return float(pair.get("pair_score") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _select_phase1_gap_case_grade_pairs(
    *,
    pairs: list[dict[str, Any]],
    rank_by_doc: dict[str, int],
    top_n: int,
) -> list[dict[str, Any]]:
    """Diagnostic-only selector for PHASE1 complement coverage.

    The ordering uses PHASE1 rank buckets and duplicate pair evidence only. It
    does not use truth labels, scenarios, row scores, or family-fusion outputs.
    Strong/moderate pair evidence is kept ahead of weak evidence, and repeated
    document concentration is softened during selection.
    """
    ordered = sorted(
        enumerate(pairs),
        key=lambda item: (
            -int(_tier(item[1]) in {"strong", "moderate"}),
            -sum(
                1
                for doc in _pair_docs(item[1])
                if _phase1_bucket(rank_by_doc.get(doc)) != "phase1_top100"
            ),
            -sum(
                1
                for doc in _pair_docs(item[1])
                if _phase1_bucket(rank_by_doc.get(doc))
                in {"phase1_1001_plus", "phase1_not_in_cases"}
            ),
            -_tier_weight(item[1]),
            -_pair_score(item[1]),
            item[0],
        ),
    )
    selected: list[dict[str, Any]] = []
    selected_ids: set[int] = set()
    doc_counts: Counter[str] = Counter()
    for max_doc_pairs in (1, 2, 5, None):
        for _idx, pair in ordered:
            if len(selected) >= top_n:
                return selected
            if id(pair) in selected_ids:
                continue
            docs = _pair_docs(pair)
            if max_doc_pairs is not None and any(
                doc_counts[doc] >= max_doc_pairs for doc in docs
            ):
                continue
            selected.append(pair)
            selected_ids.add(id(pair))
            for doc in docs:
                doc_counts[doc] += 1
    return selected


def _case_docs_for_top_n(ordered_cases: list[Any], top_n: int) -> set[str]:
    docs: set[str] = set()
    for case in ordered_cases[:top_n]:
        docs.update(_case_docs(case))
    return docs


def _case_surface_summary(
    *,
    name: str,
    ordered_cases: list[Any],
    truth_docs: set[str],
    scenario_by_doc: dict[str, str],
    rank_by_doc: dict[str, int],
    baseline_top100_docs: set[str],
) -> dict[str, Any]:
    measurement = _measure_ordered_cases(
        ordered=ordered_cases,
        truth_docs=truth_docs,
        scenario_by_doc=scenario_by_doc,
    )
    all_docs = (
        set().union(*(_case_docs(case) for case in ordered_cases))
        if ordered_cases
        else set()
    )
    out: dict[str, Any] = {
        "surface": name,
        "case_count": len(ordered_cases),
        "docs_covered": len(all_docs),
        "truth_doc_count": len(all_docs & truth_docs),
        "truth_phase1_bucket_distribution_all_cases": _truth_bucket_distribution(
            all_docs,
            truth_docs=truth_docs,
            rank_by_doc=rank_by_doc,
        ),
        "incremental_vs_phase1_all_cases": _incremental_counts(
            all_docs,
            truth_docs=truth_docs,
            rank_by_doc=rank_by_doc,
        ),
        "case_measurement": measurement,
        "policy_constraints": _policy_constraints(),
    }
    for top_n in (100, 500, 1000):
        docs = _case_docs_for_top_n(ordered_cases, top_n)
        key = f"top{top_n}"
        out[key] = {
            "docs_covered": len(docs),
            "truth_doc_count": len(docs & truth_docs),
            "truth_phase1_bucket_distribution": _truth_bucket_distribution(
                docs,
                truth_docs=truth_docs,
                rank_by_doc=rank_by_doc,
            ),
            "incremental_vs_phase1": _incremental_counts(
                docs,
                truth_docs=truth_docs,
                rank_by_doc=rank_by_doc,
            ),
            "new_docs_vs_current_top100": len(docs - baseline_top100_docs),
            "new_truth_docs_vs_current_top100": len((docs & truth_docs) - baseline_top100_docs),
        }
    return out


def _policy_constraints() -> dict[str, bool]:
    return {
        "truth_label_used_for_scoring": False,
        "truth_label_used_only_for_aggregate_evaluation": True,
        "production_default_selector_changed": False,
        "phase1_ranking_changed": False,
        "phase2_fusion_changed": False,
        "threshold_changed": False,
        "row_scores_changed": False,
    }


def _run() -> dict[str, Any]:
    started = time.perf_counter()
    df = _load_case_input(SPEC.case_input)
    truth = _load_truth(SPEC.truth_csv)
    truth_docs = set(truth["document_id"])
    scenario_by_doc = dict(
        zip(
            truth["document_id"].astype(str),
            truth["manipulation_scenario"].astype(str),
            strict=False,
        )
    )
    phase1_result = _load_phase1_result(SPEC.phase1_result)
    rank_by_doc = _phase1_doc_rank_map(phase1_result)

    settings = get_settings()
    duplicate_detector_module.b05d_time_shifted_duplicate = _fast_time_shifted_duplicate
    result = DuplicateDetector(settings).detect(df)
    generated_artifact = build_duplicate_pair_artifact(
        df,
        _copy_settings_with_top_n(settings, int(settings.duplicate_max_total_pairs)),
        candidate_scores=result.scores,
        candidate_details=result.details,
    ).to_dict()
    generated_pairs = list(generated_artifact.get("top_pairs", []))
    current_pairs = _select_score_order(generated_pairs, 500)
    evidence_pairs = _select_pair_diversity_score(generated_pairs, 500)
    phase1_gap_pairs = _select_phase1_gap_case_grade_pairs(
        pairs=generated_pairs,
        rank_by_doc=rank_by_doc,
        top_n=500,
    )

    current_cases = _case_result_for_pairs(
        pairs=current_pairs,
        df=df,
        batch_id=f"{SPEC.retention_batch_prefix}_current_500",
    )
    evidence_cases = _case_result_for_pairs(
        pairs=evidence_pairs,
        df=df,
        batch_id=f"{SPEC.retention_batch_prefix}_evidence_diversity_500",
    )
    phase1_gap_cases = _case_result_for_pairs(
        pairs=phase1_gap_pairs,
        df=df,
        batch_id=f"{SPEC.retention_batch_prefix}_phase1_gap_case_grade_500",
    )
    current_order = _default_order_cases(current_cases)
    evidence_order = _default_order_cases(evidence_cases)
    phase1_gap_order = _default_order_cases(phase1_gap_cases)
    anchor_order = _order_current_top100_case_anchor_plus_diversity_fill(
        current_cases=current_cases,
        candidate_cases=evidence_cases,
    )
    baseline_top100_docs = _case_docs_for_top_n(current_order, 100)

    phase1_all_truth_docs = set(rank_by_doc) & truth_docs
    phase1_top100_docs = {doc for doc, rank in rank_by_doc.items() if rank <= 100}
    phase1_top500_docs = {doc for doc, rank in rank_by_doc.items() if rank <= 500}
    phase1_top1000_docs = {doc for doc, rank in rank_by_doc.items() if rank <= 1000}

    payload: dict[str, Any] = {
        "schema_version": 1,
        "dataset": SPEC.dataset,
        "measurement_scope": (
            "diagnostic-only duplicate PHASE2 incremental review-surface uplift "
            "against the stored PHASE1 case ranking; aggregate only; raw identifiers omitted"
        ),
        "phase1_reference": {
            "source": SPEC.phase1_result.name,
            "rank_basis": "stored_phase1_case_order_min_case_rank_per_document",
            "case_count": len(getattr(phase1_result, "cases", ())),
            "truth_doc_count": len(truth_docs),
            "truth_docs_in_phase1_cases": len(phase1_all_truth_docs),
            "truth_docs_in_phase1_top100": len(phase1_top100_docs & truth_docs),
            "truth_docs_in_phase1_top500": len(phase1_top500_docs & truth_docs),
            "truth_docs_in_phase1_top1000": len(phase1_top1000_docs & truth_docs),
            "truth_phase1_bucket_distribution": _truth_bucket_distribution(
                truth_docs,
                truth_docs=truth_docs,
                rank_by_doc=rank_by_doc,
            ),
        },
        "pair_surfaces": {
            "generated_capped_pair_evidence": _pair_surface_summary(
                pairs=generated_pairs,
                truth_docs=truth_docs,
                rank_by_doc=rank_by_doc,
            ),
            "current_document_diversity_top_500": _pair_surface_summary(
                pairs=current_pairs,
                truth_docs=truth_docs,
                rank_by_doc=rank_by_doc,
            ),
            "evidence_diversity_top_500": _pair_surface_summary(
                pairs=evidence_pairs,
                truth_docs=truth_docs,
                rank_by_doc=rank_by_doc,
            ),
            "phase1_gap_case_grade_top_500": _pair_surface_summary(
                pairs=phase1_gap_pairs,
                truth_docs=truth_docs,
                rank_by_doc=rank_by_doc,
            ),
        },
        "case_surfaces": {
            "current_document_diversity_top_500": _case_surface_summary(
                name="current_document_diversity_top_500",
                ordered_cases=current_order,
                truth_docs=truth_docs,
                scenario_by_doc=scenario_by_doc,
                rank_by_doc=rank_by_doc,
                baseline_top100_docs=baseline_top100_docs,
            ),
            "evidence_diversity_top_500": _case_surface_summary(
                name="evidence_diversity_top_500",
                ordered_cases=evidence_order,
                truth_docs=truth_docs,
                scenario_by_doc=scenario_by_doc,
                rank_by_doc=rank_by_doc,
                baseline_top100_docs=baseline_top100_docs,
            ),
            "phase1_gap_case_grade_top_500": _case_surface_summary(
                name="phase1_gap_case_grade_top_500",
                ordered_cases=phase1_gap_order,
                truth_docs=truth_docs,
                scenario_by_doc=scenario_by_doc,
                rank_by_doc=rank_by_doc,
                baseline_top100_docs=baseline_top100_docs,
            ),
            "current_top100_anchor_plus_diversity_fill": _case_surface_summary(
                name="current_top100_anchor_plus_diversity_fill",
                ordered_cases=anchor_order,
                truth_docs=truth_docs,
                scenario_by_doc=scenario_by_doc,
                rank_by_doc=rank_by_doc,
                baseline_top100_docs=baseline_top100_docs,
            ),
            "split_ui100_current_export500_evidence": {
                "surface": "split_ui100_current_export500_evidence",
                "ui_top100": _case_surface_summary(
                    name="split_ui100_current",
                    ordered_cases=current_order[:100],
                    truth_docs=truth_docs,
                    scenario_by_doc=scenario_by_doc,
                    rank_by_doc=rank_by_doc,
                    baseline_top100_docs=baseline_top100_docs,
                )["top100"],
                "export_top500": _case_surface_summary(
                    name="split_export_evidence",
                    ordered_cases=evidence_order[:500],
                    truth_docs=truth_docs,
                    scenario_by_doc=scenario_by_doc,
                    rank_by_doc=rank_by_doc,
                    baseline_top100_docs=baseline_top100_docs,
                )["top500"],
                "policy_constraints": _policy_constraints(),
            },
        },
        "interpretation": {
            "primary_question": (
                "Does Duplicate PHASE2 add review candidates that were outside "
                "the PHASE1 TOP100 surface while retaining duplicate pair evidence?"
            ),
            "candidate_weight_provenance": {
                "phase1_gap_case_grade_top_500": (
                    "uses stored PHASE1 rank bucket as a complement signal and "
                    "duplicate pair evidence tier/score; truth labels and scenarios "
                    "are not selector inputs"
                )
            },
            "production_default_selector_changed": False,
            "production_adoption_pending": True,
            "next_validation_need": (
                "Compare the same PHASE1-uplift metrics across additional batches "
                "before changing any product review surface."
            ),
        },
        "policy_constraints": _policy_constraints(),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    payload["raw_identifier_leak_check"] = raw_identifier_leak_check(
        payload,
        forbidden_values=truth_docs,
    )
    return payload


def main() -> int:
    payload = _run()
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "out": str(OUT_JSON),
                "elapsed_seconds": payload["elapsed_seconds"],
                "phase1_top100_truth_docs": payload["phase1_reference"][
                    "truth_docs_in_phase1_top100"
                ],
                "current_top100_outside_phase1_top100_truth_docs": payload["case_surfaces"][
                    "current_document_diversity_top_500"
                ]["top100"]["incremental_vs_phase1"]["truth_docs_outside_phase1_top100"],
                "evidence_top500_outside_phase1_top100_truth_docs": payload["case_surfaces"][
                    "evidence_diversity_top_500"
                ]["top500"]["incremental_vs_phase1"]["truth_docs_outside_phase1_top100"],
                "raw_identifier_leak_check": payload["raw_identifier_leak_check"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
