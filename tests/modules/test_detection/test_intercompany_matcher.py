"""IntercompanyMatcher 단위 테스트 — WU-07 내부거래 매칭 탐지기.

24개 테스트: Basic(3) + IC01(6) + IC02(6) + IC03(3) + Graceful(4) + YAML(2)
"""

from __future__ import annotations

import pandas as pd

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
            "partner_format": {
                "ic_partner_regex": r"^[A-Za-z]\d{3}$|^[A-Za-z]$",
                "customer_partner_regex": r"^C-\d+$",
                "vendor_partner_regex": r"^V-\d+$",
            },
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


def _detector_min_rows_1(**kwargs) -> IntercompanyMatcher:
    """ic_min_ic_rows=1 로 단일 IC 행 fixture 검증 가능하게 함."""
    from config.settings import AuditSettings

    settings = AuditSettings(ic_min_ic_rows=1)
    return IntercompanyMatcher(settings=settings, audit_rules=AUDIT_RULES, **kwargs)


# ── Basic (3개) ────────────────────────────────────────────────


class TestBasic:
    """기본 인터페이스 검증."""

    def test_track_name(self):
        """#1: track_name은 'intercompany'."""
        det = _detector()
        assert det.track_name == "intercompany"

    def test_returns_detection_result(self):
        """#2: detect() 반환 타입은 DetectionResult."""
        df = _make_ic_df(
            [
                {
                    "gl_account": "1150",
                    "debit_amount": 1_000_000,
                    "credit_amount": 0,
                    "company_code": "A",
                    "trading_partner": "B",
                },
                {
                    "gl_account": "2050",
                    "debit_amount": 0,
                    "credit_amount": 1_000_000,
                    "company_code": "B",
                    "trading_partner": "A",
                },
            ]
        )
        result = _detector().detect(df)
        assert isinstance(result, DetectionResult)
        assert result.track_name == "intercompany"

    def test_scores_range(self):
        """#3: scores 범위 0.0~1.0."""
        df = _make_ic_df(
            [
                {
                    "gl_account": "1150",
                    "debit_amount": 1_000_000,
                    "credit_amount": 0,
                    "company_code": "A",
                    "trading_partner": "B",
                },
                {
                    "gl_account": "2050",
                    "debit_amount": 0,
                    "credit_amount": 1_000_000,
                    "company_code": "B",
                    "trading_partner": "A",
                },
                {"gl_account": "5000", "debit_amount": 500_000, "credit_amount": 0},  # 비IC
            ]
        )
        result = _detector().detect(df)
        assert result.scores.min() >= 0.0
        assert result.scores.max() <= 1.0


# ── IC01 미매칭 (6개) ──────────────────────────────────────────


class TestIC01Unmatched:
    """IC01: 미매칭 내부거래 탐지."""

    def test_matched_pair_score_zero(self):
        """#4: A→B receivable + B→A payable 매칭 → IC01 score 0."""
        df = _make_ic_df(
            [
                {
                    "gl_account": "1150",
                    "debit_amount": 1_000_000,
                    "credit_amount": 0,
                    "company_code": "A",
                    "trading_partner": "B",
                },
                {
                    "gl_account": "2050",
                    "debit_amount": 0,
                    "credit_amount": 1_000_000,
                    "company_code": "B",
                    "trading_partner": "A",
                },
            ]
        )
        result = _detector().detect(df)
        assert "IC01" in result.details.columns
        assert result.details["IC01"].sum() == 0.0

    def test_unmatched_ic_flagged(self):
        """#5: receivable만 존재, payable 없음 → IC01 score > 0."""
        df = _make_ic_df(
            [
                {
                    "gl_account": "1150",
                    "debit_amount": 1_000_000,
                    "credit_amount": 0,
                    "company_code": "A",
                    "trading_partner": "B",
                },
                {
                    "gl_account": "1150",
                    "debit_amount": 500_000,
                    "credit_amount": 0,
                    "company_code": "A",
                    "trading_partner": "B",
                },
                {"gl_account": "5000", "debit_amount": 500_000, "credit_amount": 0},  # 비IC
            ]
        )
        result = _detector().detect(df)
        assert result.details["IC01"].iloc[0] > 0  # IC 행 flagged

    def test_n_to_m_matching(self):
        """#6: N:M 매칭 — A사 3건 소액 vs B사 1건 통합 → 합계 일치 시 score 0."""
        df = _make_ic_df(
            [
                # A사: 3건 × 100만원 = 300만원 receivable
                {
                    "gl_account": "1150",
                    "debit_amount": 1_000_000,
                    "credit_amount": 0,
                    "company_code": "A",
                    "trading_partner": "B",
                },
                {
                    "gl_account": "1150",
                    "debit_amount": 1_000_000,
                    "credit_amount": 0,
                    "company_code": "A",
                    "trading_partner": "B",
                },
                {
                    "gl_account": "1150",
                    "debit_amount": 1_000_000,
                    "credit_amount": 0,
                    "company_code": "A",
                    "trading_partner": "B",
                },
                # B사: 1건 300만원 payable
                {
                    "gl_account": "2050",
                    "debit_amount": 0,
                    "credit_amount": 3_000_000,
                    "company_code": "B",
                    "trading_partner": "A",
                },
            ]
        )
        result = _detector().detect(df)
        # Why: 그룹 합계 일치 → IC01 전체 0
        assert result.details["IC01"].sum() == 0.0

    def test_trading_partner_null_fallback(self):
        """#7: trading_partner NULL → company_code 쌍 집계로 매칭."""
        df = _make_ic_df(
            [
                {
                    "gl_account": "1150",
                    "debit_amount": 1_000_000,
                    "credit_amount": 0,
                    "company_code": "A",
                },
                {
                    "gl_account": "2050",
                    "debit_amount": 0,
                    "credit_amount": 1_000_000,
                    "company_code": "B",
                },
            ]
        )
        result = _detector().detect(df)
        # Why: company_code만으로 aggregate 매칭
        assert isinstance(result, DetectionResult)

    def test_single_company_code_fallback(self):
        """#8: company_code 단일값 → IC 계정유형 쌍 금액 대사."""
        df = _make_ic_df(
            [
                {
                    "gl_account": "1150",
                    "debit_amount": 1_000_000,
                    "credit_amount": 0,
                    "company_code": "A",
                },
                {
                    "gl_account": "2050",
                    "debit_amount": 0,
                    "credit_amount": 1_000_000,
                    "company_code": "A",
                },
            ]
        )
        result = _detector().detect(df)
        # Why: Level 3 fallback — receivable sum == payable sum → 매칭
        assert result.details["IC01"].sum() == 0.0

    def test_non_ic_rows_zero_score(self):
        """#9: 비 IC 행은 항상 score 0."""
        df = _make_ic_df(
            [
                {
                    "gl_account": "1150",
                    "debit_amount": 1_000_000,
                    "credit_amount": 0,
                    "company_code": "A",
                    "trading_partner": "B",
                },
                {
                    "gl_account": "2050",
                    "debit_amount": 0,
                    "credit_amount": 1_000_000,
                    "company_code": "B",
                    "trading_partner": "A",
                },
                {"gl_account": "5000", "debit_amount": 500_000, "credit_amount": 0},  # 비IC
            ]
        )
        result = _detector().detect(df)
        assert result.scores.iloc[2] == 0.0


