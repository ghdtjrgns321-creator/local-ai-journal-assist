"""프로젝트 전역 설정 모듈.

우선순위: 환경변수 > .env > 코드 기본값
YAML 설정(schema, keywords, risk_keywords)은 별도 로더로 읽는다.
"""

from __future__ import annotations

import functools
from pathlib import Path

import yaml
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 프로젝트 루트 = config/ 의 부모
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"


class AuditSettings(BaseSettings):
    """프로젝트 전역 설정. 환경변수 > .env > 코드 기본값 순 우선."""

    # --- 파일 관련 (deprecated: file_validator는 file_categories.py 사용) ---
    # 카테고리별 크기 제한은 src/ingest/file_categories.py에 정의
    # 아래 필드는 하위 호환용으로 유지. 신규 코드에서 참조하지 말 것
    max_file_size_mb: int = 100
    allowed_extensions: list[str] = [
        ".xlsx", ".xls", ".xlsb",
        ".csv", ".tsv", ".txt", ".dat",
        ".parquet",
    ]

    # --- 헤더 탐지 관련 ---
    min_expected_headers: int = 4        # 키워드 스코어 정규화 분모
    max_header_scan_rows: int = 20       # 상위 N행만 탐색
    min_header_confidence: float = 0.3   # 이하면 탐지 실패 → UI 개입

    @field_validator("min_expected_headers")
    @classmethod
    def _check_min_expected_headers(cls, v: int) -> int:
        """0 이하면 스코어 공식이 무의미 → 조기 차단."""
        if v <= 0:
            raise ValueError("min_expected_headers는 1 이상이어야 합니다.")
        return v

    # --- 매핑 관련 (⚠️ 예시값 — 실제 ERP 헤더 매칭 정확도 보며 튜닝) ---
    fuzzy_threshold: int = 80            # 이상이면 확정 매핑
    fuzzy_low_threshold: int = 40        # 이상이면 추천(suggestions), 미만이면 unmapped

    # --- 타입 캐스팅 관련 ---
    casting_null_warn_threshold: float = 0.1   # 캐스팅 후 결측률 경고 임계 (10%)
    casting_null_demote_threshold: float = 0.9  # 90% 초과 → 오매핑 의심
    casting_date_dayfirst: bool = False         # True면 DD/MM/YYYY 해석

    # --- 감사 룰 관련 (⚠️ 예시값 — 실제 감사 기준에 맞춰 조정) ---
    approval_threshold: float = 50_000_000  # B02/B03: 승인한도 직하/초과
    near_threshold_ratio: float = 0.90  # 한도의 90% 이상이면 플래그
    round_unit: int = 1_000_000           # B04: 정수 단위 판정 기준 (100만원)
    zscore_threshold: float = 3.0         # C08: 이상치 기준 (detection에서 사용)
    midnight_start: int = 22  # C03: 심야 전기
    midnight_end: int = 6  # C03: 심야 전기
    period_end_margin_days: int = 5  # C01: 기말 판정 마진 (월말 전후 n일)
    fiscal_year_start: int = 1       # 회계연도 시작월 (1=1월, 4=4월~3월)
    custom_holidays: list[str] = []  # 회사 지정 휴일 ["2025-07-01"]

    # --- 텍스트 피처 관련 ---
    min_description_length: int = 3  # C06: poor/normal 경계 글자수

    # --- 매핑 프로파일 관련 ---
    profile_dir: str = "data/profiles"    # 프로파일 저장 디렉토리

    # --- ML Pipeline (Phase 2) ---
    vae_latent_dim: int = 32
    vae_epochs: int = 50
    vae_batch_size: int = 256
    if_contamination: float = 0.01          # IsolationForest
    cv_folds: int = 5
    cv_scoring: str = "f1_macro"

    # --- DB ---
    duckdb_path: str = "data/audit.duckdb"

    # --- LLM (Phase 3) ---
    ollama_model: str = "qwen3:8b"
    ollama_base_url: str = "http://localhost:11434"
    ollama_keep_alive: str = "5m"          # 모델 자동 언로드 시간
    ollama_temperature: float = 0.1        # 감사 분석은 정확성 우선 → 낮은 temperature

    # --- 전처리 판정 기준 (Heuristics) ---
    heuristic_skewness_threshold: float = 2.0      # |skewness| 초과 시 고왜도 판정 (imputer 분기)
    heuristic_log_skewness_threshold: float = 3.0  # |skewness| 초과 시 log 변환 권장 (outlier 분기)
    heuristic_outlier_rate_threshold: float = 0.10  # outlier_rate 초과 시 다수 이상치
    heuristic_high_cardinality_threshold: int = 50  # cardinality 초과 시 고카디널리티
    heuristic_imbalance_threshold: float = 0.05     # 레이블 비율 미만 시 불균형 판정
    heuristic_missing_rate_threshold: float = 0.10  # missing_rate 초과 시 고결측 판정

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="AUDIT_",
        extra="ignore",
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


@functools.lru_cache
def get_audit_rules() -> dict:
    """감사 업무 룰(패턴/키워드) 로드. config/audit_rules.yaml."""
    return _load_yaml("audit_rules.yaml")
