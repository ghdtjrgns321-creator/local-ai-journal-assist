"""다기간 추정치 데이터 로더 — TrendBreak(WU-16)의 입력 생성.

Why: Layer D의 PriorSummary는 1개 전기만 로드.
     TrendBreak는 ISA 540 소급 검토를 위해 최소 3개년 데이터가 필요.
     각 연도 engagement DB를 순차 ATTACH하여 추정치 계정 잔액을 수집한다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from src.company.models import EngagementProfile, EngagementStatus
from src.db.queries import attached_engagement

if TYPE_CHECKING:
    import duckdb

    from src.company.repository import CompanyRepository

logger = logging.getLogger(__name__)


# ── 데이터 모델 ─────────────────────────────────────────────


@dataclass(frozen=True)
class EstimationRecord:
    """단일 연도 단일 추정치 계정의 설정/상각 분리 레코드.

    Why: ISA 540 소급 검토에서 "경영진 추정치(credit)"와 "실제 사용(debit)"을
         분리해야 상각으로 인한 잔액 감소를 편의(bias)로 오탐하지 않는다.
    """

    fiscal_year: int
    gl_account: str
    account_name: str  # audit_rules.yaml name 참조
    ending_balance: float  # 부호 정규화 완료된 기말 순잔액
    total_debit: float  # 원시 차변 합계 (= 실제 사용/상각액)
    total_credit: float  # 원시 대변 합계 (= 당기 설정액 = 경영진 추정치)
    row_count: int  # 해당 계정 전표 건수


@dataclass(frozen=True)
class MultiYearEstimates:
    """다기간 추정치 데이터 번들 — TrendBreakDetector 입력."""

    # {gl_account: [EstimationRecord, ...]} 연도순 정렬
    records_by_account: dict[str, list[EstimationRecord]]
    fiscal_years: list[int]  # 포함 연도 (오름차순)

    # Why: TB01용. estimation_error[t] = total_credit[t-1] - total_debit[t]
    #      전기 설정액 - 당기 실제 사용액. 음수 지속 = 이익 편향.
    estimation_errors: dict[str, list[float]]

    # Why: TB02용. total_credit[t] 시계열 — 상각(debit)으로 오염되지 않은
    #      순수 경영진 추정 의사결정 추세.
    provision_amounts: dict[str, list[float]]

    current_fiscal_year: int
    account_sign_convention: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


# ── 전기 engagement 다기간 탐색 ─────────────────────────────


# Why: find_prior_engagement(prior_data_loader.py)의 상태 우선순위를 재사용.
#      ARCHIVED는 신뢰도 낮아 제외.
_TRUSTED_STATUSES = (
    EngagementStatus.COMPLETED,
    EngagementStatus.IN_PROGRESS,
    EngagementStatus.DRAFT,
)


def find_multi_year_engagements(
    repo: CompanyRepository,
    company_id: str,
    current_fiscal_year: int,
    max_years: int = 5,
    min_years: int = 3,
) -> list[EngagementProfile] | None:
    """다기간 engagement 탐색.

    Why: TrendBreak는 최소 3개년(= 2개 estimation error) 데이터가 필요.
         당기는 detect() 시점의 df에서 직접 산출하므로 과거만 검색한다.

    Returns:
        연도순 정렬된 EngagementProfile 리스트, 또는 min_years 미달 시 None.
    """
    all_engagements = repo.list_engagements(company_id)
    target_range = range(current_fiscal_year - max_years, current_fiscal_year)

    # Why: 연도별 최고 신뢰도 engagement 선택 (COMPLETED > IN_PROGRESS > DRAFT)
    by_year: dict[int, EngagementProfile] = {}
    for fy in target_range:
        candidates = [e for e in all_engagements if e.fiscal_year == fy]
        for status in _TRUSTED_STATUSES:
            match = next((e for e in candidates if e.status == status), None)
            if match:
                by_year[fy] = match
                break

    # Why: 당기 포함 총 연도 수가 min_years 미달이면 None
    #      과거 N개 + 당기 1개 >= min_years
    if len(by_year) + 1 < min_years:
        logger.info(
            "다기간 engagement 부족: %d개년 (최소 %d개년 필요)",
            len(by_year) + 1,
            min_years,
        )
        return None

    # Why: 연도순 정렬하여 시계열 순서 보장
    return [by_year[fy] for fy in sorted(by_year)]


# ── 다기간 추정치 로딩 ──────────────────────────────────────


def _compute_net_balance(
    total_debit: float,
    total_credit: float,
    sign: str,
) -> float:
    """추정치 계정의 순잔액 산출. sign convention에 따라 정규화.

    Why: 대변 정상(충당금/부채)은 credit - debit이 양수일 때 정상 방향.
         차변 정상 계정은 향후 확장 대비.
    """
    if sign == "credit_normal":
        return total_credit - total_debit
    return total_debit - total_credit


def _build_account_name_map(estimation_config: list[dict]) -> dict[str, str]:
    """audit_rules.yaml estimation_accounts에서 {account: name} 매핑 생성."""
    return {item["account"]: item.get("name", item["account"]) for item in estimation_config}


def load_multi_year_estimates(
    conn: duckdb.DuckDBPyConnection,
    repo: CompanyRepository,
    company_id: str,
    engagements: list[EngagementProfile],
    current_df: pd.DataFrame,
    current_fiscal_year: int,
    estimation_config: list[dict],
    account_sign_convention: dict[str, str],
) -> MultiYearEstimates | None:
    """다기간 추정치 데이터 로딩 + estimation error 산출.

    Why: 각 연도 DB를 ATTACH READ_ONLY로 접근하여 추정치 계정의
         차변/대변 합계를 분리 수집. 설정(credit) vs 상각(debit) 분리로
         FP를 방지한다.
    """
    account_names = _build_account_name_map(estimation_config)
    estimation_accounts = list(account_names.keys())
    if not estimation_accounts:
        return None

    warnings: list[str] = []

    # Why: 연도별 {gl_account: EstimationRecord} 수집
    year_data: dict[int, dict[str, EstimationRecord]] = {}

    # ── 과거 연도: DB ATTACH ──
    for eng in engagements:
        db_path = repo.db_path(company_id, eng.engagement_id)
        abs_path = Path(db_path).resolve()

        if not abs_path.exists():
            warnings.append(f"FY{eng.fiscal_year} DB 미존재: {abs_path}")
            continue

        try:
            records = _load_single_year(
                conn,
                abs_path,
                eng.fiscal_year,
                estimation_accounts,
                account_names,
                account_sign_convention,
            )
            if records:
                year_data[eng.fiscal_year] = records
        except Exception as exc:
            warnings.append(f"FY{eng.fiscal_year} 로드 실패: {exc}")
            logger.warning("FY%d 추정치 로드 실패", eng.fiscal_year, exc_info=True)

    # ── 당기: current_df에서 직접 산출 ──
    current_records = _load_current_year(
        current_df,
        current_fiscal_year,
        estimation_accounts,
        account_names,
        account_sign_convention,
    )
    if current_records:
        year_data[current_fiscal_year] = current_records

    if len(year_data) < 2:
        logger.info("유효 연도 %d개 — estimation error 산출 불가", len(year_data))
        return None

    fiscal_years = sorted(year_data)

    # ── 계정별 레코드 조립 ──
    all_accounts = set()
    for records in year_data.values():
        all_accounts.update(records.keys())

    records_by_account: dict[str, list[EstimationRecord]] = {}
    for acct in sorted(all_accounts):
        acct_records = []
        for fy in fiscal_years:
            rec = year_data[fy].get(acct)
            if rec is not None:
                acct_records.append(rec)
        if acct_records:
            records_by_account[acct] = acct_records

    # ── estimation error + provision amounts 산출 ──
    estimation_errors, provision_amounts = _compute_errors_and_provisions(
        records_by_account,
        fiscal_years,
        account_sign_convention,
    )

    return MultiYearEstimates(
        records_by_account=records_by_account,
        fiscal_years=fiscal_years,
        estimation_errors=estimation_errors,
        provision_amounts=provision_amounts,
        current_fiscal_year=current_fiscal_year,
        account_sign_convention=account_sign_convention,
        warnings=warnings,
    )


def _load_single_year(
    conn: duckdb.DuckDBPyConnection,
    db_path: Path,
    fiscal_year: int,
    estimation_accounts: list[str],
    account_names: dict[str, str],
    sign_convention: dict[str, str],
) -> dict[str, EstimationRecord]:
    """단일 과거 연도 DB에서 추정치 계정 잔액 로드.

    Why: DuckDB ATTACH READ_ONLY로 전기 DB에 접근. SQL injection 위험 없음
         (estimation_accounts는 audit_rules.yaml 내부 설정값).
    """
    # Why: alias에 연도를 포함하여 동시 ATTACH 충돌 방지
    alias_hint = f"tb_y{fiscal_year}"

    with attached_engagement(conn, db_path, alias_hint) as alias:
        total_rows = conn.execute(f"SELECT COUNT(*) FROM {alias}.general_ledger").fetchone()[0]

        if total_rows == 0:
            return {}

        # Why: estimation_accounts는 YAML 설정값이므로 f-string 안전.
        #      DuckDB IN 절은 파라미터 바인딩 미지원.
        quoted = ", ".join(f"'{a}'" for a in estimation_accounts)
        df = conn.execute(f"""
            SELECT gl_account,
                   SUM(debit_amount)  AS total_debit,
                   SUM(credit_amount) AS total_credit,
                   COUNT(*)           AS row_count
            FROM {alias}.general_ledger
            WHERE gl_account IN ({quoted})
            GROUP BY gl_account
        """).fetchdf()

    return _df_to_records(df, fiscal_year, account_names, sign_convention)


def _load_current_year(
    df: pd.DataFrame,
    fiscal_year: int,
    estimation_accounts: list[str],
    account_names: dict[str, str],
    sign_convention: dict[str, str],
) -> dict[str, EstimationRecord]:
    """당기 DataFrame에서 추정치 계정 잔액 산출."""
    if "gl_account" not in df.columns:
        return {}

    mask = df["gl_account"].isin(estimation_accounts)
    if not mask.any():
        return {}

    debit_col = "debit_amount" if "debit_amount" in df.columns else None
    credit_col = "credit_amount" if "credit_amount" in df.columns else None
    if debit_col is None or credit_col is None:
        return {}

    agg = (
        df[mask]
        .groupby("gl_account")
        .agg(
            total_debit=(debit_col, "sum"),
            total_credit=(credit_col, "sum"),
            row_count=("gl_account", "count"),
        )
        .reset_index()
    )

    return _df_to_records(agg, fiscal_year, account_names, sign_convention)


def _df_to_records(
    df: pd.DataFrame,
    fiscal_year: int,
    account_names: dict[str, str],
    sign_convention: dict[str, str],
) -> dict[str, EstimationRecord]:
    """집계 DataFrame → EstimationRecord dict 변환."""
    records: dict[str, EstimationRecord] = {}
    for _, row in df.iterrows():
        acct = str(row["gl_account"])
        td = float(row["total_debit"])
        tc = float(row["total_credit"])
        sign = sign_convention.get(acct, "credit_normal")

        records[acct] = EstimationRecord(
            fiscal_year=fiscal_year,
            gl_account=acct,
            account_name=account_names.get(acct, acct),
            ending_balance=_compute_net_balance(td, tc, sign),
            total_debit=td,
            total_credit=tc,
            row_count=int(row["row_count"]),
        )
    return records


def _compute_errors_and_provisions(
    records_by_account: dict[str, list[EstimationRecord]],
    fiscal_years: list[int],
    sign_convention: dict[str, str],
) -> tuple[dict[str, list[float]], dict[str, list[float]]]:
    """estimation error 시계열 + provision amounts 시계열 산출.

    Why: estimation_error[t] = 전기 설정액 - 당기 상각액
         - credit_normal: total_credit[t-1] - total_debit[t]
         - debit_normal:  total_debit[t-1] - total_credit[t]
         provision_amounts = [설정액 per year] (TB02용)
    """
    estimation_errors: dict[str, list[float]] = {}
    provision_amounts: dict[str, list[float]] = {}

    for acct, records in records_by_account.items():
        sign = sign_convention.get(acct, "credit_normal")

        # Why: provision = 경영진 추정 의사결정 금액
        if sign == "credit_normal":
            provisions = [r.total_credit for r in records]
        else:
            provisions = [r.total_debit for r in records]
        provision_amounts[acct] = provisions

        # Why: error는 연속 2개 레코드에서 산출 (t-1, t 쌍)
        errors: list[float] = []
        for i in range(1, len(records)):
            prev = records[i - 1]
            curr = records[i]

            if sign == "credit_normal":
                # Why: 전기 설정액(credit) - 당기 상각액(debit)
                error = prev.total_credit - curr.total_debit
            else:
                error = prev.total_debit - curr.total_credit

            errors.append(round(error, 2))

        estimation_errors[acct] = errors

    return estimation_errors, provision_amounts
