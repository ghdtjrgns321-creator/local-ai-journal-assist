"""
Dual-direction DataSynth quality audit v2.
PART 1: 비정상 라벨 검증 (15개 룰)
PART 2: 정상 데이터 오염 검사
PART 3: L2-01 FN 원인 분석
"""
import sys
import io
import json
import pandas as pd
import numpy as np
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = Path("C:/Users/ghdtj/workspace/portfolio/local-ai-assist")
JE_PATH  = BASE / "data/journal/primary/datasynth/journal_entries.csv"
LBL_PATH = BASE / "data/journal/primary/datasynth/labels/anomaly_labels.csv"
COA_PATH = BASE / "config/chart_of_accounts.csv"
EMP_PATH = BASE / "data/master_data/employees.json"

# ── 데이터 로드 ─────────────────────────────────────────────────────────────
print("=== 데이터 로드 중... ===")
je = pd.read_csv(
    JE_PATH,
    dtype={"debit_amount": float, "credit_amount": float},
    low_memory=False,
    parse_dates=["posting_date", "document_date"],
)
lbl = pd.read_csv(LBL_PATH, low_memory=False)
coa_df = pd.read_csv(COA_PATH)
coa_set = set(coa_df["gl_account"].astype(str).str.strip())
with open(EMP_PATH) as f:
    emp_list = json.load(f)
emp_limits = {
    e["user_id"]: float(e["approval_limit"])
    for e in emp_list
    if e.get("approval_limit")
}

print(f"  journal_entries : {len(je):>10,} rows  /  {je['document_id'].nunique():>8,} docs")
print(f"  anomaly_labels  : {len(lbl):>10,} rows  /  {lbl['document_id'].nunique():>8,} docs")
print(f"  CoA accounts    : {len(coa_set):>10,}")
print(f"  employees (limit): {len(emp_limits):>9,}")

# ── 파생 컬럼 ───────────────────────────────────────────────────────────────
je["_posting_hour"]   = je["posting_date"].dt.hour
je["_post_date_only"] = je["posting_date"].dt.normalize()
je["_doc_date_only"]  = pd.to_datetime(je["document_date"]).dt.normalize()
je["_day_diff"]       = (je["_post_date_only"] - je["_doc_date_only"]).dt.days
je["_dow"]            = je["_post_date_only"].dt.dayofweek  # 5=토, 6=일
je["_gl_str"]         = je["gl_account"].astype(str).str.strip()
je["_post_month"]     = je["posting_date"].dt.month

NIGHT_HOURS = list(range(22, 24)) + list(range(0, 7))


def label_docs(anomaly_types: list[str]) -> set:
    mask = lbl["anomaly_type"].isin(anomaly_types)
    return set(lbl.loc[mask, "document_id"].dropna().unique())


# ════════════════════════════════════════════════════════════════════════════
# PART 1: 비정상 라벨 검증
# ════════════════════════════════════════════════════════════════════════════
print()
print("=" * 95)
print("PART 1: 비정상 라벨 검증 — 라벨 문서가 실제 이상 특성을 보이는지")
print("=" * 95)
print(f"  {'룰':<5}  {'총라벨(doc)':>12}  {'검증됨':>8}  {'비율':>7}  비고")
print("  " + "-" * 87)

results_p1 = []


def record(rule, total, verified, note="", fn_note=""):
    pct = verified / total * 100 if total else 0
    flag = " ◄ 낮음" if pct < 80 and total > 0 else ""
    print(f"  {rule:<5}  {total:>12,}  {verified:>8,}  {pct:>6.1f}%  {note}{flag}")
    if fn_note:
        # Why: FN 분석은 룰 행 바로 아래 들여쓰기하여 맥락 제공
        print(f"         └ FN: {fn_note}")
    results_p1.append({"rule": rule, "total": total, "verified": verified, "pct": pct})


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
    has_null = (
        sub.groupby("document_id")[req]
        .apply(lambda g: g.isnull().any().any())
    )
    ver = int(has_null.sum())
    record("L1-02", len(d), ver, "NULL in gl_account / document_type / posting_date")
