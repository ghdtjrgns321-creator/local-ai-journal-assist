"""Phase 2 evaluation report helpers."""

from __future__ import annotations

import argparse
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

HOLD_OUT_CAVEAT = (
    "n=50, 95% CI ≈ ±0.14, 시나리오 단위 hold-out "
    "(true zero-day fraud type 아님)"
)
INSIGNIFICANT_MARKER = "[insignificant]"
SIGNIFICANCE_CLAIM_RE = re.compile(r"(통계적\s*유의|statistically\s+significant)", re.I)
FOLD_STAT_KEYS = {
    "fold",
    "fold_id",
    "fold_idx",
    "fold_index",
    "fold_mean_recall",
    "fold_std_recall",
    "mean_n_truth_per_fold",
    "n_truth_in_fold",
}


def build_hold_out_metrics(
    test_df: pd.DataFrame,
    detect_result,
    *,
    hold_out_scenarios: tuple[str, ...],
    scenario_column: str = "mutation_type",
    document_column: str = "document_id",
) -> dict[str, Any]:
    """Compute document-level recall for Phase 2 hold-out scenarios."""
    scenarios = tuple(str(value).strip().lower() for value in hold_out_scenarios if value)
    base = {
        "available": False,
        "scenario_column": scenario_column,
        "document_column": document_column,
        "hold_out_scenarios": list(hold_out_scenarios),
        "hold_out_recall": None,
        "hold_out_pass": False,
        "ci95": {"lower": None, "upper": None, "half_width": None},
        "caveat": HOLD_OUT_CAVEAT,
    }
    if (
        not scenarios
        or scenario_column not in test_df.columns
        or document_column not in test_df.columns
    ):
        return base

    scenario_values = test_df[scenario_column].fillna("").astype(str).str.strip().str.lower()
    hold_out_df = test_df.loc[scenario_values.isin(scenarios)]
    doc_ids = set(hold_out_df[document_column].dropna().astype(str).unique())
    total_docs = len(doc_ids)
    if total_docs == 0:
        return {
            **base,
            "available": True,
            "hold_out_doc_count": 0,
            "hold_out_detected_docs": 0,
            "by_scenario": _hold_out_scenario_counts(
                hold_out_df,
                detected_doc_ids=set(),
                scenarios=scenarios,
                scenario_column=scenario_column,
                document_column=document_column,
            ),
        }

    flagged_index = pd.Index(list(getattr(detect_result, "flagged_indices", []) or []))
    flagged_df = hold_out_df.loc[hold_out_df.index.isin(flagged_index)]
    detected_doc_ids = set(flagged_df[document_column].dropna().astype(str).unique())
    detected_docs = len(doc_ids & detected_doc_ids)
    recall = detected_docs / total_docs
    ci = _normal_binomial_ci(recall, total_docs)
    return {
        **base,
        "available": True,
        "hold_out_doc_count": total_docs,
        "hold_out_detected_docs": detected_docs,
        "hold_out_recall": recall,
        "hold_out_pass": detected_docs >= 25 if total_docs == 50 else recall >= 0.5,
        "ci95": ci,
        "by_scenario": _hold_out_scenario_counts(
            hold_out_df,
            detected_doc_ids=detected_doc_ids,
            scenarios=scenarios,
            scenario_column=scenario_column,
            document_column=document_column,
        ),
    }


def _normal_binomial_ci(recall: float, n: int) -> dict[str, float]:
    half_width = 1.96 * float(np.sqrt((recall * (1.0 - recall)) / max(n, 1)))
    return {
        "lower": max(0.0, recall - half_width),
        "upper": min(1.0, recall + half_width),
        "half_width": half_width,
    }


def _hold_out_scenario_counts(
    hold_out_df: pd.DataFrame,
    *,
    detected_doc_ids: set[str],
    scenarios: tuple[str, ...],
    scenario_column: str,
    document_column: str,
) -> dict[str, dict[str, Any]]:
    breakdown: dict[str, dict[str, Any]] = {}
    scenario_values = hold_out_df[scenario_column].fillna("").astype(str).str.strip().str.lower()
    for scenario in scenarios:
        scenario_df = hold_out_df.loc[scenario_values.eq(scenario)]
        scenario_docs = set(scenario_df[document_column].dropna().astype(str).unique())
        detected = len(scenario_docs & detected_doc_ids)
        total = len(scenario_docs)
        breakdown[scenario] = {
            "doc_count": total,
            "detected_docs": detected,
            "recall": detected / total if total else None,
        }
    return breakdown


