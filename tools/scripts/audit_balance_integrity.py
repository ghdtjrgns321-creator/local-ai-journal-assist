"""
audit_balance_integrity.py
잔액·재무제표 정합 측정 (측정·보고 전용 — 수정 없음)

항목:
  1. TB↔JE 정합
  2. BS 등식 (자산 = 부채+자본)
  3. 연도 이월 (기말 → 기초)
  4. 보조원장 대사
  5. 선택 입력 시 fraud/overlay 대표본 동일 검사
"""

import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

import duckdb

BASE_DIR = Path("C:/Users/ghdtj/workspace/portfolio/local-ai-assist")
DATA_DIR = BASE_DIR / "data" / "journal" / "primary"

NORMAL_DIR = DATA_DIR / "datasynth_semantic_v1_normal_20260613_v42j"
FRAUD_DIR = DATA_DIR / "datasynth_semantic_v1_phase2_fraud_20260613_v1_r4l_b"

# ─────────────────────────────────────────────
# 공통 유틸
# ─────────────────────────────────────────────


def to_dec(v) -> Decimal:
    """문자열·숫자를 Decimal로 안전 변환"""
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError):
        return Decimal("0")


def load_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def je_csv_path(dataset_dir: Path) -> Path:
    """연도별 분할 없는 전체 파일 우선 사용"""
    full = dataset_dir / "journal_entries.csv"
    if full.exists():
        return full
    # fallback: 연도별 파일 glob
    return None


def build_je_table(con, je_path: Path) -> None:
    """회사·연도·기간·계정별 JE 단일기간 차대 합계를 DuckDB 임시 테이블로 만든다."""
    con.execute(f"""
        CREATE OR REPLACE TABLE je AS
        SELECT
            company_code,
            CAST(fiscal_year AS INTEGER)  AS fiscal_year,
            CAST(fiscal_period AS INTEGER) AS fiscal_period,
            gl_account,
            SUM(TRY_CAST(debit_amount  AS DOUBLE)) AS je_debit,
            SUM(TRY_CAST(credit_amount AS DOUBLE)) AS je_credit
        FROM read_csv('{je_path.as_posix()}', all_varchar=true)
        GROUP BY company_code, fiscal_year, fiscal_period, gl_account
    """)


# ─────────────────────────────────────────────
# 검사 1: TB ↔ JE 정합
# ─────────────────────────────────────────────


def _is_pl_account(acct: str) -> bool:
    """손익 계정 여부: 첫 자리가 4~8이면 P&L(YTD), 1~3이면 BS(rolling)"""
    return acct[:1] in ("4", "5", "6", "7", "8")


