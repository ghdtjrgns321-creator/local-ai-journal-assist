"""헤더 행 자동 탐지 모듈 — 구조적 스코어링 기반.

ERP마다 헤더 위치가 다르므로(1행/3행/5행 등),
데이터 구조 신호(타입 다양성, 고유값, null 밀도) + 키워드 보조로 자동 탐지한다.

공식: Confidence = TypeDiversity×0.35 + Uniqueness×0.25 + NullDensity×0.15
                 + KeywordScore×0.15 + StringRatio×0.10
"""

from __future__ import annotations

import pandas as pd

from config.settings import get_keywords, get_settings
from src.ingest._header_scoring import (
    null_density_score,
    type_diversity_score,
    uniqueness_score,
)
from src.ingest.models import HeaderDetectionResult, ReadResult


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
) -> str:
    """신뢰도 3단계 분기 메시지 생성.

    >= 0.7: 자동 패스 (높은 확신)
    0.3~0.7: UI 경고 (추정은 하지만 확인 필요)
    < 0.3: 자동화 중단 (수동 입력 대기)
    """
    if header_row is None:
        return "헤더를 찾기 어렵습니다. 사용자가 직접 헤더 행을 지정해 주세요."

    pct = round(confidence * 100)
    kw_str = ", ".join(matched)
    row_display = header_row + 1  # 0-based → 1-based 사용자 표시

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
    if best_confidence < settings.min_header_confidence:
        best_row = None
        best_matched = []

    total_cols = len(sheet_data.columns)
    message = _build_message(best_row, best_confidence, best_matched)

    return HeaderDetectionResult(
        header_row=best_row,
        confidence=best_confidence,
        matched_keywords=best_matched,
        total_columns=total_cols,
        message=message,
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
