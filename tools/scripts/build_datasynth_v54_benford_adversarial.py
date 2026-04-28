from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
from pathlib import Path

import pandas as pd


EXPECTED = {digit: math.log10(1 + 1 / digit) for digit in range(1, 10)}
MAD_THRESHOLD = 0.012
TARGETS = {
    "boundary_groups": {2022: 12, 2023: 12, 2024: 12},
    "small_sample_controls": {2022: 16, 2023: 16, 2024: 16},
    "business_skew_normal_groups": {2022: 10, 2023: 10, 2024: 10},
    "company_specific_normals": {2022: 8, 2023: 8, 2024: 8},
    "weak_fraud_holdout": {2022: 8, 2023: 8, 2024: 8},
    "high_mad_normal_controls": {2022: 6, 2023: 6, 2024: 6},
    "broad_digit_findings": {2022: 6, 2023: 6, 2024: 6},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build v54 Benford adversarial/holdout sidecars.")
    parser.add_argument("--source", required=True, help="Source dataset directory, normally datasynth_v53_candidate")
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


def parse_json_map(value: object) -> dict[int, float]:
    if not isinstance(value, str) or not value.strip():
        return {}
    data = json.loads(value)
    return {int(k): float(v) for k, v in data.items()}


def flagged_count(flagged_digits: object) -> int:
    if not isinstance(flagged_digits, str) or not flagged_digits.strip():
        return 0
    return len([part for part in flagged_digits.split("|") if part.strip()])


def max_digit_share(distribution_json: object) -> float:
    distribution = parse_json_map(distribution_json)
    return max(distribution.values()) if distribution else 0.0


def digit_profile_reason(distribution_json: object) -> str:
    distribution = parse_json_map(distribution_json)
    if not distribution:
        return "unknown"
    top_digit, top_share = max(distribution.items(), key=lambda item: item[1])
    expected_share = EXPECTED.get(top_digit, 0.0)
    if top_digit in {1, 2} and top_share > expected_share:
        return "low_digit_operational_skew"
    if top_digit in {8, 9}:
        return "high_digit_price_band_or_threshold_skew"
    if top_digit in {5, 6, 7}:
        return "mid_digit_contract_value_skew"
    return "digit_mix_variance"


def load_groups(labels_dir: Path) -> pd.DataFrame:
    findings = pd.read_csv(labels_dir / "benford_finding_truth.csv", dtype=str, keep_default_na=False)
    normals = pd.read_csv(labels_dir / "benford_normal_groups.csv", dtype=str, keep_default_na=False)
    skipped = pd.read_csv(labels_dir / "benford_skipped_small_groups.csv", dtype=str, keep_default_na=False)
    findings["source_sidecar"] = "benford_finding_truth"
    normals["source_sidecar"] = "benford_normal_groups"
    skipped["source_sidecar"] = "benford_skipped_small_groups"
    for df in (findings, normals, skipped):
        df["fiscal_year"] = pd.to_numeric(df["fiscal_year"], errors="coerce").astype("Int64")
        df["sample_size"] = pd.to_numeric(df["sample_size"], errors="coerce")
        mad_col = df["mad"] if "mad" in df.columns else pd.Series(0.0, index=df.index)
        flagged_col = df["flagged_digits"] if "flagged_digits" in df.columns else pd.Series("", index=df.index)
        observed_col = (
            df["observed_distribution_json"]
            if "observed_distribution_json" in df.columns
            else pd.Series("", index=df.index)
        )
        df["mad"] = pd.to_numeric(mad_col, errors="coerce").fillna(0.0)
        df["flagged_digit_count"] = flagged_col.map(flagged_count)
        df["max_digit_share"] = observed_col.map(max_digit_share)
        df["digit_profile_reason"] = observed_col.map(digit_profile_reason)
        df["group_key"] = (
            df["fiscal_year"].astype(str)
            + "|"
            + df["company_code"].astype(str)
            + "|"
            + df["gl_account"].astype(str)
        )
    return pd.concat([findings, normals, skipped], ignore_index=True, sort=False)


def base_record(row: pd.Series, dataset: str, case_id: str, truth_class: str, evaluation_policy: str) -> dict:
    return {
        "case_id": case_id,
        "dataset": dataset,
        "fiscal_year": int(row["fiscal_year"]),
        "company_code": row.get("company_code", ""),
        "gl_account": row.get("gl_account", ""),
        "sample_size": int(row["sample_size"]) if pd.notna(row["sample_size"]) else 0,
        "mad": round(float(row.get("mad", 0.0)), 6),
        "flagged_digits": row.get("flagged_digits", ""),
        "flagged_digit_count": int(row.get("flagged_digit_count", 0)),
        "max_digit_share": round(float(row.get("max_digit_share", 0.0)), 6),
        "digit_profile_reason": row.get("digit_profile_reason", ""),
        "source_sidecar": row.get("source_sidecar", ""),
        "truth_class": truth_class,
        "evaluation_policy": evaluation_policy,
    }


def choose(pool: pd.DataFrame, year: int, dataset: str, count: int, used: set[str], sort_cols: list[str]) -> pd.DataFrame:
    eligible = pool[pool["fiscal_year"].eq(year) & ~pool["group_key"].isin(used)].copy()
    if eligible.empty or count <= 0:
        return eligible.head(0)
    eligible["_sort_key"] = eligible["group_key"].map(lambda value: f"{dataset}:{value}")
    picked = eligible.sort_values(sort_cols + ["_sort_key"], ascending=[False] * len(sort_cols) + [True]).head(count)
    used.update(picked["group_key"].astype(str))
    return picked.drop(columns=["_sort_key"])


def build_adversarial(groups: pd.DataFrame) -> dict[str, list[dict]]:
    used: set[str] = set()
    outputs: dict[str, list[dict]] = {name: [] for name in TARGETS}

    pools = {
        "boundary_groups": groups[
            groups["sample_size"].ge(500)
            & groups["mad"].between(0.011, 0.013, inclusive="both")
        ].assign(priority=lambda df: -(df["mad"] - MAD_THRESHOLD).abs()),
        "small_sample_controls": groups[
            groups["sample_size"].between(450, 550, inclusive="both")
        ].assign(priority=lambda df: -(df["sample_size"] - 500).abs()),
        "business_skew_normal_groups": groups[
            groups["source_sidecar"].eq("benford_normal_groups")
            & groups["max_digit_share"].ge(0.20)
        ].assign(priority=lambda df: df["max_digit_share"]),
        "company_specific_normals": groups[
            groups["source_sidecar"].eq("benford_normal_groups")
        ].assign(priority=lambda df: df["sample_size"]),
        "weak_fraud_holdout": groups[
            groups["source_sidecar"].eq("benford_finding_truth")
            & groups["mad"].between(0.012, 0.016, inclusive="both")
            & groups["flagged_digit_count"].le(3)
        ].assign(priority=lambda df: -df["mad"]),
        "high_mad_normal_controls": groups[
            groups["source_sidecar"].eq("benford_finding_truth")
            & groups["mad"].gt(0.016)
        ].assign(priority=lambda df: df["mad"]),
        "broad_digit_findings": groups[
            groups["source_sidecar"].eq("benford_finding_truth")
            & groups["flagged_digit_count"].ge(4)
        ].assign(priority=lambda df: df["flagged_digit_count"] + df["mad"]),
    }

    policy = {
        "boundary_groups": ("boundary", "near-threshold MAD group; should not be overfit to strict pass/fail"),
        "small_sample_controls": ("sample_boundary", "sample-size boundary group; check minimum sample behavior"),
        "business_skew_normal_groups": ("normal_business_skew", "normal operational digit skew control"),
        "company_specific_normals": ("normal_company_specific", "same GL can behave differently by company"),
        "weak_fraud_holdout": ("weak_holdout", "weak Benford anomaly holdout, not selected from document labels"),
        "high_mad_normal_controls": ("normal_high_mad_explanation_required", "high MAD but potential normal explanation control"),
        "broad_digit_findings": ("broad_digit_anomaly", "many flagged digits; drill-down may be noisy"),
    }

    for dataset, yearly_targets in TARGETS.items():
        pool = pools[dataset]
        truth_class, evaluation_policy = policy[dataset]
        for year, target in yearly_targets.items():
            picked = choose(pool, year, dataset, target, used, ["priority"])
            if len(picked) < target and dataset in {"business_skew_normal_groups", "company_specific_normals"}:
                fallback = groups[
                    groups["fiscal_year"].eq(year)
                    & groups["source_sidecar"].eq("benford_normal_groups")
                    & ~groups["group_key"].isin(used)
                ].assign(priority=lambda df: df["sample_size"])
                extra = choose(fallback, year, dataset, target - len(picked), used, ["priority"])
                picked = pd.concat([picked, extra], ignore_index=False)
            for idx, (_, row) in enumerate(picked.iterrows(), start=1):
                outputs[dataset].append(
                    base_record(
                        row,
                        dataset,
                        f"B54-{dataset.upper()}-{year}-{idx:04d}",
                        truth_class,
                        evaluation_policy,
                    )
                )
    return outputs


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
    groups = load_groups(labels_dir)
    outputs = build_adversarial(groups)
    for dataset, records in outputs.items():
        write_sidecar_family(labels_dir, f"benford_{dataset}", records)

    combined = [record for records in outputs.values() for record in records]
    write_sidecar_family(labels_dir, "benford_adversarial_holdout", combined)

    summary = {
        dataset: {
            "total": len(records),
            "by_year": {
                str(year): sum(int(record["fiscal_year"]) == year for record in records)
                for year in (2022, 2023, 2024)
            },
        }
        for dataset, records in outputs.items()
    }

    summary_path = labels_dir / "anomaly_labels_summary.json"
    label_summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    label_summary["v54_benford_adversarial_holdout"] = {
        "policy": "Adversarial/holdout sidecars for Benford; not used as contract truth.",
        "summary": summary,
    }
    summary_path.write_text(json.dumps(label_summary, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest_path = output / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest.setdefault("candidate_patches", []).append(
        {
            "version": "v54_candidate",
            "source": source.name,
            "purpose": "Add Benford adversarial/holdout benchmark sidecars.",
            "summary": summary,
            "anti_fitting_policy": [
                "Do not change Benford contract truth.",
                "Add near-threshold, sample-boundary, normal skew, weak holdout, and broad-digit cases.",
                "Use these sidecars to assess robustness, not to force 100% contract recall.",
            ],
        }
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    (output / "FREEZE_V54_CANDIDATE.md").write_text(
        "# DataSynth v54 Candidate\n\n"
        "Benford adversarial/holdout benchmark patch.\n\n"
        "- Source: `datasynth_v53_candidate`\n"
        "- Keeps v52 group-level Benford contract truth unchanged.\n"
        "- Adds boundary, sample-size, business-skew, company-specific, weak-holdout, high-MAD-normal, and broad-digit sidecars.\n"
        "- Intended for robustness evaluation, not strict contract pass/fail.\n\n"
        f"Summary: `{json.dumps(summary, ensure_ascii=False)}`\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
