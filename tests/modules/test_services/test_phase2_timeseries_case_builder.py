"""`build_timeseries_cases` 의 PHASE2 TimeseriesCase 변환 계약 검증 (S6 Phase D).

Why: v7-plan §S6 invariant #65~68 — timeseries_window_artifact 의 windows 중
``evidence_tier ∈ {strong, moderate}`` AND ``sub_signal_high`` 만 case 화한다.
evidence_signature 는 ``sub_rule + subject + window_start`` 만 (z_score /
daily_count 포함 금지). PHASE1 prior 접근 0건, phase1_case_refs default ().
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from src.detection.base import DetectionResult
from src.models.phase2_case import TimeseriesCase
from src.services.phase2_timeseries_case_builder import (
    TIMESERIES_ORDERING_NATIVE,
    TIMESERIES_ORDERING_TS_PRIMARY_STABILIZED,
    build_timeseries_cases,
)
from tools.scripts.measure_phase2_native_cases_fixed5_20260528 import (
    _timeseries_native_diagnostics,
)


def _make_df() -> pd.DataFrame:
    """3-row timeseries fixture — gl_account + posting_date + document_id 보유."""
    return pd.DataFrame(
        {
            "document_id": ["DOC100", "DOC101", "DOC102"],
            "gl_account": ["5100", "5100", "6200"],
            "posting_date": [
                pd.Timestamp("2025-01-15"),
                pd.Timestamp("2025-01-15"),
                pd.Timestamp("2025-01-20"),
            ],
            "debit_amount": [1_000_000.0, 1_000_000.0, 500_000.0],
            "credit_amount": [0.0, 0.0, 0.0],
            "line_number": [1, 2, 1],
            "company_code": ["C01", "C01", "C01"],
        },
        index=pd.Index([10, 11, 12]),
    )


def _make_result(
    *,
    artifact: dict[str, Any] | None,
    track_name: str = "timeseries",
) -> DetectionResult:
    """timeseries detection result fixture — timeseries_window_artifact 만 다르게 주입."""
    metadata: dict[str, Any] = {}
    if artifact is not None:
        metadata["timeseries_window_artifact"] = artifact
    return DetectionResult(
        track_name=track_name,
        flagged_indices=[],
        scores=pd.Series([0.0, 0.0, 0.0], index=[10, 11, 12]),
        rule_flags=[],
        details=pd.DataFrame(),
        metadata=metadata,
    )


def _strong_window_entry(
    *,
    rule_id: str = "TS01",
    subject: str = "5100",
    window_start: str = "2025-01-15",
    window_end: str = "2025-01-15",
    positions: tuple[int, ...] = (0, 1),
    indices: tuple[Any, ...] = (10, 11),
    daily_count: int = 2,
    z_score: float = 4.0,
    sub_signal_high: bool = True,
    evidence_tier: str = "strong",
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "subject": subject,
        "window_start": window_start,
        "window_end": window_end,
        "row_indices": list(indices),
        "row_positions": list(positions),
        "daily_count": daily_count,
        "window_count": daily_count,
        # detector spec — baseline 미산출 시 None (invariant #69). fixture default 도 정합.
        "expected_count": None,
        "baseline_method": None,
        "baseline_window_days": 28,
        "baseline_observation_count": 0,
        "robust_z": None,
        "period_end_context": False,
        "period_end_day_offset": 0,
        "subject_period_end_historical_ratio": None,
        "subject_non_period_end_baseline_count": None,
        "period_end_expected_count": None,
        "period_end_lift": None,
        "amount_tail_context": 0.0,
        "manual_or_adjustment_context": 0.0,
        "after_hours_or_weekend_context": 0.0,
        "round_amount_context": 0.0,
        "rarity_context_count": 0,
        "context_evidence_count": 0,
        "subject_activity_rank": 1,
        "subject_frequency_context": {
            "subject_total_count": daily_count,
            "subject_rank_percentile": 1.0,
        },
        "z_score": z_score,
        "sub_signal_high": sub_signal_high,
        "evidence_tier": evidence_tier,
    }


def _artifact(windows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "windows": windows,
        "coverage": {
            "TS01": sum(1 for w in windows if w["rule_id"] == "TS01"),
            "TS02": sum(1 for w in windows if w["rule_id"] == "TS02"),
        },
    }


# ─────────────────────────────────────────────────────────────


def test_empty_metadata_returns_empty_tuple():
    """artifact 부재 시 빈 tuple graceful fallback (invariant #68)."""
    result = _make_result(artifact=None)
    cases = build_timeseries_cases(batch_id="b1", detection_result=result, df=_make_df())
    assert cases == ()


def test_strong_tier_with_sub_signal_high_emits_case():
    """strong + sub_signal_high 인 window → TimeseriesCase 1건 생성 (invariant #65)."""
    artifact = _artifact([_strong_window_entry()])
    result = _make_result(artifact=artifact)
    cases = build_timeseries_cases(batch_id="b1", detection_result=result, df=_make_df())
    assert len(cases) == 1
    case = cases[0]
    assert isinstance(case, TimeseriesCase)
    assert case.family == "timeseries"
    assert case.unit_type == "window"
    assert case.sub_rule == "TS01"
    assert case.subject == "5100"
    assert case.window_start == "2025-01-15"
    assert case.evidence_tier == "strong"


def test_strong_tier_without_sub_signal_high_filtered_out():
    """strong 이지만 sub_signal_high=False → case 화 안 함 (Gate, invariant #65)."""
    entry = _strong_window_entry(sub_signal_high=False)
    artifact = _artifact([entry])
    result = _make_result(artifact=artifact)
    cases = build_timeseries_cases(batch_id="b1", detection_result=result, df=_make_df())
    assert cases == ()


def test_weak_tier_excluded():
    """weak tier 는 sub_signal_high 와 무관하게 case 화 안 함."""
    entry = _strong_window_entry(evidence_tier="weak", sub_signal_high=True)
    artifact = _artifact([entry])
    result = _make_result(artifact=artifact)
    cases = build_timeseries_cases(batch_id="b1", detection_result=result, df=_make_df())
    assert cases == ()


def test_moderate_tier_with_sub_signal_high_emits_case():
    """moderate + sub_signal_high → case 생성 (Gate strong OR moderate)."""
    entry = _strong_window_entry(evidence_tier="moderate", sub_signal_high=True)
    artifact = _artifact([entry])
    result = _make_result(artifact=artifact)
    cases = build_timeseries_cases(batch_id="b1", detection_result=result, df=_make_df())
    assert len(cases) == 1
    assert cases[0].evidence_tier == "moderate"


def test_case_id_uses_canonicalized_row_refs():
    """phase2_case_id 가 canonicalize_ref_key 통과한 ref 로 산출되어 환경 무관."""
    artifact = _artifact([_strong_window_entry()])
    result = _make_result(artifact=artifact)
    cases = build_timeseries_cases(batch_id="b1", detection_result=result, df=_make_df())
    assert cases[0].phase2_case_id.startswith("p2_timeseries_window_")
    # row_refs 의 index_label 은 canonical prefix 로 시작 (Phase2RowRef invariant)
    for ref in cases[0].row_refs:
        assert ref.index_label.startswith(("i:", "s:", "ts:", "t:"))


def test_evidence_signature_contains_sub_rule_subject_window():
    """case_generation_reason 의 evidence_signature 는 sub_rule + subject + window_start 만."""
    artifact = _artifact([_strong_window_entry()])
    result = _make_result(artifact=artifact)
    cases = build_timeseries_cases(batch_id="b1", detection_result=result, df=_make_df())
    sig = cases[0].case_generation_reason.get("evidence_signature", "")
    assert "sub_rule=TS01" in sig
    assert "subject=5100" in sig
    assert "window=2025-01-15" in sig


def test_evidence_signature_does_not_include_z_score():
    """evidence_signature 에 z_score / daily_count 같은 raw score 포함 금지 (invariant #55 정합)."""
    entry = _strong_window_entry(z_score=12345.67, daily_count=42)
    artifact = _artifact([entry])
    result = _make_result(artifact=artifact)
    cases = build_timeseries_cases(batch_id="b1", detection_result=result, df=_make_df())
    sig = cases[0].case_generation_reason.get("evidence_signature", "")
    assert "12345" not in sig
    assert "z_score" not in sig
    assert "daily_count" not in sig
    assert "42" not in sig
    assert "expected_count" not in sig
    assert "robust_z" not in sig


def test_phase1_case_refs_empty_by_default():
    """builder 자체는 PHASE1 prior 접근 0건 — phase1_case_refs default () (invariant #67)."""
    artifact = _artifact([_strong_window_entry()])
    result = _make_result(artifact=artifact)
    cases = build_timeseries_cases(batch_id="b1", detection_result=result, df=_make_df())
    assert cases[0].phase1_case_refs == ()


def test_row_refs_index_label_uses_df_index_canonical_form():
    """row_refs 의 index_label 은 df.index[position] 의 canonical 결과 (invariant #66)."""
    artifact = _artifact([_strong_window_entry()])
    result = _make_result(artifact=artifact)
    cases = build_timeseries_cases(batch_id="b1", detection_result=result, df=_make_df())
    case = cases[0]
    # row_positions = (0, 1) → df.index[0] = 10, df.index[1] = 11
    # canonicalize_ref_key(int) = "i:10" / "i:11"
    expected_labels = {"i:10", "i:11"}
    actual = {ref.index_label for ref in case.row_refs}
    assert actual == expected_labels


def test_return_type_is_tuple_of_timeseries_case():
    """반환 타입은 tuple[TimeseriesCase, ...] (invariant #11 정합)."""
    artifact = _artifact([_strong_window_entry()])
    result = _make_result(artifact=artifact)
    cases = build_timeseries_cases(batch_id="b1", detection_result=result, df=_make_df())
    assert isinstance(cases, tuple)
    assert all(isinstance(c, TimeseriesCase) for c in cases)


def test_explicit_native_ordering_preserves_detector_artifact_order():
    """명시 native fallback 은 detector artifact window 순서를 그대로 보존한다."""
    entries = [
        _strong_window_entry(subject="native-first", positions=(0,), indices=(10,)),
        _strong_window_entry(subject="native-second", positions=(1,), indices=(11,)),
        _strong_window_entry(subject="native-third", positions=(2,), indices=(12,)),
    ]
    result = _make_result(artifact=_artifact(entries))

    cases = build_timeseries_cases(
        batch_id="b1",
        detection_result=result,
        df=_make_df(),
        ordering_strategy=TIMESERIES_ORDERING_NATIVE,
    )

    assert [case.subject for case in cases] == [
        "native-first",
        "native-second",
        "native-third",
    ]


def test_explicit_ts_primary_stabilized_ordering_reorders_without_truth_inputs():
    """명시 opt-in strategy 만 v3.1 TS-primary diagnostic ordering 을 적용한다."""
    low = _strong_window_entry(
        subject="low",
        positions=(0,),
        indices=(10,),
        z_score=99.0,
    )
    low.update(
        {
            "period_end_context": False,
            "after_hours_or_weekend_context": 1.0,
            "context_evidence_count": 9,
            "period_end_lift": 99.0,
            "robust_z": 99.0,
            "subject_activity_rank": 99,
        }
    )
    mid = _strong_window_entry(subject="mid", positions=(1,), indices=(11,))
    mid.update(
        {
            "period_end_context": True,
            "round_amount_context": 1.0,
            "after_hours_or_weekend_context": 0.0,
            "context_evidence_count": 1,
            "period_end_lift": 2.0,
            "robust_z": 1.0,
            "subject_activity_rank": 20,
        }
    )
    best = _strong_window_entry(subject="best", positions=(2,), indices=(12,))
    best.update(
        {
            "period_end_context": True,
            "round_amount_context": 0.0,
            "after_hours_or_weekend_context": 1.0,
            "context_evidence_count": 4,
            "period_end_lift": 5.0,
            "robust_z": 3.0,
            "subject_activity_rank": 20,
        }
    )
    result = _make_result(artifact=_artifact([low, mid, best]))

    cases = build_timeseries_cases(
        batch_id="b1",
        detection_result=result,
        df=_make_df(),
        ordering_strategy=TIMESERIES_ORDERING_TS_PRIMARY_STABILIZED,
    )

    assert [case.subject for case in cases] == ["best", "mid", "low"]


def test_unknown_timeseries_ordering_strategy_raises_value_error():
    """명시 strategy 오타는 silent fallback 하지 않는다."""
    result = _make_result(artifact=_artifact([_strong_window_entry()]))

    with pytest.raises(ValueError, match="unsupported timeseries ordering_strategy"):
        build_timeseries_cases(
            batch_id="b1",
            detection_result=result,
            df=_make_df(),
            ordering_strategy="fixed5_truth_rank",  # type: ignore[arg-type]
        )


def test_track_name_mismatch_returns_empty_tuple():
    """detection_result.track_name 이 'timeseries' 가 아니면 빈 tuple (invariant #68)."""
    artifact = _artifact([_strong_window_entry()])
    result = _make_result(artifact=artifact, track_name="duplicate")
    cases = build_timeseries_cases(batch_id="b1", detection_result=result, df=_make_df())
    assert cases == ()


def test_expected_count_none_preserved_in_case_no_zero_fallback():
    """invariant #69 — detector 가 baseline 미산출 (expected_count=None) → case 도 None 보존.

    Why: 이전 구현은 ``float(entry.get("expected_count") or 0.0)`` 로 0.0 fallback.
    daily_count 30 vs expected 0 → 무한 spike 처럼 보여 감사인 오해. None 으로 보존
    하면 UI / case detail 이 "미산출" 명시 가능.
    """
    artifact = _artifact([_strong_window_entry()])
    result = _make_result(artifact=artifact)
    cases = build_timeseries_cases(batch_id="b1", detection_result=result, df=_make_df())
    assert len(cases) >= 1
    assert cases[0].expected_count is None, (
        "detector 가 baseline 산출 안 함 → case.expected_count 는 None 유지. "
        "0.0 fallback 은 감사인 오해 유발 (#69)."
    )


def test_expected_count_propagates_actual_baseline_when_detector_provides():
    """detector 가 baseline 양수 산출 시 case.expected_count 가 그 값 그대로 전달.

    미래 detector 의 baseline 산출 도입 (S6.next family_ecdf enrichment) 회귀 가드.
    """
    entry = _strong_window_entry()
    entry["expected_count"] = 5.5  # detector 가 산출한 baseline 가정
    artifact = _artifact([entry])
    result = _make_result(artifact=artifact)
    cases = build_timeseries_cases(batch_id="b1", detection_result=result, df=_make_df())
    assert len(cases) >= 1
    assert cases[0].expected_count == pytest.approx(5.5)


def test_baseline_payload_preserved_without_builder_recalculation():
    """builder 는 detector artifact 의 baseline payload 를 그대로 전달한다."""
    entry = _strong_window_entry()
    entry.update(
        {
            "window_count": 7,
            "expected_count": 2.5,
            "baseline_method": "subject_trailing_active_day_median",
            "baseline_window_days": 28,
            "baseline_observation_count": 12,
            "robust_z": 3.25,
            "period_end_context": True,
            "period_end_day_offset": 2,
            "subject_period_end_historical_ratio": 0.4,
            "subject_non_period_end_baseline_count": 1.5,
            "period_end_expected_count": 2.0,
            "period_end_lift": 3.5,
            "amount_tail_context": 0.8,
            "manual_or_adjustment_context": 0.5,
            "after_hours_or_weekend_context": 0.5,
            "round_amount_context": 1.0,
            "rarity_context_count": 2,
            "context_evidence_count": 5,
            "subject_activity_rank": 4,
            "subject_frequency_context": {
                "subject_total_count": 99,
                "subject_rank_percentile": 0.2,
            },
        }
    )
    result = _make_result(artifact=_artifact([entry]))

    cases = build_timeseries_cases(batch_id="b1", detection_result=result, df=_make_df())

    assert len(cases) == 1
    case = cases[0]
    assert case.window_count == 7
    assert case.expected_count == pytest.approx(2.5)
    assert case.baseline_method == "subject_trailing_active_day_median"
    assert case.baseline_window_days == 28
    assert case.baseline_observation_count == 12
    assert case.robust_z == pytest.approx(3.25)
    assert case.period_end_context is True
    assert case.period_end_day_offset == 2
    assert case.subject_period_end_historical_ratio == pytest.approx(0.4)
    assert case.subject_non_period_end_baseline_count == pytest.approx(1.5)
    assert case.period_end_expected_count == pytest.approx(2.0)
    assert case.period_end_lift == pytest.approx(3.5)
    assert case.amount_tail_context == pytest.approx(0.8)
    assert case.manual_or_adjustment_context == pytest.approx(0.5)
    assert case.after_hours_or_weekend_context == pytest.approx(0.5)
    assert case.round_amount_context == pytest.approx(1.0)
    assert case.rarity_context_count == 2
    assert case.context_evidence_count == 5
    assert case.subject_activity_rank == 4
    assert case.subject_frequency_context == {
        "subject_total_count": 99,
        "subject_rank_percentile": 0.2,
    }


def test_evidence_signature_excludes_baseline_payload_values():
    """baseline payload 는 case detail 로만 보존되고 case identity 에 들어가지 않는다."""
    entry = _strong_window_entry(daily_count=42)
    entry.update({"expected_count": 5.5, "robust_z": 9.75, "window_count": 42})
    result = _make_result(artifact=_artifact([entry]))

    cases = build_timeseries_cases(batch_id="b1", detection_result=result, df=_make_df())
    sig = cases[0].case_generation_reason.get("evidence_signature", "")

    assert "expected_count" not in sig
    assert "robust_z" not in sig
    assert "period_end_lift" not in sig
    assert "context_evidence_count" not in sig
    assert "window_count" not in sig
    assert "5.5" not in sig
    assert "9.75" not in sig
    assert "42" not in sig


def test_timeseries_diagnostics_preserve_expected_count_none_and_exclusion_reason():
    """diagnostic: expected_count None 보존 + sub_signal_high=False 제외 사유 집계."""
    entries = [
        _strong_window_entry(rule_id="TS01", subject="5100", sub_signal_high=True),
        _strong_window_entry(
            rule_id="TS02",
            subject="6200",
            window_start="2025-01-14",
            window_end="2025-01-20",
            positions=(2,),
            indices=(12,),
            sub_signal_high=False,
        ),
    ]
    artifact = _artifact(entries)
    result = _make_result(artifact=artifact)
    cases = build_timeseries_cases(batch_id="b1", detection_result=result, df=_make_df())

    diag = _timeseries_native_diagnostics(
        detection_result=result,
        cases=list(cases),
        truth_docs=set(),
        df_len=len(_make_df()),
    )

    assert diag["artifact_window_count"] == 2
    assert diag["case_count"] == 1
    assert diag["expected_count_state_windows"] == {"none": 2}
    assert diag["expected_count_state_cases"] == {"none": 1}
    assert diag["builder_excluded_window_reasons"] == {"sub_signal_high_false": 1}
    assert diag["artifact_windows_by_rule"] == {"TS01": 1, "TS02": 1}
    assert diag["artifact_windows_by_kind"] == {"single_day": 1, "trailing_window": 1}
    assert diag["case_count_by_rule"] == {"TS01": 1}
    assert diag["case_count_by_kind"] == {"single_day": 1}
    assert "baseline_available_window_count" in diag
    assert "expected_count_none_ratio_cases" in diag
    assert "first_truth_case_rank" in diag


def test_timeseries_diagnostics_do_not_emit_raw_scores_or_document_ids():
    """diagnostic payload 은 aggregate evidence-unit 진단만 담고 raw identifiers 를 쓰지 않음."""
    entry = _strong_window_entry(z_score=12345.67, daily_count=42)
    result = _make_result(artifact=_artifact([entry]))
    cases = build_timeseries_cases(batch_id="b1", detection_result=result, df=_make_df())

    diag = _timeseries_native_diagnostics(
        detection_result=result,
        cases=list(cases),
        truth_docs=set(),
        df_len=len(_make_df()),
    )
    payload_text = str(diag)

    assert "12345" not in payload_text
    assert "z_score" not in payload_text
    assert "threshold" not in payload_text
    assert "DOC100" not in payload_text
    assert "DOC101" not in payload_text


def test_timeseries_diagnostics_include_truth_rank_and_case_context():
    """measurement smoke: truth-covering TS case rank와 baseline context 필드가 기록된다."""
    entry = _strong_window_entry()
    entry.update(
        {
            "expected_count": 1.0,
            "robust_z": 2.5,
            "period_end_context": True,
            "window_count": 2,
        }
    )
    result = _make_result(artifact=_artifact([entry]))
    cases = build_timeseries_cases(batch_id="b1", detection_result=result, df=_make_df())

    diag = _timeseries_native_diagnostics(
        detection_result=result,
        cases=list(cases),
        truth_docs={"DOC100"},
        df_len=len(_make_df()),
    )

    assert diag["first_truth_case_rank"] == 1
    assert diag["truth_rank_distribution"]["count"] == 1
    assert diag["baseline_available_window_count"] == 1
    assert diag["baseline_available_case_count"] == 1
    assert diag["expected_count_state_windows"] == {"provided": 1}
    top_case = diag["top_truth_covering_cases"][0]
    assert top_case["rank"] == 1
    assert top_case["rule_id"] == "TS01"
    assert top_case["window_kind"] == "single_day"
    assert top_case["subject"] == "5100"
    assert top_case["daily_count"] == 2
    assert top_case["window_count"] == 2
    assert top_case["expected_count"] == 1.0
    assert top_case["robust_z"] == 2.5
    assert top_case["period_end_context"] is True
    assert top_case["family_score"] == 4.0
    assert top_case["top500_gap_reason"] is None
    assert "period_end_lift" in top_case
    assert "context_evidence_count" in top_case
    assert diag["top500_truth_miss_reasons"] == {}
    assert "period_end_disambiguation_comparison" in diag
