"""fixed4 family/sub-detector 별 hit ↔ truth-positive 비율 분석.

IC02 가 truth_ratio 0.14% 로 noise 가 압도적이었던 패턴을 다른 family/rule 에서도
찾을 수 있는지 검증한다. 운영식·rule param 튜닝의 직접 근거로 사용하지 않고,
calibration 후보 가설 도출용 informational 측정이다.
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import pickle
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.detection.relational_rules import (
    r01_new_counterparty,
    r02_dormant_account_activity,
    r03_transfer_pricing_anomaly,
)
from src.detection.timeseries_rules import (
    ts01_transaction_burst,
    ts02_unusual_frequency,
)

PKL = ROOT / "artifacts" / "phase1_manipulation_v7_fixed4_case_input.pkl"
TRUTH = (
    ROOT
    / "data"
    / "journal"
    / "primary"
    / "datasynth_manipulation_v7_candidate_fixed4"
    / "labels"
    / "manipulated_entry_truth.csv"
)
OUT = ROOT / "artifacts" / "phase2_family_rule_noise_fixed4_20260523.json"


def main() -> int:
    print("loading PKL ...")
    with PKL.open("rb") as fh:
        data = pickle.load(fh)
    df = data["df"]
    print(f"  rows={len(df):,} docs={df['document_id'].nunique():,}")

    truth = pd.read_csv(TRUTH)
    truth_docs = set(truth["document_id"].astype(str))
    df["is_truth"] = df["document_id"].astype(str).isin(truth_docs)

    report: dict[str, Any] = {
        "dataset": "datasynth_manipulation_v7_candidate_fixed4",
        "total_rows": int(len(df)),
        "total_truth_docs": len(truth_docs),
        "sub_detectors": {},
    }

    sub_detectors: list[tuple[str, str, Any, dict]] = [
        ("T", "TS01_transaction_burst", ts01_transaction_burst, {}),
        ("T", "TS02_unusual_frequency", ts02_unusual_frequency, {}),
        ("R", "R01_new_counterparty", r01_new_counterparty, {}),
        ("R", "R02_dormant_account_activity", r02_dormant_account_activity, {}),
        ("R", "R03_transfer_pricing_anomaly", r03_transfer_pricing_anomaly, {}),
    ]

    for family, name, func, kwargs in sub_detectors:
        t0 = time.perf_counter()
        try:
            result = func(df, **kwargs)
            if result.dtype == bool:
                hit_mask = result
            else:
                hit_mask = result > 0
        except Exception as exc:
            print(f"  {name}: FAILED ({exc})")
            continue

        row_hit = int(hit_mask.sum())
        doc_hit = df.loc[hit_mask, "document_id"].nunique()
        truth_row_hit = int((hit_mask & df["is_truth"]).sum())
        truth_doc_hit = df.loc[hit_mask & df["is_truth"], "document_id"].nunique()

        row_truth_ratio = truth_row_hit / max(row_hit, 1)
        doc_in_truth_pool = truth_doc_hit / max(doc_hit, 1)
        recall_doc = truth_doc_hit / max(len(truth_docs), 1)

        report["sub_detectors"][name] = {
            "family": family,
            "row_hit": row_hit,
            "row_hit_share": row_hit / max(len(df), 1),
            "doc_hit": int(doc_hit),
            "doc_hit_share": float(doc_hit / max(df["document_id"].nunique(), 1)),
            "truth_row_hit": truth_row_hit,
            "row_truth_ratio": float(row_truth_ratio),
            "truth_doc_hit": int(truth_doc_hit),
            "doc_truth_ratio_in_hit": float(doc_in_truth_pool),
            "recall_doc": float(recall_doc),
            "elapsed_sec": round(time.perf_counter() - t0, 2),
        }
        print(
            f"  {name:34s} row_hit={row_hit:>9,} doc_hit={doc_hit:>8,} "
            f"row_truth%={row_truth_ratio * 100:6.2f}% "
            f"recall_doc%={recall_doc * 100:6.2f}% "
            f"({time.perf_counter() - t0:.1f}s)"
        )

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
