"""LLM 전처리 제안 오케스트레이터 — EDAProfile → 전처리 추천 → Pipeline 옵션 변환.

Why: Ollama Structured Output(JSON Schema 강제)으로 LLM 응답 신뢰성을 확보하고,
Ollama 미실행 시 rule_based_fallback으로 graceful degradation한다.
tree_model/distance_model 분기로 1회 LLM 호출에 전 모델 전략을 수령한다.
"""

from __future__ import annotations

import json
import logging
from typing import Literal

from config.settings import get_settings
from src.eda.models import EDAProfile
from src.llm.models import (
    ColumnPreprocessing,
    EncoderStrategy,
    ImbalanceStrategy,
    ImputerStrategy,
    ModelGroupStrategy,
    OutlierStrategy,
    PreprocessingAdvice,
    ScalerStrategy,
)
from src.llm.ollama_client import OllamaClient
from src.llm.prompt_templates import build_preprocessing_prompt, profile_to_llm_context

logger = logging.getLogger(__name__)

_MAX_RETRIES = 1  # Structured Output으로 1회 재시도면 충분


class PreprocessingAdvisor:
    """LLM 기반 전처리 전략 추천기.

    Ollama 미실행 시 규칙 기반 폴백 자동 전환.
    """

    def __init__(self, client: OllamaClient | None = None) -> None:
        self.client = client or OllamaClient()

    def advise(self, profile: EDAProfile) -> PreprocessingAdvice:
        """EDAProfile → 전처리 추천.

        1. LLM 가용 → Structured Output → Pydantic 검증
        2. 검증 실패 → 실패 응답 피드백 후 1회 재시도 → rule_based_fallback
        3. LLM 불가 → rule_based_fallback + warning 로그
        """
        if not self.client.is_available():
            logger.warning("Ollama 미실행 — 규칙 기반 폴백으로 전환")
            return self.rule_based_fallback(profile)

        profile_context = profile_to_llm_context(profile)
        messages = build_preprocessing_prompt(profile_context)
        schema = PreprocessingAdvice.model_json_schema()
        raw_response = ""

        for attempt in range(_MAX_RETRIES + 1):
            try:
                raw_response = self.client.chat(
                    messages=messages,
                    format=schema,
                )
                parsed = json.loads(raw_response)
                advice = PreprocessingAdvice(**parsed)
                advice.source = "llm"
                logger.info("LLM 전처리 제안 성공 (시도 %d/%d)", attempt + 1, _MAX_RETRIES + 1)
                return advice
            except Exception as exc:
                logger.warning(
                    "LLM 응답 파싱 실패 (시도 %d/%d): %s",
                    attempt + 1,
                    _MAX_RETRIES + 1,
                    exc,
                )
                # 재시도 시 실패 응답을 피드백으로 추가 (자기 수정 유도)
                if attempt < _MAX_RETRIES:
                    messages = messages + [
                        {"role": "assistant", "content": raw_response},
                        {"role": "user", "content": "응답이 JSON Schema에 맞지 않습니다. 다시 시도하세요."},
                    ]

        logger.warning("LLM 재시도 소진 — 규칙 기반 폴백으로 전환")
        return self.rule_based_fallback(profile)

    def rule_based_fallback(self, profile: EDAProfile) -> PreprocessingAdvice:
        """규칙 기반 폴백 — LLM 없이도 합리적 기본값 제공.

        03a-preprocessing.md §② 테이블의 조건을 코드화.
        판정 기준은 settings.py heuristic_* 설정 참조.
        """
        settings = get_settings()
        columns: list[ColumnPreprocessing] = []

        for name, col in profile.columns.items():
            # 결측치 전략
            imputer = _rule_imputer(col.dtype_group, col.skewness, settings)

            # 인코딩 전략
            encoder = _rule_encoder(col.dtype_group, col.cardinality, settings)

            # 모델 그룹별 스케일링/이상치 전략
            outlier_rate = (
                col.outlier_count / profile.total_rows
                if col.outlier_count and profile.total_rows > 0
                else 0.0
            )
            tree_strategy = _rule_tree_strategy()
            distance_strategy = _rule_distance_strategy(
                col.dtype_group, col.skewness, outlier_rate, settings,
            )

            columns.append(ColumnPreprocessing(
                column=name,
                dtype_group=col.dtype_group,
                imputer=imputer,
                encoder=encoder,
                tree_model=tree_strategy,
                distance_model=distance_strategy,
            ))

        imbalance, imbalance_reason = _rule_imbalance(settings)

        return PreprocessingAdvice(
            columns=columns,
            imbalance=imbalance,
            imbalance_reason=imbalance_reason,
            general_notes=["규칙 기반 폴백 — LLM 미사용"],
            source="rule_based",
        )

    def to_pipeline_config(
        self,
        advice: PreprocessingAdvice,
        model_group: Literal["tree", "distance"] = "tree",
    ) -> dict:
        """PreprocessingAdvice → sklearn Pipeline 구성 dict.

        Parameters
        ----------
        advice : 전처리 추천 결과
        model_group : "tree" (XGBoost) | "distance" (VAE/IF)

        Returns
        -------
        dict : Pipeline 빌더가 소비할 구성 정보

        Raises
        ------
        ValueError : model_group이 "tree" 또는 "distance"가 아닌 경우
        """
        if model_group not in ("tree", "distance"):
            raise ValueError(f"model_group은 'tree' 또는 'distance'만 허용: {model_group!r}")

        numeric_cols: list[str] = []
        categorical_cols: list[str] = []
        datetime_cols: list[str] = []
        boolean_cols: list[str] = []

        imputers: dict[str, str] = {}
        encoders: dict[str, str] = {}
        scalers: dict[str, str] = {}
        outlier_strategies: dict[str, str] = {}

        for col in advice.columns:
            # 타입별 컬럼 분류
            group_map = {
                "numeric": numeric_cols,
                "categorical": categorical_cols,
                "datetime": datetime_cols,
                "boolean": boolean_cols,
            }
            target_list = group_map.get(col.dtype_group)
            if target_list is not None:
                target_list.append(col.column)

            # imputer/encoder는 모델 그룹 무관
            imputers[col.column] = col.imputer.value
            encoders[col.column] = col.encoder.value

            # scaler/outlier는 모델 그룹별 분기
            strategy = col.tree_model if model_group == "tree" else col.distance_model
            scalers[col.column] = strategy.scaler.value
            outlier_strategies[col.column] = strategy.outlier.value

        return {
            "numeric_cols": numeric_cols,
            "categorical_cols": categorical_cols,
            "datetime_cols": datetime_cols,
            "boolean_cols": boolean_cols,
            "imputers": imputers,
            "encoders": encoders,
            "scalers": scalers,
            "outlier_strategies": outlier_strategies,
            "imbalance": advice.imbalance.value,
            "model_group": model_group,
            "source": advice.source,
        }


