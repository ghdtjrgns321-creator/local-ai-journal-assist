"""
마스터데이터 참조무결성·통제 정합 측정 스크립트
측정·보고 전용 — 수정 없음
기본 대상: datasynth_semantic_v1_normal_20260613_v42j (정상 데이터셋)
"""

import json
import sys
from pathlib import Path

import pandas as pd

BASE = (
    Path(sys.argv[1])
    if len(sys.argv) > 1
    else Path("data/journal/primary/datasynth_semantic_v1_normal_20260613_v42j")
)

# ─────────────────────────────────────────────
# 데이터 로드
# ─────────────────────────────────────────────
print("=== 마스터데이터 참조무결성·통제 정합 측정 ===\n")
print(f"[데이터셋] {BASE}\n")

journal_path = BASE / "journal_entries.csv"
df_raw = pd.read_csv(journal_path, low_memory=False)

# 정상 데이터만 — is_fraud=False, is_anomaly=False 행
df = df_raw[(df_raw["is_fraud"] == False) & (df_raw["is_anomaly"] == False)].copy()
total_raw = len(df_raw)
total_normal = len(df)
print(
    f"[데이터셋] 전체 행: {total_raw:,}  |  정상(is_fraud=False & is_anomaly=False): {total_normal:,}"
)

# 문서 단위 집계 — 금액은 debit_amount 합산 (approved_by·created_by 기준)
doc_df = (
    df.groupby(
        [
            "document_id",
            "company_code",
            "created_by",
            "approved_by",
            "sod_violation",
            "sod_conflict_type",
            "cost_center",
        ],
        dropna=False,
    )
    .agg(doc_amount=("debit_amount", "sum"))
    .reset_index()
)
total_docs = len(doc_df)
print(f"[문서 단위] 정상 문서 수: {total_docs:,}\n")

# 마스터 로드
with open(BASE / "master_data/employees.json", encoding="utf-8") as f:
    employees = json.load(f)
with open(BASE / "master_data/vendors.json", encoding="utf-8") as f:
    vendors = json.load(f)
with open(BASE / "master_data/customers.json", encoding="utf-8") as f:
    customers = json.load(f)

emp_df = pd.DataFrame(employees)
vendor_ids = {v["vendor_id"] for v in vendors}
customer_ids = {c["customer_id"] for c in customers}
emp_user_ids = set(emp_df["user_id"].dropna())
print(f"[마스터] 직원: {len(emp_df)}명 | 벤더: {len(vendor_ids)} | 고객: {len(customer_ids)}\n")

# ─────────────────────────────────────────────
# 1. 참조 무결성
# ─────────────────────────────────────────────
print("=" * 60)
print("1. 참조 무결성")
print("=" * 60)

# created_by 고아
created_vals = df["created_by"].dropna().unique()
orphan_created = set(created_vals) - emp_user_ids
orphan_created_rows = df[df["created_by"].isin(orphan_created)]
print(f"  created_by  총 고유값: {len(created_vals)}")
print(
    f"  employees 미존재 user_id: {len(orphan_created)}개  |  해당 행: {len(orphan_created_rows):,}건"
)
if orphan_created:
    print(f"    샘플: {list(orphan_created)[:5]}")

# approved_by 고아 (null 제외)
approved_vals = df["approved_by"].dropna().unique()
orphan_approved = set(approved_vals) - emp_user_ids
orphan_approved_rows = df[df["approved_by"].isin(orphan_approved)]
print(f"  approved_by 총 고유값: {len(approved_vals)}")
print(
    f"  employees 미존재 user_id: {len(orphan_approved)}개  |  해당 행: {len(orphan_approved_rows):,}건"
)
if orphan_approved:
    print(f"    샘플: {list(orphan_approved)[:5]}")

# trading_partner 고아
tp_vals = df["trading_partner"].dropna().unique()
tp_vendor = {v for v in tp_vals if str(v).startswith("V-")}
tp_customer = {v for v in tp_vals if str(v).startswith("C-")}
tp_other = {v for v in tp_vals if not str(v).startswith(("V-", "C-"))}
orphan_tp_v = tp_vendor - vendor_ids
orphan_tp_c = tp_customer - customer_ids
tp_orphan_rows = df[df["trading_partner"].isin(orphan_tp_v | orphan_tp_c)]
print(
    f"  trading_partner 총 고유값: {len(tp_vals)}  (V- {len(tp_vendor)} | C- {len(tp_customer)} | 기타 {len(tp_other)})"
)
print(
    f"  벤더 미존재: {len(orphan_tp_v)}개 | 고객 미존재: {len(orphan_tp_c)}개  |  해당 행: {len(tp_orphan_rows):,}건"
)

