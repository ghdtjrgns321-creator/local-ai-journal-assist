"""amount_features 단위 테스트.

계층: base_amount → 개별 피처 → orchestrator 순서로 검증.
"""

import numpy as np
import pandas as pd
import pytest
from pathlib import Path

from config.settings import AuditSettings
from src.ingest.datasynth_labels import set_source_path
from src.feature import amount_features as amount_features_module
from src.feature.amount_features import (
    _compute_base_amount,
    _map_coa_category,
    _zscore_with_fallback,
    add_all_amount_features,
    add_amount_magnitude,
    add_amount_zscore,
    add_exceeds_threshold,
    add_is_near_threshold,
    add_is_round_number,
)


# ── TestBaseAmount ───────────────────────────────────────────────


class TestBaseAmount:
    """_compute_base_amount: 차/대 중 큰 값 선택, NaN 방어."""

    def test_debit_only(self):
        df = pd.DataFrame({"debit_amount": [100], "credit_amount": [0]})
        assert _compute_base_amount(df).iloc[0] == 100

    def test_credit_only(self):
        df = pd.DataFrame({"debit_amount": [0], "credit_amount": [200]})
        assert _compute_base_amount(df).iloc[0] == 200

    def test_both_zero(self):
        df = pd.DataFrame({"debit_amount": [0], "credit_amount": [0]})
        assert _compute_base_amount(df).iloc[0] == 0

    def test_both_nan(self):
        """둘 다 NaN → fillna(0) → 0."""
        df = pd.DataFrame({"debit_amount": [np.nan], "credit_amount": [np.nan]})
        assert _compute_base_amount(df).iloc[0] == 0

    def test_one_nan(self):
        """한쪽 NaN → 유효값 사용."""
        df = pd.DataFrame({"debit_amount": [np.nan], "credit_amount": [500]})
        assert _compute_base_amount(df).iloc[0] == 500


# ── TestIsNearThreshold ──────────────────────────────────────────


class TestIsNearThreshold:
    """L2-01: 승인권자 한도가 확인되는 경우에만 판정."""

    THRESHOLDS = [10_000_000, 100_000_000, 1_000_000_000]
    RATIO = 0.90

    def test_uses_approver_limit_on_document_total(self, monkeypatch):
        """실제 approval_limit가 있으면 문서 총액 기준으로 near 판정."""
        monkeypatch.setattr(
            amount_features_module,
            "_resolve_employee_master_path",
            lambda df: Path("dummy-employees.json"),
        )
        monkeypatch.setattr(
            amount_features_module,
            "_load_employee_approval_map",
            lambda path: {"APR-001": (100_000_000.0, True)},
        )

        df = pd.DataFrame({
            "document_id": ["A", "A"],
            "approved_by": ["APR-001", "APR-001"],
            "debit_amount": [45_000_000, 50_000_000],
            "credit_amount": [0, 0],
        })
        base = _compute_base_amount(df)

        add_is_near_threshold(df, base, self.THRESHOLDS, self.RATIO)

        assert df["is_near_threshold"].all()

    def test_below_approver_limit_lower_bound_is_false(self, monkeypatch):
        """실제 approval_limit의 90% 미만이면 near가 아니다."""
        monkeypatch.setattr(
            amount_features_module,
            "_resolve_employee_master_path",
            lambda df: Path("dummy-employees.json"),
        )
        monkeypatch.setattr(
            amount_features_module,
            "_load_employee_approval_map",
            lambda path: {"APR-001": (100_000_000.0, True)},
        )

        df = pd.DataFrame({
            "document_id": ["A", "A"],
            "approved_by": ["APR-001", "APR-001"],
            "debit_amount": [40_000_000, 45_000_000],
            "credit_amount": [0, 0],
        })
        base = _compute_base_amount(df)

        add_is_near_threshold(df, base, self.THRESHOLDS, self.RATIO)

        assert not df["is_near_threshold"].any()

    def test_at_approver_limit_is_false(self, monkeypatch):
        """실제 approval_limit 정확히는 near 상한 밖이다."""
        monkeypatch.setattr(
            amount_features_module,
            "_resolve_employee_master_path",
            lambda df: Path("dummy-employees.json"),
        )
        monkeypatch.setattr(
            amount_features_module,
            "_load_employee_approval_map",
            lambda path: {"APR-001": (100_000_000.0, True)},
        )

        df = pd.DataFrame({
            "document_id": ["A", "A"],
            "approved_by": ["APR-001", "APR-001"],
            "debit_amount": [40_000_000, 60_000_000],
            "credit_amount": [0, 0],
        })
        base = _compute_base_amount(df)

        add_is_near_threshold(df, base, self.THRESHOLDS, self.RATIO)

        assert not df["is_near_threshold"].any()

    def test_missing_approver_limit_is_not_flagged(self):
        """approval_limit를 알 수 없으면 L2-01로 판정하지 않는다."""
        base = pd.Series([95_000_000])
        df = pd.DataFrame({
            "document_id": ["A"],
            "approved_by": ["APR-UNKNOWN"],
            "debit_amount": [95_000_000],
            "credit_amount": [0],
        })
        add_is_near_threshold(df, base, self.THRESHOLDS, self.RATIO)
        assert df["is_near_threshold"].iloc[0] == False

    def test_common_thresholds_do_not_apply_without_approver_limit(self):
        """공통 approval_thresholds는 L2-01 fallback으로 쓰지 않는다."""
        base = pd.Series([20_000_000])
        df = pd.DataFrame({
            "document_id": ["A"],
            "approved_by": ["APR-UNKNOWN"],
            "debit_amount": [20_000_000],
            "credit_amount": [0],
        })
        add_is_near_threshold(df, base, self.THRESHOLDS, self.RATIO)
        assert df["is_near_threshold"].iloc[0] == False


