"""`build_phase2_case_set` orchestrator 라우팅 / 조립 계약 검증.

Why: v7-plan S3.next Phase A invariant #80~83 — detection_results 의
``track_name`` 을 5 family builder 로 라우팅 후 ``Phase2CaseSet`` 으로
조립한다. orchestrator 자체는 PHASE1 prior 에 접근하지 않으며 (#83),
모르는 track_name 은 silent skip (#80), unsupervised 만 추가 인자 (#81),
출력 set 의 ``linked`` 는 False default (#82) 다.

monkeypatch 로 5 builder 를 capture-stub 으로 대체해 라우팅 / 인자 전달 /
조립을 직접 관찰한다. 실제 builder 의 비즈니스 로직은 본 테스트 범위 밖.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from src.detection.base import DetectionResult
from src.models.phase2_case import (
    IntercompanyCase,
    Phase2CaseSet,
    RelationalCase,
    TimeseriesCase,
    UnsupervisedCase,
)
from src.services import phase2_case_set_orchestrator as orchestrator_module
from src.services.phase2_case_set_orchestrator import build_phase2_case_set

# ---------------------------------------------------------------------------
# 공용 fixture
# ---------------------------------------------------------------------------


def _make_df() -> pd.DataFrame:
    """orchestrator 는 df 를 builder 에게 그대로 위임 — 내용 무관 minimal fixture."""
    return pd.DataFrame({"amount": [100.0, 200.0]}, index=pd.Index([10, 11]))


def _make_result(track_name: str, **metadata_extra: Any) -> DetectionResult:
    """track_name 만 의미가 있는 minimal DetectionResult fixture.

    실제 builder 가 metadata 를 읽지만 본 테스트에서는 builder 를 stub 으로
    교체하므로 metadata 내용은 무관 — track_name 식별만 검증한다.
    """
    metadata: dict[str, Any] = {"display_name": track_name}
    metadata.update(metadata_extra)
    return DetectionResult(
        track_name=track_name,
        flagged_indices=[],
        scores=pd.Series(dtype=float),
        rule_flags=[],
        details=pd.DataFrame(),
        metadata=metadata,
    )


def _make_unsup_case(case_id: str = "uns-1") -> UnsupervisedCase:
    return UnsupervisedCase(
        phase2_case_id=case_id,
        batch_id="b1",
        family="unsupervised",
        unit_type="document",
        row_refs=(),
        evidence_tier="moderate",
        case_generation_reason={"gate": "unsupervised_ecdf"},
        family_score=0.8,
        family_ecdf=0.97,
        anomaly_score=0.8,
        top_features=(),
        model_id="m-1",
        schema_hash="s-1",
    )


def _make_ic_case(case_id: str = "ic-1") -> IntercompanyCase:
    return IntercompanyCase(
        phase2_case_id=case_id,
        batch_id="b1",
        family="intercompany",
        unit_type="pair",
        row_refs=(),
        evidence_tier="strong",
        case_generation_reason={"gate": "ic_reciprocal"},
        family_score=0.95,
        family_ecdf=0.99,
        ic_role="reciprocal",
    )


def _make_rel_case(case_id: str = "rel-1") -> RelationalCase:
    return RelationalCase(
        phase2_case_id=case_id,
        batch_id="b1",
        family="relational",
        unit_type="edge",
        row_refs=(),
        evidence_tier="moderate",
        case_generation_reason={"gate": "relational_edge"},
        family_score=0.7,
        family_ecdf=0.95,
        sub_rule="R01",
        edge_a="A",
        edge_b="B",
    )


def _make_ts_case(case_id: str = "ts-1") -> TimeseriesCase:
    return TimeseriesCase(
        phase2_case_id=case_id,
        batch_id="b1",
        family="timeseries",
        unit_type="window",
        row_refs=(),
        evidence_tier="moderate",
        case_generation_reason={"gate": "timeseries_window"},
        family_score=0.6,
        family_ecdf=0.92,
        sub_rule="TS01",
    )


class _StubRecorder:
    """builder stub 호출 인자를 기록하고 사전 지정 반환값을 돌려준다."""

    def __init__(self, return_value: tuple) -> None:
        self.return_value = return_value
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> tuple:
        self.calls.append(kwargs)
        return self.return_value


@pytest.fixture
def stubs(monkeypatch: pytest.MonkeyPatch) -> dict[str, _StubRecorder]:
    """4 builder 를 모두 capture-stub 으로 대체한다. 기본 반환값은 빈 tuple.

    Test 함수가 stubs["relational"].return_value = (case,) 처럼 덮어 쓰면
    해당 family 만 의미 있는 case 를 돌려준다.
    """
    recorders = {
        "unsupervised": _StubRecorder(()),
        "intercompany": _StubRecorder(()),
        "relational": _StubRecorder(()),
        "timeseries": _StubRecorder(()),
    }
    monkeypatch.setattr(orchestrator_module, "build_unsupervised_cases", recorders["unsupervised"])
    monkeypatch.setattr(orchestrator_module, "build_intercompany_cases", recorders["intercompany"])
    monkeypatch.setattr(orchestrator_module, "build_relational_cases", recorders["relational"])
    monkeypatch.setattr(orchestrator_module, "build_timeseries_cases", recorders["timeseries"])
    return recorders


# ---------------------------------------------------------------------------
# Test cases (+10)
# ---------------------------------------------------------------------------


def test_empty_detection_results_returns_empty_case_set(
    stubs: dict[str, _StubRecorder],
) -> None:
    """detection_results 가 빈 list 면 어떤 builder 도 호출되지 않고 빈 set 반환."""
    case_set = build_phase2_case_set(
        batch_id="b1",
        detection_results=[],
        df=_make_df(),
    )

    assert isinstance(case_set, Phase2CaseSet)
    assert case_set.unsupervised_cases == ()
    assert case_set.intercompany_cases == ()
    assert case_set.relational_cases == ()
    assert case_set.timeseries_cases == ()
    assert case_set.linked is False
    for recorder in stubs.values():
        assert recorder.calls == []


def test_unknown_track_name_ignored(stubs: dict[str, _StubRecorder]) -> None:
    """모르는 track_name 은 silent skip — ValueError 던지지 않고 빈 set 반환 (invariant #80)."""
    case_set = build_phase2_case_set(
        batch_id="b1",
        detection_results=[
            _make_result("unknown_track"),
            _make_result("some_other_detector"),
        ],
        df=_make_df(),
    )

    assert case_set.unsupervised_cases == ()
    assert case_set.intercompany_cases == ()
    assert case_set.relational_cases == ()
    assert case_set.timeseries_cases == ()
    for recorder in stubs.values():
        assert recorder.calls == []


def test_unsupervised_detection_result_routes_with_model_and_schema_params(
    stubs: dict[str, _StubRecorder],
) -> None:
    """unsupervised 만 model_id / schema_hash / ecdf_gate 추가 인자 전달 (invariant #81)."""
    expected_case = _make_unsup_case()
    stubs["unsupervised"].return_value = (expected_case,)
    df = _make_df()
    uns_result = _make_result("ml_unsupervised")

    case_set = build_phase2_case_set(
        batch_id="batch-7",
        detection_results=[uns_result],
        df=df,
        unsupervised_model_id="vae-v3",
        unsupervised_schema_hash="hash-abc",
        unsupervised_ecdf_gate=0.90,
    )

    assert case_set.unsupervised_cases == (expected_case,)
    assert stubs["intercompany"].calls == []
    assert stubs["relational"].calls == []
    assert stubs["timeseries"].calls == []
    assert len(stubs["unsupervised"].calls) == 1
    call = stubs["unsupervised"].calls[0]
    assert call["batch_id"] == "batch-7"
    assert call["detection_result"] is uns_result
    assert call["df"] is df
    assert call["model_id"] == "vae-v3"
    assert call["schema_hash"] == "hash-abc"
    assert call["ecdf_gate"] == pytest.approx(0.90)
    assert call["ordering_strategy"] == "hybrid_with_soft_repeated_normal_guard"
    assert set(call.keys()) == {
        "batch_id",
        "detection_result",
        "df",
        "model_id",
        "schema_hash",
        "ecdf_gate",
        "ordering_strategy",
    }


def test_intercompany_detection_result_routes_to_intercompany_builder(
    stubs: dict[str, _StubRecorder],
) -> None:
    """track_name='intercompany' → build_intercompany_cases."""
    expected_case = _make_ic_case()
    stubs["intercompany"].return_value = (expected_case,)
    df = _make_df()
    ic_result = _make_result("intercompany")

    case_set = build_phase2_case_set(
        batch_id="b1",
        detection_results=[ic_result],
        df=df,
    )

    assert case_set.intercompany_cases == (expected_case,)
    assert stubs["unsupervised"].calls == []
    assert stubs["relational"].calls == []
    assert stubs["timeseries"].calls == []
    assert len(stubs["intercompany"].calls) == 1
    call = stubs["intercompany"].calls[0]
    assert call["batch_id"] == "b1"
    assert call["detection_result"] is ic_result
    assert call["df"] is df
    assert set(call.keys()) == {"batch_id", "detection_result", "df"}


def test_relational_detection_result_routes_to_relational_builder(
    stubs: dict[str, _StubRecorder],
) -> None:
    """track_name='relational' → build_relational_cases."""
    expected_case = _make_rel_case()
    stubs["relational"].return_value = (expected_case,)
    df = _make_df()
    rel_result = _make_result("relational")

    case_set = build_phase2_case_set(
        batch_id="b1",
        detection_results=[rel_result],
        df=df,
    )

    assert case_set.relational_cases == (expected_case,)
    assert stubs["unsupervised"].calls == []
    assert stubs["intercompany"].calls == []
    assert stubs["timeseries"].calls == []
    assert len(stubs["relational"].calls) == 1
    call = stubs["relational"].calls[0]
    assert call["batch_id"] == "b1"
    assert call["detection_result"] is rel_result
    assert call["df"] is df
    assert set(call.keys()) == {"batch_id", "detection_result", "df"}


def test_timeseries_detection_result_routes_to_timeseries_builder(
    stubs: dict[str, _StubRecorder],
) -> None:
    """track_name='timeseries' → build_timeseries_cases."""
    expected_case = _make_ts_case()
    stubs["timeseries"].return_value = (expected_case,)
    df = _make_df()
    ts_result = _make_result("timeseries")

    case_set = build_phase2_case_set(
        batch_id="b1",
        detection_results=[ts_result],
        df=df,
    )

    assert case_set.timeseries_cases == (expected_case,)
    assert stubs["unsupervised"].calls == []
    assert stubs["intercompany"].calls == []
    assert stubs["relational"].calls == []
    assert len(stubs["timeseries"].calls) == 1
    call = stubs["timeseries"].calls[0]
    assert call["batch_id"] == "b1"
    assert call["detection_result"] is ts_result
    assert call["df"] is df
    assert call["ordering_strategy"] == "ts_specific_top100_stabilized_surface"
    assert set(call.keys()) == {
        "batch_id",
        "detection_result",
        "df",
        "ordering_strategy",
    }


def test_timeseries_explicit_ordering_strategy_passed_to_builder(
    stubs: dict[str, _StubRecorder],
) -> None:
    """timeseries ordering strategy 는 명시 opt-in 때만 builder 로 전달된다."""
    ts_result = _make_result("timeseries")

    build_phase2_case_set(
        batch_id="b1",
        detection_results=[ts_result],
        df=_make_df(),
        timeseries_ordering_strategy="ts_specific_top100_stabilized_surface",
    )

    call = stubs["timeseries"].calls[0]
    assert call["ordering_strategy"] == "ts_specific_top100_stabilized_surface"


def test_multiple_families_combine_into_single_case_set(
    stubs: dict[str, _StubRecorder],
) -> None:
    """4 family 가 모두 들어오면 각 builder 호출 후 단일 Phase2CaseSet 조립."""
    uns_case = _make_unsup_case("uns-X")
    ic_case = _make_ic_case("ic-X")
    rel_case = _make_rel_case("rel-X")
    ts_case = _make_ts_case("ts-X")
    stubs["unsupervised"].return_value = (uns_case,)
    stubs["intercompany"].return_value = (ic_case,)
    stubs["relational"].return_value = (rel_case,)
    stubs["timeseries"].return_value = (ts_case,)

    case_set = build_phase2_case_set(
        batch_id="b1",
        detection_results=[
            _make_result("ml_unsupervised"),
            _make_result("intercompany"),
            _make_result("relational"),
            _make_result("timeseries"),
            _make_result("noisy_unknown_track"),  # silent skip
        ],
        df=_make_df(),
        unsupervised_model_id="m",
        unsupervised_schema_hash="s",
    )

    assert case_set.unsupervised_cases == (uns_case,)
    assert case_set.intercompany_cases == (ic_case,)
    assert case_set.relational_cases == (rel_case,)
    assert case_set.timeseries_cases == (ts_case,)
    # 4 builder 각 1회만 호출 — unknown 은 invocation 0
    assert len(stubs["unsupervised"].calls) == 1
    assert len(stubs["intercompany"].calls) == 1
    assert len(stubs["relational"].calls) == 1
    assert len(stubs["timeseries"].calls) == 1


def test_returns_phase2_case_set_with_linked_false_default(
    stubs: dict[str, _StubRecorder],
) -> None:
    """orchestrator 출력은 항상 linked=False (invariant #82) — linker 가 후속 단계에서 부착."""
    stubs["relational"].return_value = (_make_rel_case(),)

    case_set = build_phase2_case_set(
        batch_id="b1",
        detection_results=[_make_result("relational")],
        df=_make_df(),
    )

    assert case_set.linked is False
    # 4 family 모두 비어 있어도 linked=False
    empty_set = build_phase2_case_set(
        batch_id="b1",
        detection_results=[],
        df=_make_df(),
    )
    assert empty_set.linked is False


def test_orchestrator_does_not_touch_phase1_prior(
    stubs: dict[str, _StubRecorder],
) -> None:
    """invariant #83 — orchestrator 는 PHASE1 prior (priority_score / composite_sort_score
    / rule hit) 에 접근하지 않는다. 입력에 PHASE1 prior 가 전혀 없어도 정상 동작 +
    출력 case 의 phase1_case_refs 는 빈 tuple 유지.

    Why: orchestrator 시그니처는 batch_id / detection_results / df / unsupervised 인자만
    받는다. PHASE1 case / priority_score / row_ref_map 인자가 노출되지 않는 점 자체로도
    invariant #83 의 정적 보장이지만, runtime 에서도 builder 출력의 phase1_case_refs 가
    default () 인지 검증한다.
    """
    # builder stub 은 진짜 builder 와 마찬가지로 phase1_case_refs default () 인 case 반환
    rel_case = _make_rel_case()
    stubs["relational"].return_value = (rel_case,)

    case_set = build_phase2_case_set(
        batch_id="b1",
        detection_results=[_make_result("relational")],
        df=_make_df(),
    )

    # orchestrator 가 phase1_case_refs 를 손대지 않아야 함 — default () 유지
    assert case_set.relational_cases[0].phase1_case_refs == ()
    assert case_set.linked is False
    # orchestrator 가 stub 에 PHASE1-관련 kwarg 를 절대 넣지 않는다
    call = stubs["relational"].calls[0]
    forbidden_keys = {
        "phase1_cases",
        "priority_score",
        "composite_sort_score",
        "row_ref_map",
        "phase1_case_refs",
    }
    assert forbidden_keys.isdisjoint(call.keys())


# ---------------------------------------------------------------------------
# 중복 track_name 정책 — 마지막 결과 사용 (호출자 책임)
# ---------------------------------------------------------------------------


def test_repeated_track_name_last_result_wins(
    stubs: dict[str, _StubRecorder],
) -> None:
    """동일 track_name 의 detection_result 가 여러 개면 마지막 것만 builder 에 전달.

    Why: orchestrator docstring 의 "중복 track_name → 마지막 결과 사용" 정책을
    회귀로 잠근다. Phase B 의 detection_results 조립 순서가 builder 입력에 직접
    영향하므로 silent 변경 차단.
    """
    first = _make_result("relational", marker="first")
    second = _make_result("relational", marker="second")
    # by_track dict 갱신 패턴 — 마지막 등장 결과가 dispatch.
    build_phase2_case_set(
        batch_id="b1",
        detection_results=[first, second],
        df=_make_df(),
    )
    rel_recorder = stubs["relational"]
    assert len(rel_recorder.calls) == 1, (
        "동일 track_name 의 detection_result 가 여러 개여도 builder 는 한 번만 호출"
    )
    call = rel_recorder.calls[0]
    # 두 번째 결과 (marker="second") 가 전달되어야 함.
    assert call["detection_result"].metadata.get("marker") == "second", (
        "마지막 detection_result 가 builder 에 전달되어야 한다 — 호출자 책임 docstring 정합"
    )
