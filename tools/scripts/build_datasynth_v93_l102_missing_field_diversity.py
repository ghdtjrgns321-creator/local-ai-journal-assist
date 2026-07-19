"""Build v93 candidate by diversifying L1-02 required-field missing cases.

The detector already has field-aware L1-02 scoring, but previous DataSynth
candidates mostly contain single ``gl_account`` missing cases. This patch keeps
existing L1-02 truth and adds a small, varied set of required-field omissions so
the score bands are exercised without changing detector code.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.detection.integrity_layer import IntegrityDetector  # noqa: E402


SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v92_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v93_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
RULE_ID = "L1-02"
REQUIRED_FIELDS = [
    "document_id",
    "company_code",
    "fiscal_year",
    "fiscal_period",
    "posting_date",
    "document_date",
    "document_type",
    "gl_account",
    "debit_amount",
    "credit_amount",
]

PLAN = {
    2022: [
        ("document_date_only", ["document_date"], 4),
        ("document_type_only", ["document_type"], 4),
        ("fiscal_period_only", ["fiscal_period"], 3),
        ("company_code_only", ["company_code"], 2),
        ("posting_date_only", ["posting_date"], 2),
        ("debit_amount_only", ["debit_amount"], 2),
        ("amount_pair_missing", ["debit_amount", "credit_amount"], 2),
        ("account_amount_missing", ["gl_account", "debit_amount"], 2),
        ("multi_core_missing", ["gl_account", "posting_date", "fiscal_period"], 1),
    ],
    2023: [
        ("document_date_only", ["document_date"], 5),
        ("document_type_only", ["document_type"], 3),
        ("fiscal_period_only", ["fiscal_period"], 4),
        ("company_code_only", ["company_code"], 2),
        ("posting_date_only", ["posting_date"], 3),
        ("credit_amount_only", ["credit_amount"], 2),
        ("account_date_missing", ["gl_account", "posting_date"], 2),
        ("multi_core_missing", ["company_code", "gl_account", "credit_amount"], 2),
    ],
    2024: [
        ("document_date_only", ["document_date"], 4),
        ("document_type_only", ["document_type"], 5),
        ("fiscal_period_only", ["fiscal_period"], 3),
        ("company_code_only", ["company_code"], 3),
        ("posting_date_only", ["posting_date"], 2),
        ("debit_amount_only", ["debit_amount"], 3),
        ("amount_pair_missing", ["debit_amount", "credit_amount"], 2),
        ("account_amount_missing", ["gl_account", "credit_amount"], 2),
        ("multi_core_missing", ["gl_account", "posting_date", "fiscal_period"], 1),
    ],
}


def _copy_candidate_safely() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(SOURCE, DEST, copy_function=shutil.copy2)


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_years() -> dict[int, pd.DataFrame]:
    return {year: pd.read_csv(DEST / f"journal_entries_{year}.csv", low_memory=False) for year in YEARS}


def _missing_mask(df: pd.DataFrame) -> pd.Series:
    mask = pd.Series(False, index=df.index)
    for col in REQUIRED_FIELDS:
        if col not in df.columns:
            continue
        col_mask = df[col].isna()
        if pd.api.types.is_object_dtype(df[col]) or pd.api.types.is_string_dtype(df[col]):
            col_mask = col_mask | df[col].astype("string").str.strip().fillna("").eq("")
        mask = mask | col_mask
    return mask


def _eligible_rows(df: pd.DataFrame) -> pd.DataFrame:
    missing = _missing_mask(df)
    source = df.get("source", pd.Series("", index=df.index)).astype(str).str.lower()
    doc_type = df.get("document_type", pd.Series("", index=df.index)).astype(str)
    # Prefer simple, low-line documents to avoid accidental impact on unrelated
    # aggregate rules, and skip existing missing-field documents.
    doc_line_count = df.groupby("document_id")["document_id"].transform("size")
    eligible = (~missing) & doc_line_count.le(4) & source.isin(["manual", "automated", "recurring", "adjustment"]) & doc_type.ne("")
    return df.loc[eligible].copy()


def _select_documents(df: pd.DataFrame, year: int) -> list[tuple[str, str, list[str]]]:
    eligible = _eligible_rows(df)
    used: set[str] = set()
    selected: list[tuple[str, str, list[str]]] = []
    for scenario, fields, count in PLAN[year]:
        pool = eligible.loc[~eligible["document_id"].astype(str).isin(used)].copy()
        pool = pool.sort_values(["company_code", "business_process", "posting_date", "document_number", "document_id"])
        if len(pool) < count:
            raise RuntimeError(f"not enough eligible rows for {year} {scenario}: need {count}, have {len(pool)}")
        # Deterministic spread without randomness: take evenly spaced rows.
        positions = [round(i * (len(pool) - 1) / max(count, 1)) for i in range(count)]
        for _, row in pool.iloc[positions].iterrows():
            doc_id = str(row["document_id"])
            used.add(doc_id)
            selected.append((doc_id, scenario, fields))
    return selected


def _blank_value_for(field: str) -> object:
    # Use empty string for all target columns so the CSV remains structurally
    # readable and the detector treats the value as missing.
    return ""


def _apply_patch(year_frames: dict[int, pd.DataFrame]) -> pd.DataFrame:
    log_records: list[dict[str, object]] = []
    for year, df in year_frames.items():
        selected = _select_documents(df, year)
        for doc_id, scenario, fields in selected:
            doc_mask = df["document_id"].astype(str).eq(doc_id)
            before = df.loc[doc_mask].iloc[0].to_dict()
            for field in fields:
                if field not in df.columns:
                    raise RuntimeError(f"missing expected column {field}")
                df[field] = df[field].astype("object")
                df.loc[doc_mask, field] = _blank_value_for(field)
            log_records.append(
                {
                    "patch_version": "v93",
                    "fiscal_year": year,
                    "document_id": doc_id,
                    "document_number": before.get("document_number"),
                    "company_code_before": before.get("company_code"),
                    "business_process": before.get("business_process"),
                    "source": before.get("source"),
                    "scenario": scenario,
                    "missing_fields": "|".join(fields),
                    "missing_count": len(fields),
                    "patch_reason": "diversify L1-02 required-field missing cases",
                }
            )
    log = pd.DataFrame(log_records)
    log.to_csv(LABELS / "l102_missing_field_diversity_patch_log.csv", index=False, encoding="utf-8")
    _write_json_records(LABELS / "l102_missing_field_diversity_patch_log.json", log)
    return log


def _write_journal(year_frames: dict[int, pd.DataFrame]) -> None:
    combined = []
    for year in YEARS:
        frame = year_frames[year]
        frame.to_csv(DEST / f"journal_entries_{year}.csv", index=False, encoding="utf-8")
        combined.append(frame)
    pd.concat(combined, ignore_index=True, sort=False).to_csv(
        DEST / "journal_entries.csv",
        index=False,
        encoding="utf-8",
    )


def _detect_l102() -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    rows = pd.read_csv(DEST / "journal_entries.csv", low_memory=False)
    detector = IntegrityDetector()
    result = detector.detect(rows)
    l102 = result.details["L1-02"]
    score = l102.attrs.get("score_series")
    if score is None:
        score = pd.to_numeric(l102, errors="coerce").fillna(0.0)
    return rows, l102.astype(bool), score


def _is_missing_value(value: object) -> bool:
    if pd.isna(value):
        return True
    return str(value).strip() == ""


def _row_missing_fields(row: pd.Series) -> list[str]:
    return [field for field in REQUIRED_FIELDS if field in row.index and _is_missing_value(row[field])]


def _build_l102_truth(rows: pd.DataFrame, l102: pd.Series, score: pd.Series) -> pd.DataFrame:
    flagged = rows.loc[l102].copy()
    flagged = flagged.reset_index(names="_row_index")
    flagged["missing_fields"] = flagged.apply(_row_missing_fields, axis=1)
    flagged["missing_count"] = flagged["missing_fields"].map(len)
    flagged["score"] = flagged["_row_index"].map(score).fillna(0.0)

    docs = (
        flagged.sort_values(["fiscal_year", "company_code", "document_number", "document_id", "_row_index"])
        .groupby("document_id", as_index=False)
        .agg(
            fiscal_year=("fiscal_year", "first"),
            company_code=("company_code", "first"),
            document_number=("document_number", "first"),
            document_type=("document_type", "first"),
            posting_date=("posting_date", "first"),
            business_process=("business_process", "first"),
            source=("source", "first"),
            missing_fields=("missing_fields", lambda values: "|".join(sorted({field for value in values.dropna() for field in value if isinstance(value, list)}))),
            missing_count=("missing_count", "max"),
            max_score=("score", "max"),
        )
    )
    docs["rule_id"] = RULE_ID
    docs["expected_hit"] = True
    docs["truth_layer"] = "rule_truth"
    docs["truth_basis"] = "required schema field is missing"
    docs["evaluation_unit"] = "document"
    docs["truth_derivation"] = "src.detection.integrity_layer.IntegrityDetector._a02_missing_required"
    docs["source_candidate"] = "v93"
    return docs.sort_values(["fiscal_year", "company_code", "document_number", "document_id"]).reset_index(drop=True)


def _write_l102_truth(truth: pd.DataFrame) -> None:
    truth.to_csv(LABELS / "rule_truth_L1_02.csv", index=False, encoding="utf-8")
    _write_json_records(LABELS / "rule_truth_L1_02.json", truth)
    for year in YEARS:
        year_truth = truth.loc[truth["fiscal_year"].astype(str).eq(str(year))].copy()
        year_truth.to_csv(LABELS / f"rule_truth_L1_02_{year}.csv", index=False, encoding="utf-8")
        _write_json_records(LABELS / f"rule_truth_L1_02_{year}.json", year_truth)


def _rebuild_l101_truth(rows: pd.DataFrame) -> pd.DataFrame:
    work = rows.copy()
    for col in ("debit_amount", "credit_amount"):
        work[col] = pd.to_numeric(work[col], errors="coerce").fillna(0.0)
    grouped = (
        work.groupby("document_id", dropna=False)
        .agg(
            fiscal_year=("fiscal_year", "first"),
            company_code=("company_code", "first"),
            posting_date=("posting_date", "first"),
            document_type=("document_type", "first"),
            document_number=("document_number", "first"),
            source=("source", "first"),
            business_process=("business_process", "first"),
            debit_total=("debit_amount", "sum"),
            credit_total=("credit_amount", "sum"),
            line_count=("document_id", "size"),
        )
        .reset_index()
    )
    grouped["imbalance_amount"] = grouped["debit_total"] - grouped["credit_total"]
    grouped["abs_imbalance_amount"] = grouped["imbalance_amount"].abs()
    truth = grouped.loc[grouped["abs_imbalance_amount"].gt(1.0)].copy()

    anomaly_types: dict[str, str] = {}
    labels_path = LABELS / "anomaly_labels.csv"
    if labels_path.exists():
        labels = pd.read_csv(labels_path, dtype=str, usecols=["document_id", "anomaly_type"], low_memory=False)
        anomaly_types = labels.groupby("document_id")["anomaly_type"].apply(
            lambda values: "|".join(sorted({str(value) for value in values if pd.notna(value) and str(value)}))
        ).to_dict()
    truth["causal_anomaly_types"] = truth["document_id"].astype(str).map(anomaly_types).fillna("")
    truth["rule_id"] = "L1-01"
    truth["truth_layer"] = "field_contract_truth"
    truth["expected_l101_flag"] = True
    truth["truth_basis"] = "abs(sum(debit_amount)-sum(credit_amount)) > 1"
    truth = truth.sort_values(["fiscal_year", "company_code", "document_number", "document_id"]).reset_index(drop=True)
    truth.to_csv(LABELS / "l101_unbalanced_truth.csv", index=False, encoding="utf-8")
    _write_json_records(LABELS / "l101_unbalanced_truth.json", truth)

    rule_cols = [
        "document_id",
        "fiscal_year",
        "company_code",
        "document_number",
        "document_type",
        "posting_date",
        "business_process",
        "source",
    ]
    rule_truth = truth[[col for col in rule_cols if col in truth.columns]].copy()
    rule_truth["rule_id"] = "L1-01"
    rule_truth["expected_hit"] = True
    rule_truth["truth_layer"] = "rule_truth"
    rule_truth["truth_basis"] = "actual debit total and credit total are imbalanced"
    rule_truth["evaluation_unit"] = "document"
    rule_truth["truth_derivation"] = "abs(sum(debit_amount)-sum(credit_amount)) > 1"
    rule_truth["source_candidate"] = "v93"
    rule_truth.to_csv(LABELS / "rule_truth_L1_01.csv", index=False, encoding="utf-8")
    _write_json_records(LABELS / "rule_truth_L1_01.json", rule_truth)
    for year in YEARS:
        year_sidecar = truth.loc[truth["fiscal_year"].astype(str).eq(str(year))].copy()
        year_sidecar.to_csv(LABELS / f"l101_unbalanced_truth_{year}.csv", index=False, encoding="utf-8")
        _write_json_records(LABELS / f"l101_unbalanced_truth_{year}.json", year_sidecar)
        year_rule = rule_truth.loc[rule_truth["fiscal_year"].astype(str).eq(str(year))].copy()
        year_rule.to_csv(LABELS / f"rule_truth_L1_01_{year}.csv", index=False, encoding="utf-8")
        _write_json_records(LABELS / f"rule_truth_L1_01_{year}.json", year_rule)
    return rule_truth


def _rebuild_combined_rule_truth() -> pd.DataFrame:
    frames = []
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        stem = path.stem
        if stem.rsplit("_", 1)[-1] in {"2022", "2023", "2024"}:
            continue
        frames.append(pd.read_csv(path, dtype=str, low_memory=False))
    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined.to_csv(LABELS / "rule_truth.csv", index=False, encoding="utf-8")
    json_path = LABELS / "rule_truth.json"
    if json_path.exists():
        json_path.unlink()
    return combined


def main() -> None:
    _copy_candidate_safely()
    old_truth = pd.read_csv(LABELS / "rule_truth_L1_02.csv", dtype=str, low_memory=False)
    year_frames = _read_years()
    patch_log = _apply_patch(year_frames)
    _write_journal(year_frames)
    rows, l102, score = _detect_l102()
    truth = _build_l102_truth(rows, l102, score)
    _write_l102_truth(truth)
    l101_truth = _rebuild_l101_truth(rows)
    combined = _rebuild_combined_rule_truth()

    field_counts: dict[str, int] = {}
    for value in truth["missing_fields"].fillna(""):
        for field in str(value).split("|"):
            if field:
                field_counts[field] = field_counts.get(field, 0) + 1
    score_band_counts = {
        "low": int(truth["max_score"].astype(float).between(0.0001, 0.499999).sum()),
        "medium": int(truth["max_score"].astype(float).between(0.50, 0.699999).sum()),
        "high": int(truth["max_score"].astype(float).between(0.70, 0.849999).sum()),
        "critical": int(truth["max_score"].astype(float).ge(0.85).sum()),
    }
    summary = {
        "candidate": "v93",
        "source": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "destination": str(DEST.relative_to(ROOT)).replace("\\", "/"),
        "purpose": "diversify L1-02 required-field missing cases without detector fitting",
        "old_l102_truth_docs": int(old_truth["document_id"].nunique()),
        "patched_documents": int(patch_log["document_id"].nunique()),
        "new_l102_truth_docs": int(truth["document_id"].nunique()),
        "new_l101_truth_docs": int(l101_truth["document_id"].nunique()),
        "l102_by_year": {str(k): int(v) for k, v in truth["fiscal_year"].value_counts().sort_index().to_dict().items()},
        "missing_field_counts": {str(k): int(v) for k, v in sorted(field_counts.items())},
        "score_band_counts": score_band_counts,
        "score_counts": {str(k): int(v) for k, v in truth["max_score"].astype(float).round(2).value_counts().sort_index().to_dict().items()},
        "combined_rule_truth_counts": {str(k): int(v) for k, v in combined["rule_id"].value_counts().sort_index().to_dict().items()},
    }
    (DEST / "V93_L102_MISSING_FIELD_DIVERSITY.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V93_CANDIDATE.md").write_text(
        "\n".join(
            [
                "# DataSynth v93 Candidate",
                "",
                "Status: candidate, not promoted to production.",
                "",
                "Purpose: diversify L1-02 required-field missing cases without changing detector code.",
                "",
                f"- Source: `{summary['source']}`",
                f"- L1-02 truth docs: `{summary['new_l102_truth_docs']}`",
                f"- Patched documents: `{summary['patched_documents']}`",
                f"- Score bands: `{summary['score_band_counts']}`",
                f"- Missing field counts: `{summary['missing_field_counts']}`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
