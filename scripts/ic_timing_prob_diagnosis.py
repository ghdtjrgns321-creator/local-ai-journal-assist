"""ic_timing_prob normal 2,432 raw 구조 분석.

확인할 것:
- timing_prob=1.0 normal 2,432 docs 의 receivable/payable best candidate pair
- day_diff 분포
- month-end close pattern (rec 월말 N일 + pay 다음 달 초 N일 또는 반대)
- best pair 의 amount_sim / cp_score / reference_sim 강도
- truth doc 의 timing_prob 분포 비교

산출: artifacts/ic_timing_prob_diagnosis_20260524.{md, json}
"""

# ruff: noqa: E402
from __future__ import annotations

import json
import pickle
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml

from src.detection.intercompany_matcher import IntercompanyMatcher
from src.detection.intercompany_rules import (
    _ic_sides,
    load_ic_pairs,
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

OUT_JSON = ROOT / "artifacts" / "ic_timing_prob_diagnosis_20260524.json"
OUT_MD = ROOT / "artifacts" / "ic_timing_prob_diagnosis_20260524.md"


def _classify_doc_lag_pattern(rec_date: pd.Timestamp, pay_date: pd.Timestamp) -> str:
    """receivable/payable date 페어를 도메인 카테고리로 분류."""
    if pd.isna(rec_date) or pd.isna(pay_date):
        return "missing_date"
    delta = abs((rec_date - pay_date).days)
    rec_dom, pay_dom = rec_date.day, pay_date.day
    rec_dim = rec_date.daysinmonth
    pay_dim = pay_date.daysinmonth
    # month-end close pattern: 한쪽 월말 ≥25일, 다른쪽 다음달 1~7일
    rec_is_eom = rec_dom >= (rec_dim - 5)
    pay_is_bom = pay_dom <= 7
    pay_is_eom = pay_dom >= (pay_dim - 5)
    rec_is_bom = rec_dom <= 7
    is_close_pattern = (rec_is_eom and pay_is_bom and delta <= 14) or (
        pay_is_eom and rec_is_bom and delta <= 14
    )
    if is_close_pattern:
        return "month_close_lag"
    if delta == 0:
        return "same_day"
    if delta <= 5:
        return "within_5d"
    if delta <= 30:
        return "within_30d"
    return "over_30d"


def main() -> None:
    t0 = time.perf_counter()

    print(f"[t-dx] loading PKL: {FIXED5_PKL.relative_to(ROOT)}")
    with FIXED5_PKL.open("rb") as fh:
        data = pickle.load(fh)
    df = data["df"]
    print(f"[t-dx]   df rows={len(df):,}")

    truth = pd.read_csv(FIXED5_TRUTH)
    truth["document_id"] = truth["document_id"].astype(str)
    truth_docs = set(truth["document_id"])

    with AUDIT_RULES_PATH.open(encoding="utf-8") as fh:
        audit_rules = yaml.safe_load(fh)

    # 1. IntercompanyMatcher 한 번 실행 → details
    print("[t-dx] running IntercompanyMatcher ...")
    det = IntercompanyMatcher(audit_rules=audit_rules)
    result = det.detect(df)
    details = result.details
    print(f"[t-dx]   details cols={list(details.columns)}")

    work = df[
        ["document_id", "gl_account", "company_code", "trading_partner", "posting_date"]
    ].copy()
    work["document_id"] = work["document_id"].astype(str)
    work["timing_prob"] = details["ic_timing_prob"].reindex(work.index, fill_value=0.0).values
    work["amount_prob"] = details["ic_amount_prob"].reindex(work.index, fill_value=0.0).values
    work["unmatched_prob"] = details["ic_unmatched_prob"].reindex(work.index, fill_value=0.0).values
    work["reciprocal_prob"] = (
        details["ic_reciprocal_flow_prob"].reindex(work.index, fill_value=0.0).values
    )
    work["IC01"] = details["IC01"].reindex(work.index, fill_value=0.0).values
    work["IC02"] = details["IC02"].reindex(work.index, fill_value=0.0).values
    work["IC03"] = details["IC03"].reindex(work.index, fill_value=0.0).values

    # 2. ic_timing_prob ≥0.99 (= 1.0) normal docs 식별
    doc_max = work.groupby("document_id", sort=False).agg(
        timing_max=("timing_prob", "max"),
        amount_max=("amount_prob", "max"),
        unmatched_max=("unmatched_prob", "max"),
        recip_max=("reciprocal_prob", "max"),
        ic01_max=("IC01", "max"),
        ic02_max=("IC02", "max"),
        ic03_max=("IC03", "max"),
    )
    doc_max["is_truth"] = doc_max.index.isin(truth_docs)
    high_timing_mask = doc_max["timing_max"] >= 0.99
    high_timing_docs = doc_max[high_timing_mask].copy()

    summary: dict = {
        "doc_count": int(len(doc_max)),
        "truth_count": int(doc_max["is_truth"].sum()),
        "ic_timing_prob_ge_099_doc_count": int(high_timing_mask.sum()),
        "ic_timing_prob_ge_099_truth": int(high_timing_docs["is_truth"].sum()),
        "ic_timing_prob_ge_099_normal": int((~high_timing_docs["is_truth"]).sum()),
        # 같은 bucket의 amount/cp/ref 강도 (다른 components 동시 분포)
        "amount_prob_in_high_timing_describe": (
            high_timing_docs["amount_max"].describe().to_dict() if len(high_timing_docs) else {}
        ),
        "unmatched_prob_in_high_timing_describe": (
            high_timing_docs["unmatched_max"].describe().to_dict() if len(high_timing_docs) else {}
        ),
    }

    # 3. high timing normal docs 의 line-level pattern
    high_timing_doc_ids = set(high_timing_docs.index)
    htw = work[work["document_id"].isin(high_timing_doc_ids)].copy()
    htw["posting_date_pd"] = pd.to_datetime(htw["posting_date"], errors="coerce")
    htw["is_rec"] = htw["gl_account"].astype(str).str.startswith(("1150", "4500"))
    htw["is_pay"] = htw["gl_account"].astype(str).str.startswith(("2050", "2700"))

    # doc 단위로 rec/pay 가 같은 doc 안에 있는지
    g = htw.groupby("document_id")
    doc_struct = g.agg(
        has_rec=("is_rec", "any"),
        has_pay=("is_pay", "any"),
        rec_dates=(
            "posting_date_pd",
            lambda s: tuple(d for d in s[htw.loc[s.index, "is_rec"]].dropna()),
        ),
        pay_dates=(
            "posting_date_pd",
            lambda s: tuple(d for d in s[htw.loc[s.index, "is_pay"]].dropna()),
        ),
    )
    doc_struct["both_sides_same_doc"] = doc_struct["has_rec"] & doc_struct["has_pay"]
    summary["high_timing_doc_struct"] = {
        "both_sides_same_doc": int(doc_struct["both_sides_same_doc"].sum()),
        "rec_only": int((doc_struct["has_rec"] & ~doc_struct["has_pay"]).sum()),
        "pay_only": int((doc_struct["has_pay"] & ~doc_struct["has_rec"]).sum()),
    }

    # 4. probabilistic best-pair re-compute 로 day_diff 직접 분포 측정
    print("[t-dx] re-computing probabilistic pairs (for day_diff distribution) ...")
    pair_map = load_ic_pairs(audit_rules)
    rec_df, pay_df = _ic_sides(df, pair_map)

    # _cp_block 시그니처가 필요한 매칭 단계 모방 — 간단히 cc/tp 로만 grouping
    def _cp_block_key(cc: str, tp: str, ic_type: str) -> str:
        if cc or tp:
            return f"{cc}__{tp}__{ic_type}"
        return "__NA__"

    rec_df["_cp_block"] = [
        _cp_block_key(str(cc), str(tp), "rec")
        for cc, tp in zip(rec_df.get("company_code", ""), rec_df.get("trading_partner", ""))
    ]
    pay_df["_cp_block"] = [
        _cp_block_key(str(cc), str(tp), "pay")
        for cc, tp in zip(pay_df.get("company_code", ""), pay_df.get("trading_partner", ""))
    ]
    # cp 매칭: cc(rec) ↔ tp(pay) 와 tp(rec) ↔ cc(pay)
    # day_diff 분포는 best candidate pair 기준이 정확하나 여기선 simplification:
    # 같은 (cc, tp) reciprocal anchor 로 묶인 rec/pay 의 시차 분포만 본다.

    # high_timing normal docs 만 대상으로 day_diff 분포 산출 (best pair 추정)
    htw_dates_rec = htw[htw["is_rec"] & htw["posting_date_pd"].notna()].copy()
    htw_dates_pay = htw[htw["is_pay"] & htw["posting_date_pd"].notna()].copy()
    # rec doc 별 dates / pay doc 별 dates
    # high timing은 doc 단위라 doc 내 rec/pay 가 같이 있다면 day_diff 측정
    same_doc_rec = htw_dates_rec.set_index("document_id")["posting_date_pd"]
    same_doc_pay = htw_dates_pay.set_index("document_id")["posting_date_pd"]
    shared_docs = same_doc_rec.index.intersection(same_doc_pay.index)
    # 같은 doc에 양쪽 다 있는 경우는 day_diff = 0 가능
    summary["high_timing_same_doc_both_sides_count"] = int(len(shared_docs))

    # 가장 핵심: high_timing doc 의 rec(또는 pay) 와 cross-doc best counterpart 매칭은
    # compute_probabilistic_pair_scores 의 candidate matching 결과를 우리가 직접 가져와야
    # 진짜 day_diff 분포가 나온다. 이건 다음 단계에서.

    # 5. 모든 IC rec/pay 의 day_diff 분포 통계 (rec/pay 같은 cp_block 안에서 최소 시차)
    print("[t-dx] computing day_diff distribution across all IC pairs ...")
    rec_df["_amt"] = rec_df.get("_amount", 0.0)
    pay_df["_amt"] = pay_df.get("_amount", 0.0)
    rec_df["posting_date_pd"] = pd.to_datetime(rec_df.get("posting_date", pd.NaT), errors="coerce")
    pay_df["posting_date_pd"] = pd.to_datetime(pay_df.get("posting_date", pd.NaT), errors="coerce")

    merged = rec_df.reset_index(drop=True).merge(
        pay_df.reset_index(drop=True), on="_cp_block", suffixes=("_rec", "_pay")
    )
    if len(merged) > 0:
        merged["day_diff"] = (
            (merged["posting_date_pd_rec"] - merged["posting_date_pd_pay"]).abs().dt.days
        )
        # rec row 별 min day_diff (= best timing candidate)
        rec_best_day_diff = merged.groupby("_orig_idx_rec")["day_diff"].min()
        pay_best_day_diff = merged.groupby("_orig_idx_pay")["day_diff"].min()

        # high_timing normal docs 의 rec/pay best day_diff 분포
        htw_normal_docs = set(high_timing_docs[~high_timing_docs["is_truth"]].index)
        htw_normal_rec_idx = htw_dates_rec[htw_dates_rec["document_id"].isin(htw_normal_docs)].index
        htw_normal_pay_idx = htw_dates_pay[htw_dates_pay["document_id"].isin(htw_normal_docs)].index
        normal_rec_dd = rec_best_day_diff.reindex(htw_normal_rec_idx).dropna()
        normal_pay_dd = pay_best_day_diff.reindex(htw_normal_pay_idx).dropna()
        all_normal_dd = pd.concat([normal_rec_dd, normal_pay_dd])

        # truth docs 의 best day_diff 분포 비교
        htw_truth_docs = set(high_timing_docs[high_timing_docs["is_truth"]].index)
        htw_truth_rec_idx = htw_dates_rec[htw_dates_rec["document_id"].isin(htw_truth_docs)].index
        htw_truth_pay_idx = htw_dates_pay[htw_dates_pay["document_id"].isin(htw_truth_docs)].index
        truth_rec_dd = rec_best_day_diff.reindex(htw_truth_rec_idx).dropna()
        truth_pay_dd = pay_best_day_diff.reindex(htw_truth_pay_idx).dropna()
        all_truth_dd = pd.concat([truth_rec_dd, truth_pay_dd])

        summary["normal_best_day_diff_describe"] = (
            all_normal_dd.describe().to_dict() if len(all_normal_dd) else {}
        )
        summary["truth_best_day_diff_describe"] = (
            all_truth_dd.describe().to_dict() if len(all_truth_dd) else {}
        )

        # day_diff 의 구간 별 분류 (high_timing normal docs)
        bins = [-0.001, 0, 5, 14, 30, 60, 90, 180, 365, 10000]
        labels = ["0", "1-5", "6-14", "15-30", "31-60", "61-90", "91-180", "181-365", ">365"]
        normal_dd_buckets = pd.cut(all_normal_dd, bins=bins, labels=labels)
        summary["normal_day_diff_bucket_counts"] = normal_dd_buckets.value_counts().to_dict()

        # month-end close pattern (high_timing normal docs)
        rec_dates = rec_df.loc[htw_normal_rec_idx, "posting_date_pd"].dropna()
        pay_dates = pay_df.loc[htw_normal_pay_idx, "posting_date_pd"].dropna()

        # cp_block 매칭된 best pair 의 rec/pay date 페어 분류
        normal_pairs = merged[
            merged["_orig_idx_rec"].isin(htw_normal_rec_idx)
            | merged["_orig_idx_pay"].isin(htw_normal_pay_idx)
        ]
        # best per rec: min day_diff row
        normal_pairs_sorted = normal_pairs.sort_values("day_diff")
        best_normal_pairs = normal_pairs_sorted.drop_duplicates(
            subset=["_orig_idx_rec"], keep="first"
        )
        # 패턴 분류
        pattern_counts: dict[str, int] = {}
        for _, row in best_normal_pairs.head(5000).iterrows():
            cat = _classify_doc_lag_pattern(row["posting_date_pd_rec"], row["posting_date_pd_pay"])
            pattern_counts[cat] = pattern_counts.get(cat, 0) + 1
        summary["normal_high_timing_lag_pattern_top5000_pairs"] = pattern_counts

    summary["elapsed_sec"] = round(time.perf_counter() - t0, 1)

    OUT_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(f"\n[t-dx] wrote {OUT_JSON.relative_to(ROOT)}")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str)[:4000])


if __name__ == "__main__":
    main()
