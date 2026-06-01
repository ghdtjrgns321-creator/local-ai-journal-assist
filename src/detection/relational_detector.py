"""RelationalDetector — 관계 기반 이상 탐지 독립 트랙 (WU-08).

Why: GL 전표의 거래처/계정/문서 관계에서 이상 패턴을 탐지.
     R01(신규 거래처 대액) + R02(휴면 계정) + R03(IC 이전가격) + R04(문서 흐름 누락)
     + R05(rare account-partner edge) + R06(user degree spike) + R07(dormant partner).

Note: LAYER_WEIGHTS에 의도적 미등록 — 성능 평가 후 가중치 배분 예정 (WU-03 Stacking).

v7-plan S6 Phase A (2026-05-28):
    metadata['relational_edge_artifact'] 추가. row 단위 score 결과를 edge 단위로
    그룹핑한 sanitized projection — PHASE2 RelationalCase builder 가 직접 소비한다.
    기존 row 단위 출력 (scores / details / rule_flags / graph_entity_summary) 변경 0건
    (invariant #61). 도메인 정당화 — PCAOB AS 2401 §B7 (unusual relationships) +
    ISA 240 §32 (management override via unusual relationships).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from config.settings import AuditSettings
from src.detection.base import BaseDetector, DetectionResult
from src.detection.constants import SEVERITY_MAP
from src.detection.relational_rules import (
    r01_new_counterparty,
    r02_dormant_account_activity,
    r03_transfer_pricing_anomaly,
    r04_missing_relationship,
    r05_rare_account_partner_edge,
    r06_user_account_degree_spike,
    r07_dormant_partner_reactivation,
)

if TYPE_CHECKING:
    from collections.abc import Callable


# ── relational_edge_artifact (v7-plan S6 Phase A) ─────────────


# Why: 룰별 default evidence_tier — precision/recall 튜닝 압력 사용 금지 (D044).
#      R03/R05/R06/R07 은 graph/entity / outlier 신호 → strong.
#      R01/R02/R04 는 단순 binary / 행위 패턴 → moderate.
_RULE_DEFAULT_TIER: dict[str, str] = {
    "R01": "moderate",
    "R02": "moderate",
    "R03": "strong",
    "R04": "moderate",
    "R05": "strong",
    "R06": "strong",
    "R07": "strong",
}

# Why: 룰별 metric_name 의 의미 라벨. composite score 인 룰은 "composite_score",
#      이전가격 outlier 는 "transfer_pricing_score", 단순 binary 는 "binary_hit".
_RULE_METRIC_NAME: dict[str, str] = {
    "R01": "new_counterparty_score",
    "R02": "dormant_account_score",
    "R03": "transfer_pricing_score",
    "R04": "missing_relationship_score",
    "R05": "rare_pair_score",
    "R06": "user_degree_spike_score",
    "R07": "dormant_partner_score",
}


@dataclass
class RelationalEdgeArtifact:
    """relational R01~R07 row score → edge-aggregated projection (schema v1).

    Why: PHASE2 RelationalCase builder 가 row 단위 details/scores 대신 edge 단위
    grouping 을 소비하도록 한다. (edge_a, edge_b, rule_id) 튜플이 같은 row 들이
    하나의 edge entry 로 dedup 되며, row_indices 와 row_positions 가 그 row 들의
    set 를 보유한다.

    invariant:
      - edges entry 의 row_indices 는 ``_json_safe`` 통과 (MultiIndex tuple 안전).
      - row_positions 는 int — display payload 가 아닌 source of truth lookup key.
      - evidence_tier 는 룰별 default 그대로 (D044, 튜닝 압력 금지).
    """

    schema_version: int = 1
    edges: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "edges": list(self.edges),
            "coverage": dict(self.coverage),
        }


def _rel_json_safe(value: Any) -> Any:
    """duplicate_pair_features / _ic_json_safe 와 동일 sanitization."""
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    return str(value)


def _rel_safe_str(value: Any) -> str:
    """edge_a/edge_b 식별자 sanitization. None/NaN → 빈 문자열."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _column_series_or_blank(df: pd.DataFrame, column: str) -> pd.Series:
    """선택적 컬럼 시리즈. 부재 시 빈 문자열 시리즈 반환 (graceful)."""
    if column in df.columns:
        return df[column].fillna("").astype(str)
    return pd.Series([""] * len(df), index=df.index, dtype=object)


