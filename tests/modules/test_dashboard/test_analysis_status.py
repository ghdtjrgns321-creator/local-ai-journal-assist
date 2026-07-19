from __future__ import annotations

from dashboard._analysis_status import (
    format_phase2_provenance,
    get_batch_analysis_status,
)


class _StubResult:
    def __init__(
        self,
        detector_statuses,
        warnings=None,
        *,
        phase2_training_report_id=None,
        phase2_inference_mode=None,
        phase2_inference_contract=None,
    ):
        self.detector_statuses = detector_statuses
        self.warnings = warnings or []
        self.phase2_training_report_id = phase2_training_report_id
        self.phase2_inference_mode = phase2_inference_mode
        self.phase2_inference_contract = phase2_inference_contract


def test_get_batch_analysis_status_returns_degraded_when_any_detector_degraded() -> None:
    result = _StubResult(
        detector_statuses=[
            {"track_name": "layer_b", "run_status": "degraded"},
            {"track_name": "layer_c", "run_status": "executed"},
        ]
    )
    assert get_batch_analysis_status(result) == "degraded"


def test_get_batch_analysis_status_returns_failed_before_degraded() -> None:
    result = _StubResult(
        detector_statuses=[
            {"track_name": "layer_b", "run_status": "degraded"},
            {"track_name": "graph", "run_status": "failed"},
        ]
    )
    assert get_batch_analysis_status(result) == "failed"


def test_format_phase2_provenance_returns_contract_summary() -> None:
    result = _StubResult(
        detector_statuses=[],
        phase2_training_report_id="train_001",
        phase2_inference_mode="training_contract",
        phase2_inference_contract={
            "selection_mode": "best_per_family",
            "required_models": ["unsupervised", "timeseries"],
            "family_sub_detectors": {
                "timeseries": ["transaction_burst", "unusual_frequency"],
            },
        },
    )

    assert format_phase2_provenance(result) == (
        "Phase 2 provenance: train=train_001 | "
        "mode=training_contract | select=best_per_family | "
        "families=2 | subdetectors=2"
    )
