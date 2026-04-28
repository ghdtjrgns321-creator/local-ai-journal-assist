"""Build v61 manifest for L1-05 SelfApproval truth repair.

This does not mutate DataSynth data. It audits the v60 candidate and writes a
manifest that can be materialized into a separate v61 candidate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v60_candidate"
MANIFEST_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v61_patch_manifest"
YEARS = (2022, 2023, 2024)

ALLOW_PERSONAS = {"automated_system"}
ALLOW_SOURCES = {"automated"}
REVIEW_PROCESSES = {"R2R", "A2R"}
IMMEDIATE_AMOUNT = 1_000_000_000
HIGH_RISK_ACCOUNTS = {"1190", "2190"}
HIGH_RISK_PREFIXES = ("111", "112", "113")


def _read_docs() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    cols = [
        "document_id",
        "company_code",
        "fiscal_year",
        "posting_date",
        "document_type",
        "document_number",
        "source",
        "business_process",
        "created_by",
        "approved_by",
        "approval_date",
        "user_persona",
        "debit_amount",
        "credit_amount",
        "gl_account",
    ]
    for year in YEARS:
        path = SOURCE_DIR / f"journal_entries_{year}.csv"
        frames.append(pd.read_csv(path, dtype=str, usecols=cols, low_memory=False))
    df = pd.concat(frames, ignore_index=True)
    df["fiscal_year"] = pd.to_numeric(df["fiscal_year"], errors="coerce").astype("Int64")
    for col in ("debit_amount", "credit_amount"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    return df


def _doc_frame(df: pd.DataFrame) -> pd.DataFrame:
    def accounts(series: pd.Series) -> str:
        values = sorted({str(v).strip() for v in series.dropna() if str(v).strip()})
        return "|".join(values)

    doc = df.groupby("document_id", as_index=False).agg(
        company_code=("company_code", "first"),
        fiscal_year=("fiscal_year", "first"),
        posting_date=("posting_date", "min"),
        document_type=("document_type", "first"),
        document_number=("document_number", "first"),
        source=("source", "first"),
        business_process=("business_process", "first"),
        created_by=("created_by", "first"),
        approved_by=("approved_by", "first"),
        approval_date=("approval_date", "first"),
        user_persona=("user_persona", "first"),
        debit_amount=("debit_amount", "sum"),
        credit_amount=("credit_amount", "sum"),
        gl_accounts=("gl_account", accounts),
    )
    doc["document_amount"] = doc[["debit_amount", "credit_amount"]].max(axis=1)
    return doc


def _is_blank(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().eq("")


def _truth_population(doc: pd.DataFrame) -> pd.DataFrame:
    created = doc["created_by"].fillna("").astype(str).str.strip()
    approved = doc["approved_by"].fillna("").astype(str).str.strip()
    persona = doc["user_persona"].fillna("").astype(str).str.strip().str.lower()
    source = doc["source"].fillna("").astype(str).str.strip().str.lower()
    allowed = persona.isin(ALLOW_PERSONAS) | source.isin(ALLOW_SOURCES)
    return doc.loc[
        created.ne("")
        & approved.ne("")
        & created.eq(approved)
        & ~allowed
        & doc["fiscal_year"].isin(YEARS)
    ].copy()


def _existing_labels() -> pd.DataFrame:
    return pd.read_csv(SOURCE_DIR / "labels" / "anomaly_labels.csv", dtype=str)


def _has_high_risk_account(accounts: str) -> bool:
    for account in str(accounts).split("|"):
        if account in HIGH_RISK_ACCOUNTS or account.startswith(HIGH_RISK_PREFIXES):
            return True
    return False


def _risk_rows(pop: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    existing_self = set(labels.loc[labels["anomaly_type"].eq("SelfApproval"), "document_id"].astype(str))
    labeled_docs = set(labels["document_id"].astype(str))
    pop = pop.copy()
    pop["source_normalized"] = pop["source"].fillna("").astype(str).str.strip().str.lower()
    pop["persona_normalized"] = pop["user_persona"].fillna("").astype(str).str.strip().str.lower()
    pop["is_review_default"] = pop["business_process"].isin(REVIEW_PROCESSES)
    pop["is_high_amount"] = pop["document_amount"].ge(IMMEDIATE_AMOUNT)
    pop["has_high_risk_account"] = pop["gl_accounts"].map(_has_high_risk_account)
    pop["has_other_label"] = pop["document_id"].astype(str).isin(labeled_docs - existing_self)
    pop["has_existing_selfapproval_label"] = pop["document_id"].astype(str).isin(existing_self)
    pop["expected_l105_flag"] = True
    pop["truth_layer"] = "rule_contract_review_population"
    pop["self_approval_role"] = pop.apply(
        lambda row: "immediate_violation"
        if (
            (not bool(row["is_review_default"]))
            or bool(row["is_high_amount"])
            or bool(row["has_high_risk_account"])
        )
        else "review_required",
        axis=1,
    )
    pop["label_action"] = pop["has_existing_selfapproval_label"].map({True: "update_existing", False: "add_label"})
    pop["metadata_json"] = pop.apply(
        lambda row: json.dumps(
            {
                "v61_patch": "self_approval_truth_repair",
                "rule_id": "L1-05",
                "truth_layer": row["truth_layer"],
                "expected_l105_flag": True,
                "created_by": row["created_by"],
                "approved_by": row["approved_by"],
                "source": row["source"],
                "user_persona": row["user_persona"],
                "business_process": row["business_process"],
                "document_amount": int(float(row["document_amount"])),
                "self_approval_role": row["self_approval_role"],
                "review_default_process": bool(row["is_review_default"]),
                "high_amount_override": bool(row["is_high_amount"]),
                "high_risk_account_override": bool(row["has_high_risk_account"]),
                "has_other_label": bool(row["has_other_label"]),
                "anti_fitting_note": "L1-05 truth is derived from the field contract, not detector output.",
            },
            ensure_ascii=False,
        ),
        axis=1,
    )
    return pop


def _write_json(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_sidecar_split(df: pd.DataFrame, stem: str) -> None:
    cols = [
        "document_id",
        "fiscal_year",
        "company_code",
        "posting_date",
        "document_type",
        "document_number",
        "source",
        "business_process",
        "created_by",
        "approved_by",
        "approval_date",
        "user_persona",
        "document_amount",
        "gl_accounts",
        "expected_l105_flag",
        "self_approval_role",
        "truth_layer",
        "has_other_label",
    ]
    df[cols].to_csv(MANIFEST_DIR / f"{stem}.csv", index=False)
    _write_json(MANIFEST_DIR / f"{stem}.json", df[cols].where(pd.notna(df[cols]), None).to_dict(orient="records"))
    for year in YEARS:
        subset = df.loc[df["fiscal_year"].eq(year), cols]
        subset.to_csv(MANIFEST_DIR / f"{stem}_{year}.csv", index=False)
        _write_json(MANIFEST_DIR / f"{stem}_{year}.json", subset.where(pd.notna(subset), None).to_dict(orient="records"))


def main() -> None:
    if not SOURCE_DIR.exists():
        raise SystemExit(f"missing source: {SOURCE_DIR}")
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)

    docs = _doc_frame(_read_docs())
    labels = _existing_labels()
    population = _risk_rows(_truth_population(docs), labels).sort_values(
        ["fiscal_year", "posting_date", "company_code", "document_id"],
        kind="stable",
    )

    label_cols = [
        "document_id",
        "fiscal_year",
        "company_code",
        "posting_date",
        "document_type",
        "document_number",
        "source",
        "business_process",
        "created_by",
        "approved_by",
        "user_persona",
        "document_amount",
        "self_approval_role",
        "label_action",
        "metadata_json",
    ]
    population[label_cols].to_csv(MANIFEST_DIR / "self_approval_label_manifest.csv", index=False)
    _write_sidecar_split(population, "self_approval_review_population")

    controls = docs.loc[
        docs["created_by"].fillna("").astype(str).str.strip().eq(
            docs["approved_by"].fillna("").astype(str).str.strip()
        )
        & (
            docs["user_persona"].fillna("").astype(str).str.strip().str.lower().isin(ALLOW_PERSONAS)
            | docs["source"].fillna("").astype(str).str.strip().str.lower().isin(ALLOW_SOURCES)
        )
    ].copy()
    controls["expected_l105_flag"] = False
    controls["self_approval_role"] = "allowed_system_context"
    controls["truth_layer"] = "normal_control"
    controls["has_other_label"] = False
    _write_sidecar_split(controls, "self_approval_normal_controls")

    summary = {
        "candidate_version": "v61",
        "source_baseline": "data/journal/primary/datasynth_v60_candidate",
        "patch_scope": "L1-05 SelfApproval truth-layer repair",
        "review_population_docs": int(len(population)),
        "normal_control_docs": int(len(controls)),
        "label_actions": population["label_action"].value_counts().to_dict(),
        "year_counts": {str(int(k)): int(v) for k, v in population["fiscal_year"].value_counts().sort_index().to_dict().items()},
        "role_counts": population["self_approval_role"].value_counts().to_dict(),
        "existing_selfapproval_labels": int(labels["anomaly_type"].eq("SelfApproval").sum()),
        "anti_fitting_note": (
            "All L1-05 truth rows are derived from created_by == approved_by with explicit system allowlist "
            "exclusions. This repairs a data-contract gap rather than sampling detector hits."
        ),
    }
    (MANIFEST_DIR / "self_approval_manifest_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (MANIFEST_DIR / "PATCH_PLAN.md").write_text(
        "# DataSynth v61 Patch Manifest\n\n"
        "Source: `data/journal/primary/datasynth_v60_candidate`\n\n"
        "Scope: repair L1-05 SelfApproval truth contract.\n\n"
        "- Do not mutate JE fields.\n"
        "- Add/update `SelfApproval` labels for every non-system `created_by == approved_by` document.\n"
        "- Write `self_approval_review_population*` sidecars for Phase 1 population evaluation.\n"
        "- Keep explicit system/automated self-approval controls separate.\n"
        "- This is not based on detector output; it is derived from the rule input contract.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
