"""Phase 2 evaluation promotion gates."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

ANTI_SHORTCUT_RATIO_CAP = 4.0
S4_P4_MIN_DELTA_RECALL = 0.05


@dataclass(frozen=True)
class Phase2GateResult:
    name: str
    status: str
    passed: bool
    observed: float | None = None
    threshold: float | None = None
    reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "passed": self.passed,
            "observed": self.observed,
            "threshold": self.threshold,
            "reason": self.reason,
            "details": dict(self.details),
        }


def _metric(metrics: Mapping[str, Any], *names: str) -> float | None:
    for name in names:
        value = metrics.get(name)
        if value is not None:
            return float(value)
    return None


def evaluate_anti_shortcut_cap(
    *,
    ensemble_macro_auprc: float | None,
    trivial_10feature_macro_auprc: float | None,
    ratio_cap: float = ANTI_SHORTCUT_RATIO_CAP,
) -> Phase2GateResult:
    """Gate 6: block if ensemble is suspiciously better than trivial shortcuts."""
    if ensemble_macro_auprc is None or trivial_10feature_macro_auprc is None:
        return Phase2GateResult(
            name="anti_shortcut_cap",
            status="BLOCK",
            passed=False,
            threshold=ratio_cap,
            reason="missing_ensemble_or_trivial_macro_auprc",
        )
    if trivial_10feature_macro_auprc <= 0:
        return Phase2GateResult(
            name="anti_shortcut_cap",
            status="BLOCK",
            passed=False,
            observed=None,
            threshold=ratio_cap,
            reason="invalid_trivial_macro_auprc",
            details={"trivial_10feature_macro_auprc": trivial_10feature_macro_auprc},
        )

    ratio = float(ensemble_macro_auprc / trivial_10feature_macro_auprc)
    passed = ratio <= ratio_cap
    return Phase2GateResult(
        name="anti_shortcut_cap",
        status="PASS" if passed else "BLOCK",
        passed=passed,
        observed=ratio,
        threshold=ratio_cap,
        reason=None if passed else "shortcut_suspected_block_until_dataset_v4",
        details={
            "ensemble_macro_auprc": float(ensemble_macro_auprc),
            "trivial_10feature_macro_auprc": float(trivial_10feature_macro_auprc),
            "policy": "ensemble_macro_auprc / trivial_10feature_macro_auprc <= 4.0",
        },
    )


def evaluate_s4_p4_delta_recall_gate(
    scenario_delta_recall: Mapping[str, float] | None,
    *,
    min_delta: float = S4_P4_MIN_DELTA_RECALL,
) -> Phase2GateResult:
    """S4 P4 gate: every reported scenario must improve over trivial by >= 0.05."""
    if not scenario_delta_recall:
        return Phase2GateResult(
            name="s4_p4_delta_recall",
            status="BLOCK",
            passed=False,
            threshold=min_delta,
            reason="missing_scenario_delta_recall",
        )
    failing = {
        str(scenario): float(delta)
        for scenario, delta in scenario_delta_recall.items()
        if float(delta) < min_delta
    }
    return Phase2GateResult(
        name="s4_p4_delta_recall",
        status="PASS" if not failing else "BLOCK",
        passed=not failing,
        observed=min(float(v) for v in scenario_delta_recall.values()),
        threshold=min_delta,
        reason=None if not failing else "delta_recall_below_0_05",
        details={"failing_scenarios": failing},
    )


def evaluate_phase2_value_gates(metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate the Phase 2 S9/S4 promotion gates as an AND policy.

    Required gate 6 is intentionally not an OR escape hatch for S4 P4. The final
    decision is BLOCK unless both S4 P4 delta recall and anti-shortcut cap pass.
    """
    gates = [
        evaluate_s4_p4_delta_recall_gate(metrics.get("scenario_delta_recall")),
        evaluate_anti_shortcut_cap(
            ensemble_macro_auprc=_metric(
                metrics,
                "ensemble_macro_auprc",
                "ensemble_macro_ap",
                "ensemble_auprc_macro",
            ),
            trivial_10feature_macro_auprc=_metric(
                metrics,
                "trivial_10feature_macro_auprc",
                "trivial_10feature_macro_ap",
                "trivial_macro_auprc",
                "trivial_macro_ap",
            ),
        ),
    ]
    passed = all(gate.passed for gate in gates)
    return {
        "status": "PASS" if passed else "BLOCK",
        "policy": "AND",
        "block_reasons": [gate.reason for gate in gates if not gate.passed and gate.reason],
        "gates": {gate.name: gate.to_dict() for gate in gates},
    }
