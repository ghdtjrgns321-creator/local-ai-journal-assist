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
    KEY_PHASE2_RESULT,
    KEY_PIPELINE_RESULT,
    KEY_PREP_RESULT,
    KEY_SETTINGS,
    KEY_UPLOAD_COUNT,
)
from src.services.analysis_service import make_phase_settings, run_phase_analysis
from src.services.batch_service import load_batch_into_state
from src.services.session_service import (
    clear_company_selection,
    close_dashboard_connections,
    restore_loaded_result,
)


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


class _FakeConnectionManager:
    def __init__(self):
        self.closed_paths: list[str] = []
        self.close_all_called = False

    def close(self, path: str) -> None:
        self.closed_paths.append(path)

    def close_all(self) -> None:
        self.close_all_called = True


def test_close_dashboard_connections_closes_state_and_global_managers(monkeypatch):
    state_mgr = _FakeConnectionManager()
    global_mgr = _FakeConnectionManager()
    monkeypatch.setattr("src.db.connection.get_connection_manager", lambda: global_mgr)

    close_dashboard_connections({"_conn_mgr": state_mgr}, "current.db")

    assert state_mgr.closed_paths == ["current.db"]
    assert global_mgr.closed_paths == ["current.db"]


def test_clear_company_selection_resets_dashboard_state():
    conn_mgr = _FakeConnectionManager()
    state = {
        KEY_COMPANY_ID: "acme",
        KEY_PHASE1_RESULT: object(),
        KEY_PIPELINE_RESULT: object(),
        KEY_INGEST_STAGE: "PIPELINE",
        "_conn_mgr": conn_mgr,
    }

    clear_company_selection(state)

    assert KEY_COMPANY_ID not in state
    assert KEY_PHASE1_RESULT not in state
    assert KEY_PIPELINE_RESULT not in state
    assert state[KEY_INGEST_STAGE] == "UPLOAD"
    assert conn_mgr.close_all_called is True


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


def test_load_batch_into_state_restores_persisted_phase2_overlays(monkeypatch, tmp_path):
    """Engagement 폴더의 overlay JSON 이 KEY_PHASE2_RESULT 까지 attach 되어야 한다."""
    from src.services.phase2_overlay_store import save_phase2_overlays

    engagement_dir = tmp_path / "acme" / "engagements" / "FY2024"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    ctx = SimpleNamespace(
        company_id="acme",
        engagement_id="FY2024",
        db_path=engagement_dir / "audit.duckdb",
    )
    overlays = [
        {
            "phase1_case_id": "case_001",
            "phase2_family_scores": {"duplicate": 0.7},
            "phase2_adjusted_priority": 0.8,
            "precision_adjustment_reason": "family_score_overlay",
            "detector_statuses": [],
            "phase2_inference_contract": None,
            "phase2_training_report_id": "report_x",
            "family_contributions": [],
            "top_family": "duplicate",
            "coverage_breadth_q95": 1,
            "max_family_ecdf": 0.9,
            "max_evidence_tier": "strong",
            "lane_membership": ["duplicate"],
            "coverage_gap_families": [],
        }
    ]
    save_phase2_overlays(ctx=ctx, batch_id="batch_persist", overlays=overlays)

    loaded = SimpleNamespace(
        data=pd.DataFrame({"risk_level": ["High"]}),
        featured_data=pd.DataFrame({"x": [1]}),
        file_name="loaded.csv",
        phase2_training_report_id="report_x",
    )
    monkeypatch.setattr("src.services.batch_service.load_batch", lambda conn, batch_id: loaded)

    state = {KEY_COMPANY_CONTEXT: ctx}
    result = load_batch_into_state(state, object(), "batch_persist")

    assert result is loaded
    assert state[KEY_BATCH_ID] == "batch_persist"
    # has_analysis_output(loaded) → True 이므로 KEY_PHASE2_RESULT 도 loaded.
    phase2_result = state.get(KEY_PHASE2_RESULT)
    assert phase2_result is loaded
    assert getattr(phase2_result, "phase2_case_overlays", None) == overlays


