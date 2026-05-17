"""L1 구조 검증 — Pandera 스키마 기반 DataFrame 구조·타입·제약조건 검증.

Why: type_caster가 보장한 dtype을 재확인하고, 값 범위(ge=0 등)와
필수 컬럼 존재 여부를 검증하여 detection 진입 전 데이터 품질 게이트를 세운다.
피처 컬럼(is_weekend 등 19개)은 검증 대상 외.
"""

from __future__ import annotations

import logging

import pandas as pd
import pandera.pandas as pa
from pandera.typing.pandas import Series

from config.settings import AuditSettings, get_schema, get_settings
from src.validation.models import SchemaResult

logger = logging.getLogger(__name__)

# ── Detector-forbidden 메타데이터 컬럼 (deny-list) ─────────────
# Why: DataSynth가 ledger CSV에 주입하는 시나리오/뮤테이션 메타데이터.
#      탐지기가 입력 피처로 사용하면 라벨 누설(label leakage)·합성 아티팩트
#      학습이 발생한다. L1 schema에는 미정의 + strict=False로 통과되므로,
#      validate_schema()가 발견 시 warning을 남기고 pipeline에서 strip한다.
#      회귀 가드: tests/modules/test_validation/test_schema_validator.py가
#      src/detection/*.py에 이 컬럼명 참조가 없는지 AST 레벨로 검사.
DETECTOR_FORBIDDEN_COLUMNS: frozenset[str] = frozenset(
    {
        "semantic_scenario_id",
        "mutation_type",
        "mutation_base_event_type",
        "mutation_mutated_field",
        "mutation_original_value",
        "mutation_mutated_value",
        "mutation_reason",
        "detection_surface_hints",
    }
)


def strip_detector_forbidden_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """detection 진입 전 deny-list 컬럼 제거.

    Why: validate_schema()가 warning을 내고 통과시킨 메타 컬럼을, detection
         파이프라인 진입 직전에 물리적으로 제거하여 신규 룰이 실수로 참조해도
         AttributeError로 즉시 실패하도록 한다.

    Returns:
        (cleaned_df, stripped_columns) — stripped_columns는 실제 제거된 컬럼 목록.
    """
    stripped = sorted(set(df.columns) & DETECTOR_FORBIDDEN_COLUMNS)
    if not stripped:
        return df, []
    return df.drop(columns=stripped), stripped


# ── schema.yaml에서 필수/전체 컬럼 목록 추출 ──────────────────


def _load_column_sets(schema: dict | None = None) -> tuple[frozenset[str], frozenset[str]]:
    """schema.yaml 기반 필수 컬럼·전체 컬럼 집합 반환.

    Why: @lru_cache 제거 — dict 파라미터 해시 불가.
         get_schema() 자체가 lru_cache이므로 YAML 재로드 없음.
         validate_schema()에서 1회 호출.
    """
    schema = schema or get_schema()
    columns = schema.get("columns", [])
    required = frozenset(c["name"] for c in columns if c.get("required", False))
    all_cols = frozenset(c["name"] for c in columns)
    return required, all_cols


# ── Pandera DataFrameModel ────────────────────────────────────


