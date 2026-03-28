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
_V: dict[str, str] = {
    "UnbalancedEntry":       "ABS(SUM(j.debit_amount)-SUM(j.credit_amount))>1",
    "MissingField":          "bool_or(j.posting_date IS NULL OR j.gl_account IS NULL OR j.debit_amount IS NULL OR j.credit_amount IS NULL)",
    "InvalidAccount":        "bool_or(CAST(j.gl_account AS VARCHAR) NOT IN (SELECT CAST(gl_account AS VARCHAR) FROM coa))",
    "BackdatedEntry":        "bool_or(ABS(DATE_DIFF('day',CAST(j.posting_date AS DATE),CAST(j.document_date AS DATE)))>30)",
    "AfterHoursPosting":     "bool_or(EXTRACT(hour FROM CAST(j.posting_date AS TIMESTAMP))>=22 OR EXTRACT(hour FROM CAST(j.posting_date AS TIMESTAMP))<6)",
    "WeekendPosting":        "bool_or(EXTRACT(dow FROM CAST(j.posting_date AS TIMESTAMP)) IN (0,6))",
    "SelfApproval":          "bool_or(j.created_by=j.approved_by)",
    "SkippedApproval":       "bool_and(j.approved_by IS NULL)",
    "WrongPeriod":           "bool_or(j.fiscal_period!=EXTRACT(month FROM CAST(j.posting_date AS DATE)))",
    "DormantAccountActivity": "bool_or(CAST(j.gl_account AS VARCHAR) IN ('199999','299999','399999','999999'))",
    "ImproperCapitalization": "bool_or(CAST(j.gl_account AS VARCHAR) LIKE '15%' AND COALESCE(j.debit_amount,0)>0) AND bool_or(CAST(j.gl_account AS VARCHAR) LIKE '6%' AND COALESCE(j.credit_amount,0)>0)",
    "RevenueManipulation":   "bool_or(CAST(j.gl_account AS VARCHAR) LIKE '4%' AND GREATEST(COALESCE(j.debit_amount,0),COALESCE(j.credit_amount,0))>100000000)",
    "JustBelowThreshold":    "MAX(GREATEST(COALESCE(j.debit_amount,0),COALESCE(j.credit_amount,0))) BETWEEN 9000000 AND 9999999 OR MAX(GREATEST(COALESCE(j.debit_amount,0),COALESCE(j.credit_amount,0))) BETWEEN 90000000 AND 99999999 OR MAX(GREATEST(COALESCE(j.debit_amount,0),COALESCE(j.credit_amount,0))) BETWEEN 900000000 AND 999999999",
    "ExceededApprovalLimit": "MAX(GREATEST(COALESCE(j.debit_amount,0),COALESCE(j.credit_amount,0)))>=10000000",
    "ManualOverride":        "bool_or(LOWER(j.source) IN ('manual','adjustment'))",
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
    return _cr("T5-01", "53개 anomaly_type 전수대조", "PASS",
               "핵심 15개 타입 라벨-데이터 일치",
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
    return _cr("T5-10", "fiscal_period NULL (C05 위험)", "WARNING" if n else "PASS", "0", f"{n}건", ms=_ms(s))

def t5_11(con: duckdb.DuckDBPyConnection) -> CheckResult:
    s = _t()
    n = _v(con, "SELECT COUNT(*) FROM (SELECT document_id FROM je GROUP BY 1 HAVING COUNT(*)>100)")
    return _cr("T5-11", "대형 전표 line>100 (C09 제외 위험)", "WARNING" if n else "PASS", "0", f"{n}건", ms=_ms(s))

def t5_12(con: duckdb.DuckDBPyConnection) -> CheckResult:
    s = _t()
    n = _v(con, "SELECT COUNT(*) FROM je WHERE reference IS NOT NULL AND TRIM(reference)=''")
    return _cr("T5-12", "reference 공백 (B04 오탐 위험)", "WARNING" if n else "PASS", "0", f"{n}건", ms=_ms(s))

def t5_13(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """posting_date 시간 다양성 — 00:00 > 99%이면 C03 무력화."""
    s = _t()
    tot = _v(con, "SELECT COUNT(*) FROM je WHERE posting_date IS NOT NULL")
    mid = _v(con, "SELECT COUNT(*) FROM je WHERE EXTRACT(hour FROM CAST(posting_date AS TIMESTAMP))=0 AND EXTRACT(minute FROM CAST(posting_date AS TIMESTAMP))=0")
    rate = mid / tot if tot else 0
    return _cr("T5-13", "posting_date 시간=00:00 비율 (C03 위험)",
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
    s = _t()
    tot = _v(con, "SELECT COUNT(*) FROM je WHERE GREATEST(COALESCE(debit_amount,0),COALESCE(credit_amount,0))>0")
    rnd = _v(con, "SELECT COUNT(*) FROM je WHERE GREATEST(COALESCE(debit_amount,0),COALESCE(credit_amount,0))>0 AND CAST(GREATEST(COALESCE(debit_amount,0),COALESCE(credit_amount,0)) AS BIGINT)%1000000=0")
    return _cr("T5-17", "is_round_number 재계산 (%1M=0)", "PASS", "정보 제공",
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

def run_tier5(con: duckdb.DuckDBPyConnection) -> list[CheckResult]:
    """Tier 5 전체 체크 실행 (22개). T5-01 캐싱 → T5-02~04 파생."""
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
    return results
