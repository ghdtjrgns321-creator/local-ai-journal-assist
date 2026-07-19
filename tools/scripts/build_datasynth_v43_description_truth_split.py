from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.feature.text_features import add_description_quality


PHASE1_LABEL = "MissingOrCorruptedDescription"
PHASE3_LABEL = "VagueDescription"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build v43 L3-08 description truth split candidate.")
    parser.add_argument("--source", required=True, help="Source dataset directory, normally datasynth_v42_candidate")
    parser.add_argument("--output", required=True, help="Output candidate directory")
    parser.add_argument("--force", action="store_true", help="Overwrite output directory")
    return parser.parse_args()


def write_records(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for record in records for key in record}) if records else []
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)


def write_sidecar_family(labels_dir: Path, stem: str, records: list[dict], year_key: str = "fiscal_year") -> None:
    write_records(labels_dir / f"{stem}.csv", records)
    (labels_dir / f"{stem}.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    for year in sorted({int(r[year_key]) for r in records}):
        year_records = [r for r in records if int(r[year_key]) == year]
        write_records(labels_dir / f"{stem}_{year}.csv", year_records)
        (labels_dir / f"{stem}_{year}.json").write_text(json.dumps(year_records, ensure_ascii=False, indent=2), encoding="utf-8")


def build_year_quality(output: Path, year: int, existing_vague_docs: set[str]) -> tuple[list[dict], list[dict], list[dict]]:
    path = output / f"journal_entries_{year}.csv"
    df = pd.read_csv(path, low_memory=False)
    add_description_quality(df)
    df["_doc_id_str"] = df["document_id"].astype(str)
    df.to_csv(path, index=False)

    population: list[dict] = []
    missing_records: list[dict] = []
    vague_records: list[dict] = []
    doc_df = (
        df.groupby("document_id")
        .agg(
            company_code=("company_code", "first"),
            fiscal_year=("fiscal_year", "first"),
            posting_date=("posting_date", "first"),
            document_number=("document_number", "first"),
            document_type=("document_type", "first"),
            business_process=("business_process", "first"),
            source=("source", "first"),
            created_by=("created_by", "first"),
            header_text=("header_text", "first"),
            line_text=("line_text", "first"),
            description_quality=("description_quality", _worst_quality),
            line_count=("document_id", "size"),
        )
        .reset_index()
    )
    for row in doc_df.itertuples(index=False):
        doc_id = str(row.document_id)
        quality = str(row.description_quality)
        is_phase1 = quality in {"missing", "corrupted", "poor"}
        is_phase3 = doc_id in existing_vague_docs and not is_phase1
        record = {
            "document_id": doc_id,
            "company_code": row.company_code,
            "fiscal_year": int(row.fiscal_year),
            "posting_date": str(row.posting_date),
            "document_number": row.document_number,
            "document_type": row.document_type,
            "business_process": row.business_process,
            "source": row.source,
            "created_by": row.created_by,
            "header_text": _safe_text(row.header_text),
            "line_text": _safe_text(row.line_text),
            "description_quality": quality,
            "line_count": int(row.line_count),
            "is_missing_or_corrupted_description": bool(is_phase1),
            "is_vague_or_risky_description": bool(is_phase3),
            "truth_basis": "description_quality_taxonomy",
            "evaluation_policy": "phase1_missing_corrupted_phase3_semantic_vague",
        }
        population.append(record)
        if is_phase1:
            missing_records.append({**record, "anomaly_type": PHASE1_LABEL})
        if is_phase3:
            vague_records.append({**record, "semantic_label": PHASE3_LABEL})
    return population, missing_records, vague_records


def _worst_quality(values: pd.Series) -> str:
    order = {"missing": 0, "corrupted": 1, "poor": 1, "normal": 2}
    vals = [str(v) for v in values.dropna()]
    if not vals:
        return "missing"
    return min(vals, key=lambda value: order.get(value, 2))


def _safe_text(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value)


def append_missing_labels(output: Path, missing_records: list[dict]) -> pd.DataFrame:
    labels_path = output / "labels" / "anomaly_labels.csv"
    labels = pd.read_csv(labels_path, low_memory=False)
    existing = set(labels[labels["anomaly_type"].eq(PHASE1_LABEL)]["document_id"].astype(str))
    rows = []
    max_num = _max_anomaly_num(labels)
    cols = list(labels.columns)
    for record in missing_records:
        if str(record["document_id"]) in existing:
            continue
        metadata = {
            "description_quality": record["description_quality"],
            "header_text": record["header_text"],
            "line_text": record["line_text"],
            "v43_label_policy": "phase1_missing_or_corrupted_not_semantic_vague",
        }
        row = {col: "" for col in cols}
        row.update(
            {
                "anomaly_id": f"ANO{max_num + len(rows) + 1:08d}",
                "anomaly_category": "ProcessIssue",
                "anomaly_type": PHASE1_LABEL,
                "document_id": record["document_id"],
                "document_type": "JE",
                "company_code": record["company_code"],
                "anomaly_date": str(record["posting_date"])[:10],
                "detection_timestamp": pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                "confidence": 0.92,
                "severity": 1,
                "description": f"Description is {record['description_quality']} and cannot support audit traceability",
                "is_injected": True,
                "related_entities": json.dumps([], ensure_ascii=False),
                "injection_strategy": PHASE1_LABEL,
                "scenario_id": f"L308-{record['fiscal_year']}-{len(rows)+1:04d}",
                "metadata_json": json.dumps(metadata, ensure_ascii=False, separators=(",", ":")),
            }
        )
        rows.append(row)
    if rows:
        labels = pd.concat([labels, pd.DataFrame(rows, columns=cols)], ignore_index=True)
    labels.to_csv(labels_path, index=False)
    rewrite_label_jsons(output / "labels", labels)
    return labels


def _max_anomaly_num(labels: pd.DataFrame) -> int:
    nums = labels["anomaly_id"].fillna("").astype(str).str.extract(r"ANO(\d+)")[0].dropna().astype(int)
    return int(nums.max()) if not nums.empty else 0


def read_metadata(value: object) -> dict:
    if pd.isna(value) or str(value).strip() == "":
        return {}
    try:
        parsed = json.loads(str(value))
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def rewrite_label_jsons(labels_dir: Path, labels: pd.DataFrame) -> None:
    records = []
    for _, row in labels.iterrows():
        raw = row.get("related_entities", "")
        related = []
        if pd.notna(raw) and str(raw).strip():
            try:
                parsed = json.loads(str(raw))
                related = parsed if isinstance(parsed, list) else [str(raw)]
            except json.JSONDecodeError:
                related = [str(raw)]
        records.append(
            {
                "anomaly_id": row["anomaly_id"],
                "anomaly_type": {row["anomaly_category"]: row["anomaly_type"]},
                "document_id": row["document_id"],
                "document_type": row["document_type"],
                "company_code": row["company_code"],
                "anomaly_date": str(row["anomaly_date"]),
                "detection_timestamp": str(row["detection_timestamp"]),
                "confidence": row["confidence"],
                "severity": int(row["severity"]) if pd.notna(row["severity"]) and str(row["severity"]) != "" else None,
                "description": row["description"],
                "related_entities": related,
                "metadata": read_metadata(row.get("metadata_json", "")),
                "is_injected": bool(row["is_injected"]),
                "injection_strategy": row["injection_strategy"],
            }
        )
    (labels_dir / "anomaly_labels.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    with (labels_dir / "anomaly_labels.jsonl").open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    summary = {
        "total_labels": int(len(labels)),
        "by_category": {k: int(v) for k, v in labels["anomaly_category"].value_counts().to_dict().items()},
        "by_company": {k: int(v) for k, v in labels["company_code"].value_counts().to_dict().items()},
    }
    (labels_dir / "anomaly_labels_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def patch_journal_json_description_quality(output: Path, quality_by_doc: dict[str, str]) -> int:
    json_path = output / "journal_entries.json"
    if not json_path.exists():
        return 0
    tmp_path = json_path.with_suffix(".json.tmp")
    patched = 0
    first_written = False
    with json_path.open("r", encoding="utf-8") as src, tmp_path.open("w", encoding="utf-8", newline="\n") as dst:
        dst.write("[\n")
        buffer: list[str] = []
        depth = 0
        in_object = False
        for line in src:
            stripped = line.strip()
            if not in_object:
                if stripped in {"[", "]"}:
                    continue
                if stripped.startswith("{"):
                    in_object = True
                    buffer = [line]
                    depth = line.count("{") - line.count("}")
                continue
            buffer.append(line)
            depth += line.count("{") - line.count("}")
            if depth == 0:
                raw = "".join(buffer).rstrip()
                if raw.endswith(","):
                    raw = raw[:-1]
                record = json.loads(raw)
                doc_id = str(record.get("header", {}).get("document_id", ""))
                quality = quality_by_doc.get(doc_id, "normal")
                record.setdefault("header", {})["description_quality"] = quality
                for line_obj in record.get("lines", []):
                    line_obj["description_quality"] = quality
                patched += 1
                if first_written:
                    dst.write(",\n")
                dst.write(json.dumps(record, ensure_ascii=False, indent=2))
                first_written = True
                in_object = False
                buffer = []
        dst.write("\n]\n")
    tmp_path.replace(json_path)
    return patched


def write_preview(output: Path, summary: dict) -> None:
    text = f"""# DataSynth v43 Candidate

v43 keeps v42 and splits L3-08 description truth into Phase 1 data-quality truth and Phase 3 semantic vague truth.

## Summary

- Source baseline: `datasynth_v42_candidate`
- MissingOrCorruptedDescription labels: {summary['missing_or_corrupted_description']['total']}
- VagueDescription kept for Phase 3: {summary['vague_or_risky_description']['total']}
- Added column: `description_quality`
- Policy: Phase 1 L3-08 evaluates missing/corrupted descriptions only.

## Files

- `labels/description_quality_population.csv/json`
- `labels/missing_corrupted_description_truth.csv/json`
- `labels/vague_or_risky_description_truth.csv/json`
- `V43_DESCRIPTION_TRUTH_SPLIT.json`
"""
    (output / "PREVIEW.md").write_text(text, encoding="utf-8")
    (output / "FREEZE_V43_CANDIDATE.md").write_text(text, encoding="utf-8")


def main() -> None:
    args = parse_args()
    source = Path(args.source)
    output = Path(args.output)
    if output.exists():
        if not args.force:
            raise FileExistsError(f"{output} already exists; pass --force")
        shutil.rmtree(output)
    shutil.copytree(source, output)

    labels_dir = output / "labels"
    labels = pd.read_csv(labels_dir / "anomaly_labels.csv", low_memory=False)
    existing_vague_docs = set(labels[labels["anomaly_type"].eq(PHASE3_LABEL)]["document_id"].astype(str))

    population: list[dict] = []
    missing_records: list[dict] = []
    vague_records: list[dict] = []
    for year in [2022, 2023, 2024]:
        year_population, year_missing, year_vague = build_year_quality(output, year, existing_vague_docs)
        population.extend(year_population)
        missing_records.extend(year_missing)
        vague_records.extend(year_vague)

    all_year = pd.concat(
        [pd.read_csv(output / f"journal_entries_{year}.csv", low_memory=False) for year in [2022, 2023, 2024]],
        ignore_index=True,
    )
    all_year.to_csv(output / "journal_entries.csv", index=False)
    quality_by_doc = {record["document_id"]: record["description_quality"] for record in population}
    json_patched = patch_journal_json_description_quality(output, quality_by_doc)

    labels = append_missing_labels(output, missing_records)
    write_sidecar_family(labels_dir, "description_quality_population", population)
    write_sidecar_family(labels_dir, "missing_corrupted_description_truth", missing_records)
    write_sidecar_family(labels_dir, "vague_or_risky_description_truth", vague_records)

    summary = {
        "candidate_version": "v43_candidate",
        "source_baseline": "datasynth_v42_candidate",
        "focus": "Split L3-08 missing/corrupted descriptions from Phase 3 semantic vague descriptions",
        "description_quality_population": {
            "total": len(population),
            "by_quality": {str(k): int(v) for k, v in sorted(Counter(r["description_quality"] for r in population).items())},
        },
        "missing_or_corrupted_description": {
            "total": len(missing_records),
            "by_year": {str(k): int(v) for k, v in sorted(Counter(r["fiscal_year"] for r in missing_records).items())},
            "by_quality": {str(k): int(v) for k, v in sorted(Counter(r["description_quality"] for r in missing_records).items())},
        },
        "vague_or_risky_description": {
            "total": len(vague_records),
            "by_year": {str(k): int(v) for k, v in sorted(Counter(r["fiscal_year"] for r in vague_records).items())},
        },
        "label_counts_after_patch": {
            PHASE1_LABEL: int((labels["anomaly_type"] == PHASE1_LABEL).sum()),
            PHASE3_LABEL: int((labels["anomaly_type"] == PHASE3_LABEL).sum()),
        },
        "journal_json_patched_documents": json_patched,
        "contract": {
            "l308_phase1_truth": "Use MissingOrCorruptedDescription for Phase 1 L3-08.",
            "phase3_semantic_truth": "Keep VagueDescription/VagueOrRiskyDescription for semantic NLP review.",
            "not_test_fitting": "Truth is based on deterministic text quality taxonomy, not detector result backfill.",
        },
    }
    (output / "V43_DESCRIPTION_TRUTH_SPLIT.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_preview(output, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
