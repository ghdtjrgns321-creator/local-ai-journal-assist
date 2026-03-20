"""시간/날짜 기반 감사 파생변수 6개 생성 모듈.

C01(기말), C02(주말/공휴일), C03(심야), C04(소급전기), C05(기간귀속오류) 룰 대응.
ingest 완료된 표준 DataFrame을 입력으로 받는다.
"""

from __future__ import annotations

import logging
import warnings
from datetime import date, time as dt_time

import pandas as pd

from config.settings import AuditSettings, get_settings

logger = logging.getLogger(__name__)


# ── Private helpers ──────────────────────────────────────────────


def _build_holiday_set(years: set[int], custom: list[str]) -> set[date]:
    """holidays.KR(법정공휴일) + custom(회사 지정) 병합 → set[date].

    holidays 패키지 import 실패 시 custom만 사용 + 경고.
    """
    result: set[date] = set()

    # 법정공휴일: holidays.KR (대체공휴일·선거일 자동 포함)
    try:
        import holidays as hol

        kr = hol.KR(years=years)
        result.update(kr.keys())
    except ImportError:
        warnings.warn(
            "holidays 패키지 미설치 — 법정공휴일 판정 불가, custom_holidays만 사용",
            stacklevel=2,
        )

    # 회사 지정 휴일: 문자열 → date 파싱
    for s in custom:
        try:
            result.add(date.fromisoformat(s))
        except ValueError:
            logger.warning("custom_holidays 날짜 파싱 실패: %s (YYYY-MM-DD 형식 필요)", s)

    return result


def _has_time_info(series: pd.Series) -> bool:
    """컬럼 전체에서 시간 정보 유무를 판별.

    ERP 시스템 수준 결정 — 모든 값이 00:00:00이면 시간정보 없음.
    행 단위가 아닌 컬럼 단위 판정이 감사적으로 타당.
    """
    valid = series.dropna()
    if valid.empty:
        return False
    unique_times = valid.dt.time.unique()
    return bool(not (len(unique_times) == 1 and unique_times[0] == dt_time(0, 0, 0)))


# ── Public feature functions ─────────────────────────────────────


def add_is_weekend(df: pd.DataFrame) -> pd.DataFrame:
    """C02: posting_date 요일이 토(5)/일(6)이면 True.

    감사 관점: 주말 전기는 정상 업무 외 처리로 부정 가능성.
    """
    df["is_weekend"] = df["posting_date"].dt.dayofweek.ge(5).fillna(False)
    return df


def add_is_after_hours(
    df: pd.DataFrame,
    start: int = 22,
    end: int = 6,
) -> pd.DataFrame:
    """C03: posting_date 시간이 심야 구간이면 True.

    start>end (예: 22~6): 자정 걸침 → (h>=start) | (h<end)
    start<end (예: 1~5):  단순 구간 → (h>=start) & (h<end)
    start==end: 구간 없음 → 전체 False + 경고.
    시간정보 없으면 전체 False + 경고.
    """
    if start == end:
        logger.warning("midnight_start == midnight_end(%d) — is_after_hours를 전체 False로 설정", start)
        df["is_after_hours"] = False
        return df

    if not _has_time_info(df["posting_date"]):
        logger.warning("posting_date에 시간정보 없음 — is_after_hours를 전체 False로 설정")
        df["is_after_hours"] = False
        return df

    hour = df["posting_date"].dt.hour

    if start > end:
        # 자정 걸침: 22시 이후 OR 6시 이전
        df["is_after_hours"] = ((hour >= start) | (hour < end)).fillna(False)
    else:
        # 단순 구간
        df["is_after_hours"] = ((hour >= start) & (hour < end)).fillna(False)

    return df


def add_is_period_end(
    df: pd.DataFrame,
    margin: int = 5,
) -> pd.DataFrame:
    """C01: posting_date가 월말 근접(양방향)이면 True.

    양방향 탐지: 월말 전 margin일 + 익월 초 margin일.
    예) margin=5 → 26~31일(월말 전) + 1~5일(익월 초) 모두 포착.
    margin=0 → 월말 당일(days_before_end==0)만 포착, 익월 초는 탐지 안 함(day≥1).
    감사 관점: 기말 집중 전표는 실적 조정 가능성.
    """
    posting = df["posting_date"]

    # 해당 월의 마지막 날까지 남은 일수
    month_end = posting + pd.offsets.MonthEnd(0)
    days_before_end = (month_end - posting).dt.days

    # 익월 초: posting.dt.day 자체가 전월말로부터의 경과 일수
    days_after_prev_end = posting.dt.day

    df["is_period_end"] = (
        (days_before_end <= margin) | (days_after_prev_end <= margin)
    ).fillna(False)

    return df


