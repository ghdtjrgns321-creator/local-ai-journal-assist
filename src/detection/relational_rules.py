"""Relational 탐지 룰 함수 — WU-08 관계 기반 이상 탐지.

R01: 신규 거래처 대액 지급 (NewCounterparty)
R02: 휴면 계정 활동 (DormantAccountActivity)  — gl_account 단위
R03: IC 이전가격 이상 (TransferPricingAnomaly)
R04: 문서 흐름 누락 (MissingRelationship)

Graph/entity anomaly 보강 (Phase 2 relational family 격상):
R05: 희소 (gl_account, trading_partner) edge (RareAccountPartnerEdge)
R06: 사용자×계정 degree spike (UserAccountDegreeSpike) — period bucket 기반
R07: trading_partner 단위 휴면 재활성화 (DormantPartnerReactivation)

Note: LAYER_WEIGHTS에 의도적 미등록 — 성능 평가 후 WU-03 Stacking에서 배분.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from src.detection.relational_graph_features import (
    build_pair_key,
    compute_first_seen_recency_strength,
    compute_pair_rarity_score,
    compute_partner_inactivity_reactivation,
    compute_user_period_degree_zscore,
)

# R05 합성 가중치 — rarity vs recency. 도메인 근거: rarity (모집단 희소성) 가
# 일차 신호이며 recency (첫 등장 직후 가산) 가 보조 신호. fitting 으로 조정 금지.
_R05_RARITY_WEIGHT: float = 0.7
_R05_RECENCY_WEIGHT: float = 0.3

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
    required = {"trading_partner", "posting_date", "debit_amount", "credit_amount"}
    if df.empty or not required.issubset(df.columns):
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
    amount_required = {"debit_amount", "credit_amount"}
    if min_amount > 0 and not amount_required.issubset(df.columns):
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
    react_points = react_points.rename(
        columns={
            "posting_date": "react_date",
            "gap_days": "react_gap",
        }
    )

    # 원본 df의 각 행이 어떤 재활성화 윈도우에 속하는지 매핑
    # Why: cross join 후 조건 필터 (gl_account 일치 + 윈도우 범위)
    scores = pd.Series(0.0, index=df.index)
    window_td = pd.Timedelta(days=reactivation_window_days)

    # Why: min_amount > 0이면, 재활성화 윈도우 내 최대 금액이 기준 미만인 경우 스킵
    amount_col = (
        df[["debit_amount", "credit_amount"]].fillna(0).max(axis=1) if min_amount > 0 else None
    )

    for _, rp in react_points.iterrows():
        acct = rp["gl_account"]
        react_date = rp["react_date"]
        gap = rp["react_gap"]

        # Why: 해당 계정에서 재활성화 시점 이후 윈도우 내 모든 거래를 선택
        acct_mask = work["gl_account"] == acct
        date_start = react_date
        date_end = react_date + window_td
        in_window = (
            acct_mask & (work["posting_date"] >= date_start) & (work["posting_date"] <= date_end)
        )

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
    deviation_threshold: float = 1.0,
    min_ic_pairs: int = 5,
) -> pd.Series:
    """IC 거래처별 거래 금액 편차 이상 탐지.

    Why: ISA 550 §23 — 관계사 거래의 가격 이상은 이전가격 조작 위험.
         그래프 없이 통계적 근사: (trading_partner, gl_account) 그룹별 편차 분석.

    Calibration (2026-05-23):
        - deviation_threshold 0.15 → 1.0: 정상 IC pair 의 자연 분산 (환산·할인·세금)
          이 fixed4 truth-negative q95 ≈ 0.9995 까지 분포하므로 그 위만 anomaly 로 본다.
        - min_ic_pairs 3 → 5: 그룹 평균/편차 통계적 유의미 최소 표본.
        - 근거: artifacts/r03_ts01_natural_distribution_fixed4_20260523.md,
                dev/active/r03-ts01-calibration/r03-ts01-split-trial.md
    """
    if df.empty or "is_intercompany" not in df.columns:
        return pd.Series(0.0, index=df.index)

    ic_mask = df["is_intercompany"].fillna(False).astype(bool)
    if not ic_mask.any():
        return pd.Series(0.0, index=df.index)

    required = {"trading_partner", "gl_account", "debit_amount", "credit_amount"}
    if not required.issubset(df.columns):
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


# ── R05: 희소 (gl_account, trading_partner) edge ───────────────


def r05_rare_account_partner_edge(
    df: pd.DataFrame,
    *,
    min_pair_population: int = 50,
    min_freq: int = 2,
    lookback_days: int = 90,
) -> pd.Series:
    """희소 (gl_account, trading_partner) edge 탐지 + 첫 등장 recency 선형 감쇠.

    Why: ISA 240 ¶A41 (c) — 정상 거래 흐름을 벗어난 비정상 거래 조합은
         review signal. (account, partner) edge가 모집단에서 희소하거나
         첫 등장 후 lookback 윈도우 내에 발생하면 graph/entity anomaly로 본다.

    Guard:
        - unique pair count < min_pair_population: 전부 0 (small sample 무효화)
        - row의 pair frequency > min_freq: 0
        - 그 외: rarity_ecdf = 1 - rank_pct(row_freq),
                 recency_strength = max(0, 1 - days_since_first / lookback_days),
                 score = 0.7 * rarity_ecdf + 0.3 * recency_strength (cap 1.0)

    1/freq + binary boost 의 이산 격자를 ECDF + 선형 감쇠로 교체해 rare-tier
    안의 lane sort 해상도를 보존한다. 가중치 0.7/0.3 은 fitting 으로 조정 금지.
    """
    scores = pd.Series(0.0, index=df.index, dtype=float)
    if df.empty:
        return scores
    if "gl_account" not in df.columns or "trading_partner" not in df.columns:
        return scores

    pair_key = build_pair_key(df, "gl_account", "trading_partner")
    rarity = compute_pair_rarity_score(
        pair_key,
        min_pair_population=min_pair_population,
        min_freq=min_freq,
    )
    rare_mask = rarity > 0
    if not bool(rare_mask.any()):
        return scores

    if "posting_date" in df.columns and lookback_days > 0:
        posting = pd.to_datetime(df["posting_date"], errors="coerce")
        recency = compute_first_seen_recency_strength(
            pair_key,
            posting,
            lookback_days=lookback_days,
        )
    else:
        recency = pd.Series(0.0, index=df.index, dtype=float)

    composite = (_R05_RARITY_WEIGHT * rarity + _R05_RECENCY_WEIGHT * recency).clip(
        lower=0.0, upper=1.0
    )
    scores.loc[rare_mask] = composite.loc[rare_mask].to_numpy()
    return scores


# ── R06: 사용자×계정 degree spike ──────────────────────────────


def r06_user_account_degree_spike(
    df: pd.DataFrame,
    *,
    period: str = "M",
    z_threshold: float = 2.0,
    min_user_obs: int = 3,
    min_users: int = 10,
) -> pd.Series:
    """사용자별 period bucket 내 unique gl_account degree spike.

    Why: PCAOB AS 2401 §B7 — journal entries posted by individuals who do not
         typically post such entries. 평소 다루지 않던 다양한 계정을 단기에
         다루는 사용자 패턴은 graph/entity anomaly signal.

    구현:
        - posting_date를 period(M=month, W=week) bucket으로 묶는다.
        - user × period별 unique gl_account count = degree.
        - user별 median + MAD robust z-score 계산.
        - z > z_threshold 행에 대해 ECDF rank (rank_pct, method="average") 부여.

    Guard:
        - created_by/gl_account/posting_date 부재: 0
        - 전체 user 수 < min_users: small sample, 0
        - user별 period 관측 수 < min_user_obs: 통계 무의미, 0

    Why: 기존 ``min(z / (z_threshold*3), 1.0)`` 은 극단 spike 가 cap 으로 평탄화
         되어 lane sort 해상도를 잃었다. spike-mask 내부에서 z 분포의 ECDF rank
         로 변환하면 cap 손실 없이 ranking 해상도가 보존된다. spike 외 행은 0 유지.
    """
    scores = pd.Series(0.0, index=df.index, dtype=float)
    if df.empty:
        return scores

    z_series = compute_user_period_degree_zscore(
        df,
        user_col="created_by",
        target_col="gl_account",
        date_col="posting_date",
        period=period,
        min_user_obs=min_user_obs,
        min_users=min_users,
    )
    spike_mask = z_series > z_threshold
    if not bool(spike_mask.any()):
        return scores

    spike_z = z_series.loc[spike_mask]
    spike_rank = spike_z.rank(method="average", pct=True)
    scores.loc[spike_mask] = spike_rank.to_numpy()
    return scores


# ── R07: trading_partner 단위 휴면 재활성화 ────────────────────


def r07_dormant_partner_reactivation(
    df: pd.DataFrame,
    *,
    inactive_days: int = 180,
    reactivation_window_days: int = 7,
    min_amount: float = 0.0,
) -> pd.Series:
    """trading_partner 단위 휴면 후 재활성화 탐지.

    Why: PCAOB AS 2401 §B7 — unusual activity in previously dormant business
         relationships; ISA 240 ¶A41 (d) significant unusual transactions.
         R02(gl_account 단위)와 분리. 거래처 관계가 장기간 끊겼다가 재개되는
         패턴은 graph/entity anomaly signal.

    Guard (사용자 조정 #3):
        - blank/NaN trading_partner는 dormant 판단 대상에서 제외
          (빈 거래처가 하나로 묶이면 오탐 폭증)
    """
    if df.empty:
        return pd.Series(0.0, index=df.index, dtype=float)

    return compute_partner_inactivity_reactivation(
        df,
        partner_col="trading_partner",
        date_col="posting_date",
        inactive_days=inactive_days,
        reactivation_window_days=reactivation_window_days,
        min_amount=min_amount,
    )


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
               COUNT(DISTINCT CASE
                   WHEN dr.target_doc_type = 'vendor_invoice' THEN 1
               END) AS has_inv,
               COUNT(DISTINCT CASE WHEN dr.target_doc_type = 'payment' THEN 1 END) AS has_pay
        FROM purchase_order_headers poh
        LEFT JOIN document_references dr ON dr.source_doc_id = poh.document_id
        GROUP BY poh.document_id, poh.journal_entry_id
    ),
    o2c AS (
        SELECT soh.document_id,
               soh.journal_entry_id,
               COUNT(DISTINCT CASE WHEN dr.target_doc_type = 'delivery' THEN 1 END) AS has_del,
               COUNT(DISTINCT CASE
                   WHEN dr.target_doc_type = 'customer_invoice' THEN 1
               END) AS has_inv
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
