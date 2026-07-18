"""PHASE2 fraud 데이터셋 shortcut 제거 통합 게이트.

사용: uv run python tools/scripts/phase2_shortcut_gate.py <fraud_dataset_dir>
exit 0 = ALL PASS (다 수정됨), exit 1 = FAIL 1개 이상.

철학: "단일 비-회계 피처로 부정을 (정밀 식별) 또는 (비정상 농도로 집중) 하면 shortcut".
  precision = P(부정|값)  / recall = P(값|부정)  / lift = precision/base_rate
부정이 희소(0.1%)해 lift 단독은 비현실 → precision 또는 (recall AND lift) 로 판정.
회계 내용(분개 방향·균형·전수)은 회귀 게이트로 보존. 임계 완화는 사용자 승인(꼼수 통과 금지).
"""

import sys

import duckdb

# ===== 임계 =====
TH_MISSING_DIFF = 0.08  # S1: 메타 결측률 |정상-부정| 차 상한 (8%p)
TH_PRECISION = 0.25  # S2: 단일값 fraud precision 상한 (정밀 식별자)
TH_PREC_SCHEME = 0.60  # S2: scheme-결정 컬럼 완화 precision
TH_RECALL = 0.25  # S2: 단일값이 포함하는 부정 비율 상한 (집중)
TH_LIFT = 5.0  # S2: recall 높을 때 추가조건 — lift 이상이면 집중 shortcut
TH_TWIN_MIN = 300  # S4: 확장계정 정상 사용 최소 문서수 (정상 쌍둥이)
MIN_SUPPORT = 5  # S2 판정 최소 부정 표본
# 주: S7(라인수 분포) 게이트 폐기 — 라인수의 fraud precision≈base(분리력 0)로 shortcut 아님이
#     실측됨(2라인 0.131%/3라인 0.144% vs base 0.101%). 부정 단순분개(2라인)는 회계적으로 자연.
SCHEME_DETERMINED = {"business_process", "document_type"}
# s10 정합(2026-07-18): 신규 계정 도입 폐기로 확장계정 쌍둥이 검사 대상 없음.
# 계정 지름길은 S2(단일피처 precision)가 감시.
EXT_ACCOUNTS = []
META_COLS = [
    "user_persona",
    "auxiliary_account_label",
    "cost_center",
    "line_text",
    "header_text",
    "reference",
    "counterparty_type",
    "supporting_doc_type",
]
S2_COLS = [
    "created_by",
    "approved_by",
    "cost_center",
    "profit_center",
    "currency",
    "document_type",
    "source",
    "business_process",
    "batch_type",
    "sod_violation",
    "has_attachment",
    "tax_treatment",
    "counterparty_type",
    "ledger",
    "company_code",
    "fiscal_period",
    "is_intercompany",
    "supporting_doc_type",
    "user_persona",
    "auxiliary_account_label",
    "gl_account",
    "event_type",
    "exchange_rate",
    "ip_address",
    "semantic_scenario_id",
    "scenario_id",
    "line_text_family",
    "tax_code",
    "is_synthetic",
    "is_mutated",
    "line_number",
]
# 기말조작 scheme — 카탈로그 (c)상 월말(28일+) 분개가 실재해야 함 (S10)
PERIOD_END_SCHEMES = ["FS02", "FS06", "FS07", "FS09"]

if len(sys.argv) < 2:
    print("usage: phase2_shortcut_gate.py <fraud_dataset_dir> [reference_dataset_dir]")
    sys.exit(2)
OUT = sys.argv[1].rstrip("/\\")
REF = sys.argv[2].rstrip("/\\") if len(sys.argv) > 2 else None  # S13 규모 보존 비교 기준
TH_SCALE_LO, TH_SCALE_HI = 0.5, 2.0  # S13: scheme 누적규모 ref 대비 허용 배수

con = duckdb.connect()
con.execute(
    f"""
    CREATE VIEW j AS SELECT * FROM read_csv('{OUT}/journal_entries.csv', all_varchar=true);
    CREATE VIEW p AS SELECT * FROM read_csv('{OUT}/labels/phase2_scheme_provenance.csv', all_varchar=true);
    """
)
if REF:
    con.execute(
        f"""
        CREATE VIEW jr AS SELECT * FROM read_csv('{REF}/journal_entries.csv', all_varchar=true);
        CREATE VIEW pr AS SELECT * FROM read_csv('{REF}/labels/phase2_scheme_provenance.csv', all_varchar=true);
        """
    )