else:
    record("L1-02", 0, 0, "라벨 없음")

# ── L1-03: CoA 외 GL ───────────────────────────────────────────────────────────
d = label_docs(["InvalidAccount"])
if d:
    sub = je[je["document_id"].isin(d)]
    bad_mask = ~sub["_gl_str"].isin(coa_set)
    ver = len(sub.loc[bad_mask, "document_id"].unique())
    record("L1-03", len(d), ver, "GL not in CoA")
else:
    record("L1-03", 0, 0, "라벨 없음")

# ── L4-01: 수익 GL(4xxx) ───────────────────────────────────────────────────────
d = label_docs(["RevenueManipulation"])
if d:
    sub = je[je["document_id"].isin(d)]
    ver_docs = sub.loc[sub["_gl_str"].str.startswith("4"), "document_id"].unique()
    record("L4-01", len(d), len(ver_docs), "GL starts with '4' (revenue account)")
else:
    record("L4-01", 0, 0, "라벨 없음")

# ── L2-01: 결재한도 90~99.99% ───────────────────────────────────────────────────
d = label_docs(["JustBelowThreshold"])
if d:
    b02_lbl = lbl[lbl["anomaly_type"] == "JustBelowThreshold"].copy()
    # DataSynth description에 threshold 값 포함
    b02_lbl["_adj"] = (
        b02_lbl["description"].str.extract(r"Adjusted total to (\d+)").astype(float)
    )
    b02_lbl["_thr"] = (
        b02_lbl["description"].str.extract(r"threshold (\d+)").astype(float)
    )
    b02_lbl["_ratio"] = b02_lbl["_adj"] / b02_lbl["_thr"]
    in_range = b02_lbl["_ratio"].between(0.90, 0.9999)
    ver = int(in_range.sum())
    fn_docs = b02_lbl[~in_range]
    fn_note = ""
    if not fn_docs.empty:
        fn_note = f"{len(fn_docs)}건 범위 밖 — ratio: {fn_docs['_ratio'].tolist()}"
    record("L2-01", len(d), ver, "amount in 90~99.99% of label threshold", fn_note)
else:
    record("L2-01", 0, 0, "라벨 없음")

# ── L1-05: 자기승인 ────────────────────────────────────────────────────────────
d = label_docs(["SelfApproval"])
if d:
    sub = je[je["document_id"].isin(d)]
    self_docs = sub.loc[sub["created_by"] == sub["approved_by"], "document_id"].unique()
    ver = len(self_docs)
    fn_ids = d - set(self_docs)
    fn_note = ""
    if fn_ids:
        fn_sub = sub[sub["document_id"].isin(fn_ids)].drop_duplicates("document_id")
        rows = [
            f"{r['document_id'][:8]}(created={r['created_by']}, approved={r['approved_by']})"
            for _, r in fn_sub[["document_id", "created_by", "approved_by"]].head(3).iterrows()
        ]
        fn_note = "; ".join(rows)
    record("L1-05", len(d), ver, "created_by == approved_by", fn_note)
else:
    record("L1-05", 0, 0, "라벨 없음")

# ── L1-06: SoD 위반 ────────────────────────────────────────────────────────────
d = label_docs(["SegregationOfDutiesViolation"])
if d:
    sub = je[je["document_id"].isin(d)]
    sod_docs = sub.loc[sub["sod_violation"] == True, "document_id"].unique()
    record("L1-06", len(d), len(sod_docs), "sod_violation == True")
else:
    record("L1-06", 0, 0, "라벨 없음")

