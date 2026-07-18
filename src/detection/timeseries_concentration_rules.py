"""시계열 당기내 집중 — 계정별 × 일/주/월 축별 robust-z 로 "그 해 자신의 리듬" 대비 몰림 판정.

Why: PHASE1-2 자기 큐(2026-07-15 신설). D01/D02 는 **전기 대비**만 본다. "당기(그 해) 안에서
     특정 시점에 거래가 몰린다"는 D01/D02 가 못 보는 별개 차원이다(ACFE 결산 직전 이례적 집중).
     baseline 이 전기가 아니라 그 계정·그 해 자신의 median/MAD 이므로 전기 데이터 없이 성립한다.
     점수 비병합 — row anomaly_score 무기여, 전표 tier 미참여.

축별 독립: 일/주/월을 복합키로 묶지 않는다. 일 축은 "하루 몰림"(결산 직전 burst)을, 월 축은
     "한 달 몰림"을 본다 — 일별로는 평범한데 한 달에 몰린 경우를 일 축은 못 본다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.detection.timeseries_rules import _robust_z

# Why: (일=D, 주=W, 월=M) pandas period alias. 축 이름은 finding.axis 로 노출된다.
_AXIS_FREQ: dict[str, str] = {"day": "D", "week": "W", "month": "M"}


@dataclass
class TimeseriesConcentrationResult:
    """축별 finding. findings 는 신호 강도(robust_z) 내림차순."""

    findings: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def compute_timeseries_concentration_findings(
    df: pd.DataFrame | None,
    settings: Any,
) -> TimeseriesConcentrationResult:
    """GL df 에서 계정·연도별로 일/주/월 축의 당기 내 집중 finding 을 산출."""
    result = TimeseriesConcentrationResult()
    if df is None or df.empty or "posting_date" not in df.columns:
        result.warnings.append("posting_date 컬럼 부재 — 시계열 당기내 집중 스킵")
        return result
    if "gl_account" not in df.columns:
        result.warnings.append("gl_account 컬럼 부재 — 시계열 당기내 집중 스킵")
        return result

    work = _prepare(df, fiscal_year_start=int(getattr(settings, "fiscal_year_start", 1)))
    if work.empty:
        result.warnings.append("posting_date 파싱 가능한 행 없음 — 시계열 당기내 집중 스킵")
        return result

    min_buckets = int(settings.ts_concentration_min_buckets)
    min_buckets_seasonal = int(settings.ts_concentration_min_buckets_seasonal)
    z_threshold = float(settings.ts_concentration_zscore)
    min_docs = int(settings.ts_concentration_min_docs)

    for axis, freq in _AXIS_FREQ.items():
        result.findings.extend(
            _axis_findings(
                work=work,
                axis=axis,
                freq=freq,
                min_buckets=min_buckets,
                min_buckets_seasonal=min_buckets_seasonal,
                z_threshold=z_threshold,
                min_docs=min_docs,
            )
        )
    result.findings.sort(key=lambda item: (-item["robust_z"], -item["total_amount"]))
    return result


def _prepare(df: pd.DataFrame, *, fiscal_year_start: int) -> pd.DataFrame:
    """계정·연도·전기일·전표·금액·계절성 레인만 남긴 작업 프레임.

    fiscal_year 없으면 전기일에서 도출. 계절성 레인은 회계기수(fiscal_year_start 기준) 로
    산출하며 기수 % 3 == 0 이면 분기말이다 — 달 번호를 리터럴로 박지 않는다(3월 결산 회사도 성립).
    """
    posting = pd.to_datetime(df["posting_date"], errors="coerce")
    fiscal_period = (posting.dt.month - fiscal_year_start) % 12 + 1
    seasonal_lane = fiscal_period.mod(3).eq(0).map({True: "period_end", False: "regular"})
    debit = pd.to_numeric(df.get("debit_amount"), errors="coerce").fillna(0.0)
    credit = pd.to_numeric(df.get("credit_amount"), errors="coerce").fillna(0.0)
    year = (
        pd.to_numeric(df["fiscal_year"], errors="coerce")
        if "fiscal_year" in df.columns
        else posting.dt.year
    )
    doc = (
        df["document_id"].astype(str)
        if "document_id" in df.columns
        else pd.Series(df.index.astype(str), index=df.index)
    )
    work = pd.DataFrame(
        {
            "gl_account": df["gl_account"].astype(str).str.strip(),
            "fiscal_year": year,
            "posting": posting,
            "seasonal_lane": seasonal_lane,
            "document_id": doc,
            "amount": (debit + credit).abs(),
        }
    )
    return work[work["posting"].notna() & work["fiscal_year"].notna()]


def _axis_findings(
    *,
    work: pd.DataFrame,
    axis: str,
    freq: str,
    min_buckets: int,
    min_buckets_seasonal: int,
    z_threshold: float,
    min_docs: int,
) -> list[dict[str, Any]]:
    bucketed = work.assign(bucket=work["posting"].dt.to_period(freq).astype(str))
    grouped = bucketed.groupby(
        ["gl_account", "fiscal_year", "seasonal_lane", "bucket"], dropna=False
    ).agg(
        doc_count=("document_id", "nunique"),
        total_amount=("amount", "sum"),
    )

    findings: list[dict[str, Any]] = []
    for (account, fiscal_year, lane), frame in grouped.groupby(
        level=["gl_account", "fiscal_year", "seasonal_lane"]
    ):
        counts = frame["doc_count"]
        # Why: 활성 버킷만으로 baseline 을 만든다. 빈 날짜를 0 으로 채우면 희소 계정은
        #      median=0·MAD=0 이 되어 어떤 활동이든 이상으로 튄다.
        required = min_buckets_seasonal if lane == "period_end" else min_buckets
        if len(counts) < required:
            continue
        median = float(counts.median())
        mad = float((counts - median).abs().median())
        iqr = float(counts.quantile(0.75) - counts.quantile(0.25))
        for (_, _, _, bucket), row in frame.iterrows():
            doc_count = int(row["doc_count"])
            if doc_count < min_docs:
                continue
            z = _robust_z(float(doc_count), median, mad, iqr)
            if z < z_threshold:
                continue
            findings.append(
                {
                    "axis": axis,
                    "seasonal_lane": str(lane),
                    "gl_account": str(account),
                    "fiscal_year": int(fiscal_year),
                    "bucket": str(bucket),
                    "doc_count": doc_count,
                    "total_amount": float(row["total_amount"]),
                    "baseline_median": median,
                    "baseline_mad": mad,
                    "active_buckets": int(len(counts)),
                    "robust_z": float(z),
                    # Why: macro 큐는 review_score 로 정렬 후 top_n 절단한다. robust_z 는 상한이
                    #      없어 그대로 넣으면 Benford(0~1)·D02(0~1) finding 을 밀어낸다.
                    #      z/(z+임계) 포화 변환으로 [0,1) 에 넣는다 — z=임계일 때 0.5.
                    "macro_priority_score": float(z / (z + z_threshold)) if z > 0 else 0.0,
                    "finding_severity": "strong" if z >= 2 * z_threshold else "moderate",
                }
            )
    return findings
