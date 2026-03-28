"""Tier 2: 값 도메인 + 비즈니스 논리 (28개 체크)."""
from __future__ import annotations

import time

import duckdb

from ..models import CheckResult


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _excluded_docs(labels_con: duckdb.DuckDBPyConnection | None, anomaly_types: list[str]) -> str:
    """라벨 제외 SQL 서브쿼리 생성."""
    if labels_con is None or not anomaly_types:
        return "SELECT NULL WHERE FALSE"
    types_str = ", ".join(f"'{t}'" for t in anomaly_types)
    return f"SELECT DISTINCT document_id FROM labels WHERE anomaly_type IN ({types_str})"


def _timer():
    return time.perf_counter()


def _elapsed(start: float) -> float:
    return (time.perf_counter() - start) * 1000


# ---------------------------------------------------------------------------
# T2-01 ~ T2-03: 기본 프로파일링 + 금액 상호배타
# ---------------------------------------------------------------------------

def t2_01(con: duckdb.DuckDBPyConnection, labels_con) -> CheckResult:
    """39컬럼 프로파일링 (정보 제공용, 항상 PASS)."""
    start = _timer()
    cols_info = con.execute("PRAGMA table_info('je')").fetchall()
    col_names = [row[1] for row in cols_info]

    profile = {}
    for col in col_names:
        row = con.execute(f"""
            SELECT COUNT(*) - COUNT("{col}") AS null_cnt,
                   COUNT(DISTINCT "{col}") AS uniq
            FROM je
        """).fetchone()
        profile[col] = {"null_cnt": row[0], "uniq": row[1]}

    return CheckResult(
        check_id="T2-01", tier=2, name="39컬럼 프로파일링",
        status="PASS", expected="정보 제공용", actual=f"{len(profile)}컬럼 프로파일 완료",
        detail=profile, elapsed_ms=_elapsed(start),
    )


def t2_02(con: duckdb.DuckDBPyConnection, labels_con) -> CheckResult:
    """debit/credit 상호배타 — 한 행에 둘 다 양수이면 FAIL."""
    start = _timer()
    bad = con.execute("""
        SELECT COUNT(*) FROM je
        WHERE COALESCE(debit_amount, 0) > 0 AND COALESCE(credit_amount, 0) > 0
    """).fetchone()[0]

    return CheckResult(
        check_id="T2-02", tier=2, name="debit/credit 상호배타",
        status="PASS" if bad == 0 else "FAIL",
        expected="동시 양수=0", actual=f"both_positive={bad:,}",
        elapsed_ms=_elapsed(start),
    )


def t2_03(con: duckdb.DuckDBPyConnection, labels_con) -> CheckResult:
    """debit=0 AND credit=0 행 비율."""
    start = _timer()
    total = con.execute("SELECT COUNT(*) FROM je").fetchone()[0]
    zero = con.execute("""
        SELECT COUNT(*) FROM je
        WHERE COALESCE(debit_amount, 0) = 0 AND COALESCE(credit_amount, 0) = 0
    """).fetchone()[0]

    pct = (zero / total * 100) if total > 0 else 0
    status = "WARNING" if pct > 1 else "PASS"

    return CheckResult(
        check_id="T2-03", tier=2, name="debit=0 AND credit=0",
        status=status, expected="비율 ≤ 1%",
        actual=f"zero_both={zero:,} ({pct:.2f}%)",
        elapsed_ms=_elapsed(start),
    )


# ---------------------------------------------------------------------------
# T2-04 ~ T2-07: 날짜/기간/CoA 정합 (라벨 제외)
# ---------------------------------------------------------------------------

def t2_04(con: duckdb.DuckDBPyConnection, labels_con) -> CheckResult:
    """fiscal_period == posting_date의 월."""
    start = _timer()
    # Why: LatePosting/BackdatedEntry가 posting_date 변경 → period 불일치 유발
    excl = _excluded_docs(labels_con, ["WrongPeriod", "LatePosting", "BackdatedEntry", "TimingAnomaly"])
    bad = con.execute(f"""
        SELECT COUNT(*) FROM je
        WHERE fiscal_period != EXTRACT(MONTH FROM CAST(posting_date AS TIMESTAMP))
          AND document_id NOT IN ({excl})
    """).fetchone()[0]

    return CheckResult(
        check_id="T2-04", tier=2, name="fiscal_period==month",
        status="PASS" if bad == 0 else "FAIL",
        expected="불일치=0 (timing anomaly 제외)", actual=f"mismatch={bad:,}",
        elapsed_ms=_elapsed(start),
    )


