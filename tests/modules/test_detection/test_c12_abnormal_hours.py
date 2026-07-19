"""L4-05 비정상 시간대 입력자 집중 분석 — 피처 + 룰 테스트.

피처: add_time_zone_category() 경계값·결산기 보정·주말 보정
룰: c12_abnormal_hours_concentration() 3σ·폴백·급속승인
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.detection.anomaly_rules_simple import c12_abnormal_hours_concentration
from src.feature.time_features import add_time_zone_category

# ── helpers ──────────────────────────────────────────────────────


def _make_df(
    hours: list[str],
    users: list[str] | None = None,
    months: list[int] | None = None,
    days: list[int] | None = None,
    is_weekend: list[bool] | None = None,
    is_holiday: list[bool] | None = None,
) -> pd.DataFrame:
    """시간·사용자·월 지정으로 테스트 DataFrame 생성."""
    n = len(hours)
    # Why: 기본 월=6(비결산기), 일=15(결산 구간 밖)
    m = months or [6] * n
    d = days or [15] * n
    dates = [f"2025-{mm:02d}-{dd:02d} {h}" for mm, dd, h in zip(m, d, hours)]
    df = pd.DataFrame({
        "posting_date": pd.to_datetime(dates),
        "debit_amount": [1_000_000.0] * n,
        "credit_amount": [0.0] * n,
    })
    if users:
        df["created_by"] = users
    if is_weekend is not None:
        df["is_weekend"] = is_weekend
    if is_holiday is not None:
        df["is_holiday"] = is_holiday
    return df


# ══════════════════════════════════════════════════════════════════
#  Part 1: add_time_zone_category 피처 테스트
# ══════════════════════════════════════════════════════════════════


class TestTimeZoneCategory:
    """time_zone_category 피처 분류 테스트."""

    def test_normal_hours(self):
        """10:00 → normal."""
        df = _make_df(["10:00"])
        add_time_zone_category(df)
        assert df["time_zone_category"].iloc[0] == "normal"

    def test_overtime_evening(self):
        """19:00 → overtime."""
        df = _make_df(["19:00"])
        add_time_zone_category(df)
        assert df["time_zone_category"].iloc[0] == "overtime"

    def test_midnight_late(self):
        """23:00 → midnight."""
        df = _make_df(["23:00"])
        add_time_zone_category(df)
        assert df["time_zone_category"].iloc[0] == "midnight"

    def test_midnight_early(self):
        """03:00 → midnight."""
        df = _make_df(["03:00"])
        add_time_zone_category(df)
        assert df["time_zone_category"].iloc[0] == "midnight"

    # ── 경계값 테스트 ──

    def test_boundary_0829_overtime(self):
        """08:29 → overtime (normal 시작 전)."""
        df = _make_df(["08:29"])
        add_time_zone_category(df)
        assert df["time_zone_category"].iloc[0] == "overtime"

    def test_boundary_0830_normal(self):
        """08:30 → normal (정확히 시작)."""
        df = _make_df(["08:30"])
        add_time_zone_category(df)
        assert df["time_zone_category"].iloc[0] == "normal"

    def test_boundary_1830_overtime(self):
        """18:30 → overtime (normal 종료)."""
        df = _make_df(["18:30"])
        add_time_zone_category(df)
        assert df["time_zone_category"].iloc[0] == "overtime"

    def test_boundary_2200_midnight(self):
        """22:00 → midnight."""
        df = _make_df(["22:00"])
        add_time_zone_category(df)
        assert df["time_zone_category"].iloc[0] == "midnight"

    def test_boundary_2159_overtime(self):
        """21:59 → overtime (midnight 직전)."""
        df = _make_df(["21:59"])
        add_time_zone_category(df)
        assert df["time_zone_category"].iloc[0] == "overtime"

    def test_boundary_0600_overtime(self):
        """06:00 → overtime (midnight 종료)."""
        df = _make_df(["06:00"])
        add_time_zone_category(df)
        assert df["time_zone_category"].iloc[0] == "overtime"

    def test_boundary_0559_midnight(self):
        """05:59 → midnight."""
        df = _make_df(["05:59"])
        add_time_zone_category(df)
        assert df["time_zone_category"].iloc[0] == "midnight"

    # ── 결산기 보정 테스트 ──

    def test_settlement_dec25_overtime_to_normal(self):
        """12/25 19:00 → normal (결산 집중기간 내 overtime→normal 보정)."""
        df = _make_df(["19:00"], months=[12], days=[25])
        add_time_zone_category(df)
        assert df["time_zone_category"].iloc[0] == "normal"

    def test_settlement_dec10_overtime_stays(self):
        """12/10 19:00 → overtime (결산 구간 밖, 보정 안 함)."""
        df = _make_df(["19:00"], months=[12], days=[10])
        add_time_zone_category(df)
        assert df["time_zone_category"].iloc[0] == "overtime"

    def test_settlement_jan10_overtime_to_normal(self):
        """1/10 19:00 → normal (결산 집중기간 내)."""
        df = _make_df(["19:00"], months=[1], days=[10])
        add_time_zone_category(df)
        assert df["time_zone_category"].iloc[0] == "normal"

    def test_settlement_jan20_overtime_stays(self):
        """1/20 19:00 → overtime (결산 구간 밖)."""
        df = _make_df(["19:00"], months=[1], days=[20])
        add_time_zone_category(df)
        assert df["time_zone_category"].iloc[0] == "overtime"

    def test_settlement_midnight_not_corrected(self):
        """12/25 23:00 → midnight (결산기여도 심야는 보정 안 함)."""
        df = _make_df(["23:00"], months=[12], days=[25])
        add_time_zone_category(df)
        assert df["time_zone_category"].iloc[0] == "midnight"

    # ── 주말/공휴일 보정 ──

    def test_weekend_normal_becomes_overtime(self):
        """주말 10:00 → overtime (주말에 normal→overtime 보정)."""
        df = _make_df(["10:00"], is_weekend=[True])
        add_time_zone_category(df)
        assert df["time_zone_category"].iloc[0] == "overtime"

    def test_weekend_midnight_stays(self):
        """주말 23:00 → midnight (주말이어도 midnight 유지)."""
        df = _make_df(["23:00"], is_weekend=[True])
        add_time_zone_category(df)
        assert df["time_zone_category"].iloc[0] == "midnight"

    def test_holiday_normal_becomes_overtime(self):
        """공휴일 10:00 → overtime."""
        df = _make_df(["10:00"], is_holiday=[True])
        add_time_zone_category(df)
        assert df["time_zone_category"].iloc[0] == "overtime"

    # ── 시간정보 없음 ──

    def test_no_time_info_unknown(self):
        """시간정보 없는 날짜(00:00:00만) → unknown."""
        df = pd.DataFrame({
            "posting_date": pd.to_datetime(["2025-06-15", "2025-06-16"]),
            "debit_amount": [100.0, 200.0],
            "credit_amount": [0.0, 0.0],
        })
        add_time_zone_category(df)
        assert (df["time_zone_category"] == "unknown").all()

    def test_nat_posting_date_unknown(self):
        """NaT posting_date → unknown."""
        df = pd.DataFrame({
            "posting_date": pd.to_datetime(["2025-06-15 10:00", pd.NaT]),
            "debit_amount": [100.0, 200.0],
            "credit_amount": [0.0, 0.0],
        })
        add_time_zone_category(df)
        assert df["time_zone_category"].iloc[0] == "normal"
        assert df["time_zone_category"].iloc[1] == "unknown"


# ══════════════════════════════════════════════════════════════════
#  Part 2: c12_abnormal_hours_concentration 룰 테스트
# ══════════════════════════════════════════════════════════════════


def _make_rule_df(
    user_entries: dict[str, list[str]],
    tz_categories: dict[str, list[str]] | None = None,
) -> pd.DataFrame:
    """사용자별 시간 엔트리로 룰 테스트용 DataFrame 생성.

    user_entries: {"userA": ["23:00", "23:30", ...], "userB": ["10:00", ...]}
    tz_categories: 직접 지정 시 사용 (None이면 add_time_zone_category로 자동 생성)
    """
    rows = []
    for user, hours in user_entries.items():
        for h in hours:
            rows.append({"created_by": user, "hour": h})

    n = len(rows)
    df = pd.DataFrame({
        "posting_date": pd.to_datetime([
            f"2025-06-15 {r['hour']}" for r in rows
        ]),
        "created_by": [r["created_by"] for r in rows],
        "debit_amount": [1_000_000.0] * n,
        "credit_amount": [0.0] * n,
    })

    if tz_categories:
        cats = []
        for user, hours in user_entries.items():
            cats.extend(tz_categories[user])
        df["time_zone_category"] = cats
    else:
        add_time_zone_category(df)

    return df


class TestC12UserConcentration:
    """사용자별 비정상 비율 + 3σ 이상치 판정."""

    def test_high_midnight_user_flagged(self):
        """User A 80% midnight, 나머지 5명 0~5% → A만 플래그.

        Why: 3σ 판정이 유효하려면 사용자가 충분히 많아야 한다.
             이상치 1명 + 정상 다수 구성 → mean·std가 안정적으로 산출됨.
        """
        entries = {"userA": ["23:00"] * 8 + ["10:00"] * 2}
        # 5명의 정상 사용자 (0~5% 비율)
        for name in ["userB", "userC", "userD", "userE", "userF"]:
            entries[name] = ["10:00"] * 20
        # userB만 midnight 1건 (5%)
        entries["userB"] = ["23:00"] * 1 + ["10:00"] * 19

        df = _make_rule_df(entries)
        result = c12_abnormal_hours_concentration(df, sigma_threshold=2.0)
        user_flags = df.loc[result, "created_by"].unique()
        assert "userA" in user_flags
        assert "userC" not in user_flags

    def test_all_users_same_ratio_no_flag(self):
        """모든 사용자 비율 동일 → 아무도 미플래그 (std=0)."""
        df = _make_rule_df({
            "userA": ["23:00"] * 5 + ["10:00"] * 5,
            "userB": ["23:00"] * 5 + ["10:00"] * 5,
            "userC": ["23:00"] * 5 + ["10:00"] * 5,
        })
        result = c12_abnormal_hours_concentration(df)
        assert not result.any()

    def test_sigma_outlier_but_low_ratio_not_flagged(self):
        """σ 이상치이나 비율 3% → min_abnormal_ratio에 의해 미플래그."""
        # Why: userA가 통계적으로 이상치지만 절대 비율이 낮음
        df = _make_rule_df({
            "userA": ["23:00"] * 1 + ["10:00"] * 32,
            "userB": ["10:00"] * 33,
            "userC": ["10:00"] * 33,
            "userD": ["10:00"] * 33,
        })
        result = c12_abnormal_hours_concentration(
            df, sigma_threshold=2.0, min_abnormal_ratio=0.1,
        )
        assert not result.any()

    def test_missing_created_by_all_false(self):
        """created_by 컬럼 없음 → 전체 False."""
        df = _make_df(["23:00", "10:00"])
        add_time_zone_category(df)
        result = c12_abnormal_hours_concentration(df)
        assert not result.any()

    def test_missing_time_zone_category_all_false(self):
        """time_zone_category 컬럼 없음 → 전체 False."""
        df = _make_df(["23:00"], users=["userA"])
        # time_zone_category를 추가하지 않음
        result = c12_abnormal_hours_concentration(df)
        assert not result.any()


class TestC12FewUsersFallback:
    """사용자 3명 미만 소수 인원 폴백 테스트."""

    def test_two_users_midnight_below_min_entries_not_flagged(self):
        """2명, midnight 1건 → 건수 < 3이므로 미플래그."""
        df = _make_rule_df({
            "userA": ["23:00"] * 1 + ["10:00"] * 9,
            "userB": ["10:00"] * 10,
        })
        result = c12_abnormal_hours_concentration(df, min_midnight_entries=3)
        assert not result.any()

    def test_two_users_high_midnight_flagged(self):
        """2명, midnight 5건 + ratio > 0.2 → 플래그."""
        df = _make_rule_df({
            "userA": ["23:00"] * 5 + ["10:00"] * 5,
            "userB": ["10:00"] * 10,
        })
        result = c12_abnormal_hours_concentration(df, min_midnight_entries=3)
        user_flags = df.loc[result, "created_by"].unique()
        assert "userA" in user_flags
        assert "userB" not in user_flags


class TestC12RapidApproval:
    """급속 승인 검증 테스트."""

    def _make_approval_df(
        self,
        *,
        time: str = "23:00",
        approval_offset_min: int = 2,
        is_manual: bool = True,
        same_approver: bool = False,
        user_persona: str | None = None,
    ) -> pd.DataFrame:
        """급속 승인 테스트용 단일 행 DataFrame."""
        posting = pd.Timestamp(f"2025-06-15 {time}")
        approval = posting + pd.Timedelta(minutes=approval_offset_min)
        df = pd.DataFrame({
            "posting_date": [posting],
            "approval_date": [approval],
            "created_by": ["userA"],
            "approved_by": ["userA" if same_approver else "userB"],
            "debit_amount": [50_000_000.0],
            "credit_amount": [0.0],
            "is_manual_je": [is_manual],
        })
        if user_persona:
            df["user_persona"] = user_persona
        add_time_zone_category(df)
        return df

    def test_manual_rapid_midnight_flagged(self):
        """수기 전표 + 2분 + 심야 → 플래그."""
        df = self._make_approval_df(time="23:00", approval_offset_min=2)
        result = c12_abnormal_hours_concentration(df, rapid_approval_minutes=5)
        assert result.iloc[0]
        assert result.attrs["score_series"].iloc[0] >= 0.65
        assert result.attrs["breakdown"]["rapid_approval_rows"] == 1
        assert result.attrs["row_annotations"][0]["reason_codes"] == ["rapid_approval"]

    def test_auto_rapid_midnight_not_flagged(self):
        """자동 전표(is_manual_je=False) + 2분 + 심야 → 미플래그."""
        df = self._make_approval_df(
            time="23:00", approval_offset_min=2, is_manual=False,
        )
        result = c12_abnormal_hours_concentration(df, rapid_approval_minutes=5)
        assert not result.iloc[0]

    def test_manual_rapid_normal_hours_not_flagged(self):
        """수기 전표 + 2분 + 업무시간 → 미플래그."""
        df = self._make_approval_df(time="10:00", approval_offset_min=2)
        result = c12_abnormal_hours_concentration(df, rapid_approval_minutes=5)
        assert not result.iloc[0]

    def test_self_approval_not_flagged(self):
        """자기 승인(L1-05 영역) → L4-05에서 미플래그."""
        df = self._make_approval_df(
            time="23:00", approval_offset_min=2, same_approver=True,
        )
        result = c12_abnormal_hours_concentration(df, rapid_approval_minutes=5)
        assert not result.iloc[0]

    def test_automated_system_not_flagged(self):
        """automated_system → 미플래그."""
        df = self._make_approval_df(
            time="23:00", approval_offset_min=2,
            user_persona="automated_system",
        )
        result = c12_abnormal_hours_concentration(df, rapid_approval_minutes=5)
        assert not result.iloc[0]

    def test_no_approval_date_graceful_skip(self):
        """approval_date 없음 → graceful skip (에러 없이 False)."""
        df = _make_rule_df({"userA": ["23:00"] * 3, "userB": ["10:00"] * 3})
        # approval_date 컬럼 없음
        result = c12_abnormal_hours_concentration(df, rapid_approval_minutes=5)
        # 급속 승인은 skip, 집중도만 평가됨 — 에러 없이 실행 확인
        assert isinstance(result, pd.Series)


class TestC12FlagTargeting:
    """#6 보완: 이상치 사용자의 비정상 시간대 행만 플래그."""

    def test_outlier_user_normal_entries_not_flagged(self):
        """이상치 사용자의 정상 시간(10:00) 전표는 L4-05 미플래그."""
        entries = {"userA": ["23:00"] * 8 + ["10:00"] * 2}
        for name in ["userB", "userC", "userD", "userE", "userF"]:
            entries[name] = ["10:00"] * 20
        entries["userB"] = ["23:00"] * 1 + ["10:00"] * 19

        df = _make_rule_df(entries)
        result = c12_abnormal_hours_concentration(df, sigma_threshold=2.0)

        # userA의 midnight 행만 플래그, normal 행은 미플래그
        user_a_mask = df["created_by"] == "userA"
        normal_mask = df["time_zone_category"] == "normal"
        flagged_normal = result[user_a_mask & normal_mask]
        assert not flagged_normal.any(), "정상 시간 전표에 L4-05 플래그 발생"

    def test_outlier_user_midnight_entries_flagged(self):
        """이상치 사용자의 심야 전표만 플래그."""
        entries = {"userA": ["23:00"] * 8 + ["10:00"] * 2}
        for name in ["userB", "userC", "userD", "userE", "userF"]:
            entries[name] = ["10:00"] * 20

        df = _make_rule_df(entries)
        result = c12_abnormal_hours_concentration(df, sigma_threshold=2.0)

        user_a_midnight = (df["created_by"] == "userA") & (df["time_zone_category"] == "midnight")
        assert result[user_a_midnight].all(), "이상치 사용자의 심야 전표 미플래그"


