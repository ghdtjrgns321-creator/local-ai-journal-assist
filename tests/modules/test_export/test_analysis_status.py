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
            "contract_version": "phase2_unsupervised_mvp_v1",
            "selection_mode": "best_per_family",
            "required_models": ["unsupervised"],
            "promoted_versions": {"unsupervised": 3},
            "metric_semantics": {
                "metric_name": "unsupervised_selection_score",
                "interpretation": "ranking/calibration proxy, not fraud accuracy",
                "precision_recall_f1_policy": "ground_truth_only",
                "flagged_ratio_role": "metadata_only",
            },
        },
        phase3_insight=None,
    )

    summary = summarize_export_analysis_status(result)

    assert summary["status"] == "executed"
    assert summary["phase2_contract"]["required_model_count"] == 1
    assert summary["phase2_contract"]["promoted_model_count"] == 1
    assert summary["phase2_contract"]["contract_version"] == "phase2_unsupervised_mvp_v1"
    assert summary["phase2_contract"]["metric_semantics"]["metric_name"] == (
        "unsupervised_selection_score"
    )
    assert summary["phase2_contract"]["metric_semantics"]["flagged_ratio_role"] == (
        "metadata_only"
    )


def test_build_phase_provenance_lines_reports_family_and_subdetector_counts() -> None:
    result = SimpleNamespace(
        detector_statuses=[],
        warnings=[],
        phase2_training_report_id="train_001",
        phase2_inference_mode="training_contract",
        phase2_inference_contract={
            "contract_version": "phase2_unsupervised_mvp_v1",
            "selection_mode": "best_per_family",
            "required_models": ["unsupervised"],
            "promoted_versions": {"unsupervised": 3},
            "metric_semantics": {
                "metric_name": "unsupervised_selection_score",
            },
        },
        phase3_insight=None,
    )

    lines = build_phase_provenance_lines(result)

    assert lines == [
        "Phase 2 provenance: train=train_001 | mode=training_contract | "
        "contract=phase2_unsupervised_mvp_v1 | select=best_per_family | "
        "metric=unsupervised_selection_score | promoted=1 | families=1 | subdetectors=0"
    ]


def test_build_phase_provenance_lines_distinguishes_phase2_inference_modes() -> None:
    modes = ["training_contract", "untrained_contract_only", "cold_start_bootstrap"]

    lines = [
        build_phase_provenance_lines(
            SimpleNamespace(
                detector_statuses=[],
                warnings=[],
                phase2_training_report_id=None,
                phase2_inference_mode=mode,
                phase2_inference_contract={},
                phase3_insight=None,
            )
        )[0]
        for mode in modes
    ]

    assert "mode=training_contract" in lines[0]
    assert "mode=untrained_contract_only" in lines[1]
    assert "mode=cold_start_bootstrap" in lines[2]


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
