"""FS09 cutoff 시점 정합 정밀 확인 — 조기인식↔익기반품 짝이 실제로 연도경계를 맞게 걸치는지."""

import duckdb

OUT = "data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260610_v1_r1e"
con = duckdb.connect()
con.execute(
    f"""
    CREATE VIEW j AS SELECT * FROM read_csv('{OUT}/journal_entries.csv', all_varchar=true);
    CREATE VIEW p AS SELECT * FROM read_csv('{OUT}/labels/phase2_scheme_provenance.csv', all_varchar=true);
    """
)
rows = con.execute(
    """SELECT p.scheme_instance_id, p.component_role, j.document_id,
              j.posting_date, j.document_date, j.delivery_date, j.gl_account,
              j.debit_amount, j.credit_amount, j.reversal_document_id, j.original_document_id
       FROM p JOIN j USING(document_id)
       WHERE p.scheme_id='FS09'
       ORDER BY p.component_role, j.posting_date, j.line_number"""
).fetchall()
cols = [
    "instance",
    "role",
    "doc",
    "post",
    "docdate",
    "deliv",
    "acct",
    "dr",
    "cr",
    "rev_doc",
    "orig_doc",
]
for r in rows:
    d = dict(zip(cols, r))
    print(
        f"{d['role']:<22} post={d['post'][:10]} docd={str(d['docdate'])[:10]} "
        f"deliv={str(d['deliv'])[:10]} acct={d['acct']} dr={d['dr']} cr={d['cr']} "
        f"rev={str(d['rev_doc'])[:12]} orig={str(d['orig_doc'])[:12]} doc={d['doc'][:12]}"
    )
