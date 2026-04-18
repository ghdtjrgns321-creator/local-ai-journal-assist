"""NLPDetector — 적요 NLP + 임베딩 기반 의미 탐지 트랙 (WU-21).

5개 서브룰
----------
- NLP01: header-account 의미 불일치 (ISA 315/240 경제적 실질)
- NLP02: process-account 의미 불일치
- NLP03: 비정형 적요 (centroid 거리 이상치)
- NLP04: IC 적요 패턴 이상
- NLP05: risk keyword 동의어 우회

설계 원칙
---------
- GraphDetector 패턴 미러링: _build_registry → 룰 try/except 격리 → _build_result
- LAYER_WEIGHTS 미등록 — RelationalDetector/GraphDetector 선례. Phase 3 Stacking에서 배분.
- 임베딩 API 불가 시 graceful 스킵 (empty result + warning, 예외 미전파).
- 비식별화: nlp_rules 내부 _sanitize_series가 morpheme_tokens / 영문 토큰 처리.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pandas as pd

from config.settings import AuditSettings, get_risk_keywords
from src.detection.base import BaseDetector, DetectionResult
from src.detection.constants import SEVERITY_MAP

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.llm.embedding_service import EmbeddingService


class NLPDetector(BaseDetector):
    """적요 NLP + 임베딩 기반 탐지기. GraphDetector 패턴 준수."""

    def __init__(
        self,
        settings: AuditSettings | None = None,
        *,
        embedding_service: "EmbeddingService | None" = None,
        risk_keywords: list[str] | None = None,
    ) -> None:
        super().__init__(settings)
        # Why: 둘 다 lazy 초기화 — 테스트 mock 주입 + API 불가 graceful
        self._embedding_service = embedding_service
        self._risk_keywords = risk_keywords  # None이면 risk_keywords.yaml 로드

    @property
    def track_name(self) -> str:
        return "nlp"

    def detect(self, df: pd.DataFrame) -> DetectionResult:
        if df.empty:
            raise ValueError("입력 DataFrame이 비어 있습니다")

        start = time.perf_counter()
        warnings: list[str] = []

        svc = self._get_embedding_service(warnings)
        if svc is None:
            return self._empty_result(df, warnings, time.perf_counter() - start)

        rule_results: dict[str, pd.Series] = {}
        skipped: list[str] = []

        for rule_id, func, kwargs in self._build_registry(svc):
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

    # ── 헬퍼 ─────────────────────────────────────────────────

    def _get_embedding_service(self, warnings: list[str]) -> "EmbeddingService | None":
        """주입된 서비스 또는 싱글톤 lazy 초기화. 실패 시 None + warning."""
        if self._embedding_service is not None:
            return self._embedding_service
        try:
            from src.llm.embedding_service import get_embedding_service

            return get_embedding_service()
        except Exception as exc:
            warnings.append(f"임베딩 서비스 초기화 실패 — NLPDetector 스킵: {exc}")
            self._logger.warning("EmbeddingService 초기화 실패: %s", exc)
            return None

    def _get_risk_keywords(self) -> list[str]:
        """risk_keywords.yaml에서 high+medium 통합 추출."""
        if self._risk_keywords is not None:
            return self._risk_keywords
        try:
            kw = get_risk_keywords()
            return list(kw.get("high_risk", [])) + list(kw.get("medium_risk", []))
        except Exception as exc:  # pragma: no cover - 환경 의존
            self._logger.warning("risk_keywords 로드 실패: %s", exc)
            return []

    def _build_registry(
        self, svc: "EmbeddingService",
    ) -> list[tuple[str, "Callable", dict]]:
        """서브룰 레지스트리 — settings 파라미터 주입."""
        from src.detection.nlp_rules import (
            nlp01_header_account_mismatch,
            nlp02_process_account_mismatch,
            nlp03_atypical_description,
            nlp04_ic_description_anomaly,
            nlp05_synonym_evasion,
        )

        s = self._settings
        return [
            ("NLP01", nlp01_header_account_mismatch, {
                "embedding_service": svc,
                "similarity_threshold": s.nlp_header_account_threshold,
            }),
            ("NLP02", nlp02_process_account_mismatch, {
                "embedding_service": svc,
                "similarity_threshold": s.nlp_process_account_threshold,
            }),
            ("NLP03", nlp03_atypical_description, {
                "embedding_service": svc,
                "anomaly_percentile": s.nlp_anomaly_percentile,
                "min_group_size": s.nlp_min_group_size,
            }),
            ("NLP04", nlp04_ic_description_anomaly, {
                "embedding_service": svc,
                "similarity_threshold": s.nlp_ic_similarity_threshold,
                "min_group_size": s.nlp_min_group_size,
            }),
            ("NLP05", nlp05_synonym_evasion, {
                "embedding_service": svc,
                "risk_keywords": self._get_risk_keywords(),
                "synonym_threshold": s.nlp_synonym_threshold,
            }),
        ]

    def _build_result(
        self,
        df: pd.DataFrame,
        rule_results: dict[str, pd.Series],
        skipped: list[str],
        warnings: list[str],
        elapsed: float,
    ) -> DetectionResult:
        """룰별 연속 점수 → scores, details, RuleFlag 통합 (GraphDetector 패턴)."""
        details = pd.DataFrame(index=df.index)
        for rule_id, raw_scores in rule_results.items():
            severity_factor = SEVERITY_MAP[rule_id] / 5.0
            details[rule_id] = (
                raw_scores.reindex(df.index, fill_value=0.0) * severity_factor
            )

        # MAX 패턴 — 행별 최대 점수
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

        return self._make_result(
            flagged_indices=flagged_indices,
            scores=scores,
            rule_flags=rule_flags,
            details=details,
            metadata={"elapsed": elapsed, "skipped_rules": skipped},
            warnings=warnings,
        )

    def _empty_result(
        self, df: pd.DataFrame, warnings: list[str], elapsed: float,
    ) -> DetectionResult:
        return self._make_result(
            flagged_indices=[],
            scores=pd.Series(0.0, index=df.index),
            rule_flags=[],
            details=pd.DataFrame(index=df.index),
            metadata={"elapsed": elapsed, "skipped_rules": []},
            warnings=warnings,
        )
