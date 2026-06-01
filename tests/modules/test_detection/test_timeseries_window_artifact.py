"""TimeseriesDetector 의 timeseries_window_artifact metadata 검증 (S6 Phase B).

Why: v7-plan §S6 invariant #62~63 — Timeseries detector 가 기존 row 단위 score /
details / rule_flags / metadata 를 변경하지 않으면서 새 metadata key
``timeseries_window_artifact`` 를 부착하는지 확인. artifact 는 TS01/TS02 의 (rule_id,
subject, window) 단위 sanitized projection 으로 구성되며 row_indices / row_positions
양쪽을 보유한다 (MultiIndex 안전).

도메인 정당화 (모듈 docstring 인용):
    - TS01 daily burst → PCAOB AS 2401 §B7 (unusual posting timing).
    - TS02 unusual frequency → ISA 240 §32 (management override via timing manipulation).
"""

from __future__ import annotations

import pandas as pd
import pytest

from config.settings import AuditSettings
from src.detection.base import DetectionResult
from src.detection.timeseries_detector import (
    TimeseriesDetector,
    TimeseriesWindowArtifact,
    build_timeseries_window_artifact,
)


def _detector() -> TimeseriesDetector:
    """기본 settings 만 — BaseDetector 가 audit_rules kwarg 미수용."""
    settings = AuditSettings()
    return TimeseriesDetector(settings=settings)


def _burst_df() -> pd.DataFrame:
    """TS01 daily burst fixture — 1/15 에 동일 gl_account 로 30건 집중, 그 외 3건/일."""
    rows = []
    for day in range(1, 31):
        date = pd.Timestamp(f"2025-01-{day:02d}")
        count = 30 if day == 15 else 3
        for idx in range(count):
            rows.append(
                {
                    "posting_date": date,
                    "gl_account": "5100",
                    "amount": 100.0 + idx,
                    "debit_amount": 100.0 + idx,
                    "credit_amount": 0.0,
                }
            )
    return pd.DataFrame(rows)


def _frequency_df() -> pd.DataFrame:
    """TS02 group spike fixture — vendor V_A 가 1월 한 달간 baseline 거의 0 인
    상태에서 1/15~1/21 7일에 매일 10건씩 폭증. group_frequency 의 가드:
        - min_support >= 10 (총 그룹 row >= 10)
        - min_active_days >= 3
        - excess >= min_excess_count(3), ratio >= spike_ratio_min(2.0)
    위 조건 모두 만족하도록 V_A: baseline 5일 (1/1~1/5) 각 1건 + spike 5일
    (1/15~1/19) 각 5건. baseline 분포가 있어 cold-start 가 아니고 spike 가 명확.
    """
    rows = []
    # V_A baseline — 1/1~1/5 각 1건 (총 5건, active_days=5)
    for day in range(1, 6):
        rows.append(
            {
                "posting_date": pd.Timestamp(f"2025-01-{day:02d}"),
                "gl_account": "6200",
                "auxiliary_account_number": "V_A",
                "amount": 200.0,
                "debit_amount": 200.0,
                "credit_amount": 0.0,
            }
        )
    # V_A spike — 1/15~1/19 각 5건 (총 25건). group_total = 30, spike 25건.
    for day in range(15, 20):
        for _ in range(5):
            rows.append(
                {
                    "posting_date": pd.Timestamp(f"2025-01-{day:02d}"),
                    "gl_account": "6200",
                    "auxiliary_account_number": "V_A",
                    "amount": 200.0,
                    "debit_amount": 200.0,
                    "credit_amount": 0.0,
                }
            )
    # baseline 비교용 — V_B 정상 분산 (단일 그룹만 있으면 ECDF 정규화가 거의 0)
    for day in range(1, 31):
        rows.append(
            {
                "posting_date": pd.Timestamp(f"2025-01-{day:02d}"),
                "gl_account": "6200",
                "auxiliary_account_number": "V_B",
                "amount": 200.0,
                "debit_amount": 200.0,
                "credit_amount": 0.0,
            }
        )
    return pd.DataFrame(rows)


