"""DuplicateDetector 독립 트랙 테스트 — L2-03a/b/c/d 4개 서브룰."""

from __future__ import annotations

import pandas as pd
import pytest

from src.detection.base import DetectionResult
from src.detection.duplicate_detector import DuplicateDetector


# ── Fixtures ─────────────────────────────────────────────────


@pytest.fixture
def exact_pair_df() -> pd.DataFrame:
    """L2-03a: gl+amount+date 정확 일치 쌍 1조 + 고유 행 1건."""
    return pd.DataFrame({
        "gl_account": [1000, 1000, 2000],
        "debit_amount": [500.0, 500.0, 300.0],
        "credit_amount": [0.0, 0.0, 0.0],
        "posting_date": pd.to_datetime(["2025-03-01", "2025-03-01", "2025-03-01"]),
        "line_text": ["사무용품 구매", "사무용품 구매", "출장비 정산"],
    })


@pytest.fixture
def unique_df() -> pd.DataFrame:
    """모든 행이 고유 — 플래그 0."""
    return pd.DataFrame({
        "gl_account": [1000, 2000, 3000],
        "debit_amount": [100.0, 200.0, 300.0],
        "credit_amount": [0.0, 0.0, 0.0],
        "posting_date": pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"]),
        "line_text": ["매입A", "매입B", "매입C"],
    })


@pytest.fixture
def fuzzy_pair_df() -> pd.DataFrame:
    """L2-03b: 적요 유사 + 금액 근접 (0.2% 차이)."""
    return pd.DataFrame({
        "gl_account": [1000, 1000, 2000],
        "debit_amount": [1_000_000.0, 998_000.0, 500.0],
        "credit_amount": [0.0, 0.0, 0.0],
        "posting_date": pd.to_datetime(["2025-03-01", "2025-03-02", "2025-03-01"]),
        "line_text": ["삼성전자 법인카드 결제", "삼성전자 법인카드 결제건", "기타"],
    })


@pytest.fixture
def fuzzy_below_threshold_df() -> pd.DataFrame:
    """L2-03b: 적요가 완전히 다름 → 유사도 미달."""
    return pd.DataFrame({
        "gl_account": [1000, 1000],
        "debit_amount": [1_000_000.0, 999_000.0],
        "credit_amount": [0.0, 0.0],
        "posting_date": pd.to_datetime(["2025-03-01", "2025-03-02"]),
        "line_text": ["사무용품 구매", "직원 급여 지급"],
    })


@pytest.fixture
def split_df() -> pd.DataFrame:
    """L2-03c: 100만 단건 + 50만+50만 분할 (같은 gl, 윈도우 내)."""
    return pd.DataFrame({
        "gl_account": [1000, 1000, 1000, 2000],
        "debit_amount": [1_000_000.0, 500_000.0, 500_000.0, 800.0],
        "credit_amount": [0.0, 0.0, 0.0, 0.0],
        "posting_date": pd.to_datetime([
            "2025-03-01", "2025-03-02", "2025-03-02", "2025-03-01",
        ]),
        "line_text": ["대금", "분할1", "분할2", "기타"],
    })


@pytest.fixture
def timeshift_df() -> pd.DataFrame:
    """L2-03d: gl+amount 동일, 날짜 3일 차이."""
    return pd.DataFrame({
        "gl_account": [1000, 1000, 2000],
        "debit_amount": [500.0, 500.0, 300.0],
        "credit_amount": [0.0, 0.0, 0.0],
        "posting_date": pd.to_datetime(["2025-03-01", "2025-03-04", "2025-03-01"]),
        "line_text": ["매입", "매입", "기타"],
    })


@pytest.fixture
def timeshift_outside_window_df() -> pd.DataFrame:
    """L2-03d: 윈도우(7일) 초과 → 탐지 안 됨."""
    return pd.DataFrame({
        "gl_account": [1000, 1000],
        "debit_amount": [500.0, 500.0],
        "credit_amount": [0.0, 0.0],
        "posting_date": pd.to_datetime(["2025-03-01", "2025-03-30"]),
        "line_text": ["매입", "매입"],
    })


# ── Tests ────────────────────────────────────────────────────


class TestDuplicateDetectorBasic:
    def test_track_name(self) -> None:
        assert DuplicateDetector().track_name == "duplicate"

    def test_returns_detection_result(self, exact_pair_df: pd.DataFrame) -> None:
        result = DuplicateDetector().detect(exact_pair_df)
        assert isinstance(result, DetectionResult)
        assert result.track_name == "duplicate"

    def test_scores_range(self, exact_pair_df: pd.DataFrame) -> None:
        result = DuplicateDetector().detect(exact_pair_df)
        assert result.scores.min() >= 0.0
        assert result.scores.max() <= 1.0

    def test_empty_df_raises(self) -> None:
        with pytest.raises(ValueError, match="비어 있습니다"):
            DuplicateDetector().detect(pd.DataFrame())


