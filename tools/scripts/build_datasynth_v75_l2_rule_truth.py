"""Build v75 candidate by deriving L2-03/L2-04/L2-05 rule truth from rules.

This patch does not alter journal rows. It starts from v74 and replaces the
remaining label-fallback L2 rule truth with the actual Phase 1 rule-condition
population produced by the rule functions.
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

from config.settings import get_audit_rules, get_settings  # noqa: E402
from src.detection.anomaly_rules_reversal import c11_reversal_entry  # noqa: E402
from src.detection.fraud_rules_groupby import b05_duplicate_entry, b11_expense_capitalization  # noqa: E402

SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v74_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v75_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
V73_PATH = ROOT / "tools" / "scripts" / "build_datasynth_v73_rule_truth.py"
YEAR_SUFFIX_RE = re.compile(r"_20\d{2}$")

RULE_INPUT_COLUMNS = [
    "document_id",
    "fiscal_year",
    "company_code",
    "document_number",
    "document_type",
    "business_process",
    "source",
    "created_by",
    "approved_by",
    "posting_date",
    "document_date",
    "reference",
    "header_text",
    "line_text",
    "gl_account",
    "debit_amount",
    "credit_amount",
    "trading_partner",
    "auxiliary_account_number",
    "auxiliary_account_label",
    "vendor_name",
    "customer_name",
    "counterparty_code",
    "counterparty_name",
    "original_document_id",
    "reversal_document_id",
    "reference_document_id",
    "reversed_document_id",
    "reverse_document_id",
    "reversal_reason",
    "reversal_reason_code",
]


def _load_v73_module():
    spec = importlib.util.spec_from_file_location("build_datasynth_v73_rule_truth", V73_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {V73_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_year(year: int) -> pd.DataFrame:
    path = DEST / f"journal_entries_{year}.csv"
    available = pd.read_csv(path, nrows=0).columns.tolist()
    cols = [col for col in RULE_INPUT_COLUMNS if col in available]
    frame = pd.read_csv(path, dtype=str, usecols=cols, low_memory=False)
    for col in RULE_INPUT_COLUMNS:
        if col not in frame.columns:
            frame[col] = pd.NA
    frame = frame[RULE_INPUT_COLUMNS].copy()
    frame["fiscal_year"] = frame["fiscal_year"].fillna(str(year))
    return frame


def _read_rows() -> pd.DataFrame:
    frames = [_read_year(year) for year in YEARS]
    rows = pd.concat(frames, ignore_index=True)
    for col in ("debit_amount", "credit_amount"):
        rows[col] = pd.to_numeric(rows[col], errors="coerce").fillna(0.0)
    return rows


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
    return (
        rows[context_cols]
        .dropna(subset=["document_id"])
        .drop_duplicates(subset=["document_id"], keep="first")
        .copy()
    )


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_rule_truth(rule_id: str, docs: pd.DataFrame, basis: str, metadata: dict[str, object]) -> pd.DataFrame:
    out = docs.copy()
    out["rule_id"] = rule_id
    out["expected_hit"] = True
    out["truth_layer"] = "rule_truth"
    out["truth_basis"] = basis
    out["evaluation_unit"] = "document"
    for key, value in metadata.items():
        out[key] = value

    stem = f"rule_truth_{rule_id.replace('-', '_')}"
    out.to_csv(LABELS / f"{stem}.csv", index=False)
    _write_json_records(LABELS / f"{stem}.json", out)
    for year in YEARS:
        subset = out.loc[out["fiscal_year"].astype(str).eq(str(year))]
        subset.to_csv(LABELS / f"{stem}_{year}.csv", index=False)
        _write_json_records(LABELS / f"{stem}_{year}.json", subset)
    return out


def _docs_from_flag(rows: pd.DataFrame, flag: pd.Series, rule_name: str) -> pd.DataFrame:
    flagged = rows.loc[flag.fillna(False).astype(bool)].copy()
    if flagged.empty:
        return _doc_context(rows).iloc[0:0].copy()
    counts = flagged.groupby("document_id", as_index=False).size().rename(columns={"size": "flagged_row_count"})
    docs = _doc_context(rows).merge(counts, on="document_id", how="inner")
    docs["detector_rule_name"] = rule_name
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


def _build_base_v75() -> None:
    v73 = _load_v73_module()
    os.environ["DATASYNTH_RULE_TRUTH_SOURCE"] = str(SOURCE)
    os.environ["DATASYNTH_RULE_TRUTH_DEST"] = str(DEST)
    v73.SRC = SOURCE
    v73.DEST = DEST
    v73.LABELS = LABELS
    v73._materialize_candidate()
    v73.build_truth()


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")

    _build_base_v75()
    rows = _read_rows()
    settings = get_settings()
    audit_rules = get_audit_rules()

    l203_flag = b05_duplicate_entry(
        rows,
        amount_tolerance=settings.duplicate_amount_tolerance,
        fuzzy_threshold=settings.duplicate_fuzzy_threshold,
        window_days=settings.duplicate_time_window_days,
        split_window_days=settings.duplicate_split_window_days,
        max_group_size=settings.duplicate_max_group_size,
    )
    l204_flag = b11_expense_capitalization(
        rows,
        audit_rules=audit_rules,
        amount_tolerance=settings.expense_capitalization_amount_tolerance,
        min_amount=settings.expense_capitalization_min_amount,
        review_threshold=settings.expense_capitalization_review_threshold,
        immediate_threshold=settings.expense_capitalization_immediate_threshold,
    )
    l205_flag = c11_reversal_entry(
        rows,
        match_window_days=settings.reversal_match_window_days,
        rolling_window_days=settings.reversal_rolling_window_days,
        zero_threshold=settings.reversal_zero_threshold,
        score_threshold=settings.reversal_score_threshold,
    )

    replacements = {
        "L2-03": _write_rule_truth(
            "L2-03",
            _docs_from_flag(rows, l203_flag, "b05_duplicate_entry"),
            "actual duplicate-entry rule candidate population, including exact/reference/near/split signals",
            {
                "truth_derivation": "src.detection.fraud_rules_groupby.b05_duplicate_entry",
                "source_candidate": "v74",
            },
        ),
        "L2-04": _write_rule_truth(
            "L2-04",
            _docs_from_flag(rows, l204_flag, "b11_expense_capitalization"),
            "actual expense-capitalization rule candidate population using configured review threshold",
            {
                "truth_derivation": "src.detection.fraud_rules_groupby.b11_expense_capitalization",
                "source_candidate": "v74",
            },
        ),
        "L2-05": _write_rule_truth(
            "L2-05",
            _docs_from_flag(rows, l205_flag, "c11_reversal_entry"),
            "actual reversal-pattern rule candidate population using configured composite score",
            {
                "truth_derivation": "src.detection.anomaly_rules_reversal.c11_reversal_entry",
                "source_candidate": "v74",
            },
        ),
    }
    rule_counts = _rebuild_combined_rule_truth()

    summary = {
        "candidate_version": "v75",
        "source_baseline": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "patch_scope": "replace L2-03/L2-04/L2-05 label-fallback truth with actual rule-condition truth",
        "replaced_rule_counts": {rule: int(len(df)) for rule, df in replacements.items()},
        "all_rule_counts": rule_counts,
        "anti_fitting_note": (
            "This is not injected-fraud truth. It stores the rule candidate population so "
            "Phase 1 can verify what each rule should surface; audit issue truth remains separate."
        ),
    }
    (DEST / "V75_L2_RULE_TRUTH_PATCH.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V75_CANDIDATE.md").write_text(
        "# DataSynth v75 Candidate\n\n"
        f"Source baseline: `{summary['source_baseline']}`.\n\n"
        "Scope: derive L2-03/L2-04/L2-05 rule truth from the actual Phase 1 rule functions.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
