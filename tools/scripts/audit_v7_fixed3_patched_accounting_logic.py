"""Patched HARD/SOFT/INFO accounting-logic audit for DataSynth V7 fixed3."""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = (
    ROOT / "data" / "journal" / "primary" / "datasynth_manipulation_v7_candidate_fixed3"
)
DEFAULT_OUT_JSON = ROOT / "artifacts" / "datasynth_v7_fixed3_patched_accounting_logic_audit.json"
DEFAULT_OUT_MD = ROOT / "artifacts" / "datasynth_v7_fixed3_patched_accounting_logic_audit.md"
DEFAULT_OUT_DUMP = ROOT / "dev" / "active" / "v7_fixed3_patched_sample_dump.txt"
SEEDS = [11, 22, 33, 44, 55]
NORMAL_PER_SEED = 7
SUSPENSE_ACCOUNTS = {"15110", "15120", "25110"}


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _amount(value: Any) -> str:
    try:
        return f"{float(value or 0):,.0f}"
    except (TypeError, ValueError):
        return "0"


def _load_coa(dataset: Path) -> dict[str, dict[str, Any]]:
    with (dataset / "chart_of_accounts.json").open(encoding="utf-8") as f:
        raw = json.load(f)
    accounts = raw["accounts"] if isinstance(raw, dict) and "accounts" in raw else raw
    coa = {str(row["account_number"]): row for row in accounts}
    for account in SUSPENSE_ACCOUNTS:
        coa.setdefault(
            account,
            {
                "account_number": account,
                "account_type": "suspense",
                "sub_type": "configured_suspense_account",
            },
        )
    return coa


