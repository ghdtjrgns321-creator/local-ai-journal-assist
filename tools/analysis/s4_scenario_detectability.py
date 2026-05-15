"""Stage 4 — 시나리오별 detectability + bootstrap CI.

산출:
  artifacts/S4_scenario_detectability_data.json
  artifacts/S4_target_encoding_heatmap.csv
  artifacts/S4_scenario_recall.csv

설계:
  - Trivial rules (Stage 3): doc-level binary 피처 합산 점수.
  - Phase1 rule aggregate: 기존 phase1 케이스 산출물(top200_truth_docs) 그대로 사용.
  - GroupKFold: group = (company_code, fiscal_year) 9개 → 5-fold.
  - Bootstrap: 시나리오별 truth doc 재추출 (n=1000).
  - CI width > 0.15 → 통계적 무의미 표시.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_manipulation_v3"
LABELS = DATA_DIR / "labels" / "manipulated_entry_truth.csv"
TOPIC_JSON = ROOT / "artifacts" / "manipulation_v3_rust_fixed_topic_analysis.json"
OUT_DATA = ROOT / "artifacts" / "S4_scenario_detectability_data.json"
OUT_HEAT = ROOT / "artifacts" / "S4_target_encoding_heatmap.csv"
OUT_RECALL = ROOT / "artifacts" / "S4_scenario_recall.csv"

SCENARIO_ALIAS = {
    "fictitious_entry": "fictitious_entry",
    "period_end_adjustment_manipulation": "period_end_adjustment",
    "embezzlement_concealment": "embezzlement_concealment",
    "circular_related_party_transaction": "circular_related_party",
    "approval_sod_bypass": "approval_sod_bypass",
    "unusual_timing_manipulation": "unusual_timing_manipulation",
}
EXPECTED_DOC_COUNT = {
    "fictitious_entry": 168,
    "period_end_adjustment": 92,
    "embezzlement_concealment": 76,
    "circular_related_party": 34,
    "approval_sod_bypass": 29,
    "unusual_timing_manipulation": 21,
}
CI_WIDTH_INSIGNIFICANT = 0.15


def load_doc_features() -> pd.DataFrame:
    """journal_entries 3-year header를 doc 1행으로 집계, trivial 피처 산출."""
    con = duckdb.connect()
    paths = [str(DATA_DIR / f"journal_entries_{y}.csv") for y in (2022, 2023, 2024)]
    union = "\n  UNION ALL\n  ".join(
        f"SELECT * FROM read_csv_auto('{p}', SAMPLE_SIZE=-1)" for p in paths
    )
    sql = f"""
    WITH header AS (
      SELECT
        document_id,
        ANY_VALUE(company_code) AS company_code,
        ANY_VALUE(fiscal_year) AS fiscal_year,
        ANY_VALUE(fiscal_period) AS fiscal_period,
        ANY_VALUE(posting_date) AS posting_date,
        ANY_VALUE(document_type) AS document_type,
        ANY_VALUE(source) AS source,
        ANY_VALUE(user_persona) AS user_persona,
        ANY_VALUE(created_by) AS created_by,
        ANY_VALUE(approved_by) AS approved_by,
        ANY_VALUE(approval_date) AS approval_date,
        ANY_VALUE(sod_violation) AS sod_violation,
        ANY_VALUE(has_attachment) AS has_attachment,
        ANY_VALUE(business_process) AS business_process,
        SUM(TRY_CAST(debit_amount AS DOUBLE)) AS sum_debit,
        SUM(TRY_CAST(credit_amount AS DOUBLE)) AS sum_credit,
        COUNT(*) AS line_count,
        MAX(LENGTH(line_text)) AS max_line_text_len
      FROM ({union})
      GROUP BY document_id
    )
    SELECT
      document_id,
      company_code,
      fiscal_year,
      fiscal_period,
      document_type,
      source,
      user_persona,
      business_process,
      sum_debit,
      sum_credit,
      line_count,
      (sum_debit + sum_credit) / 2.0 AS doc_amount,
      CAST(posting_date AS TIMESTAMP) AS posting_ts,
      EXTRACT(dow FROM CAST(posting_date AS TIMESTAMP)) AS dow,
      EXTRACT(hour FROM CAST(posting_date AS TIMESTAMP)) AS hour,
      CASE WHEN EXTRACT(dow FROM CAST(posting_date AS TIMESTAMP)) IN (0,6) THEN 1 ELSE 0 END AS f_weekend,
      CASE WHEN EXTRACT(hour FROM CAST(posting_date AS TIMESTAMP)) < 8
            OR EXTRACT(hour FROM CAST(posting_date AS TIMESTAMP)) >= 20 THEN 1 ELSE 0 END AS f_offhour,
      CASE WHEN source IN ('manual','adjustment') THEN 1 ELSE 0 END AS f_manual,
      CASE WHEN approved_by IS NULL OR approved_by = '' THEN 1 ELSE 0 END AS f_no_approver,
      CASE WHEN approved_by = created_by AND approved_by IS NOT NULL THEN 1 ELSE 0 END AS f_self_approval,
      CASE WHEN LOWER(CAST(sod_violation AS VARCHAR)) IN ('true','1') THEN 1 ELSE 0 END AS f_sod_violation,
      CASE WHEN LOWER(CAST(has_attachment AS VARCHAR)) IN ('false','0') THEN 1 ELSE 0 END AS f_no_attachment,
      CASE WHEN fiscal_period IN (3,6,9,12) THEN 1 ELSE 0 END AS f_quarter_end,
      CASE WHEN fiscal_period = 12 THEN 1 ELSE 0 END AS f_year_end
    FROM header
    """
    df = con.execute(sql).fetchdf()
    con.close()
    df["log_amount"] = np.log1p(df["doc_amount"].clip(lower=0).fillna(0))
    amount_p95 = df["doc_amount"].quantile(0.95)
    df["f_amount_high"] = (df["doc_amount"] >= amount_p95).astype(int)
    return df


def attach_truth(df: pd.DataFrame, truth: pd.DataFrame) -> pd.DataFrame:
    truth_map = truth.set_index("document_id")["manipulation_scenario"].to_dict()
    df["scenario_raw"] = df["document_id"].map(truth_map).fillna("normal")
    df["scenario"] = df["scenario_raw"].map(lambda s: SCENARIO_ALIAS.get(s, s))
    df["is_manipulated"] = (df["scenario"] != "normal").astype(int)
    return df


TRIVIAL_FEATURES = [
    "f_weekend",
    "f_offhour",
    "f_manual",
    "f_no_approver",
    "f_self_approval",
    "f_sod_violation",
    "f_no_attachment",
    "f_quarter_end",
    "f_year_end",
    "f_amount_high",
]


def trivial_score(df: pd.DataFrame) -> pd.Series:
    return df[TRIVIAL_FEATURES].sum(axis=1).astype(float)


def target_encoding_table(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    normal = df[df["scenario"] == "normal"]
    for scenario in ["normal"] + list(EXPECTED_DOC_COUNT.keys()):
        sub = df[df["scenario"] == scenario]
        if sub.empty:
            continue
        rec = {"scenario": scenario, "n_docs": len(sub)}
        for col in TRIVIAL_FEATURES:
            rec[col] = sub[col].mean()
        rec["log_amount"] = sub["log_amount"].mean()
        rec["line_count"] = sub["line_count"].mean()
        rows.append(rec)
    return pd.DataFrame(rows)


def groupkfold_recall_at_k(
    df: pd.DataFrame, score_col: str, top_frac: float = 0.01, n_splits: int = 5
) -> pd.DataFrame:
    df = df.copy()
    df["group"] = df["company_code"].astype(str) + "_" + df["fiscal_year"].astype(str)
    gkf = GroupKFold(n_splits=n_splits)
    fold_records = []
    for fold_idx, (_, test_idx) in enumerate(
        gkf.split(df, groups=df["group"]),
    ):
        sub = df.iloc[test_idx].copy()
        k = max(1, int(len(sub) * top_frac))
        threshold = sub[score_col].nlargest(k).iloc[-1]
        sub["in_topk"] = sub[score_col] >= threshold
        for scenario, n_expected in EXPECTED_DOC_COUNT.items():
            sc_truth = sub[sub["scenario"] == scenario]
            n_truth_fold = len(sc_truth)
            n_hit = int(sc_truth["in_topk"].sum())
            fold_records.append(
                {
                    "fold": fold_idx,
                    "scenario": scenario,
                    "n_truth_in_fold": n_truth_fold,
                    "n_hit": n_hit,
                    "recall": (n_hit / n_truth_fold) if n_truth_fold else np.nan,
                    "k": k,
                    "fold_size": len(sub),
                }
            )
    return pd.DataFrame(fold_records)


def bootstrap_ci(
    df: pd.DataFrame, score_col: str, n_boot: int = 1000, top_frac: float = 0.01
) -> pd.DataFrame:
    rng = np.random.default_rng(2026)
    k = max(1, int(len(df) * top_frac))
    threshold = df[score_col].nlargest(k).iloc[-1]
    df = df.copy()
    df["in_topk"] = df[score_col] >= threshold
    rows = []
    for scenario, n_expected in EXPECTED_DOC_COUNT.items():
        sc_truth = df[df["scenario"] == scenario]
        n = len(sc_truth)
        if n == 0:
            continue
        hit_mask = sc_truth["in_topk"].astype(int).to_numpy()
        boot = rng.choice(hit_mask, size=(n_boot, n), replace=True).mean(axis=1)
        lo, hi = np.quantile(boot, [0.025, 0.975])
        width = hi - lo
        rows.append(
            {
                "scenario": scenario,
                "n_truth": n,
                "point_recall": hit_mask.mean(),
                "ci_lo": lo,
                "ci_hi": hi,
                "ci_width": width,
                "statistically_insignificant": width > CI_WIDTH_INSIGNIFICANT,
            }
        )
    return pd.DataFrame(rows)


def phase1_aggregate_recall() -> pd.DataFrame:
    blob = json.loads(TOPIC_JSON.read_text(encoding="utf-8"))
    sm = blob["scenario_metrics"]
    rows = []
    for entry in sm:
        scenario = SCENARIO_ALIAS.get(entry["scenario"], entry["scenario"])
        if scenario not in EXPECTED_DOC_COUNT:
            continue
        n = entry["truth_docs"]
        rows.append(
            {
                "scenario": scenario,
                "n_truth": n,
                "phase1_top10": entry["top10"],
                "phase1_top50": entry["top50"],
                "phase1_top100": entry["top100"],
                "phase1_top200": entry["top200"],
                "phase1_recall_at_top10_cases": entry["top10"] / n if n else np.nan,
                "phase1_recall_at_top100_cases": entry["top100"] / n if n else np.nan,
                "phase1_recall_at_top200_cases": entry["top200"] / n if n else np.nan,
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    truth = pd.read_csv(LABELS)
    doc_df = load_doc_features()
    doc_df = attach_truth(doc_df, truth)
    doc_df["trivial_score"] = trivial_score(doc_df)

    n_truth_found = int(doc_df["is_manipulated"].sum())
    assert n_truth_found == 420, f"truth join mismatch: {n_truth_found}"

    heat = target_encoding_table(doc_df)
    fold_df = groupkfold_recall_at_k(doc_df, "trivial_score")
    boot_df = bootstrap_ci(doc_df, "trivial_score")
    phase1_df = phase1_aggregate_recall()

    recall_summary = (
        fold_df.groupby("scenario")
        .agg(
            fold_mean_recall=("recall", "mean"),
            fold_std_recall=("recall", "std"),
            mean_n_truth_per_fold=("n_truth_in_fold", "mean"),
        )
        .reset_index()
    )
    recall_summary = recall_summary.merge(boot_df, on="scenario", how="outer")
    recall_summary = recall_summary.merge(phase1_df, on="scenario", how="outer")

    heat.to_csv(OUT_HEAT, index=False)
    recall_summary.to_csv(OUT_RECALL, index=False)
    OUT_DATA.write_text(
        json.dumps(
            {
                "n_docs_total": int(len(doc_df)),
                "n_truth_total": n_truth_found,
                "top_frac": 0.01,
                "n_splits": 5,
                "n_bootstrap": 1000,
                "ci_width_insignificant_threshold": CI_WIDTH_INSIGNIFICANT,
                "trivial_features": TRIVIAL_FEATURES,
                "expected_doc_count": EXPECTED_DOC_COUNT,
                "groupkfold_per_fold": fold_df.to_dict(orient="records"),
                "bootstrap_summary": boot_df.to_dict(orient="records"),
                "phase1_aggregate": phase1_df.to_dict(orient="records"),
                "heatmap": heat.to_dict(orient="records"),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print("Wrote:", OUT_DATA, OUT_HEAT, OUT_RECALL)


if __name__ == "__main__":
    main()
