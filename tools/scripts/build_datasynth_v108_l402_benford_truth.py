"""Build v108 candidate by realigning L4-02 Benford group truth.

Base: datasynth_v107_candidate.

This patch does not mutate journal rows. It rebuilds Benford group-level truth
from the current journal using the detector contract:

- evaluation unit: fiscal_year + company_code + gl_account
- minimum sample size: n >= 500
- finding threshold: MAD > 0.012

Document-level BenfordViolation labels remain legacy/injection labels and are
not used as strict L4-02 truth.
"""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v107_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v108_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
MIN_GROUP_SIZE = 500
MAD_THRESHOLD = 0.012
STRONG_MAD = 0.015
DRILLDOWN_LIMIT = 250
EXPECTED = {digit: math.log10(1 + 1 / digit) for digit in range(1, 10)}


def _copy_candidate_safely() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(SOURCE, DEST, copy_function=shutil.copy2)


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_family(stem: str, df: pd.DataFrame) -> None:
    df.to_csv(LABELS / f"{stem}.csv", index=False, encoding="utf-8")
    _write_json_records(LABELS / f"{stem}.json", df)
    if "fiscal_year" not in df.columns:
        return
    for year in YEARS:
        year_df = df.loc[df["fiscal_year"].astype(str).str.replace(r"\.0$", "", regex=True).eq(str(year))].copy()
        year_df.to_csv(LABELS / f"{stem}_{year}.csv", index=False, encoding="utf-8")
        _write_json_records(LABELS / f"{stem}_{year}.json", year_df)


