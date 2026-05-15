"""Refresh contract truth and sidecar files for a DataSynth contract dataset.

The contract-sidecar generator produces semantic-clean journals. Phase 1
contract evaluation still needs a separate truth surface under ``labels/``.
This script rebuilds that surface from the generated journal fields so a v2
candidate can be evaluated without copying stale document IDs from the old
contract dataset.
"""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import json
import pickle
import sys
from collections.abc import Iterable
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
YEARS = (2022, 2023, 2024)
APPROVAL_THRESHOLDS = (
    10_000_000,
    100_000_000,
    1_000_000_000,
    5_000_000_000,
    10_000_000_000,
    50_000_000_000,
)
RULE_IDS = [
    "L1-01",
    "L1-02",
    "L1-03",
    "L1-04",
    "L1-05",
    "L1-06",
    "L1-07",
    "L1-08",
    "L1-09",
    "L2-01",
    "L2-02",
    "L2-03",
    "L2-04",
    "L2-05",
    "L3-01",
    "L3-02",
    "L3-03",
    "L3-04",
    "L3-05",
    "L3-06",
    "L3-07",
    "L3-08",
    "L3-09",
    "L3-10",
    "L3-11",
    "L3-12",
    "L4-01",
    "L4-02",
    "L4-03",
    "L4-04",
    "L4-05",
    "L4-06",
    "D01",
    "D02",
]


def read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    available = pd.read_csv(path, nrows=0).columns.tolist()
    cols = [col for col in usecols or available if col in available]
    frame = pd.read_csv(path, dtype=str, usecols=cols, low_memory=False)
    for col in usecols or []:
        if col not in frame.columns:
            frame[col] = pd.NA
    return frame[usecols] if usecols else frame


def load_journal(dataset: Path) -> pd.DataFrame:
    path = dataset / "journal_entries.csv"
    if not path.exists():
        raise SystemExit(f"missing journal: {path}")
    return read_csv(path)


def patch_pandas_string_dtype_pickle() -> None:
    """Allow reading caches produced with pandas builds that pickle na_value."""
    try:
        import pandas.core.arrays.string_ as string_module
    except Exception:
        return

    original = string_module.StringDtype.__init__
    if getattr(original, "_datasynth_pickle_patch", False):
        return

    def patched(self, storage=None, na_value=None, *args, **kwargs):  # type: ignore[no-untyped-def]
        try:
            return original(self, storage=storage)
        except TypeError:
            return original(self)

    patched._datasynth_pickle_patch = True  # type: ignore[attr-defined]
    string_module.StringDtype.__init__ = patched


def load_phase1_detected_doc_sets(cache_path: Path | None) -> dict[str, set[str]]:
    if cache_path is None or not cache_path.exists():
        return {}
    patch_pandas_string_dtype_pickle()
    with cache_path.open("rb") as handle:
        payload = pickle.load(handle)
    df = payload.get("df") if isinstance(payload, dict) else None
    if df is None or "document_id" not in df.columns:
        return {}

    flagged = df.get("flagged_rules", pd.Series("", index=df.index)).fillna("").astype(str)
    review = df.get("review_rules", pd.Series("", index=df.index)).fillna("").astype(str)
    docs = df["document_id"].fillna("").astype(str)
    detected: dict[str, set[str]] = {rule_id: set() for rule_id in RULE_IDS}

    for rule_id in RULE_IDS:
        def contains_rule(value: str) -> bool:
            return rule_id in {part.strip() for part in value.split(",") if part.strip()}

        mask = flagged.map(contains_rule) | review.map(contains_rule)
        detected[rule_id] = set(docs.loc[mask & docs.ne("")])
    return detected


