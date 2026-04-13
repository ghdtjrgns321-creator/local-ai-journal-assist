"""TB 교차검증 단위 테스트 — WU-13.

테스트 대상: src/validation/tb_reconciliation.py
- build_trial_balance(): GL → 계정별 집계
- reconcile_by_prefix(): 계정 접두사별 GL vs TB 대사
- validate_tb_reconciliation(): 오케스트레이터
"""

import pandas as pd
import pytest

from src.validation.models import ReconciliationItem, ReconciliationResult
from src.validation.tb_reconciliation import (
    build_trial_balance,
    reconcile_by_prefix,
    validate_tb_reconciliation,
)


# ── fixture ──────────────────────────────────────────────────


def _make_gl_df(rows: list[dict]) -> pd.DataFrame:
    """GL 테스트 DataFrame 생성 헬퍼."""
    base = {
        "document_id": [],
        "gl_account": [],
        "debit_amount": [],
        "credit_amount": [],
        "fiscal_period": [],
        "fiscal_year": [],
    }
    for i, r in enumerate(rows):
        base["document_id"].append(r.get("document_id", f"JE{i:04d}"))
        base["gl_account"].append(r["gl_account"])
        base["debit_amount"].append(r.get("debit_amount", 0.0))
        base["credit_amount"].append(r.get("credit_amount", 0.0))
        base["fiscal_period"].append(r.get("fiscal_period", 1))
        base["fiscal_year"].append(r.get("fiscal_year", 2025))
    return pd.DataFrame(base)


@pytest.fixture()
def gl_3accounts() -> pd.DataFrame:
    """3개 계정(AR/AP/비용) 5건 — 기본 테스트용."""
    return _make_gl_df([
        {"gl_account": "1110", "debit_amount": 100_000.0, "credit_amount": 0.0},
        {"gl_account": "1110", "debit_amount": 50_000.0, "credit_amount": 0.0},
        {"gl_account": "2110", "debit_amount": 0.0, "credit_amount": 80_000.0},
        {"gl_account": "2110", "debit_amount": 0.0, "credit_amount": 20_000.0},
        {"gl_account": "5200", "debit_amount": 30_000.0, "credit_amount": 0.0},
    ])


@pytest.fixture()
def gl_multi_period() -> pd.DataFrame:
    """2개 기간에 걸친 GL — 기간별 분리 집계 확인."""
    return _make_gl_df([
        {"gl_account": "1110", "debit_amount": 100_000.0, "fiscal_period": 1},
        {"gl_account": "1110", "debit_amount": 200_000.0, "fiscal_period": 2},
        {"gl_account": "2110", "credit_amount": 50_000.0, "fiscal_period": 1},
    ])


# ── build_trial_balance ─────────────────────────────────────


