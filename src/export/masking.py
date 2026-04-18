"""WU-24 PII 마스킹 — 작성자/승인자 SHA-256 해싱 + 보조계정 부분 치환.

Why:
    데이터분석 보고서를 외부에 공유할 때 개인 식별 정보(작성자/승인자 ID,
    보조계정의 거래처 코드 등)를 그대로 노출하면 K-PIPA 등 개인정보 보호
    이슈가 발생한다. 보고서 원본은 보존하고 사본에만 마스킹을 적용한다.

마스킹 정책:
    - hash:    SHA-256 앞 8자리 hex (충돌 가능성 ~10^-5, 보고서 식별 목적엔 충분)
    - partial: 뒤 4자리만 노출, 앞을 ``****`` 로 치환
"""

from __future__ import annotations

import hashlib

import pandas as pd

from src.export.models import MASK_TARGETS

# Why: 빈/None 값에도 일관된 결과를 보장하기 위한 sentinel.
_EMPTY_HASH: str = "--------"
_EMPTY_PARTIAL: str = "****"


def mask_dataframe(
    df: pd.DataFrame,
    columns: dict[str, str] | None = None,
) -> pd.DataFrame:
    """DataFrame **복사본**에 PII 마스킹을 적용한다.

    Args:
        df: 원본 DataFrame. 호출 후에도 변경되지 않는다.
        columns: ``{컬럼명: "hash" | "partial"}`` 매핑. None이면 :data:`MASK_TARGETS` 사용.

    Returns:
        마스킹된 컬럼이 치환된 새 DataFrame.

    Why:
        원본 불변 보장은 보고서 다운로드 후 대시보드의 다른 시각화가
        마스킹된 데이터로 오염되는 사고를 막는다. (Streamlit session_state 공유)
    """
    targets = columns if columns is not None else MASK_TARGETS

    # Why: 적용 대상 컬럼이 하나도 없으면 사본만 반환 (원본 참조 전달 방지).
    applicable = {col: how for col, how in targets.items() if col in df.columns}
    if not applicable:
        return df.copy()

    masked = df.copy()
    for col, how in applicable.items():
        if how == "hash":
            masked[col] = _hash_column(masked[col])
        elif how == "partial":
            masked[col] = _partial_mask(masked[col])
        else:
            raise ValueError(f"unknown mask method: {how!r} for column {col!r}")
    return masked


def _hash_column(series: pd.Series) -> pd.Series:
    """SHA-256 해시의 앞 8자리 hex로 치환한다."""

    def _hash_value(v: object) -> str:
        # Why: NaN/None/"" 모두 식별 불가 → 동일 sentinel로 통일.
        if pd.isna(v) or v == "" or v is None:
            return _EMPTY_HASH
        encoded = str(v).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()[:8]

    return series.map(_hash_value).astype("string")


def _partial_mask(series: pd.Series, visible: int = 4) -> pd.Series:
    """뒤 ``visible``자리만 보존, 앞을 ``****``로 치환한다."""

    def _mask_value(v: object) -> str:
        if pd.isna(v) or v == "" or v is None:
            return _EMPTY_PARTIAL
        s = str(v)
        if len(s) <= visible:
            # Why: 원본이 너무 짧으면 마스킹할 의미가 없으므로 통째로 ****.
            return _EMPTY_PARTIAL
        return "****" + s[-visible:]

    return series.map(_mask_value).astype("string")