# ── IC02 금액 불일치 (6개) ─────────────────────────────────────


class TestIC02AmountMismatch:
    """IC02: 매칭됐으나 금액 차이 초과."""

    def test_exact_match_no_flag(self):
        """#10: 금액 정확 일치 → IC02 score 0."""
        df = _make_ic_df(
            [
                {
                    "gl_account": "1150",
                    "debit_amount": 1_000_000,
                    "credit_amount": 0,
                    "company_code": "A",
                    "trading_partner": "B",
                },
                {
                    "gl_account": "2050",
                    "debit_amount": 0,
                    "credit_amount": 1_000_000,
                    "company_code": "B",
                    "trading_partner": "A",
                },
            ]
        )
        result = _detector().detect(df)
        assert result.details["IC02"].sum() == 0.0

    def test_within_tolerance_no_flag(self):
        """#11: 차이 1.5% (tolerance 5% 이내) → IC02 score 0."""
        df = _make_ic_df(
            [
                {
                    "gl_account": "1150",
                    "debit_amount": 1_000_000,
                    "credit_amount": 0,
                    "company_code": "A",
                    "trading_partner": "B",
                },
                {
                    "gl_account": "2050",
                    "debit_amount": 0,
                    "credit_amount": 985_000,
                    "company_code": "B",
                    "trading_partner": "A",
                },
            ]
        )
        result = _detector().detect(df)
        assert result.details["IC02"].sum() == 0.0

    def test_boundary_tolerance_no_flag(self):
        """#12: 차이 5% (tolerance 5% 경계) → IC02 score 0."""
        df = _make_ic_df(
            [
                {
                    "gl_account": "1150",
                    "debit_amount": 1_000_000,
                    "credit_amount": 0,
                    "company_code": "A",
                    "trading_partner": "B",
                },
                {
                    "gl_account": "2050",
                    "debit_amount": 0,
                    "credit_amount": 950_000,
                    "company_code": "B",
                    "trading_partner": "A",
                },
            ]
        )
        result = _detector().detect(df)
        # Why: diff_ratio = 50_000 / 1_000_000 = 0.05, tolerance 0.05 이내
        assert result.details["IC02"].sum() == 0.0

    def test_over_tolerance_flagged(self):
        """#12b: 차이 6% (tolerance 5% 초과) → IC02 score > 0."""
        df = _make_ic_df(
            [
                {
                    "gl_account": "1150",
                    "debit_amount": 1_000_000,
                    "credit_amount": 0,
                    "company_code": "A",
                    "trading_partner": "B",
                },
                {
                    "gl_account": "2050",
                    "debit_amount": 0,
                    "credit_amount": 940_000,
                    "company_code": "B",
                    "trading_partner": "A",
                },
            ]
        )
        result = _detector().detect(df)
        assert result.details["IC02"].max() > 0

    def test_cross_currency_suppressed(self):
        """#13: 이종 통화 — KRW 1,300,000 vs USD 1,000 → score 억제."""
        df = _make_ic_df(
            [
                {
                    "gl_account": "1150",
                    "debit_amount": 1_300_000,
                    "credit_amount": 0,
                    "company_code": "A",
                    "trading_partner": "B",
                    "currency": "KRW",
                },
                {
                    "gl_account": "2050",
                    "debit_amount": 0,
                    "credit_amount": 1_000,
                    "company_code": "B",
                    "trading_partner": "A",
                    "currency": "USD",
                },
            ]
        )
        result = _detector().detect(df)
        # Why: currency가 달라도 대응 관계는 인식하되, FX 기준 없이는 IC02 점수 억제
        assert result.details["IC02"].sum() == 0.0
        assert result.details["IC01"].sum() == 0.0

    def test_extreme_amount_ratio_suppressed_without_currency(self):
        """#13b: 통화 컬럼이 없어도 20x 초과 금액비는 FX 의심으로 IC02 억제."""
        df = _make_ic_df(
            [
                {
                    "gl_account": "1150",
                    "debit_amount": 1_300_000,
                    "credit_amount": 0,
                    "company_code": "A",
                    "trading_partner": "B",
                },
                {
                    "gl_account": "2050",
                    "debit_amount": 0,
                    "credit_amount": 1_000,
                    "company_code": "B",
                    "trading_partner": "A",
                },
            ]
        )
        result = _detector().detect(df)
        assert result.details["IC02"].sum() == 0.0
        assert result.details["IC01"].sum() == 0.0


