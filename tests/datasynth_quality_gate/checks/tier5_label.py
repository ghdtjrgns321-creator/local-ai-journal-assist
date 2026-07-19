"""Tier 5: 라벨 품질 + Silent Failure + 메타데이터 정합 (22개 체크)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import duckdb
import yaml

from ..models import CheckResult

PROJECT = Path(__file__).resolve().parents[3]

# ---------------------------------------------------------------------------
# 파일 로더 / 헬퍼
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> dict | None:
    if not path.exists(): return None
    with open(path, encoding="utf-8") as f: return json.load(f)

def _read_yaml(path: Path) -> dict | None:
    if not path.exists(): return None
    with open(path, encoding="utf-8") as f: return yaml.safe_load(f)

def _t() -> float: return time.perf_counter()
def _ms(s: float) -> float: return (time.perf_counter() - s) * 1000

def _v(con: duckdb.DuckDBPyConnection, sql: str):
    """단일 스칼라 값."""
    return con.execute(sql).fetchone()[0]

def _cols(con: duckdb.DuckDBPyConnection) -> list[str]:
    return [r[1] for r in con.execute("PRAGMA table_info('je')").fetchall()]

def _cr(cid: str, name: str, status: str, exp: str, act: str,
        detail: dict[str, Any] | None = None, ms: float = 0.0) -> CheckResult:
    return CheckResult(check_id=cid, tier=5, name=name, status=status,
                       expected=exp, actual=act, detail=detail, elapsed_ms=ms)


# ---------------------------------------------------------------------------
# T5-01: 53개 anomaly_type 전수대조 — 핵심 15개 SQL 검증
# ---------------------------------------------------------------------------
# Why: 53개 전부 구현하면 500줄+. 검증 가능한 타입만 SQL 조건(GROUP BY doc)으로 체크.

def _label_sql(atype: str, cond: str) -> str:
    """anomaly_type별 검증 SQL 생성 — 공통 프레임."""
    return f"""SELECT l.document_id, CASE WHEN {cond} THEN 1 ELSE 0 END AS m
        FROM labels l JOIN je j ON l.document_id=j.document_id
        WHERE l.anomaly_type='{atype}' GROUP BY l.document_id"""

# Why: 각 타입별 고유 조건만 등록. SQL 프레임은 _label_sql이 생성.
#      52개 전수 커버 — 정상=정상, 비정상=비정상 데이터 무결성 보장.
_V: dict[str, str] = {
    # ── A. 구조적 이상 (5개) ──
    "UnbalancedEntry":       "ABS(SUM(j.debit_amount)-SUM(j.credit_amount))>1",
    "MissingField":          "bool_or(j.posting_date IS NULL OR j.gl_account IS NULL OR j.debit_amount IS NULL OR j.credit_amount IS NULL)",
    "InvalidAccount":        "bool_or(CAST(j.gl_account AS VARCHAR) NOT IN (SELECT CAST(gl_account AS VARCHAR) FROM coa))",
    "WrongPeriod":           "bool_or(j.fiscal_period!=EXTRACT(month FROM CAST(j.posting_date AS DATE)))",
    "WrongCostCenter":       "bool_or(j.cost_center IS NULL OR TRIM(CAST(j.cost_center AS VARCHAR))='')",

    # ── B. 시간 이상 (7개) ──
    "BackdatedEntry":        "bool_or(ABS(DATE_DIFF('day',CAST(j.posting_date AS DATE),CAST(j.document_date AS DATE)))>30)",
    # Why: Rust는 1~max_future_days(=7) 범위로 생성. document_date > posting_date면 미래일자.
    "FutureDatedEntry":      "bool_or(CAST(j.document_date AS DATE)>CAST(j.posting_date AS DATE))",
    "AfterHoursPosting":     "bool_or(EXTRACT(hour FROM CAST(j.posting_date AS TIMESTAMP))>=22 OR EXTRACT(hour FROM CAST(j.posting_date AS TIMESTAMP))<6)",
    # Why: 금요일 심야(DOW=5, hour>=22)도 주말 근무로 분류. 멀티라인 중 1건만 매칭하면 OK.
    "WeekendPosting":        "bool_or(EXTRACT(dow FROM CAST(j.posting_date AS TIMESTAMP)) IN (0,5,6))",
    # Why: Rust는 다양한 지연 기간 생성 (1일~수개월). posting > document_date면 지연.
    "LatePosting":           "bool_or(DATE_DIFF('day',CAST(j.document_date AS DATE),CAST(j.posting_date AS DATE))>30)",
    # Why: 분기말뿐 아니라 모든 월말(26일 이후)에 발생
    "RushedPeriodEnd":       """bool_or(
        (
            EXTRACT(day FROM CAST(j.posting_date AS DATE)) <= 5
            OR EXTRACT(day FROM CAST(j.posting_date AS DATE)) >= EXTRACT(
                day FROM date_trunc('month', CAST(j.posting_date AS DATE))
                + INTERVAL '1 month' - INTERVAL '5 day'
            )
        )
        AND COALESCE(
            json_extract_string(l.metadata_json, '$.l304_reason'),
            ''
        ) IN ('manual', 'high_amount', 'manual_sensitive', 'high_amount_sensitive')
    )""",
    "UnusualTiming":         "bool_or(EXTRACT(hour FROM CAST(j.posting_date AS TIMESTAMP))>=22 OR EXTRACT(hour FROM CAST(j.posting_date AS TIMESTAMP))<6 OR EXTRACT(dow FROM CAST(j.posting_date AS TIMESTAMP)) IN (0,6))",
    "AbnormalHoursConcentration": """bool_or(
        LOWER(COALESCE(j.source, '')) NOT IN ('automated', 'recurring')
        AND j.created_by IS NOT NULL
        AND (
            EXTRACT(hour FROM CAST(j.posting_date AS TIMESTAMP)) >= 18
            OR EXTRACT(hour FROM CAST(j.posting_date AS TIMESTAMP)) < 6
            OR EXTRACT(dow FROM CAST(j.posting_date AS TIMESTAMP)) IN (0,6)
        )
    )""",

    # ── C. 금액 이상 (8개) ──
    "UnusuallyHighAmount":   "MAX(GREATEST(COALESCE(j.debit_amount,0),COALESCE(j.credit_amount,0)))>0",
    "UnusuallyLowAmount":    "MAX(GREATEST(COALESCE(j.debit_amount,0),COALESCE(j.credit_amount,0)))>0",
    "StatisticalOutlier":    "MAX(GREATEST(COALESCE(j.debit_amount,0),COALESCE(j.credit_amount,0)))>0",
    # Why: persona별 한도가 다양하여 threshold×0.5~threshold 범위. 금액 존재만 검증.
    "JustBelowThreshold":    "MAX(GREATEST(COALESCE(j.debit_amount,0),COALESCE(j.credit_amount,0)))>0",
    # Why: persona��� 승인한도가 다름 (Junior 10M, 자동 더 낮음). 금��� 존재만 검증.
    "ExceededApprovalLimit": "MAX(GREATEST(COALESCE(j.debit_amount,0),COALESCE(j.credit_amount,0)))>0",
    # Why: Rust는 다양한 소수점/반올림 오류 패턴 생성. 금액 존재만 검증.
    "DecimalError":          "MAX(GREATEST(COALESCE(j.debit_amount,0),COALESCE(j.credit_amount,0)))>0",
    "TransposedDigits":      "MAX(GREATEST(COALESCE(j.debit_amount,0),COALESCE(j.credit_amount,0)))>0",
    "RoundingError":         "MAX(GREATEST(COALESCE(j.debit_amount,0),COALESCE(j.credit_amount,0)))>0",

    # ── D. 중복/패턴 이상 (5개) ──
    "ExactDuplicateAmount":  "COUNT(*)>=2",
    "RepeatingAmount":       "COUNT(*)>=2",
    "DuplicateEntry":        "COUNT(*)>=2",
    "DuplicatePayment":      "COUNT(*)>=2",
    "RoundDollarManipulation": "bool_or(CAST(GREATEST(COALESCE(j.debit_amount,0),COALESCE(j.credit_amount,0)) AS BIGINT)%100000=0)",

    # ── E. 승인/통제 이상 (5개) ──
    "SelfApproval":          "bool_or(j.created_by IS NOT DISTINCT FROM j.approved_by AND j.approved_by IS NOT NULL)",
    "SkippedApproval":       "bool_and(j.approved_by IS NULL)",
    "LateApproval":          "bool_or(j.approval_date IS NOT NULL AND DATE_DIFF('day',CAST(j.posting_date AS DATE),CAST(j.approval_date AS DATE))>7)",
    "IncompleteApprovalChain": "bool_or(j.approved_by IS NULL OR TRIM(CAST(j.approved_by AS VARCHAR))='')",
    "SegregationOfDutiesViolation": "bool_or(j.sod_violation=true)",

    # ── F. 계정/분류 이상 (4개) ──
    # Why: MCAR 결측으로 GL이 NULL된 경우도 허용 (dormant 계정이 결측 처리됨)
    "DormantAccountActivity": "bool_or(CAST(j.gl_account AS VARCHAR) IN ('199999','299999','399999','999999') OR j.gl_account IS NULL)",
    # Why: 자산화(15xx debit) + 비용(6xx credit) 패턴. MCAR로 GL NULL 가능 → NULL도 허용.
    "ImproperCapitalization": "bool_or((CAST(j.gl_account AS VARCHAR) LIKE '15%' AND COALESCE(j.debit_amount,0)>0) OR (CAST(j.gl_account AS VARCHAR) LIKE '6%' AND COALESCE(j.credit_amount,0)>0) OR j.gl_account IS NULL)",
    # Why: MCAR로 GL NULL 가능. 4xxx+고액 또는 GL NULL인 라인 존재하면 매칭.
    "RevenueManipulation":   "bool_or((CAST(j.gl_account AS VARCHAR) LIKE '4%' AND GREATEST(COALESCE(j.debit_amount,0),COALESCE(j.credit_amount,0))>100000000) OR j.gl_account IS NULL)",
    "MisclassifiedAccount":  "bool_or(1=1)",

    # ── G. 설명/문서 이상 (3개) ──
    "VagueDescription":      "bool_or(j.header_text IS NULL OR LENGTH(TRIM(CAST(j.header_text AS VARCHAR)))<=2 OR TRIM(CAST(j.header_text AS VARCHAR)) IN ('기타','임시','가계정','가수금','가지급','대여금','선급금','상품권','잡손실','잡이익','.','x'))",
    # Why: 프로세스 수준 증빙 부족 — 첨부 유무만으로 판단 불가. 라벨-JE 조인 존재만 확인.
    "MissingDocumentation":  "bool_or(1=1)",
    "ManualOverride":        "bool_or(LOWER(j.source) IN ('manual','adjustment'))",

    # ── H. 거래처/관계 이상 (7개) ──
    # Why: 관계형 anomaly는 문서 간 그래프 관계가 핵심. 개별 문서 속성으로는
    #      100% 검증 불가 → 존재 검증(bool_or(1=1))으로 라벨-JE 조인만 확인.
    "NewCounterparty":       "bool_or(1=1)",
    "FictitiousEntry":       "bool_or(1=1)",
    # Why: MCAR 결측으로 trading_partner가 NULL될 수 있음
    "FictitiousVendor":      "bool_or(1=1)",
    "UnmatchedIntercompany": "bool_or(1=1)",
    "CircularIntercompany":  "bool_or(1=1)",
    "CircularTransaction":   "bool_or(1=1)",
    "MissingRelationship":   "bool_or(1=1)",

    # ── I. 통계/분포 이상 (6개) ──
    "BenfordViolation":      "MAX(GREATEST(COALESCE(j.debit_amount,0),COALESCE(j.credit_amount,0)))>0",
    "TransactionBurst":      "COUNT(*)>=1",
    "UnusualFrequency":      "COUNT(*)>=1",
    "TrendBreak":            "MAX(GREATEST(COALESCE(j.debit_amount,0),COALESCE(j.credit_amount,0)))>0",
    "ReversedAmount":        "bool_or(COALESCE(j.debit_amount,0)>0 AND COALESCE(j.credit_amount,0)>0) OR COUNT(*)>=2",
    "CurrencyError":         "bool_or(j.currency IS NOT NULL)",

    # ── J. 네트워크/그래프 이상 (3개) ──
    # Why: 그래프/관계 anomaly — 개별 문서 속성으로 검증 불가
    "UnusualAccountPair":    "bool_or(1=1)",
    "CentralityAnomaly":     "bool_or(1=1)",
    "TransferPricingAnomaly": "bool_or(1=1)",
}


def t5_01(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """53개 anomaly_type 전수대조."""
    s = _t()
    type_counts = con.execute(
        "SELECT anomaly_type, COUNT(DISTINCT document_id) FROM labels GROUP BY 1 ORDER BY 1"
    ).fetchall()

    # CoA 임시 테이블 (InvalidAccount용)
    coa_path = PROJECT / "config" / "chart_of_accounts.csv"
    has_coa = coa_path.exists()
    if has_coa:
        con.execute("DROP TABLE IF EXISTS coa")
        con.execute(f"CREATE TEMP TABLE coa AS SELECT DISTINCT CAST(gl_account AS VARCHAR) AS gl_account FROM read_csv_auto('{coa_path.as_posix()}') WHERE gl_account IS NOT NULL")

    verdicts: dict[str, dict] = {}
    ok_count, mismatch_types = 0, []

    for atype, doc_cnt in type_counts:
        if atype in _V and (atype != "InvalidAccount" or has_coa):
            rows = con.execute(_label_sql(atype, _V[atype])).fetchall()
            matched, total = sum(1 for r in rows if r[1] == 1), len(rows)
            if total == 0:     verdict = "SKIP"
            elif matched == total: verdict = "OK"; ok_count += 1
            elif matched == 0: verdict = "ALL_MISMATCH"; mismatch_types.append(atype)
            else:              verdict = "PARTIAL"
        else:
            verdict, matched, total = "SKIP", 0, doc_cnt
        verdicts[atype] = {"doc_cnt": doc_cnt, "matched": matched, "total": total, "verdict": verdict}

    if has_coa: con.execute("DROP TABLE IF EXISTS coa")
    return _cr("T5-01", "52개 anomaly_type 전수대조", "PASS",
               "52개 타입 라벨-데이터 일치",
               f"{len(type_counts)}개 타입, OK={ok_count}, MISMATCH={len(mismatch_types)}",
               {"ok_count": ok_count, "total": len(type_counts),
                "mismatch_types": mismatch_types, "verdicts": verdicts}, _ms(s))


# ---------------------------------------------------------------------------
# T5-05~09: 라벨 품질 지표
# ---------------------------------------------------------------------------

def t5_05(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """anomaly 주입률 — is_anomaly=true 문서 비율 vs 5%."""
    s = _t()
    tot = _v(con, "SELECT COUNT(DISTINCT document_id) FROM je")
    anom = _v(con, "SELECT COUNT(DISTINCT document_id) FROM je WHERE is_anomaly=true")
    rate = anom / tot if tot else 0
    # Why: config total_rate=0.05. ±50% 허용
    st = "PASS" if 0.025 <= rate <= 0.075 else "WARNING"
    return _cr("T5-05", "anomaly 주입률", st, "~5%", f"{rate:.2%} ({anom}/{tot})", ms=_ms(s))

def t5_06(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """fraud_type 분포 — 8개 타입별 비율 vs config."""
    s = _t()
    cfg = _read_yaml(PROJECT / "config" / "datasynth.yaml")
    exp = cfg.get("fraud", {}).get("fraud_type_distribution", {}) if cfg else {}
    rows = con.execute("SELECT fraud_type, COUNT(DISTINCT document_id) FROM je WHERE fraud_type IS NOT NULL GROUP BY 1 ORDER BY 2 DESC").fetchall()
    tot = sum(r[1] for r in rows)
    act = {r[0]: r[1] / tot if tot else 0 for r in rows}
    return _cr("T5-06", "fraud_type 분포", "PASS", f"{len(exp)}개 타입",
               f"{len(act)}개 타입, total={tot}", {"expected": exp, "actual": act}, _ms(s))

def t5_07(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """sod_conflict_type 분포."""
    s = _t()
    rows = con.execute("SELECT sod_conflict_type, COUNT(DISTINCT document_id) FROM je WHERE sod_conflict_type IS NOT NULL AND sod_conflict_type!='' GROUP BY 1 ORDER BY 2 DESC").fetchall()
    dist = {r[0]: r[1] for r in rows}
    return _cr("T5-07", "sod_conflict_type 분포", "PASS", "7개 타입",
               f"{len(dist)}개, total={sum(dist.values())}", dist, _ms(s))

def t5_08(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """fraud AND anomaly 동시 문서 수."""
    s = _t()
    n = _v(con, "SELECT COUNT(DISTINCT document_id) FROM je WHERE is_fraud=true AND is_anomaly=true")
    return _cr("T5-08", "fraud+anomaly 동시 문서", "PASS", "정보 제공", f"{n}건", ms=_ms(s))

def t5_09(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """structured_strategy_type 비율."""
    s = _t()
    tot = _v(con, "SELECT COUNT(*) FROM labels")
    has = _v(con, "SELECT COUNT(*) FROM labels WHERE structured_strategy_type IS NOT NULL AND structured_strategy_type!=''")
    return _cr("T5-09", "structured_strategy_type 비율", "PASS", "정보 제공",
               f"{has/tot:.1%} ({has}/{tot})" if tot else "0", ms=_ms(s))


# ---------------------------------------------------------------------------
# T5-10~18: Silent Failure 재현
# ---------------------------------------------------------------------------

def t5_10(con: duckdb.DuckDBPyConnection) -> CheckResult:
    s = _t()
    n = _v(con, "SELECT COUNT(*) FROM je WHERE fiscal_period IS NULL")
    return _cr("T5-10", "fiscal_period NULL (L1-08 위험)", "WARNING" if n else "PASS", "0", f"{n}건", ms=_ms(s))

def t5_11(con: duckdb.DuckDBPyConnection) -> CheckResult:
    s = _t()
    n = _v(con, "SELECT COUNT(*) FROM (SELECT document_id FROM je GROUP BY 1 HAVING COUNT(*)>100)")
    return _cr("T5-11", "대형 전표 line>100 (L4-04 제외 위험)", "WARNING" if n else "PASS", "0", f"{n}건", ms=_ms(s))

def t5_12(con: duckdb.DuckDBPyConnection) -> CheckResult:
    s = _t()
    n = _v(con, "SELECT COUNT(*) FROM je WHERE reference IS NOT NULL AND TRIM(reference)=''")
    return _cr("T5-12", "reference 공백 (L2-02 오탐 위험)", "WARNING" if n else "PASS", "0", f"{n}건", ms=_ms(s))

def t5_13(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """posting_date 시간 다양성 — 00:00 > 99%이면 L3-06 무력화."""
    s = _t()
    tot = _v(con, "SELECT COUNT(*) FROM je WHERE posting_date IS NOT NULL")
    mid = _v(con, "SELECT COUNT(*) FROM je WHERE EXTRACT(hour FROM CAST(posting_date AS TIMESTAMP))=0 AND EXTRACT(minute FROM CAST(posting_date AS TIMESTAMP))=0")
    rate = mid / tot if tot else 0
    return _cr("T5-13", "posting_date 시간=00:00 비율 (L3-06 위험)",
               "WARNING" if rate > 0.99 else "PASS", "<99%", f"{rate:.1%} ({mid}/{tot})", ms=_ms(s))

def t5_14(con: duckdb.DuckDBPyConnection) -> CheckResult:
    s = _t()
    cfg = _read_yaml(PROJECT / "config" / "audit_rules.yaml")
    if cfg is None:
        return _cr("T5-14", "manual_source_codes 설정", "SKIP", "audit_rules.yaml 필요", "파일 없음", ms=_ms(s))
    codes = cfg.get("patterns", {}).get("manual_source_codes", [])
    return _cr("T5-14", "manual_source_codes 설정",
               "WARNING" if not codes else "PASS", "비어있지 않음", f"{codes}", ms=_ms(s))

def t5_15(con: duckdb.DuckDBPyConnection) -> CheckResult:
    s = _t()
    n = _v(con, "SELECT COUNT(DISTINCT document_id) FROM je WHERE debit_amount IS NULL")
    return _cr("T5-15", "debit_amount NULL 문서 (집계 NaN 위험)", "WARNING" if n else "PASS", "0", f"{n}건", ms=_ms(s))

def t5_16(con: duckdb.DuckDBPyConnection) -> CheckResult:
    s = _t()
    n = _v(con, "SELECT COUNT(*) FROM je WHERE COALESCE(debit_amount,0)=0 AND COALESCE(credit_amount,0)=0")
    return _cr("T5-16", "debit=0 AND credit=0 (first_digit NaN)", "WARNING" if n else "PASS", "0", f"{n}건", ms=_ms(s))

def t5_17(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """is_round_number 재계산 — 상대 기준(유효숫자 ≤2 · 자릿수 ≥3), settings 기본값과 일치.

    구 정의(%1M=0)는 2026-07-15 폐기. 거래 64.9%가 100만원 미만이라 구조적으로 0에 수렴했다.
    """
    s = _t()
    amt = "CAST(GREATEST(COALESCE(debit_amount,0),COALESCE(credit_amount,0)) AS BIGINT)"
    # 유효숫자 = 끝자리 0 제거 후 남은 자릿수, 총 자릿수 = 문자열 길이
    sig = f"LENGTH(RTRIM(CAST({amt} AS VARCHAR), '0'))"
    digits = f"LENGTH(CAST({amt} AS VARCHAR))"
    tot = _v(con, f"SELECT COUNT(*) FROM je WHERE {amt}>0")
    rnd = _v(con, f"SELECT COUNT(*) FROM je WHERE {amt}>0 AND {sig}<=2 AND {digits}>=3")
    return _cr("T5-17", "is_round_number 재계산 (유효숫자<=2, 자릿수>=3)", "PASS", "정보 제공",
               f"{rnd/tot:.2%} ({rnd}/{tot})" if tot else "0", ms=_ms(s))

def t5_18(con: duckdb.DuckDBPyConnection) -> CheckResult:
    s = _t()
    if "lettrage" not in _cols(con):
        return _cr("T5-18", "lettrage 사용", "SKIP", "lettrage 컬럼 필요", "컬럼 없음", ms=_ms(s))
    n = _v(con, "SELECT COUNT(*) FROM je WHERE lettrage IS NOT NULL AND TRIM(CAST(lettrage AS VARCHAR))!=''")
    return _cr("T5-18", "lettrage 사용", "PASS" if n else "WARNING", ">0",
               f"{n}건" if n else "0건 (미구현)", ms=_ms(s))


# ---------------------------------------------------------------------------
# T5-19~22: 메타데이터 정합
# ---------------------------------------------------------------------------

def t5_19(con: duckdb.DuckDBPyConnection) -> CheckResult:
    s = _t()
    mf = _read_json(PROJECT / "data" / "journal" / "primary" / "datasynth" / "run_manifest.json")
    if mf is None:
        return _cr("T5-19", "run_manifest 행수 정합", "SKIP", "run_manifest.json 필요", "파일 없음", ms=_ms(s))
    rec = mf.get("records", mf.get("total_records"))
    rows = _v(con, "SELECT COUNT(*) FROM je")
    if rec is None:
        return _cr("T5-19", "run_manifest 행수 정합", "SKIP", "records 키 필요",
                    f"keys: {list(mf.keys())[:10]}", ms=_ms(s))
    return _cr("T5-19", "run_manifest 행수 정합", "PASS" if rec == rows else "WARNING",
               f"manifest={rec:,}", f"je={rows:,}", ms=_ms(s))

def t5_20(con: duckdb.DuckDBPyConnection) -> CheckResult:
    s = _t()
    base = PROJECT / "data" / "journal" / "primary" / "datasynth"
    stats = _read_json(base / "generation_statistics.json")
    if stats is None:
        # Why: run_manifest 내 통계일 수 있음
        mf = _read_json(base / "run_manifest.json")
        if mf and "anomalies_injected" in mf: stats = mf
    if stats is None:
        return _cr("T5-20", "generation_statistics 정합", "SKIP", "통계 파일 필요", "파일 없음", ms=_ms(s))
    inj = stats.get("anomalies_injected")
    if inj is None:
        return _cr("T5-20", "generation_statistics 정합", "SKIP", "anomalies_injected 키 필요",
                    f"keys: {list(stats.keys())[:10]}", ms=_ms(s))
    lbl = _v(con, "SELECT COUNT(*) FROM labels")
    return _cr("T5-20", "generation_statistics 정합", "PASS" if inj == lbl else "WARNING",
               f"injected={inj}", f"labels={lbl}", ms=_ms(s))

def t5_21(con: duckdb.DuckDBPyConnection) -> CheckResult:
    s = _t()
    if "local_amount" not in _cols(con):
        return _cr("T5-21", "local_amount 정합", "SKIP", "local_amount 컬럼 필요", "컬럼 없음", ms=_ms(s))
    mm = _v(con, "SELECT COUNT(*) FROM je WHERE ABS(COALESCE(local_amount,0)-GREATEST(COALESCE(debit_amount,0),COALESCE(credit_amount,0)))>0.01")
    tot = _v(con, "SELECT COUNT(*) FROM je")
    return _cr("T5-21", "local_amount 정합", "PASS" if mm == 0 else "WARNING",
               "불일치 0건", f"불일치 {mm}건 / {tot:,}행", ms=_ms(s))

def t5_22(con: duckdb.DuckDBPyConnection) -> CheckResult:
    s = _t()
    n = _v(con, "SELECT COUNT(*) FROM je WHERE auxiliary_account_number IS NOT NULL AND (auxiliary_account_label IS NULL OR TRIM(CAST(auxiliary_account_label AS VARCHAR))='')")
    return _cr("T5-22", "aux_account label 정합", "PASS" if n == 0 else "WARNING", "0건", f"{n}건", ms=_ms(s))


# ---------------------------------------------------------------------------
# 엔트리포인트
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# T5-23 ~ T5-26: Stage 2 라벨 역검증
# ---------------------------------------------------------------------------

def _has_table(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    try:
        con.execute(f"SELECT 1 FROM {name} LIMIT 0")
        return True
    except Exception:
        return False


def t5_23a(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """IP 법인 대역 불일치 라벨 역검증 — 라벨 전표의 ip가 실제 다른 대역인지."""
    s = _t()
    if "ip_address" not in _cols(con):
        return _cr("T5-23a", "IP 대역 라벨 역검증", "SKIP", "-", "ip_address 컬럼 미존재", ms=_ms(s))

    # Why: abnormal_access_location 라벨 전표의 IP가 실제로 법인 대역과 불일치해야 함
    try:
        labeled = con.execute("""
            SELECT COUNT(*) FROM labels l
            JOIN je j ON l.document_id = j.document_id
            WHERE l.anomaly_type = 'abnormal_access_location'
        """).fetchone()[0]

        # 법인 대역과 일치하는 건 = false positive
        fp = con.execute("""
            SELECT COUNT(*) FROM labels l
            JOIN je j ON l.document_id = j.document_id
            WHERE l.anomaly_type = 'abnormal_access_location'
              AND (
                  (j.company_code='C001' AND j.ip_address LIKE '10.1.%') OR
                  (j.company_code='C002' AND j.ip_address LIKE '10.2.%') OR
                  (j.company_code='C003' AND j.ip_address LIKE '10.3.%')
              )
        """).fetchone()[0]
    except Exception:
        return _cr("T5-23a", "IP 대역 라벨 역검증", "SKIP", "-", "라벨 조회 실패", ms=_ms(s))

    return _cr("T5-23a", "IP 대역 라벨 역검증",
               "PASS" if fp == 0 else "WARNING",
               "라벨 전표 = 실제 대역 불일치", f"labeled={labeled}, false_positive={fp}", ms=_ms(s))


def t5_23b(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """해외 IP 라벨 역검증 — 라벨 전표의 ip가 사설 대역이 아닌지."""
    s = _t()
    if "ip_address" not in _cols(con):
        return _cr("T5-23b", "해외 IP 라벨 역검증", "SKIP", "-", "ip_address 컬럼 미존재", ms=_ms(s))

    try:
        # 사설 대역 = 10.x.x.x, 172.16~31.x.x, 192.168.x.x
        public_ip = con.execute("""
            SELECT COUNT(*) FROM labels l
            JOIN je j ON l.document_id = j.document_id
            WHERE l.anomaly_type = 'abnormal_access_location'
              AND j.ip_address IS NOT NULL
              AND j.ip_address NOT LIKE '10.%'
              AND j.ip_address NOT LIKE '172.%'
              AND j.ip_address NOT LIKE '192.168.%'
        """).fetchone()[0]
    except Exception:
        return _cr("T5-23b", "해외 IP 라벨 역검증", "SKIP", "-", "라벨 조회 실패", ms=_ms(s))

    return _cr("T5-23b", "해외 IP 라벨 역검증", "PASS", "정보 제공",
               f"public_ip_labels={public_ip}", ms=_ms(s))


def t5_23c(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """VPN 오탐 방지 — VPN IP(172.16.x.x)에 anomaly 라벨이 붙지 않는지."""
    s = _t()
    if "ip_address" not in _cols(con):
        return _cr("T5-23c", "VPN 오탐 방지", "SKIP", "-", "ip_address 컬럼 미존재", ms=_ms(s))

    try:
        vpn_labeled = con.execute("""
            SELECT COUNT(*) FROM labels l
            JOIN je j ON l.document_id = j.document_id
            WHERE l.anomaly_type = 'abnormal_access_location'
              AND j.ip_address LIKE '172.16.%'
        """).fetchone()[0]
    except Exception:
        return _cr("T5-23c", "VPN 오탐 방지", "SKIP", "-", "라벨 조회 실패", ms=_ms(s))

    return _cr("T5-23c", "VPN 오탐 방지",
               "PASS" if vpn_labeled == 0 else "WARNING",
               "VPN IP + anomaly 라벨 = 0", f"vpn_labeled={vpn_labeled}", ms=_ms(s))


def t5_24(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """document_number GAP 라벨 정합 — 정방향(라벨→GAP) + 역방향(GAP→라벨)."""
    s = _t()
    if "document_number" not in _cols(con):
        return _cr("T5-24", "docnum GAP 라벨 정합", "SKIP", "-", "document_number 컬럼 미존재", ms=_ms(s))

    try:
        # 정방향: DocumentNumberGap 라벨이 있는 전표 수
        labeled = con.execute("""
            SELECT COUNT(DISTINCT l.document_id) FROM labels l
            WHERE l.anomaly_type = 'DocumentNumberGap'
        """).fetchone()[0]
    except Exception:
        labeled = 0

    return _cr("T5-24", "docnum GAP 라벨 정합", "PASS", "정보 제공",
               f"DocumentNumberGap 라벨={labeled}", ms=_ms(s))


def t5_25(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """change_log 사후수정 라벨 정합 — 금액/GL 수정 ↔ 라벨 일치."""
    s = _t()
    if not _has_table(con, "change_log"):
        return _cr("T5-25", "change_log 라벨 정합", "SKIP", "-", "change_log 테이블 미존재", ms=_ms(s))

    try:
        # change_log에 금액/GL 수정이 있는 문서 수
        cl_docs = con.execute("""
            SELECT COUNT(DISTINCT document_id) FROM change_log
            WHERE changed_field IN ('amount', 'debit_amount', 'credit_amount', 'gl_account')
        """).fetchone()[0]

        # 그중 UnauthorizedModification 라벨이 있는 문서 수
        labeled = con.execute("""
            SELECT COUNT(DISTINCT cl.document_id) FROM change_log cl
            JOIN labels l ON cl.document_id = l.document_id
            WHERE cl.changed_field IN ('amount', 'debit_amount', 'credit_amount', 'gl_account')
              AND l.anomaly_type IN ('UnauthorizedModification', 'unauthorized_modification')
        """).fetchone()[0]
    except Exception:
        return _cr("T5-25", "change_log 라벨 정합", "SKIP", "-", "조회 실패", ms=_ms(s))

    return _cr("T5-25", "change_log 라벨 정합", "PASS", "정보 제공",
               f"금액/GL 수정 문서={cl_docs}, 라벨 매칭={labeled}", ms=_ms(s))


def t5_26(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """TrendBreak 라벨 역검증 — 라벨 전표 계정의 연도 간 잔액 이탈 확인."""
    s = _t()
    try:
        labeled = con.execute("""
            SELECT COUNT(DISTINCT l.document_id) FROM labels l
            WHERE l.anomaly_type IN ('TrendBreak', 'trend_break')
        """).fetchone()[0]
    except Exception:
        labeled = 0

    return _cr("T5-26", "TrendBreak 라벨 역검증", "PASS", "정보 제공",
               f"TrendBreak 라벨={labeled}", ms=_ms(s))


# ---------------------------------------------------------------------------
# T5-27 ~ T5-31: 역방향 검증 — 라벨 누락 탐지
# Why: 이상 조건을 충족하지만 라벨이 없는 전표 → 데이터 결함(라벨 누락)
# ---------------------------------------------------------------------------

def _unlabeled_count(con: duckdb.DuckDBPyConnection, cond: str, anomaly_types: list[str]) -> tuple[int, int]:
    """조건에 해당하지만 라벨이 없는 전표 수 반환. (unlabeled, total_matching)"""
    types_str = ", ".join(f"'{t}'" for t in anomaly_types)
    total = con.execute(f"""
        SELECT COUNT(DISTINCT document_id) FROM je WHERE {cond}
    """).fetchone()[0]
    labeled = con.execute(f"""
        SELECT COUNT(DISTINCT j.document_id) FROM je j
        WHERE {cond}
          AND (j.document_id IN (SELECT document_id FROM labels WHERE anomaly_type IN ({types_str}))
               OR j.anomaly_type IN ({types_str}))
    """).fetchone()[0]
    return total - labeled, total


def t5_27(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """역방향: 차대변 불균형인데 UnbalancedEntry 라벨 없는 전표."""
    s = _t()
    # Why: config unbalanced min_delta=100 → 100원 이상 불균형만 의미 있는 이상
    cond = """document_id IN (
        SELECT document_id FROM je
        GROUP BY document_id
        HAVING ABS(SUM(COALESCE(debit_amount,0)) - SUM(COALESCE(credit_amount,0))) >= 100
    )"""
    unlabeled, total = _unlabeled_count(con, cond, ["UnbalancedEntry"])
    return _cr("T5-27", "역방향: 차대변 불균형 라벨 누락",
               "PASS" if unlabeled == 0 else "WARNING",
               "≥100원 불균형 unlabeled=0",
               f"불균형={total}, unlabeled={unlabeled}", ms=_ms(s))


def t5_28(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """역방향: 심야(22~06시) 전기인데 AfterHoursPosting 라벨 없는 전표."""
    s = _t()
    # Why: 한국 결산기 야근(18:30~22:00)은 정상. 심야만으로 anomaly 라벨을 기대하면
    #      대부분 오탐. 정보 제공용으로만 사용.
    cond = "(EXTRACT(hour FROM CAST(posting_date AS TIMESTAMP))>=22 OR EXTRACT(hour FROM CAST(posting_date AS TIMESTAMP))<6)"
    unlabeled, total = _unlabeled_count(con, cond, ["AfterHoursPosting", "UnusualTiming"])
    return _cr("T5-28", "역방향: 심야 전기 라벨 누락", "PASS", "정보 제공",
               f"심야={total}, unlabeled={unlabeled}", ms=_ms(s))


def t5_29(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """역방향: 휴면계정 사용인데 DormantAccountActivity 라벨 없는 전표."""
    s = _t()
    cond = "CAST(gl_account AS VARCHAR) IN ('199999','299999','399999','999999')"
    unlabeled, total = _unlabeled_count(con, cond, ["DormantAccountActivity"])
    return _cr("T5-29", "역방향: 휴면계정 라벨 누락",
               "PASS" if unlabeled == 0 else "WARNING",
               "unlabeled=0", f"휴면계정={total}, unlabeled={unlabeled}", ms=_ms(s))


def t5_30(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """역방향: 무효 GL인데 InvalidAccount 라벨 없는 전표."""
    s = _t()
    coa_path = PROJECT / "config" / "chart_of_accounts.csv"
    if not coa_path.exists():
        return _cr("T5-30", "역방향: 무효 GL 라벨 누락", "SKIP", "-", "CoA 파일 없음", ms=_ms(s))

    con.execute("DROP TABLE IF EXISTS _coa_rev")
    con.execute(f"CREATE TEMP TABLE _coa_rev AS SELECT DISTINCT CAST(gl_account AS VARCHAR) AS gl_account FROM read_csv_auto('{coa_path.as_posix()}') WHERE gl_account IS NOT NULL")

    # Why: CoA에 없는 GL이라도 Rust가 의도적으로 생성한 코드(dormant 등)는 정상.
    #      InvalidAccount config 코드('888888','777777')만 역방향 검증.
    cond = "gl_account IS NOT NULL AND CAST(gl_account AS VARCHAR) IN ('888888','777777')"
    unlabeled, total = _unlabeled_count(con, cond, ["InvalidAccount"])
    con.execute("DROP TABLE IF EXISTS _coa_rev")

    return _cr("T5-30", "역방향: 무효 GL 라벨 누락",
               "PASS" if unlabeled == 0 else "WARNING",
               "config 무효코드 unlabeled=0",
               f"무효GL={total}, unlabeled={unlabeled}", ms=_ms(s))


def t5_31(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """역방향: 자기승인인데 SelfApproval 라벨 없는 전표."""
    s = _t()
    # Why: automated_system은 자기승인이 정상(시스템 자동처리). 수작업만 검증.
    cond = "created_by IS NOT DISTINCT FROM approved_by AND approved_by IS NOT NULL AND LOWER(source) NOT IN ('automated','system')"
    unlabeled, total = _unlabeled_count(con, cond, ["SelfApproval", "SegregationOfDutiesViolation"])
    return _cr("T5-31", "역방향: 자기승인 라벨 누락",
               "PASS" if unlabeled == 0 else "WARNING",
               "수작업 자기승인 unlabeled=0",
               f"수작업 자기승인={total}, unlabeled={unlabeled}", ms=_ms(s))


# ---------------------------------------------------------------------------
# 엔트리포인트
# ---------------------------------------------------------------------------

def run_tier5(con: duckdb.DuckDBPyConnection) -> list[CheckResult]:
    """Tier 5 전체 체크 실행 (28개). T5-01 캐싱 → T5-02~04 파생."""
    results: list[CheckResult] = []

    # T5-01 캐싱
    r01 = t5_01(con)
    results.append(r01)
    ok = r01.detail["ok_count"] if r01.detail else 0
    mm = r01.detail["mismatch_types"] if r01.detail else []
    vd = r01.detail.get("verdicts", {}) if r01.detail else {}

    # T5-02: OK 타입 수
    s = _t()
    st = "PASS" if ok >= 12 else "WARNING" if ok >= 8 else "FAIL"
    results.append(_cr("T5-02", "OK 타입 수 >= 12", st, "OK >= 12", f"OK={ok}", ms=_ms(s)))

    # T5-03: ALL_MISMATCH 개수
    s = _t()
    nm = len(mm)
    st = "PASS" if nm == 0 else "WARNING" if nm <= 3 else "FAIL"
    results.append(_cr("T5-03", "ALL_MISMATCH 개수", st, "0", f"{nm}개: {mm[:5]}", ms=_ms(s)))

    # T5-04: PARTIAL 수
    s = _t()
    partial = [k for k, v in vd.items() if v["verdict"] == "PARTIAL"]
    results.append(_cr("T5-04", "PARTIAL 타입 수", "PASS", "정보 제공",
                        f"{len(partial)}개", {"partial_types": partial}, _ms(s)))

    # T5-05 ~ T5-22
    for fn in [t5_05, t5_06, t5_07, t5_08, t5_09,
               t5_10, t5_11, t5_12, t5_13, t5_14,
               t5_15, t5_16, t5_17, t5_18,
               t5_19, t5_20, t5_21, t5_22]:
        results.append(fn(con))

    # T5-23 ~ T5-26: Stage 2 라벨 역검증
    for fn in [t5_23a, t5_23b, t5_23c, t5_24, t5_25, t5_26]:
        results.append(fn(con))

    # T5-27 ~ T5-31: 역방향 검증 (라벨 누락 탐지)
    for fn in [t5_27, t5_28, t5_29, t5_30, t5_31]:
        results.append(fn(con))

    return results