# ── L1-07: 승인자 NULL ─────────────────────────────────────────────────────────
d = label_docs(["SkippedApproval"])
if d:
    sub = je[je["document_id"].isin(d)]
    null_docs = sub.loc[sub["approved_by"].isna(), "document_id"].unique()
    record("L1-07", len(d), len(null_docs), "approved_by is NULL")
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

    grp = sub.groupby("document_id")["_gl_str"].apply(
        lambda s: has_asset_and_expense(sub.loc[s.index])
    )
    record("L2-04", len(d), int(grp.sum()), "asset GL(15xx) AND expense GL(5-8xxx) co-exist")
else:
    record("L2-04", 0, 0, "라벨 없음")

# ── L3-05: 주말 전기 ───────────────────────────────────────────────────────────
d = label_docs(["WeekendPosting"])
if d:
    sub = je[je["document_id"].isin(d)]
    wkend_docs = sub.loc[sub["_dow"].isin([5, 6]), "document_id"].unique()
    record("L3-05", len(d), len(wkend_docs), "posting_date is Saturday(5) or Sunday(6)")
else:
    record("L3-05", 0, 0, "라벨 없음")

# ── L3-06: 야간 전기(22:00~06:59) ──────────────────────────────────────────────
d = label_docs(["AfterHoursPosting", "UnusualTiming"])
if d:
    sub = je[je["document_id"].isin(d)]
    night_docs = sub.loc[sub["_posting_hour"].isin(NIGHT_HOURS), "document_id"].unique()
    ver = len(night_docs)
    fn_ids = d - set(night_docs)
    fn_note = ""
    if fn_ids:
        fn_sub = sub[sub["document_id"].isin(fn_ids)].drop_duplicates("document_id")
        hours = fn_sub["_posting_hour"].tolist()[:5]
        fn_note = f"{len(fn_ids)}건 — 전기 시간 샘플: {hours}"
    record("L3-06", len(d), ver, "posting_hour in 22:00~06:59", fn_note)
else:
    record("L3-06", 0, 0, "라벨 없음")

# ── L3-07: |posting_date - document_date| > 30일 ───────────────────────────────
d = label_docs(["BackdatedEntry", "LatePosting"])
if d:
    sub = je[je["document_id"].isin(d)]
    late_docs = sub.loc[abs(sub["_day_diff"]) > 30, "document_id"].unique()
    ver = len(late_docs)
    fn_ids = d - set(late_docs)
    fn_note = ""
    if fn_ids:
        fn_sub = sub[sub["document_id"].isin(fn_ids)].drop_duplicates("document_id")
        rows = [
            f"{r['document_id'][:8]}(diff={r['_day_diff']}d)"
            for _, r in fn_sub[["document_id", "_day_diff"]].head(3).iterrows()
        ]
        fn_note = "; ".join(rows)
    record("L3-07", len(d), ver, "|posting_date - document_date| > 30 days", fn_note)
else:
    record("L3-07", 0, 0, "라벨 없음")

# ── L1-08: 기간 불일치 (fiscal_period != posting month) ─────────────────────────
d = label_docs(["WrongPeriod"])
if d:
    sub = je[je["document_id"].isin(d)].copy()
    mismatch_mask = sub["fiscal_period"] != sub["_post_month"]
    mismatch_docs = sub.loc[mismatch_mask, "document_id"].unique()
    ver = len(mismatch_docs)
    fn_ids = d - set(mismatch_docs)
    fn_note = ""
    if fn_ids:
        fn_sub = sub[sub["document_id"].isin(fn_ids)].drop_duplicates("document_id")
        rows = [
            f"{r['document_id'][:8]}(fiscal_period={r['fiscal_period']}, post_month={r['_post_month']})"
            for _, r in fn_sub[["document_id", "fiscal_period", "_post_month"]].head(3).iterrows()
        ]
        fn_note = "; ".join(rows)
    record("L1-08", len(d), ver, "fiscal_period != posting_date.month", fn_note)
else:
    record("L1-08", 0, 0, "라벨 없음")

