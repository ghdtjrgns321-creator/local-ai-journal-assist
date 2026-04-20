"""
Dual-direction data quality audit on DataSynth journal entries.
PART 1: 비정상 라벨 검증 - 라벨 문서가 실제 이상 특성을 보이는지
PART 2: 정상 데이터 오염 검사 - is_fraud=False AND is_anomaly=False 행
PART 3: L1-06 sod_violation 심층 분석
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from pathlib import Path

BASE = Path(r"C:\Users\ghdtj\workspace\portfolio\local-ai-assist")
JE   = BASE / "data/journal/primary/datasynth/journal_entries.csv"
LBL  = BASE / "data/journal/primary/datasynth/labels/anomaly_labels.csv"
COA  = BASE / "config/chart_of_accounts.csv"

# ── 로드 ────────────────────────────────────────────────────────────────────
print("=== 데이터 로드 중... ===")
je = pd.read_csv(
    JE,
    parse_dates=["posting_date", "document_date"],
    dtype={"debit_amount": float, "credit_amount": float},
    low_memory=False,
)
lbl    = pd.read_csv(LBL, low_memory=False)
coa_df = pd.read_csv(COA)
coa_set = set(coa_df["gl_account"].astype(str).str.strip())

print(f"  journal_entries : {len(je):>10,} rows  /  {je['document_id'].nunique():>8,} docs")
print(f"  anomaly_labels  : {len(lbl):>10,} rows  /  {lbl['document_id'].nunique():>8,} docs")
print(f"  CoA accounts    : {len(coa_set):>10,}")

# ── 파생 컬럼 ───────────────────────────────────────────────────────────────
je["_posting_hour"]   = je["posting_date"].dt.hour
je["_post_date_only"] = je["posting_date"].dt.normalize()
je["_doc_date_only"]  = pd.to_datetime(je["document_date"]).dt.normalize()
je["_day_diff"]       = (je["_post_date_only"] - je["_doc_date_only"]).dt.days
je["_dow"]            = je["_post_date_only"].dt.dayofweek   # 5=Sat, 6=Sun
je["_gl_str"]         = je["gl_account"].astype(str).str.strip()

# ── 헬퍼 ────────────────────────────────────────────────────────────────────
def label_docs(anomaly_type_list: list[str]) -> set:
    """anomaly_type 목록으로 해당 document_id 집합 반환."""
    mask = lbl["anomaly_type"].isin(anomaly_type_list)
    return set(lbl.loc[mask, "document_id"].dropna().unique())


def fmt_row(rule, total, verified, note=""):
    pct = verified / total * 100 if total > 0 else 0
    flag = " <<" if pct < 50 and total > 0 else ""
    print(f"  {rule:<5}  {total:>8,}  {verified:>8,}  {pct:>6.1f}%  {note}{flag}")


# ════════════════════════════════════════════════════════════════════════════
# PART 1: 비정상 라벨 검증
# ════════════════════════════════════════════════════════════════════════════
print()
print("=" * 78)
print("PART 1: 비정상 라벨 검증 (라벨 문서가 실제 이상 특성을 보이는지)")
print("=" * 78)
print(f"  {'룰':<5}  {'총라벨':>8}  {'검증':>8}  {'비율':>7}  비고")
print("  " + "-" * 72)

results_p1: list[dict] = []


def record(rule, total, verified, note=""):
    fmt_row(rule, total, verified, note)
    results_p1.append({"rule": rule, "total": total, "verified": verified, "note": note})


# ── L1-01: 불균형 전표 ─────────────────────────────────────────────────────────
d = label_docs(["UnbalancedEntry"])
if d:
    grp = je[je["document_id"].isin(d)].groupby("document_id").agg(
        sum_dr=("debit_amount", "sum"), sum_cr=("credit_amount", "sum")
    )
    ver = int((abs(grp["sum_dr"] - grp["sum_cr"]) > 0.01).sum())
    record("L1-01", len(d), ver, "sum(debit) != sum(credit)")
else:
    record("L1-01", 0, 0, "라벨 없음")

# ── L1-02: 필수 필드 NULL ──────────────────────────────────────────────────────
d = label_docs(["MissingField"])
if d:
    req = ["gl_account", "document_type", "posting_date"]
    sub = je[je["document_id"].isin(d)]
    # Why: 문서 내 어느 행이라도 필수 필드 NULL이면 해당 문서 = 검증됨
    has_null = sub.groupby("document_id").apply(
        lambda g: g[req].isnull().any().any()
    )
    ver = int(has_null.sum())
    record("L1-02", len(d), ver, "NULL in gl_account / document_type / posting_date")
else:
    record("L1-02", 0, 0, "라벨 없음")

# ── L1-03: CoA 외 GL ───────────────────────────────────────────────────────────
d = label_docs(["InvalidAccount"])
if d:
    sub = je[je["document_id"].isin(d)]
    invalid_rows = ~sub["_gl_str"].isin(coa_set)
    ver = len(set(sub.loc[invalid_rows, "document_id"].unique()))
    record("L1-03", len(d), ver, "GL not in CoA")
else:
    record("L1-03", 0, 0, "라벨 없음")

# ── L4-01: 수익 GL(4xxx) ───────────────────────────────────────────────────────
d = label_docs(["RevenueManipulation"])
if d:
    sub = je[je["document_id"].isin(d)]
    rev_docs = set(sub.loc[sub["_gl_str"].str.startswith("4"), "document_id"].unique())
    record("L4-01", len(d), len(rev_docs), "GL starts with '4' (revenue)")
else:
    record("L4-01", 0, 0, "라벨 없음")

# ── L1-05: 자기승인 ────────────────────────────────────────────────────────────
d = label_docs(["SelfApproval"])
if d:
    sub = je[je["document_id"].isin(d)]
    self_appr = sub[sub["created_by"] == sub["approved_by"]]
    ver = len(set(self_appr["document_id"].unique()))
    record("L1-05", len(d), ver, "created_by == approved_by")
else:
    record("L1-05", 0, 0, "라벨 없음")

# ── L1-06: SoD 위반 ────────────────────────────────────────────────────────────
d = label_docs(["SegregationOfDutiesViolation"])
if d:
    sub = je[je["document_id"].isin(d)]
    if "sod_violation" in sub.columns:
        sod_docs = set(sub.loc[sub["sod_violation"] == True, "document_id"].unique())
        ver = len(sod_docs)
        record("L1-06", len(d), ver, "sod_violation == True")
    else:
        record("L1-06", len(d), 0, "sod_violation 컬럼 없음")
else:
    record("L1-06", 0, 0, "라벨 없음")

# ── L3-02: 수동 입력 ───────────────────────────────────────────────────────────
d = label_docs(["ManualOverride"])
if d:
    sub = je[je["document_id"].isin(d)]
    manual = sub[sub["source"].str.lower().str.contains("manual", na=False)]
    ver = len(set(manual["document_id"].unique()))
    record("L3-02", len(d), ver, "source contains 'manual'")
else:
    record("L3-02", 0, 0, "라벨 없음")

# ── L1-07: 승인자 NULL ─────────────────────────────────────────────────────────
d = label_docs(["SkippedApproval"])
if d:
    sub = je[je["document_id"].isin(d)]
    null_appr = sub[sub["approved_by"].isna()]
    ver = len(set(null_appr["document_id"].unique()))
    record("L1-07", len(d), ver, "approved_by is NULL")
else:
    record("L1-07", 0, 0, "라벨 없음")

# ── L2-04: 자산+비용 GL 혼재 ───────────────────────────────────────────────────
d = label_docs(["ImproperCapitalization"])
if d:
    sub = je[je["document_id"].isin(d)]

    def has_asset_and_expense(g: pd.DataFrame) -> bool:
        gls = g["_gl_str"].tolist()
        has_asset   = any(gl.startswith("15") for gl in gls)
        has_expense = any(gl[:1] in ("5", "6", "7", "8") for gl in gls)
        return has_asset and has_expense

    grp_check = sub.groupby("document_id").apply(has_asset_and_expense)
    ver = int(grp_check.sum())
    record("L2-04", len(d), ver, "asset GL(15xx) AND expense GL(5-8xxx) both present")
else:
    record("L2-04", 0, 0, "라벨 없음")

# ── L3-05: 주말 전기 ───────────────────────────────────────────────────────────
d = label_docs(["WeekendPosting"])
if d:
    sub = je[je["document_id"].isin(d)]
    wkend_docs = set(sub.loc[sub["_dow"].isin([5, 6]), "document_id"].unique())
    record("L3-05", len(d), len(wkend_docs), "posting_date is Saturday or Sunday")
else:
    record("L3-05", 0, 0, "라벨 없음")

# ── L3-06: 야간 전기(22:00~06:59) ──────────────────────────────────────────────
d = label_docs(["AfterHoursPosting", "UnusualTiming"])
if d:
    sub = je[je["document_id"].isin(d)]
    night_hours = list(range(22, 24)) + list(range(0, 7))
    night_docs = set(sub.loc[sub["_posting_hour"].isin(night_hours), "document_id"].unique())
    record("L3-06", len(d), len(night_docs), "posting_hour in 22:00~06:59")
else:
    record("L3-06", 0, 0, "라벨 없음")

# ── L3-07: 역일(|posting_date - document_date| > 30일) ─────────────────────────
d = label_docs(["BackdatedEntry", "LatePosting"])
if d:
    sub = je[je["document_id"].isin(d)]
    # Why: 절댓값 기준 - 미래/과거 양방향 30일 초과 모두 탐지
    late_docs = set(sub.loc[abs(sub["_day_diff"]) > 30, "document_id"].unique())
    record("L3-07", len(d), len(late_docs), "|posting_date - document_date| > 30 days")
else:
    record("L3-07", 0, 0, "라벨 없음")

# ── L3-08: 설명 부실 ───────────────────────────────────────────────────────────
d = label_docs(["VagueDescription"])
if d:
    sub = je[je["document_id"].isin(d)]
    vague_kw = ["misc", "test", "temp", "n/a", "na", "tbd", "unknown",
                "xxx", "zzz", "조정", "기타", "수정", "임시", "테스트"]

    def is_vague(txt) -> bool:
        if pd.isna(txt) or str(txt).strip() == "":
            return True
        s = str(txt).strip()
        if len(s) < 3:
            return True
        sl = s.lower()
        return any(k in sl for k in vague_kw)

    vague_rows = sub[sub["line_text"].apply(is_vague)]
    ver = len(set(vague_rows["document_id"].unique()))
    record("L3-08", len(d), ver, "blank / <3 chars / vague keywords in line_text")
else:
    record("L3-08", 0, 0, "라벨 없음")

# ── L2-06: 역분개 쌍 ──────────────────────────────────────────────────────────
d = label_docs(["ReversedAmount"])
if d:
    sub = je[je["document_id"].isin(d)].copy()

    def has_reversal(g: pd.DataFrame) -> bool:
        """같은 GL, 같은 금액이 DR/CR 양쪽에 모두 존재하는지 확인."""
        dr_set = set(
            zip(g["_gl_str"], g["debit_amount"].where(g["debit_amount"] > 0).round(2))
        ) - {(gl, np.nan) for gl in g["_gl_str"]}
        cr_set = set(
            zip(g["_gl_str"], g["credit_amount"].where(g["credit_amount"] > 0).round(2))
        ) - {(gl, np.nan) for gl in g["_gl_str"]}
        # Why: DR set과 CR set의 교집합이 있으면 역분개 쌍 존재
        return len(dr_set & cr_set) > 0

    grp_check = sub.groupby("document_id").apply(has_reversal)
    ver = int(grp_check.sum())
    record("L2-06", len(d), ver, "DR/CR reversal pairs (same GL, same amount)")
else:
    record("L2-06", 0, 0, "라벨 없음")

# ── 요약 ────────────────────────────────────────────────────────────────────
total_labels   = sum(r["total"]    for r in results_p1)
total_verified = sum(r["verified"] for r in results_p1)
overall_pct    = total_verified / total_labels * 100 if total_labels > 0 else 0
print("  " + "-" * 72)
print(f"  {'합계':<5}  {total_labels:>8,}  {total_verified:>8,}  {overall_pct:>6.1f}%  전체 검증률")


# ════════════════════════════════════════════════════════════════════════════
# PART 2: 정상 데이터 오염 검사
# ════════════════════════════════════════════════════════════════════════════
print()
print("=" * 78)
print("PART 2: 정상 데이터 오염 검사 (is_fraud=False AND is_anomaly=False 행)")
print("=" * 78)

normal_je = je[(je["is_fraud"] == False) & (je["is_anomaly"] == False)].copy()
normal_docs = set(normal_je["document_id"].unique())

print(f"  정상 행 수   : {len(normal_je):>10,}")
print(f"  정상 문서 수 : {len(normal_docs):>10,}")
print()
print(f"  {'검사항목':<38}  {'결과':>14}  판정")
print("  " + "-" * 68)


def p2_row(label, count, total, note="", is_contamination=True):
    pct = count / total * 100 if total > 0 else 0
    if is_contamination:
        status = "★ 오염" if count > 0 else "정상"
    else:
        status = "[참고]"
    print(f"  {label:<38}  {count:>6,} ({pct:>5.2f}%)  {status}  {note}")


# L1-01: 불균형 전표
grp_normal = normal_je.groupby("document_id").agg(
    sum_dr=("debit_amount", "sum"), sum_cr=("credit_amount", "sum")
)
unbal = int((abs(grp_normal["sum_dr"] - grp_normal["sum_cr"]) > 0.01).sum())
p2_row("L1-01: 불균형 전표 문서 수", unbal, len(normal_docs))

# L1-03: CoA 외 GL
invalid_normal = ~normal_je["_gl_str"].isin(coa_set)
invalid_rows_n = int(invalid_normal.sum())
p2_row("L1-03: CoA 외 GL 행 수", invalid_rows_n, len(normal_je))
if invalid_rows_n > 0:
    sample_gls = normal_je.loc[invalid_normal, "_gl_str"].value_counts().head(5)
    print(f"       샘플 GL: {dict(sample_gls)}")

# L1-07: 승인자 NULL
null_appr_normal = normal_je["approved_by"].isna()
p2_row("L1-07: approved_by NULL 행 수", int(null_appr_normal.sum()), len(normal_je),
       f"({normal_je.loc[null_appr_normal, 'document_id'].nunique()} docs)")

# L3-07: 역일 (절댓값 기준)
late_normal = abs(normal_je["_day_diff"]) > 30
p2_row("L3-07: |posting-doc_date| > 30일 행 수", int(late_normal.sum()), len(normal_je),
       f"({normal_je.loc[late_normal, 'document_id'].nunique()} docs)")

print()
print("  [ 허용 가능 패턴 - 비율이 비정상적으로 높으면 DataSynth 파라미터 점검 ]")

# L1-05: 자기승인
self_appr_n = normal_je["created_by"] == normal_je["approved_by"]
p2_row("L1-05: 자기승인 행 수", int(self_appr_n.sum()), len(normal_je),
       "승인 정책상 허용 가능", is_contamination=False)

# L1-06: SoD 위반 - CRITICAL CHECK
if "sod_violation" in normal_je.columns:
    sod_n = normal_je["sod_violation"] == True
    sod_cnt = int(sod_n.sum())
    sod_pct = sod_cnt / len(normal_je) * 100
    flag = " ← ★ CRITICAL: DataSynth 버그 의심" if sod_pct > 5 else ""
    p2_row("L1-06: sod_violation=True 행 수", sod_cnt, len(normal_je),
           f"정책상 허용 가능{flag}", is_contamination=False)

# L3-02: 수동 입력
manual_n = normal_je["source"].str.lower().str.contains("manual", na=False)
p2_row("L3-02: source='manual' 행 수", int(manual_n.sum()), len(normal_je),
       "승인된 수동 입력 가능", is_contamination=False)

# L3-05: 주말
wkend_n = normal_je["_dow"].isin([5, 6])
p2_row("L3-05: 주말 전기 행 수", int(wkend_n.sum()), len(normal_je),
       "허용 운영 가능", is_contamination=False)

# L3-06: 야간 - posting_date가 date-only면 hour=0, 별도 안내
night_hours_n = list(range(22, 24)) + list(range(0, 7))
sample_hours = normal_je["_posting_hour"].value_counts().head(5).to_dict()
if set(normal_je["_posting_hour"].unique()) == {0}:
    print(f"  {'L3-06: 야간 전기':<38}  N/A  [참고]  posting_date date-only, 시간 정보 없음")
else:
    night_n = normal_je["_posting_hour"].isin(night_hours_n)
    p2_row("L3-06: 야간(22-06) 전기 행 수", int(night_n.sum()), len(normal_je),
           "허용 운영 가능", is_contamination=False)


# ════════════════════════════════════════════════════════════════════════════
# PART 3: L1-06 sod_violation 심층 분석
# ════════════════════════════════════════════════════════════════════════════
print()
print("=" * 78)
print("PART 3: L1-06 sod_violation 심층 분석")
print("=" * 78)

sod_total = int(je["sod_violation"].sum())
total_rows = len(je)
sod_pct_total = sod_total / total_rows * 100

normal_je_b07 = je[(je["is_fraud"] == False) & (je["is_anomaly"] == False)]
sod_normal_cnt = int(normal_je_b07["sod_violation"].sum())
sod_normal_pct = sod_normal_cnt / len(normal_je_b07) * 100

al_b07_cnt = len(lbl[lbl["anomaly_type"] == "SegregationOfDutiesViolation"])

print()
print(f"  탐지 사용 컬럼    : sod_violation (bool)")
print(f"  전체 sod=True     : {sod_total:>8,} / {total_rows:,} ({sod_pct_total:.2f}%)")
print(f"  정상 데이터 sod=True: {sod_normal_cnt:>8,} / {len(normal_je_b07):,} ({sod_normal_pct:.2f}%)")
print(f"  L1-06 anomaly_labels: {al_b07_cnt:>8,} 건")

print()
print("  [ is_fraud x is_anomaly 조합별 sod_violation=True 비율 ]")
print(f"  {'is_fraud':<10} {'is_anomaly':<12} {'전체 행':>10} {'sod=True':>10} {'비율':>8}")
print("  " + "-" * 55)
for fraud_val in [False, True]:
    for anom_val in [False, True]:
        grp = je[(je["is_fraud"] == fraud_val) & (je["is_anomaly"] == anom_val)]
        if len(grp) == 0:
            continue
        sod_cnt = int(grp["sod_violation"].sum())
        sod_p = sod_cnt / len(grp) * 100
        print(f"  {str(fraud_val):<10} {str(anom_val):<12} {len(grp):>10,} {sod_cnt:>10,} {sod_p:>7.2f}%")

print()
print("  [ sod_conflict_type 분포 (sod=True인 행) ]")
sod_true_rows = je[je["sod_violation"] == True]
sct = sod_true_rows["sod_conflict_type"].value_counts(dropna=False)
for val, cnt in sct.head(10).items():
    print(f"    {str(val):<35} {cnt:>8,}")

null_conflict = int(sod_true_rows["sod_conflict_type"].isnull().sum())
print(f"  sod=True 중 conflict_type=NaN : {null_conflict:,} / {len(sod_true_rows):,} "
      f"({null_conflict/len(sod_true_rows)*100:.1f}%)")

# L1-06 라벨 vs sod=True 문서
docs_b07_lbl = label_docs(["SegregationOfDutiesViolation"])
docs_sod_true = set(je[je["sod_violation"] == True]["document_id"].unique())
print()
print(f"  L1-06 라벨 문서            : {len(docs_b07_lbl):>8,}")
print(f"  sod=True 문서 (전체 JE)  : {len(docs_sod_true):>8,}")
overlap = len(docs_b07_lbl & docs_sod_true)
print(f"  교집합 (라벨 ∩ sod=True) : {overlap:>8,}")

print()
print("  [ 진단 결론 ]")
if sod_pct_total > 90:
    print(f"  ★ CRITICAL BUG: sod_violation=True 비율 {sod_pct_total:.1f}%")
    print("    DataSynth이 sod_violation 컬럼을 anomaly_labels 주입과 독립적으로")
    print("    생성하면서 대부분의 행에 True를 할당하는 버그로 추정.")
    print("    L1-06 탐지기가 이 컬럼을 직접 사용하면 False Positive 폭발.")
    print(f"    → 권고: sod_violation 컬럼 재생성 또는 L1-06 탐지 로직 수정 필요")
elif sod_pct_total > 10:
    print(f"  WARNING: sod_violation=True 비율 {sod_pct_total:.1f}% - 파라미터 재검토 권장")
else:
    print(f"  OK: sod_violation=True 비율 {sod_pct_total:.1f}% - 정상 범위")

print()
print("=== 감사 완료 ===")
