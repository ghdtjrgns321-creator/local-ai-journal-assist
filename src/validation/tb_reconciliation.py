"""TB 교차검증 — GL 계정별 집계 무결성 + 계정유형별 잔액 대사.

Why: L2 검증(전표 단위 대차일치)과 별개로, 계정(GL) 수준에서
GL 라인아이템 합계와 Trial Balance 집계가 일치하는지 교차 확인한다.
감사기준서 330호 (수행된 감사절차의 평가) 근거.

주의: 현재 GL 원본에 이월 기초전표(Opening Entry)가 없으므로
      TB의 opening_balance는 항상 0이고, closing_balance는
      엄밀히 '당기 순증감액(Net Change)'이다 (기말 잔액 아님).
      GL-TB 무결성 검증에는 문제없으나 UI 라벨링 시 구분 필요.
"""

from __future__ import annotations

import logging

import pandas as pd

from src.validation.models import ReconciliationItem, ReconciliationResult

logger = logging.getLogger(__name__)


# ── 서브함수 ──────────────────────────────────────────────────


def build_trial_balance(df: pd.DataFrame) -> pd.DataFrame:
    """GL 전표 데이터에서 Trial Balance 생성.

    계정(gl_account) + 기간(fiscal_period)별로 집계.
    opening_balance는 Phase 1에서 0.0 (이월 기초전표 없음).
    closing_balance = opening_balance + debit_total - credit_total
                    = 당기 순증감액 (Net Change).

    Returns:
        TB DataFrame. 필수 컬럼 부재 시 빈 DataFrame.
    """
    required = {"gl_account", "debit_amount", "credit_amount"}
    if not required.issubset(df.columns):
        logger.warning("TB 생성 불가 — 필수 컬럼 부재: %s", required - set(df.columns))
        return pd.DataFrame()

    if df.empty:
        return pd.DataFrame()

    # Why: fiscal_period 없으면 전체를 단일 기간(0)으로 처리
    has_period = "fiscal_period" in df.columns
    group_cols = ["gl_account", "fiscal_period"] if has_period else ["gl_account"]

    grouped = df.groupby(group_cols, as_index=False).agg(
        debit_total=("debit_amount", "sum"),
        credit_total=("credit_amount", "sum"),
    )

    if not has_period:
        grouped["fiscal_period"] = 0

    grouped["opening_balance"] = 0.0
    # Why: round(2)로 부동소수점 집계 오차 방어
    grouped["closing_balance"] = (
        grouped["opening_balance"]
        + grouped["debit_total"]
        - grouped["credit_total"]
    ).round(2)
    grouped["debit_total"] = grouped["debit_total"].round(2)
    grouped["credit_total"] = grouped["credit_total"].round(2)

    # fiscal_year, account_name 보강 (있으면)
    # Why: fiscal_year를 None 대신 0으로 폴백 — DuckDB PK에 NULL 방지
    if "fiscal_year" in df.columns:
        fy_map = df.groupby("gl_account")["fiscal_year"].first()
        grouped["fiscal_year"] = grouped["gl_account"].map(fy_map).fillna(0).astype(int)
    else:
        grouped["fiscal_year"] = 0

    if "auxiliary_account_label" in df.columns:
        label_map = df.groupby("gl_account")["auxiliary_account_label"].first()
        grouped["account_name"] = grouped["gl_account"].map(label_map)
    else:
        grouped["account_name"] = None

    return grouped


def reconcile_by_prefix(
    df: pd.DataFrame,
    tb_df: pd.DataFrame,
    account_prefixes: list[str],
    recon_type: str,
    materiality: float,
) -> ReconciliationItem:
    """특정 계정 접두사 범위의 GL 잔액과 TB 잔액을 대사.

    Args:
        df: GL 원본 DataFrame
        tb_df: build_trial_balance()로 생성된 TB DataFrame
        account_prefixes: GL 계정 접두사 목록 (예: ["11", "12"])
        recon_type: 대사 유형 ("AR", "AP", "FA", "TOTAL")
        materiality: 중요성 금액 (허용 차이)
    """
    gl_acct = df["gl_account"].astype(str)
    tb_acct = tb_df["gl_account"].astype(str)

    if recon_type == "TOTAL":
        # 전체 GL vs 전체 TB (접두사 무관)
        mask_gl = pd.Series(True, index=df.index)
        mask_tb = pd.Series(True, index=tb_df.index)
    else:
        # Why: startswith 대신 str[:n] 슬라이싱으로 다양한 접두사 길이 지원
        mask_gl = pd.Series(False, index=df.index)
        mask_tb = pd.Series(False, index=tb_df.index)
        for prefix in account_prefixes:
            n = len(prefix)
            mask_gl = mask_gl | (gl_acct.str[:n] == prefix)
            mask_tb = mask_tb | (tb_acct.str[:n] == prefix)

    # Why: round(2)로 부동소수점 집계 오차 방어 (수십만 건 float64 sum 후 뺄셈)
    gl_balance = round(
        df.loc[mask_gl, "debit_amount"].fillna(0).sum()
        - df.loc[mask_gl, "credit_amount"].fillna(0).sum(),
        2,
    )
    tb_balance = round(tb_df.loc[mask_tb, "closing_balance"].sum(), 2)
    diff = round(gl_balance - tb_balance, 2)

    # Why: numpy bool → Python bool 변환 (JSON 직렬화 + is True 비교 방어)
    return ReconciliationItem(
        recon_type=recon_type,
        gl_balance=float(gl_balance),
        tb_balance=float(tb_balance),
        difference=float(diff),
        is_within_materiality=bool(abs(diff) <= materiality),
        account_filter=",".join(account_prefixes) if recon_type != "TOTAL" else "*",
    )


