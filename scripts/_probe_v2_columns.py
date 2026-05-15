"""v2 cache df의 컬럼 구조와 v1/v2 truth 시나리오 비교를 빠르게 점검."""

from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

V2_PKL = ROOT / "artifacts" / "phase1_manipulation_v2_case_input.pkl"
V1_TRUTH = (
    ROOT
    / "data"
    / "journal"
    / "primary"
    / "datasynth_manipulation"
    / "labels"
    / "manipulated_entry_truth.csv"
)
V2_TRUTH = (
    ROOT
    / "data"
    / "journal"
    / "primary"
    / "datasynth_manipulation_v2"
    / "labels"
    / "manipulated_entry_truth.csv"
)
OUT = ROOT / "artifacts" / "_v2_columns_and_scenario_diff.json"

TARGET = "15445ae3-3865-4e86-8c64-866f5105eb73"


def main() -> None:
    print("[load] v2 cache")
    with V2_PKL.open("rb") as fh:
        cache = pickle.load(fh)
    df: pd.DataFrame = cache["df"]
    print(f"  v2 df shape: {df.shape}")

    cols = list(df.columns)
    by_prefix: dict[str, int] = {}
    for c in cols:
        prefix = c.split("_", 1)[0] if "_" in c else c
        by_prefix[prefix] = by_prefix.get(prefix, 0) + 1

    target_rows = df[df["document_id"].astype(str) == TARGET]
    print(f"  target rows: {len(target_rows)}")

    # 모든 컬럼에 대해 target_rows의 첫 row 값 dump
    first_row = (
        {c: (str(target_rows.iloc[0][c]) if len(target_rows) else None) for c in cols}
        if len(target_rows)
        else {}
    )

    print("\n[truth diff]")
    v1_truth = pd.read_csv(V1_TRUTH) if V1_TRUTH.exists() else pd.DataFrame()
    v2_truth = pd.read_csv(V2_TRUTH) if V2_TRUTH.exists() else pd.DataFrame()
    print(f"  v1 truth: {len(v1_truth)} rows, v2 truth: {len(v2_truth)} rows")

    def _scen_counts(t: pd.DataFrame, col: str) -> dict[str, int]:
        if col not in t.columns:
            return {}
        return t[col].value_counts(dropna=False).to_dict()

    v1_scens = _scen_counts(v1_truth, "manipulation_scenario")
    v2_scens = _scen_counts(v2_truth, "manipulation_scenario")

    def _nrt(t: pd.DataFrame) -> int:
        if "not_rule_targeted" not in t.columns:
            return -1
        s = t["not_rule_targeted"].astype(str).str.lower()
        return int((s == "true").sum())

    out = {
        "v2_df_shape": list(df.shape),
        "v2_columns": cols,
        "v2_columns_by_prefix_count": dict(sorted(by_prefix.items(), key=lambda kv: -kv[1])),
        "v1_truth_total": int(len(v1_truth)),
        "v2_truth_total": int(len(v2_truth)),
        "v1_not_rule_targeted": _nrt(v1_truth),
        "v2_not_rule_targeted": _nrt(v2_truth),
        "v1_scenarios": {str(k): int(v) for k, v in v1_scens.items()},
        "v2_scenarios": {str(k): int(v) for k, v in v2_scens.items()},
        "target_doc_first_row_v2": first_row,
    }
    OUT.write_text(json.dumps(out, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    print(f"\n[saved] {OUT}")


if __name__ == "__main__":
    main()
