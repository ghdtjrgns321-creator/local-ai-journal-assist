"""Evaluation helpers for phase-specific reports."""

from typing import Any

__all__ = ["Phase2EvaluationReport", "bootstrap_ci", "groupkfold_recall_at_k"]


def __getattr__(name: str) -> Any:
    if name == "Phase2EvaluationReport":
        from src.evaluation.phase2_report import Phase2EvaluationReport

        return Phase2EvaluationReport
    if name in {"bootstrap_ci", "groupkfold_recall_at_k"}:
        from src.evaluation.scenario_detectability import bootstrap_ci, groupkfold_recall_at_k

        exports = {
            "bootstrap_ci": bootstrap_ci,
            "groupkfold_recall_at_k": groupkfold_recall_at_k,
        }
        return exports[name]
    raise AttributeError(name)
