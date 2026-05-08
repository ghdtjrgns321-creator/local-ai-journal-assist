from __future__ import annotations

from types import SimpleNamespace

from dashboard import tab_phase1
from src.detection.rule_scoring import TOPIC_REGISTRY


class _TabContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_phase1_render_uses_all_data_seven_topics_and_ai_conclusion_tabs(monkeypatch) -> None:
    captured_labels: list[str] = []

    def fake_tabs(labels):
        captured_labels.extend(labels)
        return [_TabContext() for _ in labels]

    monkeypatch.setattr(tab_phase1.st, "subheader", lambda *args, **kwargs: None)
    monkeypatch.setattr(tab_phase1.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(tab_phase1.st, "tabs", fake_tabs)
    monkeypatch.setattr(
        tab_phase1,
        "summarize_phase1_case_result",
        lambda _result: {"available": True, "case_count": 1, "themes": []},
    )
    monkeypatch.setattr(tab_phase1, "_render_overview", lambda *args, **kwargs: None)
    monkeypatch.setattr(tab_phase1, "_render_topic_top_n", lambda *args, **kwargs: None)
    monkeypatch.setattr(tab_phase1, "_render_ai_conclusion", lambda *args, **kwargs: None)

    tab_phase1.render(None, SimpleNamespace())

    expected_topic_labels = [
        tab_phase1._TOPIC_SHORT_LABELS.get(topic_id, topic.label)
        for topic_id, topic in TOPIC_REGISTRY.items()
    ]
    assert captured_labels == (
        ["전체 요약"] + expected_topic_labels + ["AI 결론"]
    )
    assert len(captured_labels) == 9
