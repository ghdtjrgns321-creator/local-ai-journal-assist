"""시계열 당기내 집중 — 계정별 × 일/주/월 축별 robust-z 자기 큐.

Why: D01/D02 는 전기 대비만 본다. "당기 안에서 특정 시점에 몰린다"는 별개 차원이며
     baseline 이 그 계정·그 해 자신의 리듬이라 전기 데이터 없이도 성립한다(ACFE 결산 직전 집중).
"""

from __future__ import annotations

import pandas as pd
import pytest
from src.detection.timeseries_concentration_rules import compute_timeseries_concentration_findings

from config.settings import AuditSettings


@pytest.fixture
def settings() -> AuditSettings:
    return AuditSettings(
        ts_concentration_min_buckets=6,
        ts_concentration_zscore=3.5,
        ts_concentration_min_docs=10,
    )


def _rows(dates: list[str], account: str, docs_per_date: int, amount: float = 1000.0):
    out = []
    for date in dates:
        for i in range(docs_per_date):
            out.append(
                {
                    "gl_account": account,
                    "fiscal_year": 2024,
                    "posting_date": date,
                    "document_id": f"{account}-{date}-{i}",
                    "debit_amount": amount,
                    "credit_amount": 0.0,
                }
            )
    return out


def _frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["posting_date"] = pd.to_datetime(df["posting_date"])
    return df


def _steady_month(account: str = "5101", docs: int = 10) -> list[dict]:
    """매월 15일에 같은 양 — 리듬이 일정한 정상 계정."""
    return _rows([f"2024-{m:02d}-15" for m in range(1, 13)], account, docs)


def test_missing_posting_date_skips_with_warning(settings) -> None:
    df = pd.DataFrame({"gl_account": ["5101"], "debit_amount": [1.0]})

    result = compute_timeseries_concentration_findings(df, settings)

    assert result.findings == []
    assert any("posting_date" in w for w in result.warnings)


def test_steady_rhythm_yields_no_findings(settings) -> None:
    """자기 리듬이 일정하면 finding 0 — 정상 과탐 방지."""
    result = compute_timeseries_concentration_findings(_frame(_steady_month()), settings)

    assert result.findings == []


def test_daily_burst_is_detected(settings) -> None:
    rows = _steady_month()
    rows += _rows(["2024-06-20"], "5101", 300)  # 평소 10건 → 하루 300건

    result = compute_timeseries_concentration_findings(_frame(rows), settings)

    day_findings = [f for f in result.findings if f["axis"] == "day"]
    assert len(day_findings) == 1
    assert day_findings[0]["bucket"] == "2024-06-20"
    assert day_findings[0]["gl_account"] == "5101"
    assert day_findings[0]["doc_count"] == 300
    assert day_findings[0]["robust_z"] >= settings.ts_concentration_zscore


def test_month_concentration_without_daily_burst(settings) -> None:
    """일별로는 평범한데 한 달에 몰린 경우 — 일 축은 못 보고 월 축이 잡는다."""
    rows = _rows([f"2024-{m:02d}-15" for m in range(1, 13)], "5101", 10)
    # 3월에만 20일간 매일 10건 — 일별 10건은 평소와 같지만 월 합계는 폭증
    rows += _rows([f"2024-03-{d:02d}" for d in range(1, 21)], "5101", 10)

    result = compute_timeseries_concentration_findings(_frame(rows), settings)

    axes = {f["axis"] for f in result.findings}
    assert "month" in axes
    month_findings = [f for f in result.findings if f["axis"] == "month"]
    assert month_findings[0]["bucket"] == "2024-03"
    assert "day" not in axes


def test_bucket_below_min_docs_is_skipped(settings) -> None:
    """전표 수 하한 미만 burst 는 finding 아님."""
    rows = _rows([f"2024-{m:02d}-15" for m in range(1, 13)], "5101", 1)
    rows += _rows(["2024-06-20"], "5101", 5)  # 5건 < min_docs(10)

    result = compute_timeseries_concentration_findings(_frame(rows), settings)

    assert result.findings == []


def test_too_few_buckets_is_skipped(settings) -> None:
    """활성 버킷이 적으면 자기 리듬 baseline 을 못 만든다 → 스킵."""
    rows = _rows(["2024-01-15", "2024-02-15"], "5101", 10)
    rows += _rows(["2024-03-15"], "5101", 500)

    result = compute_timeseries_concentration_findings(_frame(rows), settings)

    assert [f for f in result.findings if f["axis"] == "month"] == []


def test_accounts_are_independent(settings) -> None:
    """계정별 독립 — 한 계정의 폭증이 다른 정상 계정을 오염시키지 않는다."""
    rows = _steady_month("5101")
    rows += _steady_month("5202")
    rows += _rows(["2024-06-20"], "5202", 300)

    result = compute_timeseries_concentration_findings(_frame(rows), settings)

    assert {f["gl_account"] for f in result.findings} == {"5202"}


def test_fiscal_years_are_independent(settings) -> None:
    """당기 내 baseline — 연도를 섞어 비교하지 않는다(그건 D01/D02 소관)."""
    rows = _steady_month()
    rows_2023 = [
        dict(
            r,
            fiscal_year=2023,
            posting_date=r["posting_date"].replace("2024", "2023"),
            document_id=r["document_id"] + "-23",
        )
        for r in _steady_month()
    ]

    result = compute_timeseries_concentration_findings(_frame(rows + rows_2023), settings)

    assert result.findings == []


def test_priority_score_is_bounded_for_macro_queue(settings) -> None:
    """macro 큐 정렬용 점수는 0~1 — 다른 finding 의 review_score 와 스케일이 섞이면 top_n 을 독식한다."""
    rows = _steady_month()
    rows += _rows(["2024-06-20"], "5101", 5000)

    result = compute_timeseries_concentration_findings(_frame(rows), settings)

    assert result.findings
    for finding in result.findings:
        assert 0.0 <= finding["macro_priority_score"] <= 1.0
