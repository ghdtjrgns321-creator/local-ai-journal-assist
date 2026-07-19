"""Build DataSynth v29 candidate by realigning MisclassifiedAccount to L3-01.

This patch changes MisclassifiedAccount documents so their GL accounts violate
the process-category logic used by Phase 1 L3-01.
"""

from __future__ import annotations

import json
import random
import shutil
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v28_candidate"
if not SOURCE_DIR.exists():
    SOURCE_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v27_candidate"
TARGET_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v29_candidate"
TARGET_LABEL = "MisclassifiedAccount"

CATEGORY_PREFIXES = {
    "asset": ["1"],
    "liability": ["2"],
    "equity": ["3"],
    "revenue": ["4"],
    "expense": ["5", "6", "7", "8"],
    "payroll": ["54", "64", "74"],
    "inventory": ["12"],
}

PROCESS_DISALLOWED = {
    "O2C": ["expense", "payroll", "inventory", "equity"],
    "P2P": ["revenue", "equity"],
    "H2R": ["revenue", "inventory", "equity"],
    "TRE": ["revenue", "expense", "payroll", "inventory"],
    "A2R": ["revenue", "payroll"],
}

PROCESS_TARGET_CATEGORY = {
    "O2C": "expense",
    "P2P": "revenue",
    "H2R": "revenue",
    "TRE": "inventory",
    "A2R": "payroll",
}


def _copy_source() -> None:
    if TARGET_DIR.exists():
        shutil.rmtree(TARGET_DIR)
    shutil.copytree(SOURCE_DIR, TARGET_DIR)


