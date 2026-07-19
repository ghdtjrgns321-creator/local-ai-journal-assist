"""WU-31 Sprint E1 — tab_review_queue 렌더링 단위 테스트.

Streamlit 위젯 함수 자체를 monkeypatch 로 가로채 호출 인자만 검증한다.
검증 포커스:
1. priority_rank 오름차순 정렬
2. 빈 입력 처리
3. citation 클릭 시 session_state 표적 적재
4. input_hash 변경 시 citation_target / selected_candidate 자동 무효화
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from dashboard import tab_review_queue
from dashboard._state import (
    KEY_REVIEW_QUEUE_CITATION_TARGET,
    KEY_REVIEW_QUEUE_INPUT_HASH,
    KEY_REVIEW_QUEUE_NARRATIVES,
    KEY_REVIEW_QUEUE_SELECTED_CANDIDATE,
)
from dashboard.components import review_narrator, review_narrator_jump

# ── fixture ──────────────────────────────────────────────────────


def _make_narrative(
    candidate_id: str,
    *,
    rank: int,
    confidence: str = "high",
    score: float = 0.5,
) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "priority_rank": rank,
        "priority_score": score,
        "summary": f"{candidate_id} 요약",
        "confidence": confidence,
        "reasoning": [
            {
                "claim": f"{candidate_id} claim",
                "evidence": [
                    {
                        "type": "rule_hit",
                        "rule_id": "L1-04",
                        "model_id": "",
                        "feature_id": "",
                        "journal_id": "",
                        "line_no": 0,
                    }
                ],
            }
        ],
        "suggested_actions": [
            {
                "action_type": "request_evidence",
                "description": "원시 증빙 요청",
                "target": "AP",
            }
        ],
    }


@pytest.fixture
def fake_state(monkeypatch) -> dict:
    state: dict = {}
    monkeypatch.setattr(tab_review_queue.st, "session_state", state)
    monkeypatch.setattr(review_narrator.st, "session_state", state)
    monkeypatch.setattr(review_narrator_jump.st, "session_state", state)
    return state


# ── 정렬 ─────────────────────────────────────────────────────────


def test_sorted_narratives_orders_by_rank_then_score_then_id() -> None:
    narratives = [
        {"candidate_id": "C2", "priority_rank": 2, "priority_score": 0.9},
        {"candidate_id": "C1", "priority_rank": 1, "priority_score": 0.7},
        {"candidate_id": "C3", "priority_rank": 1, "priority_score": 0.7},
    ]
    ordered = tab_review_queue._sorted_narratives(narratives)
    assert [n["candidate_id"] for n in ordered] == ["C1", "C3", "C2"]


# ── render: 빈 입력 ──────────────────────────────────────────────


def test_render_with_no_narratives_emits_info(monkeypatch, fake_state) -> None:
    """narratives가 비어있으면 카드 영역 안내(info)가 출력된다.

    Sprint E2 통합 후에는 빈 상태에서도 사이드바 필터·실행 트리거·검색 박스가 그려진다.
    따라서 columns 호출 자체를 막지 않고, 카드 영역의 info 메시지가 1개 이상이면 통과.
    """
    fake_state[KEY_REVIEW_QUEUE_NARRATIVES] = None
    info_calls: list[str] = []
    monkeypatch.setattr(tab_review_queue.st, "markdown", lambda *_a, **_k: None)
    monkeypatch.setattr(tab_review_queue.st, "caption", lambda *_a, **_k: None)
    monkeypatch.setattr(tab_review_queue.st, "info", lambda msg, *_a, **_k: info_calls.append(msg))
    _stub_streamlit_layout(monkeypatch)

    tab_review_queue.render(None)
    assert any("Narrator 결과가 아직 없습니다" in m for m in info_calls)


def _stub_streamlit_layout(monkeypatch) -> None:
    """E2 통합으로 추가된 사이드바·트리거·검색 위젯을 무해화하는 공용 stub."""

    class _Ctx:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return None

        def __getattr__(self, _name):
            return lambda *_a, **_k: _Ctx()

    def _columns(spec, *_a, **_k):
        count = spec if isinstance(spec, int) else (len(spec) if hasattr(spec, "__len__") else 2)
        return [_Ctx() for _ in range(int(count))]

    monkeypatch.setattr(tab_review_queue.st, "columns", _columns)
    monkeypatch.setattr(tab_review_queue.st, "container", lambda *_a, **_k: _Ctx())
    monkeypatch.setattr(tab_review_queue.st, "sidebar", _Ctx())
    monkeypatch.setattr(tab_review_queue.st, "expander", lambda *_a, **_k: _Ctx())
    monkeypatch.setattr(tab_review_queue.st, "multiselect", lambda *_a, **_k: [])
    monkeypatch.setattr(tab_review_queue.st, "slider", lambda *_a, **_k: 100)
    monkeypatch.setattr(tab_review_queue.st, "number_input", lambda *_a, **_k: 20)
    monkeypatch.setattr(tab_review_queue.st, "text_input", lambda *_a, **_k: "")
    monkeypatch.setattr(tab_review_queue.st, "button", lambda *_a, **_k: False)
    monkeypatch.setattr(tab_review_queue.st, "metric", lambda *_a, **_k: None)
    monkeypatch.setattr(tab_review_queue.st, "progress", lambda *_a, **_k: _Ctx())
    monkeypatch.setattr(tab_review_queue.st, "success", lambda *_a, **_k: None)
    monkeypatch.setattr(tab_review_queue.st, "warning", lambda *_a, **_k: None)
    monkeypatch.setattr(tab_review_queue.st, "error", lambda *_a, **_k: None)
    monkeypatch.setattr(tab_review_queue.st, "divider", lambda *_a, **_k: None)
    monkeypatch.setattr(tab_review_queue.st, "rerun", lambda *_a, **_k: None)


# ── render: 카드 정렬 ───────────────────────────────────────────


def test_render_invokes_card_in_priority_rank_order(monkeypatch, fake_state) -> None:
    """카드 렌더 순서가 priority_rank 오름차순임을 검증.

    E2 통합 후 사이드바·트리거·분류 위젯도 함께 그려지므로 _stub_streamlit_layout으로
    모든 위젯을 무해화한다. 검증 포커스는 카드 호출 순서만.
    """
    fake_state[KEY_REVIEW_QUEUE_NARRATIVES] = [
        _make_narrative("C_B", rank=5),
        _make_narrative("C_A", rank=1),
        _make_narrative("C_C", rank=3),
    ]
    fake_state[KEY_REVIEW_QUEUE_INPUT_HASH] = "h1"

    rendered: list[str] = []

    def _fake_card(narrative):  # noqa: ANN001
        rendered.append(narrative["candidate_id"])

    monkeypatch.setattr(tab_review_queue, "render_candidate_card", _fake_card)
    monkeypatch.setattr(tab_review_queue, "render_citation_jump_panel", lambda *_a, **_k: None)
    monkeypatch.setattr(tab_review_queue, "_render_decision_widget", lambda *_a, **_k: None)
    monkeypatch.setattr(tab_review_queue.st, "markdown", lambda *_a, **_k: None)
    monkeypatch.setattr(tab_review_queue.st, "caption", lambda *_a, **_k: None)
    monkeypatch.setattr(tab_review_queue.st, "info", lambda *_a, **_k: None)
    _stub_streamlit_layout(monkeypatch)

    tab_review_queue.render(SimpleNamespace(data=pd.DataFrame()))

    assert rendered == ["C_A", "C_C", "C_B"]


# ── citation 클릭 → 점프 표적 적재 ─────────────────────────────


def test_set_citation_target_writes_session_state(fake_state) -> None:
    evidence = {
        "type": "rule_hit",
        "rule_id": "L3-06",
        "model_id": "",
        "feature_id": "",
        "journal_id": "",
        "line_no": 0,
    }
    review_narrator._set_citation_target("CAND-1", evidence)

    assert fake_state[KEY_REVIEW_QUEUE_SELECTED_CANDIDATE] == "CAND-1"
    target = fake_state[KEY_REVIEW_QUEUE_CITATION_TARGET]
    assert target["candidate_id"] == "CAND-1"
    assert target["type"] == "rule_hit"
    assert target["rule_id"] == "L3-06"


# ── input_hash 변경 → citation 표적 자동 무효화 ───────────────


def test_hash_change_clears_citation_target(fake_state) -> None:
    fake_state[KEY_REVIEW_QUEUE_CITATION_TARGET] = {
        "candidate_id": "OLD",
        "type": "rule_hit",
        "rule_id": "L1-01",
    }
    fake_state[KEY_REVIEW_QUEUE_SELECTED_CANDIDATE] = "OLD"
    fake_state[tab_review_queue._PRIOR_HASH_KEY] = "prev"

    tab_review_queue._invalidate_jump_on_hash_change("new")

    assert fake_state[KEY_REVIEW_QUEUE_CITATION_TARGET] is None
    assert fake_state[KEY_REVIEW_QUEUE_SELECTED_CANDIDATE] is None
    assert fake_state[tab_review_queue._PRIOR_HASH_KEY] == "new"


def test_same_hash_keeps_citation_target(fake_state) -> None:
    target = {"candidate_id": "KEEP", "type": "rule_hit", "rule_id": "L1-01"}
    fake_state[KEY_REVIEW_QUEUE_CITATION_TARGET] = target
    fake_state[KEY_REVIEW_QUEUE_SELECTED_CANDIDATE] = "KEEP"
    fake_state[tab_review_queue._PRIOR_HASH_KEY] = "h1"

    tab_review_queue._invalidate_jump_on_hash_change("h1")

    assert fake_state[KEY_REVIEW_QUEUE_CITATION_TARGET] is target
    assert fake_state[KEY_REVIEW_QUEUE_SELECTED_CANDIDATE] == "KEEP"


# ── citation label 포맷 ─────────────────────────────────────────


@pytest.mark.parametrize(
    "evidence,expected_prefix",
    [
        ({"type": "rule_hit", "rule_id": "L4-02"}, "룰: L4-02"),
        (
            {"type": "ml_feature", "model_id": "vae_v1", "feature_id": "amount_z"},
            "ML 피처: vae_v1/amount_z",
        ),
        (
            {"type": "row", "journal_id": "DOC-9", "line_no": 3},
            "전표 라인: DOC-9#3",
        ),
    ],
)
def test_format_citation_label(evidence: dict, expected_prefix: str) -> None:
    assert review_narrator._format_citation_label(evidence) == expected_prefix