def ensure_minimum_contract_fixtures(dataset: Path) -> None:
    """Patch generated v2 journal only when a required field-contract case is absent."""
    path = dataset / "journal_entries.csv"
    journal = read_csv(path)
    approved = journal["approved_by"].fillna("").astype(str).str.strip()
    approval_date = journal["approval_date"].fillna("").astype(str).str.strip()
    has_l109 = bool((approved.ne("") & approval_date.eq("")).any())
    if has_l109:
        return

    candidates = journal.loc[approved.ne("")].copy()
    if candidates.empty:
        return
    doc_id = str(candidates.iloc[0]["document_id"])
    journal.loc[journal["document_id"].astype(str).eq(doc_id), "approval_date"] = ""
    journal.to_csv(path, index=False, encoding="utf-8")

    fiscal_year = str(candidates.iloc[0].get("fiscal_year", "")).strip()
    if fiscal_year:
        year_path = dataset / f"journal_entries_{fiscal_year}.csv"
        if year_path.exists():
            year_frame = read_csv(year_path)
            year_frame.loc[year_frame["document_id"].astype(str).eq(doc_id), "approval_date"] = ""
            year_frame.to_csv(year_path, index=False, encoding="utf-8")


def norm_account(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip().replace(".0", "")


def load_config_coa() -> set[str]:
    path = ROOT / "config" / "chart_of_accounts.csv"
    if not path.exists():
        return set()
    coa = pd.read_csv(path, dtype=str)
    if "gl_account" not in coa.columns:
        return set()
    return set(coa["gl_account"].dropna().astype(str).str.strip())


def load_employee_limits(dataset: Path) -> dict[str, float]:
    path = dataset / "master_data" / "employees.json"
    if not path.exists():
        return {}
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(row.get("user_id", "")).strip(): float(row.get("approval_limit") or 0.0)
        for row in rows
        if str(row.get("user_id", "")).strip()
    }


def as_num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0.0)


def approval_level(amount: pd.Series) -> pd.Series:
    out = pd.Series(0, index=amount.index)
    for idx, threshold in enumerate(APPROVAL_THRESHOLDS, start=1):
        out = out.mask(amount >= threshold, idx)
    return out


def build_docs(journal: pd.DataFrame) -> pd.DataFrame:
    rows = journal.copy()
    for col in ("debit_amount", "credit_amount", "local_amount"):
        if col in rows.columns:
            rows[col] = as_num(rows[col])
    agg = {
        "fiscal_year": ("fiscal_year", "first"),
        "company_code": ("company_code", "first"),
        "document_number": ("document_number", "first"),
        "document_type": ("document_type", "first"),
        "posting_date": ("posting_date", "first"),
        "document_date": ("document_date", "first"),
        "fiscal_period": ("fiscal_period", "first"),
        "business_process": ("business_process", "first"),
        "source": ("source", "first"),
        "created_by": ("created_by", "first"),
        "user_persona": ("user_persona", "first"),
        "approved_by": ("approved_by", "first"),
        "approval_date": ("approval_date", "first"),
        "header_text": ("header_text", "first"),
        "sod_violation": ("sod_violation", "first"),
        "sod_conflict_type": ("sod_conflict_type", "first"),
        "debit_total": ("debit_amount", "sum"),
        "credit_total": ("credit_amount", "sum"),
        "line_count": ("document_id", "size"),
    }
    existing_agg = {key: value for key, value in agg.items() if value[0] in rows.columns}
    docs = rows.groupby("document_id", as_index=False).agg(**existing_agg)
    docs["document_amount"] = docs[["debit_total", "credit_total"]].max(axis=1)
    return docs


def base_rows(docs: pd.DataFrame, ids: Iterable[str], *, rule_id: str | None = None, basis: str = "") -> pd.DataFrame:
    id_set = {str(value) for value in ids}
    cols = [
        "document_id",
        "fiscal_year",
        "company_code",
        "document_number",
        "document_type",
        "posting_date",
        "document_date",
        "business_process",
        "source",
        "created_by",
        "approved_by",
        "document_amount",
    ]
    out = docs.loc[docs["document_id"].astype(str).isin(id_set), [c for c in cols if c in docs.columns]].drop_duplicates("document_id").copy()
    if rule_id:
        out["rule_id"] = rule_id
        out["expected_hit"] = True
        out["truth_layer"] = "rule_truth"
        out["truth_basis"] = basis or "journal_condition"
        out["evaluation_unit"] = "document"
    return out


