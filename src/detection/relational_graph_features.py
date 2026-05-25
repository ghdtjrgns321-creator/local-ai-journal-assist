"""Relational family graph/entity anomaly helper.

Why: RelationalDetector R05~R07 sub-detector의 graph/entity feature 계산을
     pandas 벡터화로 분리. networkx 미사용 — high-cardinality entity에서
     add_edge 루프 OOM 회피 (feedback_networkx_oom 정책).

Phase 1 rule hit/score는 입력에 사용하지 않는다. 합성 라벨 컬럼
(is_fraud, is_anomaly, mutation_*)도 미참조.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def build_pair_key(
    df: pd.DataFrame,
    col_a: str,
    col_b: str,
    *,
    sep: str = "||",
) -> pd.Series:
    """두 컬럼 조합을 단일 key Series로 묶는다. 빈/NaN 값은 NaN 유지.

    Returns: df.index 정렬 Series. 유효한 행만 string key, 나머지는 NaN.
    """
    if col_a not in df.columns or col_b not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype=object)

    a = df[col_a].fillna("").astype(str).str.strip()
    b = df[col_b].fillna("").astype(str).str.strip()
    valid = (a != "") & (b != "")

    key = pd.Series(np.nan, index=df.index, dtype=object)
    key.loc[valid] = a[valid].str.cat(b[valid], sep=sep)
    return key


def compute_pair_rarity_score(
    pair_key: pd.Series,
    *,
    min_pair_population: int,
    min_freq: int,
) -> pd.Series:
    """Pair 빈도 기반 rarity score (0~1, ECDF 연속화).

    - unique pair count < min_pair_population: 전부 0 (small sample 무효화)
    - row가 속한 pair의 frequency > min_freq: 0 (rare-tier mask)
    - rare-tier 행: ``1 - rank_pct(row_freq, method="average")`` 부여

    Why: 기존 ``1 / freq`` 는 {1.0, 0.5, 0.33, …} 의 hyperbolic 격자로 양자화되어
         lane sort 해상도를 잃었다. 모집단 freq 분포의 1-ECDF 로 바꾸면
         rare-tier 행 안에서도 연속 ranking 이 보존된다. mask (population/min_freq)
         는 도메인 가드로 유지.
    """
    scores = pd.Series(0.0, index=pair_key.index, dtype=float)
    valid_mask = pair_key.notna()
    valid_keys = pair_key.loc[valid_mask]
    if valid_keys.empty or valid_keys.nunique() < min_pair_population:
        return scores

    freq_map = valid_keys.value_counts()
    row_freq = pair_key.map(freq_map)
    rare_mask = valid_mask & (row_freq <= min_freq)
    if not rare_mask.any():
        return scores

    # Why: 모집단 행 분포 freq 의 1-ECDF. 낮은 freq → 높은 rarity.
    #      method="average" 로 같은 freq 행은 동일 점수.
    valid_row_freq = row_freq.loc[valid_mask].astype(float)
    rank_pct = valid_row_freq.rank(method="average", pct=True)
    rarity_ecdf = (1.0 - rank_pct).clip(lower=0.0, upper=1.0)
    scores.loc[rare_mask] = rarity_ecdf.loc[rare_mask].to_numpy()
    return scores


def compute_first_seen_recency_strength(
    pair_key: pd.Series,
    posting_date: pd.Series,
    *,
    lookback_days: int,
) -> pd.Series:
    """Pair 첫 등장 후 경과일 기반 선형 recency strength (0~1).

    - days_since_first == 0 → 1.0
    - days_since_first >= lookback_days → 0.0
    - 그 사이 → 선형 감쇠 ``1 - days_since_first / lookback_days``

    Why: 기존 binary mask + ``+0.2`` 보너스는 lane sort 해상도를 추가로
         양자화한다. 선형 감쇠로 첫 등장 직후 행이 더 높게 평가되도록 한다.
    """
    strength = pd.Series(0.0, index=pair_key.index, dtype=float)
    valid = pair_key.notna() & posting_date.notna()
    if not valid.any() or lookback_days <= 0:
        return strength

    work = pd.DataFrame({"key": pair_key, "date": posting_date}).loc[valid]
    first_seen = work.groupby("key")["date"].transform("min")
    days_since = (work["date"] - first_seen).dt.days.clip(lower=0)
    raw_strength = 1.0 - (days_since.astype(float) / float(lookback_days))
    strength.loc[work.index] = raw_strength.clip(lower=0.0, upper=1.0).to_numpy()
    return strength


def compute_first_seen_recency_mask(
    pair_key: pd.Series,
    posting_date: pd.Series,
    *,
    lookback_days: int,
) -> pd.Series:
    """Pair 첫 등장일로부터 lookback_days 이내 행 mask.

    Returns: pair_key.index 정렬 bool Series.
    """
    mask = pd.Series(False, index=pair_key.index, dtype=bool)
    valid = pair_key.notna() & posting_date.notna()
    if not valid.any() or lookback_days <= 0:
        return mask

    work = pd.DataFrame({"key": pair_key, "date": posting_date}).loc[valid]
    first_seen = work.groupby("key")["date"].transform("min")
    days_since = (work["date"] - first_seen).dt.days
    recency = days_since <= lookback_days
    mask.loc[recency.index] = recency.astype(bool).to_numpy()
    return mask


def compute_user_period_degree_zscore(
    df: pd.DataFrame,
    *,
    user_col: str,
    target_col: str,
    date_col: str,
    period: str,
    min_user_obs: int,
    min_users: int,
) -> pd.Series:
    """User × period bucket의 unique target degree에 대한 robust z-score.

    - posting_date를 period(M/W) bucket으로 묶는다.
    - user × period별 unique target count.
    - user별 median/MAD로 z-score (MAD=0 방어 clip).
    - min_user_obs 미만의 user는 통계 무의미 → 0.
    - 전체 user 수 < min_users면 small sample → 모두 0.

    Why: 사용자 조정 #2 — rolling unique는 구현 복잡도가 높아 period bucket으로
         단순화. rolling은 후속 PR에서 다룬다.

    Returns: df.index 정렬 z-score Series (음수 포함, 단 양수만 score로 의미).
    """
    zeros = pd.Series(0.0, index=df.index, dtype=float)
    required = {user_col, target_col, date_col}
    if not required.issubset(df.columns):
        return zeros

    user = df[user_col].fillna("").astype(str).str.strip()
    target = df[target_col].fillna("").astype(str).str.strip()
    posting = pd.to_datetime(df[date_col], errors="coerce")
    valid = (user != "") & (target != "") & posting.notna()
    if not valid.any():
        return zeros
    if user[valid].nunique() < min_users:
        return zeros

    try:
        period_label = posting.dt.to_period(period).astype(str)
    except ValueError:
        return zeros

    work = pd.DataFrame(
        {"user": user, "target": target, "period": period_label},
        index=df.index,
    ).loc[valid]

    degree = (
        work.groupby(["user", "period"], sort=False)["target"].nunique().reset_index(name="degree")
    )
    # Why: user별 통계 유의미 보장 — period 관측 수가 min_user_obs 미만이면 제외
    user_period_counts = degree.groupby("user")["period"].transform("count")
    degree = degree.loc[user_period_counts >= min_user_obs].copy()
    if degree.empty:
        return zeros

    # Why: median + MAD robust z. MAD=0 (단조 시리즈)일 때 분모 1로 clip
    user_median = degree.groupby("user")["degree"].transform("median")
    deviation = (degree["degree"] - user_median).abs()
    user_mad = deviation.groupby(degree["user"]).transform("median").clip(lower=1.0)
    degree["z"] = (degree["degree"] - user_median) / (1.4826 * user_mad)

    score_map = degree.set_index(["user", "period"])["z"]

    z_series = pd.Series(0.0, index=df.index, dtype=float)
    keys = list(zip(work["user"], work["period"], strict=True))
    values = [float(score_map.get((u, p), 0.0)) for u, p in keys]
    z_series.loc[work.index] = values
    return z_series


def compute_partner_inactivity_reactivation(
    df: pd.DataFrame,
    *,
    partner_col: str,
    date_col: str,
    inactive_days: int,
    reactivation_window_days: int,
    min_amount: float,
) -> pd.Series:
    """Partner 단위 휴면 후 재활성화 score (0~1).

    - blank/NaN partner 제외 (사용자 조정 #3 — 빈 거래처 묶임 오탐 방지).
    - partner별 posting_date.diff() > inactive_days → 재활성화 시점.
    - 재활성화 시점 이후 reactivation_window_days 내 거래에 점수 전파.
    - min_amount > 0이면 window 내 최대 금액이 기준 미만일 때 skip.
    - score = min(gap / (inactive_days * 3), 1.0).

    R02(account 단위)와 분리. partner 관계 재활성화는 거래처 단위 view.
    """
    scores = pd.Series(0.0, index=df.index, dtype=float)
    if df.empty or partner_col not in df.columns or date_col not in df.columns:
        return scores

    partner = df[partner_col].fillna("").astype(str).str.strip()
    posting = pd.to_datetime(df[date_col], errors="coerce")
    valid = (partner != "") & posting.notna()
    if not valid.any():
        return scores

    work = pd.DataFrame(
        {
            "partner": partner,
            "posting_date": posting,
            "_orig_idx": df.index,
        },
    ).loc[valid]
    work = work.sort_values(["partner", "posting_date"])
    work["gap_days"] = work.groupby("partner")["posting_date"].diff().dt.days

    react_mask = work["gap_days"] > inactive_days
    if not react_mask.any():
        return scores

    react_points = work.loc[react_mask, ["partner", "posting_date", "gap_days"]].rename(
        columns={"posting_date": "react_date", "gap_days": "react_gap"},
    )

    window_td = pd.Timedelta(days=reactivation_window_days)
    if min_amount > 0 and "debit_amount" in df.columns and "credit_amount" in df.columns:
        amount_col: pd.Series | None = df[["debit_amount", "credit_amount"]].fillna(0).max(axis=1)
    else:
        amount_col = None

    for _, rp in react_points.iterrows():
        ptn = rp["partner"]
        react_date = rp["react_date"]
        gap = float(rp["react_gap"])

        ptn_mask = work["partner"] == ptn
        in_window = (
            ptn_mask
            & (work["posting_date"] >= react_date)
            & (work["posting_date"] <= react_date + window_td)
        )
        if not in_window.any():
            continue

        orig_indices = work.loc[in_window, "_orig_idx"].to_numpy()
        if amount_col is not None and len(orig_indices) > 0:
            if amount_col.reindex(orig_indices).fillna(0).max() < min_amount:
                continue

        score_val = min(gap / max(inactive_days * 3, 1), 1.0)
        current = scores.loc[orig_indices].to_numpy()
        scores.loc[orig_indices] = np.maximum(current, score_val)

    return scores
