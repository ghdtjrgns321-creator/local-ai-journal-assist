"""Build v117 candidate with independent L2 scenario/control sidecars.

The L2 rule-truth files are detector-contract snapshots. This patch adds
independent sidecars for behavioral validation without using detector output:

- L2-03 duplicate-entry confirmed scenarios and normal/routine controls
- L2-04 plausible capitalization cases and normal CAPEX controls
- L2-05 reversal-pattern plausible cases and normal clearing controls

No journal rows are modified. Rule-truth membership is unchanged from v116.
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
SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v116_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v117_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
YEAR_SUFFIX_RE = re.compile(r"_20\d{2}$")

KEEP_VERSION_FILES = {"FREEZE_V117_CANDIDATE.md", "V117_L2_INDEPENDENT_SIDECARS.json"}

JOURNAL_COLS = [
    "document_id",
    "company_code",
    "fiscal_year",
    "fiscal_period",
    "posting_date",
    "document_date",
    "document_type",
    "reference",
    "header_text",
    "line_text",
    "source",
    "business_process",
    "created_by",
    "approved_by",
    "user_persona",
    "gl_account",
    "debit_amount",
    "credit_amount",
    "trading_partner",
    "vendor_name",
    "customer_name",
    "auxiliary_account_number",
    "lettrage",
    "amount_open",
    "is_cleared",
    "settlement_status",
    "settlement_date",
]


def _copy_candidate_fast() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        required = [DEST / f"journal_entries_{year}.csv" for year in YEARS]
        required.append(DEST / "V117_L2_INDEPENDENT_SIDECARS.json")
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


def _cleanup_copied_version_files() -> list[str]:
    removed: list[str] = []
    for path in DEST.iterdir():
        if not path.is_file():
            continue
        if path.name in KEEP_VERSION_FILES:
            continue
        if path.name.startswith("FREEZE_V") or re.match(r"^V\d+_", path.name):
            removed.append(path.name)
            path.unlink()
    return sorted(removed)


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _first_non_null(values: pd.Series) -> object:
    clean = values.dropna()
    return None if clean.empty else clean.iloc[0]


def _load_journal() -> pd.DataFrame:
    frames = []
    for year in YEARS:
        path = DEST / f"journal_entries_{year}.csv"
        header = pd.read_csv(path, nrows=0).columns.tolist()
        cols = [column for column in JOURNAL_COLS if column in header]
        frame = pd.read_csv(path, usecols=cols, parse_dates=["posting_date", "document_date"], low_memory=False)
        for column in JOURNAL_COLS:
            if column not in frame.columns:
                frame[column] = pd.NA
        frames.append(frame[JOURNAL_COLS])
    rows = pd.concat(frames, ignore_index=True)
    for column in ("debit_amount", "credit_amount", "amount_open"):
        rows[column] = pd.to_numeric(rows[column], errors="coerce")
    rows["_base_amount"] = rows[["debit_amount", "credit_amount"]].abs().max(axis=1)
    return rows


def _doc_context(rows: pd.DataFrame) -> pd.DataFrame:
    grouped = rows.groupby("document_id", dropna=False).agg(
        fiscal_year=("fiscal_year", _first_non_null),
        company_code=("company_code", _first_non_null),
        posting_date=("posting_date", _first_non_null),
        document_date=("document_date", _first_non_null),
        document_number=("document_id", "size"),
        document_type=("document_type", _first_non_null),
        business_process=("business_process", _first_non_null),
        source=("source", _first_non_null),
        created_by=("created_by", _first_non_null),
        approved_by=("approved_by", _first_non_null),
        user_persona=("user_persona", _first_non_null),
        reference=("reference", _first_non_null),
        trading_partner=("trading_partner", _first_non_null),
        vendor_name=("vendor_name", _first_non_null),
        customer_name=("customer_name", _first_non_null),
        gl_accounts=("gl_account", lambda value: "|".join(sorted({str(v) for v in value.dropna()}))),
        line_count=("document_id", "size"),
        max_line_amount=("_base_amount", "max"),
        total_debit=("debit_amount", "sum"),
        total_credit=("credit_amount", "sum"),
        text_sample=("line_text", _first_non_null),
    )
    grouped = grouped.rename(columns={"document_number": "line_count_duplicate_guard"}).reset_index()
    grouped["fiscal_year"] = pd.to_numeric(grouped["fiscal_year"], errors="coerce").astype("Int64")
    grouped["posting_date"] = grouped["posting_date"].astype(str)
    grouped["document_date"] = grouped["document_date"].astype(str)
    return grouped


def _load_labels() -> pd.DataFrame:
    path = LABELS / "anomaly_labels.csv"
    labels = pd.read_csv(path, low_memory=False)
    labels["document_id"] = labels["document_id"].astype(str)
    return labels


def _label_docs(labels: pd.DataFrame, types: set[str]) -> pd.DataFrame:
    cols = [
        "document_id",
        "anomaly_type",
        "anomaly_category",
        "confidence",
        "severity",
        "description",
        "metadata_json",
    ]
    return labels.loc[labels["anomaly_type"].isin(types), cols].drop_duplicates("document_id")


def _merge_context(docs: pd.DataFrame, context: pd.DataFrame) -> pd.DataFrame:
    out = docs.merge(context, on="document_id", how="inner")
    return out.drop_duplicates("document_id").reset_index(drop=True)


def _add_sidecar_columns(
    df: pd.DataFrame,
    *,
    sidecar_name: str,
    rule_id: str,
    sidecar_role: str,
    expected_detector_behavior: str,
    selection_basis: str,
    scenario_column: str,
) -> pd.DataFrame:
    out = df.copy()
    if scenario_column not in out.columns:
        out[scenario_column] = sidecar_role
    out["sidecar_name"] = sidecar_name
    out["rule_id"] = rule_id
    out["sidecar_role"] = sidecar_role
    out["expected_detector_behavior"] = expected_detector_behavior
    out["selection_basis"] = selection_basis
    out["independence_policy"] = (
        "Selected from anomaly labels and journal business fields only; detector output is not read."
    )
    out["source_candidate"] = "v117"
    out["evaluation_usage"] = (
        "Behavioral validation sidecar. Do not use as the strict Phase1 rule_truth denominator."
    )
    return out


def _sample_by_year(df: pd.DataFrame, n_per_year: int) -> pd.DataFrame:
    parts = []
    for year in YEARS:
        subset = df.loc[pd.to_numeric(df["fiscal_year"], errors="coerce").eq(year)].copy()
        parts.append(subset.sort_values(["company_code", "document_id"]).head(n_per_year))
    return pd.concat(parts, ignore_index=True) if parts else df.iloc[0:0].copy()


def _duplicate_entry_sidecars(rows: pd.DataFrame, context: pd.DataFrame, labels: pd.DataFrame) -> dict[str, pd.DataFrame]:
    confirmed = _merge_context(_label_docs(labels, {"DuplicateEntry", "ExactDuplicateAmount"}), context)
    confirmed["scenario_type"] = confirmed["anomaly_type"].fillna("DuplicateEntry")
    confirmed = _add_sidecar_columns(
        confirmed,
        sidecar_name="duplicate_entry_confirmed_scenarios",
        rule_id="L2-03",
        sidecar_role="independent_confirmed_scenario",
        expected_detector_behavior="should_surface",
        selection_basis="Injected DuplicateEntry/ExactDuplicateAmount labels from anomaly_labels, not detector output.",
        scenario_column="scenario_type",
    )

    anomaly_docs = set(labels["document_id"].astype(str))
    normal = context.loc[
        ~context["document_id"].astype(str).isin(anomaly_docs)
        & context["source"].fillna("").astype(str).str.lower().isin(["automated", "recurring", "interface"])
        & context["reference"].notna()
        & context["max_line_amount"].fillna(0).gt(0)
    ].copy()
    normal["scenario_type"] = "routine_system_or_recurring_duplicate_lookalike"
    controls = _sample_by_year(normal, 30)
    controls = _add_sidecar_columns(
        controls,
        sidecar_name="duplicate_entry_negative_controls",
        rule_id="L2-03",
        sidecar_role="independent_negative_control",
        expected_detector_behavior="may_surface_but_should_score_low",
        selection_basis=(
            "Unlabeled automated/recurring/interface documents with normal references and positive amounts; "
            "chosen as routine duplicate-lookalike controls without reading detector output."
        ),
        scenario_column="scenario_type",
    )
    return {
        "duplicate_entry_confirmed_scenarios": confirmed,
        "duplicate_entry_negative_controls": controls,
    }


def _expense_capitalization_sidecars(rows: pd.DataFrame, context: pd.DataFrame, labels: pd.DataFrame) -> dict[str, pd.DataFrame]:
    plausible = _merge_context(_label_docs(labels, {"ExpenseCapitalization", "ImproperCapitalization"}), context)
    plausible["scenario_type"] = plausible["anomaly_type"].fillna("ImproperCapitalization")
    plausible = _add_sidecar_columns(
        plausible,
        sidecar_name="expense_capitalization_plausible_cases",
        rule_id="L2-04",
        sidecar_role="independent_plausible_case",
        expected_detector_behavior="should_surface_or_score",
        selection_basis="Injected capitalization labels from anomaly_labels, not detector output.",
        scenario_column="scenario_type",
    )

    text = (
        rows["header_text"].fillna("").astype(str)
        + " "
        + rows["line_text"].fillna("").astype(str)
        + " "
        + rows["document_type"].fillna("").astype(str)
    ).str.lower()
    asset_line = rows["gl_account"].fillna("").astype(str).str.startswith(("12", "15")) & rows["debit_amount"].fillna(0).gt(0)
    capex_text = text.str.contains("capex|capital|asset|software|project|fa|construction|개발|구축|자산|설비", regex=True)
    normal_doc_ids = set(rows.loc[asset_line & capex_text, "document_id"].dropna().astype(str))
    anomaly_docs = set(labels["document_id"].astype(str))
    normal = context.loc[
        context["document_id"].astype(str).isin(normal_doc_ids - anomaly_docs)
        & context["document_type"].fillna("").astype(str).str.upper().isin(["AA", "FA", "JE", "SA"])
    ].copy()
    normal["scenario_type"] = "normal_capex_or_asset_acquisition_context"
    controls = _sample_by_year(normal, 30)
    controls = _add_sidecar_columns(
        controls,
        sidecar_name="expense_capitalization_normal_capex_controls",
        rule_id="L2-04",
        sidecar_role="independent_negative_control",
        expected_detector_behavior="may_surface_but_should_score_low_or_review",
        selection_basis=(
            "Unlabeled documents with asset debit lines and normal CAPEX/asset context terms; "
            "selected from journal fields only, not detector output."
        ),
        scenario_column="scenario_type",
    )
    return {
        "expense_capitalization_plausible_cases": plausible,
        "expense_capitalization_normal_capex_controls": controls,
    }


def _reversal_sidecars(rows: pd.DataFrame, context: pd.DataFrame, labels: pd.DataFrame) -> dict[str, pd.DataFrame]:
    plausible = _merge_context(_label_docs(labels, {"ReversedAmount", "ReversalEntry"}), context)
    plausible["scenario_type"] = plausible["anomaly_type"].fillna("ReversedAmount")
    plausible = _add_sidecar_columns(
        plausible,
        sidecar_name="reversal_pattern_plausible_cases",
        rule_id="L2-05",
        sidecar_role="independent_plausible_case",
        expected_detector_behavior="should_surface_or_score",
        selection_basis="Injected ReversedAmount/ReversalEntry labels from anomaly_labels, not detector output.",
        scenario_column="scenario_type",
    )

    anomaly_docs = set(labels["document_id"].astype(str))
    clearing_doc_ids = set(
        rows.loc[
            rows["settlement_status"].fillna("").astype(str).str.lower().eq("cleared")
            | rows["is_cleared"].fillna("").astype(str).str.lower().isin(["true", "1", "yes"]),
            "document_id",
        ].dropna().astype(str)
    )
    normal = context.loc[
        context["document_id"].astype(str).isin(clearing_doc_ids - anomaly_docs)
        & context["source"].fillna("").astype(str).str.lower().isin(["automated", "recurring", "interface"])
    ].copy()
    normal["scenario_type"] = "normal_clearing_or_settlement_context"
    controls = _sample_by_year(normal, 30)
    controls = _add_sidecar_columns(
        controls,
        sidecar_name="reversal_pattern_normal_clearing_controls",
        rule_id="L2-05",
        sidecar_role="independent_negative_control",
        expected_detector_behavior="may_surface_but_should_score_low",
        selection_basis=(
            "Unlabeled cleared/settled automated or recurring documents; selected from settlement fields only, "
            "not detector output."
        ),
        scenario_column="scenario_type",
    )
    return {
        "reversal_pattern_plausible_cases": plausible,
        "reversal_pattern_normal_clearing_controls": controls,
    }


def _write_sidecar(stem: str, df: pd.DataFrame) -> None:
    df = df.sort_values(["fiscal_year", "company_code", "document_id"], na_position="last").reset_index(drop=True)
    df.to_csv(LABELS / f"{stem}.csv", index=False)
    _write_json_records(LABELS / f"{stem}.json", df)
    for year in YEARS:
        year_df = df.loc[pd.to_numeric(df["fiscal_year"], errors="coerce").eq(year)].copy()
        year_df.to_csv(LABELS / f"{stem}_{year}.csv", index=False)
        _write_json_records(LABELS / f"{stem}_{year}.json", year_df)


def _normalize_rule_truth_metadata() -> int:
    count = 0
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        stem = path.stem
        if YEAR_SUFFIX_RE.search(stem):
            continue
        df = pd.read_csv(path, low_memory=False)
        if "source_candidate" in df.columns:
            df = df.drop(columns=["source_candidate"])
        if "truth_contract_version" in df.columns:
            df = df.drop(columns=["truth_contract_version"])
        df["source_candidate"] = "v117"
        df["truth_contract_version"] = "v117_active_candidate_contract"
        df.to_csv(path, index=False)
        _write_json_records(path.with_suffix(".json"), df)
        count += 1
        if "fiscal_year" in df.columns:
            for year in YEARS:
                year_path = LABELS / f"{stem}_{year}.csv"
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
    return {
        str(rule): int(count)
        for rule, count in combined["rule_id"].value_counts().sort_index().to_dict().items()
    }


def _legacy_source_count() -> int:
    count = 0
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        if YEAR_SUFFIX_RE.search(path.stem):
            continue
        df = pd.read_csv(path, usecols=lambda column: column == "source_candidate", low_memory=False)
        values = sorted(df["source_candidate"].dropna().astype(str).unique().tolist())
        if values != ["v117"]:
            count += 1
    return count


def main() -> int:
    _copy_candidate_fast()
    old_manifest_files = _cleanup_copied_version_files()

    rows = _load_journal()
    context = _doc_context(rows)
    labels = _load_labels()

    sidecars: dict[str, pd.DataFrame] = {}
    sidecars.update(_duplicate_entry_sidecars(rows, context, labels))
    sidecars.update(_expense_capitalization_sidecars(rows, context, labels))
    sidecars.update(_reversal_sidecars(rows, context, labels))
    for stem, df in sidecars.items():
        _write_sidecar(stem, df)

    normalized_truth_files = _normalize_rule_truth_metadata()
    rule_counts = _rebuild_combined_rule_truth()
    legacy_source_files = _legacy_source_count()
    if legacy_source_files:
        raise SystemExit(f"legacy rule_truth source metadata remains: {legacy_source_files}")

    summary: dict[str, Any] = {
        "candidate_version": "v117",
        "source_baseline": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "patch_scope": "add independent L2 scenario/control sidecars without detector-output selection",
        "sidecar_counts": {name: int(len(df)) for name, df in sidecars.items()},
        "sidecar_year_counts": {
            name: {
                str(year): int(pd.to_numeric(df["fiscal_year"], errors="coerce").eq(year).sum())
                for year in YEARS
            }
            for name, df in sidecars.items()
        },
        "normalized_rule_truth_files": normalized_truth_files,
        "legacy_rule_truth_source_files": legacy_source_files,
        "removed_copied_version_manifests": old_manifest_files,
        "rule_counts": rule_counts,
        "anti_fitting_note": (
            "Independent sidecars are selected from injected labels or journal business fields. "
            "They do not read detector output and must not replace strict rule_truth."
        ),
    }
    (DEST / "V117_L2_INDEPENDENT_SIDECARS.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V117_CANDIDATE.md").write_text(
        "# DataSynth v117 Candidate\n\n"
        f"Source baseline: `{summary['source_baseline']}`.\n\n"
        "Scope: independent L2 sidecars for behavioral validation. No journal rows changed.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2, default=str)}\n```\n",
        encoding="utf-8",
    )
    _cleanup_copied_version_files()
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
