"""PHASE2 native case set orchestrator (v7-plan S3.next Phase A).

5 family detection_results 를 받아 각 family builder 로 라우팅 후 Phase2CaseSet
조립. invariant #80~83.

호출자 책임:
- detection_results 의 track_name 이 정확해야 한다 (duplicate / ml_unsupervised /
  intercompany / relational / timeseries 외 track 은 silent skip).
- unsupervised builder 만 model_id / schema_hash / ecdf_gate 추가 인자 받음.
- 출력 Phase2CaseSet.linked == False — linker (S4.next.2 / S6.next Phase 2) 가
  후속 단계에서 phase1_case_refs 부착 + linked=True 설정.

PHASE1 prior 접근 0건 — 5 builder 의 invariant 인계.
"""

from __future__ import annotations

from typing import Literal

import pandas as pd

from src.detection.base import DetectionResult
from src.models.phase2_case import Phase2CaseSet
from src.services.phase2_intercompany_case_builder import build_intercompany_cases
from src.services.phase2_relational_case_builder import build_relational_cases
from src.services.phase2_timeseries_case_builder import build_timeseries_cases
from src.services.phase2_unsupervised_case_builder import build_unsupervised_cases

# track_name → family key. 모르는 track 은 dict 부재로 silent skip (invariant #80).
_TRACK_NAME_TO_FAMILY: dict[str, str] = {
    "ml_unsupervised": "unsupervised",
    "intercompany": "intercompany",
    "relational": "relational",
    "timeseries": "timeseries",
}


def build_phase2_case_set(
    *,
    batch_id: str,
    detection_results: list[DetectionResult],
    df: pd.DataFrame,
    unsupervised_model_id: str = "",
    unsupervised_schema_hash: str = "",
    unsupervised_ecdf_gate: float = 0.95,
    unsupervised_ordering_strategy: Literal[
        "native", "hybrid_with_soft_repeated_normal_guard"
    ] = "hybrid_with_soft_repeated_normal_guard",
    timeseries_ordering_strategy: Literal[
        "native", "ts_specific_top100_stabilized_surface"
    ] = "ts_specific_top100_stabilized_surface",
) -> Phase2CaseSet:
    """5 family builder 호출 후 ``Phase2CaseSet`` 조립.

    detection_results 에서 track_name 별 라우팅:
    - ``"ml_unsupervised"`` → ``build_unsupervised_cases(... + model_id, schema_hash, ecdf_gate)``
    - ``"intercompany"``    → ``build_intercompany_cases(...)``
    - ``"relational"``      → ``build_relational_cases(...)``
    - ``"timeseries"``      → ``build_timeseries_cases(...)``

    각 family detection_result 부재 시 해당 cases tuple 은 빈 ``()``.
    detection_results 가 빈 list 면 모든 family 빈 ``Phase2CaseSet`` 반환.
    detection_results 에 중복 track_name 이 있으면 마지막 결과 사용 (호출자 책임).
    모르는 track_name 은 silent skip — ``ValueError`` 던지지 않는다 (invariant #80).

    Args:
        batch_id: 분석 배치 식별자. 각 builder 의 case_id payload 에 그대로 전달.
        detection_results: 5 family detector 가 산출한 ``DetectionResult`` list.
            ``track_name`` 으로 라우팅.
        df: detection 대상 GL DataFrame. 모든 builder 에 동일 객체 그대로 전달.
        unsupervised_model_id: unsupervised builder 전용 — VAE/IsolationForest
            model identifier. evidence_signature 에 포함된다.
        unsupervised_schema_hash: unsupervised builder 전용 — feature schema hash.
            evidence_signature 에 포함된다.
        unsupervised_ecdf_gate: unsupervised builder 전용 — ECDF gate 임계
            (default 0.95). 이 값 이상인 row 만 case 화.
        unsupervised_ordering_strategy: unsupervised builder 전용. 기본
            ``"hybrid_with_soft_repeated_normal_guard"`` 시그니처는 이전 진단
            호환용이며 현재는 context 필드를 쓰지 않는 document max-score 순서를
            적용한다. ``"native"`` 도 row-native 가 아니라 document max-score 순서다.
        timeseries_ordering_strategy: timeseries builder 전용. 기본
            ``"ts_specific_top100_stabilized_surface"`` 는 TS-primary stabilized
            ordering 을 적용한다. ``"native"`` 명시 시 artifact 순서 보존.

    Returns:
        ``Phase2CaseSet`` — ``linked=False`` default. linker 가 후속 단계에서
        ``phase1_case_refs`` 부착 + ``linked=True`` 로 갱신한다 (invariant #82).
    """
    # track_name → detection_result 매핑. 중복 track_name 은 마지막 결과로 덮어쓰기
    # — 호출자 책임 (docstring 명시). 모르는 track 은 _TRACK_NAME_TO_FAMILY dict
    # 부재로 자연스럽게 skip (invariant #80).
    by_track: dict[str, DetectionResult] = {}
    for result in detection_results:
        track = getattr(result, "track_name", "")
        if track in _TRACK_NAME_TO_FAMILY:
            by_track[track] = result

    # family 별 builder 호출. 부재 track 은 빈 tuple 로 graceful fallback.
    unsupervised_cases: tuple = ()
    if "ml_unsupervised" in by_track:
        # invariant #81 — unsupervised 만 model_id / schema_hash / ecdf_gate 전달.
        unsupervised_cases = build_unsupervised_cases(
            batch_id=batch_id,
            detection_result=by_track["ml_unsupervised"],
            df=df,
            model_id=unsupervised_model_id,
            schema_hash=unsupervised_schema_hash,
            ecdf_gate=unsupervised_ecdf_gate,
            ordering_strategy=unsupervised_ordering_strategy,
        )

    intercompany_cases: tuple = ()
    if "intercompany" in by_track:
        intercompany_cases = build_intercompany_cases(
            batch_id=batch_id,
            detection_result=by_track["intercompany"],
            df=df,
        )

    relational_cases: tuple = ()
    if "relational" in by_track:
        relational_cases = build_relational_cases(
            batch_id=batch_id,
            detection_result=by_track["relational"],
            df=df,
        )

    timeseries_cases: tuple = ()
    if "timeseries" in by_track:
        timeseries_cases = build_timeseries_cases(
            batch_id=batch_id,
            detection_result=by_track["timeseries"],
            df=df,
            ordering_strategy=timeseries_ordering_strategy,
        )

    # invariant #82 — linked=False default. linker 가 후속 단계에서 부착.
    return Phase2CaseSet(
        intercompany_cases=intercompany_cases,
        relational_cases=relational_cases,
        unsupervised_cases=unsupervised_cases,
        timeseries_cases=timeseries_cases,
        linked=False,
    )


__all__ = ["build_phase2_case_set"]
