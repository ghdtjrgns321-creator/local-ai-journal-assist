"""Check strict Phase1 A-axis alignment for datasynth_contract_v2.

For contract datasets, every ``rule_truth_*`` document set must match the
Phase1 rule-hit document set. This is intentionally stricter than comparing
v2 counts to the historical contract counts.
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from refresh_contract_sidecar_truth import RULE_IDS, patch_pandas_string_dtype_pickle


def load_cache_df(path: Path) -> pd.DataFrame:
    patch_pandas_string_dtype_pickle()
    with path.open("rb") as handle:
        payload = pickle.load(handle)
    if not isinstance(payload, dict) or "df" not in payload:
        raise SystemExit(f"invalid Phase1 cache: {path}")
    return payload["df"]


def truth_docs(dataset: Path, rule_id: str) -> set[str]:
    path = dataset / "labels" / f"rule_truth_{rule_id.replace('-', '_')}.csv"
    if not path.exists():
        return set()
    frame = pd.read_csv(path, dtype=str, usecols=lambda col: col == "document_id", low_memory=False)
    if "document_id" not in frame.columns:
        return set()
    return set(frame["document_id"].dropna().astype(str))


def detected_docs(df: pd.DataFrame, rule_id: str) -> set[str]:
    flagged = df.get("flagged_rules", pd.Series("", index=df.index)).fillna("").astype(str)
    review = df.get("review_rules", pd.Series("", index=df.index)).fillna("").astype(str)
    docs = df["document_id"].fillna("").astype(str)

    def contains(value: str) -> bool:
        return rule_id in {part.strip() for part in value.split(",") if part.strip()}

    mask = flagged.map(contains) | review.map(contains)
    return set(docs.loc[mask & docs.ne("")])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", nargs="?", default="data/journal/primary/datasynth_contract_v2")
    parser.add_argument("--phase1-cache", default="artifacts/phase1_contract_v2_case_input_20260514.pkl")
    parser.add_argument("--output", default="tests/datasynth_quality_gate3/results/contract_v2_a_axis_strict.json")
    args = parser.parse_args()

    dataset = Path(args.dataset)
    df = load_cache_df(Path(args.phase1_cache))
    rows = []
    failures = []
    for rule_id in RULE_IDS:
        truth = truth_docs(dataset, rule_id)
        detected = detected_docs(df, rule_id)
        fp = truth - detected
        fn = detected - truth
        row = {
            "rule_id": rule_id,
            "truth_docs": len(truth),
            "detected_docs": len(detected),
            "false_positive_docs": len(fp),
            "false_negative_docs": len(fn),
            "sample_false_positive_docs": sorted(fp)[:10],
            "sample_false_negative_docs": sorted(fn)[:10],
        }
        rows.append(row)
        if fp or fn:
            failures.append(f"{rule_id}: fp={len(fp)}, fn={len(fn)}")

    result = {
        "dataset": str(dataset),
        "phase1_cache": str(args.phase1_cache),
        "rules_checked": len(rows),
        "rules_with_diff": sum(1 for row in rows if row["false_positive_docs"] or row["false_negative_docs"]),
        "total_false_positive_docs": sum(row["false_positive_docs"] for row in rows),
        "total_false_negative_docs": sum(row["false_negative_docs"] for row in rows),
        "rules": rows,
        "failures": failures,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
