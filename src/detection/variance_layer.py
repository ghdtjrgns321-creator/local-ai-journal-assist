"""Layer D: 전기 대비 변동 탐지 오케스트레이터 — D01, D02.

Why: 과거 engagement가 있는 기존회사에서만 실행.
     AnomalyDetector(anomaly_layer.py)와 동일한 레지스트리 패턴.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pandas as pd

from src.detection.base import BaseDetector, validate_input
from src.detection.constants import SEVERITY_MAP
from src.detection.explanation_schema import RuleExplanation
from src.detection.prior_data_loader import PriorSummary
from src.detection.variance_rules import (
    _lookup_prior_account,
    _normalise_key_part,
    d01_account_activity_variance,
    d02_monthly_pattern_diagnostics,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.detection.base import DetectionResult

# Why: 최소한 금액 + 계정 컬럼은 있어야 Layer D 실행 의미가 있음
_REQUIRED_COLUMNS = ["debit_amount", "credit_amount", "gl_account"]
_D01_ROW_SCORE = 0.0

VARIANCE_RULE_EXPLANATIONS: dict[str, RuleExplanation] = {
    "D01": RuleExplanation(
        principle="Analytical review should identify unusual account activity changes.",
        violation_reason=(
            "Current account activity differs materially from the prior-period account baseline."
        ),
        audit_next_action=(
            "Review account-level business events, compare supporting schedules, and prioritize "
            "overlapping row-level rule hits."
        ),
        reference="ISA 520; PCAOB AS 2305",
    ),
    "D02": RuleExplanation(
        principle=(
            "Monthly account patterns should be evaluated for unexplained distribution shifts."
        ),
        violation_reason=(
            "The current monthly distribution differs from prior-period monthly patterns."
        ),
        audit_next_action=(
            "Inspect monthly drivers, closing entries, recurring batches, and related "
            "row-level signals."
        ),
        reference="ISA 520; PCAOB AS 2305",
    ),
}


class VarianceDetector(BaseDetector):
    """Layer D: 전기 대비 변동 탐지. 기존회사 전용.

    Why: 과거 데이터가 있는 회사에서만 실행되어
         계정과목별 급변(D01)과 월별 패턴 변화(D02)를 탐지.
    """

    def __init__(
        self,
        settings=None,
        prior_summary: PriorSummary | None = None,
    ) -> None:
        super().__init__(settings)
        self._prior = prior_summary

    @property
    def track_name(self) -> str:
        return "layer_d"

    def detect(self, df: pd.DataFrame) -> DetectionResult:
        """D01, D02 순차 실행. prior_summary 없으면 빈 결과."""
        start = time.perf_counter()
        warnings: list[str] = []

        if self._prior is None:
            warnings.append("전기 데이터 없음 — Layer D 스킵")
            return self._empty_result(df, warnings, time.perf_counter() - start)

        missing = validate_input(df, _REQUIRED_COLUMNS)
        if missing:
            warnings.append(f"필수 컬럼 누락: {missing}")
            return self._empty_result(df, warnings, time.perf_counter() - start)

        rule_results: dict[str, pd.Series] = {}
        skipped: list[str] = []
        d02_diagnostics = pd.DataFrame()

        for rule_id, func, kwargs in self._build_registry():
            try:
                rule_results[rule_id] = func(df, **kwargs)
            except Exception as exc:
                skipped.append(rule_id)
                warnings.append(f"{rule_id} 실행 실패: {exc}")
                self._logger.warning("%s 실행 실패: %s", rule_id, exc)

        try:
            d02_diagnostics = self._calculate_d02_account_diagnostics(df)
            rule_results["D02"] = self._d02_flags_from_diagnostics(df, d02_diagnostics)
        except Exception as exc:
            skipped.append("D02")
            warnings.append(f"D02 실행 실패: {exc}")
            self._logger.warning("%s 실행 실패: %s", "D02", exc)

        elapsed = time.perf_counter() - start
        return self._build_result(
            df,
            rule_results,
            skipped,
            warnings,
            elapsed,
            d02_diagnostics=d02_diagnostics,
        )

    def _build_registry(self) -> list[tuple[str, Callable, dict]]:
        """룰 레지스트리: (rule_id, callable, kwargs)."""
        s = self._settings
        registry: list[tuple[str, Callable, dict]] = [
            (
                "D01",
                d01_account_activity_variance,
                {
                    "prior_aggregates": self._prior.account_aggregates,
                    "variance_threshold": s.variance_threshold,
                },
            ),
        ]

        # Why: fiscal_period 누락 시 d02 내부에서 조기 반환 처리.
        #      레지스트리에는 항상 등록하여 실패 룰 추적(skipped) 일관성 유지.
        return registry

    def _build_result(
        self,
        df: pd.DataFrame,
        rule_results: dict[str, pd.Series],
        skipped: list[str],
        warnings: list[str],
        elapsed: float,
        d02_diagnostics: pd.DataFrame | None = None,
    ) -> DetectionResult:
        """룰별 bool Series → scores, details, RuleFlag 통합."""
        if not rule_results:
            return self._empty_result(df, warnings, elapsed)

        details = pd.DataFrame(index=df.index)
        for rule_id, flagged in rule_results.items():
            severity_score = SEVERITY_MAP[rule_id] / 5.0
            if rule_id == "D01":
                details[rule_id] = 0.0
            elif rule_id == "D02":
                details[rule_id] = 0.0
            else:
                details[rule_id] = flagged.astype(float) * severity_score

        scores = details.max(axis=1).fillna(0.0)
        flagged_indices = scores[scores > 0].index.tolist()

        rule_flags = [
            self._create_rule_flag(
                rule_id=rule_id,
                flagged_count=int(flagged.sum()),
                total_count=len(df),
            )
            for rule_id, flagged in rule_results.items()
        ]

        d01_flags = rule_results.get("D01")
        d01_summary = (
            self._build_d01_account_summary(df, d01_flags) if d01_flags is not None else []
        )
        d01_review_rows = int(d01_flags.sum()) if d01_flags is not None else 0
        d02_diagnostics_rows = self._build_d02_account_diagnostics(d02_diagnostics)

        metadata = {
            "elapsed": elapsed,
            "skipped_rules": skipped,
            "account_activity_variance": d01_summary,
            "d01_review_account_count": len(d01_summary),
            "d01_review_row_count": d01_review_rows,
            "d01_row_scoring_mode": "account_review_metadata_only",
            "d02_account_diagnostics": d02_diagnostics_rows,
            "d02_review_score": self._settings.d02_review_score,
            "d02_guardrails": {
                "group_keys": self._settings.d02_group_keys,
                "min_account_docs": self._settings.d02_min_account_docs,
                "min_annual_amount": self._settings.d02_min_annual_amount,
                "min_top_month_delta": self._settings.d02_min_top_month_delta,
            },
            "operational_limitations": [
                "Layer D is an analytical-review screen, not a standalone fraud conclusion.",
                "D01 is reported as an account-level review population and does not "
                "create standalone row-level anomaly scores.",
                "D02 flags all current-period rows for an account once the account-level "
                "monthly pattern shifts, but the row score stays zero.",
                "D02 compares company/account groups when company_code is available, "
                "then falls back to account-level comparison for legacy data.",
                "D02 compares monthly distribution shape, so it does not explain "
                "which single journal line is wrong.",
            ],
            "high_risk_combinations": {
                "D01": ["L4-03", "L4-04", "L3-04", "L3-10", "L1-05", "L1-06", "L1-07"],
                "D02": ["L3-04", "L3-07", "L1-08", "L4-03", "L4-04", "L3-08", "L2-05"],
            },
        }

        return self._make_result(
            flagged_indices=flagged_indices,
            scores=scores,
            rule_flags=rule_flags,
            details=details,
            metadata=metadata,
            warnings=warnings,
        )

    def _build_d01_account_summary(
        self,
        df: pd.DataFrame,
        flagged: pd.Series,
    ) -> list[dict[str, object]]:
        """Build account-level D01 review metadata without row-level scoring."""
        if flagged.empty or not flagged.any():
            return []

        review_df = df.loc[flagged].copy()
        if review_df.empty:
            return []

        amount = review_df[["debit_amount", "credit_amount"]].fillna(0).sum(axis=1)
        has_company_code = "company_code" in review_df.columns
        group_cols = ["company_code", "gl_account"] if has_company_code else ["gl_account"]
        current_agg = (
            review_df.assign(_amount=amount)
            .groupby(group_cols, dropna=False)["_amount"]
            .agg(total_amount="sum", count="count", avg_amount="mean")
        )

        rows: list[dict[str, object]] = []
        for account_key, current in current_agg.iterrows():
            if has_company_code:
                company_code, acct = account_key
            else:
                company_code, acct = None, account_key

            prior = _lookup_prior_account(self._prior.account_aggregates, acct, company_code)
            common = {
                "gl_account": _normalise_key_part(acct),
                "review_row_count": int(current["count"]),
            }
            if has_company_code:
                common["company_code"] = _normalise_key_part(company_code)
            if prior is None:
                rows.append(
                    {
                        **common,
                        "reason": "new_account",
                        "current_total_amount": float(current["total_amount"]),
                        "current_count": int(current["count"]),
                        "current_avg_amount": float(current["avg_amount"]),
                        "prior_total_amount": None,
                        "prior_count": None,
                        "prior_avg_amount": None,
                        "total_var": None,
                        "count_var": None,
                        "avg_var": None,
                        "weighted_variance": 1.0,
                    }
                )
                continue

            total_var = abs(current["total_amount"] - prior["total_amount"]) / max(
                prior["total_amount"], 1.0
            )
            count_var = abs(current["count"] - prior["count"]) / max(prior["count"], 1.0)
            avg_var = abs(current["avg_amount"] - prior["avg_amount"]) / max(
                prior["avg_amount"], 1.0
            )
            weighted = total_var * 0.5 + count_var * 0.3 + avg_var * 0.2
            rows.append(
                {
                    **common,
                    "reason": "activity_variance",
                    "current_total_amount": float(current["total_amount"]),
                    "current_count": int(current["count"]),
                    "current_avg_amount": float(current["avg_amount"]),
                    "prior_total_amount": float(prior["total_amount"]),
                    "prior_count": int(prior["count"]),
                    "prior_avg_amount": float(prior["avg_amount"]),
                    "total_var": float(total_var),
                    "count_var": float(count_var),
                    "avg_var": float(avg_var),
                    "weighted_variance": float(weighted),
                }
            )

        rows.sort(key=lambda item: float(item["weighted_variance"]), reverse=True)
        return rows

    def _calculate_d02_account_diagnostics(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate D02 account-level diagnostics once per detection run."""
        if self._prior is None:
            return pd.DataFrame()
        s = self._settings
        return d02_monthly_pattern_diagnostics(
            df,
            self._prior.monthly_patterns,
            jsd_threshold=s.monthly_pattern_threshold,
            min_months=s.min_monthly_data_months,
            min_account_docs=s.d02_min_account_docs,
            min_annual_amount=s.d02_min_annual_amount,
            min_top_month_delta=s.d02_min_top_month_delta,
            group_keys=s.d02_group_keys,
        )

    def _d02_flags_from_diagnostics(
        self,
        df: pd.DataFrame,
        diagnostics: pd.DataFrame,
    ) -> pd.Series:
        """Build the D02 row mask from already-computed account diagnostics."""
        if diagnostics.empty or "flagged" not in diagnostics.columns:
            return pd.Series(False, index=df.index)

        flagged_groups = set(diagnostics.loc[diagnostics["flagged"], "d02_group_key"])
        if not flagged_groups or "gl_account" not in df.columns:
            return pd.Series(False, index=df.index)

        group_keys = self._effective_d02_group_keys(df)
        current_group_keys = df[group_keys].apply(
            lambda row: "::".join(_normalise_key_part(row[key]) for key in group_keys),
            axis=1,
        )
        valid_accounts = df["gl_account"].notna() & ~df["gl_account"].astype(
            str,
        ).str.strip().str.lower().isin({"", "nan", "none", "null", "<na>"})
        return current_group_keys.isin(flagged_groups) & valid_accounts

    def _effective_d02_group_keys(self, df: pd.DataFrame) -> list[str]:
        """Return D02 grouping columns available in the current DataFrame."""
        requested = list(self._settings.d02_group_keys or ["company_code", "gl_account"])
        if "gl_account" not in requested:
            requested.append("gl_account")
        effective = [key for key in requested if key in df.columns]
        return effective or ["gl_account"]

    def _build_d02_account_diagnostics(
        self,
        diagnostics: pd.DataFrame | None,
    ) -> list[dict[str, object]]:
        """Build compact account-level D02 evidence for review and tuning."""
        if diagnostics is None or diagnostics.empty:
            return []

        compact = diagnostics.sort_values(["flagged", "jsd"], ascending=[False, False])
        return compact.to_dict(orient="records")

    def _empty_result(
        self,
        df: pd.DataFrame,
        warnings: list[str],
        elapsed: float,
    ) -> DetectionResult:
        """빈 결과 생성 — prior 없음, 컬럼 누락, 모든 룰 실패 시.

        Why: 빈 결과는 곧 D01/D02 두 룰 모두 실행되지 못했다는 의미. UI 의 룰 오딧
        패널이 "스킵됨" 배지를 붙일 수 있도록 트랙 소유 룰을 metadata.skipped_rules 에
        명시한다. 이걸 빈 리스트로 두면 룰 오딧이 'no_match' 로 분류해 사유 없이
        회색 텍스트만 보이게 된다.
        """
        return self._make_result(
            flagged_indices=[],
            scores=pd.Series(0.0, index=df.index if not df.empty else pd.RangeIndex(0)),
            rule_flags=[],
            details=pd.DataFrame(index=df.index if not df.empty else pd.RangeIndex(0)),
            metadata={"elapsed": elapsed, "skipped_rules": ["D01", "D02"]},
            warnings=warnings,
        )