class TestC12MinUserEntries:
    """#4 보완: 소수 표본(Small N) 오탐 방지."""

    def test_few_midnight_entries_user_flagged(self):
        """전표 수가 적어도 심야 3건 반복이면 플래그."""
        entries = {"userA": ["23:00"] * 3}
        for name in ["userB", "userC", "userD"]:
            entries[name] = ["10:00"] * 20

        df = _make_rule_df(entries)
        result = c12_abnormal_hours_concentration(
            df, sigma_threshold=2.0, min_user_entries=10,
        )
        user_flags = df.loc[result, "created_by"].unique()
        assert "userA" in user_flags

    def test_few_overtime_entries_user_not_flagged(self):
        """Low-volume users are not flagged for overtime-only repetition."""
        entries = {"userA": ["19:00"] * 3}
        for name in ["userB", "userC", "userD"]:
            entries[name] = ["10:00"] * 20

        df = _make_rule_df(entries)
        result = c12_abnormal_hours_concentration(
            df, sigma_threshold=2.0, min_user_entries=10,
        )
        user_flags = df.loc[result, "created_by"].unique()
        assert "userA" not in user_flags

    def test_automated_system_midnight_concentration_not_flagged(self):
        """Automated/system users are excluded from concentration stats."""
        df = _make_rule_df({
            "SYSTEM": ["23:00"] * 20,
            "IC_GENERATOR": ["23:00"] * 20,
            "userB": ["10:00"] * 20,
            "userC": ["10:00"] * 20,
        })
        df["source"] = ["automated"] * len(df)
        df["user_persona"] = ["Automated System"] * len(df)

        result = c12_abnormal_hours_concentration(
            df,
            auto_entry_sources=["batch", "interface", "system", "automated"],
        )
        assert not result.any()

    def test_sufficient_entries_user_flagged(self):
        """전표 15건 사용자 80% 심야 → min_user_entries=10 통과 + 플래그.

        Why: 정상 사용자 6명(0% 비정상)에 대해 mean≈0, std≈0이면
             userA(80%)가 확실히 이상치로 판정됨.
        """
        entries = {"userA": ["23:00"] * 12 + ["10:00"] * 3}
        for name in ["userB", "userC", "userD", "userE", "userF", "userG"]:
            entries[name] = ["10:00"] * 20

        df = _make_rule_df(entries)
        result = c12_abnormal_hours_concentration(
            df, sigma_threshold=2.0, min_user_entries=10,
        )
        user_flags = df.loc[result, "created_by"].unique()
        assert "userA" in user_flags

    def test_high_context_midnight_user_flagged_below_sigma(self):
        """Many midnight entries are flagged even when the user is below sigma."""
        entries = {"userA": ["23:00"] * 5 + ["10:00"] * 45}
        for name in ["userB", "userC", "userD", "userE", "userF"]:
            entries[name] = ["19:00"] * 8 + ["10:00"] * 42

        df = _make_rule_df(entries)
        result = c12_abnormal_hours_concentration(
            df,
            sigma_threshold=10.0,
            min_abnormal_ratio=0.1,
            min_high_context_midnight_entries=5,
        )

        user_a_midnight = (df["created_by"] == "userA") & (
            df["time_zone_category"] == "midnight"
        )
        user_a_normal = (df["created_by"] == "userA") & (
            df["time_zone_category"] == "normal"
        )
        assert result[user_a_midnight].all()
        assert not result[user_a_normal].any()

    def test_system_context_rows_get_lower_priority_not_removed(self):
        """System/source rows propagated from a human user hit stay detected but low score."""
        entries = {"userA": ["23:00"] * 5 + ["10:00"] * 45}
        for name in ["userB", "userC", "userD", "userE", "userF"]:
            entries[name] = ["19:00"] * 8 + ["10:00"] * 42

        df = _make_rule_df(entries)
        df["source"] = "manual"
        df["user_persona"] = "staff"
        system_idx = df.index[
            (df["created_by"] == "userA")
            & (df["time_zone_category"] == "midnight")
        ][0]
        df.loc[system_idx, "source"] = "automated"
        df.loc[system_idx, "user_persona"] = "Automated System"

        result = c12_abnormal_hours_concentration(
            df,
            sigma_threshold=10.0,
            min_abnormal_ratio=0.08,
            min_high_context_midnight_entries=4,
            auto_entry_sources=["automated"],
        )

        assert result.loc[system_idx]
        assert result.attrs["score_series"].loc[system_idx] == 0.25
        assert result.attrs["row_annotations"][system_idx]["score_bucket"] == (
            "system_context_review"
        )
        assert "system_context_review" in result.attrs["row_annotations"][system_idx][
            "reason_codes"
        ]
        assert result.attrs["breakdown"]["system_context_review_rows"] == 1

    def test_high_context_midnight_ignores_overtime_only(self):
        """High-context supplement applies only to midnight, not overtime."""
        entries = {"userA": ["19:00"] * 5 + ["10:00"] * 45}
        for name in ["userB", "userC", "userD", "userE", "userF"]:
            entries[name] = ["10:00"] * 50

        df = _make_rule_df(entries)
        result = c12_abnormal_hours_concentration(
            df,
            sigma_threshold=10.0,
            min_abnormal_ratio=0.1,
            min_high_context_midnight_entries=5,
        )
        assert not result.any()

    def test_min_user_entries_lowered_flags(self):
        """min_user_entries=3으로 낮추면 전표 5건 사용자도 분석 대상 포함.

        Why: 정상 사용자 5명(0%) 대비 userA(100%)는 확실한 이상치.
        """
        entries = {"userA": ["23:00"] * 5}
        for name in ["userB", "userC", "userD", "userE", "userF"]:
            entries[name] = ["10:00"] * 20

        df = _make_rule_df(entries)
        result = c12_abnormal_hours_concentration(
            df, sigma_threshold=2.0, min_user_entries=3,
        )
        user_flags = df.loc[result, "created_by"].unique()
        assert "userA" in user_flags