# rule_id → (edge_a 컬럼, edge_b 컬럼). 빈 문자열 컬럼명은 "" 의미.
_RULE_EDGE_COLUMNS: dict[str, tuple[str, str]] = {
    "R01": ("trading_partner", ""),
    "R02": ("", "gl_account"),
    "R03": ("trading_partner", "gl_account"),
    "R04": ("", "gl_account"),
    "R05": ("trading_partner", "gl_account"),
    "R06": ("created_by", "gl_account"),
    "R07": ("trading_partner", ""),
}


def _extract_rule_edges(
    df: pd.DataFrame,
    rule_id: str,
    scores: pd.Series,
) -> list[dict[str, Any]]:
    """단일 룰의 row score → edge entry list.

    동일 (edge_a, edge_b) 튜플을 가진 row 들을 한 edge entry 로 dedup.
    metric_value 는 그 row 들의 max raw score (rule 별 의미 — composite/binary/outlier).
    """
    if scores is None or scores.empty:
        return []
    positive = scores[scores > 0]
    if positive.empty:
        return []

    col_a, col_b = _RULE_EDGE_COLUMNS.get(rule_id, ("", ""))
    series_a = _column_series_or_blank(df, col_a) if col_a else None
    series_b = _column_series_or_blank(df, col_b) if col_b else None

    # row label → row position 매핑 (df.index.get_indexer 가 안전).
    positions_by_label = pd.Series(np.arange(len(df), dtype=int), index=df.index)

    metric_name = _RULE_METRIC_NAME.get(rule_id, "score")
    tier = _RULE_DEFAULT_TIER.get(rule_id, "moderate")

    # (edge_a, edge_b) → list[(label, position, score)] 그룹핑.
    grouped: dict[tuple[str, str], list[tuple[Any, int, float]]] = {}
    for label, raw_score in positive.items():
        try:
            position = int(positions_by_label.loc[label])
        except KeyError:
            continue
        edge_a = _rel_safe_str(series_a.loc[label]) if series_a is not None else ""
        edge_b = _rel_safe_str(series_b.loc[label]) if series_b is not None else ""
        # 빈 edge (양쪽 모두 공란) 은 edge 단위 case 의미가 없으므로 제외.
        if edge_a == "" and edge_b == "":
            continue
        key = (edge_a, edge_b)
        grouped.setdefault(key, []).append((label, position, float(raw_score)))

    entries: list[dict[str, Any]] = []
    for (edge_a, edge_b), rows in grouped.items():
        row_labels = [r[0] for r in rows]
        row_positions = [r[1] for r in rows]
        metric_value = max(r[2] for r in rows)
        entries.append(
            {
                "rule_id": rule_id,
                "row_indices": [_rel_json_safe(label) for label in row_labels],
                "row_positions": row_positions,
                "edge_a": edge_a,
                "edge_b": edge_b,
                "metric_name": metric_name,
                "metric_value": metric_value,
                "evidence_tier": tier,
            }
        )
    return entries