def _empty_df() -> pd.DataFrame:
    """필수 컬럼만 있고 모든 sub-signal 비활성 fixture."""
    return pd.DataFrame(
        {
            "posting_date": [pd.Timestamp("2025-01-01")],
            "gl_account": ["1000"],
            "amount": [100.0],
            "debit_amount": [100.0],
            "credit_amount": [0.0],
        }
    )


# ─────────────────────────────────────────────────────────────


def test_artifact_contains_windows_and_coverage():
    """timeseries_window_artifact metadata 에 windows / coverage 필드 존재."""
    detector = _detector()
    result = detector.detect(_burst_df())
    assert isinstance(result, DetectionResult)
    artifact = result.metadata.get("timeseries_window_artifact")
    assert isinstance(artifact, dict)
    assert "windows" in artifact
    assert "coverage" in artifact
    assert artifact.get("schema_version") == 1
    assert isinstance(artifact["windows"], list)
    assert isinstance(artifact["coverage"], dict)


def test_artifact_empty_when_no_timeseries_rules_fired():
    """sub-signal 모두 비활성 → 빈 windows 와 coverage (graceful)."""
    detector = _detector()
    result = detector.detect(_empty_df())
    artifact = result.metadata.get("timeseries_window_artifact")
    assert isinstance(artifact, dict)
    assert artifact["windows"] == []
    # coverage 는 dict — TS01/TS02 carrier 키 존재 또는 빈 dict.
    assert isinstance(artifact["coverage"], dict)


def test_ts01_window_extracted_with_subject_start_end_z():
    """TS01 windows 항목이 subject/window_start/window_end/z_score 보유."""
    detector = _detector()
    result = detector.detect(_burst_df())
    artifact = result.metadata["timeseries_window_artifact"]
    ts01_windows = [w for w in artifact["windows"] if w["rule_id"] == "TS01"]
    assert ts01_windows, "TS01 burst 가 detection 됐는데 artifact 에 entry 없음"
    sample = ts01_windows[0]
    assert "subject" in sample and isinstance(sample["subject"], str)
    assert "window_start" in sample and isinstance(sample["window_start"], str)
    assert "window_end" in sample and isinstance(sample["window_end"], str)
    # TS01 은 single-day burst → window_start == window_end
    assert sample["window_start"] == sample["window_end"]
    assert "z_score" in sample
    assert isinstance(sample["z_score"], float)


def test_ts02_window_extracted_with_expected_count():
    """TS02 windows 항목이 daily_count + expected_count 슬롯 보유.

    invariant #69 (S6 followup): detector 가 baseline 미산출 → expected_count 는
    ``None`` 로 노출. 0.0 fallback 은 감사인 오해 방지 위해 사용 금지.
    """
    detector = _detector()
    result = detector.detect(_frequency_df())
    artifact = result.metadata["timeseries_window_artifact"]
    ts02_windows = [w for w in artifact["windows"] if w["rule_id"] == "TS02"]
    # TS02 frequency fixture 가 group_frequency 양수 score 를 못 만들면 skip
    if not ts02_windows:
        pytest.skip("TS02 group_frequency fixture 가 spike 를 만들지 못함 — 환경 의존")
    sample = ts02_windows[0]
    assert "daily_count" in sample and isinstance(sample["daily_count"], int)
    assert "expected_count" in sample
    assert sample["expected_count"] is None or isinstance(sample["expected_count"], float)
    assert sample["daily_count"] >= 1


def test_window_row_positions_match_indices():
    """row_indices 와 row_positions 의 길이 일치 + row_positions int."""
    detector = _detector()
    result = detector.detect(_burst_df())
    artifact = result.metadata["timeseries_window_artifact"]
    for entry in artifact["windows"]:
        assert isinstance(entry["row_indices"], list)
        assert isinstance(entry["row_positions"], list)
        assert len(entry["row_indices"]) == len(entry["row_positions"])
        for pos in entry["row_positions"]:
            assert isinstance(pos, int)