class TestC12SourceFallback:
    """#5 보완: source 컬럼 대체 판별로 시스템 전표 과탐 방지."""

    def _make_source_df(self, source: str) -> pd.DataFrame:
        """source 컬럼 포함, is_manual_je 없는 급속 승인 DataFrame."""
        posting = pd.Timestamp("2025-06-15 23:00")
        approval = posting + pd.Timedelta(minutes=2)
        df = pd.DataFrame({
            "posting_date": [posting],
            "approval_date": [approval],
            "created_by": ["userA"],
            "approved_by": ["userB"],
            "debit_amount": [50_000_000.0],
            "credit_amount": [0.0],
            "source": [source],
        })
        add_time_zone_category(df)
        return df

    def test_batch_source_rapid_not_flagged(self):
        """source='batch' + 급속승인 → 미플래그 (자동 전기)."""
        df = self._make_source_df("batch")
        result = c12_abnormal_hours_concentration(
            df, rapid_approval_minutes=5,
            auto_entry_sources=["batch", "interface", "system"],
        )
        assert not result.iloc[0]

    def test_manual_source_rapid_flagged(self):
        """source='manual' + 심야 급속승인 → 플래그."""
        df = self._make_source_df("manual")
        result = c12_abnormal_hours_concentration(
            df, rapid_approval_minutes=5,
            auto_entry_sources=["batch", "interface", "system"],
        )
        assert result.iloc[0]

    def test_automated_system_persona_normalized_not_flagged(self):
        """Persona comparison handles case and spaces."""
        df = self._make_source_df("manual")
        df["user_persona"] = ["Automated System"]
        result = c12_abnormal_hours_concentration(
            df,
            rapid_approval_minutes=5,
            auto_entry_sources=["batch", "interface", "system"],
        )
        assert not result.iloc[0]

    def test_no_manual_no_source_defaults_manual(self):
        """is_manual_je·source 모두 없음 → 수기 간주 (기존 동작 유지)."""
        posting = pd.Timestamp("2025-06-15 23:00")
        approval = posting + pd.Timedelta(minutes=2)
        df = pd.DataFrame({
            "posting_date": [posting],
            "approval_date": [approval],
            "created_by": ["userA"],
            "approved_by": ["userB"],
            "debit_amount": [50_000_000.0],
            "credit_amount": [0.0],
        })
        add_time_zone_category(df)
        result = c12_abnormal_hours_concentration(df, rapid_approval_minutes=5)
        assert result.iloc[0]