class Phase2EvaluationReport:
    """Validated container for Phase 2 ensemble-vs-baseline evaluation results."""

    def __init__(
        self,
        ensemble_results: Mapping[str, Any],
        trivial_baseline: Mapping[str, Any] | None,
        phase1_baseline: Mapping[str, Any],
    ) -> None:
        self.ensemble_results = ensemble_results
        self.trivial_baseline = trivial_baseline
        self.phase1_baseline = phase1_baseline
        self._validate_p1_through_p5()

    def _validate_p1_through_p5(self) -> None:
        errors: list[str] = []
        payload = {
            "ensemble_results": self.ensemble_results,
            "trivial_baseline": self.trivial_baseline,
            "phase1_baseline": self.phase1_baseline,
        }

        errors.extend(self._validate_p1_bootstrap_ci(payload))
        errors.extend(self._validate_p2_unusual_timing_fold_stats(payload))
        errors.extend(self._validate_p3_macro_f2(payload))
        errors.extend(self._validate_p4_delta_vs_trivial())
        errors.extend(self._validate_p5_fold_truth_matrix(payload))

        if errors:
            raise ValueError("Phase 2 evaluation protocol violation: " + "; ".join(errors))

    def to_markdown(self) -> str:
        lines = [
            "# Phase 2 Evaluation Report",
            "",
            "## Protocol Checks",
            "",
            "- P1 bootstrap CI: enforced",
            "- P2 unusual_timing fold-level statistics: blocked",
            "- P3 macro F2 variants: present",
            "- P4 delta recall vs trivial: present",
            "- P5 fold scenario truth count: present",
            "",
            "## Conclusion",
            "",
            self._conclusion_text(),
        ]
        markdown = "\n".join(lines)
        assert_no_insignificant_significance_claims(markdown)
        return markdown

    def _conclusion_text(self) -> str:
        markers = list(_iter_values_by_key(self.ensemble_results, "statistically_insignificant"))
        if any(bool(marker) for marker in markers):
            return (
                "[insignificant] Some confidence intervals are too wide "
                "for a significance claim."
            )
        return "No insignificant confidence-interval markers were reported."

    @staticmethod
    def _validate_p1_bootstrap_ci(payload: Mapping[str, Any]) -> list[str]:
        errors: list[str] = []
        for path, parent in _iter_metric_parents(payload):
            if "bootstrap_ci" not in parent:
                errors.append(f"P1 missing bootstrap_ci at {path}")
        return errors

    @staticmethod
    def _validate_p2_unusual_timing_fold_stats(payload: Mapping[str, Any]) -> list[str]:
        errors: list[str] = []
        for path, node in _walk(payload):
            if "fold_scenario_truth_count" in path:
                continue
            if not _path_has_unusual_timing(path, node):
                continue
            if _has_fold_stat(node):
                errors.append(f"P2 unusual_timing fold-level statistics are not allowed at {path}")
        return errors

    @staticmethod
    def _validate_p3_macro_f2(payload: Mapping[str, Any]) -> list[str]:
        required = {"macro_f2_unweighted", "macro_f2_prevalence_weighted"}
        present = {key for key in required if any(True for _ in _iter_values_by_key(payload, key))}
        missing = sorted(required - present)
        return [f"P3 missing {', '.join(missing)}"] if missing else []

    def _validate_p4_delta_vs_trivial(self) -> list[str]:
        if self.trivial_baseline is None:
            return ["P4 trivial_baseline is required for delta_recall_vs_trivial"]

        scenarios = set(_scenario_names(self.ensemble_results))
        scenarios.update(_scenario_names(self.trivial_baseline))
        missing = sorted(
            scenario
            for scenario in scenarios
            if not _scenario_has_key(self.ensemble_results, scenario, "delta_recall_vs_trivial")
        )
        if missing:
            return ["P4 missing delta_recall_vs_trivial for scenarios: " + ", ".join(missing)]
        return []

    @staticmethod
    def _validate_p5_fold_truth_matrix(payload: Mapping[str, Any]) -> list[str]:
        values = list(_iter_values_by_key(payload, "fold_scenario_truth_count"))
        if not values:
            return ["P5 missing fold_scenario_truth_count matrix"]
        if not any(_is_non_empty_matrix(value) for value in values):
            return ["P5 fold_scenario_truth_count matrix is empty"]
        return []


