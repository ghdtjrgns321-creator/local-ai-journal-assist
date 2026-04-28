"""Build DataSynth v59 by fixing MisclassifiedAccount/CoA boundary leakage.

MisclassifiedAccount must use a valid CoA account that is wrong for the
business process. It must not create an L1-03 InvalidAccount hit.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(os.environ.get("DATASYNTH_SOURCE", ROOT / "data" / "journal" / "primary" / "datasynth"))
OUTPUT = Path(os.environ.get("DATASYNTH_OUTPUT", ROOT / "data" / "journal" / "primary" / "datasynth_v59_candidate"))
YEARS = (2022, 2023, 2024)

REPLACEMENTS = {
    "1300": "1500",
    "1400": "1600",
    "1700": "1200",
    "1800": "1100",
    "1900": "1150",
    "2800": "2700",
    "4800": "4600",
    "5400": "6400",
    "5600": "6500",
    "5700": "6800",
    "5800": "6000",
    "5900": "9300",
}


def norm(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip().replace(".0", "")


def records_for_json(df: pd.DataFrame) -> list[dict[str, Any]]:
    records = []
    for row in df.to_dict(orient="records"):
        out = {}
        for key, value in row.items():
            if value is None or pd.isna(value):
                out[key] = None
            else:
                out[key] = value
        records.append(out)
    return records


def load_valid_accounts() -> set[str]:
    coa = pd.read_csv(ROOT / "config" / "chart_of_accounts.csv", dtype=str)
    return set(coa["gl_account"].dropna().astype(str).str.strip())


def copy_source() -> None:
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    shutil.copytree(SOURCE, OUTPUT)


def write_year_files(df: pd.DataFrame) -> None:
    df.to_csv(OUTPUT / "journal_entries.csv", index=False)
    for year in YEARS:
        subset = df.loc[pd.to_numeric(df["fiscal_year"], errors="coerce").eq(year)].copy()
        subset.to_csv(OUTPUT / f"journal_entries_{year}.csv", index=False)


def write_labels(labels: pd.DataFrame) -> None:
    labels_dir = OUTPUT / "labels"
    labels.to_csv(labels_dir / "anomaly_labels.csv", index=False)
    records = records_for_json(labels)
    (labels_dir / "anomaly_labels.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (labels_dir / "anomaly_labels.jsonl").open("w", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary = {
        "total_labels": int(len(labels)),
        "by_anomaly_type": {str(k): int(v) for k, v in labels["anomaly_type"].value_counts().to_dict().items()},
        "by_category": {str(k): int(v) for k, v in labels["anomaly_category"].value_counts().to_dict().items()},
    }
    (labels_dir / "anomaly_labels_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def find_unregistered_misclassified_rows(df: pd.DataFrame, labels: pd.DataFrame, valid: set[str]) -> pd.DataFrame:
    mis_docs = set(labels.loc[labels["anomaly_type"].eq("MisclassifiedAccount"), "document_id"].dropna().astype(str))
    work = df.loc[df["document_id"].astype(str).isin(mis_docs)].copy()
    work["_gl_norm"] = work["gl_account"].map(norm)
    return work.loc[work["_gl_norm"].ne("") & ~work["_gl_norm"].isin(valid)].copy()


def patch_rows(df: pd.DataFrame, bad: pd.DataFrame) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for idx, row in bad.iterrows():
        before = norm(row["gl_account"])
        if before not in REPLACEMENTS:
            raise RuntimeError(f"No replacement defined for MisclassifiedAccount GL {before}")
        after = REPLACEMENTS[before]
        df.at[idx, "gl_account"] = after
        cases.append(
            {
                "case_id": f"MCA-V59-{len(cases) + 1:03d}",
                "document_id": row["document_id"],
                "fiscal_year": int(row["fiscal_year"]),
                "company_code": row.get("company_code"),
                "document_type": row.get("document_type"),
                "business_process": row.get("business_process"),
                "line_number": int(float(row["line_number"])) if pd.notna(row.get("line_number")) else None,
                "from_invalid_account": before,
                "to_valid_misclassified_account": after,
                "truth_basis": "MisclassifiedAccount must remain inside CoA and be evaluated by L3-01, not L1-03",
            }
        )
    return cases


def update_label_metadata(labels: pd.DataFrame, cases: list[dict[str, Any]]) -> pd.DataFrame:
    by_doc = {str(case["document_id"]): case for case in cases}
    mask = labels["anomaly_type"].eq("MisclassifiedAccount") & labels["document_id"].astype(str).isin(by_doc)
    for idx, row in labels.loc[mask].iterrows():
        case = by_doc[str(row["document_id"])]
        try:
            metadata = json.loads(row["metadata_json"]) if pd.notna(row.get("metadata_json")) else {}
        except Exception:
            metadata = {}
        metadata.update(
            {
                "v59_misclassified_coa_fix": True,
                "from_invalid_account": case["from_invalid_account"],
                "to_valid_misclassified_account": case["to_valid_misclassified_account"],
                "truth_basis": case["truth_basis"],
            }
        )
        labels.at[idx, "metadata_json"] = json.dumps(metadata, ensure_ascii=False)
        labels.at[idx, "description"] = (
            f"Misclassified account: {case['from_invalid_account']} -> "
            f"{case['to_valid_misclassified_account']} (valid CoA account, wrong process)"
        )
    return labels


def write_sidecars(cases: list[dict[str, Any]]) -> None:
    labels_dir = OUTPUT / "labels"
    df = pd.DataFrame(cases)
    df.to_csv(labels_dir / "misclassified_account_coa_fix_cases.csv", index=False)
    (labels_dir / "misclassified_account_coa_fix_cases.json").write_text(
        json.dumps(records_for_json(df), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for year in YEARS:
        subset = df.loc[df["fiscal_year"].eq(year)].copy()
        subset.to_csv(labels_dir / f"misclassified_account_coa_fix_cases_{year}.csv", index=False)
        (labels_dir / f"misclassified_account_coa_fix_cases_{year}.json").write_text(
            json.dumps(records_for_json(subset), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def validate(df: pd.DataFrame, labels: pd.DataFrame, valid: set[str], cases: list[dict[str, Any]]) -> dict[str, Any]:
    invalid_docs = set(labels.loc[labels["anomaly_type"].eq("InvalidAccount"), "document_id"].dropna().astype(str))
    df = df.copy()
    df["_gl_norm"] = df["gl_account"].map(norm)
    bad = df.loc[df["_gl_norm"].ne("") & ~df["_gl_norm"].isin(valid)].copy()
    mis_bad = find_unregistered_misclassified_rows(df, labels, valid)
    unlabeled_bad = bad.loc[~bad["document_id"].astype(str).isin(invalid_docs)]
    by_year = {}
    for year in YEARS:
        y_bad = bad.loc[pd.to_numeric(bad["fiscal_year"], errors="coerce").eq(year)]
        y_unlabeled = unlabeled_bad.loc[pd.to_numeric(unlabeled_bad["fiscal_year"], errors="coerce").eq(year)]
        y_cases = [case for case in cases if case["fiscal_year"] == year]
        by_year[str(year)] = {
            "patched_misclassified_rows": len(y_cases),
            "unregistered_gl_rows": int(len(y_bad)),
            "unregistered_gl_docs": int(y_bad["document_id"].nunique()),
            "unregistered_without_invalid_label_docs": int(y_unlabeled["document_id"].nunique()),
        }
    failures = []
    if not mis_bad.empty:
        failures.append("MisclassifiedAccount still contains unregistered GL accounts")
    if int(unlabeled_bad["document_id"].nunique()) != 0:
        failures.append("Unregistered GL exists without InvalidAccount label")
    return {
        "patched_rows": len(cases),
        "patched_docs": len({case["document_id"] for case in cases}),
        "by_year": by_year,
        "remaining_misclassified_unregistered_rows": int(len(mis_bad)),
        "remaining_unregistered_without_invalid_label_docs": int(unlabeled_bad["document_id"].nunique()),
        "failures": failures,
    }


def update_manifest(validation: dict[str, Any]) -> None:
    path = OUTPUT / "run_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    manifest.setdefault("candidate_patches", []).append(
        {
            "version": "v59_candidate",
            "source": "data/journal/primary/datasynth",
            "purpose": "fix MisclassifiedAccount labels that used GL accounts outside CoA",
            "validation": validation,
        }
    )
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def write_docs(validation: dict[str, Any]) -> None:
    freeze = f"""# DataSynth v59 Candidate

