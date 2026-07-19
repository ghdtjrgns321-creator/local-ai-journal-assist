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
    KEY_PHASE1_RESULT,
    KEY_PHASE2_RESULT,
    KEY_PIPELINE_RESULT,
    KEY_PREP_RESULT,
    KEY_SETTINGS,
)
from src.services.phase2_inference_service import (
    load_latest_phase2_training_snapshot,
    run_phase2_inference,
    run_phase2_inference_analysis,
)
from tests.modules.test_services.test_phase2_case_contract import _phase1_result


def _make_local_temp_dir() -> Path:
    root = Path("tests") / ".tmp_phase2_inference"
    root.mkdir(parents=True, exist_ok=True)
    target = root / uuid.uuid4().hex
    target.mkdir(parents=True, exist_ok=True)
    return target


class _FakePipeline:
    last_phase2_inference_contract = None
    last_phase2_training_report_id = None
    last_phase2_promotion_policy = None
    last_phase2_inference_mode = None
    last_batch_id = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def redetect(
        self,
        featured_df,
        batch_id: str,
        file_name: str,
        reference_df=None,
        detection_scope: str = "default",
        phase2_inference_contract=None,
        phase2_training_report_id=None,
        phase2_promotion_policy=None,
        phase2_inference_mode=None,
    ):
        type(self).last_phase2_inference_contract = phase2_inference_contract
        type(self).last_phase2_training_report_id = phase2_training_report_id
        type(self).last_phase2_promotion_policy = phase2_promotion_policy
        type(self).last_phase2_inference_mode = phase2_inference_mode
        type(self).last_batch_id = batch_id
        # Why: phase2 추론은 phase1 batch_id 를 재사용해야 한다. fake pipeline 도 동일
        #      계약을 따라 받은 batch_id 를 그대로 반환하면 호출자가 새 row 를 만들지
        #      않는 흐름을 통과해 검증할 수 있다.
        return SimpleNamespace(
            data=featured_df.copy(),
            featured_data=featured_df.copy(),
            batch_id=batch_id,
            file_name=file_name,
            load_result=object(),
            warnings=[],
            detector_statuses=[],
        )


