from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pandas as pd

from dashboard._state import (
    KEY_BATCH_ID,
    KEY_COMPANY_CONTEXT,
    KEY_COMPANY_ID,
    KEY_FEATURED_DATA,
    KEY_INGEST_DATA_DF,
    KEY_INGEST_MAPPING_RESULT,
    KEY_INGEST_STAGE,
    KEY_PHASE1_RESULT,
    KEY_PIPELINE_RESULT,
    KEY_PREP_RESULT,
    KEY_SETTINGS,
    KEY_UPLOAD_COUNT,
)
from src.services.analysis_service import make_phase_settings, run_phase_analysis
from src.services.batch_service import load_batch_into_state
from src.services.session_service import clear_company_selection, restore_loaded_result


@dataclass
class _FakeSettings:
    enable_variance_detection: bool = True
    enable_relational_detection: bool = True
    enable_graph_detection: bool = True
    enable_nlp_detection: bool = True
    enable_access_audit_detection: bool = True
    enable_evidence_detection: bool = True
    enable_trendbreak_detection: bool = True
    enable_ml_detection: bool = True
    min_description_length: int = 3
    ttr_threshold: float = 0.3
    entropy_threshold: float = 1.0

    def model_copy(self, update: dict):
        data = self.__dict__.copy()
        data.update(update)
        return _FakeSettings(**data)


class _FakePipeline:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def redetect(
        self,
        featured_df,
        batch_id: str,
        file_name: str,
        detection_scope: str = "default",
    ):
        return SimpleNamespace(
            data=featured_df.copy(),
            featured_data=featured_df.copy(),
            batch_id="phase_batch",
            file_name=file_name,
            detection_scope=detection_scope,
        )


def test_clear_company_selection_resets_dashboard_state():
    state = {
        KEY_COMPANY_ID: "acme",
        KEY_PHASE1_RESULT: object(),
        KEY_PIPELINE_RESULT: object(),
        KEY_INGEST_STAGE: "PIPELINE",
    }

    clear_company_selection(state)

    assert KEY_COMPANY_ID not in state
    assert KEY_PHASE1_RESULT not in state
    assert KEY_PIPELINE_RESULT not in state
    assert state[KEY_INGEST_STAGE] == "UPLOAD"


def test_restore_loaded_result_sets_pipeline_slots_for_analyzed_batch():
    result = SimpleNamespace(
        data=pd.DataFrame({"risk_level": ["High"]}),
        featured_data=pd.DataFrame({"x": [1]}),
        file_name="saved.csv",
    )
    state = {}

    restore_loaded_result(state, result, "batch_001")

    assert state[KEY_PREP_RESULT] is result
    assert state[KEY_PHASE1_RESULT] is result
    assert state[KEY_PIPELINE_RESULT] is result
    assert state[KEY_BATCH_ID] == "batch_001"


def test_load_batch_into_state_uses_batch_reader(monkeypatch):
    loaded = SimpleNamespace(
        data=pd.DataFrame({"risk_level": ["Normal"]}),
        featured_data=pd.DataFrame({"x": [1]}),
        file_name="loaded.csv",
    )

    monkeypatch.setattr("src.services.batch_service.load_batch", lambda conn, batch_id: loaded)

    state = {}
    result = load_batch_into_state(state, object(), "batch_777")

    assert result is loaded
    assert state[KEY_PREP_RESULT] is loaded
    assert state[KEY_BATCH_ID] == "batch_777"


def test_prepare_mapped_data_clears_review_state(monkeypatch):
    from dashboard.components import data_uploader, mapping_finalize

    prepared = SimpleNamespace(
        data=pd.DataFrame({"document_id": ["D1"]}),
        featured_data=pd.DataFrame({"document_id": ["D1"]}),
        batch_id="batch_prepared",
    )

    def fake_run_pipeline_from_mapped(file_key, progress_cb, *, prepare_only=False):
        assert file_key == "journal.csv_123"
        assert prepare_only is True
        progress_cb(1.0, "done")
        return prepared, []

    monkeypatch.setattr(
        data_uploader,
        "_run_pipeline_from_mapped",
        fake_run_pipeline_from_mapped,
    )
    state = {
        KEY_INGEST_STAGE: "REVIEW",
        KEY_INGEST_MAPPING_RESULT: object(),
        KEY_INGEST_DATA_DF: pd.DataFrame({"x": [1]}),
        "_ingest_file_key": "journal.csv_123",
    }
    monkeypatch.setattr(mapping_finalize.st, "session_state", state)

    result = mapping_finalize.prepare_mapped_data("journal.csv_123")

    assert result is prepared
    assert state[KEY_PREP_RESULT] is prepared
    assert state[KEY_BATCH_ID] == "batch_prepared"
    assert state[KEY_UPLOAD_COUNT] == "journal.csv_123"
    assert state[KEY_FEATURED_DATA].equals(prepared.featured_data)
    assert state[KEY_INGEST_STAGE] == "UPLOAD"
    assert KEY_INGEST_MAPPING_RESULT not in state
    assert KEY_INGEST_DATA_DF not in state
    assert "_ingest_file_key" not in state


def test_make_phase_settings_enables_ml_only_for_phase2():
    base = _FakeSettings()

    phase1 = make_phase_settings(base, phase="phase1")
    phase2 = make_phase_settings(base, phase="phase2")

    assert phase1.enable_ml_detection is False
    assert phase2.enable_ml_detection is True
    assert phase1.enable_variance_detection is True
    assert phase2.enable_variance_detection is True
    assert phase1.enable_graph_detection is False


def test_run_phase_analysis_uses_service_pipeline():
    prep = SimpleNamespace(
        data=pd.DataFrame({"document_id": ["D1"], "line_text": [""]}),
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

    result = run_phase_analysis(state, phase="phase1", pipeline_cls=_FakePipeline)

    assert result.batch_id == "phase_batch"
    assert state[KEY_PHASE1_RESULT] is result
    assert state[KEY_PIPELINE_RESULT] is result
    assert isinstance(state[KEY_FEATURED_DATA], pd.DataFrame)
    assert result.detection_scope == "phase1_core"


def test_run_phase_analysis_phase1_rebuilds_only_core_features(monkeypatch):
    calls = {}

    def fake_generate_all_features(
        df,
        *,
        settings,
        rules,
        risk_keywords,
        categories,
        include_morpheme_tokens,
    ):
        calls["categories"] = [category.value for category in categories]
        calls["include_morpheme_tokens"] = include_morpheme_tokens
        df = df.copy()
        df["phase1_feature_marker"] = 1
        return SimpleNamespace(data=df)

    monkeypatch.setattr("src.feature.engine.generate_all_features", fake_generate_all_features)

    prep = SimpleNamespace(
        data=pd.DataFrame({"document_id": ["D1"], "line_text": [""]}),
        featured_data=pd.DataFrame({"document_id": ["D1"], "heavy_feature": [999]}),
        file_name="journal.csv",
    )
    state = {
        KEY_PREP_RESULT: prep,
        KEY_SETTINGS: _FakeSettings(),
    }

    result = run_phase_analysis(state, phase="phase1", pipeline_cls=_FakePipeline)

    assert calls["categories"] == ["time", "amount", "pattern", "text"]
    assert calls["include_morpheme_tokens"] is False
    assert "phase1_feature_marker" in result.data.columns
    assert "heavy_feature" not in result.data.columns
