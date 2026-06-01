"""VAE/unsupervised v3.2d exact owner-surface diagnostic.

Diagnostic-only. This measures the current VAE document surfaces against the
v3.2d responsibility map with exact matched-document joins. Scenario-level
proration is retained only as a historical/reference estimate.
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.scripts.diagnose_unsupervised_v31_owner_surface_fixed5_20260531 import (
    BATCH_ID,
    PHASE1_CASE_RESULT,
    _document_records,
    _family_cases,
    _primary_top100_gap_analysis,
    _role_summary,
    _role_surface_metrics,
    _surface_orders,
    _topk_details_from_bundle,
    _unsupervised_case_rows,
    attach_phase1_document_prior,
    build_phase1_baseline,
    build_phase2_case_set,
    identifier_leak_check,
    load_model_bundle,
)

V32_RESPONSIBILITY = import_module(
    "tools.scripts."
    "measure_phase2_family_responsibility_recall_v32_fixed5_ownermeta_v32d_20260531"
)

OUT_JSON = (
    ROOT
    / "artifacts"
    / "unsupervised_v32_exact_owner_surface_fixed5_20260531.json"
)
V32_RESPONSIBILITY_ARTIFACT = V32_RESPONSIBILITY.OUT_JSON
DATASET_NAME = V32_RESPONSIBILITY.CANDIDATE_NAME


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _load_v32_truth() -> pd.DataFrame:
    truth = pd.read_csv(V32_RESPONSIBILITY.TRUTH_PATH, dtype=str).fillna("")
    truth["document_id"] = truth["document_id"].astype(str)
    return truth


def _load_v32_case_input() -> pd.DataFrame:
    df = pd.read_csv(V32_RESPONSIBILITY.JOURNAL_PATH, low_memory=False)
    df["document_id"] = df["document_id"].astype(str)
    return df


def _owner_doc_sets(truth: pd.DataFrame) -> dict[str, set[str]]:
    masks = V32_RESPONSIBILITY._owner_masks(truth)
    return {
        "primary": set(
            truth.loc[masks["unsupervised"]["primary"], "document_id"].astype(str)
        ),
        "companion": set(
            truth.loc[masks["unsupervised"]["companion"], "document_id"].astype(str)
        ),
    }


def _load_proration_reference() -> dict[str, Any]:
    if not V32_RESPONSIBILITY_ARTIFACT.exists():
        return {"status": "v32_responsibility_artifact_missing"}
    payload = json.loads(V32_RESPONSIBILITY_ARTIFACT.read_text(encoding="utf-8"))
    topn = payload["primary_owner_target_recall_v32"]["unsupervised"]["topn"]
    return {
        "status": "historical_reference_not_official_for_v32_split_owner",
        "measurement_basis": "scenario_level_proration",
        "topn": {
            key: {
                "matched_docs_estimated_proration": value.get(
                    "matched_docs_estimated_proration"
                ),
                "recall_estimated_proration": value.get(
                    "recall_estimated_proration"
                ),
                "official_status_in_v32_artifact": value.get("status"),
            }
            for key, value in topn.items()
        },
    }


def build_payload() -> dict[str, Any]:
    started = time.perf_counter()
    df = _load_v32_case_input()
    truth = _load_v32_truth()
    role_docs = _owner_doc_sets(truth)
    all_role_docs = set().union(*role_docs.values())

    result = _topk_details_from_bundle(df, load_model_bundle())
    case_set = build_phase2_case_set(
        batch_id=f"{BATCH_ID}_v32d_journal",
        detection_results=[result],
        df=df,
        unsupervised_model_id="stage7-fixed5-model-bundle-v1",
        unsupervised_schema_hash="stage7-fixed5-normalcal5",
    )
    cases = list(_family_cases(case_set, "unsupervised"))
    rows = attach_phase1_document_prior(
        _unsupervised_case_rows(cases, df=df, truth_docs=all_role_docs),
        df,
    )
    records = _document_records(rows)
    phase1 = build_phase1_baseline(df, all_role_docs, case_result_path=PHASE1_CASE_RESULT)
    surface_orders = _surface_orders(cases, records)

    primary_metrics = _role_surface_metrics(
        surface_orders,
        role_docs=role_docs["primary"],
        phase1=phase1,
        rows=rows,
        records=records,
    )
    companion_metrics = _role_surface_metrics(
        surface_orders,
        role_docs=role_docs["companion"],
        phase1=phase1,
        rows=rows,
        records=records,
    )
    default_name = "hybrid_with_soft_repeated_normal_guard"
    probe_name = "soft_guard_context_top100_probe"
    default_primary = primary_metrics[default_name]
    probe_primary = primary_metrics[probe_name]
    pressure_delta = (
        probe_primary["top500_pressure"]["repeated_normal_pressure"]
        - default_primary["top500_pressure"]["repeated_normal_pressure"]
    )

    payload: dict[str, Any] = {
        "generated_at": _now_iso(),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "dataset": DATASET_NAME,
        "responsibility_map": "v3.2d",
        "source_candidate": V32_RESPONSIBILITY.CANDIDATE_NAME,
        "detector_input_source": str(
            V32_RESPONSIBILITY.JOURNAL_PATH.relative_to(ROOT)
        ).replace("\\", "/"),
        "phase1_action_tier_source": str(PHASE1_CASE_RESULT.relative_to(ROOT)).replace(
            "\\", "/"
        ),
        "diagnostic_only": True,
        "truth_label_used_for_scoring": False,
        "truth_label_used_only_for_aggregate_evaluation": True,
        "truth_or_owner_metadata_used_as_selector": False,
        "truth_or_owner_metadata_used_only_for_exact_matched_doc_join": True,
        "measurement_basis": "exact_matched_doc_join",
        "q95_gate_changed": False,
        "vae_score_or_threshold_changed": False,
        "case_generation_changed": False,
        "phase1_ranking_changed": False,
        "phase2_fusion_changed": False,
        "product_default_changed_by_this_diagnostic": False,
        "current_product_default_surface": default_name,
        "role_denominators": {
            "primary": _role_summary(role_docs["primary"], phase1),
            "companion": _role_summary(role_docs["companion"], phase1),
        },
        "surface_metrics_by_role": {
            "primary": primary_metrics,
            "companion": companion_metrics,
        },
        "primary_top100_gap_analysis": _primary_top100_gap_analysis(
            surface_orders=surface_orders,
            primary_docs=role_docs["primary"],
            phase1=phase1,
            primary_metrics=primary_metrics,
        ),
        "scenario_proration_reference": _load_proration_reference(),
        "decision": {
            "adopted_surface": default_name,
            "probe_surface": probe_name,
            "change_product_default_now": False,
            "probe_top100_lift_vs_adopted": (
                int(probe_primary["topn"]["100"]["matched_docs"])
                - int(default_primary["topn"]["100"]["matched_docs"])
            ),
            "probe_top500_lift_vs_adopted": (
                int(probe_primary["topn"]["500"]["matched_docs"])
                - int(default_primary["topn"]["500"]["matched_docs"])
            ),
            "probe_repeated_normal_pressure_delta": pressure_delta,
            "probe_pressure_not_above_adopted": pressure_delta <= 0,
            "read": (
                "v3.2d exact owner join keeps the adopted soft guard as the "
                "single VAE family-list ordering. The TOP100 probe is diagnostic "
                "only until pressure and review-burden guardrails are validated."
            ),
        },
    }
    payload["raw_identifier_leak_check"] = identifier_leak_check(payload)
    return payload


def main() -> int:
    payload = build_payload()
    OUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "out": OUT_JSON.relative_to(ROOT).as_posix(),
                "primary_denominator": payload["role_denominators"]["primary"][
                    "truth_docs"
                ],
                "companion_denominator": payload["role_denominators"]["companion"][
                    "truth_docs"
                ],
                "adopted_top100": payload["surface_metrics_by_role"]["primary"][
                    "hybrid_with_soft_repeated_normal_guard"
                ]["topn"]["100"]["matched_docs"],
                "adopted_top500": payload["surface_metrics_by_role"]["primary"][
                    "hybrid_with_soft_repeated_normal_guard"
                ]["topn"]["500"]["matched_docs"],
                "probe_top100": payload["surface_metrics_by_role"]["primary"][
                    "soft_guard_context_top100_probe"
                ]["topn"]["100"]["matched_docs"],
                "probe_pressure_delta": payload["decision"][
                    "probe_repeated_normal_pressure_delta"
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