def test_load_batch_into_state_skips_overlay_when_ctx_missing(monkeypatch):
    """KEY_COMPANY_CONTEXT 없으면 overlay 본체는 attach 되지 않고, status 만 표시."""
    loaded = SimpleNamespace(
        data=pd.DataFrame({"risk_level": ["High"]}),
        featured_data=pd.DataFrame({"x": [1]}),
        file_name="loaded.csv",
        phase2_training_report_id="report_x",
    )
    monkeypatch.setattr("src.services.batch_service.load_batch", lambda conn, batch_id: loaded)

    state = {}
    load_batch_into_state(state, object(), "batch_no_ctx")

    phase2_result = state.get(KEY_PHASE2_RESULT)
    # phase2 메타가 있으므로 restore_loaded_result 가 KEY_PHASE2_RESULT 에 loaded 를 채움.
    assert phase2_result is loaded
    # 단 overlay 본체는 attach 안 되어 있고, status 는 ctx_missing 으로 표시되어야 한다.
    assert getattr(phase2_result, "phase2_case_overlays", None) is None
    assert getattr(phase2_result, "phase2_overlay_status", None) == "ctx_missing"


def test_load_batch_into_state_attaches_status_when_overlay_missing(monkeypatch, tmp_path):
    """E9/P2: overlay 파일이 없으면 status='missing' + 메시지가 loaded 에 attach."""
    engagement_dir = tmp_path / "acme" / "engagements" / "FY2024"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    ctx = SimpleNamespace(
        company_id="acme",
        engagement_id="FY2024",
        db_path=engagement_dir / "audit.duckdb",
    )
    loaded = SimpleNamespace(
        data=pd.DataFrame({"risk_level": ["High"]}),
        featured_data=pd.DataFrame({"x": [1]}),
        file_name="loaded.csv",
        phase2_training_report_id="report_x",
    )
    monkeypatch.setattr("src.services.batch_service.load_batch", lambda conn, batch_id: loaded)

    state = {KEY_COMPANY_CONTEXT: ctx}
    load_batch_into_state(state, object(), "batch_no_overlay")

    phase2_result = state.get(KEY_PHASE2_RESULT)
    assert phase2_result is loaded
    assert getattr(phase2_result, "phase2_case_overlays", None) is None
    assert getattr(phase2_result, "phase2_overlay_status", None) == "missing"
    assert getattr(phase2_result, "phase2_overlay_message", "")


def test_load_batch_into_state_attaches_status_on_schema_mismatch(monkeypatch, tmp_path):
    """E9/P2: schema_version 다른 overlay 파일 → status='schema_mismatch', overlay attach 안 됨."""
    import json as _json

    engagement_dir = tmp_path / "acme" / "engagements" / "FY2024"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    overlay_dir = engagement_dir / "phase2_overlays"
    overlay_dir.mkdir(parents=True, exist_ok=True)
    (overlay_dir / "batch_schema.json").write_text(
        _json.dumps(
            {
                "schema_version": "0.9",
                "batch_id": "batch_schema",
                "overlays": [],
            }
        ),
        encoding="utf-8",
    )

    ctx = SimpleNamespace(
        company_id="acme",
        engagement_id="FY2024",
        db_path=engagement_dir / "audit.duckdb",
    )
    loaded = SimpleNamespace(
        data=pd.DataFrame({"risk_level": ["High"]}),
        featured_data=pd.DataFrame({"x": [1]}),
        file_name="loaded.csv",
        # phase2 메타가 없으면 restore_loaded_result 가 KEY_PHASE2_RESULT=None 으로 둠.
        # status attach 자체는 일어나지만 phase2_result 가 None 이라 검증이 어려움.
        # 따라서 phase2 흔적은 있되 overlay 만 schema mismatch 인 시나리오로 설정.
        phase2_training_report_id="report_x",
    )
    monkeypatch.setattr("src.services.batch_service.load_batch", lambda conn, batch_id: loaded)

    state = {KEY_COMPANY_CONTEXT: ctx}
    load_batch_into_state(state, object(), "batch_schema")

    phase2_result = state.get(KEY_PHASE2_RESULT)
    assert phase2_result is loaded
    assert getattr(phase2_result, "phase2_case_overlays", None) is None
    assert getattr(phase2_result, "phase2_overlay_status", None) == "schema_mismatch"


