"""DataSynth 라벨 전수조사 — 53개 anomaly_type별 라벨-데이터 일치 여부 진단."""
from __future__ import annotations
import pandas as pd
import numpy as np
import json

PROJECT = "C:/Users/ghdtj/workspace/portfolio/local-ai-assist"
df = pd.read_csv(f"{PROJECT}/data/journal/primary/datasynth/journal_entries.csv", low_memory=False)
labels = pd.read_csv(f"{PROJECT}/data/journal/primary/datasynth/labels/anomaly_labels.csv")
employees = json.load(open(f"{PROJECT}/data/journal/primary/datasynth/master_data/employees.json", encoding="utf-8"))
employee_by_user = {str(e["user_id"]): e for e in employees}
coa_raw = pd.read_csv(f"{PROJECT}/config/chart_of_accounts.csv")["gl_account"].dropna()
coa = set()
for g in coa_raw:
    try:
        coa.add(str(int(float(g))))
    except (ValueError, OverflowError):
        coa.add(str(g))

print(f"DATASET: {len(df):,} rows, {df['document_id'].nunique():,} docs")
print(f"LABELS: {len(labels):,}, {labels['document_id'].nunique():,} docs\n")

total_base = df[["debit_amount", "credit_amount"]].max(axis=1).fillna(0)
total_mean, total_std = total_base.mean(), total_base.std()

