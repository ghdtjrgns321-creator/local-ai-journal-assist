"""Build v77 candidate by expanding L1-06/L1-07 rule truth to review candidates."""

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
from src.detection.fraud_rules_access import (  # noqa: E402
    b07_segregation_of_duties,
    b09_skipped_approval,
    build_access_rule_cache,
)
from src.feature.amount_features import add_all_amount_features  # noqa: E402
from src.feature.pattern_features import add_all_pattern_features  # noqa: E402
from src.feature.time_features import add_all_time_features  # noqa: E402
from src.ingest.datasynth_labels import SOURCE_PATH_ATTR  # noqa: E402


SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v76_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v77_candidate"
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
    "user_persona",
    "reference",
    "header_text",
    "line_text",
    "gl_account",
    "debit_amount",
    "credit_amount",
    "sod_violation",
    "sod_conflict_type",
    "description_quality",
    "lettrage",
    "lettrage_date",
    "amount_open",
    "is_cleared",
    "settlement_status",
    "settlement_date",
]


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
    for col in ("posting_date", "document_date", "approval_date", "lettrage_date", "settlement_date"):
        rows[col] = pd.to_datetime(rows[col], errors="coerce")
    rows["fiscal_period"] = pd.to_numeric(rows["fiscal_period"], errors="coerce")
    for col in ("debit_amount", "credit_amount", "amount_open"):
        rows[col] = pd.to_numeric(rows[col], errors="coerce")
    rows[["debit_amount", "credit_amount"]] = rows[["debit_amount", "credit_amount"]].fillna(0.0)
    rows.attrs[SOURCE_PATH_ATTR] = str((DEST / "journal_entries_2022.csv").resolve())
    return rows


def _add_features(rows: pd.DataFrame) -> pd.DataFrame:
    settings = get_settings()
    audit_rules = get_audit_rules()
    out = rows.copy()
    out.attrs[SOURCE_PATH_ATTR] = rows.attrs[SOURCE_PATH_ATTR]
    add_all_time_features(out, settings)
    add_all_amount_features(out, settings, audit_rules)
    add_all_pattern_features(out, audit_rules.get("patterns", {}))
    return out


def _truth_flag_from_rule_result(result: pd.Series) -> pd.Series:
    flag = result.fillna(False).astype(bool).copy()
    review_scores = result.attrs.get("review_score_series")
    if review_scores is not None:
        review = pd.Series(review_scores, index=result.index).fillna(0.0).astype(float).gt(0.0)
        flag = flag | review
    return flag


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
    docs = rows[cols].dropna(subset=["document_id"]).drop_duplicates("document_id").copy()
    docs["posting_date"] = docs["posting_date"].astype(str)
    return docs


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_rule_truth(rule_id: str, rows: pd.DataFrame, flag: pd.Series, basis: str, derivation: str) -> pd.DataFrame:
    flagged = rows.loc[flag.fillna(False).astype(bool)]
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
    docs["source_candidate"] = "v76"

    stem = f"rule_truth_{rule_id.replace('-', '_')}"
    docs.to_csv(LABELS / f"{stem}.csv", index=False)
    _write_json_records(LABELS / f"{stem}.json", docs)
    for year in YEARS:
        subset = docs.loc[docs["fiscal_year"].astype(str).eq(str(year))]
        subset.to_csv(LABELS / f"{stem}_{year}.csv", index=False)
        _write_json_records(LABELS / f"{stem}_{year}.json", subset)
    return docs


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
    rows = _add_features(_read_rows())
    settings = get_settings()
    audit_rules = get_audit_rules()
    cache = build_access_rule_cache(rows)

    l106_result = b07_segregation_of_duties(
        rows,
        sod_threshold=settings.sod_process_threshold,
        audit_rules=audit_rules,
        cache=cache,
    )
    l107_result = b09_skipped_approval(rows, audit_rules=audit_rules, cache=cache)
    l106_flag = _truth_flag_from_rule_result(l106_result)
    l107_flag = _truth_flag_from_rule_result(l107_result)

    replacements = {
        "L1-06": _write_rule_truth(
            "L1-06",
            rows,
            l106_flag,
            "actual segregation-of-duties immediate or review candidate population",
            "src.detection.fraud_rules_access.b07_segregation_of_duties + review_score_series",
        ),
        "L1-07": _write_rule_truth(
            "L1-07",
            rows,
            l107_flag,
            "actual skipped-approval immediate or review candidate population",
            "src.detection.fraud_rules_access.b09_skipped_approval + review_score_series",
        ),
    }
    rule_counts = _rebuild_combined()

    summary = {
        "candidate_version": "v77",
        "source_baseline": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "patch_scope": "expand L1-06/L1-07 rule truth to include review candidates, not only injected labels or immediate hits",
        "replaced_rule_counts": {rule: int(len(df)) for rule, df in replacements.items()},
        "all_rule_counts": rule_counts,
        "anti_fitting_note": "L1-06/L1-07 truth follows current rule candidate semantics including review queues; injected issue labels remain separate.",
    }
    (DEST / "V77_L1_REVIEW_RULE_TRUTH_PATCH.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V77_CANDIDATE.md").write_text(
        "# DataSynth v77 Candidate\n\n"
        f"Source baseline: `{summary['source_baseline']}`.\n\n"
        "Scope: include L1-06/L1-07 review candidates in rule truth.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
