"""Verify DataSynth manipulation-v5 candidate generator fixes.

This script reports aggregate-only metrics. It does not dump source journal rows.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_manipulation_v5_candidate"
DEFAULT_OUT_JSON = ROOT / "artifacts" / "datasynth_v5_quality_verification.json"
DEFAULT_OUT_MD = ROOT / "artifacts" / "datasynth_v5_quality_verification.md"


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def _union_sql(data_dir: Path) -> str:
    parts = []
    for year in (2022, 2023, 2024):
        path = data_dir / f"journal_entries_{year}.csv"
        parts.append(f"SELECT * FROM read_csv_auto('{path.as_posix()}', SAMPLE_SIZE=-1)")
    return "\nUNION ALL\n".join(parts)


def _scalar(con: duckdb.DuckDBPyConnection, sql: str) -> dict[str, Any]:
    row = con.execute(sql).fetchdf().iloc[0].to_dict()
    result: dict[str, Any] = {}
    for key, value in row.items():
        if pd.isna(value):
            result[str(key)] = None
        elif hasattr(value, "item"):
            result[str(key)] = value.item()
        else:
            result[str(key)] = value
    return result


def verify(data_dir: Path) -> dict[str, Any]:
    union = _union_sql(data_dir)
    truth_path = data_dir / "labels" / "manipulated_entry_truth.csv"
    con = duckdb.connect()

    truth_counts = _scalar(
        con,
        f"""
        SELECT count(*) AS truth_docs, count(distinct document_id) AS distinct_truth_docs
        FROM read_csv_auto('{truth_path.as_posix()}')
        """,
    )
    o2c = _scalar(
        con,
        f"""
        WITH j AS ({union}),
        d AS (
          SELECT document_id,
                 bool_or(CAST(gl_account AS VARCHAR) LIKE '4%') AS has_revenue,
                 bool_or(CAST(gl_account AS VARCHAR) IN ('2100','2110')
                         OR CAST(gl_account AS VARCHAR) LIKE '21%') AS has_vat,
                 bool_or(CAST(gl_account AS VARCHAR) LIKE '10%'
                         OR CAST(gl_account AS VARCHAR) LIKE '11%') AS has_ar_cash
          FROM j
          WHERE semantic_scenario_id = 'O2C_CUSTOMER_INVOICE'
          GROUP BY document_id
        )
        SELECT count(*) AS docs,
               sum(CASE WHEN NOT has_revenue THEN 1 ELSE 0 END) AS no_revenue_docs,
               sum(CASE WHEN has_ar_cash AND has_vat AND NOT has_revenue THEN 1 ELSE 0 END)
                   AS ar_vat_no_revenue_docs
        FROM d
        """,
    )
    o2c_full_doc = _scalar(
        con,
        f"""
        WITH j AS ({union}),
        target_docs AS (
          SELECT DISTINCT document_id
          FROM j
          WHERE semantic_scenario_id = 'O2C_CUSTOMER_INVOICE'
        ),
        d AS (
          SELECT j.document_id,
                 bool_or(CAST(gl_account AS VARCHAR) LIKE '4%') AS has_revenue,
                 max(coalesce(try_cast(debit_amount AS DOUBLE), 0)) AS max_debit,
                 max(coalesce(try_cast(credit_amount AS DOUBLE), 0)) AS max_credit,
                 max(abs(coalesce(try_cast(local_amount AS DOUBLE), 0))) AS max_abs_local,
                 count(*) AS line_count
          FROM j
          JOIN target_docs USING(document_id)
          GROUP BY j.document_id
        )
        SELECT count(*) AS docs,
               sum(CASE WHEN NOT has_revenue THEN 1 ELSE 0 END) AS full_doc_no_revenue_docs,
               sum(CASE WHEN NOT has_revenue AND max_debit > 0 THEN 1 ELSE 0 END)
                   AS no_revenue_has_debit_docs,
               sum(CASE WHEN NOT has_revenue AND max_credit > 0 THEN 1 ELSE 0 END)
                   AS no_revenue_has_credit_docs,
               sum(CASE WHEN NOT has_revenue AND max_abs_local > 0 THEN 1 ELSE 0 END)
                   AS no_revenue_has_local_docs,
               avg(CASE WHEN NOT has_revenue THEN line_count ELSE NULL END)
                   AS no_revenue_avg_line_count
        FROM d
        """,
    )
    o2c_missing_types = con.execute(
        f"""
        WITH j AS ({union}),
        target_docs AS (
          SELECT DISTINCT document_id
          FROM j
          WHERE semantic_scenario_id = 'O2C_CUSTOMER_INVOICE'
        ),
        d AS (
          SELECT j.document_id,
                 string_agg(DISTINCT CAST(business_process AS VARCHAR), '|') AS processes,
                 string_agg(DISTINCT CAST(document_type AS VARCHAR), '|') AS document_types,
                 bool_or(CAST(gl_account AS VARCHAR) LIKE '4%') AS has_revenue
          FROM j
          JOIN target_docs USING(document_id)
          GROUP BY j.document_id
        )
        SELECT processes, document_types, count(*) AS docs
        FROM d
        WHERE NOT has_revenue
        GROUP BY processes, document_types
        ORDER BY docs DESC
        LIMIT 10
        """
    ).fetchdf()
    p2p = _scalar(
        con,
        f"""
        WITH j AS ({union})
        SELECT count(*) AS cr_grir_rows,
               count(distinct document_id) AS cr_grir_docs
        FROM j
        WHERE semantic_scenario_id = 'P2P_VENDOR_INVOICE'
          AND CAST(gl_account AS VARCHAR) = '2900'
          AND try_cast(credit_amount AS DOUBLE) > 0
        """,
    )
    sod = _scalar(
        con,
        f"""
        WITH j AS ({union})
        SELECT count(*) AS self_approval_rows,
               count(distinct document_id) AS self_approval_docs,
               sum(CASE WHEN lower(CAST(sod_violation AS VARCHAR)) IN ('true','1','yes')
                        THEN 1 ELSE 0 END) AS sod_true_rows,
               sum(CASE WHEN lower(CAST(sod_violation AS VARCHAR)) IN ('false','0','no')
                        THEN 1 ELSE 0 END) AS sod_false_rows
        FROM j
        WHERE created_by = approved_by
          AND coalesce(CAST(approved_by AS VARCHAR), '') NOT IN ('', 'NAN', 'NONE', 'NULL')
        """,
    )
    zero = _scalar(
        con,
        f"""
        WITH j AS ({union})
        SELECT count(*) AS zero_rows,
               count(distinct document_id) AS zero_docs
        FROM j
        WHERE coalesce(try_cast(debit_amount AS DOUBLE), 0) = 0
          AND coalesce(try_cast(credit_amount AS DOUBLE), 0) = 0
          AND coalesce(try_cast(local_amount AS DOUBLE), 0) = 0
        """,
    )
    background = con.execute(
        f"""
        WITH j AS ({union}),
        truth AS (SELECT document_id FROM read_csv_auto('{truth_path.as_posix()}')),
        d AS (
          SELECT j.document_id,
                 max(CASE WHEN truth.document_id IS NULL THEN 0 ELSE 1 END) AS is_truth,
                 max(CASE WHEN created_by = approved_by
                          AND coalesce(CAST(approved_by AS VARCHAR), '')
                              NOT IN ('', 'NAN', 'NONE', 'NULL')
                          THEN 1 ELSE 0 END) AS self_approval_gap_proxy,
                 max(CASE WHEN coalesce(CAST(approved_by AS VARCHAR), '')
                              IN ('', 'NAN', 'NONE', 'NULL')
                          THEN 1 ELSE 0 END) AS missing_approval_proxy,
                 max(CASE WHEN business_process = 'Intercompany'
                          OR counterparty_type = 'IntercompanyAffiliate'
                          OR CAST(trading_partner AS VARCHAR) LIKE 'IC-%'
                          THEN 1 ELSE 0 END) AS is_intercompany_proxy,
                 max(CASE WHEN CAST(gl_account AS VARCHAR) IN ('15110', '15120', '25110')
                          THEN 1 ELSE 0 END) AS is_suspense_account_proxy,
                 max(CASE WHEN CAST(created_by AS VARCHAR) LIKE 'TEMP_ONBOARDING%'
                          THEN 1 ELSE 0 END) AS employee_creator_join_gap_proxy,
                 max(abs(date_diff('day', try_cast(document_date AS TIMESTAMP),
                                   try_cast(posting_date AS TIMESTAMP)))) AS abs_days_backdated,
                 max(CASE WHEN approved_by = 'NEAR_LIMIT_REVIEWER'
                          THEN 1 ELSE 0 END) AS near_threshold_proxy,
                 max(abs(date_diff('day', try_cast(posting_date AS TIMESTAMP),
                                   try_cast(approval_date AS TIMESTAMP)))) AS approval_lag_abs
          FROM j
          LEFT JOIN truth USING(document_id)
          GROUP BY j.document_id
        )
        SELECT is_truth,
               count(*) AS docs,
               avg(self_approval_gap_proxy) AS self_approval_gap_proxy_rate,
               avg(missing_approval_proxy) AS missing_approval_proxy_rate,
               avg(CASE WHEN abs_days_backdated > 0 THEN 1 ELSE 0 END) AS backdated_rate,
               avg(near_threshold_proxy) AS near_threshold_proxy_rate,
               avg(is_intercompany_proxy) AS intercompany_proxy_rate,
               avg(is_suspense_account_proxy) AS suspense_proxy_rate,
               avg(employee_creator_join_gap_proxy) AS creator_join_gap_proxy_rate,
               avg(approval_lag_abs) AS approval_lag_abs_mean
        FROM d
        GROUP BY is_truth
        ORDER BY is_truth
        """
    ).fetchdf()
    con.close()

    coa_raw = json.loads((data_dir / "chart_of_accounts.json").read_text(encoding="utf-8"))
    manifest_path = data_dir / "MANIPULATION_V5_DATASET_MANIFEST.json"
    if not manifest_path.exists():
        manifest_path = data_dir / "MANIPULATION_V6_DATASET_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    accounts = coa_raw.get("accounts", []) if isinstance(coa_raw, dict) else []
    coa = {
        "has_15110": any(str(row.get("account_number")) == "15110" for row in accounts),
        "has_8010": any(str(row.get("account_number")) == "8010" for row in accounts),
        "has_8030": any(str(row.get("account_number")) == "8030" for row in accounts),
        "account_8000": [
            {
                "account_type": row.get("account_type"),
                "sub_type": row.get("sub_type"),
                "description": row.get("description"),
            }
            for row in accounts
            if str(row.get("account_number")) == "8000"
        ][:3],
    }

    checks = {
        "truth_docs_620": truth_counts["truth_docs"] == 620
        and truth_counts["distinct_truth_docs"] == 620,
        "o2c_revenue_missing_zero": o2c["no_revenue_docs"] == 0,
        "p2p_credit_grir_zero": p2p["cr_grir_rows"] == 0,
        "sod_self_approval_false_zero": sod["sod_false_rows"] == 0,
        "zero_filler_rows_zero": zero["zero_rows"] == 0,
        "coa_15110_present": coa["has_15110"],
        "coa_8010_present": coa["has_8010"],
        "coa_8030_present": coa["has_8030"],
    }
    result = {
        "dataset": _rel(data_dir),
        "truth": truth_counts,
        "o2c_customer_invoice": o2c,
        "o2c_customer_invoice_full_doc_debug": o2c_full_doc,
        "o2c_missing_document_type_debug": o2c_missing_types.to_dict(orient="records"),
        "p2p_vendor_invoice": p2p,
        "sod_consistency": sod,
        "zero_filler": zero,
        "background_enrichment": background.to_dict(orient="records"),
        "chart_of_accounts": coa,
        "manifest_top_level_keys": sorted(manifest.keys()),
        "manifest_stats": manifest.get("stats", {}),
        "checks": checks,
        "status": "pass" if all(checks.values()) else "fail",
    }
    return result


def write_md(result: dict[str, Any], path: Path) -> None:
    lines = [
        "# DataSynth Manipulation Candidate Quality Verification",
        "",
        f"- dataset: `{result['dataset']}`",
        f"- status: **{result['status'].upper()}**",
        "",
        "## Checks",
        "",
    ]
    for key, value in result["checks"].items():
        lines.append(f"- {key}: {'PASS' if value else 'FAIL'}")
    lines.extend(
        [
            "",
            "## Key Metrics",
            "",
            f"- truth_docs: {result['truth']['truth_docs']}",
            f"- O2C revenue missing docs: {result['o2c_customer_invoice']['no_revenue_docs']}",
            f"- P2P credit GR/IR rows: {result['p2p_vendor_invoice']['cr_grir_rows']}",
            f"- self-approval rows with sod=false: {result['sod_consistency']['sod_false_rows']}",
            f"- zero amount filler rows: {result['zero_filler']['zero_rows']}",
            f"- CoA 15110 present: {result['chart_of_accounts']['has_15110']}",
            f"- CoA 8010 present: {result['chart_of_accounts']['has_8010']}",
            f"- CoA 8030 present: {result['chart_of_accounts']['has_8030']}",
            "",
            "Phase2 AUROC targets are intentionally not used as generation goals.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    args = parser.parse_args()

    result = verify(args.data_dir)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    write_md(result, args.out_md)
    print(json.dumps({"status": result["status"], "out_json": _rel(args.out_json)}))


if __name__ == "__main__":
    main()
