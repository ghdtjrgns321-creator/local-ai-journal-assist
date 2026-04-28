from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path

import pandas as pd


PERCENTILE = 0.01
MAX_LINES_PER_DOC = 100
TARGETS = {
    2022: {"confirmed": 17, "normal": 80},
    2023: {"confirmed": 19, "normal": 86},
    2024: {"confirmed": 16, "normal": 92},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build v49 L4-04 rare account-pair truth sidecars.")
    parser.add_argument("--source", required=True, help="Source dataset directory, normally datasynth_v48_candidate")
    parser.add_argument("--output", required=True, help="Output candidate directory")
    parser.add_argument("--force", action="store_true", help="Overwrite output directory")
    parser.add_argument("--version", default="v49_candidate", help="Version label written to manifest/freeze note")
    return parser.parse_args()


def account_code(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().str.lower().str.replace(r"\.0+$", "", regex=True)


def bool_series(series: pd.Series) -> pd.Series:
    return series.astype("string").fillna("").str.strip().str.lower().isin({"true", "1", "yes", "y"})


def first_nonempty(values: pd.Series) -> str:
    for value in values:
        if pd.notna(value) and str(value).strip():
            return str(value)
    return ""


def write_records(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for record in records for key in record}) if records else []
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)


def write_sidecar_family(labels_dir: Path, stem: str, records: list[dict]) -> None:
    write_records(labels_dir / f"{stem}.csv", records)
    (labels_dir / f"{stem}.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    for year in sorted({int(r["fiscal_year"]) for r in records}):
        year_records = [r for r in records if int(r["fiscal_year"]) == year]
        write_records(labels_dir / f"{stem}_{year}.csv", year_records)
        (labels_dir / f"{stem}_{year}.json").write_text(
            json.dumps(year_records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def load_minimal_rows(source: Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    usecols = [
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
        "gl_account",
        "debit_amount",
        "credit_amount",
        "line_text",
        "header_text",
        "is_period_end",
        "is_after_hours",
        "is_weekend",
        "is_holiday",
    ]
    for year in (2022, 2023, 2024):
        path = source / f"journal_entries_{year}.csv"
        header = pd.read_csv(path, nrows=0).columns
        cols = [col for col in usecols if col in header]
        df = pd.read_csv(path, dtype=str, usecols=cols, low_memory=False)
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def build_rare_pairs(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object], set[str]]:
    work = df[["document_id", "gl_account", "debit_amount", "credit_amount"]].copy()
    work["_account_code"] = account_code(work["gl_account"])
    debit = pd.to_numeric(work["debit_amount"], errors="coerce").fillna(0.0)
    credit = pd.to_numeric(work["credit_amount"], errors="coerce").fillna(0.0)
    doc_sizes = work.groupby("document_id").size()
    bloated_docs = set(doc_sizes[doc_sizes > MAX_LINES_PER_DOC].index.astype(str))
    safe = work[~work["document_id"].astype(str).isin(bloated_docs)].copy()
    debits = safe.loc[
        (debit.loc[safe.index] > 0) & safe["_account_code"].ne(""),
        ["document_id", "_account_code"],
    ].rename(
        columns={"_account_code": "gl_account_dr"}
    )
    credits = safe.loc[
        (credit.loc[safe.index] > 0) & safe["_account_code"].ne(""),
        ["document_id", "_account_code"],
    ].rename(
        columns={"_account_code": "gl_account_cr"}
    )
    pairs = debits.merge(credits, on="document_id")
    pair_counts = pairs.groupby(["gl_account_dr", "gl_account_cr"]).size()
    threshold = max(float(pair_counts.quantile(PERCENTILE)), 1.0)
    rare_idx = pair_counts[pair_counts <= threshold].reset_index(name="pair_count")
    rare_pairs = pairs.merge(rare_idx, on=["gl_account_dr", "gl_account_cr"], how="inner")
    rare_pairs = rare_pairs[
        rare_pairs["gl_account_dr"].astype(str).str.strip().ne("")
        & rare_pairs["gl_account_cr"].astype(str).str.strip().ne("")
    ].copy()
    rare_pairs["rare_pair"] = rare_pairs["gl_account_dr"].astype(str) + "->" + rare_pairs["gl_account_cr"].astype(str)
    meta = {
        "percentile": PERCENTILE,
        "threshold_count": threshold,
        "distinct_pair_count": int(len(pair_counts)),
        "rare_pair_count": int(len(rare_idx)),
        "candidate_document_count": int(rare_pairs["document_id"].nunique()),
        "excluded_large_document_count": int(len(bloated_docs)),
    }
    return rare_pairs, meta, bloated_docs


def document_summary(df: pd.DataFrame, rare_pairs: pd.DataFrame, existing_label_docs: set[str]) -> pd.DataFrame:
    rare_doc_ids = set(rare_pairs["document_id"].astype(str))
    rare_pair_map = (
        rare_pairs.groupby("document_id")["rare_pair"]
        .apply(lambda values: "|".join(sorted(set(values))[:8]))
        .to_dict()
    )
    rare_pair_count_map = rare_pairs.groupby("document_id")["rare_pair"].nunique().to_dict()
    pair_min_count_map = rare_pairs.groupby("document_id")["pair_count"].min().to_dict()
    work = df[df["document_id"].astype(str).isin(rare_doc_ids)].copy()
    debit = pd.to_numeric(work.get("debit_amount", 0), errors="coerce").fillna(0.0).abs()
    credit = pd.to_numeric(work.get("credit_amount", 0), errors="coerce").fillna(0.0).abs()
    work["_line_amount"] = pd.concat([debit, credit], axis=1).max(axis=1)
    rows: list[dict] = []
    for doc_id, group in work.groupby("document_id", sort=False):
        source = first_nonempty(group.get("source", pd.Series(dtype=object))).lower()
        posting_date = first_nonempty(group.get("posting_date", pd.Series(dtype=object)))
        parsed_posting = pd.to_datetime(posting_date, errors="coerce")
        is_period_end = bool_series(group.get("is_period_end", pd.Series(False, index=group.index))).any()
        if not is_period_end and pd.notna(parsed_posting):
            is_period_end = int(parsed_posting.day) >= 26 or int(parsed_posting.day) <= 5
        text = " ".join(
            [
                first_nonempty(group.get("header_text", pd.Series(dtype=object))),
                " ".join(group.get("line_text", pd.Series(dtype=object)).fillna("").astype(str).head(8)),
            ]
        ).lower()
        rows.append(
            {
                "document_id": str(doc_id),
                "company_code": first_nonempty(group.get("company_code", pd.Series(dtype=object))),
                "fiscal_year": int(first_nonempty(group.get("fiscal_year", pd.Series(dtype=object)))),
                "posting_date": posting_date,
                "document_number": first_nonempty(group.get("document_number", pd.Series(dtype=object))),
                "document_type": first_nonempty(group.get("document_type", pd.Series(dtype=object))),
                "business_process": first_nonempty(group.get("business_process", pd.Series(dtype=object))),
                "source": source,
                "created_by": first_nonempty(group.get("created_by", pd.Series(dtype=object))),
                "approved_by": first_nonempty(group.get("approved_by", pd.Series(dtype=object))),
                "line_count": int(len(group)),
                "max_line_amount": round(float(group["_line_amount"].max()), 2),
                "rare_pairs": rare_pair_map.get(str(doc_id), ""),
                "rare_pair_count": int(rare_pair_count_map.get(str(doc_id), 0)),
                "min_pair_count": int(pair_min_count_map.get(str(doc_id), 0)),
                "is_manual_or_adjustment": source in {"manual", "adjustment"},
                "is_period_boundary": bool(is_period_end),
                "is_after_hours": bool_series(group.get("is_after_hours", pd.Series(False, index=group.index))).any(),
                "is_weekend": bool_series(group.get("is_weekend", pd.Series(False, index=group.index))).any(),
                "is_holiday": bool_series(group.get("is_holiday", pd.Series(False, index=group.index))).any(),
                "has_weak_description": any(token in text for token in ["기타", "임시", "조정", "정리", "misc", "manual"]),
                "has_existing_anomaly_label": str(doc_id) in existing_label_docs,
                "truth_basis": "rare debit-credit account pair review population",
                "evaluation_policy": "review_population_not_exhaustive_fraud_truth",
            }
        )
    return pd.DataFrame(rows)


def classify(population: pd.DataFrame, existing_l404_docs: set[str]) -> tuple[list[dict], list[dict]]:
    confirmed_records: list[dict] = []
    normal_records: list[dict] = []
    used = set(existing_l404_docs)
    for year, targets in TARGETS.items():
        year_pop = population[population["fiscal_year"].eq(year)].copy()
        year_pop["_confirmed_priority"] = (
            year_pop["is_manual_or_adjustment"].astype(int) * 3
            + year_pop["is_period_boundary"].astype(int) * 2
            + year_pop["is_after_hours"].astype(int)
            + year_pop["has_weak_description"].astype(int)
            + year_pop["has_existing_anomaly_label"].astype(int)
            + year_pop["rare_pair_count"].clip(upper=5)
            + year_pop["max_line_amount"].rank(pct=True)
        )
        year_pop["_normal_priority"] = (
            year_pop["source"].isin(["automated", "recurring", "batch", "system"]).astype(int) * 3
            + (~year_pop["is_period_boundary"]).astype(int)
            + (~year_pop["is_after_hours"]).astype(int)
            + (~year_pop["has_weak_description"]).astype(int)
            + year_pop["max_line_amount"].rank(pct=True)
        )
        eligible_confirmed = year_pop[~year_pop["document_id"].isin(used)].copy()
        eligible_confirmed["_sort_key"] = eligible_confirmed["document_id"].map(lambda value: f"{year}:confirmed:{value}")
        confirmed = eligible_confirmed.sort_values(["_confirmed_priority", "_sort_key"], ascending=[False, True]).head(
            targets["confirmed"]
        )
        used.update(confirmed["document_id"].astype(str))
        for idx, (_, row) in enumerate(confirmed.iterrows(), start=1):
            record = row.drop(labels=[c for c in row.index if c.startswith("_")], errors="ignore").to_dict()
            record.update(
                {
                    "case_id": f"L404UAP-{year}-{idx:04d}",
                    "anomaly_type": "UnusualAccountPair",
                    "truth_basis": "confirmed unusual account-pair anomaly with corroborating context",
                    "evaluation_policy": "confirmed anomaly recall subset; review population is broader",
                }
            )
            confirmed_records.append(record)

        eligible_normal = year_pop[~year_pop["document_id"].isin(used)].copy()
        eligible_normal["_sort_key"] = eligible_normal["document_id"].map(lambda value: f"{year}:normal:{value}")
        normal = eligible_normal.sort_values(["_normal_priority", "_sort_key"], ascending=[False, True]).head(
            targets["normal"]
        )
        used.update(normal["document_id"].astype(str))
        for idx, (_, row) in enumerate(normal.iterrows(), start=1):
            record = row.drop(labels=[c for c in row.index if c.startswith("_")], errors="ignore").to_dict()
            record.update(
                {
                    "control_id": f"L404NC-{year}-{idx:04d}",
                    "control_reason": "normal rare account-pair business context",
                    "truth_basis": "normal rare-pair control",
                    "evaluation_policy": "review candidate, not confirmed anomaly",
                }
            )
            normal_records.append(record)
    return confirmed_records, normal_records


def append_labels(labels_dir: Path, confirmed_records: list[dict]) -> None:
    labels_path = labels_dir / "anomaly_labels.csv"
    labels = pd.read_csv(labels_path, dtype=str, keep_default_na=False)
    labels = labels[~labels["anomaly_type"].eq("UnusualAccountPair")].copy()
    max_id = max(int(value.replace("ANO", "")) for value in labels["anomaly_id"].astype(str) if value.startswith("ANO"))
    new_rows = []
    for offset, record in enumerate(confirmed_records, start=1):
        metadata = {
            "rule_id": "L4-04",
            "case_id": record["case_id"],
            "rare_pairs": record["rare_pairs"],
            "rare_pair_count": record["rare_pair_count"],
            "min_pair_count": record["min_pair_count"],
            "truth_basis": record["truth_basis"],
            "evaluation_policy": "confirmed subset; rare_account_pair_review_population is coverage only",
        }
        new_rows.append(
            {
                "anomaly_id": f"ANO{max_id + offset:08d}",
                "anomaly_category": "ReviewSignal",
                "anomaly_type": "UnusualAccountPair",
                "document_id": record["document_id"],
                "document_type": record["document_type"],
                "company_code": record["company_code"],
                "anomaly_date": record["posting_date"],
                "detection_timestamp": "2026-04-26 00:00:00",
                "confidence": "0.70",
                "severity": "2",
                "description": "L4-04 rare debit-credit account-pair anomaly",
                "is_injected": "True",
                "monetary_impact": str(record["max_line_amount"]),
                "related_entities": json.dumps([record["document_id"]], ensure_ascii=False),
                "cluster_id": "",
                "original_document_hash": "",
                "injection_strategy": "RareAccountPairCoverage",
                "structured_strategy_type": "UnusualAccountPair",
                "structured_strategy_json": json.dumps(metadata, ensure_ascii=False),
                "causal_reason_type": "RareAccountPair",
                "causal_reason_json": json.dumps(metadata, ensure_ascii=False),
                "parent_anomaly_id": "",
                "child_anomaly_ids": "[]",
                "scenario_id": "",
                "run_id": "",
                "generation_seed": "",
                "metadata_json": json.dumps(metadata, ensure_ascii=False),
            }
        )
    merged = pd.concat([labels, pd.DataFrame(new_rows, columns=labels.columns)], ignore_index=True)
    merged.to_csv(labels_path, index=False)
    merged.to_json(labels_dir / "anomaly_labels.json", orient="records", force_ascii=False, indent=2)
    with (labels_dir / "anomaly_labels.jsonl").open("w", encoding="utf-8") as fh:
        for row in merged.to_dict("records"):
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary_path = labels_dir / "anomaly_labels_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    counts = merged["anomaly_type"].value_counts().to_dict()
    summary["total_labels"] = int(len(merged))
    summary["label_counts"] = {str(key): int(value) for key, value in counts.items()}
    summary["v49_rare_account_pair"] = {
        "added_confirmed_labels": len(new_rows),
        "policy": "confirmed subset only; rare_account_pair_review_population is coverage truth",
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    args = parse_args()
    source = Path(args.source)
    output = Path(args.output)
    if output.exists():
        if not args.force:
            raise SystemExit(f"Output exists: {output}")
        shutil.rmtree(output)
    shutil.copytree(source, output)

    labels_dir = output / "labels"
    labels = pd.read_csv(labels_dir / "anomaly_labels.csv", dtype=str, keep_default_na=False)
    existing_label_docs = set(labels["document_id"].astype(str))
    existing_l404_docs = set(labels.loc[labels["anomaly_type"].eq("UnusualAccountPair"), "document_id"].astype(str))
    df = load_minimal_rows(output)
    rare_pairs, meta, bloated_docs = build_rare_pairs(df)
    population = document_summary(df, rare_pairs, existing_label_docs)
    population["population_id"] = [f"L404POP-{idx + 1:05d}" for idx in range(len(population))]
    confirmed, normal = classify(population, existing_l404_docs)

    excluded = [
        {"document_id": doc_id, "exclusion_reason": f"line_count_over_{MAX_LINES_PER_DOC}"}
        for doc_id in sorted(bloated_docs)
    ]
    write_sidecar_family(labels_dir, "rare_account_pair_review_population", population.to_dict("records"))
    write_sidecar_family(labels_dir, "rare_account_pair_confirmed_anomalies", confirmed)
    write_sidecar_family(labels_dir, "rare_account_pair_normal_controls", normal)
    write_records(labels_dir / "rare_account_pair_excluded_large_docs.csv", excluded)
    (labels_dir / "rare_account_pair_excluded_large_docs.json").write_text(
        json.dumps(excluded, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    append_labels(labels_dir, confirmed)

    summary = {
        str(year): {
            "review_population": int((population["fiscal_year"] == year).sum()),
            "confirmed": int(sum(int(r["fiscal_year"]) == year for r in confirmed)),
            "normal_controls": int(sum(int(r["fiscal_year"]) == year for r in normal)),
        }
        for year in (2022, 2023, 2024)
    }
    manifest_path = output / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest.setdefault("candidate_patches", []).append(
        {
            "version": args.version,
            "source": source.name,
            "purpose": "Add L4-04 rare account-pair review population, confirmed subset, and normal controls.",
            "rare_pair_meta": meta,
            "summary": summary,
            "anti_fitting_policy": [
                "Do not label every rare account pair as UnusualAccountPair.",
                "Keep normal rare-pair controls for legitimate low-frequency business events.",
                "Use confirmed labels for recall and rare_account_pair_review_population for coverage.",
                "Preserve large-document exclusions to match detector's Cartesian-product guardrail.",
            ],
        }
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    freeze_name = f"FREEZE_{args.version.upper()}.md"
    (output / freeze_name).write_text(
        f"# DataSynth {args.version} Candidate\n\n"
        "L4-04 rare account-pair truth and review-population patch.\n\n"
        f"- Source: `{source.name}`\n"
        "- Adds `labels/rare_account_pair_review_population*`.\n"
        "- Adds `labels/rare_account_pair_confirmed_anomalies*`.\n"
        "- Adds `labels/rare_account_pair_normal_controls*`.\n"
        "- Adds `labels/rare_account_pair_excluded_large_docs*` for >100-line Cartesian guardrail exclusions.\n"
        "- Keeps L4-04 as rare-pair review anchor, not exhaustive fraud truth.\n\n"
        f"Rare pair meta: `{json.dumps(meta, ensure_ascii=False)}`\n\n"
        f"Summary: `{json.dumps(summary, ensure_ascii=False)}`\n",
        encoding="utf-8",
    )
    print(json.dumps({"rare_pair_meta": meta, "summary": summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
