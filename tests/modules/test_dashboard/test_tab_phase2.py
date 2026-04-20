from __future__ import annotations

from dashboard import tab_phase2
from src.metrics.models import PerformanceReport, RuleMetric


def test_build_performance_cards_formats_values():
    report = PerformanceReport(
        report_id="rep_001",
        upload_batch_id="batch_001",
        source_kind="operational_proxy",
        phase_scope="phase2_included",
        total_docs=10,
        flagged_docs=4,
        high_risk_docs=2,
        high_risk_ratio=0.2,
        whitelist_removed_docs=1,
    )

    cards = tab_phase2._build_performance_cards(report)

    assert cards[0][0] == "Flagged Docs"
    assert cards[0][1] == "4"
    assert cards[2][1] == "20.0%"


def test_build_performance_rule_frame_returns_dataframe():
    report = PerformanceReport(
        report_id="rep_001",
        upload_batch_id="batch_001",
        source_kind="ground_truth",
        phase_scope="phase1_only",
        rule_metrics=[
            RuleMetric(
                track_name="layer_a",
                rule_code="L1-01",
                label_docs=3,
                flagged_docs=2,
                tp_docs=1,
                fp_docs=1,
                fn_docs=2,
                precision=0.5,
                recall=1 / 3,
                f1=0.4,
            )
        ],
    )

    df = tab_phase2._build_performance_rule_frame(report)

    assert list(df["rule_code"]) == ["L1-01"]
    assert list(df["precision"]) == ["50.0%"]