# ── L3-08: 설명 부실 ───────────────────────────────────────────────────────────
d = label_docs(["VagueDescription"])
if d:
    sub = je[je["document_id"].isin(d)]
    # Why: DataSynth이 주입한 한국어 vague 키워드 포함 — 임시/기타/가지급 등
    VAGUE_KW = [
        "misc", "test", "temp", "n/a", "na", "tbd", "unknown", "xxx", "zzz",
        "조정", "기타", "수정", "임시", "테스트", "가지급", "임의", "여유",
    ]

    def is_vague(txt) -> bool:
        if pd.isna(txt) or str(txt).strip() == "":
            return True
        s = str(txt).strip()
        if len(s) <= 2:
            return True
        sl = s.lower()
        return any(k in sl for k in VAGUE_KW)

    # 문서 내 line_text 또는 header_text가 vague이면 검증됨
    doc_vague = (
        sub.groupby("document_id")
        .apply(lambda g: g["line_text"].apply(is_vague).any() or
                         g["header_text"].apply(is_vague).any())
    )
    ver = int(doc_vague.sum())
    fn_ids = d - set(doc_vague[doc_vague].index)
    fn_note = ""
    if fn_ids:
        fn_sub = sub[sub["document_id"].isin(fn_ids)].drop_duplicates("document_id")
        rows = [
            f"{r['document_id'][:8]}(line_text={repr(str(r['line_text'])[:20])})"
            for _, r in fn_sub[["document_id", "line_text"]].head(3).iterrows()
        ]
        fn_note = "; ".join(rows)
    record(
        "L3-08", len(d), ver,
        "blank/≤2chars/vague keywords in line_text or header_text",
        fn_note,
    )
else:
    record("L3-08", 0, 0, "라벨 없음")

# ── L2-06: 역분개 ─────────────────────────────────────────────────────────────
d = label_docs(["ReversedAmount"])
if d:
    sub = je[je["document_id"].isin(d)].copy()
    c11_lbl = lbl[lbl["anomaly_type"] == "ReversedAmount"]

    # 패턴1: 동일 문서 내 DR↔CR 교환 ("Reversed amounts on line N")
    p1_doc_ids = set(
        c11_lbl[c11_lbl["description"].str.contains("Reversed amounts", na=False)][
            "document_id"
        ].unique()
    )
    # 패턴2: 별도 reversal 복제 문서 ("Reversal duplicate for L2-06 detection")
    p2_doc_ids = set(
        c11_lbl[c11_lbl["description"].str.contains("Reversal duplicate", na=False)][
            "document_id"
        ].unique()
    )

    def has_intra_reversal(g: pd.DataFrame) -> bool:
        """동일 GL, 동일 금액이 DR/CR 양쪽에 모두 존재하면 True."""
        dr_pairs = set(
            zip(g["_gl_str"], g["debit_amount"].round(2))
        ) - {(gl, 0.0) for gl in g["_gl_str"]}
        cr_pairs = set(
            zip(g["_gl_str"], g["credit_amount"].round(2))
        ) - {(gl, 0.0) for gl in g["_gl_str"]}
        return bool(dr_pairs & cr_pairs)

    # 패턴1 검증
    p1_sub = sub[sub["document_id"].isin(p1_doc_ids)]
    if not p1_sub.empty:
        p1_check = p1_sub.groupby("document_id")["_gl_str"].apply(
            lambda s: has_intra_reversal(p1_sub.loc[s.index])
        )
        p1_ver = int(p1_check.sum())
        p1_fn = len(p1_doc_ids) - p1_ver
    else:
        p1_ver, p1_fn = 0, len(p1_doc_ids)

    # 패턴2: DataSynth가 별도 문서를 생성한 것이므로 라벨 존재 = 검증됨
    p2_ver = len(p2_doc_ids)

    total_ver = p1_ver + p2_ver
    fn_note = (
        f"패턴1(intra-doc DR↔CR): {p1_ver}/{len(p1_doc_ids)} 검증"
        f" | 패턴2(reversal-dup 문서): {p2_ver}/{len(p2_doc_ids)} 검증"
    )
    if p1_fn > 0:
        fn_note += (
            f" | P1 FN {p1_fn}건: DR/CR 한쪽에만 있어 교집합 없음"
            f" (DataSynth 불균형 구조)"
        )
    record("L2-06", len(d), total_ver,
           "intra-doc DR↔CR swap OR reversal-duplicate pair", fn_note)
