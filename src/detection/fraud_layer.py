"""L1-L4 fraud-rule detector."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import pandas as pd

from src.detection.base import BaseDetector, validate_input
from src.detection.constants import SEVERITY_MAP
from src.detection.fraud_rules_access import (
    b06_self_approval,
    b07_segregation_of_duties,
    b09_skipped_approval,
    b10_intercompany_review_signal,
    b12_missing_approval_date,
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
                if rule_id in {"L1-05", "L1-06", "L1-07", "L1-09"}:
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
            ("L1-09", b12_missing_approval_date, {"audit_rules": self._audit_rules}),
            ("L3-10", b13_high_risk_account_use, {"audit_rules": self._audit_rules}),
            ("L3-12", b14_work_scope_excess_review, {"audit_rules": self._audit_rules}),
            ("L3-03", b10_intercompany_review_signal, {}),
            (
                "L2-04",
                b11_expense_capitalization,
                {
                    "audit_rules": self._audit_rules,
                    "amount_tolerance": s.expense_capitalization_amount_tolerance,
                    "min_amount": s.expense_capitalization_min_amount,
                    "review_threshold": s.expense_capitalization_review_threshold,
                    "immediate_threshold": s.expense_capitalization_immediate_threshold,
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
            "L1-09": ["approval_date"],
            "L3-10": ["gl_account"],
            "L3-12": ["created_by", "business_process"],
            "L3-03": ["is_intercompany"],
            "L2-04": ["document_id", "gl_account", "debit_amount", "credit_amount"],
        }
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
        rule_breakdowns: dict[str, Any] = {}
        row_annotations: dict[str, Any] = {}
        for rule_id, flagged in rule_results.items():
            score_series = flagged.attrs.get("score_series") if hasattr(flagged, "attrs") else None
            if score_series is not None:
                details[rule_id] = pd.Series(score_series, index=df.index).fillna(0.0).astype(float)
            else:
                details[rule_id] = flagged.astype(float) * (SEVERITY_MAP[rule_id] / 5.0)
            review_score_series = (
                flagged.attrs.get("review_score_series") if hasattr(flagged, "attrs") else None
            )
            if review_score_series is not None:
                review_details[rule_id] = (
                    pd.Series(review_score_series, index=df.index).fillna(0.0).astype(float)
                )
                details[rule_id] = pd.concat(
                    [details[rule_id], review_details[rule_id]],
                    axis=1,
                ).max(axis=1)
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
