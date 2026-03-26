"""EDAProfile → LLM 프롬프트 변환 — 전처리 제안용 프롬프트 빌더.

Why: EDAProfile의 raw 측정값에 해석 필드(is_highly_skewed 등)를 추가하여
LLM이 판단하기 쉬운 컨텍스트를 만든다.
판정 기준은 config/settings.py의 heuristic_* 설정을 참조하여 하드코딩을 방지한다.
"""

from __future__ import annotations

import json

from config.settings import get_settings
from src.eda.models import EDAProfile


def profile_to_llm_context(profile: EDAProfile) -> dict:
    """EDAProfile → LLM이 해석하기 쉬운 축약 dict.

    원본 수치 + 해석 boolean 플래그를 함께 전달하여,
    LLM이 플래그를 참고하되 원본으로 세밀한 판단도 가능하게 한다.
    """
    settings = get_settings()
    columns_context: dict[str, dict] = {}

    for name, col in profile.columns.items():
        entry: dict = {
            "dtype_group": col.dtype_group,
            "missing_rate": col.missing_rate,
            "is_high_missing": col.missing_rate > settings.heuristic_missing_rate_threshold,
            "unique_count": col.unique_count,
        }

        if col.dtype_group == "numeric":
            # 이상치 비율 산출
            outlier_rate = (
                col.outlier_count / profile.total_rows
                if col.outlier_count and profile.total_rows > 0
                else 0.0
            )
            entry.update({
                "mean": col.mean,
                "median": col.median,
                "std": col.std,
                "skewness": col.skewness,
                "is_highly_skewed": (
                    abs(col.skewness) > settings.heuristic_skewness_threshold
                    if col.skewness is not None
                    else False
                ),
                "kurtosis": col.kurtosis,
                "outlier_count": col.outlier_count,
                "outlier_rate": round(outlier_rate, 4),
                "has_many_outliers": (
                    outlier_rate > settings.heuristic_outlier_rate_threshold
                ),
                "min_val": col.min_val,
                "max_val": col.max_val,
            })

        elif col.dtype_group == "categorical":
            entry.update({
                "cardinality": col.cardinality,
                "is_high_cardinality": (
                    col.cardinality > settings.heuristic_high_cardinality_threshold
                    if col.cardinality is not None
                    else False
                ),
                "top_values": col.top_values[:5] if col.top_values else [],
            })

        elif col.dtype_group == "datetime":
            entry.update({
                "min_date": col.min_date,
                "max_date": col.max_date,
                "date_range_days": col.date_range_days,
            })

        elif col.dtype_group == "boolean":
            entry.update({
                "true_rate": col.true_rate,
            })

        columns_context[name] = entry

    return {
        "total_rows": profile.total_rows,
        "total_columns": profile.total_columns,
        "duplicate_rows": profile.duplicate_rows,
        "sampled": profile.sampled,
        "columns": columns_context,
    }


def build_preprocessing_prompt(profile_context: dict) -> list[dict[str, str]]:
    """전처리 제안 프롬프트 생성.

    tree_model/distance_model 양쪽 전략을 한 번에 요청하여
    LLM 호출 1회로 전 모델 전략을 수령한다.

    Returns
    -------
    list[dict] : [{"role": "system", ...}, {"role": "user", ...}]
    """
    system_prompt = _build_system_prompt()
    user_prompt = _build_user_prompt(profile_context)
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _build_system_prompt() -> str:
    """시스템 프롬프트 — 전처리 전략 추천 규칙."""
    return """당신은 감사 데이터 전처리 전문가입니다.
EDA 프로파일링 결과를 분석하여 최적의 전처리 전략을 추천하세요.

## 추천 규칙 (참고용 — 데이터 특성에 따라 유연하게 판단)

### 결측치 대체 (imputer)
- 수치형: is_highly_skewed=true이면 "median", 아니면 "mean"
- 범주형: "most_frequent"
- datetime: "forward_fill"
- boolean: "most_frequent"

### 인코딩 (encoder)
- is_high_cardinality=true이면 "target" (차원 폭발 방지)
- 카디널리티 낮으면 "ordinal"
- boolean/수치형/datetime: "passthrough"

### 스케일링 + 이상치 (모델 그룹별)
tree_model (XGBoost 등 트리 기반):
- scaler: "none" (트리 모델은 스케일 불변)
- outlier: "none" (트리 모델은 이상치에 강건)

distance_model (VAE, Isolation Forest 등 거리/분포 기반):
- scaler: has_many_outliers=true이면 "robust", 아니면 "standard"
- outlier: |skewness| > 3이면 "log", outlier_rate > 10%이면 "clip"

### 불균형 대응 (imbalance)
- 감사 데이터 이상 비율이 5% 미만이면 "smote"
- 5~20%이면 "class_weight"
- 그 외: "none"

## 출력 형식
반드시 지정된 JSON Schema 형식으로 답하세요.
각 컬럼에 대해 tree_model과 distance_model 전략을 분리하여 제시하세요.
*_reason 필드에 추천 근거를 간결하게 한국어로 작성하세요."""


def _build_user_prompt(profile_context: dict) -> str:
    """유저 프롬프트 — EDA 프로파일 데이터 주입."""
    profile_json = json.dumps(profile_context, ensure_ascii=False, indent=2)

    return f"""## 데이터 개요
- 행: {profile_context['total_rows']:,}
- 컬럼: {profile_context['total_columns']}
- 중복행: {profile_context['duplicate_rows']:,}
- 샘플링 여부: {profile_context['sampled']}

## 컬럼별 EDA 프로파일
```json
{profile_json}
```

위 EDA 결과를 분석하여 컬럼별 전처리 전략을 추천하세요.
tree_model(XGBoost)과 distance_model(VAE/IF) 전략을 분리하여 답하세요."""
