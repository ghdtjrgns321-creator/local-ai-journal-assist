from __future__ import annotations

from pathlib import Path

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
    assert list(df["rule_group"]) == ["L1"]
    assert list(df["precision"]) == ["50.0%"]


def test_build_phase2_provenance_cards_reports_mode_and_contract():
    result = type(
        "Result",
        (),
        {
            "phase2_training_report_id": "train_001",
            "phase2_inference_mode": "training_contract",
            "phase2_inference_contract": {
                "required_models": ["supervised", "unsupervised"],
                "promoted_versions": {"supervised": 3},
            },
        },
    )()

    cards = tab_phase2._build_phase2_provenance_cards(result)

    assert cards == [
        ("모델 기준", "train_001"),
        ("실행 방식", "저장된 기준 사용"),
        ("사용 후보", "2"),
        ("확정 모델", "1"),
    ]


def test_build_promoted_model_frame_summarizes_contract():
    snapshot = {
        "report_id": "train_001",
        "inference_contract": {
            "required_models": ["supervised", "timeseries"],
            "promoted_versions": {"supervised": 4},
            "family_sub_detectors": {
                "timeseries": ["transaction_burst", "unusual_frequency"],
            },
        },
        "promotion_policy": {"selection_mode": "best_per_family"},
    }

    df = tab_phase2._build_promoted_model_frame(snapshot)

    assert list(df["분석 기준"]) == ["supervised", "timeseries"]
    assert list(df["버전"]) == ["4", "-"]
    assert list(df["세부 점검"]) == ["-", "transaction_burst, unusual_frequency"]


def test_phase1_no_longer_imports_phase2_inference_action_directly():
    source = Path("dashboard/tab_phase1.py").read_text(encoding="utf-8")

    assert "from dashboard.tab_phase2 import _start_phase2_analysis" not in source
    assert "Phase 2 탭으로 이동" in source