class TestB05aExact:
    def test_exact_match_flagged(self, exact_pair_df: pd.DataFrame) -> None:
        """gl+amount+date 일치 쌍은 score > 0."""
        result = DuplicateDetector().detect(exact_pair_df)
        assert result.scores.iloc[0] > 0
        assert result.scores.iloc[1] > 0

    def test_unique_not_flagged(self, unique_df: pd.DataFrame) -> None:
        """모든 행 고유 → L2-03a score = 0."""
        result = DuplicateDetector().detect(unique_df)
        # Why: L2-03d도 체크하므로 전체 0인지 확인
        assert result.details.get("L2-03a", pd.Series(0.0)).sum() == 0.0


class TestB05bFuzzy:
    def test_fuzzy_text_flagged(self, fuzzy_pair_df: pd.DataFrame) -> None:
        """유사 적요 + 근접 금액 → score > 0."""
        result = DuplicateDetector().detect(fuzzy_pair_df)
        assert result.details["L2-03b"].iloc[0] > 0
        assert result.details["L2-03b"].iloc[1] > 0

    def test_fuzzy_below_threshold(self, fuzzy_below_threshold_df: pd.DataFrame) -> None:
        """적요 완전히 다름 → L2-03b score = 0."""
        result = DuplicateDetector().detect(fuzzy_below_threshold_df)
        assert result.details["L2-03b"].sum() == 0.0

    def test_no_line_text_skips_b05b(self, exact_pair_df: pd.DataFrame) -> None:
        """line_text 컬럼 없으면 L2-03b 스킵, 나머지 정상."""
        df = exact_pair_df.drop(columns=["line_text"])
        result = DuplicateDetector().detect(df)
        assert isinstance(result, DetectionResult)
        assert result.details["L2-03b"].sum() == 0.0
        # L2-03a는 여전히 동작
        assert result.details["L2-03a"].sum() > 0


class TestB05cSplit:
    def test_split_detected(self, split_df: pd.DataFrame) -> None:
        """100만 + 50만×2 분할 → 탐지."""
        result = DuplicateDetector().detect(split_df)
        assert result.details["L2-03c"].iloc[0] > 0  # 타겟(100만)
        assert result.details["L2-03c"].iloc[1] > 0  # 분할1(50만)
        assert result.details["L2-03c"].iloc[2] > 0  # 분할2(50만)

    def test_no_split_unrelated(self, unique_df: pd.DataFrame) -> None:
        """무관 금액 → L2-03c score = 0."""
        result = DuplicateDetector().detect(unique_df)
        assert result.details["L2-03c"].sum() == 0.0


class TestB05dTimeShift:
    def test_timeshift_flagged(self, timeshift_df: pd.DataFrame) -> None:
        """gl+amount 동일, 3일 차이 → score > 0."""
        result = DuplicateDetector().detect(timeshift_df)
        assert result.details["L2-03d"].iloc[0] > 0
        assert result.details["L2-03d"].iloc[1] > 0

    def test_timeshift_outside_window(self, timeshift_outside_window_df: pd.DataFrame) -> None:
        """윈도우(7일) 초과 → L2-03d = 0."""
        result = DuplicateDetector().detect(timeshift_outside_window_df)
        assert result.details["L2-03d"].sum() == 0.0


class TestGracefulDegradation:
    def test_missing_gl_account(self) -> None:
        """gl_account 없으면 전체 0점 (graceful)."""
        df = pd.DataFrame({
            "debit_amount": [100.0, 100.0],
            "credit_amount": [0.0, 0.0],
            "posting_date": pd.to_datetime(["2025-01-01", "2025-01-01"]),
        })
        result = DuplicateDetector().detect(df)
        assert isinstance(result, DetectionResult)
        assert result.scores.sum() == 0.0

    def test_large_group_warning(self) -> None:
        """max_group_size 초과 시 warning 포함."""
        from config.settings import AuditSettings
        settings = AuditSettings(duplicate_max_group_size=2)
        df = pd.DataFrame({
            "gl_account": [1000] * 5,
            "debit_amount": [100.0] * 5,
            "credit_amount": [0.0] * 5,
            "posting_date": pd.to_datetime(["2025-01-01"] * 5),
            "line_text": ["테스트"] * 5,
        })
        result = DuplicateDetector(settings).detect(df)
        assert any("초과" in w for w in result.warnings)
