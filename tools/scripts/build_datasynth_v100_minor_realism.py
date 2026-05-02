"""Build v100 candidate with a light source-distribution realism pass.

This patch starts from v99. It does not change Phase 1 rule contracts. It only
reclassifies a deterministic subset of manual journal documents to adjustment
where the document is already part of the broad manual/adjustment population.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v99_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v100_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
TARGET_L302_ADJUSTMENT_RATIO = 0.12
TARGET_L405_ADJUSTMENT_DOCS = 9


def _copy_candidate_safely() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(SOURCE, DEST, copy_function=shutil.copy2)


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl_records(path: Path, df: pd.DataFrame) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for record in df.where(pd.notna(df), None).to_dict(orient="records"):
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _stable_select(df: pd.DataFrame, n: int) -> pd.DataFrame:
    if n <= 0:
        return df.iloc[0:0].copy()
    out = df.copy()
    out["_stable_hash"] = pd.util.hash_pandas_object(
        out[["document_id", "fiscal_year", "company_code", "business_process"]].astype(str),
        index=False,
    )
    out = out.sort_values(["fiscal_year", "company_code", "business_process", "_stable_hash"])
    return out.head(min(n, len(out))).drop(columns=["_stable_hash"])


def _select_l302_conversions() -> pd.DataFrame:
    l302 = pd.read_csv(LABELS / "rule_truth_L3_02.csv", low_memory=False)
    anomaly_docs = set(
        pd.read_csv(LABELS / "anomaly_labels.csv", usecols=["document_id"], low_memory=False)[
            "document_id"
        ].astype(str)
    )
    manipulated_path = LABELS / "manipulated_entry_truth.csv"
    manipulated_docs: set[str] = set()
    if manipulated_path.exists():
        manipulated_docs = set(pd.read_csv(manipulated_path, usecols=["document_id"])["document_id"].astype(str))
    protected = anomaly_docs | manipulated_docs
    current_adjustment = int(l302["source"].astype(str).str.lower().eq("adjustment").sum())
    target_adjustment = int(round(len(l302) * TARGET_L302_ADJUSTMENT_RATIO))
    need = max(0, target_adjustment - current_adjustment)
    eligible = l302.loc[
        l302["source"].astype(str).str.lower().eq("manual")
        & ~l302["document_id"].astype(str).isin(protected)
    ].copy()
    selected_parts = []
    group_cols = ["fiscal_year", "company_code", "business_process"]
    for _, group in eligible.groupby(group_cols, sort=True):
        group_share = len(group) / max(1, len(eligible))
        selected_parts.append(_stable_select(group, int(round(need * group_share))))
    selected = pd.concat(selected_parts, ignore_index=True) if selected_parts else eligible.iloc[0:0].copy()
    if len(selected) < need:
        remaining = eligible.loc[~eligible["document_id"].astype(str).isin(selected["document_id"].astype(str))]
        selected = pd.concat([selected, _stable_select(remaining, need - len(selected))], ignore_index=True)
    return selected.drop_duplicates("document_id").head(need)


def _select_l405_conversions(existing: pd.DataFrame) -> pd.DataFrame:
    l405_path = LABELS / "rule_truth_L4_05.csv"
    if not l405_path.exists():
        return existing.iloc[0:0].copy()
    l405 = pd.read_csv(l405_path, low_memory=False)
    current_adjustment = int(l405["source"].astype(str).str.lower().eq("adjustment").sum())
    need = max(0, TARGET_L405_ADJUSTMENT_DOCS - current_adjustment)
    eligible = l405.loc[
        l405["source"].astype(str).str.lower().eq("manual")
        & ~l405["document_id"].astype(str).isin(existing["document_id"].astype(str))
    ].copy()
    selected_parts = []
    for _, group in eligible.groupby(["fiscal_year", "company_code"], sort=True):
        selected_parts.append(_stable_select(group, 1))
    selected = pd.concat(selected_parts, ignore_index=True) if selected_parts else eligible.iloc[0:0].copy()
    if len(selected) < need:
        remaining = eligible.loc[~eligible["document_id"].astype(str).isin(selected["document_id"].astype(str))]
        selected = pd.concat([selected, _stable_select(remaining, need - len(selected))], ignore_index=True)
    return selected.drop_duplicates("document_id").head(need)


def _update_journal_sources(changes: pd.DataFrame) -> None:
    change_map = dict(zip(changes["document_id"].astype(str), changes["new_source"].astype(str), strict=False))
    for year in YEARS:
        path = DEST / f"journal_entries_{year}.csv"
        df = pd.read_csv(path, low_memory=False)
        mask = df["document_id"].astype(str).isin(change_map)
        if mask.any():
            df.loc[mask, "source"] = df.loc[mask, "document_id"].astype(str).map(change_map)
            df.to_csv(path, index=False)


def _update_label_csv_sources(changes: pd.DataFrame) -> list[str]:
    change_map = dict(zip(changes["document_id"].astype(str), changes["new_source"].astype(str), strict=False))
    touched = []
    for path in LABELS.glob("*.csv"):
        try:
            header = pd.read_csv(path, nrows=0)
        except pd.errors.EmptyDataError:
            continue
        if "document_id" not in header.columns or "source" not in header.columns:
            continue
        df = pd.read_csv(path, low_memory=False)
        mask = df["document_id"].astype(str).isin(change_map)
        if not mask.any():
            continue
        df.loc[mask, "source"] = df.loc[mask, "document_id"].astype(str).map(change_map)
        df.to_csv(path, index=False)
        json_path = path.with_suffix(".json")
        if json_path.exists():
            _write_json_records(json_path, df)
        if path.name == "anomaly_labels.csv":
            _write_jsonl_records(path.with_suffix(".jsonl"), df)
        touched.append(path.name)
    return touched


def _write_patch_outputs(changes: pd.DataFrame, touched_files: list[str]) -> None:
    changes.to_csv(LABELS / "source_realism_reclassification_v100.csv", index=False)
    _write_json_records(LABELS / "source_realism_reclassification_v100.json", changes)

    l302 = pd.read_csv(LABELS / "rule_truth_L3_02.csv", low_memory=False)
    l405 = pd.read_csv(LABELS / "rule_truth_L4_05.csv", low_memory=False)
    manifest = {
        "version": "v100_candidate",
        "base_version": "v99_candidate",
        "patch": "minor_source_distribution_realism",
        "journal_rows_mutated": "source column only",
        "reclassified_documents": int(len(changes)),
        "l302_source_distribution": {
            str(k): int(v) for k, v in l302["source"].value_counts().sort_index().items()
        },
        "l405_source_distribution": {
            str(k): int(v) for k, v in l405["source"].value_counts().sort_index().items()
        },
        "touched_label_csvs": touched_files,
        "contract": "manual and adjustment both remain L3-02 truth; this is not a detector-fitting patch",
    }
    (LABELS / "V100_MINOR_REALISM.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V100_CANDIDATE.md").write_text(
        "# DataSynth v100 Candidate\n\n"
        "Base: `datasynth_v99_candidate`.\n\n"
        "Patch: minor source-distribution realism for broad manual/adjustment review populations.\n\n"
        f"```json\n{json.dumps(manifest, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )


def main() -> None:
    _copy_candidate_safely()
    l302_changes = _select_l302_conversions()
    l405_changes = _select_l405_conversions(l302_changes)
    changes = pd.concat([l302_changes, l405_changes], ignore_index=True)
    changes = changes.drop_duplicates("document_id").copy()
    changes["old_source"] = changes["source"]
    changes["new_source"] = "adjustment"
    changes["patch_reason"] = "minor_realism_manual_to_adjustment"
    keep_cols = [
        "document_id",
        "fiscal_year",
        "company_code",
        "document_number",
        "document_type",
        "business_process",
        "old_source",
        "new_source",
        "patch_reason",
    ]
    changes = changes[keep_cols]
    _update_journal_sources(changes)
    touched = _update_label_csv_sources(changes)
    _write_patch_outputs(changes, touched)
    print(
        json.dumps(
            {
                "dest": str(DEST.relative_to(ROOT)),
                "reclassified_documents": int(len(changes)),
                "by_year": {
                    str(k): int(v) for k, v in changes["fiscal_year"].value_counts().sort_index().items()
                },
                "by_process": {
                    str(k): int(v) for k, v in changes["business_process"].value_counts().items()
                },
                "touched_label_csvs": touched,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
