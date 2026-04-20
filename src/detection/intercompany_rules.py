"""내부거래 매칭 룰 함수 — IC 그룹 대사 + 3개 서브룰 (WU-07).

Why: L3-03(MVP)은 is_intercompany bool만 flag. 양측 거래 대사 없이 recall 7%.
     그룹 단위 집계 비교로 N:M 다대다 매칭 대응 + 이종 통화 방어.
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)


# ── YAML 설정 헬퍼 ─────────────────────────────────────────────


def load_ic_pairs(audit_rules: dict) -> dict[str, str]:
    """YAML intercompany.pairs → 양방향 매핑 dict.

    Why: 클라이언트별 CoA 체계가 다르므로 코드 하드코딩 금지.
    """
    patterns = audit_rules.get("patterns", audit_rules)
    ic_config = patterns.get("intercompany", {})
    pairs_list = ic_config.get("pairs", [])

    pair_map: dict[str, str] = {}
    for pair in pairs_list:
        rec = str(pair.get("receivable", ""))
        pay = str(pair.get("payable", ""))
        if rec and pay:
            pair_map[rec] = pay
            pair_map[pay] = rec
    return pair_map


def extract_ic_prefixes(audit_rules: dict) -> list[str]:
    """pairs에서 모든 고유 prefix 추출 — add_is_intercompany() 호환용."""
    pair_map = load_ic_pairs(audit_rules)
    return sorted(set(pair_map.keys()))


# ── IC 계정 유형 분류 ──────────────────────────────────────────


def _classify_ic_type(
    gl_account: pd.Series, pair_map: dict[str, str],
) -> pd.Series:
    """GL 계정 prefix로 IC 유형(receivable/payable) 분류.

    Why: pair_map은 양방향이므로 YAML pairs 순서(receivable 먼저)를 기준으로
         첫 등장 키를 receivable로 분류. Python 3.7+ dict 삽입 순서 보장.
    """
    gl_str = gl_account.astype(str).str.strip()
    receivable_prefixes: set[str] = set()
    payable_prefixes: set[str] = set()
    seen: set[str] = set()
    for k, v in pair_map.items():
        if k not in seen and v not in seen:
            receivable_prefixes.add(k)
            payable_prefixes.add(v)
            seen.update([k, v])

    def _get_type(gl: str) -> str | None:
        for p in receivable_prefixes:
            if gl.startswith(p):
                return "receivable"
        for p in payable_prefixes:
            if gl.startswith(p):
                return "payable"
        return None

    return gl_str.map(_get_type)


# ── 그룹 매칭 엔진 ─────────────────────────────────────────────


def match_ic_groups(
    df: pd.DataFrame,
    pair_map: dict[str, str],
    amount_tolerance: float,
) -> pd.DataFrame:
    """IC 전표를 그룹 단위로 매칭 — N:M 다대다 대응.

    Why: A법인 10건 소액 vs B법인 1건 통합 기표 → 행 단위 비교 실패.
         그룹별 sum(debit)/sum(credit) 집계 비교가 핵심.

    Returns: 원본 인덱스 기준 매칭 결과 DataFrame
        columns: [has_counterpart, matched, diff_ratio,
                  match_level, date_diff_days, cross_currency]
    """
    if not pair_map:
        return pd.DataFrame(index=df.index)

    ic_mask = df.get(
        "is_intercompany", pd.Series(False, index=df.index),
    ).fillna(False)
    if not ic_mask.any():
        return pd.DataFrame(index=df.index)

    ic_df = df.loc[ic_mask].copy()
    ic_df["_ic_type"] = _classify_ic_type(ic_df["gl_account"], pair_map)
    ic_df = ic_df.dropna(subset=["_ic_type"])
    if ic_df.empty:
        return pd.DataFrame(index=df.index)

    # Why: receivable → sum(debit), payable → sum(credit)
    ic_df["_amount"] = ic_df.apply(
        lambda r: r["debit_amount"]
        if r["_ic_type"] == "receivable"
        else r["credit_amount"],
        axis=1,
    ).fillna(0.0)

    # Why: groupby lambda가 반환하는 x.index는 그룹 내 상대 위치일 수 있음
    #      원본 인덱스를 컬럼으로 보존하여 안전하게 추적
    ic_df["_orig_idx"] = ic_df.index

    # ── 집계 키 결정 (graceful degradation) ──
    # match_level 매트릭스:
    #   company_code multi + trading_partner 있음 → "exact"     (Level 1)
    #   company_code multi, trading_partner 없음  → "aggregate" (Level 2)
    #   그 외                                    → "fallback"  (Level 3)
    has_tp = (
        "trading_partner" in ic_df.columns
        and ic_df["trading_partner"].notna().any()
    )
    has_cc = (
        "company_code" in ic_df.columns
        and ic_df["company_code"].nunique() > 1
    )
    has_cur = (
        "currency" in ic_df.columns
        and ic_df["currency"].notna().any()
    )

    group_cols: list[str] = []
    if has_cc:
        group_cols.append("company_code")
    if has_tp:
        group_cols.append("trading_partner")
    if has_cur:
        group_cols.append("currency")

    if not group_cols:
        match_level = "fallback"
    elif has_tp:
        match_level = "exact"
    else:
        match_level = "aggregate"

    # ── 그룹별 집계 ──
    agg_key = (group_cols + ["_ic_type"]) if group_cols else ["_ic_type"]

    # Why: agg 딕셔너리를 사전 구성하여 조건부 컬럼 참조 버그 방지
    agg_spec: dict = {
        "sum_amount": ("_amount", "sum"),
        "row_indices": ("_orig_idx", list),
    }
    if "posting_date" in ic_df.columns:
        agg_spec["median_date"] = ("posting_date", "median")

    group_agg = (
        ic_df.groupby(agg_key, dropna=False)
        .agg(**agg_spec)
        .reset_index()
    )

    # ── 대응 그룹 매칭 ──
    result_rows: list[dict] = []
    rec_groups = group_agg[group_agg["_ic_type"] == "receivable"]
    pay_groups = group_agg[group_agg["_ic_type"] == "payable"]

    for _, rec_row in rec_groups.iterrows():
        match_mask = pd.Series(True, index=pay_groups.index)
        for col in group_cols:
            match_mask = _apply_group_filter(
                match_mask, pay_groups, rec_row, col,
                has_cc=has_cc, has_tp=has_tp,
            )
        matched_pays = pay_groups[match_mask]

        if matched_pays.empty:
            _append_unmatched(result_rows, rec_row, match_level)
        else:
            _append_matched(
                result_rows, rec_row, matched_pays,
                amount_tolerance, match_level, ic_df,
            )

    # Why: _append_matched()가 매칭된 payable 행도 result_rows에 삽입하므로
    #      seen_indices에 이미 포함됨. 아래 루프는 매칭 안 된 payable만 처리.
    seen_indices = {r["orig_idx"] for r in result_rows}
    for _, pay_row in pay_groups.iterrows():
        for idx in pay_row["row_indices"]:
            if idx not in seen_indices:
                result_rows.append({
                    "orig_idx": idx, "has_counterpart": False,
                    "matched": False, "diff_ratio": 1.0,
                    "match_level": match_level,
                    "date_diff_days": None,
                })

    if not result_rows:
        return pd.DataFrame(index=df.index)

    result_df = pd.DataFrame(result_rows).set_index("orig_idx")
    result_df = result_df[~result_df.index.duplicated(keep="first")]
    return result_df.reindex(df.index)


def _apply_group_filter(
    mask: pd.Series,
    pay_groups: pd.DataFrame,
    rec_row: pd.Series,
    col: str,
    *,
    has_cc: bool,
    has_tp: bool,
) -> pd.Series:
    """그룹 매칭 필터 적용 — 교차 매칭 포함."""
    if col == "trading_partner" and has_cc:
        # Why: rec의 trading_partner → pay의 company_code 교차 매칭
        return mask & (
            pay_groups["company_code"]
            == rec_row.get("trading_partner", "")
        )
    if col == "company_code" and has_tp:
        # Why: rec의 company_code → pay의 trading_partner 교차 매칭
        if "trading_partner" in pay_groups.columns:
            return mask & (
                pay_groups["trading_partner"]
                == rec_row.get("company_code", "")
            )
        return mask
    if col in pay_groups.columns:
        return mask & (pay_groups[col] == rec_row[col])
    return mask


def _append_unmatched(
    rows: list[dict], rec_row: pd.Series, match_level: str,
) -> None:
    """미매칭 결과 추가."""
    for idx in rec_row["row_indices"]:
        rows.append({
            "orig_idx": idx, "has_counterpart": False,
            "matched": False, "diff_ratio": 1.0,
            "match_level": match_level, "date_diff_days": None,
        })


def _append_matched(
    rows: list[dict],
    rec_row: pd.Series,
    matched_pays: pd.DataFrame,
    amount_tolerance: float,
    match_level: str,
    ic_df: pd.DataFrame,
) -> None:
    """매칭 결과 계산 + 추가."""
    counterpart_sum = matched_pays["sum_amount"].sum()
    rec_sum = rec_row["sum_amount"]
    max_val = max(abs(rec_sum), abs(counterpart_sum), 1e-10)
    diff_ratio = abs(rec_sum - counterpart_sum) / max_val
    matched = diff_ratio <= amount_tolerance

    # Why: 이종 통화 방어 — 100x 이상 차이면 비교 무의미
    ratio_a = abs(rec_sum) / max(abs(counterpart_sum), 1e-10)
    ratio_b = abs(counterpart_sum) / max(abs(rec_sum), 1e-10)
    cross_currency = max_val > 0 and (ratio_a > 100 or ratio_b > 100)

    date_diff = _calc_date_diff(rec_row, matched_pays, ic_df)

    row_data = {
        "has_counterpart": True, "matched": matched,
        "diff_ratio": diff_ratio, "match_level": match_level,
        "date_diff_days": date_diff, "cross_currency": cross_currency,
    }
    for idx in rec_row["row_indices"]:
        rows.append({"orig_idx": idx, **row_data})
    for _, pay_row in matched_pays.iterrows():
        for idx in pay_row["row_indices"]:
            rows.append({"orig_idx": idx, **row_data})


def _calc_date_diff(
    rec_row: pd.Series,
    matched_pays: pd.DataFrame,
    ic_df: pd.DataFrame,
) -> float | None:
    """매칭 쌍의 전기일 차이(일) 계산."""
    if "posting_date" not in ic_df.columns:
        return None
    if "median_date" not in rec_row.index:
        return None
    if "median_date" not in matched_pays.columns:
        return None
    try:
        rec_date = pd.Timestamp(rec_row["median_date"])
        pay_date = pd.Timestamp(matched_pays["median_date"].iloc[0])
        if pd.notna(rec_date) and pd.notna(pay_date):
            return abs((rec_date - pay_date).days)
    except Exception:
        pass
    return None


# ── 서브룰 함수 ────────────────────────────────────────────────


def ic01_unmatched_intercompany(
    df: pd.DataFrame,
    *,
    match_df: pd.DataFrame,
) -> pd.Series:
    """IL3-04: 미매칭 내부거래 — 대응 그룹 없는 IC 전표 탐지.

    Why: 감사기준서 550호 §23. 관계사 간 거래는 양측 대사가 필수.
    """
    if match_df.empty or "has_counterpart" not in match_df.columns:
        return pd.Series(0.0, index=df.index)
    has_cp = match_df["has_counterpart"].astype(bool)
    return has_cp.map({True: 0.0, False: 1.0}).fillna(0.0)


def ic02_amount_mismatch(
    df: pd.DataFrame,
    *,
    match_df: pd.DataFrame,
    amount_tolerance: float = 0.02,
    max_diff_ratio: float = 0.10,
) -> pd.Series:
    """IL3-05: 금액 불일치 — 매칭됐으나 합계 차이 초과.

    Why: IC 거래는 양측 금액 일치가 원칙. 차이는 부정/오류 징후.
    """
    if match_df.empty or "has_counterpart" not in match_df.columns:
        return pd.Series(0.0, index=df.index)

    scores = pd.Series(0.0, index=df.index)
    has_cp = match_df["has_counterpart"].astype("boolean").fillna(False).astype(bool)
    over_tol = match_df["diff_ratio"].fillna(0.0) > amount_tolerance

    # Why: 이종 통화 추정 시 점수 억제
    if "cross_currency" in match_df.columns:
        xc = match_df["cross_currency"].astype("boolean").fillna(False).astype(bool)
    else:
        xc = pd.Series(False, index=match_df.index)
    target = has_cp & over_tol & ~xc

    if target.any():
        valid = scores.index.intersection(target.index[target])
        diff = match_df.loc[valid, "diff_ratio"].fillna(0.0)
        scores.loc[valid] = (diff / max_diff_ratio).clip(upper=1.0)

    return scores


def ic03_timing_gap(
    df: pd.DataFrame,
    *,
    match_df: pd.DataFrame,
    date_window_days: int = 5,
    max_day_diff: int = 30,
) -> pd.Series:
    """IL3-06: 시차 이상 — 매칭됐으나 전기일 차이 과대.

    Why: 동시 기표가 원칙인 IC 거래에서 시차는 기간귀속 오류 징후.
    """
    if "posting_date" not in df.columns:
        return pd.Series(0.0, index=df.index)
    if match_df.empty or "date_diff_days" not in match_df.columns:
        return pd.Series(0.0, index=df.index)

    scores = pd.Series(0.0, index=df.index)
    if "has_counterpart" in match_df.columns:
        has_cp = match_df["has_counterpart"].fillna(False).astype(bool)
    else:
        has_cp = pd.Series(False, index=match_df.index)
    has_date = match_df["date_diff_days"].notna()
    over_window = match_df["date_diff_days"].fillna(0) > date_window_days
    target = has_cp & has_date & over_window

    if target.any():
        valid = scores.index.intersection(target.index[target])
        days = match_df.loc[valid, "date_diff_days"].fillna(0)
        scores.loc[valid] = (days / max_day_diff).clip(upper=1.0)

    return scores