def q(sql):
    return con.execute(sql).fetchall()


TOTAL = q("SELECT count(DISTINCT document_id) FROM j")[0][0]
FRAUD = q("SELECT count(DISTINCT document_id) FROM j WHERE is_fraud='true'")[0][0]
BASE = FRAUD / TOTAL
results = []


def gate(name, ok, detail):
    results.append((name, ok, detail))


# ---------- 회귀 (회계 내용 보존) ----------
gate("R-COV 14scheme전수", q("SELECT count(DISTINCT scheme_id) FROM p")[0][0] == 14, "")
selfc = q("""WITH l AS (SELECT j.document_id, j.gl_account, sum(CAST(j.debit_amount AS DOUBLE)) dr, sum(CAST(j.credit_amount AS DOUBLE)) cr
    FROM p JOIN j USING(document_id) GROUP BY 1,2) SELECT count(DISTINCT document_id) FROM l WHERE dr>0 AND cr>0""")[
    0
][0]
gate("R-SELF 자기상쇄0", selfc == 0, f"{selfc}")
unbal = q(
    "SELECT count(*) FROM (SELECT document_id FROM j WHERE is_fraud='true' GROUP BY 1 HAVING abs(sum(CAST(debit_amount AS DOUBLE))-sum(CAST(credit_amount AS DOUBLE)))>0.01)"
)[0][0]
gate("R-BAL 부정균형", unbal == 0, f"{unbal}")
anti = q("""WITH dr AS (SELECT document_id, semantic_account_subtype st FROM j WHERE CAST(debit_amount AS DOUBLE)>0),
     cr AS (SELECT document_id, semantic_account_subtype st FROM j WHERE CAST(credit_amount AS DOUBLE)>0)
   SELECT count(DISTINCT dr.document_id) FROM dr JOIN cr USING(document_id)
   WHERE (dr.st LIKE '%expense%' AND cr.st LIKE '%REVENUE%') OR (dr.st LIKE '%REVENUE%' AND cr.st LIKE '%expense%')""")[
    0
][0]
gate("R-DIR 방향안티패턴0", anti == 0, f"{anti}")

# ---------- S1 메타 결측률 차 ----------
s1 = []
for col in META_COLS:
    rt = {}
    for lab, cond in [("n", "is_fraud='false'"), ("f", "is_fraud='true'")]:
        r = q(
            f'SELECT count(*) FILTER (WHERE "{col}" IS NULL OR "{col}"=\'\'), count(*) FROM j WHERE {cond}'
        )
        rt[lab] = r[0][0] / max(r[0][1], 1)
    if abs(rt["n"] - rt["f"]) > TH_MISSING_DIFF:
        s1.append(f"{col}(정상{rt['n'] * 100:.0f}/부정{rt['f'] * 100:.0f})")
gate("S1 메타결측률차", not s1, "; ".join(s1))

# ---------- S2 단일피처 precision/recall (모든 범주형 + 계정 + null) ----------
s2 = []


def judge(col, label, fd, tot):
    if fd < MIN_SUPPORT:
        return
    prec = fd / tot
    recall = fd / FRAUD
    lift = prec / BASE
    tp = TH_PREC_SCHEME if col in SCHEME_DETERMINED else TH_PRECISION
    if prec >= tp:
        s2.append(f"{label}[prec{prec * 100:.0f}% {fd}/{tot}]")
    elif recall >= TH_RECALL and lift >= TH_LIFT:
        s2.append(f"{label}[recall{recall * 100:.0f}% lift{lift:.0f}x {fd}/{tot}]")


for col in S2_COLS:
    for (
        v,
        fd,
        tot,
    ) in q(f"""WITH dv AS (SELECT DISTINCT document_id, is_fraud, "{col}" v FROM j WHERE "{col}" IS NOT NULL AND "{col}"<>'')
            SELECT v, count(*) FILTER (WHERE is_fraud='true') fd, count(*) tot FROM dv GROUP BY v
            HAVING count(*) FILTER (WHERE is_fraud='true')>={MIN_SUPPORT}"""):
        judge(col, f"{col}='{str(v)[:16]}'", fd, tot)
    rn = q(f"""WITH dv AS (SELECT DISTINCT document_id, is_fraud, ("{col}" IS NULL OR "{col}"='') blank FROM j)
        SELECT count(*) FILTER (WHERE is_fraud='true' AND blank), count(*) FILTER (WHERE blank) FROM dv""")
    if rn[0][1]:
        judge(col, f"{col} IS NULL", rn[0][0], rn[0][1])
