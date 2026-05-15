"""Materialize DataSynth manipulation-v3 candidate.

v3 deliberately keeps the v2 scenario selection and most substantive mutation
logic unchanged. The only DataSynth-side recovery applied here is distribution-
based fictitious revenue amount/batch substance. `unusual_timing` and circular
intercompany are not strengthened for detector entry rates because their raw
accounting substance is already present in v2.
"""

# ruff: noqa: E501,E402,I001

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.scripts import materialize_datasynth_manipulation_v2 as v2


DEFAULT_SOURCE = Path("data/journal/primary/datasynth_contract_v2")
DEFAULT_TARGET = Path("data/journal/primary/datasynth_manipulation_v3")
REVENUE_AMOUNT_QUANTILE = 0.9995
REVENUE_AMOUNT_MULTIPLIER = 1.5


def revenue_amount_reference(rows: pd.DataFrame) -> dict[tuple[str, str], float]:
    work = rows.copy()
    for column in ("debit_amount", "credit_amount", "local_amount"):
        work[column] = pd.to_numeric(work[column], errors="coerce").fillna(0.0).abs()
    work["_abs_amount"] = work[["debit_amount", "credit_amount", "local_amount"]].max(axis=1)
    work["_account_group"] = work["gl_account"].fillna("").astype(str).str[:1]

    revenue = work.loc[work["_account_group"].eq("4")].copy()
    if revenue.empty:
        global_value = float(work["_abs_amount"].quantile(REVENUE_AMOUNT_QUANTILE))
        return {("__GLOBAL__", "4"): max(global_value, 1.0)}

    refs: dict[tuple[str, str], float] = {}
    for company, subset in revenue.groupby("company_code"):
        refs[(str(company), "4")] = float(subset["_abs_amount"].quantile(REVENUE_AMOUNT_QUANTILE))
    refs[("__GLOBAL__", "4")] = float(revenue["_abs_amount"].quantile(REVENUE_AMOUNT_QUANTILE))
    return refs


def reference_for_doc(rows: pd.DataFrame, mask: pd.Series, refs: dict[tuple[str, str], float]) -> float:
    company = str(rows.loc[mask, "company_code"].iloc[0])
    return max(refs.get((company, "4"), refs.get(("__GLOBAL__", "4"), 1.0)), 1.0)


def apply_v3_fictitious_revenue_substance(
    rows: pd.DataFrame,
    selected: dict[str, str],
    refs: dict[tuple[str, str], float],
) -> dict[str, Any]:
    """Refine fictitious revenue as a high-tail revenue event, not a rule target.

    The amount is tied to the generated company's revenue distribution instead
    of a detector threshold. The batch subset represents coordinated false sales
    posting and is selected deterministically from the scenario order.
    """
    doc_ids = rows["document_id"].astype(str)
    fictitious_docs = sorted(
        doc_id for doc_id, scenario in selected.items() if scenario == "fictitious_entry"
    )
    stats = {
        "fictitious_docs": len(fictitious_docs),
        "revenue_gl_docs": 0,
        "amount_ref_quantile": REVENUE_AMOUNT_QUANTILE,
        "amount_ref_multiplier": REVENUE_AMOUNT_MULTIPLIER,
        "amount_ref_enforced_docs": 0,
        "batch_docs": 0,
        "unusual_timing_docs_changed": 0,
        "intercompany_docs_changed": 0,
    }
    year_offsets: dict[int, int] = {}
    for offset, doc_id in enumerate(fictitious_docs):
        mask = doc_ids.eq(doc_id)
        if not mask.any():
            continue
        bucket = v2.stable_bucket(doc_id)
        year = int(rows.loc[mask, "fiscal_year"].iloc[0])
        year_offset = year_offsets.get(year, 0)
        year_offsets[year] = year_offset + 1
        reference_amount = reference_for_doc(rows, mask, refs)
        current_amount = v2.doc_base_amount(rows, mask)
        target_amount = max(current_amount, reference_amount * REVENUE_AMOUNT_MULTIPLIER)
        if target_amount > current_amount:
            stats["amount_ref_enforced_docs"] += 1
        v2.force_two_sided_entry(
            rows,
            mask,
            debit_gl=v2.FICTITIOUS_REVENUE_DEBIT_ACCOUNTS[
                bucket % len(v2.FICTITIOUS_REVENUE_DEBIT_ACCOUNTS)
            ],
            credit_gl=v2.FICTITIOUS_REVENUE_CREDIT_ACCOUNTS[
                bucket % len(v2.FICTITIOUS_REVENUE_CREDIT_ACCOUNTS)
            ],
            amount=target_amount,
        )
        rows.loc[mask, "business_process"] = "O2C"
        rows.loc[mask, "counterparty_type"] = "Customer"
        rows.loc[mask, "document_type"] = "SA"
        rows.loc[mask, "mutation_mutated_field"] = "substantive_fictitious_revenue_distribution"
        rows.loc[mask, "mutation_mutated_value"] = (
            f"ar_to_revenue_amount_ge_{REVENUE_AMOUNT_MULTIPLIER}x_company_revenue_p"
            f"{int(REVENUE_AMOUNT_QUANTILE * 10000)}"
        )
        stats["revenue_gl_docs"] += 1

        if year_offset % 4 in {1, 2}:
            batch_dt = pd.Timestamp(year=year, month=12, day=30, hour=22, minute=year_offset % 60)
            prefix = f"FICTB{year}{year_offset // 4:03d}"
            rows.loc[mask, "posting_date"] = batch_dt.strftime("%Y-%m-%d %H:%M:%S")
            rows.loc[mask, "document_date"] = batch_dt.date().isoformat()
            rows.loc[mask, "created_by"] = f"BATCH_FICT_USER_{year}"
            rows.loc[mask, "document_number"] = rows.loc[mask, "document_number"].astype(str).map(
                lambda value: f"{prefix}-{value[-4:]}" if value else f"{prefix}-{offset:04d}"
            )
            rows.loc[mask, "source"] = "adjustment"
            stats["batch_docs"] += 1
    return stats