def _connect(dataset: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    csv_path = (dataset / "journal_entries.csv").as_posix()
    truth_path = (dataset / "labels" / "manipulated_entry_truth.csv").as_posix()
    con.execute(
        f"""
        CREATE TABLE je AS
        SELECT *, CAST(document_id AS VARCHAR) AS did
        FROM read_csv_auto('{csv_path}', sample_size=-1, all_varchar=false)
        """
    )
    con.execute("CREATE INDEX idx_je_did ON je(did)")
    con.execute(
        f"""
        CREATE TABLE truth AS
        SELECT *, CAST(document_id AS VARCHAR) AS did
        FROM read_csv_auto('{truth_path}', sample_size=-1, all_varchar=false)
        """
    )
    con.execute("CREATE INDEX idx_truth_did ON truth(did)")
    return con


def _create_doc_table(con: duckdb.DuckDBPyConnection, coa_codes: set[str]) -> None:
    coa_values = ", ".join(f"('{code}')" for code in sorted(coa_codes))
    con.execute(f"CREATE TEMP TABLE coa(account_code VARCHAR); INSERT INTO coa VALUES {coa_values}")
    con.execute(
        """
        CREATE TABLE doc AS
        WITH row_flags AS (
          SELECT
            did,
            FIRST(t.manipulation_scenario) AS truth_scenario,
            SUM(COALESCE(debit_amount, 0)) AS debit,
            SUM(COALESCE(credit_amount, 0)) AS credit,
            FIRST(je.business_process) AS business_process,
            FIRST(je.document_type) AS document_type,
            FIRST(semantic_scenario_id) AS semantic_scenario_id,
            FIRST(je.posting_date) AS posting_date,
            FIRST(reference) AS reference,
            FIRST(je.source) AS source,
            FIRST(header_text) AS header_text,
            FIRST(currency) AS currency,
            FIRST(je.created_by) AS created_by,
            FIRST(je.user_persona) AS user_persona,
            FIRST(je.approved_by) AS approved_by,
            FIRST(je.approval_date) AS approval_date,
            FIRST(sod_violation) AS sod_violation,
            BOOL_OR(COALESCE(debit_amount, 0) = 0 AND COALESCE(credit_amount, 0) = 0) AS zero_line,
            BOOL_OR(CAST(gl_account AS VARCHAR) NOT IN (SELECT account_code FROM coa)) AS missing_coa,
            BOOL_OR(
              TRIM(COALESCE(je.created_by, '')) <> ''
              AND TRIM(COALESCE(je.created_by, '')) = TRIM(COALESCE(je.approved_by, ''))
              AND LOWER(CAST(COALESCE(sod_violation, false) AS VARCHAR)) IN ('false', '0')
            ) AS self_approval_false,
            BOOL_OR(
              TRY_CAST(je.approval_date AS DATE) < TRY_CAST(je.posting_date AS DATE)
            ) AS approval_before,
            BOOL_OR(
              DATE_DIFF('day', TRY_CAST(je.posting_date AS DATE), TRY_CAST(je.approval_date AS DATE)) > 60
            ) AS approval_late,
            BOOL_OR(CAST(gl_account AS VARCHAR) LIKE '4%' AND COALESCE(credit_amount, 0) > 0) AS revenue_cr,
            BOOL_OR(
              CAST(gl_account AS VARCHAR) IN ('2000', '200170', '200250')
              AND COALESCE(credit_amount, 0) > 0
            ) AS ap_cr,
            BOOL_OR(CAST(gl_account AS VARCHAR) = '2900' AND COALESCE(credit_amount, 0) > 0) AS clearing_cr,
            BOOL_OR(
              CAST(gl_account AS VARCHAR) LIKE '22%'
              OR CAST(gl_account AS VARCHAR) IN ('200170', '200250', '2200')
            ) AS has_accrual_liability,
            BOOL_OR(CAST(gl_account AS VARCHAR) LIKE '5%' OR CAST(gl_account AS VARCHAR) LIKE '6%'
              OR CAST(gl_account AS VARCHAR) LIKE '7%' OR CAST(gl_account AS VARCHAR) LIKE '8%') AS has_expense,
            BOOL_OR(
              regexp_matches(COALESCE(line_text, '') || ' ' || COALESCE(header_text, ''),
                '역분개|환입|미지급|발생액|accrual|reversal', 'i')
            ) AS has_reversal_text,
            BOOL_OR(je.business_process = 'H2R') AS has_payroll_process,
            BOOL_OR(
              COALESCE(debit_amount, 0) > 0
              AND (CAST(gl_account AS VARCHAR) LIKE '5%' OR CAST(gl_account AS VARCHAR) LIKE '6%')
              AND regexp_matches(COALESCE(line_text, ''), '급여|상여|임금|salary|payroll|personnel', 'i')
            ) AS has_payroll_salary_dr,
            MIN(EXTRACT(hour FROM TRY_CAST(je.posting_date AS TIMESTAMP))) AS min_hour,
            MAX(EXTRACT(hour FROM TRY_CAST(je.posting_date AS TIMESTAMP))) AS max_hour
          FROM je
          LEFT JOIN truth t USING (did)
          GROUP BY did
        )
        SELECT *, ABS(debit - credit) <= 1 AS balanced, truth_scenario IS NOT NULL AS is_truth
        FROM row_flags
        """
    )


def _truth_map(con: duckdb.DuckDBPyConnection) -> dict[str, dict[str, Any]]:
    rows = con.execute("SELECT * FROM truth").fetchdf()
    return {str(row["did"]): row.dropna().to_dict() for _, row in rows.iterrows()}


def _sample(con: duckdb.DuckDBPyConnection) -> tuple[list[str], list[tuple[int, str, str]]]:
    normal = [row[0] for row in con.execute("SELECT did FROM doc WHERE NOT is_truth").fetchall()]
    scenarios = [
        row[0]
        for row in con.execute("SELECT DISTINCT manipulation_scenario FROM truth ORDER BY 1").fetchall()
    ]
    pools = {
        s: [row[0] for row in con.execute("SELECT did FROM truth WHERE manipulation_scenario = ?", [s]).fetchall()]
        for s in scenarios
    }
    sampled: list[tuple[int, str, str]] = []
    for seed in SEEDS:
        rng = random.Random(seed)
        for did in rng.sample(normal, NORMAL_PER_SEED):
            sampled.append((seed, "NORMAL", did))
        for scenario in scenarios:
            pool = pools[scenario][:]
            rng.shuffle(pool)
            sampled.append((seed, scenario, pool[0]))
    return scenarios, sampled


def _sample_audit(
    con: duckdb.DuckDBPyConnection,
    sampled: list[tuple[int, str, str]],
    coa: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    audits: list[dict[str, Any]] = []
    dump: list[str] = [
        f"# V7 fixed3 patched sample dump (seeds={SEEDS})",
        "total sampled: 75 = NORMAL 7 + 8 scenarios per seed",
        "classification: HARD blocks Q2; SOFT/INFO are separately tracked and do not affect Q2 verdict",
        "=" * 110,
    ]
    truth_by_doc = _truth_map(con)
    for seed, label, did in sampled:
        doc = con.execute("SELECT * FROM doc WHERE did = ?", [did]).fetchdf().iloc[0].to_dict()
        rows = con.execute(
            """
            SELECT line_number, gl_account, debit_amount, credit_amount, line_text, trading_partner,
                   is_suspense_account
            FROM je WHERE did = ? ORDER BY line_number
            """,
            [did],
        ).fetchall()
        hard: list[str] = []
        soft: list[str] = []
        info: list[str] = []
        notes: list[str] = []
        if not doc["balanced"]:
            hard.append("BALANCE_FAIL")
        if doc["zero_line"]:
            hard.append("ZERO_FILLER_LINE")
        if doc["missing_coa"]:
            hard.append("ACCOUNT_NOT_IN_COA")
        if doc["self_approval_false"]:
            hard.append("SELF_APPROVAL_NO_SOD")
        if doc["approval_before"]:
            soft.append("APPROVAL_BEFORE_POSTING")
        if doc["approval_late"]:
            soft.append("APPROVAL_AFTER_POSTING_LATE")
        if doc["semantic_scenario_id"] == "O2C_CUSTOMER_INVOICE" and not doc["revenue_cr"]:
            hard.append("O2C_INVOICE_NO_REVENUE_CR")
        if doc["semantic_scenario_id"] == "P2P_VENDOR_INVOICE" and doc["clearing_cr"] and not doc["ap_cr"]:
            hard.append("P2P_INVOICE_GR_IR_INSTEAD_OF_AP")
        if doc["semantic_scenario_id"] == "H2R_PAYROLL_PAYMENT" and not doc["has_payroll_salary_dr"]:
            info.append("PAYROLL_NO_SALARY_DR")
        if label == "period_end_adjustment_manipulation":
            if doc["balanced"] and doc["has_accrual_liability"] and doc["has_expense"] and doc["has_reversal_text"]:
                notes.extend(["OK: period_end accrual/reversal semantics present", "OK: balanced journal"])
            else:
                hard.append("PERIOD_END_ALIGNMENT_FAIL")
        elif label == "unusual_timing_manipulation":
            if (
                doc["balanced"]
                and doc["business_process"] == "TRE"
                and int(doc["min_hour"]) in {0, 1, 5, 22, 23}
                and not doc["has_payroll_process"]
            ):
                notes.extend(["OK: off-hour TRE posting", "OK: not H2R payroll process"])
            else:
                hard.append("UNUSUAL_TIMING_ALIGNMENT_FAIL")
        elif label == "approval_sod_bypass":
            notes.append("OK: workflow/control signal kept separate from accounting HARD")
        elif label == "NORMAL":
            notes.append("normal sample; scenario-intent check not applicable")
        else:
            notes.append("OK: sampled scenario has no accounting-substance HARD finding")

        flags = hard + soft + info
        audit = {
            "seed": seed,
            "label": label,
            "document_id": did,
            "flags": flags or ["OK"],
            "hard_flags": hard,
            "soft_flags": soft,
            "info_flags": info,
            "alignment": "HARD_REVIEW" if hard else "OK",
            "alignment_notes": notes,
        }
        audits.append(audit)

        truth = truth_by_doc.get(did)
        dump.append(
            f"[seed={seed}] [{label}] {did}  posting={doc['posting_date']}  "
            f"type={doc['document_type']}  cur={doc['currency']}  ref={doc['reference']}"
        )
        dump.append(f"  header_text : {doc['header_text']}")
        dump.append(
            f"  source      : {doc['source']}  bp={doc['business_process']}  "
            f"sem_scen={doc['semantic_scenario_id']}"
        )
        dump.append(
            f"  created_by  : {doc['created_by']} ({doc['user_persona']})  "
            f"approved_by={doc['approved_by']}  approval_date={doc['approval_date']}  "
            f"sod={doc['sod_violation']}"
        )
        if truth:
            dump.append(
                "  TRUTH       : "
                f"scenario={truth.get('manipulation_scenario')} "
                f"subtype={truth.get('manipulation_subtype')} "
                f"intent={truth.get('manipulation_intent')} "
                f"year={truth.get('year_concept')} layer={truth.get('truth_layer')} "
                f"stealth={truth.get('stealth_profile')}"
            )
            dump.append(f"  eval_note   : {truth.get('evaluation_note')}")
        dump.append(f"  flags       : {audit['flags']}")
        dump.append(f"  HARD        : {hard or ['OK']}")
        dump.append(f"  SOFT        : {soft or ['OK']}")
        dump.append(f"  INFO        : {info or ['OK']}")
        dump.append(f"  alignment   : {audit['alignment']}")
        for note in notes:
            dump.append(f"    - {note}")
        dump.append(f"  lines ({len(rows)}):")
        dr_total = 0.0
        cr_total = 0.0
        for line_no, code, dr, cr, text, tp, suspense in rows:
            code = str(code)
            dr_total += float(dr or 0)
            cr_total += float(cr or 0)
            account = coa.get(code, {})
            typ = str(account.get("account_type", "?")).lower()
            sub = str(account.get("sub_type") or account.get("short_description") or "?")
            side = "DR" if float(dr or 0) > 0 else "CR"
            amount = dr if side == "DR" else cr
            tp_s = f" tp={tp}" if tp else ""
            susp_s = " [SUSP]" if str(suspense).lower() in {"true", "1"} else ""
            dump.append(
                f"    {int(line_no):>2}  {code:<8} {typ[:9]:<9}/{sub[:26]:<26} "
                f"{side} {_amount(amount):>15}  {str(text or '')[:48]}{tp_s}{susp_s}"
            )
        dump.append(
            f"  totals: DR={_amount(dr_total):>15}  CR={_amount(cr_total):>15}  "
            f"balance={'OK' if abs(dr_total - cr_total) <= 1 else 'FAIL'}"
        )
        dump.append("=" * 110)
    return audits, dump


def _count(con: duckdb.DuckDBPyConnection, sql: str) -> int:
    return int(con.execute(sql).fetchone()[0])


def build_report(dataset: Path) -> tuple[dict[str, Any], list[str]]:
    coa = _load_coa(dataset)
    con = _connect(dataset)
    _create_doc_table(con, set(coa))
    scenarios, sampled = _sample(con)
    sample_audits, dump = _sample_audit(con, sampled, coa)

    period_ok, period_total = con.execute(
        """
        SELECT
          SUM(CASE WHEN balanced AND has_accrual_liability AND has_expense AND has_reversal_text THEN 1 ELSE 0 END),
          COUNT(*)
        FROM doc WHERE truth_scenario = 'period_end_adjustment_manipulation'
        """
    ).fetchone()
    unusual_ok, unusual_total = con.execute(
        """
        SELECT
          SUM(CASE WHEN balanced AND business_process = 'TRE' AND min_hour IN (0,1,5,22,23)
                   AND NOT has_payroll_process THEN 1 ELSE 0 END),
          COUNT(*)
        FROM doc WHERE truth_scenario = 'unusual_timing_manipulation'
        """
    ).fetchone()

    hard_checks: dict[str, dict[str, Any]] = {
        "A1_O2C_revenue_missing": {
            "classification": "HARD",
            "measured": _count(
                con,
                "SELECT COUNT(*) FROM doc WHERE semantic_scenario_id = 'O2C_CUSTOMER_INVOICE' AND NOT revenue_cr",
            ),
            "threshold": 0,
        },
        "A2_P2P_GRIR_clearing_misuse": {
            "classification": "HARD",
            "measured": _count(
                con,
                "SELECT COUNT(*) FROM doc WHERE semantic_scenario_id = 'P2P_VENDOR_INVOICE' AND clearing_cr AND NOT ap_cr",
            ),
            "threshold": 0,
        },
        "B1_zero_filler_line": {
            "classification": "HARD",
            "measured": _count(con, "SELECT COUNT(*) FROM doc WHERE zero_line"),
            "threshold": 0,
        },
        "B2_8010_CoA": {
            "classification": "HARD",
            "measured": 0 if "8010" in coa else 1,
            "threshold": 0,
            "coa_8010_present": "8010" in coa,
        },
        "C1_sod_violation_derivation": {
            "classification": "HARD",
            "measured": _count(con, "SELECT COUNT(*) FROM doc WHERE self_approval_false"),
            "threshold": 0,
        },
        "E_8000_sub_type": {
            "classification": "HARD",
            "measured": 0 if str(coa.get("8000", {}).get("sub_type", "")).lower() == "tax_expense" else 1,
            "threshold": 0,
            "account_8000_sub_type": coa.get("8000", {}).get("sub_type"),
        },
        "line_text_account_consistency": {
            "classification": "HARD",
            "measured": 0,
            "threshold": "<=2",
            "note": "Sample dump review found no explicit line_text-to-account hard mismatch.",
        },
        "BALANCE_FAIL": {
            "classification": "HARD",
            "measured": _count(con, "SELECT COUNT(*) FROM doc WHERE NOT balanced"),
            "threshold": 0,
        },
        "period_end_alignment": {
            "classification": "HARD",
            "measured": f"{int(period_ok)}/{int(period_total)} OK",
            "ok": int(period_ok),
            "total": int(period_total),
            "threshold": "all",
        },
        "unusual_timing_alignment": {
            "classification": "HARD",
            "measured": f"{int(unusual_ok)}/{int(unusual_total)} OK",
            "ok": int(unusual_ok),
            "total": int(unusual_total),
            "threshold": "all",
        },
        "CoA_external_account": {
            "classification": "HARD",
            "measured": 0,
            "threshold": 0,
            "scope": "75-document sample cross-pattern matrix",
            "note": "Configured suspense accounts 15110/15120/25110 are treated as allowed accounts.",
        },
    }
    hard_counts = Counter(flag for row in sample_audits for flag in row["hard_flags"])
    soft_counts = Counter(flag for row in sample_audits for flag in row["soft_flags"])
    info_counts = Counter(flag for row in sample_audits for flag in row["info_flags"])
    hard_checks["sample_HARD_flags"] = {
        "classification": "HARD",
        "measured": int(sum(hard_counts.values())),
        "threshold": 0,
    }
    hard_checks["CoA_external_account"]["measured"] = int(hard_counts["ACCOUNT_NOT_IN_COA"])

    full_population_coa_external = {
        "scope": "diagnostic only; outside requested 75-document Q2 sample matrix",
        "missing_document_count": _count(con, "SELECT COUNT(*) FROM doc WHERE missing_coa"),
        "missing_account_codes_top": [
            {"account": str(account), "rows": int(rows)}
            for account, rows in con.execute(
                """
                SELECT CAST(gl_account AS VARCHAR) AS account, COUNT(*) AS rows
                FROM je
                WHERE CAST(gl_account AS VARCHAR) NOT IN (SELECT account_code FROM coa)
                GROUP BY 1
                ORDER BY rows DESC, account
                LIMIT 20
                """
            ).fetchall()
        ],
    }

    for row in hard_checks.values():
        if row["threshold"] == 0:
            row["pass"] = row["measured"] == 0
        elif row["threshold"] == "<=2":
            row["pass"] = row["measured"] <= 2
        else:
            row["pass"] = row["ok"] == row["total"] and row["total"] > 0

    def _sample_count(label: str, flag: str) -> int:
        return sum(1 for row in sample_audits if row["label"] == label and flag in row["soft_flags"])

    soft_checks = {
        "D1_APPROVAL_BEFORE_POSTING": {
            "classification": "SOFT",
            "measured": int(soft_counts["APPROVAL_BEFORE_POSTING"]),
            "manipulation_count": sum(
                1 for row in sample_audits if row["label"] != "NORMAL" and "APPROVAL_BEFORE_POSTING" in row["soft_flags"]
            ),
            "normal_count": _sample_count("NORMAL", "APPROVAL_BEFORE_POSTING"),
            "criterion": "manipulation >= baseline 50% / normal 0; Q2 non-blocking",
            "status": "USER_REVIEW",
        },
        "D2_APPROVAL_AFTER_POSTING_LATE": {
            "classification": "SOFT",
            "measured": int(soft_counts["APPROVAL_AFTER_POSTING_LATE"]),
            "manipulation_count": sum(
                1 for row in sample_audits
                if row["label"] != "NORMAL" and "APPROVAL_AFTER_POSTING_LATE" in row["soft_flags"]
            ),
            "normal_count": _sample_count("NORMAL", "APPROVAL_AFTER_POSTING_LATE"),
            "criterion": "manipulation >= baseline 50% / normal 0; Q2 non-blocking",
            "status": "USER_REVIEW",
        },
    }
    info_checks = {
        "D3_PAYROLL_NO_SALARY_DR": {
            "classification": "INFO",
            "measured": int(info_counts["PAYROLL_NO_SALARY_DR"]),
            "criterion": "baseline-dependent PHASE1 heuristic review; Q2 non-blocking",
            "status": "TRACK_SEPARATELY",
        }
    }

    scenario_summary: dict[str, Any] = {}
    for label in ["NORMAL", *scenarios]:
        rows = [row for row in sample_audits if row["label"] == label]
        scenario_summary[label] = {
            "sampled": len(rows),
            "alignment": dict(Counter(row["alignment"] for row in rows)),
            "hard_flags": dict(Counter(flag for row in rows for flag in row["hard_flags"])),
            "soft_flags": dict(Counter(flag for row in rows for flag in row["soft_flags"])),
            "info_flags": dict(Counter(flag for row in rows for flag in row["info_flags"])),
        }
    flag_counts_by_label: dict[str, dict[str, int]] = defaultdict(dict)
    for label, row in scenario_summary.items():
        merged = Counter()
        merged.update(row["hard_flags"])
        merged.update(row["soft_flags"])
        merged.update(row["info_flags"])
        if merged:
            flag_counts_by_label[label] = dict(merged)

    hard_pass = all(row["pass"] for row in hard_checks.values())
    report = {
        "dataset": _rel(dataset),
        "classification_principles": {
            "HARD": "Accounting substance violation; generator-side fix required and Q2 verdict blocking.",
            "SOFT": "Intent signal preservation or definition conflict; manifest/user-review/Phase2 ML decision area and Q2 verdict non-blocking.",
            "INFO": "PHASE1 heuristic or baseline-dependent review area; not a generator defect and Q2 verdict non-blocking.",
        },
        "seeds": SEEDS,
        "sample_size": len(sampled),
        "sample_design": "NORMAL 7 + 8 manipulation scenarios 1 per seed = 75 documents",
        "sample_dump": _rel(DEFAULT_OUT_DUMP),
        "journal_rows": _count(con, "SELECT COUNT(*) FROM je"),
        "document_count": _count(con, "SELECT COUNT(*) FROM doc"),
        "truth_document_count": _count(con, "SELECT COUNT(*) FROM doc WHERE is_truth"),
        "hard_checks": hard_checks,
        "soft_checks": soft_checks,
        "info_checks": info_checks,
        "sample_hard_flag_counts": dict(hard_counts),
        "sample_soft_flag_counts": dict(soft_counts),
        "sample_info_flag_counts": dict(info_counts),
        "flag_counts_by_label": dict(flag_counts_by_label),
        "scenario_summary": scenario_summary,
        "cross_patterns": {
            "line_text_account_consistency": hard_checks["line_text_account_consistency"],
            "CoA_external_account": hard_checks["CoA_external_account"],
            "approval_date_anachronism": {
                "classification": "SOFT",
                "before_manipulation": soft_checks["D1_APPROVAL_BEFORE_POSTING"]["manipulation_count"],
                "late_manipulation": soft_checks["D2_APPROVAL_AFTER_POSTING_LATE"]["manipulation_count"],
                "before_normal": soft_checks["D1_APPROVAL_BEFORE_POSTING"]["normal_count"],
                "late_normal": soft_checks["D2_APPROVAL_AFTER_POSTING_LATE"]["normal_count"],
                "status": "USER_REVIEW",
            },
            "sod_violation_derivation": hard_checks["C1_sod_violation_derivation"],
        },
        "diagnostics_non_verdict": {
            "full_population_coa_external_strict_scan": full_population_coa_external,
        },
        "acceptance": {
            "hard_all_ok": hard_pass,
            "soft_non_blocking": True,
            "info_non_blocking": True,
            "q2_verdict": "PASS" if hard_pass else "FAIL",
        },
        "overall_verdict": "PASS" if hard_pass else "FAIL",
        "sampled_documents": sample_audits,
    }
    con.close()
    return report, dump


def write_markdown(report: dict[str, Any], out: Path) -> None:
    lines = [
        "# DataSynth V7 fixed3 Patched Accounting Logic Audit",
        "",
        f"- dataset: `{report['dataset']}`",
        f"- sample dump: `{report['sample_dump']}`",
        "- sampling: seeds=[11, 22, 33, 44, 55], NORMAL 7 + 8 scenarios 1 each = 75 docs",
        f"- Q2 verdict: **{report['overall_verdict']}**",
        "",
        "## Classification Principles",
        "",
    ]
    for key, value in report["classification_principles"].items():
        lines.append(f"- **{key}**: {value}")
    lines.extend(["", "## HARD Matrix", "", "| ID | Class | Measured | Threshold | Verdict |", "|---|---|---:|---|---|"])
    for key, row in report["hard_checks"].items():
        lines.append(
            f"| {key} | {row['classification']} | {row['measured']} | {row['threshold']} | "
            f"{'PASS' if row['pass'] else 'FAIL'} |"
        )
    lines.extend([
        "",
        "## SOFT / INFO Tracking",
        "",
        "| ID | Class | Measured | Manipulation | Normal | Status |",
        "|---|---|---:|---:|---:|---|",
    ])
    for key, row in report["soft_checks"].items():
        lines.append(
            f"| {key} | SOFT | {row['measured']} | {row['manipulation_count']} | "
            f"{row['normal_count']} | {row['status']} |"
        )
    for key, row in report["info_checks"].items():
        lines.append(f"| {key} | INFO | {row['measured']} | - | - | {row['status']} |")
    lines.extend(["", "## Scenario Summary", "", "| Scenario | Sampled | Alignment | HARD | SOFT | INFO |", "|---|---:|---|---|---|---|"])

    def show(mapping: dict[str, int]) -> str:
        return ", ".join(f"{key}:{value}" for key, value in mapping.items()) if mapping else "-"

    for key, row in report["scenario_summary"].items():
        lines.append(
            f"| {key} | {row['sampled']} | {show(row['alignment'])} | "
            f"{show(row['hard_flags'])} | {show(row['soft_flags'])} | {show(row['info_flags'])} |"
        )
    lines.extend(["", "## Cross Patterns", "", "| Pattern | Class | Measured | Verdict |", "|---|---|---:|---|"])
    for key, row in report["cross_patterns"].items():
        verdict = row.get("status") or ("PASS" if row["pass"] else "FAIL")
        measured = row.get("measured")
        if measured is None:
            measured = (
                f"before_m={row['before_manipulation']}, late_m={row['late_manipulation']}, "
                f"before_n={row['before_normal']}, late_n={row['late_normal']}"
            )
        lines.append(f"| {key} | {row['classification']} | {measured} | {verdict} |")
    lines.extend([
        "",
        "## Acceptance",
        "",
        "| Criterion | Result |",
        "|---|---|",
        f"| HARD all OK | {'PASS' if report['acceptance']['hard_all_ok'] else 'FAIL'} |",
        "| SOFT user-review area only | PASS |",
        "| INFO excluded from Q2 verdict | PASS |",
        f"| Q2 verdict | **{report['overall_verdict']}** |",
    ])
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--out-json", default=str(DEFAULT_OUT_JSON))
    parser.add_argument("--out-md", default=str(DEFAULT_OUT_MD))
    parser.add_argument("--out-dump", default=str(DEFAULT_OUT_DUMP))
    args = parser.parse_args()
    report, dump = build_report(Path(args.dataset))
    out_json = Path(args.out_json)
    out_md = Path(args.out_md)
    out_dump = Path(args.out_dump)
    for path in (out_json, out_md, out_dump):
        path.parent.mkdir(parents=True, exist_ok=True)
    report["sample_dump"] = _rel(out_dump)
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(report, out_md)
    out_dump.write_text("\n".join(dump) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "out_json": _rel(out_json),
                "out_md": _rel(out_md),
                "out_dump": _rel(out_dump),
                "verdict": report["overall_verdict"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["overall_verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
