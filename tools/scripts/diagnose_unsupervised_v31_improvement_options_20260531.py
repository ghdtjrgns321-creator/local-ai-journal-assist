"""VAE/unsupervised v3.1 improvement option synthesis.

Reads the v3.1 owner-surface artifact and compares remaining fitting-free
surfaces. No detector, threshold, q95 gate, PHASE1 ranking, or PHASE2 fusion
changes are made here.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "artifacts" / "unsupervised_v31_owner_surface_fixed5_20260531.json"
OUT_JSON = ROOT / "artifacts" / "unsupervised_v31_improvement_options_20260531.json"


def _surface_row(payload: dict[str, Any], role: str, surface: str) -> dict[str, Any]:
    value = payload["surface_metrics_by_role"][role][surface]
    topn = value["topn"]
    pressure = value["top500_pressure"]
    return {
        "top100_matched": topn["100"]["matched_docs"],
        "top500_matched": topn["500"]["matched_docs"],
        "top100_recall": topn["100"]["recall"],
        "top500_recall": topn["500"]["recall"],
        "top500_phase1_immediate_outside": topn["500"][
            "phase1_immediate_review_outside_docs"
        ],
        "top500_phase1_review_or_above_outside": topn["500"][
            "phase1_review_or_above_outside_docs"
        ],
        "top500_repeated_normal_pressure": pressure["repeated_normal_pressure"],
        "top500_period_end_normal_background_ratio": pressure[
            "period_end_normal_background_ratio"
        ],
        "top500_process_top1_share": pressure["process_concentration"]["top1_share"],
        "top500_account_top1_share": pressure["account_concentration"]["top1_share"],
    }


def build_payload() -> dict[str, Any]:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    primary = source["role_denominators"]["primary"]["truth_docs"]
    companion = source["role_denominators"]["companion"]["truth_docs"]
    surfaces = [
        "native_row_queue",
        "hybrid_with_soft_repeated_normal_guard",
        "soft_guard_with_row_count_context",
        "hybrid_row_count_blended_surface_upper_bound",
        "soft_guard_pressure_guard_surface",
    ]
    primary_rows = {name: _surface_row(source, "primary", name) for name in surfaces}
    companion_rows = {name: _surface_row(source, "companion", name) for name in surfaces}
    soft = primary_rows["hybrid_with_soft_repeated_normal_guard"]
    context = primary_rows["soft_guard_with_row_count_context"]
    upper = primary_rows["hybrid_row_count_blended_surface_upper_bound"]
    pressure_guard = primary_rows["soft_guard_pressure_guard_surface"]
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source_artifact": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "diagnostic_only": True,
        "responsibility_map": "v3.1",
        "q95_gate_changed": False,
        "vae_score_or_threshold_changed": False,
        "phase1_ranking_changed": False,
        "phase2_fusion_changed": False,
        "truth_label_used_for_scoring": False,
        "truth_label_used_only_for_aggregate_evaluation": True,
        "role_denominators": {
            "primary": primary,
            "companion": companion,
        },
        "primary_surface_options": primary_rows,
        "companion_surface_options": companion_rows,
        "incremental_options_vs_adopted_soft_guard": {
            "soft_guard_with_row_count_context": {
                "top100_delta": context["top100_matched"] - soft["top100_matched"],
                "top500_delta": context["top500_matched"] - soft["top500_matched"],
                "repeated_normal_pressure_delta": (
                    context["top500_repeated_normal_pressure"]
                    - soft["top500_repeated_normal_pressure"]
                ),
                "read": (
                    "Small primary lift, but pressure worsens. Keep diagnostic-only "
                    "unless pressure guard improves."
                ),
            },
            "hybrid_row_count_blended_surface_upper_bound": {
                "top100_delta": upper["top100_matched"] - soft["top100_matched"],
                "top500_delta": upper["top500_matched"] - soft["top500_matched"],
                "repeated_normal_pressure_delta": (
                    upper["top500_repeated_normal_pressure"]
                    - soft["top500_repeated_normal_pressure"]
                ),
                "read": (
                    "TOP100 lift is large but repeated-normal pressure is too high; "
                    "treat as upper bound, not product default."
                ),
            },
            "soft_guard_pressure_guard_surface": {
                "top100_delta": pressure_guard["top100_matched"] - soft["top100_matched"],
                "top500_delta": pressure_guard["top500_matched"] - soft["top500_matched"],
                "repeated_normal_pressure_delta": (
                    pressure_guard["top500_repeated_normal_pressure"]
                    - soft["top500_repeated_normal_pressure"]
                ),
                "read": "Pressure improves but recall collapses; reject as default.",
            },
        },
        "decision": {
            "current_default_surface": "hybrid_with_soft_repeated_normal_guard",
            "change_default_now": False,
            "best_next_experiment": "soft_guard_with_row_count_context_pressure_control",
            "anti_fitting_guardrails": [
                "do not use PHASE1 prior as VAE score",
                "do not relax q95 gate",
                "do not use truth/scenario/owner metadata for ordering",
                "do not adopt upper-bound hybrid without pressure reduction",
            ],
        },
        "raw_identifier_leak_check": source["raw_identifier_leak_check"],
    }


def main() -> int:
    payload = build_payload()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "out": OUT_JSON.relative_to(ROOT).as_posix(),
                "current_default": payload["decision"]["current_default_surface"],
                "best_next_experiment": payload["decision"]["best_next_experiment"],
                "soft_guard_primary_top500": payload["primary_surface_options"][
                    "hybrid_with_soft_repeated_normal_guard"
                ]["top500_matched"],
                "context_primary_top500": payload["primary_surface_options"][
                    "soft_guard_with_row_count_context"
                ]["top500_matched"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
