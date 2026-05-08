from __future__ import annotations

from types import SimpleNamespace

from dashboard import tab_phase1
from src.detection.rule_detail_metadata import (
    canonicalize_rule_id,
    get_rule_detail_metadata,
)
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


# ----------------------------------------------------------------------------
# Rule Detail Metadata v1 — topic 탭 적용 가드
# ----------------------------------------------------------------------------


def test_rules_for_topic_excludes_benford_alias_and_macro_rules() -> None:
    revenue = tab_phase1._rules_for_topic("revenue_statistical")

    # alias / macro 는 canonical L4-02 로 흡수되어야 한다.
    assert "Benford" not in revenue
    assert "L4-02" in revenue
    # macro (D01/D02) 는 canonical 32 에 포함되지 않으므로 토픽 활성 룰에서 제거.
    assert "D01" not in revenue
    assert "D02" not in revenue


def test_rules_for_topic_excludes_d_macro_from_account_and_closing() -> None:
    account = tab_phase1._rules_for_topic("account_logic")
    closing = tab_phase1._rules_for_topic("closing_timing")

    assert "D01" not in account
    assert "D02" not in closing
    # 정상 canonical 룰은 그대로 살아 있어야 한다.
    assert "L1-03" in account
    assert "L3-04" in closing


def test_rules_for_topic_keeps_canonical_transaction_rules() -> None:
    """canonical L1-L4 32 룰은 토픽 활성 룰에서 발견되어야 한다 (전탐방지)."""
    duplicate = tab_phase1._rules_for_topic("duplicate_outflow")
    assert {"L2-02", "L2-03", "L2-05", "L1-05", "L1-07"}.issubset(duplicate)
    # L2-03a~d 는 internal reason code → canonical L2-03 으로만 노출.
    assert "L2-03a" not in duplicate
    assert "L2-03b" not in duplicate


def test_metadata_rule_label_prefers_legacy_korean_then_metadata() -> None:
    # legacy `_RULE_NAMES_KR` 가 있으면 그대로 사용.
    assert tab_phase1._metadata_rule_label("L1-01") == "차대변 불일치"
    # legacy 에 없는 canonical 룰은 metadata display_title fallback.
    legacy_only_id = "L3-11"
    assert legacy_only_id not in tab_phase1._RULE_NAMES_KR
    fallback_label = tab_phase1._metadata_rule_label(legacy_only_id)
    assert fallback_label == get_rule_detail_metadata(legacy_only_id).display_copy.display_title


def test_topic_rule_groups_canonicalize_alias_and_internal_reason(monkeypatch) -> None:
    """raw_rule_hits 가 Benford / L2-03a 같은 alias·내부 코드여도 canonical 로 묶여야."""

    class _Hit:
        def __init__(self, rule_id: str) -> None:
            self.rule_id = rule_id

    class _Doc:
        def __init__(self, document_id: str, matched: list[str], amount: float) -> None:
            self.document_id = document_id
            self.matched_rules = matched
            self.amount = amount

    class _Case:
        def __init__(
            self,
            *,
            case_id: str,
            band: str,
            hits: list[str],
            documents: list[_Doc],
        ) -> None:
            self.case_id = case_id
            self.priority_band = band
            self.raw_rule_hits = [_Hit(rule_id) for rule_id in hits]
            self.documents = documents

    case = _Case(
        case_id="C-1",
        band="high",
        hits=["Benford", "L2-03a"],
        documents=[
            _Doc("D-1", ["Benford"], 1000.0),
            _Doc("D-2", ["L2-03a"], 500.0),
        ],
    )
    fake_phase1 = SimpleNamespace(cases=[case])

    fake_topic_ids = {"revenue_statistical", "duplicate_outflow"}
    monkeypatch.setattr(tab_phase1, "resolve_phase1_case_result", lambda _pr: fake_phase1)
    monkeypatch.setattr(tab_phase1, "_case_topic_ids", lambda _case: fake_topic_ids)
    monkeypatch.setattr(tab_phase1, "_case_topic_score", lambda _case, _topic: 0.9)

    revenue_groups = tab_phase1._topic_rule_groups_builder(SimpleNamespace(), "revenue_statistical")
    duplicate_groups = tab_phase1._topic_rule_groups_builder(SimpleNamespace(), "duplicate_outflow")

    revenue_ids = {group["rule_id"] for group in revenue_groups}
    duplicate_ids = {group["rule_id"] for group in duplicate_groups}

    # Benford 는 L4-02 로 흡수되어야 하고 별도 행이 생기면 안 된다.
    assert "L4-02" in revenue_ids
    assert "Benford" not in revenue_ids
    # L2-03a 는 L2-03 으로 흡수.
    assert "L2-03" in duplicate_ids
    assert "L2-03a" not in duplicate_ids
    # canonicalize_rule_id 동작 확인 (스모크).
    assert canonicalize_rule_id("Benford") == "L4-02"
    assert canonicalize_rule_id("L2-03a") == "L2-03"