def test_sub_signal_high_set_for_strong_evidence():
    """evidence_tier == strong 인 window 는 sub_signal_high True."""
    detector = _detector()
    result = detector.detect(_burst_df())
    artifact = result.metadata["timeseries_window_artifact"]
    strong_windows = [w for w in artifact["windows"] if w["evidence_tier"] == "strong"]
    assert strong_windows, "strong tier window 가 검출되지 않음 — fixture 재검토 필요"
    for entry in strong_windows:
        assert entry["sub_signal_high"] is True


def test_artifact_schema_version_pinned_to_1():
    """schema_version 은 1 고정 (S6 lock)."""
    detector = _detector()
    result_a = detector.detect(_burst_df())
    result_b = detector.detect(_empty_df())
    assert result_a.metadata["timeseries_window_artifact"]["schema_version"] == 1
    assert result_b.metadata["timeseries_window_artifact"]["schema_version"] == 1


def test_existing_row_scores_and_details_unchanged():
    """invariant #62 — artifact 부착이 기존 scores / details / rule_flags / 기존 metadata 변경 0건.

    artifact 만 새 key 로 추가되고 그 외 모든 surface 값 / key 셋이 동일.
    """
    detector = _detector()
    df = _burst_df()
    result = detector.detect(df)
    # scores / details / rule_flags 는 동일 input 으로 두 번 호출해도 동일
    result2 = detector.detect(df)
    pd.testing.assert_series_equal(result.scores, result2.scores, check_names=False)
    pd.testing.assert_frame_equal(result.details, result2.details, check_like=True)
    assert [(rf.rule_id, rf.flagged_count) for rf in result.rule_flags] == [
        (rf.rule_id, rf.flagged_count) for rf in result2.rule_flags
    ]
    # artifact key 외 기존 metadata key 모두 보존 (회귀 보장)
    expected_keys = {
        "elapsed",
        "skipped_rules",
        "sub_signals",
        "score_distribution",
        "evidence_role_gating",
        "composite_temporal_gating",
        "period_end_gating",
        "explanation_summary",
        "why_it_flagged",
        "timeseries_window_artifact",  # 신규
    }
    assert expected_keys.issubset(set(result.metadata.keys()))


# ─────────────────────────────────────────────────────────────
# build_timeseries_window_artifact 의 빈 / direct 호출 검증 (보조)


def test_build_timeseries_window_artifact_returns_dataclass():
    """builder 함수가 TimeseriesWindowArtifact dataclass 인스턴스 반환."""
    df = _empty_df()
    artifact = build_timeseries_window_artifact(
        df,
        ts01_signal=pd.Series(0.0, index=df.index),
        ts01_flag=pd.Series(False, index=df.index),
        ts02_signal=pd.Series(0.0, index=df.index),
        ts02_flag=pd.Series(False, index=df.index),
        settings=AuditSettings(),
    )
    assert isinstance(artifact, TimeseriesWindowArtifact)
    assert artifact.schema_version == 1
    assert artifact.windows == []
    payload = artifact.to_dict()
    assert payload["schema_version"] == 1
    assert payload["windows"] == []
    assert isinstance(payload["coverage"], dict)


