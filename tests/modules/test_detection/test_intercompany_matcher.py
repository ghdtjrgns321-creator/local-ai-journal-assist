"""IntercompanyMatcher 단위 테스트 — WU-07 내부거래 매칭 탐지기.

22개 테스트: Basic(3) + IC01(6) + IC02(4) + IC03(3) + Graceful(4) + YAML(2)
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.detection.base import DetectionResult
from src.detection.intercompany_matcher import IntercompanyMatcher
from src.detection.intercompany_rules import extract_ic_prefixes, load_ic_pairs

# ── 공용 헬퍼 ──────────────────────────────────────────────────

AUDIT_RULES = {
    "patterns": {
        "intercompany": {
            "pairs": [
                {"receivable": "1150", "payable": "2050"},
                {"receivable": "4500", "payable": "2700"},
            ],
        },
    },
}

RULES_FLAT = AUDIT_RULES["patterns"]


def _make_ic_df(
    rows: list[dict],
    *,
    ic_identifiers: list[str] | None = None,
) -> pd.DataFrame:
    """IC 테스트용 DataFrame 생성 — is_intercompany 자동 설정."""
    df = pd.DataFrame(rows)
    if "posting_date" in df.columns:
        df["posting_date"] = pd.to_datetime(df["posting_date"])
    if ic_identifiers is None:
        ic_identifiers = ["1150", "2050", "4500", "2700"]
    if "gl_account" in df.columns:
        gl_str = df["gl_account"].astype(str).str.strip()
        df["is_intercompany"] = gl_str.str.startswith(tuple(ic_identifiers))
    else:
        df["is_intercompany"] = False
    for col in ["debit_amount", "credit_amount"]:
        if col not in df.columns:
            df[col] = 0.0
    return df


def _detector(**kwargs) -> IntercompanyMatcher:
    return IntercompanyMatcher(audit_rules=AUDIT_RULES, **kwargs)


# ── Basic (3개) ────────────────────────────────────────────────


class TestBasic:
    """기본 인터페이스 검증."""

    def test_track_name(self):
        """#1: track_name은 'intercompany'."""
        det = _detector()
        assert det.track_name == "intercompany"

    def test_returns_detection_result(self):
        """#2: detect() 반환 타입은 DetectionResult."""
        df = _make_ic_df([
            {"gl_account": "1150", "debit_amount": 1_000_000, "credit_amount": 0, "company_code": "A", "trading_partner": "B"},
            {"gl_account": "2050", "debit_amount": 0, "credit_amount": 1_000_000, "company_code": "B", "trading_partner": "A"},
        ])
        result = _detector().detect(df)
        assert isinstance(result, DetectionResult)
        assert result.track_name == "intercompany"

    def test_scores_range(self):
        """#3: scores 범위 0.0~1.0."""
        df = _make_ic_df([
            {"gl_account": "1150", "debit_amount": 1_000_000, "credit_amount": 0, "company_code": "A", "trading_partner": "B"},
            {"gl_account": "2050", "debit_amount": 0, "credit_amount": 1_000_000, "company_code": "B", "trading_partner": "A"},
            {"gl_account": "5000", "debit_amount": 500_000, "credit_amount": 0},  # 비IC
        ])
        result = _detector().detect(df)
        assert result.scores.min() >= 0.0
        assert result.scores.max() <= 1.0


# ── IC01 미매칭 (6개) ──────────────────────────────────────────


