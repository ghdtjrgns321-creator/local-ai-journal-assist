"""Phase 2 Fitting Audit — Stage 0: Column Catalog & Leakage AUROC.

53개 컬럼을 (A) 라벨/누수 / (B) 라벨 메타 / (C) ML 피처 후보 / (D) 식별자/구조 로
분류한다. 각 컬럼의 dtype/null_rate/distinct/sample + manipulated=1 vs =0 단일컬럼
AUROC 를 계산한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parents[3]
DATASET_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_manipulation_v3"
JE_PATH = DATASET_DIR / "journal_entries.csv"
TRUTH_PATH = DATASET_DIR / "labels" / "manipulated_entry_truth.csv"
OUT_DIR = ROOT / "tests" / "datasynth_quality_gate" / "results" / "phase2_fitting_audit"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 도메인 사전 분류 — AUROC와 별도로 의미상의 분류를 부여한다.
# (A) 라벨/누수 의심: mutation_* 컬럼군은 manipulated 행에만 채워지는 메타데이터
LABEL_LEAK_DOMAIN = {
    "mutation_base_event_type",
    "mutation_type",
    "mutation_mutated_field",
    "mutation_original_value",
    "mutation_mutated_value",
    "mutation_reason",
    "detection_surface_hints",
    "semantic_scenario_id",
}
# (B) 라벨 메타: truth.csv 에 등장하는 식별·승인 메타로, manipulated 라벨과 연동되어 사용
LABEL_METADATA_DOMAIN: set[str] = set()  # truth join key 는 식별자(D)로 둠
# (D) 식별자/구조: PK, FK, fiscal 좌표, 텍스트 free-form
IDENTIFIER_DOMAIN = {
    "document_id",
    "document_number",
    "line_number",
    "company_code",
    "fiscal_year",
    "fiscal_period",
    "reference",
    "header_text",
    "line_text",
    "ledger",
}


def _to_python(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if pd.isna(value):
        return None
    return str(value)


def _sample_values(series: pd.Series, k: int = 3) -> list:
    non_null = series.dropna()
    if non_null.empty:
        return []
    uniques = non_null.drop_duplicates().head(k).tolist()
    return [_to_python(v) for v in uniques]


def _column_auroc(series: pd.Series, y: np.ndarray) -> float | None:
    """단일 컬럼 AUROC. continuous 면 그대로, categorical/boolean 이면 mean-target-encode."""
    if series.isna().all():
        return None
    s = series.copy()
    if s.dtype == bool or pd.api.types.is_bool_dtype(s):
        score = s.fillna(False).astype(int).to_numpy()
    elif pd.api.types.is_numeric_dtype(s):
        score = s.fillna(s.median()).astype(float).to_numpy()
    elif pd.api.types.is_datetime64_any_dtype(s):
        score = (
            s.view("int64")
            .where(~s.isna(), other=pd.Series(s.view("int64")).median())
            .astype(float)
            .to_numpy()
        )
    else:
        # categorical: mean target encoding (manipulated rate per category)
        s = s.astype("object").where(~s.isna(), other="__NA__")
        target_map = pd.Series(y, index=s.index).groupby(s).mean()
        score = s.map(target_map).astype(float).to_numpy()
    if np.unique(y).size < 2:
        return None
    try:
        auroc = roc_auc_score(y, score)
    except ValueError:
        return None
    # AUROC <0.5 인 경우는 방향 뒤집기 (정렬 기준 무관하게 분별력만 본다)
    return float(max(auroc, 1.0 - auroc))


def main() -> None:
    con = duckdb.connect()
    je = con.execute(f"SELECT * FROM read_csv_auto('{JE_PATH.as_posix()}')").df()
    truth = con.execute(f"SELECT document_id FROM read_csv_auto('{TRUTH_PATH.as_posix()}')").df()
    manipulated_docs = set(truth["document_id"].unique())
    y = je["document_id"].isin(manipulated_docs).astype(int).to_numpy()
    print(f"[info] rows={len(je)} manipulated_rows={y.sum()} prevalence={y.mean():.4f}")

    rows: list[dict] = []
    for col in je.columns:
        series = je[col]
        catalog = {
            "column": col,
            "dtype": str(series.dtype),
            "null_rate": float(series.isna().mean()),
            "distinct_count": int(series.nunique(dropna=True)),
            "sample_values": _sample_values(series, k=3),
            "auroc_vs_manipulated": _column_auroc(series, y),
        }
        # 분류 결정
        auroc = catalog["auroc_vs_manipulated"]
        if col in LABEL_LEAK_DOMAIN:
            category = "A_label_leak"
            reasoning = (
                "도메인: mutation/scenario 메타는 manipulated 행에만 채워지는 truth 라벨 사이드카"
            )
        elif auroc is not None and auroc >= 0.95:
            category = "A_label_leak"
            reasoning = f"AUROC={auroc:.4f} ≥ 0.95 → 단일 컬럼으로 라벨을 거의 복원, 누수 의심"
        elif col in IDENTIFIER_DOMAIN:
            category = "D_identifier_structure"
            reasoning = "도메인: PK/FK/fiscal 좌표/free-form 텍스트는 ML 피처가 아닌 구조 컬럼"
        elif catalog["null_rate"] > 0.0 and abs(catalog["null_rate"] - (1.0 - y.mean())) < 0.02:
            # null 율이 정상행 비율과 거의 일치 → manipulated 에만 채워지는 메타 가능성 (보수적 A)
            category = "A_label_leak"
            reasoning = (
                f"null_rate={catalog['null_rate']:.4f} 가 정상행 비율 {(1.0 - y.mean()):.4f} 와"
                " 거의 일치 → manipulated 행에만 채워지는 라벨 사이드카 의심 (보수 분류)"
            )
        elif catalog["distinct_count"] <= 1:
            category = "D_identifier_structure"
            reasoning = f"distinct={catalog['distinct_count']} → 상수 컬럼, 피처 가치 없음"
        elif col in LABEL_METADATA_DOMAIN:
            category = "B_label_metadata"
            reasoning = "도메인: 라벨 메타데이터 (truth 와 같이 관리되는 운영 컬럼)"
        else:
            category = "C_ml_feature_candidate"
            reasoning = (
                f"AUROC={'NA' if auroc is None else f'{auroc:.4f}'}"
                f", null_rate={catalog['null_rate']:.4f}, distinct={catalog['distinct_count']}"
                " → 일반 피처 후보"
            )
        catalog["category"] = category
        catalog["reasoning"] = reasoning
        rows.append(catalog)

    # ── 산출물 1: JSON
    out_json = OUT_DIR / "S0_column_catalog.json"
    out_json.write_text(
        json.dumps(
            {
                "dataset": str(JE_PATH.relative_to(ROOT)).replace("\\", "/"),
                "truth_path": str(TRUTH_PATH.relative_to(ROOT)).replace("\\", "/"),
                "n_rows": int(len(je)),
                "n_columns": int(len(je.columns)),
                "manipulated_row_count": int(y.sum()),
                "manipulated_row_prevalence": float(y.mean()),
                "columns": rows,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"[ok] wrote {out_json}")

    # ── 산출물 2: Markdown 표
    by_cat: dict[str, list[dict]] = {
        "A_label_leak": [],
        "B_label_metadata": [],
        "C_ml_feature_candidate": [],
        "D_identifier_structure": [],
    }
    for r in rows:
        by_cat[r["category"]].append(r)

    lines: list[str] = []
    lines.append("# Stage 0 — Column Catalog & Leakage Classification\n")
    lines.append("- dataset: `data/journal/primary/datasynth_manipulation_v3/journal_entries.csv`")
    lines.append("- truth join: `labels/manipulated_entry_truth.csv` (document_id 기준 행 라벨링)")
    lines.append(f"- 총 행수: **{len(je):,}**, 컬럼수: **{len(je.columns)}**")
    lines.append(f"- manipulated 행: **{int(y.sum()):,}** ({y.mean() * 100:.2f}%)")
    lines.append("")
    lines.append(
        "분류 규약: 도메인 우선 분류 → AUROC ≥ 0.95 자동 (A) → null_rate 가 정상행 비율과"
        " ±2%p 이내면 보수적으로 (A) → 식별자/상수는 (D) → 그 외 (C)."
    )
    lines.append("AUROC 는 대칭화(`max(auroc, 1-auroc)`)하여 분별력 방향과 무관하게 평가.")
    lines.append("")

    cat_titles = {
        "A_label_leak": "## (A) 라벨/누수 의심",
        "B_label_metadata": "## (B) 라벨 메타데이터",
        "C_ml_feature_candidate": "## (C) ML 피처 후보",
        "D_identifier_structure": "## (D) 식별자/구조 컬럼",
    }
    for cat, title in cat_titles.items():
        items = by_cat[cat]
        lines.append(title)
        lines.append(f"- 컬럼 수: **{len(items)}**")
        lines.append("")
        if not items:
            lines.append("_(해당 컬럼 없음)_")
            lines.append("")
            continue
        lines.append("| column | dtype | null_rate | distinct | AUROC | sample | reasoning |")
        lines.append("|---|---|---:|---:|---:|---|---|")
        for r in sorted(
            items,
            key=lambda x: (
                -(x["auroc_vs_manipulated"] or 0.0),
                x["column"],
            ),
        ):
            auroc = r["auroc_vs_manipulated"]
            auroc_str = "NA" if auroc is None else f"{auroc:.4f}"
            sample_str = (
                ", ".join(
                    str(v)[:24] + ("…" if len(str(v)) > 24 else "") for v in r["sample_values"][:3]
                )
                or "_(empty)_"
            )
            reasoning = r["reasoning"].replace("|", "\\|")
            sample_str = sample_str.replace("|", "\\|")
            lines.append(
                f"| `{r['column']}` | `{r['dtype']}` | "
                f"{r['null_rate']:.4f} | {r['distinct_count']:,} | {auroc_str} | "
                f"{sample_str} | {reasoning} |"
            )
        lines.append("")

    # 누수 의심 사유 별도 정리
    lines.append("## 누수 의심 컬럼 reasoning (요약)\n")
    leak_items = by_cat["A_label_leak"]
    if not leak_items:
        lines.append("_(누수 의심 없음)_")
    else:
        for r in sorted(
            leak_items,
            key=lambda x: -(x["auroc_vs_manipulated"] or 0.0),
        ):
            auroc = r["auroc_vs_manipulated"]
            auroc_str = "NA" if auroc is None else f"{auroc:.4f}"
            lines.append(
                f"- **`{r['column']}`** — AUROC={auroc_str}, null_rate={r['null_rate']:.4f}"
                f" — {r['reasoning']}"
            )
    lines.append("")

    out_md = OUT_DIR / "S0_column_classification.md"
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"[ok] wrote {out_md}")

    # 최종 sanity check: 53개 모두 분류되었는지
    classified = sum(len(v) for v in by_cat.values())
    assert classified == len(je.columns), f"classified {classified} != total {len(je.columns)}"
    print("[ok] 53 columns all classified across A/B/C/D")


if __name__ == "__main__":
    main()