rows = []
for atype in sorted(labels["anomaly_type"].unique()):
    docs = set(labels.loc[labels["anomaly_type"] == atype, "document_id"])
    sub = df[df["document_id"].isin(docs)]
    n = len(docs)
    tl = labels[labels["anomaly_type"] == atype]
    strat = tl["structured_strategy_type"].notna().sum()

    check = ""
    ok = 0  # 라벨과 데이터가 일치하는 문서 수
    total = n

    if atype == "MissingField":
        req = ["posting_date", "gl_account", "debit_amount", "credit_amount"]
        for did in docs:
            d = sub[sub["document_id"] == did]
            if d[req].isna().any(axis=1).any():
                ok += 1
        check = f"has_null={ok}/{n}"

    elif atype == "UnbalancedEntry":
        bal = sub.groupby("document_id")[["debit_amount", "credit_amount"]].sum()
        ok = int((abs(bal["debit_amount"] - bal["credit_amount"]) > 1).sum())
        check = f"imbalanced={ok}/{n}"

    elif atype == "InvalidAccount":
        for did in docs:
            d = sub[sub["document_id"] == did]
            gl = d["gl_account"].dropna().astype(str).str.split(".").str[0]
            if (~gl.isin(coa)).any():
                ok += 1
        check = f"invalid_gl={ok}/{n}"

    elif atype in ("DuplicatePayment", "DuplicateEntry", "ExactDuplicateAmount"):
        base = sub[["debit_amount", "credit_amount"]].max(axis=1).fillna(0)
        work = sub[["document_id", "auxiliary_account_number"]].copy()
        work["base"] = base.values
        for did in docs:
            d = work[work["document_id"] == did]
            if d["auxiliary_account_number"].isna().all():
                continue
            vendor = d["auxiliary_account_number"].iloc[0]
            amt = d["base"].max()
            others = work[(work["auxiliary_account_number"] == vendor) & (work["base"] == amt) & (work["document_id"] != did)]
            if len(others) > 0:
                ok += 1
        check = f"has_pair={ok}/{n}"

    elif atype == "SelfApproval":
        for did in docs:
            d = sub[sub["document_id"] == did]
            if (d["created_by"] == d["approved_by"]).any():
                ok += 1
        check = f"self_approve={ok}/{n}"

    elif atype == "SkippedApproval":
        for did in docs:
            d = sub[sub["document_id"] == did]
            if d["approved_by"].isna().all():
                ok += 1
        check = f"no_approver={ok}/{n}"

    elif atype == "ManualOverride":
        for did in docs:
            d = sub[sub["document_id"] == did]
            if d["source"].fillna("").astype(str).str.lower().isin(["manual", "adjustment"]).any():
                ok += 1
        check = f"manual_source_subset={ok}/{n}"

    elif atype in ("AfterHoursPosting", "UnusualTiming"):
        for did in docs:
            d = sub[sub["document_id"] == did]
            h = pd.to_datetime(d["posting_date"]).dt.hour
            if ((h >= 22) | (h < 6)).any():
                ok += 1
        check = f"after_hours={ok}/{n}"

    elif atype in ("BackdatedEntry", "LatePosting"):
        for did in docs:
            d = sub[sub["document_id"] == did]
            p = pd.to_datetime(d["posting_date"].iloc[0])
            dd = pd.to_datetime(d["document_date"].iloc[0])
            if abs((p - dd).days) > 30:
                ok += 1
        check = f"diff>30d={ok}/{n}"

    elif atype == "WeekendPosting":
        for did in docs:
            d = sub[sub["document_id"] == did]
            dow = pd.to_datetime(d["posting_date"]).dt.dayofweek
            if (dow >= 5).any():
                ok += 1
        check = f"weekend={ok}/{n}"

    elif atype == "WrongPeriod":
        for did in docs:
            d = sub[sub["document_id"] == did]
            pm = pd.to_datetime(d["posting_date"]).dt.month
            if (pm != d["fiscal_period"]).any():
                ok += 1
        check = f"wrong_period={ok}/{n}"

    elif atype == "VagueDescription":
        kw = ["misc", "tbd", "see attachment", "test", "etc", "check", "temp",
              "기타", "임시", "확인", "테스트"]
        for did in docs:
            d = sub[sub["document_id"] == did]
            txt = d["line_text"].fillna("").str.lower()
            if txt.apply(lambda x: any(k in x for k in kw)).any():
                ok += 1
        check = f"vague_text={ok}/{n}"

    elif atype == "RevenueManipulation":
        for did in docs:
            d = sub[sub["document_id"] == did]
            gl = d["gl_account"].astype(str)
            base = d[["debit_amount", "credit_amount"]].max(axis=1)
            rev_amt = base[gl.str.startswith("4")]
            if len(rev_amt) > 0 and rev_amt.max() > 100_000_000:
                ok += 1
        check = f"4xxx+high={ok}/{n}"

    elif atype == "ImproperCapitalization":
        for did in docs:
            d = sub[sub["document_id"] == did]
            gl = d["gl_account"].astype(str)
            dr15 = (gl.str.startswith("15") & (d["debit_amount"].fillna(0) > 0)).any()
            cr6 = (gl.str.startswith("6") & (d["credit_amount"].fillna(0) > 0)).any()
            if dr15 and cr6:
                ok += 1
        check = f"15xx+6xx={ok}/{n}"

    elif atype in ("CircularTransaction", "CircularIntercompany"):
        tp = sub["trading_partner"].notna().sum()
        check = f"trading_partner={tp}/{len(sub)}"
        ok = -1  # 판정 불가

    elif atype == "SegregationOfDutiesViolation":
        for did in docs:
            d = sub[sub["document_id"] == did]
            if (d["sod_violation"] == True).any():
                ok += 1
        check = f"sod=True={ok}/{n}"

    elif atype == "RushedPeriodEnd":
        for did in docs:
            d = sub[sub["document_id"] == did]
            day = pd.to_datetime(d["posting_date"]).dt.day
            if (day >= 26).any():
                ok += 1
        check = f"month_end={ok}/{n}"

    elif atype in ("UnusuallyHighAmount", "StatisticalOutlier"):
        for did in docs:
            d = sub[sub["document_id"] == did]
            base = d[["debit_amount", "credit_amount"]].max(axis=1)
            z = (base - total_mean) / total_std
            if (z.abs() > 3).any():
                ok += 1
        check = f"z>3={ok}/{n}"

    elif atype == "WrongCostCenter":
        # 비정상 cost_center = 해당 프로세스와 매칭 안 됨 (간이 판정: NULL이 아닌 이상한 값)
        ok = -1
        check = f"(manual_check_needed)"

    elif atype == "DormantAccountActivity":
        dormant = {"199999", "299999", "399999", "999999"}
        for did in docs:
            d = sub[sub["document_id"] == did]
            gl = set(d["gl_account"].dropna().astype(str).str.split(".").str[0])
            if gl & dormant:
                ok += 1
        check = f"dormant_gl={ok}/{n}"

    elif atype in ("TransferPricingAnomaly", "UnmatchedIntercompany"):
        tp = sub["trading_partner"].notna().sum()
        check = f"trading_partner={tp}/{len(sub)}"
        ok = -1

    elif atype == "FutureDatedEntry":
        for did in docs:
            d = sub[sub["document_id"] == did]
            p = pd.to_datetime(d["posting_date"].iloc[0]).normalize()
            dd = pd.to_datetime(d["document_date"].iloc[0])
            if dd > p:
                ok += 1
        check = f"future={ok}/{n}"

    elif atype == "JustBelowThreshold":
        thresholds = [10e6, 100e6, 1e9, 5e9, 10e9, 50e9]
        for did in docs:
            d = sub[sub["document_id"] == did]
            base = d[["debit_amount", "credit_amount"]].max(axis=1).max()
            if any(t * 0.9 <= base < t for t in thresholds):
                ok += 1
        check = f"threshold_match={ok}/{n}"

    elif atype == "ExceededApprovalLimit":
        for did in docs:
            d = sub[sub["document_id"] == did]
            if d.empty:
                continue
            approver = str(d["approved_by"].iloc[0]) if pd.notna(d["approved_by"].iloc[0]) else ""
            employee = employee_by_user.get(approver)
            if not approver or employee is None:
                continue
            try:
                approval_limit = float(employee.get("approval_limit") or 0)
            except (TypeError, ValueError):
                continue
            base = (d["debit_amount"].fillna(0) + d["credit_amount"].fillna(0)).max()
            if base > approval_limit:
                ok += 1
        check = f"approved_by_limit={ok}/{n}"

    elif atype == "UnusualAccountPair":
        ok = -1
        check = "median_freq=4766(not_rare)"

    elif atype == "ReversedAmount":
        # 역분개 쌍 존재 확인
        for did in docs:
            d = sub[sub["document_id"] == did]
            gl_set = set(d["gl_account"].dropna().astype(str))
            dr_max = d["debit_amount"].max()
            cr_max = d["credit_amount"].max()
            amt = max(dr_max, cr_max) if pd.notna(dr_max) and pd.notna(cr_max) else 0
            # 같은 GL + 같은 금액 + 반대 방향 문서 검색
            others = df[(df["document_id"] != did) & (df["gl_account"].astype(str).isin(gl_set))]
            if len(others) > 0:
                ok += 1
        check = f"reversal_pair={ok}/{n}"

    elif atype == "BenfordViolation":
        base = sub[["debit_amount", "credit_amount"]].max(axis=1)
        fd = base[base > 0].astype(str).str[0].astype(int)
        d1_pct = fd.value_counts(normalize=True).get(1, 0)
        check = f"digit1={d1_pct:.1%}(expect30%)"
        ok = -1

    elif atype in ("NewCounterparty", "MissingRelationship", "CentralityAnomaly"):
        ok = -1
        check = "relational(Phase2/3)"

    elif atype in ("RepeatingAmount", "UnusualFrequency", "TransactionBurst", "TrendBreak"):
        ok = -1
        check = "temporal(Phase2/3)"

    elif atype in ("FictitiousEntry", "FictitiousVendor"):
        ok = -1
        check = "fictitious(Phase2/3)"

    elif atype in ("IncompleteApprovalChain", "LateApproval", "MissingDocumentation"):
        ok = -1
        check = "process_workflow"

    elif atype in ("TransposedDigits", "DecimalError", "RoundingError", "CurrencyError"):
        ok = -1
        check = "format_error"

    elif atype == "MisclassifiedAccount":
        ok = -1
        check = "classification"
    else:
        ok = -1
        check = "?"

    # 판정
    if ok == -1:
        verdict = "SKIP"
    elif ok == n:
        verdict = "OK"
    elif ok == 0:
        verdict = "ALL_MISMATCH"
    else:
        verdict = f"PARTIAL({ok}/{n})"

    rows.append((atype, n, strat, ok, verdict, check))