def add_days_backdated(df: pd.DataFrame) -> pd.DataFrame:
    """C04: posting_date - document_date 일수 차이 (부호 유지).

    양수(+): 지연전기(Late Recording) — posting이 document보다 나중.
    음수(-): 선전기(Forward Recording) — 시스템 조작 의심.
    감사 관점: 큰 양수 = 소급 전기, 음수 = 통제 우회.

    Phase 2+ 확장 메모:
    SAP ERP 3 Dates — document_date(BLDAT), posting_date(BUDAT), entry_date(CPUDT).
    진짜 위험한 소급 기표는 posting_date - entry_date에서 발생.
    MVP에서는 posting_date - document_date만 구현.
    """
    if "document_date" not in df.columns:
        logger.warning("document_date 컬럼 누락 — days_backdated를 전체 NaN으로 설정")
        df["days_backdated"] = pd.array([pd.NA] * len(df), dtype="Int64")
        return df

    diff = (df["posting_date"] - df["document_date"]).dt.days
    df["days_backdated"] = diff.astype("Int64")
    return df


def add_fiscal_period_mismatch(
    df: pd.DataFrame,
    fiscal_year_start: int = 1,
) -> pd.DataFrame:
    """C05: fiscal_period ≠ 기대 기수이면 True (비표준 회계연도 대응).

    modulo 연산: expected = (month - fiscal_year_start) % 12 + 1
    예) fiscal_year_start=4 → 4월=기수1, 5월=기수2, ..., 3월=기수12
    NaN 함정 방지: 결측치 행은 pd.NA로 덮어씌워 억울한 오탐 차단.
    """
    if "fiscal_period" not in df.columns:
        logger.warning("fiscal_period 컬럼 누락 — fiscal_period_mismatch를 전체 pd.NA로 설정")
        df["fiscal_period_mismatch"] = pd.array([pd.NA] * len(df), dtype="boolean")
        return df

    posting_month = df["posting_date"].dt.month
    expected_period = (posting_month - fiscal_year_start) % 12 + 1

    # NaN 함정 방지: NaT/NaN → modulo 결과가 NaN → NaN != 숫자 = True (오탐)
    has_null = df["posting_date"].isna() | df["fiscal_period"].isna()
    mismatch = df["fiscal_period"] != expected_period

    df["fiscal_period_mismatch"] = mismatch.where(~has_null, other=pd.NA).astype("boolean")
    return df


def add_is_holiday(
    df: pd.DataFrame,
    custom: list[str] | None = None,
) -> pd.DataFrame:
    """C02: posting_date가 공휴일(법정+회사지정)이면 True.

    holidays.KR 자동 + custom_holidays 수동 하이브리드.
    감사 관점: 공휴일 전기는 비영업일 부정 탐지.
    """
    valid_dates = df["posting_date"].dropna()
    if valid_dates.empty:
        df["is_holiday"] = False
        return df

    years = set(valid_dates.dt.year.unique())
    holiday_set = _build_holiday_set(years, custom or [])

    df["is_holiday"] = df["posting_date"].dt.date.isin(holiday_set).fillna(False)
    return df


# ── Orchestrator ─────────────────────────────────────────────────


def add_all_time_features(
    df: pd.DataFrame,
    settings: AuditSettings | None = None,
) -> pd.DataFrame:
    """시간 파생변수 6개를 한번에 추가. engine.py 진입점.

    Warning: df를 in-place로 수정하고 동일 객체를 반환한다.
    복사본이 필요하면 add_all_time_features(df.copy())로 호출할 것.
    """
    s = settings or get_settings()

    add_is_weekend(df)
    add_is_after_hours(df, start=s.midnight_start, end=s.midnight_end)
    add_is_period_end(df, margin=s.period_end_margin_days)
    add_days_backdated(df)
    add_fiscal_period_mismatch(df, fiscal_year_start=s.fiscal_year_start)
    add_is_holiday(df, custom=s.custom_holidays)

    return df