class _FakePipelineWithPhase1Case(_FakePipeline):
    def redetect(
        self,
        featured_df,
        batch_id: str,
        file_name: str,
        reference_df=None,
        detection_scope: str = "default",
        phase2_inference_contract=None,
        phase2_training_report_id=None,
        phase2_promotion_policy=None,
        phase2_inference_mode=None,
    ):
        result = super().redetect(
            featured_df,
            batch_id=batch_id,
            file_name=file_name,
            reference_df=reference_df,
            detection_scope=detection_scope,
            phase2_inference_contract=phase2_inference_contract,
            phase2_training_report_id=phase2_training_report_id,
            phase2_promotion_policy=phase2_promotion_policy,
            phase2_inference_mode=phase2_inference_mode,
        )
        result.phase1_case_result = _phase1_result()
        result.phase1_case_count = 1
        return result


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
        batch_id="phase1_batch",
        file_name="journal.csv",
        reference_df=featured_df,
        settings=_FakeSettings(),
        pipeline_cls=_FakePipeline,
    )

    assert result.batch_id == "phase1_batch"
    assert _FakePipeline.last_batch_id == "phase1_batch"
    assert result.file_name == "journal.csv"
    assert getattr(result, "phase2_inference_contract", None) is None
    assert result.phase2_inference_mode == "untrained_contract_only"


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
            batch_id="phase1_batch_training",
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
        assert _FakePipeline.last_phase2_inference_contract is result.phase2_inference_contract
        assert _FakePipeline.last_phase2_training_report_id == "train_001"
        assert _FakePipeline.last_phase2_promotion_policy == result.phase2_promotion_policy
        assert _FakePipeline.last_phase2_inference_mode == "training_contract"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_load_latest_phase2_training_snapshot_prefers_newest_report():
    root = _make_local_temp_dir()
    try:
        older = root / "models" / "phase2_train" / "train_old" / "reports"
        newer = root / "models" / "phase2_train" / "train_new" / "reports"
        older.mkdir(parents=True, exist_ok=True)
        newer.mkdir(parents=True, exist_ok=True)
        old_path = older / "training_report.json"
        new_path = newer / "training_report.json"
        old_path.write_text(
            json.dumps(
                {
                    "report_id": "train_old",
                    "metadata": {"inference_contract": {"required_models": ["old"]}},
                }
            ),
            encoding="utf-8",
        )
        new_path.write_text(
            json.dumps(
                {
                    "report_id": "train_new",
                    "metadata": {"inference_contract": {"required_models": ["new"]}},
                }
            ),
            encoding="utf-8",
        )
        old_time = 1_700_000_000
        new_time = old_time + 100
        import os

        os.utime(old_path, (old_time, old_time))
        os.utime(new_path, (new_time, new_time))

        snapshot = load_latest_phase2_training_snapshot(SimpleNamespace(model_dir=root / "models"))

        assert snapshot["report_id"] == "train_new"
        assert snapshot["inference_contract"]["required_models"] == ["new"]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_load_latest_phase2_training_snapshot_reads_leaderboard_and_decision():
    root = _make_local_temp_dir()
    try:
        reports = root / "models" / "phase2_train" / "train_001" / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        (reports / "training_report.json").write_text(
            json.dumps(
                {
                    "report_id": "train_001",
                    "metadata": {"inference_contract": {"required_models": ["duplicate"]}},
                }
            ),
            encoding="utf-8",
        )
        (reports / "leaderboard.json").write_text(
            json.dumps({"rows": [{"family": "duplicate", "schema_hash": None}]}),
            encoding="utf-8",
        )
        (reports / "promotion_decision.json").write_text(
            json.dumps({"family_decisions": {"duplicate": {"eligible_for_promotion": True}}}),
            encoding="utf-8",
        )

        snapshot = load_latest_phase2_training_snapshot(SimpleNamespace(model_dir=root / "models"))

        assert snapshot["leaderboard_artifact"]["rows"][0]["schema_hash"] is None
        assert snapshot["promotion_decision_artifact"]["family_decisions"]["duplicate"][
            "eligible_for_promotion"
        ]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_run_phase2_inference_marks_untrained_contract_only_without_snapshot():
    featured_df = pd.DataFrame({"document_id": ["D1"]})
    result = run_phase2_inference(
        featured_df,
        batch_id="phase1_batch",
        file_name="journal.csv",
        reference_df=featured_df,
        settings=_FakeSettings(),
        pipeline_cls=_FakePipeline,
    )

    assert result.phase2_inference_mode == "untrained_contract_only"


def test_run_phase2_inference_ignores_bootstrap_status_as_training_contract():
    class _BootstrapPipeline(_FakePipeline):
        def redetect(
            self,
            featured_df,
            batch_id: str,
            file_name: str,
            reference_df=None,
            detection_scope: str = "default",
            phase2_inference_contract=None,
            phase2_training_report_id=None,
            phase2_promotion_policy=None,
            phase2_inference_mode=None,
        ):
            result = super().redetect(
                featured_df,
                batch_id=batch_id,
                file_name=file_name,
                reference_df=reference_df,
                detection_scope=detection_scope,
                phase2_inference_contract=phase2_inference_contract,
                phase2_training_report_id=phase2_training_report_id,
                phase2_promotion_policy=phase2_promotion_policy,
                phase2_inference_mode=phase2_inference_mode,
            )
            result.detector_statuses = [
                {
                    "track_name": "ml_unsupervised",
                    "run_status": "executed",
                    "reason": "bootstrapped_" + "phase2_model",
                }
            ]
            return result

    featured_df = pd.DataFrame({"document_id": ["D1"]})
    result = run_phase2_inference(
        featured_df,
        batch_id="phase1_batch",
        file_name="journal.csv",
        reference_df=featured_df,
        settings=_FakeSettings(),
        pipeline_cls=_BootstrapPipeline,
    )

    assert result.phase2_inference_mode == "untrained_contract_only"