ri_fail = (len(orphan_created) + len(orphan_approved) + len(orphan_tp_v) + len(orphan_tp_c)) > 0
print(f"  → {'FAIL' if ri_fail else 'PASS'}: 고아 참조 {'존재' if ri_fail else '없음'}")

# ─────────────────────────────────────────────
# 2. 승인 한도·권한
# ─────────────────────────────────────────────
print("\n" + "=" * 60)
print("2. 승인 한도 / can_approve_je")
print("=" * 60)

emp_approval = emp_df[["user_id", "approval_limit", "can_approve_je"]].copy()
emp_approval["approval_limit"] = pd.to_numeric(emp_approval["approval_limit"], errors="coerce")

doc_with_approver = doc_df[doc_df["approved_by"].notna()].copy()
doc_merged = doc_with_approver.merge(
    emp_approval.rename(
        columns={
            "user_id": "approved_by",
            "approval_limit": "approver_limit",
            "can_approve_je": "approver_can_je",
        }
    ),
    on="approved_by",
    how="left",
)

# 승인한도 초과 (정상 문서 기준)
over_limit = doc_merged[
    doc_merged["approver_limit"].notna() & (doc_merged["doc_amount"] > doc_merged["approver_limit"])
]
pct_over = len(over_limit) / len(doc_merged) * 100 if len(doc_merged) > 0 else 0
print(f"  승인 있는 정상 문서: {len(doc_merged):,}건")
print(f"  승인한도 초과 문서: {len(over_limit):,}건 ({pct_over:.1f}%)")
if len(over_limit) > 0:
    print(
        f"    초과 금액 분포: min={over_limit['doc_amount'].min():,.0f}  max={over_limit['doc_amount'].max():,.0f}  median={over_limit['doc_amount'].median():,.0f}"
    )

# can_approve_je=False인 직원이 승인한 건수
no_je_approve = doc_merged[doc_merged["approver_can_je"] == False]
pct_no_je = len(no_je_approve) / len(doc_merged) * 100 if len(doc_merged) > 0 else 0
print(f"  can_approve_je=False 직원 승인: {len(no_je_approve):,}건 ({pct_no_je:.1f}%)")
if len(no_je_approve) > 0:
    sample_approvers = no_je_approve["approved_by"].value_counts().head(3).to_dict()
    print(f"    주요 승인자: {sample_approvers}")

lim_fail = len(over_limit) > 0
nje_fail = len(no_je_approve) > 0
print(
    f"  → 승인한도 초과: {'FAIL' if lim_fail else 'PASS'} | can_approve_je 위반: {'FAIL' if nje_fail else 'PASS'}"
)

# ─────────────────────────────────────────────
# 3. SoD — 자기승인 정합
# ─────────────────────────────────────────────
print("\n" + "=" * 60)
print("3. SoD — 자기승인 정합")
print("=" * 60)

self_approve_docs = doc_df[
    doc_df["approved_by"].notna() & (doc_df["created_by"] == doc_df["approved_by"])
]
pct_sa = len(self_approve_docs) / total_docs * 100 if total_docs > 0 else 0
print(f"  자기승인 문서(created_by==approved_by): {len(self_approve_docs):,}건 ({pct_sa:.1f}%)")

# sod_violation 플래그 검토 — 행 단위
self_rows = df[df["approved_by"].notna() & (df["created_by"] == df["approved_by"])]
flag_false = self_rows[self_rows["sod_violation"] == False]
flag_true = self_rows[self_rows["sod_violation"] == True]
print(
    f"  자기승인 행 {len(self_rows):,}건 중 sod_violation=True: {len(flag_true):,}  False: {len(flag_false):,}"
)

# 반대: sod_violation=True인데 자기승인 아닌 경우
sod_true_rows = df[df["sod_violation"] == True]
not_self_but_sod = sod_true_rows[sod_true_rows["created_by"] != sod_true_rows["approved_by"]]
print(
    f"  sod_violation=True 전체 행: {len(sod_true_rows):,}  (자기승인 아닌 경우: {len(not_self_but_sod):,})"
)
if len(not_self_but_sod) > 0:
    print(
        f"    sod_conflict_type 분포: {not_self_but_sod['sod_conflict_type'].value_counts().head(5).to_dict()}"
    )

