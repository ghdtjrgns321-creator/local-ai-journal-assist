"""AuditPipeline unit and integration tests."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from config.settings import AuditSettings
from src.detection.base import DetectionResult, RuleFlag
from src.ingest.datasynth_metadata import MetadataReconciliation
from src.pipeline import AuditPipeline, PipelineResult


class TestRunFromDataframe:
    def test_basic(self, small_gl_df):
        result = AuditPipeline(skip_db=True).run_from_dataframe(small_gl_df)

        assert isinstance(result, PipelineResult)
        assert "anomaly_score" in result.data.columns
        assert "risk_level" in result.data.columns
        assert result.elapsed > 0

    def test_results_count(self, small_gl_df):
        result = AuditPipeline(skip_db=True).run_from_dataframe(small_gl_df)

        track_names = {r.track_name for r in result.results}
        assert {"layer_a", "layer_b", "layer_c", "benford"}.issubset(track_names)
        assert "evidence" not in track_names
        assert "nlp" not in track_names

        detector_statuses = {
            status["track_name"]: status for status in result.detector_statuses
        }
        assert "nlp" in detector_statuses
        assert detector_statuses["nlp"]["run_status"] == "not_in_path"

    def test_batch_id_format(self, small_gl_df):
        result = AuditPipeline(skip_db=True).run_from_dataframe(small_gl_df)

        assert len(result.batch_id) == 8
        int(result.batch_id, 16)

    def test_risk_summary_keys(self, small_gl_df):
        result = AuditPipeline(skip_db=True).run_from_dataframe(small_gl_df)

        assert isinstance(result.risk_summary, dict)
        assert len(result.risk_summary) >= 1

    def test_skip_db(self, small_gl_df):
        result = AuditPipeline(skip_db=True).run_from_dataframe(small_gl_df)
        assert result.load_result is None

    def test_preserves_uploaded_source_hint_for_datasynth(self, monkeypatch, small_gl_df):
        seen: dict[str, str] = {}

        def _capture(df, *, source_path=None, mode="hidden"):
            seen["source_path"] = str(source_path)
            seen["mode"] = mode
            return df

        monkeypatch.setattr("src.pipeline.apply_datasynth_label_mode", _capture)

        AuditPipeline(skip_db=True).run_from_dataframe(
            small_gl_df,
            file_name="journal_entries_2022.csv",
        )

        assert seen["source_path"] == "journal_entries_2022.csv"
        assert seen["mode"] == "hidden"

    def test_uses_ground_truth_report_when_datasynth_labels_exist(self, monkeypatch, small_gl_df):
        labels_df = pd.DataFrame(
            {
                "document_id": [small_gl_df.iloc[0]["document_id"]],
                "anomaly_type": ["UnbalancedEntry"],
            }
        )

        monkeypatch.setattr(
            "src.pipeline.load_document_labels",
            lambda source_path: labels_df.copy(),
        )

        result = AuditPipeline(skip_db=True).run_from_dataframe(
            small_gl_df,
            file_name="journal_entries_2022.csv",
        )

        assert result.performance_report is not None
        assert result.performance_report.source_kind == "ground_truth"

    def test_falls_back_to_operational_report_without_datasynth_labels(
        self, monkeypatch, small_gl_df,
    ):
        monkeypatch.setattr("src.pipeline.load_document_labels", lambda source_path: None)

        result = AuditPipeline(skip_db=True).run_from_dataframe(
            small_gl_df,
            file_name="journal_entries_2022.csv",
        )

        assert result.performance_report is not None
        assert result.performance_report.source_kind == "operational_proxy"

    def test_warns_on_datasynth_metadata_mismatch(self, monkeypatch, small_gl_df):
        monkeypatch.setattr("src.pipeline.load_document_labels", lambda source_path: None)
        monkeypatch.setattr(
            "src.pipeline.load_validated_metadata_json",
            lambda source_path: MetadataReconciliation(
                status="fail",
                critical_mismatches=["total_entries: reported=0, observed=2"],
                warning_mismatches=["duplicates.total_duplicates: reported=0, observed=1"],
                reported_generation_statistics={},
                reported_data_quality_stats={},
                observed={},
            ),
        )

        result = AuditPipeline(
            settings=AuditSettings(datasynth_metadata_enforcement="warn"),
            skip_db=True,
        ).run_from_dataframe(small_gl_df, file_name="journal_entries_2022.csv")

        assert any("DataSynth metadata validation failed" in warning for warning in result.warnings)
        assert result.data.attrs["datasynth_metadata_status"] == "fail"

    def test_blocks_on_datasynth_metadata_mismatch_in_strict_mode(self, monkeypatch, small_gl_df):
        monkeypatch.setattr("src.pipeline.load_document_labels", lambda source_path: None)
        monkeypatch.setattr(
            "src.pipeline.load_validated_metadata_json",
            lambda source_path: MetadataReconciliation(
                status="fail",
                critical_mismatches=["total_entries: reported=0, observed=2"],
                warning_mismatches=[],
                reported_generation_statistics={},
                reported_data_quality_stats={},
                observed={},
            ),
        )

        with pytest.raises(ValueError, match="DataSynth metadata validation failed"):
            AuditPipeline(
                settings=AuditSettings(datasynth_metadata_enforcement="strict"),
                skip_db=True,
            ).run_from_dataframe(small_gl_df, file_name="journal_entries_2022.csv")

    def test_skips_supervised_when_training_gate_blocks_model(self, monkeypatch, small_gl_df):
        class DummyRegistry:
            pass

        class DummySupervisedDetector:
            def __init__(self, settings=None, model_registry=None):
                self.model_registry = model_registry

            def load_model(self, model_name="supervised", version=None):
                return None

            def get_training_gate_snapshot(self):
                return {
                    "label_source": "detection_scores",
                    "positive_count": 80,
                    "positive_rate": 0.2,
                    "gate_status": "fallback_to_unsupervised",
                    "gate_reason": "circular_label_risk",
                }

        class DummyUnsupervisedDetector:
            def __init__(self, settings=None, model_registry=None):
                self.model_registry = model_registry

            def load_model(self, model_name="unsupervised", version=None):
                return None

            def detect(self, df):
                scores = pd.Series(0.2, index=df.index, name="ML02")
                details = pd.DataFrame({"ML02": scores}, index=df.index)
                return DetectionResult(
                    track_name="ml_unsupervised",
                    flagged_indices=[],
                    scores=scores,
                    rule_flags=[RuleFlag("ML02", "ML02", 3, 0, len(df))],
                    details=details,
                    metadata={
                        "elapsed": 0.01,
                        "skipped_rules": [],
                        "matrix_schema_hash": 12345,
                    },
                    warnings=[],
                )

        monkeypatch.setattr("src.preprocessing.model_registry.ModelRegistry", DummyRegistry)
        monkeypatch.setattr(
            "src.detection.supervised_detector.SupervisedDetector",
            DummySupervisedDetector,
        )
        monkeypatch.setattr(
            "src.detection.vae_detector.UnsupervisedDetector",
            DummyUnsupervisedDetector,
        )
        monkeypatch.setattr("src.context.CompanyContext.is_anonymous", property(lambda self: False))
        monkeypatch.setattr("src.pipeline.load_document_labels", lambda source_path: None)

        result = AuditPipeline(
            settings=AuditSettings(enable_ml_detection=True),
            skip_db=True,
        ).run_from_dataframe(small_gl_df, file_name="journal_entries_2022.csv")

        statuses = {status["track_name"]: status for status in result.detector_statuses}
        assert statuses["ml_supervised"]["run_status"] == "skipped"
        assert statuses["ml_supervised"]["reason"] == "circular_label_risk"
        assert statuses["ml_unsupervised"]["run_status"] == "executed"
        assert "ml_supervised" not in {r.track_name for r in result.results}
        assert "ml_unsupervised" in {r.track_name for r in result.results}

    def test_marks_legacy_supervised_model_as_unknown_training_gate(self, monkeypatch, small_gl_df):
        class DummyRegistry:
            pass

        class DummySupervisedDetector:
            def __init__(self, settings=None, model_registry=None):
                self.model_registry = model_registry

            def load_model(self, model_name="supervised", version=None):
                return None

            def get_training_gate_snapshot(self):
                return {
                    "label_source": "unknown",
                    "positive_count": 0,
                    "positive_rate": 0.0,
                    "gate_status": "unknown",
                    "gate_reason": None,
                }

            def detect(self, df):
                scores = pd.Series(0.1, index=df.index, name="ML01")
                details = pd.DataFrame({"ML01": scores}, index=df.index)
                return DetectionResult(
                    track_name="ml_supervised",
                    flagged_indices=[],
                    scores=scores,
                    rule_flags=[RuleFlag("ML01", "ML01", 3, 0, len(df))],
                    details=details,
                    metadata={"elapsed": 0.01, "skipped_rules": []},
                    warnings=[],
                )

        class DummyUnsupervisedDetector:
            def __init__(self, settings=None, model_registry=None):
                self.model_registry = model_registry

            def load_model(self, model_name="unsupervised", version=None):
                raise FileNotFoundError

        monkeypatch.setattr("src.preprocessing.model_registry.ModelRegistry", DummyRegistry)
        monkeypatch.setattr(
            "src.detection.supervised_detector.SupervisedDetector",
            DummySupervisedDetector,
        )
        monkeypatch.setattr(
            "src.detection.vae_detector.UnsupervisedDetector",
            DummyUnsupervisedDetector,
        )
        monkeypatch.setattr("src.context.CompanyContext.is_anonymous", property(lambda self: False))
        monkeypatch.setattr("src.pipeline.load_document_labels", lambda source_path: None)

        result = AuditPipeline(
            settings=AuditSettings(enable_ml_detection=True),
            skip_db=True,
        ).run_from_dataframe(small_gl_df, file_name="journal_entries_2022.csv")

        statuses = {status["track_name"]: status for status in result.detector_statuses}
        assert statuses["ml_supervised"]["run_status"] == "executed"
        assert statuses["ml_supervised"]["reason"] == "unknown_training_gate"

    def test_uses_context_model_dir_for_phase2_model_registry(self, monkeypatch, small_gl_df):
        root = Path("tests") / ".tmp_pipeline_registry" / uuid.uuid4().hex
        model_dir = root / "models"
        model_dir.mkdir(parents=True, exist_ok=True)
        registry_dirs = []

        class DummyRegistry:
            def __init__(self, registry_dir=None):
                registry_dirs.append(registry_dir)

        monkeypatch.setattr("src.preprocessing.model_registry.ModelRegistry", DummyRegistry)
        monkeypatch.setattr("src.context.CompanyContext.is_anonymous", property(lambda self: False))
        monkeypatch.setattr("src.pipeline.load_document_labels", lambda source_path: None)

        settings = AuditSettings(enable_ml_detection=True)
        try:
            ctx = SimpleNamespace(
                settings=settings,
                schema={},
                keywords={},
                audit_rules={},
                risk_keywords={},
                chart_of_accounts=None,
                model_dir=model_dir,
                company_id="acme",
                engagement_id="acme_2025",
                is_anonymous=False,
            )

            AuditPipeline(context=ctx, skip_db=True).redetect(
                small_gl_df,
                detection_scope="phase2_only",
            )

            assert registry_dirs
            assert all(path == model_dir for path in registry_dirs)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_detector_status_carries_phase2_provenance_fields(self, monkeypatch, small_gl_df):
        class DummyRegistry:
            pass

        class DummySupervisedDetector:
            def __init__(self, settings=None, model_registry=None):
                self.model_registry = model_registry

            def load_model(self, model_name="supervised", version=None):
                raise FileNotFoundError

        class DummyUnsupervisedDetector:
            def __init__(self, settings=None, model_registry=None):
                self.model_registry = model_registry

            def load_model(self, model_name="unsupervised", version=None):
                return None

            def detect(self, df):
                scores = pd.Series(0.2, index=df.index, name="ML02")
                details = pd.DataFrame({"ML02": scores}, index=df.index)
                return DetectionResult(
                    track_name="ml_unsupervised",
                    flagged_indices=[],
                    scores=scores,
                    rule_flags=[RuleFlag("ML02", "ML02", 3, 0, len(df))],
                    details=details,
                    metadata={
                        "elapsed": 0.01,
                        "skipped_rules": [],
                        "registry_version": 7,
                        "saved_model_name": "unsupervised",
                        "sub_detector_keys": ["transaction_burst", "unusual_frequency"],
                    },
                    warnings=[],
                )

        monkeypatch.setattr("src.preprocessing.model_registry.ModelRegistry", DummyRegistry)
        monkeypatch.setattr(
            "src.detection.supervised_detector.SupervisedDetector",
            DummySupervisedDetector,
        )
        monkeypatch.setattr(
            "src.detection.vae_detector.UnsupervisedDetector",
            DummyUnsupervisedDetector,
        )
        monkeypatch.setattr("src.context.CompanyContext.is_anonymous", property(lambda self: False))
        monkeypatch.setattr("src.pipeline.load_document_labels", lambda source_path: None)

        result = AuditPipeline(
            settings=AuditSettings(enable_ml_detection=True),
            skip_db=True,
        ).run_from_dataframe(small_gl_df, file_name="journal_entries_2022.csv")

        statuses = {status["track_name"]: status for status in result.detector_statuses}
        assert statuses["ml_unsupervised"]["registry_version"] == 7
        assert statuses["ml_unsupervised"]["saved_model_name"] == "unsupervised"
        assert statuses["ml_unsupervised"]["sub_detector_keys"] == [
            "transaction_burst",
            "unusual_frequency",
        ]

    def test_phase2_only_loads_contract_pinned_unsupervised_version(
        self, monkeypatch, small_gl_df,
    ):
        load_calls = []
        supervised_load_calls = []

        class DummyRegistry:
            pass

        class DummySupervisedDetector:
            def __init__(self, settings=None, model_registry=None):
                self.model_registry = model_registry

            def load_model(self, model_name="supervised", version=None):
                supervised_load_calls.append((model_name, version))
                raise FileNotFoundError

        class DummyUnsupervisedDetector:
            def __init__(self, settings=None, model_registry=None):
                self.model_registry = model_registry

            def load_model(self, model_name="unsupervised", version=None):
                load_calls.append((model_name, version))
                return None

            def detect(self, df):
                scores = pd.Series(0.2, index=df.index, name="ML02")
                details = pd.DataFrame({"ML02": scores}, index=df.index)
                return DetectionResult(
                    track_name="ml_unsupervised",
                    flagged_indices=[],
                    scores=scores,
                    rule_flags=[RuleFlag("ML02", "ML02", 3, 0, len(df))],
                    details=details,
                    metadata={
                        "elapsed": 0.01,
                        "skipped_rules": [],
                        "matrix_schema_hash": 12345,
                    },
                    warnings=[],
                )

        monkeypatch.setattr("src.preprocessing.model_registry.ModelRegistry", DummyRegistry)
        monkeypatch.setattr(
            "src.detection.supervised_detector.SupervisedDetector",
            DummySupervisedDetector,
        )
        monkeypatch.setattr(
            "src.detection.vae_detector.UnsupervisedDetector",
            DummyUnsupervisedDetector,
        )
        monkeypatch.setattr("src.context.CompanyContext.is_anonymous", property(lambda self: False))
        monkeypatch.setattr("src.pipeline.load_document_labels", lambda source_path: None)

        contract = {
            "contract_version": "phase2_unsupervised_mvp_v1",
            "promoted_versions": {"unsupervised": 7},
        }
        result = AuditPipeline(
            settings=AuditSettings(enable_ml_detection=True),
            skip_db=True,
        ).redetect(
            small_gl_df,
            detection_scope="phase2_only",
            phase2_inference_contract=contract,
        )

        assert load_calls == [("unsupervised", 7)]
        assert supervised_load_calls == []
        statuses = {status["track_name"]: status for status in result.detector_statuses}
        assert statuses["ml_supervised"]["run_status"] == "skipped"
        assert statuses["ml_supervised"]["reason"] == "phase2_unsupervised_only"
        assert statuses["ml_unsupervised"]["contract_version"] == "phase2_unsupervised_mvp_v1"
        assert statuses["ml_unsupervised"]["loaded_version"] == 7
        assert statuses["ml_unsupervised"]["matrix_schema_hash"] == 12345
        assert result.results[0].metadata["contract_version"] == "phase2_unsupervised_mvp_v1"
        assert result.results[0].metadata["loaded_version"] == 7

    def test_phase2_only_skips_stacking_ensemble(self, monkeypatch, small_gl_df):
        def fail_stacking(self, results, df):
            raise AssertionError("phase2_only must not invoke stacking ensemble")

        class DummyRegistry:
            pass

        class DummySupervisedDetector:
            def __init__(self, settings=None, model_registry=None):
                self.model_registry = model_registry

            def load_model(self, model_name="supervised", version=None):
                raise AssertionError("phase2_only must not load supervised model")

        class DummyUnsupervisedDetector:
            def __init__(self, settings=None, model_registry=None):
                self.model_registry = model_registry

            def load_model(self, model_name="unsupervised", version=None):
                return None

            def detect(self, df):
                scores = pd.Series(0.2, index=df.index, name="ML02")
                details = pd.DataFrame({"ML02": scores}, index=df.index)
                return DetectionResult(
                    track_name="ml_unsupervised",
                    flagged_indices=[],
                    scores=scores,
                    rule_flags=[RuleFlag("ML02", "ML02", 3, 0, len(df))],
                    details=details,
                    metadata={"elapsed": 0.01, "skipped_rules": []},
                    warnings=[],
                )

        monkeypatch.setattr(AuditPipeline, "_try_stacking_ensemble", fail_stacking)
        monkeypatch.setattr("src.preprocessing.model_registry.ModelRegistry", DummyRegistry)
        monkeypatch.setattr(
            "src.detection.supervised_detector.SupervisedDetector",
            DummySupervisedDetector,
        )
        monkeypatch.setattr(
            "src.detection.vae_detector.UnsupervisedDetector",
            DummyUnsupervisedDetector,
        )
        monkeypatch.setattr("src.context.CompanyContext.is_anonymous", property(lambda self: False))
        monkeypatch.setattr("src.pipeline.load_document_labels", lambda source_path: None)

        result = AuditPipeline(
            settings=AuditSettings(enable_ml_detection=True),
            skip_db=True,
        ).redetect(small_gl_df, detection_scope="phase2_only")

        statuses = {status["track_name"]: status for status in result.detector_statuses}
        assert statuses["ensemble"]["run_status"] != "executed"
        assert {item.track_name for item in result.results} == {"ml_unsupervised"}

    def test_default_redetect_still_invokes_stacking_when_ml_enabled(
        self, monkeypatch, small_gl_df,
    ):
        stacking_calls = []

        def capture_stacking(self, results, df):
            stacking_calls.append([result.track_name for result in results])
            return None

        monkeypatch.setattr(AuditPipeline, "_try_ml_detection", lambda self, df, **kwargs: [])
        monkeypatch.setattr(AuditPipeline, "_try_stacking_ensemble", capture_stacking)

        AuditPipeline(
            settings=AuditSettings(enable_ml_detection=True),
            skip_db=True,
        ).redetect(small_gl_df)

        assert stacking_calls

    def test_phase2_only_without_contract_uses_latest_unsupervised_fallback(
        self, monkeypatch, small_gl_df,
    ):
        load_calls = []

        class DummyRegistry:
            pass

        class DummySupervisedDetector:
            def __init__(self, settings=None, model_registry=None):
                self.model_registry = model_registry

            def load_model(self, model_name="supervised", version=None):
                raise FileNotFoundError

        class DummyUnsupervisedDetector:
            def __init__(self, settings=None, model_registry=None):
                self.model_registry = model_registry

            def load_model(self, model_name="unsupervised", version=None):
                load_calls.append((model_name, version))
                return None

            def detect(self, df):
                scores = pd.Series(0.2, index=df.index, name="ML02")
                details = pd.DataFrame({"ML02": scores}, index=df.index)
                return DetectionResult(
                    track_name="ml_unsupervised",
                    flagged_indices=[],
                    scores=scores,
                    rule_flags=[RuleFlag("ML02", "ML02", 3, 0, len(df))],
                    details=details,
                    metadata={"elapsed": 0.01, "skipped_rules": []},
                    warnings=[],
                )

        monkeypatch.setattr("src.preprocessing.model_registry.ModelRegistry", DummyRegistry)
        monkeypatch.setattr(
            "src.detection.supervised_detector.SupervisedDetector",
            DummySupervisedDetector,
        )
        monkeypatch.setattr(
            "src.detection.vae_detector.UnsupervisedDetector",
            DummyUnsupervisedDetector,
        )
        monkeypatch.setattr("src.context.CompanyContext.is_anonymous", property(lambda self: False))
        monkeypatch.setattr("src.pipeline.load_document_labels", lambda source_path: None)

        AuditPipeline(
            settings=AuditSettings(enable_ml_detection=True),
            skip_db=True,
        ).redetect(small_gl_df, detection_scope="phase2_only")

        assert load_calls == [("unsupervised", None)]

    def test_phase1_default_excludes_timeseries_detector(self, monkeypatch, small_gl_df):
        class DummyTimeseriesDetector:
            def __init__(self, settings=None):
                self.settings = settings

            def detect(self, df):
                scores = pd.Series([0.0, 0.7, 0.0, 0.9][: len(df)], index=df.index, name="TS01")
                return DetectionResult(
                    track_name="timeseries",
                    flagged_indices=list(scores[scores > 0].index),
                    scores=scores,
                    rule_flags=[RuleFlag("TS01", "TS01", 4, int((scores > 0).sum()), len(df))],
                    details=pd.DataFrame({"TS01": scores}, index=df.index),
                    metadata={"elapsed": 0.02, "sub_detector_keys": ["transaction_burst"]},
                    warnings=[],
                )

        monkeypatch.setattr(
            "src.detection.timeseries_detector.TimeseriesDetector",
            DummyTimeseriesDetector,
        )

        result = AuditPipeline(
            settings=AuditSettings(enable_timeseries_detection=True),
            skip_db=True,
        ).run_from_dataframe(small_gl_df)

        track_names = {r.track_name for r in result.results}
        assert "timeseries" not in track_names

    def test_phase1_core_scope_excludes_ml_even_when_enabled(self, monkeypatch, small_gl_df):
        def fail_ml(self, df):
            raise AssertionError("phase1_core must not invoke ML detectors")

        monkeypatch.setattr(AuditPipeline, "_try_ml_detection", fail_ml)

        result = AuditPipeline(
            settings=AuditSettings(enable_ml_detection=True),
            skip_db=True,
        ).redetect(small_gl_df, detection_scope="phase1_core")

        track_names = {r.track_name for r in result.results}
        assert {"layer_a", "layer_b", "layer_c", "benford"}.issubset(track_names)
        assert not any(name.startswith("ml_") for name in track_names)


class TestRunCsv:
    def test_run_csv(self, tmp_path, small_gl_df):
        csv_path = tmp_path / "test.csv"
        small_gl_df["gl_account"] = ["11010000", "21010000", "11010000", "21010000"]
        small_gl_df.to_csv(csv_path, index=False)

        result = AuditPipeline(skip_db=True).run(csv_path)
        assert isinstance(result, PipelineResult)
        assert len(result.data) > 0

    def test_unsupported_extension(self, tmp_path):
        bad_file = tmp_path / "data.json"
        bad_file.write_text("{}")
        with pytest.raises(ValueError, match="지지원하지 않는|지원하지 않는"):
            AuditPipeline(skip_db=True).run(bad_file)


class TestValidation:
    def test_blocks_invalid_df(self):
        bad_df = pd.DataFrame({"x": [1, 2, 3]})
        with pytest.raises(ValueError, match="L1"):
            AuditPipeline(skip_db=True).run_from_dataframe(bad_df)

    def test_warnings_collected(self, small_gl_df):
        result = AuditPipeline(skip_db=True).run_from_dataframe(small_gl_df)
        assert isinstance(result.warnings, list)
