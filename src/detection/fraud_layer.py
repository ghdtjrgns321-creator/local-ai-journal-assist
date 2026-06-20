"""L1-L4 fraud-rule detector."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import pandas as pd

from src.detection.base import BaseDetector, validate_input
from src.detection.constants import SEVERITY_MAP
from src.detection.explanation_schema import RuleExplanation
from src.detection.fraud_rules_access import (
    b06_self_approval,
    b07_segregation_of_duties,
    b09_skipped_approval,
    b09b_unknown_approver,
    b10_intercompany_review_signal,
    b13_high_risk_account_use,
    b14_work_scope_excess_review,
    build_access_rule_cache,
)
from src.detection.fraud_rules_feature import (
    b01_revenue_manipulation,
    b02_near_threshold,
    b03_exceeds_threshold,
    b08_manual_override,
)
from src.detection.fraud_rules_groupby import (
    _resolve_b04_partner_key,
    b04_duplicate_payment,
    b05_duplicate_entry,
    b11_expense_capitalization,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from config.settings import AuditSettings
    from src.detection.base import DetectionResult


_REQUIRED_COLUMNS = ["debit_amount", "credit_amount"]
_L2_02_PARTNER_COLUMNS = (
    "auxiliary_account_number",
    "trading_partner",
    "auxiliary_account_label",
    "vendor_name",
    "customer_name",
    "counterparty_code",
    "counterparty_name",
)

FRAUD_RULE_EXPLANATIONS: dict[str, RuleExplanation] = {
    "L4-01": RuleExplanation(
        principle="Revenue postings should be supported by population-consistent evidence.",
        violation_reason="The revenue amount is an outlier within its peer distribution.",
        audit_next_action=(
            "Inspect revenue support, cutoff evidence, approval, and reversal activity."
        ),
        reference="PCAOB AS 2401; ISA 240; ISA 520",
    ),
    "L2-01": RuleExplanation(
        principle="Approval controls should not be circumvented by near-threshold structuring.",
        violation_reason="The amount falls close to an approval threshold or review boundary.",
        audit_next_action=(
            "Compare related entries, approver authority, and split-pattern evidence."
        ),
        reference="PCAOB AS 2401; ISA 240",
    ),
    "L1-04": RuleExplanation(
        principle="Transactions should remain within delegated approval authority.",
        violation_reason="The amount exceeds the configured approval limit or approver authority.",
        audit_next_action="Obtain approval matrix evidence and confirm post-approval remediation.",
        reference="PCAOB AS 1105; ISA 330",
    ),
    "L2-02": RuleExplanation(
        principle="Cash outflows should not duplicate the same obligation.",
        violation_reason=(
            "The entry resembles another payment by amount, date, and counterparty evidence."
        ),
        audit_next_action=(
            "Match invoice, vendor, reference, and payment evidence for duplicate settlement."
        ),
        reference="PCAOB AS 2401; ISA 240",
    ),
    "L2-03": RuleExplanation(
        principle="Duplicate documents and split postings require consolidated review.",
        violation_reason=(
            "The document matches exact, fuzzy, split, or sequential duplicate patterns."
        ),
        audit_next_action=(
            "Review duplicate groups and verify whether each posting has distinct support."
        ),
        reference="PCAOB AS 1105; ISA 240",
    ),
    "L1-05": RuleExplanation(
        principle="Preparation and approval duties should be separated.",
        violation_reason="The same user appears as creator and approver for the entry.",
        audit_next_action=(
            "Inspect workflow logs and determine whether a compensating review occurred."
        ),
        reference="PCAOB AS 2401; ISA 240; ISA 330",
    ),
    "L1-06": RuleExplanation(
        principle="Segregation-of-duties conflicts should be resolved before posting reliance.",
        violation_reason="The user/process combination matches a configured SoD conflict.",
        audit_next_action=(
            "Confirm access roles, exception approvals, and compensating control evidence."
        ),
        reference="PCAOB AS 2401; ISA 330",
    ),
    "L3-02": RuleExplanation(
        principle="Manual journal entries require heightened audit attention.",
        violation_reason="The source or document context indicates a manual or adjustment entry.",
        audit_next_action="Inspect preparer rationale, approval trail, and period-end context.",
        reference="PCAOB AS 2401; ISA 240",
    ),
    "L1-07": RuleExplanation(
        principle="Approval workflow should not be bypassed or left unresolved.",
        violation_reason=(
            "Approval evidence is missing, bypassed, or inconsistent with workflow policy."
        ),
        audit_next_action=(
            "Trace workflow status and confirm authorized review before relying on the entry."
        ),
        reference="PCAOB AS 1105; ISA 330",
    ),
    "L1-07-02": RuleExplanation(
        principle="Approval workflow should reference an identifiable authorized approver.",
        violation_reason="The approver value is populated but absent from the employee master.",
        audit_next_action=(
            "Confirm whether the approver is a valid employee or a workflow bypass artifact."
        ),
        reference="PCAOB AS 1105; ISA 330",
    ),
    "L3-10": RuleExplanation(
        principle=(
            "Sensitive accounts should be reviewed with account-specific professional skepticism."
        ),
        violation_reason="The entry touches a configured sensitive or high-risk account.",
        audit_next_action=(
            "Inspect account purpose, supporting evidence, approver, and related entries."
        ),
        reference="PCAOB AS 2401; ISA 240",
    ),
    "L3-12": RuleExplanation(
        principle=(
            "Broad user activity across processes is a review context, not a standalone finding."
        ),
        violation_reason=(
            "One user is concentrated across multiple processes, companies, or account scopes."
        ),
        audit_next_action=(
            "Assess role design and compensating controls, especially when other rules also hit."
        ),
        reference="PCAOB AS 315; ISA 330",
    ),
    "L3-03": RuleExplanation(
        principle="Intercompany and related-party activity requires clear counterparty support.",
        violation_reason="The entry contains intercompany or related-party indicators.",
        audit_next_action=(
            "Reconcile counterparty evidence and attach sidecar matching results when available."
        ),
        reference="PCAOB AS 2410; ISA 550",
    ),
    "L2-04": RuleExplanation(
        principle=(
            "Expense and asset classification should reflect the substance of the transaction."
        ),
        violation_reason=(
            "The account, process, or amount pattern indicates possible misclassification."
        ),
        audit_next_action=(
            "Inspect capitalization policy, invoice substance, and period classification."
        ),
        reference="PCAOB AS 1105; ISA 240",
    ),
}


def _populated_mask(series: pd.Series) -> pd.Series:
    """Return a non-empty value mask."""

    if series.dtype == "O":
        return series.notna() & series.astype(str).str.strip().ne("")
    return series.notna()


class FraudLayer(BaseDetector):
    """Fraud and control-circumvention detector."""

    def __init__(
        self,
        settings: AuditSettings | None = None,
        audit_rules: dict | None = None,
    ) -> None:
        super().__init__(settings)
        self._audit_rules = audit_rules

    @property
    def track_name(self) -> str:
        return "layer_b"

    def detect(self, df: pd.DataFrame) -> DetectionResult:
        """Execute fraud and control-circumvention rules."""

        start = time.perf_counter()
        warnings: list[str] = []

        missing = validate_input(df, _REQUIRED_COLUMNS)
        if missing:
            warnings.append(f"missing required columns: {missing}")
            return self._empty_result(df, warnings, time.perf_counter() - start)

        rule_results: dict[str, pd.Series] = {}
        skipped: list[str] = []
        coverage_issues: list[dict[str, Any]] = []
        access_cache = build_access_rule_cache(df)

        for rule_id, func, kwargs in self._build_registry():
            missing_inputs = self._missing_inputs(rule_id, df)
            if missing_inputs:
                skipped.append(rule_id)
                warnings.append(f"{rule_id} skipped: missing inputs {missing_inputs}")
                coverage_issues.append(
                    {
                        "rule_id": rule_id,
                        "kind": "missing_prerequisites",
                        "severity": "high",
                        "affected_rows": int(len(df)),
                        "missing_inputs": missing_inputs,
                    }
                )
                continue

            try:
                if rule_id in {"L1-05", "L1-06", "L1-07", "L1-07-02"}:
                    kwargs = {**kwargs, "cache": access_cache}
                rule_results[rule_id] = func(df, **kwargs)
                coverage_issues.extend(self._coverage_issues(rule_id, df))
            except Exception as exc:
                skipped.append(rule_id)
                warnings.append(f"{rule_id} failed: {exc}")
                self._logger.warning("%s failed: %s", rule_id, exc)

        elapsed = time.perf_counter() - start
        return self._build_result(
            df=df,
            rule_results=rule_results,
            skipped=skipped,
            warnings=warnings,
            elapsed=elapsed,
            coverage_issues=coverage_issues,
        )

    def _build_registry(self) -> list[tuple[str, Callable, dict]]:
        """Return the rule registry for fraud and control-circumvention rules."""

        s = self._settings
        return [
            ("L4-01", b01_revenue_manipulation, {"zscore_threshold": s.zscore_threshold}),
            ("L2-01", b02_near_threshold, {}),
            ("L1-04", b03_exceeds_threshold, {"audit_rules": self._audit_rules}),
            ("L2-02", b04_duplicate_payment, {"window_days": s.duplicate_payment_window_days}),
            (
                "L2-03",
                b05_duplicate_entry,
                {
                    "amount_tolerance": s.duplicate_amount_tolerance,
                    "fuzzy_threshold": s.duplicate_fuzzy_threshold,
                    "window_days": s.duplicate_time_window_days,
                    "split_window_days": s.duplicate_split_window_days,
                    "max_group_size": s.duplicate_max_group_size,
                    "reference_max_frequency_ratio": s.duplicate_reference_max_frequency_ratio,
                    "reference_min_unique_ratio": s.duplicate_reference_min_unique_ratio,
                    "reference_nonunique_min_count": s.duplicate_reference_nonunique_min_count,
                },
            ),
            (
                "L1-05",
                b06_self_approval,
                {"audit_rules": self._audit_rules},
            ),
            (
                "L1-06",
                b07_segregation_of_duties,
                {"sod_threshold": s.sod_process_threshold, "audit_rules": self._audit_rules},
            ),
            ("L3-02", b08_manual_override, {"audit_rules": self._audit_rules}),
            ("L1-07", b09_skipped_approval, {"audit_rules": self._audit_rules}),
            ("L1-07-02", b09b_unknown_approver, {"audit_rules": self._audit_rules}),
            ("L3-10", b13_high_risk_account_use, {"audit_rules": self._audit_rules}),
            ("L3-12", b14_work_scope_excess_review, {"audit_rules": self._audit_rules}),
            ("L3-03", b10_intercompany_review_signal, {"audit_rules": self._audit_rules}),
            (
                "L2-04",
                b11_expense_capitalization,
                {
                    "audit_rules": self._audit_rules,
                    "amount_tolerance": s.expense_capitalization_amount_tolerance,
                    "min_amount": s.expense_capitalization_min_amount,
                },
            ),
        ]

    def _missing_inputs(self, rule_id: str, df: pd.DataFrame) -> list[str]:
        """Return missing prerequisite columns or features for a rule."""

        required_by_rule = {
            "L4-01": ["is_revenue_account", "amount_zscore"],
            "L2-01": ["is_near_threshold"],
            "L1-04": ["exceeds_threshold"],
            "L2-03": ["document_id", "gl_account", "posting_date", "debit_amount", "credit_amount"],
            "L1-06": ["created_by", "business_process"],
            "L1-07": ["approved_by"],
            "L3-10": ["gl_account"],
            "L3-12": ["created_by", "business_process"],
            "L2-04": ["document_id", "gl_account", "debit_amount", "credit_amount"],
        }
        if rule_id == "L3-03":
            if "is_intercompany" in df.columns or "gl_account" in df.columns:
                return []
            return ["is_intercompany|gl_account"]
        if rule_id == "L3-02":
            if "is_manual_je" in df.columns or "source" in df.columns:
                return []
            return ["is_manual_je|source"]
        if rule_id == "L1-05":
            missing: list[str] = []
            if "created_by" not in df.columns:
                missing.append("created_by")
            if "approved_by" not in df.columns:
                missing.append("approved_by")
            return missing
        if rule_id == "L2-02":
            return [
                column
                for column in ["posting_date", "debit_amount", "credit_amount"]
                if column not in df.columns
            ]
        return [column for column in required_by_rule.get(rule_id, []) if column not in df.columns]

    def _coverage_issues(self, rule_id: str, df: pd.DataFrame) -> list[dict[str, Any]]:
        """Return coverage metadata for rules with fallback inputs."""

        if rule_id != "L2-02":
            return []

        partner_key = _resolve_b04_partner_key(df)
        if partner_key is None:
            return [
                {
                    "rule_id": "L2-02",
                    "kind": "missing_prerequisites",
                    "severity": "high",
                    "affected_rows": int(len(df)),
                    "missing_inputs": ["|".join(_L2_02_PARTNER_COLUMNS)],
                }
            ]

        populated = _populated_mask(partner_key)
        populated_rows = int(populated.sum())
        if populated_rows == len(df):
            return []

        sparse_inputs = [
            column
            for column in _L2_02_PARTNER_COLUMNS
            if column in df.columns and not _populated_mask(df[column]).all()
        ]
        if not sparse_inputs:
            sparse_inputs = ["|".join(_L2_02_PARTNER_COLUMNS)]

        return [
            {
                "rule_id": "L2-02",
                "kind": "partial_input_coverage",
                "severity": "medium",
                "affected_rows": int(len(df) - populated_rows),
                "available_rows": populated_rows,
                "coverage_ratio": float(populated.mean()),
                "low_coverage_inputs": sparse_inputs,
            }
        ]

    def _build_result(
        self,
        df: pd.DataFrame,
        rule_results: dict[str, pd.Series],
        skipped: list[str],
        warnings: list[str],
        elapsed: float,
        coverage_issues: list[dict[str, Any]],
    ) -> DetectionResult:
        """Build a DetectionResult from rule outputs."""

        if not rule_results:
            index = df.index if not df.empty else pd.RangeIndex(0)
            return self._make_result(
                flagged_indices=[],
                scores=pd.Series(0.0, index=index),
                rule_flags=[],
                details=pd.DataFrame(index=index),
                metadata={
                    "elapsed": elapsed,
                    "skipped_rules": skipped,
                    "coverage_issues": coverage_issues,
                    "analysis_degraded": bool(coverage_issues),
                },
                warnings=warnings,
            )

        details = pd.DataFrame(index=df.index)
        review_details = pd.DataFrame(index=df.index)
        flag_details = pd.DataFrame(index=df.index)
        rule_breakdowns: dict[str, Any] = {}
        row_annotations: dict[str, Any] = {}
        for rule_id, flagged in rule_results.items():
            score_series = flagged.attrs.get("score_series") if hasattr(flagged, "attrs") else None
            if score_series is not None:
                details[rule_id] = pd.Series(score_series, index=df.index).fillna(0.0).astype(float)
                flag_details[rule_id] = details[rule_id].gt(0)
            else:
                details[rule_id] = flagged.astype(float) * (SEVERITY_MAP[rule_id] / 5.0)
                flag_details[rule_id] = flagged.reindex(df.index, fill_value=False).astype(bool)
            review_score_series = (
                flagged.attrs.get("review_score_series") if hasattr(flagged, "attrs") else None
            )
            if review_score_series is not None:
                review_details[rule_id] = (
                    pd.Series(review_score_series, index=df.index).fillna(0.0).astype(float)
                )
            breakdown = flagged.attrs.get("breakdown") if hasattr(flagged, "attrs") else None
            if breakdown:
                rule_breakdowns[rule_id] = breakdown
            annotations = (
                flagged.attrs.get("row_annotations") if hasattr(flagged, "attrs") else None
            )
            if annotations:
                row_annotations[rule_id] = annotations

        scores = details.max(axis=1).fillna(0.0)
        flagged_indices = scores[scores > 0].index.tolist()
        rule_flags = [
            self._create_rule_flag(
                rule_id=rule_id,
                flagged_count=int(details[rule_id].gt(0).sum()),
                total_count=len(df),
                detail=self._format_rule_detail(flagged),
            )
            for rule_id, flagged in rule_results.items()
        ]

        return self._make_result(
            flagged_indices=flagged_indices,
            scores=scores,
            rule_flags=rule_flags,
            details=details,
            metadata={
                "elapsed": elapsed,
                "skipped_rules": skipped,
                "coverage_issues": coverage_issues,
                "analysis_degraded": bool(coverage_issues),
                "rule_breakdowns": rule_breakdowns,
                "row_annotations": row_annotations,
                "review_score_series": review_details,
                "rule_flag_series": flag_details,
            },
            warnings=warnings,
        )

    def _empty_result(
        self,
        df: pd.DataFrame,
        warnings: list[str],
        elapsed: float,
    ) -> DetectionResult:
        """Build an empty result with warning metadata."""

        index = df.index if not df.empty else pd.RangeIndex(0)
        return self._make_result(
            flagged_indices=[],
            scores=pd.Series(0.0, index=index),
            rule_flags=[],
            details=pd.DataFrame(index=index),
            metadata={
                "elapsed": elapsed,
                "skipped_rules": [],
                "coverage_issues": [],
                "analysis_degraded": False,
            },
            warnings=warnings,
        )

    def _format_rule_detail(self, flagged: pd.Series) -> str | None:
        """Render optional rule detail text from rule breakdown metadata."""

        if not hasattr(flagged, "attrs"):
            return None
        breakdown = flagged.attrs.get("breakdown")
        if not breakdown:
            return None
        if "immediate_rows" in breakdown and "review_rows" in breakdown:
            return f"immediate={breakdown['immediate_rows']}, review={breakdown['review_rows']}"
        if "reason_counts" in breakdown:
            parts = [f"{key}={value}" for key, value in sorted(breakdown["reason_counts"].items())]
            return ", ".join(parts) if parts else None
        return None