sod_mismatch = len(flag_false)  # 자기승인인데 플래그 false
print(f"  → 자기승인+sod_violation=False(불일치): {sod_mismatch:,}건")
sod_fail = sod_mismatch > 0
print(f"  → {'FAIL' if sod_fail else 'PASS'}: SoD 플래그 정합")

# ─────────────────────────────────────────────
# 4. authorized_company_codes 밖 생성 건수
# ─────────────────────────────────────────────
print("\n" + "=" * 60)
print("4. 권한·회사 정합 (authorized_company_codes)")
print("=" * 60)

emp_auth = emp_df[["user_id", "authorized_company_codes"]].copy()
# authorized_company_codes가 리스트 형태 — 정규화
emp_auth = emp_auth.explode("authorized_company_codes").rename(
    columns={"user_id": "created_by", "authorized_company_codes": "auth_cc"}
)
auth_set = emp_auth.groupby("created_by")["auth_cc"].apply(set).reset_index()
auth_set.columns = ["created_by", "auth_codes"]

df_cc = (
    df[["document_id", "created_by", "company_code"]]
    .drop_duplicates(subset=["document_id", "created_by", "company_code"])
    .merge(auth_set, on="created_by", how="left")
)


def is_unauthorized(row):
    if pd.isna(row["company_code"]):
        return False
    if not isinstance(row["auth_codes"], set):
        return True  # 마스터 없음 → 고아
    return row["company_code"] not in row["auth_codes"]


df_cc["unauthorized"] = df_cc.apply(is_unauthorized, axis=1)
unauth_rows = df_cc[df_cc["unauthorized"]]
pct_unauth = len(unauth_rows) / len(df_cc) * 100 if len(df_cc) > 0 else 0
print(f"  검사 행(문서×생성자): {len(df_cc):,}건")
print(f"  권한 외 회사 문서: {len(unauth_rows):,}건 ({pct_unauth:.1f}%)")
if len(unauth_rows) > 0:
    top_cc = unauth_rows["company_code"].value_counts().head(3).to_dict()
    print(f"    회사코드별 분포: {top_cc}")

auth_fail = len(unauth_rows) > 0
print(f"  → {'FAIL' if auth_fail else 'PASS'}: 회사 권한 정합")

# ─────────────────────────────────────────────
# 5. cost_center 형식·존재성 정합
# ─────────────────────────────────────────────
print("\n" + "=" * 60)
print("5. cost_center 정합")
print("=" * 60)

# 직원 마스터에서 authorized_cost_centers 수집
emp_cc_set = set()
for e in employees:
    for cc in e.get("authorized_cost_centers") or []:
        emp_cc_set.add(cc)
# 직원 본인 cost_center도 포함
for e in employees:
    if e.get("cost_center"):
        emp_cc_set.add(e["cost_center"])

journal_cc_vals = df["cost_center"].dropna().unique()
# 형식 검사: CC-XXXX-YYYY 패턴
import re

cc_pattern = re.compile(r"^CC-[A-Z0-9]+-[A-Z]+$")
invalid_format = [cc for cc in journal_cc_vals if not cc_pattern.match(str(cc))]
not_in_master = [cc for cc in journal_cc_vals if cc not in emp_cc_set]
invalid_rows = df[df["cost_center"].isin(invalid_format)]
not_in_master_rows = df[df["cost_center"].isin(not_in_master)]

print(f"  마스터 cost_center 집합 크기: {len(emp_cc_set)}")
print(f"  저널 고유 cost_center 수: {len(journal_cc_vals)}")
print(f"  형식 불일치(CC-XXX-XXX 패턴 외): {len(invalid_format)}개  |  행: {len(invalid_rows):,}건")
print(f"  마스터 미등록 cost_center: {len(not_in_master)}개  |  행: {len(not_in_master_rows):,}건")
if not_in_master[:5]:
    print(f"    샘플: {not_in_master[:5]}")

cc_fail = len(not_in_master) > 0 or len(invalid_format) > 0
print(f"  → {'FAIL' if cc_fail else 'PASS'}: cost_center 정합")

# ─────────────────────────────────────────────
# 6. 퇴사자 활동 (termination_date 이후 분개)
# ─────────────────────────────────────────────
print("\n" + "=" * 60)
print("6. 퇴사자 활동 (termination_date 이후 분개)")
print("=" * 60)

terminated = emp_df[emp_df["termination_date"].notna()][["user_id", "termination_date"]].copy()
terminated["termination_date"] = pd.to_datetime(terminated["termination_date"])
print(f"  퇴사자 수: {len(terminated)}명")

