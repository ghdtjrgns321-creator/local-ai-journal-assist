"""조합 빌더 엔진 계약 테스트 (SoT: docs/spec/PHASE1_COMBO_BUILDER_SPEC.md §2·§3·§4).

tier 폐지 후 주 검토 표면 — 결합 의미론(그룹 내 OR/간 AND·엄격 모드)과
어휘 무결성(몸통10·특징10·프리셋4, 겹침 금지)을 계약으로 박는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from src.export.phase1_combo_builder import (
    build_combo_builder_result,
    load_combo_vocabulary,
    match_units,
)


@dataclass
class _Ref:
    rule_id: str
    document_id: str = "doc-x"


@dataclass
class _Unit:
    unit_id: str
    evidence_rows: list
    triage_rank_score: float = 0.0
    time_severity_score: int = 0
    total_amount: float = 0.0
    unit_type: str = "document"
    priority_band: str = "low"
    priority_score: float = 0.0
    base_priority_score: float = 0.0
    composite_sort_score: float = 0.0
    triage_rank_reasons: list = field(default_factory=list)
    topic_scores: dict = field(default_factory=dict)
    topic_score_breakdown: dict = field(default_factory=dict)


def _unit(unit_id: str, *rules: str, **kw) -> _Unit:
    return _Unit(unit_id=unit_id, evidence_rows=[_Ref(r) for r in rules], **kw)


# ── 어휘 무결성 ────────────────────────────────────────────────


def test_vocabulary_shape_and_disjointness():
    vocab = load_combo_vocabulary()
    assert len(vocab.bodies) == 10
    assert len(vocab.features) == 10
    assert not (vocab.body_ids & vocab.feature_ids)
    # 프리셋 5종: 4종 + 결산 손상·충당금 미인식(2026-07-21, v3 기말결산+추정계정 5건 근거)
    assert len(vocab.presets) == 5


def test_preset_features_all_resolved_to_full_feature_list():
    vocab = load_combo_vocabulary()
    by_id = {p["preset_id"]: p for p in vocab.presets}
    assert set(by_id["revenue_recognition"]["features"]) == set(vocab.feature_ids)
    # 명시 목록 프리셋은 그대로 유지
    assert set(by_id["estimate_related_party"]["bodies"]) == {"L3-10", "L3-03"}


def test_vocabulary_bodies_carry_fss_and_basis():
    vocab = load_combo_vocabulary()
    for body in vocab.bodies:
        assert int(body["fss_confirmed"]) >= 1
        assert body["basis"]
    for feat in vocab.features:
        assert feat["basis"]


# ── 결합 의미론 (§3) ──────────────────────────────────────────


def test_default_mode_or_within_and_across_groups():
    units = [
        _unit("u1", "L3-10", "L3-02"),  # 몸통1 + 특징1 → 매치
        _unit("u2", "L3-03", "L1-05"),  # 다른 몸통 + 다른 특징 → 매치 (그룹 내 OR)
        _unit("u3", "L3-10"),  # 몸통만 → 특징 조건 실패
        _unit("u4", "L3-02"),  # 특징만 → 몸통 조건 실패
    ]
    got = match_units(units, bodies={"L3-10", "L3-03"}, features={"L3-02", "L1-05"})
    assert {u.unit_id for u in got} == {"u1", "u2"}


def test_body_only_selection_is_body_search_mode():
    units = [_unit("u1", "L2-04"), _unit("u2", "L3-02")]
    got = match_units(units, bodies={"L2-04"}, features=set())
    assert [u.unit_id for u in got] == ["u1"]


def test_feature_only_selection_is_shape_search_mode():
    units = [_unit("u1", "L2-04"), _unit("u2", "L1-07-02")]
    got = match_units(units, bodies=set(), features={"L1-07-02"})
    assert [u.unit_id for u in got] == ["u2"]


def test_empty_selection_returns_nothing():
    assert match_units([_unit("u1", "L3-10")], bodies=set(), features=set()) == []


def test_strict_mode_requires_every_selected_rule():
    units = [
        _unit("u1", "L3-10", "L3-03", "L3-02"),
        _unit("u2", "L3-10", "L3-02"),  # L3-03 없음 → 엄격 탈락
    ]
    got = match_units(units, bodies={"L3-10", "L3-03"}, features={"L3-02"}, strict=True)
    assert [u.unit_id for u in got] == ["u1"]


def test_sort_key_without_band_triage_then_time_then_amount():
    units = [
        _unit("small", "L3-10", "L3-02", total_amount=100.0),
        _unit("big", "L3-10", "L3-02", total_amount=900.0),
        _unit("timed", "L3-10", "L3-02", total_amount=50.0, time_severity_score=2),
        _unit("triaged", "L3-10", "L3-02", total_amount=10.0, triage_rank_score=1.0),
    ]
    got = match_units(units, bodies={"L3-10"}, features={"L3-02"})
    assert [u.unit_id for u in got] == ["triaged", "timed", "big", "small"]


# ── 대시보드 결과 뷰 ──────────────────────────────────────────


def test_build_result_rejects_selection_outside_vocabulary():
    with pytest.raises(ValueError, match="어휘 밖"):
        build_combo_builder_result(SimpleNamespace(), bodies=["L9-99"], features=[], strict=False)


def test_build_result_unavailable_without_phase1_artifact():
    pr = SimpleNamespace(phase1_case_result=None, phase1_case_path=None)
    out = build_combo_builder_result(pr, bodies=["L3-10"], features=[])
    assert out == {"available": False, "matched": 0, "rows": []}


def test_build_result_rows_and_top_n():
    units = [
        _unit("u1", "L3-10", "L3-02", total_amount=900.0),
        _unit("u2", "L3-10", "L1-05", total_amount=100.0),
        _unit("u3", "L2-04"),
    ]
    phase1 = SimpleNamespace(units=units, cases=[])
    pr = SimpleNamespace(phase1_case_result=phase1, phase1_case_path=None)
    out = build_combo_builder_result(pr, bodies=["L3-10"], features=["L3-02", "L1-05"], top_n=1)
    assert out["available"] is True
    assert out["matched"] == 2  # top_n 절단 전 전체 매치 수 보존
    assert len(out["rows"]) == 1
    assert out["rows"][0]["unit_id"] == "u1"
    assert out["rows"][0]["fired_rules"] == ["L3-02", "L3-10"]
    assert out["selection"] == {
        "bodies": ["L3-10"],
        "features": ["L1-05", "L3-02"],
        "strict": False,
    }