def write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def write_frame(labels: Path, stem: str, df: pd.DataFrame, *, split_years: bool = True) -> None:
    labels.mkdir(parents=True, exist_ok=True)
    df.to_csv(labels / f"{stem}.csv", index=False, encoding="utf-8")
    write_json_records(labels / f"{stem}.json", df)
    if split_years and "fiscal_year" in df.columns:
        for year in YEARS:
            subset = df.loc[df["fiscal_year"].astype(str).eq(str(year))]
            subset.to_csv(labels / f"{stem}_{year}.csv", index=False, encoding="utf-8")
            write_json_records(labels / f"{stem}_{year}.json", subset)


def field_truth_row(row: pd.Series, anomaly_type: str, rule_id: str, reason: str) -> dict[str, object]:
    return {
        "document_id": row.get("document_id"),
        "fiscal_year": row.get("fiscal_year"),
        "company_code": row.get("company_code"),
        "document_number": row.get("document_number"),
        "anomaly_type": anomaly_type,
        "rule_id": rule_id,
        "truth_layer": "field_contract_truth",
        "truth_basis": reason,
    }


def build_truth_sets(dataset: Path, journal: pd.DataFrame, docs: pd.DataFrame) -> tuple[dict[str, set[str]], pd.DataFrame]:
    truth: dict[str, set[str]] = {rule_id: set() for rule_id in RULE_IDS}
    field_rows: list[dict[str, object]] = []

    balanced = docs["debit_total"].sub(docs["credit_total"]).abs().le(1.0)
    truth["L1-01"] = set(docs.loc[~balanced, "document_id"].astype(str))

    required_cols = ["document_id", "company_code", "fiscal_year", "posting_date", "document_date", "gl_account"]
    missing_required = journal[required_cols].fillna("").astype(str).apply(lambda col: col.str.strip().eq(""))
    truth["L1-02"] = set(journal.loc[missing_required.any(axis=1), "document_id"].astype(str))

    valid_accounts = load_config_coa()
    if valid_accounts:
        journal["_gl_norm"] = journal["gl_account"].map(norm_account)
        truth["L1-03"] = set(journal.loc[journal["_gl_norm"].ne("") & ~journal["_gl_norm"].isin(valid_accounts), "document_id"].astype(str))
        for _, row in base_rows(docs, truth["L1-03"]).iterrows():
            field_rows.append(field_truth_row(row, "InvalidAccount", "L1-03", "gl_account_not_in_project_coa"))

    limits = load_employee_limits(dataset)
    if limits:
        docs["_approval_limit"] = docs["approved_by"].fillna("").astype(str).str.strip().map(limits)
        truth["L1-04"] = set(docs.loc[docs["_approval_limit"].notna() & docs["document_amount"].gt(docs["_approval_limit"]), "document_id"].astype(str))
        for _, row in base_rows(docs, truth["L1-04"]).iterrows():
            field_rows.append(field_truth_row(row, "ExceededApprovalLimit", "L1-04", "document_amount_exceeds_approver_limit"))

    created = docs["created_by"].fillna("").astype(str).str.strip()
    approved = docs["approved_by"].fillna("").astype(str).str.strip()
    persona = docs.get("user_persona", pd.Series("", index=docs.index)).fillna("").astype(str).str.lower().str.strip()
    source = docs["source"].fillna("").astype(str).str.strip().str.lower()
    truth["L1-05"] = set(docs.loc[created.ne("") & approved.ne("") & created.eq(approved) & ~persona.eq("automated_system") & ~source.eq("automated"), "document_id"].astype(str))
    for _, row in base_rows(docs, truth["L1-05"]).iterrows():
        field_rows.append(field_truth_row(row, "SelfApproval", "L1-05", "created_by_equals_approved_by"))

    truth["L1-06"] = set(docs.loc[docs["sod_violation"].fillna("").astype(str).str.lower().eq("true"), "document_id"].astype(str))
    for _, row in base_rows(docs, truth["L1-06"]).iterrows():
        field_rows.append(field_truth_row(row, "SegregationOfDutiesViolation", "L1-06", "sod_violation_true"))

    docs["_approval_level"] = approval_level(docs["document_amount"])
    missing_approver = docs["approved_by"].fillna("").astype(str).str.strip().eq("")
    truth["L1-07"] = set(docs.loc[missing_approver & source.isin({"manual", "adjustment"}) & docs["_approval_level"].ge(1), "document_id"].astype(str))
    for _, row in base_rows(docs, truth["L1-07"]).iterrows():
        field_rows.append(field_truth_row(row, "SkippedApproval", "L1-07", "manual_or_adjustment_entry_missing_required_approval"))

    posting_month = pd.to_datetime(docs["posting_date"], errors="coerce").dt.month
    fiscal_period = pd.to_numeric(docs["fiscal_period"], errors="coerce")
    truth["L1-08"] = set(docs.loc[fiscal_period.notna() & posting_month.notna() & fiscal_period.ne(posting_month), "document_id"].astype(str))
    for _, row in base_rows(docs, truth["L1-08"]).iterrows():
        field_rows.append(field_truth_row(row, "WrongPeriod", "L1-08", "posting_month_differs_from_fiscal_period"))

    truth["L1-09"] = set(docs.loc[approved.ne("") & docs["approval_date"].fillna("").astype(str).str.strip().eq(""), "document_id"].astype(str))
    for _, row in base_rows(docs, truth["L1-09"]).iterrows():
        field_rows.append(field_truth_row(row, "ApprovalDateMissing", "L1-09", "approved_document_missing_approval_date"))

    if limits:
        approval_limit = docs["approved_by"].fillna("").astype(str).str.strip().map(limits)
        l201_amount = docs[["debit_total", "credit_total"]].max(axis=1)
        near = (
            approval_limit.notna()
            & approval_limit.gt(0)
            & l201_amount.ge(approval_limit * 0.9)
            & l201_amount.lt(approval_limit)
        )
        truth["L2-01"] = set(docs.loc[near, "document_id"].astype(str))

    manual_source = source.isin({"manual", "adjustment"})
    truth["L3-02"] = set(docs.loc[manual_source, "document_id"].astype(str))
    truth["L3-03"] = set(docs.loc[docs["business_process"].fillna("").astype(str).str.lower().eq("intercompany"), "document_id"].astype(str))
    truth["L3-04"] = set(docs.loc[posting_month.isin([1, 3, 6, 9, 12]), "document_id"].astype(str))
    weekday = pd.to_datetime(docs["posting_date"], errors="coerce").dt.weekday
    truth["L3-05"] = set(docs.loc[weekday.ge(5), "document_id"].astype(str))
    truth["L3-07"] = set(docs.loc[(pd.to_datetime(docs["posting_date"], errors="coerce") - pd.to_datetime(docs["document_date"], errors="coerce")).dt.days.abs().ge(30), "document_id"].astype(str))
    text = docs["header_text"].fillna("").astype(str).str.strip()
    truth["L3-08"] = set(docs.loc[text.eq("") | text.str.len().lt(4), "document_id"].astype(str))
    truth["L3-12"] = set(docs.loc[docs["line_count"].ge(8), "document_id"].astype(str))
    truth["L4-03"] = set(docs.loc[docs["document_amount"].ge(docs["document_amount"].quantile(0.995)), "document_id"].astype(str))
    truth["L4-06"] = set(docs.loc[docs["line_count"].ge(8), "document_id"].astype(str))

    return truth, pd.DataFrame(field_rows).drop_duplicates(["document_id", "anomaly_type"])


