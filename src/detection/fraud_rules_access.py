"""접근통제 기반 부정 탐지 룰 — B06, B07, B09, B10.

권장 컬럼(created_by, business_process, source, company_code) 의존.
해당 컬럼 미존재 시 Series(False) 반환 → 오케스트레이터가 warning 기록.
"""

from __future__ import annotations

import functools

import pandas as pd

from config.settings import get_audit_rules


@functools.lru_cache(maxsize=1)
def _get_manual_codes() -> tuple[str, ...]:
    """수기 전표 소스 코드 목록 (소문자 정규화). lru_cache로 스레드 안전."""
    rules = get_audit_rules()
    raw = rules.get("patterns", {}).get("manual_source_codes", ["SA", "Manual", "수기"])
    return tuple(c.lower() for c in raw)


def b06_self_approval(df: pd.DataFrame) -> pd.Series:
    """B06 자기 승인: 입력자 = 승인자 또는 수기 + 단일 사용자.

    Why: 외감법 §8①5호 — 업무 분장 위반.
         오스템임플란트(2021) 사례: 1인이 입력·승인·이체 전부 수행 → 2,215억 횡령.
    Case A: approved_by 존재 → created_by == approved_by
    Case B: approved_by 부재 → 수기 소스 + created_by 존재 = 자기 승인 추정
    """
    if "created_by" not in df.columns:
        return pd.Series(False, index=df.index)

    # Case A: approved_by 컬럼이 있으면 직접 비교
    if "approved_by" in df.columns:
        return (df["created_by"] == df["approved_by"]) & df["created_by"].notna()

    # Case B: approved_by 없으면 수기 전표 + 사용자 존재 = 자기 승인 추정
    if "source" in df.columns:
        is_manual = df["source"].astype(str).str.lower().isin(_get_manual_codes())
        return is_manual & df["created_by"].notna()

    return pd.Series(False, index=df.index)


def b07_segregation_of_duties(
    df: pd.DataFrame,
    sod_threshold: int = 3,
) -> pd.Series:
    """B07 직무분리 위반: 동일인이 N개 이상 프로세스에 관여.

    Why: K-SOX COSO 2013 — 직무분리는 내부통제의 핵심 원칙.
    알고리즘: 사용자별 프로세스 nunique 집계 → 위반자 목록 → isin으로 행 레벨 매핑.
    """
    required = ["created_by", "business_process"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return pd.Series(False, index=df.index)

    # Why: groupby.nunique()는 사용자 단위 → isin()으로 행 레벨 bool 변환
    counts = df.groupby("created_by")["business_process"].nunique()
    violators = counts[counts >= sod_threshold].index
    return df["created_by"].isin(violators)


def b09_skipped_approval(df: pd.DataFrame) -> pd.Series:
    """B09 승인 생략: 한도 초과 + 비자동 소스.

    Why: 외감법 §8② — 승인 절차 없이 처리된 한도 초과 전표는 내회관 우회.
    """
    if "exceeds_threshold" not in df.columns or "source" not in df.columns:
        return pd.Series(False, index=df.index)

    exceeds = df["exceeds_threshold"].fillna(False)
    # Why: 자동 처리(automated)는 시스템 통제 하에 있으므로 제외
    not_automated = df["source"].astype(str).str.lower() != "automated"
    return exceeds & not_automated


def b10_circular_intercompany(df: pd.DataFrame) -> pd.Series:
    """B10 관계사 거래 탐지 (MVP: GL prefix로 식별된 IC 전표를 flag).

    Why: 감사기준서 550호 §23 — 합리적 사업 근거 없는 특수관계자 거래.
    MVP 한계: IC 전용 GL 계정(채권/채무)에 해당하는 전표를 flag.
              실제 순환 탐지(n-hop)는 Phase 2 GraphDetector에서 수행.
    """
    if "is_intercompany" not in df.columns:
        return pd.Series(False, index=df.index)

    ic_mask = df["is_intercompany"].fillna(False)
    if not ic_mask.any():
        return pd.Series(False, index=df.index)

    # Why: company_code가 있으면 복수 회사 관여 여부로 추가 검증
    #      없어도 GL 기반 IC 전표는 flag (Phase 2 GraphDetector로 대체 예정)
    if "company_code" in df.columns:
        ic_companies = set(df.loc[ic_mask, "company_code"].dropna().unique())
        if len(ic_companies) < 2:
            return ic_mask

    return ic_mask
