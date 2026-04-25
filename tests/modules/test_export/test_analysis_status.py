from __future__ import annotations

from types import SimpleNamespace

from src.export.analysis_status import (
    build_phase_provenance_lines,
    summarize_export_analysis_status,
)


def test_summarize_export_analysis_status_includes_extended_phase2_contract() -> None:
    result = SimpleNamespace(
        detector_statuses=[{"track_name": "timeseries", "run_status": "executed"}],
        warnings=[],
        phase2_training_report_id="train_001",
        phase2_inference_mode="training_contract",
        phase2_inference_contract={
            "selection_mode": "best_per_family",
            "required_models": ["unsupervised", "timeseries"],
            "promoted_versions": {"unsupervised": 3},
            "family_sub_detectors": {
                "timeseries": ["transaction_burst", "unusual_frequency"],
            },
        },
        phase3_insight=None,
    )

    summary = summarize_export_analysis_status(result)

    assert summary["status"] == "executed"
    assert summary["phase2_contract"]["required_model_count"] == 2
    assert summary["phase2_contract"]["promoted_model_count"] == 1
    assert summary["phase2_contract"]["family_sub_detectors"]["timeseries"] == [
        "transaction_burst",
        "unusual_frequency",
    ]


def test_build_phase_provenance_lines_reports_family_and_subdetector_counts() -> None:
    result = SimpleNamespace(
        detector_statuses=[],
        warnings=[],
        phase2_training_report_id="train_001",
        phase2_inference_mode="training_contract",
        phase2_inference_contract={
            "selection_mode": "best_per_family",
            "required_models": ["unsupervised", "timeseries"],
            "promoted_versions": {"unsupervised": 3},
            "family_sub_detectors": {
                "timeseries": ["transaction_burst", "unusual_frequency"],
            },
        },
        phase3_insight=None,
    )

    lines = build_phase_provenance_lines(result)

    assert lines == [
        "Phase 2 provenance: train=train_001 | mode=training_contract | "
        "select=best_per_family | promoted=1 | families=2 | subdetectors=2"
    ]


def test_phase3_case_narratives_are_exposed_in_export_status() -> None:
    result = SimpleNamespace(
        detector_statuses=[],
        warnings=[],
        phase2_training_report_id=None,
        phase2_inference_mode=None,
        phase2_inference_contract={},
        phase2_case_overlays=[{"phase1_case_id": "case_001"}],
        phase3_insight=None,
        phase3_case_narratives=[SimpleNamespace(case_id="case_001")],
    )

    summary = summarize_export_analysis_status(result)
    lines = build_phase_provenance_lines(result)

    assert summary["phase3_insight"]["available"] is True
    assert summary["phase3_insight"]["case_narrative_count"] == 1
    assert summary["phase3_insight"]["phase2_linked"] is True
    assert lines == [
        "Phase 3 provenance: insight=yes | top_risks=0 | significant_tx=0 | "
        "case_narratives=1 | phase2_linked=yes"
    ]
