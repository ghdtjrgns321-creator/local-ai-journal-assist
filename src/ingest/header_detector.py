"""헤더 행 자동 탐지 모듈 — 구조적 스코어링 기반.

ERP마다 헤더 위치가 다르므로(1행/3행/5행 등),
데이터 구조 신호(타입 다양성, 고유값, null 밀도) + 키워드 보조로 자동 탐지한다.

공식: Confidence = TypeDiversity×0.35 + Uniqueness×0.25 + NullDensity×0.15
                 + KeywordScore×0.15 + StringRatio×0.10

WU-28: 구조 스코어 < min_header_confidence(0.3)일 때 LLM(gpt-5.4-mini)에 재검증을
요청해 confidence를 보정한다. LLM 미가용/설정 off 시 기존 동작 그대로.
"""

from __future__ import annotations

import json
import logging

import pandas as pd

from config.settings import get_keywords, get_settings
from src.ingest._header_scoring import (
    null_density_score,
    type_diversity_score,
    uniqueness_score,
)
from src.ingest.models import HeaderDetectionResult, ReadResult

logger = logging.getLogger(__name__)

_LLM_CONTEXT_ROWS = 5       # LLM에 전달할 상위 행 수
_LLM_SYSTEM_PROMPT = (
    "너는 ERP 전표 원본에서 헤더 행(컬럼명 행)을 식별하는 감사 보조 역할이다. "
    "주어진 텍스트에서 지정된 [Row N] 행이 데이터 표의 헤더(컬럼명)인지, "
    "아니면 표지/메모/데이터 값 행인지 판단하라."
)


# ── 내부 헬퍼 ──────────────────────────────────────────────


def _build_keyword_map(keywords: dict) -> dict[str, str]:
    """keywords.yaml → {lowercase별칭: 원본표기} 매핑 생성.

    Why: 매칭 시 대소문자 무시하되, 결과 메시지에는 원본 표기를 보여주기 위함.
    """
    kw_map: dict[str, str] = {}
    for aliases in keywords.values():
        for alias in aliases:
            kw_map[alias.strip().lower()] = alias
    return kw_map


def _score_row(
    row: pd.Series,
    keyword_map: dict[str, str],
    min_expected: int,
    total_cols: int,
) -> tuple[float, list[str]]:
    """단일 행의 헤더 신뢰도를 5개 구조 신호로 계산.

    Returns:
        (confidence, matched_keywords_원본명)
    """
    valid_cells = row.dropna()

    # 빈 행 방어: 모든 셀이 NaN이면 스코어 0
    if len(valid_cells) == 0:
        return 0.0, []

    # 키워드 매칭 — 정확 일치(strip+lower)
    matched: list[str] = []
    string_count = 0
    for val in valid_cells:
        if isinstance(val, str):
            string_count += 1
            key = val.strip().lower()
            if key in keyword_map:
                matched.append(keyword_map[key])

    # 키워드 스코어: 매칭 수 / 최소 기대 헤더 수 (1.0 캡)
    keyword_score = min(len(matched) / min_expected, 1.0) if min_expected > 0 else 0.0

    # 문자열 비율: 헤더 행은 대부분 문자열
    string_ratio = string_count / len(valid_cells) if len(valid_cells) > 0 else 0.0

    # 구조적 신호 3개
    td_score = type_diversity_score(row)
    uq_score = uniqueness_score(row)
    nd_score = null_density_score(row, total_cols)

    # 5개 신호 가중 합산
    confidence = (
        td_score * 0.35
        + uq_score * 0.25
        + nd_score * 0.15
        + keyword_score * 0.15
        + string_ratio * 0.10
    )
    return confidence, matched