# ── TestExceedsThreshold ─────────────────────────────────────────


class TestExceedsThreshold:
    """L1-04: 다단계 승인한도 초과. base >= min(thresholds)."""

    THRESHOLDS = [10_000_000, 100_000_000, 1_000_000_000]

    def test_exact_threshold(self):
        """최고 한도(1B) 정확히 → True, level=3."""
        base = pd.Series([self.THRESHOLDS[-1]])
        df = pd.DataFrame({"x": [0]})
        add_exceeds_threshold(df, base, self.THRESHOLDS)
        assert df["exceeds_threshold"].iloc[0] == True
        assert df["approval_level"].iloc[0] == 3

    def test_below_all_thresholds(self):
        """최저 한도(10M) 미만 → False, level=0."""
        base = pd.Series([self.THRESHOLDS[0] - 1])
        df = pd.DataFrame({"x": [0]})
        add_exceeds_threshold(df, base, self.THRESHOLDS)
        assert df["exceeds_threshold"].iloc[0] == False
        assert df["approval_level"].iloc[0] == 0

    def test_mid_level_exceeds(self):
        """최저 한도(10M) 초과, 중간 한도(100M) 미만 → True, level=1."""
        base = pd.Series([50_000_000])
        df = pd.DataFrame({"x": [0]})
        add_exceeds_threshold(df, base, self.THRESHOLDS)
        assert df["exceeds_threshold"].iloc[0] == True
        assert df["approval_level"].iloc[0] == 1

    def test_no_gap_with_near(self):
        """최고 한도 정확히 → near=False, exceeds=True (gap 없음)."""
        ratio = 0.90
        base = pd.Series([self.THRESHOLDS[-1]])
        df = pd.DataFrame({"x": [0]})
        add_is_near_threshold(df, base, self.THRESHOLDS, ratio)
        add_exceeds_threshold(df, base, self.THRESHOLDS)
        assert df["is_near_threshold"].iloc[0] == False
        assert df["exceeds_threshold"].iloc[0] == True


# ── TestMapCoaCategory ───────────────────────────────────────────


