"""LLM 테스트용 공통 fixture.

prefix: lm_ (llm module)
"""

from __future__ import annotations

import pytest

from src.eda.models import ColumnProfile, EDAProfile
from src.llm.models import (
    ColumnPreprocessing,
    ImbalanceStrategy,
    ImputerStrategy,
    ModelGroupStrategy,
    PreprocessingAdvice,
    ScalerStrategy,
)


@pytest.fixture()
def lm_eda_profile() -> EDAProfile:
    """테스트용 EDAProfile — 수치형 2개 + 범주형 1개 + datetime 1개."""
    return EDAProfile(
        total_rows=10_000,
        total_columns=4,
        memory_bytes=320_000,
        duplicate_rows=5,
        columns={
            "debit_amount": ColumnProfile(
                name="debit_amount",
                dtype="float64",
                dtype_group="numeric",
                missing_rate=0.002,
                unique_count=8500,
                mode="0.0",
                mean=2_100_000.0,
                median=500_000.0,
                std=15_300_000.0,
                skewness=8.7,
                kurtosis=120.0,
                q1=100_000.0,
                q3=2_000_000.0,
                iqr=1_900_000.0,
                outlier_count=500,
                min_val=0.0,
                max_val=900_000_000.0,
            ),
            "credit_amount": ColumnProfile(
                name="credit_amount",
                dtype="float64",
                dtype_group="numeric",
                missing_rate=0.0,
                unique_count=7200,
                mode="0.0",
                mean=1_800_000.0,
                median=400_000.0,
                std=12_000_000.0,
                skewness=1.2,
                kurtosis=5.0,
                q1=50_000.0,
                q3=1_500_000.0,
                iqr=1_450_000.0,
                outlier_count=100,
                min_val=0.0,
                max_val=500_000_000.0,
            ),
            "gl_account": ColumnProfile(
                name="gl_account",
                dtype="object",
                dtype_group="categorical",
                missing_rate=0.0,
                unique_count=4200,
                mode="4100",
                cardinality=4200,
                top_values=[("4100", 520), ("1200", 480)],
            ),
            "posting_date": ColumnProfile(
                name="posting_date",
                dtype="datetime64[ns]",
                dtype_group="datetime",
                missing_rate=0.001,
                unique_count=365,
                mode="2025-01-15",
                min_date="2025-01-01",
                max_date="2025-12-31",
                date_range_days=364,
            ),
        },
    )


@pytest.fixture()
def lm_valid_advice_dict() -> dict:
    """LLM이 반환할 유효한 JSON dict (Pydantic 파싱 대상)."""
    return {
        "columns": [
            {
                "column": "debit_amount",
                "dtype_group": "numeric",
                "imputer": "median",
                "imputer_reason": "왜도 8.7 — median이 이상치에 안정적",
                "tree_model": {
                    "scaler": "none",
                    "scaler_reason": "XGBoost는 스케일 불변",
                    "outlier": "none",
                    "outlier_reason": "트리 모델은 이상치에 강건",
                },
                "distance_model": {
                    "scaler": "robust",
                    "scaler_reason": "이상치 5% — RobustScaler 권장",
                    "outlier": "log",
                    "outlier_reason": "skewness 8.7 — log1p 변환 적용",
                },
            },
            {
                "column": "gl_account",
                "dtype_group": "categorical",
                "imputer": "most_frequent",
                "imputer_reason": "결측 0%",
                "encoder": "target",
                "encoder_reason": "카디널리티 4,200 — OneHot 시 차원 폭발",
                "tree_model": {"scaler": "none", "outlier": "none"},
                "distance_model": {"scaler": "none", "outlier": "none"},
            },
        ],
        "imbalance": "class_weight",
        "imbalance_reason": "감사 데이터 이상 비율 3~5% 예상",
        "general_notes": ["datetime 컬럼은 피처 엔진에서 이미 변환 완료"],
    }


@pytest.fixture()
def lm_advice_object() -> PreprocessingAdvice:
    """테스트용 PreprocessingAdvice 객체."""
    return PreprocessingAdvice(
        columns=[
            ColumnPreprocessing(
                column="amount",
                dtype_group="numeric",
                imputer=ImputerStrategy.MEDIAN,
                tree_model=ModelGroupStrategy(
                    scaler=ScalerStrategy.NONE,
                ),
                distance_model=ModelGroupStrategy(
                    scaler=ScalerStrategy.ROBUST,
                ),
            ),
        ],
        imbalance=ImbalanceStrategy.CLASS_WEIGHT,
        source="llm",
    )