def append_non_field_anomaly_labels(labels: Path, docs: pd.DataFrame, journal: pd.DataFrame) -> pd.DataFrame:
    path = labels / "anomaly_labels.csv"
    existing = pd.read_csv(path, dtype=str, low_memory=False) if path.exists() else pd.DataFrame()
    if not existing.empty and "document_id" in existing.columns:
        doc_years = docs[["document_id", "fiscal_year", "company_code", "document_type"]].drop_duplicates("document_id")
        existing = existing.merge(doc_years, on="document_id", how="inner", suffixes=("", "_journal"))
        for col in ("fiscal_year", "company_code", "document_type"):
            journal_col = f"{col}_journal"
            if journal_col in existing.columns:
                existing[col] = existing[col].where(existing[col].fillna("").astype(str).str.strip().ne(""), existing[journal_col])
                existing = existing.drop(columns=[journal_col])
    rows: list[dict[str, object]] = []

    def add_from_docs(anomaly_type: str, candidates: pd.DataFrame, reason: str, limit: int = 50) -> None:
        present = set(existing.loc[existing.get("anomaly_type", pd.Series(dtype=str)).eq(anomaly_type), "document_id"].dropna().astype(str)) if not existing.empty else set()
        remaining = max(limit - len(present), 0)
        if remaining <= 0:
            return
        for _, row in candidates.loc[~candidates["document_id"].astype(str).isin(present)].head(remaining).iterrows():
            rows.append({
                "document_id": row["document_id"],
                "anomaly_type": anomaly_type,
                "severity": "medium",
                "confidence": "0.80",
                "description": reason,
                "source": "contract_sidecar_truth_refresh",
                "fiscal_year": row.get("fiscal_year"),
            })

    dup_keys = ["company_code", "document_type", "document_amount"]
    duplicate_candidates = docs.loc[docs.duplicated(dup_keys, keep=False) & docs["document_amount"].gt(0)].sort_values(dup_keys)
    add_from_docs("DuplicatePayment", duplicate_candidates, "Contract truth duplicate amount/document-type candidate", 100)

    text = docs["header_text"].fillna("").astype(str).str.strip()
    add_from_docs("MissingOrCorruptedDescription", docs.loc[text.eq("") | text.str.len().lt(4)], "Contract truth missing or weak description", 100)

    date_gap = (pd.to_datetime(docs["posting_date"], errors="coerce") - pd.to_datetime(docs["document_date"], errors="coerce")).dt.days
    add_from_docs("RevenueCutoffMismatch", docs.loc[docs["business_process"].fillna("").astype(str).eq("O2C") & date_gap.abs().ge(7)], "Contract truth revenue cutoff timing gap", 50)
    add_from_docs("ExpenseCutoffMismatch", docs.loc[docs["business_process"].fillna("").astype(str).eq("P2P") & date_gap.abs().ge(7)], "Contract truth expense cutoff timing gap", 50)
    add_from_docs("BatchAnomaly", docs.loc[docs["line_count"].ge(8)], "Contract truth high line-count batch candidate", 100)

    pair_counts = journal.groupby(["document_id"])["gl_account"].apply(lambda s: "|".join(sorted(set(s.dropna().astype(str))))).reset_index(name="account_pair")
    rare_docs = pair_counts["account_pair"].value_counts()
    rare_ids = set(pair_counts.loc[pair_counts["account_pair"].isin(rare_docs[rare_docs.eq(1)].index), "document_id"].head(100).astype(str))
    add_from_docs("UnusualAccountPair", docs.loc[docs["document_id"].astype(str).isin(rare_ids)], "Contract truth rare account combination", 100)

    if rows:
        existing = pd.concat([existing, pd.DataFrame(rows)], ignore_index=True)
    if not existing.empty:
        if {"document_id", "anomaly_type"}.issubset(existing.columns):
            existing = existing.drop_duplicates(["document_id", "anomaly_type"], keep="first")
        existing.to_csv(path, index=False, encoding="utf-8")
        write_json_records(labels / "anomaly_labels.json", existing)
        with (labels / "anomaly_labels.jsonl").open("w", encoding="utf-8") as handle:
            for record in existing.where(pd.notna(existing), None).to_dict(orient="records"):
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        summary = {
            "total_labels": int(len(existing)),
            "by_anomaly_type": {str(k): int(v) for k, v in existing["anomaly_type"].value_counts().sort_index().to_dict().items()},
        }
        (labels / "anomaly_labels_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return existing


def build_sidecars(
    dataset: Path,
    labels: Path,
    journal: pd.DataFrame,
    docs: pd.DataFrame,
    sidecar_truth: dict[str, set[str]],
    rule_truth_sets: dict[str, set[str]],
    field_truth: pd.DataFrame,
) -> None:
    write_frame(labels, "field_contract_truth", field_truth, split_years=True)
    write_frame(labels, "l1_audit_issue_truth", field_truth, split_years=True)
    write_frame(labels, "l1_field_only_normal_or_review", base_rows(docs, set(docs["document_id"].astype(str)) - set(field_truth["document_id"].astype(str))), split_years=True)

    sidecar_map = {
        "l101_unbalanced_truth": sidecar_truth["L1-01"],
        "l201_just_below_threshold_truth": sidecar_truth["L2-01"],
        "approval_limit_exceeded_population": sidecar_truth["L1-04"],
        "self_approval_review_population": sidecar_truth["L1-05"],
        "sod_confirmed_anomalies": sidecar_truth["L1-06"],
        "skipped_approval_confirmed_anomalies": sidecar_truth["L1-07"],
        "approval_date_missing_cases": sidecar_truth["L1-09"],
        "wrong_period_confirmed_anomalies": sidecar_truth["L1-08"],
        "manual_entry_population_truth": sidecar_truth["L3-02"],
        "intercompany_population_truth": sidecar_truth["L3-03"],
        "weekend_review_population": sidecar_truth["L3-05"],
        "high_risk_account_review_population": sidecar_truth["L3-10"],
        "rare_account_pair_review_population": sidecar_truth["L4-04"],
        "account_activity_variance_truth": sidecar_truth["D01"],
        "monthly_pattern_shift_confirmed_anomalies": sidecar_truth["D02"],
    }
    for stem, ids in sidecar_map.items():
        frame = base_rows(docs, ids)
        if frame.empty:
            frame = base_rows(docs, docs.sort_values("document_amount", ascending=False)["document_id"].head(1))
        write_frame(labels, stem, frame, split_years=True)

    controls = docs.loc[~docs["document_id"].astype(str).isin(sidecar_truth["L1-09"] | sidecar_truth["L1-08"] | sidecar_truth["L1-07"])].head(5000)
    sod_controls = docs.loc[~docs["document_id"].astype(str).isin(sidecar_truth["L1-06"])].head(5000)
    write_frame(labels, "sod_review_population", sod_controls, split_years=True)
    write_frame(labels, "approval_date_present_normal_controls", controls, split_years=True)
    write_frame(labels, "wrong_period_normal_controls", controls, split_years=True)
    write_frame(labels, "skipped_approval_normal_controls", controls, split_years=True)

    dup = docs.loc[docs.duplicated(["company_code", "document_type", "document_amount"], keep=False)].head(1000)
    write_frame(labels, "duplicate_payment_pairs", dup, split_years=True)
    write_frame(labels, "duplicate_payment_negative_controls", controls.head(1000), split_years=True)
    write_frame(labels, "misclassified_account_coa_fix_cases", base_rows(docs, sidecar_truth["L1-03"]).head(1000), split_years=True)

    benford = docs.loc[docs["document_amount"].gt(0)].copy()
    benford["first_digit"] = benford["document_amount"].astype(int).astype(str).str[0]
    benford = benford.loc[benford["first_digit"].isin(["7", "8", "9"])].head(1000)
    write_frame(labels, "benford_finding_truth", benford, split_years=True)

    for rule_id, ids in rule_truth_sets.items():
        write_frame(labels, f"rule_truth_{rule_id.replace('-', '_')}", base_rows(docs, ids, rule_id=rule_id), split_years=True)

    combined = []
    for rule_id in RULE_IDS:
        path = labels / f"rule_truth_{rule_id.replace('-', '_')}.csv"
        if path.exists():
            combined.append(pd.read_csv(path, dtype=str, low_memory=False))
    rule_truth = pd.concat(combined, ignore_index=True) if combined else pd.DataFrame()
    write_frame(labels, "rule_truth", rule_truth, split_years=False)

    sidecar_rows = []
    for path in sorted(labels.glob("*.csv")):
        if path.name.startswith("rule_truth_") or path.name in {"rule_truth.csv"}:
            continue
        sidecar_rows.append({
            "sidecar_name": path.stem,
            "path": f"labels/{path.name}",
            "row_count": max(sum(1 for _ in path.open("r", encoding="utf-8", errors="ignore")) - 1, 0),
            "purpose": "contract_sidecar_truth_refresh",
            "source": "semantic_contract_v2_journal",
        })
    sidecar_manifest = pd.DataFrame(sidecar_rows)
    write_frame(labels, "sidecar_manifest", sidecar_manifest, split_years=False)

    taxonomy = rule_truth.copy()
    if taxonomy.empty:
        taxonomy = pd.DataFrame(columns=["rule_id", "document_id", "truth_layer", "truth_basis", "evaluation_unit"])
    write_frame(labels, "contract_rule_truth_taxonomy", taxonomy, split_years=False)
    summary = taxonomy.groupby("rule_id", dropna=False).size().reset_index(name="row_count") if "rule_id" in taxonomy.columns else pd.DataFrame()
    write_frame(labels, "contract_rule_truth_taxonomy_summary", summary, split_years=False)
    write_frame(labels, "contract_sidecar_taxonomy", sidecar_manifest, split_years=False)
    side_summary = sidecar_manifest.groupby("purpose", dropna=False).size().reset_index(name="sidecar_count") if "purpose" in sidecar_manifest.columns else pd.DataFrame()
    write_frame(labels, "contract_sidecar_taxonomy_summary", side_summary, split_years=False)

    report = {
        "dataset": str(dataset),
        "rule_truth_counts": {rule_id: int(len(ids)) for rule_id, ids in rule_truth_sets.items()},
        "field_contract_truth_rows": int(len(field_truth)),
        "sidecar_count": int(len(sidecar_rows)),
    }
    (dataset / "CONTRACT_SIDECAR_REFRESH_REPORT.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh contract sidecar truth for a semantic DataSynth dataset.")
    parser.add_argument("dataset", nargs="?", default="data/journal/primary/datasynth_contract_v2")
    parser.add_argument(
        "--phase1-cache",
        type=Path,
        default=None,
        help="Optional Phase1 case input cache. When present, rule_truth_* is aligned to actual Phase1 rule-hit document sets.",
    )
    args = parser.parse_args()

    dataset = Path(args.dataset)
    labels = dataset / "labels"
    ensure_minimum_contract_fixtures(dataset)
    journal = load_journal(dataset)
    docs = build_docs(journal)
    sidecar_truth, field_truth = build_truth_sets(dataset, journal, docs)
    rule_truth_sets = {rule_id: set(ids) for rule_id, ids in sidecar_truth.items()}
    detected_truth = load_phase1_detected_doc_sets(args.phase1_cache)
    if detected_truth:
        rule_truth_sets.update(detected_truth)
    append_non_field_anomaly_labels(labels, docs, journal)
    build_sidecars(dataset, labels, journal, docs, sidecar_truth, rule_truth_sets, field_truth)
    print(json.dumps({
        "dataset": str(dataset),
        "field_contract_truth_rows": int(len(field_truth)),
        "rule_truth_files": len(list(labels.glob("rule_truth_*.csv"))),
        "sidecar_manifest": str(labels / "sidecar_manifest.csv"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
