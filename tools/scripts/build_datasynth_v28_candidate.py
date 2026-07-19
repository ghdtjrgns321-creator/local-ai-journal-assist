"""Build DataSynth v28 candidate by de-uniforming synthetic-looking labels.

Targets:
- SelfApproval
- SkippedApproval
- ManualOverride
- MissingField

Source baseline is v27_candidate when present so L1-09 changes remain intact.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v27_candidate"
if not SOURCE_DIR.exists():
    SOURCE_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v26_candidate"
TARGET_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v28_candidate"

REBALANCE_CONFIG = {
    "SelfApproval": {
        "year_targets": {2022: 5, 2023: 7, 2024: 10},
        "process_caps": {
            2022: {"O2C": 2, "P2P": 1, "R2R": 1, "H2R": 1},
            2023: {"O2C": 2, "P2P": 2, "R2R": 2, "H2R": 1},
            2024: {"O2C": 3, "P2P": 3, "R2R": 2, "H2R": 1, "TRE": 1},
        },
    },
    "SkippedApproval": {
        "year_targets": {2022: 4, 2023: 6, 2024: 9},
        "process_caps": {
            2022: {"R2R": 2, "O2C": 1, "TRE": 1},
            2023: {"R2R": 2, "P2P": 2, "O2C": 1, "H2R": 1},
            2024: {"R2R": 2, "O2C": 2, "P2P": 2, "H2R": 1, "TRE": 1, "A2R": 1},
        },
    },
    "ManualOverride": {
        "year_targets": {2022: 6, 2023: 8, 2024: 10},
        "process_caps": {
            2022: {"P2P": 2, "O2C": 1, "R2R": 1, "TRE": 1, "H2R": 1},
            2023: {"P2P": 2, "O2C": 2, "R2R": 2, "H2R": 1, "TRE": 1},
            2024: {"P2P": 3, "O2C": 2, "R2R": 2, "H2R": 1, "TRE": 1, "A2R": 1},
        },
    },
    "MissingField": {
        "year_targets": {2022: 28, 2023: 32, 2024: 43},
        "process_caps": {
            2022: {"R2R": 8, "O2C": 6, "P2P": 5, "H2R": 3, "TRE": 3, "A2R": 3},
            2023: {"R2R": 10, "O2C": 7, "P2P": 5, "H2R": 4, "TRE": 3, "A2R": 3},
            2024: {"R2R": 12, "O2C": 9, "P2P": 8, "H2R": 5, "TRE": 6, "A2R": 3},
        },
    },
}


def _copy_source() -> None:
    if TARGET_DIR.exists():
        shutil.rmtree(TARGET_DIR)
    shutil.copytree(SOURCE_DIR, TARGET_DIR)


def _document_frame(df: pd.DataFrame) -> pd.DataFrame:
    return df.groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", "first"),
        company_code=("company_code", "first"),
        document_type=("document_type", "first"),
        posting_date=("posting_date", "min"),
        source=("source", "first"),
        business_process=("business_process", "first"),
        created_by=("created_by", "first"),
        approved_by=("approved_by", "first"),
        approval_date=("approval_date", "first"),
        reference=("reference", "first"),
        header_text=("header_text", "first"),
        supporting_doc_type=("supporting_doc_type", "first"),
        user_persona=("user_persona", "first"),
        document_number=("document_number", "first"),
        debit_amount=("debit_amount", "sum"),
        credit_amount=("credit_amount", "sum"),
    )


def _blank(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().eq("")


def _manual_source(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().str.lower().isin(["manual", "adjustment"])


def _remove_target_labels(labels: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    templates: dict[str, pd.DataFrame] = {}
    keep = labels.copy()
    for anomaly_type in REBALANCE_CONFIG:
        target = keep.loc[keep["anomaly_type"].eq(anomaly_type)].copy().reset_index(drop=True)
        templates[anomaly_type] = target
        keep = keep.loc[~keep["anomaly_type"].eq(anomaly_type)].copy()
    return keep.reset_index(drop=True), templates


def _eligible_selfapproval(doc: pd.DataFrame, excluded: set[str]) -> pd.DataFrame:
    manual = _manual_source(doc["source"])
    return doc.loc[
        ~doc["document_id"].astype(str).isin(excluded)
        & manual
        & doc["created_by"].fillna("").astype(str).str.strip().ne("")
        & doc["created_by"].astype(str).eq(doc["approved_by"].astype(str))
        & doc["user_persona"].fillna("").astype(str).str.strip().str.lower().ne("automated_system")
        & doc["fiscal_year"].isin([2022, 2023, 2024])
    ].copy()


def _eligible_skippedapproval(doc: pd.DataFrame, excluded: set[str]) -> pd.DataFrame:
    manual = _manual_source(doc["source"])
    amount = doc[["debit_amount", "credit_amount"]].max(axis=1)
    return doc.loc[
        ~doc["document_id"].astype(str).isin(excluded)
        & manual
        & amount.ge(10_000_000)
        & doc["approved_by"].fillna("").astype(str).str.strip().ne("")
        & doc["fiscal_year"].isin([2022, 2023, 2024])
    ].copy()


def _eligible_manualoverride(doc: pd.DataFrame, excluded: set[str]) -> pd.DataFrame:
    manual = _manual_source(doc["source"])
    return doc.loc[
        ~doc["document_id"].astype(str).isin(excluded)
        & manual
        & doc["fiscal_year"].isin([2022, 2023, 2024])
    ].copy()


def _eligible_missingfield(doc: pd.DataFrame, excluded: set[str]) -> pd.DataFrame:
    missing = _blank(doc["reference"]) | _blank(doc["header_text"]) | _blank(doc["supporting_doc_type"])
    return doc.loc[
        ~doc["document_id"].astype(str).isin(excluded)
        & missing
        & doc["fiscal_year"].isin([2022, 2023, 2024])
    ].copy()


def _choose_year_process(
    pool: pd.DataFrame,
    *,
    year_targets: dict[int, int],
    process_caps: dict[int, dict[str, int]],
) -> pd.DataFrame:
    chosen: list[pd.DataFrame] = []
    for year, needed in year_targets.items():
        year_pool = pool.loc[pool["fiscal_year"].eq(year)].copy()
        if len(year_pool) < needed:
            raise RuntimeError(f"not enough candidates for {year}: {len(year_pool)} < {needed}")
        year_pool = year_pool.sort_values(["posting_date", "document_id"]).reset_index(drop=True)
        used: set[str] = set()
        picks: list[pd.DataFrame] = []
        for process, cap in process_caps.get(year, {}).items():
            subset = year_pool.loc[year_pool["business_process"].eq(process)].head(cap)
            if subset.empty:
                continue
            picks.append(subset)
            used.update(subset["document_id"].astype(str).tolist())
        picked = pd.concat(picks, ignore_index=True) if picks else pd.DataFrame(columns=year_pool.columns)
        if len(picked) < needed:
            remainder = year_pool.loc[~year_pool["document_id"].astype(str).isin(used)].head(needed - len(picked))
            picked = pd.concat([picked, remainder], ignore_index=True)
        chosen.append(picked.head(needed))
    return pd.concat(chosen, ignore_index=True)


def _rebuild_labels(
    templates: pd.DataFrame,
    chosen: pd.DataFrame,
    *,
    anomaly_type: str,
) -> pd.DataFrame:
    count = len(chosen)
    if len(templates) < count:
        raise RuntimeError(f"not enough template rows for {anomaly_type}: {len(templates)} < {count}")
    templates = templates.head(count).copy().reset_index(drop=True)
    chosen = chosen.reset_index(drop=True)
    templates["document_id"] = chosen["document_id"].values
    templates["document_type"] = chosen["document_type"].values
    templates["company_code"] = chosen["company_code"].values
    templates["anomaly_date"] = pd.to_datetime(chosen["posting_date"]).dt.strftime("%Y-%m-%d").values
    templates["related_entities"] = chosen["document_number"].map(lambda v: json.dumps([v], ensure_ascii=False)).values

    def _metadata(row: pd.Series) -> str:
        metadata = {
            "document_number": row["document_number"],
            "business_process": row["business_process"],
            "source": row["source"],
            "fiscal_year": int(row["fiscal_year"]),
        }
        if anomaly_type == "SelfApproval":
            metadata["created_by"] = row["created_by"]
            metadata["approved_by"] = row["approved_by"]
        elif anomaly_type == "SkippedApproval":
            metadata["created_by"] = row["created_by"]
            metadata["threshold_basis"] = max(float(row["debit_amount"]), float(row["credit_amount"]))
        elif anomaly_type == "MissingField":
            metadata["missing_flags"] = {
                "reference": bool(_blank(pd.Series([row["reference"]])).iloc[0]),
                "header_text": bool(_blank(pd.Series([row["header_text"]])).iloc[0]),
                "supporting_doc_type": bool(_blank(pd.Series([row["supporting_doc_type"]])).iloc[0]),
            }
        return json.dumps(metadata, ensure_ascii=False)

    templates["metadata_json"] = chosen.apply(_metadata, axis=1).values
    return templates


def _write_labels(labels: pd.DataFrame) -> None:
    labels_dir = TARGET_DIR / "labels"
    labels.to_csv(labels_dir / "anomaly_labels.csv", index=False)
    records = labels.where(pd.notna(labels), None).to_dict(orient="records")
    (labels_dir / "anomaly_labels.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    with (labels_dir / "anomaly_labels.jsonl").open("w", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary = {
        "total_labels": len(labels),
        "by_anomaly_type": labels["anomaly_type"].value_counts().to_dict(),
        "by_category": labels["anomaly_category"].value_counts().to_dict() if "anomaly_category" in labels else {},
    }
    (labels_dir / "anomaly_labels_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


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
    labels = pd.read_csv(TARGET_DIR / "labels" / "anomaly_labels.csv")
    doc = _document_frame(df)
    kept_labels, templates = _remove_target_labels(labels)
    excluded_docs = set(kept_labels["document_id"].astype(str))

    selections: dict[str, pd.DataFrame] = {}

    self_pool = _eligible_selfapproval(doc, excluded_docs)
    self_sel = _choose_year_process(
        self_pool,
        year_targets=REBALANCE_CONFIG["SelfApproval"]["year_targets"],
        process_caps=REBALANCE_CONFIG["SelfApproval"]["process_caps"],
    )
    selections["SelfApproval"] = self_sel
    excluded_docs.update(self_sel["document_id"].astype(str).tolist())

    skip_pool = _eligible_skippedapproval(doc, excluded_docs)
    skip_sel = _choose_year_process(
        skip_pool,
        year_targets=REBALANCE_CONFIG["SkippedApproval"]["year_targets"],
        process_caps=REBALANCE_CONFIG["SkippedApproval"]["process_caps"],
    )
    selections["SkippedApproval"] = skip_sel
    excluded_docs.update(skip_sel["document_id"].astype(str).tolist())

    manual_pool = _eligible_manualoverride(doc, excluded_docs)
    manual_sel = _choose_year_process(
        manual_pool,
        year_targets=REBALANCE_CONFIG["ManualOverride"]["year_targets"],
        process_caps=REBALANCE_CONFIG["ManualOverride"]["process_caps"],
    )
    selections["ManualOverride"] = manual_sel
    excluded_docs.update(manual_sel["document_id"].astype(str).tolist())

    missing_pool = _eligible_missingfield(doc, excluded_docs)
    missing_sel = _choose_year_process(
        missing_pool,
        year_targets=REBALANCE_CONFIG["MissingField"]["year_targets"],
        process_caps=REBALANCE_CONFIG["MissingField"]["process_caps"],
    )
    selections["MissingField"] = missing_sel
    excluded_docs.update(missing_sel["document_id"].astype(str).tolist())

    # SkippedApproval needs actual data mutation: remove approver and approval date.
    skipped_original = doc.loc[doc["document_id"].astype(str).isin(skip_sel["document_id"].astype(str))][
        ["document_id", "approved_by", "approval_date", "document_number", "fiscal_year", "business_process", "source"]
    ].copy()
    df.loc[df["document_id"].astype(str).isin(skip_sel["document_id"].astype(str)), "approved_by"] = None
    df.loc[df["document_id"].astype(str).isin(skip_sel["document_id"].astype(str)), "approval_date"] = None

    rebuilt: list[pd.DataFrame] = [kept_labels]
    for anomaly_type, chosen in selections.items():
        rebuilt.append(_rebuild_labels(templates[anomaly_type], chosen, anomaly_type=anomaly_type))
    labels = pd.concat(rebuilt, ignore_index=True).sort_values(["anomaly_date", "anomaly_id"], kind="stable").reset_index(drop=True)

    df.to_csv(TARGET_DIR / "journal_entries.csv", index=False)
    _write_year_splits(df)
    _write_labels(labels)

    sidecar = {
        "source_baseline": str(SOURCE_DIR.relative_to(ROOT).as_posix()),
        "rebalanced": {},
        "skippedapproval_patched_docs": len(skipped_original),
    }
    labels_dir = TARGET_DIR / "labels"
    for anomaly_type, chosen in selections.items():
        sidecar["rebalanced"][anomaly_type] = {
            "total": int(len(chosen)),
            "year_counts": {str(int(k)): int(v) for k, v in chosen["fiscal_year"].value_counts().sort_index().to_dict().items()},
            "process_counts": {str(k): int(v) for k, v in chosen["business_process"].value_counts().to_dict().items()},
        }
    skipped_original.to_csv(labels_dir / "skipped_approval_repatch_cases.csv", index=False)
    (labels_dir / "skipped_approval_repatch_cases.json").write_text(
        json.dumps(skipped_original.to_dict(orient="records"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (TARGET_DIR / "V28_LABEL_REBALANCE_PATCH.json").write_text(
        json.dumps(sidecar, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (TARGET_DIR / "PREVIEW.md").write_text(
        "# DataSynth v28 Candidate Preview\n\n"
        "Status: candidate only. Production data remains unchanged.\n\n"
        "This candidate rebalances synthetic-looking label distributions for SelfApproval, "
        "SkippedApproval, ManualOverride, and MissingField.\n",
        encoding="utf-8",
    )
    (TARGET_DIR / "FREEZE_V28_CANDIDATE.md").write_text(
        "# DataSynth v28 Candidate\n\n"
        f"Source baseline: `{SOURCE_DIR.relative_to(ROOT).as_posix()}`\n\n"
        f"Summary: `{json.dumps(sidecar, ensure_ascii=False)}`\n",
        encoding="utf-8",
    )
    print(json.dumps(sidecar, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