def test_run_phase2_inference_attaches_phase2_case_overlays_without_overwriting_phase1():
    featured_df = pd.DataFrame({"document_id": ["D1"]})
    result = run_phase2_inference(
        featured_df,
        batch_id="phase1_batch",
        file_name="journal.csv",
        reference_df=featured_df,
        settings=_FakeSettings(),
        pipeline_cls=_FakePipelineWithPhase1Case,
    )

    assert len(result.phase2_case_overlays) == 1
    overlay = result.phase2_case_overlays[0]
    assert overlay["phase1_case_id"] == "case_control_failure_00001"
    assert overlay["phase2_adjusted_priority"] is None
    assert overlay["precision_adjustment_reason"] == "phase2_not_applied"
    assert result.phase1_case_result.cases[0].priority_score == 0.8


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
    temp_dir = _make_local_temp_dir()
    ctx.db_path = temp_dir / "unit.store"
    ctx.clone_with_settings = lambda settings: SimpleNamespace(db_path=temp_dir / "unit.store")
    conn_mgr = SimpleNamespace(get=lambda path: f"conn:{path}")
    # Why: phase2 는 phase1 batch_id 를 재사용한다. KEY_PHASE1_RESULT 가 없으면
    #      run_phase2_inference_analysis 가 RuntimeError 로 막는 정상 흐름이다.
    phase1_result = SimpleNamespace(batch_id="phase1_batch")
    state = {
        KEY_PREP_RESULT: prep,
        KEY_PHASE1_RESULT: phase1_result,
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
            batch_id=kwargs["batch_id"],
            file_name=kwargs["file_name"],
            load_result=object(),
            warnings=[],
        ),
    )

    assert result.batch_id == "phase1_batch"
    assert state[KEY_PHASE2_RESULT] is result
    assert state[KEY_PIPELINE_RESULT] is result
    assert state[KEY_BATCH_ID] == "phase1_batch"
    assert isinstance(state[KEY_FEATURED_DATA], pd.DataFrame)


def test_run_phase2_inference_analysis_loads_phase1_case_artifact_for_overlay():
    phase1 = _phase1_result()
    temp_dir = _make_local_temp_dir()
    artifact_path = temp_dir / "phase1_case.json"
    artifact_json = phase1.__pydantic_serializer__.to_json(phase1).decode("utf-8")
    artifact_path.write_text(artifact_json, encoding="utf-8")
    prep = SimpleNamespace(
        data=pd.DataFrame({"document_id": ["D1"]}),
        featured_data=None,
        file_name="journal.csv",
    )
    phase1_metadata_only = SimpleNamespace(
        batch_id="phase1_batch",
        phase1_case_path=str(artifact_path),
        phase1_case_count=len(phase1.cases),
        phase1_case_run_id=phase1.run_id,
    )
    state = {
        KEY_PREP_RESULT: prep,
        KEY_PHASE1_RESULT: phase1_metadata_only,
        KEY_COMPANY_CONTEXT: None,
        KEY_SETTINGS: _FakeSettings(),
    }

    result = run_phase2_inference_analysis(
        state,
        inference_runner=lambda featured_df, **kwargs: SimpleNamespace(
            data=featured_df.copy(),
            featured_data=featured_df.copy(),
            batch_id=kwargs["batch_id"],
            file_name=kwargs["file_name"],
            load_result=object(),
            warnings=[],
            detector_statuses=[],
            phase1_case_result=None,
            phase2_case_overlays=[],
        ),
    )

    assert result.phase1_case_result is phase1_metadata_only.phase1_case_result
    assert result.phase1_case_count == len(phase1.cases)
    assert len(result.phase2_case_overlays) == len(phase1.cases)
    assert result.phase2_case_overlays[0]["phase1_case_id"] == phase1.cases[0].case_id


def test_run_phase2_inference_analysis_keeps_redetect_cases_when_canonical_missing():
    phase1 = _phase1_result()
    prep = SimpleNamespace(
        data=pd.DataFrame({"document_id": ["D1"]}),
        featured_data=None,
        file_name="journal.csv",
    )
    phase1_metadata_only = SimpleNamespace(
        batch_id="phase1_batch",
        phase1_case_path="missing_phase1_case_artifact.json",
        phase1_case_count=len(phase1.cases),
        phase1_case_run_id=phase1.run_id,
        phase1_case_result=None,
    )
    state = {
        KEY_PREP_RESULT: prep,
        KEY_PHASE1_RESULT: phase1_metadata_only,
        KEY_COMPANY_CONTEXT: None,
        KEY_SETTINGS: _FakeSettings(),
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
            detector_statuses=[],
            phase1_case_result=phase1,
            phase1_case_count=len(phase1.cases),
            phase2_case_overlays=[],
        ),
    )

    assert result.phase1_case_result is phase1
    assert len(result.phase2_case_overlays) == len(phase1.cases)
    assert result.phase2_case_overlays[0]["phase1_case_id"] == phase1.cases[0].case_id