# ── IC03 시차 (3개) ────────────────────────────────────────────


class TestIC03TimingGap:
    """IC03: 매칭됐으나 전기일 차이 과대."""

    def test_same_date_no_flag(self):
        """#14: 전기일 동일 → IC03 score 0."""
        df = _make_ic_df(
            [
                {
                    "gl_account": "1150",
                    "debit_amount": 1_000_000,
                    "credit_amount": 0,
                    "company_code": "A",
                    "trading_partner": "B",
                    "posting_date": "2025-03-01",
                },
                {
                    "gl_account": "2050",
                    "debit_amount": 0,
                    "credit_amount": 1_000_000,
                    "company_code": "B",
                    "trading_partner": "A",
                    "posting_date": "2025-03-01",
                },
            ]
        )
        result = _detector().detect(df)
        assert result.details["IC03"].sum() == 0.0

    def test_within_window_no_flag(self):
        """#15: 3일 차이 (window 5일 이내) → IC03 score 0."""
        df = _make_ic_df(
            [
                {
                    "gl_account": "1150",
                    "debit_amount": 1_000_000,
                    "credit_amount": 0,
                    "company_code": "A",
                    "trading_partner": "B",
                    "posting_date": "2025-03-01",
                },
                {
                    "gl_account": "2050",
                    "debit_amount": 0,
                    "credit_amount": 1_000_000,
                    "company_code": "B",
                    "trading_partner": "A",
                    "posting_date": "2025-03-04",
                },
            ]
        )
        result = _detector().detect(df)
        assert result.details["IC03"].sum() == 0.0

    def test_over_window_flagged(self):
        """#16: 15일 차이 → IC03 score > 0."""
        df = _make_ic_df(
            [
                {
                    "gl_account": "1150",
                    "debit_amount": 1_000_000,
                    "credit_amount": 0,
                    "company_code": "A",
                    "trading_partner": "B",
                    "posting_date": "2025-03-01",
                },
                {
                    "gl_account": "2050",
                    "debit_amount": 0,
                    "credit_amount": 1_000_000,
                    "company_code": "B",
                    "trading_partner": "A",
                    "posting_date": "2025-03-16",
                },
            ]
        )
        result = _detector().detect(df)
        assert result.details["IC03"].max() > 0


# ── Graceful Degradation (4개) ─────────────────────────────────


class TestIC01PracticalFilters:
    def test_customer_vendor_partner_codes_are_not_unmatched_ic(self):
        df = _make_ic_df(
            [
                {
                    "gl_account": "1150",
                    "debit_amount": 1_000_000,
                    "credit_amount": 0,
                    "company_code": "A",
                    "trading_partner": "C-000123",
                },
                {
                    "gl_account": "2050",
                    "debit_amount": 0,
                    "credit_amount": 1_000_000,
                    "company_code": "A",
                    "trading_partner": "V-000123",
                },
            ]
        )
        result = _detector().detect(df)
        assert result.details["IC01"].sum() == 0.0


class TestGracefulDegradation:
    """컬럼 부재·빈 데이터 시 안전한 동작."""

    def test_no_is_intercompany_column(self):
        """#17: is_intercompany 컬럼 없음 → GL prefix 로 graceful 추론."""
        df = pd.DataFrame(
            {
                "gl_account": ["1150", "2050"],
                "debit_amount": [1_000_000, 0],
                "credit_amount": [0, 1_000_000],
            }
        )
        result = _detector().detect(df)
        # company/document evidence 가 부족해 점수는 0이어도 matcher 자체는 실행된다.
        assert result.scores.sum() == 0.0
        assert not any("필수 컬럼 누락" in w for w in result.warnings)

    def test_no_ic_rows(self):
        """#18: IC 행 없음 → 전체 0."""
        df = _make_ic_df(
            [
                {"gl_account": "5000", "debit_amount": 1_000_000, "credit_amount": 0},
                {"gl_account": "6000", "debit_amount": 0, "credit_amount": 500_000},
            ]
        )
        result = _detector().detect(df)
        assert result.scores.sum() == 0.0

    def test_empty_pairs_warning(self):
        """#19: pairs 빈 리스트 → warning."""
        empty_rules = {"patterns": {"intercompany": {"pairs": []}}}
        det = IntercompanyMatcher(audit_rules=empty_rules)
        df = _make_ic_df(
            [
                {"gl_account": "1150", "debit_amount": 1_000_000, "credit_amount": 0},
            ]
        )
        result = det.detect(df)
        assert result.scores.sum() == 0.0
        assert any("비어있음" in w for w in result.warnings)

    def test_no_company_code_graceful(self):
        """#20: company_code 없어도 동작 (Level 3 fallback)."""
        df = _make_ic_df(
            [
                {"gl_account": "1150", "debit_amount": 1_000_000, "credit_amount": 0},
                {"gl_account": "2050", "debit_amount": 0, "credit_amount": 1_000_000},
            ]
        )
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


