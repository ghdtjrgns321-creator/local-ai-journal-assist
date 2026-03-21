"""model_registry 테스트 — save/load/list."""

from __future__ import annotations

from pathlib import Path

import pytest
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

from src.preprocessing.model_registry import ModelRegistry


@pytest.fixture()
def registry(tmp_path):
    """임시 디렉토리 기반 레지스트리."""
    return ModelRegistry(registry_dir=tmp_path / "models")


@pytest.fixture()
def dummy_pipeline():
    """저장용 더미 Pipeline."""
    return Pipeline([
        ("scaler", StandardScaler()),
        ("clf", DecisionTreeClassifier(random_state=42)),
    ])


class TestModelRegistry:
    """ModelRegistry 검증."""

    def test_save_creates_file(self, registry, dummy_pipeline):
        """save 시 .pkl 파일이 생성되는지."""
        meta = registry.save(dummy_pipeline, "xgb", mean_f1=0.85)
        filepath = registry.registry_dir / meta.file_path
        assert filepath.exists()

    def test_save_returns_metadata(self, registry, dummy_pipeline):
        """save 반환값이 ModelMetadata인지."""
        meta = registry.save(dummy_pipeline, "xgb", mean_f1=0.85)
        assert meta.model_name == "xgb"
        assert meta.version == "v1"
        assert meta.mean_f1 == 0.85

    def test_version_increments(self, registry, dummy_pipeline):
        """같은 모델을 여러 번 저장하면 버전 증가."""
        m1 = registry.save(dummy_pipeline, "xgb", mean_f1=0.80)
        m2 = registry.save(dummy_pipeline, "xgb", mean_f1=0.85)
        assert m1.version == "v1"
        assert m2.version == "v2"

    def test_load_latest(self, registry, dummy_pipeline):
        """latest 로드 시 최신 버전 반환."""
        registry.save(dummy_pipeline, "xgb", mean_f1=0.80)
        registry.save(dummy_pipeline, "xgb", mean_f1=0.90)
        pipe, meta = registry.load("xgb", version="latest")
        assert meta.version == "v2"
        assert meta.mean_f1 == 0.90
        assert isinstance(pipe, Pipeline)

    def test_load_specific_version(self, registry, dummy_pipeline):
        """특정 버전 로드."""
        registry.save(dummy_pipeline, "xgb", mean_f1=0.80)
        registry.save(dummy_pipeline, "xgb", mean_f1=0.90)
        _, meta = registry.load("xgb", version="v1")
        assert meta.mean_f1 == 0.80

    def test_load_nonexistent_raises(self, registry):
        """없는 모델 로드 시 에러."""
        with pytest.raises(FileNotFoundError):
            registry.load("nonexistent")

    def test_list_models(self, registry, dummy_pipeline):
        """등록된 모델 목록 반환."""
        registry.save(dummy_pipeline, "xgb", mean_f1=0.85)
        registry.save(dummy_pipeline, "vae", mean_f1=0.75)
        models = registry.list_models()
        assert len(models) == 2
        names = {m.model_name for m in models}
        assert names == {"xgb", "vae"}

    def test_compare_versions(self, registry, dummy_pipeline):
        """버전별 성능 비교."""
        registry.save(dummy_pipeline, "xgb", mean_f1=0.80)
        registry.save(dummy_pipeline, "xgb", mean_f1=0.90)
        comparison = registry.compare_versions("xgb")
        assert len(comparison) == 2
        assert comparison[0]["version"] == "v1"
        assert comparison[1]["version"] == "v2"

    def test_registry_json_persisted(self, registry, dummy_pipeline):
        """registry.json이 디스크에 저장되는지."""
        registry.save(dummy_pipeline, "xgb", mean_f1=0.85)
        assert (registry.registry_dir / "registry.json").exists()

    def test_registry_survives_reload(self, registry, dummy_pipeline):
        """레지스트리 재생성 시 기존 데이터 유지."""
        registry.save(dummy_pipeline, "xgb", mean_f1=0.85)
        # 같은 디렉토리로 새 인스턴스 생성
        registry2 = ModelRegistry(registry_dir=registry.registry_dir)
        models = registry2.list_models()
        assert len(models) == 1