Status: candidate. Built on production v58.

## Purpose

Fix `MisclassifiedAccount` records that used GL accounts outside `config/chart_of_accounts.csv`.

## Scope

- Patched rows/docs: `{validation["patched_rows"]}` / `{validation["patched_docs"]}`
- Remaining misclassified unregistered GL rows: `{validation["remaining_misclassified_unregistered_rows"]}`
- Remaining unregistered GL docs without `InvalidAccount` label: `{validation["remaining_unregistered_without_invalid_label_docs"]}`

## Year Split

| Year | Patched rows | Remaining unregistered GL docs | Unlabeled unregistered GL docs |
|---|---:|---:|---:|
| 2022 | {validation["by_year"]["2022"]["patched_misclassified_rows"]} | {validation["by_year"]["2022"]["unregistered_gl_docs"]} | {validation["by_year"]["2022"]["unregistered_without_invalid_label_docs"]} |
| 2023 | {validation["by_year"]["2023"]["patched_misclassified_rows"]} | {validation["by_year"]["2023"]["unregistered_gl_docs"]} | {validation["by_year"]["2023"]["unregistered_without_invalid_label_docs"]} |
| 2024 | {validation["by_year"]["2024"]["patched_misclassified_rows"]} | {validation["by_year"]["2024"]["unregistered_gl_docs"]} | {validation["by_year"]["2024"]["unregistered_without_invalid_label_docs"]} |