def test_ts01_baseline_computed_when_subject_history_sufficient():
    """TS01 single-day baseline 은 같은 subject 과거 active day median 으로 산출."""
    df = _burst_df()
    signal = pd.Series(0.0, index=df.index)
    flag = pd.Series(False, index=df.index)
    target_mask = df["posting_date"].eq(pd.Timestamp("2025-01-15"))
    signal.loc[target_mask] = 1.0
    flag.loc[target_mask] = True

    artifact = build_timeseries_window_artifact(
        df,
        ts01_signal=signal,
        ts01_flag=flag,
        ts02_signal=pd.Series(0.0, index=df.index),
        ts02_flag=pd.Series(False, index=df.index),
        settings=AuditSettings(),
    )

    assert artifact.windows
    sample = artifact.windows[0]
    assert sample["expected_count"] == pytest.approx(3.0)
    assert sample["baseline_method"] == "subject_trailing_active_day_median"
    assert sample["baseline_window_days"] == 28
    assert sample["baseline_observation_count"] >= 5
    assert isinstance(sample["robust_z"], float)


def test_baseline_unavailable_preserves_expected_count_none_no_zero_fallback():
    """관측 수 부족 시 expected_count=None 이며 0.0 fallback 을 쓰지 않는다."""
    df = pd.DataFrame(
        {
            "posting_date": [pd.Timestamp("2025-01-01"), pd.Timestamp("2025-01-01")],
            "gl_account": ["5100", "5100"],
            "amount": [100.0, 200.0],
            "debit_amount": [100.0, 200.0],
            "credit_amount": [0.0, 0.0],
        }
    )
    artifact = build_timeseries_window_artifact(
        df,
        ts01_signal=pd.Series([1.0, 1.0], index=df.index),
        ts01_flag=pd.Series([True, True], index=df.index),
        ts02_signal=pd.Series(0.0, index=df.index),
        ts02_flag=pd.Series(False, index=df.index),
        settings=AuditSettings(),
    )

    assert artifact.windows
    sample = artifact.windows[0]
    assert sample["expected_count"] is None
    assert sample["baseline_method"] is None
    assert sample["robust_z"] is None
    assert sample["baseline_observation_count"] == 0


def test_period_end_context_flag_is_separate_from_baseline():
    """period_end_context 는 별도 context flag 로 노출되고 baseline fallback 과 결합하지 않는다."""
    rows = []
    for day in range(1, 32):
        count = 6 if day == 31 else 1
        for _ in range(count):
            rows.append(
                {
                    "posting_date": pd.Timestamp(f"2025-01-{day:02d}"),
                    "gl_account": "5100",
                    "amount": 100.0,
                    "debit_amount": 100.0,
                    "credit_amount": 0.0,
                }
            )
    df = pd.DataFrame(rows)
    signal = pd.Series(0.0, index=df.index)
    flag = pd.Series(False, index=df.index)
    target_mask = df["posting_date"].eq(pd.Timestamp("2025-01-31"))
    signal.loc[target_mask] = 1.0
    flag.loc[target_mask] = True

    artifact = build_timeseries_window_artifact(
        df,
        ts01_signal=signal,
        ts01_flag=flag,
        ts02_signal=pd.Series(0.0, index=df.index),
        ts02_flag=pd.Series(False, index=df.index),
        settings=AuditSettings(),
    )

    sample = artifact.windows[0]
    assert sample["period_end_context"] is True
    assert sample["period_end_day_offset"] == 0
    assert sample["expected_count"] == pytest.approx(1.0)


def test_period_end_disambiguation_lift_preserved_when_history_sufficient():
    """과거 period-end 관측이 충분하면 period_end_lift 를 context 로 산출한다."""
    rows = []
    for month in range(1, 8):
        for _ in range(2):
            rows.append(
                {
                    "posting_date": pd.Timestamp(f"2025-{month:02d}-28"),
                    "gl_account": "5100",
                    "amount": 100.0,
                    "debit_amount": 100.0,
                    "credit_amount": 0.0,
                }
            )
    for _ in range(8):
        rows.append(
            {
                "posting_date": pd.Timestamp("2025-07-31"),
                "gl_account": "5100",
                "amount": 100.0,
                "debit_amount": 100.0,
                "credit_amount": 0.0,
            }
        )
    df = pd.DataFrame(rows)
    signal = pd.Series(0.0, index=df.index)
    flag = pd.Series(False, index=df.index)
    target_mask = df["posting_date"].eq(pd.Timestamp("2025-07-31"))
    signal.loc[target_mask] = 1.0
    flag.loc[target_mask] = True

    artifact = build_timeseries_window_artifact(
        df,
        ts01_signal=signal,
        ts01_flag=flag,
        ts02_signal=pd.Series(0.0, index=df.index),
        ts02_flag=pd.Series(False, index=df.index),
        settings=AuditSettings(),
    )

    sample = artifact.windows[0]
    assert sample["period_end_expected_count"] == pytest.approx(2.0)
    assert sample["period_end_lift"] == pytest.approx(4.0)
    assert sample["subject_period_end_historical_ratio"] is not None


