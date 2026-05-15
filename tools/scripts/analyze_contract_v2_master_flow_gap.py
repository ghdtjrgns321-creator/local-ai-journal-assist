"""Classify remaining contract-v2 approval master/flow gaps.

This script is diagnostic only. It does not change detector thresholds or
generated data. The goal is to separate intentional approval-control fixtures
from generator/master-data gaps and detector enrichment mismatches.
"""

# ruff: noqa: E501,I001

from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_CACHE = ROOT / "artifacts" / "phase1_contract_v2_final_candidate_20260514.pkl"
OUT_MD = ROOT / "artifacts" / "contract_v2_master_flow_gap_analysis.md"
OUT_JSON = ROOT / "artifacts" / "contract_v2_master_flow_gap_analysis.json"
OUT_CSV = ROOT / "artifacts" / "contract_v2_master_flow_gap_rows.csv"


def load_cache(path: Path) -> pd.DataFrame:
    with path.open("rb") as handle:
        payload = pickle.load(handle)
    if isinstance(payload, pd.DataFrame):
        return payload
    if isinstance(payload, dict):
        for key in ("df", "aggregated", "case_input", "rows"):
            value = payload.get(key)
            if isinstance(value, pd.DataFrame):
                return value
    raise TypeError(f"Unsupported cache payload in {path}")


def bool_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(False, index=df.index)
    values = df[column]
    if values.dtype == bool:
        return values.fillna(False)
    return values.fillna(False).astype(str).str.lower().isin({"true", "1", "yes", "y"})