def test_run_phase2_inference_analysis_keeps_result_when_db_load_fails():
    prep = SimpleNamespace(
        data=pd.DataFrame({"document_id": ["D1"]}),
        featured_data=None,
        file_name="journal.csv",
    )
    state = {
        KEY_PREP_RESULT: prep,
        KEY_PHASE1_RESULT: SimpleNamespace(batch_id="phase1_batch"),
        KEY_COMPANY_CONTEXT: None,
        KEY_SETTINGS: _FakeSettings(),
    }

    result = run_phase2_inference_analysis(
        state,
        inference_runner=lambda featured_df, **kwargs: SimpleNamespace(
            data=featured_df.copy(),
            featured_data=featured_df.copy(),
            batch_id=kwargs["batch_id"],
            file_name=kwargs["file_name"],
            load_result=None,
            warnings=["group_loss_dominated", "DB 적재 실패"],
        ),
    )

    assert result.batch_id == "phase1_batch"
    assert state[KEY_PHASE2_RESULT] is result
    assert state[KEY_PIPELINE_RESULT] is result
    assert state[KEY_BATCH_ID] == "phase1_batch"


def test_run_phase2_inference_analysis_keeps_result_when_featured_cache_write_fails():
    class FailingFeaturedDataState(dict):
        def __setitem__(self, key, value):
            if key == KEY_FEATURED_DATA:
                raise RuntimeError("group_loss_dominated; DB 적재 실패")
            return super().__setitem__(key, value)

    prep = SimpleNamespace(
        data=pd.DataFrame({"document_id": ["D1"]}),
        featured_data=None,
        file_name="journal.csv",
    )
    state = FailingFeaturedDataState(
        {
            KEY_PREP_RESULT: prep,
            KEY_PHASE1_RESULT: SimpleNamespace(batch_id="phase1_batch"),
            KEY_COMPANY_CONTEXT: None,
            KEY_SETTINGS: _FakeSettings(),
        }
    )

    result = run_phase2_inference_analysis(
        state,
        inference_runner=lambda featured_df, **kwargs: SimpleNamespace(
            data=featured_df.copy(),
            featured_data=featured_df.copy(),
            batch_id=kwargs["batch_id"],
            file_name=kwargs["file_name"],
            load_result=None,
            warnings=["group_loss_dominated", "DB 적재 실패"],
        ),
    )

    assert result.batch_id == "phase1_batch"
    assert state[KEY_PHASE2_RESULT] is result
    assert state[KEY_PIPELINE_RESULT] is result
    assert state[KEY_BATCH_ID] == "phase1_batch"
    assert KEY_FEATURED_DATA not in state
    assert any("featured_data 세션 저장 스킵" in warning for warning in result.warnings)


def test_run_phase2_inference_analysis_filters_selected_year_partition():
    prep = SimpleNamespace(
        data=pd.DataFrame(
            {
                "document_id": ["D1", "D2", "D3"],
                "fiscal_year": [2022, 2024, 2024],
            }
        ),
        featured_data=None,
        file_name="journal.csv",
    )
    state = {
        KEY_PREP_RESULT: prep,
        KEY_PHASE1_RESULT: SimpleNamespace(batch_id="phase1_batch"),
        KEY_COMPANY_CONTEXT: None,
        KEY_SETTINGS: _FakeSettings(),
    }

    result = run_phase2_inference_analysis(
        state,
        partition="2024",
        inference_runner=lambda featured_df, **kwargs: SimpleNamespace(
            data=featured_df.copy(),
            featured_data=featured_df.copy(),
            batch_id=kwargs["batch_id"],
            file_name=kwargs["file_name"],
            load_result=object(),
            warnings=[],
        ),
    )

    assert list(result.data["document_id"]) == ["D2", "D3"]
    assert result.phase2_partition == "2024"


# ── P3: phase1_case_basis_status attach 통합 테스트 ───────────


from src.export.phase1_case_view import Phase1CaseBasisStatus  # noqa: E402
from src.services.phase2_inference_service import _inherit_phase1_case_result  # noqa: E402


