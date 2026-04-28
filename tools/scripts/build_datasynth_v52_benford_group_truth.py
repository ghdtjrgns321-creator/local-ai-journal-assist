from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
from pathlib import Path

import pandas as pd


MIN_GROUP_SIZE = 500
MAD_THRESHOLD = 0.012
STRONG_MAD = 0.015
EXPECTED = {digit: math.log10(1 + 1 / digit) for digit in range(1, 10)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build v52 L4-02 Benford group-level truth sidecars.")
    parser.add_argument("--source", required=True, help="Source dataset directory, normally datasynth_v51_candidate")
    parser.add_argument("--output", required=True, help="Output candidate directory")
    parser.add_argument("--force", action="store_true", help="Overwrite output directory")
    return parser.parse_args()


def write_records(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for record in records for key in record}) if records else []
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)


def write_sidecar_family(labels_dir: Path, stem: str, records: list[dict]) -> None:
    write_records(labels_dir / f"{stem}.csv", records)
    (labels_dir / f"{stem}.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    for year in sorted({int(r["fiscal_year"]) for r in records}):
        year_records = [r for r in records if int(r["fiscal_year"]) == year]
        write_records(labels_dir / f"{stem}_{year}.csv", year_records)
        (labels_dir / f"{stem}_{year}.json").write_text(
            json.dumps(year_records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def account_code(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().str.lower().str.replace(r"\.0+$", "", regex=True)


def first_digit_from_amount(series: pd.Series) -> pd.Series:
    amount = pd.to_numeric(series, errors="coerce").abs()
    text = amount.fillna(0).map(lambda value: f"{value:.12g}")
    digit = text.str.extract(r"([1-9])", expand=False)
    return pd.to_numeric(digit, errors="coerce").astype("Int64")


def load_year(path: Path, year: int) -> pd.DataFrame:
    usecols = [
        "document_id",
        "company_code",
        "fiscal_year",
        "posting_date",
        "document_number",
        "document_type",
        "business_process",
        "source",
        "gl_account",
        "debit_amount",
        "credit_amount",
        "line_number",
    ]
    header = pd.read_csv(path, nrows=0).columns
    cols = [col for col in usecols if col in header]
    df = pd.read_csv(path, dtype=str, usecols=cols, low_memory=False)
    df["fiscal_year"] = year
    debit = pd.to_numeric(df.get("debit_amount", 0), errors="coerce").fillna(0.0).abs()
    credit = pd.to_numeric(df.get("credit_amount", 0), errors="coerce").fillna(0.0).abs()
    df["_amount"] = pd.concat([debit, credit], axis=1).max(axis=1)
    df["_first_digit"] = first_digit_from_amount(df["_amount"])
    df["_account_code"] = account_code(df.get("gl_account", pd.Series(dtype=object)))
    df = df[df["_amount"] > 0].copy()
    df = df[df["_first_digit"].notna()].copy()
    df = df[df["_account_code"].ne("")].copy()
    return df


def distribution_metrics(digits: pd.Series) -> tuple[float, dict[int, float], list[int], dict[int, float]]:
    counts = digits.astype(int).value_counts().reindex(range(1, 10), fill_value=0)
    total = int(counts.sum())
    observed = {int(d): float(counts.loc[d] / total) for d in range(1, 10)}
    deviations = {digit: observed[digit] - EXPECTED[digit] for digit in range(1, 10)}
    mad = sum(abs(deviations[digit]) for digit in range(1, 10)) / 9
    flagged_digits = [digit for digit in range(1, 10) if abs(deviations[digit]) > MAD_THRESHOLD]
    return mad, observed, flagged_digits, deviations


def build_year_records(df: pd.DataFrame, year: int) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    finding_records: list[dict] = []
    drilldown_records: list[dict] = []
    normal_records: list[dict] = []
    skipped_records: list[dict] = []

    groups = df.groupby(["company_code", "_account_code"], dropna=False)
    for group_idx, ((company_code, gl_account), group) in enumerate(groups, start=1):
        sample_size = int(len(group))
        if sample_size < MIN_GROUP_SIZE:
            skipped_records.append(
                {
                    "group_id": f"BENFORD-SKIP-{year}-{group_idx:05d}",
                    "fiscal_year": year,
                    "company_code": str(company_code),
                    "gl_account": str(gl_account),
                    "sample_size": sample_size,
                    "skip_reason": f"sample_size_below_{MIN_GROUP_SIZE}",
                }
            )
            continue

        mad, observed, flagged_digits, deviations = distribution_metrics(group["_first_digit"])
        common = {
            "fiscal_year": year,
            "company_code": str(company_code),
            "gl_account": str(gl_account),
            "sample_size": sample_size,
            "mad": round(float(mad), 6),
            "flagged_digits": "|".join(str(digit) for digit in flagged_digits),
            "observed_distribution_json": json.dumps({str(k): round(v, 6) for k, v in observed.items()}),
            "deviation_json": json.dumps({str(k): round(v, 6) for k, v in deviations.items()}),
            "evaluation_unit": "fiscal_year+company_code+gl_account",
        }
        if mad > MAD_THRESHOLD and flagged_digits:
            severity = "strong" if mad > STRONG_MAD else "moderate"
            finding_id = f"BENFORD-FIND-{year}-{len(finding_records) + 1:04d}"
            finding_record = common | {
                "finding_id": finding_id,
                "finding_severity": severity,
                "truth_basis": "group-level Benford distribution anomaly",
                "evaluation_policy": "finding-level truth, not document-level label truth",
            }
            finding_records.append(finding_record)

            candidates = group[group["_first_digit"].astype(int).isin(flagged_digits)].copy()
            candidates["_sort_key"] = candidates["document_id"].astype(str) + ":" + candidates.get("line_number", "").astype(str)
            candidates = candidates.sort_values(["_first_digit", "_sort_key"]).head(250)
            for offset, (_, row) in enumerate(candidates.iterrows(), start=1):
                drilldown_records.append(
                    {
                        "candidate_id": f"{finding_id}-ROW-{offset:04d}",
                        "finding_id": finding_id,
                        "fiscal_year": year,
                        "company_code": str(company_code),
                        "gl_account": str(gl_account),
                        "document_id": row.get("document_id", ""),
                        "posting_date": row.get("posting_date", ""),
                        "document_number": row.get("document_number", ""),
                        "document_type": row.get("document_type", ""),
                        "business_process": row.get("business_process", ""),
                        "source": row.get("source", ""),
                        "line_number": row.get("line_number", ""),
                        "amount": round(float(row["_amount"]), 2),
                        "first_digit": int(row["_first_digit"]),
                        "flagged_digits": "|".join(str(digit) for digit in flagged_digits),
                        "truth_basis": "drill-down candidate inside anomalous Benford group",
                        "evaluation_policy": "candidate row for audit review, not standalone confirmed fraud",
                    }
                )
        else:
            normal_records.append(
                common | {
                    "group_id": f"BENFORD-NORMAL-{year}-{len(normal_records) + 1:04d}",
                    "truth_basis": "normal Benford-conforming group",
                    "evaluation_policy": "normal group control for false-finding checks",
                }
            )
    return finding_records, drilldown_records, normal_records, skipped_records


def main() -> None:
    args = parse_args()
    source = Path(args.source)
    output = Path(args.output)
    if output.exists():
        if not args.force:
            raise SystemExit(f"Output exists: {output}")
        shutil.rmtree(output)
    shutil.copytree(source, output)

    labels_dir = output / "labels"
    findings: list[dict] = []
    drilldown: list[dict] = []
    normals: list[dict] = []
    skipped: list[dict] = []
    summary: dict[str, dict[str, int]] = {}
    for year in (2022, 2023, 2024):
        df = load_year(output / f"journal_entries_{year}.csv", year)
        year_findings, year_drilldown, year_normals, year_skipped = build_year_records(df, year)
        findings.extend(year_findings)
        drilldown.extend(year_drilldown)
        normals.extend(year_normals)
        skipped.extend(year_skipped)
        summary[str(year)] = {
            "finding_groups": len(year_findings),
            "drilldown_candidates": len(year_drilldown),
            "normal_groups": len(year_normals),
            "skipped_small_groups": len(year_skipped),
        }

    write_sidecar_family(labels_dir, "benford_finding_truth", findings)
    write_sidecar_family(labels_dir, "benford_drilldown_candidates", drilldown)
    write_sidecar_family(labels_dir, "benford_normal_groups", normals)
    write_sidecar_family(labels_dir, "benford_skipped_small_groups", skipped)

    summary_path = labels_dir / "anomaly_labels_summary.json"
    label_summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    label_summary["v52_benford_group_truth"] = {
        "policy": "Benford truth is group-level; document-level BenfordViolation labels are legacy only.",
        "summary": summary,
        "min_group_size": MIN_GROUP_SIZE,
        "mad_threshold": MAD_THRESHOLD,
    }
    summary_path.write_text(json.dumps(label_summary, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest_path = output / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest.setdefault("candidate_patches", []).append(
        {
            "version": "v52_candidate",
            "source": source.name,
            "purpose": "Add L4-02 Benford group-level truth sidecars without changing document labels.",
            "summary": summary,
            "anti_fitting_policy": [
                "Do not add more document-level BenfordViolation labels.",
                "Evaluate Benford at fiscal_year+company_code+gl_account level.",
                "Keep drill-down candidates separate from confirmed document-level fraud truth.",
                "Keep normal Benford-conforming groups for false-finding checks.",
            ],
        }
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    (output / "FREEZE_V52_CANDIDATE.md").write_text(
        "# DataSynth v52 Candidate\n\n"
        "L4-02 Benford group-level truth patch.\n\n"
        "- Source: `datasynth_v51_candidate`\n"
        "- Adds `labels/benford_finding_truth*` for fiscal_year+company_code+gl_account findings.\n"
        "- Adds `labels/benford_drilldown_candidates*` for candidate rows inside finding groups.\n"
        "- Adds `labels/benford_normal_groups*` for sufficiently large conforming groups.\n"
        "- Adds `labels/benford_skipped_small_groups*` for groups below sample threshold.\n"
        "- Does not add document-level `BenfordViolation` labels.\n\n"
        f"Summary: `{json.dumps(summary, ensure_ascii=False)}`\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