def text(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series("", index=df.index)
    return df[column].fillna("").astype(str).str.strip()


def classify_approval_matrix(row: pd.Series) -> str:
    raw_mutation = row.get("mutation_type")
    mutation = "" if pd.isna(raw_mutation) else str(raw_mutation).strip()
    created_by = str(row.get("created_by") or "").strip().upper()
    approved_by = str(row.get("approved_by") or "").strip().upper()
    limit_resolved = bool(row.get("approval_limit_resolved", False))
    if mutation:
        return "INTENTIONAL_FIXTURE_WITH_PROVENANCE"
    if not approved_by or approved_by in {"NAN", "NONE", "NULL"}:
        return "GENERATOR_FIX_NEEDED_APPROVER_MISSING"
    if created_by and created_by == approved_by:
        return "INTENTIONAL_OR_BACKGROUND_SELF_APPROVAL_UNLABELLED"
    if not limit_resolved:
        return "GENERATOR_FIX_NEEDED_LIMIT_NOT_RESOLVED"
    return "DETECTOR_REVIEW_OR_UNLABELLED_CONTROL_GAP"


def classify_limit(row: pd.Series) -> str:
    raw_mutation = row.get("mutation_type")
    mutation = "" if pd.isna(raw_mutation) else str(raw_mutation).strip()
    approved_by = str(row.get("approved_by") or "").strip().upper()
    limit_resolved = bool(row.get("approval_limit_resolved", False))
    excess = float(row.get("approval_excess_amount") or 0.0)
    if mutation:
        return "INTENTIONAL_FIXTURE_WITH_PROVENANCE"
    if approved_by in {"LIMIT_REVIEWER", "NEAR_LIMIT_REVIEWER"} and limit_resolved:
        return "INTENTIONAL_FIXTURE_NEEDS_MANIFEST_PROVENANCE"
    if not limit_resolved:
        return "GENERATOR_FIX_NEEDED_LIMIT_NOT_RESOLVED"
    if excess > 0:
        return "DETECTOR_REVIEW_OR_UNLABELLED_LIMIT_FIXTURE"
    return "UNCLASSIFIED"


def count_dict(series: pd.Series) -> dict[str, int]:
    return {str(k): int(v) for k, v in series.value_counts(dropna=False).sort_index().items()}


def compact_records(df: pd.DataFrame, columns: list[str], limit: int = 50) -> list[dict[str, Any]]:
    present = [column for column in columns if column in df.columns]
    return df[present].head(limit).fillna("").to_dict(orient="records")


def main() -> None:
    df = load_cache(DEFAULT_CACHE)
    matrix_mask = bool_series(df, "approval_matrix_gap") | bool_series(df, "approval_contract_gap")
    limit_mask = bool_series(df, "approval_limit_exceeded_independent")
    flow_mask = bool_series(df, "document_flow_orphan")

    matrix = df.loc[matrix_mask].copy()
    limit = df.loc[limit_mask].copy()
    flow = df.loc[flow_mask].copy()

    if not matrix.empty:
        matrix["root_cause_class"] = matrix.apply(classify_approval_matrix, axis=1)
    else:
        matrix["root_cause_class"] = []
    if not limit.empty:
        limit["root_cause_class"] = limit.apply(classify_limit, axis=1)
    else:
        limit["root_cause_class"] = []

    matrix_docs = matrix.drop_duplicates("document_id") if "document_id" in matrix.columns else matrix
    limit_docs = limit.drop_duplicates("document_id") if "document_id" in limit.columns else limit

    summary = {
        "source_cache": str(DEFAULT_CACHE.relative_to(ROOT)),
        "rows": int(len(df)),
        "document_flow_orphan_rows": int(len(flow)),
        "approval_matrix_gap_rows": int(len(matrix)),
        "approval_matrix_gap_documents": int(matrix["document_id"].nunique()) if "document_id" in matrix.columns else 0,
        "approval_limit_exceeded_rows": int(len(limit)),
        "approval_limit_exceeded_documents": int(limit["document_id"].nunique()) if "document_id" in limit.columns else 0,
        "approval_matrix_root_cause_rows": count_dict(matrix["root_cause_class"]) if not matrix.empty else {},
        "approval_matrix_root_cause_docs": count_dict(matrix_docs["root_cause_class"]) if not matrix_docs.empty else {},
        "approval_limit_root_cause_rows": count_dict(limit["root_cause_class"]) if not limit.empty else {},
        "approval_limit_root_cause_docs": count_dict(limit_docs["root_cause_class"]) if not limit_docs.empty else {},
        "approval_matrix_mutation_type_rows": count_dict(text(matrix, "mutation_type")) if not matrix.empty else {},
        "approval_limit_mutation_type_rows": count_dict(text(limit, "mutation_type")) if not limit.empty else {},
        "approval_limit_excess_amount": {
            "min": float(pd.to_numeric(limit.get("approval_excess_amount"), errors="coerce").min()) if not limit.empty else 0.0,
            "p50": float(pd.to_numeric(limit.get("approval_excess_amount"), errors="coerce").quantile(0.5)) if not limit.empty else 0.0,
            "p95": float(pd.to_numeric(limit.get("approval_excess_amount"), errors="coerce").quantile(0.95)) if not limit.empty else 0.0,
            "max": float(pd.to_numeric(limit.get("approval_excess_amount"), errors="coerce").max()) if not limit.empty else 0.0,
        },
        "sample_matrix_rows": compact_records(
            matrix,
            [
                "document_id",
                "fiscal_year",
                "company_code",
                "business_process",
                "source",
                "created_by",
                "approved_by",
                "approval_level",
                "approval_limit_resolved",
                "mutation_type",
                "risk_level",
                "root_cause_class",
            ],
        ),
        "sample_limit_rows": compact_records(
            limit,
            [
                "document_id",
                "fiscal_year",
                "company_code",
                "business_process",
                "source",
                "approved_by",
                "approval_level",
                "document_approval_amount",
                "approval_limit_resolved",
                "approval_excess_amount",
                "mutation_type",
                "risk_level",
                "root_cause_class",
            ],
        ),
    }

    rows_out = []
    for kind, subset in (("approval_matrix_gap", matrix), ("approval_limit_exceeded", limit)):
        if subset.empty:
            continue
        cols = [
            "document_id",
            "fiscal_year",
            "company_code",
            "business_process",
            "source",
            "created_by",
            "approved_by",
            "approval_level",
            "document_approval_amount",
            "approval_limit_resolved",
            "approval_excess_amount",
            "mutation_type",
            "risk_level",
            "root_cause_class",
        ]
        present = [col for col in cols if col in subset.columns]
        temp = subset[present].copy()
        temp.insert(0, "gap_kind", kind)
        rows_out.append(temp)
    if rows_out:
        pd.concat(rows_out, ignore_index=True).to_csv(OUT_CSV, index=False, encoding="utf-8")

    write_json = json.dumps(summary, ensure_ascii=False, indent=2)
    OUT_JSON.write_text(write_json + "\n", encoding="utf-8")

    md = f"""# contract_v2 master/flow gap 원인 분리

이 분석은 fitting 방지를 위해 detector threshold나 DataSynth 데이터를 변경하지 않고, 최신 Phase1 cache의 approval/flow gap만 분류한다.

## 요약

| 항목 | 값 |
|---|---:|
| source cache | `{summary['source_cache']}` |
| rows | {summary['rows']:,} |
| document_flow_orphan_rows | {summary['document_flow_orphan_rows']:,} |
| approval_matrix_gap_rows | {summary['approval_matrix_gap_rows']:,} |
| approval_matrix_gap_documents | {summary['approval_matrix_gap_documents']:,} |
| approval_limit_exceeded_rows | {summary['approval_limit_exceeded_rows']:,} |
| approval_limit_exceeded_documents | {summary['approval_limit_exceeded_documents']:,} |

## 판정

- `document_flow_orphan_rows=0` 이므로 document-flow master coverage는 blocker가 아니다.
- `approval_matrix_gap`은 provenance가 있는 fixture와 provenance 없는 자기승인/승인자 결손이 섞여 있다. 즉시 detector를 바꾸기보다 unlabelled control-gap 성격을 manifest에 명시할지, generator에서 정상 배경을 더 정리할지 결정해야 한다.
- `approval_limit_exceeded`는 `LIMIT_REVIEWER` 계열 승인자가 대부분이고 limit도 resolve된다. master join 실패라기보다 의도된 한도초과 fixture 또는 provenance 설명 부족으로 보는 것이 타당하다.

## approval_matrix root cause

```json
{json.dumps(summary['approval_matrix_root_cause_docs'], ensure_ascii=False, indent=2)}
```

## approval_limit root cause

```json
{json.dumps(summary['approval_limit_root_cause_docs'], ensure_ascii=False, indent=2)}
```

## 산출물

- `artifacts/contract_v2_master_flow_gap_analysis.json`
- `artifacts/contract_v2_master_flow_gap_rows.csv`
"""
    OUT_MD.write_text(md, encoding="utf-8")
    print(write_json)


if __name__ == "__main__":
    main()