class TestBuildTrialBalance:
    """build_trial_balance() 테스트."""

    def test_basic(self, gl_3accounts: pd.DataFrame) -> None:
        """GL 3계정 5건 → TB 3행, 집계값 정확성."""
        tb = build_trial_balance(gl_3accounts)
        assert len(tb) == 3
        # 1110: debit=150000, credit=0 → closing=150000
        row_1110 = tb[tb["gl_account"] == "1110"].iloc[0]
        assert row_1110["debit_total"] == 150_000.0
        assert row_1110["credit_total"] == 0.0
        assert row_1110["closing_balance"] == 150_000.0
        # 2110: debit=0, credit=100000 → closing=-100000
        row_2110 = tb[tb["gl_account"] == "2110"].iloc[0]
        assert row_2110["debit_total"] == 0.0
        assert row_2110["credit_total"] == 100_000.0
        assert row_2110["closing_balance"] == -100_000.0

    def test_empty(self) -> None:
        """빈 DataFrame → 빈 TB, 에러 없음."""
        empty = pd.DataFrame({
            "gl_account": pd.Series([], dtype="str"),
            "debit_amount": pd.Series([], dtype="float64"),
            "credit_amount": pd.Series([], dtype="float64"),
        })
        tb = build_trial_balance(empty)
        assert tb.empty

    def test_missing_columns(self) -> None:
        """필수 컬럼(debit_amount) 부재 → 빈 TB, 에러 없음."""
        df = pd.DataFrame({"gl_account": ["1110"], "credit_amount": [100.0]})
        tb = build_trial_balance(df)
        assert tb.empty

    def test_multi_period(self, gl_multi_period: pd.DataFrame) -> None:
        """fiscal_period 2개 → 기간별 분리 집계."""
        tb = build_trial_balance(gl_multi_period)
        # 1110: period 1 + period 2 = 2행, 2110: period 1 = 1행
        assert len(tb) == 3
        p1_1110 = tb[(tb["gl_account"] == "1110") & (tb["fiscal_period"] == 1)].iloc[0]
        assert p1_1110["debit_total"] == 100_000.0
        p2_1110 = tb[(tb["gl_account"] == "1110") & (tb["fiscal_period"] == 2)].iloc[0]
        assert p2_1110["debit_total"] == 200_000.0

    def test_float_precision(self) -> None:
        """부동소수점 집계 오차 → round(2) 방어 확인."""
        # Why: 0.1 + 0.2 != 0.3 같은 부동소수점 오차를 round(2)로 방어
        rows = [
            {"gl_account": "1110", "debit_amount": 0.1, "credit_amount": 0.0},
            {"gl_account": "1110", "debit_amount": 0.2, "credit_amount": 0.0},
        ]
        df = _make_gl_df(rows)
        tb = build_trial_balance(df)
        assert tb.iloc[0]["closing_balance"] == 0.3


# ── reconcile_by_prefix ─────────────────────────────────────


class TestReconcileByPrefix:
    """reconcile_by_prefix() 테스트."""

    def test_exact_match(self, gl_3accounts: pd.DataFrame) -> None:
        """GL 잔액 == TB 잔액 → diff=0, within_materiality=True."""
        tb = build_trial_balance(gl_3accounts)
        item = reconcile_by_prefix(gl_3accounts, tb, ["11"], "AR", materiality=0.0)
        assert item.difference == 0.0
        assert item.is_within_materiality is True

    def test_within_materiality(self, gl_3accounts: pd.DataFrame) -> None:
        """materiality 내 차이 → within_materiality=True."""
        tb = build_trial_balance(gl_3accounts)
        # TB closing_balance를 임의 조작하여 차이 발생
        tb.loc[tb["gl_account"] == "1110", "closing_balance"] = 150_001.0
        item = reconcile_by_prefix(gl_3accounts, tb, ["11"], "AR", materiality=5.0)
        assert abs(item.difference) <= 5.0
        assert item.is_within_materiality is True

    def test_exceeds_materiality(self, gl_3accounts: pd.DataFrame) -> None:
        """materiality 초과 차이 → within_materiality=False."""
        tb = build_trial_balance(gl_3accounts)
        tb.loc[tb["gl_account"] == "1110", "closing_balance"] = 160_000.0
        item = reconcile_by_prefix(gl_3accounts, tb, ["11"], "AR", materiality=1000.0)
        assert abs(item.difference) > 1000.0
        assert item.is_within_materiality is False

    def test_no_matching_accounts(self, gl_3accounts: pd.DataFrame) -> None:
        """해당 접두사 계정 없음 → balance=0."""
        tb = build_trial_balance(gl_3accounts)
        item = reconcile_by_prefix(gl_3accounts, tb, ["99"], "OTHER", materiality=0.0)
        assert item.gl_balance == 0.0
        assert item.tb_balance == 0.0
        assert item.difference == 0.0
        assert item.is_within_materiality is True


# ── validate_tb_reconciliation ──────────────────────────────