gate("S2 단일피처분리", not s2, "; ".join(s2[:10]))

# ---------- S4 확장계정 정상 쌍둥이 ----------
s4 = []
for a in EXT_ACCOUNTS:
    n = q(f"SELECT count(DISTINCT document_id) FROM j WHERE gl_account='{a}' AND is_fraud='false'")[
        0
    ][0]
    if n < TH_TWIN_MIN:
        s4.append(f"{a}({n})")
gate("S4 확장계정정상쌍둥이", not s4, "; ".join(s4))

# ---------- S8 scheme-계정 정합성 (카탈로그 (b)(c)(d) 정당 sub_type 화이트리스트) ----------
# 부정의 회계 메커니즘이 scheme별 정당 계정으로만 구성돼야 함. 라인추가용 무관계정 침입 = "억지 부정".
# s10 정합(2026-07-18): base 세대교체(4자리 39계정, 부정 전용 계정 폐기)에 맞춰
# scheme별 정당 subtype 화이트리스트를 s10 계정 매핑(base 실측 subtype) 기준으로 재산정.
# 게이트 기능(설계 외 무관계정 침입 차단)은 동일 — 임계 완화 아님.
SCHEME_ACCT = {
    "FS01": {"AR", "PRODUCT_REVENUE", "CASH", "SHORT_TERM_DEBT"},
    "FS02": {"AR", "SERVICE_REVENUE", "INVENTORY", "COGS_MATERIAL", "AP"},
    "FS03": {"SUSPENSE_RECEIVABLE", "CASH", "AR"},
    "FS04": {
        "SUSPENSE_RECEIVABLE",
        "CASH",
        "AR",
        "OPEX_PROFESSIONAL_FEES",
        "FIXED_ASSET",
    },
    "FS05": {"AR", "PRODUCT_REVENUE", "COGS_MATERIAL", "AP", "CASH"},
    "FS06": {"AP", "AR", "PRODUCT_REVENUE", "GRIR"},
    "FS07": {"INVENTORY", "COGS_MATERIAL", "GRIR", "RAW_MATERIALS"},
    "FS08": {
        "INTANGIBLE_ASSET",
        "OPEX_PROFESSIONAL_FEES",
        "FIXED_ASSET",
        "AP",
        "AMORTIZATION_EXPENSE",
    },
    "FS09": {"AR", "PRODUCT_REVENUE", "COGS_MATERIAL", "INVENTORY"},
    "FS10": {"CASH", "AR", "BAD_DEBT_EXPENSE"},
    "FS11": {"IC_RECEIVABLE", "IC_PAYABLE", "PRODUCT_REVENUE", "COGS_MATERIAL"},
    "FS12": {"OPEX_PROFESSIONAL_FEES", "CASH", "BAD_DEBT_EXPENSE", "ACCRUED_LIABILITIES"},
    "FS13": {"FIXED_ASSET", "CASH", "MISC_INCOME", "DEPRECIATION_EXPENSE"},
    "FS14": {"OPEX_PAYROLL", "CASH"},
}
s8 = []
for sc, allowed in SCHEME_ACCT.items():
    used = q(f"""SELECT DISTINCT j.semantic_account_subtype FROM p JOIN j USING(document_id)
        WHERE p.scheme_id='{sc}' AND j.semantic_account_subtype IS NOT NULL AND j.semantic_account_subtype<>''""")
    intruders = sorted({r[0] for r in used} - allowed)
    if intruders:
        s8.append(f"{sc}⟵{intruders}")
gate("S8 scheme계정정합", not s8, "; ".join(s8))

