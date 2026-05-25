"""circular truth 34건의 raw structure 진단 — reciprocal evidence 존재 여부.

분석 항목 (helper가 잡을 수 있는 증거가 raw에 있는지):
- (a) reciprocal GL pair (1150 ↔ 2050 등) 동시 사용
- (b) company_code ↔ trading_partner reciprocal (forward + reverse)
- (c) amount symmetry (debit ↔ credit balance)
- (d) period-end / after-hours / round amount context
- (e) document-level reciprocal flow (같은 doc에 양방향 흐름)

추가:
- normal IC ic_score=1.0 점유 doc 표본 5건의 IC01 trigger 원인 추정
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATASET_DIR = ROOT / "data/journal/primary/datasynth_manipulation_v7_candidate_fixed5_normalcal5"
TRUTH_CSV = DATASET_DIR / "labels/manipulated_entry_truth.csv"
JOURNAL_GLOB = str(DATASET_DIR / "journal_entries_*.csv")
OUT_JSON = ROOT / "artifacts/ic_design_diagnostic_20260524_part2.json"


def main() -> None:
    con = duckdb.connect()

    # 1. circular truth doc 34개
    truth = pd.read_csv(TRUTH_CSV)
    circ = truth[truth["manipulation_scenario"] == "circular_related_party_transaction"].copy()
    circ_docs = sorted(circ["document_id"].dropna().astype(str).unique().tolist())
    print(f"circular truth docs: {len(circ_docs)}")

    docs_sql = ",".join(f"'{d}'" for d in circ_docs)

    # 2. journal_entries에서 circular truth lines 로드 (debit/credit, gl, partner)
    q = f"""
    SELECT document_id, company_code, posting_date, business_process,
           gl_account, debit_amount, credit_amount,
           trading_partner, reference, line_number, source, created_by
    FROM read_csv_auto('{JOURNAL_GLOB}')
    WHERE document_id IN ({docs_sql})
    ORDER BY document_id, line_number
    """
    df = con.execute(q).fetchdf()
    print(f"circular truth lines: {len(df)}")

    summary: dict = {
        "circular_truth_doc_count": len(circ_docs),
        "circular_truth_line_count": int(len(df)),
    }

    # 3. document-level 구조
    g = df.groupby("document_id")
    doc_struct = []
    for doc_id, group in g:
        gls = sorted(group["gl_account"].astype(str).unique().tolist())
        tps = sorted(
            [
                t
                for t in group["trading_partner"].dropna().astype(str).unique().tolist()
                if t.strip()
            ]
        )
        cc = sorted(group["company_code"].astype(str).unique().tolist())
        debit_sum = float(group["debit_amount"].fillna(0).sum())
        credit_sum = float(group["credit_amount"].fillna(0).sum())
        bp = group["business_process"].iloc[0]
        doc_struct.append(
            {
                "document_id": str(doc_id),
                "business_process": str(bp),
                "company_codes": cc,
                "trading_partners": tps,
                "gl_accounts": gls,
                "line_count": int(len(group)),
                "debit_sum": debit_sum,
                "credit_sum": credit_sum,
                "balanced": abs(debit_sum - credit_sum) < 0.01,
            }
        )

    summary["doc_struct_sample"] = doc_struct[:5]
    summary["business_process_counts"] = (
        df["business_process"].astype(str).value_counts().head(10).to_dict()
    )

    # 4. GL pair 사용 패턴 — receivable 1150 ↔ payable 2050 등
    # circular truth에 어떤 GL이 나오는지
    gl_used = df["gl_account"].astype(str).value_counts().head(20).to_dict()
    summary["gl_account_counts_in_circular"] = gl_used

    # IC pair map (audit_rules.yaml에서 receivable/payable prefix)
    import yaml

    with open(ROOT / "config/audit_rules.yaml", encoding="utf-8") as f:
        rules = yaml.safe_load(f)
    pairs = rules.get("patterns", {}).get("intercompany", {}).get("pairs", [])
    receivables = {str(p["receivable"]) for p in pairs}
    payables = {str(p["payable"]) for p in pairs}
    summary["ic_pair_receivable_prefixes"] = sorted(receivables)
    summary["ic_pair_payable_prefixes"] = sorted(payables)

    # circular truth doc 중 reciprocal GL pair (한 문서에 receivable + payable 둘 다)를 가진 비율
    has_reciprocal = 0
    for doc_id, group in g:
        gls = group["gl_account"].astype(str).tolist()
        has_rec = any(any(gl.startswith(r) for r in receivables) for gl in gls)
        has_pay = any(any(gl.startswith(p) for p in payables) for gl in gls)
        if has_rec and has_pay:
            has_reciprocal += 1
    summary["circular_doc_reciprocal_gl_count"] = has_reciprocal
    summary["circular_doc_reciprocal_gl_ratio"] = round(has_reciprocal / max(len(circ_docs), 1), 3)

    # 5. counterparty reciprocal — circular truth doc 간 cross-company 흐름
    # company_code × trading_partner 쌍
    pair_counts = (
        df[df["trading_partner"].notna()]
        .groupby(["company_code", "trading_partner"])
        .size()
        .reset_index(name="n")
        .sort_values("n", ascending=False)
        .head(20)
    )
    summary["company_partner_pairs_top20"] = pair_counts.to_dict(orient="records")

    # 같은 (A, B) pair가 reverse (B, A)로도 존재하는지
    reciprocal_pairs = []
    seen = set()
    if "trading_partner" in df.columns:
        for _, row in pair_counts.iterrows():
            a, b = str(row["company_code"]), str(row["trading_partner"])
            if (a, b) in seen or (b, a) in seen:
                continue
            reverse = pair_counts[
                (pair_counts["company_code"] == b) & (pair_counts["trading_partner"] == a)
            ]
            if not reverse.empty:
                reciprocal_pairs.append(
                    {
                        "a": a,
                        "b": b,
                        "forward_n": int(row["n"]),
                        "reverse_n": int(reverse["n"].iloc[0]),
                    }
                )
                seen.add((a, b))
    summary["reciprocal_company_partner_pairs"] = reciprocal_pairs[:10]

    # 6. amount symmetry — 각 doc 내 absolute (debit - credit) / max(debit, credit) 분포
    amount_asym = []
    for doc_id, group in g:
        debit = float(group["debit_amount"].fillna(0).sum())
        credit = float(group["credit_amount"].fillna(0).sum())
        denom = max(abs(debit), abs(credit), 1.0)
        asym = abs(debit - credit) / denom
        amount_asym.append(asym)
    summary["amount_asymmetry_describe"] = pd.Series(amount_asym).describe().to_dict()

    # 7. document-level reciprocal flow — 한 문서에서 한 line은 X→Y로, 다른 line은 Y→X로
    doc_reciprocal_flow = 0
    for doc_id, group in g:
        sub = group[group["trading_partner"].notna()].copy()
        pairs_in_doc = list(
            zip(sub["company_code"].astype(str), sub["trading_partner"].astype(str))
        )
        pair_set = set(pairs_in_doc)
        for a, b in pair_set:
            if (b, a) in pair_set:
                doc_reciprocal_flow += 1
                break
    summary["circular_doc_reciprocal_flow_count"] = doc_reciprocal_flow
    summary["circular_doc_reciprocal_flow_ratio"] = round(
        doc_reciprocal_flow / max(len(circ_docs), 1), 3
    )

    # 8. period-end / after-hours / round amount context
    # posting_date 마지막 5일 / 처음 5일
    df["posting_date_pd"] = pd.to_datetime(df["posting_date"], errors="coerce")
    df["dom"] = df["posting_date_pd"].dt.day
    df["dow"] = df["posting_date_pd"].dt.dayofweek
    period_end_count = int(((df["dom"] >= 25) | (df["dom"] <= 5)).sum())
    weekend_count = int((df["dow"] >= 5).sum())
    round_count = int(
        (df["debit_amount"].fillna(0) % 1000 == 0).sum()
        + (df["credit_amount"].fillna(0) % 1000 == 0).sum()
    )
    summary["period_end_context_lines"] = period_end_count
    summary["weekend_context_lines"] = weekend_count
    summary["round_amount_context_lines"] = round_count

    OUT_JSON.write_text(
        json.dumps(summary, indent=2, default=str, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\n[saved] {OUT_JSON}")
    print(json.dumps(summary, indent=2, default=str, ensure_ascii=False)[:3000])


if __name__ == "__main__":
    main()