def build_relational_edge_artifact(
    df: pd.DataFrame,
    rule_results: dict[str, pd.Series],
    settings: AuditSettings | None = None,  # noqa: ARG001 — schema-stable signature
    audit_rules: dict | None = None,  # noqa: ARG001 — schema-stable signature
) -> RelationalEdgeArtifact:
    """rule_results (rule_id → row score) → RelationalEdgeArtifact.

    Args:
        df: detection 대상 DataFrame. edge_a/edge_b 컬럼 조회용.
        rule_results: rule_id → row score Series. raw score (severity 정규화 전)
            또는 severity 정규화 후 모두 동작 — schema 는 동일.
        settings: reserved (현재 미사용, 추후 룰별 tier override 확장 여지).
        audit_rules: reserved (현재 미사용, audit standard 인용 enrichment 여지).

    Returns:
        RelationalEdgeArtifact — edges 리스트 + rule_id 별 coverage (edge 개수).
        rule_results 가 빈 dict 거나 모든 row score 가 0 → 빈 edges + 0 coverage.
    """
    if not rule_results or df.empty:
        return RelationalEdgeArtifact()

    artifact = RelationalEdgeArtifact()
    for rule_id, scores in rule_results.items():
        rule_entries = _extract_rule_edges(df, rule_id, scores)
        artifact.coverage[rule_id] = len(rule_entries)
        artifact.edges.extend(rule_entries)
    return artifact


