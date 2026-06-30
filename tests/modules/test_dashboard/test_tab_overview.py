from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from dashboard import tab_overview
from src.metrics.models import PerformanceReport, RuleMetric


class _DummyColumn:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


def _dummy_columns(spec, **kwargs):
    count = spec if isinstance(spec, int) else len(spec)
    return [_DummyColumn() for _ in range(count)]


def test_render_before_uses_line_count_for_total_journals(monkeypatch):
    rendered: list[tuple[str, str, str]] = []

    monkeypatch.setattr(tab_overview.st, "subheader", lambda *args, **kwargs: None)
    monkeypatch.setattr(tab_overview.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(tab_overview.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(tab_overview.st, "divider", lambda *args, **kwargs: None)
    monkeypatch.setattr(tab_overview.st, "columns", _dummy_columns)
    monkeypatch.setattr(tab_overview.st, "container", lambda *args, **kwargs: _DummyColumn())
    monkeypatch.setattr(tab_overview, "_render_document_type_donut", lambda df: None)
    monkeypatch.setattr(tab_overview, "_render_monthly_trend_line", lambda df: None)
    monkeypatch.setattr(tab_overview, "_render_quality_checklist", lambda df: None)
    monkeypatch.setattr(tab_overview, "_render_pipeline_briefing", lambda: None)
    monkeypatch.setattr(tab_overview, "_render_pipeline_cta", lambda: None)
    monkeypatch.setattr(
        tab_overview,
        "_render_kpi_card",
        lambda title, value, unit="": rendered.append((title, value, unit)),
    )

    result = SimpleNamespace(
        data=pd.DataFrame(
            {
                "document_id": ["D1", "D1", "D2"],
                "posting_date": pd.to_datetime(["2022-01-01", "2022-01-01", "2022-01-02"]),
                "debit_amount": [100.0, 0.0, 50.0],
            }
        )
    )

    tab_overview._render_before(result)

    assert ("총 전표 수", "3", "건") in rendered
    assert not any(title == "고유 전표 수" for title, _, _ in rendered)


def test_monthly_trend_uses_line_count_not_distinct_documents(monkeypatch):
    plotted = {}

    monkeypatch.setattr(tab_overview.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(tab_overview.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        tab_overview.st,
        "plotly_chart",
        lambda fig, *args, **kwargs: plotted.setdefault("fig", fig),
    )

    df = pd.DataFrame(
        {
            "document_id": ["D1", "D1", "D2"],
            "posting_date": pd.to_datetime(["2022-01-01", "2022-01-01", "2022-02-01"]),
        }
    )

    tab_overview._render_monthly_trend_line(df)

    y = list(plotted["fig"].data[0].y)
    assert y[0] == 2
    assert y[1] == 1


def test_quality_checks_label_line_and_document_basis() -> None:
    df = pd.DataFrame(
        {
            "document_id": ["D1", "D1", "D2"],
            "created_by": ["U1", "U1", "U2"],
            "approved_by": ["U1", "U3", "U4"],
            "source": ["manual", "manual", "automated"],
            "posting_date": pd.to_datetime(["2022-12-28", "2022-12-29", "2022-01-03"]),
            "debit_amount": [100.0, 0.0, 50.0],
            "credit_amount": [0.0, 100.0, 50.0],
        }
    )

    assert tab_overview._check_self_approval(df)[1] == "자기승인 라인"
    assert tab_overview._check_manual_je(df)[1] == "수기 라인 비율"
    assert tab_overview._check_timing(df)[1] == "시간대 분포(라인 기준)"
    assert tab_overview._check_period_end_concentration(df)[1] == "기말 집중도(라인 기준)"
    assert tab_overview._check_trial_balance(df)[1] == "차대변 대사(전표 단위)"


def test_build_datasynth_rule_tables_splits_ground_truth_and_separate_benchmarks():
    report = PerformanceReport(
        report_id="rep_001",
        upload_batch_id="batch_001",
        source_kind="ground_truth",
        phase_scope="phase1_only",
        rule_metrics=[
            RuleMetric(
                track_name="layer_c",
                rule_code="L3-06",
                evaluation_status="ok",
                label_docs=6,
                flagged_docs=16035,
                tp_docs=6,
                fp_docs=16029,
                fn_docs=0,
                precision=6 / 16035,
                recall=1.0,
                f1=0.0007,
            ),
            RuleMetric(
                track_name="benford",
                rule_code="L4-02",
                evaluation_status="ok",
                label_docs=0,
                flagged_docs=34123,
                tp_docs=0,
                fp_docs=34123,
                fn_docs=0,
                precision=0.0,
                recall=None,
                f1=None,
            ),
            RuleMetric(
                track_name="layer_c",
                rule_code="L4-05",
                evaluation_status="no_label",
                label_docs=0,
                flagged_docs=129,
                tp_docs=0,
                fp_docs=129,
                fn_docs=0,
                precision=None,
                recall=None,
                f1=None,
            ),
        ],
    )

    evaluated_df, separate_df = tab_overview._build_datasynth_rule_tables(report)

    assert list(evaluated_df["Rule ID"]) == ["L3-06"]
    assert list(evaluated_df["Status"]) == ["Evaluated"]
    assert list(evaluated_df["Recall"]) == ["100.0%"]

    assert list(separate_df["Rule ID"]) == ["L4-02", "L4-05"]
    assert list(separate_df["Benchmark Type"]) == ["Separate Benchmark", "Separate Benchmark"]
    assert list(separate_df["Benchmark Scope"]) == ["dataset / segment", "user / user-day"]


def test_build_datasynth_rule_tables_keeps_no_label_non_benchmark_rules_in_ground_truth_table():
    report = PerformanceReport(
        report_id="rep_002",
        upload_batch_id="batch_002",
        source_kind="ground_truth",
        phase_scope="phase1_only",
        rule_metrics=[
            RuleMetric(
                track_name="layer_c",
                rule_code="L3-05",
                evaluation_status="no_label",
                label_docs=0,
                flagged_docs=10,
                tp_docs=0,
                fp_docs=10,
                fn_docs=0,
                precision=None,
                recall=None,
                f1=None,
            ),
        ],
    )

    evaluated_df, separate_df = tab_overview._build_datasynth_rule_tables(report)

    assert list(evaluated_df["Rule ID"]) == ["L3-05"]
    assert list(evaluated_df["Status"]) == ["No Label"]
    assert list(evaluated_df["Precision"]) == ["N/A"]
    assert separate_df.empty