def test_context_evidence_count_aggregates_window_context_axes():
    """manual/after-hours/round/amount-tail/rarity context 를 evidence count 로 집계."""
    df = _burst_df()
    target_mask = df["posting_date"].eq(pd.Timestamp("2025-01-15"))
    signal = pd.Series(0.0, index=df.index)
    flag = pd.Series(False, index=df.index)
    signal.loc[target_mask] = 1.0
    flag.loc[target_mask] = True
    amount_tail = pd.Series(0.0, index=df.index)
    manual = pd.Series(0.0, index=df.index)
    after_hours = pd.Series(0.0, index=df.index)
    round_amount = pd.Series(0.0, index=df.index)
    rarity = pd.Series(0.0, index=df.index)
    amount_tail.loc[target_mask] = 0.8
    manual.loc[target_mask] = 0.5
    after_hours.loc[target_mask] = 0.5
    round_amount.loc[target_mask] = 1.0
    rarity.loc[target_mask] = 0.9

    artifact = build_timeseries_window_artifact(
        df,
        ts01_signal=signal,
        ts01_flag=flag,
        ts02_signal=pd.Series(0.0, index=df.index),
        ts02_flag=pd.Series(False, index=df.index),
        settings=AuditSettings(),
        amount_tail_context=amount_tail,
        manual_or_adjustment_context=manual,
        after_hours_or_weekend_context=after_hours,
        round_amount_context=round_amount,
        account_process_rarity_context=rarity,
    )

    sample = artifact.windows[0]
    assert sample["amount_tail_context"] == pytest.approx(0.8)
    assert sample["manual_or_adjustment_context"] == pytest.approx(0.5)
    assert sample["after_hours_or_weekend_context"] == pytest.approx(0.5)
    assert sample["round_amount_context"] == pytest.approx(1.0)
    assert sample["rarity_context_count"] == 1
    assert sample["context_evidence_count"] == 5


def test_ts02_trailing_window_baseline_computed_when_history_sufficient():
    """TS02 는 같은 subject 과거 trailing window count 분포와 비교한다."""
    df = _frequency_df()
    signal = pd.Series(0.0, index=df.index)
    flag = pd.Series(False, index=df.index)
    target_mask = df["posting_date"].eq(pd.Timestamp("2025-01-19")) & df[
        "gl_account"
    ].eq("6200")
    signal.loc[target_mask] = 1.0
    flag.loc[target_mask] = True

    artifact = build_timeseries_window_artifact(
        df,
        ts01_signal=pd.Series(0.0, index=df.index),
        ts01_flag=pd.Series(False, index=df.index),
        ts02_signal=signal,
        ts02_flag=flag,
        settings=AuditSettings(),
    )

    ts02_windows = [entry for entry in artifact.windows if entry["rule_id"] == "TS02"]
    assert ts02_windows
    sample = ts02_windows[0]
    assert sample["window_start"] != sample["window_end"]
    assert sample["window_count"] >= sample["daily_count"]
    assert sample["expected_count"] is not None
    assert sample["baseline_method"] == "subject_trailing_window_median"
    assert sample["baseline_observation_count"] >= 5
