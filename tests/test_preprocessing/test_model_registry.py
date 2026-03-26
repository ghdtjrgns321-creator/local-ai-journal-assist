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
