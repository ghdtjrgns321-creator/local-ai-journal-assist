from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from dashboard import tab_phase1
from src.detection.rule_detail_metadata import (
    canonicalize_rule_id,
    get_rule_detail_metadata,
)
from src.models.phase1_case import CaseDocumentRef, CaseGroupResult, RawRuleHitRef


class _TabContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _phase1_grid_pr() -> SimpleNamespace:
    data = pd.DataFrame(
        {
            "document_id": ["DOC-TRUTH", "DOC-TRUTH", "DOC-STALE"],
            "line_number": [1, 2, 1],
            "flagged_rules": ["", "", "L1-03"],
            "review_rules": ["", "", ""],
        }
    )
    case = CaseGroupResult(
        case_id="CASE-L1-03",
        primary_topic="account_logic",
        primary_theme="account_logic",
        primary_queue="account_logic",
        primary_queue_label="",
        topic_scores={"account_logic": 0.9},
        secondary_topics=[],
        secondary_queues=[],
        secondary_queue_labels=[],
        fraud_scenario_tags=[],
        case_key="CASE-L1-03",
        priority_score=0.9,
        priority_band="high",
        triage_rank_score=0.9,
        document_count=1,
        row_count=1,
        rule_count=1,
        total_amount=250.0,
        representative_explanation="truth-only row",
        documents=[CaseDocumentRef(document_id="DOC-TRUTH", matched_rules=["L1-03"], amount=250.0)],
        raw_rule_hits=[
            RawRuleHitRef(
                rule_id="L1-03",
                severity=5,
                document_id="DOC-TRUTH",
                row_index=1,
                score=0.9,
                normalized_score=0.9,
                evidence_type="account_logic",
            )
        ],
    )
    return SimpleNamespace(
        data=data,
        featured_data=data,
        phase1_case_result=SimpleNamespace(cases=[case]),
    )


def test_phase1_render_uses_compact_three_tab_layout(monkeypatch) -> None:
    """3-tab 압축 구조 가드.

    Why: tier 폐지·조합 빌더 전환(2026-07-21)으로 3-tab(전체 요약/데이터 정합성/조합별 검토)으로
         재편. 구 "통계결과" 탭은 case·priority_band 기반 차트라 폐기하고 모집단 프로파일은 전체
         요약으로 이관. "AI 결론" 탭은 PHASE3 Review Queue Narrator로 대체되어 제거.
    """
    captured_label_groups: list[list[str]] = []

    def fake_tabs(labels):
        captured_label_groups.append(list(labels))
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
    monkeypatch.setattr(tab_phase1, "_render_data_quality_gate", lambda *args, **kwargs: None)
    monkeypatch.setattr(tab_phase1, "_render_violation_cases_tab", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        tab_phase1, "_render_year_over_year", lambda *args, **kwargs: None, raising=False
    )

    tab_phase1.render(None, SimpleNamespace())

    # 최상위 탭 라벨 가드.
    assert captured_label_groups, "st.tabs가 호출되지 않았습니다."
    assert captured_label_groups[0] == [
        "전체 요약",
        "데이터 정합성",
        "조합별 검토",
    ]
    # AI 결론 탭이 더 이상 노출되지 않음을 보장.
    flat = [label for group in captured_label_groups for label in group]
    assert "AI 결론" not in flat


def test_available_rules_uses_raw_rule_hits_when_phase1_truth_exists() -> None:
    pr = _phase1_grid_pr()

    rules = tab_phase1._available_rules(pr.featured_data, pr=pr)

    assert rules == ["L1-03"]


def test_case_band_distribution_counts_phase1_cases() -> None:
    pr = SimpleNamespace(
        phase1_case_result=SimpleNamespace(
            cases=[
                SimpleNamespace(priority_band="high"),
                SimpleNamespace(priority_band="high"),
                SimpleNamespace(priority_band="medium"),
                SimpleNamespace(priority_band="low"),
                SimpleNamespace(priority_band="unexpected"),
            ]
        )
    )

    result = tab_phase1._case_band_distribution(pr)

    counts = dict(zip(result["band"], result["count"]))
    assert counts == {"high": 2, "medium": 1, "low": 2}


def test_filter_master_data_uses_raw_rule_hits_and_ignores_stale_flags() -> None:
    pr = _phase1_grid_pr()

    filtered = tab_phase1._filter_master_data(
        pr.featured_data,
        pr=pr,
        rule_only=True,
        selected_rules=["L1-03"],
        data_quality_only=False,
        audit_risk_only=False,
        review_only=False,
    )

    assert filtered["document_id"].tolist() == ["DOC-TRUTH"]
    assert filtered["line_number"].tolist() == [2]


def test_filter_master_data_falls_back_to_row_flags_without_phase1_truth() -> None:
    pr = _phase1_grid_pr()
    pr.phase1_case_result = None

    filtered = tab_phase1._filter_master_data(
        pr.featured_data,
        pr=pr,
        rule_only=True,
        selected_rules=["L1-03"],
        data_quality_only=False,
        audit_risk_only=False,
        review_only=False,
    )

    assert filtered["document_id"].tolist() == ["DOC-STALE"]


# ----------------------------------------------------------------------------
# Rule Detail Metadata v1 — topic 탭 적용 가드
# ----------------------------------------------------------------------------


def test_rules_for_topic_excludes_benford_alias_and_macro_rules() -> None:
    revenue = tab_phase1._rules_for_topic("revenue_statistical")

    # Benford(L4-02)·D01·D02 는 PHASE1-2 macro 로 이관(2026-06-17)되어 canonical
    # L1~L4 count·PHASE1-1 토픽 활성 룰에서 모두 제외된다(3-surface 불변식).
    assert "Benford" not in revenue
    assert "L4-02" not in revenue
    assert "D01" not in revenue
    assert "D02" not in revenue
    # 전표 단위 canonical row 룰은 그대로 활성 룰로 유지.
    assert {"L3-10", "L4-01", "L4-03", "L4-06"}.issubset(revenue)


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

    # Benford 는 canonical L4-02 로 매핑되지만 macro(PHASE1-2 이관)라 토픽 활성
    # 그룹에는 노출되지 않는다 — alias 별도 행도, canonical 행도 생기지 않는다.
    assert "L4-02" not in revenue_ids
    assert "Benford" not in revenue_ids
    # L2-03a 는 전표 단위 canonical L2-03 으로 흡수되어 그룹에 노출.
    assert "L2-03" in duplicate_ids
    assert "L2-03a" not in duplicate_ids
    # canonicalize_rule_id 동작 확인 (스모크).
    assert canonicalize_rule_id("Benford") == "L4-02"
    assert canonicalize_rule_id("L2-03a") == "L2-03"
