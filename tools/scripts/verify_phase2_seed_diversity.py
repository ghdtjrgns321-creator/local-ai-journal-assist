"""시드 회전 다양성 게이트 — seed 데이터셋들의 부정 내용이 서로 실제로 다른지 검증.

사용: uv run python tools/scripts/verify_phase2_seed_diversity.py <dataset_dir1> <dataset_dir2> [...]
판정: 모든 쌍에서 부정 내용(scheme, role, 금액, 일자, 계정) 멀티셋 차이가 임계 이상이어야 PASS.
동일 복사본(차이 0)이나 표면만 바꾼 복제는 FAIL — "같은 문제지를 이름만 바꿔 N부"는 표본이 아님.
exit 0 = PASS, exit 1 = FAIL.
"""

import sys

import duckdb

TH_MIN_DIFF_RATIO = 0.5  # 쌍별 차이 행 / 부정 행 최소 비율 (금액·일자 수준에서 절반 이상 달라야)

if len(sys.argv) < 3:
    print("usage: verify_phase2_seed_diversity.py <dir1> <dir2> [...]")
    sys.exit(2)
DIRS = [d.rstrip("/\\") for d in sys.argv[1:]]

con = duckdb.connect()
for i, d in enumerate(DIRS):
    con.execute(f"""CREATE VIEW f{i} AS
        SELECT p.scheme_id, p.component_role, j.local_amount, j.posting_date, j.gl_account
        FROM read_csv('{d}/labels/phase2_scheme_provenance.csv', all_varchar=true) p
        JOIN read_csv('{d}/journal_entries.csv', all_varchar=true) j USING(document_id)""")

rows = con.execute("SELECT count(*) FROM f0").fetchall()[0][0]
fails = []
print(f"=== seed 다양성 검증: {len(DIRS)}개 데이터셋, 부정 내용행 기준 {rows} ===")
for i in range(len(DIRS)):
    for k in range(i + 1, len(DIRS)):
        diff = con.execute(f"""SELECT count(*) FROM (
            (SELECT * FROM f{i} EXCEPT SELECT * FROM f{k})
            UNION ALL (SELECT * FROM f{k} EXCEPT SELECT * FROM f{i}))""").fetchall()[0][0]
        ratio = diff / max(rows * 2, 1)
        name_i, name_k = DIRS[i].split("/")[-1], DIRS[k].split("/")[-1]
        status = "OK " if ratio >= TH_MIN_DIFF_RATIO else "XXX"
        print(
            f"[{status}] {name_i} vs {name_k}: 차이 {diff}행 (비율 {ratio * 100:.0f}%, 요구 ≥{TH_MIN_DIFF_RATIO * 100:.0f}%)"
        )
        if ratio < TH_MIN_DIFF_RATIO:
            fails.append((name_i, name_k, ratio))

# ---------- 배정 다양성: scheme→회사 배정 벡터가 쌍별로 동일하면 FAIL ----------
# 내용(금액·일자)이 달라도 "어느 scheme이 어느 회사에서" 배정이 통째로 같으면(mod-N 로테이션)
# 배치 차원의 표본 다양성이 없음. 단일회사 scheme들의 배정 벡터로 비교.
assign = []
for i, d in enumerate(DIRS):
    vec = con.execute(f"""SELECT p.scheme_id, list_sort(array_agg(DISTINCT j.company_code))
        FROM read_csv('{d}/labels/phase2_scheme_provenance.csv', all_varchar=true) p
        JOIN read_csv('{d}/journal_entries.csv', all_varchar=true) j USING(document_id)
        GROUP BY 1 ORDER BY 1""").fetchall()
    assign.append(str(vec))
print("\n=== 배정 다양성 (scheme→회사 벡터 쌍별 비교) ===")
afails = []
for i in range(len(DIRS)):
    for k in range(i + 1, len(DIRS)):
        same = assign[i] == assign[k]
        name_i, name_k = DIRS[i].split("/")[-1], DIRS[k].split("/")[-1]
        print(
            f"[{'XXX' if same else 'OK '}] {name_i} vs {name_k}: 배정 {'동일' if same else '상이'}"
        )
        if same:
            afails.append((name_i, name_k))

ok = not fails and not afails
print(
    f"\n{'PASS — 내용·배정 모두 전 쌍 상이' if ok else f'FAIL — 내용복사 {len(fails)}쌍 / 배정동일 {len(afails)}쌍'}"
)
sys.exit(0 if ok else 1)
