"""`phase2_native_case_panel` family row builder / 정렬 / 헬퍼 검증.

Why: Streamlit 렌더링 (AgGrid / st.dataframe) 자체는 단위 테스트로 검증이
어렵지만, family 별 컬럼 매핑·정렬 키·linked_to 트런케이트·short id 등
순수 함수 부분은 결정성 보장이 필요해 잠금한다 (사용자 lock 결정 1·4 회귀 가드).
"""

from __future__ import annotations

import pandas as pd

from dashboard.components import phase2_native_case_panel as panel
from src.models.phase2_case import (
    DuplicateCase,
    IntercompanyCase,
    Phase2CaseSet,
    Phase2RowRef,
    RelationalCase,
    TimeseriesCase,
    UnsupervisedCase,
    make_row_ref,
)


def _row_ref(doc_id: str = "DOC-A", line: int = 3) -> Phase2RowRef:
    return make_row_ref(
        row_position=0,
        index_label=f"doc:{doc_id}:{line}",
        document_id=doc_id,
        raw_line_number=line,
        company_code="kr01",
    )


def _duplicate(
    *,
    case_id: str = "p2_duplicate_pair_abc1234567",
    tier: str = "strong",
    score: float = 0.9,
) -> DuplicateCase:
    return DuplicateCase(
        phase2_case_id=case_id,
        batch_id="batch-1",
        family="duplicate",
        unit_type="pair",
        row_refs=(_row_ref("DOC-A", 3), _row_ref("DOC-B", 7)),
        evidence_tier=tier,
        case_generation_reason={"gate": "evidence_tier_strong"},
        family_score=score,
        family_ecdf=0.0,
        pair_id="pair-1",
        sub_rule="L2-03a",
        left_ref=_row_ref("DOC-A", 3),
        right_ref=_row_ref("DOC-B", 7),
        pair_evidence_tier=tier,
    )


def test_short_case_id_strips_prefix():
    assert panel._short_case_id("p2_duplicate_pair_abc1234567") == "abc1234567"
    assert panel._short_case_id("") == "—"
    # prefix 형태 어긋나도 안전하게 원본 반환
    assert panel._short_case_id("oddform") == "oddform"


def test_linked_to_text_truncates_at_three():
    assert panel._linked_to_text(()) == "—"
    assert panel._linked_to_text(("c1",)) == "c1"
    assert panel._linked_to_text(("c1", "c2", "c3")) == "c1, c2, c3"
    assert panel._linked_to_text(("c1", "c2", "c3", "c4", "c5")) == "c1, c2, c3 +2"


def test_sort_key_orders_by_tier_then_score():
    """evidence_tier 우선 → 같은 tier 안에서 family_score 내림차순."""
    a = _duplicate(case_id="p2_duplicate_pair_aaaaaaaa01", tier="moderate", score=0.95)
    b = _duplicate(case_id="p2_duplicate_pair_aaaaaaaa02", tier="strong", score=0.30)
    c = _duplicate(case_id="p2_duplicate_pair_aaaaaaaa03", tier="strong", score=0.80)
    d = _duplicate(case_id="p2_duplicate_pair_aaaaaaaa04", tier="weak", score=0.99)
    cases = sorted([a, b, c, d], key=panel._sort_key)
    # strong (높은 score 우선) → moderate → weak
    assert [case.phase2_case_id[-2:] for case in cases] == ["03", "02", "01", "04"]


def test_build_duplicate_row_spec_columns():
    case = _duplicate()
    row = panel._build_duplicate_row(case)
    assert row["case_id"] == "abc1234567"
    assert row["evidence_tier"] == "Strong"
    assert row["sub_rule"] == "L2-03a"
    assert "DOC-A" in row["left_doc"]
    assert "DOC-B" in row["right_doc"]
    assert row["family_score"] == 0.9
    assert row["linked_to"] == "—"