class TestExceedsThresholdDocumentLevel:
    """L1-04 additional coverage for document-level totals."""

    THRESHOLDS = [10_000_000, 100_000_000, 1_000_000_000]

    def test_document_total_exceeds_even_when_each_line_is_below_threshold(self):
        df = pd.DataFrame({
            "document_id": ["A", "A", "A", "A"],
            "debit_amount": [6_627_172, 4_372_828, 0, 0],
            "credit_amount": [0, 0, 7_523_745, 3_476_255],
        })
        base = _compute_base_amount(df)

        add_exceeds_threshold(df, base, self.THRESHOLDS)

        assert df["exceeds_threshold"].all()
        assert (df["approval_level"] == 1).all()


class TestExceedsThresholdApproverLimit:
    THRESHOLDS = [10_000_000, 100_000_000, 1_000_000_000]

    def test_uses_approver_limit_when_employee_master_exists(self, monkeypatch):
        monkeypatch.setattr(
            amount_features_module,
            "_resolve_employee_master_path",
            lambda df: Path("dummy-employees.json"),
        )
        monkeypatch.setattr(
            amount_features_module,
            "_load_employee_approval_map",
            lambda path: {
                "APR-001": (10_000_000.0, True),
                "APR-002": (50_000_000.0, True),
            },
        )

        df = pd.DataFrame({
            "document_id": ["A", "A", "B", "B"],
            "approved_by": ["APR-001", "APR-001", "APR-002", "APR-002"],
            "debit_amount": [6_000_000, 5_000_000, 30_000_000, 10_000_000],
            "credit_amount": [0, 0, 0, 0],
        })
        base = _compute_base_amount(df)

        add_exceeds_threshold(df, base, self.THRESHOLDS)

        assert df.loc[df["document_id"] == "A", "exceeds_threshold"].all()
        assert not df.loc[df["document_id"] == "B", "exceeds_threshold"].any()

    def test_can_approve_je_false_behaves_like_zero_limit(self, monkeypatch):
        monkeypatch.setattr(
            amount_features_module,
            "_resolve_employee_master_path",
            lambda df: Path("dummy-employees.json"),
        )
        monkeypatch.setattr(
            amount_features_module,
            "_load_employee_approval_map",
            lambda path: {"APR-001": (50_000_000.0, False)},
        )

        df = pd.DataFrame({
            "document_id": ["A", "A"],
            "approved_by": ["APR-001", "APR-001"],
            "debit_amount": [1_000_000, 2_000_000],
            "credit_amount": [0, 0],
        })
        base = _compute_base_amount(df)

        add_exceeds_threshold(df, base, self.THRESHOLDS)

        assert df["exceeds_threshold"].all()


class TestMapCoaCategory:
    """GL 계정 코드 → CoA 상위그룹 매핑."""

    COA_PREFIXES = {
        "asset": ["1"],
        "liability": ["2"],
        "equity": ["3"],
        "revenue": ["4"],
        "expense": ["5"],
    }

    def test_standard_mapping(self):
        """1xxx→asset, 2xxx→liability, 4xxx→revenue 등."""
        gl = pd.Series(["1000", "2100", "3000", "4100", "5200"])
        result = _map_coa_category(gl, self.COA_PREFIXES)
        assert result.tolist() == ["asset", "liability", "equity", "revenue", "expense"]

    def test_unknown_prefix_returns_other(self):
        """9xxx 등 비표준 계정 → "other"."""
        gl = pd.Series(["9990", "8000", "0100"])
        result = _map_coa_category(gl, self.COA_PREFIXES)
        assert (result == "other").all()

    def test_none_prefixes_returns_all_other(self):
        """coa_prefixes=None → 전부 "other"."""
        gl = pd.Series(["1000", "4100"])
        result = _map_coa_category(gl, None)
        assert (result == "other").all()

    def test_int64_gl_account(self):
        """int64로 캐스팅된 gl_account도 정상 매핑."""
        gl = pd.Series([1000, 4100, 9990])
        result = _map_coa_category(gl, self.COA_PREFIXES)
        assert result.tolist() == ["asset", "revenue", "other"]

    def test_nullable_int64(self):
        """nullable Int64 (pandas NA 포함) 안전 처리."""
        gl = pd.array([1000, None, 4100], dtype="Int64")
        result = _map_coa_category(pd.Series(gl), self.COA_PREFIXES)
        assert result.iloc[0] == "asset"
        assert result.iloc[1] == "other"  # NA → "<NA>" → 어떤 prefix와도 미매칭
        assert result.iloc[2] == "revenue"