class GeneralLedgerSchema(pa.DataFrameModel):
    """표준 GL DataFrame의 L1 구조 스키마.

    필수 10개: nullable=False, dtype 강제
    선택 41개: Optional → df에 없어도 에러 아님, nullable=True
    Config.strict=False → 피처 컬럼 등 추가 컬럼 허용
    """

    # ── 필수 컬럼 ──
    document_id: Series[str] = pa.Field(nullable=False)
    company_code: Series[str] = pa.Field(nullable=False)
    fiscal_year: Series[pd.Int64Dtype] = pa.Field(ge=2000, le=2099, nullable=False)
    fiscal_period: Series[pd.Int64Dtype] = pa.Field(ge=1, le=12, nullable=False)
    posting_date: Series[pa.DateTime] = pa.Field(nullable=False)
    # Why: schema.yaml type: date이나, type_caster가 datetime64[ns]로 통일 변환
    document_date: Series[pa.DateTime] = pa.Field(nullable=False)
    # Why: DataSynth L1-02(MissingField) 라벨 데이터가 의도적으로 NULL 포함.
    #      NULL 행은 L1-02 탐지 룰에서 플래그하므로 파이프라인 통과 허용.
    gl_account: Series[str] = pa.Field(nullable=True)
    debit_amount: Series[float] = pa.Field(ge=0, nullable=False)
    credit_amount: Series[float] = pa.Field(ge=0, nullable=False)
    document_type: Series[str] = pa.Field(nullable=True)

    # ── 선택 컬럼 — Header (Optional → df에 없어도 통과) ──
    currency: Series[str] | None = pa.Field(nullable=True)
    exchange_rate: Series[float] | None = pa.Field(nullable=True)
    reference: Series[str] | None = pa.Field(nullable=True)
    header_text: Series[str] | None = pa.Field(nullable=True)
    created_by: Series[str] | None = pa.Field(nullable=True)
    user_persona: Series[str] | None = pa.Field(nullable=True)
    source: Series[str] | None = pa.Field(nullable=True)
    business_process: Series[str] | None = pa.Field(nullable=True)
    # Why: pattern_features.py가 intercompany 컨텍스트 도출에 사용. v2 ledger 메타.
    counterparty_type: Series[str] | None = pa.Field(nullable=True)
    ledger: Series[str] | None = pa.Field(nullable=True)
    approved_by: Series[str] | None = pa.Field(nullable=True)
    # Why: schema.yaml type: date → type_caster가 datetime64[ns]로 변환
    approval_date: Series[pa.DateTime] | None = pa.Field(nullable=True)

    # ── 선택 컬럼 — 레이블 (DataSynth 전용, 검증/평가 전용 — detection 입력 금지) ──
    # Why: PHASE1 detector에 라벨이 흘러가면 truth leakage. sidecar로만 주입되며 ledger 데이터 아님.
    is_fraud: Series[bool] | None = pa.Field(nullable=True)
    fraud_type: Series[str] | None = pa.Field(nullable=True)
    is_anomaly: Series[bool] | None = pa.Field(nullable=True)
    anomaly_type: Series[str] | None = pa.Field(nullable=True)
    sod_violation: Series[bool] | None = pa.Field(nullable=True)
    sod_conflict_type: Series[str] | None = pa.Field(nullable=True)

    # ── 선택 컬럼 ── Stage 2 확장
    has_attachment: Series[bool] | None = pa.Field(nullable=True)
    supporting_doc_type: Series[str] | None = pa.Field(nullable=True)
    delivery_date: Series[pa.DateTime] | None = pa.Field(nullable=True)
    invoice_amount: Series[float] | None = pa.Field(nullable=True)
    supply_amount: Series[float] | None = pa.Field(nullable=True)
    ip_address: Series[str] | None = pa.Field(nullable=True)
    document_number: Series[pd.Int64Dtype] | None = pa.Field(nullable=True)

    # ── 선택 컬럼 — Line ──
    line_number: Series[pd.Int64Dtype] | None = pa.Field(nullable=True)
    local_amount: Series[float] | None = pa.Field(nullable=True)
    cost_center: Series[str] | None = pa.Field(nullable=True)
    profit_center: Series[str] | None = pa.Field(nullable=True)
    line_text: Series[str] | None = pa.Field(nullable=True)
    tax_code: Series[str] | None = pa.Field(nullable=True)
    tax_amount: Series[float] | None = pa.Field(nullable=True)
    trading_partner: Series[str] | None = pa.Field(nullable=True)
    auxiliary_account_number: Series[str] | None = pa.Field(nullable=True)
    auxiliary_account_label: Series[str] | None = pa.Field(nullable=True)

    # ── 선택 컬럼 — Clearing / suspense lifecycle (v2 ledger 메타) ──
    # Why: anomaly_rules_simple.py(L3-09 aging) / fraud_rules_access.py가 직접 참조.
    #      라벨이 아닌 ledger 상태값이므로 L1 optional 허용.
    is_suspense_account: Series[bool] | None = pa.Field(nullable=True)
    amount_open: Series[float] | None = pa.Field(nullable=True)
    is_cleared: Series[bool] | None = pa.Field(nullable=True)
    settlement_status: Series[str] | None = pa.Field(nullable=True)

    lettrage: Series[str] | None = pa.Field(nullable=True)
    # Why: schema.yaml type: date → type_caster가 datetime64[ns]로 변환
    lettrage_date: Series[pa.DateTime] | None = pa.Field(nullable=True)

    class Config:
        strict = False  # 피처 컬럼 등 스키마 외 컬럼 허용
        coerce = False  # type_caster가 이미 처리 → 재변환 안 함


# ── 내부 헬퍼 ─────────────────────────────────────────────────


def _collect_column_stats(df: pd.DataFrame, schema_columns: set[str]) -> dict[str, dict]:
    """schema.yaml에 정의된 컬럼만 대상으로 기초 통계 수집."""
    stats: dict[str, dict] = {}
    for col in sorted(schema_columns & set(df.columns)):
        series = df[col]
        stats[col] = {
            "dtype": str(series.dtype),
            "null_rate": round(float(series.isna().mean()), 4),
            "unique_count": int(series.nunique()),
            "total_count": len(series),
        }
    return stats


