"""PHASE2 전용 입력 프레임 — 허용 목록 원본 칸 + PHASE2 전용 파생.

Why: 2026-07-29. 그전까지 PHASE2 입력은 **막지 않은 것이 전부 들어오는** deny 방식이었다.
     PHASE1 이 룰을 위해 칸을 하나 만들면 그 순간 PHASE2 입력이 하나 늘었다 — 아무도
     결정하지 않았는데. 그렇게 들어온 PHASE1 파생이 39칸이었고, 그중 한도·승인 축
     18칸이 원재료 3개에서 나온 것이었다(`near_threshold_amount` 와
     `document_approval_amount` 는 코드상 같은 변수였다).

     룰에게는 합리적인 칸들이다 — L2-01 은 "한도의 몇 %인가"가 발화 조건이니
     `ratio_to_limit` 칸이 필요하다. **VAE 에게는 아니다.** 금액과 한도 두 칸을 주면
     관계는 스스로 학습하고, 파생을 더 주면 정보가 아니라 그 축의 무게만 는다.

     그래서 allow 방식으로 뒤집는다. PHASE2 입력은 여기 적힌 것만이다.

파생은 **원본으로 표현할 수 없는 것**에만 만든다. 세 종류뿐이다.

    날짜        datetime 은 크기 비교가 무의미하다(12월과 1월이 가장 멀어진다).
                주기 성분과 간격으로 바꾼다.
    마스터 조인 승인자 한도·권한처럼 원장에 없는 정보.
    금액 구조   끝자리 0 개수·첫자리는 로그 변환에서 소실된다.

판정(`is_near_threshold`)·비율(`gap_ratio`)·중복 표현(`amount_magnitude`)은 만들지 않는다.

3-surface 비병합(FINAL-REPORT 9장 §9.4)이 점수만이 아니라 **입력에서도** 성립하게 하는 것이
이 모듈의 목적이다. PHASE1 파생은 한 칸도 쓰지 않는다.
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

_DERIVED_PREFIX = "p2_"

# PHASE2 가 원본에서 그대로 받는 칸. 여기 없으면 들어오지 않는다.
PHASE2_SOURCE_COLUMNS: tuple[str, ...] = (
    # 계정·분류
    "gl_account",
    "semantic_account_subtype",
    "debit_account_subtype",
    "credit_account_subtype",
    "document_type",
    "business_process",
    "event_type",
    "counterparty_type",
    "tax_treatment",
    "tax_code",
    "profit_center",
    "line_text_family",
    "supporting_doc_type",
    "source",
    "user_persona",
    "company_code",
    "currency",
    "ledger",
    # 금액 (2026-07-29 차단 해제 — §9.3.1)
    "debit_amount",
    "credit_amount",
    "local_amount",
    "invoice_amount",
    "supply_amount",
    "tax_amount",
    "exchange_rate",
    # 상대·조직 (고카디널리티 → 빈도 인코딩)
    "created_by",
    "approved_by",
    "cost_center",
    "trading_partner",
    "auxiliary_account_number",
    "auxiliary_account_label",
    "line_text",
    "header_text",
    # 상태 플래그
    "has_attachment",
    "is_intercompany",
    "is_suspense_account",
    "is_cleared",
    # 기간
    "fiscal_year",
    "fiscal_period",
)

# 파생이 참조하는 원본 칸. 파생 재료일 뿐 그대로 넘기지는 않는다.
_DERIVATION_INPUTS: tuple[str, ...] = (
    "posting_date",
    "document_date",
    "approval_date",
    "delivery_date",
    "approved_by",
    "gl_account",
    "local_amount",
    "debit_amount",
    "credit_amount",
)


# PHASE2 가 어떤 형태로든 참조하는 원본 칸 전부 — 허용 목록 + 파생 재료.
# Why: 호출자가 "이 칸들만 남기고 버려도 되나"를 판정할 수 있어야 한다. 파이프라인이
#      내는 프레임을 통째로 들고 다니면 PHASE1 룰용 파생까지 함께 끌려온다.
PHASE2_INPUT_COLUMNS: frozenset[str] = frozenset(PHASE2_SOURCE_COLUMNS) | frozenset(
    _DERIVATION_INPUTS
)


def build_phase2_input_frame(
    df: pd.DataFrame,
    *,
    settings=None,
    employee_master_path=None,
) -> pd.DataFrame:
    """PHASE2 입력 프레임 조립 — 허용 원본 + 전용 파생."""
    present = [column for column in PHASE2_SOURCE_COLUMNS if column in df.columns]
    missing = [column for column in PHASE2_SOURCE_COLUMNS if column not in df.columns]
    if missing:
        logger.info("PHASE2 허용 목록 중 원장에 없는 칸 %d개: %s", len(missing), missing)

    base = df.loc[:, present].copy()
    derived = build_phase2_derived_features(
        df,
        settings=settings,
        employee_master_path=employee_master_path,
    )
    frame = pd.concat([base, derived], axis=1)
    frame.attrs["phase2_source_columns"] = present
    frame.attrs["phase2_derived_columns"] = list(derived.columns)
    return frame


def build_phase2_derived_features(
    df: pd.DataFrame,
    *,
    settings=None,
    employee_master_path=None,
) -> pd.DataFrame:
    """원본으로 표현할 수 없는 것만 파생한다."""
    derived = pd.DataFrame(index=df.index)
    _add_calendar_features(df, derived, settings=settings)
    _add_interval_features(df, derived)
    _add_master_features(df, derived, employee_master_path=employee_master_path)
    _add_amount_structure_features(df, derived)
    return derived


def _add_calendar_features(df: pd.DataFrame, out: pd.DataFrame, *, settings=None) -> None:
    """전기 시점의 주기 성분. datetime 원본은 크기 비교가 무의미하므로 범주로 낸다.

    요일·시각을 범주로 내는 이유: 23시와 0시는 수치상 가장 멀지만 실제로는 붙어 있다.
    원-핫이면 그 왜곡이 없고, 범주 컬럼 하나의 총분산이 1 이하라 무게도 과하지 않다.
    """
    if "posting_date" not in df.columns:
        return
    posting = pd.to_datetime(df["posting_date"], errors="coerce")
    out[f"{_DERIVED_PREFIX}posting_dow"] = posting.dt.dayofweek.astype("string")
    out[f"{_DERIVED_PREFIX}posting_hour"] = posting.dt.hour.astype("string")
    out[f"{_DERIVED_PREFIX}posting_day_of_month"] = posting.dt.day.astype("string")
    out[f"{_DERIVED_PREFIX}is_holiday"] = _holiday_flag(posting, settings=settings)


def _holiday_flag(posting: pd.Series, *, settings=None) -> pd.Series:
    """법정공휴일 판정. 원장에 없는 외부 달력 정보라 파생이 불가피하다."""
    from src.feature.time_features import _build_holiday_set

    valid = posting.dropna()
    if valid.empty:
        return pd.Series(False, index=posting.index)
    custom = list(getattr(settings, "custom_holidays", []) or [])
    holiday_set = _build_holiday_set(set(valid.dt.year.unique()), custom)
    if not holiday_set:
        return pd.Series(False, index=posting.index)
    return posting.dt.date.isin(holiday_set).fillna(False)


def _add_interval_features(df: pd.DataFrame, out: pd.DataFrame) -> None:
    """날짜 사이의 간격. 날짜 자체가 아니라 간격이 감사 신호다.

    결측 처리는 여기서 하지 않는다. `approval_date` 는 승인이 없으면 비고(실측 r9 72%)
    `delivery_date` 는 인도가 없으면 비는데(57%), 간격을 0 으로 채우면 "당일 승인"과
    "승인 없음"이 같아진다. 그 처리는 매트릭스 빌더의 일반 규칙이 맡는다 —
    결측이 있고 값이 갈리는 칸에 `__missing` 표식을 세운다(`phase2_matrix`).
    여기서 표식을 손으로 만들면 같은 정보가 2칸이 된다.
    """
    posting = _to_datetime(df, "posting_date")
    document = _to_datetime(df, "document_date")
    approval = _to_datetime(df, "approval_date")
    delivery = _to_datetime(df, "delivery_date")

    if posting is not None and document is not None:
        out[f"{_DERIVED_PREFIX}days_posting_minus_document"] = _day_diff(posting, document)
    if approval is not None and posting is not None:
        out[f"{_DERIVED_PREFIX}days_approval_minus_posting"] = _day_diff(approval, posting)
    if delivery is not None and document is not None:
        out[f"{_DERIVED_PREFIX}days_delivery_minus_document"] = _day_diff(delivery, document)


def _to_datetime(df: pd.DataFrame, column: str) -> pd.Series | None:
    if column not in df.columns:
        return None
    return pd.to_datetime(df[column], errors="coerce")


def _day_diff(later: pd.Series, earlier: pd.Series) -> pd.Series:
    """일수 차이. 부호를 유지한다 — 소급(음수)과 지연(양수)은 다른 신호다."""
    return (later.dt.normalize() - earlier.dt.normalize()).dt.days.astype("Int64")


def _add_master_features(df: pd.DataFrame, out: pd.DataFrame, *, employee_master_path=None) -> None:
    """직원 마스터 조인 결과. 원장 안에 없는 정보라 파생이 불가피하다."""
    from src.feature.amount_features import _compute_approver_info

    info = _compute_approver_info(df, employee_master_path)
    if info is None:
        return
    if "approval_limit" in info.columns:
        out[f"{_DERIVED_PREFIX}approver_limit_amount"] = info["approval_limit"]
    if "approver_in_master" in info.columns:
        out[f"{_DERIVED_PREFIX}approver_in_master"] = info["approver_in_master"]


def _add_amount_structure_features(df: pd.DataFrame, out: pd.DataFrame) -> None:
    """금액의 자릿수 구조. 로그 변환을 거치면 소실되므로 따로 낸다.

    끝자리 0 개수는 라운드넘버(5,000,000)를, 첫자리는 벤포드 분포를 본다.
    둘 다 금액 크기와는 다른 축이다 — 같은 1,000만원이라도 10,000,000 과
    9,873,412 는 자릿수 구조가 완전히 다르다.
    """
    amount = _base_amount(df)
    if amount is None:
        return
    magnitude = amount.abs().round().astype("Int64")
    out[f"{_DERIVED_PREFIX}amount_trailing_zeros"] = _trailing_zeros(magnitude)
    out[f"{_DERIVED_PREFIX}amount_first_digit"] = _first_digit(magnitude)


def _base_amount(df: pd.DataFrame) -> pd.Series | None:
    if "local_amount" in df.columns:
        return pd.to_numeric(df["local_amount"], errors="coerce")
    if "debit_amount" in df.columns and "credit_amount" in df.columns:
        debit = pd.to_numeric(df["debit_amount"], errors="coerce").fillna(0.0)
        credit = pd.to_numeric(df["credit_amount"], errors="coerce").fillna(0.0)
        return debit - credit
    return None


def _trailing_zeros(magnitude: pd.Series) -> pd.Series:
    text = magnitude.astype("string")
    stripped = text.str.rstrip("0")
    counts = text.str.len() - stripped.str.len()
    # Why: 0 원은 "끝자리 0 이 여러 개"가 아니라 금액이 없는 것이다.
    counts = counts.where(magnitude.ne(0), 0)
    return counts.astype("Int64")


def _first_digit(magnitude: pd.Series) -> pd.Series:
    text = magnitude.astype("string").str.lstrip("0")
    digit = text.str.slice(0, 1)
    return digit.where(digit.isin([str(n) for n in range(1, 10)]), pd.NA)


def phase2_feature_provenance() -> dict[str, list[str]]:
    """무엇을 어디서 받았는지 — 리포트·감사용."""
    return {
        "source_columns": list(PHASE2_SOURCE_COLUMNS),
        "derivation_inputs": list(_DERIVATION_INPUTS),
        "derived_prefix": _DERIVED_PREFIX,
    }


__all__ = [
    "PHASE2_SOURCE_COLUMNS",
    "build_phase2_derived_features",
    "build_phase2_input_frame",
    "phase2_feature_provenance",
]