# ── TestAmountZscore ─────────────────────────────────────────────


class TestAmountZscore:
    """L4-03: 그룹별 Z-score + fallback."""

    def test_large_group_has_values(self, af_zscore_df):
        """30건+ 그룹은 Z-score 값이 존재해야 한다."""
        base = _compute_base_amount(af_zscore_df)
        df = af_zscore_df.copy()
        add_amount_zscore(df, base)
        # 큰 그룹 "A"의 zscore는 NaN이 아님
        large = df[df["gl_account"] == "A"]["amount_zscore"]
        assert large.notna().all()

    def test_small_group_fallback(self, af_zscore_df):
        """30건 미만 그룹은 전체 기준 Z-score로 fallback."""
        base = _compute_base_amount(af_zscore_df)
        df = af_zscore_df.copy()
        add_amount_zscore(df, base)
        small = df[df["gl_account"] == "B"]["amount_zscore"]
        assert small.notna().all()

    def test_std_zero_returns_zero(self, af_uniform_df):
        """모든 금액 동일(std=0) → Z-score 0.0, 에러 없음."""
        base = _compute_base_amount(af_uniform_df)
        df = af_uniform_df.copy()
        add_amount_zscore(df, base)
        assert (df["amount_zscore"] == 0.0).all()

    def test_too_few_rows_returns_nan(self):
        """전체 10건 미만 → Z-score 전부 NaN."""
        df = pd.DataFrame({
            "debit_amount": [1_000_000] * 5,
            "credit_amount": [0] * 5,
            "gl_account": ["X"] * 5,
        })
        base = _compute_base_amount(df)
        add_amount_zscore(df, base)
        assert df["amount_zscore"].isna().all()

    def test_missing_gl_account(self):
        """gl_account 컬럼 누락 → NaN + warning."""
        df = pd.DataFrame({
            "debit_amount": [1_000_000],
            "credit_amount": [0],
        })
        base = _compute_base_amount(df)
        add_amount_zscore(df, base)
        assert df["amount_zscore"].isna().all()

    # ── CoA 상위계정 fallback (WU-11) ────────────────────────

    COA_PREFIXES = {
        "asset": ["1"],
        "liability": ["2"],
        "revenue": ["4"],
        "expense": ["5"],
    }

    def test_coa_fallback_same_category(self, af_coa_fallback_df):
        """소그룹 B(1200, n=5)가 같은 CoA(자산=A+B, n=40) 통계로 fallback.

        CoA fallback 없이 전체 데이터 fallback을 했을 때와 다른 값이어야 한다.
        """
        df = af_coa_fallback_df.copy()
        base = _compute_base_amount(df)

        # CoA fallback 없는 기존 방식
        df_no_coa = df.copy()
        add_amount_zscore(df_no_coa, base.copy())
        z_no_coa = df_no_coa.loc[df_no_coa["gl_account"] == "1200", "amount_zscore"]

        # CoA fallback 사용
        df_coa = df.copy()
        add_amount_zscore(df_coa, base.copy(), coa_prefixes=self.COA_PREFIXES)
        z_coa = df_coa.loc[df_coa["gl_account"] == "1200", "amount_zscore"]

        # 둘 다 NaN이 아니어야 함
        assert z_no_coa.notna().all()
        assert z_coa.notna().all()
        # CoA fallback(자산 그룹)과 전체 fallback 값은 달라야 함
        assert not np.allclose(z_no_coa.values, z_coa.values)

    def test_coa_fallback_small_coa_uses_total(self, af_coa_fallback_df):
        """소그룹 C(4100, n=5) + CoA(수익, n=5) → CoA도 소그룹 → 전체 fallback."""
        df = af_coa_fallback_df.copy()
        base = _compute_base_amount(df)

        # CoA fallback 없는 기존 방식
        df_no_coa = df.copy()
        add_amount_zscore(df_no_coa, base.copy())
        z_no_coa = df_no_coa.loc[df_no_coa["gl_account"] == "4100", "amount_zscore"]

        # CoA fallback 사용 — revenue 그룹도 5건이므로 전체 fallback과 동일해야 함
        df_coa = df.copy()
        add_amount_zscore(df_coa, base.copy(), coa_prefixes=self.COA_PREFIXES)
        z_coa = df_coa.loc[df_coa["gl_account"] == "4100", "amount_zscore"]

        assert z_no_coa.notna().all()
        assert z_coa.notna().all()
        # CoA도 소그룹이므로 전체 fallback과 동일
        assert np.allclose(z_no_coa.values, z_coa.values)


