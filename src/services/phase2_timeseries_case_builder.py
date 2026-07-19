"""PHASE2 timeseries family case builder (v7-plan §S6 Phase D).

Why: TimeseriesDetector 가 metadata.timeseries_window_artifact 로 산출한 windows
중 ``evidence_tier ∈ {strong, moderate}`` AND ``sub_signal_high == True`` 인
entry 만 TimeseriesCase tuple 로 변환한다 (Gate, invariant #65, Δ13 final).
builder 는 detector 가 산출한 sub_signal_high flag 만 신뢰하고 임계를 재정의하지
않는다.

도메인 정당화:
    - TS01 daily burst → PCAOB AS 2401 §B7 (unusual posting timing / period-end
      clustering — burst 는 의도성 증거 보강).
    - TS02 unusual frequency → ISA 240 §32 (Management override via timing
      manipulation — 짧은 기간 vendor/account 활동 집중).

evidence_signature 는 case identity 만 — ``sub_rule + subject + window_start``.
    z_score / daily_count / expected_count / robust_z 같은 raw metric 은 절대
    포함하지 않는다 (invariant #65 정합, IC builder invariant #55 동일 원칙).

builder 자체는 detection_result + df + batch_id 만 사용 — PHASE1 prior
(priority_score / composite_sort_score / rule hit) 접근 금지 (invariant #67).
phase1_case_refs 는 default () 로 두고 linker (S4) 가 부착한다.
"""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd

from src.detection.base import DetectionResult
from src.models.phase2_case import Phase2RowRef, TimeseriesCase, make_row_ref
from src.services.phase2_case_id import make_phase2_case_id

_FAMILY = "timeseries"
_UNIT_TYPE = "window"
_ALLOWED_TIERS: frozenset[str] = frozenset({"strong", "moderate"})
TIMESERIES_ORDERING_NATIVE = "native"
TIMESERIES_ORDERING_TS_PRIMARY_STABILIZED = "ts_specific_top100_stabilized_surface"
TIMESERIES_ORDERING_DEFAULT = TIMESERIES_ORDERING_TS_PRIMARY_STABILIZED
TimeseriesOrderingStrategy = Literal["native", "ts_specific_top100_stabilized_surface"]


def _column_value(df: pd.DataFrame, column: str, position: int) -> Any:
    """선택적 컬럼 값 안전 조회 — 컬럼 부재 / NaN → None.

    IC builder 의 동일 helper 와 contract 일치.
    """
    if column not in df.columns:
        return None
    value = df[column].iat[position]
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _make_ref_from_position(df: pd.DataFrame, *, position: int) -> Phase2RowRef | None:
    """artifact entry 의 row_position 으로 ``df.index[position]`` 을 source of truth.

    Why (invariant #66 + S5 invariant #60): artifact 의 ``row_indices`` 는
    ``_ts_json_safe`` 평탄화된 display payload 이므로 그대로 ``make_row_ref`` 에
    주입하면 canonicalize 결과가 어긋난다 (MultiIndex tuple → "s:(...)" 가공).
    ``df.index[position]`` 자체를 source of truth 로 사용해 canonical identity
    (``i:10`` / ``t:(s:DOC|i:0)`` 등) 를 보장한다. artifact 의 ``row_indices`` 는
    display / debug payload 로만 보존.
    """
    if position < 0 or position >= len(df):
        return None
    document_id = _column_value(df, "document_id", position)
    raw_line_number = _column_value(df, "line_number", position)
    company_code = _column_value(df, "company_code", position)
    # source of truth: df.index[position] — MultiIndex tuple 도 그대로 보존되어
    # canonicalize_ref_key 가 t:(s:...|i:...) 같은 canonical 표현을 만든다.
    actual_label = df.index[position]
    return make_row_ref(
        row_position=position,
        index_label=actual_label,
        document_id=str(document_id) if document_id is not None else None,
        raw_line_number=raw_line_number,
        company_code=str(company_code) if company_code is not None else None,
    )