# ── 오케스트레이터 ────────────────────────────────────────────


def validate_tb_reconciliation(
    df: pd.DataFrame,
    materiality: float = 0.0,
    account_prefixes: dict[str, list[str]] | None = None,
) -> ReconciliationResult:
    """TB 교차검증 오케스트레이터 — TB 생성 + 유형별 대사 + 전체 대사.

    Args:
        df: GL DataFrame (L1/L2 검증 통과)
        materiality: 중요성 금액 (EngagementProfile.materiality_amount)
        account_prefixes: 계정 유형별 접두사. None이면 audit_rules.yaml에서 로드.
    """
    warnings: list[str] = []

    # 1. 계정 접두사 로드 (YAML 설정 우선, 코드 하드코딩 금지)
    if account_prefixes is None:
        account_prefixes = _load_recon_prefixes()

    # 2. TB 생성
    tb_df = build_trial_balance(df)
    if tb_df.empty:
        return ReconciliationResult(
            warnings=["GL 데이터에서 TB 생성 불가 (필수 컬럼 부재 또는 빈 데이터)"],
        )

    # 3. 유형별 대사 (AR, AP, FA)
    items: list[ReconciliationItem] = []
    for recon_type, prefixes_list in account_prefixes.items():
        item = reconcile_by_prefix(df, tb_df, prefixes_list, recon_type, materiality)
        items.append(item)
        if not item.is_within_materiality:
            warnings.append(
                f"{recon_type} 대사 차이 {item.difference:,.2f}"
                f" (중요성 {materiality:,.2f} 초과)"
            )

    # 4. 전체 대사 (GL 합계 vs TB 합계)
    total_item = reconcile_by_prefix(df, tb_df, [], "TOTAL", materiality)
    items.append(total_item)
    if not total_item.is_within_materiality:
        warnings.append(
            f"전체 대사 차이 {total_item.difference:,.2f}"
            f" (중요성 {materiality:,.2f} 초과)"
        )

    total_diff = round(sum(abs(item.difference) for item in items), 2)
    all_ok = all(item.is_within_materiality for item in items)

    result = ReconciliationResult(
        items=items,
        total_differences=total_diff,
        all_reconciled=all_ok,
        trial_balance_rows=len(tb_df),
        materiality_amount=materiality,
        warnings=warnings,
        # Why: pipeline._load_db()에서 재사용 — 이중 build_trial_balance() 호출 방지
        trial_balance_df=tb_df,
    )

    if all_ok:
        logger.info("TB 교차검증 통과 — %d 계정, %d건 대사", len(tb_df), len(items))
    else:
        logger.warning("TB 교차검증 이슈: %s", ", ".join(warnings))

    return result


def _load_recon_prefixes() -> dict[str, list[str]]:
    """audit_rules.yaml에서 reconciliation_account_prefixes 로드."""
    try:
        from config.settings import get_audit_rules

        rules = get_audit_rules()
        prefixes = rules.get("reconciliation_account_prefixes")
        if isinstance(prefixes, dict) and prefixes:
            return prefixes
    except (ImportError, AttributeError):
        # Why: 테스트 환경에서 config 모듈 미설치 시만 폴백
        #      YAML 파싱 오류(ValueError 등)는 상위로 전파하여 설정 오류 즉시 노출
        logger.warning("config.settings 로드 불가 — 기본 접두사 사용")

    # Why: YAML 로드 실패 시 안전 폴백 (테스트 환경 등)
    return {"AR": ["11"], "AP": ["21"], "FA": ["15"]}
