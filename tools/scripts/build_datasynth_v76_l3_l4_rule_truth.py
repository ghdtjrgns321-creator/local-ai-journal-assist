"""Build v76 candidate by deriving selected L3/L4 rule truth from rules."""

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

from config.settings import get_audit_rules, get_settings  # noqa: E402
from src.detection.anomaly_rules_simple import c01_period_end_large, c08_amount_outlier  # noqa: E402
from src.detection.fraud_rules_feature import b01_revenue_manipulation  # noqa: E402
from src.feature.amount_features import add_all_amount_features  # noqa: E402
from src.feature.pattern_features import add_all_pattern_features  # noqa: E402
from src.feature.time_features import add_all_time_features  # noqa: E402
from src.ingest.datasynth_labels import SOURCE_PATH_ATTR  # noqa: E402


SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v75_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v76_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
V73_PATH = ROOT / "tools" / "scripts" / "build_datasynth_v73_rule_truth.py"
YEAR_SUFFIX_RE = re.compile(r"_20\d{2}$")

INPUT_COLUMNS = [
    "document_id",
    "fiscal_year",
    "company_code",
    "document_number",
    "document_type",
    "business_process",
    "source",
    "created_by",
    "approved_by",
    "approval_date",
    "posting_date",
    "document_date",
    "fiscal_period",
    "currency",
    "reference",
    "header_text",
    "line_text",
    "gl_account",
    "debit_amount",
    "credit_amount",
    "description_quality",
]


