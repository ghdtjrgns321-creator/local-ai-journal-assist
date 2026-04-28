"""Build v78 candidate with broad L1 rule-truth semantics.

Scope:
- Add realistic automated/system self-approval samples so L1-05 can test them.
- L1-05 rule truth: created_by == approved_by, regardless of source/persona.
- L1-06 rule truth: direct SoD markers plus configured role-threshold review users.
- L1-07 rule truth: approved_by is missing, regardless of source or amount.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config.settings import get_audit_rules  # noqa: E402


SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v77_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v78_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
V73_PATH = ROOT / "tools" / "scripts" / "build_datasynth_v73_rule_truth.py"
YEAR_SUFFIX_RE = re.compile(r"_20\d{2}$")
SYSTEM_SELF_APPROVAL_TARGETS = {2022: 7, 2023: 11, 2024: 9}


def _load_v73_module():
    spec = importlib.util.spec_from_file_location("build_datasynth_v73_rule_truth", V73_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {V73_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _materialize() -> None:
    v73 = _load_v73_module()
    os.environ["DATASYNTH_RULE_TRUTH_SOURCE"] = str(SOURCE)
    os.environ["DATASYNTH_RULE_TRUTH_DEST"] = str(DEST)
    v73.SRC = SOURCE
    v73.DEST = DEST
    v73.LABELS = LABELS
    v73._materialize_candidate()


def _patch_system_self_approval() -> list[dict[str, object]]:
    patched: list[dict[str, object]] = []
    for year, target_count in SYSTEM_SELF_APPROVAL_TARGETS.items():
        path = DEST / f"journal_entries_{year}.csv"
        df = pd.read_csv(path, dtype=str, low_memory=False)
        docs = (
            df.groupby("document_id", as_index=False)
            .agg(
                fiscal_year=("fiscal_year", "first"),
                source=("source", "first"),
                user_persona=("user_persona", "first"),
                business_process=("business_process", "first"),
                created_by=("created_by", "first"),
                approved_by=("approved_by", "first"),
                approval_date=("approval_date", "first"),
                posting_date=("posting_date", "first"),
            )
        )
        src = docs["source"].fillna("").str.strip().str.lower()
        persona = docs["user_persona"].fillna("").str.strip().str.lower().str.replace(" ", "_", regex=False)
        created = docs["created_by"].fillna("").str.strip()
        approved = docs["approved_by"].fillna("").str.strip()
        candidates = docs.loc[
            src.isin({"automated", "batch", "interface", "system", "recurring"})
            & persona.isin({"automated_system"})
            & created.ne("")
            & approved.ne("")
            & created.ne(approved)
        ].copy()
        candidates = candidates.sort_values(["business_process", "document_id"]).head(target_count)
        selected_ids = set(candidates["document_id"].astype(str))
        if not selected_ids:
            continue
        for row in candidates.to_dict(orient="records"):
            doc_id = str(row["document_id"])
            previous_creator = str(row["created_by"]).strip()
            approver = str(row["approved_by"]).strip()
            mask = df["document_id"].astype(str).eq(doc_id)
            # Preserve the existing approver/approval-limit relationship so this
            # L1-05 control does not accidentally create new L1-04 truth.
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
    sidecar = pd.DataFrame(patched)
    sidecar.to_csv(LABELS / "system_self_approval_controls.csv", index=False)
    (LABELS / "system_self_approval_controls.json").write_text(
        json.dumps(patched, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return patched


def _read_rows() -> pd.DataFrame:
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
        "user_persona",
        "sod_violation",
        "sod_conflict_type",
    ]
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


def _doc_context(rows: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "document_id",
        "fiscal_year",
        "company_code",
        "document_number",
        "document_type",
        "posting_date",
        "business_process",
        "source",
    ]
    return rows[cols].dropna(subset=["document_id"]).drop_duplicates("document_id").copy()


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
    out["source_candidate"] = "v77"
    stem = f"rule_truth_{rule_id.replace('-', '_')}"
    out.to_csv(LABELS / f"{stem}.csv", index=False)
    _write_json_records(LABELS / f"{stem}.json", out)
    for year in YEARS:
        subset = out.loc[out["fiscal_year"].astype(str).eq(str(year))]
        subset.to_csv(LABELS / f"{stem}_{year}.csv", index=False)
        _write_json_records(LABELS / f"{stem}_{year}.json", subset)
    return out


def _build_l105(rows: pd.DataFrame) -> pd.DataFrame:
    docs = rows.groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", "first"),
        company_code=("company_code", "first"),
        document_number=("document_number", "first"),
        document_type=("document_type", "first"),
        posting_date=("posting_date", "first"),
        business_process=("business_process", "first"),
        source=("source", "first"),
        created_by=("created_by", "first"),
        approved_by=("approved_by", "first"),
    )
    created = docs["created_by"].fillna("").astype(str).str.strip()
    approved = docs["approved_by"].fillna("").astype(str).str.strip()
    truth = docs.loc[created.ne("") & approved.ne("") & created.eq(approved)]
    return _write_rule_truth(
        "L1-05",
        truth.drop(columns=["created_by", "approved_by"]),
        "created_by equals approved_by regardless of source or system context",
        "broad field contract: created_by == approved_by",
    )


def _build_l106(rows: pd.DataFrame) -> pd.DataFrame:
    docs = rows.groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", "first"),
        company_code=("company_code", "first"),
        document_number=("document_number", "first"),
        document_type=("document_type", "first"),
        posting_date=("posting_date", "first"),
        business_process=("business_process", "first"),
        source=("source", "first"),
        created_by=("created_by", "first"),
        user_persona=("user_persona", "first"),
        sod_violation=("sod_violation", "first"),
        sod_conflict_type=("sod_conflict_type", "first"),
    )
    direct = docs["sod_violation"].fillna("").astype(str).str.strip().str.lower().isin({"true", "1", "yes", "y"})
    direct = direct | docs["sod_conflict_type"].fillna("").astype(str).str.strip().ne("")

    patterns = get_audit_rules().get("patterns", {})
    thresholds = {
        str(k).strip().lower().replace(" ", "_"): int(v)
        for k, v in patterns.get("sod_role_thresholds", {}).items()
    }
    source = docs["source"].fillna("").astype(str).str.strip().str.lower()
    persona = docs["user_persona"].fillna("").astype(str).str.strip().str.lower().str.replace(" ", "_", regex=False)
    human = ~source.isin({"automated", "batch", "interface", "system"}) & ~persona.eq("automated_system")
    process = docs["business_process"].fillna("").astype(str).str.strip().str.upper()
    user = docs["created_by"].fillna("").astype(str).str.strip()
    human_docs = docs.loc[human & user.ne("")].assign(_process=process[human & user.ne("")], _persona=persona[human & user.ne("")])
    process_counts = human_docs.groupby("created_by")["_process"].nunique()
    persona_map = human_docs.drop_duplicates("created_by").set_index("created_by")["_persona"]
    role_violators = {
        user_id
        for user_id, count in process_counts.items()
        if persona_map.get(user_id) in thresholds and count > thresholds[persona_map.get(user_id)]
    }
    role_threshold = human & user.isin(role_violators)

    truth = docs.loc[direct | role_threshold].copy()
    truth["sod_truth_reason"] = "direct_or_role_threshold"
    return _write_rule_truth(
        "L1-06",
        truth.drop(columns=["created_by", "user_persona", "sod_violation", "sod_conflict_type"]),
        "direct SoD conflict marker or configured role-based process-count threshold",
        "broad SoD contract: sod marker OR role threshold review signal",
    )


def _build_l107(rows: pd.DataFrame) -> pd.DataFrame:
    docs = rows.groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", "first"),
        company_code=("company_code", "first"),
        document_number=("document_number", "first"),
        document_type=("document_type", "first"),
        posting_date=("posting_date", "first"),
        business_process=("business_process", "first"),
        source=("source", "first"),
        approved_by=("approved_by", "first"),
    )
    no_approver = docs["approved_by"].fillna("").astype(str).str.strip().isin({"", "None", "nan", "NaN", "<NA>"})
    truth = docs.loc[no_approver]
    return _write_rule_truth(
        "L1-07",
        truth.drop(columns=["approved_by"]),
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
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")

    _materialize()
    patched_self_approval = _patch_system_self_approval()
    rows = _read_rows()
    replacements = {
        "L1-05": _build_l105(rows),
        "L1-06": _build_l106(rows),
        "L1-07": _build_l107(rows),
    }
    rule_counts = _rebuild_combined()
    summary = {
        "candidate_version": "v78",
        "source_baseline": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "patch_scope": "broaden L1-05/L1-06/L1-07 rule truth to field/review candidate semantics and add system self-approval controls",
        "patched_system_self_approval_docs": len(patched_self_approval),
        "system_self_approval_targets": SYSTEM_SELF_APPROVAL_TARGETS,
        "replaced_rule_counts": {rule: int(len(df)) for rule, df in replacements.items()},
        "all_rule_counts": rule_counts,
        "anti_fitting_note": "This intentionally broadens Phase 1 contract truth. Risk/priority classification must be evaluated downstream, not by excluding candidates from rule_truth.",
    }
    (DEST / "V78_L1_BROAD_RULE_TRUTH_PATCH.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V78_CANDIDATE.md").write_text(
        "# DataSynth v78 Candidate\n\n"
        f"Source baseline: `{summary['source_baseline']}`.\n\n"
        "Scope: broad L1 rule truth for L1-05/L1-06/L1-07.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
