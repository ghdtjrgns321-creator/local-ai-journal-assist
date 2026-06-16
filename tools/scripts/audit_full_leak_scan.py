"""PHASE2 fraud 데이터셋 전 컬럼 전수 누출 스캔 (화이트리스트 없음).

사용: uv run python tools/scripts/audit_full_leak_scan.py <fraud_dataset_dir>

목적: 게이트(phase2_shortcut_gate.py)는 "내가 의심한 컬럼(S2_COLS 등)"만 본다.
  전 컬럼을 화이트리스트 없이 전수 스캔해 게이트가 못 본 미지의 누출 차원을 찾는다.
  부정(is_fraud='true')을 "구조가 아닌 표시(라벨·식별자·지문)"로 들키게 하는 신호를 색출.

판정 (라인 단위, is_fraud 행 기준):
  precision = P(부정행|값)  / 부정전용 = 정상행 0 & 부정행 ≥ MIN_FRAUD
  결측률차 = |정상 결측률 − 부정 결측률|

라벨/정답 컬럼(LABEL_COLS)은 부정전용이 당연하므로 스캔 제외.
이미 게이트가 잡는 것(S16 sub_type, S17 gl_account)은 [known] 표기, 그 외 [NEW] 강조.
"""

import sys

import duckdb

# ── 임계 ──
MIN_FRAUD = 5  # 값별 최소 부정 행수 (free-text noise 컷)
TH_PRECISION = 0.25  # 정밀 식별자 상한
TH_MISSING_DIFF = 0.05  # 결측률차 상한 (5%p)
NUM_MIN_FRAUD = 3  # 수치형 부정전용 반복값 최소 부정 행수
TOP_N = 12  # 컬럼별 최대 출력 값 수

# 라벨/정답 컬럼 — 부정전용이 의도된 정답이므로 누출 판정 대상 아님
LABEL_COLS = {
    "is_fraud",
    "fraud_type",
    "is_anomaly",
    "anomaly_type",
    "detection_surface_hints",
    "mutation_base_event_type",
    "mutation_type",
    "mutation_mutated_field",
    "mutation_original_value",
    "mutation_mutated_value",
    "mutation_reason",
    "is_mutated",  # mutation 라벨 (NULL마커는 게이트 deny-list 처리됨)
}
# 고유 식별자 — 값별 카디널리티≈행수라 부정전용이 자명. NULL규칙·결측률만 본다(값별 스킵).
ID_COLS = {
    "document_id",
    "document_number",
    "original_document_id",
    "reversal_document_id",
    "batch_id",
    "job_id",
    "reference",
}
# 수치형 컬럼 — 부정전용 반복값/금액 지문 스캔
NUM_COLS = {
    "exchange_rate",
    "invoice_amount",
    "supply_amount",
    "debit_amount",
    "credit_amount",
    "local_amount",
    "tax_amount",
    "line_number",
    "fiscal_period",
}
# 이미 게이트가 잡는 누출 — [known] 표기
KNOWN_SUBTYPE = {"semantic_account_subtype", "debit_account_subtype", "credit_account_subtype"}
KNOWN_GL = {"gl_account"}

if len(sys.argv) < 2:
    print("usage: audit_full_leak_scan.py <fraud_dataset_dir>")
    sys.exit(2)
OUT = sys.argv[1].rstrip("/\\")

con = duckdb.connect()
con.execute(
    f"CREATE VIEW j AS SELECT * FROM read_csv('{OUT}/journal_entries.csv', all_varchar=true);"
)


def q(sql):
    return con.execute(sql).fetchall()


COLS = [r[1] for r in q("PRAGMA table_info('j')")]
N = q("SELECT count(*) FROM j")[0][0]
FN = q("SELECT count(*) FROM j WHERE is_fraud='true'")[0][0]
BASE = FN / N
print(f"# 전 컬럼 전수 누출 스캔: {OUT.split('/')[-1]}")
print(f"#   라인 {N:,} / 부정 {FN:,} (base {BASE * 100:.3f}%) / 컬럼 {len(COLS)}")
print(
    "#   판정: 부정전용=정상0&부정≥%d, precision≥%.0f%%, 결측률차>%.0f%%p\n"
    % (MIN_FRAUD, TH_PRECISION * 100, TH_MISSING_DIFF * 100)
)

new_leaks = []  # (col, kind, detail)
known_hits = 0  # 기지(S16/S17) 누출 실제 검출 수 — 요약 문구 정확화용


def tag(col):
    if col in KNOWN_SUBTYPE:
        return "known(S16)"
    if col in KNOWN_GL:
        return "known(S17)"
    return "NEW"


