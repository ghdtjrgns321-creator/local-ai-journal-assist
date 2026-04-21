from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from dashboard._state import (
    KEY_BATCH_ID,
    KEY_COMPANY_CONTEXT,
    KEY_FEATURED_DATA,
    KEY_PHASE2_RESULT,
    KEY_PIPELINE_RESULT,
    KEY_PREP_RESULT,
    KEY_SETTINGS,
)
from src.services.phase2_inference_service import (
    run_phase2_inference,
    run_phase2_inference_analysis,
)


def _make_local_temp_dir() -> Path:
    root = Path("tests") / ".tmp_phase2_inference"
    root.mkdir(parents=True, exist_ok=True)
    target = root / uuid.uuid4().hex
    target.mkdir(parents=True, exist_ok=True)
    return target


class _FakePipeline:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def redetect(self, featured_df, batch_id: str, file_name: str, reference_df=None):
        return SimpleNamespace(
            data=featured_df.copy(),
            featured_data=featured_df.copy(),
            batch_id="phase2_batch",
            file_name=file_name,
            load_result=object(),
            warnings=[],
            detector_statuses=[],
        )


class _FakeSettings:
    analysis_phase: str = "full"
    enable_variance_detection: bool = True
    enable_relational_detection: bool = True
    enable_graph_detection: bool = True
    enable_nlp_detection: bool = True
    enable_access_audit_detection: bool = True
    enable_evidence_detection: bool = True
    enable_trendbreak_detection: bool = True
    enable_ml_detection: bool = True

    def model_copy(self, update: dict):
        inst = _FakeSettings()
        for key, value in self.__dict__.items():
            setattr(inst, key, value)
        for key, value in update.items():
            setattr(inst, key, value)
        return inst


def test_run_phase2_inference_uses_pipeline():
    featured_df = pd.DataFrame({"document_id": ["D1"]})
    result = run_phase2_inference(
        featured_df,
        file_name="journal.csv",
        reference_df=featured_df,
        settings=_FakeSettings(),
        pipeline_cls=_FakePipeline,
    )

    assert result.batch_id == "phase2_batch"
    assert result.file_name == "journal.csv"


def test_run_phase2_inference_attaches_training_contract_snapshot():
    root = _make_local_temp_dir()
    try:
        report_dir = root / "models" / "phase2_train" / "train_001" / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "training_report.json").write_text(
            json.dumps(
                {
                    "report_id": "train_001",
                    "metadata": {
                        "inference_contract": {
                            "promoted_versions": {"supervised": 11},
                            "required_models": ["supervised", "timeseries"],
                            "family_sub_detectors": {
                                "timeseries": [
                                    "transaction_burst",
                                    "unusual_frequency",
                                ],
                            },
                        },
                        "promotion_policy": {
                            "selection_mode": "best_per_family",
                        },
                    },
                }
            ),
            encoding="utf-8",
        )

        featured_df = pd.DataFrame({"document_id": ["D1"]})
        result = run_phase2_inference(
            featured_df,
            file_name="journal.csv",
            reference_df=featured_df,
            ctx=SimpleNamespace(model_dir=root / "models"),
            pipeline_cls=_FakePipeline,
        )

        assert result.phase2_training_report_id == "train_001"
        assert result.phase2_inference_contract["promoted_versions"]["supervised"] == 11
        assert result.phase2_inference_contract["required_models"] == [
            "supervised",
            "timeseries",
        ]
        assert result.phase2_inference_contract["family_sub_detectors"]["timeseries"] == [
            "transaction_burst",
            "unusual_frequency",
        ]
        assert result.phase2_promotion_policy["selection_mode"] == "best_per_family"
        assert result.phase2_inference_mode == "training_contract"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_run_phase2_inference_marks_untrained_contract_only_without_snapshot():
    featured_df = pd.DataFrame({"document_id": ["D1"]})
    result = run_phase2_inference(
        featured_df,
        file_name="journal.csv",
        reference_df=featured_df,
        settings=_FakeSettings(),
        pipeline_cls=_FakePipeline,
    )

    assert result.phase2_inference_mode == "untrained_contract_only"


def test_run_phase2_inference_marks_cold_start_bootstrap_when_statuses_indicate_bootstrap():
    class _BootstrapPipeline(_FakePipeline):
        def redetect(self, featured_df, batch_id: str, file_name: str, reference_df=None):
            result = super().redetect(
                featured_df,
                batch_id=batch_id,
                file_name=file_name,
                reference_df=reference_df,
            )
            result.detector_statuses = [
                {
                    "track_name": "ml_unsupervised",
                    "run_status": "executed",
                    "reason": "bootstrapped_phase2_model",
                }
            ]
            return result

    featured_df = pd.DataFrame({"document_id": ["D1"]})
    result = run_phase2_inference(
        featured_df,
        file_name="journal.csv",
        reference_df=featured_df,
        settings=_FakeSettings(),
        pipeline_cls=_BootstrapPipeline,
    )

    assert result.phase2_inference_mode == "cold_start_bootstrap"


def test_run_phase2_inference_analysis_persists_state():
    prep = SimpleNamespace(
        data=pd.DataFrame({"document_id": ["D1"]}),
        featured_data=None,
        file_name="journal.csv",
    )
    ctx = SimpleNamespace(
        db_path="engagement.duckdb",
        clone_with_settings=lambda settings: SimpleNamespace(db_path="engagement.duckdb"),
    )
    conn_mgr = SimpleNamespace(get=lambda path: f"conn:{path}")
    state = {
        KEY_PREP_RESULT: prep,
        KEY_COMPANY_CONTEXT: ctx,
        KEY_SETTINGS: _FakeSettings(),
        "_company_repo": object(),
        "_conn_mgr": conn_mgr,
    }

    result = run_phase2_inference_analysis(
        state,
        inference_runner=lambda featured_df, **kwargs: SimpleNamespace(
            data=featured_df.copy(),
            featured_data=featured_df.copy(),
            batch_id="phase2_batch",
            file_name=kwargs["file_name"],
            load_result=object(),
            warnings=[],
        ),
    )

    assert result.batch_id == "phase2_batch"
    assert state[KEY_PHASE2_RESULT] is result
    assert state[KEY_PIPELINE_RESULT] is result
    assert state[KEY_BATCH_ID] == "phase2_batch"
    assert isinstance(state[KEY_FEATURED_DATA], pd.DataFrame)