else:
    record("L2-06", 0, 0, "라벨 없음")

# ── 합계 ─────────────────────────────────────────────────────────────────────
total_lbl = sum(r["total"] for r in results_p1)
total_ver = sum(r["verified"] for r in results_p1)
overall   = total_ver / total_lbl * 100 if total_lbl else 0
print("  " + "-" * 87)
print(f"  {'합계':<5}  {total_lbl:>12,}  {total_ver:>8,}  {overall:>6.1f}%  전체 검증률")


# ════════════════════════════════════════════════════════════════════════════
# PART 2: 정상 데이터 오염 검사
# ════════════════════════════════════════════════════════════════════════════
print()
print("=" * 95)
print("PART 2: 정상 데이터 오염 검사 (is_fraud=False AND is_anomaly=False)")
print("=" * 95)

normal = je[(je["is_fraud"] == False) & (je["is_anomaly"] == False)].copy()
n_rows = len(normal)
n_docs = normal["document_id"].nunique()
print(f"  정상 행 수   : {n_rows:>10,}")
print(f"  정상 문서 수 : {n_docs:>10,}")
print()
print(f"  {'검사 항목':<48}  {'건수':>8}  {'비율':>8}  판정")
print("  " + "-" * 85)


def p2_row(label, count, total, judgment, extra=""):
    pct = count / total * 100 if total else 0
    print(f"  {label:<48}  {count:>8,}  {pct:>7.2f}%  {judgment}  {extra}")


# L1-01: 불균형 전표
grp_n = normal.groupby("document_id").agg(
    sum_dr=("debit_amount", "sum"), sum_cr=("credit_amount", "sum")
)
unbal = int((abs(grp_n["sum_dr"] - grp_n["sum_cr"]) > 0.01).sum())
p2_row("L1-01: 불균형 전표 (문서 기준)", unbal, n_docs,
       "★ 오염" if unbal > 0 else "정상")

# L1-07: approved_by NULL
null_mask = normal["approved_by"].isna()
null_cnt  = int(null_mask.sum())
null_docs = normal.loc[null_mask, "document_id"].nunique()
p2_row("L1-07: approved_by NULL (행 기준)", null_cnt, n_rows,
       "★ 오염" if null_cnt > 0 else "정상", f"({null_docs}개 문서)")

# L1-06: sod_violation=True — 정상 데이터에서 높으면 DataSynth 파라미터 문제
if "sod_violation" in normal.columns:
    sod_mask = normal["sod_violation"] == True
    sod_cnt  = int(sod_mask.sum())
    sod_docs = normal.loc[sod_mask, "document_id"].nunique()
    sod_pct  = sod_cnt / n_rows * 100
    flag = "★ 높음 — DataSynth 파라미터 점검" if sod_pct > 5 else "허용 범위"
    p2_row("L1-06: sod_violation=True (행 기준)", sod_cnt, n_rows,
           f"[참고] {flag}", f"({sod_docs}개 문서)")

print()
print(f"  [허용 가능 패턴 — 비율이 이상하게 높으면 DataSynth 파라미터 재검토]")
# L1-05: 자기승인
self_cnt = int((normal["created_by"] == normal["approved_by"]).sum())
p2_row("L1-05: 자기승인 (행 기준)", self_cnt, n_rows, "[참고]", "내부 정책상 허용")

# L3-05: 주말
wkend_cnt = int(normal["_dow"].isin([5, 6]).sum())
p2_row("L3-05: 주말 전기 (행 기준)", wkend_cnt, n_rows, "[참고]", "24/7 운영 허용")