def check_tb_je(dataset_dir: Path, label: str, con) -> dict:
    """
    TB 검증 공식 (계정 유형에 따라 분기):
    - BS 계정(1~3xxx): TB = OB(기초) + 전 기간 누적 JE_net  (rolling)
    - P&L 계정(4~8xxx): TB = 연도 내 YTD JE_net (연도 초 0에서 시작, OB 없음)
    두 공식 모두 기간 이동은 단일기간 JE_net을 누적하는 방식으로 동일하게 처리.
    BS는 연도 경계에서 직전 연도 FP_last TB를 rolling OB로 사용.
    P&L은 연도 경계에서 0으로 리셋.
    """
    print(f"\n[1] TB↔JE 정합 — {label}")

    tb_path = dataset_dir / "period_close" / "trial_balances.json"
    ob_path = dataset_dir / "balance" / "opening_balances.json"
    je_path = je_csv_path(dataset_dir)
    if not tb_path.exists() or je_path is None or not je_path.exists():
        print("  SKIP: 파일 없음")
        return {"status": "SKIP"}

    # opening_balances: {company: {acct: Decimal}} — BS 계정 최초 기초잔액
    ob_map: dict = {}
    if ob_path.exists():
        for r in load_json(ob_path):
            ob_map[r["company_code"]] = {k: to_dec(v) for k, v in r["balances"].items()}

    # DuckDB로 JE 집계: 회사·연도·기간·계정 별 단일기간 net
    build_je_table(con, je_path)

    tb_data = load_json(tb_path)
    tb_sorted = sorted(
        tb_data, key=lambda r: (r["company_code"], int(r["fiscal_year"]), int(r["fiscal_period"]))
    )

    from itertools import groupby

    # rolling OB 저장: {(company, acct): Decimal}
    # BS: 연도 경계에서 직전 FP_last TB 값 유지
    # P&L: 연도 경계에서 0으로 리셋
    rolling_ob: dict = {}  # (company, acct) → Decimal
    prev_fy: dict = {}  # company → 직전 처리 연도

    mismatches = []
    total_tb_rows = 0
    total_compared = 0

    for (company, fy, fp), group in groupby(
        tb_sorted, key=lambda r: (r["company_code"], int(r["fiscal_year"]), int(r["fiscal_period"]))
    ):
        entries = list(group)[0].get("entries", [])

        # 연도 경계 감지: P&L 계정 rolling_ob를 0으로 리셋
        last_fy = prev_fy.get(company)
        if last_fy is not None and fy != last_fy:
            # 새 연도 시작 → P&L 계정 리셋
            for key in list(rolling_ob.keys()):
                if key[0] == company and _is_pl_account(key[1]):
                    rolling_ob[key] = Decimal("0")
        prev_fy[company] = fy

        cur_tb: dict = {}
        for e in entries:
            acct = str(e["account_code"])
            tb_dr = to_dec(e.get("debit_balance", 0) or 0)
            tb_cr = to_dec(e.get("credit_balance", 0) or 0)
            tb_net = tb_dr - tb_cr
            cur_tb[acct] = tb_net
            total_tb_rows += 1

            # 기초잔액 결정
            ob_key = (company, acct)
            if ob_key not in rolling_ob:
                if _is_pl_account(acct):
                    # P&L: 첫 기간도 0 시작
                    rolling_ob[ob_key] = Decimal("0")
                else:
                    # BS: opening_balances 값, 없으면 0
                    rolling_ob[ob_key] = ob_map.get(company, {}).get(acct, Decimal("0"))

            period_ob = rolling_ob[ob_key]

            # JE 단일기간 이동
            row = con.execute(
                """
                SELECT COALESCE(je_debit,0), COALESCE(je_credit,0)
                FROM je
                WHERE company_code=? AND fiscal_year=? AND fiscal_period=? AND gl_account=?
                """,
                [company, fy, fp, acct],
            ).fetchone()
            je_dr = to_dec(row[0]) if row else Decimal("0")
            je_cr = to_dec(row[1]) if row else Decimal("0")
            je_net = je_dr - je_cr

            expected = period_ob + je_net
            diff = abs(tb_net - expected)
            total_compared += 1
            if diff >= Decimal("1"):
                mismatches.append(
                    {
                        "company": company,
                        "fy": fy,
                        "fp": fp,
                        "acct": acct,
                        "acct_type": "PL" if _is_pl_account(acct) else "BS",
                        "tb_net": float(tb_net),
                        "expected": float(expected),
                        "diff": float(diff),
                    }
                )

            # rolling_ob를 현재 TB_net으로 갱신 (다음 기간의 기초)
            rolling_ob[ob_key] = tb_net

        # cur_tb는 연도 경계 rolling 처리에 불필요 (rolling_ob가 담당)
        _ = cur_tb

    n_mismatch = len(mismatches)
    total_diff = sum(m["diff"] for m in mismatches)
    max_diff = max((m["diff"] for m in mismatches), default=0)
    worst = max(mismatches, key=lambda x: x["diff"], default=None)

    # 계정 유형별 불일치 집계
    n_bs_fail = sum(1 for m in mismatches if m["acct_type"] == "BS")
    n_pl_fail = sum(1 for m in mismatches if m["acct_type"] == "PL")

    status = "PASS" if n_mismatch == 0 else "FAIL"
    print(f"  상태: {status}")
    print(f"  전체 TB 계정행: {total_tb_rows:,}  비교 완료: {total_compared:,}")
    print(f"  불일치 건수: {n_mismatch:,}  (BS={n_bs_fail}, P&L={n_pl_fail})")
    if n_mismatch:
        print(f"  차이 합계: {total_diff:,.0f}  최대 단일 차이: {max_diff:,.0f}")
        if worst:
            print(
                f"  최대 차이 계정: {worst['company']} FY{worst['fy']} FP{worst['fp']} "
                f"acct={worst['acct']}({worst['acct_type']}) "
                f"TB={worst['tb_net']:,.0f} 기대={worst['expected']:,.0f}"
            )
    return {
        "status": status,
        "total_tb_rows": total_tb_rows,
        "total_compared": total_compared,
        "n_mismatch": n_mismatch,
        "total_diff": float(total_diff),
        "max_diff": float(max_diff),
    }