def _build_message(
    header_row: int | None,
    confidence: float,
    matched: list[str],
    llm_assisted: bool = False,
) -> str:
    """신뢰도 3단계 분기 메시지 생성.

    >= 0.7: 자동 패스 (높은 확신)
    0.3~0.7: UI 경고 (추정은 하지만 확인 필요)
    < 0.3: 자동화 중단 (수동 입력 대기)

    llm_assisted=True면 LLM 보조 탐지 출처를 메시지에 명시한다.
    """
    if header_row is None:
        return "헤더를 찾기 어렵습니다. 사용자가 직접 헤더 행을 지정해 주세요."

    pct = round(confidence * 100)
    kw_str = ", ".join(matched)
    row_display = header_row + 1  # 0-based → 1-based 사용자 표시

    # LLM 보조 경로는 구조/키워드 메시지와 분리 (출처 혼동 방지)
    if llm_assisted:
        if confidence >= 0.7:
            return (
                f"AI(LLM 보조)가 {row_display}번째 줄을 헤더로 인식했습니다. "
                f"(신뢰도 {pct}%)"
            )
        return (
            f"{row_display}번째 줄을 LLM 보조로 헤더로 추정하지만, 확신이 낮습니다. "
            f"확인해 주세요. (신뢰도 {pct}%)"
        )

    if confidence >= 0.7:
        if matched:
            return (
                f"AI가 {row_display}번째 줄을 헤더로 완벽히 인식했습니다. "
                f"(신뢰도 {pct}%, 매칭 키워드: {kw_str})"
            )
        return (
            f"AI가 {row_display}번째 줄을 데이터 구조 기반으로 헤더로 인식했습니다. "
            f"(신뢰도 {pct}%)"
        )
    if matched:
        return (
            f"{row_display}번째 줄을 헤더로 추정하지만, 확신이 낮습니다. "
            f"확인해 주세요. (신뢰도 {pct}%, 매칭 키워드: {kw_str})"
        )
    return (
        f"{row_display}번째 줄을 데이터 구조 기반으로 헤더로 추정합니다. "
        f"확인해 주세요. (신뢰도 {pct}%)"
    )


# ── LLM 보조 (WU-28) ───────────────────────────────────────


def _serialize_context(sheet_data: pd.DataFrame, max_rows: int = _LLM_CONTEXT_ROWS) -> str:
    """LLM 입력용 행 직렬화.

    환각 방지 2중 장치:
      1. fillna("") — pandas NaN → "nan" 텍스트가 실제 컬럼명으로 오해되는 사고 차단
      2. [Row N] 라벨 강제 — pandas 0-based 인덱스를 프롬프트·응답 공통 키로 고정
    """
    df_context = sheet_data.head(max_rows).fillna("")
    lines: list[str] = []
    for idx, row in df_context.iterrows():
        row_str = "\t".join(str(val).strip() for val in row.values)
        lines.append(f"[Row {idx}] {row_str}")
    return "\n".join(lines)


