"""Build v112 candidate by realigning L4-06 truth to batch detector output.

L4-06 is a Phase 1 combo-only review signal. Its rule truth should describe the
raw batch review universe produced by the detector, while confirmed
`BatchAnomaly` labels remain a smaller subset. Normal and boundary controls are
kept as controls only and are not copied into rule truth.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config.settings import get_settings  # noqa: E402
from src.detection.anomaly_rules_batch import c13_batch_anomaly  # noqa: E402
from src.feature.time_features import add_is_period_end  # noqa: E402


SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v111_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v112_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
RULE_ID = "L4-06"
CONFIRMED_COUNT = 175
CONFIRMED_YEAR_TARGETS = {2022: 58, 2023: 64, 2024: 53}


def _copy_candidate_fast() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        required = [DEST / f"journal_entries_{year}.csv" for year in YEARS]
        required.append(LABELS / "rule_truth_L4_06.csv")
        if all(path.exists() for path in required):
            return
        raise SystemExit(f"destination exists but is incomplete: {DEST}")

    source_resolved = SOURCE.resolve()
    dest_resolved = DEST.resolve()
    allowed_root = (ROOT / "data" / "journal" / "primary").resolve()
    if allowed_root not in dest_resolved.parents:
        raise SystemExit(f"refusing to write outside DataSynth root: {DEST}")

    for src in SOURCE.rglob("*"):
        rel = src.relative_to(source_resolved)
        dst = dest_resolved / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if rel.parts and rel.parts[0] == "labels":
            shutil.copy2(src, dst)
        else:
            os.link(src, dst)


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl_records(path: Path, df: pd.DataFrame) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for record in df.where(pd.notna(df), None).to_dict(orient="records"):
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _first_non_null(values: pd.Series) -> object:
    clean = values.dropna()
    return None if clean.empty else clean.iloc[0]


def _load_journal() -> pd.DataFrame:
    usecols = {
        "document_id",
        "company_code",
        "fiscal_year",
        "posting_date",
        "document_number",
        "document_type",
        "business_process",
        "source",
        "created_by",
        "approved_by",
        "user_persona",
        "gl_account",
        "debit_amount",
        "credit_amount",
        "is_period_end",
    }
    frames: list[pd.DataFrame] = []
    for year in YEARS:
        path = DEST / f"journal_entries_{year}.csv"
        header = pd.read_csv(path, nrows=0).columns
        cols = [column for column in header if column in usecols]
        frames.append(pd.read_csv(path, usecols=cols, parse_dates=["posting_date"], low_memory=False))
    df = pd.concat(frames, ignore_index=True)
    if "is_period_end" not in df.columns:
        df = add_is_period_end(df, margin=get_settings().period_end_margin_days)
    return df


def _truth_from_detector(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    settings = get_settings()
    result = c13_batch_anomaly(
        df,
        batch_sources=settings.batch_source_values,
        period_end_ratio=settings.batch_period_end_ratio,
        simultaneous_threshold=settings.batch_simultaneous_threshold,
        amount_zscore=settings.batch_amount_zscore,
    )
    mask = pd.Series(result, index=df.index).fillna(False).astype(bool)
    annotations = result.attrs.get("row_annotations", {})
    scores = pd.Series(result.attrs.get("score_series", 0.0), index=df.index).fillna(0.0)

    work = df.loc[mask].copy()
    work["_l406_score"] = scores.loc[work.index].astype(float)
    work["_score_bucket"] = work.index.map(
        lambda idx: annotations.get(int(idx), {}).get("score_bucket", "")
    )
    work["_reason_codes"] = work.index.map(
        lambda idx: "|".join(annotations.get(int(idx), {}).get("reason_codes", []))
    )
    work["_primary_reason"] = work.index.map(
        lambda idx: annotations.get(int(idx), {}).get("primary_reason", "")
    )

    grouped = (
        work.groupby("document_id", dropna=False)
        .agg(
            fiscal_year=("fiscal_year", _first_non_null),
            company_code=("company_code", _first_non_null),
            posting_date=("posting_date", _first_non_null),
            document_number=("document_number", _first_non_null),
            document_type=("document_type", _first_non_null),
            business_process=("business_process", _first_non_null),
            source=("source", _first_non_null),
            created_by=("created_by", _first_non_null),
            approved_by=("approved_by", _first_non_null),
            user_persona=("user_persona", _first_non_null),
            line_count=("document_id", "size"),
            l406_score=("_l406_score", "max"),
            score_bucket=("_score_bucket", _first_non_null),
            reason_codes=("_reason_codes", _first_non_null),
            primary_reason=("_primary_reason", _first_non_null),
        )
        .reset_index()
    )
    grouped["fiscal_year"] = pd.to_numeric(grouped["fiscal_year"], errors="coerce").astype(int)
    grouped["posting_date"] = grouped["posting_date"].astype(str)
    grouped["rule_id"] = RULE_ID
    grouped["expected_hit"] = True
    grouped["truth_layer"] = "rule_truth"
    grouped["truth_basis"] = "batch-source review universe"
    grouped["evaluation_unit"] = "document_id"
    grouped["truth_derivation"] = "src.detection.anomaly_rules_batch.c13_batch_anomaly current detector output"
    grouped["source_candidate"] = "v112"
    grouped["evaluation_policy"] = (
        "Phase1 raw batch review universe; confirmed BatchAnomaly subset and "
        "normal/boundary controls are separate"
    )
    grouped["case_id"] = [
        f"L406-{int(year)}-{idx + 1:05d}"
        for idx, year in enumerate(grouped["fiscal_year"].tolist())
    ]

    columns = [
        "document_id",
        "fiscal_year",
        "company_code",
        "posting_date",
        "document_number",
        "document_type",
        "business_process",
        "source",
        "created_by",
        "approved_by",
        "user_persona",
        "line_count",
        "l406_score",
        "score_bucket",
        "reason_codes",
        "primary_reason",
        "case_id",
        "rule_id",
        "expected_hit",
        "truth_layer",
        "truth_basis",
        "evaluation_unit",
        "truth_derivation",
        "source_candidate",
        "evaluation_policy",
    ]
    return grouped[columns].sort_values(["fiscal_year", "document_id"]).reset_index(drop=True), (
        result.attrs.get("breakdown", {})
    )


def _write_truth_family(truth: pd.DataFrame) -> None:
    stems = ["rule_truth_L4_06", "batch_review_population"]
    for stem in stems:
        truth.to_csv(LABELS / f"{stem}.csv", index=False)
        _write_json_records(LABELS / f"{stem}.json", truth)
        for year in YEARS:
            year_df = truth.loc[truth["fiscal_year"].eq(year)].copy()
            year_df.to_csv(LABELS / f"{stem}_{year}.csv", index=False)
            _write_json_records(LABELS / f"{stem}_{year}.json", year_df)


def _replace_combined_rule_truth(truth: pd.DataFrame) -> None:
    path = LABELS / "rule_truth.csv"
    combined = pd.read_csv(path, low_memory=False)
    combined = combined.loc[combined["rule_id"].astype(str).ne(RULE_ID)].copy()
    rebuilt = pd.concat([combined, truth], ignore_index=True, sort=False)
    rebuilt.to_csv(path, index=False)
    _write_json_records(LABELS / "rule_truth.json", rebuilt)


def _balanced_pick(group: pd.DataFrame, count: int) -> pd.DataFrame:
    ordered = group.sort_values(
        ["score_bucket", "business_process", "company_code", "source", "document_number", "document_id"]
    ).copy()
    bucket_cols = ["score_bucket", "business_process", "company_code", "source"]
    buckets = [
        bucket.reset_index(drop=True)
        for _, bucket in ordered.groupby(bucket_cols, sort=True, dropna=False)
    ]
    cursor = [0 for _ in buckets]
    picks = []
    while len(picks) < count:
        progressed = False
        for bucket_idx, bucket in enumerate(buckets):
            row_idx = cursor[bucket_idx]
            if row_idx >= len(bucket):
                continue
            picks.append(bucket.iloc[row_idx])
            cursor[bucket_idx] += 1
            progressed = True
            if len(picks) >= count:
                break
        if not progressed:
            break
    if len(picks) < count:
        raise SystemExit(f"not enough L4-06 detector rows to pick confirmed subset: {len(picks)} < {count}")
    return pd.DataFrame(picks)


def _select_confirmed(truth: pd.DataFrame) -> pd.DataFrame:
    selected = []
    for year, target in CONFIRMED_YEAR_TARGETS.items():
        group = truth.loc[truth["fiscal_year"].eq(year)].copy()
        if len(group) < target:
            raise SystemExit(f"not enough L4-06 truth rows for {year}: {len(group)} < {target}")
        selected.append(_balanced_pick(group, target))
    confirmed = pd.concat(selected, ignore_index=True)
    if len(confirmed) != CONFIRMED_COUNT:
        raise SystemExit(f"unexpected confirmed count: {len(confirmed)} != {CONFIRMED_COUNT}")
    confirmed = confirmed.sort_values(["fiscal_year", "business_process", "company_code", "document_id"]).reset_index(drop=True)
    confirmed["batch_signal"] = confirmed["primary_reason"].fillna("batch_review")
    confirmed["run_type"] = confirmed["business_process"].astype(str).str.lower()
    confirmed["run_id"] = confirmed.apply(
        lambda row: f"L406-{int(row['fiscal_year'])}-{row['business_process']}-{row['score_bucket']}",
        axis=1,
    )
    confirmed["truth_basis"] = confirmed["primary_reason"].map(
        {
            "amount_outlier": "confirmed batch amount outlier",
            "simultaneous_creation": "confirmed simultaneous batch creation",
            "period_end_concentration": "confirmed period-end batch concentration",
        }
    ).fillna("confirmed multi-signal batch run")
    confirmed["evaluation_policy"] = "confirmed subset; batch_review_population is raw Phase1 rule truth"
    confirmed["anomaly_type"] = "BatchAnomaly"
    confirmed["confirmed_subset"] = True
    return confirmed


def _line_summary() -> pd.DataFrame:
    parts = []
    for year in YEARS:
        df = pd.read_csv(
            DEST / f"journal_entries_{year}.csv",
            usecols=["document_id", "debit_amount", "credit_amount"],
            low_memory=False,
        )
        df["_line_amount"] = df[["debit_amount", "credit_amount"]].fillna(0).max(axis=1)
        parts.append(
            df.groupby("document_id", dropna=False).agg(
                max_line_amount=("_line_amount", "max"),
                total_line_amount=("_line_amount", "sum"),
                line_count=("document_id", "size"),
            )
        )
    return pd.concat(parts)


def _write_confirmed(confirmed: pd.DataFrame) -> None:
    summary = _line_summary()
    confirmed = confirmed.merge(summary, left_on="document_id", right_index=True, how="left", suffixes=("", "_journal"))
    for column in ["line_count", "max_line_amount", "total_line_amount"]:
        if column not in confirmed.columns:
            confirmed[column] = None
    columns = [
        "document_id",
        "fiscal_year",
        "company_code",
        "posting_date",
        "document_number",
        "document_type",
        "business_process",
        "source",
        "created_by",
        "approved_by",
        "user_persona",
        "line_count",
        "max_line_amount",
        "total_line_amount",
        "l406_score",
        "score_bucket",
        "reason_codes",
        "primary_reason",
        "batch_signal",
        "run_type",
        "run_id",
        "truth_basis",
        "evaluation_policy",
        "anomaly_type",
        "confirmed_subset",
    ]
    out = confirmed[columns].copy()
    out.to_csv(LABELS / "batch_confirmed_anomalies.csv", index=False)
    _write_json_records(LABELS / "batch_confirmed_anomalies.json", out)
    for year in YEARS:
        year_df = out.loc[out["fiscal_year"].eq(year)].copy()
        year_df.to_csv(LABELS / f"batch_confirmed_anomalies_{year}.csv", index=False)
        _write_json_records(LABELS / f"batch_confirmed_anomalies_{year}.json", year_df)


def _replace_anomaly_labels(confirmed: pd.DataFrame) -> None:
    path = LABELS / "anomaly_labels.csv"
    labels = pd.read_csv(path, low_memory=False)
    old = labels.loc[labels["anomaly_type"].eq("BatchAnomaly")].copy().reset_index(drop=True)
    if len(old) != len(confirmed):
        raise SystemExit(f"BatchAnomaly count changed: old={len(old)} new={len(confirmed)}")
    keep = labels.loc[~labels["anomaly_type"].eq("BatchAnomaly")].copy()
    new_rows = old.copy()
    summary = _line_summary()
    enriched = confirmed.merge(summary, left_on="document_id", right_index=True, how="left")
    timestamp = old["detection_timestamp"].iloc[0] if not old.empty else "2026-05-02 00:00:00"
    for i, row in enriched.reset_index(drop=True).iterrows():
        confidence = 0.55
        if row.get("score_bucket") == "multi_signal_batch":
            confidence = 0.68
        elif row.get("score_bucket") == "simultaneous_creation":
            confidence = 0.60
        elif row.get("score_bucket") == "period_end_concentration":
            confidence = 0.58
        meta = {
            "rule_id": RULE_ID,
            "source_candidate": "v112",
            "truth_basis": row.get("truth_basis"),
            "evaluation_policy": row.get("evaluation_policy"),
            "score_bucket": row.get("score_bucket"),
            "reason_codes": row.get("reason_codes"),
            "source": row.get("source"),
            "business_process": row.get("business_process"),
            "detector_contract": "batch source plus period-end/simultaneous/amount-outlier signal",
        }
        new_rows.loc[i, "document_id"] = row["document_id"]
        new_rows.loc[i, "document_type"] = row.get("document_type")
        new_rows.loc[i, "company_code"] = row.get("company_code")
        new_rows.loc[i, "anomaly_date"] = row.get("posting_date")
        new_rows.loc[i, "detection_timestamp"] = timestamp
        new_rows.loc[i, "confidence"] = confidence
        new_rows.loc[i, "severity"] = 2
        new_rows.loc[i, "description"] = f"L4-06 {row.get('business_process')} batch review subset"
        new_rows.loc[i, "is_injected"] = True
        new_rows.loc[i, "monetary_impact"] = row.get("max_line_amount", 0.0)
        new_rows.loc[i, "related_entities"] = json.dumps([row["document_id"], row.get("run_id")], ensure_ascii=False)
        new_rows.loc[i, "cluster_id"] = row.get("run_id")
        new_rows.loc[i, "injection_strategy"] = "BatchAnomalyDetectorUniverseSubset"
        new_rows.loc[i, "structured_strategy_type"] = "BatchAnomaly"
        new_rows.loc[i, "structured_strategy_json"] = json.dumps(meta, ensure_ascii=False)
        new_rows.loc[i, "causal_reason_type"] = "BatchRunReviewSignal"
        new_rows.loc[i, "causal_reason_json"] = json.dumps(meta, ensure_ascii=False)
        new_rows.loc[i, "scenario_id"] = row.get("run_id")
        new_rows.loc[i, "metadata_json"] = json.dumps(meta, ensure_ascii=False)
    rebuilt = pd.concat([keep, new_rows], ignore_index=True, sort=False)
    rebuilt.to_csv(path, index=False)
    _write_json_records(LABELS / "anomaly_labels.json", rebuilt)
    _write_jsonl_records(LABELS / "anomaly_labels.jsonl", rebuilt)


def _annotate_control_sidecar(stem: str, truth_docs: set[str]) -> dict[str, int]:
    path = LABELS / f"{stem}.csv"
    if not path.exists():
        return {"rows": 0, "raw_hit_overlap": 0}
    df = pd.read_csv(path, low_memory=False)
    if "document_id" not in df.columns:
        return {"rows": int(len(df)), "raw_hit_overlap": 0}
    df["control_role"] = stem
    df["is_rule_truth"] = False
    df["raw_l406_hit"] = df["document_id"].astype(str).isin(truth_docs)
    df["control_policy"] = (
        "L4-06 control sidecar only; excluded from rule_truth_L4_06 and strict rule recall"
    )
    df.to_csv(path, index=False)
    _write_json_records(LABELS / f"{stem}.json", df)
    for year in YEARS:
        year_col = pd.to_numeric(df.get("fiscal_year"), errors="coerce") if "fiscal_year" in df.columns else pd.Series([], dtype=float)
        year_df = df.loc[year_col.eq(year)].copy()
        year_df.to_csv(LABELS / f"{stem}_{year}.csv", index=False)
        _write_json_records(LABELS / f"{stem}_{year}.json", year_df)
    return {
        "rows": int(len(df)),
        "raw_hit_overlap": int(df["raw_l406_hit"].sum()),
    }


def _read_docs(path: Path) -> set[str]:
    if not path.exists():
        return set()
    df = pd.read_csv(path, usecols=lambda column: column == "document_id", low_memory=False)
    if "document_id" not in df.columns:
        return set()
    return set(df["document_id"].dropna().astype(str).unique())


def _write_manifest(
    truth: pd.DataFrame,
    confirmed: pd.DataFrame,
    breakdown: dict[str, object],
    previous_truth: set[str],
    control_stats: dict[str, dict[str, int]],
) -> None:
    current_truth = set(truth["document_id"].astype(str))
    confirmed_docs = set(confirmed["document_id"].astype(str))
    manifest = {
        "version": "v112_candidate",
        "base_version": "v111_candidate",
        "patch": "l406_truth_realign_to_batch_detector_universe",
        "rule_id": RULE_ID,
        "truth_docs": int(len(current_truth)),
        "truth_by_year": {
            str(k): int(v) for k, v in truth["fiscal_year"].value_counts().sort_index().items()
        },
        "truth_by_source": {
            str(k): int(v) for k, v in truth["source"].value_counts().sort_index().items()
        },
        "added_docs": int(len(current_truth - previous_truth)),
        "removed_stale_docs": int(len(previous_truth - current_truth)),
        "confirmed_subset_docs": int(len(confirmed_docs)),
        "confirmed_subset_in_truth": int(len(confirmed_docs & current_truth)),
        "confirmed_by_year": {
            str(k): int(v) for k, v in confirmed["fiscal_year"].value_counts().sort_index().items()
        },
        "confirmed_by_source": {
            str(k): int(v) for k, v in confirmed["source"].value_counts().sort_index().items()
        },
        "score_bucket_counts": {
            str(k): int(v) for k, v in truth["score_bucket"].value_counts().items()
        },
        "control_sidecars": control_stats,
        "detector_breakdown": breakdown,
        "contract": {
            "rule_truth": "current L4-06 detector raw batch review universe",
            "batch_review_population": "same as rule_truth_L4_06",
            "confirmed_anomalies": "stratified subset of rule truth; no recurring-only source outside detector contract",
            "normal_boundary_controls": "control sidecars only; excluded from strict rule truth",
            "recurring_policy": "recurring is not a batch source unless classified as batch/interface/automated in journal source",
            "anti_fitting": (
                "Detector output is not changed. DataSynth truth is aligned to the "
                "Phase1 combo-only raw review contract and controls are separated."
            ),
        },
    }
    (LABELS / "V112_L406_TRUTH_REALIGNMENT.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V112_CANDIDATE.md").write_text(
        "\n".join(
            [
                "# DataSynth v112 Candidate",
                "",
                "Base: `datasynth_v111_candidate`",
                "",
                "Patch: realign L4-06 rule truth to the current batch detector universe.",
                "",
                "Contract:",
                "- `rule_truth_L4_06.csv` and `batch_review_population.csv` are the raw L4-06 batch review universe.",
                "- `batch_confirmed_anomalies.csv` and `BatchAnomaly` labels are a confirmed subset of that universe.",
                "- `batch_normal_controls.csv` and `batch_boundary_controls.csv` are controls only, not strict rule truth.",
                "- `recurring` remains outside the L4-06 batch source contract unless the journal source is classified as batch/interface/automated.",
                "",
                f"Truth documents: {len(current_truth):,}",
                f"Confirmed subset: {len(confirmed_docs):,}",
                f"Confirmed subset in truth: {len(confirmed_docs & current_truth):,} / {len(confirmed_docs):,}",
                f"Added documents: {len(current_truth - previous_truth):,}",
                f"Removed stale documents: {len(previous_truth - current_truth):,}",
                "",
                "This patch does not modify journal entry rows or the detector.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> int:
    _copy_candidate_fast()
    previous_truth = _read_docs(LABELS / "rule_truth_L4_06.csv")
    df = _load_journal()
    truth, breakdown = _truth_from_detector(df)
    confirmed = _select_confirmed(truth)
    _write_truth_family(truth)
    _replace_combined_rule_truth(truth)
    _write_confirmed(confirmed)
    _replace_anomaly_labels(confirmed)
    truth_docs = set(truth["document_id"].astype(str))
    control_stats = {
        "batch_normal_controls": _annotate_control_sidecar("batch_normal_controls", truth_docs),
        "batch_boundary_controls": _annotate_control_sidecar("batch_boundary_controls", truth_docs),
    }
    _write_manifest(truth, confirmed, breakdown, previous_truth, control_stats)
    current_truth = set(truth["document_id"].astype(str))
    print(
        json.dumps(
            {
                "dest": str(DEST.relative_to(ROOT)),
                "truth_docs": int(len(current_truth)),
                "added_docs": int(len(current_truth - previous_truth)),
                "removed_stale_docs": int(len(previous_truth - current_truth)),
                "confirmed_docs": int(len(confirmed)),
                "confirmed_in_truth": int(len(set(confirmed["document_id"].astype(str)) & current_truth)),
                "truth_by_year": {
                    str(k): int(v)
                    for k, v in truth["fiscal_year"].value_counts().sort_index().items()
                },
                "truth_by_source": {
                    str(k): int(v) for k, v in truth["source"].value_counts().sort_index().items()
                },
                "confirmed_by_source": {
                    str(k): int(v) for k, v in confirmed["source"].value_counts().sort_index().items()
                },
                "control_stats": control_stats,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