# ── TestAmountMagnitude ──────────────────────────────────────────


class TestAmountMagnitude:
    """log10(abs(base) + 1) 스케일."""

    def test_million(self):
        base = pd.Series([1_000_000])
        df = pd.DataFrame({"x": [0]})
        add_amount_magnitude(df, base)
        assert pytest.approx(df["amount_magnitude"].iloc[0], abs=0.01) == np.log10(1_000_001)

    def test_zero(self):
        base = pd.Series([0])
        df = pd.DataFrame({"x": [0]})
        add_amount_magnitude(df, base)
        assert df["amount_magnitude"].iloc[0] == 0.0

    def test_nan(self):
        base = pd.Series([np.nan])
        df = pd.DataFrame({"x": [0]})
        add_amount_magnitude(df, base)
        assert pd.isna(df["amount_magnitude"].iloc[0])


# ── TestIsRoundNumber ────────────────────────────────────────────


class TestIsRoundNumber:
    """L2-02: 라운드넘버 판정."""

    UNIT = 1_000_000

    def test_round(self):
        base = pd.Series([10_000_000])
        df = pd.DataFrame({"x": [0]})
        add_is_round_number(df, base, self.UNIT)
        assert df["is_round_number"].iloc[0] == True

    def test_not_round(self):
        base = pd.Series([10_500_000])
        df = pd.DataFrame({"x": [0]})
        add_is_round_number(df, base, self.UNIT)
        assert df["is_round_number"].iloc[0] == False

    def test_zero_excluded(self):
        """0원 → False (라운드넘버에서 제외)."""
        base = pd.Series([0])
        df = pd.DataFrame({"x": [0]})
        add_is_round_number(df, base, self.UNIT)
        assert df["is_round_number"].iloc[0] == False

    def test_nan_is_false(self):
        """NaN → False."""
        base = pd.Series([np.nan])
        df = pd.DataFrame({"x": [0]})
        add_is_round_number(df, base, self.UNIT)
        assert df["is_round_number"].iloc[0] == False

    def test_float_tail_tolerance(self):
        """float 소수점 꼬리(미세)가 있어도 round 후 배수 판정."""
        base = pd.Series([10_000_000.000001, 5_000_000.4])
        df = pd.DataFrame({"x": [0, 0]})
        add_is_round_number(df, base, self.UNIT)
        # .000001 → round → 10M (배수), .4 → round → 5M (배수)
        assert df["is_round_number"].tolist() == [True, True]

    def test_near_but_not_round(self):
        """반올림해도 배수가 아닌 경우 → False."""
        base = pd.Series([10_500_000.3])
        df = pd.DataFrame({"x": [0]})
        add_is_round_number(df, base, self.UNIT)
        assert df["is_round_number"].iloc[0] == False

    # ── 외화 소수점 처리 (currency_decimals) ──────────────────

    _CURR_DEC = {"KRW": 0, "USD": 2, "EUR": 2, "JPY": 0}

    def test_usd_round_with_decimals(self):
        """USD $10,000,000.00 → round(2) → %1M==0 → True."""
        base = pd.Series([10_000_000.00])
        df = pd.DataFrame({"x": [0], "currency": ["USD"]})
        add_is_round_number(df, base, self.UNIT, currency_decimals=self._CURR_DEC)
        assert df["is_round_number"].iloc[0] == True  # noqa: E712

    def test_mixed_currency(self):
        """KRW + USD 혼합: 둘 다 10M → 둘 다 True."""
        base = pd.Series([10_000_000, 10_000_000.00])
        df = pd.DataFrame({"x": [0, 0], "currency": ["KRW", "USD"]})
        add_is_round_number(df, base, self.UNIT, currency_decimals=self._CURR_DEC)
        assert df["is_round_number"].tolist() == [True, True]

    def test_no_currency_column_fallback(self):
        """currency 컬럼 없으면 기존 로직(round(0)) 폴백."""
        base = pd.Series([10_000_000.00])
        df = pd.DataFrame({"x": [0]})
        add_is_round_number(df, base, self.UNIT, currency_decimals=self._CURR_DEC)
        assert df["is_round_number"].iloc[0] == True  # noqa: E712

    def test_unknown_currency_defaults_to_round0(self):
        """currency_decimals에 없는 통화 → round(0) 폴백."""
        base = pd.Series([10_000_000.00])
        df = pd.DataFrame({"x": [0], "currency": ["CHF"]})
        add_is_round_number(df, base, self.UNIT, currency_decimals=self._CURR_DEC)
        assert df["is_round_number"].iloc[0] == True  # noqa: E712

    def test_nan_currency_fallback(self):
        """currency가 NaN인 행 → round(0) 폴백. groupby NaN 제외 버그 방지."""
        base = pd.Series([10_000_000.0, 5_000_000.0])
        df = pd.DataFrame({"x": [0, 0], "currency": ["USD", None]})
        add_is_round_number(df, base, self.UNIT, currency_decimals=self._CURR_DEC)
        assert df["is_round_number"].iloc[0] == True   # noqa: E712 — USD round(2)
        assert df["is_round_number"].iloc[1] == True   # noqa: E712 — NaN round(0)


