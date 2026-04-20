"""접근감사/감사추적 룰 — AL1-01, AL1-02, AL1-03, AL3-01.

AL1-01: 전표 수정/삭제 이력 (KLCA IT 변경관리 4.3~4.5)
AL1-02: IP 비정상 접근 (스켈레톤 — ip_address 컬럼 추가 후 구현)
AL1-03: 전표번호 연속성 갭 (감사기준서 240/315호)
AL3-01: 승인 프로세스 검증 (감사기준서 315/330호 ITGC)
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def aa01_document_modification(
    df: pd.DataFrame,
    change_log_df: pd.DataFrame | None = None,
    *,
    watched_fields: tuple[str, ...] = ("line_text", "header_text"),
    high_amount_quantile: float = 0.90,
) -> pd.Series:
    """AL1-01 전표 수정이력 이상: change_log 사전 집계 → 1:1 병합 → 서브 신호 가중합.

    Why: KLCA IT 체크리스트 4.3~4.5 — 전기 후 적요/금액 수정은 조작 가능성.
         1:N 행 폭발 방어를 위해 merge 전 document_id 단위 사전 집계 필수.

    서브 신호 (가중합 0.0~1.0):
      S1(0.4): 기말 + 감시 대상 필드 수정 → 결산 조정 의심
      S2(0.4): created_by ≠ changed_by + 고액(Q90) → 무단 수정 의심
      S3(0.2): 동일 전표 수정 3회 이상 → 빈번 수정
    """
    if change_log_df is None or change_log_df.empty:
        return pd.Series(0.0, index=df.index)

    # Why: change_log 최소 필수 컬럼 검증 — ERP 데이터 연결 시 스키마 차이 방어
    if "document_id" not in change_log_df.columns or "changed_field" not in change_log_df.columns:
        return pd.Series(0.0, index=df.index)

    # Why: 1:N 행 폭발 방어 — document_id 단위로 사전 집계하여 1:1 병합
    agg_kwargs: dict = {
        "change_count": ("document_id", "count"),
        "changed_fields": ("changed_field", lambda x: frozenset(x.dropna())),
    }
    if "changed_by" in change_log_df.columns:
        agg_kwargs["last_changed_by"] = ("changed_by", "last")

    agg = change_log_df.groupby("document_id", sort=False).agg(**agg_kwargs).reset_index()

    merged = df.merge(agg, on="document_id", how="left")
    has_change = merged["change_count"].notna() & (merged["change_count"] > 0)

    score = pd.Series(0.0, index=df.index)

    # S1: 기말 + 감시 대상 필드 수정
    if "is_period_end" in df.columns:
        watched = frozenset(watched_fields)
        field_match = merged["changed_fields"].apply(
            lambda fs: bool(fs & watched) if isinstance(fs, frozenset) else False
        )
        s1 = has_change & field_match & df["is_period_end"].fillna(False)
        score = score + s1.astype(float) * 0.4

    # S2: 무단 수정 (타인 수정 + 고액)
    if "created_by" in df.columns and "last_changed_by" in merged.columns:
        diff_user = (
            has_change
            & merged["last_changed_by"].notna()
            & (merged["last_changed_by"] != df["created_by"])
        )
        base = df[["debit_amount", "credit_amount"]].fillna(0).max(axis=1)
        threshold = base.quantile(high_amount_quantile)
        s2 = diff_user & (base > threshold)
        score = score + s2.astype(float) * 0.4

    # S3: 빈번 수정 (3회 이상)
    s3 = has_change & (merged["change_count"] > 2)
    score = score + s3.astype(float) * 0.2

    return score.clip(upper=1.0)


def aa02_abnormal_ip_access(df: pd.DataFrame, **kwargs) -> pd.Series:
    """AL1-02 IP 비정상 접근 — 스켈레톤 (ip_address 컬럼 추가 후 구현).

    Why: KLCA IT 체크리스트 — 사용자별 평소 IP 풀 대비 이탈 IP 탐지.
         현재 GL 테이블에 ip_address 컬럼 미존재 (DataSynth Rust 확장 필요).
    """
    if "ip_address" not in df.columns:
        return pd.Series(0.0, index=df.index)
    # TODO: DataSynth ip_address 컬럼 생성 후 구현
    # S1: 사용자별 최빈 IP 대역 이탈
    # S2: 외부 IP(203.x.x.x) + 고액
    # S3: 심야 + VPN + 고액 → 가중
    return pd.Series(0.0, index=df.index)


def aa03_document_number_gap(
    df: pd.DataFrame,
    *,
    exclude_doc_types: tuple[str, ...] = ("ST", "MG"),
) -> pd.Series:
    """AL1-03 전표번호 연속성 갭: 파티션별 번호 갭 탐지.

    Why: 감사기준서 240§32, 315호 — 전표번호 누락은 삭제/은닉 의심.
         SAP 번호는 선행0/알파벳 혼합 가능 → 정규식으로 숫자 추출 후 변환.

    로직:
      1. (company_code, fiscal_year, document_type)별 파티션
      2. 파티션 내 번호 정렬 → 인접 차이(gap) 계산
      3. gap > 1인 행 플래그 (갭 직전 행)
      4. exclude_doc_types 제외 (취소/마이그레이션)
    """
    if "document_number" not in df.columns:
        return pd.Series(0.0, index=df.index)

    # Why: SAP 전표번호는 선행0("00100005432") 또는 알파벳 혼합("RV-10293") 가능
    numeric = df["document_number"].astype(str).str.extract(r"(\d+)", expand=False)
    numeric = pd.to_numeric(numeric, errors="coerce")

    if numeric.isna().all():
        return pd.Series(0.0, index=df.index)

    # Why: exclude_doc_types에 해당하는 전표유형은 갭 적법 사유 (취소/마이그레이션)
    if "document_type" in df.columns and exclude_doc_types:
        exclude_mask = df["document_type"].isin(exclude_doc_types)
    else:
        exclude_mask = pd.Series(False, index=df.index)

    # Why: 파티션 그룹핑 — 회사코드+연도+유형별 독립 번호범위
    group_cols = [c for c in ("company_code", "fiscal_year", "document_type")
                  if c in df.columns]
    if not group_cols:
        group_cols = ["document_type"] if "document_type" in df.columns else []

    score = pd.Series(0.0, index=df.index)
    work = df.assign(_numeric=numeric, _exclude=exclude_mask)
    valid = work["_numeric"].notna() & ~work["_exclude"]

    if not valid.any():
        return score

    if group_cols:
        groups = work[valid].groupby(group_cols, sort=False)
    else:
        groups = [(None, work[valid])]

    for _key, grp in groups:
        if len(grp) < 2:
            continue
        sorted_grp = grp.sort_values("_numeric")
        gaps = sorted_grp["_numeric"].diff().iloc[1:]  # 첫 행 NaN 제외
        # Why: diff()는 현재행-이전행 → gap > 1인 행이 번호 건너뜀 직후 행
        gap_rows = gaps[gaps > 1]
        for idx, gap_size in gap_rows.items():
            # Why: 갭 크기에 비례한 점수 (cap 1.0). gap=2→0.2, gap=10→1.0
            if idx in score.index:
                score.at[idx] = min(gap_size / 10.0, 1.0)

    return score


def _required_level(amount: float, thresholds: list[int]) -> int:
    """금액에 필요한 최소 승인 레벨 계산 (전결규정 6단계)."""
    for i, t in enumerate(thresholds):
        if amount <= t:
            return i + 1
    return len(thresholds) + 1


def aa04_approval_process(
    df: pd.DataFrame,
    *,
    approval_thresholds: list[int] | None = None,
    max_delay_days: int = 3,
) -> pd.Series:
    """AL3-01 승인 프로세스 검증: 누락+지연+레벨 건너뜀 3중 검증.

    Why: 감사기준서 315/330호 — ITGC 통제 테스트(TOE).
         기존 L1-07(bool 승인생략)를 float 연속 점수로 정밀화.

    서브 신호 (가중합 0.0~1.0):
      S1(0.4): 고액 + 승인자 부재 + 비자동 → 승인 누락
      S2(0.3): 승인일 - 전기일 > N일 → 승인 지연
      S3(0.3): approval_level < required_level(금액) → 레벨 건너뜀
    """
    if approval_thresholds is None:
        approval_thresholds = [
            10_000_000, 100_000_000, 1_000_000_000,
            5_000_000_000, 10_000_000_000, 50_000_000_000,
        ]

    score = pd.Series(0.0, index=df.index)
    base = df[["debit_amount", "credit_amount"]].fillna(0).max(axis=1)
    min_amount = approval_thresholds[0]  # Level 1 이하는 자동승인 범위

    # Why: automated_system 제외 — 시스템 자동 전기는 인간 승인 대상 아님
    if "user_persona" in df.columns:
        human = df["user_persona"].fillna("") != "automated_system"
    else:
        human = pd.Series(True, index=df.index)

    # S1: 승인 누락 — 고액 + 승인자 부재 + 비자동
    if "approved_by" in df.columns:
        no_approval = df["approved_by"].isna() | (df["approved_by"].astype(str).str.strip() == "")
        s1 = human & no_approval & (base > min_amount)
        score = score + s1.astype(float) * 0.4

    # S2: 승인 지연 — approval_date - posting_date > N일
    if "approval_date" in df.columns and "posting_date" in df.columns:
        a_date = pd.to_datetime(df["approval_date"], errors="coerce")
        p_date = pd.to_datetime(df["posting_date"], errors="coerce")
        delay_days = (a_date - p_date).dt.days
        # Why: 지연 비례 점수 (max_delay=3일 → 0.3, 6일 → 0.3)
        delayed = human & delay_days.notna() & (delay_days > max_delay_days)
        score = score + delayed.astype(float) * 0.3

    # S3: 레벨 건너뜀 — approval_level < required_level(금액)
    if "approval_level" in df.columns:
        required = base.apply(lambda amt: _required_level(amt, approval_thresholds))
        actual = pd.to_numeric(df["approval_level"], errors="coerce").fillna(0).astype(int)
        # Why: 금액 > Level 1 이상이어야 레벨 검증 의미 있음
        level_skip = human & (base > min_amount) & (actual > 0) & (actual < required)
        score = score + level_skip.astype(float) * 0.3

    return score.clip(upper=1.0)
