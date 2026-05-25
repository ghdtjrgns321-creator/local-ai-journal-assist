"""IntercompanyMatcher — 내부거래 매칭 독립 트랙 (WU-07).

Why: L3-03(MVP)은 is_intercompany bool만 flag하여 recall 7%.
     양측 거래 대사(group-level matching)로 미매칭/금액불일치/시차이상 탐지.
     N:M 다대다 매칭 + 이종 통화 방어 적용.

Note: LAYER_WEIGHTS에 의도적 미등록 — 성능 평가 후 가중치 배분 예정 (WU-03 Stacking).
      FraudLayer의 기존 L3-03(IC 전표 존재 감지)은 하위 호환 목적으로 병존 유지.

PHASE2 internal probabilistic reconciliation surface (additive, 2026-05-24):
    `details` 에 `ic_unmatched_prob` / `ic_amount_prob` / `ic_timing_prob` 3개
    0~1 raw probability column 을 추가한다. canonical rule id (IC04 등) 는
    생성하지 않으며 SEVERITY_MAP / RULE_CODES / RULE_DETAIL_METADATA_REGISTRY /
    `_RULE_STYLE_SUB_DETECTORS` 는 변경 없다.
    DetectionResult.scores 는 기존 IC01~03 점수와 신규 prob column 의 row-wise
    max 로 통합되어 PHASE2 family overlay (zero-preserving ECDF + Noisy-OR) 에
    자연 흡수된다. metadata["probabilistic_reconciliation"] 에 contract tier /
    candidate count / capped / warnings / params 만 노출하고 pair queue 산출물은
    공개하지 않는다. Phase 1 rule hit / DataSynth truth / document_id 식별자는
    입력으로 사용하지 않는다.

PHASE2 internal reciprocal flow surface (additive, 2026-05-24):
    `details` 에 `ic_reciprocal_flow_prob` 0~1 raw probability column 을 추가한다.
    single-document structural(rec+pay 동시 + amount symmetry ≥ 0.95) + context
    (period_end/after_hours/round_amount) 가중평균이며 score 통합은 위와 동일.

PHASE2 sub-detector tier registry 등록 (2026-05-25, 옵션 2):
    `phase2_subdetector_tiers.yaml` 에 4개 internal prob column 을 추가 등록
    (ic_reciprocal_flow_prob=strong, ic_amount_prob=moderate,
    ic_unmatched_prob=weak, ic_timing_prob=weak). IntercompanyMatcher 의 score
    합성·output column 자체는 변경 없으며, family overlay 의 lane sort
    `ic_role_priority` secondary dim + `phase2_review_band` 승격 chain 만
    영향받는다. 자세한 계약은 docs/PHASE2_INTERFACE_DESIGN.md §4.3.2 참조.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pandas as pd

from config.settings import AuditSettings
from src.detection.base import BaseDetector, DetectionResult, validate_input
from src.detection.constants import SEVERITY_MAP
from src.detection.intercompany_rules import (
    compute_probabilistic_pair_scores,
    compute_reciprocal_flow_scores,
    ic01_unmatched_intercompany,
    ic02_amount_mismatch,
    ic03_timing_gap,
    load_candidate_blocking,
    load_contract_score_caps,
    load_ic_pairs,
    load_matching_weights,
    load_partner_format_policy,
    load_related_party_master,
    load_timing_domain,
    match_ic_groups,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_PROBABILISTIC_COLUMNS: tuple[str, ...] = (
    "ic_unmatched_prob",
    "ic_amount_prob",
    "ic_timing_prob",
)
_RECIPROCAL_FLOW_COLUMN: str = "ic_reciprocal_flow_prob"


class IntercompanyMatcher(BaseDetector):
    """내부거래 매칭 탐지기. DuplicateDetector _build_registry 패턴 준수."""

    def __init__(
        self,
        settings: AuditSettings | None = None,
        *,
        audit_rules: dict | None = None,
    ) -> None:
        super().__init__(settings)
        self._audit_rules = audit_rules or {}
        self._pair_map = load_ic_pairs(self._audit_rules)

    @property
    def track_name(self) -> str:
        return "intercompany"

    def detect(self, df: pd.DataFrame) -> DetectionResult:
        start = time.perf_counter()
        warnings: list[str] = []

        required = [
            "is_intercompany",
            "gl_account",
            "debit_amount",
            "credit_amount",
        ]
        missing = validate_input(df, required)
        if missing:
            warnings.append(f"필수 컬럼 누락: {missing}")
            return self._empty_result(df, warnings, time.perf_counter() - start)

        if not self._pair_map:
            warnings.append("intercompany.pairs 설정 비어있음 — IC 매칭 스킵")
            return self._empty_result(df, warnings, time.perf_counter() - start)

        ic_count = df["is_intercompany"].fillna(False).sum()
        if ic_count < self._settings.ic_min_ic_rows:
            warnings.append(
                f"IC 행 {ic_count}건 < 최소 {self._settings.ic_min_ic_rows}건 — 스킵",
            )
            return self._empty_result(df, warnings, time.perf_counter() - start)

        # Why: match_ic_groups를 한 번만 호출하여 3개 서브룰에 공유 (O(n) → O(3n) 방지)
        match_df = match_ic_groups(
            df,
            self._pair_map,
            self._settings.ic_amount_tolerance,
            self._settings.ic_cross_currency_ratio_threshold,
        )

        rule_results: dict[str, pd.Series] = {}
        sidecar_columns: dict[str, pd.Series] = {}
        skipped: list[str] = []

        for rule_id, func, kwargs in self._build_registry(match_df):
            try:
                result = func(df, **kwargs)
                if rule_id == "IC01":
                    # IC01 returns (score, evidence_level, review_reason)
                    score_series, evidence_level, review_reason = result
                    rule_results[rule_id] = score_series
                    sidecar_columns["ic01_evidence_level"] = evidence_level
                    sidecar_columns["ic01_review_reason"] = review_reason
                else:
                    rule_results[rule_id] = result
            except Exception as exc:
                skipped.append(rule_id)
                warnings.append(f"{rule_id} 실행 실패: {exc}")
                self._logger.warning("%s 실행 실패: %s", rule_id, exc)

        prob_scores, prob_summary = self._compute_probabilistic_scores(df)
        warnings.extend(prob_summary.get("warnings", []))

        reciprocal_scores, reciprocal_summary = self._compute_reciprocal_flow_scores(df)
        warnings.extend(reciprocal_summary.get("warnings", []))

        elapsed = time.perf_counter() - start
        return self._build_result(
            df,
            rule_results,
            sidecar_columns,
            prob_scores,
            prob_summary,
            reciprocal_scores,
            reciprocal_summary,
            skipped,
            warnings,
            elapsed,
        )

    def _build_registry(
        self,
        match_df: pd.DataFrame,
    ) -> list[tuple[str, Callable, dict]]:
        """서브룰 레지스트리 — 사전 계산된 match_df를 공유."""
        s = self._settings
        related_party_master: set[str] | None = None
        if getattr(s, "ic_use_related_party_master", True):
            related_party_master = load_related_party_master(self._audit_rules)
        partner_format_policy = load_partner_format_policy(self._audit_rules)

        return [
            (
                "IC01",
                ic01_unmatched_intercompany,
                {
                    "match_df": match_df,
                    "related_party_master": related_party_master,
                    "partner_format_policy": partner_format_policy,
                },
            ),
            (
                "IC02",
                ic02_amount_mismatch,
                {
                    "match_df": match_df,
                    "amount_tolerance": s.ic_amount_tolerance,
                    "max_diff_ratio": s.ic_max_diff_ratio,
                },
            ),
            (
                "IC03",
                ic03_timing_gap,
                {
                    "match_df": match_df,
                    "date_window_days": s.ic_date_window_days,
                    "max_day_diff": s.ic_max_day_diff,
                },
            ),
        ]

    def _compute_probabilistic_scores(
        self,
        df: pd.DataFrame,
    ) -> tuple[pd.DataFrame, dict]:
        """Run probabilistic reconciliation; never raise — return summary on failure."""
        try:
            weights = load_matching_weights(self._audit_rules, self._settings)
            blocking = load_candidate_blocking(self._audit_rules, self._settings)
            caps = load_contract_score_caps(self._audit_rules, self._settings)
            timing_domain = load_timing_domain(self._audit_rules, self._settings)
            return compute_probabilistic_pair_scores(
                df,
                self._pair_map,
                weights=weights,
                blocking=blocking,
                max_day_diff=self._settings.ic_max_day_diff,
                caps=caps,
                timing_domain=timing_domain,
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("probabilistic reconciliation 실행 실패: %s", exc)
            empty = pd.DataFrame(
                {
                    col: pd.Series(0.0, index=df.index, dtype=float)
                    for col in _PROBABILISTIC_COLUMNS
                },
                index=df.index,
            )
            return empty, {
                "contract_tier": "L3_insufficient",
                "missing_reasons": ["probabilistic_runtime_error"],
                "pair_candidate_count": 0,
                "capped": False,
                "warnings": [f"probabilistic_runtime_error: {exc}"],
            }

    def _compute_reciprocal_flow_scores(
        self,
        df: pd.DataFrame,
    ) -> tuple[pd.DataFrame, dict]:
        """Run single-document reciprocal IC flow scoring; never raise."""
        try:
            return compute_reciprocal_flow_scores(
                df,
                self._pair_map,
                settings=self._settings,
                audit_rules=self._audit_rules,
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("reciprocal flow scoring 실행 실패: %s", exc)
            empty = pd.DataFrame(
                {_RECIPROCAL_FLOW_COLUMN: pd.Series(0.0, index=df.index, dtype=float)},
                index=df.index,
            )
            return empty, {
                "evaluated_ic_rows": 0,
                "structural_candidate_docs": 0,
                "context_boost_docs": 0,
                "score_q95": 0.0,
                "score_q99": 0.0,
                "score_max": 0.0,
                "warnings": [f"reciprocal_runtime_error: {exc}"],
            }

    def _build_result(
        self,
        df: pd.DataFrame,
        rule_results: dict[str, pd.Series],
        sidecar_columns: dict[str, pd.Series],
        prob_scores: pd.DataFrame,
        prob_summary: dict,
        reciprocal_scores: pd.DataFrame,
        reciprocal_summary: dict,
        skipped: list[str],
        warnings: list[str],
        elapsed: float,
    ) -> DetectionResult:
        """룰 점수 + probabilistic + reciprocal_flow prob → scores/details/RuleFlag 통합."""
        if not rule_results and prob_scores.empty and reciprocal_scores.empty:
            return self._empty_result(df, warnings, elapsed)

        # Why: severity/5.0 정규화 (DuplicateDetector 패턴 동일)
        # details 는 numeric rule-score matrix 계약 (metrics/case_builder 가 > 0 비교).
        # 문자열 sidecar 는 metadata["row_sidecar"] 로 분리 — 평가/리포트 read 전용.
        details = pd.DataFrame(index=df.index)
        for rule_id, raw_scores in rule_results.items():
            severity_factor = SEVERITY_MAP[rule_id] / 5.0
            details[rule_id] = raw_scores.reindex(df.index, fill_value=0.0) * severity_factor

        # PHASE2 internal probabilistic columns — severity normalization 미적용 (raw 0~1)
        for col in _PROBABILISTIC_COLUMNS:
            if col in prob_scores.columns:
                details[col] = (
                    prob_scores[col]
                    .reindex(df.index, fill_value=0.0)
                    .clip(lower=0.0, upper=1.0)
                    .astype(float)
                )

        # PHASE2 internal reciprocal flow column — severity normalization 미적용 (raw 0~1)
        if _RECIPROCAL_FLOW_COLUMN in reciprocal_scores.columns:
            details[_RECIPROCAL_FLOW_COLUMN] = (
                reciprocal_scores[_RECIPROCAL_FLOW_COLUMN]
                .reindex(df.index, fill_value=0.0)
                .clip(lower=0.0, upper=1.0)
                .astype(float)
            )

        # IC01 evidence_level / review_reason sidecar — metadata 에 보관
        row_sidecar: dict[str, pd.Series] = {
            col: series.reindex(df.index, fill_value="").astype("object")
            for col, series in sidecar_columns.items()
        }

        scores = details.max(axis=1).fillna(0.0)
        flagged_indices = scores[scores > 0].index.tolist()

        # RuleFlag 는 canonical rule id (IC01~03) 만 — probabilistic / reciprocal column 미포함.
        rule_flags = [
            self._create_rule_flag(
                rule_id=rule_id,
                flagged_count=int((raw_scores > 0).sum()),
                total_count=len(df),
            )
            for rule_id, raw_scores in rule_results.items()
        ]

        return self._make_result(
            flagged_indices=flagged_indices,
            scores=scores,
            rule_flags=rule_flags,
            details=details,
            metadata={
                "elapsed": elapsed,
                "skipped_rules": skipped,
                "row_sidecar": row_sidecar,
                "probabilistic_reconciliation": prob_summary,
                "reciprocal_flow": reciprocal_summary,
            },
            warnings=warnings,
        )

    def _empty_result(
        self,
        df: pd.DataFrame,
        warnings: list[str],
        elapsed: float,
    ) -> DetectionResult:
        return self._make_result(
            flagged_indices=[],
            scores=pd.Series(0.0, index=df.index),
            rule_flags=[],
            details=pd.DataFrame(index=df.index),
            metadata={"elapsed": elapsed, "skipped_rules": []},
            warnings=warnings,
        )
