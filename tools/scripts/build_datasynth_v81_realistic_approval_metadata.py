"""Build v81 candidate with realistic approval metadata coverage.

v80 intentionally used broad Phase 1 rule truth: missing approver/date means a
rule candidate. That exposed that automated/recurring entries had unrealistic
mass approval metadata gaps. v81 keeps the broad rule-truth policy, but patches
unlabeled automated/recurring documents with system approval traces.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v80_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v81_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
YEAR_SUFFIX_RE = re.compile(r"_20\d{2}$")
SYSTEM_APPROVER = "SYSTEM_AUTO_APPROVED"


def _copy_candidate_safely() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists() and (DEST / "journal_entries_2024.csv").exists():
        return
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(SOURCE, DEST, copy_function=shutil.copy2)


def _read_anomaly_doc_ids(anomaly_type: str) -> set[str]:
    path = LABELS / "field_contract_truth.csv"
    if not path.exists():
        path = LABELS / "anomaly_labels.csv"
    labels = pd.read_csv(path, dtype=str, usecols=["document_id", "anomaly_type"])
    return set(
        labels.loc[labels["anomaly_type"].eq(anomaly_type), "document_id"]
        .dropna()
        .astype(str)
    )


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _approval_date_for_docs(df: pd.DataFrame) -> pd.Series:
    posting = pd.to_datetime(df["posting_date"], errors="coerce")
    fallback = pd.to_datetime(df["document_date"], errors="coerce")
    date = posting.fillna(fallback)
    return date.dt.strftime("%Y-%m-%d").fillna("")


def _patch_year(
    year: int,
    skipped_labels: set[str],
    approval_date_labels: set[str],
) -> pd.DataFrame:
    path = DEST / f"journal_entries_{year}.csv"
    df = pd.read_csv(path, dtype=str, low_memory=False)
    docs = df.groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", "first"),
        source=("source", "first"),
        business_process=("business_process", "first"),
        user_persona=("user_persona", "first"),
        approved_by=("approved_by", "first"),
        approval_date=("approval_date", "first"),
        posting_date=("posting_date", "first"),
        document_date=("document_date", "first"),
    )
    doc_id = docs["document_id"].astype(str)
    source = docs["source"].fillna("").astype(str).str.strip().str.lower()
    approved_by = docs["approved_by"].fillna("").astype(str).str.strip()
    approval_date = docs["approval_date"].fillna("").astype(str).str.strip()
    routine = source.isin({"automated", "recurring", "batch", "interface", "system"})
    preserve_skipped = doc_id.isin(skipped_labels)
    preserve_approval_date = doc_id.isin(approval_date_labels)

    fill_approver_docs = set(
        docs.loc[routine & approved_by.eq("") & ~preserve_skipped, "document_id"].astype(str)
    )
    fill_date_docs = set(
        docs.loc[routine & approval_date.eq("") & ~preserve_approval_date, "document_id"].astype(str)
    )
    docs_indexed = docs.set_index("document_id")
    fill_date_values = docs_indexed.loc[list(fill_date_docs)] if fill_date_docs else pd.DataFrame()
    date_by_doc = (
        _approval_date_for_docs(fill_date_values).to_dict()
        if not fill_date_values.empty
        else {}
    )

    patch_docs = sorted(fill_approver_docs | fill_date_docs)
    before_by_doc = docs_indexed[["approved_by", "approval_date", "source", "business_process"]].fillna("")
    df_doc_id = df["document_id"].astype(str)
    if fill_approver_docs:
        df.loc[df_doc_id.isin(fill_approver_docs), "approved_by"] = SYSTEM_APPROVER
    if fill_date_docs:
        date_mask = df_doc_id.isin(fill_date_docs)
        df.loc[date_mask, "approval_date"] = df.loc[date_mask, "document_id"].astype(str).map(date_by_doc).fillna("")
    skipped_mask = df_doc_id.isin(skipped_labels)
    adm_mask = df_doc_id.isin(approval_date_labels)
    if skipped_labels:
        df.loc[skipped_mask, "approved_by"] = ""
    if approval_date_labels:
        df.loc[adm_mask, "approval_date"] = ""
        adm_without_skipped = adm_mask & ~skipped_mask
        missing_approver_for_adm = df.loc[adm_without_skipped, "approved_by"].fillna("").astype(str).str.strip().eq("")
        if missing_approver_for_adm.any():
            adm_indices = df.loc[adm_without_skipped].index[missing_approver_for_adm]
            df.loc[adm_indices, "approved_by"] = SYSTEM_APPROVER

    manifest_rows: list[dict[str, object]] = []
    for target_doc in patch_docs:
        before_approver = str(before_by_doc.at[target_doc, "approved_by"])
        before_date = str(before_by_doc.at[target_doc, "approval_date"])
        patched_fields: list[str] = []
        if target_doc in fill_approver_docs:
            patched_fields.append("approved_by")
        if target_doc in fill_date_docs:
            patched_fields.append("approval_date")
        manifest_rows.append(
            {
                "document_id": target_doc,
                "fiscal_year": year,
                "source": before_by_doc.at[target_doc, "source"],
                "business_process": before_by_doc.at[target_doc, "business_process"],
                "previous_approved_by": before_approver,
                "previous_approval_date": before_date,
                "new_approved_by": SYSTEM_APPROVER if target_doc in fill_approver_docs else before_approver,
                "new_approval_date": date_by_doc.get(target_doc, before_date),
                "patched_fields": ",".join(patched_fields),
                "patch_reason": "routine_document_system_approval_trace",
            }
        )

    df.to_csv(path, index=False)
    return pd.DataFrame(manifest_rows)


def _rewrite_combined_journal() -> None:
    frames = [
        pd.read_csv(DEST / f"journal_entries_{year}.csv", dtype=str, low_memory=False)
        for year in YEARS
    ]
    pd.concat(frames, ignore_index=True).to_csv(DEST / "journal_entries.csv", index=False)


def _read_docs() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    usecols = [
        "document_id",
        "fiscal_year",
        "company_code",
        "document_number",
        "document_type",
        "posting_date",
        "business_process",
        "source",
        "created_by",
        "approved_by",
        "approval_date",
        "user_persona",
    ]
    for year in YEARS:
        df = pd.read_csv(DEST / f"journal_entries_{year}.csv", dtype=str, usecols=usecols, low_memory=False)
        frames.append(df)
    rows = pd.concat(frames, ignore_index=True)
    return rows.groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", "first"),
        company_code=("company_code", "first"),
        document_number=("document_number", "first"),
        document_type=("document_type", "first"),
        posting_date=("posting_date", "first"),
        business_process=("business_process", "first"),
        source=("source", "first"),
        created_by=("created_by", "first"),
        approved_by=("approved_by", "first"),
        approval_date=("approval_date", "first"),
        user_persona=("user_persona", "first"),
    )


def _write_rule_truth(rule_id: str, docs: pd.DataFrame, mask: pd.Series, basis: str) -> pd.DataFrame:
    out = docs.loc[mask].drop(columns=["approved_by", "approval_date", "created_by", "user_persona"]).copy()
    out["rule_id"] = rule_id
    out["expected_hit"] = True
    out["truth_layer"] = "rule_truth"
    out["truth_basis"] = basis
    out["evaluation_unit"] = "document"
    out["truth_derivation"] = "v81 realistic approval metadata patch + broad field contract"
    out["source_candidate"] = "v81"
    stem = f"rule_truth_{rule_id.replace('-', '_')}"
    out.to_csv(LABELS / f"{stem}.csv", index=False)
    _write_json_records(LABELS / f"{stem}.json", out)
    for year in YEARS:
        subset = out.loc[out["fiscal_year"].astype(str).eq(str(year))]
        subset.to_csv(LABELS / f"{stem}_{year}.csv", index=False)
        _write_json_records(LABELS / f"{stem}_{year}.json", subset)
    return out


def _rewrite_approval_sidecars(docs: pd.DataFrame) -> dict[str, int]:
    labels_path = LABELS / "field_contract_truth.csv"
    if not labels_path.exists():
        labels_path = LABELS / "anomaly_labels.csv"
    labels = pd.read_csv(labels_path, dtype=str)
    skipped_label_docs = set(labels.loc[labels["anomaly_type"].eq("SkippedApproval"), "document_id"].astype(str))
    approval_date_label_docs = set(labels.loc[labels["anomaly_type"].eq("ApprovalDateMissing"), "document_id"].astype(str))

    skipped_confirmed = docs.loc[docs["document_id"].astype(str).isin(skipped_label_docs)].copy()
    skipped_controls = docs.loc[
        docs["approved_by"].fillna("").astype(str).str.strip().eq("")
        & ~docs["document_id"].astype(str).isin(skipped_label_docs)
    ].copy()
    adm_cases = docs.loc[docs["document_id"].astype(str).isin(approval_date_label_docs)].copy()
    adm_controls = docs.loc[
        docs["approval_date"].fillna("").astype(str).str.strip().ne("")
        & ~docs["document_id"].astype(str).isin(approval_date_label_docs)
    ].copy()

    sidecars = {
        "skipped_approval_confirmed_anomalies": skipped_confirmed,
        "skipped_approval_normal_controls": skipped_controls,
        "approval_date_missing_cases": adm_cases,
        "approval_date_present_normal_controls": adm_controls,
    }
    counts: dict[str, int] = {}
    for name, frame in sidecars.items():
        frame.to_csv(LABELS / f"{name}.csv", index=False)
        if len(frame) <= 10000:
            _write_json_records(LABELS / f"{name}.json", frame)
        counts[name] = int(len(frame))
        for year in YEARS:
            subset = frame.loc[frame["fiscal_year"].astype(str).eq(str(year))]
            subset.to_csv(LABELS / f"{name}_{year}.csv", index=False)
            if len(subset) <= 10000:
                _write_json_records(LABELS / f"{name}_{year}.json", subset)
    return counts


def _rebuild_rule_truth_combined() -> dict[str, int]:
    frames: list[pd.DataFrame] = []
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        stem = path.stem.removeprefix("rule_truth_")
        if YEAR_SUFFIX_RE.search(stem):
            continue
        frames.append(pd.read_csv(path, dtype=str, low_memory=False))
    combined = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    combined.to_csv(LABELS / "rule_truth.csv", index=False)
    return {str(k): int(v) for k, v in combined["rule_id"].value_counts().sort_index().to_dict().items()}


def main() -> None:
    _copy_candidate_safely()
    skipped_labels = _read_anomaly_doc_ids("SkippedApproval")
    approval_date_labels = _read_anomaly_doc_ids("ApprovalDateMissing")
    manifests = [_patch_year(year, skipped_labels, approval_date_labels) for year in YEARS]
    manifest = pd.concat(manifests, ignore_index=True) if manifests else pd.DataFrame()
    manifest.to_csv(LABELS / "routine_approval_metadata_fill_manifest.csv", index=False)
    _write_json_records(LABELS / "routine_approval_metadata_fill_manifest.json", manifest)
    _rewrite_combined_journal()

    docs = _read_docs()
    missing_approver = docs["approved_by"].fillna("").astype(str).str.strip().eq("")
    missing_date = docs["approval_date"].fillna("").astype(str).str.strip().eq("")
    l107 = _write_rule_truth(
        "L1-07",
        docs,
        missing_approver,
        "approved_by is missing under broad Phase 1 field contract",
    )
    l109 = _write_rule_truth(
        "L1-09",
        docs,
        missing_date,
        "approval_date is missing under broad Phase 1 field contract",
    )
    sidecar_counts = _rewrite_approval_sidecars(docs)
    rule_counts = _rebuild_rule_truth_combined()
    summary = {
        "candidate_version": "v81",
        "source_baseline": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "patch_scope": "fill unlabeled automated/recurring approval metadata gaps with system approval traces",
        "patched_documents": int(manifest["document_id"].nunique()) if not manifest.empty else 0,
        "patched_rows": int(len(manifest)),
        "replaced_rule_counts": {"L1-07": int(len(l107)), "L1-09": int(len(l109))},
        "approval_sidecar_counts": sidecar_counts,
        "all_rule_counts": rule_counts,
        "anti_fitting_note": "Labels were preserved. The patch changes unrealistic routine approval metadata coverage, not detector output.",
    }
    (DEST / "V81_REALISTIC_APPROVAL_METADATA_PATCH.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V81_CANDIDATE.md").write_text(
        "# DataSynth v81 Candidate\n\n"
        f"Source baseline: `{summary['source_baseline']}`.\n\n"
        "Scope: realistic approval metadata coverage for routine automated/recurring documents.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
