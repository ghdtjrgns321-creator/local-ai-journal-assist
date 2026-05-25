"""tab_review_queue.render() 4탭 구조 단위 테스트.

검증:
1. st.tabs 가 통합/PHASE1/PHASE2/Narrator 4개 라벨로 호출된다.
2. 통합 탭이 첫번째(기본 활성) 라벨이다.
3. 각 sub-tab 컨텍스트에서 render_queue_browser 가 해당 kind 로 호출된다.
4. Narrator 탭이 보존되어 있다 (4번째 탭).
"""

from __future__ import annotations

from typing import Any

import pytest

from dashboard import tab_review_queue


class _TabContext:
    """st.tabs 가 반환하는 context manager 시뮬레이터."""

    def __init__(self, label: str, tracker: list[str]) -> None:
        self.label = label
        self._tracker = tracker

    def __enter__(self) -> _TabContext:
        self._tracker.append(self.label)
        return self

    def __exit__(self, *args: Any) -> None:
        return None


@pytest.fixture
def tab_spy(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """st.tabs 호출 + render_queue_browser / narrator 호출을 기록."""
    state: dict[str, Any] = {
        "tabs_labels": None,
        "active_tabs": [],
        "browser_calls": [],
        "narrator_called": False,
    }

    def fake_tabs(labels: list[str]) -> list[_TabContext]:
        state["tabs_labels"] = labels
        return [_TabContext(lbl, state["active_tabs"]) for lbl in labels]

    def fake_render_queue_browser(source: Any, *, kind: str, **kwargs: Any) -> None:
        state["browser_calls"].append({"kind": kind, "source": source})

    def fake_render_narrator(result: Any) -> None:
        state["narrator_called"] = True

    # Why: render() 가 KEY_PHASE2_RESULT / KEY_PHASE1_RESULT / overlay → DataFrame 변환을
    #      거치므로 session_state 가 비어 있도록 mock + _build_overlay_queue_df 가 빈 DF
    #      반환하도록 stub 한다. _ci_baseline fallback 은 제거됐다.
    import pandas as pd

    monkeypatch.setattr(tab_review_queue, "_build_overlay_queue_df", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(tab_review_queue.st, "session_state", {})
    monkeypatch.setattr(tab_review_queue.st, "tabs", fake_tabs)
    monkeypatch.setattr(tab_review_queue.st, "markdown", lambda *a, **k: None)
    monkeypatch.setattr(tab_review_queue.st, "caption", lambda *a, **k: None)
    monkeypatch.setattr(tab_review_queue, "render_queue_browser", fake_render_queue_browser)
    monkeypatch.setattr(tab_review_queue, "_render_narrator_workflow", fake_render_narrator)
    return state


def test_render_creates_4_tabs(tab_spy: dict[str, Any]) -> None:
    tab_review_queue.render(result=None)
    assert tab_spy["tabs_labels"] is not None
    assert len(tab_spy["tabs_labels"]) == 4


def test_first_tab_is_integrated(tab_spy: dict[str, Any]) -> None:
    """통합 추천이 첫번째 라벨 → Streamlit default 활성 탭."""
    tab_review_queue.render(result=None)
    labels = tab_spy["tabs_labels"]
    assert labels[0] == "통합 추천"


def test_tab_labels_use_audit_language_not_algorithm(tab_spy: dict[str, Any]) -> None:
    """탭 라벨에 RRF, k=60 같은 알고리즘 명칭이 노출되지 않는다."""
    tab_review_queue.render(result=None)
    labels = tab_spy["tabs_labels"]
    joined = " ".join(labels)
    assert "RRF" not in joined
    assert "k=60" not in joined


def test_each_browser_tab_invoked_with_correct_kind(tab_spy: dict[str, Any]) -> None:
    tab_review_queue.render(result=None)
    kinds = [c["kind"] for c in tab_spy["browser_calls"]]
    assert kinds == ["integrated", "phase1", "phase2"]


def test_narrator_tab_preserved(tab_spy: dict[str, Any]) -> None:
    """4번째 탭으로 기존 Narrator UI 가 호출된다."""
    tab_review_queue.render(result=None)
    assert tab_spy["narrator_called"] is True
    assert tab_spy["tabs_labels"][3] == "Narrator 분석"
