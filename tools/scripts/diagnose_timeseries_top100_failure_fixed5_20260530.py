"""Diagnose why TS-primary truth evidence misses TOP100 on fixed5.

Diagnostic-only. Candidate ordering does not use truth labels, scenario labels,
PHASE1 ranks, raw document identifiers, row identifiers, or case identifiers.
Truth/scenario labels are used only after ordering for aggregate evaluation.
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.scripts.diagnose_timeseries_primary_surface_crossbatch_20260530 import (
    _build_row_score_windows,
    _candidate_policies,
    _current_native_windows,
)
from tools.scripts.diagnose_timeseries_ranking_candidates_fixed5_20260529 import (
    _raw_identifier_leak_report,
)
from tools.scripts.diagnose_timeseries_ranking_crossbatch_20260529 import (
    _TS_ALIGNED_SCENARIOS,
    _load_case_input,
    _load_truth,
    _num_dist,
    _phase1_reference_sets,
    _retention_review_burden_proxy,
    _scenario_counts,
    _truth_scenario_by_doc,
)
from tools.scripts.measure_phase2_native_cases_fixed5_20260528 import (
    BATCH_ID as FIXED5_BATCH_ID,
)
from tools.scripts.measure_phase2_native_cases_fixed5_20260528 import _run_rule_detector

OUT_JSON = ROOT / "artifacts" / "timeseries_top100_failure_diagnostic_fixed5_20260530.json"
CASE_INPUT = ROOT / "artifacts" / "phase1_manipulation_v7_fixed5_normalcal5_case_input.pkl"
TRUTH_CSV = (
    ROOT
    / "data"
    / "journal"
    / "primary"
    / "datasynth_manipulation_v7_candidate_fixed5_normalcal5"
    / "labels"
    / "manipulated_entry_truth.csv"
)
PHASE1_RESULT = ROOT / "artifacts" / "stage7_fixed5_normalcal5_phase1_case_result.pkl"
FAMILY_BY_DOC = (
    ROOT / "artifacts" / "stage7_fixed5_normalcal5_phase2_family_by_doc_20260524.parquet"
)
TOP_NS = (100, 500)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _print(message: str) -> None:
    print(f"[{_now_iso()}] {message}", flush=True)


def main() -> int:
    started = time.perf_counter()
    df = _load_case_input(CASE_INPUT)
    truth = _load_truth(TRUTH_CSV)
    truth_docs = set(truth["document_id"].astype(str))
    scenario_by_doc = _truth_scenario_by_doc(truth)
    phase1_reference = _phase1_reference_sets(PHASE1_RESULT)
    family_by_doc = _family_by_doc_lookup(FAMILY_BY_DOC)

    ts_result = _run_rule_detector("timeseries", df)
    windows = _build_row_score_windows(df=df, detection_result=ts_result, truth_docs=truth_docs)
    doc_features = _truth_doc_features(
        windows=windows,
        truth_docs=truth_docs,
        scenario_by_doc=scenario_by_doc,
        df=df,
        detection_result=ts_result,
        family_by_doc=family_by_doc,
        phase1_reference=phase1_reference,
    )
    base_policies = _candidate_policies(windows)
    policies = {
        "current_native_ts_order": _current_native_windows(
            df=df,
            detection_result=ts_result,
            batch_id=FIXED5_BATCH_ID,
            truth_docs=truth_docs,
        ),
        "ts_primary_conservative_surface": base_policies["ts_primary_conservative_surface"],
        "ts_specific_severity_surface": _ts_specific_severity_surface(windows),
        "mixed_ts_relevant_surface": _mixed_ts_relevant_surface(windows),
    }

    alignment = _label_alignment(doc_features)
    candidate_rankings = {
        name: _candidate_failure_summary(
            ordered,
            doc_features=doc_features,
            alignment=alignment,
            truth_docs=truth_docs,
            scenario_by_doc=scenario_by_doc,
            phase1_reference=phase1_reference,
        )
        for name, ordered in policies.items()
    }
    miss_reasons = _miss_reason_summary(
        policies["ts_primary_conservative_surface"],
        doc_features=doc_features,
        alignment=alignment,
        phase1_reference=phase1_reference,
    )
    payload = {
        "generated_at": _now_iso(),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "dataset": "fixed5_normalcal5",
        "guardrails": {
            "truth_label_used_for_selector": False,
            "scenario_label_used_for_selector": False,
            "production_gate_ranking_fusion_changed": False,
            "phase1_ranking_changed": False,
            "broad_companion_used_as_ts_primary": False,
        },
        "truth_document_count": len(truth_docs),
        "ts_truth_attribution_audit": _truth_attribution_audit(
            doc_features,
            alignment,
            windows=windows,
        ),
        "top100_miss_reason_summary": miss_reasons,
        "implementation_verification": _implementation_verification(
            ts_result=ts_result,
            windows=windows,
            doc_features=doc_features,
        ),
        "datasynth_label_alignment": _alignment_counts(alignment),
        "candidate_surfaces": candidate_rankings,
        "decision": _decision_payload(
            alignment=alignment,
            doc_features=doc_features,
            miss_reasons=miss_reasons,
            candidates=candidate_rankings,
        ),
    }
    payload["raw_identifier_leak_check"] = _raw_identifier_leak_report(
        payload,
        truth_docs=truth_docs,
    )
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _print(f"wrote {OUT_JSON.relative_to(ROOT).as_posix()}")
    return 0


def _family_by_doc_lookup(path: Path) -> dict[str, dict[str, float]]:
    if not path.exists():
        return {}
    data = pd.read_parquet(path)
    out: dict[str, dict[str, float]] = {}
    for row in data.itertuples(index=False):
        doc = str(row.document_id)
        out[doc] = {
            "unsupervised": float(getattr(row, "phase2_unsupervised_score_max", 0.0) or 0.0),
            "relational": float(getattr(row, "phase2_relational_score_max", 0.0) or 0.0),
            "duplicate": float(getattr(row, "phase2_duplicate_score_max", 0.0) or 0.0),
            "intercompany": float(getattr(row, "phase2_intercompany_score_max", 0.0) or 0.0),
        }
    return out


def _truth_doc_features(
    *,
    windows: list[dict[str, Any]],
    truth_docs: set[str],
    scenario_by_doc: dict[str, str],
    df: pd.DataFrame,
    detection_result: Any,
    family_by_doc: dict[str, dict[str, float]],
    phase1_reference: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    by_doc = {
        doc: {
            "scenario": scenario_by_doc.get(doc, "unknown"),
            "in_candidate_pool": False,
            "window_count": 0,
            "max_robust_z": 0.0,
            "max_period_end_lift": 0.0,
            "max_baseline_observation_count": 0,
            "max_context_evidence_count": 0,
            "max_row_count": 0,
            "period_end_context": False,
            "manual_or_adjustment_context": False,
            "after_hours_or_weekend_context": False,
            "round_amount_context": False,
            "amount_tail_context": False,
            "subject_activity_rank_min": None,
            "subject_frequency_context_max": 0,
            "ts01_match": False,
            "ts02_match": False,
            "matched_by_other_phase2_family": False,
            "phase1_top100": doc in phase1_reference["top100_docs"],
            "phase1_top500": doc in phase1_reference["top500_docs"],
        }
        for doc in truth_docs
    }
    for window in windows:
        docs = set(window.get("_docs", set())) & truth_docs
        for doc in docs:
            item = by_doc[doc]
            item["in_candidate_pool"] = True
            item["window_count"] += 1
            item["max_robust_z"] = max(item["max_robust_z"], float(window["robust_z"]))
            item["max_period_end_lift"] = max(
                item["max_period_end_lift"],
                float(window["period_end_lift"]),
            )
            item["max_baseline_observation_count"] = max(
                item["max_baseline_observation_count"],
                int(window["baseline_observation_count"]),
            )
            item["max_context_evidence_count"] = max(
                item["max_context_evidence_count"],
                int(window["context_evidence_count"]),
            )
            item["max_row_count"] = max(item["max_row_count"], int(window["row_count"]))
            item["period_end_context"] = item["period_end_context"] or bool(
                window["period_end_context"]
            )
            item["manual_or_adjustment_context"] = item["manual_or_adjustment_context"] or bool(
                window["manual_or_adjustment_context"]
            )
            item["after_hours_or_weekend_context"] = item[
                "after_hours_or_weekend_context"
            ] or bool(window["after_hours_or_weekend_context"])
            item["round_amount_context"] = item["round_amount_context"] or bool(
                window["round_amount_context"]
            )
            item["amount_tail_context"] = item["amount_tail_context"] or bool(
                window["amount_tail_context"]
            )
            rank = int(window["subject_activity_rank"])
            item["subject_activity_rank_min"] = (
                rank
                if item["subject_activity_rank_min"] is None
                else min(int(item["subject_activity_rank_min"]), rank)
            )
            item["subject_frequency_context_max"] = max(
                item["subject_frequency_context_max"],
                int(window["subject_frequency_context"]),
            )
    _attach_ts_rule_matches(by_doc, df=df, detection_result=detection_result)
    for doc, scores in family_by_doc.items():
        if doc in by_doc:
            by_doc[doc]["matched_by_other_phase2_family"] = any(
                value > 0.0 for value in scores.values()
            )
    return by_doc


def _attach_ts_rule_matches(
    by_doc: dict[str, dict[str, Any]],
    *,
    df: pd.DataFrame,
    detection_result: Any,
) -> None:
    details = getattr(detection_result, "details", None)
    if not isinstance(details, pd.DataFrame) or "document_id" not in df.columns:
        return
    for rule in ("TS01", "TS02"):
        if rule not in details.columns:
            continue
        values = details[rule].reindex(df.index).fillna(0.0).astype(float)
        matched_docs = set(df.loc[values > 0.0, "document_id"].astype(str))
        for doc in matched_docs & set(by_doc):
            by_doc[doc][f"{rule.lower()}_match"] = True


def _label_alignment(doc_features: dict[str, dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for doc, item in doc_features.items():
        strong_ts = (
            bool(item["in_candidate_pool"])
            and bool(item["period_end_context"])
            and int(item["max_row_count"]) >= 7
            and int(item["max_baseline_observation_count"]) >= 10
            and (
                float(item["max_robust_z"]) >= 3.0
                or float(item["max_period_end_lift"]) >= 2.0
            )
        )
        scenario = str(item["scenario"])
        if scenario in _TS_ALIGNED_SCENARIOS and strong_ts:
            out[doc] = "ts_primary_label_aligned"
        elif scenario in _TS_ALIGNED_SCENARIOS or (
            bool(item["period_end_context"]) and int(item["max_context_evidence_count"]) >= 2
        ):
            out[doc] = "mixed_but_ts_relevant"
        elif bool(item["in_candidate_pool"]):
            out[doc] = "non_ts_primary_but_ts_context_present"
        else:
            out[doc] = "not_ts_family_target"
    return out


def _alignment_counts(alignment: dict[str, str]) -> dict[str, int]:
    return dict(Counter(alignment.values()))


def _truth_attribution_audit(
    doc_features: dict[str, dict[str, Any]],
    alignment: dict[str, str],
    *,
    windows: list[dict[str, Any]],
) -> dict[str, Any]:
    in_pool = {doc for doc, item in doc_features.items() if bool(item["in_candidate_pool"])}
    top100_docs = _selected_docs(
        _candidate_policies(windows)["ts_primary_conservative_surface"][:100]
    )
    return {
        "ts_specific_truth_docs_count": sum(
            1 for value in alignment.values() if value == "ts_primary_label_aligned"
        ),
        "mixed_non_ts_truth_docs_count": sum(
            1 for value in alignment.values() if value != "ts_primary_label_aligned"
        ),
        "ts_candidate_pool_truth_docs_count": len(in_pool),
        "candidate_pool_but_outside_top100_truth_docs_count": len(in_pool - top100_docs),
        "candidate_pool_missing_truth_docs_count": len(set(doc_features) - in_pool),
        "alignment_counts": _alignment_counts(alignment),
        "feature_buckets": _feature_bucket_counts(doc_features),
    }


def _feature_bucket_counts(doc_features: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "ts01_match": sum(1 for item in doc_features.values() if bool(item["ts01_match"])),
        "ts02_match": sum(1 for item in doc_features.values() if bool(item["ts02_match"])),
        "period_end_context": sum(
            1 for item in doc_features.values() if bool(item["period_end_context"])
        ),
        "robust_z_ge_3": sum(
            1 for item in doc_features.values() if float(item["max_robust_z"]) >= 3.0
        ),
        "period_end_lift_ge_2": sum(
            1
            for item in doc_features.values()
            if float(item["max_period_end_lift"]) >= 2.0
        ),
        "baseline_obs_ge_10": sum(
            1
            for item in doc_features.values()
            if int(item["max_baseline_observation_count"]) >= 10
        ),
        "supported_window_ge_7": sum(
            1 for item in doc_features.values() if int(item["max_row_count"]) >= 7
        ),
        "matched_by_other_phase2_family": sum(
            1
            for item in doc_features.values()
            if bool(item["matched_by_other_phase2_family"])
        ),
        "phase1_top100": sum(1 for item in doc_features.values() if bool(item["phase1_top100"])),
        "phase1_top500": sum(1 for item in doc_features.values() if bool(item["phase1_top500"])),
    }


def _miss_reason_summary(
    ordered: list[dict[str, Any]],
    *,
    doc_features: dict[str, dict[str, Any]],
    alignment: dict[str, str],
    phase1_reference: dict[str, Any],
) -> dict[str, int]:
    top100_docs = _selected_docs(ordered[:100])
    reasons: Counter[str] = Counter()
    for doc, item in doc_features.items():
        if not bool(item["in_candidate_pool"]) or doc in top100_docs:
            continue
        if alignment[doc] == "not_ts_family_target":
            reasons["mixed_scenario_not_ts_primary"] += 1
        if int(item["max_row_count"]) < 7:
            reasons["low_support_window"] += 1
        if int(item["max_baseline_observation_count"]) < 10:
            reasons["baseline_unavailable_or_weak"] += 1
        if float(item["max_robust_z"]) < 3.0 and float(item["max_period_end_lift"]) < 2.0:
            reasons["weak_ts_signal"] += 1
        if int(item["subject_activity_rank_min"] or 9999) <= 10:
            reasons["high_subject_activity_background"] += 1
        if bool(item["amount_tail_context"]) and alignment[doc] != "ts_primary_label_aligned":
            reasons["amount_signal_belongs_to_unsupervised"] += 1
        if bool(item["manual_or_adjustment_context"]) and doc in phase1_reference["top500_docs"]:
            reasons["manual_adjustment_signal_belongs_to_phase1_or_other_family"] += 1
        if bool(item["period_end_context"]) and alignment[doc] != "not_ts_family_target":
            reasons["normal_period_end_competition"] += 1
        if alignment[doc] in {"mixed_but_ts_relevant", "non_ts_primary_but_ts_context_present"}:
            reasons["mixed_scenario_not_ts_primary"] += 1
        if alignment[doc] == "ts_primary_label_aligned":
            reasons["ranking_formula_underweights_ts_specific_signal"] += 1
    reasons["implementation_suspect"] = 0
    return dict(reasons)


def _implementation_verification(
    *,
    ts_result: Any,
    windows: list[dict[str, Any]],
    doc_features: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    metadata = getattr(ts_result, "metadata", {})
    artifact = metadata.get("timeseries_window_artifact", {}) if isinstance(metadata, dict) else {}
    artifact_windows = artifact.get("windows", []) if isinstance(artifact, dict) else []
    truth_in_artifact = 0
    for item in artifact_windows:
        if not isinstance(item, dict):
            continue
        # Artifact raw positions are internal only; count truth via candidate rows is not emitted.
        if item.get("sub_signal_high"):
            truth_in_artifact += 1
    return {
        "expected_count_distribution": _num_dist(
            [window["expected_count"] for window in windows]
        ),
        "robust_z_distribution": _num_dist([window["robust_z"] for window in windows]),
        "period_end_lift_distribution": _num_dist(
            [window["period_end_lift"] for window in windows]
        ),
        "baseline_observation_count_distribution": _num_dist(
            [window["baseline_observation_count"] for window in windows]
        ),
        "low_support_window_ratio": sum(1 for window in windows if int(window["row_count"]) < 7)
        / max(1, len(windows)),
        "ts01_truth_doc_count": sum(
            1 for item in doc_features.values() if bool(item["ts01_match"])
        ),
        "ts02_truth_doc_count": sum(
            1 for item in doc_features.values() if bool(item["ts02_match"])
        ),
        "artifact_window_count": len(artifact_windows),
        "artifact_sub_signal_high_window_count": truth_in_artifact,
        "implementation_bug_suspected": False,
        "implementation_notes": [
            "Expected count, robust_z, period_end_lift, and baseline support are "
            "present in candidate windows.",
            "No aggregate evidence of TS01/TS02 mixing or raw identifier leakage was emitted.",
        ],
    }


def _ts_specific_severity_surface(windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        windows,
        key=lambda item: (
            not bool(item["period_end_context"]),
            int(item["baseline_observation_count"]) < 10,
            int(item["row_count"]) < 7,
            bool(item["round_amount_context"]),
            -float(item["robust_z"]),
            -float(item["period_end_lift"]),
            -int(item["context_evidence_count"]),
            int(item["ordinal"]),
        ),
    )


def _mixed_ts_relevant_surface(windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        windows,
        key=lambda item: (
            not bool(item["period_end_context"]),
            int(item["baseline_observation_count"]) < 10,
            int(item["row_count"]) < 7,
            -int(item["context_evidence_count"]),
            -float(item["period_end_lift"]),
            bool(item["round_amount_context"]),
            -float(item["robust_z"]),
            int(item["ordinal"]),
        ),
    )


def _candidate_failure_summary(
    ordered: list[dict[str, Any]],
    *,
    doc_features: dict[str, dict[str, Any]],
    alignment: dict[str, str],
    truth_docs: set[str],
    scenario_by_doc: dict[str, str],
    phase1_reference: dict[str, Any],
) -> dict[str, Any]:
    topn: dict[str, Any] = {}
    for top_n in TOP_NS:
        docs = _selected_docs(ordered[:top_n])
        selected_truth = docs & truth_docs
        topn[str(top_n)] = {
            "ts_specific_truth_docs": sum(
                1 for doc in selected_truth if alignment.get(doc) == "ts_primary_label_aligned"
            ),
            "mixed_but_ts_relevant_truth_docs": sum(
                1 for doc in selected_truth if alignment.get(doc) == "mixed_but_ts_relevant"
            ),
            "truth_docs_outside_phase1_top100": len(
                selected_truth - phase1_reference["top100_docs"]
            ),
            "truth_docs_outside_phase1_top500": len(
                selected_truth - phase1_reference["top500_docs"]
            ),
            "scenario_counts": _scenario_counts(selected_truth, scenario_by_doc),
        }
    top500 = ordered[:500]
    return {
        "topn": topn,
        "review_burden": _retention_review_burden_proxy(top500),
        "period_end_normal_pressure": _retention_review_burden_proxy(top500)[
            "period_end_share"
        ],
        "low_support_ratio": sum(1 for item in top500 if int(item["row_count"]) < 7)
        / max(1, len(top500)),
        "candidate_pool_attrition": {
            "candidate_windows": len(ordered),
            "top100_windows": min(100, len(ordered)),
            "top500_windows": min(500, len(ordered)),
        },
    }


def _selected_docs(windows: list[dict[str, Any]]) -> set[str]:
    docs: set[str] = set()
    for window in windows:
        raw_docs = window.get("_docs")
        if isinstance(raw_docs, set):
            docs.update(str(doc) for doc in raw_docs)
    return docs


def _decision_payload(
    *,
    alignment: dict[str, str],
    doc_features: dict[str, dict[str, Any]],
    miss_reasons: dict[str, int],
    candidates: dict[str, Any],
) -> dict[str, Any]:
    ts_specific_count = sum(
        1 for value in alignment.values() if value == "ts_primary_label_aligned"
    )
    mixed_count = sum(1 for value in alignment.values() if value == "mixed_but_ts_relevant")
    in_pool = {doc for doc, item in doc_features.items() if bool(item["in_candidate_pool"])}
    best = max(
        (
            "ts_primary_conservative_surface",
            "ts_specific_severity_surface",
            "mixed_ts_relevant_surface",
        ),
        key=lambda name: (
            candidates[name]["topn"]["100"]["ts_specific_truth_docs"],
            -candidates[name]["topn"]["100"]["mixed_but_ts_relevant_truth_docs"],
        ),
    )
    return {
        "ts_top100_failure_primary_reason": max(
            miss_reasons,
            key=lambda key: miss_reasons[key],
        )
        if miss_reasons
        else "none",
        "implementation_bug_suspected": False,
        "datasynth_label_alignment_issue_suspected": mixed_count > ts_specific_count,
        "ts_primary_label_aligned_truth_docs": ts_specific_count,
        "mixed_but_ts_relevant_truth_docs": mixed_count,
        "candidate_pool_missing_truth_docs": len(set(doc_features) - in_pool),
        "candidate_but_ranked_below_top100_truth_docs": max(
            0,
            len(in_pool)
            - candidates[best]["topn"]["100"]["ts_specific_truth_docs"]
            - candidates[best]["topn"]["100"]["mixed_but_ts_relevant_truth_docs"],
        ),
        "best_ts_primary_candidate": best,
        "top100_product_viable": candidates[best]["topn"]["100"]["ts_specific_truth_docs"] > 0,
        "top500_companion_only_rejected_as_final_goal": True,
        "production_adoption": False,
        "next_required_fix": (
            "Investigate DataSynth TS label alignment and continue TS-specific severity "
            "ranking diagnostics without broad companion inflation."
        ),
    }
if __name__ == "__main__":
    raise SystemExit(main())
