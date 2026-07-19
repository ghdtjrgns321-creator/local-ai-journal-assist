"""Build v121 candidate by clarifying D01/D02 macro sidecar semantics.

Changes:

- Keep D01/D02 rule-truth membership unchanged.
- Add D01 stable/near-threshold guardrail sidecars.
- Add explicit D01/D02 macro priority and precision-policy metadata.
- Split D02 normal controls into raw-positive normal contexts and guardrail
  negatives via metadata, without changing row labels.
- Refresh sidecar_manifest classifications for D01/D02 sidecars.

No journal rows, anomaly labels, or rule-truth membership are changed.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v120_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v121_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
YEAR_SUFFIX_RE = re.compile(r"_20\d{2}$")
KEEP_VERSION_FILES = {"FREEZE_V121_CANDIDATE.md", "V121_D01_D02_MACRO_SIDECARS.json"}


D01_SIDECARS = {
    "account_activity_variance_truth": ("D01", "confirmed_subset", "scenario_coverage", "true", True),
    "account_activity_variance_normal_controls": ("D01", "normal_context", "realism_control", "true", True),
    "account_activity_variance_review_population": ("D01", "strict_truth_alias", "detector_contract_universe", "true", False),
    "account_activity_variance_stable_controls": ("D01", "normal_context", "realism_control", "false", True),
    "account_activity_variance_near_threshold_controls": ("D01", "boundary_control", "realism_control", "false", True),
    "account_activity_variance_exclusions": ("D01", "contract_manifest", "contract_manifest", "false", False),
    "rule_truth_D01": ("D01", "strict_truth_alias", "detector_contract_universe", "true", False),
}

D02_SIDECARS = {
    "monthly_pattern_shift_confirmed_anomalies": ("D02", "confirmed_subset", "scenario_coverage", "true", True),
    "monthly_pattern_shift_truth": ("D02", "confirmed_subset", "scenario_coverage", "true", True),
    "monthly_pattern_shift_normal_controls": ("D02", "normal_context", "realism_control", "may_be_true", True),
    "monthly_pattern_shift_raw_positive_normal_contexts": ("D02", "normal_context", "realism_control", "true", True),
    "monthly_pattern_shift_guardrail_negative_controls": ("D02", "boundary_control", "realism_control", "false", True),
    "monthly_pattern_shift_review_population": ("D02", "strict_truth_alias", "detector_contract_universe", "true", False),
    "monthly_pattern_shift_exclusions": ("D02", "contract_manifest", "contract_manifest", "false", False),
    "rule_truth_D02": ("D02", "strict_truth_alias", "detector_contract_universe", "true", False),
}


def _copy_candidate_fast() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        required = [DEST / f"journal_entries_{year}.csv" for year in YEARS]
        required.append(DEST / "V121_D01_D02_MACRO_SIDECARS.json")
        if all(path.exists() for path in required):
            return
        raise SystemExit(f"destination exists but is incomplete: {DEST}")

    source_resolved = SOURCE.resolve()
    dest_resolved = DEST.resolve()
    allowed_root = (ROOT / "data" / "journal" / "primary").resolve()
    if allowed_root not in dest_resolved.parents:
        raise SystemExit(f"refusing to write outside DataSynth root: {DEST}")

    for src in SOURCE.rglob("*"):
        rel = src.relative_to(source_resolved)
        dst = dest_resolved / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if rel.parts and rel.parts[0] == "labels":
            shutil.copy2(src, dst)
        else:
            os.link(src, dst)


def _cleanup_version_files() -> dict[str, list[str]]:
    removed_root: list[str] = []
    for path in DEST.iterdir():
        if not path.is_file() or path.name in KEEP_VERSION_FILES:
            continue
        if path.name.startswith("FREEZE_V") or re.match(r"^V\d+_", path.name):
            removed_root.append(path.name)
            path.unlink()
    removed_labels: list[str] = []
    for path in LABELS.glob("V*.json"):
        if re.match(r"^V\d+_.+\.json$", path.name):
            removed_labels.append(path.name)
            path.unlink()
    return {"root": sorted(removed_root), "labels": sorted(removed_labels)}


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_family(stem: str, df: pd.DataFrame) -> None:
    df.to_csv(LABELS / f"{stem}.csv", index=False)
    _write_json_records(LABELS / f"{stem}.json", df)
    if "fiscal_year" not in df.columns:
        return
    for year in YEARS:
        year_df = df.loc[pd.to_numeric(df["fiscal_year"], errors="coerce").eq(year)].copy()
        year_df.to_csv(LABELS / f"{stem}_{year}.csv", index=False)
        _write_json_records(LABELS / f"{stem}_{year}.json", year_df)


def _read(stem: str) -> pd.DataFrame:
    return pd.read_csv(LABELS / f"{stem}.csv", low_memory=False)


def _macro_priority_from_variance(value: Any, confirmed: bool) -> str:
    score = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(score):
        return "review"
    if not confirmed:
        if score >= 1.0:
            return "review_high"
        if score >= 0.5:
            return "review_medium"
        return "guardrail_or_low"
    if score >= 2.0:
        return "high"
    if score >= 1.0:
        return "medium"
    return "low"


def _annotate_macro(
    df: pd.DataFrame,
    *,
    owner_rule: str,
    role: str,
    purpose: str,
    expected: str,
    independent: bool,
    semantics: str,
) -> pd.DataFrame:
    df = df.copy()
    df["owner_rule"] = owner_rule
    df["sidecar_role"] = role
    df["sidecar_purpose"] = purpose
    df["sidecar_semantics"] = semantics
    df["expected_detector_positive"] = expected
    df["allowed_for_independent_sidecar_eval"] = independent
    df["can_overlap_detector_universe"] = expected in {"true", "may_be_true", "null"}
    df["source_candidate"] = "v121"
    df["truth_contract_version"] = "v121_active_candidate_contract"
    return df


def _patch_d01() -> dict[str, Any]:
    stats: dict[str, Any] = {}
    for stem in [
        "account_activity_variance_truth",
        "account_activity_variance_normal_controls",
        "account_activity_variance_review_population",
    ]:
        df = _read(stem)
        confirmed = df.get("is_true_positive_account", pd.Series(False, index=df.index)).fillna(False).astype(bool)
        if "expected_macro_priority_band" not in df.columns:
            df["expected_macro_priority_band"] = [
                _macro_priority_from_variance(value, is_confirmed)
                for value, is_confirmed in zip(df.get("weighted_variance", pd.Series(None, index=df.index)), confirmed, strict=False)
            ]
        df["macro_truth_role"] = confirmed.map({True: "confirmed_account_variance", False: "raw_positive_normal_or_review_context"})
        df["macro_evaluation_unit"] = "fiscal_year+company_code+gl_account"
        owner_rule, role, purpose, expected, independent = D01_SIDECARS[stem]
        df = _annotate_macro(
            df,
            owner_rule=owner_rule,
            role=role,
            purpose=purpose,
            expected=expected,
            independent=independent,
            semantics="D01 account-level analytical-review sidecar; not row-level anomaly truth.",
        )
        _write_family(stem, df)
        stats[stem] = int(len(df))

    review = _read("account_activity_variance_review_population")
    review_keys = set(
        zip(
            pd.to_numeric(review["fiscal_year"], errors="coerce").astype("Int64").astype(str),
            review["company_code"].astype(str),
            review["gl_account"].astype(str),
        )
    )
    stable, near, exclusions = _build_d01_guardrails(review_keys)
    _write_family("account_activity_variance_stable_controls", stable)
    _write_family("account_activity_variance_near_threshold_controls", near)
    _write_family("account_activity_variance_exclusions", exclusions)
    stats["account_activity_variance_stable_controls"] = int(len(stable))
    stats["account_activity_variance_near_threshold_controls"] = int(len(near))
    stats["account_activity_variance_exclusions"] = int(len(exclusions))
    return stats


def _build_d01_guardrails(review_keys: set[tuple[str, str, str]]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    usecols = ["fiscal_year", "company_code", "gl_account", "debit_amount", "credit_amount", "document_id"]
    journal = pd.read_csv(DEST / "journal_entries.csv", usecols=lambda c: c in usecols, low_memory=False)
    journal["fiscal_year"] = pd.to_numeric(journal["fiscal_year"], errors="coerce")
    journal["gl_account"] = journal["gl_account"].astype("string")
    blank = journal.loc[journal["gl_account"].isna() | journal["gl_account"].str.strip().eq("")]
    amount = (
        pd.to_numeric(journal["debit_amount"], errors="coerce").fillna(0).abs()
        + pd.to_numeric(journal["credit_amount"], errors="coerce").fillna(0).abs()
    )
    journal = journal.assign(abs_amount=amount)
    grouped = (
        journal.dropna(subset=["fiscal_year", "company_code", "gl_account"])
        .groupby(["fiscal_year", "company_code", "gl_account"], dropna=False)
        .agg(
            doc_count=("document_id", "nunique"),
            total_amount=("abs_amount", "sum"),
            avg_amount=("abs_amount", "mean"),
        )
        .reset_index()
    )
    grouped["fiscal_year"] = grouped["fiscal_year"].astype(int)
    prior = grouped.rename(
        columns={
            "fiscal_year": "prior_fiscal_year",
            "doc_count": "prior_count",
            "total_amount": "prior_total_amount",
            "avg_amount": "prior_avg_amount",
        }
    )
    current = grouped.rename(
        columns={
            "doc_count": "current_count",
            "total_amount": "current_total_amount",
            "avg_amount": "current_avg_amount",
        }
    )
    current = current.loc[current["fiscal_year"].isin([2023, 2024])].copy()
    current["join_prior_year"] = current["fiscal_year"] - 1
    merged = current.merge(
        prior,
        left_on=["company_code", "gl_account", "join_prior_year"],
        right_on=["company_code", "gl_account", "prior_fiscal_year"],
        how="left",
    )
    merged = merged.loc[merged["prior_count"].fillna(0).gt(0)].copy()
    merged["count_variance"] = (merged["current_count"] - merged["prior_count"]).abs() / merged["prior_count"].clip(lower=1)
    merged["total_amount_variance"] = (
        (merged["current_total_amount"] - merged["prior_total_amount"]).abs()
        / merged["prior_total_amount"].abs().clip(lower=1)
    )
    merged["avg_amount_variance"] = (
        (merged["current_avg_amount"] - merged["prior_avg_amount"]).abs()
        / merged["prior_avg_amount"].abs().clip(lower=1)
    )
    merged["weighted_variance"] = (
        0.4 * merged["count_variance"] + 0.4 * merged["total_amount_variance"] + 0.2 * merged["avg_amount_variance"]
    )
    key = list(zip(merged["fiscal_year"].astype(str), merged["company_code"].astype(str), merged["gl_account"].astype(str), strict=False))
    merged = merged.loc[[item not in review_keys for item in key]].copy()
    merged["case_id"] = [
        f"D01-GUARD-{int(year)}-{idx + 1:05d}" for idx, year in enumerate(merged["fiscal_year"].tolist())
    ]
    common = [
        "case_id",
        "fiscal_year",
        "company_code",
        "gl_account",
        "current_count",
        "prior_count",
        "current_total_amount",
        "prior_total_amount",
        "current_avg_amount",
        "prior_avg_amount",
        "count_variance",
        "total_amount_variance",
        "avg_amount_variance",
        "weighted_variance",
    ]
    stable = merged.loc[merged["weighted_variance"].le(0.2)].sort_values(["fiscal_year", "weighted_variance"]).head(240)[common].copy()
    near = merged.loc[merged["weighted_variance"].between(0.25, 0.5, inclusive="left")].sort_values(
        ["fiscal_year", "weighted_variance"], ascending=[True, False]
    ).head(120)[common].copy()
    for df, role, reason in [
        (stable, "stable_negative_control", "Stable account activity below D01 review threshold."),
        (near, "near_threshold_negative_control", "Near-threshold account activity below D01 review threshold."),
    ]:
        df["expected_d01_flag"] = False
        df["is_true_positive_account"] = False
        df["evaluation_unit"] = "fiscal_year+company_code+gl_account"
        df["normal_reason"] = reason
        df["precision_policy"] = "guardrail_negative_control"
        df["business_event_type"] = role
        df["evaluation_bucket"] = role
        df["expected_macro_priority_band"] = "guardrail_or_low"
        df["macro_truth_role"] = role
        df["account_variance_label"] = "AccountActivityVariance"
        df["variance_threshold"] = 0.5
        df["source_candidate"] = "v121"
    stable = _annotate_macro(
        stable,
        owner_rule="D01",
        role="normal_context",
        purpose="realism_control",
        expected="false",
        independent=True,
        semantics="Stable D01 guardrail group below review threshold.",
    )
    near = _annotate_macro(
        near,
        owner_rule="D01",
        role="boundary_control",
        purpose="realism_control",
        expected="false",
        independent=True,
        semantics="Near-threshold D01 guardrail group below review threshold.",
    )
    exclusions = blank[["document_id", "fiscal_year", "company_code", "gl_account"]].drop_duplicates().copy()
    exclusions["case_id"] = [f"D01-EXCL-BLANK-{idx + 1:05d}" for idx in range(len(exclusions))]
    exclusions["evaluation_unit"] = "row_input_quality"
    exclusions["exclusion_reason"] = "blank_gl_account"
    exclusions["expected_d01_flag"] = False
    exclusions = _annotate_macro(
        exclusions,
        owner_rule="D01",
        role="contract_manifest",
        purpose="contract_manifest",
        expected="false",
        independent=False,
        semantics="D01 exclusion/input-quality context, not D01 account-level truth.",
    )
    return stable, near, exclusions


def _d02_priority(row: pd.Series) -> str:
    if not bool(row.get("expected_d02_flag", False)):
        return "guardrail_or_low"
    if bool(row.get("is_true_positive_account", False)):
        jsd = pd.to_numeric(pd.Series([row.get("jsd")]), errors="coerce").iloc[0]
        if pd.notna(jsd) and jsd >= 0.55:
            return "high"
        return "medium"
    scenario = str(row.get("scenario_type", ""))
    if scenario == "normal_recurring_or_interface_batch":
        return "normal_batch_context"
    if scenario in {"normal_project_or_bonus_expense_concentration", "normal_seasonal_or_quarter_end_revenue"}:
        return "normal_seasonal_or_timing_context"
    return "review_low"


def _patch_d02() -> dict[str, Any]:
    stats: dict[str, Any] = {}
    confirmed = _read("monthly_pattern_shift_confirmed_anomalies")
    confirmed["evaluation_bucket"] = "confirmed_monthly_pattern_shift"
    confirmed["precision_policy"] = "count_as_d02_truth"
    confirmed["business_event_type"] = confirmed.get("scenario_type", "target_anomaly_monthly_shift")
    confirmed["expected_macro_priority_band"] = confirmed.apply(_d02_priority, axis=1)
    confirmed["macro_truth_role"] = "confirmed_monthly_pattern_shift"
    confirmed = _annotate_macro(
        confirmed,
        owner_rule="D02",
        role="confirmed_subset",
        purpose="scenario_coverage",
        expected="true",
        independent=True,
        semantics="D02 confirmed monthly-pattern group truth; not row-level anomaly truth.",
    )
    _write_family("monthly_pattern_shift_confirmed_anomalies", confirmed)
    _write_family("monthly_pattern_shift_truth", confirmed)
    stats["monthly_pattern_shift_confirmed_anomalies"] = int(len(confirmed))

    normal = _read("monthly_pattern_shift_normal_controls")
    expected = normal["expected_d02_flag"].fillna(False).astype(bool)
    normal["evaluation_bucket"] = expected.map({True: "normal_raw_positive_control", False: "guardrail_negative_control"})
    normal["precision_policy"] = expected.map(
        {True: "expected_raw_flag_but_exclude_from_confirmed_truth", False: "guardrail_negative_control"}
    )
    normal["business_event_type"] = normal["scenario_type"].fillna(normal.get("normal_reason", ""))
    normal["expected_macro_priority_band"] = normal.apply(_d02_priority, axis=1)
    normal["macro_truth_role"] = expected.map({True: "normal_raw_positive_context", False: "guardrail_negative_control"})
    normal["normal_classifier_version"] = "v121_batch_interface_system_context"
    normal = _annotate_macro(
        normal,
        owner_rule="D02",
        role="normal_context",
        purpose="realism_control",
        expected="may_be_true",
        independent=True,
        semantics="D02 normal/boundary macro context. Raw-positive normal contexts are not confirmed anomalies.",
    )
    _write_family("monthly_pattern_shift_normal_controls", normal)
    raw_positive = normal.loc[expected].copy()
    guardrail = normal.loc[~expected].copy()
    _write_family("monthly_pattern_shift_raw_positive_normal_contexts", raw_positive)
    _write_family("monthly_pattern_shift_guardrail_negative_controls", guardrail)
    stats["monthly_pattern_shift_normal_controls"] = int(len(normal))
    stats["monthly_pattern_shift_raw_positive_normal_contexts"] = int(len(raw_positive))
    stats["monthly_pattern_shift_guardrail_negative_controls"] = int(len(guardrail))

    review = _read("monthly_pattern_shift_review_population")
    review["evaluation_bucket"] = review["is_true_positive_account"].fillna(False).astype(bool).map(
        {True: "confirmed_monthly_pattern_shift", False: "normal_raw_positive_control"}
    )
    review["precision_policy"] = review["is_true_positive_account"].fillna(False).astype(bool).map(
        {True: "count_as_d02_truth", False: "expected_raw_flag_but_exclude_from_confirmed_truth"}
    )
    review["business_event_type"] = review["scenario_type"].fillna(review.get("normal_reason", ""))
    review["expected_macro_priority_band"] = review.apply(_d02_priority, axis=1)
    review["macro_truth_role"] = review["is_true_positive_account"].fillna(False).astype(bool).map(
        {True: "confirmed_monthly_pattern_shift", False: "normal_raw_positive_context"}
    )
    review = _annotate_macro(
        review,
        owner_rule="D02",
        role="strict_truth_alias",
        purpose="detector_contract_universe",
        expected="true",
        independent=False,
        semantics="D02 macro detector-contract universe; not independent realism sample.",
    )
    _write_family("monthly_pattern_shift_review_population", review)
    stats["monthly_pattern_shift_review_population"] = int(len(review))

    exclusions = _read("monthly_pattern_shift_exclusions")
    exclusions["evaluation_bucket"] = "excluded_from_d02"
    exclusions["precision_policy"] = "excluded_from_d02_denominator"
    exclusions["business_event_type"] = exclusions["exclusion_reason"]
    exclusions["expected_d02_flag"] = False
    exclusions["expected_macro_priority_band"] = "excluded"
    exclusions["macro_truth_role"] = "excluded_from_d02"
    exclusions = _annotate_macro(
        exclusions,
        owner_rule="D02",
        role="contract_manifest",
        purpose="contract_manifest",
        expected="false",
        independent=False,
        semantics="D02 exclusion/input-quality context, not D02 macro truth.",
    )
    _write_family("monthly_pattern_shift_exclusions", exclusions)
    stats["monthly_pattern_shift_exclusions"] = int(len(exclusions))
    return stats


def _normalize_rule_truth_metadata() -> int:
    count = 0
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        if YEAR_SUFFIX_RE.search(path.stem):
            continue
        df = pd.read_csv(path, low_memory=False)
        df = df.drop(columns=[col for col in ["source_candidate", "truth_contract_version"] if col in df.columns])
        df["source_candidate"] = "v121"
        df["truth_contract_version"] = "v121_active_candidate_contract"
        df.to_csv(path, index=False)
        _write_json_records(path.with_suffix(".json"), df)
        count += 1
        if "fiscal_year" in df.columns:
            for year in YEARS:
                year_path = LABELS / f"{path.stem}_{year}.csv"
                if year_path.exists():
                    year_df = df.loc[pd.to_numeric(df["fiscal_year"], errors="coerce").eq(year)].copy()
                    year_df.to_csv(year_path, index=False)
                    _write_json_records(year_path.with_suffix(".json"), year_df)
    return count


def _rebuild_combined_rule_truth() -> dict[str, int]:
    frames = []
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        if YEAR_SUFFIX_RE.search(path.stem):
            continue
        frames.append(pd.read_csv(path, low_memory=False))
    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined.to_csv(LABELS / "rule_truth.csv", index=False)
    _write_json_records(LABELS / "rule_truth.json", combined)
    return {str(rule): int(count) for rule, count in combined["rule_id"].value_counts().sort_index().to_dict().items()}


def _manifest_row(stem: str, values: tuple[str, str, str, str, bool]) -> dict[str, Any]:
    path = LABELS / f"{stem}.csv"
    owner_rule, role, purpose, expected, independent = values
    if path.exists():
        df = pd.read_csv(path, low_memory=False)
        row_count = len(df)
        if {"fiscal_year", "company_code", "gl_account"}.issubset(df.columns):
            document_count = int(df[["fiscal_year", "company_code", "gl_account"]].drop_duplicates().shape[0])
        elif "document_id" in df.columns:
            document_count = int(df["document_id"].dropna().astype(str).nunique())
        else:
            document_count = None
    else:
        row_count = 0
        document_count = None
    return {
        "sidecar_name": stem,
        "path": f"labels/{stem}.csv",
        "exists": path.exists(),
        "row_count": row_count,
        "document_count": document_count,
        "owner_rule": owner_rule,
        "purpose": purpose,
        "expected_detector_positive": expected,
        "allowed_for_independent_sidecar_eval": independent,
        "semantics": f"{owner_rule} macro sidecar classified as {role}; evaluation unit is company/account/year.",
        "reason": "v121 D01/D02 macro sidecar role classification.",
        "source_candidate": "v121",
        "sidecar_role": role,
        "can_overlap_detector_universe": expected in {"true", "may_be_true", "null"},
        "preferred_replacement": "monthly_pattern_shift_truth" if stem == "monthly_pattern_shift_confirmed_anomalies" else "",
        "legacy_sidecar_name": "",
    }


def _update_manifest() -> dict[str, Any]:
    path = LABELS / "sidecar_manifest.csv"
    manifest = pd.read_csv(path, low_memory=False)
    for col in [
        "sidecar_role",
        "can_overlap_detector_universe",
        "preferred_replacement",
        "legacy_sidecar_name",
    ]:
        if col not in manifest.columns:
            manifest[col] = None
    classifications = {**D01_SIDECARS, **D02_SIDECARS}
    for stem, values in classifications.items():
        row = _manifest_row(stem, values)
        mask = manifest["sidecar_name"].astype(str).eq(stem)
        if mask.any():
            for key, value in row.items():
                manifest.loc[mask, key] = value
        else:
            manifest = pd.concat([manifest, pd.DataFrame([row])], ignore_index=True, sort=False)
    manifest["source_candidate"] = "v121"
    manifest.to_csv(path, index=False)
    _write_json_records(LABELS / "sidecar_manifest.json", manifest)
    macro_manifest = manifest.loc[manifest["owner_rule"].astype(str).isin(["D01", "D02"])].copy()
    return {
        "manifest_rows": int(len(manifest)),
        "macro_manifest_rows": int(len(macro_manifest)),
        "macro_role_counts": {str(k): int(v) for k, v in macro_manifest["sidecar_role"].fillna("").value_counts().sort_index().to_dict().items()},
    }


def _legacy_source_count() -> int:
    bad = {}
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        if YEAR_SUFFIX_RE.search(path.stem):
            continue
        df = pd.read_csv(path, usecols=lambda c: c == "source_candidate", low_memory=False)
        values = sorted(df["source_candidate"].dropna().astype(str).unique().tolist())
        if values != ["v121"]:
            bad[path.name] = values
    if bad:
        raise SystemExit(f"legacy rule_truth source metadata remains: {bad}")
    return 0


def main() -> int:
    _copy_candidate_fast()
    removed_before = _cleanup_version_files()
    d01_stats = _patch_d01()
    d02_stats = _patch_d02()
    normalized_truth_files = _normalize_rule_truth_metadata()
    rule_counts = _rebuild_combined_rule_truth()
    manifest_stats = _update_manifest()
    legacy_sources = _legacy_source_count()
    removed_after = _cleanup_version_files()

    summary = {
        "candidate_version": "v121",
        "source_baseline": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "patch_scope": "clarify D01/D02 macro sidecar semantics; no journal rows or rule-truth membership changed",
        "d01": d01_stats,
        "d02": d02_stats,
        "sidecar_manifest": manifest_stats,
        "normalized_rule_truth_files": normalized_truth_files,
        "legacy_rule_truth_source_files": legacy_sources,
        "removed_copied_version_manifests": removed_before,
        "removed_copied_version_manifests_after_write": removed_after,
        "rule_counts": rule_counts,
    }
    (DEST / "V121_D01_D02_MACRO_SIDECARS.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V121_CANDIDATE.md").write_text(
        "# DataSynth v121 Candidate\n\n"
        f"Source baseline: `{summary['source_baseline']}`.\n\n"
        "Scope: D01/D02 macro sidecar semantics cleanup. No journal rows or rule-truth membership changed.\n\n"
        "Key policy: D01/D02 are account/month macro review contracts. Row labels are not changed to satisfy macro truth.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2, default=str)}\n```\n",
        encoding="utf-8",
    )
    _cleanup_version_files()
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