if len(terminated) > 0:
    df_post = (
        df[["document_id", "created_by", "posting_date"]]
        .drop_duplicates(subset=["document_id", "created_by"])
        .copy()
    )
    df_post["posting_date"] = pd.to_datetime(df_post["posting_date"], errors="coerce")
    df_post = df_post.merge(
        terminated.rename(columns={"user_id": "created_by"}), on="created_by", how="inner"
    )
    post_term = df_post[df_post["posting_date"] > df_post["termination_date"]]
    pct_term = len(post_term) / total_docs * 100 if total_docs > 0 else 0
    print(f"  퇴사자 생성 문서(정상 데이터): {len(post_term):,}건 ({pct_term:.2f}%)")
    if len(post_term) > 0:
        print(f"    관련 직원: {post_term['created_by'].nunique()}명")
else:
    post_term = pd.DataFrame()
    print("  퇴사자 없음 — 측정 불가")

term_fail = len(post_term) > 0
print(f"  → {'FAIL' if term_fail else 'PASS'}: 퇴사자 활동")

# ─────────────────────────────────────────────
# 종합 요약
# ─────────────────────────────────────────────
print("\n" + "=" * 60)
print("종합 요약")
print("=" * 60)
results = [
    (
        "1. 참조 무결성",
        "FAIL" if ri_fail else "PASS",
        f"고아 created_by {len(orphan_created)}, approved_by {len(orphan_approved)}, TP {len(orphan_tp_v) + len(orphan_tp_c)}",
    ),
    (
        "2a. 승인 한도 초과",
        "FAIL" if lim_fail else "PASS",
        f"정상 문서 중 한도 초과 {len(over_limit):,}건 ({pct_over:.1f}%)",
    ),
    (
        "2b. can_approve_je 위반",
        "FAIL" if nje_fail else "PASS",
        f"권한 없는 승인자 {len(no_je_approve):,}건 ({pct_no_je:.1f}%)",
    ),
    (
        "3. SoD 플래그 정합",
        "FAIL" if sod_fail else "PASS",
        f"자기승인 {len(self_approve_docs):,}건, 불일치(플래그 누락) {sod_mismatch:,}건",
    ),
    (
        "4. 회사 권한 정합",
        "FAIL" if auth_fail else "PASS",
        f"권한 외 회사 문서 {len(unauth_rows):,}건 ({pct_unauth:.1f}%)",
    ),
    (
        "5. cost_center 정합",
        "FAIL" if cc_fail else "PASS",
        f"마스터 미등록 {len(not_in_master)}개 CC, 형식 불일치 {len(invalid_format)}개",
    ),
    ("6. 퇴사자 활동", "FAIL" if term_fail else "PASS", f"퇴사 후 문서 {len(post_term):,}건"),
]

for name, status, detail in results:
    marker = "✓" if status == "PASS" else "✗"
    print(f"  {marker} [{status}] {name}: {detail}")

# 3분류 판정
print("\n[3분류]")
print("  코드버그: 없음 (모든 항목 정상 측정됨)")
print("  Graceful Degradation(정상 설계): trading_partner 기타 유형·cost_center 마스터 미등록은")
print("    데이터셋 설계 범위 이슈일 수 있음 — 아래 상세 참조")
print("  데이터 특성: 승인한도 초과·자기승인 비율이 ML 피처 신뢰도에 직접 영향")

# PHASE2 판정
print("\n[PHASE2 ML 학습 적합성]")
blockers = []
if lim_fail and pct_over > 20:
    blockers.append(f"정상 문서 승인한도 초과 {pct_over:.1f}% → 통제 피처 노이즈 과다")
if nje_fail and pct_no_je > 5:
    blockers.append(f"can_approve_je 위반 {pct_no_je:.1f}% → 승인 권한 피처 신뢰 불가")
if sod_mismatch > 0:
    blockers.append(f"SoD 플래그 불일치 {sod_mismatch:,}건 → sod_violation 피처 직접 사용 불가")
if auth_fail and pct_unauth > 5:
    blockers.append(f"회사 권한 위반 {pct_unauth:.1f}% → authorized_company 피처 노이즈")

if blockers:
    print("  BLOCK 요인:")
    for b in blockers:
        print(f"    - {b}")
    print("  → PHASE2 ML 학습에 걸림 있음: 위 항목 수정 또는 피처 설계 시 플래그 제외 필요")
else:
    print("  → PHASE2 ML 학습에 걸림 없음: 피처 신뢰도 정상 범위")

sys.exit(1 if any(status == "FAIL" for _, status, _ in results) else 0)