# ── 규칙 기반 헬퍼 (private) ──


def _rule_imputer(
    dtype_group: str,
    skewness: float | None,
    settings,
) -> ImputerStrategy:
    """dtype_group + 왜도 기반 결측치 전략 결정."""
    if dtype_group == "numeric":
        if skewness is not None and abs(skewness) > settings.heuristic_skewness_threshold:
            return ImputerStrategy.MEDIAN
        return ImputerStrategy.MEAN
    if dtype_group == "datetime":
        return ImputerStrategy.FORWARD_FILL
    # categorical, boolean
    return ImputerStrategy.MOST_FREQUENT


def _rule_encoder(
    dtype_group: str,
    cardinality: int | None,
    settings,
) -> EncoderStrategy:
    """dtype_group + 카디널리티 기반 인코딩 전략 결정."""
    if dtype_group != "categorical":
        return EncoderStrategy.PASSTHROUGH
    if cardinality is not None and cardinality > settings.heuristic_high_cardinality_threshold:
        return EncoderStrategy.TARGET
    return EncoderStrategy.ORDINAL


def _rule_tree_strategy() -> ModelGroupStrategy:
    """트리 모델 — 스케일링/이상치 불필요."""
    return ModelGroupStrategy(
        scaler=ScalerStrategy.NONE,
        scaler_reason="트리 모델은 스케일 불변",
        outlier=OutlierStrategy.NONE,
        outlier_reason="트리 모델은 이상치에 강건",
    )


def _rule_distance_strategy(
    dtype_group: str,
    skewness: float | None,
    outlier_rate: float,
    settings,
) -> ModelGroupStrategy:
    """거리/분포 기반 모델 — 데이터 특성에 따른 스케일링/이상치 전략."""
    if dtype_group != "numeric":
        return ModelGroupStrategy(
            scaler=ScalerStrategy.NONE,
            outlier=OutlierStrategy.NONE,
        )

    # 스케일링
    if outlier_rate > settings.heuristic_outlier_rate_threshold:
        scaler = ScalerStrategy.ROBUST
        scaler_reason = f"이상치 비율 {outlier_rate:.1%} — RobustScaler 권장"
    else:
        scaler = ScalerStrategy.STANDARD
        scaler_reason = "StandardScaler 기본 적용"

    # 이상치 — log 변환 임계값은 imputer 분기(2.0)보다 높은 3.0 사용
    # Why: log-normal 분포 경험칙에서 |skewness| > 3은 극심한 비대칭을 의미
    outlier = OutlierStrategy.NONE
    outlier_reason = ""
    if skewness is not None and abs(skewness) > settings.heuristic_log_skewness_threshold:
        outlier = OutlierStrategy.LOG
        outlier_reason = f"|skewness|={abs(skewness):.1f} — log1p 변환 권장"
    elif outlier_rate > settings.heuristic_outlier_rate_threshold:
        outlier = OutlierStrategy.CLIP
        outlier_reason = f"이상치 비율 {outlier_rate:.1%} — IQR 클리핑 권장"

    return ModelGroupStrategy(
        scaler=scaler,
        scaler_reason=scaler_reason,
        outlier=outlier,
        outlier_reason=outlier_reason,
    )


def _rule_imbalance(settings) -> tuple[ImbalanceStrategy, str]:
    """불균형 대응 전략 결정.

    Why: rule_based_fallback에서는 레이블 비율 정보가 없으므로
    heuristic_imbalance_threshold 기준으로 보수적으로 CLASS_WEIGHT 적용.
    """
    threshold = settings.heuristic_imbalance_threshold
    return (
        ImbalanceStrategy.CLASS_WEIGHT,
        f"감사 데이터 이상 비율 {threshold:.0%} 미만 기본 가정 — class_weight 적용",
    )
