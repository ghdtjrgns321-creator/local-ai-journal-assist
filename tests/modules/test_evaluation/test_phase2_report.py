from __future__ import annotations

import pytest

from src.evaluation.phase2_report import (
    Phase2EvaluationReport,
    assert_no_insignificant_significance_claims,
)


def _valid_ensemble() -> dict:
    return {
        "macro_f2_unweighted": {
            "value": 0.41,
            "bootstrap_ci": {"low": 0.35, "high": 0.47},
        },
        "macro_f2_prevalence_weighted": {
            "value": 0.37,
            "bootstrap_ci": {"low": 0.31, "high": 0.42},
        },
        "scenarios": {
            "embezzlement_concealment": {
                "recall": 0.62,
                "precision": 0.44,
                "bootstrap_ci": {"low": 0.50, "high": 0.70},
                "delta_recall_vs_trivial": 0.62,
            },
            "unusual_timing_manipulation": {
                "recall": 0.80,
                "precision": 0.36,
                "bootstrap_ci": {"low": 0.64, "high": 0.91},
                "delta_recall_vs_trivial": 0.10,
            },
        },
        "fold_scenario_truth_count": [
            {
                "fold": 0,
                "embezzlement_concealment": 15,
                "unusual_timing_manipulation": 5,
            },
            {
                "fold": 1,
                "embezzlement_concealment": 16,
                "unusual_timing_manipulation": 4,
            },
        ],
    }


def _valid_trivial() -> dict:
    return {
        "scenarios": {
            "embezzlement_concealment": {
                "recall": 0.0,
                "precision": 0.0,
                "bootstrap_ci": {"low": 0.0, "high": 0.0},
            },
            "unusual_timing_manipulation": {
                "recall": 0.70,
                "precision": 0.10,
                "bootstrap_ci": {"low": 0.50, "high": 0.85},
            },
        }
    }


def _valid_phase1() -> dict:
    return {
        "macro_f2_unweighted": {
            "value": 0.25,
            "bootstrap_ci": {"low": 0.20, "high": 0.30},
        },
        "macro_f2_prevalence_weighted": {
            "value": 0.22,
            "bootstrap_ci": {"low": 0.18, "high": 0.27},
        },
        "scenarios": {
            "embezzlement_concealment": {
                "recall": 0.20,
                "precision": 0.30,
                "bootstrap_ci": {"low": 0.10, "high": 0.31},
            }
        },
    }


def test_phase2_evaluation_report_accepts_valid_protocol_payload():
    report = Phase2EvaluationReport(
        _valid_ensemble(),
        _valid_trivial(),
        _valid_phase1(),
    )

    assert "P1 bootstrap CI: enforced" in report.to_markdown()


def test_p2_rejects_unusual_timing_fold_level_statistics():
    ensemble = _valid_ensemble()
    ensemble["scenarios"]["unusual_timing_manipulation"]["fold_mean_recall"] = 0.82

    with pytest.raises(ValueError, match="P2 unusual_timing"):
        Phase2EvaluationReport(ensemble, _valid_trivial(), _valid_phase1())


def test_p4_rejects_missing_trivial_baseline():
    with pytest.raises(ValueError, match="P4 trivial_baseline"):
        Phase2EvaluationReport(_valid_ensemble(), None, _valid_phase1())


def test_conclusion_guard_rejects_significance_claim_with_insignificant_marker():
    markdown = """
# Phase 2 Evaluation Report

Some row has [insignificant].

## Conclusion

통계적 유의 개선으로 판단한다.
"""
    with pytest.raises(ValueError, match="insignificant"):
        assert_no_insignificant_significance_claims(markdown)
