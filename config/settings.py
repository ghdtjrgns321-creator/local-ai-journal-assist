"""프로젝트 전역 설정 모듈.

우선순위: 환경변수 > .env > 코드 기본값
YAML 설정(schema, keywords, risk_keywords)은 별도 로더로 읽는다.
"""

from __future__ import annotations

import functools
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

# 프로젝트 루트 = config/ 의 부모
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"


class AuditSettings(BaseSettings):
    """프로젝트 전역 설정. 환경변수 > .env > 코드 기본값 순 우선."""

    # --- 파일 관련 (⚠️ 예시값 — 실제 전표 파일에 맞춰 조정) ---
    max_file_size_mb: int = 100
    allowed_extensions: list[str] = [".xlsx", ".xls", ".csv"]

    # --- 매핑 관련 (⚠️ 예시값 — 실제 ERP 헤더 매칭 정확도 보며 튜닝) ---
    fuzzy_threshold: int = 80

    # --- 감사 룰 관련 (⚠️ 예시값 — 실제 감사 기준에 맞춰 조정) ---
    approval_threshold: float = 50_000_000  # R001: 승인 한도
    near_threshold_ratio: float = 0.98  # 한도의 98% 이상이면 플래그
    midnight_start: int = 22  # R003: 심야 시작
    midnight_end: int = 6  # R003: 심야 종료
    period_end_days: int = 5  # R004: 기말 n일

    # --- DB ---
    duckdb_path: str = "data/audit.duckdb"

    # --- LLM (Phase 3) ---
    ollama_model: str = "qwen3:8b"
    ollama_base_url: str = "http://localhost:11434"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="AUDIT_",
    )


# --- YAML 로더 ---


def _load_yaml(filename: str) -> dict:
    """config/ 디렉토리의 YAML 파일을 읽어 dict로 반환."""
    path = CONFIG_DIR / filename
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


@functools.lru_cache
def get_settings() -> AuditSettings:
    """싱글톤 — 앱 전체에서 하나의 설정 인스턴스만 사용."""
    return AuditSettings()


@functools.lru_cache
def get_schema() -> dict:
    """표준 컬럼 스키마 로드."""
    return _load_yaml("schema.yaml")


@functools.lru_cache
def get_keywords() -> dict:
    """ERP별 헤더 키워드 사전 로드."""
    return _load_yaml("keywords.yaml")


@functools.lru_cache
def get_risk_keywords() -> dict:
    """위험 적요 키워드 사전 로드."""
    return _load_yaml("risk_keywords.yaml")