def t2_05(con: duckdb.DuckDBPyConnection, labels_con) -> CheckResult:
    """fiscal_year == posting_date의 연도."""
    start = _timer()
    excl = _excluded_docs(labels_con, ["WrongPeriod", "LatePosting", "BackdatedEntry"])
    bad = con.execute(f"""
        SELECT COUNT(*) FROM je
        WHERE fiscal_year != EXTRACT(YEAR FROM CAST(posting_date AS TIMESTAMP))
          AND document_id NOT IN ({excl})
    """).fetchone()[0]

    return CheckResult(
        check_id="T2-05", tier=2, name="fiscal_year==year",
        status="PASS" if bad == 0 else "FAIL",
        expected="불일치=0 (timing anomaly 제외)", actual=f"mismatch={bad:,}",
        elapsed_ms=_elapsed(start),
    )


def t2_06(con: duckdb.DuckDBPyConnection, labels_con) -> CheckResult:
    """doc_date <= posting_date."""
    start = _timer()
    excl = _excluded_docs(labels_con, ["FutureDatedEntry", "BackdatedEntry", "RushedPeriodEnd", "WrongPeriod"])
    bad = con.execute(f"""
        SELECT COUNT(*) FROM je
        WHERE CAST(document_date AS DATE) > CAST(posting_date AS DATE)
          AND document_id NOT IN ({excl})
    """).fetchone()[0]

    return CheckResult(
        check_id="T2-06", tier=2, name="doc_date<=posting_date",
        status="PASS" if bad == 0 else "FAIL",
        expected="역전=0 (FutureDated+Backdated 제외)", actual=f"reversed={bad:,}",
        elapsed_ms=_elapsed(start),
    )


def t2_07(con: duckdb.DuckDBPyConnection, labels_con) -> CheckResult:
    """CoA 미등록 GL 계정."""
    start = _timer()
    excl = _excluded_docs(labels_con, ["InvalidAccount", "DormantAccountActivity", "MisclassifiedAccount"])
    bad_gls = con.execute(f"""
        SELECT DISTINCT gl_account FROM je
        WHERE gl_account IS NOT NULL
          AND gl_account NOT IN (SELECT gl_account FROM coa)
          AND document_id NOT IN ({excl})
    """).fetchall()
    bad_list = [r[0] for r in bad_gls]

    return CheckResult(
        check_id="T2-07", tier=2, name="CoA 미등록 GL",
        status="PASS" if len(bad_list) == 0 else "FAIL",
        expected="미등록 GL=0 (InvalidAccount 등 제외)",
        actual=f"unregistered={len(bad_list)}",
        detail={"unregistered_gls": bad_list[:20]} if bad_list else None,
        elapsed_ms=_elapsed(start),
    )


# ---------------------------------------------------------------------------
# T2-08 ~ T2-13: 도메인 값 검증
# ---------------------------------------------------------------------------

def t2_08(con: duckdb.DuckDBPyConnection, labels_con) -> CheckResult:
    """document_type 도메인."""
    start = _timer()
    # DataSynth 허용 document_type 목록
    allowed = ("SA", "KR", "KG", "DZ", "DR", "WE", "RE", "AA", "AB", "HR", "IC", "WL", "KZ")
    allowed_str = ", ".join(f"'{v}'" for v in allowed)
    bad = con.execute(f"""
        SELECT DISTINCT document_type FROM je
        WHERE document_type NOT IN ({allowed_str})
          AND document_type IS NOT NULL AND TRIM(document_type) != ''
    """).fetchall()
    bad_list = [r[0] for r in bad]

    return CheckResult(
        check_id="T2-08", tier=2, name="document_type 도메인",
        status="PASS" if len(bad_list) == 0 else "FAIL",
        expected=f"허용값: {allowed}",
        actual=f"out_of_domain={bad_list}" if bad_list else "OK",
        elapsed_ms=_elapsed(start),
    )


