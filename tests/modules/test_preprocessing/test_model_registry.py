"""Pipeline 직렬화 + 버전 관리 테스트."""

from __future__ import annotations

import pytest
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from src.preprocessing.model_registry import ModelMetadata, ModelRegistry


@pytest.fixture()
def registry(tmp_path):
    """임시 디렉토리 기반 ModelRegistry."""
    return ModelRegistry(tmp_path / "models")


@pytest.fixture()
def dummy_pipeline() -> Pipeline:
    """저장용 간단한 Pipeline."""
    return Pipeline([
        ("imputer", SimpleImputer(strategy="mean")),
        ("clf", LogisticRegression(max_iter=200)),
    ])


class TestModelRegistry:
    """Pipeline 저장·로드·버전 관리 검증."""

    def test_save_creates_file(self, registry, dummy_pipeline):
        meta = registry.save(dummy_pipeline, "test_model", mean_f1=0.85)
        from pathlib import Path
        assert Path(meta.file_path).exists()

    def test_save_returns_metadata(self, registry, dummy_pipeline):
        meta = registry.save(dummy_pipeline, "test_model", mean_f1=0.85)
        assert isinstance(meta, ModelMetadata)
        assert meta.model_name == "test_model"
        assert meta.mean_f1 == 0.85

    def test_version_increments(self, registry, dummy_pipeline):
        m1 = registry.save(dummy_pipeline, "test_model", mean_f1=0.80)
        m2 = registry.save(dummy_pipeline, "test_model", mean_f1=0.85)
        assert m1.version == 1
        assert m2.version == 2

    def test_load_latest(self, registry, dummy_pipeline):
        registry.save(dummy_pipeline, "test_model", mean_f1=0.80)
        registry.save(dummy_pipeline, "test_model", mean_f1=0.85)
        loaded = registry.load("test_model")
        assert isinstance(loaded, Pipeline)

    def test_load_specific_version(self, registry, dummy_pipeline):
        registry.save(dummy_pipeline, "test_model", mean_f1=0.80)
        registry.save(dummy_pipeline, "test_model", mean_f1=0.85)
        loaded = registry.load("test_model", version=1)
        assert isinstance(loaded, Pipeline)

    def test_load_nonexistent_raises(self, registry):
        with pytest.raises(FileNotFoundError):
            registry.load("nonexistent_model")

    def test_list_models(self, registry, dummy_pipeline):
        registry.save(dummy_pipeline, "model_a", mean_f1=0.80)
        registry.save(dummy_pipeline, "model_b", mean_f1=0.90)
        models = registry.list_models()
        assert len(models) == 2
        assert all(isinstance(m, ModelMetadata) for m in models)

    def test_compare_versions(self, registry, dummy_pipeline):
        registry.save(dummy_pipeline, "test_model", mean_f1=0.80)
        registry.save(dummy_pipeline, "test_model", mean_f1=0.85)
        comparison = registry.compare_versions("test_model")
        assert len(comparison) == 2
        assert all("version" in c and "mean_f1" in c for c in comparison)

    def test_registry_json_persisted(self, registry, dummy_pipeline):
        registry.save(dummy_pipeline, "test_model", mean_f1=0.85)
        assert (registry._dir / "registry.json").exists()

    def test_registry_survives_reload(self, registry, dummy_pipeline, tmp_path):
        registry.save(dummy_pipeline, "test_model", mean_f1=0.85)
        # 같은 디렉토리로 새 인스턴스 생성
        new_registry = ModelRegistry(tmp_path / "models")
        models = new_registry.list_models()
        assert len(models) == 1
        assert models[0].model_name == "test_model"


class TestDriftMetadata:
    """드리프트 감지용 메타데이터 보존 검증."""

    def test_save_with_training_stats(self, registry, dummy_pipeline):
        # Why: 신규 필드(training_data_stats, schema_version 등)가 정상 저장되는지
        meta = registry.save(
            dummy_pipeline,
            "drift_model",
            mean_f1=0.9,
            training_data_stats={"n_samples": 100, "columns": {"x": {"mean": 0.5}}},
            feature_schema_version=42,
            class_imbalance_ratio=0.1,
            n_train_samples=100,
            evaluation_policy="temporal_holdout",
            evaluation_confidence="benchmark",
            train_years=(2022, 2023),
            test_years=(2024,),
            label_source="ground_truth",
            positive_count=24,
            positive_rate=0.24,
            gate_status="eligible",
            feature_quality_profile={"normalized_persona": True},
        )
        assert meta.training_data_stats["n_samples"] == 100
        assert meta.feature_schema_version == 42
        assert meta.class_imbalance_ratio == 0.1
        assert meta.n_train_samples == 100
        assert meta.evaluation_policy == "temporal_holdout"
        assert meta.evaluation_confidence == "benchmark"
        assert meta.train_years == (2022, 2023)
        assert meta.test_years == (2024,)
        assert meta.label_source == "ground_truth"
        assert meta.positive_count == 24
        assert meta.positive_rate == 0.24
        assert meta.gate_status == "eligible"
        assert meta.feature_quality_profile["normalized_persona"] is True

    def test_save_without_drift_fields_default(self, registry, dummy_pipeline):
        # Why: 하위호환 — drift 필드 없이 저장해도 default 값으로 채워짐
        meta = registry.save(dummy_pipeline, "old_caller", mean_f1=0.8)
        assert meta.training_data_stats == {}
        assert meta.feature_schema_version == 1
        assert meta.class_imbalance_ratio == 0.0
        assert meta.n_train_samples == 0
        assert meta.evaluation_policy == "unknown"
        assert meta.evaluation_confidence == "unknown"
        assert meta.label_source == "unknown"
        assert meta.positive_count == 0
        assert meta.gate_status == "unknown"

    def test_legacy_registry_json_loadable(self, tmp_path):
        # Why: 구버전 registry.json (신규 필드 없음) 로드 시 default로 보강
        import json
        legacy_dir = tmp_path / "legacy"
        legacy_dir.mkdir()
        legacy_index = [{
            "model_name": "legacy",
            "version": 1,
            "file_path": str(legacy_dir / "legacy_v1.pkl"),
            "mean_f1": 0.7,
            "feature_count": 5,
            "params": {},
            "saved_at": "2025-01-01T00:00:00+00:00",
        }]
        (legacy_dir / "registry.json").write_text(
            json.dumps(legacy_index), encoding="utf-8",
        )
        registry = ModelRegistry(legacy_dir)
        models = registry.list_models()
        assert len(models) == 1
        # 신규 필드는 default 값이 채워져야 함
        assert models[0].training_data_stats == {}
        assert models[0].feature_schema_version == 1
        assert models[0].n_train_samples == 0
        assert models[0].evaluation_policy == "unknown"
        assert models[0].evaluation_confidence == "unknown"
        assert models[0].label_source == "unknown"
        assert models[0].gate_status == "unknown"

    def test_drift_fields_persisted_to_json(self, registry, dummy_pipeline, tmp_path):
        registry.save(
            dummy_pipeline,
            "persisted_model",
            mean_f1=0.95,
            training_data_stats={"n_samples": 500, "columns": {}},
            feature_schema_version=99,
            n_train_samples=500,
        )
        new_registry = ModelRegistry(tmp_path / "models")
        models = new_registry.list_models()
        assert len(models) == 1
        assert models[0].training_data_stats["n_samples"] == 500
        assert models[0].feature_schema_version == 99
        assert models[0].n_train_samples == 500
        assert models[0].evaluation_policy == "unknown"
        assert models[0].label_source == "unknown"