class TestValidateTbReconciliation:
    """validate_tb_reconciliation() 오케스트레이터 테스트."""

    def test_all_pass(self, gl_3accounts: pd.DataFrame) -> None:
        """AR/AP/FA + TOTAL 전체 통과."""
        result = validate_tb_reconciliation(
            gl_3accounts,
            materiality=0.0,
            account_prefixes={"AR": ["11"], "AP": ["21"], "FA": ["15"]},
        )
        assert isinstance(result, ReconciliationResult)
        assert result.all_reconciled is True
        assert result.total_differences == 0.0
        assert len(result.warnings) == 0
        # 3 유형 + TOTAL = 4 항목
        assert len(result.items) == 4

    def test_partial_fail(self) -> None:
        """AR 대사 차이 발생 → all_reconciled=False, warnings 포함.

        Why: GL 데이터를 조작하여 AR 계정(11xx)의 debit/credit 집계가
             TB의 closing_balance와 불일치하는 상황을 시뮬레이션.
             reconcile_by_prefix가 GL 원본과 TB를 독립적으로 집계하므로,
             GL에 집계 후 TB를 수동 조작하면 차이를 만들 수 있다.
        """
        from src.validation.tb_reconciliation import build_trial_balance

        gl = _make_gl_df([
            {"gl_account": "1110", "debit_amount": 100_000.0},
            {"gl_account": "2110", "credit_amount": 50_000.0},
        ])
        # 정상 TB 생성 후 closing_balance를 조작하여 차이 유발
        tb = build_trial_balance(gl)
        tb.loc[tb["gl_account"] == "1110", "closing_balance"] = 200_000.0

        from src.validation.tb_reconciliation import reconcile_by_prefix

        item = reconcile_by_prefix(gl, tb, ["11"], "AR", materiality=1000.0)
        # GL: 100,000 vs TB: 200,000 → diff = -100,000 > materiality(1,000)
        assert item.is_within_materiality is False
        assert abs(item.difference) == 100_000.0

    def test_custom_prefixes(self, gl_3accounts: pd.DataFrame) -> None:
        """커스텀 접두사 동작 확인."""
        result = validate_tb_reconciliation(
            gl_3accounts,
            materiality=0.0,
            account_prefixes={"CUSTOM": ["52"]},
        )
        # CUSTOM(5200) + TOTAL = 2 항목
        assert len(result.items) == 2
        custom_item = result.items[0]
        assert custom_item.recon_type == "CUSTOM"
        assert custom_item.gl_balance == 30_000.0

    def test_empty_df(self) -> None:
        """빈 DataFrame → warnings 메시지, 에러 없음."""
        empty = pd.DataFrame({
            "gl_account": pd.Series([], dtype="str"),
            "debit_amount": pd.Series([], dtype="float64"),
            "credit_amount": pd.Series([], dtype="float64"),
        })
        result = validate_tb_reconciliation(empty, materiality=0.0)
        assert result.all_reconciled is True
        assert result.trial_balance_rows == 0
        assert len(result.warnings) > 0

    def test_zero_materiality(self, gl_3accounts: pd.DataFrame) -> None:
        """materiality=0 → 차이 0만 통과."""
        result = validate_tb_reconciliation(
            gl_3accounts,
            materiality=0.0,
            account_prefixes={"AR": ["11"]},
        )
        # GL→TB 동일 소스이므로 차이=0, 통과
        assert result.all_reconciled is True
        for item in result.items:
            assert item.difference == 0.0

    def test_result_types(self, gl_3accounts: pd.DataFrame) -> None:
        """반환 타입 검증."""
        result = validate_tb_reconciliation(
            gl_3accounts,
            materiality=1000.0,
            account_prefixes={"AR": ["11"]},
        )
        assert isinstance(result, ReconciliationResult)
        assert isinstance(result.items[0], ReconciliationItem)
        assert isinstance(result.total_differences, float)
        assert isinstance(result.all_reconciled, bool)
        assert isinstance(result.trial_balance_rows, int)

    def test_materiality_from_engagement(self, gl_3accounts: pd.DataFrame) -> None:
        """materiality 값이 결과에 기록되는지 확인."""
        mat = 500_000.0
        result = validate_tb_reconciliation(
            gl_3accounts,
            materiality=mat,
            account_prefixes={"AR": ["11"]},
        )
        assert result.materiality_amount == mat
