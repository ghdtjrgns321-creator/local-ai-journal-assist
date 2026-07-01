"""Phase 4 badge_tags 통합 필드 — 헬퍼 + 집계 검증.

Why: 거래처 배지(first_seen/rare/dormant) + off_time + L4-06/L3-12 + weak_evidence 를
     한 리스트로 통합. **점수 비병합**(배지가 priority_score·band 무영향)이 핵심 불변식.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from config.settings import get_settings
from src.detection.base import DetectionResult, RuleFlag
from src.detection.phase1_case_builder import (
    _compose_badge_tags,
    _partner_badges_for_positions,
    build_phase1_case_result,
)
from src.models.phase1_case import CaseGroupResult
from src.models.phase1_unit import DocumentUnit


def _badges(first=(), rare=(), dormant=()):
    """positional 배지 DataFrame — 지정 위치만 True."""
    n = 5
    df = pd.DataFrame(
        {
            "is_first_seen_partner": [i in first for i in range(n)],
            "is_rare_partner": [i in rare for i in range(n)],
            "is_dormant_partner": [i in dormant for i in range(n)],
        }
    )
    return df


def test_partner_badges_positional_any():
    badges = _badges(first=(1,), rare=(3,))
    # position 1 은 first_seen, 3 은 rare
    assert _partner_badges_for_positions(badges, [1]) == {"first_seen_partner"}
    assert _partner_badges_for_positions(badges, [3]) == {"rare_partner"}
    assert _partner_badges_for_positions(badges, [1, 3]) == {
        "first_seen_partner",
        "rare_partner",
    }
    assert _partner_badges_for_positions(badges, [0, 2, 4]) == set()


def test_partner_badges_none_or_empty_graceful():
    assert _partner_badges_for_positions(None, [0, 1]) == set()
    assert _partner_badges_for_positions(pd.DataFrame(), [0]) == set()
    assert _partner_badges_for_positions(_badges(first=(0,)), []) == set()


def test_compose_off_time_and_rules():
    tags = _compose_badge_tags(
        partner_tags={"first_seen_partner"},
        time_severity_score=2,
        fired_rule_ids={"L4-06", "L3-12", "L1-01"},
        weak_tags=["is_round_number"],
    )
    assert "first_seen_partner" in tags
    assert "off_time" in tags  # time_severity>0
    assert "batch_posting_outlier" in tags  # L4-06
    assert "work_scope_excess" in tags  # L3-12
    assert "is_round_number" in tags  # weak
    assert tags == sorted(tags)  # 정렬


def test_compose_no_signal_empty():
    tags = _compose_badge_tags(
        partner_tags=set(),
        time_severity_score=0,
        fired_rule_ids={"L1-01", "L2-03"},
    )
    assert tags == []


def test_compose_dedup():
    # 같은 태그가 여러 소스에서 와도 1건
    tags = _compose_badge_tags(
        partner_tags={"rare_partner"},
        time_severity_score=0,
        fired_rule_ids=set(),
        weak_tags=["rare_partner", "rare_partner"],
    )
    assert tags == ["rare_partner"]


def test_model_fields_default_empty():
    # badge_tags 필드가 두 모델에 존재하고 기본 빈 리스트
    case = CaseGroupResult(case_id="c1", primary_theme="t", case_key="k")
    assert case.badge_tags == []
    unit = DocumentUnit(unit_id="d1")
    assert unit.badge_tags == []


def test_integration_first_seen_partner_badge_on_case():
    """다년 df에서 당기(2024) 신규 거래처가 flagged → case.badge_tags에 first_seen_partner."""
    df = pd.DataFrame(
        {
            "document_id": ["D22", "D23", "D24"],
            "fiscal_year": [2022, 2023, 2024],
            "posting_date": pd.to_datetime(["2022-03-01", "2023-03-01", "2024-03-01"]),
            "created_by": ["kim", "kim", "kim"],
            "business_process": ["P2P", "P2P", "P2P"],
            "gl_account": ["410000", "410000", "410000"],
            "debit_amount": [1_000_000.0, 1_000_000.0, 9_000_000.0],
            "credit_amount": [0.0, 0.0, 0.0],
            "company_code": ["kr01", "kr01", "kr01"],
            "trading_partner": ["P_KNOWN", "P_KNOWN", "P_NEW_2024"],
            "document_type": ["SA", "SA", "SA"],
        }
    )
    # 당기(2024, index 2) 행만 flag → 그 case 의 거래처 P_NEW_2024 는 first-seen.
    details = pd.DataFrame({"L1-05": [0.0, 0.0, 0.8]}, index=df.index)
    result = build_phase1_case_result(
        df,
        [
            DetectionResult(
                track_name="layer_b",
                flagged_indices=[2],
                scores=details.max(axis=1),
                rule_flags=[RuleFlag("L1-05", "SelfApproval", 4, 1, len(df))],
                details=details,
                metadata={"elapsed": 0.01},
            )
        ],
        company_id="kr01",
        batch_id="b1",
        dataset_id=None,
        phase1_case_config={"phase1_case": {"top_n_cases": 50, "top_n_per_theme": 10}},
        generated_at=datetime(2026, 7, 1, tzinfo=UTC),
        settings=get_settings(),
    )
    assert result.cases, "case 가 최소 1건 생성돼야 함"
    all_badges = {tag for case in result.cases for tag in case.badge_tags}
    assert "first_seen_partner" in all_badges