Failures: `{len(validation["failures"])}`
"""
    preview = f"""# DataSynth v59 Candidate Preview

`datasynth_v59_candidate` fixes L1-03/L3-01 boundary leakage.

- Patched `MisclassifiedAccount` rows: `{validation["patched_rows"]}`
- Remaining unregistered non-InvalidAccount docs: `{validation["remaining_unregistered_without_invalid_label_docs"]}`
- Validation failures: `{len(validation["failures"])}`
"""
    (OUTPUT / "FREEZE_V59_CANDIDATE.md").write_text(freeze, encoding="utf-8")
    (OUTPUT / "PREVIEW.md").write_text(preview, encoding="utf-8")
    (OUTPUT / "V59_MISCLASSIFIED_COA_FIX.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    valid = load_valid_accounts()
    missing_targets = sorted(set(REPLACEMENTS.values()) - valid)
    if missing_targets:
        raise RuntimeError(f"Replacement targets are missing from config CoA: {missing_targets}")

    copy_source()
    df = pd.read_csv(OUTPUT / "journal_entries.csv", low_memory=False)
    df["gl_account"] = df["gl_account"].map(norm)
    labels = pd.read_csv(OUTPUT / "labels" / "anomaly_labels.csv")
    bad = find_unregistered_misclassified_rows(df, labels, valid)
    cases = patch_rows(df, bad)
    labels = update_label_metadata(labels, cases)

    write_year_files(df)
    write_labels(labels)
    write_sidecars(cases)
    validation = validate(df, labels, valid, cases)
    update_manifest(validation)
    write_docs(validation)
    if validation["failures"]:
        raise RuntimeError(json.dumps(validation, ensure_ascii=False, indent=2))
    print(json.dumps(validation, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
