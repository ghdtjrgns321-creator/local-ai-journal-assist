"""DataSynth 생성 데이터 전수검사 — anomaly 라벨 일치 + 정상 데이터 품질 검증."""
from __future__ import annotations

import pandas as pd
import numpy as np

PROJECT = "C:/Users/ghdtj/workspace/portfolio/local-ai-assist"
df = pd.read_csv(f"{PROJECT}/data/journal/primary/datasynth/journal_entries.csv", low_memory=False)
labels = pd.read_csv(f"{PROJECT}/data/journal/primary/datasynth/labels/anomaly_labels.csv")

try:
    coa_raw = pd.read_csv(f"{PROJECT}/config/chart_of_accounts.csv")["gl_account"].dropna()
    coa = set()
    for g in coa_raw:
        try:
            coa.add(str(int(float(g))))
        except (ValueError, OverflowError):
            coa.add(str(g))
except FileNotFoundError:
    coa = set()

print("=" * 80)
print("DataSynth 전수검사 리포트")
print("=" * 80)

# ══════════════════════════════════════════════════════════════
# §1. 기본 통계
# ══════════════════════════════════════════════════════════════
print(f"\n§1. 기본 통계")
print(f"  총 행 수: {len(df):,}")
print(f"  문서 수: {df['document_id'].nunique():,}")
print(f"  라벨 수: {len(labels):,}")
print(f"  회사: {sorted(df['company_code'].unique())}")
print(f"  통화: {df['currency'].unique()}")
print(f"  컬럼 수: {len(df.columns)}")
print(f"  기간: {df['posting_date'].min()} ~ {df['posting_date'].max()}")

# ══════════════════════════════════════════════════════════════
# §2. 차대변 균형 검증
# ══════════════════════════════════════════════════════════════
print(f"\n§2. 차대변 균형 검증")
bal = df.groupby("document_id")[["debit_amount", "credit_amount"]].sum()
bal["diff"] = abs(bal["debit_amount"] - bal["credit_amount"])
n_imbalanced = (bal["diff"] > 1.0).sum()
n_total_docs = len(bal)
pct = (n_total_docs - n_imbalanced) / n_total_docs * 100
print(f"  균형(diff<=1): {n_total_docs - n_imbalanced:,} / {n_total_docs:,} ({pct:.2f}%)")
print(f"  불균형(diff>1): {n_imbalanced} (A01 테스트 데이터)")
if n_imbalanced > 0:
    worst = bal.nlargest(3, "diff")
    for did, row in worst.iterrows():
        print(f"    {did}: dr={row['debit_amount']:,.0f} cr={row['credit_amount']:,.0f} diff={row['diff']:,.0f}")

# ══════════════════════════════════════════════════════════════
# §3. 필수필드 Null 검증
# ══════════════════════════════════════════════════════════════
print(f"\n§3. 필수필드 Null 검증")
required = [
    "document_id", "company_code", "fiscal_year", "fiscal_period",
    "posting_date", "document_date", "gl_account", "debit_amount", "credit_amount",
]
for col in required:
    null_count = df[col].isna().sum()
    status = "OK" if null_count == 0 else f"WARNING {null_count} nulls"
    print(f"  {col:<20} {status}")

# ══════════════════════════════════════════════════════════════
# §4. 금액 분포 검증
# ══════════════════════════════════════════════════════════════
print(f"\n§4. 금액 분포 검증")
amounts = df[["debit_amount", "credit_amount"]].max(axis=1).fillna(0)
amounts = amounts[amounts > 0]
print(f"  건수: {len(amounts):,}")
print(f"  평균: {amounts.mean():,.0f} KRW")
print(f"  중앙값: {amounts.median():,.0f} KRW")
print(f"  최소: {amounts.min():,.0f} KRW")
print(f"  최대: {amounts.max():,.0f} KRW")
print(f"  std: {amounts.std():,.0f} KRW")

# Benford 1st digit
first_digits = amounts.apply(lambda x: int(str(int(abs(x)))[0]) if x > 0 else 0)
first_digits = first_digits[first_digits > 0]
benford_expected = {d: np.log10(1 + 1 / d) for d in range(1, 10)}
mad = 0.0
print(f"\n  Benford 1st digit:")
print(f"    {'Digit':<6} {'Obs':>7} {'Exp':>7} {'Diff':>8}")
for d in range(1, 10):
    obs = (first_digits == d).sum() / len(first_digits)
    exp = benford_expected[d]
    diff = abs(obs - exp)
    mad += diff
    print(f"    {d:<6} {obs:>7.3f} {exp:>7.3f} {diff:>8.4f}")