# ── 1. 범주형 값별: 부정전용 / 고precision ──
print("=" * 70)
print("[1] 범주형 값별 누출 (부정전용·고precision)")
print("=" * 70)
for col in COLS:
    if col in LABEL_COLS or col in ID_COLS or col in NUM_COLS:
        continue
    rows = q(
        f'''SELECT "{col}" v,
              count(*) FILTER (WHERE is_fraud='true') fd,
              count(*) FILTER (WHERE is_fraud='false') nd
            FROM j WHERE "{col}" IS NOT NULL AND "{col}"<>''
            GROUP BY 1
            HAVING count(*) FILTER (WHERE is_fraud='true') >= {MIN_FRAUD}
               AND ( count(*) FILTER (WHERE is_fraud='false')=0
                  OR count(*) FILTER (WHERE is_fraud='true')::DOUBLE
                     /(count(*) FILTER (WHERE is_fraud='true')+count(*) FILTER (WHERE is_fraud='false')) >= {TH_PRECISION} )
            ORDER BY fd DESC'''
    )
    if not rows:
        continue
    t = tag(col)
    if t.startswith("known"):
        known_hits += 1
    only = [(v, fd) for v, fd, nd in rows if nd == 0]
    hiprec = [(v, fd, nd) for v, fd, nd in rows if nd > 0]
    msgs = []
    for v, fd in only[:TOP_N]:
        msgs.append(f"'{v}'={fd}부정전용")
    for v, fd, nd in hiprec[:TOP_N]:
        msgs.append(f"'{v}'={fd}/{fd + nd}({fd / (fd + nd) * 100:.0f}%)")
    print(
        f"  [{t}] {col}: "
        + "; ".join(msgs[:TOP_N])
        + (f"  (+{len(rows) - TOP_N})" if len(rows) > TOP_N else "")
    )
    if t == "NEW":
        new_leaks.append((col, "범주형부정전용/고prec", "; ".join(msgs[:6])))

# ── 2. NULL 규칙: 결측(또는 채움)이 부정 식별자인가 ──
# 판정: 결측률차 단독 금지(노이즈). NULL 또는 NOT-NULL 어느 방향이든
#   precision≥25% OR (recall≥25% AND lift≥5) 일 때만 누출 (게이트 S2 철학과 동일).
TH_LIFT = 5.0
print("\n" + "=" * 70)
print("[2] NULL/채움 규칙 누출 (precision≥25% 또는 recall≥25%&lift≥5)")
print("=" * 70)
for col in COLS:
    if col in LABEL_COLS:
        continue
    r = q(
        f'''SELECT
            count(*) FILTER (WHERE ("{col}" IS NULL OR "{col}"='') AND is_fraud='true') fnull,
            count(*) FILTER (WHERE ("{col}" IS NULL OR "{col}"='') AND is_fraud='false') nnull,
            count(*) FILTER (WHERE is_fraud='true') ft,
            count(*) FILTER (WHERE is_fraud='false') nt
            FROM j'''
    )[0]
    fnull, nnull, ft, nt = r
    fnn, nnn = ft - fnull, nt - nnull  # not-null 측
    cand = []  # (방향, precision, recall, lift, 부정수, 전체수)
    for label, fd, td in [("결측이부정", fnull, fnull + nnull), ("채움이부정", fnn, fnn + nnn)]:
        if fd < MIN_FRAUD:
            continue
        p = fd / max(td, 1)
        rec = fd / max(ft, 1)
        lift = p / BASE if BASE else 0
        if p >= TH_PRECISION or (rec >= 0.25 and lift >= TH_LIFT):
            cand.append((label, p, rec, lift, fd, td))
    if not cand:
        continue
    t = tag(col)
    if t.startswith("known"):
        known_hits += 1
    kind, p, rec, lift, fd, td = max(cand, key=lambda c: c[3])  # lift 큰 방향
    print(
        f"  [{t}] {col} [{kind}]: precision {p * 100:.1f}% recall {rec * 100:.0f}% "
        f"lift {lift:.0f} (부정 {fd}/{td})"
    )
    if t == "NEW":
        new_leaks.append(
            (col, f"NULL규칙({kind})", f"prec{p * 100:.1f}% rec{rec * 100:.0f}% lift{lift:.0f}")
        )

# ── 3. 수치형 부정전용 반복값 / 금액 지문 ──
print("\n" + "=" * 70)
print("[3] 수치형 부정전용 반복값 (라운드/지문 금액)")
print("=" * 70)
for col in NUM_COLS:
    if col not in COLS:
        continue
    rows = q(
        f'''SELECT "{col}" v, count(*) FILTER (WHERE is_fraud='true') fd
            FROM j WHERE "{col}" IS NOT NULL AND "{col}"<>'' AND CAST("{col}" AS DOUBLE)<>0
            GROUP BY 1
            HAVING count(*) FILTER (WHERE is_fraud='true') >= {NUM_MIN_FRAUD}
               AND count(*) FILTER (WHERE is_fraud='false')=0
            ORDER BY fd DESC'''
    )
    if not rows:
        continue
    msgs = [f"{v}={fd}건" for v, fd in rows[:TOP_N]]
    print(
        f"  [NEW] {col}: "
        + "; ".join(msgs)
        + (f"  (+{len(rows) - TOP_N})" if len(rows) > TOP_N else "")
    )
    new_leaks.append((col, "수치부정전용값", "; ".join(msgs[:6])))

