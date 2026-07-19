from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def load_year_file(base_dir: Path, year: int) -> pd.DataFrame:
    path = base_dir / f"journal_entries_{year}.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    return pd.read_csv(path, low_memory=False)


def non_empty_ratio(series: pd.Series) -> float:
    if series.empty:
        return 0.0
    values = series.fillna("").astype(str).str.strip()
    return float((values != "").mean())


def true_ratio(series: pd.Series) -> float:
    if series.empty:
        return 0.0
    normalized = (
        series.fillna(False)
        .astype(str)
        .str.strip()
        .str.lower()
        .isin(["true", "1", "yes", "y"])
    )
    return float(normalized.mean())


def summarize_year(base_dir: Path, year: int) -> dict[str, object]:
    df = load_year_file(base_dir, year)
    source = df["source"].fillna("").astype(str).str.lower() if "source" in df.columns else pd.Series([], dtype=str)
    return {
        "year": year,
        "rows": len(df),
        "documents": df["document_id"].nunique() if "document_id" in df.columns else 0,
        "fraud_rate_pct": round(true_ratio(df["is_fraud"]) * 100, 2) if "is_fraud" in df.columns else None,
        "anomaly_rate_pct": round(true_ratio(df["is_anomaly"]) * 100, 2) if "is_anomaly" in df.columns else None,
        "sod_rate_pct": round(true_ratio(df["sod_violation"]) * 100, 2) if "sod_violation" in df.columns else None,
        "manual_ratio_pct": round(float((source == "manual").mean()) * 100, 2) if not source.empty else None,
        "automated_ratio_pct": round(float((source == "automated").mean()) * 100, 2) if not source.empty else None,
        "cost_center_pct": round(non_empty_ratio(df["cost_center"]) * 100, 2) if "cost_center" in df.columns else None,
        "tax_code_pct": round(non_empty_ratio(df["tax_code"]) * 100, 2) if "tax_code" in df.columns else None,
        "trading_partner_pct": round(non_empty_ratio(df["trading_partner"]) * 100, 2) if "trading_partner" in df.columns else None,
        "user_persona_distinct": int(df["user_persona"].nunique(dropna=True)) if "user_persona" in df.columns else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Report yearly drift across DataSynth yearly JE CSV files.")
    parser.add_argument("base_dir", type=Path, help="Directory containing journal_entries_YYYY.csv files")
    parser.add_argument("--years", nargs="+", type=int, default=[2022, 2023, 2024], help="Years to summarize")
    args = parser.parse_args()

    rows = [summarize_year(args.base_dir, year) for year in args.years]
    report = pd.DataFrame(rows)
    print(report.to_string(index=False))


if __name__ == "__main__":
    main()
