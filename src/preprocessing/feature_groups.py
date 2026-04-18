"""EDAProfile → 6그룹 피처 자동 분류.

Why: ColumnTransformer에 전달할 컬럼 목록을 EDA 결과 기반으로 자동 결정.
ID/datetime/label → excluded, 고카디널리티 → categorical_high 등.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.eda.models import ColumnProfile, EDAProfile
from src.preprocessing.constants import LABEL_COLUMNS

logger = logging.getLogger(__name__)

# 자동 제외 대상 컬럼명 패턴
_EXCLUDE_NAMES = {"document_id", "doc_id", "row_id", "id"}
_HIGH_MISSING_THRESHOLD = 0.90
_LOW_CARD_DOMAIN_COLUMNS = {"user_persona"}


@dataclass
class FeatureGroups:
    """6그룹 피처 분류 결과."""

    numeric: list[str] = field(default_factory=list)
    categorical_high: list[str] = field(default_factory=list)
    categorical_low: list[str] = field(default_factory=list)
    boolean: list[str] = field(default_factory=list)
    ordinal: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)

    @property
    def all_features(self) -> list[str]:
        """excluded 제외한 전체 피처 목록."""
        return (
            self.numeric
            + self.categorical_high
            + self.categorical_low
            + self.boolean
            + self.ordinal
        )


def classify_features(
    profile: EDAProfile,
    high_card_threshold: int = 50,
    exclude_columns: list[str] | None = None,
    domain_overrides: dict[str, str] | None = None,
) -> FeatureGroups:
    """EDAProfile 기반 컬럼 6그룹 자동 분류."""
    groups = FeatureGroups()
    exclude_set = set(exclude_columns or [])

    for col_name, cp in profile.columns.items():
        # 사용자 지정 제외
        if col_name in exclude_set:
            _assign_to_group(groups, col_name, "excluded")
            continue

        # ID·label·datetime 자동 제외
        if col_name.lower() in _EXCLUDE_NAMES | LABEL_COLUMNS:
            _assign_to_group(groups, col_name, "excluded")
            continue
        if cp.dtype_group == "datetime":
            _assign_to_group(groups, col_name, "excluded")
            continue

        # 고결측률 자동 제외
        if cp.missing_rate >= _HIGH_MISSING_THRESHOLD:
            logger.warning("컬럼 '%s' 결측률 %.1f%% → excluded", col_name, cp.missing_rate * 100)
            _assign_to_group(groups, col_name, "excluded")
            continue

        # 도메인 오버라이드 (ordinal, categorical_high 등 수동 지정)
        if domain_overrides and col_name in domain_overrides:
            _assign_to_group(groups, col_name, domain_overrides[col_name])
            continue
        if col_name in _LOW_CARD_DOMAIN_COLUMNS:
            _assign_to_group(groups, col_name, "categorical_low")
            continue

        # dtype 기반 자동 분류
        _classify_by_dtype(groups, col_name, cp, high_card_threshold)

    return groups


def _assign_to_group(groups: FeatureGroups, col: str, group: str) -> None:
    """컬럼을 지정 그룹에 배치."""
    getattr(groups, group).append(col)


def _classify_by_dtype(
    groups: FeatureGroups,
    col: str,
    cp: ColumnProfile,
    high_card_threshold: int,
) -> None:
    """dtype_group 기반 자동 분류. 범주형은 카디널리티로 high/low 분기."""
    if cp.dtype_group == "boolean":
        _assign_to_group(groups, col, "boolean")
    elif cp.dtype_group == "numeric":
        _assign_to_group(groups, col, "numeric")
    elif cp.dtype_group == "categorical":
        if cp.unique_count >= high_card_threshold:
            _assign_to_group(groups, col, "categorical_high")
        else:
            _assign_to_group(groups, col, "categorical_low")
    else:
        # 알 수 없는 dtype_group → numeric fallback
        logger.warning("컬럼 '%s' dtype_group='%s' → numeric 배치", col, cp.dtype_group)
        _assign_to_group(groups, col, "numeric")