def _load_v73_module():
    spec = importlib.util.spec_from_file_location("build_datasynth_v73_rule_truth", V73_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {V73_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _materialize_from_v75() -> None:
    v73 = _load_v73_module()
    os.environ["DATASYNTH_RULE_TRUTH_SOURCE"] = str(SOURCE)
    os.environ["DATASYNTH_RULE_TRUTH_DEST"] = str(DEST)
    v73.SRC = SOURCE
    v73.DEST = DEST
    v73.LABELS = LABELS
    v73._materialize_candidate()


def _read_year(year: int) -> pd.DataFrame:
    path = DEST / f"journal_entries_{year}.csv"
    available = pd.read_csv(path, nrows=0).columns.tolist()
    cols = [col for col in INPUT_COLUMNS if col in available]
    frame = pd.read_csv(path, dtype=str, usecols=cols, low_memory=False)
    for col in INPUT_COLUMNS:
        if col not in frame.columns:
            frame[col] = pd.NA
    frame = frame[INPUT_COLUMNS].copy()
    frame["fiscal_year"] = frame["fiscal_year"].fillna(str(year))
    return frame


def _read_rows() -> pd.DataFrame:
    rows = pd.concat([_read_year(year) for year in YEARS], ignore_index=True)
    for col in ("posting_date", "document_date"):
        rows[col] = pd.to_datetime(rows[col], errors="coerce")
    rows["fiscal_period"] = pd.to_numeric(rows["fiscal_period"], errors="coerce")
    for col in ("debit_amount", "credit_amount"):
        rows[col] = pd.to_numeric(rows[col], errors="coerce").fillna(0.0)
    rows.attrs[SOURCE_PATH_ATTR] = str((DEST / "journal_entries_2022.csv").resolve())
    return rows


def _add_rule_features(rows: pd.DataFrame) -> pd.DataFrame:
    settings = get_settings()
    audit_rules = get_audit_rules()
    out = rows.copy()
    out.attrs[SOURCE_PATH_ATTR] = rows.attrs[SOURCE_PATH_ATTR]
    add_all_time_features(out, settings)
    add_all_amount_features(out, settings, audit_rules)
    add_all_pattern_features(out, audit_rules.get("patterns", {}))
    return out


def _doc_context(rows: pd.DataFrame) -> pd.DataFrame:
    context_cols = [
        "document_id",
        "fiscal_year",
        "company_code",
        "document_number",
        "document_type",
        "posting_date",
        "business_process",
        "source",
    ]
    docs = (
        rows[context_cols]
        .dropna(subset=["document_id"])
        .drop_duplicates(subset=["document_id"], keep="first")
        .copy()
    )
    docs["posting_date"] = docs["posting_date"].astype(str)
    return docs


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_rule_truth(rule_id: str, rows: pd.DataFrame, flag: pd.Series, basis: str, derivation: str) -> pd.DataFrame:
    flagged = rows.loc[flag.fillna(False).astype(bool)].copy()
    docs = _doc_context(flagged) if not flagged.empty else _doc_context(rows).iloc[0:0].copy()
    if not flagged.empty:
        counts = flagged.groupby("document_id", as_index=False).size().rename(columns={"size": "flagged_row_count"})
        docs = docs.merge(counts, on="document_id", how="left")
    else:
        docs["flagged_row_count"] = pd.Series(dtype="int64")
    docs["rule_id"] = rule_id
    docs["expected_hit"] = True
    docs["truth_layer"] = "rule_truth"
    docs["truth_basis"] = basis
    docs["evaluation_unit"] = "document"
    docs["truth_derivation"] = derivation
    docs["source_candidate"] = "v75"

    stem = f"rule_truth_{rule_id.replace('-', '_')}"
    docs.to_csv(LABELS / f"{stem}.csv", index=False)
    _write_json_records(LABELS / f"{stem}.json", docs)
    for year in YEARS:
        subset = docs.loc[docs["fiscal_year"].astype(str).eq(str(year))]
        subset.to_csv(LABELS / f"{stem}_{year}.csv", index=False)
        _write_json_records(LABELS / f"{stem}_{year}.json", subset)
    return docs


def _rebuild_combined_rule_truth() -> dict[str, int]:
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

    _materialize_from_v75()
    rows = _add_rule_features(_read_rows())
    settings = get_settings()
    patterns = get_audit_rules().get("patterns", {})

    l304_flag = c01_period_end_large(
        rows,
        quantile=settings.period_end_amount_quantile,
        min_group_size=settings.c01_min_group_size,
        whitelist_patterns=patterns.get("period_end_whitelist", []),
    )
    l401_flag = b01_revenue_manipulation(rows, zscore_threshold=settings.zscore_threshold)
    l403_flag = c08_amount_outlier(
        rows,
        zscore_threshold=settings.zscore_threshold,
        min_amount_quantile=settings.l403_min_amount_quantile,
    )

    replacements = {
        "L3-04": _write_rule_truth(
            "L3-04",
            rows,
            l304_flag,
            "actual period-end/start large or manual posting rule candidate population",
            "src.detection.anomaly_rules_simple.c01_period_end_large",
        ),
        "L4-01": _write_rule_truth(
            "L4-01",
            rows,
            l401_flag,
            "actual revenue-account amount z-score rule candidate population",
            "src.detection.fraud_rules_feature.b01_revenue_manipulation",
        ),
        "L4-03": _write_rule_truth(
            "L4-03",
            rows,
            l403_flag,
            "actual high-amount z-score rule candidate population with amount guard",
            "src.detection.anomaly_rules_simple.c08_amount_outlier",
        ),
    }
    rule_counts = _rebuild_combined_rule_truth()

    summary = {
        "candidate_version": "v76",
        "source_baseline": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "patch_scope": "replace L3-04/L4-01/L4-03 approximate or sidecar truth with actual feature-backed rule-condition truth",
        "replaced_rule_counts": {rule: int(len(df)) for rule, df in replacements.items()},
        "all_rule_counts": rule_counts,
        "anti_fitting_note": (
            "Truth is recomputed from project feature functions and rule functions. "
            "It is a Phase 1 candidate-population contract, not injected fraud truth."
        ),
    }
    (DEST / "V76_L3_L4_RULE_TRUTH_PATCH.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V76_CANDIDATE.md").write_text(
        "# DataSynth v76 Candidate\n\n"
        f"Source baseline: `{summary['source_baseline']}`.\n\n"
        "Scope: derive L3-04/L4-01/L4-03 rule truth from the feature-backed rule functions.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