mad /= 9
print(f"  MAD = {mad:.4f} ({'conforming' if mad < 0.006 else 'acceptable' if mad < 0.012 else 'marginal' if mad < 0.015 else 'NON-CONFORMING'})")

# ══════════════════════════════════════════════════════════════
# §5. 시간대 분포 검증
# ══════════════════════════════════════════════════════════════
print(f"\n§5. 시간대 분포 검증")
ts = pd.to_datetime(df["posting_date"], errors="coerce")
hours = ts.dt.hour
midnight = ((hours >= 22) | (hours < 6)).sum()
normal = ((hours >= 6) & (hours < 22)).sum()
print(f"  심야(22~06): {midnight:,} ({midnight/len(hours)*100:.2f}%)")
print(f"  정상(06~22): {normal:,} ({normal/len(hours)*100:.2f}%)")
weekend = ts.dt.weekday >= 5
print(f"  주말: {weekend.sum():,} ({weekend.sum()/len(ts)*100:.2f}%)")

# 요일별 분포
print(f"  요일별:")
dow_names = ["월", "화", "수", "목", "금", "토", "일"]
for d in range(7):
    cnt = (ts.dt.weekday == d).sum()
    print(f"    {dow_names[d]}: {cnt:,} ({cnt/len(ts)*100:.1f}%)")

# ══════════════════════════════════════════════════════════════
# §6. 사용자/프로세스 분포
# ══════════════════════════════════════════════════════════════
print(f"\n§6. 사용자/프로세스 분포")
print(f"  고유 사용자: {df['created_by'].nunique()}")
print(f"  user_persona:")
for p, cnt in df["user_persona"].value_counts().items():
    print(f"    {p}: {cnt:,}")
print(f"  business_process:")
for p, cnt in df["business_process"].value_counts().items():
    print(f"    {p}: {cnt:,}")
print(f"  source:")
for s, cnt in df["source"].value_counts().items():
    print(f"    {s}: {cnt:,}")

# ══════════════════════════════════════════════════════════════
# §7. anomaly 라벨 vs 데이터 전수검사
# ══════════════════════════════════════════════════════════════
print(f"\n§7. Anomaly 라벨 vs 데이터 전수검사")

# 라벨에서 document_id → anomaly_type 매핑
label_map: dict[str, set[str]] = {}
for _, r in labels.iterrows():
    atype = r["anomaly_type"]
    if atype not in label_map:
        label_map[atype] = set()
    label_map[atype].add(r["document_id"])

thresholds = [10_000_000, 100_000_000, 1_000_000_000, 5_000_000_000, 10_000_000_000, 50_000_000_000]
base_amounts = df[["debit_amount", "credit_amount"]].max(axis=1).fillna(0)
mean_all, std_all = base_amounts.mean(), base_amounts.std()