def prepare_target_v3(source: Path, target: Path, force: bool) -> None:
    source = source.resolve()
    target = target.resolve()
    workspace = Path.cwd().resolve()
    if not str(target).startswith(str(workspace)):
        raise ValueError(f"Refusing to write outside workspace: {target}")
    if target.exists():
        if not force:
            raise FileExistsError(f"{target} already exists; pass --force to replace it")
        if target.name != "datasynth_manipulation_v3":
            raise ValueError(f"Refusing to remove unexpected target: {target}")
        shutil.rmtree(target)
    target.mkdir(parents=True)

    for child in source.iterdir():
        if child.name == "labels":
            continue
        if child.name.startswith("_archive"):
            continue
        if child.name.startswith("journal_entries"):
            continue
        if child.name.startswith("CONTRACT"):
            continue
        dest = target / child.name
        if child.is_dir():
            shutil.copytree(child, dest)
        elif child.is_file():
            shutil.copy2(child, dest)


def write_v3_manifests(
    target: Path,
    source: Path,
    stats: dict[str, Any],
    label_summary: dict[str, Any],
    checks: dict[str, Any],
    operational_noise_floor: dict[str, Any],
) -> None:
    manifest = {
        "dataset": "datasynth_manipulation_v3",
        "source_dataset": str(source),
        "base_policy": "semantic contract-v2 journal schema and v2 manipulation scenario selection",
        "purpose": "v3 freeze candidate with distribution-based fictitious revenue substance.",
        "fitting_guard_policy": {
            "unusual_timing": "no DataSynth strengthening; raw off-hour/weekend substance is measured only",
            "intercompany_cycle": "no added high-cash cross-trigger strengthening",
            "fictitious_revenue": (
                "amounts are tied to company revenue distribution quantiles, not detector thresholds"
            ),
            "phase1_entry_rates": "measure-only; not a generation gate",
        },
        "journal_policy": "No direct is_fraud/is_anomaly labels; manipulation truth is represented through labels and mutation provenance.",
        "labels_policy": "Manipulation-only labels; contract rule truth and sidecars are excluded.",
        "stats": stats,
        "label_summary": label_summary,
        "checks": checks,
        "operational_noise_floor": operational_noise_floor,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    v2.write_json(target / "MANIPULATION_V3_DATASET_MANIFEST.json", manifest)
    v2.write_json(target / "validated_metadata.json", {"version": "datasynth_manipulation_v3", "status": checks["status"], "checks": checks})
    (target / "PREVIEW.md").write_text(
        "\n".join(
            [
                "# DataSynth Manipulation V3 Candidate",
                "",
                "Semantic-clean background dataset with manipulation-only truth labels.",
                "",
                f"- source: `{source}`",
                f"- truth documents: `{checks['truth_documents']}`",
                f"- status: `{checks['status']}`",
                "",
                "Fitting guard: unusual_timing and intercompany are not strengthened for topic entry rates.",
            ]
        ),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    target = args.target.resolve()
    if target.exists() and target.name != "datasynth_manipulation_v3":
        raise ValueError(f"Refusing to replace unexpected target: {target}")

    prepare_target_v3(args.source, args.target, args.force)
    v2.ensure_manipulation_employee_limits(args.target)
    rows = v2.load_journal(args.source)
    refs = revenue_amount_reference(rows)
    docs = v2.doc_frame(rows)
    selected = v2.select_docs(docs)
    approval_cleanup = v2.neutralize_nontruth_contract_approval_fixtures(rows, selected)
    v2.apply_manipulation_surface(rows, selected)
    substantive_stats = v2.apply_substantive_manipulation_patterns(rows, selected)
    v3_stats = apply_v3_fictitious_revenue_substance(rows, selected, refs)
    truth = v2.build_truth(rows, selected)
    labels = v2.build_anomaly_labels(truth)
    stats = v2.write_journal(args.target, rows)
    label_summary = v2.write_labels(args.target, truth, labels)
    checks = v2.validate(args.target, rows, truth, labels)
    checks["approval_cleanup"] = approval_cleanup
    checks["substantive_mutation_stats"] = substantive_stats
    checks["v3_fictitious_revenue_stats"] = v3_stats
    checks["fitting_guard"] = {
        "unusual_timing_changed_for_entry_rate": False,
        "intercompany_changed_for_cross_rule_entry_rate": False,
        "fictitious_amount_policy": "company revenue p99.95 * 1.5 floor",
    }
    operational_noise_floor = v2.compute_operational_noise_floor(args.target, rows)
    write_v3_manifests(args.target, args.source, stats, label_summary, checks, operational_noise_floor)
    print(json.dumps({"target": str(args.target), "checks": checks}, ensure_ascii=False, indent=2))
    if checks["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