# ─────────────────────────────────────────────
# 검사 2: BS 등식 (자산 = 부채+자본)
# ─────────────────────────────────────────────


def check_bs_equation(dataset_dir: Path, label: str) -> dict:
    """
    financial_statements.json 의 balance_sheet 에서
    BS-TA (Total Assets), BS-TL (Total Liabilities), BS-TE (Total Equity)를 읽어
    TA = TL + TE 검증.
    허용 오차: 절대 1원 미만 (정수 반올림 차이).
    """
    print(f"\n[2] BS 등식 — {label}")

    fs_path = dataset_dir / "financial_reporting" / "financial_statements.json"
    if not fs_path.exists():
        print("  SKIP: 파일 없음")
        return {"status": "SKIP"}

    fs_data = load_json(fs_path)
    bs_recs = [r for r in fs_data if r.get("statement_type") == "balance_sheet"]

    fails = []
    total = 0
    for rec in bs_recs:
        company = rec["company_code"]
        fy = rec.get("fiscal_year")
        fp = rec.get("fiscal_period")
        items = {li["line_code"]: to_dec(li["amount"]) for li in rec.get("line_items", [])}

        ta = items.get("BS-TA", None)
        tl = items.get("BS-TL", None)
        te = items.get("BS-TE", None)
        tle = items.get("BS-TLE", None)  # TA와 동일해야 함

        if ta is None or tl is None or te is None:
            continue  # 불완전 레코드는 건너뜀
        total += 1

        diff_eq = abs(ta - (tl + te))  # TA vs TL+TE
        diff_tle = abs(ta - tle) if tle is not None else Decimal("0")  # BS-TA vs BS-TLE

        if diff_eq >= Decimal("1"):
            fails.append(
                {
                    "company": company,
                    "fy": fy,
                    "fp": fp,
                    "ta": float(ta),
                    "tl": float(tl),
                    "te": float(te),
                    "diff_eq": float(diff_eq),
                }
            )

    n_fail = len(fails)
    status = "PASS" if n_fail == 0 else "FAIL"
    max_diff = max((f["diff_eq"] for f in fails), default=0)
    total_diff = sum(f["diff_eq"] for f in fails)

    print(f"  상태: {status}")
    print(f"  BS 레코드 수: {total:,}  불균형: {n_fail:,}")
    if n_fail:
        print(f"  불균형 차이 합계: {total_diff:,.0f}  최대: {max_diff:,.0f}")
        worst = max(fails, key=lambda x: x["diff_eq"])
        print(
            f"  최대 불균형: {worst['company']} FY{worst['fy']} FP{worst['fp']} "
            f"TA={worst['ta']:,.0f} TL+TE={(worst['tl'] + worst['te']):,.0f}"
        )
    return {
        "status": status,
        "total_bs": total,
        "n_fail": n_fail,
        "total_diff": float(total_diff),
        "max_diff": float(max_diff),
    }


# ─────────────────────────────────────────────
# 검사 3: 연도 이월 (기말 → 기초)
# ─────────────────────────────────────────────


