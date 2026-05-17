from __future__ import annotations

from src.services.phase2_evaluation import evaluate_phase2_value_gates


def test_anti_shortcut_cap_blocks_four_x_trivial_outperformance():
    result = evaluate_phase2_value_gates(
        {
            "ensemble_macro_auprc": 0.99,
            "trivial_10feature_macro_auprc": 0.13,
            "scenario_delta_recall": {
                "approval_sod_bypass": 0.10,
                "circular_related_party": 0.10,
                "embezzlement_concealment": 0.10,
                "fictitious_entry": 0.10,
                "period_end_adjustment": 0.10,
                "unusual_timing_manipulation": 0.10,
            },
        }
    )

    assert result["status"] == "BLOCK"
    assert result["policy"] == "AND"
    gate = result["gates"]["anti_shortcut_cap"]
    assert gate["status"] == "BLOCK"
    assert gate["observed"] > 4.0
    assert gate["reason"] == "shortcut_suspected_block_until_dataset_v4"