# ---------- S11 다컬럼 조합 분리 (정상에 없는 메타 조합 셀) ----------
# 부정 메타를 독립 샘플링하면 정상의 조건부 분포에 없는 조합이 생겨 조합 셀이 정밀 식별자가 됨.
COMBO_PAIRS = [
    ("source", "user_persona"),
    ("source", "document_type"),
    ("user_persona", "document_type"),
    ("company_code", "source"),
    ("counterparty_type", "document_type"),
    ("user_persona", "business_process"),
]
COMBO_TRIPLES = [
    ("source", "user_persona", "document_type"),
    ("company_code", "source", "document_type"),
    ("counterparty_type", "source", "document_type"),
]
TH_COMBO_PREC = 0.50  # 조합 셀 precision 상한
COMBO_MIN = 10  # 최소 부정 표본
s11 = []
for combo in COMBO_PAIRS + COMBO_TRIPLES:
    c = "||'|'||".join(f"COALESCE(\"{x}\",'∅')" for x in combo)
    for v, fd, tot in q(f"""WITH dv AS (SELECT DISTINCT document_id, is_fraud, {c} v FROM j)
            SELECT v, count(*) FILTER (WHERE is_fraud='true') fd, count(*) tot FROM dv GROUP BY v
            HAVING count(*) FILTER (WHERE is_fraud='true')>={COMBO_MIN}
               AND count(*) FILTER (WHERE is_fraud='true')*1.0/count(*)>={TH_COMBO_PREC}"""):
        s11.append(f"{'×'.join(combo)}='{str(v)[:40]}'[{fd}/{tot}]")
gate("S11 조합분리", not s11, "; ".join(s11[:8]))

# ---------- S12 소액 부정 실재 + 자릿수 셀 분리 없음 ----------
# 현실 부정엔 소액 구성요소가 실재(FS03 초기 소액 점증, FS04 소액 소각, FS14 월급여, 한도회피 쪼개기).
# floor: 1백만 미만 부정 라인 비율 >= 5% (존재 보장). 인위 자릿수 맞추기 금지 — scheme 메커니즘에서 자연 발생.
TH_SMALL_RATIO = 0.05
TH_SMALL_AMT = 1_000_000
s12 = []
sm = q(f"""SELECT count(*) FILTER (WHERE CAST(local_amount AS DOUBLE) < {TH_SMALL_AMT}), count(*)
    FROM j WHERE is_fraud='true' AND local_amount IS NOT NULL AND local_amount<>'' AND CAST(local_amount AS DOUBLE)>0""")
small_ratio = sm[0][0] / max(sm[0][1], 1)
if small_ratio < TH_SMALL_RATIO:
    s12.append(
        f"소액(<{TH_SMALL_AMT:,}) 부정 라인 {sm[0][0]}/{sm[0][1]}={small_ratio * 100:.1f}% (<{TH_SMALL_RATIO * 100:.0f}%)"
    )
# 자릿수 셀 단위 정밀 분리(precision>=25%) 없음
for r in q("""WITH amt AS (SELECT is_fraud, length(CAST(CAST(local_amount AS DOUBLE) AS BIGINT)::VARCHAR) ln
        FROM j WHERE local_amount IS NOT NULL AND local_amount<>'' AND CAST(local_amount AS DOUBLE)>=1)
    SELECT ln, count(*) FILTER (WHERE is_fraud='true') fd, count(*) tot FROM amt GROUP BY 1
    HAVING count(*) FILTER (WHERE is_fraud='true')>=5 AND count(*) FILTER (WHERE is_fraud='true')*1.0/count(*)>=0.25"""):
    s12.append(f"자릿수{r[0]}[prec {r[1]}/{r[2]}]")
gate("S12 소액부정실재", not s12, "; ".join(s12))

# ---------- S9 식별자 형식 (부정 document_id 가 정상과 같은 형식/길이) ----------
s9 = []
idlen = q("""WITH dv AS (SELECT DISTINCT document_id, is_fraud FROM j)
    SELECT is_fraud, list_sort(array_agg(DISTINCT length(document_id))) FROM dv GROUP BY 1""")
lend = {r[0]: set(r[1]) for r in idlen}
extra = lend.get("true", set()) - lend.get("false", set())
if extra:
    s9.append(
        f"부정전용 document_id 길이 {sorted(extra)} (정상 {sorted(lend.get('false', set()))})"
    )
# document_number/batch_id 부정전용 prefix
dn = q("""WITH f AS (SELECT DISTINCT substr(document_number,1,9) p FROM j WHERE is_fraud='true' AND document_number IS NOT NULL AND document_number<>''),
    n AS (SELECT DISTINCT substr(document_number,1,9) p FROM j WHERE is_fraud='false')
    SELECT count(*) FROM f WHERE p NOT IN (SELECT p FROM n)""")[0][0]
if dn:
    s9.append(f"부정전용 document_number prefix {dn}개")
gate("S9 식별자형식", not s9, "; ".join(s9))

