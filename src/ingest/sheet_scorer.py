"""시트 품질 스코어링 — 멀티시트 Excel에서 데이터 시트를 자동 추천.

Why: 실무 Excel은 메모/표지/요약 시트가 섞여 있어
단순 active_sheet 선택이 오탐을 유발한다.
행 수 + 열 수 + 헤더 신뢰도를 가중 합산하여 데이터 시트를 추천한다.

가중치: row_norm * 0.3 + col_norm * 0.2 + header_confidence * 0.5
"""

from __future__ import annotations

import pandas as pd

from src.ingest.models import HeaderDetectionResult, ReadResult, SheetScore

# 스코어 가중치
_W_ROW = 0.3
_W_COL = 0.2
_W_HEADER = 0.5


def _count_non_empty_rows(df: pd.DataFrame) -> int:
    """빈 행(전체 NaN) 제외 실제 행 수."""
    return int((~df.isna().all(axis=1)).sum())


def _count_non_empty_cols(df: pd.DataFrame) -> int:
    """비어있지 않은 열 수 (전체 NaN 열 제외)."""
    return int((~df.isna().all(axis=0)).sum())


def score_sheets(
    read_result: ReadResult,
    header_results: dict[str, HeaderDetectionResult],
) -> list[SheetScore]:
    """각 시트의 품질 스코어를 계산하여 내림차순 정렬 반환.

    Args:
        read_result: read_file() 결과.
        header_results: detect_headers() 결과 {시트명: HeaderDetectionResult}.

    Returns:
        SheetScore 리스트 (total_score 내림차순).
        최고 점수 1개만 recommended=True. 동점 시 active_sheet 우선.
    """
    raw_scores: list[dict] = []

    for sheet_name, raw_df in read_result.raw_data.items():
        row_count = _count_non_empty_rows(raw_df)
        col_count = _count_non_empty_cols(raw_df)

        header_result = header_results.get(sheet_name)
        header_conf = header_result.confidence if header_result else 0.0

        raw_scores.append(
            {
                "sheet_name": sheet_name,
                "row_count": row_count,
                "col_count": col_count,
                "header_confidence": header_conf,
            }
        )

    # 정규화 기준값 (전체 시트 중 최대)
    max_rows = max((s["row_count"] for s in raw_scores), default=1) or 1
    max_cols = max((s["col_count"] for s in raw_scores), default=1) or 1

    # 가중 합산 스코어 계산
    scored: list[SheetScore] = []
    for s in raw_scores:
        row_norm = s["row_count"] / max_rows
        col_norm = s["col_count"] / max_cols
        total = row_norm * _W_ROW + col_norm * _W_COL + s["header_confidence"] * _W_HEADER

        # 빈 DataFrame → 강제 0점
        if s["row_count"] == 0 and s["col_count"] == 0:
            total = 0.0

        scored.append(
            SheetScore(
                sheet_name=s["sheet_name"],
                row_count=s["row_count"],
                col_count=s["col_count"],
                header_confidence=s["header_confidence"],
                total_score=round(total, 4),
                recommended=False,  # 아래에서 설정
            )
        )

    # total_score 내림차순 정렬
    scored.sort(key=lambda x: x.total_score, reverse=True)

    # 최고 점수 시트 추천 — 동점 시 active_sheet 우선
    if scored:
        top_score = scored[0].total_score
        top_candidates = [s for s in scored if s.total_score == top_score]

        if len(top_candidates) > 1:
            # 동점: active_sheet가 있으면 우선
            for s in top_candidates:
                if s.sheet_name == read_result.active_sheet:
                    s.recommended = True
                    break
            else:
                # active_sheet가 동점 후보에 없으면 첫 번째
                top_candidates[0].recommended = True
        else:
            top_candidates[0].recommended = True

    return scored