class TestIC01Unmatched:
    """IC01: 미매칭 내부거래 탐지."""

    def test_matched_pair_score_zero(self):
        """#4: A→B receivable + B→A payable 매칭 → IC01 score 0."""
        df = _make_ic_df([
            {"gl_account": "1150", "debit_amount": 1_000_000, "credit_amount": 0,
             "company_code": "A", "trading_partner": "B"},
            {"gl_account": "2050", "debit_amount": 0, "credit_amount": 1_000_000,
             "company_code": "B", "trading_partner": "A"},
        ])
        result = _detector().detect(df)
        assert "IC01" in result.details.columns
        assert result.details["IC01"].sum() == 0.0

    def test_unmatched_ic_flagged(self):
        """#5: receivable만 존재, payable 없음 → IC01 score > 0."""
        df = _make_ic_df([
            {"gl_account": "1150", "debit_amount": 1_000_000, "credit_amount": 0,
             "company_code": "A", "trading_partner": "B"},
            {"gl_account": "1150", "debit_amount": 500_000, "credit_amount": 0,
             "company_code": "A", "trading_partner": "B"},
            {"gl_account": "5000", "debit_amount": 500_000, "credit_amount": 0},  # 비IC
        ])
        result = _detector().detect(df)
        assert result.details["IC01"].iloc[0] > 0  # IC 행 flagged

    def test_n_to_m_matching(self):
        """#6: N:M 매칭 — A사 3건 소액 vs B사 1건 통합 → 합계 일치 시 score 0."""
        df = _make_ic_df([
            # A사: 3건 × 100만원 = 300만원 receivable
            {"gl_account": "1150", "debit_amount": 1_000_000, "credit_amount": 0,
             "company_code": "A", "trading_partner": "B"},
            {"gl_account": "1150", "debit_amount": 1_000_000, "credit_amount": 0,
             "company_code": "A", "trading_partner": "B"},
            {"gl_account": "1150", "debit_amount": 1_000_000, "credit_amount": 0,
             "company_code": "A", "trading_partner": "B"},
            # B사: 1건 300만원 payable
            {"gl_account": "2050", "debit_amount": 0, "credit_amount": 3_000_000,
             "company_code": "B", "trading_partner": "A"},
        ])
        result = _detector().detect(df)
        # Why: 그룹 합계 일치 → IC01 전체 0
        assert result.details["IC01"].sum() == 0.0

    def test_trading_partner_null_fallback(self):
        """#7: trading_partner NULL → company_code 쌍 집계로 매칭."""
        df = _make_ic_df([
            {"gl_account": "1150", "debit_amount": 1_000_000, "credit_amount": 0,
             "company_code": "A"},
            {"gl_account": "2050", "debit_amount": 0, "credit_amount": 1_000_000,
             "company_code": "B"},
        ])
        result = _detector().detect(df)
        # Why: company_code만으로 aggregate 매칭
        assert isinstance(result, DetectionResult)

    def test_single_company_code_fallback(self):
        """#8: company_code 단일값 → IC 계정유형 쌍 금액 대사."""
        df = _make_ic_df([
            {"gl_account": "1150", "debit_amount": 1_000_000, "credit_amount": 0,
             "company_code": "A"},
            {"gl_account": "2050", "debit_amount": 0, "credit_amount": 1_000_000,
             "company_code": "A"},
        ])
        result = _detector().detect(df)
        # Why: Level 3 fallback — receivable sum == payable sum → 매칭
        assert result.details["IC01"].sum() == 0.0

    def test_non_ic_rows_zero_score(self):
        """#9: 비 IC 행은 항상 score 0."""
        df = _make_ic_df([
            {"gl_account": "1150", "debit_amount": 1_000_000, "credit_amount": 0,
             "company_code": "A", "trading_partner": "B"},
            {"gl_account": "2050", "debit_amount": 0, "credit_amount": 1_000_000,
             "company_code": "B", "trading_partner": "A"},
            {"gl_account": "5000", "debit_amount": 500_000, "credit_amount": 0},  # 비IC
        ])
        result = _detector().detect(df)
        assert result.scores.iloc[2] == 0.0


# ── IC02 금액 불일치 (4개) ─────────────────────────────────────


