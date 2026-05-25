"""Stage 1 회귀 잠금: priority_floors 가 topic_scoring 으로 덮이지 않는지 검증.

`src/detection/phase1_case_builder.py` 의 `priority_score = max(topic, legacy)` 머지
정책이 회귀되면 본 테스트가 실패한다. macro 이중가산도 함께 차단된다.

테스트 분류:
- anti-disappear: 강한 단일 결함은 0.90 floor 유지
- anti-noise: 약한 단독 context 는 0.90 미만 유지
- composite_sort: 머지로 올라온 점수가 정렬에서 일관되게 사용됨
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from src.detection.base import DetectionResult, RuleFlag
from src.detection.phase1_case_builder import build_phase1_case_result


def _stage1_config(priority_floors: list[dict] | None = None) -> dict:
    """topic_scoring 이 활성화된 최소 config. priority_floors 는 인자로 주입."""

    return {
        "phase1_case": {
            "top_n_cases": 50,
            "top_n_per_theme": 10,
            "priority_band": {"high": 0.90, "medium": 0.75},
            "priority_floors": priority_floors or [],
            "topic_scoring": {},
        }
    }


def _row(
    *,
    document_id: str = "DOC-1",
    gl_account: str = "410000",
    business_process: str = "R2R",
    document_type: str = "SA",
    debit_amount: float = 10_000_000.0,
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "document_id": [document_id],
            "posting_date": pd.to_datetime(["2026-04-30"]),
            "created_by": ["kim"],
            "business_process": [business_process],
            "gl_account": [gl_account],
            "debit_amount": [debit_amount],
            "credit_amount": [0.0],
            "company_code": ["kr01"],
            "trading_partner": ["kr02"],
            "document_type": [document_type],
        }
    )


def _build(
    df: pd.DataFrame,
    rule_id: str,
    *,
    score: float,
    severity: int = 4,
    row_annotations: dict | None = None,
    priority_floors: list[dict] | None = None,
    extra_rule_flags: list[RuleFlag] | None = None,
    extra_details: dict[str, list[float]] | None = None,
):
    details_columns: dict[str, list[float]] = {rule_id: [score]}
    if extra_details:
        details_columns.update(extra_details)
    details = pd.DataFrame(details_columns, index=df.index)
    rule_flags = [RuleFlag(rule_id, rule_id, severity, 1, len(df))]
    if extra_rule_flags:
        rule_flags.extend(extra_rule_flags)
    detection_result = DetectionResult(
        track_name="metadata_policy",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=rule_flags,
        details=details,
        metadata={"row_annotations": row_annotations or {}},
    )
    return build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config=_stage1_config(priority_floors=priority_floors),
        generated_at=datetime(2026, 5, 20, 0, 0, 0, tzinfo=UTC),
    )


# ---- anti-disappear ----------------------------------------------------------


def test_stage1_multiple_core_required_fields_missing_stays_above_090():
    """L1-02 다중 핵심 필드 누락이 topic_scoring 활성 환경에서도 0.90 유지.

    floor 매칭은 ``_hit_missing_fields(hit)`` 가 ``hit.annotation["missing_fields"]`` 를
    읽는 annotation 기반 경로 — row 컬럼 NaN 여부와 무관하다. 따라서 row 의 컬럼이
    실제 채워져 있더라도 row_annotation 에 missing_fields 가 있으면 floor 가 적용된다.
    """

    df = _row()
    floors = [
        {
            "rule_id": "L1-02",
            "missing_fields": [
                "document_id",
                "gl_account",
                "posting_date",
                "debit_amount",
                "credit_amount",
            ],
            "min_matching_missing_fields": 2,
            "min_priority_score": 0.90,
            "reason": "multiple_core_required_fields_missing",
        }
    ]
    result = _build(
        df,
        "L1-02",
        score=0.90,
        row_annotations={
            "L1-02": {
                0: {
                    "missing_fields": ["gl_account", "posting_date", "debit_amount"],
                    "score": 0.90,
                }
            }
        },
        priority_floors=floors,
    )
    assert result.cases, "expected at least one case"
    case = result.cases[0]
    assert case.priority_score >= 0.90, (
        f"priority_score={case.priority_score} (topic 덮어쓰기로 floor가 죽으면 < 0.90)"
    )
    assert "multiple_core_required_fields_missing" in case.priority_adjustment_reasons
    assert case.priority_band == "high"


def test_stage1_sod_direct_critical_stays_above_090():
    """L1-06 raw>=0.95 단독으로 sod_direct_critical floor 0.90 유지."""

    df = _row()
    floors = [
        {
            "rule_id": "L1-06",
            "min_raw_score": 0.95,
            "min_priority_score": 0.90,
            "reason": "sod_direct_critical",
        }
    ]
    result = _build(df, "L1-06", score=0.95, priority_floors=floors)
    case = result.cases[0]
    assert case.priority_score >= 0.90, (
        f"sod_direct_critical: priority_score={case.priority_score} < 0.90"
    )
    assert "sod_direct_critical" in case.priority_adjustment_reasons


def test_stage1_skipped_approval_critical_stays_above_090():
    """L1-04 co-seeder + L1-07 label=immediate 결합의 critical floor 0.90 유지.

    L1-07 단독은 case seed 금지이므로 (light_seeder 정책) co-seeder L1-04 와 결합한다.
    row_annotation 의 ``label`` 키가 _row_display_label 의 매칭 대상.
    """

    df = _row()
    floors = [
        {
            "rule_id": "L1-07",
            "labels": ["immediate"],
            "min_raw_score": 0.85,
            "min_priority_score": 0.90,
            "reason": "skipped_approval_critical",
        }
    ]
    result = _build(
        df,
        "L1-04",
        score=0.85,
        extra_rule_flags=[RuleFlag("L1-07", "L1-07", 4, 1, 1)],
        extra_details={"L1-07": [0.85]},
        row_annotations={"L1-07": {0: {"label": "immediate", "score": 0.85}}},
        priority_floors=floors,
    )
    case = result.cases[0]
    assert case.priority_score >= 0.90, (
        f"skipped_approval_critical: priority_score={case.priority_score} < 0.90"
    )
    assert "skipped_approval_critical" in case.priority_adjustment_reasons


def test_stage1_escalated_self_approval_material_or_sensitive_stays_above_090():
    """L1-05 label=escalated_materiality 의 escalated 자기승인 floor 0.90 유지."""

    df = _row()
    floors = [
        {
            "rule_id": "L1-05",
            "labels": ["escalated_materiality", "escalated_high_risk_account"],
            "min_priority_score": 0.90,
            "reason": "escalated_self_approval_material_or_sensitive",
        }
    ]
    result = _build(
        df,
        "L1-05",
        score=0.85,
        row_annotations={"L1-05": {0: {"label": "escalated_materiality", "score": 0.85}}},
        priority_floors=floors,
    )
    case = result.cases[0]
    assert case.priority_score >= 0.90, (
        f"escalated_self_approval: priority_score={case.priority_score} < 0.90"
    )
    assert "escalated_self_approval_material_or_sensitive" in case.priority_adjustment_reasons


# ---- anti-noise --------------------------------------------------------------


def test_stage1_manual_only_stays_below_090():
    """L3-02 수기 입력 단독은 0.90 미만 유지 (priority_floors 없는 약한 신호)."""

    df = _row()
    result = _build(df, "L3-02", score=0.50, severity=2)
    if not result.cases:
        return  # 단독 약한 신호로 case 가 안 만들어지면 정상
    case = result.cases[0]
    assert case.priority_score < 0.90, (
        f"manual-only L3-02 가 0.90 이상 - 약한 단독 신호 잠금 위반: {case.priority_score}"
    )


def test_stage1_closing_only_stays_below_090():
    """L3-04 결산 집중 단독은 0.90 미만 유지."""

    df = _row()
    result = _build(df, "L3-04", score=0.50, severity=2)
    if not result.cases:
        return
    case = result.cases[0]
    assert case.priority_score < 0.90, (
        f"closing-only L3-04 가 0.90 이상 - 약한 단독 신호 잠금 위반: {case.priority_score}"
    )


def test_stage1_sensitive_only_stays_below_090():
    """L3-10 민감계정 사용 단독은 0.90 미만 유지."""

    df = _row()
    result = _build(
        df,
        "L3-10",
        score=0.50,
        severity=2,
        row_annotations={"L3-10": {0: {"display_label": "priority_case", "score": 0.50}}},
    )
    if not result.cases:
        return
    case = result.cases[0]
    assert case.priority_score < 0.90, (
        f"sensitive-only L3-10 가 0.90 이상 - 약한 단독 신호 잠금 위반: {case.priority_score}"
    )


def test_stage1_weekend_only_stays_below_090():
    """L3-05 주말 전기 단독은 0.90 미만 유지."""

    df = _row()
    result = _build(df, "L3-05", score=0.50, severity=2)
    if not result.cases:
        return
    case = result.cases[0]
    assert case.priority_score < 0.90, (
        f"weekend-only L3-05 가 0.90 이상 - 약한 단독 신호 잠금 위반: {case.priority_score}"
    )


# ---- composite_sort_score / merge sanity -------------------------------------


def test_stage1_legacy_floor_merge_does_not_demote_in_topic_score():
    """legacy floor 로 0.90 진입한 케이스의 priority_score 는 topic 점수보다 우선."""

    df = _row()
    floors = [
        {
            "rule_id": "L1-06",
            "min_raw_score": 0.95,
            "min_priority_score": 0.90,
            "reason": "sod_direct_critical",
        }
    ]
    result = _build(df, "L1-06", score=0.95, priority_floors=floors)
    case = result.cases[0]
    topic_max = max(case.topic_scores.values(), default=0.0)
    assert case.priority_score == pytest.approx(max(topic_max, 0.90)), (
        f"merge mismatch: priority_score={case.priority_score}, topic_max={topic_max}"
    )
    assert case.priority_score >= 0.90


def test_stage1_macro_context_does_not_promote_weak_seed_to_immediate():
    """topic_scoring 활성 상태에서 D01 confirmed macro context 가 약한 시드 (L3-04) 를
    단독으로 0.90 이상으로 끌어올리지 않는다.

    legacy `_apply_macro_context_priority` 는 confirmed_account_shift 에 +0.06 보너스를
    부여하지만, use_topic_scoring=True 경로의 머지 후보는 macro 이전 점수이므로 이 보너스가
    priority_score 에 반영되지 않는다. priority_adjustment_reasons 에도 macro_context=...
    문자열이 들어가지 않아야 audit 표현 정합성이 보장된다.
    """

    df = pd.DataFrame(
        {
            "document_id": ["DOC-MACRO"],
            "posting_date": pd.to_datetime(["2024-12-30"]),
            "created_by": ["kim"],
            "business_process": ["R2R"],
            "gl_account": ["410000"],
            "debit_amount": [80_000_000.0],
            "credit_amount": [0.0],
            "company_code": ["kr01"],
            "fiscal_year": [2024],
            "trading_partner": ["kr02"],
            "document_type": ["SA"],
        }
    )
    details = pd.DataFrame({"L3-04": [0.60]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_c",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[RuleFlag("L3-04", "PeriodEnd", 3, 1, len(df))],
        details=details,
        metadata={
            "account_activity_variance": [
                {
                    "fiscal_year": 2024,
                    "company_code": "kr01",
                    "gl_account": "410000",
                    "review_row_count": 10,
                    "weighted_variance": 0.8,
                    "evaluation_bucket": "confirmed_truth",
                    "precision_policy": "count_as_d01_truth",
                    "d01_target_document_count": 1,
                }
            ],
        },
    )
    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config=_stage1_config(),
        generated_at=datetime(2026, 5, 20, 0, 0, 0, tzinfo=UTC),
    )
    assert result.cases, "expected a case for L3-04 + D01 macro context"
    case = result.cases[0]
    assert case.priority_score < 0.90, (
        f"weak seed + macro context 가 0.90 진입: priority_score={case.priority_score}"
    )
    # macro 보너스가 머지에서 배제되었으므로 audit 사유에도 macro_context=... 가 없어야 한다.
    assert not any("macro_context=" in reason for reason in case.priority_adjustment_reasons), (
        f"use_topic_scoring=True 경로에서 macro_reasons 가 부당하게 audit 사유로 노출됨: "
        f"{case.priority_adjustment_reasons}"
    )