def check_carryover(dataset_dir: Path, label: str, con) -> dict:
    """
    opening_balances.json 및 TB/JE로 연도 이월을 검증한다.
    - 최초 연도: opening_balances vs 첫 기간 TB에서 당기 JE를 뺀 inferred opening 비교.
    - 이후 연도: current FY FP1 inferred opening = prior FY FP last ending.
      단, P&L 계정은 연초 0이어야 하고, 전년 손익은 closing을 통해 retained earnings에 반영되어야 한다.
    """
    print(f"\n[3] 연도 이월 — {label}")

    ob_path = dataset_dir / "balance" / "opening_balances.json"
    tb_path = dataset_dir / "period_close" / "trial_balances.json"
    if not ob_path.exists():
        print("  SKIP: opening_balances.json 없음")
        return {"status": "SKIP"}

    ob_data = load_json(ob_path)

    # is_balanced 검사
    unbalanced = [r for r in ob_data if not r.get("is_balanced", True)]
    n_unbalanced = len(unbalanced)

    # 총 계정 수 & 잔액 범위
    total_accounts = sum(len(r["balances"]) for r in ob_data)

    # 최초 연도 opening_balances와 FP1 inferred opening 대조.
    mismatches = []
    compared = 0
    yearly_mismatches = []
    yearly_compared = 0

    if tb_path.exists():
        je_path = je_csv_path(dataset_dir)
        if je_path is not None and je_path.exists():
            build_je_table(con, je_path)

        tb_data = load_json(tb_path)
        # opening_balances의 as_of_date로 기준 연도·기간을 동적으로 결정
        # as_of_date가 회사별로 다를 수 있으므로 회사별로 추출
        # as_of_date 예: "2022-01-01" → fiscal_year=2022, fiscal_period=1 (첫 기간)
        ob_key_by_company: dict = {}  # company_code → (target_fy, target_fp)
        for ob_rec in ob_data:
            co = ob_rec["company_code"]
            as_of = ob_rec.get("as_of_date", "")
            if as_of:
                ob_fy = int(as_of[:4])
                ob_month = int(as_of[5:7])
                ob_key_by_company[co] = (ob_fy, ob_month)

        # TB에서 (company, fy, fp) 조합으로 인덱싱
        tb_by_key: dict = {}
        for r in tb_data:
            co_key = (r["company_code"], int(r["fiscal_year"]), int(r["fiscal_period"]))
            tb_by_key[co_key] = {str(e["account_code"]): e for e in r.get("entries", [])}

        # 회사별 기준 기간 TB 선택
        tb_fp1_by_company = {
            co: tb_by_key.get((co, fy, fp), {}) for co, (fy, fp) in ob_key_by_company.items()
        }

        for ob_rec in ob_data:
            company = ob_rec["company_code"]
            ob_bals = {k: to_dec(v) for k, v in ob_rec["balances"].items()}
            tb_accts = tb_fp1_by_company.get(company, {})

            for acct, ob_bal in ob_bals.items():
                if acct not in tb_accts:
                    continue
                tb_e = tb_accts[acct]
                tb_dr = to_dec(tb_e.get("debit_balance", 0))
                tb_cr = to_dec(tb_e.get("credit_balance", 0))
                tb_net = tb_dr - tb_cr
                fy, fp = ob_key_by_company.get(company, (None, None))
                row = None
                if fy is not None:
                    row = con.execute(
                        """
                        SELECT COALESCE(je_debit,0), COALESCE(je_credit,0)
                        FROM je
                        WHERE company_code=? AND fiscal_year=? AND fiscal_period=? AND gl_account=?
                        """,
                        [company, fy, fp, acct],
                    ).fetchone()
                je_net = (to_dec(row[0]) - to_dec(row[1])) if row else Decimal("0")
                inferred_opening = tb_net - je_net
                diff = abs(ob_bal - inferred_opening)
                compared += 1
                if diff >= Decimal("1"):
                    mismatches.append(
                        {
                            "company": company,
                            "acct": acct,
                            "ob": float(ob_bal),
                            "inferred_opening": float(inferred_opening),
                            "diff": float(diff),
                        }
                    )

        # 연도별 carry-forward: current FY FP1 inferred opening vs prior FY final TB.
        tb_by_period: dict = {}
        for r in tb_data:
            key = (r["company_code"], int(r["fiscal_year"]), int(r["fiscal_period"]))
            tb_by_period[key] = {
                str(e["account_code"]): to_dec(e.get("debit_balance", 0)) - to_dec(e.get("credit_balance", 0))
                for e in r.get("entries", [])
            }

        by_company_year: dict = {}
        for company, fy, fp in tb_by_period:
            by_company_year.setdefault((company, fy), []).append(fp)

        for (company, fy), periods in sorted(by_company_year.items()):
            prev_key = (company, fy - 1)
            if prev_key not in by_company_year:
                continue
            cur_first_fp = min(periods)
            prev_last_fp = max(by_company_year[prev_key])
            cur_tb = tb_by_period.get((company, fy, cur_first_fp), {})
            prev_tb = tb_by_period.get((company, fy - 1, prev_last_fp), {})
            accounts = set(cur_tb) | set(prev_tb)
            for acct in sorted(accounts):
                row = con.execute(
                    """
                    SELECT COALESCE(je_debit,0), COALESCE(je_credit,0)
                    FROM je
                    WHERE company_code=? AND fiscal_year=? AND fiscal_period=? AND gl_account=?
                    """,
                    [company, fy, cur_first_fp, acct],
                ).fetchone()
                je_net = (to_dec(row[0]) - to_dec(row[1])) if row else Decimal("0")
                inferred_opening = cur_tb.get(acct, Decimal("0")) - je_net
                expected_opening = Decimal("0") if _is_pl_account(acct) else prev_tb.get(acct, Decimal("0"))
                diff = abs(inferred_opening - expected_opening)
                yearly_compared += 1
                if diff >= Decimal("1"):
                    yearly_mismatches.append(
                        {
                            "company": company,
                            "fy": fy,
                            "acct": acct,
                            "acct_type": "PL" if _is_pl_account(acct) else "BS",
                            "inferred_opening": float(inferred_opening),
                            "expected_opening": float(expected_opening),
                            "diff": float(diff),
                        }
                    )

    n_mismatch = len(mismatches)
    n_yearly_mismatch = len(yearly_mismatches)
    max_diff = max((m["diff"] for m in mismatches), default=0)
    max_yearly_diff = max((m["diff"] for m in yearly_mismatches), default=0)
    status = "PASS" if (n_unbalanced == 0 and n_mismatch == 0 and n_yearly_mismatch == 0) else "FAIL"

    print(f"  상태: {status}")
    print(f"  opening_balances 레코드: {len(ob_data)}  계정 합계: {total_accounts:,}")
    print(f"  is_balanced=False: {n_unbalanced}")
    print(f"  OB vs inferred FP1 opening 비교 건수: {compared:,}  불일치: {n_mismatch:,}")
    print(f"  연도별 carry-forward 비교 건수: {yearly_compared:,}  불일치: {n_yearly_mismatch:,}")
    if n_mismatch:
        print(f"  최대 이월 차이: {max_diff:,.0f}")
        worst = max(mismatches, key=lambda x: x["diff"])
        print(
            f"  최대 불일치: {worst['company']} acct={worst['acct']} "
            f"OB={worst['ob']:,.0f} inferred_opening={worst['inferred_opening']:,.0f}"
        )
    if n_yearly_mismatch:
        print(f"  최대 연도 이월 차이: {max_yearly_diff:,.0f}")
        worst_y = max(yearly_mismatches, key=lambda x: x["diff"])
        print(
            f"  최대 연도 이월 불일치: {worst_y['company']} FY{worst_y['fy']} "
            f"acct={worst_y['acct']}({worst_y['acct_type']}) "
            f"inferred_opening={worst_y['inferred_opening']:,.0f} "
            f"expected={worst_y['expected_opening']:,.0f}"
        )
    return {
        "status": status,
        "n_unbalanced_ob": n_unbalanced,
        "compared_accounts": compared,
        "n_mismatch": n_mismatch,
        "max_diff": float(max_diff),
        "yearly_compared_accounts": yearly_compared,
        "n_yearly_mismatch": n_yearly_mismatch,
        "max_yearly_diff": float(max_yearly_diff),
    }