def _account_code(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().str.replace(r"\.0+$", "", regex=True)


def _first_digit_from_amount(series: pd.Series) -> pd.Series:
    amount = pd.to_numeric(series, errors="coerce").abs()
    text = amount.fillna(0).map(lambda value: f"{value:.12g}")
    digit = text.str.extract(r"([1-9])", expand=False)
    return pd.to_numeric(digit, errors="coerce").astype("Int64")


def _read_year(year: int) -> pd.DataFrame:
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
    path = DEST / f"journal_entries_{year}.csv"
    header = pd.read_csv(path, nrows=0).columns
    cols = [col for col in usecols if col in header]
    df = pd.read_csv(path, dtype=str, usecols=cols, low_memory=False)
    df["fiscal_year"] = year
    debit = pd.to_numeric(df.get("debit_amount", 0), errors="coerce").fillna(0.0).abs()
    credit = pd.to_numeric(df.get("credit_amount", 0), errors="coerce").fillna(0.0).abs()
    df["_amount"] = pd.concat([debit, credit], axis=1).max(axis=1)
    df["_first_digit"] = _first_digit_from_amount(df["_amount"])
    df["_account_code"] = _account_code(df.get("gl_account", pd.Series(dtype=object)))
    df = df[df["_amount"] > 0].copy()
    df = df[df["_first_digit"].notna()].copy()
    df = df[df["_account_code"].ne("")].copy()
    return df


def _distribution_metrics(digits: pd.Series) -> tuple[float, dict[int, float], list[int], dict[int, float]]:
    counts = digits.astype(int).value_counts().reindex(range(1, 10), fill_value=0)
    total = int(counts.sum())
    observed = {int(d): float(counts.loc[d] / total) for d in range(1, 10)}
    deviations = {digit: observed[digit] - EXPECTED[digit] for digit in range(1, 10)}
    mad = sum(abs(deviations[digit]) for digit in range(1, 10)) / 9
    flagged_digits = [digit for digit in range(1, 10) if abs(deviations[digit]) > MAD_THRESHOLD]
    return mad, observed, flagged_digits, deviations


def _build_year_records(df: pd.DataFrame, year: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    findings: list[dict] = []
    drilldown: list[dict] = []
    normals: list[dict] = []
    skipped: list[dict] = []

    groups = df.groupby(["company_code", "_account_code"], dropna=False)
    for group_idx, ((company_code, gl_account), group) in enumerate(groups, start=1):
        sample_size = int(len(group))
        if sample_size < MIN_GROUP_SIZE:
            skipped.append(
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

        mad, observed, flagged_digits, deviations = _distribution_metrics(group["_first_digit"])
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
            finding_id = f"BENFORD-FIND-{year}-{len(findings) + 1:04d}"
            findings.append(
                common
                | {
                    "finding_id": finding_id,
                    "finding_severity": severity,
                    "truth_basis": "group-level Benford distribution anomaly",
                    "evaluation_policy": "finding-level truth, not document-level label truth",
                }
            )

            candidates = group[group["_first_digit"].astype(int).isin(flagged_digits)].copy()
            candidates["_sort_key"] = (
                candidates["document_id"].fillna("").astype(str)
                + ":"
                + candidates.get("line_number", "").fillna("").astype(str)
            )
            candidates = candidates.sort_values(["_first_digit", "_sort_key"]).head(DRILLDOWN_LIMIT)
            for offset, (_, row) in enumerate(candidates.iterrows(), start=1):
                drilldown.append(
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
            normals.append(
                common
                | {
                    "group_id": f"BENFORD-NORMAL-{year}-{len(normals) + 1:04d}",
                    "truth_basis": "normal Benford-conforming group",
                    "evaluation_policy": "normal group control for false-finding checks",
                }
            )

    return pd.DataFrame(findings), pd.DataFrame(drilldown), pd.DataFrame(normals), pd.DataFrame(skipped)


def _rule_truth_from_findings(findings: pd.DataFrame) -> pd.DataFrame:
    if findings.empty:
        return pd.DataFrame(
            columns=[
                "fiscal_year",
                "company_code",
                "gl_account",
                "finding_id",
                "rule_id",
                "expected_hit",
                "truth_layer",
                "truth_basis",
                "evaluation_unit",
            ]
        )
    out = findings[["fiscal_year", "company_code", "gl_account", "finding_id"]].copy()
    out["rule_id"] = "L4-02"
    out["expected_hit"] = True
    out["truth_layer"] = "rule_truth"
    out["truth_basis"] = "group-level Benford distribution anomaly"
    out["evaluation_unit"] = "fiscal_year+company_code+gl_account"
    return out.sort_values(["fiscal_year", "company_code", "gl_account"]).reset_index(drop=True)


def _parse_json_map(value: object) -> dict[int, float]:
    if not isinstance(value, str) or not value.strip():
        return {}
    data = json.loads(value)
    return {int(k): float(v) for k, v in data.items()}


def _flagged_count(value: object) -> int:
    if not isinstance(value, str) or not value.strip():
        return 0
    return len([part for part in value.split("|") if part.strip()])


def _max_digit_share(value: object) -> float:
    distribution = _parse_json_map(value)
    return max(distribution.values()) if distribution else 0.0


def _digit_profile_reason(value: object) -> str:
    distribution = _parse_json_map(value)
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


def _group_pool(findings: pd.DataFrame, normals: pd.DataFrame, skipped: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for name, df in [
        ("benford_finding_truth", findings),
        ("benford_normal_groups", normals),
        ("benford_skipped_small_groups", skipped),
    ]:
        if df.empty:
            continue
        work = df.copy()
        work["source_sidecar"] = name
        frames.append(work)
    groups = pd.concat(frames, ignore_index=True, sort=False)
    for col in ("mad", "sample_size"):
        groups[col] = pd.to_numeric(groups.get(col), errors="coerce").fillna(0.0)
    groups["fiscal_year"] = pd.to_numeric(groups["fiscal_year"], errors="coerce").astype("Int64")
    groups["flagged_digit_count"] = groups.get("flagged_digits", pd.Series("", index=groups.index)).map(_flagged_count)
    groups["max_digit_share"] = groups.get("observed_distribution_json", pd.Series("", index=groups.index)).map(
        _max_digit_share
    )
    groups["digit_profile_reason"] = groups.get("observed_distribution_json", pd.Series("", index=groups.index)).map(
        _digit_profile_reason
    )
    groups["group_key"] = (
        groups["fiscal_year"].astype(str)
        + "|"
        + groups["company_code"].astype(str)
        + "|"
        + groups["gl_account"].astype(str)
    )
    return groups


def _base_holdout_record(row: pd.Series, dataset: str, case_id: str, truth_class: str, policy: str) -> dict:
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
        "evaluation_policy": policy,
    }


def _choose(pool: pd.DataFrame, year: int, dataset: str, count: int, used: set[str], sort_cols: list[str]) -> pd.DataFrame:
    eligible = pool[pool["fiscal_year"].eq(year) & ~pool["group_key"].isin(used)].copy()
    if eligible.empty or count <= 0:
        return eligible.head(0)
    eligible["_sort_key"] = eligible["group_key"].map(lambda value: f"{dataset}:{value}")
    picked = eligible.sort_values(sort_cols + ["_sort_key"], ascending=[False] * len(sort_cols) + [True]).head(count)
    used.update(picked["group_key"].astype(str))
    return picked.drop(columns=["_sort_key"])


def _build_holdout_sidecars(groups: pd.DataFrame) -> dict[str, pd.DataFrame]:
    targets = {
        "benford_boundary_groups": {year: 12 for year in YEARS},
        "benford_small_sample_controls": {year: 16 for year in YEARS},
        "benford_business_skew_normal_groups": {year: 10 for year in YEARS},
        "benford_company_specific_normals": {year: 8 for year in YEARS},
        "benford_weak_fraud_holdout": {year: 8 for year in YEARS},
        "benford_high_mad_normal_controls": {year: 6 for year in YEARS},
        "benford_broad_digit_findings": {year: 6 for year in YEARS},
    }
    pools = {
        "benford_boundary_groups": groups[
            groups["sample_size"].ge(MIN_GROUP_SIZE)
            & groups["mad"].between(0.011, 0.013, inclusive="both")
        ].assign(priority=lambda df: -(df["mad"] - MAD_THRESHOLD).abs()),
        "benford_small_sample_controls": groups[
            groups["sample_size"].between(450, 550, inclusive="both")
        ].assign(priority=lambda df: -(df["sample_size"] - MIN_GROUP_SIZE).abs()),
        "benford_business_skew_normal_groups": groups[
            groups["source_sidecar"].eq("benford_normal_groups") & groups["max_digit_share"].ge(0.20)
        ].assign(priority=lambda df: df["max_digit_share"]),
        "benford_company_specific_normals": groups[
            groups["source_sidecar"].eq("benford_normal_groups")
        ].assign(priority=lambda df: df["sample_size"]),
        "benford_weak_fraud_holdout": groups[
            groups["source_sidecar"].eq("benford_finding_truth")
            & groups["mad"].between(0.012, 0.016, inclusive="both")
            & groups["flagged_digit_count"].le(3)
        ].assign(priority=lambda df: -df["mad"]),
        "benford_high_mad_normal_controls": groups[
            groups["source_sidecar"].eq("benford_finding_truth") & groups["mad"].gt(0.016)
        ].assign(priority=lambda df: df["mad"]),
        "benford_broad_digit_findings": groups[
            groups["source_sidecar"].eq("benford_finding_truth") & groups["flagged_digit_count"].ge(4)
        ].assign(priority=lambda df: df["flagged_digit_count"] + df["mad"]),
    }
    policy = {
        "benford_boundary_groups": ("boundary", "near-threshold MAD group; should not be overfit to strict pass/fail"),
        "benford_small_sample_controls": ("sample_boundary", "sample-size boundary group; check minimum sample behavior"),
        "benford_business_skew_normal_groups": ("normal_business_skew", "normal operational digit skew control"),
        "benford_company_specific_normals": ("normal_company_specific", "same GL can behave differently by company"),
        "benford_weak_fraud_holdout": ("weak_holdout", "weak Benford anomaly holdout, not selected from document labels"),
        "benford_high_mad_normal_controls": (
            "normal_high_mad_explanation_required",
            "high MAD but potential normal explanation control",
        ),
        "benford_broad_digit_findings": ("broad_digit_anomaly", "many flagged digits; drill-down may be noisy"),
    }

    used: set[str] = set()
    outputs: dict[str, list[dict]] = {name: [] for name in targets}
    for dataset, yearly_targets in targets.items():
        pool = pools[dataset]
        truth_class, evaluation_policy = policy[dataset]
        for year, target in yearly_targets.items():
            picked = _choose(pool, year, dataset, target, used, ["priority"])
            if len(picked) < target and dataset in {
                "benford_business_skew_normal_groups",
                "benford_company_specific_normals",
            }:
                fallback = groups[
                    groups["fiscal_year"].eq(year)
                    & groups["source_sidecar"].eq("benford_normal_groups")
                    & ~groups["group_key"].isin(used)
                ].assign(priority=lambda df: df["sample_size"])
                extra = _choose(fallback, year, dataset, target - len(picked), used, ["priority"])
                picked = pd.concat([picked, extra], ignore_index=False)
            for idx, (_, row) in enumerate(picked.iterrows(), start=1):
                outputs[dataset].append(
                    _base_holdout_record(
                        row,
                        dataset,
                        f"B108-{dataset.upper()}-{year}-{idx:04d}",
                        truth_class,
                        evaluation_policy,
                    )
                )

    out_frames = {name: pd.DataFrame(records) for name, records in outputs.items()}
    combined = pd.concat(out_frames.values(), ignore_index=True, sort=False)
    out_frames["benford_adversarial_holdout"] = combined
    return out_frames


def _rebuild_rule_truth_combined() -> pd.DataFrame:
    frames = []
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        if path.stem.rsplit("_", 1)[-1] in {"2022", "2023", "2024"}:
            continue
        frames.append(pd.read_csv(path, dtype=str, low_memory=False))
    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined.to_csv(LABELS / "rule_truth.csv", index=False, encoding="utf-8")
    _write_json_records(LABELS / "rule_truth.json", combined)
    return combined


def main() -> None:
    _copy_candidate_safely()
    old_truth = pd.read_csv(LABELS / "rule_truth_L4_02.csv", dtype=str, low_memory=False)

    finding_frames = []
    drilldown_frames = []
    normal_frames = []
    skipped_frames = []
    yearly_summary: dict[str, dict[str, int]] = {}
    for year in YEARS:
        rows = _read_year(year)
        findings, drilldown, normals, skipped = _build_year_records(rows, year)
        finding_frames.append(findings)
        drilldown_frames.append(drilldown)
        normal_frames.append(normals)
        skipped_frames.append(skipped)
        yearly_summary[str(year)] = {
            "finding_groups": int(len(findings)),
            "drilldown_candidates": int(len(drilldown)),
            "normal_groups": int(len(normals)),
            "skipped_small_groups": int(len(skipped)),
        }

    findings_all = pd.concat(finding_frames, ignore_index=True, sort=False)
    drilldown_all = pd.concat(drilldown_frames, ignore_index=True, sort=False)
    normals_all = pd.concat(normal_frames, ignore_index=True, sort=False)
    skipped_all = pd.concat(skipped_frames, ignore_index=True, sort=False)
    rule_truth = _rule_truth_from_findings(findings_all)

    _write_family("benford_finding_truth", findings_all)
    _write_family("benford_drilldown_candidates", drilldown_all)
    _write_family("benford_normal_groups", normals_all)
    _write_family("benford_skipped_small_groups", skipped_all)
    _write_family("rule_truth_L4_02", rule_truth)

    groups = _group_pool(findings_all, normals_all, skipped_all)
    holdouts = _build_holdout_sidecars(groups)
    for stem, df in holdouts.items():
        _write_family(stem, df)

    combined = _rebuild_rule_truth_combined()

    old_keys = set(zip(old_truth["fiscal_year"].astype(str), old_truth["company_code"].astype(str), old_truth["gl_account"].astype(str)))
    new_keys = set(zip(rule_truth["fiscal_year"].astype(str), rule_truth["company_code"].astype(str), rule_truth["gl_account"].astype(str)))
    summary = {
        "version": "v108_candidate",
        "base_version": "v107_candidate",
        "journal_rows_mutated": 0,
        "rule_truth_rebuilt": ["L4-02"],
        "evaluation_unit": "fiscal_year+company_code+gl_account",
        "min_group_size": MIN_GROUP_SIZE,
        "mad_threshold": MAD_THRESHOLD,
        "old_l402_truth_groups": int(len(old_keys)),
        "new_l402_truth_groups": int(len(new_keys)),
        "added_truth_groups": sorted("|".join(key) for key in new_keys - old_keys),
        "removed_truth_groups": sorted("|".join(key) for key in old_keys - new_keys),
        "yearly_summary": yearly_summary,
        "drilldown_candidates": int(len(drilldown_all)),
        "normal_groups": int(len(normals_all)),
        "skipped_small_groups": int(len(skipped_all)),
        "holdout_counts": {stem: int(len(df)) for stem, df in holdouts.items()},
        "combined_rule_truth_counts": {
            str(rule): int(count)
            for rule, count in combined["rule_id"].value_counts().sort_index().to_dict().items()
        },
    }
    (DEST / "V108_L402_BENFORD_TRUTH.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V108_CANDIDATE.md").write_text(
        "# DataSynth v108 Candidate\n\n"
        f"Source baseline: `{SOURCE.relative_to(ROOT).as_posix()}`.\n\n"
        "Scope: rebuild L4-02 Benford group-level truth from current journal.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
