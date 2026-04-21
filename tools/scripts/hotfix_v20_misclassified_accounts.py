from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "journal" / "primary" / "datasynth"
HOTFIX_TS = "2026-04-21T00:20:00+09:00"

# Replace invalid MisclassifiedAccount targets with valid but still misclassified CoA accounts.
REPLACEMENTS = {
    "1300": "1500",
    "1400": "1600",
    "1700": "1200",
    "1800": "1100",
    "1900": "1150",
    "2800": "2700",
    "4200": "4100",
    "4300": "4500",
    "4400": "4600",
    "4800": "4600",
    "5400": "6400",
    "5500": "6700",
    "5600": "6500",
    "5700": "6800",
    "5800": "6000",
    "9990": "9300",
}


def main() -> None:
    valid_accounts = load_valid_accounts()
    missing = sorted(set(REPLACEMENTS.values()) - valid_accounts)
    if missing:
        raise RuntimeError(f"Replacement targets missing from CoA: {missing}")

    summary: dict[str, object] = {
        "hotfixed_at": HOTFIX_TS,
        "replacement_map": REPLACEMENTS,
        "years": {},
    }

    year_frames: list[pd.DataFrame] = []
    for year in (2022, 2023, 2024):
        path = DATA_DIR / f"journal_entries_{year}.csv"
        df = pd.read_csv(path, low_memory=False)
        updated_df, year_summary = hotfix_year(df)
        updated_df.to_csv(path, index=False)
        year_frames.append(updated_df)
        summary["years"][str(year)] = year_summary

    carry_paths = [DATA_DIR / "journal_entries_2025.csv"]
    for path in carry_paths:
        if path.exists():
            year_frames.append(pd.read_csv(path, low_memory=False))

    combined = pd.concat(year_frames, ignore_index=True)
    combined.sort_values(["fiscal_year", "posting_date", "document_number", "line_number"], inplace=True)
    combined.to_csv(DATA_DIR / "journal_entries.csv", index=False)

    (DATA_DIR / "V20_1_MISCLASSIFIED_ACCOUNT_HOTFIX.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_valid_accounts() -> set[str]:
    coa = json.loads((DATA_DIR / "chart_of_accounts.json").read_text(encoding="utf-8"))
    return {str(account["account_number"]) for account in coa["accounts"]}


def hotfix_year(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    gl_norm = df["gl_account"].astype(str).str.replace(".0", "", regex=False)
    mask = (df["anomaly_type"].fillna("") == "MisclassifiedAccount") & gl_norm.isin(REPLACEMENTS)
    before_docs = int(df.loc[mask, "document_id"].nunique())
    before_rows = int(mask.sum())
    before_counts = gl_norm[mask].value_counts().sort_index().to_dict()

    df.loc[mask, "gl_account"] = gl_norm[mask].map(REPLACEMENTS)

    after_norm = df["gl_account"].astype(str).str.replace(".0", "", regex=False)
    residual = (df["anomaly_type"].fillna("") == "MisclassifiedAccount") & after_norm.isin(REPLACEMENTS)
    if residual.any():
        raise RuntimeError("Residual invalid MisclassifiedAccount codes remain after hotfix")

    return df, {
        "documents_updated": before_docs,
        "rows_updated": before_rows,
        "before_counts": before_counts,
    }


if __name__ == "__main__":
    main()