class TestC12SecondPrecision:
    """#1 보완: 초 단위 경계값 정밀도."""

    def test_boundary_1830_30s_overtime(self):
        """18:30:30 → overtime (초 단위 포함 시 hour_frac=18.508)."""
        df = pd.DataFrame({
            "posting_date": pd.to_datetime(["2025-06-15 18:30:30"]),
            "debit_amount": [1_000_000.0],
            "credit_amount": [0.0],
        })
        add_time_zone_category(df)
        assert df["time_zone_category"].iloc[0] == "overtime"

    def test_boundary_0830_exact_normal(self):
        """08:30:00 → normal (경계 정확히 포함)."""
        df = pd.DataFrame({
            "posting_date": pd.to_datetime(["2025-06-15 08:30:00"]),
            "debit_amount": [1_000_000.0],
            "credit_amount": [0.0],
        })
        add_time_zone_category(df)
        assert df["time_zone_category"].iloc[0] == "normal"


class TestC12Integration:
    """AnomalyDetector 레지스트리 통합 테스트."""

    def test_c12_in_anomaly_detector(self):
        """AnomalyDetector._build_registry()에 L4-05 포함 확인."""
        from src.detection.anomaly_layer import AnomalyDetector

        detector = AnomalyDetector()
        registry = detector._build_registry()
        rule_ids = [r[0] for r in registry]
        assert "L4-05" in rule_ids

    def test_c12_detect_runs_without_error(self):
        """AnomalyDetector.detect()에서 L4-05 포함 실행 — 에러 없음."""
        from src.detection.anomaly_layer import AnomalyDetector

        df = _make_rule_df({
            "userA": ["23:00"] * 5 + ["10:00"] * 5,
            "userB": ["10:00"] * 10,
        })
        detector = AnomalyDetector()
        result = detector.detect(df)
        assert "L4-05" not in result.metadata.get("skipped_rules", [])