# ---------- S10 기말조작 scheme 월말 실재 (카탈로그 (c) 회계정합) ----------
s10 = []
for sc in PERIOD_END_SCHEMES:
    r = q(f"""SELECT count(DISTINCT j.document_id) FILTER (WHERE day(CAST(substr(j.posting_date,1,10) AS DATE))>=28),
                 count(DISTINCT j.document_id)
          FROM p JOIN j USING(document_id) WHERE p.scheme_id='{sc}'""")
    if r[0][1] > 0 and r[0][0] == 0:
        s10.append(f"{sc}(월말 0/{r[0][1]})")
gate("S10 기말scheme월말실재", not s10, "; ".join(s10))

# ---------- S13 scheme 누적규모 보존 (reference 대비) ----------
# 소액 혼입이 scheme 전체 금액을 축소(누적 미보존)하면 안 됨. reference 제공 시만 검사.
if REF:
    s13 = []
    # 급여 등 현실 상한이 규모를 정하는 scheme 은 ref 보존 대상 아님(FS14 유령직원 = 정상 월급 × 건수).
    S13_EXCLUDE = {"FS14"}
    cur = {
        r[0]: r[1]
        for r in q("""SELECT p.scheme_id, sum(CAST(j.debit_amount AS DOUBLE))
        FROM p JOIN j USING(document_id) GROUP BY 1""")
    }
    ref = {
        r[0]: r[1]
        for r in q("""SELECT pr.scheme_id, sum(CAST(jr.debit_amount AS DOUBLE))
        FROM pr JOIN jr USING(document_id) GROUP BY 1""")
    }
    for sc in sorted(ref):
        if sc in S13_EXCLUDE:
            continue
        rv = ref[sc] or 0
        cv = cur.get(sc, 0) or 0
        if rv > 0:
            ratio = cv / rv
            if not (TH_SCALE_LO <= ratio <= TH_SCALE_HI):
                s13.append(f"{sc}({ratio:.2f}x cur{cv / 1e6:.0f}M/ref{rv / 1e6:.0f}M)")
    gate("S13 규모보존", not s13, "; ".join(s13))

# ---------- S14 구조신호 floor (utility — 부정 고유 구조가 분산으로 평탄화되지 않게) ----------
# shortcut 제거(분산)가 진짜 탐지신호까지 지우면 안 됨. scheme별 핵심 구조신호 존재 강제.
s14 = []
# FS01 가공매출: 같은 고객 반복(모뉴엘형). 한 고객 최소 3건 이상.
fs01_rep = q("""SELECT max(c) FROM (SELECT j.trading_partner, count(DISTINCT j.document_id) c
    FROM p JOIN j USING(document_id) WHERE p.scheme_id='FS01' AND j.trading_partner IS NOT NULL AND j.trading_partner<>'' GROUP BY 1)""")
fs01_max = fs01_rep[0][0] if fs01_rep and fs01_rep[0][0] else 0
if fs01_max < 3:
    s14.append(f"FS01 고객반복 최대{fs01_max}건(<3)")
# FS05 순환거래: s10 정합(2026-07-18) — base 가 단일 법인(C001)이므로 원환은 company_code 가 아니라
# 관계사 trading_partner(C002/C003) 순환으로 실재해야 함. 관계사 상대 수 >= 2.
fs05_rp = q("""SELECT count(DISTINCT j.trading_partner) FROM p JOIN j USING(document_id)
    WHERE p.scheme_id='FS05' AND j.trading_partner IN ('C002','C003')""")[0][0]
if fs05_rp < 2:
    s14.append(f"FS05 관계사상대 {fs05_rp}(<2, 원환부재)")
# FS01 가공매출 상대는 외부 고객이어야(카탈로그 (d) 가공 고객 = customers 정상형식 외부처).
# 내부부서(DEPT-*)·계열사 코드(자사 company_code)가 fictitious_sale 상대면 회계 비현실.
fs01_internal = q("""SELECT count(DISTINCT j.document_id) FROM p JOIN j USING(document_id)
    WHERE p.scheme_id='FS01' AND p.component_role='fictitious_sale'
      AND (j.trading_partner LIKE 'DEPT-%'
           OR j.trading_partner IN (SELECT DISTINCT company_code FROM j))""")[0][0]
if fs01_internal > 0:
    s14.append(f"FS01 가공매출 상대 내부/계열 {fs01_internal}건(외부고객이어야)")
