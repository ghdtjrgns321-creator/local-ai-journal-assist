"""Build v97 candidate by diversifying BatchAnomaly confirmed labels.

L4-06 rule truth is already broader than confirmed anomalies. v96 confirmed
BatchAnomaly labels were all automated R2R SA. This patch selects a deterministic
stratified confirmed subset from existing L4-06 rule truth so confirmed labels
cover realistic recurring payroll, customer billing, vendor payment, treasury,
and R2R batch contexts without changing detector code.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v96_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v97_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
RULE_ID = "L4-06"

PLAN = {
    2022: {"R2R": 20, "H2R": 20, "P2P": 18},
    2023: {"R2R": 22, "H2R": 22, "O2C": 20},
    2024: {"R2R": 18, "H2R": 18, "TRE": 17},
}

SIGNAL_BY_PROCESS = {
    "R2R": ("period_end_batch_run", "general ledger closing batch concentration", 0.68),
    "H2R": ("recurring_payroll_batch", "recurring payroll or HR allocation batch concentration", 0.58),
    "O2C": ("customer_billing_batch", "customer billing batch concentration", 0.62),
    "P2P": ("vendor_payment_batch", "vendor payment batch concentration", 0.62),
    "TRE": ("treasury_payment_batch", "treasury payment batch concentration", 0.64),
}


def _copy_candidate_safely() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(SOURCE, DEST, copy_function=shutil.copy2)


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl_records(path: Path, df: pd.DataFrame) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for record in df.where(pd.notna(df), None).to_dict(orient="records"):
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _select_confirmed() -> pd.DataFrame:
    rt = pd.read_csv(LABELS / "rule_truth_L4_06.csv", low_memory=False)
    selected = []
    for year, process_plan in PLAN.items():
        for process, count in process_plan.items():
            group = rt.loc[
                rt["fiscal_year"].eq(year) & rt["business_process"].astype(str).eq(process)
            ].copy()
            if len(group) < count:
                raise SystemExit(f"not enough L4-06 rows for {year} {process}: {len(group)} < {count}")
            selected.append(_balanced_company_pick(group, count))
    out = pd.concat(selected, ignore_index=True)
    return out.sort_values(["fiscal_year", "business_process", "company_code", "document_number"]).reset_index(drop=True)


def _balanced_company_pick(group: pd.DataFrame, count: int) -> pd.DataFrame:
    ordered = group.sort_values(["company_code", "document_number", "document_id"]).copy()
    buckets = {
        str(company): company_df.reset_index(drop=True)
        for company, company_df in ordered.groupby("company_code", sort=True)
    }
    picks = []
    cursor = {company: 0 for company in buckets}
    companies = list(buckets)
    while len(picks) < count:
        progressed = False
        for company in companies:
            idx = cursor[company]
            if idx >= len(buckets[company]):
                continue
            picks.append(buckets[company].iloc[idx])
            cursor[company] += 1
            progressed = True
            if len(picks) >= count:
                break
        if not progressed:
            break
    if len(picks) < count:
        raise SystemExit(f"company-balanced pick exhausted rows: {len(picks)} < {count}")
    return pd.DataFrame(picks)


def _journal_summary() -> pd.DataFrame:
    parts = []
    usecols = [
        "document_id",
        "fiscal_year",
        "approved_by",
        "created_by",
        "user_persona",
        "debit_amount",
        "credit_amount",
    ]
    for year in YEARS:
        df = pd.read_csv(DEST / f"journal_entries_{year}.csv", usecols=usecols, low_memory=False)
        amount = df[["debit_amount", "credit_amount"]].fillna(0).max(axis=1)
        df["_line_amount"] = amount
        parts.append(
            df.groupby("document_id", dropna=False).agg(
                approved_by=("approved_by", "first"),
                created_by=("created_by", "first"),
                user_persona=("user_persona", "first"),
                line_count=("document_id", "size"),
                max_line_amount=("_line_amount", "max"),
            )
        )
    return pd.concat(parts)


def _make_confirmed(selected: pd.DataFrame) -> pd.DataFrame:
    summary = _journal_summary()
    selected = selected.merge(summary, left_on="document_id", right_index=True, how="left")
    rows = []
    seq = 1
    for _, row in selected.iterrows():
        process = str(row["business_process"])
        signal, basis_text, confidence = SIGNAL_BY_PROCESS.get(
            process,
            ("batch_concentration", "batch concentration", 0.60),
        )
        year = int(row["fiscal_year"])
        run_id = f"L406-{year}-{process}-CONFIRMED-RUN"
        run_count = int(
            selected.loc[
                selected["fiscal_year"].eq(year)
                & selected["business_process"].astype(str).eq(process)
            ].shape[0]
        )
        case_id = f"{run_id}-{seq:04d}"
        rows.append(
            {
                "anomaly_type": "BatchAnomaly",
                "approved_by": row.get("approved_by"),
                "batch_signal": signal,
                "business_process": process,
                "case_id": case_id,
                "company_code": row.get("company_code"),
                "created_by": row.get("created_by"),
                "document_id": row.get("document_id"),
                "document_number": row.get("document_number"),
                "document_type": row.get("document_type"),
                "evaluation_policy": "confirmed subset; batch_review_population is coverage only",
                "fiscal_year": year,
                "is_period_end": True,
                "line_count": int(row.get("line_count") or 0),
                "max_line_amount": float(row.get("max_line_amount") or 0.0),
                "posting_date": row.get("posting_date"),
                "run_document_count": run_count,
                "run_id": run_id,
                "run_type": process.lower(),
                "source": row.get("source"),
                "truth_basis": f"confirmed {basis_text}",
                "user_persona": row.get("user_persona"),
            }
        )
        seq += 1
    return pd.DataFrame(rows)


def _replace_anomaly_labels(confirmed: pd.DataFrame) -> None:
    path = LABELS / "anomaly_labels.csv"
    labels = pd.read_csv(path, low_memory=False)
    old = labels.loc[labels["anomaly_type"].eq("BatchAnomaly")].copy().reset_index(drop=True)
    if len(old) != len(confirmed):
        raise SystemExit(f"BatchAnomaly count changed: old={len(old)} new={len(confirmed)}")
    keep = labels.loc[~labels["anomaly_type"].eq("BatchAnomaly")].copy()
    new_rows = old.copy()
    timestamp = old["detection_timestamp"].iloc[0] if not old.empty else "2026-04-26 00:00:00"
    for i, row in confirmed.reset_index(drop=True).iterrows():
        meta = {
            "rule_id": RULE_ID,
            "case_id": row["case_id"],
            "run_id": row["run_id"],
            "run_document_count": int(row["run_document_count"]),
            "source": row["source"],
            "business_process": row["business_process"],
            "document_type": row["document_type"],
            "batch_signal": row["batch_signal"],
            "truth_basis": row["truth_basis"],
            "evaluation_policy": row["evaluation_policy"],
            "source_candidate": "v97",
        }
        new_rows.loc[i, "document_id"] = row["document_id"]
        new_rows.loc[i, "document_type"] = row["document_type"]
        new_rows.loc[i, "company_code"] = row["company_code"]
        new_rows.loc[i, "anomaly_date"] = row["posting_date"]
        new_rows.loc[i, "detection_timestamp"] = timestamp
        new_rows.loc[i, "confidence"] = SIGNAL_BY_PROCESS.get(
            str(row["business_process"]),
            ("", "", 0.60),
        )[2]
        new_rows.loc[i, "severity"] = 2
        new_rows.loc[i, "description"] = f"L4-06 {row['business_process']} batch anomaly run"
        new_rows.loc[i, "is_injected"] = True
        new_rows.loc[i, "monetary_impact"] = row["max_line_amount"]
        new_rows.loc[i, "related_entities"] = json.dumps([row["document_id"], row["run_id"]], ensure_ascii=False)
        new_rows.loc[i, "cluster_id"] = row["run_id"]
        new_rows.loc[i, "injection_strategy"] = "BatchAnomalyRunCoverage"
        new_rows.loc[i, "structured_strategy_type"] = "BatchAnomaly"
        new_rows.loc[i, "structured_strategy_json"] = json.dumps(meta, ensure_ascii=False)
        new_rows.loc[i, "causal_reason_type"] = "BatchRunConcentration"
        new_rows.loc[i, "causal_reason_json"] = json.dumps(meta, ensure_ascii=False)
        new_rows.loc[i, "scenario_id"] = row["run_id"]
        new_rows.loc[i, "metadata_json"] = json.dumps(meta, ensure_ascii=False)
    rebuilt = pd.concat([keep, new_rows], ignore_index=True)
    rebuilt.to_csv(path, index=False)
    _write_json_records(LABELS / "anomaly_labels.json", rebuilt)
    _write_jsonl_records(LABELS / "anomaly_labels.jsonl", rebuilt)


def _write_confirmed(confirmed: pd.DataFrame) -> None:
    confirmed.to_csv(LABELS / "batch_confirmed_anomalies.csv", index=False)
    _write_json_records(LABELS / "batch_confirmed_anomalies.json", confirmed)
    for year in YEARS:
        year_df = confirmed.loc[confirmed["fiscal_year"].eq(year)].copy()
        year_df.to_csv(LABELS / f"batch_confirmed_anomalies_{year}.csv", index=False)
        _write_json_records(LABELS / f"batch_confirmed_anomalies_{year}.json", year_df)


def _write_manifest(confirmed: pd.DataFrame) -> None:
    manifest = {
        "version": "v97_candidate",
        "base_version": "v96_candidate",
        "patch": "batch_anomaly_confirmed_diversity",
        "confirmed_count": int(len(confirmed)),
        "by_year": {str(k): int(v) for k, v in confirmed["fiscal_year"].value_counts().sort_index().items()},
        "by_process": {str(k): int(v) for k, v in confirmed["business_process"].value_counts().items()},
        "by_source": {str(k): int(v) for k, v in confirmed["source"].value_counts().items()},
        "by_document_type": {str(k): int(v) for k, v in confirmed["document_type"].value_counts().items()},
        "contract": {
            "rule_truth": "rule_truth_L4_06 remains the broad review/booster population",
            "confirmed_subset": "batch_confirmed_anomalies and BatchAnomaly labels are a stratified confirmed subset",
        },
    }
    (LABELS / "V97_BATCH_ANOMALY_DIVERSITY.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V97_CANDIDATE.md").write_text(
        "\n".join(
            [
                "# DataSynth v97 Candidate",
                "",
                "Base: `datasynth_v96_candidate`",
                "",
                "Patch: diversify confirmed BatchAnomaly labels across existing L4-06 rule-truth contexts.",
                "",
                f"Confirmed BatchAnomaly labels: {len(confirmed):,}",
                "",
                "Process split:",
                *[f"- {k}: {v}" for k, v in confirmed["business_process"].value_counts().items()],
                "",
                "Production baseline remains unchanged.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> None:
    _copy_candidate_safely()
    selected = _select_confirmed()
    confirmed = _make_confirmed(selected)
    _write_confirmed(confirmed)
    _replace_anomaly_labels(confirmed)
    _write_manifest(confirmed)
    print(
        json.dumps(
            {
                "dest": str(DEST.relative_to(ROOT)),
                "confirmed_count": int(len(confirmed)),
                "by_year": {
                    str(k): int(v) for k, v in confirmed["fiscal_year"].value_counts().sort_index().items()
                },
                "by_process": {
                    str(k): int(v) for k, v in confirmed["business_process"].value_counts().items()
                },
                "by_source": {
                    str(k): int(v) for k, v in confirmed["source"].value_counts().items()
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