def test_load_batch_into_state_rejects_stale_overlay_after_retrain(monkeypatch, tmp_path):
    """E9/P1c: overlay 의 training_report_id 가 batch_meta 와 다르면 attach 거부.

    재학습 후 batch_meta 는 새 report_id 로 update 되지만, overlay 파일에 이전
    report_id 가 남아있는 경우 stale 로 간주해 attach 거부해야 한다.
    """
    from src.services.phase2_overlay_store import save_phase2_overlays

    engagement_dir = tmp_path / "acme" / "engagements" / "FY2024"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    ctx = SimpleNamespace(
        company_id="acme",
        engagement_id="FY2024",
        db_path=engagement_dir / "audit.duckdb",
    )
    overlays = [
        {
            "phase1_case_id": "case_001",
            "phase2_family_scores": {},
            "phase2_adjusted_priority": None,
            "precision_adjustment_reason": "family_score_overlay",
            "detector_statuses": [],
            "phase2_inference_contract": None,
            "phase2_training_report_id": "report_old",
            "family_contributions": [],
            "top_family": None,
            "coverage_breadth_q95": 0,
            "max_family_ecdf": None,
            "max_evidence_tier": None,
            "lane_membership": [],
            "coverage_gap_families": [],
        }
    ]
    save_phase2_overlays(
        ctx=ctx,
        batch_id="batch_after_retrain",
        overlays=overlays,
        phase2_training_report_id="report_old",
    )

    # batch_meta 는 재학습 후 새 report_id (loaded 에 attach 된 값)
    loaded = SimpleNamespace(
        data=pd.DataFrame({"risk_level": ["High"]}),
        featured_data=pd.DataFrame({"x": [1]}),
        file_name="loaded.csv",
        phase2_training_report_id="report_new",
    )
    monkeypatch.setattr("src.services.batch_service.load_batch", lambda conn, batch_id: loaded)

    state = {KEY_COMPANY_CONTEXT: ctx}
    load_batch_into_state(state, object(), "batch_after_retrain")

    phase2_result = state.get(KEY_PHASE2_RESULT)
    assert phase2_result is loaded
    # overlay 의 report_id 가 stale 이므로 attach 거부.
    assert getattr(phase2_result, "phase2_case_overlays", None) is None


def test_prepare_mapped_data_resets_phase2_training_report_id(monkeypatch):
    """E10/P1b: prepare_mapped_data 가 KEY_PHASE2_TRAINING_REPORT_ID 도 reset 하는지.

    Why: 새 데이터 schema 가 이전 학습 기준과 다를 수 있어 reset 필요.
    """
    from dashboard._state import KEY_PHASE2_TRAINING_REPORT_ID
    from dashboard.components import mapping_finalize

    fake_result = SimpleNamespace(
        data=pd.DataFrame({"x": [1]}),
        featured_data=pd.DataFrame({"x": [1]}),
        batch_id="batch_new",
    )

    class _FakeSt:
        session_state: dict = {KEY_PHASE2_TRAINING_REPORT_ID: "old_report"}

    # Why: prepare_mapped_data 안에서 data_uploader 의 _run_pipeline_from_mapped 를
    #      lazy import 하므로, mapping_finalize 자체가 아니라 원본 모듈을 monkeypatch.
    monkeypatch.setattr(
        "dashboard.components.data_uploader._run_pipeline_from_mapped",
        lambda *args, **kwargs: (fake_result, []),
    )
    monkeypatch.setattr(mapping_finalize, "st", _FakeSt)
    monkeypatch.setattr(mapping_finalize, "_clear_ingest_review_state", lambda: None)

    mapping_finalize.prepare_mapped_data("journal.csv_123")

    assert _FakeSt.session_state[KEY_PHASE2_TRAINING_REPORT_ID] is None


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


def test_run_phase_analysis_phase1_invalidates_phase2_result():
    """E10/P1a: Phase 1 재실행 시 KEY_PHASE2_RESULT 가 None 으로 reset 되어야 한다.

    Why: 이전 phase1 case_id 기반 overlay 가 새 phase1 cases 와 어긋나 stale.
    """
    prep = SimpleNamespace(
        data=pd.DataFrame({"document_id": ["D1"], "line_text": [""]}),
        featured_data=None,
        file_name="journal.csv",
    )
    ctx = SimpleNamespace(
        db_path="engagement.duckdb",
        clone_with_settings=lambda settings: SimpleNamespace(db_path="engagement.duckdb"),
    )
    state = {
        KEY_PREP_RESULT: prep,
        KEY_COMPANY_CONTEXT: ctx,
        KEY_SETTINGS: _FakeSettings(),
        "_company_repo": object(),
        "_conn_mgr": SimpleNamespace(get=lambda path: f"conn:{path}"),
        # Phase 2 결과가 이미 메모리에 있는 상태
        KEY_PHASE2_RESULT: SimpleNamespace(batch_id="stale_phase2"),
    }

    run_phase_analysis(state, phase="phase1", pipeline_cls=_FakePipeline)

    assert state[KEY_PHASE2_RESULT] is None


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
