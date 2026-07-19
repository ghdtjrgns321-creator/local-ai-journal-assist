"""거래처(trading_partner) 단위 분석적 검토 신호 — 첫등장·희소·휴면재활성 3배지.

Why: PHASE1-2 재설계(2026-06-30)로 옛 PHASE2 relational family(R01/R05/R07)를 삭제한 뒤,
     base 경로에서 거래처 단위로 신규 계산한다. 점수 비병합(배지·자기큐 전용, anomaly_score
     무기여). first-seen/dormant는 다년 데이터가 필요해 단일 연도 실행 시 가드로 빈 결과 반환.
     임계값은 §3 데이터주도 원칙에 따라 전부 settings 에서 read (리터럴 계산분기 금지).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

BADGE_COLUMNS: tuple[str, ...] = (
    "is_first_seen_partner",
    "is_rare_partner",
    "is_dormant_partner",
)


@dataclass
class PartnerSignalResult:
    """거래처 신호 산출 결과. row_badges 는 df.index 정렬 3 bool 컬럼."""

    first_seen_partners: set[str] = field(default_factory=set)
    rare_partners: set[str] = field(default_factory=set)
    dormant_partners: set[str] = field(default_factory=set)
    row_badges: pd.DataFrame = field(default_factory=pd.DataFrame)
    partner_summary: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def compute_partner_signals(df: pd.DataFrame | None, settings: Any) -> PartnerSignalResult:
    """GL df 에서 거래처 단위 첫등장/희소/휴면재활성 신호를 계산.

    trading_partner 가 null/'' 인 행은 실제 거래처가 아니라 신호 대상에서 제외한다.
    """
    result = PartnerSignalResult()
    if df is None or "trading_partner" not in df.columns:
        result.warnings.append("trading_partner 컬럼 부재 — 거래처 신호 스킵")
        result.row_badges = _empty_badges(df)
        return result

    # §3 데이터주도 — 임계값은 전부 settings 에서 read.
    rare_quantile = float(getattr(settings, "partner_rare_quantile", 0.10))
    dormant_days = int(getattr(settings, "partner_dormant_inactive_days", 180))
    min_population = int(getattr(settings, "partner_signal_min_population", 50))

    partner = df["trading_partner"].astype("string")
    valid = partner.notna() & (partner.str.strip() != "")
    year = _resolve_year(df)
    if year is None:
        result.warnings.append("fiscal_year/posting_date 부재 — 거래처 신호 스킵")
        result.row_badges = _empty_badges(df)
        return result

    valid = valid & year.notna()
    distinct_years = sorted(year[valid].dropna().unique().tolist())
    current_year = distinct_years[-1] if distinct_years else None

    # 거래처별 등장 연도 집합 (first-seen / dormant 판정 근거).
    pv = pd.DataFrame({"partner": partner[valid], "year": year[valid]}).dropna()
    years_by_partner = pv.groupby("partner")["year"].agg(set)

    if len(distinct_years) < 2:
        result.warnings.append(
            "단일 연도 데이터 — 첫등장/휴면재활성은 다년 비교 필요, rare 만 산출"
        )
    else:
        prior_years = {y for y in distinct_years if y != current_year}
        result.first_seen_partners = {
            str(p)
            for p, yrs in years_by_partner.items()
            if current_year in yrs and not (yrs & prior_years)
        }
        result.dormant_partners = _dormant_partners(
            df, partner, year, valid, current_year, dormant_days, years_by_partner
        )

    result.rare_partners = _rare_partners(
        partner, year, valid, current_year, rare_quantile, min_population, result.warnings
    )

    result.row_badges = _build_badges(df, partner, valid, result)
    result.partner_summary = _build_partner_summary(df, partner, valid, result)
    return result


def _resolve_year(df: pd.DataFrame) -> pd.Series | None:
    """fiscal_year 우선, 없으면 posting_date 에서 연도 도출."""
    if "fiscal_year" in df.columns:
        return pd.to_numeric(df["fiscal_year"], errors="coerce")
    if "posting_date" in df.columns:
        return pd.to_datetime(df["posting_date"], errors="coerce").dt.year
    return None


def _rare_partners(
    partner: pd.Series,
    year: pd.Series,
    valid: pd.Series,
    current_year: Any,
    rare_quantile: float,
    min_population: int,
    warnings: list[str],
) -> set[str]:
    """당기 거래처별 txn count 하위 분위수 이하를 rare 로. 모집단 부족 시 빈 set."""
    cur_mask = valid & (year == current_year)
    counts = partner[cur_mask].value_counts()
    if len(counts) < min_population:
        warnings.append(
            f"당기 거래처 {len(counts)} < min_population({min_population}) — rare 산출 스킵"
        )
        return set()
    threshold = counts.quantile(rare_quantile)
    return {str(p) for p in counts[counts <= threshold].index}


def _dormant_partners(
    df: pd.DataFrame,
    partner: pd.Series,
    year: pd.Series,
    valid: pd.Series,
    current_year: Any,
    dormant_days: int,
    years_by_partner: pd.Series,
) -> set[str]:
    """휴면재활성: 전기 활동 有 + **직전 회계연도 결번**(밀도 무관 가드) +
    마지막 전기 활동~당기 첫 활동 gap ≥ dormant_days.

    직전 연도 결번 조건이 없으면 매년 꾸준한 거래처도 연 단위 간격(≈365d)만으로 잡혀
    오탐이 된다(sparse cadence 함정). 두 조건을 함께 걸어 밀도에 의존하지 않는다.
    """
    if "posting_date" not in df.columns:
        return set()
    prev_year = current_year - 1
    year_skipped = {
        str(p)
        for p, yrs in years_by_partner.items()
        if current_year in yrs and prev_year not in yrs and any(y < prev_year for y in yrs)
    }
    if not year_skipped:
        return set()
    posting = pd.to_datetime(df["posting_date"], errors="coerce")
    work = pd.DataFrame({"partner": partner, "year": year, "pd": posting})[valid].dropna(
        subset=["partner", "year", "pd"]
    )
    prior_last = work[work["year"] < current_year].groupby("partner")["pd"].max()
    cur_first = work[work["year"] == current_year].groupby("partner")["pd"].min()
    gap_days = (cur_first - prior_last).dropna().dt.days
    gap_ok = {str(p) for p in gap_days[gap_days >= dormant_days].index}
    return year_skipped & gap_ok


def _build_badges(
    df: pd.DataFrame, partner: pd.Series, valid: pd.Series, result: PartnerSignalResult
) -> pd.DataFrame:
    """df.index 정렬 3 독립 bool 컬럼. 점수 비병합(배지 전용)."""
    badges = pd.DataFrame(index=df.index)
    valid_bool = valid.fillna(False).astype(bool)
    badges["is_first_seen_partner"] = (
        valid_bool & partner.isin(result.first_seen_partners)
    ).astype(bool)
    badges["is_rare_partner"] = (valid_bool & partner.isin(result.rare_partners)).astype(bool)
    badges["is_dormant_partner"] = (valid_bool & partner.isin(result.dormant_partners)).astype(bool)
    return badges


def _build_partner_summary(
    df: pd.DataFrame, partner: pd.Series, valid: pd.Series, result: PartnerSignalResult
) -> list[dict[str, Any]]:
    """신호 거래처를 고액/대량 순 정렬. 금액 게이트 없음(§3 — 소액도 전수 노출)."""
    signaled = result.first_seen_partners | result.rare_partners | result.dormant_partners
    if not signaled:
        return []
    debit = pd.to_numeric(df.get("debit_amount"), errors="coerce").fillna(0.0)
    credit = pd.to_numeric(df.get("credit_amount"), errors="coerce").fillna(0.0)
    magnitude = (debit + credit).abs()
    rows: list[dict[str, Any]] = []
    for p in signaled:
        mask = valid & (partner == p)
        subset = df[mask]
        signals = []
        if p in result.first_seen_partners:
            signals.append("first_seen")
        if p in result.rare_partners:
            signals.append("rare")
        if p in result.dormant_partners:
            signals.append("dormant")
        rows.append(
            {
                "partner": p,
                "signals": signals,
                "txn_count": int(mask.sum()),
                "total_amount": float(magnitude[mask].sum()),
                "content_groups": _content_groups(subset),
            }
        )
    rows.sort(key=lambda r: (-r["total_amount"], -r["txn_count"]))
    return rows


def _content_groups(subset: pd.DataFrame) -> list[dict[str, Any]]:
    """거래처 거래를 gl_account·document_type 별로 묶어 요약."""
    keys = [c for c in ("gl_account", "document_type") if c in subset.columns]
    if not keys:
        return []
    grouped = subset.groupby(keys, dropna=False).size().reset_index(name="count")
    grouped = grouped.sort_values("count", ascending=False)
    return [
        {**{k: str(row[k]) for k in keys}, "count": int(row["count"])}
        for _, row in grouped.iterrows()
    ]


def _empty_badges(df: pd.DataFrame | None) -> pd.DataFrame:
    index = df.index if df is not None else pd.Index([])
    badges = pd.DataFrame(index=index)
    for col in BADGE_COLUMNS:
        badges[col] = False
    return badges