def t2_09(con: duckdb.DuckDBPyConnection, labels_con) -> CheckResult:
    """user_persona 도메인 (5값)."""
    start = _timer()
    allowed = ("automated_system", "junior_accountant", "senior_accountant", "controller", "manager")
    allowed_str = ", ".join(f"'{v}'" for v in allowed)
    bad = con.execute(f"""
        SELECT DISTINCT user_persona FROM je
        WHERE user_persona NOT IN ({allowed_str})
          AND user_persona IS NOT NULL AND TRIM(user_persona) != ''
    """).fetchall()
    bad_list = [r[0] for r in bad]

    return CheckResult(
        check_id="T2-09", tier=2, name="user_persona 도메인",
        status="PASS" if len(bad_list) == 0 else "FAIL",
        expected=f"허용값: {allowed}",
        actual=f"out_of_domain={bad_list}" if bad_list else "OK",
        elapsed_ms=_elapsed(start),
    )


def t2_10(con: duckdb.DuckDBPyConnection, labels_con) -> CheckResult:
    """business_process 도메인 (6값)."""
    start = _timer()
    allowed = ("P2P", "O2C", "R2R", "H2R", "TRE", "A2R")
    allowed_str = ", ".join(f"'{v}'" for v in allowed)
    bad = con.execute(f"""
        SELECT DISTINCT business_process FROM je
        WHERE business_process NOT IN ({allowed_str})
          AND business_process IS NOT NULL AND TRIM(business_process) != ''
    """).fetchall()
    bad_list = [r[0] for r in bad]

    return CheckResult(
        check_id="T2-10", tier=2, name="business_process 도메인",
        status="PASS" if len(bad_list) == 0 else "FAIL",
        expected=f"허용값: {allowed}",
        actual=f"out_of_domain={bad_list}" if bad_list else "OK",
        elapsed_ms=_elapsed(start),
    )


def t2_11(con: duckdb.DuckDBPyConnection, labels_con) -> CheckResult:
    """source 도메인 (대소문자 무시)."""
    start = _timer()
    allowed = ("automated", "manual", "recurring", "adjustment")
    allowed_str = ", ".join(f"'{v}'" for v in allowed)
    bad = con.execute(f"""
        SELECT DISTINCT source FROM je
        WHERE LOWER(source) NOT IN ({allowed_str})
          AND source IS NOT NULL AND TRIM(source) != ''
    """).fetchall()
    bad_list = [r[0] for r in bad]

    return CheckResult(
        check_id="T2-11", tier=2, name="source 도메인",
        status="PASS" if len(bad_list) == 0 else "FAIL",
        expected=f"허용값: {allowed} (대소문자 무시)",
        actual=f"out_of_domain={bad_list}" if bad_list else "OK",
        elapsed_ms=_elapsed(start),
    )


def t2_12(con: duckdb.DuckDBPyConnection, labels_con) -> CheckResult:
    """currency 단일 (KRW만)."""
    start = _timer()
    vals = con.execute("SELECT DISTINCT currency FROM je WHERE currency IS NOT NULL").fetchall()
    val_list = [r[0] for r in vals]

    return CheckResult(
        check_id="T2-12", tier=2, name="currency 단일",
        status="PASS" if val_list == ["KRW"] else "FAIL",
        expected="KRW만", actual=f"distinct={val_list}",
        elapsed_ms=_elapsed(start),
    )


def t2_13(con: duckdb.DuckDBPyConnection, labels_con) -> CheckResult:
    """exchange_rate 단일 (1만)."""
    start = _timer()
    vals = con.execute("SELECT DISTINCT exchange_rate FROM je WHERE exchange_rate IS NOT NULL").fetchall()
    val_list = [r[0] for r in vals]

    ok = len(val_list) == 1 and val_list[0] == 1
    return CheckResult(
        check_id="T2-13", tier=2, name="exchange_rate 단일",
        status="PASS" if ok else "FAIL",
        expected="exchange_rate=1만", actual=f"distinct={val_list}",
        elapsed_ms=_elapsed(start),
    )


