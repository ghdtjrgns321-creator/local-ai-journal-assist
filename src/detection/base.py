"""Detection 공용 기반 클래스 — BaseDetector ABC + 결과 dataclass.

Why: 모든 탐지 트랙(Layer A/B/C, Phase 2 ML)이 동일한 인터페이스를 구현하도록 강제.
     score_aggregator가 DetectionResult 리스트만으로 가중합 산출 가능.

구현 가이드 (Layer 작성자용):
    - detect() 내부에서 룰 결과를 dict로 모은 뒤 DataFrame 변환 시 원본 인덱스 강제 할당:
        rule_results = {"A01": series_a01, "A02": series_a02}
        details = pd.DataFrame(rule_results, index=df.index).fillna(0.0)
    - 이렇게 해야 인덱스 틀어짐으로 인한 NaN/행 밀림을 방지할 수 있음.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import pandas as pd

from config.settings import AuditSettings, get_settings
from src.detection.constants import (
    RULE_CODES,
    SEVERITY_MAP,
    DetectorExplanationProfile,
    DetectorProfile,
    get_detector_explanation_profile,
    get_detector_profile,
)


# ── 결과 dataclass ───────────────────────────────────────────


@dataclass
class RuleFlag:
    """개별 룰의 탐지 요약 — 대시보드 요약 표시용.

    행별 상세는 DetectionResult.details DataFrame이 담당.
    """

    rule_id: str                # "A01", "B03" 등
    rule_name: str              # RULE_CODES에서 참조
    severity: int               # 1~5 (SEVERITY_MAP)
    flagged_count: int          # 플래그된 행 수
    total_count: int            # 검사 대상 행 수
    detail: str | None = None   # 부가 설명 (선택)

    def __post_init__(self) -> None:
        if self.flagged_count < 0:
            raise ValueError(f"flagged_count는 음수일 수 없습니다: {self.flagged_count}")
        if self.total_count < 0:
            raise ValueError(f"total_count는 음수일 수 없습니다: {self.total_count}")
        if self.flagged_count > self.total_count:
            raise ValueError(
                f"flagged_count({self.flagged_count})가 "
                f"total_count({self.total_count})를 초과합니다"
            )

    @property
    def flag_rate(self) -> float:
        """플래그 비율 (0.0~1.0)."""
        return self.flagged_count / self.total_count if self.total_count > 0 else 0.0


@dataclass
class DetectionResult:
    """하나의 탐지 트랙(Layer) 전체 결과.

    scores: 행별 종합 점수 (0.0~1.0), index=원본 DataFrame index.
    details: index=원본 행, columns=룰 ID, values=float 0.0~1.0.
    """

    track_name: str
    flagged_indices: list[int]
    scores: pd.Series
    rule_flags: list[RuleFlag]
    details: pd.DataFrame
    metadata: dict                  # {"elapsed": float, "skipped_rules": [...]}
    warnings: list[str] = field(default_factory=list)

    @property
    def elapsed_seconds(self) -> float:
        """소요 시간 (FeatureResult 패턴과 일관)."""
        return self.metadata.get("elapsed", 0.0)

    @property
    def detector_profile(self) -> DetectorProfile:
        """탐지기 운영 메타데이터."""
        return get_detector_profile(self.track_name)

    @property
    def display_name(self) -> str:
        return str(self.metadata.get("display_name", self.detector_profile.display_name))

    @property
    def maturity(self) -> str:
        return str(self.metadata.get("maturity", self.detector_profile.maturity))

    @property
    def default_enabled(self) -> bool:
        return bool(self.metadata.get("default_enabled", self.detector_profile.default_enabled))

    @property
    def activation_requirements(self) -> list[str]:
        reqs = self.metadata.get(
            "activation_requirements",
            list(self.detector_profile.activation_requirements),
        )
        return [str(req) for req in reqs]

    @property
    def run_status(self) -> str:
        return str(self.metadata.get("run_status", "executed"))

    @property
    def skip_reason(self) -> str | None:
        value = self.metadata.get("skip_reason")
        return None if value in (None, "") else str(value)

    @property
    def flagged_count(self) -> int:
        """플래그된 행 수."""
        return len(self.flagged_indices)

    @property
    def total_rules_run(self) -> int:
        """실행된 룰 수."""
        return len(self.rule_flags)

    @property
    def detector_explanation_profile(self) -> DetectorExplanationProfile:
        """탐지기 설명 메타데이터."""
        return get_detector_explanation_profile(self.track_name)

    @property
    def explanation_summary(self) -> str:
        return str(
            self.metadata.get("explanation_summary", self.detector_explanation_profile.summary)
        )

    @property
    def why_it_flagged(self) -> str:
        return str(
            self.metadata.get("why_it_flagged", self.detector_explanation_profile.why_it_flagged)
        )

    @property
    def used_columns(self) -> list[str]:
        values = self.metadata.get(
            "used_columns",
            list(self.detector_explanation_profile.used_columns),
        )
        return [str(value) for value in values]

    @property
    def false_positive_risks(self) -> list[str]:
        values = self.metadata.get(
            "false_positive_risks",
            list(self.detector_explanation_profile.false_positive_risks),
        )
        return [str(value) for value in values]

    @property
    def auditor_checks(self) -> list[str]:
        values = self.metadata.get(
            "auditor_checks",
            list(self.detector_explanation_profile.auditor_checks),
        )
        return [str(value) for value in values]

    @property
    def references(self) -> list[str]:
        values = self.metadata.get(
            "references",
            list(self.detector_explanation_profile.references),
        )
        return [str(value) for value in values]


# ── 입력 검증 유틸 ───────────────────────────────────────────


def validate_input(df: pd.DataFrame, required_columns: list[str]) -> list[str]:
    """필수 컬럼 존재 확인. 빈 DataFrame이면 ValueError.

    Returns:
        누락 컬럼 리스트. 빈 리스트 = 모두 존재.
    """
    if df.empty:
        raise ValueError("입력 DataFrame이 비어 있습니다")
    return sorted(set(required_columns) - set(df.columns))


# ── 추상 기반 클래스 ─────────────────────────────────────────


class BaseDetector(ABC):
    """모든 탐지 트랙이 구현해야 할 인터페이스."""

    def __init__(self, settings: AuditSettings | None = None) -> None:
        self._settings = settings or get_settings()
        self._logger = logging.getLogger(type(self).__name__)

    @abstractmethod
    def detect(self, df: pd.DataFrame) -> DetectionResult:
        """DataFrame을 입력받아 이상탐지 수행."""
        ...

    @property
    @abstractmethod
    def track_name(self) -> str:
        """트랙 고유 이름 (예: 'layer_a'). Layer enum 값과 대응."""
        ...

    # ── 헬퍼 메서드 ──────────────────────────────────────────

    def _make_result(
        self,
        flagged_indices: list[int],
        scores: pd.Series,
        rule_flags: list[RuleFlag],
        details: pd.DataFrame,
        metadata: dict,
        warnings: list[str],
    ) -> DetectionResult:
        """DetectionResult 생성. track_name 자동 설정 + numpy.int64 방어."""
        # Why: df[cond].index.tolist()가 numpy.int64를 반환할 수 있어 JSON 직렬화 실패 방지
        clean_indices = [int(idx) for idx in flagged_indices]
        meta = dict(metadata or {})
        profile = get_detector_profile(self.track_name)
        meta.setdefault("display_name", profile.display_name)
        meta.setdefault("maturity", str(profile.maturity))
        meta.setdefault("default_enabled", profile.default_enabled)
        meta.setdefault("activation_requirements", list(profile.activation_requirements))
        meta.setdefault("run_status", "executed")
        explanation = get_detector_explanation_profile(self.track_name)
        meta.setdefault("explanation_summary", explanation.summary)
        meta.setdefault("why_it_flagged", explanation.why_it_flagged)
        meta.setdefault("used_columns", list(explanation.used_columns))
        meta.setdefault("false_positive_risks", list(explanation.false_positive_risks))
        meta.setdefault("auditor_checks", list(explanation.auditor_checks))
        meta.setdefault("references", list(explanation.references))
        return DetectionResult(
            track_name=self.track_name,
            flagged_indices=clean_indices,
            scores=scores,
            rule_flags=rule_flags,
            details=details,
            metadata=meta,
            warnings=warnings,
        )

    def _create_rule_flag(
        self,
        rule_id: str,
        flagged_count: int,
        total_count: int,
        detail: str | None = None,
    ) -> RuleFlag:
        """RULE_CODES/SEVERITY_MAP에서 자동 조회하여 RuleFlag 생성.

        Raises:
            ValueError: rule_id가 RULE_CODES에 없을 때 (유효 ID 목록 포함).
        """
        if rule_id not in RULE_CODES:
            valid_ids = sorted(RULE_CODES.keys())
            raise ValueError(
                f"알 수 없는 rule_id: '{rule_id}'. "
                f"유효한 ID: {valid_ids}"
            )
        return RuleFlag(
            rule_id=rule_id,
            rule_name=RULE_CODES[rule_id],
            severity=SEVERITY_MAP[rule_id],
            flagged_count=flagged_count,
            total_count=total_count,
            detail=detail,
        )