def _classify_failures(
    exc: pa.errors.SchemaErrors,
    required_columns: set[str],
) -> tuple[list[dict], list[dict]]:
    """Pandera SchemaErrors → 치명적(errors) / 경고(warnings) 분류.

    치명적: 필수 컬럼의 dtype 불일치, nullable 위반
    경고: 값 범위 위반(ge=0), 권장 컬럼 이슈
    """
    # Why: 같은 (column, check) 조합의 failure_count를 합산하기 위해 dict로 집계
    error_agg: dict[tuple[str, str], int] = {}
    warning_agg: dict[tuple[str, str], int] = {}

    for _, row in exc.failure_cases.iterrows():
        col = str(row.get("column", ""))
        check = str(row.get("check", ""))
        key = (col, check)

        # Why: 필수 컬럼의 구조적 위반만 치명적으로 분류
        # Pandera dtype check 이름은 "dtype('datetime64[ns]')" 형태이므로 startswith 사용
        is_dtype_check = check.startswith("dtype") or check.startswith("coerce")
        is_structural = is_dtype_check or check in (
            "not_nullable",
            "column_in_dataframe",
        )
        is_critical = col in required_columns and is_structural

        if is_critical:
            error_agg[key] = error_agg.get(key, 0) + 1
        else:
            warning_agg[key] = warning_agg.get(key, 0) + 1

    errors = [
        {"column": col, "check": chk, "failure_count": cnt} for (col, chk), cnt in error_agg.items()
    ]
    warnings = [
        {"column": col, "issue": chk, "detail": f"{cnt}건 위반"}
        for (col, chk), cnt in warning_agg.items()
    ]
    return errors, warnings


# ── 공개 API ──────────────────────────────────────────────────


def validate_schema(
    df: pd.DataFrame,
    schema: dict | None = None,
    settings: AuditSettings | None = None,
) -> SchemaResult:
    """L1 구조 검증 — Pandera lazy=True로 모든 에러 수집.

    Args:
        df: type_caster 완료 + feature 추가된 DataFrame
        schema: 스키마 dict (None이면 글로벌 폴백)
        settings: 감사 설정 (None이면 글로벌 폴백)

    Returns:
        SchemaResult: is_valid=False이면 파이프라인 중단
    """
    settings = settings or get_settings()
    high_null_threshold = settings.casting_null_demote_threshold
    required_columns, all_schema_columns = _load_column_sets(schema)
    errors: list[dict] = []
    warnings: list[dict] = []

    # 1) 필수 컬럼 존재 확인 — Pandera 전 조기 차단
    missing = required_columns - set(df.columns)
    if missing:
        for col in sorted(missing):
            errors.append(
                {
                    "column": col,
                    "check": "column_in_dataframe",
                    "failure_count": 1,
                }
            )
        logger.warning("필수 컬럼 누락: %s", sorted(missing))

    # 2) column_stats 수집
    column_stats = _collect_column_stats(df, all_schema_columns)

    # 3) 권장 컬럼 고null 경고 수집
    optional_columns = all_schema_columns - required_columns
    for col in sorted(optional_columns & set(df.columns)):
        null_rate = column_stats.get(col, {}).get("null_rate", 0.0)
        if null_rate >= high_null_threshold:
            warnings.append(
                {
                    "column": col,
                    "issue": "high_null_rate",
                    "detail": f"결측률 {null_rate:.1%} — 오매핑 의심",
                }
            )

    # 3.5) Detector-forbidden 메타데이터 경고 (DataSynth 메타 → detection 차단 신호)
    # Why: strict=False로 통과되는 잠재적 라벨 누설 컬럼을 노출. pipeline은
    #      strip_detector_forbidden_columns()로 detection 진입 전 제거.
    forbidden_present = sorted(set(df.columns) & DETECTOR_FORBIDDEN_COLUMNS)
    for col in forbidden_present:
        warnings.append(
            {
                "column": col,
                "issue": "detector_forbidden_column",
                "detail": "DataSynth 메타데이터 — detection 진입 전 strip 필요",
            }
        )

    # 4) Pandera lazy=True 검증 (필수 컬럼이 모두 존재할 때만 실행)
    if not missing:
        try:
            GeneralLedgerSchema.validate(df, lazy=True)
        except pa.errors.SchemaErrors as exc:
            pandera_errors, pandera_warnings = _classify_failures(exc, required_columns)
            errors.extend(pandera_errors)
            warnings.extend(pandera_warnings)
        except pa.errors.SchemaError as exc:
            # Why: lazy=True에서도 단일 에러가 SchemaError로 올 수 있음
            errors.append(
                {
                    "column": str(getattr(exc, "schema", "")),
                    "check": str(getattr(exc, "check", "unknown")),
                    "failure_count": 1,
                }
            )

    is_valid = len(errors) == 0
    if is_valid:
        logger.info("L1 구조 검증 통과 — %d행, %d 경고", len(df), len(warnings))
    else:
        logger.error("L1 구조 검증 실패 — %d건 치명적 오류", len(errors))

    return SchemaResult(
        is_valid=is_valid,
        errors=errors,
        warnings=warnings,
        column_stats=column_stats,
    )