# ── IC01 fitting 의존성 회피 (T-P5-1) ──────────────────────────


class TestIC01NoFittingDependency:
    """D065 supersede 검증 — DataSynth v38 patch signature 의존성 제거."""

    @staticmethod
    def _sidecar(result, col: str) -> pd.Series:
        return result.metadata["row_sidecar"][col]

    def test_unmatched_without_unmatched_suffix(self):
        """#23: trading_partner=C999 (master 외부, -UNMATCHED 접미사 없음) → IC01 high."""
        df = _make_ic_df(
            [
                {
                    "gl_account": "1150",
                    "debit_amount": 1_000_000,
                    "credit_amount": 0,
                    "company_code": "A001",
                    "trading_partner": "C999",
                },
            ]
        )
        result = _detector_min_rows_1().detect(df)
        assert result.details["IC01"].iloc[0] > 0
        assert self._sidecar(result, "ic01_evidence_level").iloc[0] == "high"

    def test_unmatched_with_unmatched_suffix_no_special_weight(self):
        """#24: -UNMATCHED 접미사가 더 이상 특별 가중치를 받지 않음.

        D065 이전: endswith('-UNMATCHED') 휴리스틱이 high-confidence 부여.
        D065 이후: nonstandard_format 으로 분류되어 review 만 부여.
        review 신호는 IC01 details score 가 0 (sidecar metadata 만 노출).
        """
        df = _make_ic_df(
            [
                {
                    "gl_account": "1150",
                    "debit_amount": 1_000_000,
                    "credit_amount": 0,
                    "company_code": "A001",
                    "trading_partner": "C001-UNMATCHED",
                },
            ]
        )
        result = _detector_min_rows_1().detect(df)
        assert result.details["IC01"].iloc[0] == 0.0
        assert self._sidecar(result, "ic01_evidence_level").iloc[0] == "review"
        assert self._sidecar(result, "ic01_review_reason").iloc[0] == "nonstandard_format"


# ── IC01 evidence level 분류 (T-P5-2) ──────────────────────────


class TestIC01EvidenceLevelClassification:
    """IC01 high / review / 제외 3분류 검증."""

    @staticmethod
    def _sidecar(result, col: str) -> pd.Series:
        return result.metadata["row_sidecar"][col]

    def test_evidence_high_master_absent(self):
        """#25: master 외부 회사코드 (C999) → high + score 1.0 양수."""
        df = _make_ic_df(
            [
                {
                    "gl_account": "1150",
                    "debit_amount": 1_000_000,
                    "credit_amount": 0,
                    "company_code": "A001",
                    "trading_partner": "C999",
                },
            ]
        )
        result = _detector_min_rows_1().detect(df)
        # high evidence 만 IC01 details 양수 (flagged_rules 격상 대상)
        assert result.details["IC01"].iloc[0] > 0
        assert self._sidecar(result, "ic01_evidence_level").iloc[0] == "high"
        assert self._sidecar(result, "ic01_review_reason").iloc[0] == ""

    def test_evidence_review_missing_partner(self):
        """#26: trading_partner 결측 → review + score 0 (sidecar 만).

        D065 + AGENTS.md: review-only 신호는 confirmed violation 으로 흐르면 안 됨.
        IC01 details 양수는 high 만, review 는 sidecar (metadata) 로만 노출.
        """
        df = _make_ic_df(
            [
                {
                    "gl_account": "1150",
                    "debit_amount": 1_000_000,
                    "credit_amount": 0,
                    "company_code": "A001",
                    "trading_partner": "",
                },
            ]
        )
        result = _detector_min_rows_1().detect(df)
        assert result.details["IC01"].iloc[0] == 0.0
        assert self._sidecar(result, "ic01_evidence_level").iloc[0] == "review"
        assert self._sidecar(result, "ic01_review_reason").iloc[0] == "missing_partner"

    def test_evidence_review_invalid_format(self):
        """#27: trading_partner=xyz (regex 비매칭) → review + score 0 (sidecar 만)."""
        df = _make_ic_df(
            [
                {
                    "gl_account": "1150",
                    "debit_amount": 1_000_000,
                    "credit_amount": 0,
                    "company_code": "A001",
                    "trading_partner": "xyz",
                },
            ]
        )
        result = _detector_min_rows_1().detect(df)
        assert result.details["IC01"].iloc[0] == 0.0
        assert self._sidecar(result, "ic01_evidence_level").iloc[0] == "review"
        assert self._sidecar(result, "ic01_review_reason").iloc[0] == "nonstandard_format"

    def test_excluded_customer_code(self):
        """#28: trading_partner=C-000123 (customer 형식) → IC01 score 0 + level 빈문자열."""
        df = _make_ic_df(
            [
                {
                    "gl_account": "1150",
                    "debit_amount": 1_000_000,
                    "credit_amount": 0,
                    "company_code": "A001",
                    "trading_partner": "C-000123",
                },
            ]
        )
        result = _detector_min_rows_1().detect(df)
        assert result.details["IC01"].iloc[0] == 0.0
        assert self._sidecar(result, "ic01_evidence_level").iloc[0] == ""

    def test_excluded_vendor_code(self):
        """#29: trading_partner=V-000123 (vendor 형식) → IC01 score 0 + level 빈문자열."""
        df = _make_ic_df(
            [
                {
                    "gl_account": "1150",
                    "debit_amount": 1_000_000,
                    "credit_amount": 0,
                    "company_code": "A001",
                    "trading_partner": "V-000123",
                },
            ]
        )
        result = _detector_min_rows_1().detect(df)
        assert result.details["IC01"].iloc[0] == 0.0
        assert self._sidecar(result, "ic01_evidence_level").iloc[0] == ""


