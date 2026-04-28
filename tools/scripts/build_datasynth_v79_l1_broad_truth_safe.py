"""Build v79 candidate safely without hardlink mutation.

v78 exposed that journal-row patches must not be applied on hardlinked
candidate files. This builder copies v77 metadata/labels, restores clean journal
CSV files from v71, then reapplies broad L1 rule-truth semantics.
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

from config.settings import get_audit_rules  # noqa: E402


METADATA_SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v77_candidate"
CLEAN_JOURNAL_SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v71_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v79_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
YEAR_SUFFIX_RE = re.compile(r"_20\d{2}$")
SYSTEM_SELF_APPROVAL_TARGETS = {2022: 7, 2023: 11, 2024: 9}


def _copy_candidate_safely() -> None:
    if not METADATA_SOURCE.exists():
        raise SystemExit(f"missing metadata source: {METADATA_SOURCE}")
    if not CLEAN_JOURNAL_SOURCE.exists():
        raise SystemExit(f"missing clean journal source: {CLEAN_JOURNAL_SOURCE}")
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(METADATA_SOURCE, DEST, copy_function=shutil.copy2)
    for year in YEARS:
        shutil.copy2(
            CLEAN_JOURNAL_SOURCE / f"journal_entries_{year}.csv",
            DEST / f"journal_entries_{year}.csv",
        )


def _patch_system_self_approval() -> list[dict[str, object]]:
    patched: list[dict[str, object]] = []
    for year, target_count in SYSTEM_SELF_APPROVAL_TARGETS.items():
        path = DEST / f"journal_entries_{year}.csv"
        df = pd.read_csv(path, dtype=str, low_memory=False)
        docs = df.groupby("document_id", as_index=False).agg(
            fiscal_year=("fiscal_year", "first"),
            source=("source", "first"),
            user_persona=("user_persona", "first"),
            business_process=("business_process", "first"),
            created_by=("created_by", "first"),
            approved_by=("approved_by", "first"),
        )
        src = docs["source"].fillna("").str.strip().str.lower()
        persona = docs["user_persona"].fillna("").str.strip().str.lower().str.replace(" ", "_", regex=False)
        created = docs["created_by"].fillna("").str.strip()
        approved = docs["approved_by"].fillna("").str.strip()
        candidates = docs.loc[
            src.isin({"automated", "batch", "interface", "system", "recurring"})
            & persona.eq("automated_system")
            & created.ne("")
            & approved.ne("")
            & created.ne(approved)
        ].sort_values(["business_process", "document_id"]).head(target_count)
        for row in candidates.to_dict(orient="records"):
            doc_id = str(row["document_id"])
            approver = str(row["approved_by"]).strip()
            previous_creator = str(row["created_by"]).strip()
            mask = df["document_id"].astype(str).eq(doc_id)
            df.loc[mask, "created_by"] = approver
            patched.append({
                "document_id": doc_id,
                "fiscal_year": year,
                "source": row.get("source"),
                "user_persona": row.get("user_persona"),
                "business_process": row.get("business_process"),
                "previous_created_by": previous_creator,
                "new_created_by": approver,
                "approved_by": approver,
                "patch_reason": "system_or_automated_self_approval_control",
            })
        df.to_csv(path, index=False)
    pd.DataFrame(patched).to_csv(LABELS / "system_self_approval_controls.csv", index=False)
    (LABELS / "system_self_approval_controls.json").write_text(
        json.dumps(patched, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return patched


def _rewrite_combined_journal() -> None:
    frames = [
        pd.read_csv(DEST / f"journal_entries_{year}.csv", dtype=str, low_memory=False)
        for year in YEARS
    ]
    pd.concat(frames, ignore_index=True).to_csv(DEST / "journal_entries.csv", index=False)


def _read_rows() -> pd.DataFrame:
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
        "user_persona",
        "sod_violation",
        "sod_conflict_type",
    ]
    frames: list[pd.DataFrame] = []
    for year in YEARS:
        path = DEST / f"journal_entries_{year}.csv"
        available = pd.read_csv(path, nrows=0).columns.tolist()
        cols = [col for col in usecols if col in available]
        frame = pd.read_csv(path, dtype=str, usecols=cols, low_memory=False)
        for col in usecols:
            if col not in frame.columns:
                frame[col] = pd.NA
        frame["fiscal_year"] = frame["fiscal_year"].fillna(str(year))
        frames.append(frame[usecols])
    return pd.concat(frames, ignore_index=True)


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_rule_truth(rule_id: str, docs: pd.DataFrame, basis: str, derivation: str) -> pd.DataFrame:
    out = docs.copy()
    out["rule_id"] = rule_id
    out["expected_hit"] = True
    out["truth_layer"] = "rule_truth"
    out["truth_basis"] = basis
    out["evaluation_unit"] = "document"
    out["truth_derivation"] = derivation
    out["source_candidate"] = "v79"
    stem = f"rule_truth_{rule_id.replace('-', '_')}"
    out.to_csv(LABELS / f"{stem}.csv", index=False)
    _write_json_records(LABELS / f"{stem}.json", out)
    for year in YEARS:
        subset = out.loc[out["fiscal_year"].astype(str).eq(str(year))]
        subset.to_csv(LABELS / f"{stem}_{year}.csv", index=False)
        _write_json_records(LABELS / f"{stem}_{year}.json", subset)
    return out


def _doc_agg(rows: pd.DataFrame) -> pd.DataFrame:
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
        user_persona=("user_persona", "first"),
        sod_violation=("sod_violation", "first"),
        sod_conflict_type=("sod_conflict_type", "first"),
    )


def _build_l105(docs: pd.DataFrame) -> pd.DataFrame:
    created = docs["created_by"].fillna("").astype(str).str.strip()
    approved = docs["approved_by"].fillna("").astype(str).str.strip()
    truth = docs.loc[created.ne("") & approved.ne("") & created.eq(approved)]
    return _write_rule_truth(
        "L1-05",
        truth.drop(columns=["created_by", "approved_by", "user_persona", "sod_violation", "sod_conflict_type"]),
        "created_by equals approved_by regardless of source or system context",
        "broad field contract: created_by == approved_by",
    )


def _build_l106(docs: pd.DataFrame) -> pd.DataFrame:
    direct = docs["sod_violation"].fillna("").astype(str).str.strip().str.lower().isin({"true", "1", "yes", "y"})
    direct = direct | docs["sod_conflict_type"].fillna("").astype(str).str.strip().ne("")
    thresholds = {
        str(k).strip().lower().replace(" ", "_"): int(v)
        for k, v in get_audit_rules().get("patterns", {}).get("sod_role_thresholds", {}).items()
    }
    source = docs["source"].fillna("").astype(str).str.strip().str.lower()
    persona = docs["user_persona"].fillna("").astype(str).str.strip().str.lower().str.replace(" ", "_", regex=False)
    created = docs["created_by"].fillna("").astype(str).str.strip()
    human = ~source.isin({"automated", "batch", "interface", "system"}) & ~persona.eq("automated_system")
    tmp = docs.loc[human & created.ne("")].assign(
        _process=docs.loc[human & created.ne(""), "business_process"].fillna("").astype(str).str.strip().str.upper(),
        _persona=persona.loc[human & created.ne("")],
    )
    process_counts = tmp.groupby("created_by")["_process"].nunique()
    persona_map = tmp.drop_duplicates("created_by").set_index("created_by")["_persona"]
    role_violators = {
        user_id
        for user_id, count in process_counts.items()
        if persona_map.get(user_id) in thresholds and count > thresholds[persona_map.get(user_id)]
    }
    role_threshold = human & created.isin(role_violators)
    truth = docs.loc[direct | role_threshold]
    return _write_rule_truth(
        "L1-06",
        truth.drop(columns=["created_by", "approved_by", "user_persona", "sod_violation", "sod_conflict_type"]),
        "direct SoD conflict marker or configured role-based process-count threshold",
        "broad SoD contract: sod marker OR role threshold review signal",
    )


def _build_l107(docs: pd.DataFrame) -> pd.DataFrame:
    approved = docs["approved_by"].fillna("").astype(str).str.strip().str.lower()
    truth = docs.loc[approved.isin({"", "none", "nan", "<na>"})]
    return _write_rule_truth(
        "L1-07",
        truth.drop(columns=["created_by", "approved_by", "user_persona", "sod_violation", "sod_conflict_type"]),
        "approved_by is missing regardless of source, amount, or later review priority",
        "broad field contract: approved_by missing",
    )


def _rebuild_combined() -> dict[str, int]:
    frames: list[pd.DataFrame] = []
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        stem = path.stem.removeprefix("rule_truth_")
        if YEAR_SUFFIX_RE.search(stem):
            continue
        frames.append(pd.read_csv(path, dtype=str, low_memory=False))
    combined = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    combined.to_csv(LABELS / "rule_truth.csv", index=False)
    return {
        str(rule): int(count)
        for rule, count in combined["rule_id"].value_counts().sort_index().to_dict().items()
    }


def main() -> None:
    _copy_candidate_safely()
    patched = _patch_system_self_approval()
    _rewrite_combined_journal()
    docs = _doc_agg(_read_rows())
    replacements = {
        "L1-05": _build_l105(docs),
        "L1-06": _build_l106(docs),
        "L1-07": _build_l107(docs),
    }
    rule_counts = _rebuild_combined()
    summary = {
        "candidate_version": "v79",
        "source_baseline": str(METADATA_SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "clean_journal_source": str(CLEAN_JOURNAL_SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "patch_scope": "safe rebuild of broad L1-05/L1-06/L1-07 rule truth without hardlinked journal mutation",
        "patched_system_self_approval_docs": len(patched),
        "system_self_approval_targets": SYSTEM_SELF_APPROVAL_TARGETS,
        "replaced_rule_counts": {rule: int(len(df)) for rule, df in replacements.items()},
        "all_rule_counts": rule_counts,
        "anti_fitting_note": "Broad rule_truth is candidate-population truth. Audit issue truth remains separate.",
    }
    (DEST / "V79_L1_BROAD_RULE_TRUTH_SAFE_PATCH.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V79_CANDIDATE.md").write_text(
        "# DataSynth v79 Candidate\n\n"
        f"Source baseline: `{summary['source_baseline']}`.\n\n"
        f"Clean journal source: `{summary['clean_journal_source']}`.\n\n"
        "Scope: safe broad L1 rule truth for L1-05/L1-06/L1-07.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