# ── TestAddAllAmountFeatures ─────────────────────────────────────


class TestAddAllAmountFeatures:
    """오케스트레이터: 5개 컬럼 생성, base_amount 미포함."""

    EXPECTED_COLS = {
        "is_near_threshold",
        "exceeds_threshold",
        "amount_zscore",
        "amount_magnitude",
        "is_round_number",
    }

    def test_all_columns_present(self, af_basic_df):
        result = add_all_amount_features(af_basic_df.copy())
        assert self.EXPECTED_COLS.issubset(result.columns)

    def test_base_amount_not_in_output(self, af_basic_df):
        result = add_all_amount_features(af_basic_df.copy())
        assert "base_amount" not in result.columns

    def test_custom_settings(self, af_basic_df):
        """approval_thresholds 커스텀 주입이 피처에 반영되는지 확인."""
        custom = AuditSettings(
            approval_thresholds=[10_000_000],
            near_threshold_ratio=0.80,
            round_unit=500_000,
        )
        result = add_all_amount_features(af_basic_df.copy(), settings=custom)
        assert self.EXPECTED_COLS.issubset(result.columns)
        # 10M 초과 금액은 exceeds=True 여야 함
        assert result["exceeds_threshold"].any()

    def test_edge_cases(self, af_edge_df):
        """NaN/0 포함 데이터에서 에러 없이 완료."""
        result = add_all_amount_features(af_edge_df.copy())
        assert self.EXPECTED_COLS.issubset(result.columns)

    def test_currency_decimals_via_audit_rules(self, af_basic_df):
        """audit_rules 주입 시 currency_decimals가 is_round_number에 반영."""
        df = af_basic_df.copy()
        df["currency"] = "USD"
        rules = {"currency_decimals": {"USD": 2, "KRW": 0}}
        result = add_all_amount_features(df, audit_rules=rules)
        assert "is_round_number" in result.columns
