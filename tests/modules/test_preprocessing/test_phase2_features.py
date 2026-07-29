"""PHASE2 전용 입력 프레임 — 허용 목록과 전용 파생의 계약."""

from __future__ import annotations

import pandas as pd

from src.preprocessing.constants import LEAKAGE_DENY_COLUMNS
from src.preprocessing.phase2_features import (
    PHASE2_SOURCE_COLUMNS,
    build_phase2_input_frame,
)


def _ledger() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "document_id": ["d1", "d2", "d3"],
            "gl_account": ["4000", "5000", "6000"],
            "local_amount": [10_000_000.0, 9_873_412.0, -5_000.0],
            "debit_amount": [10_000_000.0, 9_873_412.0, 0.0],
            "credit_amount": [0.0, 0.0, 5_000.0],
            "trading_partner": ["A", "B", "C"],
            "posting_date": pd.to_datetime(
                ["2024-01-05 23:10:00", "2024-03-01 09:00:00", "2024-06-06 14:30:00"]
            ),
            "document_date": pd.to_datetime(["2024-01-01", "2024-03-01", "2024-06-01"]),
            "approval_date": pd.to_datetime(["2024-01-06", None, None]),
            "delivery_date": pd.to_datetime(["2024-01-02", None, "2024-06-03"]),
            # PHASE1 이 룰용으로 만든 파생 — 허용 목록에 없으므로 들어오면 안 된다.
            "is_near_threshold": [True, False, False],
            "near_threshold_gap_ratio": [0.1, 0.2, 0.3],
            "amount_magnitude": [7.0, 6.9, 3.7],
            "description_both_missing": [False, False, True],
            "anomaly_score": [0.9, 0.1, 0.2],
        }
    )


def test_phase1_rule_features_never_enter_phase2_input():
    """3-surface 비병합은 점수만이 아니라 입력에서도 성립해야 한다."""
    frame = build_phase2_input_frame(_ledger())

    for column in (
        "is_near_threshold",
        "near_threshold_gap_ratio",
        "amount_magnitude",
        "description_both_missing",
        "anomaly_score",
    ):
        assert column not in frame.columns, column


def test_phase2_derived_features_cover_only_unrepresentable_axes():
    """파생은 원본으로 표현할 수 없는 것에만 만든다 — 날짜·마스터·금액 구조."""
    frame = build_phase2_input_frame(_ledger())
    derived = set(frame.attrs["phase2_derived_columns"])

    # 날짜: datetime 원본은 크기 비교가 무의미하므로 주기 성분과 간격으로 바꾼다.
    assert {"p2_posting_dow", "p2_posting_hour", "p2_is_holiday"} <= derived
    assert "p2_days_posting_minus_document" in derived
    assert "p2_days_approval_minus_posting" in derived
    # 금액 구조: 로그 변환에서 소실되는 축.
    assert {"p2_amount_trailing_zeros", "p2_amount_first_digit"} <= derived

    # 원본 날짜는 파생 재료일 뿐 그대로 넘기지 않는다.
    for column in ("posting_date", "document_date", "approval_date", "delivery_date"):
        assert column not in frame.columns


def test_phase2_amount_structure_survives_log_transform():
    """라운드넘버와 첫자리는 금액 크기와 다른 축이다."""
    frame = build_phase2_input_frame(_ledger())

    zeros = frame["p2_amount_trailing_zeros"].tolist()
    digits = frame["p2_amount_first_digit"].tolist()
    # 10,000,000 은 끝자리 0 이 7개, 9,873,412 는 0개 — 크기는 거의 같다.
    assert zeros[0] > zeros[1]
    assert digits[:2] == ["1", "9"]


def test_allow_list_and_deny_list_never_overlap():
    """허용 목록에 차단 대상이 섞이면 즉시 실패한다.

    허용이 1차 관문이 된 뒤 deny 는 발동하지 않는다(실측: 겹침 0). 그래서 deny 는
    죽은 코드가 아니라 **허용 목록의 가드레일**로 역할이 바뀐다 — 누군가 위험한 칸을
    허용 목록에 추가하는 순간 이 테스트가 잡는다.
    """
    overlap = set(PHASE2_SOURCE_COLUMNS) & LEAKAGE_DENY_COLUMNS
    assert not overlap, f"허용 목록에 차단 대상이 있다: {sorted(overlap)}"