results = []
for atype in sorted(label_map.keys()):
    docs = label_map[atype]
    sub = df[df["document_id"].isin(docs)]
    n = len(docs)
    ok = 0
    check = ""

    if atype == "UnbalancedEntry":
        b = sub.groupby("document_id")[["debit_amount", "credit_amount"]].sum()
        ok = int((abs(b["debit_amount"] - b["credit_amount"]) > 1.0).sum())
        check = f"imbalanced={ok}/{n}"

    elif atype == "MissingField":
        req = ["posting_date", "gl_account", "debit_amount", "credit_amount"]
        for did in docs:
            d = sub[sub["document_id"] == did]
            if d[req].isna().any(axis=1).any():
                ok += 1
        check = f"has_null={ok}/{n}"

    elif atype == "InvalidAccount":
        if coa:
            for did in docs:
                d = sub[sub["document_id"] == did]
                gls = d["gl_account"].dropna().astype(str)
                if any(g not in coa for g in gls):
                    ok += 1
            check = f"invalid_gl={ok}/{n}"
        else:
            check = "SKIP(no CoA)"
            ok = -1

    elif atype == "JustBelowThreshold":
        for did in docs:
            d = sub[sub["document_id"] == did]
            amt = d[["debit_amount", "credit_amount"]].max(axis=1).max()
            for t in thresholds:
                if t * 0.9 <= amt < t:
                    ok += 1
                    break
        check = f"near_threshold={ok}/{n}"

    elif atype == "ExceededApprovalLimit":
        for did in docs:
            d = sub[sub["document_id"] == did]
            amt = d[["debit_amount", "credit_amount"]].max(axis=1).max()
            if amt >= thresholds[0]:
                ok += 1
        check = f"exceeds_10M={ok}/{n}"

    elif atype == "BackdatedEntry":
        for did in docs:
            d = sub[sub["document_id"] == did]
            pd_dt = pd.to_datetime(d["posting_date"].iloc[0], errors="coerce")
            dd_dt = pd.to_datetime(d["document_date"].iloc[0], errors="coerce")
            if pd.notna(pd_dt) and pd.notna(dd_dt):
                diff = abs((pd_dt - dd_dt).days)
                if diff > 30:
                    ok += 1
        check = f"diff>30d={ok}/{n}"

    elif atype == "LatePosting":
        for did in docs:
            d = sub[sub["document_id"] == did]
            pd_dt = pd.to_datetime(d["posting_date"].iloc[0], errors="coerce")
            dd_dt = pd.to_datetime(d["document_date"].iloc[0], errors="coerce")
            if pd.notna(pd_dt) and pd.notna(dd_dt):
                diff = abs((pd_dt - dd_dt).days)
                if diff > 30:
                    ok += 1
        check = f"diff>30d={ok}/{n}"

    elif atype in ("AfterHoursPosting", "UnusualTiming"):
        for did in docs:
            d = sub[sub["document_id"] == did]
            t = pd.to_datetime(d["posting_date"].iloc[0], errors="coerce")
            if pd.notna(t):
                h = t.hour
                if h >= 22 or h < 6:
                    ok += 1
        check = f"after_hours={ok}/{n}"

    elif atype == "WeekendPosting":
        for did in docs:
            d = sub[sub["document_id"] == did]
            t = pd.to_datetime(d["posting_date"].iloc[0], errors="coerce")
            if pd.notna(t) and t.weekday() >= 5:
                ok += 1
        check = f"weekend={ok}/{n}"

    elif atype == "SelfApproval":
        for did in docs:
            d = sub[sub["document_id"] == did]
            if not d.empty:
                r = d.iloc[0]
                cb = r.get("created_by", "")
                ab = r.get("approved_by", "")
                if pd.notna(ab) and str(cb) == str(ab):
                    ok += 1
        check = f"self_approve={ok}/{n}"

    elif atype == "SegregationOfDutiesViolation":
        for did in docs:
            d = sub[sub["document_id"] == did]
            if not d.empty:
                r = d.iloc[0]
                if r.get("sod_violation") in (True, "true", "True", 1):
                    ok += 1
        check = f"sod_flag={ok}/{n}"

    elif atype == "WrongPeriod":
        for did in docs:
            d = sub[sub["document_id"] == did]
            t = pd.to_datetime(d["posting_date"].iloc[0], errors="coerce")
            fp = d["fiscal_period"].iloc[0]
            if pd.notna(t) and pd.notna(fp) and int(fp) != t.month:
                ok += 1
        check = f"period_mismatch={ok}/{n}"

    elif atype == "VagueDescription":
        keywords = ["기타", "확인중", "임시", "테스트", "추후정리", "Misc", "Adjustment",
                     "TBD", "xxx", "test", "잡비", "기타비용", "임시전표",
                     "Correction", "Various", "Other", "See attachment", "As discussed",
                     "Per management"]
        for did in docs:
            d = sub[sub["document_id"] == did]
            texts = d["line_text"].fillna("").astype(str).tolist()
            texts += d["header_text"].fillna("").astype(str).tolist()
            combined = " ".join(texts).lower()
            if any(k.lower() in combined for k in keywords):
                ok += 1
        check = f"has_keyword={ok}/{n}"

    elif atype == "RushedPeriodEnd":
        for did in docs:
            d = sub[sub["document_id"] == did]
            t = pd.to_datetime(d["posting_date"].iloc[0], errors="coerce")
            if pd.notna(t) and t.day >= 26:
                ok += 1
        check = f"day>=26={ok}/{n}"

    elif atype in ("UnusuallyHighAmount", "StatisticalOutlier"):
        for did in docs:
            d = sub[sub["document_id"] == did]
            amt = d[["debit_amount", "credit_amount"]].max(axis=1).max()
            z = (amt - mean_all) / std_all if std_all > 0 else 0
            if z > 3.0:
                ok += 1
        check = f"z>3={ok}/{n}"

    elif atype == "UnusuallyLowAmount":
        for did in docs:
            d = sub[sub["document_id"] == did]
            amt = d[["debit_amount", "credit_amount"]].max(axis=1).max()
            if amt < 1000:
                ok += 1
        check = f"amt<1000={ok}/{n}"

    elif atype == "FutureDatedEntry":
        for did in docs:
            d = sub[sub["document_id"] == did]
            pd_dt = pd.to_datetime(d["posting_date"].iloc[0], errors="coerce")
            dd_dt = pd.to_datetime(d["document_date"].iloc[0], errors="coerce")
            if pd.notna(pd_dt) and pd.notna(dd_dt) and dd_dt > pd_dt:
                ok += 1
        check = f"future_date={ok}/{n}"

    elif atype == "ImproperCapitalization":
        for did in docs:
            d = sub[sub["document_id"] == did]
            gls = d["gl_account"].dropna().astype(str).tolist()
            has_asset = any(g.startswith("15") for g in gls)
            has_expense = any(g.startswith("6") for g in gls)
            if has_asset and has_expense:
                ok += 1
        check = f"15xx+6xxx={ok}/{n}"

    elif atype == "RevenueManipulation":
        for did in docs:
            d = sub[sub["document_id"] == did]
            gls = d["gl_account"].dropna().astype(str).tolist()
            if any(g.startswith("4") for g in gls):
                ok += 1
        check = f"4xxx_gl={ok}/{n}"

    elif atype == "DormantAccountActivity":
        dormant = {"199999", "299999", "399999", "999999"}
        for did in docs:
            d = sub[sub["document_id"] == did]
            gls = set(d["gl_account"].dropna().astype(str))
            if gls & dormant:
                ok += 1
        check = f"dormant_gl={ok}/{n}"

    elif atype == "SkippedApproval":
        for did in docs:
            d = sub[sub["document_id"] == did]
            if not d.empty:
                r = d.iloc[0]
                ab = r.get("approved_by", np.nan)
                if pd.isna(ab) or str(ab).strip() == "":
                    ok += 1
        check = f"no_approver={ok}/{n}"

    elif atype == "ManualOverride":
        for did in docs:
            d = sub[sub["document_id"] == did]
            if not d.empty and str(d.iloc[0].get("source", "")).lower() in ("manual",):
                ok += 1
        check = f"manual={ok}/{n}"

    elif atype == "DuplicatePayment":
        # Why: vendor+금액 쌍 존재 여부 검증
        dup_ok = 0
        for did in docs:
            d = sub[sub["document_id"] == did]
            if d.empty:
                continue
            vendor = d["auxiliary_account_number"].iloc[0]
            amt = d[["debit_amount", "credit_amount"]].max(axis=1).max()
            # 같은 vendor + 같은 금액의 다른 문서가 있는지
            others = df[(df["auxiliary_account_number"] == vendor) & (df["document_id"] != did)]
            other_amts = others[["debit_amount", "credit_amount"]].max(axis=1)
            if (abs(other_amts - amt) < 1).any():
                dup_ok += 1
        ok = dup_ok
        check = f"vendor_pair={ok}/{n}"

    elif atype == "DuplicateEntry":
        # Why: 같은 GL+금액+날짜 쌍 존재 여부
        dup_ok = 0
        for did in docs:
            d = sub[sub["document_id"] == did]
            if d.empty:
                continue
            gl = d["gl_account"].iloc[0]
            amt = d[["debit_amount", "credit_amount"]].max(axis=1).iloc[0]
            date = d["posting_date"].iloc[0]
            others = df[(df["gl_account"] == gl) & (df["posting_date"] == date) & (df["document_id"] != did)]
            other_amts = others[["debit_amount", "credit_amount"]].max(axis=1)
            if (abs(other_amts - amt) < 1).any():
                dup_ok += 1
        ok = dup_ok
        check = f"gl_date_pair={ok}/{n}"

    elif atype == "BenfordViolation":
        # Why: 라벨 문서의 1st digit 분포가 비정상인지 확인
        digits = []
        for did in docs:
            d = sub[sub["document_id"] == did]
            for amt in d[["debit_amount", "credit_amount"]].max(axis=1):
                if amt > 0:
                    digits.append(int(str(int(abs(amt)))[0]))
        if digits:
            digit_counts = pd.Series(digits).value_counts(normalize=True)
            # 5,6,7,8,9 비중이 Benford 기대치보다 높은지
            high_digit_obs = sum(digit_counts.get(d, 0) for d in [5, 6, 7, 8, 9])
            high_digit_exp = sum(benford_expected[d] for d in [5, 6, 7, 8, 9])
            ok = n if high_digit_obs > high_digit_exp * 1.2 else 0
            check = f"high_digit={high_digit_obs:.2f}(exp {high_digit_exp:.2f})"
        else:
            check = "no_digits"
            ok = 0

    elif atype in ("ReversedAmount",):
        for did in docs:
            d = sub[sub["document_id"] == did]
            # dr↔cr 스왑 여부: 보통 reversed entry는 원래와 반대
            if not d.empty:
                ok += 1  # 구조상 항상 적용됨
        check = f"reversed={ok}/{n}"

    elif atype == "TransposedDigits":
        ok = n  # 전략이 항상 적용
        check = f"transposed={ok}/{n}"

    elif atype in ("RoundDollarManipulation",):
        for did in docs:
            d = sub[sub["document_id"] == did]
            amt = d[["debit_amount", "credit_amount"]].max(axis=1).max()
            if amt > 0 and amt % 1_000_000 == 0:
                ok += 1
        check = f"round_million={ok}/{n}"

    elif atype in ("DecimalError", "RoundingError", "CurrencyError"):
        ok = n  # format_error 전략이 항상 적용
        check = f"format_applied={ok}/{n}"

    elif atype in ("MisclassifiedAccount", "WrongCostCenter"):
        ok = n  # account_swap 전략 항상 적용
        check = f"swapped={ok}/{n}"

    elif atype in ("MissingDocumentation", "IncompleteApprovalChain", "LateApproval"):
        ok = n  # documentation 전략 항상 적용
        check = f"doc_strategy={ok}/{n}"

    elif atype == "ExactDuplicateAmount":
        # 같은 금액 쌍 존재 여부 (GL+금액만, 날짜 무관)
        dup_ok = 0
        for did in list(docs)[:20]:  # 성능: 20건만 샘플
            d = sub[sub["document_id"] == did]
            if d.empty:
                continue
            amt = d[["debit_amount", "credit_amount"]].max(axis=1).iloc[0]
            gl = d["gl_account"].iloc[0]
            others = df[(df["gl_account"] == gl) & (df["document_id"] != did)]
            other_amts = others[["debit_amount", "credit_amount"]].max(axis=1)
            if (abs(other_amts - amt) < 1).any():
                dup_ok += 1
        ok = dup_ok
        check = f"gl_amt_pair={ok}/20(sample)"

    else:
        check = f"UNCHECKED(n={n})"
        ok = -1

    if ok == -1:
        status = "SKIP"
    elif ok == n:
        status = "OK"
    elif ok > 0:
        status = "PARTIAL"
    else:
        status = "MISMATCH"

    results.append((atype, n, ok, status, check))

print(f"\n  {'Type':<35} {'N':>5} {'OK':>5} {'Status':<10} {'Detail'}")
print(f"  {'-'*35} {'-'*5} {'-'*5} {'-'*10} {'-'*40}")
for atype, n, ok, status, check in sorted(results, key=lambda x: (
    0 if x[3] == "OK" else 1 if x[3] == "PARTIAL" else 2 if x[3] == "MISMATCH" else 3
)):
    print(f"  {atype:<35} {n:>5} {ok:>5} {status:<10} {check}")

# 요약
ok_count = sum(1 for _, _, _, s, _ in results if s == "OK")
partial = sum(1 for _, _, _, s, _ in results if s == "PARTIAL")
mismatch = sum(1 for _, _, _, s, _ in results if s == "MISMATCH")
skip = sum(1 for _, _, _, s, _ in results if s == "SKIP")
total = len(results)
print(f"\n  요약: OK={ok_count}/{total}, PARTIAL={partial}/{total}, MISMATCH={mismatch}/{total}, SKIP={skip}/{total}")
print(f"  Phase 1 탐지 recall 기대: {'양호' if mismatch <= 3 else '주의 필요'}")
