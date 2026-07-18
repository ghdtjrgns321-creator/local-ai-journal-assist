"""라운드넘버 밀집도 — 계정·월·작성자 축별 이항검정 자기 큐.

Why: 단건 is_round_number 는 배지이고, 본 모듈은 "이 계정/이 달/이 사람이 통째로 둥근
     금액에 쏠렸나"를 모집단 단위로 본다(AS2401 §61(e), Benford 동렬).
     baseline 은 원장 자체의 round 비율 — 산업별 정상 둥근 금액률 차이를 흡수한다.
"""

from __future__ import annotations

import pandas as pd
import pytest

from config.settings import AuditSettings
from src.detection.round_density_rules import compute_round_density_findings


@pytest.fixture
def settings() -> AuditSettings:
    return AuditSettings(
        round_density_min_sample=100,
        round_density_alpha=0.01,
        round_density_strong_alpha=0.0001,
        round_density_min_excess=0.05,
    )


def _frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


_USERS = 5
_MONTHS = 12


def _uniform_rows(n: int, round_every: int, account: str = "5101") -> list[dict[str, object]]:
    """round 비율 = 1/round_every 이고 **모든 축에 균일하게 퍼진** 모집단.

    주의: round 여부를 `i % round_every` 로 정하면 축과 상관된다 —
    round_every(20)가 사용자 수(5)의 배수라 둥근 금액이 전부 U00 에 몰려
    "정상인데 finding 이 뜬다". 사용자·월과 독립인 블록 인덱스로 round 를 정해
    각 사용자·각 월이 똑같이 1/round_every 를 갖게 한다.
    """
    block = _USERS * _MONTHS
    return [
        {
            "gl_account": account,
            "posting_date": f"2024-{((i // _USERS) % _MONTHS) + 1:02d}-15",
            "created_by": f"U{i % _USERS:02d}",
            "is_round_number": ((i // block) % round_every == 0),
        }
        for i in range(n)
    ]


def test_missing_is_round_number_column_skips_with_warning(settings) -> None:
    df = _frame([{"gl_account": "5101", "posting_date": "2024-01-15", "created_by": "U01"}])

    result = compute_round_density_findings(df, settings)

    assert result.findings == []
    assert any("is_round_number" in w for w in result.warnings)


def test_uniform_population_yields_no_findings(settings) -> None:
    """모든 그룹의 round 비율이 baseline 과 같으면 finding 0 — 정상 과탐 방지."""
    result = compute_round_density_findings(_frame(_uniform_rows(1200, round_every=20)), settings)

    assert result.findings == []
    assert result.baseline_ratio == pytest.approx(0.05, abs=0.01)


def test_account_axis_detects_round_concentrated_account(settings) -> None:
    rows = _uniform_rows(1000, round_every=20, account="5101")
    rows += [
        {
            "gl_account": "9999",
            "posting_date": "2024-03-15",
            "created_by": "U01",
            "is_round_number": True,
        }
        for _ in range(200)
    ]

    result = compute_round_density_findings(_frame(rows), settings)

    account_findings = [f for f in result.findings if f["axis"] == "gl_account"]
    assert len(account_findings) == 1
    finding = account_findings[0]
    assert finding["group_key"] == "9999"
    assert finding["sample_size"] == 200
    assert finding["round_count"] == 200
    assert finding["round_ratio"] == pytest.approx(1.0)
    assert finding["finding_severity"] == "strong"
    assert finding["excess"] > settings.round_density_min_excess


def test_created_by_axis_is_independent_of_account_axis(settings) -> None:
    """축별 독립 — 작성자 집중은 계정이 정상이어도 작성자 레인에서 잡힌다."""
    rows = _uniform_rows(1000, round_every=20, account="5101")
    rows += [
        {
            "gl_account": "5101",
            "posting_date": "2024-04-15",
            "created_by": "SUSPECT",
            "is_round_number": True,
        }
        for _ in range(150)
    ]

    result = compute_round_density_findings(_frame(rows), settings)

    user_findings = [f for f in result.findings if f["axis"] == "created_by"]
    assert [f["group_key"] for f in user_findings] == ["SUSPECT"]


def test_small_group_below_min_sample_is_skipped(settings) -> None:
    """표본 미달 그룹은 100% round 여도 finding 아님 — 우연 배제."""
    rows = _uniform_rows(1000, round_every=20, account="5101")
    rows += [
        {
            "gl_account": "8888",
            "posting_date": "2024-05-15",
            "created_by": "U01",
            "is_round_number": True,
        }
        for _ in range(10)
    ]

    result = compute_round_density_findings(_frame(rows), settings)

    assert "8888" not in {f["group_key"] for f in result.findings}


def test_significant_but_tiny_effect_is_not_a_finding(settings) -> None:
    """표본이 크면 사소한 차이도 통계적 유의 — effect size 하한이 막아야 한다."""
    rows = _uniform_rows(20000, round_every=20, account="5101")
    # 6% (baseline 5% + 1%p) — 표본 3000 이면 통계적으로 유의하지만 실무적으로 무의미
    rows += [
        {
            "gl_account": "7777",
            "posting_date": "2024-06-15",
            "created_by": "U01",
            "is_round_number": (i % 100) < 6,
        }
        for i in range(3000)
    ]

    result = compute_round_density_findings(_frame(rows), settings)

    assert "7777" not in {f["group_key"] for f in result.findings}


def test_degenerate_baseline_skips_all_axes(settings) -> None:
    """모든 행이 round 면 baseline=1.0 — 비교 기준이 없으므로 finding 0 + 경고."""
    rows = [
        {
            "gl_account": "5101",
            "posting_date": "2024-01-15",
            "created_by": "U01",
            "is_round_number": True,
        }
        for _ in range(500)
    ]

    result = compute_round_density_findings(_frame(rows), settings)

    assert result.findings == []
    assert any("baseline" in w for w in result.warnings)
