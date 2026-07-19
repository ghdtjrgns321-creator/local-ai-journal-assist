from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections import Counter
from pathlib import Path

import pandas as pd


TARGETS = {
    2022: {
        "short_valid": 55,
        "system_code_valid": 45,
        "line_missing_header_valid": 50,
        "semantic_vague_not_l308": 24,
    },
    2023: {
        "short_valid": 52,
        "system_code_valid": 48,
        "line_missing_header_valid": 46,
        "semantic_vague_not_l308": 28,
    },
    2024: {
        "short_valid": 58,
        "system_code_valid": 51,
        "line_missing_header_valid": 48,
        "semantic_vague_not_l308": 30,
    },
}

SHORT_VALID = ["VAT", "AP", "AR", "급여", "수수료", "정산", "이자", "운임", "보험", "임차료"]
SYSTEM_CODE_TEMPLATES = ["INV-{year}-{seq:06d}", "GR-{year}-{seq:06d}", "PAY-{year}-{seq:06d}", "BATCH-{year}-{seq:05d}"]
HEADER_VALID = [
    "{year}년 {month:02d}월 공급업체 정산 전표",
    "{year}년 {month:02d}월 고객 청구 자동전표",
    "{year}년 {month:02d}월 급여 배부 전표",
    "{year}년 {month:02d}월 감가상각 자동전표",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build v44 L3-08 boundary normal controls.")
    parser.add_argument("--source", required=True, help="Source dataset directory, normally datasynth_v43_candidate")
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


def build_year_controls(output: Path, year: int, excluded_docs: set[str], vague_docs: set[str]) -> tuple[list[dict], dict[str, dict]]:
    path = output / f"journal_entries_{year}.csv"
    df = pd.read_csv(path, low_memory=False, parse_dates=["posting_date"])
    doc = (
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
            description_quality=("description_quality", "first"),
        )
        .reset_index()
    )
    eligible = doc[
        doc["description_quality"].eq("normal")
        & ~doc["document_id"].astype(str).isin(excluded_docs)
        & ~doc["document_id"].astype(str).isin(vague_docs)
    ].copy()
    patch_by_doc: dict[str, dict] = {}
    controls: list[dict] = []

    for control_type, count in TARGETS[year].items():
        if control_type == "semantic_vague_not_l308":
            pool = doc[
                doc["document_id"].astype(str).isin(vague_docs)
                & ~doc["document_id"].astype(str).isin(excluded_docs)
            ].copy()
        elif control_type == "system_code_valid":
            pool = eligible[eligible["source"].astype(str).str.lower().isin(["automated", "recurring", "batch", "system"])].copy()
        elif control_type == "line_missing_header_valid":
            pool = eligible[eligible["header_text"].notna()] if "header_text" in eligible.columns else eligible.copy()
        else:
            pool = eligible.copy()
        pool = pool.sort_values(["posting_date", "document_id"])
        picked = [doc_id for doc_id in pool["document_id"].astype(str).tolist() if doc_id not in patch_by_doc][:count]
        if len(picked) < count and control_type != "semantic_vague_not_l308":
            raise RuntimeError(f"Only selected {len(picked)}/{count} {control_type} controls for {year}")
        for idx, doc_id in enumerate(picked, start=1):
            patch = _patch_for(control_type, year, idx)
            patch_by_doc[doc_id] = patch
            row = pool[pool["document_id"].astype(str).eq(doc_id)].iloc[0]
            controls.append(
                {
                    "control_id": f"L308NC-{year}-{len(controls)+1:04d}",
                    "document_id": doc_id,
                    "company_code": row["company_code"],
                    "fiscal_year": int(row["fiscal_year"]),
                    "posting_date": pd.Timestamp(row["posting_date"]).strftime("%Y-%m-%d %H:%M:%S"),
                    "document_number": row["document_number"],
                    "document_type": row["document_type"],
                    "business_process": row["business_process"],
                    "source": row["source"],
                    "created_by": row["created_by"],
                    "normal_control_type": control_type,
                    "patched_header_text": patch.get("header_text", ""),
                    "patched_line_text": patch.get("line_text", ""),
                    "expected_description_quality": "normal",
                    "expected_l308_raw_result": "false",
                    "anomaly_label_expected": "false",
                    "evaluation_policy": "boundary_normal_control_not_phase1_l308_truth",
                }
            )
    _apply_text_patches(df, patch_by_doc, path, output)
    return controls, patch_by_doc