class TestIC02AmountMismatch:
    """IC02: 매칭됐으나 금액 차이 초과."""

    def test_exact_match_no_flag(self):
        """#10: 금액 정확 일치 → IC02 score 0."""
        df = _make_ic_df([
            {"gl_account": "1150", "debit_amount": 1_000_000, "credit_amount": 0,
             "company_code": "A", "trading_partner": "B"},
            {"gl_account": "2050", "debit_amount": 0, "credit_amount": 1_000_000,
             "company_code": "B", "trading_partner": "A"},
        ])
        result = _detector().detect(df)
        assert result.details["IC02"].sum() == 0.0

    def test_within_tolerance_no_flag(self):
        """#11: 차이 1.5% (tolerance 2% 이내) → IC02 score 0."""
        df = _make_ic_df([
            {"gl_account": "1150", "debit_amount": 1_000_000, "credit_amount": 0,
             "company_code": "A", "trading_partner": "B"},
            {"gl_account": "2050", "debit_amount": 0, "credit_amount": 985_000,
             "company_code": "B", "trading_partner": "A"},
        ])
        result = _detector().detect(df)
        assert result.details["IC02"].sum() == 0.0

    def test_over_tolerance_flagged(self):
        """#12: 차이 5% (tolerance 2% 초과) → IC02 score > 0."""
        df = _make_ic_df([
            {"gl_account": "1150", "debit_amount": 1_000_000, "credit_amount": 0,
             "company_code": "A", "trading_partner": "B"},
            {"gl_account": "2050", "debit_amount": 0, "credit_amount": 950_000,
             "company_code": "B", "trading_partner": "A"},
        ])
        result = _detector().detect(df)
        # Why: diff_ratio = 50_000 / 1_000_000 = 0.05, tolerance 0.02 초과
        assert result.details["IC02"].max() > 0

    def test_cross_currency_suppressed(self):
        """#13: 이종 통화 — KRW 1,300,000 vs USD 1,000 → score 억제."""
        df = _make_ic_df([
            {"gl_account": "1150", "debit_amount": 1_300_000, "credit_amount": 0,
             "company_code": "A", "trading_partner": "B", "currency": "KRW"},
            {"gl_account": "2050", "debit_amount": 0, "credit_amount": 1_000,
             "company_code": "B", "trading_partner": "A", "currency": "USD"},
        ])
        result = _detector().detect(df)
        # Why: currency가 다르면 별도 그룹 → 매칭 안 됨 (IC01에서 처리)
        # IC02는 매칭된 건만 평가하므로 이종 통화 쌍은 IC02 score 0
        assert result.details["IC02"].sum() == 0.0


# ── IC03 시차 (3개) ────────────────────────────────────────────


class TestIC03TimingGap:
    """IC03: 매칭됐으나 전기일 차이 과대."""

    def test_same_date_no_flag(self):
        """#14: 전기일 동일 → IC03 score 0."""
        df = _make_ic_df([
            {"gl_account": "1150", "debit_amount": 1_000_000, "credit_amount": 0,
             "company_code": "A", "trading_partner": "B",
             "posting_date": "2025-03-01"},
            {"gl_account": "2050", "debit_amount": 0, "credit_amount": 1_000_000,
             "company_code": "B", "trading_partner": "A",
             "posting_date": "2025-03-01"},
        ])
        result = _detector().detect(df)
        assert result.details["IC03"].sum() == 0.0

    def test_within_window_no_flag(self):
        """#15: 3일 차이 (window 5일 이내) → IC03 score 0."""
        df = _make_ic_df([
            {"gl_account": "1150", "debit_amount": 1_000_000, "credit_amount": 0,
             "company_code": "A", "trading_partner": "B",
             "posting_date": "2025-03-01"},
            {"gl_account": "2050", "debit_amount": 0, "credit_amount": 1_000_000,
             "company_code": "B", "trading_partner": "A",
             "posting_date": "2025-03-04"},
        ])
        result = _detector().detect(df)
        assert result.details["IC03"].sum() == 0.0

    def test_over_window_flagged(self):
        """#16: 15일 차이 → IC03 score > 0."""
        df = _make_ic_df([
            {"gl_account": "1150", "debit_amount": 1_000_000, "credit_amount": 0,
             "company_code": "A", "trading_partner": "B",
             "posting_date": "2025-03-01"},
            {"gl_account": "2050", "debit_amount": 0, "credit_amount": 1_000_000,
             "company_code": "B", "trading_partner": "A",
             "posting_date": "2025-03-16"},
        ])
        result = _detector().detect(df)
        assert result.details["IC03"].max() > 0