# ══════════════════════════════════════════════════════════════════
#  Part 5: DataSynth E2E 검증
# ══════════════════════════════════════════════════════════════════

DATASYNTH_CSV = Path("data/journal/primary/datasynth/journal_entries.csv")


def _load_datasynth_with_features() -> pd.DataFrame:
    """DataSynth CSV → ingest → feature 파이프라인 실행."""
    from src.feature.engine import generate_all_features
    from src.ingest.column_mapper import auto_map_columns, prepare_dataframe
    from src.ingest.file_validator import validate_file
    from src.ingest.header_detector import detect_header_row
    from src.ingest.reader_api import read_file
    from src.ingest.type_caster import cast_dataframe

    validate_file(DATASYNTH_CSV)
    rr = read_file(DATASYNTH_CSV)
    raw_df = rr.raw_data[rr.active_sheet]
    hr = detect_header_row(raw_df)
    columns, data_df = prepare_dataframe(raw_df, hr.header_row or 0)
    mr = auto_map_columns(columns, matched_keywords=hr.matched_keywords, data_df=data_df)
    cr = cast_dataframe(data_df.rename(columns=mr.mapping))
    result = generate_all_features(cr.data)
    return result.data


class TestC12DataSynthE2E:
    """DataSynth 1M건 기반 L4-05 E2E 검증."""

    @pytest.fixture(scope="class")
    def datasynth_df(self) -> pd.DataFrame:
        if not DATASYNTH_CSV.exists():
            pytest.skip(f"DataSynth 파일 없음: {DATASYNTH_CSV}")
        return _load_datasynth_with_features()

    def test_c12_not_skipped(self, datasynth_df):
        """DataSynth에서 L4-05가 skip 없이 실행."""
        from src.detection.anomaly_layer import AnomalyDetector

        detector = AnomalyDetector()
        result = detector.detect(datasynth_df)
        assert "L4-05" in [rf.rule_id for rf in result.rule_flags], "L4-05 결과 누락"
        assert "L4-05" not in result.metadata.get("skipped_rules", [])

    def test_c12_flag_rate_reasonable(self, datasynth_df):
        """DataSynth L4-05 플래그율이 0.1%~20% 범위 — 극단적 과탐/미탐 방지."""
        from src.detection.anomaly_layer import AnomalyDetector

        detector = AnomalyDetector()
        result = detector.detect(datasynth_df)

        c12_flag = next(rf for rf in result.rule_flags if rf.rule_id == "L4-05")
        flag_rate = c12_flag.flagged_count / c12_flag.total_count

        assert flag_rate > 0.001, f"L4-05 미탐 의심: {flag_rate:.4%} (0.1% 미만)"
        assert flag_rate < 0.20, f"L4-05 과탐 의심: {flag_rate:.4%} (20% 초과)"

    def test_c12_flags_only_abnormal_time(self, datasynth_df):
        """L4-05 플래그 행은 비정상 시간대(midnight/overtime)여야 함."""
        result = c12_abnormal_hours_concentration(
            datasynth_df,
            sigma_threshold=3.0,
            min_abnormal_ratio=0.1,
            min_midnight_entries=3,
        )
        flagged = datasynth_df.loc[result]
        if len(flagged) == 0:
            pytest.skip("L4-05 플래그 0건 — 데이터 특성")
        # Why: 이상치 사용자의 정상 시간 행은 미플래그
        normal_in_flagged = flagged[flagged["time_zone_category"] == "normal"]
        normal_rate = len(normal_in_flagged) / len(flagged)
        assert normal_rate < 0.05, (
            f"L4-05 플래그 중 normal 시간대 비율 {normal_rate:.1%} — 과탐 가능성"
        )
