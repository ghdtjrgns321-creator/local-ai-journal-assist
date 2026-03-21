"""EDAProfile 기반 피처 자동 분류.

Why: sklearn ColumnTransformer에 투입할 컬럼 그룹을 자동으로 결정한다.
EDAProfile의 dtype_group·cardinality를 활용하고, 감사 도메인 특수 케이스는
오버라이드 맵으로 처리한다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.eda.models import EDAProfile

logger = logging.getLogger(__name__)

# 기본 제외 컬럼 — ID, datetime(이미 파생변수로 변환됨), 레이블
_DEFAULT_EXCLUDE = frozenset({
    "document_id",
    "posting_date",
    "document_date",
    "is_fraud",
    "is_anomaly",
})

# 감사 도메인 오버라이드: 자동 분류와 다르게 배치해야 하는 컬럼
_DOMAIN_OVERRIDES: dict[str, str] = {
    "description_quality": "ordinal",   # object지만 순서 있는 범주 (missing/poor/normal)
    "has_risk_keyword": "ordinal",      # object지만 순서 있는 범주 (none/low/medium/high)
}


@dataclass
class FeatureGroups:
    """Pipeline에 투입할 피처 그룹 분류 결과."""

    numeric: list[str] = field(default_factory=list)
    categorical_high: list[str] = field(default_factory=list)   # TargetEncoder 대상
    categorical_low: list[str] = field(default_factory=list)    # OrdinalEncoder 대상
    boolean: list[str] = field(default_factory=list)
    ordinal: list[str] = field(default_factory=list)            # 순서형 범주
    excluded: list[str] = field(default_factory=list)           # Pipeline 미투입

    @property
    def all_features(self) -> list[str]:
        """Pipeline에 투입되는 전체 피처 목록."""
        return (
            self.numeric
            + self.categorical_high
            + self.categorical_low
            + self.boolean
            + self.ordinal
        )


def classify_features(
    profile: EDAProfile,
    *,
    high_cardinality_threshold: int = 50,
    exclude_columns: set[str] | None = None,
    overrides: dict[str, str] | None = None,
    high_missing_threshold: float = 0.9,
) -> FeatureGroups:
    """EDAProfile → FeatureGroups 자동 분류.

    Parameters
    ----------
    profile : EDA 프로파일링 결과
    high_cardinality_threshold : 이 이상이면 categorical_high로 분류
    exclude_columns : 추가 제외 컬럼. None이면 기본 제외만 적용
    overrides : 컬럼→그룹 수동 매핑. 기본 도메인 오버라이드에 병합
    high_missing_threshold : 결측률이 이 이상이면 자동 제외 + 경고
    """
    excludes = _DEFAULT_EXCLUDE | (exclude_columns or set())
    override_map = {**_DOMAIN_OVERRIDES, **(overrides or {})}

    groups = FeatureGroups()

    for col_name, cp in profile.columns.items():
        # 1단계: 제외 대상 필터
        if col_name in excludes:
            groups.excluded.append(col_name)
            continue

        # 2단계: 고결측률 컬럼 제외
        if cp.missing_rate >= high_missing_threshold:
            logger.warning(
                "컬럼 '%s' 결측률 %.1f%% → 자동 제외",
                col_name, cp.missing_rate * 100,
            )
            groups.excluded.append(col_name)
            continue

        # 3단계: 오버라이드 맵 우선
        if col_name in override_map:
            _assign_to_group(groups, col_name, override_map[col_name])
            continue

        # 4단계: dtype_group 기반 자동 분류
        _classify_by_dtype(groups, col_name, cp, high_cardinality_threshold)

    logger.info(
        "피처 분류 완료: numeric=%d, cat_high=%d, cat_low=%d, "
        "bool=%d, ordinal=%d, excluded=%d",
        len(groups.numeric), len(groups.categorical_high),
        len(groups.categorical_low), len(groups.boolean),
        len(groups.ordinal), len(groups.excluded),
    )
    return groups


def _assign_to_group(groups: FeatureGroups, col: str, group: str) -> None:
    """컬럼을 지정된 그룹에 배치."""
    target = getattr(groups, group, None)
    if target is None:
        logger.warning("알 수 없는 그룹 '%s' → excluded 처리: %s", group, col)
        groups.excluded.append(col)
        return
    target.append(col)


def _classify_by_dtype(
    groups: FeatureGroups,
    col: str,
    cp,  # ColumnProfile
    high_card_threshold: int,
) -> None:
    """dtype_group 기반 자동 분류."""
    if cp.dtype_group == "boolean":
        groups.boolean.append(col)
    elif cp.dtype_group == "numeric":
        groups.numeric.append(col)
    elif cp.dtype_group == "datetime":
        # datetime은 이미 파생변수로 변환됨 → 제외
        groups.excluded.append(col)
    elif cp.dtype_group == "categorical":
        card = cp.cardinality if cp.cardinality is not None else cp.unique_count
        if card >= high_card_threshold:
            groups.categorical_high.append(col)
        else:
            groups.categorical_low.append(col)
    else:
        groups.excluded.append(col)