# FS03 횡령 점증 시계열(카탈로그 (d) 초기 소액 → 점증): 인출 후반 1/3 평균 > 전반 1/3 평균.
fs03_esc = q("""WITH w AS (SELECT CAST(j.local_amount AS DOUBLE) amt,
        row_number() OVER (ORDER BY j.posting_date) rn, count(*) OVER () n
    FROM p JOIN (SELECT DISTINCT document_id, posting_date, local_amount FROM j) j USING(document_id)
    WHERE p.scheme_id='FS03' AND p.component_role='cash_withdrawal')
    SELECT avg(amt) FILTER (WHERE rn <= n/3), avg(amt) FILTER (WHERE rn > n - n/3) FROM w""")
if fs03_esc and fs03_esc[0][0] and fs03_esc[0][1] and fs03_esc[0][1] <= fs03_esc[0][0]:
    s14.append(f"FS03 점증위반(전반평균 {fs03_esc[0][0]:,.0f} >= 후반평균 {fs03_esc[0][1]:,.0f})")
gate("S14 구조신호floor", not s14, "; ".join(s14))

# ---------- S15 라벨 인터페이스 완전성 ----------
# fraud/anomaly 행의 anomaly_type 이 비어 있으면 multi-class/stratum 평가에서 라벨 표면이 사라진다.
s15 = []
fraud_docs = q("SELECT count(DISTINCT document_id) FROM j WHERE is_fraud='true'")[0][0]
anomaly_docs = q("SELECT count(DISTINCT document_id) FROM j WHERE is_anomaly='true'")[0][0]
missing_anomaly_type = q("""SELECT count(DISTINCT document_id) FROM j
    WHERE is_anomaly='true' AND (anomaly_type IS NULL OR anomaly_type='')""")[0][0]
if fraud_docs == 0:
    s15.append("fraud_docs=0")
if anomaly_docs == 0:
    s15.append("anomaly_docs=0")
if missing_anomaly_type > 0:
    s15.append(f"anomaly_type missing {missing_anomaly_type} docs")
gate("S15 라벨인터페이스", not s15, "; ".join(s15))

# ---------- S16 sub_type 라벨 누출 (정상/부정 어휘 동기화) ----------
# 같은 gl_account인데 정상과 부정이 다른 semantic_account_subtype 라벨을 찍으면(예: 정상 intangible_assets
# vs 부정 intangible_development_cost) sub_type 이 부정 식별자가 됨. PHASE2 피처로 들어가므로 치명.
s16 = []
for col in ["semantic_account_subtype", "debit_account_subtype", "credit_account_subtype"]:
    rows = q(f"""SELECT "{col}", count(*) FILTER (WHERE is_fraud='true') fd
        FROM j WHERE "{col}" IS NOT NULL AND "{col}"<>''
        GROUP BY 1 HAVING count(*) FILTER (WHERE is_fraud='true')>0
           AND count(*) FILTER (WHERE is_fraud='false')=0""")
    for v, fd in rows:
        s16.append(f"{col}='{v}'({fd}부정전용)")
gate("S16 subtype라벨누출", not s16, "; ".join(s16[:8]))

# ---------- S17 부정전용 gl_account (세부계정 누출) ----------
# 부정이 쓰는 계정은 정상도 써야 함(세부코드 분산 시 정상이 안 쓰는 계정 고르면 누출).
s17 = q("""SELECT count(*) FROM (
    SELECT DISTINCT gl_account FROM j WHERE is_fraud='true'
    EXCEPT SELECT DISTINCT gl_account FROM j WHERE is_fraud='false')""")[0][0]
gate("S17 부정전용계정", s17 == 0, f"{s17}개" if s17 else "")

# ---------- 출력 ----------
print(
    f"=== PHASE2 shortcut gate : {OUT.split('/')[-1]} ==="
    + (f"  (ref={REF.split('/')[-1]})" if REF else "  (S13 skip: no ref)")
)
print(f"모집단 {TOTAL} / 부정 {FRAUD} / base {BASE * 100:.4f}%\n")
nfail = sum(1 for _, ok, _ in results if not ok)
for name, ok, detail in results:
    print(f"[{'OK ' if ok else 'XXX'}] {name}: {'PASS' if ok else 'FAIL  ' + detail}")
print(f"\n총 {len(results)}게이트 / FAIL {nfail}")
print("RESULT:", "ALL PASS — 다 수정됨" if nfail == 0 else f"FAIL {nfail}개 — 수정 계속")
sys.exit(0 if nfail == 0 else 1)