# ---------------------------------------------------------------------------
# T2-14 ~ T2-17: 관계/구조 정합
# ---------------------------------------------------------------------------

def t2_14(con: duckdb.DuckDBPyConnection, labels_con) -> CheckResult:
    """trading_partner NULL 비율 — IC 10% 대비 95% 초과 시 WARNING."""
    start = _timer()
    excl = _excluded_docs(labels_con, ["UnmatchedIntercompany", "CircularIntercompany"])
    total = con.execute("SELECT COUNT(*) FROM je").fetchone()[0]
    null_tp = con.execute(f"""
        SELECT COUNT(*) FROM je
        WHERE (trading_partner IS NULL OR TRIM(trading_partner) = '')
          AND document_id NOT IN ({excl})
    """).fetchone()[0]

    pct = (null_tp / total * 100) if total > 0 else 0
    # IC 거래는 전체의 ~10%, 나머지 90%는 정상 NULL → 95% 초과 시 IC 누락 의심
    status = "WARNING" if pct > 95 else "PASS"

    return CheckResult(
        check_id="T2-14", tier=2, name="trading_partner NULL 비율",
        status=status, expected="NULL ≤ 95% (IC 라벨 제외)",
        actual=f"null={null_tp:,} ({pct:.1f}%)",
        elapsed_ms=_elapsed(start),
    )


def t2_15(con: duckdb.DuckDBPyConnection, labels_con) -> CheckResult:
    """라벨 논리 정합 — is_fraud=true인데 fraud_type NULL, 또는 역방향."""
    start = _timer()
    # is_fraud=true AND fraud_type IS NULL
    fwd = con.execute("""
        SELECT COUNT(*) FROM je
        WHERE is_fraud = true
          AND (fraud_type IS NULL OR TRIM(fraud_type) = '')
    """).fetchone()[0]
    # is_fraud=false (or NULL) AND fraud_type IS NOT NULL
    rev = con.execute("""
        SELECT COUNT(*) FROM je
        WHERE (is_fraud = false OR is_fraud IS NULL)
          AND fraud_type IS NOT NULL AND TRIM(fraud_type) != ''
    """).fetchone()[0]

    total_bad = fwd + rev
    return CheckResult(
        check_id="T2-15", tier=2, name="is_fraud↔fraud_type 정합",
        status="PASS" if total_bad == 0 else "FAIL",
        expected="불일치=0",
        actual=f"fraud_no_type={fwd:,}, type_no_fraud={rev:,}",
        elapsed_ms=_elapsed(start),
    )


def t2_16(con: duckdb.DuckDBPyConnection, labels_con) -> CheckResult:
    """approved_by 있는데 approval_date 없는 쌍."""
    start = _timer()
    bad = con.execute("""
        SELECT COUNT(*) FROM je
        WHERE approved_by IS NOT NULL AND TRIM(approved_by) != ''
          AND (approval_date IS NULL OR TRIM(CAST(approval_date AS VARCHAR)) = '')
    """).fetchone()[0]

    return CheckResult(
        check_id="T2-16", tier=2, name="approved_by↔approval_date 쌍",
        status="PASS" if bad == 0 else "FAIL",
        expected="approved_by 있는데 approval_date 없음=0",
        actual=f"orphan_approval={bad:,}",
        elapsed_ms=_elapsed(start),
    )