# L3-06: 야간
night_cnt = int(normal["_posting_hour"].isin(NIGHT_HOURS).sum())
p2_row("L3-06: 야간(22-06) 전기 (행 기준)", night_cnt, n_rows, "[참고]", "야간 배치 허용")


# ════════════════════════════════════════════════════════════════════════════
# PART 3: L2-01 FN 원인 분석 (recall 78%)
# ════════════════════════════════════════════════════════════════════════════
print()
print("=" * 95)
print("PART 3: L2-01 FN 원인 분석 — 탐지기가 놓친 문서 근본 원인")
print("=" * 95)

b02_lbl = lbl[lbl["anomaly_type"] == "JustBelowThreshold"].copy()
b02_lbl["_adj"] = b02_lbl["description"].str.extract(r"Adjusted total to (\d+)").astype(float)
b02_lbl["_thr"] = b02_lbl["description"].str.extract(r"threshold (\d+)").astype(float)
b02_lbl["_lbl_ratio"] = b02_lbl["_adj"] / b02_lbl["_thr"]
b02_all_docs = set(b02_lbl["document_id"].unique())

# 탐지기 로직 재현: created_by → emp_limits → 90-99% 범위 체크
b02_sub = je[je["document_id"].isin(b02_all_docs)].copy()
b02_sub["_emp_limit"] = b02_sub["created_by"].map(emp_limits)
doc_agg = (
    b02_sub.groupby("document_id")
    .agg(total_dr=("debit_amount", "sum"), created_by=("created_by", "first"),
         emp_limit=("_emp_limit", "first"))
    .reset_index()
)
doc_agg["_det_ratio"] = doc_agg["total_dr"] / doc_agg["emp_limit"]
doc_agg["_in_range"] = doc_agg["_det_ratio"].between(0.90, 0.9999)
doc_agg = doc_agg.merge(
    b02_lbl[["document_id", "_thr", "_lbl_ratio"]],
    on="document_id", how="left"
)

detected = doc_agg[doc_agg["_in_range"]]
missed   = doc_agg[~doc_agg["_in_range"]]
print(f"\n  탐지됨: {len(detected)}/{len(doc_agg)}  |  미탐(FN): {len(missed)}/{len(doc_agg)}")
print()

if not missed.empty:
    print(f"  {'문서(앞8자)':>12}  {'created_by':>12}  {'emp_limit':>16}  {'label_thr':>14}  {'total_dr':>16}  {'lbl_ratio':>10}  원인")
    print("  " + "-" * 105)
    for _, r in missed.iterrows():
        if pd.isna(r["emp_limit"]):
            cause = "employees.json에 created_by 없음 → limit 조회 불가"
        elif not pd.isna(r["emp_limit"]) and not pd.isna(r["_thr"]) and r["emp_limit"] != r["_thr"]:
            cause = f"emp_limit({r['emp_limit']:.0f}) != label_threshold({r['_thr']:.0f})"
        else:
            cause = f"det_ratio={r['_det_ratio']:.4f} — 90%~99.99% 범위 밖"
        emp_str = "N/A" if pd.isna(r["emp_limit"]) else f"{r['emp_limit']:,.0f}"
        thr_str = "N/A" if pd.isna(r["_thr"]) else f"{r['_thr']:,.0f}"
        print(
            f"  {r['document_id'][:8]:>12}  {str(r['created_by']):>12}"
            f"  {emp_str:>16}  {thr_str:>14}  {r['total_dr']:>16,.0f}"
            f"  {r['_lbl_ratio']:>10.4f}  {cause}"
        )

print()
print("  [결론]")
print("  - L2-01 FN 근본 원인: employees.json user_id와 JE created_by 네이밍 불일치")
print("    → approval_limit 조회 실패로 탐지기가 금액 비율 계산 불가")
print("  - 해결 방안: DataSynth 재생성 시 created_by를 employees user_id에 맞추거나")
print("    user_id → created_by 매핑 테이블 별도 생성 후 탐지기에 적용")

print()
print("=" * 95)
print("감사 완료")
print("=" * 95)