def _llm_header_check(
    sheet_data: pd.DataFrame,
    candidate_row: int,
    client,  # ChatClient Protocol — 순환 import 방지 위해 타입 힌트 제외
) -> float:
    """LLM에게 candidate_row가 헤더인지 재검증.

    Returns:
        보정 confidence (0.0~1.0). is_header=False면 0.0, 파싱 실패도 0.0.

    예외는 호출자(_try_llm_boost)가 흡수한다.
    """
    from src.llm.models import HeaderLLMResponse

    context = _serialize_context(sheet_data)
    user_prompt = (
        f"{context}\n\n"
        f"위 텍스트에서 [Row {candidate_row}]로 시작하는 행이 이 표의 헤더(컬럼명)인지 "
        "판단하라. 데이터 값이나 표지/메모 행이면 is_header=false로 응답하라. "
        "confidence는 판단 확신도(0.0~1.0), reason은 판단 근거 한 줄이다."
    )
    messages = [
        {"role": "system", "content": _LLM_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    schema = HeaderLLMResponse.model_json_schema()
    raw = client.chat(messages=messages, format=schema)
    parsed = json.loads(raw)
    response = HeaderLLMResponse(**parsed)

    if not response.is_header:
        logger.info(
            "LLM: Row %d 헤더 아님 (conf=%.2f, reason=%s)",
            candidate_row, response.confidence, response.reason,
        )
        return 0.0

    logger.info(
        "LLM: Row %d 헤더 확인 (conf=%.2f, reason=%s)",
        candidate_row, response.confidence, response.reason,
    )
    return response.confidence


def _try_llm_boost(sheet_data: pd.DataFrame, candidate_row: int) -> float | None:
    """LLM 보조를 시도하되 미가용/예외 시 None을 반환해 기존 폴백 경로로 유도.

    호출 조건: enable_llm_header_fallback=True + candidate_row is not None.
    """
    try:
        from src.llm.api_client import get_chat_client

        client = get_chat_client("light")
    except (RuntimeError, ImportError) as exc:
        # RuntimeError: 키 미설정 또는 연결 실패 (preprocessing_advisor와 동일 패턴)
        # ImportError: openai SDK 미설치
        logger.warning("LLM 헤더 보조 미가용 — 기존 폴백: %s", exc)
        return None

    try:
        return _llm_header_check(sheet_data, candidate_row, client)
    except json.JSONDecodeError as exc:
        # LLM이 Structured Output 스키마를 어기고 비JSON 응답을 돌려준 경우
        logger.warning("LLM 헤더 응답 JSON 파싱 실패 — 기존 폴백: %s", exc)
        return None
    except Exception as exc:
        # Pydantic ValidationError / 네트워크 오류 / 기타 SDK 예외 일괄 흡수
        logger.warning("LLM 헤더 보조 실패 — 기존 폴백: %s", exc)
        return None


# ── 공개 API ───────────────────────────────────────────────


def detect_header_row(
    sheet_data: pd.DataFrame,
    keywords: dict | None = None,
) -> HeaderDetectionResult:
    """단일 시트 DataFrame에서 헤더 행을 자동 탐지.

    Args:
        sheet_data: header=None으로 읽은 raw DataFrame
        keywords: keywords.yaml dict (None이면 자동 로드)
    """
    settings = get_settings()

    if keywords is None:
        keywords = get_keywords()

    # 빈 DataFrame → 즉시 실패
    if sheet_data.empty:
        return HeaderDetectionResult(
            header_row=None,
            confidence=0.0,
            matched_keywords=[],
            total_columns=0,
            message=_build_message(None, 0.0, []),
        )

    keyword_map = _build_keyword_map(keywords)
    scan_rows = min(len(sheet_data), settings.max_header_scan_rows)
    total_cols = len(sheet_data.columns)

    best_row: int | None = None
    best_confidence = 0.0
    best_matched: list[str] = []

    for idx in range(scan_rows):
        row = sheet_data.iloc[idx]
        confidence, matched = _score_row(
            row, keyword_map, settings.min_expected_headers, total_cols,
        )

        # 동점(>=) 시 상단 행 우선 → strict > 비교
        if confidence > best_confidence:
            best_confidence = confidence
            best_matched = matched
            best_row = idx

    # 최소 신뢰도 미달 → 실패
    # Why: 키워드 매칭 없이 구조적 신호만으로는 데이터 행과 헤더 행 구분이 어렵다.
    #      키워드 0개면 threshold를 0.7로 높여 거짓 양성을 방지한다.
    effective_threshold = settings.min_header_confidence
    if not best_matched:
        effective_threshold = max(effective_threshold, 0.7)

    # WU-28: 구조 스코어 미달 시 LLM 보조 판단으로 복원 시도.
    # 후보 행 자체가 없으면(best_row is None) LLM도 판단할 대상이 없으므로 스킵.
    # Why(대체 vs max): 구조 스코어는 형태 신호, LLM confidence는 의미 판단으로 축이 다르다.
    # max()로 섞으면 UI 메시지에서 "구조 기반 탐지 0.85" 같은 혼동된 출처가 생기므로,
    # LLM 가용 시에는 LLM 값을 직접 대체하고 llm_assisted 플래그로 출처를 분리한다.
    llm_assisted = False
    if (
        best_confidence < effective_threshold
        and best_row is not None
        and settings.enable_llm_header_fallback
    ):
        llm_confidence = _try_llm_boost(sheet_data, best_row)
        if llm_confidence is not None and llm_confidence > 0.0:
            best_confidence = llm_confidence
            llm_assisted = True

    if best_confidence < effective_threshold:
        best_row = None
        best_matched = []
        llm_assisted = False

    total_cols = len(sheet_data.columns)
    message = _build_message(best_row, best_confidence, best_matched, llm_assisted)

    return HeaderDetectionResult(
        header_row=best_row,
        confidence=best_confidence,
        matched_keywords=best_matched,
        total_columns=total_cols,
        message=message,
        llm_assisted=llm_assisted,
    )


def detect_headers(
    read_result: ReadResult,
    keywords: dict | None = None,
) -> dict[str, HeaderDetectionResult]:
    """멀티시트 퍼사드 — ReadResult 내 모든 시트를 한 번에 탐지.

    Returns:
        {시트명: HeaderDetectionResult}
        탐지 실패한 시트도 포함됨 (header_row=None으로 표시).
        호출자는 result.header_row is None 여부를 반드시 확인할 것.
    """
    if keywords is None:
        keywords = get_keywords()

    return {
        sheet_name: detect_header_row(df, keywords)
        for sheet_name, df in read_result.raw_data.items()
    }
