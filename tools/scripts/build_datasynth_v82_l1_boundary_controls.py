"""Build v82 candidate with realistic L1 boundary/control cases.

The patch preserves v81's broad L1 rule-truth policy while adding small,
realistic edge cases around approvals and workflow controls:

- late/post approvals
- delegated approvals
- approver master mapping gaps
- post-approval changes requiring re-approval
- a small number of routine system-control gaps

Only actual field-contract gaps are added to L1-07/L1-09 rule truth. Boundary
cases are sidecars for downstream triage and should not be treated as injected
fraud labels.
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


SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v81_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v82_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
YEAR_SUFFIX_RE = re.compile(r"_20\d{2}$")
SYSTEM_GAP_TARGETS = {2022: 6, 2023: 9, 2024: 7}
LATE_APPROVAL_TARGETS = {2022: 120, 2023: 145, 2024: 110}
DELEGATED_APPROVAL_TARGETS = {2022: 55, 2023: 72, 2024: 61}
MAPPING_GAP_TARGETS = {2022: 14, 2023: 22, 2024: 18}
POST_APPROVAL_CHANGE_TARGETS = {2022: 38, 2023: 49, 2024: 43}


def _copy_candidate_safely() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(SOURCE, DEST, copy_function=shutil.copy2)


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_employees() -> list[str]:
    path = DEST / "master_data" / "employees.json"
    records = json.loads(path.read_text(encoding="utf-8"))
    users = [
        str(row.get("user_id", "")).strip()
        for row in records
        if str(row.get("user_id", "")).strip()
        and float(row.get("approval_limit") or 0) >= 1_000_000_000
    ]
    if not users:
        raise RuntimeError("no high-limit employees available for delegated approval controls")
    return sorted(users)


def _doc_frame(df: pd.DataFrame) -> pd.DataFrame:
    return df.groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", "first"),
        company_code=("company_code", "first"),
        document_number=("document_number", "first"),
        document_type=("document_type", "first"),
        posting_date=("posting_date", "first"),
        document_date=("document_date", "first"),
        business_process=("business_process", "first"),
        source=("source", "first"),
        created_by=("created_by", "first"),
        approved_by=("approved_by", "first"),
        approval_date=("approval_date", "first"),
        user_persona=("user_persona", "first"),
        header_text=("header_text", "first"),
    )


def _valid_approval_docs(docs: pd.DataFrame) -> pd.Series:
    approved = docs["approved_by"].fillna("").astype(str).str.strip()
    approval_date = docs["approval_date"].fillna("").astype(str).str.strip()
    return approved.ne("") & approval_date.ne("")


def _pick(docs: pd.DataFrame, mask: pd.Series, count: int, salt: str) -> pd.DataFrame:
    candidates = docs.loc[mask].copy()
    if candidates.empty:
        return candidates
    candidates["_sort"] = (
        candidates["company_code"].fillna("")
        + "|"
        + candidates["business_process"].fillna("")
        + "|"
        + candidates["document_id"].astype(str)
        + "|"
        + salt
    )
    return candidates.sort_values("_sort").head(count).drop(columns=["_sort"])


def _patch_year(year: int, delegates: list[str]) -> dict[str, pd.DataFrame]:
    path = DEST / f"journal_entries_{year}.csv"
    df = pd.read_csv(path, dtype=str, low_memory=False)
    docs = _doc_frame(df)
    protected_self_approval_docs: set[str] = set()
    self_controls_path = LABELS / "system_self_approval_controls.csv"
    if self_controls_path.exists():
        controls = pd.read_csv(self_controls_path, dtype=str, usecols=["document_id"])
        protected_self_approval_docs.update(controls["document_id"].dropna().astype(str))
    l105_truth_path = LABELS / "rule_truth_L1_05.csv"
    if l105_truth_path.exists():
        truth = pd.read_csv(l105_truth_path, dtype=str, usecols=["document_id"])
        protected_self_approval_docs.update(truth["document_id"].dropna().astype(str))
    doc_id = docs["document_id"].astype(str)
    source = docs["source"].fillna("").astype(str).str.strip().str.lower()
    created = docs["created_by"].fillna("").astype(str).str.strip()
    approved = docs["approved_by"].fillna("").astype(str).str.strip()
    posting = pd.to_datetime(docs["posting_date"], errors="coerce")
    has_approval = _valid_approval_docs(docs)
    routine = source.isin({"automated", "recurring", "batch", "interface", "system"})
    human_source = source.isin({"manual", "adjustment"})

    used: set[str] = set()
    late = _pick(
        docs,
        has_approval & human_source & posting.notna(),
        LATE_APPROVAL_TARGETS[year],
        "late",
    )
    used.update(late["document_id"].astype(str))
    delegated = _pick(
        docs,
        has_approval & human_source & ~doc_id.isin(used) & created.ne(approved),
        DELEGATED_APPROVAL_TARGETS[year],
        "delegated",
    )
    used.update(delegated["document_id"].astype(str))
    mapping_gap = _pick(
        docs,
        has_approval & human_source & ~doc_id.isin(used),
        MAPPING_GAP_TARGETS[year],
        "mapping",
    )
    used.update(mapping_gap["document_id"].astype(str))
    post_change = _pick(
        docs,
        has_approval & human_source & ~doc_id.isin(used),
        POST_APPROVAL_CHANGE_TARGETS[year],
        "post_change",
    )
    used.update(post_change["document_id"].astype(str))
    system_gap = _pick(
        docs,
        has_approval & routine & ~doc_id.isin(used) & ~doc_id.isin(protected_self_approval_docs),
        SYSTEM_GAP_TARGETS[year],
        "system_gap",
    )

    df_doc_id = df["document_id"].astype(str)
    sidecars: dict[str, list[dict[str, object]]] = {
        "late_approval_boundary_controls": [],
        "delegated_approval_controls": [],
        "approver_master_mapping_issues": [],
        "post_approval_change_controls": [],
        "system_control_gap_controls": [],
    }

    for offset, row in enumerate(late.to_dict(orient="records")):
        target_doc = str(row["document_id"])
        delay_days = [2, 3, 5, 8, 13, 21][offset % 6]
        new_date = (pd.to_datetime(row["posting_date"]) + pd.Timedelta(days=delay_days)).strftime("%Y-%m-%d")
        df.loc[df_doc_id.eq(target_doc), "approval_date"] = new_date
        sidecars["late_approval_boundary_controls"].append({
            **row,
            "boundary_type": "late_post_approval",
            "original_approval_date": row.get("approval_date"),
            "new_approval_date": new_date,
            "delay_days": delay_days,
            "l1_truth_effect": "not_L1_07_or_L1_09_because_approver_and_approval_date_exist",
        })

    for offset, row in enumerate(delegated.to_dict(orient="records")):
        target_doc = str(row["document_id"])
        delegate = delegates[(offset + year) % len(delegates)]
        if delegate == str(row.get("created_by", "")):
            delegate = delegates[(offset + year + 1) % len(delegates)]
        df.loc[df_doc_id.eq(target_doc), "approved_by"] = delegate
        sidecars["delegated_approval_controls"].append({
            **row,
            "boundary_type": "delegated_approval",
            "original_approved_by": row.get("approved_by"),
            "delegated_approved_by": delegate,
            "delegation_reason": ["absence_cover", "entity_backup", "temporary_workflow_routing"][offset % 3],
            "l1_truth_effect": "not_L1_07_or_L1_09_because_approval_trace_exists",
        })

    for offset, row in enumerate(mapping_gap.to_dict(orient="records")):
        target_doc = str(row["document_id"])
        external_approver = f"EXTAPR{year}{offset + 1:03d}"
        df.loc[df_doc_id.eq(target_doc), "approved_by"] = external_approver
        sidecars["approver_master_mapping_issues"].append({
            **row,
            "boundary_type": "approver_master_mapping_gap",
            "original_approved_by": row.get("approved_by"),
            "new_approved_by": external_approver,
            "mapping_gap_reason": ["external_delegate", "legacy_user_id", "hr_master_lag"][offset % 3],
            "l1_truth_effect": "not_L1_07_or_L1_09_because_approved_by_and_approval_date_exist",
        })

    for offset, row in enumerate(post_change.to_dict(orient="records")):
        target_doc = str(row["document_id"])
        suffix = f" | post-approval reclass review {offset + 1:02d}"
        current_text = df.loc[df_doc_id.eq(target_doc), "header_text"].fillna("").astype(str)
        df.loc[df_doc_id.eq(target_doc), "header_text"] = current_text.str.slice(0, 180) + suffix
        sidecars["post_approval_change_controls"].append({
            **row,
            "boundary_type": "post_approval_change",
            "changed_field": ["header_text", "cost_center", "gl_account_review_note"][offset % 3],
            "reapproval_required": "review",
            "l1_truth_effect": "not_direct_L1_field_gap; downstream_reapproval_triage_case",
        })

    for _, row in system_gap.iterrows():
        target_doc = str(row["document_id"])
        mask = df_doc_id.eq(target_doc)
        df.loc[mask, "approved_by"] = ""
        df.loc[mask, "approval_date"] = ""
        sidecars["system_control_gap_controls"].append({
            **row.to_dict(),
            "boundary_type": "routine_system_control_gap",
            "original_approved_by": row.get("approved_by"),
            "original_approval_date": row.get("approval_date"),
            "l1_truth_effect": "added_to_L1_07_and_L1_09_broad_rule_truth",
        })

    df.to_csv(path, index=False)
    return {name: pd.DataFrame(records) for name, records in sidecars.items()}


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
    out["truth_derivation"] = "v82 L1 boundary controls + broad field contract"
    out["source_candidate"] = "v82"
    stem = f"rule_truth_{rule_id.replace('-', '_')}"
    out.to_csv(LABELS / f"{stem}.csv", index=False)
    _write_json_records(LABELS / f"{stem}.json", out)
    for year in YEARS:
        subset = out.loc[out["fiscal_year"].astype(str).eq(str(year))]
        subset.to_csv(LABELS / f"{stem}_{year}.csv", index=False)
        _write_json_records(LABELS / f"{stem}_{year}.json", subset)
    return out


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


def _write_sidecars(sidecars_by_year: list[dict[str, pd.DataFrame]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    names = sorted({name for sidecars in sidecars_by_year for name in sidecars})
    for name in names:
        frames = [sidecars[name] for sidecars in sidecars_by_year if name in sidecars and not sidecars[name].empty]
        frame = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
        frame.to_csv(LABELS / f"{name}.csv", index=False)
        _write_json_records(LABELS / f"{name}.json", frame)
        counts[name] = int(len(frame))
        for year in YEARS:
            subset = frame.loc[frame["fiscal_year"].astype(str).eq(str(year))] if not frame.empty else frame
            subset.to_csv(LABELS / f"{name}_{year}.csv", index=False)
            _write_json_records(LABELS / f"{name}_{year}.json", subset)
    return counts


def main() -> None:
    _copy_candidate_safely()
    delegates = _load_employees()
    sidecars = [_patch_year(year, delegates) for year in YEARS]
    _rewrite_combined_journal()
    sidecar_counts = _write_sidecars(sidecars)
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
    rule_counts = _rebuild_rule_truth_combined()
    summary = {
        "candidate_version": "v82",
        "source_baseline": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "patch_scope": "add realistic L1 approval/workflow boundary controls",
        "sidecar_counts": sidecar_counts,
        "replaced_rule_counts": {"L1-07": int(len(l107)), "L1-09": int(len(l109))},
        "all_rule_counts": rule_counts,
        "anti_fitting_note": "Boundary controls are not injected fraud labels. Only actual missing approved_by/approval_date fields enter L1 rule truth.",
    }
    (DEST / "V82_L1_BOUNDARY_CONTROLS_PATCH.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V82_CANDIDATE.md").write_text(
        "# DataSynth v82 Candidate\n\n"
        f"Source baseline: `{summary['source_baseline']}`.\n\n"
        "Scope: realistic L1 approval/workflow boundary controls.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
