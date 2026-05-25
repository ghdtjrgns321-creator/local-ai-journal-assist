"""normal IC entry vs circular truth 비교 — 진짜 도메인 차이 식별.

핵심: 정상 IC entry도 single-doc reciprocal GL pair인가, 아니면 양측 별도 doc인가?
정상이 single-doc balanced 구조면 circular와 구조적으로 동일 → helper로도 분리 불가
정상이 split-doc 구조면 single-doc balanced 자체가 도메인 의심 신호 → helper 정당
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
OUT_JSON = ROOT / "artifacts/ic_design_diagnostic_20260524_part3_normal_compare.json"


def main() -> None:
    con = duckdb.connect()

    truth = pd.read_csv(TRUTH_CSV)
    all_truth_docs = set(truth["document_id"].dropna().astype(str).unique())
    circ_docs = set(
        truth[truth["manipulation_scenario"] == "circular_related_party_transaction"]["document_id"]
        .dropna()
        .astype(str)
        .unique()
    )
    print(f"truth docs: {len(all_truth_docs)}, circular truth: {len(circ_docs)}")

    # IC entries 전체 로드
    q = f"""
    SELECT document_id, company_code, posting_date, business_process,
           gl_account, debit_amount, credit_amount,
           trading_partner, reference, line_number
    FROM read_csv_auto('{JOURNAL_GLOB}')
    WHERE business_process = 'Intercompany'
       OR gl_account IN ('1150', '2050', '4500', '2700')
    """
    df = con.execute(q).fetchdf()
    print(f"IC-related lines: {len(df)}")

    # truth 라벨 분류
    df["doc_str"] = df["document_id"].astype(str)
    df["is_circular_truth"] = df["doc_str"].isin(circ_docs)
    df["is_any_truth"] = df["doc_str"].isin(all_truth_docs)

    # document-level 집계 (IC entries만)
    g = df.groupby("doc_str")
    summary_rows = []
    for doc_id, group in g:
        gls = set(group["gl_account"].astype(str).tolist())
        has_rec = any(g.startswith("1150") or g.startswith("4500") for g in gls)
        has_pay = any(g.startswith("2050") or g.startswith("2700") for g in gls)
        debit = float(group["debit_amount"].fillna(0).sum())
        credit = float(group["credit_amount"].fillna(0).sum())
        balanced = abs(debit - credit) < 0.01
        partners = set(
            t for t in group["trading_partner"].dropna().astype(str).tolist() if t.strip()
        )
        cc = set(group["company_code"].astype(str).tolist())
        bp = group["business_process"].iloc[0] if len(group) > 0 else ""

        summary_rows.append(
            {
                "doc_id": str(doc_id),
                "is_circular_truth": bool(group["is_circular_truth"].iloc[0]),
                "is_any_truth": bool(group["is_any_truth"].iloc[0]),
                "single_doc_reciprocal_gl": has_rec and has_pay,
                "balanced": balanced,
                "line_count": int(len(group)),
                "company_count": len(cc),
                "partner_count": len(partners),
                "first_partner": next(iter(partners), ""),
                "bp": str(bp),
            }
        )

    doc_df = pd.DataFrame(summary_rows)
    print(f"\ndoc-level: {len(doc_df)}")

    # 정상 IC (truth 아님) vs circular truth 비교
    normal_ic = doc_df[(~doc_df["is_any_truth"]) & (doc_df["bp"] == "Intercompany")]
    circular = doc_df[doc_df["is_circular_truth"]]
    other_truth_ic = doc_df[
        (doc_df["is_any_truth"]) & (~doc_df["is_circular_truth"]) & (doc_df["bp"] == "Intercompany")
    ]

    result = {
        "normal_ic_doc_count": int(len(normal_ic)),
        "circular_truth_doc_count": int(len(circular)),
        "other_truth_ic_doc_count": int(len(other_truth_ic)),
        "normal_ic": {
            "single_doc_reciprocal_gl_ratio": round(
                float(normal_ic["single_doc_reciprocal_gl"].mean()), 4
            )
            if len(normal_ic) > 0
            else None,
            "balanced_ratio": round(float(normal_ic["balanced"].mean()), 4)
            if len(normal_ic) > 0
            else None,
            "line_count_describe": normal_ic["line_count"].describe().to_dict()
            if len(normal_ic) > 0
            else None,
            "partner_count_describe": normal_ic["partner_count"].describe().to_dict()
            if len(normal_ic) > 0
            else None,
            "company_count_describe": normal_ic["company_count"].describe().to_dict()
            if len(normal_ic) > 0
            else None,
        },
        "circular_truth": {
            "single_doc_reciprocal_gl_ratio": round(
                float(circular["single_doc_reciprocal_gl"].mean()), 4
            )
            if len(circular) > 0
            else None,
            "balanced_ratio": round(float(circular["balanced"].mean()), 4)
            if len(circular) > 0
            else None,
            "line_count_describe": circular["line_count"].describe().to_dict()
            if len(circular) > 0
            else None,
            "partner_count_describe": circular["partner_count"].describe().to_dict()
            if len(circular) > 0
            else None,
            "company_count_describe": circular["company_count"].describe().to_dict()
            if len(circular) > 0
            else None,
        },
    }

    # 정상 IC에서 single_doc_reciprocal_gl=True (circular와 구조 동일)인 비율이 핵심
    if len(normal_ic) > 0:
        same_struct_normal = normal_ic[
            normal_ic["single_doc_reciprocal_gl"] & normal_ic["balanced"]
        ]
        result["normal_ic_same_struct_as_circular_count"] = int(len(same_struct_normal))
        result["normal_ic_same_struct_ratio"] = round(
            float(len(same_struct_normal) / max(len(normal_ic), 1)), 4
        )

    # partner format 비교
    if len(circular) > 0:
        result["circular_partner_examples"] = (
            circular["first_partner"].value_counts().head(5).to_dict()
        )
    if len(normal_ic) > 0:
        result["normal_partner_examples"] = (
            normal_ic["first_partner"].value_counts().head(10).to_dict()
        )

    OUT_JSON.write_text(
        json.dumps(result, indent=2, default=str, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(result, indent=2, default=str, ensure_ascii=False))
    print(f"\n[saved] {OUT_JSON}")


if __name__ == "__main__":
    main()