# ── 4. 시각 지문 (posting_date HH:MM, MM 단독) ──
print("\n" + "=" * 70)
print("[4] 시각 지문 (posting_date 시:분 / 분 집중)")
print("=" * 70)
has_time = q("SELECT count(*) FROM j WHERE posting_date LIKE '% %:%' OR posting_date LIKE '%T%:%'")[
    0
][0]
if has_time == 0:
    print("  posting_date 에 시:분 성분 없음 (날짜만) — 시각 지문 없음 [clean]")
else:
    for expr, label in [
        ("strftime(CAST(posting_date AS TIMESTAMP), '%H:%M')", "시:분"),
        ("strftime(CAST(posting_date AS TIMESTAMP), '%M')", "분단독"),
    ]:
        rows = q(
            f"""SELECT {expr} v,
                  count(*) FILTER (WHERE is_fraud='true') fd,
                  count(*) FILTER (WHERE is_fraud='false') nd
                FROM j GROUP BY 1
                HAVING count(*) FILTER (WHERE is_fraud='true') >= {MIN_FRAUD}
                   AND ( count(*) FILTER (WHERE is_fraud='false')=0
                      OR count(*) FILTER (WHERE is_fraud='true')::DOUBLE
                         /(count(*) FILTER (WHERE is_fraud='true')+count(*) FILTER (WHERE is_fraud='false')) >= {TH_PRECISION} )
                ORDER BY fd DESC"""
        )
        if rows:
            msgs = [f"{v}={fd}/{fd + nd}" for v, fd, nd in rows[:TOP_N]]
            print(f"  [NEW] posting_date {label}: " + "; ".join(msgs))
            new_leaks.append(("posting_date", f"시각지문({label})", "; ".join(msgs[:6])))
        else:
            print(f"  posting_date {label}: 집중 없음 [clean]")

# ── 5. 결측률 표 (전 컬럼 정상 vs 부정, 차 > 5%p) — [2]와 별개로 전체 조망 ──
print("\n" + "=" * 70)
print("[5] 전 컬럼 결측률 차 요약 (>5%p 만)")
print("=" * 70)
miss_tbl = []
for col in COLS:
    if col in LABEL_COLS:
        continue
    r = q(
        f'''SELECT
            count(*) FILTER (WHERE ("{col}" IS NULL OR "{col}"='') AND is_fraud='true')::DOUBLE/{FN},
            count(*) FILTER (WHERE ("{col}" IS NULL OR "{col}"='') AND is_fraud='false')::DOUBLE/{N - FN}
            FROM j'''
    )[0]
    if abs(r[0] - r[1]) > TH_MISSING_DIFF:
        miss_tbl.append((col, r[0], r[1], abs(r[0] - r[1])))
if miss_tbl:
    for col, fm, nm, d in sorted(miss_tbl, key=lambda x: -x[3]):
        print(f"  {col:32s} 부정 {fm * 100:5.1f}% / 정상 {nm * 100:5.1f}%  (차 {d * 100:.1f}%p)")
else:
    print("  >5%p 차 컬럼 없음 [clean]")

# ── 6. 2-컬럼 조합 (S11 밖 새 쌍 — 회계 의미쌍 위주) ──
print("\n" + "=" * 70)
print("[6] 2-컬럼 조합 누출 (부정전용 조합)")
print("=" * 70)
COMBO = [
    ("business_process", "tax_treatment"),
    ("document_type", "counterparty_type"),
    ("created_by", "source"),
    ("cost_center", "profit_center"),
    ("event_type", "supporting_doc_type"),
    ("tax_code", "tax_treatment"),
]
combo_found = False
for a, b in COMBO:
    if a not in COLS or b not in COLS:
        continue
    rows = q(
        f'''SELECT "{a}" va, "{b}" vb,
              count(*) FILTER (WHERE is_fraud='true') fd
            FROM j WHERE "{a}" IS NOT NULL AND "{b}" IS NOT NULL
            GROUP BY 1,2
            HAVING count(*) FILTER (WHERE is_fraud='true') >= {MIN_FRAUD}
               AND count(*) FILTER (WHERE is_fraud='false')=0
            ORDER BY fd DESC'''
    )
    if rows:
        combo_found = True
        msgs = [f"({va},{vb})={fd}" for va, vb, fd in rows[:6]]
        print(f"  [NEW] {a}×{b}: " + "; ".join(msgs))
        new_leaks.append((f"{a}×{b}", "조합부정전용", "; ".join(msgs[:4])))
if not combo_found:
    print("  부정전용 조합 없음 [clean]")

# ── 요약 ──
print("\n" + "=" * 70)
print(f"[요약] 신규(NEW) 누출 후보 {len(new_leaks)}건")
print("=" * 70)
if new_leaks:
    for col, kind, detail in new_leaks:
        print(f"  ✗ {col} [{kind}]: {detail}")
    print("\n→ r4m 프롬프트 L4~ 추가 + 게이트 S18~ 보강 대상")
elif known_hits:
    print(f"  신규 누출 없음. 기지(S16/S17) 누출 {known_hits}건 검출 — 게이트가 추적 중.")
else:
    print("  신규·기지 누출 모두 없음 — 전 컬럼 깨끗.")
sys.exit(1 if new_leaks else 0)