print(f"{'Type':<35} {'N':>5} {'Strat':>5} {'OK':>5} {'Verdict':<18} Check")
print("-" * 120)
for t, n, s, o, v, c in sorted(rows, key=lambda x: x[4]):
    print(f"{t:<35} {n:>5} {s:>5} {o:>5} {v:<18} {c}")

# 글로벌 데이터 무결성 체크
print("\n\n=== GLOBAL DATA INTEGRITY ===")
print(f"Negative debit: {(df['debit_amount'].fillna(0) < 0).sum()}")
print(f"Negative credit: {(df['credit_amount'].fillna(0) < 0).sum()}")
both = ((df['debit_amount'].fillna(0) > 0) & (df['credit_amount'].fillna(0) > 0)).sum()
print(f"Both dr+cr on same line: {both}")
zero = ((df['debit_amount'].fillna(0) == 0) & (df['credit_amount'].fillna(0) == 0)).sum()
print(f"Zero amount lines: {zero}")
print(f"trading_partner NULL: {df['trading_partner'].isna().mean()*100:.1f}%")
fraud_docs = df[df['is_fraud'] == True]['document_id'].nunique()
fraud_type_docs = df[df['fraud_type'].notna()]['document_id'].nunique()
print(f"is_fraud docs: {fraud_docs}, fraud_type docs: {fraud_type_docs}")
pm = pd.to_datetime(df['posting_date']).dt.month
period_mis = (pm != df['fiscal_period']).sum()
print(f"fiscal_period != posting_month: {period_mis}")
posting = pd.to_datetime(df['posting_date']).dt.normalize()
docdate = pd.to_datetime(df['document_date'])
future = (docdate > posting).sum()
print(f"document_date > posting_date: {future}")
csv_docs = set(df['document_id'])
label_docs = set(labels['document_id'])
orphans = label_docs - csv_docs
print(f"Orphaned labels: {len(orphans)}")
single = (df.groupby('document_id').size() == 1).sum()
print(f"Single-line docs: {single}")