def _build_case(
    *,
    batch_id: str,
    entry: dict[str, Any],
    row_refs: tuple[Phase2RowRef, ...],
) -> TimeseriesCase:
    """단일 window entry → TimeseriesCase.

    evidence_signature 는 case identity 만 — sub_rule + subject + window_start.
    z_score / daily_count / expected_count 등 raw metric 은 절대 포함하지 않음.
    """
    sub_rule = str(entry.get("rule_id") or "")
    subject = str(entry.get("subject") or "")
    window_start = str(entry.get("window_start") or "")
    window_end = str(entry.get("window_end") or "")
    daily_count = int(entry.get("daily_count") or 0)
    window_count = entry.get("window_count")
    # Why: detector 가 baseline 산출 못 했으면 None 그대로 보존 — 감사인이
    # "미산출" 로 인식. 0.0 fallback 은 daily_count vs expected=0 의 잘못된 비교
    # 유발 (invariant #69).
    raw_expected = entry.get("expected_count")
    expected_count: float | None = float(raw_expected) if raw_expected is not None else None
    z_score = float(entry.get("z_score") or 0.0)
    raw_robust_z = entry.get("robust_z")
    robust_z: float | None = float(raw_robust_z) if raw_robust_z is not None else None
    raw_baseline_days = entry.get("baseline_window_days")
    raw_baseline_obs = entry.get("baseline_observation_count")
    raw_subject_rank = entry.get("subject_activity_rank")
    raw_period_end_offset = entry.get("period_end_day_offset")
    raw_period_end_ratio = entry.get("subject_period_end_historical_ratio")
    raw_non_period_baseline = entry.get("subject_non_period_end_baseline_count")
    raw_period_end_expected = entry.get("period_end_expected_count")
    raw_period_end_lift = entry.get("period_end_lift")
    raw_rarity_context_count = entry.get("rarity_context_count")
    raw_context_evidence_count = entry.get("context_evidence_count")
    tier = str(entry.get("evidence_tier") or "")

    canonical_refs = tuple(ref.index_label for ref in row_refs)
    # case identity 만 — raw metric 절대 포함 금지 (invariant #65)
    evidence_signature = f"sub_rule={sub_rule}|subject={subject}|window={window_start}"
    case_id = make_phase2_case_id(
        batch_id=batch_id,
        family=_FAMILY,
        unit_type=_UNIT_TYPE,
        canonical_refs=canonical_refs,
        evidence_signature=evidence_signature,
    )
    return TimeseriesCase(
        phase2_case_id=case_id,
        batch_id=batch_id,
        family=_FAMILY,
        unit_type=_UNIT_TYPE,
        row_refs=row_refs,
        evidence_tier=tier,
        case_generation_reason={
            "gate": f"timeseries_{tier}_sub_signal_high",
            "sub_rule": sub_rule,
            "evidence_signature": evidence_signature,
        },
        family_score=z_score,
        family_ecdf=0.0,  # S3 store / ECDF 결합에서 별도 계산
        sub_rule=sub_rule,
        subject=subject,
        window_start=window_start,
        window_end=window_end,
        daily_count=daily_count,
        expected_count=expected_count,
        z_score=z_score,
        window_count=int(window_count) if window_count is not None else None,
        baseline_method=entry.get("baseline_method"),
        baseline_window_days=int(raw_baseline_days) if raw_baseline_days is not None else None,
        baseline_observation_count=int(raw_baseline_obs)
        if raw_baseline_obs is not None
        else None,
        robust_z=robust_z,
        period_end_context=bool(entry.get("period_end_context")),
        period_end_day_offset=int(raw_period_end_offset)
        if raw_period_end_offset is not None
        else None,
        subject_period_end_historical_ratio=float(raw_period_end_ratio)
        if raw_period_end_ratio is not None
        else None,
        subject_non_period_end_baseline_count=float(raw_non_period_baseline)
        if raw_non_period_baseline is not None
        else None,
        period_end_expected_count=float(raw_period_end_expected)
        if raw_period_end_expected is not None
        else None,
        period_end_lift=float(raw_period_end_lift) if raw_period_end_lift is not None else None,
        amount_tail_context=float(entry.get("amount_tail_context") or 0.0),
        manual_or_adjustment_context=float(entry.get("manual_or_adjustment_context") or 0.0),
        after_hours_or_weekend_context=float(entry.get("after_hours_or_weekend_context") or 0.0),
        round_amount_context=float(entry.get("round_amount_context") or 0.0),
        rarity_context_count=int(raw_rarity_context_count)
        if raw_rarity_context_count is not None
        else None,
        context_evidence_count=int(raw_context_evidence_count)
        if raw_context_evidence_count is not None
        else None,
        subject_activity_rank=int(raw_subject_rank) if raw_subject_rank is not None else None,
        subject_frequency_context=entry.get("subject_frequency_context")
        if isinstance(entry.get("subject_frequency_context"), dict)
        else None,
    )