# ── PHASE2 internal probabilistic reconciliation (additive) ────


_PROB_COLS = ("ic_unmatched_prob", "ic_amount_prob", "ic_timing_prob")


def _make_ic_pair(
    *,
    rec_amount: float = 1_000_000,
    pay_amount: float = 1_000_000,
    rec_date: str = "2025-03-01",
    pay_date: str = "2025-03-01",
    rec_partner: str = "B001",
    pay_partner: str = "A001",
    rec_company: str = "A001",
    pay_company: str = "B001",
    rec_reference: str | None = None,
    pay_reference: str | None = None,
    rec_currency: str | None = None,
    pay_currency: str | None = None,
) -> pd.DataFrame:
    """Build a 2-row IC pair (receivable + payable) for probabilistic tests."""
    rec: dict = {
        "gl_account": "1150",
        "debit_amount": rec_amount,
        "credit_amount": 0,
        "company_code": rec_company,
        "trading_partner": rec_partner,
        "posting_date": rec_date,
    }
    pay: dict = {
        "gl_account": "2050",
        "debit_amount": 0,
        "credit_amount": pay_amount,
        "company_code": pay_company,
        "trading_partner": pay_partner,
        "posting_date": pay_date,
    }
    if rec_reference is not None:
        rec["reference"] = rec_reference
    if pay_reference is not None:
        pay["reference"] = pay_reference
    if rec_currency is not None:
        rec["currency"] = rec_currency
    if pay_currency is not None:
        pay["currency"] = pay_currency
    return _make_ic_df([rec, pay])


