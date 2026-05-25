"""IC design diagnostic — circular truth 0.5 cap root cause + max=1.0 점유자 정체.

분석 전용: 코드 변경 0, 결과만 artifacts/ic_design_diagnostic_20260524.{md,json} 산출.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PARQUET = ROOT / "artifacts/stage7_fixed5_normalcal5_phase2_family_by_doc_20260524.parquet"
DATASET_DIR = ROOT / "data/journal/primary/datasynth_manipulation_v7_candidate_fixed5_normalcal5"
TRUTH_CSV = DATASET_DIR / "labels/manipulated_entry_truth.csv"
OUT_JSON = ROOT / "artifacts/ic_design_diagnostic_20260524.json"
OUT_MD = ROOT / "artifacts/ic_design_diagnostic_20260524.md"


def main() -> None:
    con = duckdb.connect()

    # 1. parquet 컬럼 스키마 파악
    cols = con.execute(f"DESCRIBE SELECT * FROM '{PARQUET}'").fetchdf()
    print("=== parquet columns ===")
    print(cols.to_string())

    summary: dict = {"parquet_columns": cols.to_dict(orient="records")}

    # 2. truth doc_id 집합
    truth_df = pd.read_csv(TRUTH_CSV)
    print(f"\n=== truth rows: {len(truth_df)} ===")
    print(truth_df["manipulation_scenario"].value_counts())
    summary["truth_scenario_counts"] = truth_df["manipulation_scenario"].value_counts().to_dict()
    circular_truth_docs = (
        truth_df[truth_df["manipulation_scenario"] == "circular_related_party_transaction"][
            "document_id"
        ]
        .dropna()
        .astype(str)
        .unique()
        .tolist()
    )
    print(f"\ncircular truth docs: {len(circular_truth_docs)}")
    summary["circular_truth_doc_count"] = len(circular_truth_docs)

    # 3. parquet에서 intercompany 관련 컬럼 식별
    ic_cols = [c for c in cols["column_name"] if "intercompany" in c.lower() or "ic_" in c.lower()]
    print(f"\nIC related parquet columns: {ic_cols}")
    summary["ic_related_columns"] = ic_cols

    # 4. circular truth doc의 intercompany score 분포 (parquet level)
    truth_doc_str = ",".join(f"'{d}'" for d in circular_truth_docs)
    if truth_doc_str:
        score_col_candidates = [
            c
            for c in cols["column_name"]
            if "intercompany" in c.lower() and ("score" in c.lower() or "family" in c.lower())
        ]
        if score_col_candidates:
            score_col = score_col_candidates[0]
            q = f"""
            SELECT document_id, {score_col} AS ic_score
            FROM '{PARQUET}'
            WHERE document_id IN ({truth_doc_str})
            """
            df_circ = con.execute(q).fetchdf()
            print(f"\n=== circular truth in parquet: {len(df_circ)} ===")
            print(df_circ["ic_score"].describe())
            summary["circular_in_parquet_count"] = len(df_circ)
            summary["circular_ic_score_describe"] = df_circ["ic_score"].describe().to_dict()
            summary["circular_ic_score_value_counts"] = (
                df_circ["ic_score"].round(4).value_counts().head(20).to_dict()
            )

    # 5. intercompany score 전체 분포 (max=1.0 점유 그룹 분석)
    if ic_cols:
        score_col_candidates = [
            c
            for c in cols["column_name"]
            if "intercompany" in c.lower() and ("score" in c.lower() or "family" in c.lower())
        ]
        if score_col_candidates:
            score_col = score_col_candidates[0]
            # max=1.0 점유 doc
            q_top = f"""
            SELECT document_id, {score_col} AS ic_score
            FROM '{PARQUET}'
            WHERE {score_col} >= 0.99
            ORDER BY {score_col} DESC
            LIMIT 200
            """
            df_top = con.execute(q_top).fetchdf()
            print(f"\n=== ic_score >= 0.99 docs: {len(df_top)} ===")
            print(df_top.head(20))
            summary["ic_score_ge_099_count"] = len(df_top)

            # truth와 normal 분리
            all_truth_docs = set(truth_df["document_id"].dropna().astype(str).unique())
            df_top["is_truth"] = df_top["document_id"].astype(str).isin(all_truth_docs)
            truth_in_top = df_top["is_truth"].sum()
            normal_in_top = (~df_top["is_truth"]).sum()
            print(f"\nTOP ic_score>=0.99: truth={truth_in_top}, normal={normal_in_top}")
            summary["ic_top_099_truth_count"] = int(truth_in_top)
            summary["ic_top_099_normal_count"] = int(normal_in_top)

            # truth top 10 scenarios
            df_top_truth = df_top[df_top["is_truth"]].copy()
            df_top_truth["scenario"] = (
                df_top_truth["document_id"]
                .astype(str)
                .map(
                    dict(
                        zip(
                            truth_df["document_id"].astype(str),
                            truth_df["manipulation_scenario"],
                        )
                    )
                )
            )
            summary["ic_top_099_truth_scenarios"] = (
                df_top_truth["scenario"].value_counts().head(10).to_dict()
            )

    # JSON 저장
    OUT_JSON.write_text(
        json.dumps(summary, indent=2, default=str, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\n[saved] {OUT_JSON}")


if __name__ == "__main__":
    main()