class RelationalDetector(BaseDetector):
    """관계 기반 이상 탐지기. IntercompanyMatcher _build_registry 패턴 준수."""

    def __init__(
        self,
        settings: AuditSettings | None = None,
        *,
        audit_rules: dict | None = None,
        doc_flow_df: pd.DataFrame | None = None,
    ) -> None:
        super().__init__(settings)
        self._audit_rules = audit_rules or {}
        self._doc_flow_df = doc_flow_df

    @property
    def track_name(self) -> str:
        return "relational"

    def detect(self, df: pd.DataFrame) -> DetectionResult:
        start = time.perf_counter()
        warnings: list[str] = []

        rule_results: dict[str, pd.Series] = {}
        skipped: list[str] = []

        for rule_id, func, kwargs in self._build_registry():
            try:
                rule_results[rule_id] = func(df, **kwargs)
            except Exception as exc:
                skipped.append(rule_id)
                warnings.append(f"{rule_id} 실행 실패: {exc}")
                self._logger.warning("%s 실행 실패: %s", rule_id, exc)

        elapsed = time.perf_counter() - start
        if not rule_results:
            return self._empty_result(df, warnings, elapsed)
        return self._build_result(df, rule_results, skipped, warnings, elapsed)

    def _build_registry(self) -> list[tuple[str, Callable, dict]]:
        """서브룰 레지스트리 — settings 기반 파라미터 주입."""
        s = self._settings
        registry: list[tuple[str, Callable, dict]] = [
            (
                "R01",
                r01_new_counterparty,
                {
                    "lookback_days": s.rel_new_cp_lookback_days,
                    "large_quantile": s.rel_new_cp_large_quantile,
                },
            ),
            (
                "R02",
                r02_dormant_account_activity,
                {
                    "inactive_days": s.rel_dormant_inactive_days,
                    "reactivation_window_days": s.rel_dormant_reactivation_window_days,
                    "min_amount": s.rel_dormant_reactivation_min_amount,
                },
            ),
            (
                "R03",
                r03_transfer_pricing_anomaly,
                {
                    "deviation_threshold": s.rel_tp_ic_deviation_threshold,
                    "min_ic_pairs": s.rel_tp_min_ic_pairs,
                },
            ),
            # Why: R05~R07 graph/entity anomaly 보강. 각 함수는 컬럼 부재 시
            #      pd.Series(0.0, index=df.index)을 반환하여 graceful degrade.
            (
                "R05",
                r05_rare_account_partner_edge,
                {
                    "min_pair_population": s.rel_r05_min_pair_population,
                    "min_freq": s.rel_r05_min_freq,
                    "lookback_days": s.rel_r05_lookback_days,
                },
            ),
            (
                "R06",
                r06_user_account_degree_spike,
                {
                    "period": s.rel_r06_period,
                    "z_threshold": s.rel_r06_z_threshold,
                    "min_user_obs": s.rel_r06_min_user_obs,
                    "min_users": s.rel_r06_min_users,
                },
            ),
            (
                "R07",
                r07_dormant_partner_reactivation,
                {
                    "inactive_days": s.rel_r07_partner_inactive_days,
                    "reactivation_window_days": s.rel_r07_reactivation_window_days,
                    "min_amount": s.rel_r07_min_amount,
                },
            ),
        ]
        # Why: R04는 document_flows 데이터가 있을 때만 실행 (graceful)
        if self._doc_flow_df is not None and not self._doc_flow_df.empty:
            registry.append(
                (
                    "R04",
                    r04_missing_relationship,
                    {
                        "doc_flow_df": self._doc_flow_df,
                    },
                ),
            )
        return registry

    def _build_result(
        self,
        df: pd.DataFrame,
        rule_results: dict[str, pd.Series],
        skipped: list[str],
        warnings: list[str],
        elapsed: float,
    ) -> DetectionResult:
        """룰별 연속 점수 → scores, details, RuleFlag 통합."""
        # Why: severity/5.0 정규화 (IntercompanyMatcher 패턴 동일)
        details = pd.DataFrame(index=df.index)
        for rule_id, raw_scores in rule_results.items():
            severity_factor = SEVERITY_MAP[rule_id] / 5.0
            details[rule_id] = raw_scores.reindex(df.index, fill_value=0.0) * severity_factor

        # Why: MAX 패턴 — 행별 최대 점수 (합산 아님)
        scores = details.max(axis=1).fillna(0.0)
        flagged_indices = scores[scores > 0].index.tolist()

        rule_flags = [
            self._create_rule_flag(
                rule_id=rule_id,
                flagged_count=int((raw_scores > 0).sum()),
                total_count=len(df),
            )
            for rule_id, raw_scores in rule_results.items()
        ]

        # Why (v7-plan S6 Phase A): relational_edge_artifact 추가.
        #     rule_results (severity 정규화 전 raw score) 를 그대로 넘긴다 —
        #     edge metric_value 는 룰 의미상 raw score 가 자연스럽다.
        edge_artifact = build_relational_edge_artifact(
            df, rule_results, self._settings, self._audit_rules
        )

        # Why: graph/entity 요약 metadata (사용자 조정 — UI 미노출, 디버깅·QA 용).
        metadata = {
            "elapsed": elapsed,
            "skipped_rules": skipped,
            "graph_entity_summary": _build_graph_entity_summary(rule_results),
            "relational_edge_artifact": edge_artifact.to_dict(),
        }

        return self._make_result(
            flagged_indices=flagged_indices,
            scores=scores,
            rule_flags=rule_flags,
            details=details,
            metadata=metadata,
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
            metadata={
                "elapsed": elapsed,
                "skipped_rules": [],
                "relational_edge_artifact": RelationalEdgeArtifact().to_dict(),
            },
            warnings=warnings,
        )


def _build_graph_entity_summary(rule_results: dict[str, pd.Series]) -> dict[str, float]:
    """R05~R07 sub-detector의 graph/entity score 요약 지표.

    UI에 노출하지 않으며, run-level 진단/회귀 점검용. 빈 dict 반환은
    sub-detector 실행 실패 또는 모집단 0을 의미.
    """
    summary: dict[str, float] = {}
    for code, scores in rule_results.items():
        if code not in {"R05", "R06", "R07"}:
            continue
        non_zero: pd.Series = scores.loc[scores > 0]
        summary[f"{code}_flagged_rows"] = float(len(non_zero))
        summary[f"{code}_score_max"] = float(non_zero.max()) if not non_zero.empty else 0.0
        summary[f"{code}_score_q95"] = float(non_zero.quantile(0.95)) if not non_zero.empty else 0.0
    return summary


__all__ = [
    "RelationalDetector",
    "RelationalEdgeArtifact",
    "build_relational_edge_artifact",
]
