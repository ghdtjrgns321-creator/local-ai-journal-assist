"""Build v83 candidate by fixing L1-05 self-approval journal/sidecar drift."""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v82_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v83_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
YEAR_SUFFIX_RE = re.compile(r"_20\d{2}$")


def _copy_candidate_safely() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(SOURCE, DEST, copy_function=shutil.copy2)


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_system_self_approval_controls() -> pd.DataFrame:
    path = LABELS / "system_self_approval_controls.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str)


def _patch_year(year: int, controls: pd.DataFrame) -> pd.DataFrame:
    year_controls = controls.loc[controls["fiscal_year"].astype(str).eq(str(year))].copy()
    if year_controls.empty:
        return pd.DataFrame()
    path = DEST / f"journal_entries_{year}.csv"
    df = pd.read_csv(path, dtype=str, low_memory=False)
    df_doc_id = df["document_id"].astype(str)
    patches: list[dict[str, object]] = []
    for row in year_controls.to_dict(orient="records"):
        doc_id = str(row["document_id"])
        expected = str(row.get("approved_by") or row.get("new_created_by") or "").strip()
        if not expected:
            continue
        mask = df_doc_id.eq(doc_id)
        if not mask.any():
            continue
        before_created = str(df.loc[mask, "created_by"].iloc[0])
        before_approved = str(df.loc[mask, "approved_by"].iloc[0])
        before_date = str(df.loc[mask, "approval_date"].iloc[0])
        created = str(df.loc[mask, "created_by"].iloc[0]).strip()
        approved = str(df.loc[mask, "approved_by"].iloc[0]).strip()
        if created != approved:
            df.loc[mask, "created_by"] = expected
            df.loc[mask, "approved_by"] = expected
            if df.loc[mask, "approval_date"].fillna("").astype(str).str.strip().eq("").all():
                posting = pd.to_datetime(df.loc[mask, "posting_date"].iloc[0], errors="coerce")
                if pd.notna(posting):
                    df.loc[mask, "approval_date"] = posting.strftime("%Y-%m-%d")
            patches.append(
                {
                    "document_id": doc_id,
                    "fiscal_year": year,
                    "document_number": df.loc[mask, "document_number"].iloc[0],
                    "source": df.loc[mask, "source"].iloc[0],
                    "previous_created_by": before_created,
                    "previous_approved_by": before_approved,
                    "previous_approval_date": before_date,
                    "new_created_by": expected,
                    "new_approved_by": expected,
                    "new_approval_date": df.loc[mask, "approval_date"].iloc[0],
                    "patch_reason": "restore_system_self_approval_control_consistency",
                }
            )
    df.to_csv(path, index=False)
    return pd.DataFrame(patches)


def _rewrite_combined_journal() -> None:
    frames = [
        pd.read_csv(DEST / f"journal_entries_{year}.csv", dtype=str, low_memory=False)
        for year in YEARS
    ]
    pd.concat(frames, ignore_index=True).to_csv(DEST / "journal_entries.csv", index=False)


def _read_docs() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    cols = [
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
        frames.append(pd.read_csv(DEST / f"journal_entries_{year}.csv", dtype=str, usecols=cols, low_memory=False))
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
    out["truth_derivation"] = "v83 self-approval consistency fix + field contract"
    out["source_candidate"] = "v83"
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
    labels = pd.read_csv(labels_path, dtype=str)
    skipped_docs = set(labels.loc[labels["anomaly_type"].eq("SkippedApproval"), "document_id"].astype(str))
    adm_docs = set(labels.loc[labels["anomaly_type"].eq("ApprovalDateMissing"), "document_id"].astype(str))
    sidecars = {
        "skipped_approval_confirmed_anomalies": docs.loc[docs["document_id"].astype(str).isin(skipped_docs)].copy(),
        "skipped_approval_normal_controls": docs.loc[
            docs["approved_by"].fillna("").astype(str).str.strip().eq("")
            & ~docs["document_id"].astype(str).isin(skipped_docs)
        ].copy(),
        "approval_date_missing_cases": docs.loc[docs["document_id"].astype(str).isin(adm_docs)].copy(),
        "approval_date_present_normal_controls": docs.loc[
            docs["approval_date"].fillna("").astype(str).str.strip().ne("")
            & ~docs["document_id"].astype(str).isin(adm_docs)
        ].copy(),
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
    controls = _load_system_self_approval_controls()
    patches = [_patch_year(year, controls) for year in YEARS]
    manifest = pd.concat([p for p in patches if not p.empty], ignore_index=True) if patches else pd.DataFrame()
    manifest.to_csv(LABELS / "l105_self_approval_consistency_fix_manifest.csv", index=False)
    _write_json_records(LABELS / "l105_self_approval_consistency_fix_manifest.json", manifest)
    _rewrite_combined_journal()
    docs = _read_docs()
    created = docs["created_by"].fillna("").astype(str).str.strip()
    approved = docs["approved_by"].fillna("").astype(str).str.strip()
    missing_approver = approved.eq("")
    missing_date = docs["approval_date"].fillna("").astype(str).str.strip().eq("")
    l105 = _write_rule_truth(
        "L1-05",
        docs,
        created.ne("") & created.eq(approved),
        "created_by equals approved_by under broad Phase 1 field contract",
    )
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
        "candidate_version": "v83",
        "source_baseline": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "patch_scope": "restore journal/sidecar consistency for system self-approval controls",
        "patched_documents": int(manifest["document_id"].nunique()) if not manifest.empty else 0,
        "replaced_rule_counts": {
            "L1-05": int(len(l105)),
            "L1-07": int(len(l107)),
            "L1-09": int(len(l109)),
        },
        "approval_sidecar_counts": sidecar_counts,
        "all_rule_counts": rule_counts,
        "anti_fitting_note": "The fix restores field-contract consistency; it does not tune detector output.",
    }
    (DEST / "V83_L105_CONSISTENCY_FIX.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V83_CANDIDATE.md").write_text(
        "# DataSynth v83 Candidate\n\n"
        f"Source baseline: `{summary['source_baseline']}`.\n\n"
        "Scope: L1-05 self-approval journal/sidecar consistency fix.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
