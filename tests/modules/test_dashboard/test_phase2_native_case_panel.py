"""`phase2_native_case_panel` family row builder / 정렬 / 헬퍼 검증.

Why: Streamlit 렌더링 (AgGrid / st.dataframe) 자체는 단위 테스트로 검증이
어렵지만, family 별 컬럼 매핑·정렬 키·linked_to 트런케이트·short id 등
순수 함수 부분은 결정성 보장이 필요해 잠금한다 (사용자 lock 결정 1·4 회귀 가드).
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from dashboard.components import phase2_native_case_panel as panel
from src.models.phase2_case import (
    Phase2CaseSet,
    Phase2RowRef,
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


def _ts_fixture(
    *,
    case_id: str = "p2_timeseries_window_abc1234567",
    tier: str = "strong",
    score: float = 0.9,
) -> TimeseriesCase:
    """case 인프라 generic fixture — 정렬·프레임 빌더 검증용 TimeseriesCase."""
    return TimeseriesCase(
        phase2_case_id=case_id,
        batch_id="batch-1",
        family="timeseries",
        unit_type="window",
        row_refs=(_row_ref("DOC-A", 3), _row_ref("DOC-B", 7)),
        evidence_tier=tier,
        case_generation_reason={"gate": "timeseries_window"},
        family_score=score,
        family_ecdf=0.0,
        sub_rule="TS01",
        subject="acct:1100",
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
    a = _ts_fixture(case_id="p2_timeseries_window_aaaaaaaa01", tier="moderate", score=0.95)
    b = _ts_fixture(case_id="p2_timeseries_window_aaaaaaaa02", tier="strong", score=0.30)
    c = _ts_fixture(case_id="p2_timeseries_window_aaaaaaaa03", tier="strong", score=0.80)
    d = _ts_fixture(case_id="p2_timeseries_window_aaaaaaaa04", tier="weak", score=0.99)
    cases = sorted([a, b, c, d], key=panel._sort_key)
    # strong (높은 score 우선) → moderate → weak
    assert [case.phase2_case_id[-2:] for case in cases] == ["03", "02", "01", "04"]


def _unsup_fixture(*, case_id: str, anomaly: float) -> UnsupervisedCase:
    return UnsupervisedCase(
        phase2_case_id=case_id,
        batch_id="batch-1",
        family="unsupervised",
        unit_type="document",
        row_refs=(_row_ref("DOC-A", 1),),
        evidence_tier="ml_quantile",
        case_generation_reason={"document_grouping": "document_id"},
        family_score=0.0,
        family_ecdf=0.0,
        anomaly_score=anomaly,
        document_id="DOC-A",
        evidence_row_count=1,
    )


def test_sort_key_unsupervised_orders_by_anomaly_tail_first():
    """VAE case 는 anomaly_score(분포 꼬리) 내림차순 — 꼬리 전표가 먼저 보인다."""
    a = _unsup_fixture(case_id="p2_unsupervised_document_uuuuuuu01", anomaly=0.9612)
    b = _unsup_fixture(case_id="p2_unsupervised_document_uuuuuuu02", anomaly=0.9987)
    c = _unsup_fixture(case_id="p2_unsupervised_document_uuuuuuu03", anomaly=0.9740)
    cases = sorted([a, b, c], key=panel._sort_key)
    assert [case.phase2_case_id[-2:] for case in cases] == ["02", "03", "01"]


def test_build_unsupervised_row_surface_columns():
    """VAE 목록 컬럼 = 전표·VAE 점수·금액 꼬리·희소도·증거 수·연계 Phase1.

    정보량 없는 컬럼(신호 강도=전 case ML, 이상 사유/주요 피처=단일 generic 태그,
    결산 근접=전 case 0.00)은 제거됐다. 대신 히스토그램 x축과 동일한
    anomaly_score(VAE 점수)를 노출한다.
    """
    case = UnsupervisedCase(
        phase2_case_id="p2_unsupervised_document_unsup0000001",
        batch_id="batch-1",
        family="unsupervised",
        unit_type="document",
        row_refs=(_row_ref("DOC-A", 1), _row_ref("DOC-A", 2)),
        evidence_tier="ml_quantile",
        case_generation_reason={},
        family_score=0.92,
        family_ecdf=0.97,
        anomaly_score=0.9971,
        top_features=(
            {
                "feature_id": "amount_z",
                "contrib": 0.45,
                "tag": "amount_outlier",
                "label_ko": "금액 꼬리",
            },
        ),
        document_id="DOC-A",
        evidence_row_count=2,
        amount_tail_context=0.98,
        period_end_context=0.9,
        account_rarity_context=0.5,
        process_rarity_context=0.25,
        model_id="model-1",
        schema_hash="hash-1",
    )
    row = panel._build_unsupervised_row(case, entry_amount=1234567.0)
    assert row["review_unit"] == "DOC-A"
    assert row["anomaly_score"] == "0.9971"
    # 금액은 백분위(금액 꼬리)가 아니라 실제 전표 차변 총액을 천단위 구분해 표시.
    assert row["amount"] == "1,234,567"
    # 정보량 없는 컬럼은 더 이상 노출하지 않는다.
    for removed in (
        "evidence_tier",
        "reason_tag",
        "top_feature",
        "period_end",
        "amount_tail",
        "account_process_rarity",
        "evidence_row_count",
        "linked_to",
    ):
        assert removed not in row


def test_build_unsupervised_row_amount_missing_shows_dash():
    """pr.data 부재 등으로 전표 금액을 못 구하면 '—'."""
    case = UnsupervisedCase(
        phase2_case_id="p2_unsupervised_document_unsup0000009",
        batch_id="batch-1",
        family="unsupervised",
        unit_type="document",
        row_refs=(_row_ref("DOC-A", 1),),
        evidence_tier="ml_quantile",
        case_generation_reason={"document_grouping": "document_id"},
        family_score=0.9,
        family_ecdf=0.97,
        anomaly_score=0.95,
        document_id="DOC-A",
        evidence_row_count=1,
    )
    row = panel._build_unsupervised_row(case, entry_amount=None)
    assert row["amount"] == "—"


def test_unsupervised_entry_amounts_sums_debit_with_company_isolation():
    """전표 금액 = 같은 (company_code, document_id) 차변 합. 타 회사 동일 전표번호 배제."""
    case = UnsupervisedCase(
        phase2_case_id="p2_unsupervised_document_amount0001",
        batch_id="batch-1",
        family="unsupervised",
        unit_type="document",
        row_refs=(
            make_row_ref(
                row_position=0,
                index_label="doc:DOC-X:1",
                document_id="DOC-X",
                raw_line_number=1,
                company_code="C001",
            ),
        ),
        evidence_tier="ml_quantile",
        case_generation_reason={"document_grouping": "document_id"},
        family_score=0.9,
        family_ecdf=0.97,
        anomaly_score=0.95,
        document_id="DOC-X",
        evidence_row_count=1,
    )
    pr = SimpleNamespace(
        data=pd.DataFrame(
            {
                "company_code": ["C001", "C001", "C002"],
                "document_id": ["DOC-X", "DOC-X", "DOC-X"],
                "debit_amount": [100.0, 250.0, 999.0],
                "credit_amount": [0.0, 0.0, 0.0],
            }
        )
    )
    amounts = panel._unsupervised_entry_amounts([case], pr)
    # C001·DOC-X 차변 합 350 만 잡히고 C002 의 999 는 배제.
    assert amounts[case.phase2_case_id] == 350.0


def test_build_unsupervised_row_uses_document_review_surface_columns():
    case = UnsupervisedCase(
        phase2_case_id="p2_unsupervised_document_unsup0000005",
        batch_id="batch-1",
        family="unsupervised",
        unit_type="document",
        row_refs=(_row_ref("DOC-A", 1), _row_ref("DOC-A", 2)),
        evidence_tier="ml_quantile",
        case_generation_reason={"document_grouping": "document_id"},
        family_score=0.92,
        family_ecdf=0.97,
        anomaly_score=0.92,
        top_features=(
            {
                "feature_id": "amount_z",
                "contrib": 0.45,
                "tag": "amount_outlier",
                "label_ko": "금액 꼬리",
            },
        ),
        document_id="DOC-A",
        evidence_row_count=2,
        amount_tail_context=0.98,
        period_end_context=0.9,
        account_rarity_context=0.5,
        process_rarity_context=0.25,
    )

    row = panel._build_unsupervised_row(case, entry_amount=5_000_000.0)

    assert row["anomaly_score"] == "0.9200"
    assert row["review_unit"] == "DOC-A"
    assert row["amount"] == "5,000,000"
    # 금액 꼬리(백분위)·희소도·증거 수·연계 Phase1 은 정보량이 없어 표에서 제거됐다.
    assert "amount_tail" not in row
    assert "account_process_rarity" not in row
    assert "evidence_row_count" not in row
    assert "linked_to" not in row


def test_build_unsupervised_row_empty_top_features():
    case = UnsupervisedCase(
        phase2_case_id="p2_unsupervised_document_unsup0000002",
        batch_id="batch-1",
        family="unsupervised",
        unit_type="document",
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
    # top_features 유무와 무관하게 reason_tag/top_feature 컬럼은 제거됐다.
    assert "reason_tag" not in row
    assert "top_feature" not in row
    assert row["anomaly_score"] == "1.0000"


def test_build_unsupervised_row_fallback_singleton_does_not_imply_document_group():
    case = UnsupervisedCase(
        phase2_case_id="p2_unsupervised_document_unsup0000003",
        batch_id="batch-1",
        family="unsupervised",
        unit_type="document",
        row_refs=(
            make_row_ref(
                row_position=0,
                index_label=0,
                document_id=None,
                raw_line_number=1,
                company_code="kr01",
            ),
        ),
        evidence_tier="ml_quantile",
        case_generation_reason={"document_grouping": "fallback_row_identity"},
        family_score=0.5,
        family_ecdf=0.96,
        anomaly_score=1.0,
        evidence_row_count=1,
    )

    row = panel._build_unsupervised_row(case)
    narrative = panel._build_case_narrative(case)

    assert row["review_unit"] == "전표 ID 없음 · 단일 행 review"
    assert "전표 묶음" not in row["review_unit"]
    assert "전표 식별자가 없어 단일 행 기준으로 표시" in narrative


def test_unsupervised_evidence_rows_puts_max_score_row_first():
    max_ref = _row_ref("DOC-A", 2)
    case = UnsupervisedCase(
        phase2_case_id="p2_unsupervised_document_unsup0000004",
        batch_id="batch-1",
        family="unsupervised",
        unit_type="document",
        row_refs=(_row_ref("DOC-A", 1), max_ref, _row_ref("DOC-A", 3)),
        evidence_tier="ml_quantile",
        case_generation_reason={"document_grouping": "document_id"},
        family_score=0.9,
        family_ecdf=0.99,
        anomaly_score=0.9,
        evidence_row_count=3,
        max_score_row_ref=max_ref,
    )

    ordered = panel._ordered_unsupervised_row_refs(case)

    assert ordered[0] == max_ref


def test_unsupervised_evidence_rows_trace_orders_by_score_ecdf_desc():
    low_ref = _row_ref("DOC-A", 1)
    high_ref = _row_ref("DOC-A", 2)
    case = UnsupervisedCase(
        phase2_case_id="p2_unsupervised_document_unsup0000006",
        batch_id="batch-1",
        family="unsupervised",
        unit_type="document",
        row_refs=(low_ref, high_ref),
        evidence_tier="ml_quantile",
        case_generation_reason={
            "document_grouping": "document_id",
            "evidence_rows": [
                {
                    "row_position": low_ref.row_position,
                    "score": 0.80,
                    "ecdf": 0.95,
                },
                {
                    "row_position": high_ref.row_position,
                    "score": 0.90,
                    "ecdf": 0.99,
                },
            ],
        },
        family_score=0.9,
        family_ecdf=0.99,
        anomaly_score=0.9,
        evidence_row_count=2,
        max_score_row_ref=high_ref,
    )

    rows = panel._unsupervised_evidence_row_display_rows(case)

    assert rows[0]["row_ref"] == panel._row_label(high_ref)
    assert rows[0]["score"] == "0.9000"
    assert rows[0]["ecdf"] == "0.9900"
    assert "index" not in rows[0]
    assert "company" not in rows[0]


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
    ts = _ts_fixture()
    frame = panel._build_family_frame("timeseries", [ts], phase1_case_lookup={})
    assert isinstance(frame, pd.DataFrame)
    assert "case_id" in frame.columns
    assert "_full_case_id" in frame.columns
    assert frame.iloc[0]["_full_case_id"] == ts.phase2_case_id


def test_render_panel_when_case_set_none_shows_info(monkeypatch):
    """case_set=None → st.info + 실행 버튼 분기 (사용자 lock 결정 5)."""
    captured = {"info": [], "button": [], "rerun": False}

    monkeypatch.setattr(panel.st, "info", lambda msg: captured["info"].append(msg))
    monkeypatch.setattr(panel.st, "button", lambda *args, **kwargs: False)
    monkeypatch.setattr(panel.st, "rerun", lambda: captured.update(rerun=True))

    panel.render_phase2_native_case_panel("timeseries", case_set=None)
    assert any("실행되지 않았습니다" in msg for msg in captured["info"])
    assert captured["rerun"] is False


def test_render_panel_empty_family_shows_info(monkeypatch):
    """case_set 은 있지만 family case 0건 → 빈 안내."""
    captured = {"info": []}
    monkeypatch.setattr(panel.st, "info", lambda msg: captured["info"].append(msg))
    empty_set = Phase2CaseSet()
    panel.render_phase2_native_case_panel("timeseries", case_set=empty_set)
    assert captured["info"], "0건 안내 표시 필요"
    assert "전표" in captured["info"][0]


def test_phase2_document_drilldown_preserves_company_boundary():
    case = UnsupervisedCase(
        phase2_case_id="p2_unsupervised_document_company0001",
        batch_id="batch-1",
        family="unsupervised",
        unit_type="document",
        row_refs=(
            make_row_ref(
                row_position=0,
                index_label=0,
                document_id="DOC-SAME",
                raw_line_number=1,
                company_code="C001",
            ),
        ),
        evidence_tier="ml_quantile",
        case_generation_reason={"document_grouping": "document_id"},
        family_score=0.9,
        family_ecdf=0.99,
        anomaly_score=0.9,
        evidence_row_count=1,
    )
    pr = SimpleNamespace(
        data=pd.DataFrame(
            {
                "company_code": ["C001", "C002"],
                "document_id": ["DOC-SAME", "DOC-SAME"],
                "posting_date": ["2026-06-01", "2026-06-01"],
                "gl_account": ["1000", "2000"],
                "debit_amount": [10.0, 99.0],
                "credit_amount": [0.0, 0.0],
            }
        )
    )

    documents = panel._build_phase2_documents_list(case, ["DOC-SAME"], pr=pr)
    raw_lines = panel._phase2_case_document_raw_lines(pr, case, "DOC-SAME")

    assert len(documents) == 1
    assert documents[0]["debit_amount"] == 10.0
    assert raw_lines == [
        {
            "company_code": "C001",
            "document_id": "DOC-SAME",
            "posting_date": "2026-06-01",
            "gl_account": "1000",
            "debit_amount": 10.0,
            "credit_amount": 0.0,
        }
    ]
