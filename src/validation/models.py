"""Validation 공용 데이터 모델 — L1/L2/L3 검증 결과 구조체.

Why: schema_validator → accounting_validator → statistical_validator → report_generator 간 데이터 계약.
JSON 직렬화 가능하도록 numpy 타입 대신 Python 네이티브만 사용.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd


@dataclass
class SchemaResult:
    """L1 구조 검증 결과 — schema_validator.validate_schema()가 반환.

    is_valid=False이면 파이프라인 중단 (필수 컬럼 누락/타입 불일치).
    is_valid=True + warnings이면 계속 진행 + 경고 누적.
    """

    is_valid: bool
    errors: list[dict] = field(default_factory=list)
    # [{column: str, check: str, failure_count: int}]
    warnings: list[dict] = field(default_factory=list)
    # [{column: str, issue: str, detail: str}]
    column_stats: dict[str, dict] = field(default_factory=dict)
    # {col_name: {dtype: str, null_rate: float, unique_count: int, total_count: int}}


@dataclass
class AccountingResult:
    """L2 회계 검증 결과 — accounting_validator.validate_accounting()가 반환."""

    balance_check: bool = True
    balance_diff: float = 0.0
    unbalanced_docs: list[str] = field(default_factory=list)
    date_continuity: bool = True
    missing_dates: list[str] = field(default_factory=list)
    duplicate_entries: int = 0


@dataclass
class ValidationReport:
    """L1+L2 종합 리포트 — report_generator.generate_report()가 반환.

    validation_score: 규칙 준수 품질 (0~100). EDA quality_score(현황 품질)와 구분.
    is_pipeline_ready: L1 치명적 에러 0건이면 True → detection 진행 가능.
    """

    total_rows: int
    total_documents: int
    valid_rows: int
    valid_documents: int
    schema_errors: list[dict] = field(default_factory=list)
    schema_warnings: list[dict] = field(default_factory=list)
    accounting_issues: list[dict] = field(default_factory=list)
    # [{check_type: str, severity: str, message: str, detail: dict | None}]
    statistical_flags: list[dict] = field(default_factory=list)
    # Phase 2: [{month: str, volatility: float, flag: str}]
    validation_score: float = 100.0
    is_pipeline_ready: bool = True
    generated_at: str = ""
    source_file: str | None = None
    date_range: tuple[str, str] | None = None


# ── L3 통계 검증 결과 (Phase 2) ──────────────────────────────


@dataclass
class BenfordResult:
    """Benford's Law 분석 결과. L4-02 detection 입력.

    판정 기준: MAD(주) + Chi-square(주) + KS(보조).
    Nigrini(2012) MAD 판정 기준: close≤0.006, acceptable≤0.012,
    marginally≤0.015, nonconforming>0.015.
    """

    sample_size: int
    observed: dict[int, float]       # {1: 0.301, ..., 9: 0.046}
    expected: dict[int, float]       # Benford 이론값
    mad: float | None                # Mean Absolute Deviation
    mad_conformity: str              # "close"|"acceptable"|"marginally"|"nonconforming"
    chi2_statistic: float | None
    chi2_p_value: float | None
    ks_statistic: float | None       # 보조 지표 (이산 분포 한계)
    ks_p_value: float | None         # 보조 지표
    is_conforming: bool              # 종합 판정 (MAD + Chi-square)
    confidence: str                  # "high"(≥500) | "moderate"(100~499) | "low"(<100)


@dataclass
class MonthlyVolatility:
    """월별 변동성 분석 결과."""

    monthly_totals: dict[str, float]            # {"2024-01": 총액, ...}
    mom_change_rates: dict[str, float]          # MoM % 변화율
    outlier_months: list[str]                   # |Z-score| > threshold 월
    seasonality_index: dict[int, float] | None  # 월(1~12)별 계절성 지수


@dataclass
class DistributionStats:
    """금액 분포 분석 결과."""

    shapiro_statistic: float | None
    shapiro_p_value: float | None
    is_normal: bool | None           # p > alpha → True
    skewness: float | None
    skewness_label: str | None       # "symmetric"|"right_skewed"|"left_skewed"
    kurtosis: float | None
    kurtosis_label: str | None       # "mesokurtic"|"leptokurtic"|"platykurtic"
    outlier_concentration: float | None  # 이상치 금액 합 / 전체 금액 합


@dataclass
class AccountStats:
    """계정별 통계 요약."""

    account_count: int
    cv_by_account: dict[str, float]     # 계정별 변동계수 (CV = std/mean)
    high_cv_accounts: list[str]         # CV > threshold 계정
    hhi: float                          # Herfindahl-Hirschman Index
    hhi_label: str                      # "concentrated"|"moderate"|"diversified"
    activity_frequency: dict[str, int]  # 계정별 거래 건수


@dataclass
class TemporalPatternStats:
    """시간 패턴 통계."""

    weekday_volume: dict[int, int]          # 0(Mon)~6(Sun) → 건수
    weekend_ratio: float
    period_end_concentration: float         # 월말 margin일 거래 비율
    yoy_change: dict[str, float] | None     # {"01": 0.05, ...} 월별 평균 YoY


@dataclass
class StatisticalResult:
    """L3 통계 검증 종합 결과. JSON-serializable."""

    total_rows: int
    analysis_timestamp: str                 # ISO 8601
    monthly_volatility: MonthlyVolatility
    distribution: DistributionStats
    benford: BenfordResult
    account_stats: AccountStats
    temporal_patterns: TemporalPatternStats
    warnings: list[str] = field(default_factory=list)
    flags: list[dict[str, str]] = field(default_factory=list)


# ── TB 교차검증 결과 (WU-13) ────────────────────────────────


@dataclass
class ReconciliationItem:
    """개별 대사 항목 결과 — 계정 유형별 GL vs TB 잔액 비교."""

    recon_type: str              # "AR" | "AP" | "FA" | "TOTAL"
    gl_balance: float            # GL 라인아이템 합계 (debit - credit)
    tb_balance: float            # TB closing_balance(당기 순증감액) 합계
    difference: float            # gl_balance - tb_balance (round(2) 적용 후)
    is_within_materiality: bool  # |difference| <= materiality
    account_filter: str          # 사용된 계정 접두사 (예: "11,12")


@dataclass
class ReconciliationResult:
    """TB 교차검증 종합 결과 — validate_tb_reconciliation()이 반환."""

    items: list[ReconciliationItem] = field(default_factory=list)
    total_differences: float = 0.0       # sum(|diff|)
    all_reconciled: bool = True          # 전체 대사 통과 여부
    trial_balance_rows: int = 0          # TB 행 수
    materiality_amount: float = 0.0
    warnings: list[str] = field(default_factory=list)
    # Why: pipeline._load_db()에서 DB 적재용으로 재사용 — 이중 생성 방지
    trial_balance_df: pd.DataFrame | None = field(default=None, repr=False)