class TestProbabilisticReconciliation:
    """PHASE2 internal probabilistic surface — IC01~03 보존 + 신규 prob column."""

    def test_columns_present(self):
        df = _make_ic_pair()
        result = _detector().detect(df)
        for col in _PROB_COLS:
            assert col in result.details.columns

    def test_matched_pair_low_unmatched_prob(self):
        """완전 일치 pair → ic_unmatched_prob ≤ 0.05."""
        df = _make_ic_pair(rec_reference="INV-1001", pay_reference="INV-1001")
        result = _detector().detect(df)
        assert result.details["ic_unmatched_prob"].max() <= 0.05

    def test_affiliate_counterparty_columns_used_when_trading_partner_absent(self):
        """trading_partner shortcut 없이 affiliate/counterparty symmetry 로 IC pair 매칭."""
        df = _make_ic_df(
            [
                {
                    "gl_account": "1150",
                    "debit_amount": 1_000_000,
                    "credit_amount": 0,
                    "company_code": "A001",
                    "affiliate": "B001",
                    "posting_date": "2025-03-01",
                    "reference": "INV-ALT-1",
                },
                {
                    "gl_account": "2050",
                    "debit_amount": 0,
                    "credit_amount": 1_000_000,
                    "company_code": "B001",
                    "counterparty": "A001",
                    "posting_date": "2025-03-01",
                    "reference": "INV-ALT-1",
                },
            ]
        )
        result = _detector().detect(df)

        assert result.details["IC01"].sum() == 0.0
        assert result.details["ic_unmatched_prob"].max() <= 0.05

    def test_no_counterpart_under_l2_capped_to_no_candidate_cap(self):
        """receivable 만 존재 + L2 tier (reference 없음) → ic_unmatched_prob ≤ no_candidate_l2 cap.

        semantics change (2026-05-24): no_candidate 가 1.0 hard signal 로 들어가면 정상
        단방향 거래 / matching evidence 부족 case 가 PHASE2 TOP 구간을 오염시킨다.
        contract tier × cp_block 기반 cap 으로 weak review 로 격하한다.
        """
        df = _make_ic_df(
            [
                {
                    "gl_account": "1150",
                    "debit_amount": 1_000_000,
                    "credit_amount": 0,
                    "company_code": "A001",
                    "trading_partner": "B001",
                    "posting_date": "2025-03-01",
                },
                {
                    "gl_account": "1150",
                    "debit_amount": 500_000,
                    "credit_amount": 0,
                    "company_code": "A001",
                    "trading_partner": "B001",
                    "posting_date": "2025-03-02",
                },
                # B 법인 payable 행 없음. cc multi 충족을 위해 비-IC 행으로 cc 확보.
                {
                    "gl_account": "5000",
                    "debit_amount": 100,
                    "credit_amount": 0,
                    "company_code": "B001",
                    "trading_partner": "A001",
                    "posting_date": "2025-03-01",
                },
            ]
        )
        result = _detector().detect(df)
        ic_rows = df[df["is_intercompany"].fillna(False)].index
        # L2 + no_candidate cap (audit_rules.yaml default 0.3) 이하
        assert (result.details.loc[ic_rows, "ic_unmatched_prob"] <= 0.3 + 1e-9).all()
        # 여전히 양수 (review signal 보존)
        assert (result.details.loc[ic_rows, "ic_unmatched_prob"] > 0).all()
        # mismatch evidence 없음 → amount/timing_prob 는 0
        assert (result.details.loc[ic_rows, "ic_amount_prob"] == 0).all()
        assert (result.details.loc[ic_rows, "ic_timing_prob"] == 0).all()

    def test_amount_mismatch_prob_monotonic(self):
        """금액 차이 클수록 ic_amount_prob 단조 증가."""
        prob_close = (
            _detector()
            .detect(_make_ic_pair(rec_amount=1_000_000, pay_amount=990_000))
            .details["ic_amount_prob"]
            .max()
        )
        prob_far = (
            _detector()
            .detect(_make_ic_pair(rec_amount=1_000_000, pay_amount=500_000))
            .details["ic_amount_prob"]
            .max()
        )
        assert prob_far > prob_close

    def test_timing_gap_prob_monotonic(self):
        """일자 차이 클수록 ic_timing_prob 단조 증가."""
        prob_close = (
            _detector()
            .detect(_make_ic_pair(rec_date="2025-03-01", pay_date="2025-03-02"))
            .details["ic_timing_prob"]
            .max()
        )
        prob_far = (
            _detector()
            .detect(_make_ic_pair(rec_date="2025-03-01", pay_date="2025-03-25"))
            .details["ic_timing_prob"]
            .max()
        )
        assert prob_far > prob_close

    def test_reference_similarity_reduces_unmatched(self):
        """동일 reference → ic_unmatched_prob 가 reference 없는 경우보다 감소."""
        with_ref = (
            _detector()
            .detect(_make_ic_pair(rec_reference="INV-2025-001", pay_reference="INV-2025-001"))
            .details["ic_unmatched_prob"]
            .max()
        )
        without_ref = _detector().detect(_make_ic_pair()).details["ic_unmatched_prob"].max()
        assert with_ref <= without_ref

    def test_short_reference_treated_as_empty(self):
        """양측 reference 길이 < min_length (3) → reference term 0."""
        result_short = _detector().detect(_make_ic_pair(rec_reference="x", pay_reference="x"))
        result_no_ref = _detector().detect(_make_ic_pair())
        # 짧은 ref 는 무시되므로 ic_unmatched_prob 가 ref 없을 때와 같아야 한다.
        assert (
            abs(
                float(result_short.details["ic_unmatched_prob"].max())
                - float(result_no_ref.details["ic_unmatched_prob"].max())
            )
            < 1e-6
        )

    def test_cross_currency_amount_term_zero(self):
        """cross-currency → amount_similarity=0 → ic_amount_prob ≈ 1.0."""
        df = _make_ic_pair(
            rec_amount=1_000_000,
            pay_amount=1_000_000,
            rec_currency="KRW",
            pay_currency="USD",
        )
        result = _detector().detect(df)
        assert result.details["ic_amount_prob"].max() >= 0.99

    def test_l3_insufficient_single_company_zero_prob(self):
        """company_code 단일 → L3_insufficient, 신규 prob 전 0, 기존 IC01~03 보존."""
        df = _make_ic_df(
            [
                {
                    "gl_account": "1150",
                    "debit_amount": 1_000_000,
                    "credit_amount": 0,
                    "company_code": "A",
                },
                {
                    "gl_account": "2050",
                    "debit_amount": 0,
                    "credit_amount": 1_000_000,
                    "company_code": "A",
                },
            ]
        )
        result = _detector().detect(df)
        for col in _PROB_COLS:
            assert result.details[col].sum() == 0.0
        assert result.metadata["probabilistic_reconciliation"]["contract_tier"] == "L3_insufficient"
        # 기존 IC01 동작 보존 — Level 3 fallback 매칭으로 IC01 sum=0
        assert result.details["IC01"].sum() == 0.0

    def test_l2_aggregate_no_reference(self):
        """reference 없음 → L2_aggregate, prob 정상 산출, weight 재정규화 동작."""
        df = _make_ic_pair()  # reference 컬럼 자체 없음
        result = _detector().detect(df)
        assert result.metadata["probabilistic_reconciliation"]["contract_tier"] == "L2_aggregate"
        # weight 재정규화 후에도 매칭 시 unmatched_prob 낮음
        assert result.details["ic_unmatched_prob"].max() < 0.5

    def test_metadata_summary_keys(self):
        """metadata["probabilistic_reconciliation"] 필수 키 노출."""
        df = _make_ic_pair(rec_reference="INV-1", pay_reference="INV-1")
        result = _detector().detect(df)
        meta = result.metadata["probabilistic_reconciliation"]
        for key in (
            "contract_tier",
            "missing_reasons",
            "pair_candidate_count",
            "capped",
            "warnings",
            "weights",
            "params",
        ):
            assert key in meta
        weights = meta["weights"]
        assert abs(sum(weights.values()) - 1.0) < 1e-6

    def test_phase1_columns_do_not_influence(self):
        """flagged_rules / priority_score / is_fraud 주입해도 prob 결과 동일."""
        base = _make_ic_pair()
        injected = base.copy()
        injected["flagged_rules"] = "L1-05,L3-04"
        injected["priority_score"] = 0.95
        injected["is_fraud"] = True
        injected["mutation_kind"] = "embezzlement"
        baseline = _detector().detect(base).details[list(_PROB_COLS)]
        polluted = _detector().detect(injected).details[list(_PROB_COLS)]
        pd.testing.assert_frame_equal(
            baseline.reset_index(drop=True),
            polluted.reset_index(drop=True),
            check_like=True,
        )

    def test_ic01_sidecar_preserved(self):
        """IC01 sidecar (evidence_level / review_reason) 키 보존."""
        df = _make_ic_pair(rec_reference="INV-1", pay_reference="INV-1")
        result = _detector().detect(df)
        assert "ic01_evidence_level" in result.metadata["row_sidecar"]
        assert "ic01_review_reason" in result.metadata["row_sidecar"]

    def test_scores_combine_with_prob(self):
        """DetectionResult.scores 가 prob column 과 row-wise max 로 결합."""
        df = _make_ic_pair(rec_amount=1_000_000, pay_amount=500_000)
        result = _detector().detect(df)
        # ic_amount_prob 가 양수이므로 scores 도 양수.
        assert result.details["ic_amount_prob"].max() > 0
        assert result.scores.max() >= result.details["ic_amount_prob"].max() - 1e-9

    def test_mixed_reference_pair_level_renormalization(self):
        """L1 tier 인 배치에서 일부 pair 만 reference 가 있을 때, reference 없는 pair 가
        reference weight 0.20 floor 에 묶이지 않고 amount/date/cp 로 재정규화되어
        완전 매칭 시 ic_unmatched_prob ≈ 0 이 되어야 한다 (false-positive 방지).
        """
        df = _make_ic_df(
            [
                # pair 1: reference 양측 동일 (L1 active)
                {
                    "gl_account": "1150",
                    "debit_amount": 1_000_000,
                    "credit_amount": 0,
                    "company_code": "A001",
                    "trading_partner": "B001",
                    "posting_date": "2025-03-01",
                    "reference": "INV-100",
                },
                {
                    "gl_account": "2050",
                    "debit_amount": 0,
                    "credit_amount": 1_000_000,
                    "company_code": "B001",
                    "trading_partner": "A001",
                    "posting_date": "2025-03-01",
                    "reference": "INV-100",
                },
                # pair 2: reference 양측 부재이지만 amount/date/counterparty 완전 매칭
                {
                    "gl_account": "1150",
                    "debit_amount": 2_000_000,
                    "credit_amount": 0,
                    "company_code": "A001",
                    "trading_partner": "C001",
                    "posting_date": "2025-04-15",
                    "reference": "",
                },
                {
                    "gl_account": "2050",
                    "debit_amount": 0,
                    "credit_amount": 2_000_000,
                    "company_code": "C001",
                    "trading_partner": "A001",
                    "posting_date": "2025-04-15",
                    "reference": "",
                },
            ]
        )
        result = _detector().detect(df)
        # batch 전체는 L1_exact 로 분류 (pair 1 의 INV-100 덕에)
        meta = result.metadata["probabilistic_reconciliation"]
        assert meta["contract_tier"] == "L1_exact"
        # 완전 매칭 pair 2 의 양 row 도 unmatched_prob ≤ 0.05 floor 에 묶이지 않아야 한다
        assert float(result.details.loc[2, "ic_unmatched_prob"]) <= 0.05
        assert float(result.details.loc[3, "ic_unmatched_prob"]) <= 0.05
        # reference 있는 pair 1 도 unmatched_prob 낮음 (회귀 확인)
        assert float(result.details.loc[0, "ic_unmatched_prob"]) <= 0.05
        assert float(result.details.loc[1, "ic_unmatched_prob"]) <= 0.05

    def test_no_candidate_under_l1_capped(self):
        """L1 tier (reference 양측 있음) + 후보 없음 → cap = no_candidate_l1 (0.5)."""
        df = _make_ic_df(
            [
                # IC receivable 2건 (ic_min_ic_rows=2 충족) — payable 없음
                {
                    "gl_account": "1150",
                    "debit_amount": 1_000_000,
                    "credit_amount": 0,
                    "company_code": "A001",
                    "trading_partner": "B001",
                    "posting_date": "2025-03-01",
                    "reference": "INV-2025-001",
                },
                {
                    "gl_account": "1150",
                    "debit_amount": 500_000,
                    "credit_amount": 0,
                    "company_code": "A001",
                    "trading_partner": "B001",
                    "posting_date": "2025-03-02",
                    "reference": "INV-2025-002",
                },
                # cc multi 확보용 비-IC 행
                {
                    "gl_account": "5000",
                    "debit_amount": 100,
                    "credit_amount": 0,
                    "company_code": "B001",
                    "trading_partner": "A001",
                    "posting_date": "2025-03-01",
                    "reference": "INV-2025-001",
                },
            ]
        )
        result = _detector().detect(df)
        ic_rows = df[df["is_intercompany"].fillna(False)].index
        # L1_exact + no_candidate → 0.5 cap
        assert (result.details.loc[ic_rows, "ic_unmatched_prob"] <= 0.5 + 1e-9).all()
        assert (result.details.loc[ic_rows, "ic_unmatched_prob"] > 0.3).all()
        meta = result.metadata["probabilistic_reconciliation"]
        assert meta["contract_tier"] == "L1_exact"
        assert meta["no_candidate_count"] >= 2

    def test_weak_cp_block_capped_to_weak_contract(self):
        """cc/tp 모두 비어 cp_block 이 unique tag 인 row → weak_contract cap."""
        df = _make_ic_df(
            [
                # IC row: cp/tp 모두 비어 anchor 부재 → weak cp_block
                {
                    "gl_account": "1150",
                    "debit_amount": 1_000_000,
                    "credit_amount": 0,
                    "company_code": "",
                    "trading_partner": "",
                    "posting_date": "2025-03-01",
                },
                # cc multi 확보를 위한 비-IC 행
                {
                    "gl_account": "5000",
                    "debit_amount": 100,
                    "credit_amount": 0,
                    "company_code": "A",
                    "trading_partner": "B",
                    "posting_date": "2025-03-01",
                },
                {
                    "gl_account": "5000",
                    "debit_amount": 100,
                    "credit_amount": 0,
                    "company_code": "B",
                    "trading_partner": "A",
                    "posting_date": "2025-03-01",
                },
            ]
        )
        result = _detector_min_rows_1().detect(df)
        ic_rows = df[df["is_intercompany"].fillna(False)].index
        # weak_contract cap (default 0.3) 이하
        assert (result.details.loc[ic_rows, "ic_unmatched_prob"] <= 0.3 + 1e-9).all()
        meta = result.metadata["probabilistic_reconciliation"]
        assert meta["weak_contract_count"] >= 1

    def test_candidate_mismatch_can_exceed_no_candidate_cap(self):
        """L1 + candidate mismatch → mismatch_cap (1.0) 까지 강 신호 허용,
        L1 no_candidate (0.5) 보다 명확히 높은 점수 가능.

        후보가 만들어지려면 amount bucket 인접 ±1 안이어야 한다 (factor 2.0 → 최대 4x).
        amount 차이를 그 범위에서 두고 date 와 reference 를 크게 어긋나게 두어
        match_score 가 낮아지고 raw_unmatched 가 L1 no_candidate cap 0.5 를 초과하도록 한다.
        """
        df = _make_ic_pair(
            rec_amount=1_000_000,
            pay_amount=300_000,  # bucket 19 vs 18 (±1 join 안)
            rec_reference="INVA",  # length 4 → effective
            pay_reference="INVB",  # 다른 token
            rec_date="2025-03-01",
            pay_date="2025-03-31",  # max_day_diff(30) 경계
        )
        result = _detector().detect(df)
        meta = result.metadata["probabilistic_reconciliation"]
        assert meta["contract_tier"] == "L1_exact"
        # candidate mismatch 가 강한 unmatched evidence → L1 no_candidate cap 0.5 초과
        assert result.details["ic_unmatched_prob"].max() > 0.5

    def test_l2_mismatch_capped_at_l2_mismatch_cap(self):
        """L2 + candidate mismatch → l2_mismatch cap (0.7) 까지 허용."""
        df = _make_ic_pair(
            rec_amount=1_000_000,
            pay_amount=10,  # 거의 0 매칭
            # reference 없음 → L2_aggregate
        )
        result = _detector().detect(df)
        meta = result.metadata["probabilistic_reconciliation"]
        assert meta["contract_tier"] == "L2_aggregate"
        # L2 + candidate mismatch → cap 0.7
        assert result.details["ic_unmatched_prob"].max() <= 0.7 + 1e-9

    def test_summary_counters_present(self):
        """metadata 에 no_candidate_count / weak_contract_count / capped_by_contract_count 노출."""
        df = _make_ic_pair(rec_reference="INV-X", pay_reference="INV-X")
        result = _detector().detect(df)
        meta = result.metadata["probabilistic_reconciliation"]
        for key in (
            "no_candidate_count",
            "weak_contract_count",
            "capped_by_contract_count",
            "caps",
        ):
            assert key in meta

    def test_synthetic_label_columns_do_not_influence(self):
        """is_fraud / is_anomaly / mutation_kind / scenario_id injected → 결과 동일.

        threshold/score 가 label-derived 컬럼에 fitting 되지 않음을 회귀 가드.
        """
        base = _make_ic_pair(rec_amount=1_000_000, pay_amount=500_000)
        injected = base.copy()
        injected["is_fraud"] = True
        injected["is_anomaly"] = True
        injected["mutation_kind"] = "amount_inflation"
        injected["semantic_scenario_id"] = "synthetic_mismatch"
        baseline = _detector().detect(base).details[list(_PROB_COLS)]
        polluted = _detector().detect(injected).details[list(_PROB_COLS)]
        pd.testing.assert_frame_equal(
            baseline.reset_index(drop=True),
            polluted.reset_index(drop=True),
            check_like=True,
        )

    def test_existing_ic01_unaffected_when_prob_active(self):
        """high-evidence IC01 hit 가 신규 prob 추가 후에도 그대로 발화."""
        df = _make_ic_df(
            [
                {
                    "gl_account": "1150",
                    "debit_amount": 1_000_000,
                    "credit_amount": 0,
                    "company_code": "A001",
                    "trading_partner": "C999",
                    "posting_date": "2025-03-01",
                },
                # cc multi 충족 + IC01 non-matched 유지를 위한 비-IC payable
                {
                    "gl_account": "5000",
                    "debit_amount": 100,
                    "credit_amount": 0,
                    "company_code": "B001",
                    "trading_partner": "A001",
                    "posting_date": "2025-03-01",
                },
            ]
        )
        result = _detector_min_rows_1().detect(df)
        assert result.details["IC01"].iloc[0] > 0
        assert result.metadata["row_sidecar"]["ic01_evidence_level"].iloc[0] == "high"