def _normalize_account(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip().replace(".0", "")


def _infer_category(account: object) -> str:
    code = _normalize_account(account)
    if not code:
        return ""
    items = [
        (category, prefix)
        for category, prefixes in CATEGORY_PREFIXES.items()
        for prefix in prefixes
    ]
    items.sort(key=lambda item: len(item[1]), reverse=True)
    for category, prefix in items:
        if code.startswith(prefix):
            return category
    return ""


def _build_category_account_pool(df: pd.DataFrame) -> dict[str, list[str]]:
    accounts = pd.Series(df["gl_account"].dropna().astype(str).map(_normalize_account).unique())
    pool: dict[str, list[str]] = {}
    for account in accounts:
        category = _infer_category(account)
        if not category:
            continue
        pool.setdefault(category, []).append(account)
    for category in pool:
        pool[category] = sorted(set(pool[category]))
    return pool


def _load_misclassified_docs(df: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    target_docs = labels.loc[labels["anomaly_type"].eq(TARGET_LABEL), "document_id"].astype(str).unique().tolist()
    doc = df.loc[df["document_id"].astype(str).isin(target_docs)].groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", "first"),
        company_code=("company_code", "first"),
        business_process=("business_process", "first"),
        document_type=("document_type", "first"),
        document_number=("document_number", "first"),
    )
    return doc


def _pick_target_account(process: str, category_pool: dict[str, list[str]], rng: random.Random) -> tuple[str, str]:
    desired = PROCESS_TARGET_CATEGORY.get(process)
    allowed = PROCESS_DISALLOWED.get(process, [])
    if desired in allowed and desired in category_pool and category_pool[desired]:
        return desired, rng.choice(category_pool[desired])
    for category in allowed:
        if category in category_pool and category_pool[category]:
            return category, rng.choice(category_pool[category])
    raise RuntimeError(f"no disallowed account pool for process {process}")


def _rewrite_document_accounts(
    df: pd.DataFrame,
    *,
    document_id: str,
    process: str,
    category_pool: dict[str, list[str]],
) -> dict[str, object]:
    rng = random.Random(f"v29:{document_id}:{process}")
    mask = df["document_id"].astype(str).eq(document_id)
    rows = df.loc[mask].copy()
    if rows.empty:
        raise RuntimeError(f"document not found: {document_id}")

    candidate_idx = rows.index[
        rows["gl_account"].map(_infer_category).ne(PROCESS_TARGET_CATEGORY.get(process, ""))
    ].tolist()
    if not candidate_idx:
        candidate_idx = rows.index.tolist()
    target_idx = candidate_idx[0]
    before = _normalize_account(df.at[target_idx, "gl_account"])
    before_category = _infer_category(before)
    target_category, target_account = _pick_target_account(process, category_pool, rng)
    if before == target_account and len(candidate_idx) > 1:
        target_idx = candidate_idx[1]
        before = _normalize_account(df.at[target_idx, "gl_account"])
        before_category = _infer_category(before)
    df.at[target_idx, "gl_account"] = target_account
    return {
        "document_id": document_id,
        "line_number": int(df.at[target_idx, "line_number"]) if "line_number" in df.columns and pd.notna(df.at[target_idx, "line_number"]) else None,
        "business_process": process,
        "from_account": before,
        "from_category": before_category,
        "to_account": target_account,
        "to_category": target_category,
    }


def _write_labels(labels: pd.DataFrame) -> None:
    labels_dir = TARGET_DIR / "labels"
    labels.to_csv(labels_dir / "anomaly_labels.csv", index=False)
    records = labels.where(pd.notna(labels), None).to_dict(orient="records")
    (labels_dir / "anomaly_labels.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    with (labels_dir / "anomaly_labels.jsonl").open("w", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_year_splits(df: pd.DataFrame) -> None:
    for year in (2022, 2023, 2024, 2025):
        subset = df.loc[pd.to_numeric(df["fiscal_year"], errors="coerce").eq(year)]
        path = TARGET_DIR / f"journal_entries_{year}.csv"
        if subset.empty:
            if path.exists():
                path.unlink()
            continue
        subset.to_csv(path, index=False)


def main() -> None:
    _copy_source()
    df = pd.read_csv(TARGET_DIR / "journal_entries.csv", low_memory=False)
    if "gl_account" in df.columns:
        df["gl_account"] = df["gl_account"].map(_normalize_account)
    labels = pd.read_csv(TARGET_DIR / "labels" / "anomaly_labels.csv")
    mis_docs = _load_misclassified_docs(df, labels)
    category_pool = _build_category_account_pool(df)

    cases: list[dict[str, object]] = []
    for row in mis_docs.itertuples(index=False):
        process = str(row.business_process)
        if process not in PROCESS_DISALLOWED or not PROCESS_DISALLOWED[process]:
            continue
        case = _rewrite_document_accounts(
            df,
            document_id=str(row.document_id),
            process=process,
            category_pool=category_pool,
        )
        case["fiscal_year"] = int(row.fiscal_year)
        case["company_code"] = row.company_code
        case["document_number"] = row.document_number
        cases.append(case)

    cases_df = pd.DataFrame(cases)
    labels.loc[labels["anomaly_type"].eq(TARGET_LABEL), "metadata_json"] = labels.loc[
        labels["anomaly_type"].eq(TARGET_LABEL), "document_id"
    ].map(
        cases_df.set_index("document_id").apply(
            lambda row: json.dumps(
                {
                    "document_number": row["document_number"],
                    "business_process": row["business_process"],
                    "from_account": row["from_account"],
                    "from_category": row["from_category"],
                    "to_account": row["to_account"],
                    "to_category": row["to_category"],
                },
                ensure_ascii=False,
            ),
            axis=1,
        ).to_dict()
    ).fillna(labels.loc[labels["anomaly_type"].eq(TARGET_LABEL), "metadata_json"])

    df.to_csv(TARGET_DIR / "journal_entries.csv", index=False)
    _write_year_splits(df)
    _write_labels(labels)

    labels_dir = TARGET_DIR / "labels"
    cases_df.to_csv(labels_dir / "misclassified_account_cases.csv", index=False)
    (labels_dir / "misclassified_account_cases.json").write_text(
        json.dumps(cases_df.to_dict(orient="records"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    summary = {
        "source_baseline": str(SOURCE_DIR.relative_to(ROOT).as_posix()),
        "misclassified_docs": int(len(cases_df)),
        "year_counts": {str(int(k)): int(v) for k, v in cases_df["fiscal_year"].value_counts().sort_index().to_dict().items()},
        "process_counts": {str(k): int(v) for k, v in cases_df["business_process"].value_counts().to_dict().items()},
        "target_category_counts": {str(k): int(v) for k, v in cases_df["to_category"].value_counts().to_dict().items()},
    }
    (TARGET_DIR / "V29_MISCLASSIFIED_ACCOUNT_PATCH.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (TARGET_DIR / "PREVIEW.md").write_text(
        "# DataSynth v29 Candidate Preview\n\n"
        "Status: candidate only. Production data remains unchanged.\n\n"
        "This candidate realigns `MisclassifiedAccount` to the L3-01 process-category mismatch definition.\n",
        encoding="utf-8",
    )
    (TARGET_DIR / "FREEZE_V29_CANDIDATE.md").write_text(
        "# DataSynth v29 Candidate\n\n"
        f"Source baseline: `{SOURCE_DIR.relative_to(ROOT).as_posix()}`\n\n"
        f"Summary: `{json.dumps(summary, ensure_ascii=False)}`\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
