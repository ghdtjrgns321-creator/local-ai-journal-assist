"""LLM 기반 컬럼 매핑 추천 — Ollama + Qwen3-8B.

샘플 데이터를 LLM에 보내 표준 컬럼명을 추천받는다.
헤더가 없거나 fuzzy match가 실패한 컬럼에 대해
데이터 의미를 이해하여 정확한 매핑을 제안한다.

Ollama 미실행 시 빈 dict 반환 (규칙 기반 폴백).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

_MODEL = "qwen3:8b"
# Why: Qwen3는 thinking mode가 기본 활성화되어 사고 과정에 ~3000토큰 사용.
#      num_predict가 작으면 thinking에 토큰을 다 쓰고 응답이 빈 문자열이 됨.
_NUM_PREDICT = 4096
_TIMEOUT = 60


def suggest_columns(
    data_df: pd.DataFrame,
    source_columns: list[str],
    standard_columns: list[str],
    column_labels: dict[str, str],
    *,
    n_sample: int = 5,
) -> dict[str, str]:
    """LLM으로 원본 컬럼 → 표준 컬럼 매핑을 추천한다.

    Args:
        data_df: 원본 데이터 (header=None 상태, 컬럼은 정수 인덱스).
        source_columns: 원본 컬럼명 리스트.
        standard_columns: 표준 컬럼명 리스트.
        column_labels: 표준 컬럼의 한글 라벨 맵.
        n_sample: 프롬프트에 포함할 샘플 행 수.

    Returns:
        {원본_컬럼명: 표준_컬럼명} dict.
        Ollama 미실행 또는 파싱 실패 시 빈 dict.
    """
    try:
        import ollama
    except ImportError:
        logger.info("ollama 패키지 미설치 — LLM 매핑 스킵")
        return {}

    prompt = _build_prompt(
        data_df, source_columns, standard_columns, column_labels, n_sample,
    )

    try:
        response = ollama.chat(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.1, "num_predict": _NUM_PREDICT},
        )
        content = response.message.content.strip()
        return _parse_response(
            content, source_columns, standard_columns, column_labels,
        )

    except Exception as exc:
        logger.warning("LLM 매핑 실패 (폴백): %s", exc)
        return {}


def _build_prompt(
    data_df: pd.DataFrame,
    source_columns: list[str],
    standard_columns: list[str],
    column_labels: dict[str, str],
    n_sample: int,
) -> str:
    """LLM에 보낼 프롬프트를 구성한다."""
    # 표준 컬럼 목록 (영문키: 한글설명)
    std_list = []
    for col in standard_columns:
        label = column_labels.get(col, "")
        desc = f"{col}: {label}" if label else col
        std_list.append(desc)

    # 각 원본 컬럼의 샘플값
    column_info = []
    for i, src in enumerate(source_columns):
        if i < data_df.shape[1]:
            series = data_df.iloc[:, i].dropna().astype(str)
            samples = list(series.unique()[:n_sample])
        else:
            samples = []
        column_info.append(f"컬럼 '{src}': {samples}")

    columns_text = "\n".join(column_info)
    standards_text = ", ".join(std_list)

    return f"""회계 감사 데이터의 컬럼 매핑 작업이다.
아래 원본 데이터의 각 컬럼이 어떤 표준 컬럼에 해당하는지 JSON으로 답해라.

## 표준 컬럼 목록 (영문키: 한글설명)
{standards_text}

## 원본 데이터 컬럼별 샘플값
{columns_text}

## 규칙
- 각 원본 컬럼을 가장 적합한 표준 컬럼 1개에 매핑
- 매핑할 수 없으면 해당 컬럼을 결과에서 제외
- 하나의 표준 컬럼에 여러 원본 컬럼을 매핑하지 말 것
- JSON 키는 원본 컬럼명 그대로 (예: "0", "posting_date" 등)
- JSON 값은 반드시 표준 컬럼의 **영문키** (예: "document_id", "posting_date")

## 예시
원본 컬럼 "0"에 "JE2025-0001" 같은 전표번호가 있으면:
{{"0": "document_id"}}

JSON만 출력하고 다른 설명은 하지 마라:"""


def _parse_response(
    content: str,
    source_columns: list[str],
    standard_columns: list[str],
    column_labels: dict[str, str] | None = None,
) -> dict[str, str]:
    """LLM 응답을 파싱하여 유효한 매핑만 반환."""
    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        # JSON 블록 추출 시도
        if "{" in content and "}" in content:
            start = content.index("{")
            end = content.rindex("}") + 1
            try:
                result = json.loads(content[start:end])
            except json.JSONDecodeError:
                logger.warning("LLM 응답 JSON 파싱 실패: %s", content[:200])
                return {}
        else:
            return {}

    if not isinstance(result, dict):
        return {}

    # Why: LLM이 영문 키 대신 한글 라벨을 반환할 수 있으므로 역매핑 테이블 생성
    label_to_key: dict[str, str] = {}
    if column_labels:
        for key, label in column_labels.items():
            label_to_key[label] = key

    # 유효성 검증: 원본/표준 컬럼에 실제 존재하는 것만 반환
    src_set = set(source_columns)
    std_set = set(standard_columns)
    used_targets: set[str] = set()
    valid: dict[str, str] = {}

    for src, tgt in result.items():
        src_str = str(src)
        tgt_str = str(tgt)

        # 한글 라벨로 반환된 경우 영문 키로 변환
        if tgt_str not in std_set and tgt_str in label_to_key:
            tgt_str = label_to_key[tgt_str]

        if src_str in src_set and tgt_str in std_set and tgt_str not in used_targets:
            valid[src_str] = tgt_str
            used_targets.add(tgt_str)

    logger.info("LLM 매핑 결과: %d/%d 컬럼 매핑 성공", len(valid), len(source_columns))
    return valid


def is_available() -> bool:
    """Ollama + 모델이 사용 가능한지 확인."""
    try:
        import ollama
        models = ollama.list()
        return any(_MODEL.split(":")[0] in m.model for m in models.models)
    except Exception:
        return False