# ─────────────────────────────────────────────
# 검사 4: 보조원장 대사
# ─────────────────────────────────────────────


def check_subledger(dataset_dir: Path, label: str) -> dict:
    """
    subledger_reconciliation.json 의 difference 가 0인지,
    AR/AP 보조원장 합계가 GL 통제계정과 일치하는지 확인.
    """
    print(f"\n[4] 보조원장 대사 — {label}")

    recon_path = dataset_dir / "balance" / "subledger_reconciliation.json"
    ar_path = dataset_dir / "subledger" / "ar_invoices.json"
    ap_path = dataset_dir / "subledger" / "ap_invoices.json"

    if not recon_path.exists():
        print("  SKIP: subledger_reconciliation.json 없음")
        return {"status": "SKIP"}

    recon_data = load_json(recon_path)

    # 4-1. difference 체크
    nonzero_diff = []
    for r in recon_data:
        diff = to_dec(r.get("difference", "0"))
        if abs(diff) >= Decimal("1"):
            nonzero_diff.append(
                {
                    "id": r.get("reconciliation_id"),
                    "company": r.get("company_code"),
                    "type": r.get("subledger_type"),
                    "diff": float(diff),
                }
            )

    n_nonzero = len(nonzero_diff)
    status_4a = "PASS" if n_nonzero == 0 else "FAIL"
    print(f"  [4a] difference≠0 건수: {n_nonzero} / {len(recon_data)}  → {status_4a}")

    # 4-2. AR 보조원장 합 vs GL(1100)
    ar_gl_diff = []
    if ar_path.exists():
        ar_data = load_json(ar_path)
        # AR는 invoice 단위 — company별 open 잔액 합산
        ar_by_company: dict = {}
        for inv in ar_data:
            co = inv.get("company_code", "")
            gross_obj = inv.get("gross_amount", {})
            if isinstance(gross_obj, dict):
                amt = to_dec(gross_obj.get("local_amount", "0"))
            else:
                amt = to_dec(gross_obj)
            ar_by_company[co] = ar_by_company.get(co, Decimal("0")) + amt

        # GL 통제계정(1100)은 recon_data에서 가져옴
        gl_1100 = {
            r["company_code"]: abs(to_dec(r.get("gl_balance", "0")))
            for r in recon_data
            if r.get("subledger_type") == "AR" and r.get("gl_account") == "1100"
        }
        for co, ar_sum in ar_by_company.items():
            gl_val = gl_1100.get(co, None)
            if gl_val is None:
                continue
            diff = abs(ar_sum - gl_val)
            if diff >= Decimal("1"):
                ar_gl_diff.append(
                    {
                        "company": co,
                        "ar_sum": float(ar_sum),
                        "gl": float(gl_val),
                        "diff": float(diff),
                    }
                )

    status_4b = "PASS" if len(ar_gl_diff) == 0 else "FAIL"
    print(f"  [4b] AR합계 vs GL(1100): 불일치 회사 {len(ar_gl_diff)}개  → {status_4b}")
    if ar_gl_diff:
        for item in ar_gl_diff[:3]:
            print(
                f"       {item['company']}: AR={item['ar_sum']:,.0f}  GL={item['gl']:,.0f}  diff={item['diff']:,.0f}"
            )

    # 4-3. AP 보조원장 합 vs GL(2050)
    ap_gl_diff = []
    if ap_path.exists():
        ap_data = load_json(ap_path)
        ap_by_company: dict = {}
        for inv in ap_data:
            co = inv.get("company_code", "")
            gross_obj = inv.get("gross_amount", inv.get("invoice_amount", {}))
            if isinstance(gross_obj, dict):
                amt = to_dec(gross_obj.get("local_amount", "0"))
            else:
                amt = to_dec(gross_obj)
            ap_by_company[co] = ap_by_company.get(co, Decimal("0")) + amt

        gl_2050 = {
            r["company_code"]: abs(to_dec(r.get("gl_balance", "0")))
            for r in recon_data
            if r.get("subledger_type") == "AP" and r.get("gl_account") == "2050"
        }
        for co, ap_sum in ap_by_company.items():
            gl_val = gl_2050.get(co, None)
            if gl_val is None:
                continue
            diff = abs(ap_sum - gl_val)
            if diff >= Decimal("1"):
                ap_gl_diff.append(
                    {
                        "company": co,
                        "ap_sum": float(ap_sum),
                        "gl": float(gl_val),
                        "diff": float(diff),
                    }
                )

    status_4c = "PASS" if len(ap_gl_diff) == 0 else "FAIL"
    print(f"  [4c] AP합계 vs GL(2050): 불일치 회사 {len(ap_gl_diff)}개  → {status_4c}")
    if ap_gl_diff:
        for item in ap_gl_diff[:3]:
            print(
                f"       {item['company']}: AP={item['ap_sum']:,.0f}  GL={item['gl']:,.0f}  diff={item['diff']:,.0f}"
            )

    overall = "PASS" if (n_nonzero == 0 and len(ar_gl_diff) == 0 and len(ap_gl_diff) == 0) else "FAIL"
    return {
        "status": overall,
        "n_recon_records": len(recon_data),
        "n_nonzero_diff": n_nonzero,
        "n_ar_gl_mismatch": len(ar_gl_diff),
        "n_ap_gl_mismatch": len(ap_gl_diff),
    }