def t2_17(con: duckdb.DuckDBPyConnection, labels_con) -> CheckResult:
    """line_number 순차 — doc별 MIN=1, MAX=COUNT, 갭 없는지."""
    start = _timer()
    gap_docs = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT document_id
            FROM je
            GROUP BY document_id
            HAVING MIN(line_number) != 1
                OR MAX(line_number) != COUNT(*)
        )
    """).fetchone()[0]

    return CheckResult(
        check_id="T2-17", tier=2, name="line_number 순차",
        status="PASS" if gap_docs == 0 else "FAIL",
        expected="갭 있는 문서=0", actual=f"gap_docs={gap_docs:,}",
        elapsed_ms=_elapsed(start),
    )


# ---------------------------------------------------------------------------
# T2-18 ~ T2-21: 비즈니스 논리 (라벨 제외)
# ---------------------------------------------------------------------------

def t2_18(con: duckdb.DuckDBPyConnection, labels_con) -> CheckResult:
    """역할-금액 정합 — junior가 1억 초과 전표."""
    start = _timer()
    excl = _excluded_docs(labels_con, ["ExceededApprovalLimit", "JustBelowThreshold"])
    bad = con.execute(f"""
        SELECT COUNT(*) FROM je
        WHERE user_persona = 'junior_accountant'
          AND GREATEST(COALESCE(debit_amount, 0), COALESCE(credit_amount, 0)) > 100000000
          AND document_id NOT IN ({excl})
    """).fetchone()[0]

    return CheckResult(
        check_id="T2-18", tier=2, name="junior 1억 초과",
        status="PASS" if bad == 0 else "WARNING",
        expected="junior 1억 초과=0 (전결규정은 승인 한도, 작성 한도 아님. 승인 한도 검증은 B02/B03에서 수행)",
        actual=f"violations={bad:,}",
        elapsed_ms=_elapsed(start),
    )


def t2_19(con: duckdb.DuckDBPyConnection, labels_con) -> CheckResult:
    """approval_date >= posting_date (사후승인 탐지)."""
    start = _timer()
    excl = _excluded_docs(labels_con, ["LateApproval", "SkippedApproval", "LatePosting", "RushedPeriodEnd", "WrongPeriod"])
    bad = con.execute(f"""
        SELECT COUNT(*) FROM je
        WHERE approval_date IS NOT NULL
          AND TRIM(CAST(approval_date AS VARCHAR)) != ''
          AND CAST(approval_date AS DATE) < CAST(posting_date AS DATE)
          AND document_id NOT IN ({excl})
    """).fetchone()[0]

    return CheckResult(
        check_id="T2-19", tier=2, name="approval_date>=posting_date",
        status="PASS" if bad == 0 else "FAIL",
        expected="사전승인 위반=0 (LateApproval+SkippedApproval+LatePosting+RushedPeriodEnd+WrongPeriod 제외)",
        actual=f"pre_post_violations={bad:,}",
        elapsed_ms=_elapsed(start),
    )


def t2_20(con: duckdb.DuckDBPyConnection, labels_con) -> CheckResult:
    """automated 논리 — automated source인데 제3자 승인자가 있는 경우."""
    start = _timer()
    excl = _excluded_docs(labels_con, ["ManualOverride", "SelfApproval"])
    bad = con.execute(f"""
        SELECT COUNT(*) FROM je
        WHERE LOWER(source) = 'automated'
          AND approved_by IS NOT NULL AND TRIM(approved_by) != ''
          AND approved_by != created_by
          AND document_id NOT IN ({excl})
    """).fetchone()[0]

    return CheckResult(
        check_id="T2-20", tier=2, name="automated 제3자승인",
        status="PASS" if bad == 0 else "WARNING",
        expected="automated+제3자승인=0 (ManualOverride 등 제외)",
        actual=f"anomalies={bad:,}",
        elapsed_ms=_elapsed(start),
    )


def t2_21(con: duckdb.DuckDBPyConnection, labels_con) -> CheckResult:
    """GL prefix-process 매핑 — P2P인데 GL이 2xxx/1200xxx로 시작하지 않는 비율."""
    start = _timer()
    excl = _excluded_docs(labels_con, ["MisclassifiedAccount", "ImproperCapitalization"])

    # P2P 전표 중 GL prefix 불일치 비율
    p2p_total = con.execute(f"""
        SELECT COUNT(*) FROM je
        WHERE business_process = 'P2P'
          AND document_id NOT IN ({excl})
    """).fetchone()[0]

    p2p_bad = con.execute(f"""
        SELECT COUNT(*) FROM je
        WHERE business_process = 'P2P'
          AND gl_account IS NOT NULL
          AND gl_account NOT LIKE '2%' AND gl_account NOT LIKE '1200%'
          AND document_id NOT IN ({excl})
    """).fetchone()[0]

    pct = (p2p_bad / p2p_total * 100) if p2p_total > 0 else 0
    status = "WARNING" if pct > 20 else "PASS"

    return CheckResult(
        check_id="T2-21", tier=2, name="GL prefix↔process",
        status=status, expected="P2P+GL불일치 ≤ 20%",
        actual=f"P2P total={p2p_total:,}, bad_prefix={p2p_bad:,} ({pct:.1f}%)",
        elapsed_ms=_elapsed(start),
    )


# ---------------------------------------------------------------------------
# T2-22 ~ T2-24: doctype-process 매핑, self-offsetting, 차대변 방향
# ---------------------------------------------------------------------------

def t2_22(con: duckdb.DuckDBPyConnection, labels_con) -> CheckResult:
    """doctype-process 매핑 위반."""
    start = _timer()
    # 기대 매핑: document_type → business_process
    mapping = {
        "WE": "P2P", "KR": "P2P",
        "DR": "O2C", "DZ": "O2C",
        "HR": "H2R",
        "AA": "A2R",
    }
    conditions = " OR ".join(
        f"(document_type = '{dt}' AND business_process != '{bp}')"
        for dt, bp in mapping.items()
    )
    bad = con.execute(f"""
        SELECT COUNT(*) FROM je WHERE {conditions}
    """).fetchone()[0]

    return CheckResult(
        check_id="T2-22", tier=2, name="doctype↔process 매핑",
        status="PASS" if bad == 0 else "WARNING",
        expected="매핑 위반=0",
        actual=f"violations={bad:,}",
        detail={"mapping": mapping},
        elapsed_ms=_elapsed(start),
    )


def t2_23(con: duckdb.DuckDBPyConnection, labels_con) -> CheckResult:
    """Self-offsetting — 같은 doc+GL에 dr>0과 cr>0 동시 존재 (GL 2900/1150/2050 제외)."""
    start = _timer()
    excl = _excluded_docs(labels_con, ["ReversedAmount"])
    # 같은 document_id + gl_account 내에 차변과 대변 행이 모두 존재
    bad = con.execute(f"""
        SELECT COUNT(*) FROM (
            SELECT document_id, gl_account
            FROM je
            WHERE document_id NOT IN ({excl})
              AND gl_account NOT IN ('2900', '1150', '2050')
            GROUP BY document_id, gl_account
            HAVING SUM(CASE WHEN COALESCE(debit_amount, 0) > 0 THEN 1 ELSE 0 END) > 0
               AND SUM(CASE WHEN COALESCE(credit_amount, 0) > 0 THEN 1 ELSE 0 END) > 0
        )
    """).fetchone()[0]

    return CheckResult(
        check_id="T2-23", tier=2, name="Self-offsetting",
        status="PASS" if bad == 0 else "WARNING",
        expected="self-offset 쌍=0 (GL 2900/1150/2050+ReversedAmount 제외)",
        actual=f"self_offset_pairs={bad:,}",
        elapsed_ms=_elapsed(start),
    )


def t2_24(con: duckdb.DuckDBPyConnection, labels_con) -> CheckResult:
    """차대변 방향 — 4xxx(수익) 계정에 debit>0 비율."""
    start = _timer()
    excl = _excluded_docs(labels_con, ["ReversedAmount", "ImproperCapitalization", "RevenueManipulation"])

    rev_total = con.execute(f"""
        SELECT COUNT(*) FROM je
        WHERE gl_account LIKE '4%'
          AND document_id NOT IN ({excl})
    """).fetchone()[0]

    rev_debit = con.execute(f"""
        SELECT COUNT(*) FROM je
        WHERE gl_account LIKE '4%'
          AND COALESCE(debit_amount, 0) > 0
          AND document_id NOT IN ({excl})
    """).fetchone()[0]

    pct = (rev_debit / rev_total * 100) if rev_total > 0 else 0
    # 수익 계정 차변은 매출환불/할인 등 소수만 정상
    status = "WARNING" if pct > 10 else "PASS"

    return CheckResult(
        check_id="T2-24", tier=2, name="수익계정 차변 비율",
        status=status, expected="4xxx debit ≤ 10%",
        actual=f"4xxx total={rev_total:,}, debit={rev_debit:,} ({pct:.1f}%)",
        elapsed_ms=_elapsed(start),
    )


# ---------------------------------------------------------------------------
# T2-25 ~ T2-28: 보조 필드 검증
# ---------------------------------------------------------------------------

def t2_25(con: duckdb.DuckDBPyConnection, labels_con) -> CheckResult:
    """tax_code 100% NULL — DataSynth 설계 의도 확인용."""
    start = _timer()
    non_null = con.execute("""
        SELECT COUNT(*) FROM je
        WHERE tax_code IS NOT NULL AND TRIM(tax_code) != ''
    """).fetchone()[0]

    return CheckResult(
        check_id="T2-25", tier=2, name="tax_code 100% NULL",
        status="WARNING" if non_null == 0 else "PASS",
        expected="설계상 tax_code 미사용 (WARNING=정상)",
        actual=f"non_null={non_null:,}",
        elapsed_ms=_elapsed(start),
    )


def t2_26(con: duckdb.DuckDBPyConnection, labels_con) -> CheckResult:
    """cost_center 형식 — CC로 시작해야 함."""
    start = _timer()
    bad = con.execute("""
        SELECT COUNT(*) FROM je
        WHERE cost_center IS NOT NULL AND TRIM(cost_center) != ''
          AND cost_center NOT LIKE 'CC%'
    """).fetchone()[0]

    return CheckResult(
        check_id="T2-26", tier=2, name="cost_center 형식",
        status="PASS" if bad == 0 else "FAIL",
        expected="cost_center LIKE 'CC%'", actual=f"bad_format={bad:,}",
        elapsed_ms=_elapsed(start),
    )


def t2_27(con: duckdb.DuckDBPyConnection, labels_con) -> CheckResult:
    """profit_center 형식 — PC-로 시작해야 함."""
    start = _timer()
    bad = con.execute("""
        SELECT COUNT(*) FROM je
        WHERE profit_center IS NOT NULL AND TRIM(profit_center) != ''
          AND profit_center NOT LIKE 'PC-%'
    """).fetchone()[0]

    return CheckResult(
        check_id="T2-27", tier=2, name="profit_center 형식",
        status="PASS" if bad == 0 else "FAIL",
        expected="profit_center LIKE 'PC-%'", actual=f"bad_format={bad:,}",
        elapsed_ms=_elapsed(start),
    )


def t2_28(con: duckdb.DuckDBPyConnection, labels_con) -> CheckResult:
    """sod_violation=true인데 sod_conflict_type 없는 경우."""
    start = _timer()
    bad = con.execute("""
        SELECT COUNT(*) FROM je
        WHERE sod_violation = true
          AND (sod_conflict_type IS NULL OR TRIM(sod_conflict_type) = '')
    """).fetchone()[0]

    return CheckResult(
        check_id="T2-28", tier=2, name="sod↔conflict_type 정합",
        status="PASS" if bad == 0 else "FAIL",
        expected="sod=true+type없음=0", actual=f"orphan_sod={bad:,}",
        elapsed_ms=_elapsed(start),
    )


# ---------------------------------------------------------------------------
# 엔트리포인트
# ---------------------------------------------------------------------------

def run_tier2(
    con: duckdb.DuckDBPyConnection,
    labels_con: duckdb.DuckDBPyConnection | None = None,
) -> list[CheckResult]:
    """Tier 2 전체 체크 실행 (28개)."""
    results: list[CheckResult] = []
    for fn in [
        t2_01, t2_02, t2_03, t2_04, t2_05, t2_06, t2_07,
        t2_08, t2_09, t2_10, t2_11, t2_12, t2_13,
        t2_14, t2_15, t2_16, t2_17,
        t2_18, t2_19, t2_20, t2_21,
        t2_22, t2_23, t2_24,
        t2_25, t2_26, t2_27, t2_28,
    ]:
        results.append(fn(con, labels_con))
    return results
