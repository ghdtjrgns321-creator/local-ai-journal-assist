"""high_timing normal 2,432 docs의 day_diff 분포 + month-end close lag 분류 보강.

match_ic_groups 결과 (match_df["date_diff_days"]) 를 high_timing normal docs 에 매핑.
"""

# ruff: noqa: E402
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.detection.intercompany_matcher import IntercompanyMatcher
from src.detection.intercompany_rules import (
    load_ic_pairs,
    match_ic_groups,
)

FIXED5_PKL = ROOT / "artifacts" / "phase1_manipulation_v7_fixed5_normalcal5_case_input.pkl"
FIXED5_TRUTH = (
    ROOT
    / "data"
    / "journal"
    / "primary"
    / "datasynth_manipulation_v7_candidate_fixed5_normalcal5"
    / "labels"
    / "manipulated_entry_truth.csv"
)
AUDIT_RULES_PATH = ROOT / "config" / "audit_rules.yaml"
OUT_JSON = ROOT / "artifacts" / "ic_timing_prob_diagnosis_20260524_supplement.json"


def main() -> None:
    with FIXED5_PKL.open("rb") as fh:
        data = pickle.load(fh)
    df = data["df"]
    truth = pd.read_csv(FIXED5_TRUTH)
    truth["document_id"] = truth["document_id"].astype(str)
    truth_docs = set(truth["document_id"])

    with AUDIT_RULES_PATH.open(encoding="utf-8") as fh:
        audit_rules = yaml.safe_load(fh)

    det = IntercompanyMatcher(audit_rules=audit_rules)
    result = det.detect(df)
    timing = result.details["ic_timing_prob"]

    # high_timing docs (≥0.99)
    work_doc = pd.DataFrame(
        {
            "document_id": df["document_id"].astype(str).values,
            "timing": timing.values,
        }
    )
    doc_timing_max = work_doc.groupby("document_id")["timing"].max()
    high_timing_docs = set(doc_timing_max[doc_timing_max >= 0.99].index)
    high_timing_normal = set(d for d in high_timing_docs if d not in truth_docs)
    high_timing_truth = set(d for d in high_timing_docs if d in truth_docs)

    # match_ic_groups 직접 호출 → date_diff_days 분포
    pair_map = load_ic_pairs(audit_rules)
    match_df = match_ic_groups(df, pair_map, 0.05, 20.0)
    match_df = match_df.reindex(df.index)

    work = pd.DataFrame(
        {
            "document_id": df["document_id"].astype(str).values,
            "posting_date": pd.to_datetime(df["posting_date"], errors="coerce").values,
            "date_diff_days": pd.to_numeric(match_df["date_diff_days"], errors="coerce").values,
            "has_counterpart": match_df["has_counterpart"].astype("boolean").fillna(False),
        }
    )

    # high_timing normal docs 의 date_diff_days 분포
    htn = work[work["document_id"].isin(high_timing_normal)]
    htn_dd = htn["date_diff_days"].dropna()

    summary: dict = {
        "high_timing_normal_doc_count": len(high_timing_normal),
        "high_timing_truth_doc_count": len(high_timing_truth),
        "normal_date_diff_describe": htn_dd.describe().to_dict() if len(htn_dd) else {},
        "normal_date_diff_buckets": {},
    }

    if len(htn_dd) > 0:
        bins = [-0.001, 0, 5, 14, 30, 31, 35, 45, 60, 90, 180, 365, 10000]
        labels = [
            "0",
            "1-5",
            "6-14",
            "15-30",
            "exactly_31",
            "32-35",
            "36-45",
            "46-60",
            "61-90",
            "91-180",
            "181-365",
            ">365",
        ]
        buckets = pd.cut(htn_dd, bins=bins, labels=labels)
        summary["normal_date_diff_buckets"] = buckets.value_counts().sort_index().to_dict()

    # month-end close lag detection (doc 단위)
    # rec 측 doc 날짜 vs pay 측 doc 날짜의 같은 trading_partner 매칭은 match_ic_groups 가 이미
    # 그룹 비교로 처리. 여기선 high_timing normal docs 의 자체 posting_date 가 월말/월초인지만 본다.
    htn_dates = work[
        (work["document_id"].isin(high_timing_normal)) & (work["posting_date"].notna())
    ]["posting_date"]
    if len(htn_dates) > 0:
        dom = htn_dates.dt.day
        dim = htn_dates.dt.daysinmonth
        is_eom_5 = dom >= (dim - 4)
        is_bom_5 = dom <= 5
        is_eom_7 = dom >= (dim - 6)
        is_bom_7 = dom <= 7
        summary["normal_doc_date_position"] = {
            "total_lines": int(len(htn_dates)),
            "eom_5d_lines": int(is_eom_5.sum()),
            "bom_5d_lines": int(is_bom_5.sum()),
            "eom_7d_lines": int(is_eom_7.sum()),
            "bom_7d_lines": int(is_bom_7.sum()),
            "either_close_5d_lines": int((is_eom_5 | is_bom_5).sum()),
            "either_close_7d_lines": int((is_eom_7 | is_bom_7).sum()),
        }

    # 비교: truth high_timing 분포 (있으면)
    htt = work[work["document_id"].isin(high_timing_truth)]
    htt_dd = htt["date_diff_days"].dropna()
    summary["truth_date_diff_describe"] = htt_dd.describe().to_dict() if len(htt_dd) else {}

    # 비교: 전체 정상 IC matched pair (timing 제한 없음) date_diff 분포
    matched_all = work[(work["has_counterpart"]) & (work["date_diff_days"].notna())]
    matched_normal = matched_all[~matched_all["document_id"].isin(truth_docs)]
    summary["all_normal_matched_date_diff_describe"] = (
        matched_normal["date_diff_days"].describe().to_dict() if len(matched_normal) else {}
    )

    OUT_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
