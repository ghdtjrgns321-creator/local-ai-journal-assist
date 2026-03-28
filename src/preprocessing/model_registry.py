"""Pipeline 직렬화 + 버전 관리.

Why: 학습된 Pipeline을 디스크에 저장하고 버전별 성능을 비교할 수 있어야
모델 업데이트 이력을 추적할 수 있다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import joblib

from config.settings import PROJECT_ROOT

logger = logging.getLogger(__name__)

# Why: CWD 의존 상대경로 대신 프로젝트 루트 기준 고정 경로 사용
_DEFAULT_MODELS_DIR = PROJECT_ROOT / "models"


@dataclass
class ModelMetadata:
    """저장된 모델의 메타데이터."""

    model_name: str
    version: int
    file_path: str
    mean_f1: float
    feature_count: int = 0
    params: dict = field(default_factory=dict)
    saved_at: str = ""


class ModelRegistry:
    """Pipeline 직렬화 + 버전 관리 (joblib + registry.json)."""

    def __init__(self, registry_dir: Path = _DEFAULT_MODELS_DIR):
        self._dir = Path(registry_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._dir / "registry.json"
        self._index: list[dict] = self._load_index()

    def _load_index(self) -> list[dict]:
        if self._index_path.exists():
            with open(self._index_path, encoding="utf-8") as f:
                return json.load(f)
        return []

    def _save_index(self) -> None:
        with open(self._index_path, "w", encoding="utf-8") as f:
            json.dump(self._index, f, indent=2, ensure_ascii=False)

    def _next_version(self, model_name: str) -> int:
        versions = [
            e["version"] for e in self._index if e["model_name"] == model_name
        ]
        return max(versions, default=0) + 1

    def save(
        self,
        pipeline,
        model_name: str,
        mean_f1: float,
        feature_count: int = 0,
        params: dict | None = None,
    ) -> ModelMetadata:
        """Pipeline을 .pkl로 저장하고 레지스트리에 등록."""
        version = self._next_version(model_name)
        filename = f"{model_name}_v{version}.pkl"
        file_path = self._dir / filename

        joblib.dump(pipeline, file_path)

        meta = ModelMetadata(
            model_name=model_name,
            version=version,
            file_path=str(file_path),
            mean_f1=mean_f1,
            feature_count=feature_count,
            params=params or {},
            saved_at=datetime.now(timezone.utc).isoformat(),
        )
        self._index.append(asdict(meta))
        self._save_index()
        logger.info("모델 저장: %s v%d (F1=%.4f)", model_name, version, mean_f1)
        return meta

    def load(self, model_name: str, version: int | None = None):
        """모델 로드. version=None이면 최신 버전."""
        entries = [e for e in self._index if e["model_name"] == model_name]
        if not entries:
            raise FileNotFoundError(f"모델 '{model_name}'을 찾을 수 없습니다.")

        if version is not None:
            entry = next((e for e in entries if e["version"] == version), None)
            if entry is None:
                raise FileNotFoundError(f"모델 '{model_name}' v{version}을 찾을 수 없습니다.")
        else:
            entry = max(entries, key=lambda e: e["version"])

        path = Path(entry["file_path"])
        # Why: registry.json 조작으로 경로 순회 시 임의 파일 로드 방지
        try:
            path.resolve().relative_to(self._dir.resolve())
        except ValueError:
            raise ValueError(
                f"경로 순회 차단: '{path}'는 레지스트리 디렉토리 외부입니다."
            )
        if not path.exists():
            raise FileNotFoundError(
                f"모델 파일 없음: '{path}'. 레지스트리 인덱스가 손상되었을 수 있습니다."
            )
        return joblib.load(path)

    def list_models(self) -> list[ModelMetadata]:
        """등록된 전체 모델 메타데이터 목록."""
        return [ModelMetadata(**e) for e in self._index]

    def compare_versions(self, model_name: str) -> list[dict]:
        """동일 모델의 버전별 성능 비교."""
        return [
            {"version": e["version"], "mean_f1": e["mean_f1"]}
            for e in self._index
            if e["model_name"] == model_name
        ]