def test_build_intercompany_row_counterparty_pair_formatting():
    case = IntercompanyCase(
        phase2_case_id="p2_intercompany_amount_xyz00099911",
        batch_id="batch-1",
        family="intercompany",
        unit_type="pair",
        row_refs=(_row_ref(),),
        evidence_tier="moderate",
        case_generation_reason={},
        family_score=0.7,
        family_ecdf=0.0,
        ic_role="amount",
        counterparty_pair=("A001", "B002"),
        amount_a=1_000_000.0,
        amount_b=999_000.0,
        amount_symmetry=0.999,
    )
    row = panel._build_intercompany_row(case)
    assert row["counterparty_pair"] == "A001↔B002"
    assert row["amount_a"] == "1,000,000"
    assert row["amount_b"] == "999,000"
    assert row["evidence_tier"] == "Moderate"


def test_build_intercompany_row_handles_missing_pair():
    case = IntercompanyCase(
        phase2_case_id="p2_intercompany_reciprocal_xyz11111111",
        batch_id="batch-1",
        family="intercompany",
        unit_type="row",
        row_refs=(_row_ref(),),
        evidence_tier="weak",
        case_generation_reason={},
        family_score=0.4,
        family_ecdf=0.0,
        ic_role="reciprocal",
        counterparty_pair=None,
        amount_a=None,
        amount_b=None,
        amount_symmetry=None,
    )
    row = panel._build_intercompany_row(case)
    assert row["counterparty_pair"] == "—"
    assert row["amount_a"] == "—"
    assert row["amount_b"] == "—"


def test_intercompany_family_frame_preserves_native_case_fields_without_layout_change():
    rec_case = IntercompanyCase(
        phase2_case_id="p2_intercompany_pair_reciprocal22222",
        batch_id="batch-1",
        family="intercompany",
        unit_type="pair",
        row_refs=(_row_ref("DOC-IC", 1), _row_ref("DOC-IC", 2)),
        evidence_tier="strong",
        case_generation_reason={"gate": "ic_strong_evidence"},
        family_score=1.0,
        family_ecdf=0.0,
        phase1_case_refs=("case-phase1-1",),
        ic_role="reciprocal_flow",
        counterparty_pair=("C001", "C002"),
        amount_a=500_000.0,
        amount_b=500_000.0,
        amount_symmetry=1.0,
    )
    frame = panel._build_family_frame(
        "intercompany",
        [rec_case],
        phase1_case_lookup={},
    )

    assert list(frame.columns) == [
        "case_id",
        "_full_case_id",
        "evidence_tier",
        "ic_role",
        "counterparty_pair",
        "amount_a",
        "amount_b",
        "linked_to",
    ]
    row = frame.iloc[0].to_dict()
    assert row["_full_case_id"] == rec_case.phase2_case_id
    assert row["ic_role"] == "reciprocal_flow"
    assert row["counterparty_pair"] == "C001↔C002"
    assert row["amount_a"] == "500,000"
    assert row["amount_b"] == "500,000"
    assert row["linked_to"] == "case-phase1-1"


def test_intercompany_detail_helpers_handle_paired_refs_and_optional_payloads():
    rec_case = IntercompanyCase(
        phase2_case_id="p2_intercompany_pair_reciprocal33333",
        batch_id="batch-1",
        family="intercompany",
        unit_type="pair",
        row_refs=(_row_ref("DOC-IC-A", 1), _row_ref("DOC-IC-B", 2)),
        evidence_tier="strong",
        case_generation_reason={},
        family_score=1.0,
        family_ecdf=0.0,
        ic_role="reciprocal_flow",
        counterparty_pair=("C001", "C002"),
        amount_a=500_000.0,
        amount_b=500_000.0,
        amount_symmetry=1.0,
    )
    mismatch_without_amounts = IntercompanyCase(
        phase2_case_id="p2_intercompany_pair_mismatch33333",
        batch_id="batch-1",
        family="intercompany",
        unit_type="pair",
        row_refs=(_row_ref("DOC-IC-C", 1), _row_ref("DOC-IC-D", 2)),
        evidence_tier="moderate",
        case_generation_reason={},
        family_score=0.7,
        family_ecdf=0.0,
        ic_role="amount_mismatch",
        counterparty_pair=("C003", "C004"),
        amount_a=None,
        amount_b=None,
        amount_symmetry=None,
    )

    assert panel._document_ids_from_row_refs(rec_case.row_refs) == ["DOC-IC-A", "DOC-IC-B"]
    rec_narrative = panel._build_case_narrative(rec_case)
    mismatch_row = panel._build_intercompany_row(mismatch_without_amounts)

    assert "reciprocal_flow" in rec_narrative
    assert "C001↔C002" in rec_narrative
    assert "부정" not in rec_narrative
    assert "fraud" not in rec_narrative.lower()
    assert mismatch_row["amount_a"] == "—"
    assert mismatch_row["amount_b"] == "—"