def _patch_for(control_type: str, year: int, idx: int) -> dict:
    if control_type == "short_valid":
        text = SHORT_VALID[(idx + year) % len(SHORT_VALID)]
        return {"header_text": text, "line_text": text, "description_quality": "normal"}
    if control_type == "system_code_valid":
        template = SYSTEM_CODE_TEMPLATES[(idx + year) % len(SYSTEM_CODE_TEMPLATES)]
        text = template.format(year=year, seq=idx * 37 + year)
        return {"header_text": text, "line_text": text, "description_quality": "normal"}
    if control_type == "line_missing_header_valid":
        template = HEADER_VALID[(idx + year) % len(HEADER_VALID)]
        header = template.format(year=year, month=(idx % 12) + 1)
        return {"header_text": header, "line_text": "", "description_quality": "normal"}
    return {"description_quality": "normal"}


def _apply_text_patches(df: pd.DataFrame, patch_by_doc: dict[str, dict], path: Path, output: Path) -> None:
    doc_ids = df["document_id"].astype(str)
    for doc_id, patch in patch_by_doc.items():
        mask = doc_ids.eq(doc_id)
        for col in ["header_text", "line_text", "description_quality"]:
            if col in patch and col in df.columns:
                df.loc[mask, col] = patch[col]
    df.to_csv(path, index=False)
    all_year = pd.concat(
        [pd.read_csv(output / f"journal_entries_{year}.csv", low_memory=False) for year in [2022, 2023, 2024]],
        ignore_index=True,
    )
    all_year.to_csv(output / "journal_entries.csv", index=False)


def patch_json(output: Path, patch_by_doc: dict[str, dict]) -> int:
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
                patch = patch_by_doc.get(doc_id)
                if patch:
                    for col in ["header_text", "description_quality"]:
                        if col in patch:
                            record.setdefault("header", {})[col] = patch[col]
                    for line_obj in record.get("lines", []):
                        if "line_text" in patch:
                            line_obj["line_text"] = patch["line_text"] or None
                        line_obj["description_quality"] = patch.get("description_quality", "normal")
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
    text = f"""# DataSynth v44 Candidate

v44 keeps v43 and adds L3-08 boundary normal controls to avoid treating contract alignment as real precision.

## Summary

- Source baseline: `datasynth_v43_candidate`
- Boundary normal controls: {summary['description_boundary_normal_controls']['total']}
- Control types: {summary['description_boundary_normal_controls']['by_type']}
- Policy: short valid text, valid system codes, and line-missing/header-valid cases are normal controls.

## Files

- `labels/description_boundary_normal_controls.csv/json`
- `labels/description_boundary_normal_controls_2022/2023/2024.csv/json`
- `V44_DESCRIPTION_BOUNDARY_CONTROLS.json`
"""
    (output / "PREVIEW.md").write_text(text, encoding="utf-8")
    (output / "FREEZE_V44_CANDIDATE.md").write_text(text, encoding="utf-8")


def main() -> None:
    args = parse_args()
    source = Path(args.source)
    output = Path(args.output)
    if output.exists():
        if not args.force:
            raise FileExistsError(f"{output} already exists; pass --force")
        shutil.rmtree(output)
    shutil.copytree(source, output)

    labels = pd.read_csv(output / "labels" / "anomaly_labels.csv", usecols=["document_id", "anomaly_type"], low_memory=False)
    excluded_docs = set(labels[labels["anomaly_type"].eq("MissingOrCorruptedDescription")]["document_id"].astype(str))
    vague_docs = set(labels[labels["anomaly_type"].eq("VagueDescription")]["document_id"].astype(str))
    controls: list[dict] = []
    all_patches: dict[str, dict] = {}
    for year in [2022, 2023, 2024]:
        year_controls, year_patches = build_year_controls(output, year, excluded_docs, vague_docs)
        controls.extend(year_controls)
        all_patches.update(year_patches)
    json_patched = patch_json(output, all_patches)

    labels_dir = output / "labels"
    write_sidecar_family(labels_dir, "description_boundary_normal_controls", controls)
    summary = {
        "candidate_version": "v44_candidate",
        "source_baseline": "datasynth_v43_candidate",
        "focus": "Add L3-08 boundary normal controls so contract tests are not mistaken for real-world precision.",
        "description_boundary_normal_controls": {
            "total": len(controls),
            "by_year": {str(k): int(v) for k, v in sorted(Counter(r["fiscal_year"] for r in controls).items())},
            "by_type": {str(k): int(v) for k, v in sorted(Counter(r["normal_control_type"] for r in controls).items())},
        },
        "journal_json_patched_documents": json_patched,
        "contract": {
            "l308_contract_test": "MissingOrCorruptedDescription alignment is a contract test, not real precision.",
            "normal_controls": "Boundary normal controls must remain non-L3-08 hits and unlabeled.",
            "not_test_fitting": "Controls are selected before evaluation and represent plausible business text edge cases.",
        },
    }
    (output / "V44_DESCRIPTION_BOUNDARY_CONTROLS.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_preview(output, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