def assert_no_insignificant_significance_claims(markdown: str) -> None:
    """Block significance claims when the report marks CI results insignificant."""
    if INSIGNIFICANT_MARKER not in markdown:
        return
    conclusion = _extract_conclusion(markdown)
    if SIGNIFICANCE_CLAIM_RE.search(conclusion):
        raise ValueError(
            "Phase 2 report has [insignificant] marker but conclusion claims "
            "statistical significance"
        )


def _extract_conclusion(markdown: str) -> str:
    match = re.search(r"(?im)^#{1,6}\s*(conclusion|결론)\s*$", markdown)
    if not match:
        return ""
    tail = markdown[match.end() :]
    next_heading = re.search(r"(?m)^#{1,6}\s+\S", tail)
    return tail[: next_heading.start()] if next_heading else tail


def _iter_metric_parents(node: Any, path: str = "$") -> Iterable[tuple[str, Mapping[str, Any]]]:
    if isinstance(node, Mapping):
        metric_name = str(node.get("metric", "")).lower()
        if metric_name in {"recall", "precision"}:
            yield path, node
        for key, value in node.items():
            key_l = str(key).lower()
            if key_l in {"recall", "precision"} and value is not None:
                yield f"{path}.{key}", node
            yield from _iter_metric_parents(value, f"{path}.{key}")
    elif isinstance(node, list | tuple):
        for idx, item in enumerate(node):
            yield from _iter_metric_parents(item, f"{path}[{idx}]")


def _walk(node: Any, path: str = "$") -> Iterable[tuple[str, Any]]:
    yield path, node
    if isinstance(node, Mapping):
        for key, value in node.items():
            yield from _walk(value, f"{path}.{key}")
    elif isinstance(node, list | tuple):
        for idx, item in enumerate(node):
            yield from _walk(item, f"{path}[{idx}]")


def _iter_values_by_key(node: Any, wanted_key: str) -> Iterable[Any]:
    if isinstance(node, Mapping):
        for key, value in node.items():
            if key == wanted_key:
                yield value
            yield from _iter_values_by_key(value, wanted_key)
    elif isinstance(node, list | tuple):
        for item in node:
            yield from _iter_values_by_key(item, wanted_key)


def _scenario_names(node: Any) -> Iterable[str]:
    if isinstance(node, Mapping):
        if isinstance(node.get("scenario"), str):
            yield node["scenario"]
        scenarios = node.get("scenarios")
        if isinstance(scenarios, Mapping):
            yield from (str(key) for key in scenarios)
        for value in node.values():
            yield from _scenario_names(value)
    elif isinstance(node, list | tuple):
        for item in node:
            yield from _scenario_names(item)


def _scenario_has_key(node: Any, scenario: str, required_key: str) -> bool:
    if isinstance(node, Mapping):
        if node.get("scenario") == scenario and required_key in node:
            return True
        scenarios = node.get("scenarios")
        if isinstance(scenarios, Mapping):
            scenario_payload = scenarios.get(scenario)
            if isinstance(scenario_payload, Mapping) and required_key in scenario_payload:
                return True
        return any(_scenario_has_key(value, scenario, required_key) for value in node.values())
    if isinstance(node, list | tuple):
        return any(_scenario_has_key(item, scenario, required_key) for item in node)
    return False


def _path_has_unusual_timing(path: str, node: Any) -> bool:
    if "unusual_timing" in path:
        return True
    return isinstance(node, Mapping) and "unusual_timing" in str(node.get("scenario", ""))


def _has_fold_stat(node: Any) -> bool:
    if isinstance(node, Mapping):
        return any(str(key) in FOLD_STAT_KEYS for key in node)
    return False


def _is_non_empty_matrix(value: Any) -> bool:
    if isinstance(value, Mapping):
        return bool(value)
    if isinstance(value, list | tuple):
        return bool(value) and all(isinstance(row, Mapping | list | tuple) for row in value)
    return False


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 2 evaluation report guards")
    parser.add_argument("--check-markdown", nargs="+", type=Path)
    args = parser.parse_args(argv)

    if args.check_markdown:
        for path in args.check_markdown:
            if not path.exists():
                continue
            assert_no_insignificant_significance_claims(path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
