"""Inventory downloaded Tritscher ERP-Fraud files.

The script inspects file shapes, columns, missingness, and likely label/proxy
columns without training any model. It writes only metadata/profiles to
artifacts; it does not copy raw data.

Usage:
    uv run python tools/scripts/inventory_tritscher_erp_fraud.py \
        --input-dir data/external/tritscher_erp_fraud \
        --output-dir artifacts/external_validation/tritscher_erp_fraud_20260519
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SUPPORTED_SUFFIXES = {".csv", ".tsv", ".parquet", ".pq", ".xlsx", ".xls"}

PROXY_PATTERNS = (
    "fraud",
    "anomaly",
    "target",
    "label",
    "class",
    "scenario",
    "case",
    "manipulation",
    "ground_truth",
    "annotation",
    "annotator",
    "expert",
    "run",
    "session",
    "participant",
    "game",
    "round",
)

CANONICAL_HINTS: dict[str, tuple[str, ...]] = {
    "document_id": ("document", "doc", "belnr", "belegnummer", "journal", "voucher", "posting_id"),
    "line_id": ("line", "item", "buzei", "position", "buchungszeilen"),
    "gl_account": ("account", "hkont", "saknr", "gl", "ledger", "hauptbuch", "sachkonto"),
    "amount": ("amount", "betrag", "dmbtr", "wrbtr", "value", "debit", "credit", "wert"),
    "debit_credit_indicator": ("debit", "credit", "soll", "haben", "kennz"),
    "posting_date": ("date", "posting", "budat", "timestamp", "time", "uhrzeit", "erfassung"),
    "user": ("user", "creator", "created_by", "uname", "employee", "bearbeiter"),
    "vendor": ("vendor", "supplier", "lifnr", "counterparty", "kreditor"),
    "customer": ("customer", "kunnr", "debitor"),
    "transaction_code": ("tcode", "transaction", "code", "blart", "transaktionsart", "vorgang"),
    "label": ("label", "fraud", "target", "class"),
}

TRITSCHER_MANUAL_MAPPING: dict[str, list[str]] = {
    "document_id": ["Belegnummer"],
    "line_id": ["Position"],
    "gl_account": ["Sachkonto", "Hauptbuchkonto", "Alternative Kontonummer"],
    "amount": ["Betrag Hauswaehr", "Betrag", "Betrag_5", "Gesamtwert"],
    "debit_credit_indicator": ["Soll/Haben-Kennz_"],
    "posting_date": ["Erfassungsuhrzeit"],
    "vendor": ["Kreditor"],
    "transaction_code": ["Transaktionsart", "Vorgang", "Vorgangsart GL", "Buchungsschluessel"],
    "label": ["Label"],
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _jsonable(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _iter_files(input_dir: Path) -> Iterable[Path]:
    for path in sorted(input_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
            yield path


def _read_sample(path: Path, sample_rows: int) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, nrows=sample_rows, low_memory=False)
    if suffix == ".tsv":
        return pd.read_csv(path, sep="\t", nrows=sample_rows, low_memory=False)
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path).head(sample_rows)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path, nrows=sample_rows)
    raise ValueError(f"unsupported file: {path}")


def _read_full_count(path: Path) -> int | None:
    suffix = path.suffix.lower()
    try:
        if suffix == ".csv":
            return int(sum(1 for _ in path.open("rb")) - 1)
        if suffix == ".tsv":
            return int(sum(1 for _ in path.open("rb")) - 1)
        if suffix in {".parquet", ".pq"}:
            return int(len(pd.read_parquet(path, columns=[])))
    except Exception:
        return None
    return None


def _normalized(name: str) -> str:
    return str(name).strip().lower()


def _proxy_columns(columns: Iterable[str]) -> list[str]:
    result: list[str] = []
    for col in columns:
        lowered = _normalized(col)
        if any(pattern in lowered for pattern in PROXY_PATTERNS):
            result.append(col)
    return sorted(result)


def _canonical_candidates(columns: Iterable[str]) -> dict[str, list[str]]:
    candidates: dict[str, list[str]] = {}
    for canonical, hints in CANONICAL_HINTS.items():
        matched = []
        for col in columns:
            lowered = _normalized(col)
            if any(hint in lowered for hint in hints):
                matched.append(col)
        manual = [col for col in TRITSCHER_MANUAL_MAPPING.get(canonical, []) if col in columns]
        candidates[canonical] = sorted(set(matched + manual))
    return candidates


def _column_profile(sample: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for col in sample.columns:
        series = sample[col]
        rows.append(
            {
                "column": str(col),
                "dtype": str(series.dtype),
                "sample_non_null": int(series.notna().sum()),
                "sample_missing_rate": float(series.isna().mean()),
                "sample_nunique": int(series.nunique(dropna=True)),
            }
        )
    return rows


def _file_inventory(path: Path, root: Path, sample_rows: int) -> dict[str, Any]:
    sample = _read_sample(path, sample_rows)
    columns = [str(col) for col in sample.columns]
    return {
        "relative_path": str(path.relative_to(root)),
        "suffix": path.suffix.lower(),
        "bytes": int(path.stat().st_size),
        "row_count_estimate": _read_full_count(path),
        "sample_rows": int(len(sample)),
        "column_count": int(len(columns)),
        "columns": columns,
        "proxy_column_candidates": _proxy_columns(columns),
        "canonical_candidates": _canonical_candidates(columns),
        "column_profile": _column_profile(sample),
    }


def _write_markdown(output_path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# Tritscher ERP-Fraud Schema Inventory",
        "",
        f"- Created at: {payload['created_at']}",
        f"- Input dir: `{payload['input_dir']}`",
        f"- Files inventoried: {payload['file_count']}",
        "",
        "This is metadata only. It does not train models and does not copy raw data.",
        "",
    ]
    if payload["file_count"] == 0:
        lines.extend(
            [
                "## Acquisition Gate",
                "",
                "No supported data files were found. Download/extract the dataset under "
                "`data/external/tritscher_erp_fraud/` and rerun this script.",
            ]
        )
    for item in payload["files"]:
        lines.extend(
            [
                f"## `{item['relative_path']}`",
                "",
                f"- Size bytes: {item['bytes']}",
                f"- Row count estimate: {item['row_count_estimate']}",
                f"- Columns: {item['column_count']}",
                f"- Proxy candidates: {', '.join(item['proxy_column_candidates']) or '(none)'}",
                "",
                "### Canonical Candidates",
                "",
                "| Canonical | Candidate columns |",
                "|---|---|",
            ]
        )
        for canonical, candidates in item["canonical_candidates"].items():
            rendered = ", ".join(f"`{col}`" for col in candidates) or "(none)"
            lines.append(f"| `{canonical}` | {rendered} |")
        lines.extend(
            [
                "",
                "### Columns",
                "",
                "| Column | Dtype | Missing | Nunique |",
                "|---|---|---:|---:|",
            ]
        )
        for col in item["column_profile"]:
            lines.append(
                f"| `{col['column']}` | `{col['dtype']}` | "
                f"{col['sample_missing_rate']:.4f} | {col['sample_nunique']} |"
            )
        lines.append("")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True, help="Extracted Tritscher dataset directory.")
    parser.add_argument("--output-dir", required=True, help="Inventory output directory.")
    parser.add_argument("--sample-rows", type=int, default=1000)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    files = []
    if input_dir.exists():
        for path in _iter_files(input_dir):
            try:
                files.append(_file_inventory(path, input_dir, args.sample_rows))
            except Exception as exc:
                files.append(
                    {
                        "relative_path": str(path.relative_to(input_dir)),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

    payload = {
        "created_at": _now_iso(),
        "input_dir": str(input_dir),
        "file_count": len(files),
        "files": files,
        "policy": {
            "use": "schema inventory and shadow benchmark only",
            "forbidden": "active promotion or feature use of proxy columns",
        },
    }
    (output_dir / "tritscher_schema_inventory.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_jsonable),
        encoding="utf-8",
    )
    _write_markdown(output_dir / "tritscher_schema_inventory.md", payload)
    print(json.dumps({"output_dir": str(output_dir), "file_count": len(files)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