def test_inherit_phase1_case_attaches_canonical_in_memory_status():
    """canonical in-memory: status=canonical_in_memory + phase1_case_result 덮어쓰기."""
    phase1 = _phase1_result()
    phase1_holder = SimpleNamespace(
        phase1_case_result=phase1,
        phase1_case_count=len(phase1.cases),
    )
    result = SimpleNamespace(
        data=pd.DataFrame({"x": [1]}),
        results=[],
        phase1_case_result=None,
    )

    _inherit_phase1_case_result(result, phase1_holder)

    assert result.phase1_case_basis_status == Phase1CaseBasisStatus.CANONICAL_IN_MEMORY
    assert result.phase1_case_result is phase1
    assert result.phase1_case_basis_message
    assert result.phase1_case_count == len(phase1.cases)


def test_inherit_phase1_case_attaches_canonical_artifact_status():
    """phase1_case_path 존재 + load 성공 → canonical_artifact + 캐시 mutate."""
    phase1 = _phase1_result()
    temp_dir = _make_local_temp_dir()
    artifact_path = temp_dir / "phase1_case.json"
    artifact_path.write_text(
        phase1.__pydantic_serializer__.to_json(phase1).decode("utf-8"),
        encoding="utf-8",
    )
    phase1_holder = SimpleNamespace(
        phase1_case_path=str(artifact_path),
        phase1_case_count=len(phase1.cases),
    )
    result = SimpleNamespace(
        data=pd.DataFrame({"x": [1]}),
        results=[],
        phase1_case_result=None,
    )

    _inherit_phase1_case_result(result, phase1_holder)

    assert result.phase1_case_basis_status == Phase1CaseBasisStatus.CANONICAL_ARTIFACT
    assert result.phase1_case_result is not None
    assert len(result.phase1_case_result.cases) == len(phase1.cases)
    # mutate: 다음 호출에서는 canonical_in_memory 로 해소되어야 한다.
    assert phase1_holder.phase1_case_result is result.phase1_case_result


def test_inherit_phase1_case_attaches_fallback_redetect_status():
    """artifact 없음 + redetect cases 있음 → fallback_redetect."""
    redetect_cases = _phase1_result()
    phase1_holder = SimpleNamespace(
        phase1_case_path="/nonexistent/path.json",
        phase1_case_count=5,
    )
    result = SimpleNamespace(
        data=pd.DataFrame({"x": [1]}),
        results=[],
        phase1_case_result=redetect_cases,
    )

    _inherit_phase1_case_result(result, phase1_holder)

    assert result.phase1_case_basis_status == Phase1CaseBasisStatus.FALLBACK_REDETECT
    # fallback 상태에서는 redetect cases 를 덮어쓰지 않는다 (정책).
    assert result.phase1_case_result is redetect_cases


def test_inherit_phase1_case_attaches_unavailable_when_phase1_none():
    """phase1_result=None → unavailable."""
    result = SimpleNamespace(
        data=pd.DataFrame({"x": [1]}),
        results=[],
        phase1_case_result=None,
    )

    _inherit_phase1_case_result(result, None)

    assert result.phase1_case_basis_status == Phase1CaseBasisStatus.UNAVAILABLE
    assert getattr(result, "phase1_case_result", None) is None


# ── P4: status axes attach 통합 테스트 ────────────────────────


from src.services.phase2_inference_service import (  # noqa: E402
    _apply_partition_filter,
    _apply_partition_filter_with_status,
    _attach_phase2_context_status,
    _persist_phase2_batch_snapshot,
)


def test_persist_phase2_batch_snapshot_attaches_saved_status():
    """conn + load_result + batch_id 가 모두 있고 update 성공 → saved."""
    called = {}

    class _FakeConn:
        pass

    def _fake_update(conn, batch_id, **kwargs):
        called["batch_id"] = batch_id

    import src.db.loader as loader_mod

    original = getattr(loader_mod, "update_upload_batch_meta", None)
    loader_mod.update_upload_batch_meta = _fake_update
    try:
        result = SimpleNamespace(
            batch_id="b1",
            load_result=object(),
            phase2_training_report_id=None,
            phase2_inference_contract=None,
            phase2_promotion_policy=None,
            phase2_inference_mode=None,
            detector_statuses=None,
        )
        warning = _persist_phase2_batch_snapshot(conn=_FakeConn(), result=result)
        assert warning is None
        assert result.phase2_db_load_status == "saved"
        assert called["batch_id"] == "b1"
    finally:
        if original is not None:
            loader_mod.update_upload_batch_meta = original


