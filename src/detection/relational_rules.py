"""Relational 탐지 룰 함수 — WU-08 관계 기반 이상 탐지.

R01: 신규 거래처 대액 지급 (NewCounterparty)
R02: 휴면 계정 활동 (DormantAccountActivity)
R03: IC 이전가격 이상 (TransferPricingAnomaly)
R04: 문서 흐름 누락 (MissingRelationship)

Note: LAYER_WEIGHTS에 의도적 미등록 — 성능 평가 후 WU-03 Stacking에서 배분.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    import duckdb


# ── R01: 신규 거래처 대액 지급 ──────────────────────────────────


def r01_new_counterparty(
    df: pd.DataFrame,
    *,
    lookback_days: int = 90,
    large_quantile: float = 0.90,
) -> pd.Series:
    """신규 거래처(첫 등장 후 lookback 이내) + 대액 거래 탐지.

    Why: ISA 240 — 신규 거래처와의 비정상 대규모 거래는 가공거래 위험.
    """
    if df.empty or "trading_partner" not in df.columns or "posting_date" not in df.columns:
        return pd.Series(0.0, index=df.index)

    posting = pd.to_datetime(df["posting_date"], errors="coerce")
    tp = df["trading_partner"].fillna("")

    # Why: 빈 문자열 거래처는 판단 불가 → 제외
    valid_mask = tp != ""
    if not valid_mask.any():
        return pd.Series(0.0, index=df.index)

    # 거래처별 첫 등장일
    first_seen = posting.groupby(tp).transform("min")
    days_since_first = (posting - first_seen).dt.days
    is_new = valid_mask & (days_since_first <= lookback_days)

    # Why: 대액 판정 — valid_mask 행만으로 threshold 계산 (빈 거래처 금액이 왜곡 방지)
    amount = df[["debit_amount", "credit_amount"]].fillna(0).max(axis=1)
    threshold = amount[valid_mask].quantile(large_quantile)
    if threshold <= 0:
        return pd.Series(0.0, index=df.index)

    is_large = amount > threshold

    # Why: 연속 점수 — 금액이 클수록 높은 점수 (0.5~1.0)
    scores = pd.Series(0.0, index=df.index)
    mask = is_new & is_large
    scores[mask] = (amount[mask] / threshold).clip(upper=2.0) / 2.0

    return scores


# ── R02: 휴면 계정 활동 ────────────────────────────────────────


def r02_dormant_account_activity(
    df: pd.DataFrame,
    *,
    inactive_days: int = 180,
    reactivation_window_days: int = 7,
    min_amount: float = 0.0,
) -> pd.Series:
    """휴면 계정 재활성화 탐지 + 윈도우 내 후속 전표 연좌 플래깅.

    Why: PCAOB AS 2401 — 장기 미사용 계정의 갑작스러운 활성화는 부정 은닉 시도.
         diff()만 쓰면 첫 건만 잡히고 쪼개기 등 후속 부정 전표가 빠진다.
         → 재활성화 시점(Reactivation Point) 발견 후 윈도우 내 모든 거래를 연좌 플래깅.
    """
    if df.empty or "gl_account" not in df.columns or "posting_date" not in df.columns:
        return pd.Series(0.0, index=df.index)

    work = df[["gl_account", "posting_date"]].copy()
    work["posting_date"] = pd.to_datetime(work["posting_date"], errors="coerce")
    work["_orig_idx"] = df.index

    # Why: sort 필수 — diff()가 시간순으로 정확한 gap 계산
    work = work.sort_values(["gl_account", "posting_date"])
    work["gap_days"] = work.groupby("gl_account")["posting_date"].diff().dt.days

    # 재활성화 시점 식별 (gap > inactive_days)
    react_mask = work["gap_days"] > inactive_days
    if not react_mask.any():
        return pd.Series(0.0, index=df.index)

    # Why: 재활성화 시점의 gap을 윈도우 내 모든 행에 전파하기 위해 추출
    react_points = work.loc[react_mask, ["gl_account", "posting_date", "gap_days"]].copy()
    react_points = react_points.rename(columns={
        "posting_date": "react_date",
        "gap_days": "react_gap",
    })

    # 원본 df의 각 행이 어떤 재활성화 윈도우에 속하는지 매핑
    # Why: cross join 후 조건 필터 (gl_account 일치 + 윈도우 범위)
    scores = pd.Series(0.0, index=df.index)
    window_td = pd.Timedelta(days=reactivation_window_days)

    # Why: min_amount > 0이면, 재활성화 윈도우 내 최대 금액이 기준 미만인 경우 스킵
    amount_col = df[["debit_amount", "credit_amount"]].fillna(0).max(axis=1) if min_amount > 0 else None

    for _, rp in react_points.iterrows():
        acct = rp["gl_account"]
        react_date = rp["react_date"]
        gap = rp["react_gap"]

        # Why: 해당 계정에서 재활성화 시점 이후 윈도우 내 모든 거래를 선택
        acct_mask = work["gl_account"] == acct
        date_start = react_date
        date_end = react_date + window_td
        in_window = acct_mask & (work["posting_date"] >= date_start) & (work["posting_date"] <= date_end)

        # Why: min_amount 가드 — 소액 재활성화는 무시 (과탐 방지)
        if amount_col is not None:
            window_orig = work.loc[in_window, "_orig_idx"].to_numpy()
            if amount_col.loc[window_orig].max() < min_amount:
                continue

        # Why: gap 기반 점수 전파 — 휴면 기간이 길수록 높은 점수
        score_val = min(gap / (inactive_days * 3), 1.0)
        # Why: .to_numpy()로 Series 레이블 인덱서 충돌 방어 (대규모 데이터 안전)
        orig_indices = work.loc[in_window, "_orig_idx"].to_numpy()
        # Why: 여러 reactivation point에 걸칠 수 있으므로 max 적용
        current = scores.loc[orig_indices].to_numpy()
        scores.loc[orig_indices] = current.clip(min=score_val)

    return scores


# ── R03: IC 이전가격 이상 ──────────────────────────────────────


def r03_transfer_pricing_anomaly(
    df: pd.DataFrame,
    *,
    deviation_threshold: float = 0.15,
    min_ic_pairs: int = 3,
) -> pd.Series:
    """IC 거래처별 거래 금액 편차 이상 탐지.

    Why: ISA 550 §23 — 관계사 거래의 가격 이상은 이전가격 조작 위험.
         그래프 없이 통계적 근사: (trading_partner, gl_account) 그룹별 편차 분석.
    """
    if df.empty or "is_intercompany" not in df.columns:
        return pd.Series(0.0, index=df.index)

    ic_mask = df["is_intercompany"].fillna(False).astype(bool)
    if not ic_mask.any():
        return pd.Series(0.0, index=df.index)

    if "trading_partner" not in df.columns or "gl_account" not in df.columns:
        return pd.Series(0.0, index=df.index)

    amount = df[["debit_amount", "credit_amount"]].fillna(0).max(axis=1)
    group_cols = ["trading_partner", "gl_account"]

    # Why: IC 행만 대상으로 그룹 통계 계산 → 전체 df에 매핑
    ic_amount = amount.where(ic_mask)
    group_mean = ic_amount.groupby([df[c] for c in group_cols]).transform("mean")
    group_count = ic_amount.groupby([df[c] for c in group_cols]).transform("count")

    # Why: 소그룹은 통계적 의미 없음 → 제외
    valid_group = ic_mask & (group_count >= min_ic_pairs)
    if not valid_group.any():
        return pd.Series(0.0, index=df.index)

    # 편차 비율 계산
    deviation = (amount - group_mean).abs() / group_mean.clip(lower=1e-10)
    flagged = valid_group & (deviation > deviation_threshold)

    scores = pd.Series(0.0, index=df.index)
    # Why: 연속 점수 — 편차가 클수록 높은 점수
    scores[flagged] = (deviation[flagged] / (deviation_threshold * 3)).clip(upper=1.0)

    return scores


# ── R04: 문서 흐름 누락 ────────────────────────────────────────


def r04_missing_relationship(
    df: pd.DataFrame,
    *,
    doc_flow_df: pd.DataFrame | None = None,
) -> pd.Series:
    """P2P/O2C 문서 흐름 체인에서 단계 누락 탐지.

    Why: PO→GR→Invoice→Payment 체인에서 누락된 단계는 가공거래/미승인지급 위험.
         doc_flow_df는 build_doc_flow_df()가 사전 쿼리한 결과.
    """
    if df.empty:
        return pd.Series(0.0, index=df.index)

    if doc_flow_df is None or doc_flow_df.empty:
        return pd.Series(0.0, index=df.index)

    if "document_id" not in df.columns:
        return pd.Series(0.0, index=df.index)

    # Why: journal_entry_id 기준으로 GL df에 매핑
    merged = df[["document_id"]].merge(
        doc_flow_df[["journal_entry_id", "total", "present"]],
        left_on="document_id",
        right_on="journal_entry_id",
        how="left",
    )

    # Why: 누락 비율 = (total - present) / total
    scores = pd.Series(0.0, index=df.index)
    matched = merged["total"].notna()
    if matched.any():
        missing_ratio = (merged["total"] - merged["present"]) / merged["total"]
        scores[matched] = missing_ratio[matched].clip(lower=0.0, upper=1.0)

    return scores


# ── DuckDB 사전 쿼리 헬퍼 ──────────────────────────────────────


def build_doc_flow_df(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame | None:
    """document_references + 헤더 테이블에서 불완전 체인 추출.

    Why: R04 detect() 호출 전에 pipeline에서 실행 — O(1) DuckDB 쿼리로
         GL df와의 반복 조인 회피.
    """
    sql = """
    WITH p2p AS (
        SELECT poh.document_id,
               poh.journal_entry_id,
               COUNT(DISTINCT CASE WHEN dr.target_doc_type = 'goods_receipt' THEN 1 END) AS has_gr,
               COUNT(DISTINCT CASE WHEN dr.target_doc_type = 'vendor_invoice' THEN 1 END) AS has_inv,
               COUNT(DISTINCT CASE WHEN dr.target_doc_type = 'payment' THEN 1 END) AS has_pay
        FROM purchase_order_headers poh
        LEFT JOIN document_references dr ON dr.source_doc_id = poh.document_id
        GROUP BY poh.document_id, poh.journal_entry_id
    ),
    o2c AS (
        SELECT soh.document_id,
               soh.journal_entry_id,
               COUNT(DISTINCT CASE WHEN dr.target_doc_type = 'delivery' THEN 1 END) AS has_del,
               COUNT(DISTINCT CASE WHEN dr.target_doc_type = 'customer_invoice' THEN 1 END) AS has_inv
        FROM sales_order_headers soh
        LEFT JOIN document_references dr ON dr.source_doc_id = soh.document_id
        GROUP BY soh.document_id, soh.journal_entry_id
    )
    SELECT journal_entry_id, 'P2P' AS chain, 3 AS total,
           (CASE WHEN has_gr > 0 THEN 1 ELSE 0 END
            + CASE WHEN has_inv > 0 THEN 1 ELSE 0 END
            + CASE WHEN has_pay > 0 THEN 1 ELSE 0 END) AS present
    FROM p2p
    WHERE has_gr = 0 OR has_inv = 0 OR has_pay = 0
    UNION ALL
    SELECT journal_entry_id, 'O2C' AS chain, 2 AS total,
           (CASE WHEN has_del > 0 THEN 1 ELSE 0 END
            + CASE WHEN has_inv > 0 THEN 1 ELSE 0 END) AS present
    FROM o2c
    WHERE has_del = 0 OR has_inv = 0
    """
    try:
        result = conn.execute(sql).fetchdf()
        return result if not result.empty else None
    except Exception:
        return None
