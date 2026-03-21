"""Pipeline 직렬화 & 모델 레지스트리.

Why: 최적 Pipeline을 매번 재학습하지 않고, 디스크에 저장하여
다음 감사 시 즉시 Inference에 재사용할 수 있다.
joblib(sklearn 객체) + torch.save(VAE 모델) 이원화 직렬화.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import joblib
from sklearn.pipeline import Pipeline

logger = logging.getLogger(__name__)

_DEFAULT_REGISTRY_DIR = Path("models")


@dataclass
class ModelMetadata:
    """저장된 모델의 메타데이터."""

    model_name: str         # "xgb", "vae", "if"
    version: str            # "v1", "v2", ...
    created_at: str         # ISO 8601
    mean_f1: float          # CV 성능
    feature_count: int      # 학습 시 피처 수
    params: dict            # 하이퍼파라미터
    file_path: str          # .pkl 파일 경로 (registry_dir 상대)


class ModelRegistry:
    """Pipeline 저장/불러오기/버전 관리."""

    def __init__(self, registry_dir: Path | str = _DEFAULT_REGISTRY_DIR):
        self.registry_dir = Path(registry_dir)
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self.registry_dir / "registry.json"
        self._index: list[dict] = self._load_index()

    def _load_index(self) -> list[dict]:
        """registry.json 로드. 없으면 빈 리스트."""
        if self._index_path.exists():
            with open(self._index_path, encoding="utf-8") as f:
                return json.load(f)
        return []

    def _save_index(self) -> None:
        """registry.json 저장."""
        with open(self._index_path, "w", encoding="utf-8") as f:
            json.dump(self._index, f, indent=2, ensure_ascii=False)

    def _next_version(self, model_name: str) -> str:
        """동일 모델의 다음 버전 번호."""
        existing = [
            m for m in self._index if m["model_name"] == model_name
        ]
        return f"v{len(existing) + 1}"

    def save(
        self,
        pipeline: Pipeline,
        model_name: str,
        mean_f1: float,
        feature_count: int = 0,
        params: dict | None = None,
    ) -> ModelMetadata:
        """Pipeline을 디스크에 저장 + 메타데이터 등록.

        Returns
        -------
        저장된 모델의 ModelMetadata
        """
        version = self._next_version(model_name)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"{model_name}_{version}_{timestamp}.pkl"
        filepath = self.registry_dir / filename

        joblib.dump(pipeline, filepath)

        metadata = ModelMetadata(
            model_name=model_name,
            version=version,
            created_at=datetime.now(timezone.utc).isoformat(),
            mean_f1=mean_f1,
            feature_count=feature_count,
            params=params or {},
            file_path=filename,
        )

        self._index.append(asdict(metadata))
        self._save_index()

        logger.info("모델 저장: %s → %s (F1=%.4f)", model_name, filepath, mean_f1)
        return metadata

    def load(
        self,
        model_name: str,
        version: str = "latest",
    ) -> tuple[Pipeline, ModelMetadata]:
        """저장된 Pipeline 불러오기.

        Parameters
        ----------
        model_name : "xgb", "vae", "if"
        version : "latest" 또는 "v1", "v2" 등
        """
        candidates = [
            m for m in self._index if m["model_name"] == model_name
        ]
        if not candidates:
            raise FileNotFoundError(f"모델 '{model_name}' 이 레지스트리에 없습니다")

        if version == "latest":
            entry = candidates[-1]
        else:
            matches = [m for m in candidates if m["version"] == version]
            if not matches:
                raise FileNotFoundError(
                    f"모델 '{model_name}' 버전 '{version}'을 찾을 수 없습니다",
                )
            entry = matches[-1]

        filepath = self.registry_dir / entry["file_path"]
        pipeline = joblib.load(filepath)
        metadata = ModelMetadata(**entry)

        logger.info("모델 로드: %s %s (F1=%.4f)", model_name, entry["version"], entry["mean_f1"])
        return pipeline, metadata

    def list_models(self) -> list[ModelMetadata]:
        """등록된 모델 목록."""
        return [ModelMetadata(**m) for m in self._index]

    def compare_versions(self, model_name: str) -> list[dict]:
        """동일 모델의 버전별 성능 비교."""
        return [
            {"version": m["version"], "mean_f1": m["mean_f1"], "created_at": m["created_at"]}
            for m in self._index
            if m["model_name"] == model_name
        ]