def test_build_relational_row_metric_format():
    case = RelationalCase(
        phase2_case_id="p2_relational_edge_rel00000001",
        batch_id="batch-1",
        family="relational",
        unit_type="edge",
        row_refs=(_row_ref(),),
        evidence_tier="strong",
        case_generation_reason={},
        family_score=0.82,
        family_ecdf=0.0,
        sub_rule="R01",
        edge_a="acct:1100",
        edge_b="cp:1234",
        metric_name="novelty",
        metric_value=0.7654321,
    )
    row = panel._build_relational_row(case)
    assert row["sub_rule"] == "R01"
    assert row["edge_a"] == "acct:1100"
    assert row["edge_b"] == "cp:1234"
    assert row["metric"] == "novelty=0.77"


def test_render_relational_panel_preserves_case_set_order_without_schema_change(monkeypatch):
    low_score_first = RelationalCase(
        phase2_case_id="p2_relational_edge_rel00000010",
        batch_id="batch-1",
        family="relational",
        unit_type="edge",
        row_refs=(_row_ref("DOC-A", 1),),
        evidence_tier="moderate",
        case_generation_reason={},
        family_score=0.10,
        family_ecdf=0.96,
        sub_rule="R01",
        edge_a="acct:1100",
        edge_b="cp:1234",
        metric_name="new_counterparty_score",
        metric_value=0.10,
    )
    high_score_second = RelationalCase(
        phase2_case_id="p2_relational_edge_rel00000020",
        batch_id="batch-1",
        family="relational",
        unit_type="edge",
        row_refs=(_row_ref("DOC-B", 1),),
        evidence_tier="strong",
        case_generation_reason={},
        family_score=0.99,
        family_ecdf=1.0,
        sub_rule="R03",
        edge_a="acct:2100",
        edge_b="cp:9999",
        metric_name="transfer_pricing_score",
        metric_value=0.99,
    )
    case_set = Phase2CaseSet(relational_cases=(low_score_first, high_score_second))
    captured: dict[str, object] = {}

    def capture_frame(family, cases, *, phase1_case_lookup):
        del phase1_case_lookup
        captured["family"] = family
        captured["case_ids"] = [case.phase2_case_id for case in cases]
        return pd.DataFrame(
            {
                "case_id": ["a", "b"],
                "_full_case_id": [case.phase2_case_id for case in cases],
            }
        )

    monkeypatch.setattr(panel, "_build_family_frame", capture_frame)
    monkeypatch.setattr(panel, "_render_master_table", lambda *args, **kwargs: None)

    panel.render_phase2_native_case_panel("relational", case_set=case_set)

    assert captured["family"] == "relational"
    assert captured["case_ids"] == [
        low_score_first.phase2_case_id,
        high_score_second.phase2_case_id,
    ]