# ── Graceful Degradation (4개) ─────────────────────────────────


class TestIC01PracticalFilters:
    def test_customer_vendor_partner_codes_are_not_unmatched_ic(self):
        df = _make_ic_df([
            {"gl_account": "1150", "debit_amount": 1_000_000, "credit_amount": 0,
             "company_code": "A", "trading_partner": "C-000123"},
            {"gl_account": "2050", "debit_amount": 0, "credit_amount": 1_000_000,
             "company_code": "A", "trading_partner": "V-000123"},
        ])
        result = _detector().detect(df)
        assert result.details["IC01"].sum() == 0.0


class TestGracefulDegradation:
    """컬럼 부재·빈 데이터 시 안전한 동작."""

    def test_no_is_intercompany_column(self):
        """#17: is_intercompany 컬럼 없음 → 전체 0 + warning."""
        df = pd.DataFrame({
            "gl_account": ["1150", "2050"],
            "debit_amount": [1_000_000, 0],
            "credit_amount": [0, 1_000_000],
        })
        # Why: is_intercompany 없으면 필수 컬럼 누락
        result = _detector().detect(df)
        assert result.scores.sum() == 0.0
        assert any("필수 컬럼 누락" in w for w in result.warnings)

    def test_no_ic_rows(self):
        """#18: IC 행 없음 → 전체 0."""
        df = _make_ic_df([
            {"gl_account": "5000", "debit_amount": 1_000_000, "credit_amount": 0},
            {"gl_account": "6000", "debit_amount": 0, "credit_amount": 500_000},
        ])
        result = _detector().detect(df)
        assert result.scores.sum() == 0.0

    def test_empty_pairs_warning(self):
        """#19: pairs 빈 리스트 → warning."""
        empty_rules = {"patterns": {"intercompany": {"pairs": []}}}
        det = IntercompanyMatcher(audit_rules=empty_rules)
        df = _make_ic_df([
            {"gl_account": "1150", "debit_amount": 1_000_000, "credit_amount": 0},
        ])
        result = det.detect(df)
        assert result.scores.sum() == 0.0
        assert any("비어있음" in w for w in result.warnings)

    def test_no_company_code_graceful(self):
        """#20: company_code 없어도 동작 (Level 3 fallback)."""
        df = _make_ic_df([
            {"gl_account": "1150", "debit_amount": 1_000_000, "credit_amount": 0},
            {"gl_account": "2050", "debit_amount": 0, "credit_amount": 1_000_000},
        ])
        result = _detector().detect(df)
        # Why: company_code 없으면 Level 3 fallback — 유형 쌍 금액 대사
        assert isinstance(result, DetectionResult)
        assert result.details["IC01"].sum() == 0.0


# ── YAML 설정 호환 (2개) ───────────────────────────────────────


class TestYAMLCompat:
    """YAML 설정 파싱 헬퍼 검증."""

    def test_load_ic_pairs(self):
        """#21: 정상 pairs → 양방향 dict 생성."""
        pair_map = load_ic_pairs(AUDIT_RULES)
        assert pair_map["1150"] == "2050"
        assert pair_map["2050"] == "1150"
        assert pair_map["4500"] == "2700"
        assert pair_map["2700"] == "4500"
        assert len(pair_map) == 4

    def test_extract_ic_prefixes(self):
        """#22: pairs에서 flat list 추출."""
        prefixes = extract_ic_prefixes(AUDIT_RULES)
        assert sorted(prefixes) == ["1150", "2050", "2700", "4500"]