def _build_window_case(
    entry: dict[str, Any],
    *,
    df: pd.DataFrame,
    batch_id: str,
) -> TimeseriesCase | None:
    """window entry → TimeseriesCase. Gate 미통과 / 빈 row_refs → None."""
    tier = str(entry.get("evidence_tier") or "")
    if tier not in _ALLOWED_TIERS:
        return None
    if not bool(entry.get("sub_signal_high")):
        return None
    positions = entry.get("row_positions") or []
    if not positions:
        return None
    # Why: invariant #66 — row_refs 의 index_label 은 df.index[position] source of truth.
    # artifact 의 row_indices 는 display payload (json_safe 평탄화) 이므로 무시.
    refs: list[Phase2RowRef] = []
    for position in positions:
        try:
            pos_int = int(position)
        except (TypeError, ValueError):
            continue
        ref = _make_ref_from_position(df, position=pos_int)
        if ref is not None:
            refs.append(ref)
    if not refs:
        return None
    return _build_case(batch_id=batch_id, entry=entry, row_refs=tuple(refs))


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _ts_primary_stabilized_sort_key(case: TimeseriesCase, ordinal: int) -> tuple:
    """Diagnostic TS-primary ordering key.

    This mirrors the fixed5 v3.1 diagnostic surface and uses only fields already
    present in the detector artifact/case payload. It deliberately excludes
    truth labels, scenario labels, owner metadata, PHASE1 rank, raw identifiers,
    and matched results.
    """

    support_count = len(case.row_refs)
    return (
        not bool(case.period_end_context),
        support_count < 7,
        bool(_float_or_zero(case.round_amount_context)),
        not bool(_float_or_zero(case.after_hours_or_weekend_context)),
        -_int_or_zero(case.context_evidence_count),
        -_float_or_zero(case.period_end_lift),
        -_float_or_zero(case.robust_z),
        _int_or_zero(case.subject_activity_rank) <= 10,
        ordinal,
    )


def _apply_ordering_strategy(
    cases: list[TimeseriesCase],
    *,
    ordering_strategy: TimeseriesOrderingStrategy,
) -> tuple[TimeseriesCase, ...]:
    """Return cases in native or explicit diagnostic ordering."""

    if ordering_strategy == TIMESERIES_ORDERING_NATIVE:
        return tuple(cases)
    if ordering_strategy != TIMESERIES_ORDERING_TS_PRIMARY_STABILIZED:
        raise ValueError(
            "unsupported timeseries ordering_strategy: "
            f"{ordering_strategy!r}; expected 'native' or "
            f"{TIMESERIES_ORDERING_TS_PRIMARY_STABILIZED!r}"
        )

    ordered = sorted(
        enumerate(cases),
        key=lambda item: _ts_primary_stabilized_sort_key(item[1], item[0]),
    )
    return tuple(case for _, case in ordered)


def build_timeseries_cases(
    *,
    batch_id: str,
    detection_result: DetectionResult,
    df: pd.DataFrame,
    ordering_strategy: TimeseriesOrderingStrategy = TIMESERIES_ORDERING_DEFAULT,
) -> tuple[TimeseriesCase, ...]:
    """timeseries_window_artifact.windows → TimeseriesCase tuple.

    Args:
        batch_id: 분석 배치 식별자.
        detection_result: ``TimeseriesDetector`` 가 산출한 DetectionResult.
            ``metadata.timeseries_window_artifact.windows`` 중 ``evidence_tier ∈
            {strong, moderate}`` AND ``sub_signal_high == True`` 인 entry 만
            case 화한다 (invariant #65, Δ13 final).
        df: detection 대상 GL DataFrame.

            **Row lookup 정책 (invariant #66, S5 invariant #60 정합)**:
            artifact entry 의 ``row_positions`` 를 source of truth 로 사용 —
            ``df.index[position]`` 을 canonicalize 한 결과를 row_refs 의
            index_label 로 부여한다. artifact 의 ``row_indices`` 는 display /
            debug payload 로만 보존되며 join key 가 아니다.
        ordering_strategy: 기본 ``"ts_specific_top100_stabilized_surface"`` 는
            v3.1 TS-primary stabilized ordering 을 적용한다. 이 전략은
            truth/scenario/owner metadata/PHASE1 rank 를 입력으로 쓰지 않는다.
            ``"native"`` 를 명시하면 detector artifact 순서를 그대로 보존한다.

    Returns:
        Gate 통과한 TimeseriesCase tuple. timeseries_window_artifact 부재 /
        빈 windows / track_name mismatch → 빈 tuple graceful fallback
        (invariant #68).
    """
    if detection_result is None or getattr(detection_result, "track_name", "") != _FAMILY:
        return ()
    metadata = getattr(detection_result, "metadata", None) or {}
    if not isinstance(metadata, dict):
        return ()
    artifact = metadata.get("timeseries_window_artifact")
    if not isinstance(artifact, dict):
        return ()
    windows = artifact.get("windows")
    if not isinstance(windows, list):
        return ()

    cases: list[TimeseriesCase] = []
    for entry in windows:
        if not isinstance(entry, dict):
            continue
        case = _build_window_case(entry, df=df, batch_id=batch_id)
        if case is not None:
            cases.append(case)
    return _apply_ordering_strategy(cases, ordering_strategy=ordering_strategy)


__all__ = [
    "TIMESERIES_ORDERING_NATIVE",
    "TIMESERIES_ORDERING_DEFAULT",
    "TIMESERIES_ORDERING_TS_PRIMARY_STABILIZED",
    "build_timeseries_cases",
]
