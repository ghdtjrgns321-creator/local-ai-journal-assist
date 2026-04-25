from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections import Counter
from pathlib import Path

import pandas as pd


IC_PREFIXES = ("1150", "2050", "4500", "2700")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build v37 DataSynth intercompany population truth candidate.")
    parser.add_argument("--source", required=True, help="Source dataset directory, normally datasynth_v36_candidate")
    parser.add_argument("--output", required=True, help="Output candidate directory")
    parser.add_argument("--force", action="store_true", help="Overwrite output directory")
    return parser.parse_args()


def normalize_scalar(value: object) -> object:
    if pd.isna(value):
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def write_records(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(records[0]) if records else [
        "document_id",
        "company_code",
        "fiscal_year",
        "posting_date",
        "document_number",
        "document_type",
        "business_process",
        "source",
        "created_by",
        "ic_account_prefixes",
        "ic_gl_accounts",
        "has_trading_partner",
        "trading_partners",
        "population_basis",
        "has_any_anomaly_label",
        "anomaly_types",
    ]
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


def build_intercompany_population(output: Path) -> tuple[list[dict], dict]:
    cols = [
        "document_id",
        "company_code",
        "fiscal_year",
        "posting_date",
        "document_number",
        "document_type",
        "business_process",
        "source",
        "created_by",
        "gl_account",
        "trading_partner",
    ]
    je = pd.read_csv(output / "journal_entries.csv", usecols=cols, low_memory=False, parse_dates=["posting_date"])
    labels = pd.read_csv(output / "labels" / "anomaly_labels.csv", low_memory=False)
    label_types = labels.groupby("document_id")["anomaly_type"].apply(lambda s: "|".join(sorted(set(s)))).to_dict()

    gl = je["gl_account"].fillna("").astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
    je["_ic_prefix"] = ""
    for prefix in IC_PREFIXES:
        je.loc[gl.str.startswith(prefix), "_ic_prefix"] = prefix
    ic_rows = je[je["_ic_prefix"].ne("")].copy()

    records: list[dict] = []
    for doc_id, group in ic_rows.groupby("document_id", sort=True):
        first = group.iloc[0]
        prefixes = sorted(set(group["_ic_prefix"].dropna().astype(str)) - {""})
        accounts = sorted(set(group["gl_account"].dropna().astype(str)))
        tps = sorted(
            set(
                group["trading_partner"]
                .dropna()
                .astype(str)
                .str.strip()
                .loc[lambda s: s.ne("")]
            )
        )
        anomaly_types = label_types.get(doc_id, "")
        records.append(
            {
                "document_id": doc_id,
                "company_code": first["company_code"],
                "fiscal_year": int(first["fiscal_year"]),
                "posting_date": normalize_scalar(first["posting_date"]),
                "document_number": first["document_number"],
                "document_type": first["document_type"],
                "business_process": first["business_process"],
                "source": first["source"],
                "created_by": first["created_by"],
                "ic_account_prefixes": "|".join(prefixes),
                "ic_gl_accounts": "|".join(accounts),
                "has_trading_partner": bool(tps),
                "trading_partners": "|".join(tps),
                "population_basis": "ic_gl_account_prefix",
                "has_any_anomaly_label": anomaly_types != "",
                "anomaly_types": anomaly_types,
            }
        )

    records.sort(key=lambda r: (r["fiscal_year"], str(r["posting_date"]), r["document_id"]))
    all_tp_docs = int(je.loc[je["trading_partner"].fillna("").astype(str).str.strip().ne(""), "document_id"].nunique())
    summary = {
        "candidate_version": "v37_candidate",
        "source_baseline": "datasynth_v36_candidate",
        "focus_rule": "L3-03",
        "purpose": "Separate L3-03 intercompany population truth from CircularIntercompany anomaly labels.",
        "intercompany_population_docs": len(records),
        "by_year": {str(k): int(v) for k, v in sorted(Counter(r["fiscal_year"] for r in records).items())},
        "by_business_process": {
            str(k): int(v) for k, v in sorted(Counter(r["business_process"] for r in records).items())
        },
        "by_prefix": _prefix_counts(records),
        "with_trading_partner": sum(1 for r in records if r["has_trading_partner"]),
        "with_any_anomaly_label": sum(1 for r in records if r["has_any_anomaly_label"]),
        "all_trading_partner_docs_reference_only": all_tp_docs,
        "contract": {
            "l3_03_truth": "labels/intercompany_population_truth.csv",
            "truth_basis": "Documents containing configured intercompany GL account prefixes.",
            "not_anomaly_truth": "CircularIntercompany remains an anomaly label and is not expanded to all normal IC transactions.",
            "precision_note": "Raw precision against anomaly labels is not meaningful for L3-03; use population coverage.",
        },
    }
    return records, summary


def _prefix_counts(records: list[dict]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for record in records:
        for prefix in str(record["ic_account_prefixes"]).split("|"):
            if prefix:
                counts[prefix] += 1
    return {str(k): int(v) for k, v in sorted(counts.items())}


def write_preview(output: Path, summary: dict) -> None:
    text = f"""# DataSynth v37 Candidate

v37은 v36을 기준으로 L3-03 관계사 거래 평가 기준을 anomaly label에서 population truth로 분리한 후보 데이터입니다.

## 변경 요약

- 기준 데이터: `datasynth_v36_candidate`
- 원장 본문 변경: 없음
- anomaly 라벨 추가/삭제: 없음
- 추가 sidecar: `labels/intercompany_population_truth*.csv/json`
- 목적: L3-03을 `CircularIntercompany` 부정 라벨 탐지기가 아니라 관계사 거래 모집단 flag로 평가

## Intercompany Population Truth

- 모집단 문서: {summary['intercompany_population_docs']}
- 연도 분포: {summary['by_year']}
- prefix 분포: {summary['by_prefix']}
- trading_partner 보유 문서: {summary['with_trading_partner']}
- anomaly label 동시 보유 문서: {summary['with_any_anomaly_label']}

## 평가 해석

- L3-03 contract 평가는 `intercompany_population_truth` 기준으로 한다.
- `CircularIntercompany`는 진짜 이상 관계사 흐름 라벨로만 유지한다.
- 정상 관계사 거래를 `CircularIntercompany`로 대량 라벨링하지 않는다.
- 따라서 기존 anomaly-label precision이 낮은 것은 룰 실패가 아니라 평가 기준 불일치로 해석한다.

## 생성 파일

- `labels/intercompany_population_truth.csv/json`
- `labels/intercompany_population_truth_2022.csv/json`
- `labels/intercompany_population_truth_2023.csv/json`
- `labels/intercompany_population_truth_2024.csv/json`
- `V37_INTERCOMPANY_POPULATION.json`
"""
    (output / "PREVIEW.md").write_text(text, encoding="utf-8")
    (output / "FREEZE_V37_CANDIDATE.md").write_text(text, encoding="utf-8")


def main() -> None:
    args = parse_args()
    source = Path(args.source)
    output = Path(args.output)
    if not source.exists():
        raise FileNotFoundError(source)
    if output.exists():
        if not args.force:
            raise FileExistsError(f"{output} already exists; pass --force to overwrite")
        shutil.rmtree(output)
    shutil.copytree(source, output)

    records, summary = build_intercompany_population(output)
    write_sidecar_family(output / "labels", "intercompany_population_truth", records)
    (output / "V37_INTERCOMPANY_POPULATION.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_preview(output, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
