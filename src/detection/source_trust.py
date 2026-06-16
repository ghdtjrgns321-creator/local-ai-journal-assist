"""source 신뢰 분류 — 자동 전표 식별과 위장(단독 자동) 의심 분리.

Why: 자동 결산 배치 전표는 승인 부재·결산기 집중·심야 전기가 정상이다. 이를 사람 행위
     전제의 fraud-combo floor가 조작 의심으로 승격하면 정상 medium 노이즈가 생긴다
     (v41 실측 3,516건 — OPEN_ISSUES #14). 반대로 source 필드를 무조건 믿으면
     "자동인 척하는 수기 전표"(위장)가 감시를 빠져나간다 (#16).
     해법: source가 자동 계열이어도 배치 정체성(batch/job id)도 같은 날 동류 무리도
     없는 단독 전표는 신뢰하지 않는다. v41 실측: 정상 자동 202,102 문서 중 단독성
     임계 10 기준 82건만 위장 의심 — 정상 자동 전표는 항상 무리지어 다닌다.
"""

from __future__ import annotations

import pandas as pd

# Why: L4-06(anomaly_rules_batch)의 배치 source 토큰과 정합 + recurring(반복 자동) 포함.
AUTOMATED_SOURCE_TOKENS = frozenset(
    {"batch", "interface", "system", "auto", "automated", "if", "sys", "recurring"}
)
DEFAULT_LONE_THRESHOLD = 10


def automated_source_mask(
    df: pd.DataFrame,
    *,
    source_tokens: frozenset[str] | set[str] | None = None,
) -> pd.Series:
    """source가 자동 계열인 행. source 컬럼 부재 시 전부 False.

    Why: 기본 토큰은 recurring 포함(floor 게이트용 — 반복 자동의 승인 부재는 정상).
         L4-06은 스펙상 recurring을 batch source로 보지 않으므로 자체 토큰을 전달한다.
    """
    if "source" not in df.columns:
        return pd.Series(False, index=df.index)
    tokens = source_tokens or AUTOMATED_SOURCE_TOKENS
    values = df["source"].astype("string").str.strip().str.lower()
    return values.isin(set(tokens)).fillna(False).astype(bool)


def lone_automated_mask(
    df: pd.DataFrame,
    *,
    lone_threshold: int = DEFAULT_LONE_THRESHOLD,
    source_tokens: frozenset[str] | set[str] | None = None,
) -> pd.Series:
    """위장 의심: 자동 계열 source인데 배치 정체성이 없고 같은 날 동류도 없는 단독 전표.

    조건 (모두 충족):
    1. source 자동 계열
    2. batch_id·job_id 모두 결측/공백 (컬럼이 둘 다 없으면 정체성 검증 불가 → 의심 없음)
    3. 같은 날 같은 조건(자동+정체성 없음)의 전표 수 ≤ lone_threshold
    """
    automated = automated_source_mask(df, source_tokens=source_tokens)
    if not automated.any():
        return pd.Series(False, index=df.index)

    identity_columns = [column for column in ("batch_id", "job_id") if column in df.columns]
    if not identity_columns:
        return pd.Series(False, index=df.index)
    no_identity = pd.Series(True, index=df.index)
    for column in identity_columns:
        values = df[column].astype("string").str.strip()
        no_identity &= values.isna() | values.eq("")

    if "posting_date" not in df.columns:
        return pd.Series(False, index=df.index)
    dates = pd.to_datetime(df["posting_date"], errors="coerce", format="ISO8601")
    # Why: NaT 날짜는 단독성 판정 불가 — candidates에서 제외해 "<NA>" 키가 무리로 묶이지 않게 함
    candidates = automated & no_identity & dates.notna()
    if not candidates.any():
        return pd.Series(False, index=df.index)

    # Why: 같은 날 동류 전표 수 — document_id가 있으면 전표 단위로 센다 (GL 다중 line 방지)
    day = dates.dt.date.astype("string")
    subset = df.loc[candidates]
    if "document_id" in df.columns:
        per_day = (
            pd.DataFrame({"day": day.loc[candidates], "doc": subset["document_id"]})
            .groupby("day")["doc"]
            .nunique()
        )
    else:
        per_day = day.loc[candidates].value_counts()
    lone_days = set(per_day.loc[per_day <= lone_threshold].index)
    return candidates & day.isin(lone_days).fillna(False)


def trusted_automated_mask(
    df: pd.DataFrame,
    *,
    lone_threshold: int = DEFAULT_LONE_THRESHOLD,
) -> pd.Series:
    """신뢰 가능한 자동 전표: 자동 계열이면서 위장 의심(단독 자동)이 아닌 행."""
    return automated_source_mask(df) & ~lone_automated_mask(df, lone_threshold=lone_threshold)
