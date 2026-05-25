"""IC reciprocal refix diagnosis — score≥0.99 normal 2,432 source breakdown 진단.

분석 전용. 코드 변경 0.

핵심 질문 (사용자 작업 지시):
1. score ≥ 0.99 normal 2,432건의 source breakdown (IC01 / probabilistic / reciprocal / mixed max)
2. ic_reciprocal_flow_prob = 1.0 normal docs 개수
3. 그 normal docs의 GL pair breakdown (1150↔2050 / 4500↔2700 / 기타)
4. 직전 진단 single_doc_reciprocal_gl_ratio normal=0% 와 fresh rerun normal≥0.99=2,432 충돌 원인
5. 4500↔2700 accrual pair가 reciprocal-flow strong 후보로 들어가는지
6. tie-break 분포

산출:
- artifacts/ic_reciprocal_refix_diagnosis_20260524.md
- artifacts/ic_reciprocal_refix_diagnosis_20260524.json
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

OUT_JSON = ROOT / "artifacts" / "ic_reciprocal_refix_diagnosis_20260524.json"
OUT_MD = ROOT / "artifacts" / "ic_reciprocal_refix_diagnosis_20260524.md"


def main() -> None:
    t_start = time.perf_counter()
    print(f"[refix-dx] loading PKL: {FIXED5_PKL.relative_to(ROOT)}")
    with FIXED5_PKL.open("rb") as fh:
        data = pickle.load(fh)
    df = data["df"]
    print(f"[refix-dx]   df rows={len(df):,}")

    truth = pd.read_csv(FIXED5_TRUTH)
    truth["document_id"] = truth["document_id"].astype(str)
    truth_docs = set(truth["document_id"])
    print(f"[refix-dx]   truth docs={len(truth_docs):,}")

    with AUDIT_RULES_PATH.open(encoding="utf-8") as fh:
        audit_rules = yaml.safe_load(fh)

    print("[refix-dx] running IntercompanyMatcher (single pass) ...")
    t_p = time.perf_counter()
    det = IntercompanyMatcher(audit_rules=audit_rules)
    result = det.detect(df)
    details = result.details.copy()
    elapsed_det = time.perf_counter() - t_p
    print(f"[refix-dx]   detect elapsed={elapsed_det:.1f}s, details cols={list(details.columns)}")

    # row-level column attach
    work = df[["document_id", "gl_account", "company_code", "trading_partner"]].copy()
    work["document_id"] = work["document_id"].astype(str)
    for col in details.columns:
        work[col] = details[col].reindex(work.index, fill_value=0.0).astype(float).values

    # doc-level max for each column
    grouped = work.groupby("document_id", sort=False)
    doc_max_cols = [c for c in details.columns]
    doc_max = grouped[doc_max_cols].max()
    doc_max["any_max"] = doc_max.max(axis=1)
    doc_max["is_truth"] = doc_max.index.isin(truth_docs)

    summary: dict = {
        "doc_count": int(len(doc_max)),
        "truth_count": int(doc_max["is_truth"].sum()),
        "normal_count": int((~doc_max["is_truth"]).sum()),
        "details_columns": list(details.columns),
        "detect_elapsed_sec": round(elapsed_det, 1),
    }

    # 질문 1 — score≥0.99 normal source breakdown
    thresholds = [0.99, 0.90, 0.70, 0.50]
    source_breakdown: dict = {}
    for t in thresholds:
        bucket = doc_max[doc_max["any_max"] >= t]
        truth_in_bucket = int(bucket["is_truth"].sum())
        normal_in_bucket = int((~bucket["is_truth"]).sum())
        # 각 column 별 "이 bucket에서 ≥t 만족하는 doc 수"
        col_hits = {}
        for col in doc_max_cols:
            col_hits[col] = int((bucket[col] >= t).sum())
            col_hits[f"{col}__truth"] = int(((bucket[col] >= t) & bucket["is_truth"]).sum())
            col_hits[f"{col}__normal"] = int(((bucket[col] >= t) & (~bucket["is_truth"])).sum())
        # exclusive: 해당 column만 ≥t 인 doc (다른 column < t)
        exclusive: dict = {}
        for col in doc_max_cols:
            other_cols = [c for c in doc_max_cols if c != col]
            mask = (bucket[col] >= t) & (bucket[other_cols] < t).all(axis=1)
            exclusive[col] = int(mask.sum())
            exclusive[f"{col}__truth"] = int((mask & bucket["is_truth"]).sum())
            exclusive[f"{col}__normal"] = int((mask & (~bucket["is_truth"])).sum())
        # multi-source (≥2 columns ≥t)
        multi_mask = (bucket[doc_max_cols] >= t).sum(axis=1) >= 2
        multi = {
            "doc_count": int(multi_mask.sum()),
            "truth": int((multi_mask & bucket["is_truth"]).sum()),
            "normal": int((multi_mask & (~bucket["is_truth"])).sum()),
        }
        source_breakdown[f"ge_{t:.2f}"] = {
            "bucket_doc_count": int(len(bucket)),
            "truth_in_bucket": truth_in_bucket,
            "normal_in_bucket": normal_in_bucket,
            "any_column_ge_t": col_hits,
            "exclusive_column_ge_t": exclusive,
            "multi_source_ge_t": multi,
        }

    summary["source_breakdown"] = source_breakdown

    # 질문 2 — ic_reciprocal_flow_prob = 1.0 normal docs
    recip = doc_max["ic_reciprocal_flow_prob"]
    recip_1_mask = recip >= 0.999
    recip_high_mask = recip >= 0.9
    summary["reciprocal_flow_high"] = {
        "ge_0.999_doc_count": int(recip_1_mask.sum()),
        "ge_0.999_truth": int((recip_1_mask & doc_max["is_truth"]).sum()),
        "ge_0.999_normal": int((recip_1_mask & ~doc_max["is_truth"]).sum()),
        "ge_0.9_doc_count": int(recip_high_mask.sum()),
        "ge_0.9_truth": int((recip_high_mask & doc_max["is_truth"]).sum()),
        "ge_0.9_normal": int((recip_high_mask & ~doc_max["is_truth"]).sum()),
        "ge_0.5_doc_count": int((recip >= 0.5).sum()),
    }

    # 질문 3 — reciprocal ≥0.9 docs의 GL pair breakdown
    high_recip_docs = set(doc_max[recip_high_mask].index)
    high_recip_rows = work[work["document_id"].isin(high_recip_docs)].copy()
    # doc 별 GL 조합
    doc_gls = high_recip_rows.groupby("document_id")["gl_account"].apply(
        lambda s: tuple(sorted(set(str(x) for x in s)))
    )
    pair_counts: dict[str, int] = {}
    pair_truth_counts: dict[str, int] = {}
    for doc_id, gls in doc_gls.items():
        has_1150 = any(g.startswith("1150") for g in gls)
        has_2050 = any(g.startswith("2050") for g in gls)
        has_4500 = any(g.startswith("4500") for g in gls)
        has_2700 = any(g.startswith("2700") for g in gls)
        clearing = has_1150 and has_2050
        accrual = has_4500 and has_2700
        if clearing and accrual:
            tag = "both_clearing_and_accrual"
        elif clearing:
            tag = "clearing_1150_2050"
        elif accrual:
            tag = "accrual_4500_2700"
        else:
            tag = "other"
        pair_counts[tag] = pair_counts.get(tag, 0) + 1
        if doc_id in truth_docs:
            pair_truth_counts[tag] = pair_truth_counts.get(tag, 0) + 1
    summary["reciprocal_high_gl_pair_breakdown"] = {
        "total_docs": pair_counts,
        "truth_docs": pair_truth_counts,
    }

    # 질문 4 — 직전 진단 vs fresh rerun 충돌 분석
    # 직전 진단은 business_process=Intercompany OR gl in (1150/2050/4500/2700) 으로 IC entries 정의.
    # helper는 gl_account prefix만 봄 (is_intercompany 미사용). 둘 다 GL prefix 기준이지만
    # 직전 진단의 분모(9,256 normal IC docs)와 fresh rerun의 분모(전체 318,653 docs)가 다름.
    # 핵심 확인: helper가 high score 주는 normal 2,432 docs가 직전 진단에서 IC entries로 잡혔는지.
    bp_check = df[df["document_id"].astype(str).isin(high_recip_docs)][
        ["document_id", "gl_account", "business_process"]
    ].copy()
    bp_check["document_id"] = bp_check["document_id"].astype(str)
    bp_doc = bp_check.groupby("document_id")["business_process"].apply(
        lambda s: tuple(sorted(set(str(x) for x in s)))
    )
    bp_counts: dict[str, int] = {}
    for doc_id, bps in bp_doc.items():
        for b in bps:
            bp_counts[b] = bp_counts.get(b, 0) + 1
    summary["reciprocal_high_business_process_counts"] = bp_counts

    # 질문 5 — 4500/2700 accrual pair single-doc reciprocal 정상 빈도
    # df 전체에서 4500/2700 single-doc reciprocal balanced docs 정상 비율
    accrual_rows = df[df["gl_account"].astype(str).str.startswith(("4500", "2700"))].copy()
    accrual_rows["document_id"] = accrual_rows["document_id"].astype(str)
    accrual_rows["is_4500"] = accrual_rows["gl_account"].astype(str).str.startswith("4500")
    accrual_rows["is_2700"] = accrual_rows["gl_account"].astype(str).str.startswith("2700")
    accrual_doc_gls = accrual_rows.groupby("document_id").agg(
        has_4500=("is_4500", "any"),
        has_2700=("is_2700", "any"),
    )
    single_doc_accrual_reciprocal = accrual_doc_gls[
        accrual_doc_gls["has_4500"] & accrual_doc_gls["has_2700"]
    ]
    summary["accrual_pair_single_doc_reciprocal"] = {
        "docs_with_both_4500_2700": int(len(single_doc_accrual_reciprocal)),
        "truth_count": int(single_doc_accrual_reciprocal.index.isin(truth_docs).sum()),
        "normal_count": int((~single_doc_accrual_reciprocal.index.isin(truth_docs)).sum()),
    }
    # clearing
    clearing_rows = df[df["gl_account"].astype(str).str.startswith(("1150", "2050"))].copy()
    clearing_rows["document_id"] = clearing_rows["document_id"].astype(str)
    clearing_rows["is_1150"] = clearing_rows["gl_account"].astype(str).str.startswith("1150")
    clearing_rows["is_2050"] = clearing_rows["gl_account"].astype(str).str.startswith("2050")
    clearing_doc_gls = clearing_rows.groupby("document_id").agg(
        has_1150=("is_1150", "any"),
        has_2050=("is_2050", "any"),
    )
    single_doc_clearing_reciprocal = clearing_doc_gls[
        clearing_doc_gls["has_1150"] & clearing_doc_gls["has_2050"]
    ]
    summary["clearing_pair_single_doc_reciprocal"] = {
        "docs_with_both_1150_2050": int(len(single_doc_clearing_reciprocal)),
        "truth_count": int(single_doc_clearing_reciprocal.index.isin(truth_docs).sum()),
        "normal_count": int((~single_doc_clearing_reciprocal.index.isin(truth_docs)).sum()),
    }

    # 질문 6 — tie-break 분포
    # IC family score (any_max) 의 1.0 동률 bucket
    tie_buckets = doc_max["any_max"].round(4).value_counts().head(20)
    summary["score_tie_buckets_top20"] = tie_buckets.to_dict()

    # 추가: IC01 + reciprocal 합산 단독 vs 다른 column
    ic01_only_max = doc_max[doc_max["IC01"] >= 0.99]
    summary["ic01_high_doc_count"] = int(len(ic01_only_max))
    summary["ic01_high_truth"] = int(ic01_only_max["is_truth"].sum())
    summary["ic01_high_normal"] = int((~ic01_only_max["is_truth"]).sum())

    OUT_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(f"\n[refix-dx] wrote {OUT_JSON.relative_to(ROOT)}")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str)[:4000])
    print(f"\n[refix-dx] total elapsed={time.perf_counter() - t_start:.1f}s")


if __name__ == "__main__":
    main()
