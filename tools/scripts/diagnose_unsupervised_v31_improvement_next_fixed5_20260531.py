"""VAE/unsupervised v3.1 next-improvement diagnostic.

Reads the checked-in v3.1 owner surface artifact and emits an aggregate-only
decision payload. No detector, score, threshold, q95 gate, PHASE1 ranking, or
PHASE2 fusion behavior is changed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "artifacts" / "unsupervised_v31_owner_surface_fixed5_20260531.json"
OUT_JSON = ROOT / "artifacts" / "unsupervised_v31_improvement_next_fixed5_20260531.json"

ADOPTED = "hybrid_with_soft_repeated_normal_guard"
CONTEXT_CANDIDATE = "soft_guard_with_row_count_context"
UPPER_BOUND = "hybrid_row_count_blended_surface_upper_bound"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _surface(source: dict[str, Any], role: str, name: str) -> dict[str, Any]:
    item = source["surface_metrics_by_role"][role][name]
    return {
        "surface": name,
        "top100": item["topn"]["100"]["matched_docs"],
        "top500": item["topn"]["500"]["matched_docs"],
        "top10000": item["topn"]["10000"]["matched_docs"],
        "outside_phase1_review_or_above_top500": item["topn"]["500"][
            "phase1_review_or_above_outside_docs"
        ],
        "outside_phase1_candidate_or_above_top500": item["topn"]["500"][
            "phase1_candidate_or_above_outside_docs"
        ],
        "repeated_normal_pressure_top500": item["top500_pressure"][
            "repeated_normal_pressure"
        ],
        "period_end_normal_background_top500": item["top500_pressure"][
            "period_end_normal_background_ratio"
        ],
        "account_top1_share_top500": item["top500_pressure"]["account_concentration"][
            "top1_share"
        ],
        "process_top1_share_top500": item["top500_pressure"]["process_concentration"][
            "top1_share"
        ],
    }


def main() -> int:
    source = _read_json(SOURCE)
    primary_adopted = _surface(source, "primary", ADOPTED)
    primary_context = _surface(source, "primary", CONTEXT_CANDIDATE)
    primary_upper = _surface(source, "primary", UPPER_BOUND)
    companion_adopted = _surface(source, "companion", ADOPTED)
    companion_context = _surface(source, "companion", CONTEXT_CANDIDATE)
    companion_upper = _surface(source, "companion", UPPER_BOUND)

    payload: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "diagnostic_only": True,
        "source_artifact": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "production_default_currently_adopted": ADOPTED,
        "q95_gate_changed": False,
        "vae_score_or_threshold_changed": False,
        "phase1_ranking_changed": False,
        "phase2_fusion_changed": False,
        "truth_or_owner_metadata_used_as_selector": False,
        "truth_or_owner_metadata_used_only_for_aggregate_evaluation": True,
        "role_denominators": source["role_denominators"],
        "primary_surface_comparison": {
            "adopted_soft_guard": primary_adopted,
            "row_count_context_candidate": primary_context,
            "upper_bound_not_adoptable": primary_upper,
            "row_count_context_lift_vs_adopted": {
                "top100": primary_context["top100"] - primary_adopted["top100"],
                "top500": primary_context["top500"] - primary_adopted["top500"],
                "pressure_delta": (
                    primary_context["repeated_normal_pressure_top500"]
                    - primary_adopted["repeated_normal_pressure_top500"]
                ),
            },
            "upper_bound_lift_vs_adopted": {
                "top100": primary_upper["top100"] - primary_adopted["top100"],
                "top500": primary_upper["top500"] - primary_adopted["top500"],
                "pressure_delta": (
                    primary_upper["repeated_normal_pressure_top500"]
                    - primary_adopted["repeated_normal_pressure_top500"]
                ),
            },
        },
        "companion_surface_comparison": {
            "adopted_soft_guard": companion_adopted,
            "row_count_context_candidate": companion_context,
            "upper_bound_not_adoptable": companion_upper,
        },
        "decision": {
            "change_product_default_now": False,
            "reason": (
                "The only non-upper-bound primary lift over the adopted soft guard is "
                "small: TOP100 +7 and TOP500 +4, while repeated-normal pressure rises "
                "from 0.336 to 0.400. The aggressive upper bound improves TOP100 but "
                "raises pressure to 0.682. Keep the single VAE list on the adopted "
                "soft guard and monitor pressure."
            ),
            "next_improvement_class": "pressure_stable_primary_top100_lift",
            "next_prompt": (
                "Run a diagnostic-only pressure-stable VAE TOP100 experiment: start "
                "from hybrid_with_soft_repeated_normal_guard, allow only observable "
                "document context already present in UnsupervisedCase, and require "
                "primary TOP100 lift without increasing TOP500 repeated-normal "
                "pressure above the adopted 0.336 baseline. Do not use PHASE1 prior, "
                "truth/owner metadata, q95 near-miss promotion, or top_features as "
                "ranking inputs."
            ),
        },
        "raw_identifier_leak_check": source["raw_identifier_leak_check"],
    }

    OUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