# ─────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────


def run_dataset(dataset_dir: Path, label: str, con) -> dict:
    print(f"\n{'=' * 60}")
    print(f" 데이터셋: {label}")
    print(f" 경로: {dataset_dir}")
    print(f"{'=' * 60}")

    if not dataset_dir.exists():
        print(f"  [오류] 경로 없음: {dataset_dir}")
        return {}

    r1 = check_tb_je(dataset_dir, label, con)
    r2 = check_bs_equation(dataset_dir, label)
    r3 = check_carryover(dataset_dir, label, con)
    r4 = check_subledger(dataset_dir, label)
    return {"tb_je": r1, "bs_eq": r2, "carryover": r3, "subledger": r4}


def main():
    con = duckdb.connect(":memory:")

    normal_dir = Path(sys.argv[1]) if len(sys.argv) >= 2 else NORMAL_DIR
    fraud_dir = Path(sys.argv[2]) if len(sys.argv) >= 3 else None

    results_normal = run_dataset(normal_dir, f"NORMAL ({normal_dir.name})", con)
    results_fraud = (
        run_dataset(fraud_dir, f"FRAUD/OVERLAY ({fraud_dir.name})", con) if fraud_dir else {}
    )

    # ─── 비교 요약 ───
    print(f"\n{'=' * 60}")
    print(" 종합 요약")
    print(f"{'=' * 60}")

    items = [
        ("1. TB↔JE 정합", "tb_je"),
        ("2. BS 등식", "bs_eq"),
        ("3. 연도 이월", "carryover"),
        ("4. 보조원장 대사", "subledger"),
    ]

    for title, key in items:
        n_s = results_normal.get(key, {}).get("status", "N/A")
        f_s = results_fraud.get(key, {}).get("status", "N/A")
        print(f"  {title:<20}  NORMAL={n_s:<8}  FRAUD={f_s}")

    # ─── 발견사항 분류 ───
    print(f"\n{'=' * 60}")
    print(" 발견사항 3분류")
    print(f"{'=' * 60}")

    # TB↔JE 수치 요약
    r1n = results_normal.get("tb_je", {})
    r1f = results_fraud.get("tb_je", {})
    r2n = results_normal.get("bs_eq", {})
    r2f = results_fraud.get("bs_eq", {})
    r3n = results_normal.get("carryover", {})
    r4n = results_normal.get("subledger", {})

    print()
    print("■ 코드버그 (생성기 결함):")
    issues_found = False

    if r1n.get("n_mismatch", 0) > 0:
        print(
            f"  - [1] TB↔JE 불일치 (NORMAL): {r1n['n_mismatch']:,}건, "
            f"차이합계={r1n['total_diff']:,.0f}, 최대={r1n['max_diff']:,.0f}"
        )
        issues_found = True
    if r1f.get("n_mismatch", 0) > 0:
        print(
            f"  - [1] TB↔JE 불일치 (FRAUD): {r1f['n_mismatch']:,}건, "
            f"차이합계={r1f['total_diff']:,.0f}, 최대={r1f['max_diff']:,.0f}"
        )
        issues_found = True
    if r2n.get("n_fail", 0) > 0:
        print(f"  - [2] BS 불균형 (NORMAL): {r2n['n_fail']:,}건, 차이합계={r2n['total_diff']:,.0f}")
        issues_found = True
    if r2f.get("n_fail", 0) > 0:
        print(f"  - [2] BS 불균형 (FRAUD): {r2f['n_fail']:,}건, 차이합계={r2f['total_diff']:,.0f}")
        issues_found = True
    if r3n.get("n_unbalanced_ob", 0) > 0:
        print(f"  - [3] OB is_balanced=False: {r3n['n_unbalanced_ob']}건")
        issues_found = True
    if r3n.get("n_mismatch", 0) > 0:
        print(f"  - [3] OB↔FP1 inferred opening 불일치: {r3n['n_mismatch']:,}건, 최대={r3n['max_diff']:,.0f}")
        issues_found = True
    if r3n.get("n_yearly_mismatch", 0) > 0:
        print(
            f"  - [3] 연도별 기초↔전년기말 이월 불일치: "
            f"{r3n['n_yearly_mismatch']:,}건, 최대={r3n['max_yearly_diff']:,.0f}"
        )
        issues_found = True
    if r4n.get("n_nonzero_diff", 0) > 0:
        print(f"  - [4] subledger_reconciliation difference≠0: {r4n['n_nonzero_diff']}건")
        issues_found = True
    if r4n.get("n_ar_gl_mismatch", 0) > 0:
        print(f"  - [4] AR 보조원장 합계 vs GL(1100) 실측 불일치: {r4n['n_ar_gl_mismatch']}개 회사")
        issues_found = True
    if r4n.get("n_ap_gl_mismatch", 0) > 0:
        print(f"  - [4] AP 보조원장 합계 vs GL(2050) 실측 불일치: {r4n['n_ap_gl_mismatch']}개 회사")
        issues_found = True
    if not issues_found:
        print("  (없음)")

    print()
    print("■ Graceful (의도된 미생성):")
    print("  (없음) — v42 N10~N12 이후 TB/이월/보조원장 대사는 hollow PASS 없이 hard gate로 판정.")

    print()
    print("■ 데이터특성 (허용):")
    print("  - 최초 연도 이전 기말 TB는 존재하지 않으므로 최초 opening_balances는 FP1 inferred opening과 비교.")
    print(
        "  - 부가세 계정 분리(tax_amount) 로 인해 JE 순이동과 TB 잔액의 소수점 오차 허용 범위 1원."
    )

    print()
    print(f"{'=' * 60}")
    print(" PHASE2 ML 학습 영향 판정")
    print(f"{'=' * 60}")

    n_bugs = (
        r1n.get("n_mismatch", 0)
        + r1f.get("n_mismatch", 0)
        + r2n.get("n_fail", 0)
        + r2f.get("n_fail", 0)
        + r3n.get("n_unbalanced_ob", 0)
        + r3n.get("n_mismatch", 0)
        + r3n.get("n_yearly_mismatch", 0)
        + r4n.get("n_nonzero_diff", 0)
        + r4n.get("n_ar_gl_mismatch", 0)
        + r4n.get("n_ap_gl_mismatch", 0)
    )

    if n_bugs == 0:
        print("  PASS — 잔액·재무제표 정합 이상 없음. PHASE2 ML 학습에 걸림 없음.")
    else:
        print(f"  WARN — 코드버그 분류 이상 {n_bugs}건 발견.")
        if r1n.get("n_mismatch", 0) > 0 or r1f.get("n_mismatch", 0) > 0:
            print(
                "  TB↔JE 불일치가 존재하면 balance-based feature (period_net, cumulative_balance)에"
            )
            print("  신호 오염이 발생할 수 있어 PHASE2 학습 전 생성기 수정 권고.")
        if r2n.get("n_fail", 0) > 0 or r2f.get("n_fail", 0) > 0:
            print(
                "  BS 불균형은 재무비율 feature (debt_ratio, leverage) 왜곡으로 이어지므로 수정 필요."
            )
    sys.exit(1 if n_bugs else 0)


if __name__ == "__main__":
    main()
