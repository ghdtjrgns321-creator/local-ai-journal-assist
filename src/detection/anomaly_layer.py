"""L1-L4 anomaly-rule track orchestrator — L3-04~L3-07, L4-03~L4-06.

룰 레지스트리를 순회하며 try/except로 격리 실행.
한 룰 실패해도 나머지 계속 진행, 실패 룰은 skipped + warning 기록.
L4-02(Benford)은 BenfordDetector 독립 트랙으로 분리됨 (DETECTION_RULES.md §2.4 점수 체계).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import pandas as pd

from src.detection.anomaly_rules_batch import c13_batch_anomaly
from src.detection.anomaly_rules_reversal import c11_reversal_entry
from src.detection.anomaly_rules_simple import (
    c01_period_end_large,
    c02_weekend_entry,
    c03_after_hours_entry,
    c04_backdated_entry,
    c05_fiscal_period_mismatch,
    c08_amount_outlier,
    c10_suspense_account,
    c12_abnormal_hours_concentration,
)
from src.detection.anomaly_rules_statistical import c09_rare_account_pair
from src.detection.base import BaseDetector, validate_input
from src.detection.constants import SEVERITY_MAP
from src.detection.explanation_schema import RuleExplanation

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.detection.base import DetectionResult

# Why: 최소한 금액 컬럼은 있어야 L1-L4 anomaly-rule track 실행 의미가 있음
_REQUIRED_COLUMNS = ["debit_amount", "credit_amount"]

ANOMALY_RULE_EXPLANATIONS: dict[str, RuleExplanation] = {
    "L3-04": RuleExplanation(
        principle="Period-end postings should be supported by clear cutoff rationale.",
        violation_reason=("The entry occurs near period end or period start."),
        audit_next_action=(
            "Inspect cutoff support and corroborating amount, approval, source, or account context."
        ),
        reference="PCAOB AS 2401; ISA 240",
    ),
    "L3-05": RuleExplanation(
        principle="Non-business-day postings are timing context for audit review.",
        violation_reason="The entry was posted on a weekend or holiday.",
        audit_next_action=(
            "Confirm whether the posting source, schedule, and approval are expected."
        ),
        reference="PCAOB AS 2401; ISA 240",
    ),
    "L3-06": RuleExplanation(
        principle="After-hours postings require context before relying on automated controls.",
        violation_reason="The entry was posted outside configured business hours.",
        audit_next_action=(
            "Review source system, user role, and whether the timing was routine or exceptional."
        ),
        reference="PCAOB AS 2401; ISA 240",
    ),
    "L3-07": RuleExplanation(
        principle=(
            "Posting date and document date should align with the recorded accounting period."
        ),
        violation_reason="The date gap exceeds the configured threshold.",
        audit_next_action=(
            "Inspect source document date, posting rationale, and subsequent adjustment evidence."
        ),
        reference="PCAOB AS 1105; ISA 240",
    ),
    "L1-08": RuleExplanation(
        principle="Fiscal period should agree with posting date policy.",
        violation_reason="The fiscal period or year does not match the posting date expectation.",
        audit_next_action=(
            "Confirm period assignment, closing calendar, and whether a reclassification is needed."
        ),
        reference="PCAOB AS 1105; ISA 240",
    ),
    "L4-03": RuleExplanation(
        principle="Journal entries exceeding performance materiality warrant auditor review.",
        violation_reason=(
            "The transaction amount exceeds the performance materiality threshold derived "
            "from the entity's PBT or revenue for the fiscal year."
        ),
        audit_next_action=(
            "Inspect supporting documents and compare peer transactions in the same "
            "account/process."
        ),
        reference="ISA 320; PCAOB AS 2101",
    ),
    "L4-04": RuleExplanation(
        principle="Rare account pairings can indicate unusual transaction substance.",
        violation_reason="The debit-credit account pair is rare in the current population.",
        audit_next_action="Review the business rationale and corroborate with source evidence.",
        reference="PCAOB AS 1105; ISA 240",
    ),
    "L3-09": RuleExplanation(
        principle="Suspense or clearing items should be resolved timely.",
        violation_reason="A suspense-account item remains unresolved beyond the aging threshold.",
        audit_next_action=(
            "Inspect reconciliation status, subsequent clearing, and responsible owner evidence."
        ),
        reference="PCAOB AS 1105; ISA 330",
    ),
    "L2-05": RuleExplanation(
        principle="Reversals and offsets should have a valid accounting rationale.",
        violation_reason=(
            "The entry matches reversal, offset, or clearing patterns requiring review."
        ),
        audit_next_action=(
            "Trace the original entry, reversal timing, and supporting approval evidence."
        ),
        reference="PCAOB AS 2401; ISA 240",
    ),
    "L4-05": RuleExplanation(
        principle="Unusual user timing patterns are corroborating context for audit review.",
        violation_reason="The user or timing cluster is statistically unusual.",
        audit_next_action=(
            "Assess whether the pattern is expected, automated, or linked to other rule hits."
        ),
        reference="PCAOB AS 2401; ISA 240",
    ),
    "L4-06": RuleExplanation(
        principle=(
            "Batch postings should be evaluated as population context before row-level conclusion."
        ),
        violation_reason="The posting pattern appears batch-like or unusually concentrated.",
        audit_next_action=(
            "Confirm interface schedule, batch owner, and overlap with cutoff or amount signals."
        ),
        reference="PCAOB AS 1105; ISA 330",
    ),
}


class AnomalyDetector(BaseDetector):
    """L3-04~L3-07, L4-03~L4-05 이상 징후 탐지. 보조 레이어 (가중치 0.25).

    L4-02(Benford)은 BenfordDetector 독립 트랙으로 분리.
    """

    def __init__(self, settings=None, audit_rules: dict | None = None) -> None:
        super().__init__(settings)
        if audit_rules is None:
            from config.settings import get_audit_rules

            audit_rules = get_audit_rules()
        self._audit_rules = audit_rules

    @property
    def track_name(self) -> str:
        return "layer_c"

    def detect(self, df: pd.DataFrame) -> DetectionResult:
        """L3-04~L3-07, L4-03~L4-05 순차 실행. 각 룰은 try/except로 격리."""
        start = time.perf_counter()
        warnings: list[str] = []

        missing = validate_input(df, _REQUIRED_COLUMNS)
        if missing:
            warnings.append(f"필수 컬럼 누락: {missing}")
            return self._empty_result(df, warnings, time.perf_counter() - start)

        rule_results: dict[str, pd.Series] = {}
        skipped: list[str] = []
        coverage_issues: list[dict[str, Any]] = []

        for rule_id, func, kwargs in self._build_registry():
            missing_inputs = self._missing_inputs(rule_id, df)
            if missing_inputs:
                skipped.append(rule_id)
                coverage_issues.append(
                    {
                        "rule_id": rule_id,
                        "kind": "missing_prerequisites",
                        "missing_inputs": missing_inputs,
                    }
                )
                warnings.append(f"{rule_id} skipped: missing inputs {missing_inputs}")
                rule_results[rule_id] = pd.Series(False, index=df.index)
                continue
            try:
                rule_results[rule_id] = func(df, **kwargs)
            except Exception as exc:
                skipped.append(rule_id)
                warnings.append(f"{rule_id} 실행 실패: {exc}")
                self._logger.warning("%s 실행 실패: %s", rule_id, exc)

        elapsed = time.perf_counter() - start
        return self._build_result(df, rule_results, skipped, warnings, elapsed, coverage_issues)

    def _missing_inputs(self, rule_id: str, df: pd.DataFrame) -> list[str]:
        if rule_id == "L3-04" and "is_period_end" not in df.columns:
            return ["is_period_end"]
        return []

    def _build_registry(self) -> list[tuple[str, Callable, dict]]:
        """룰 레지스트리: (rule_id, callable, kwargs)."""
        s = self._settings
        patterns = self._audit_rules.get("patterns", {})
        return [
            (
                "L3-04",
                c01_period_end_large,
                {
                    "period_end_margin_days": s.period_end_margin_days,
                },
            ),
            ("L3-05", c02_weekend_entry, {}),
            ("L3-06", c03_after_hours_entry, {}),
            ("L3-07", c04_backdated_entry, {"threshold_days": s.backdated_threshold_days}),
            (
                "L1-08",
                c05_fiscal_period_mismatch,
                {
                    "policy": patterns.get("fiscal_period_mismatch_policy", {}),
                },
            ),
            # L4-02(Benford)은 BenfordDetector 독립 트랙으로 분리
            (
                "L4-03",
                c08_amount_outlier,
                {
                    "materiality_config": patterns.get("l403_materiality", {}),
                },
            ),
            (
                "L4-04",
                c09_rare_account_pair,
                {"cadence_per_quarter": s.rare_account_pair_cadence_per_quarter},
            ),
            (
                "L3-09",
                c10_suspense_account,
                {
                    "threshold_days": s.suspense_aging_days,
                    "min_open_amount": s.suspense_min_open_amount,
                },
            ),
            (
                "L2-05",
                c11_reversal_entry,
                {
                    "match_window_days": s.reversal_mirror_window_days,
                },
            ),
            (
                "L4-05",
                c12_abnormal_hours_concentration,
                {
                    "sigma_threshold": s.abnormal_sigma_threshold,
                    "rapid_approval_minutes": s.rapid_approval_minutes,
                    "min_abnormal_ratio": s.min_abnormal_ratio,
                    "min_midnight_entries": s.min_midnight_entries,
                    "min_user_entries": s.min_user_entries,
                    "min_high_context_midnight_entries": s.min_high_context_midnight_entries,
                    "auto_entry_sources": s.auto_entry_sources,
                },
            ),
            (
                "L4-06",
                c13_batch_anomaly,
                {
                    "batch_sources": s.batch_source_values,
                    "period_end_ratio": s.batch_period_end_ratio,
                    "simultaneous_threshold": s.batch_simultaneous_threshold,
                    "amount_zscore": s.batch_amount_zscore,
                },
            ),
        ]

    def _build_result(
        self,
        df: pd.DataFrame,
        rule_results: dict[str, pd.Series],
        skipped: list[str],
        warnings: list[str],
        elapsed: float,
        coverage_issues: list[dict[str, Any]] | None = None,
    ) -> DetectionResult:
        """룰별 bool Series → scores, details, RuleFlag 통합."""
        if not rule_results:
            return self._empty_result(df, warnings, elapsed, skipped, coverage_issues)

        details = pd.DataFrame(index=df.index)
        flag_details = pd.DataFrame(index=df.index)
        rule_breakdowns: dict[str, object] = {}
        row_annotations: dict[str, object] = {}
        for rule_id, flagged in rule_results.items():
            flag_details[rule_id] = flagged.reindex(df.index, fill_value=False).astype(bool)
            severity_score = SEVERITY_MAP[rule_id] / 5.0
            score_series = flagged.attrs.get("score_series") if hasattr(flagged, "attrs") else None
            if score_series is not None:
                score = pd.Series(score_series, index=df.index).fillna(0.0).astype(float)
                details[rule_id] = score
            elif rule_id == "L3-04":
                details[rule_id] = self._score_l304(df, flagged, severity_score)
            else:
                details[rule_id] = flagged.astype(float) * severity_score
            breakdown = flagged.attrs.get("breakdown") if hasattr(flagged, "attrs") else None
            if breakdown:
                rule_breakdowns[rule_id] = breakdown
            annotations = (
                flagged.attrs.get("row_annotations") if hasattr(flagged, "attrs") else None
            )
            if annotations:
                row_annotations[rule_id] = annotations

        scores = details.max(axis=1).fillna(0.0)
        raw_flag_mask = flag_details.any(axis=1) if not flag_details.empty else scores.gt(0)
        flagged_indices = raw_flag_mask[raw_flag_mask].index.tolist()

        rule_flags = [
            self._create_rule_flag(
                rule_id=rule_id,
                flagged_count=int(flagged.sum()),
                total_count=len(df),
                detail=self._format_rule_detail(rule_id, flagged),
            )
            for rule_id, flagged in rule_results.items()
        ]

        metadata = {
            "elapsed": elapsed,
            "skipped_rules": skipped,
            "coverage_issues": coverage_issues or [],
            "analysis_degraded": bool(coverage_issues),
            "rule_breakdowns": rule_breakdowns,
            "row_annotations": row_annotations,
            "rule_flag_series": flag_details,
        }

        return self._make_result(
            flagged_indices=flagged_indices,
            scores=scores,
            rule_flags=rule_flags,
            details=details,
            metadata=metadata,
            warnings=warnings,
        )

    def _score_l304(
        self,
        df: pd.DataFrame,
        flagged: pd.Series,
        severity_score: float,
        base_score: pd.Series | None = None,
    ) -> pd.Series:
        """Return binary L3-04 score without amount or sensitive-account escalation."""
        if base_score is not None:
            return base_score.copy()
        return flagged.astype(float) * severity_score

    def _format_rule_detail(self, rule_id: str, flagged: pd.Series) -> str | None:
        """Render optional rule detail from attrs for surfaced rules."""
        if not hasattr(flagged, "attrs"):
            return None
        breakdown = flagged.attrs.get("breakdown")
        if not breakdown:
            return None
        if rule_id == "L3-07":
            return f"threshold_days={breakdown.get('threshold_days')}"
        if rule_id == "L3-09":
            return f"threshold_days={breakdown.get('base_threshold_days')}"
        if rule_id == "L2-05":
            return (
                "high_confidence="
                f"{breakdown.get('high_confidence_count', 0)}, "
                "candidate="
                f"{breakdown.get('candidate_count', 0)}"
            )
        return None

    def _empty_result(
        self,
        df: pd.DataFrame,
        warnings: list[str],
        elapsed: float,
        skipped: list[str] | None = None,
        coverage_issues: list[dict[str, Any]] | None = None,
    ) -> DetectionResult:
        """빈 결과 생성 — 필수 컬럼 누락 또는 모든 룰 실패 시."""
        return self._make_result(
            flagged_indices=[],
            scores=pd.Series(0.0, index=df.index if not df.empty else pd.RangeIndex(0)),
            rule_flags=[],
            details=pd.DataFrame(index=df.index if not df.empty else pd.RangeIndex(0)),
            metadata={
                "elapsed": elapsed,
                "skipped_rules": skipped or [],
                "coverage_issues": coverage_issues or [],
                "analysis_degraded": bool(coverage_issues),
            },
            warnings=warnings,
        )