def test_persist_phase2_batch_snapshot_attaches_skipped_no_conn():
    """conn=None → skipped_no_conn."""
    result = SimpleNamespace(batch_id="b1", load_result=object())
    warning = _persist_phase2_batch_snapshot(conn=None, result=result)
    assert warning is None
    assert result.phase2_db_load_status == "skipped_no_conn"
    assert "DB connection" in result.phase2_db_load_message


def test_persist_phase2_batch_snapshot_attaches_skipped_no_load_result():
    """batch_id 비어있을 때 update_upload_batch_meta 호출 안 함 (skip).

    Why: phase2 추론은 phase1 batch_id 재사용 모델로 변경되어 ``_load_db`` 가 스킵된다.
    이 함수의 가드는 ``load_result is None`` 이 아니라 ``not batch_id`` 로 좁혀졌고,
    batch_id 만 있으면 phase1 row 의 phase2 컬럼 UPDATE 를 시도한다.
    """
    result = SimpleNamespace(batch_id="", load_result=None)
    warning = _persist_phase2_batch_snapshot(conn=object(), result=result)
    assert warning is None
    assert result.phase2_db_load_status == "skipped_no_load_result"


def test_persist_phase2_batch_snapshot_attaches_failed_status():
    """update_upload_batch_meta 예외 → failed + warning string 반환."""
    import src.db.loader as loader_mod

    original = getattr(loader_mod, "update_upload_batch_meta", None)

    def _raise(*args, **kwargs):
        raise RuntimeError("disk full")

    loader_mod.update_upload_batch_meta = _raise
    try:
        result = SimpleNamespace(
            batch_id="b1",
            load_result=object(),
            phase2_training_report_id=None,
            phase2_inference_contract=None,
            phase2_promotion_policy=None,
            phase2_inference_mode=None,
            detector_statuses=None,
        )
        warning = _persist_phase2_batch_snapshot(conn=object(), result=result)
        assert warning is not None
        assert "disk full" in warning
        assert result.phase2_db_load_status == "failed"
        assert "disk full" in result.phase2_db_load_message
    finally:
        if original is not None:
            loader_mod.update_upload_batch_meta = original


def test_apply_partition_filter_with_status_returns_executed_when_year_present():
    """fiscal_year 가 있고 매칭 row 가 있으면 executed == requested + fallback_reason=None."""
    df = pd.DataFrame({"fiscal_year": [2024, 2024, 2023], "x": [1, 2, 3]})
    filtered, status = _apply_partition_filter_with_status(df, "2024")
    assert len(filtered) == 2
    assert status["requested"] == "2024"
    assert status["executed"] == "2024"
    assert status["fallback_reason"] is None


def test_apply_partition_filter_with_status_fallback_when_zero_rows():
    """선택 연도에 0 rows 면 전체 df + fallback_reason 명시."""
    df = pd.DataFrame({"fiscal_year": [2022, 2022], "x": [1, 2]})
    filtered, status = _apply_partition_filter_with_status(df, "2024")
    assert len(filtered) == 2  # full fallback
    assert status["requested"] == "2024"
    assert status["executed"] == "전체"
    assert status["fallback_reason"] == "selected_year_zero_rows"


def test_apply_partition_filter_backward_compat_returns_df_only():
    """기존 호출자 호환 — df 만 반환."""
    df = pd.DataFrame({"fiscal_year": [2024], "x": [1]})
    out = _apply_partition_filter(df, "2024")
    assert len(out) == 1


def test_attach_phase2_context_status_company_context():
    """ctx + db_path → company_context."""
    result = SimpleNamespace()
    ctx = SimpleNamespace(db_path=Path("/tmp/x.duckdb"))
    _attach_phase2_context_status(result, ctx)
    assert result.phase2_context_status == "company_context"


def test_attach_phase2_context_status_missing_context():
    """ctx=None → missing_context."""
    result = SimpleNamespace()
    _attach_phase2_context_status(result, None)
    assert result.phase2_context_status == "missing_context"


def test_attach_phase2_context_status_missing_db_path():
    """ctx 는 있지만 db_path 없음 → missing_db_path."""
    result = SimpleNamespace()
    ctx = SimpleNamespace(db_path=None)
    _attach_phase2_context_status(result, ctx)
    assert result.phase2_context_status == "missing_db_path"
