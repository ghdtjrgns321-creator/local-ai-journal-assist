"""Build v87 candidate by realigning L3-03 population truth.

L3-03 is a population/review rule. The current detector contract flags rows
where ``is_intercompany`` is true, and that feature is derived from configured
intercompany GL account prefixes. DataSynth should therefore use the same GL
prefix population as official L3-03 rule truth unless a separate related-party
master is introduced.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v86_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v87_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
RULE_ID = "L3-03"


def _copy_candidate_safely() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(SOURCE, DEST, copy_function=shutil.copy2)


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _ic_prefixes() -> tuple[str, ...]:
    config_path = ROOT / "config" / "audit_rules.yaml"
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    pairs = (((raw.get("patterns") or {}).get("intercompany") or {}).get("pairs") or [])
    prefixes: list[str] = []
    for pair in pairs:
        for key in ("receivable", "payable"):
            value = str(pair.get(key, "")).strip()
            if value:
                prefixes.append(value)
    if not prefixes:
        prefixes = ["1150", "2050", "4500", "2700"]
    return tuple(dict.fromkeys(prefixes))


def _read_year_rows() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for year in YEARS:
        frame = pd.read_csv(DEST / f"journal_entries_{year}.csv", dtype=str, low_memory=False)
        frame["_year_file"] = str(year)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True, sort=False)


def _unique_join(values: pd.Series) -> str:
    cleaned = values.dropna().astype(str).map(str.strip)
    cleaned = cleaned[cleaned.ne("")]
    return "|".join(sorted(cleaned.unique()))


def _load_label_types() -> dict[str, str]:
    path = LABELS / "anomaly_labels.csv"
    if not path.exists():
        return {}
    labels = pd.read_csv(path, dtype=str, usecols=["document_id", "anomaly_type"])
    return labels.groupby("document_id")["anomaly_type"].apply(lambda s: "|".join(sorted(set(s.dropna().astype(str))))).to_dict()


def _build_l303_population(rows: pd.DataFrame, prefixes: tuple[str, ...]) -> pd.DataFrame:
    gl = rows["gl_account"].fillna("").astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
    ic_mask = gl.str.startswith(prefixes)
    ic_rows = rows.loc[ic_mask].copy()
    ic_rows["_normalized_gl_account"] = gl.loc[ic_mask]
    ic_rows["_ic_prefix"] = ""
    for prefix in prefixes:
        ic_rows.loc[ic_rows["_normalized_gl_account"].str.startswith(prefix), "_ic_prefix"] = prefix

    label_types = _load_label_types()
    truth = ic_rows.groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", "first"),
        company_code=("company_code", "first"),
        document_number=("document_number", "first"),
        document_type=("document_type", "first"),
        posting_date=("posting_date", "first"),
        business_process=("business_process", "first"),
        source=("source", "first"),
        created_by=("created_by", "first"),
        ic_account_prefixes=("_ic_prefix", _unique_join),
        ic_gl_accounts=("_normalized_gl_account", _unique_join),
        has_trading_partner=("trading_partner", lambda s: bool(s.dropna().astype(str).str.strip().ne("").any())),
        trading_partners=("trading_partner", _unique_join),
    )
    truth["rule_id"] = RULE_ID
    truth["expected_hit"] = True
    truth["truth_layer"] = "rule_truth"
    truth["truth_basis"] = "intercompany GL account prefix population matching current L3-03 detector contract"
    truth["population_basis"] = "ic_gl_account_prefix"
    truth["evaluation_unit"] = "document"
    truth["related_anomaly_types"] = truth["document_id"].map(label_types).fillna("")
    truth["has_any_anomaly_label"] = truth["related_anomaly_types"].ne("")
    columns = [
        "document_id",
        "fiscal_year",
        "company_code",
        "document_number",
        "document_type",
        "posting_date",
        "business_process",
        "source",
        "created_by",
        "rule_id",
        "expected_hit",
        "truth_layer",
        "truth_basis",
        "population_basis",
        "evaluation_unit",
        "ic_account_prefixes",
        "ic_gl_accounts",
        "has_trading_partner",
        "trading_partners",
        "has_any_anomaly_label",
        "related_anomaly_types",
    ]
    return truth[columns].sort_values(["fiscal_year", "company_code", "document_number", "document_id"]).reset_index(drop=True)


def _write_l303_truth(truth: pd.DataFrame) -> None:
    for stem in ("rule_truth_L3_03", "intercompany_population_truth"):
        truth.to_csv(LABELS / f"{stem}.csv", index=False, encoding="utf-8")
        _write_json_records(LABELS / f"{stem}.json", truth)
        for year in YEARS:
            year_df = truth.loc[truth["fiscal_year"].astype(str).eq(str(year))].copy()
            year_df.to_csv(LABELS / f"{stem}_{year}.csv", index=False, encoding="utf-8")
            _write_json_records(LABELS / f"{stem}_{year}.json", year_df)


def _rebuild_combined_rule_truth() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        stem = path.stem
        if stem.rsplit("_", 1)[-1] in {"2022", "2023", "2024"}:
            continue
        frames.append(pd.read_csv(path, dtype=str))
    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined.to_csv(LABELS / "rule_truth.csv", index=False, encoding="utf-8")
    _write_json_records(LABELS / "rule_truth.json", combined)
    return combined


def main() -> None:
    _copy_candidate_safely()
    rows = _read_year_rows()
    prefixes = _ic_prefixes()
    old_truth = pd.read_csv(LABELS / "rule_truth_L3_03.csv", dtype=str)
    old_docs = set(old_truth["document_id"].astype(str))

    truth = _build_l303_population(rows, prefixes)
    _write_l303_truth(truth)
    combined = _rebuild_combined_rule_truth()

    new_docs = set(truth["document_id"].astype(str))
    by_year = truth.groupby("fiscal_year")["document_id"].nunique().to_dict()
    by_process = truth["business_process"].value_counts().sort_index().to_dict()
    summary = {
        "candidate": "v87",
        "source": str(SOURCE.relative_to(ROOT)),
        "destination": str(DEST.relative_to(ROOT)),
        "purpose": "realign L3-03 rule truth to intercompany GL-prefix detector contract",
        "ic_prefixes": list(prefixes),
        "old_l303_truth_docs": int(len(old_docs)),
        "new_l303_truth_docs": int(len(new_docs)),
        "old_minus_new_docs": int(len(old_docs - new_docs)),
        "new_minus_old_docs": int(len(new_docs - old_docs)),
        "new_l303_truth_by_year": {str(k): int(v) for k, v in by_year.items()},
        "new_l303_truth_by_process": {str(k): int(v) for k, v in by_process.items()},
        "combined_rule_truth_counts": {str(k): int(v) for k, v in combined["rule_id"].value_counts().sort_index().to_dict().items()},
    }
    (DEST / "V87_L303_RULE_TRUTH_REALIGNMENT.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (DEST / "FREEZE_V87_CANDIDATE.md").write_text(
        "\n".join(
            [
                "# DataSynth v87 Candidate",
                "",
                "Status: candidate, not promoted to production.",
                "",
                "Purpose: realign L3-03 population truth to the current detector contract.",
                "",
                f"- IC prefixes: `{summary['ic_prefixes']}`",
                f"- L3-03 old truth docs: `{summary['old_l303_truth_docs']}`",
                f"- L3-03 new truth docs: `{summary['new_l303_truth_docs']}`",
                f"- Old minus new: `{summary['old_minus_new_docs']}`",
                f"- New minus old: `{summary['new_minus_old_docs']}`",
                f"- By year: `{summary['new_l303_truth_by_year']}`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
