"""Base classes and shared result models for detection tracks."""

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


def _coerce_index_positions(index: pd.Index, values: list[object]) -> list[int]:
    """Return row positions for result indices, accepting labels or positions."""

    positions: list[int] = []
    label_positions = {label: pos for pos, label in enumerate(index)}
    for value in values:
        if value in label_positions:
            positions.append(label_positions[value])
            continue
        try:
            pos = int(value)
        except (TypeError, ValueError):
            continue
        if 0 <= pos < len(index):
            positions.append(pos)
    return positions


@dataclass
class RuleFlag:
    """Summary information for a single rule."""

    rule_id: str
    rule_name: str
    severity: int
    flagged_count: int
    total_count: int
    detail: str | None = None

    def __post_init__(self) -> None:
        if self.flagged_count < 0:
            raise ValueError(
                f"flagged_count must be non-negative / 음수일 수 없습니다: {self.flagged_count}"
            )
        if self.total_count < 0:
            raise ValueError(
                f"total_count must be non-negative / 음수일 수 없습니다: {self.total_count}"
            )
        if self.flagged_count > self.total_count:
            raise ValueError(
                f"flagged_count({self.flagged_count}) exceeds total_count"
                f"({self.total_count}) / 초과"
            )

    @property
    def flag_rate(self) -> float:
        """Return the flagged ratio."""

        return self.flagged_count / self.total_count if self.total_count > 0 else 0.0


@dataclass
class DetectionResult:
    """Aggregate output for one detector track."""

    track_name: str
    flagged_indices: list[int]
    scores: pd.Series
    rule_flags: list[RuleFlag]
    details: pd.DataFrame
    metadata: dict
    warnings: list[str] = field(default_factory=list)

    @property
    def elapsed_seconds(self) -> float:
        return float(self.metadata.get("elapsed", 0.0))

    @property
    def detector_profile(self) -> DetectorProfile:
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
        values = self.metadata.get(
            "activation_requirements",
            list(self.detector_profile.activation_requirements),
        )
        return [str(value) for value in values]

    @property
    def run_status(self) -> str:
        return str(self.metadata.get("run_status", "executed"))

    @property
    def skip_reason(self) -> str | None:
        value = self.metadata.get("skip_reason")
        return None if value in (None, "") else str(value)

    @property
    def flagged_count(self) -> int:
        return len(self.flagged_indices)

    @property
    def total_rules_run(self) -> int:
        return len(self.rule_flags)

    @property
    def detector_explanation_profile(self) -> DetectorExplanationProfile:
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
        values = self.metadata.get("references", list(self.detector_explanation_profile.references))
        return [str(value) for value in values]


def validate_input(df: pd.DataFrame, required_columns: list[str]) -> list[str]:
    """Return missing required columns, raising on empty input."""

    if df.empty:
        raise ValueError("입력 DataFrame이 비어 있습니다 (input DataFrame is empty)")
    return sorted(set(required_columns) - set(df.columns))


class BaseDetector(ABC):
    """Abstract detector interface implemented by every track."""

    def __init__(self, settings: AuditSettings | None = None) -> None:
        self._settings = settings or get_settings()
        self._logger = logging.getLogger(type(self).__name__)

    @abstractmethod
    def detect(self, df: pd.DataFrame) -> DetectionResult:
        """Run the detector on the provided DataFrame."""

    @property
    @abstractmethod
    def track_name(self) -> str:
        """Return the detector track name."""

    def _make_result(
        self,
        flagged_indices: list[int],
        scores: pd.Series,
        rule_flags: list[RuleFlag],
        details: pd.DataFrame,
        metadata: dict,
        warnings: list[str],
    ) -> DetectionResult:
        """Create a normalized DetectionResult."""

        clean_indices = _coerce_index_positions(scores.index, list(flagged_indices))
        meta = dict(metadata or {})
        profile = get_detector_profile(self.track_name)
        explanation = get_detector_explanation_profile(self.track_name)

        meta.setdefault("display_name", profile.display_name)
        meta.setdefault("maturity", str(profile.maturity))
        meta.setdefault("default_enabled", profile.default_enabled)
        meta.setdefault("activation_requirements", list(profile.activation_requirements))
        meta.setdefault("run_status", "executed")
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
        """Create a RuleFlag using shared rule metadata."""

        if rule_id not in RULE_CODES:
            valid_ids = sorted(RULE_CODES.keys())
            raise ValueError(
                f"알 수 없는 rule_id '{rule_id}' (unknown rule_id). valid ids: {valid_ids}"
            )

        return RuleFlag(
            rule_id=rule_id,
            rule_name=RULE_CODES[rule_id],
            severity=SEVERITY_MAP[rule_id],
            flagged_count=flagged_count,
            total_count=total_count,
            detail=detail,
        )
