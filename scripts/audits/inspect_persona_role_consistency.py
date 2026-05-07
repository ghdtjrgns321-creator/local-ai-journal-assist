"""직원 마스터 vs persona / 승인한도 정합성 점검."""
from __future__ import annotations
import json
from pathlib import Path
import duckdb

ROOT = Path("C:/Users/ghdtj/workspace/portfolio/local-ai-assist")
DATA = ROOT / "data/journal/primary/datasynth_manipulation"
EMP = (DATA / "master_data/employees.json").as_posix()
JE = (DATA / "journal_entries.csv").as_posix()
TRUTH = (DATA / "labels/manipulated_entry_truth.csv").as_posix()
META = (DATA / "validated_metadata.json").as_posix()

con = duckdb.connect()
con.execute(f"""
  CREATE VIEW emp   AS SELECT * FROM read_json_auto('{EMP}');
  CREATE VIEW je    AS SELECT * FROM read_csv_auto('{JE}', header=True);
  CREATE VIEW truth AS SELECT * FROM read_csv_auto('{TRUTH}', header=True);
""")

def section(t):
    print("\n" + "="*88 + "\n" + t + "\n" + "="*88)

section("1. 직원 마스터 컬럼")
print(con.execute("DESCRIBE emp").fetchdf().to_string(index=False))

section("2. truth.user_persona vs emp.job_level/job_title — 의심 직원")
print(con.execute("""
  WITH t AS (
    SELECT DISTINCT created_by, user_persona
    FROM truth WHERE created_by IS NOT NULL
  )
  SELECT t.created_by,
         t.user_persona            AS persona_in_truth,
         e.persona                 AS persona_in_master,
         e.job_level,
         e.job_title,
         CAST(e.approval_limit AS HUGEINT) AS approval_limit
  FROM t LEFT JOIN emp e ON e.user_id = t.created_by
  ORDER BY t.user_persona, t.created_by
""").fetchdf().to_string(index=False))

section("3. junior persona(in truth)인데 master 승인한도 1억 초과")
print(con.execute("""
  WITH t AS (
    SELECT DISTINCT created_by, user_persona
    FROM truth WHERE LOWER(user_persona) LIKE '%junior%'
  )
  SELECT t.created_by, t.user_persona, e.persona, e.job_level, e.job_title,
         CAST(e.approval_limit AS HUGEINT) AS approval_limit
  FROM t LEFT JOIN emp e ON e.user_id = t.created_by
  WHERE CAST(e.approval_limit AS HUGEINT) > 100000000
  ORDER BY CAST(e.approval_limit AS HUGEINT) DESC
""").fetchdf().to_string(index=False))

section("4. truth approver의 마스터 정합성")
print(con.execute("""
  WITH a AS (
    SELECT DISTINCT approved_by FROM truth
    WHERE approved_by IS NOT NULL AND approved_by NOT LIKE 'SYSTEM%'
  )
  SELECT a.approved_by, e.persona, e.job_level, e.job_title,
         CAST(e.approval_limit AS HUGEINT) AS approval_limit,
         e.can_approve_je
  FROM a LEFT JOIN emp e ON e.user_id = a.approved_by
  ORDER BY CAST(e.approval_limit AS HUGEINT) DESC NULLS LAST
""").fetchdf().to_string(index=False))

section("5. 승인한도 초과 분개 여부 (truth 전체)")
print(con.execute("""
  WITH doc AS (
    SELECT t.document_id, t.approved_by, t.manipulation_scenario,
           SUM(je.local_amount) AS amt
    FROM truth t JOIN je USING(document_id)
    GROUP BY 1,2,3
  )
  SELECT d.manipulation_scenario,
         COUNT(*) AS docs,
         SUM(CASE WHEN d.amt > CAST(e.approval_limit AS HUGEINT) THEN 1 ELSE 0 END) AS over_limit,
         SUM(CASE WHEN e.approval_limit IS NULL THEN 1 ELSE 0 END) AS approver_unknown,
         SUM(CASE WHEN e.can_approve_je IS FALSE THEN 1 ELSE 0 END) AS approver_lacks_je_right
  FROM doc d LEFT JOIN emp e ON e.user_id = d.approved_by
  GROUP BY 1 ORDER BY docs DESC
""").fetchdf().to_string(index=False))

section("5b. junior persona 작성자 + 본인 승인한도 vs 분개금액")
print(con.execute("""
  WITH doc AS (
    SELECT t.document_id, t.created_by, t.approved_by, t.user_persona, t.manipulation_scenario,
           SUM(je.local_amount) AS amt
    FROM truth t JOIN je USING(document_id)
    WHERE LOWER(t.user_persona) LIKE '%junior%'
    GROUP BY 1,2,3,4,5
  )
  SELECT d.manipulation_scenario,
         d.user_persona,
         d.created_by,
         d.approved_by,
         d.amt::BIGINT AS amt,
         CAST(e_app.approval_limit AS HUGEINT)::BIGINT AS approver_limit,
         e_cre.persona AS creator_master_persona,
         e_app.persona AS approver_master_persona
  FROM doc d
  LEFT JOIN emp e_cre ON e_cre.user_id = d.created_by
  LEFT JOIN emp e_app ON e_app.user_id = d.approved_by
  ORDER BY d.amt DESC LIMIT 20
""").fetchdf().to_string(index=False))

section("6. validated_metadata.json status / overall")
meta = json.loads(Path(META).read_text(encoding="utf-8"))
def shrink(o, depth=0):
    if depth>2: return "..."
    if isinstance(o, dict):
        return {k: shrink(v, depth+1) for k,v in list(o.items())[:30]}
    if isinstance(o, list):
        return [shrink(x, depth+1) for x in o[:5]]
    return o
print(json.dumps(shrink(meta), ensure_ascii=False, indent=2)[:4000])