def test_build_unsupervised_row_top_feature():
    case = UnsupervisedCase(
        phase2_case_id="p2_unsupervised_row_unsup0000001",
        batch_id="batch-1",
        family="unsupervised",
        unit_type="row",
        row_refs=(_row_ref(),),
        evidence_tier="ml_quantile",
        case_generation_reason={},
        family_score=0.92,
        family_ecdf=0.97,
        anomaly_score=3.456789,
        top_features=({"feature_id": "amount_z", "contrib": 0.45},),
        model_id="model-1",
        schema_hash="hash-1",
    )
    row = panel._build_unsupervised_row(case)
    assert row["evidence_tier"] == "ML"
    assert row["anomaly_score"] == 3.4568
    assert row["top_feature_1"] == "amount_z"


def test_build_unsupervised_row_empty_top_features():
    case = UnsupervisedCase(
        phase2_case_id="p2_unsupervised_row_unsup0000002",
        batch_id="batch-1",
        family="unsupervised",
        unit_type="row",
        row_refs=(_row_ref(),),
        evidence_tier="ml_quantile",
        case_generation_reason={},
        family_score=0.5,
        family_ecdf=0.96,
        anomaly_score=1.0,
        top_features=(),
        model_id="",
        schema_hash="",
    )
    row = panel._build_unsupervised_row(case)
    assert row["top_feature_1"] == "—"


def test_build_timeseries_row_window_formatting():
    multi_day = TimeseriesCase(
        phase2_case_id="p2_timeseries_window_ts00000001",
        batch_id="batch-1",
        family="timeseries",
        unit_type="window",
        row_refs=(_row_ref(),),
        evidence_tier="moderate",
        case_generation_reason={},
        family_score=0.65,
        family_ecdf=0.0,
        sub_rule="TS01",
        subject="user:U001|process:closing",
        window_start="2026-04-28",
        window_end="2026-04-30",
        daily_count=15,
        expected_count=3.2,
        z_score=4.1,
    )
    single_day = TimeseriesCase(
        phase2_case_id="p2_timeseries_window_ts00000002",
        batch_id="batch-1",
        family="timeseries",
        unit_type="window",
        row_refs=(_row_ref(),),
        evidence_tier="weak",
        case_generation_reason={},
        family_score=0.4,
        family_ecdf=0.0,
        sub_rule="TS02",
        subject="acct:1100",
        window_start="2026-04-30",
        window_end="2026-04-30",
        daily_count=7,
        expected_count=None,
        z_score=2.0,
    )
    multi_row = panel._build_timeseries_row(multi_day)
    single_row = panel._build_timeseries_row(single_day)
    assert multi_row["window"] == "2026-04-28~2026-04-30"
    assert single_row["window"] == "2026-04-30"
    assert multi_row["daily_count"] == 15


def test_build_family_frame_returns_dataframe_for_each_family():
    dup = _duplicate()
    frame = panel._build_family_frame("duplicate", [dup], phase1_case_lookup={})
    assert isinstance(frame, pd.DataFrame)
    assert "case_id" in frame.columns
    assert "_full_case_id" in frame.columns
    assert frame.iloc[0]["_full_case_id"] == dup.phase2_case_id


def test_render_panel_when_case_set_none_shows_info(monkeypatch):
    """case_set=None → st.info + 실행 버튼 분기 (사용자 lock 결정 5)."""
    captured = {"info": [], "button": [], "rerun": False}

    monkeypatch.setattr(panel.st, "info", lambda msg: captured["info"].append(msg))
    monkeypatch.setattr(panel.st, "button", lambda *args, **kwargs: False)
    monkeypatch.setattr(panel.st, "rerun", lambda: captured.update(rerun=True))

    panel.render_phase2_native_case_panel("duplicate", case_set=None)
    assert any("실행되지 않았습니다" in msg for msg in captured["info"])
    assert captured["rerun"] is False


def test_render_panel_empty_family_shows_info(monkeypatch):
    """case_set 은 있지만 family case 0건 → 빈 안내."""
    captured = {"info": []}
    monkeypatch.setattr(panel.st, "info", lambda msg: captured["info"].append(msg))
    empty_set = Phase2CaseSet()
    panel.render_phase2_native_case_panel("duplicate", case_set=empty_set)
    assert captured["info"], "0건 안내 표시 필요"
    assert "duplicate" in captured["info"][0]
