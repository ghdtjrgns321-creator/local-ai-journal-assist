"""프로젝트 전역 설정 모듈.

우선순위: 환경변수 > .env > 코드 기본값
YAML 설정(schema, keywords, risk_keywords)은 별도 로더로 읽는다.
"""

from __future__ import annotations

import functools
from pathlib import Path

import yaml
from pydantic import computed_field, field_validator
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
    balance_tolerance: float = 1.0         # A01: 차대변 불일치 허용 오차 (원)
    chart_of_accounts_path: str = "config/chart_of_accounts.csv"  # A03: CoA 파일 경로
    # 다단계 승인한도 — 한국 중견 제조업 전결규정 반영 (DataSynth v1.2.0)
    # Level 1~6: 자동승인(10M) → 담당자(100M) → 팀장(1B) → 본부장(5B) → CFO(10B) → 이사회(50B)
    approval_thresholds: list[int] = [
        10_000_000, 100_000_000, 1_000_000_000,
        5_000_000_000, 10_000_000_000, 50_000_000_000,
    ]
    @computed_field
    @property
    def approval_threshold(self) -> int:
        """레거시 호환용. approval_thresholds의 최고 한도 반환."""
        return max(self.approval_thresholds)

    near_threshold_ratio: float = 0.90  # 한도의 90% 이상이면 플래그
    round_unit: int = 1_000_000           # B04: 정수 단위 판정 기준 (100만원)
    zscore_threshold: float = 3.0         # C08: 이상치 기준 (detection에서 사용)
    midnight_start: int = 22  # C03: 심야 전기
    midnight_end: int = 6  # C03: 심야 전기
    period_end_margin_days: int = 5  # C01: 기말 판정 마진 (월말 전후 n일)
    fiscal_year_start: int = 1       # 회계연도 시작월 (1=1월, 4=4월~3월)
    custom_holidays: list[str] = []  # 회사 지정 휴일 ["2025-07-01"]

    # --- Detection Layer B 관련 ---
    duplicate_payment_window_days: int = 30   # B04: 중복 지급 판정 기간 (일)
    sod_process_threshold: int = 3            # B07: 직무분리 위반 프로세스 수 임계
    topside_threshold: int = 2               # B19: Top-side JE 가점 임계 (5점 만점, 수기 전제)

    # --- Detection Layer C 관련 ---
    backdated_threshold_days: int = 30          # C04: 소급 임계 일수
    account_pair_rare_percentile: float = 0.01  # C09: 희소 쌍 하위 백분위
    period_end_amount_quantile: float = 0.75    # C01: 기말 대규모 금액 분위수 (Q3)

    # --- Detection Layer C: C11 역분개 ---
    reversal_match_window_days: int = 1          # S1: 1:1 매칭 허용 일수
    reversal_rolling_window_days: int = 7        # S2: N:M 롤링 윈도우 (일)
    reversal_zero_threshold: float = 1000.0      # S2: 순액 0 수렴 허용 오차 (KRW)
    reversal_score_threshold: float = 0.3        # 종합 점수 플래그 임계값

    # --- Detection Layer C: C12 비정상 시간대 집중 분석 ---
    normal_hours_start: float = 8.5             # 정상 업무시간 시작 (08:30)
    normal_hours_end: float = 18.5              # 정상 업무시간 종료 (18:30)
    settlement_start_mmdd: str = "1220"         # 결산 집중기간 시작 (12월 20일)
    settlement_end_mmdd: str = "0115"           # 결산 집중기간 종료 (1월 15일)

    @field_validator("settlement_start_mmdd", "settlement_end_mmdd")
    @classmethod
    def _check_mmdd_format(cls, v: str) -> str:
        """MMDD 형식 검증 — 잘못된 값은 silent 오탐 유발."""
        if len(v) != 4 or not v.isdigit():
            raise ValueError(f"MMDD 형식이어야 합니다 (예: '1220'): {v!r}")
        m, d = int(v[:2]), int(v[2:])
        if not (1 <= m <= 12 and 1 <= d <= 31):
            raise ValueError(f"유효하지 않은 월/일: month={m}, day={d}")
        return v

    abnormal_sigma_threshold: float = 3.0       # 사용자별 이상치 판정 σ
    rapid_approval_minutes: int = 5             # 부실 검토 의심 임계 (분)
    min_abnormal_ratio: float = 0.1             # σ 이상치여도 절대 비율 10% 미만이면 미플래그
    min_midnight_entries: int = 3               # 소수 인원 폴백 시 최소 심야 건수
    min_user_entries: int = 10                  # C12: 사용자별 최소 전표 건수 (미달 시 분석 제외)
    auto_entry_sources: list[str] = [           # 자동 전기 소스 (급속 승인 검증 제외 대상)
        "batch", "interface", "system",
        "BATCH", "IF", "SYS",
    ]

    # --- Detection Layer D: 전기 대비 변동 ---
    variance_threshold: float = 0.5           # D01: 계정 집계 변동률 플래그 임계 (50%)
    monthly_pattern_threshold: float = 0.3    # D02: JSD 플래그 임계
    min_monthly_data_months: int = 3          # D02: 비교 수행 최소 월수

    # --- L3 통계 검증 (statistical_validator) ---
    monthly_volatility_zscore: float = 2.0      # 월별 변동률 이상 판정 Z-score
    shapiro_alpha: float = 0.05                  # 정규성 검정 유의수준
    benford_mad_threshold: float = 0.012         # MAD 이상 판정 (Nigrini "acceptable")
    benford_min_sample: int = 100                # Benford 최소 표본
    benford_chi2_alpha: float = 0.05             # Chi-square 유의수준
    hhi_concentrated_threshold: float = 0.25     # HHI 집중 판정
    cv_high_threshold: float = 1.0               # 계정 CV 고변동 판정

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
def get_cleaning_config() -> dict:
    """타입 캐스팅 전처리 규칙 로드. config/cleaning.yaml."""
    return _load_yaml("cleaning.yaml")


@functools.lru_cache
def get_audit_rules() -> dict:
    """감사 업무 룰(패턴/키워드) 로드. config/audit_rules.yaml."""
    return _load_yaml("audit_rules.yaml")
