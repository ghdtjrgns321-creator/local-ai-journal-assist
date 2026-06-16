"""source 신뢰 분류 단위 테스트 — 자동 전표 식별과 위장(단독 자동) 탐지.

Why: fraud-combo floor가 자동 결산 배치 전표(승인 부재가 정상)를 조작 의심 조합으로
     오인하지 않도록, "신뢰 가능한 자동 전표"와 "자동이라 주장하지만 배치 정체성이
     없는 단독 전표(위장 의심)"를 구분한다 (OPEN_ISSUES #14·#16).
"""

from __future__ import annotations

import pandas as pd
from src.detection.source_trust import (
    automated_source_mask,
    lone_automated_mask,
    trusted_automated_mask,
)


def _frame(**overrides) -> pd.DataFrame:
    base = {
        "document_id": [f"D{i}" for i in range(6)],
        "source": ["automated"] * 6,
        "posting_date": ["2024-12-30 02:00:00"] * 6,
        "batch_id": ["B1"] * 6,
        "job_id": ["J1"] * 6,
    }
    base.update(overrides)
    return pd.DataFrame(base)


class TestAutomatedSourceMask:
    def test_automated_and_recurring_are_automated(self) -> None:
        df = _frame(source=["automated", "batch", "system", "recurring", "manual", "adjustment"])
        mask = automated_source_mask(df)
        assert mask.tolist() == [True, True, True, True, False, False]

    def test_missing_source_column_returns_all_false(self) -> None:
        df = _frame().drop(columns=["source"])
        assert not automated_source_mask(df).any()


class TestLoneAutomatedMask:
    def test_lone_without_batch_identity_is_flagged(self) -> None:
        # Why: 자동이라 주장 + batch/job id 없음 + 같은 날 동류가 임계 이하 → 위장 의심
        df = _frame(batch_id=[None] * 6, job_id=[None] * 6)
        mask = lone_automated_mask(df, lone_threshold=10)
        assert mask.all()

    def test_batch_identity_present_is_not_lone(self) -> None:
        df = _frame(batch_id=["B1"] * 6, job_id=[None] * 6)
        assert not lone_automated_mask(df, lone_threshold=10).any()

    def test_crowd_of_same_day_automated_is_not_lone(self) -> None:
        # Why: 같은 날 동류 전표가 임계보다 많으면 정상 배치 무리로 본다
        n = 30
        df = pd.DataFrame(
            {
                "document_id": [f"D{i}" for i in range(n)],
                "source": ["automated"] * n,
                "posting_date": ["2024-12-30 02:00:00"] * n,
                "batch_id": [None] * n,
                "job_id": [None] * n,
            }
        )
        assert not lone_automated_mask(df, lone_threshold=10).any()

    def test_manual_rows_never_lone(self) -> None:
        df = _frame(source=["manual"] * 6, batch_id=[None] * 6, job_id=[None] * 6)
        assert not lone_automated_mask(df, lone_threshold=10).any()


class TestTrustedAutomatedMask:
    def test_trusted_is_automated_minus_lone(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D2", "D3"],
                "source": ["automated", "automated", "manual"],
                "posting_date": ["2024-12-30", "2024-12-31", "2024-12-30"],
                "batch_id": ["B1", None, None],
                "job_id": [None, None, None],
            }
        )
        mask = trusted_automated_mask(df, lone_threshold=10)
        # D1: 자동+배치ID → 신뢰. D2: 자동+정체성 없음+단독 → 비신뢰. D3: 수기 → 자동 아님.
        assert mask.tolist() == [True, False, False]
