"""IC noise robustness probe (A1) — baseline + noisy background 비교.

목적: 현재 IC 100% recall 이 "노이즈 0 인 완벽한 정상 배경" 덕분인지 측정한다.
탐지기 코드는 변경하지 않는다. journal 의 정상 IC 행에만 현실 노이즈를 주입한
변형본을 만들어 IC matcher 를 재실행하고, doc 단위로 다음을 비교한다.

    - truth recall    : injected_intercompany_primary doc 중 score>0 비율
    - normal FP rate  : 정상 IC doc 중 score>0 비율  (baseline 에서 0 이어야 정상)
    - precision@K     : score 상위 K doc 중 truth 비율

노이즈는 정상 IC pair (truth 아님) 에만 적용하며 truth doc 은 절대 건드리지 않는다.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config.settings import get_settings
from src.detection.base import DetectionResult
from src.detection.intercompany_matcher import IntercompanyMatcher
from src.detection.intercompany_rules import load_ic_pairs
from src.services.phase2_intercompany_case_builder import build_intercompany_cases
from tools.scripts.measure_phase2_native_cases_fixed5_20260528 import (
    _case_documents,
    _sorted_cases,
)
from tools.scripts.phase2_family_correlation_audit import load_audit_rules

CANDIDATE = "datasynth_manipulation_v7_candidate_fixed5_ownermeta_v33d"
DATA_DIR = ROOT / "data" / "journal" / "primary" / CANDIDATE
JOURNAL = DATA_DIR / "journal_entries.csv"
TRUTH = DATA_DIR / "labels" / "manipulated_entry_truth.csv"
OUT = ROOT / "artifacts" / "ic_noise_probe_20260601.json"

USECOLS = [
    "document_id",
    "company_code",
    "posting_date",
    "currency",
    "reference",
    "gl_account",
    "debit_amount",
    "credit_amount",
    "trading_partner",
]


def _print(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _load() -> tuple[pd.DataFrame, set[str], dict[str, str]]:
    audit_rules = load_audit_rules()
    pair_map = load_ic_pairs(audit_rules)
    _print(f"journal 로드: {JOURNAL.name}")
    df = pd.read_csv(JOURNAL, usecols=USECOLS, low_memory=False)
    df["document_id"] = df["document_id"].astype(str)
    _print(f"  rows={len(df):,} docs={df['document_id'].nunique():,}")

    truth = pd.read_csv(TRUTH, dtype=str).fillna("")
    if "injected_intercompany_primary" in truth.columns:
        ic_mask = truth["injected_intercompany_primary"].str.lower().eq("true")
    else:
        ic_mask = pd.Series(False, index=truth.index)
    truth_docs = set(truth.loc[ic_mask, "document_id"].astype(str))
    _print(f"  truth IC docs (injected_intercompany_primary) = {len(truth_docs)}")
    return df, truth_docs, pair_map


def _ic_row_mask(df: pd.DataFrame, pair_map: dict[str, str]) -> pd.Series:
    prefixes = tuple(sorted(pair_map))
    gl = df["gl_account"].fillna("").astype(str).str.strip()
    return gl.str.startswith(prefixes) if prefixes else pd.Series(False, index=df.index)


def _run_matcher(df: pd.DataFrame, settings: Any, audit_rules: dict) -> DetectionResult:
    """IC matcher 실행 → DetectionResult (scores + ic_pair_artifact metadata)."""
    matcher = IntercompanyMatcher(settings, audit_rules=audit_rules)
    return matcher.detect(df)


def _case_tier_metrics(
    result: DetectionResult,
    df: pd.DataFrame,
    ic_docs: set[str],
    truth_docs: set[str],
) -> dict[str, Any]:
    """공식 IC case 정렬(strong reciprocal → moderate mismatch) 기준 precision/recall.

    raw score 와 달리 unmatched(IC01)는 case 화되지 않으므로(invariant #54) FP 가
    얼마나 걸러지는지, 그리고 truth 34건을 모두 담으려면 감사인이 IC case queue 에서
    총 몇 doc 을 검토해야 하는지(review_cost)를 측정한다.
    """
    cases = build_intercompany_cases(batch_id="ic_noise_probe", detection_result=result, df=df)
    ordered = _sorted_cases(list(cases))
    normal_ic_docs = ic_docs - truth_docs

    # case 정렬 순서로 doc 의 첫 등장 순 ranking 생성 (감사인 검토 순서)
    doc_rank: list[str] = []
    seen: set[str] = set()
    for case in ordered:
        for doc in sorted(_case_documents(case)):
            if doc not in seen:
                seen.add(doc)
                doc_rank.append(doc)

    total = len(doc_rank)
    cum_truth = 0
    review_cost: int | None = None
    for rank, doc in enumerate(doc_rank, 1):
        if doc in truth_docs:
            cum_truth += 1
            if cum_truth == len(truth_docs):
                review_cost = rank

    prec_at: dict[str, float | None] = {}
    rec_at: dict[str, float | None] = {}
    for k in (34, 50, 100, 200, 500):
        topk = set(doc_rank[:k])
        denom = min(k, total)
        prec_at[f"p@{k}"] = (len(topk & truth_docs) / denom) if denom else None
        rec_at[f"r@{k}"] = (len(topk & truth_docs) / len(truth_docs)) if truth_docs else None

    return {
        "ic_case_count": len(ordered),
        "case_covered_docs": total,
        "case_covered_truth": len(set(doc_rank) & truth_docs),
        "case_covered_normal_fp": len(set(doc_rank) & normal_ic_docs),
        "review_cost_for_full_recall": review_cost,
        "precision_at_k": prec_at,
        "recall_at_k": rec_at,
    }


def _doc_scores(df: pd.DataFrame, scores: pd.Series) -> pd.Series:
    """doc 단위 max score (어떤 line 이라도 발화하면 doc flagged)."""
    return scores.groupby(df["document_id"]).max()


def _metrics(
    doc_score: pd.Series,
    ic_docs: set[str],
    truth_docs: set[str],
) -> dict[str, Any]:
    """doc 단위 recall / FP / precision@K."""
    normal_ic_docs = ic_docs - truth_docs
    flagged = set(doc_score.index[doc_score > 0].astype(str))

    truth_flagged = len(truth_docs & flagged)
    normal_flagged = len(normal_ic_docs & flagged)

    ranked = doc_score[doc_score > 0].sort_values(ascending=False)
    ranked_docs = list(ranked.index.astype(str))
    prec_at: dict[str, float | None] = {}
    for k in (34, 50, 100, 200, 500):
        topk = set(ranked_docs[:k])
        denom = min(k, len(ranked_docs))
        prec_at[f"p@{k}"] = (len(topk & truth_docs) / denom) if denom else None

    return {
        "truth_ic_docs": len(truth_docs),
        "normal_ic_docs": len(normal_ic_docs),
        "truth_recall": (truth_flagged / len(truth_docs)) if truth_docs else None,
        "truth_flagged": truth_flagged,
        "normal_fp_rate": (normal_flagged / len(normal_ic_docs)) if normal_ic_docs else None,
        "normal_flagged": normal_flagged,
        "total_flagged_docs": len(flagged),
        "precision_at_k": prec_at,
    }


# ── 노이즈 주입 (정상 IC pair 에만) ──────────────────────────────


def _apply_noise(
    df: pd.DataFrame,
    ic_mask: pd.Series,
    truth_docs: set[str],
    *,
    fraction: float,
    seed: int,
) -> pd.DataFrame:
    """정상 IC 행에 현실 노이즈 4종을 주입한 복사본 반환.

    truth doc 은 절대 변경하지 않는다. 정상 IC doc 중 `fraction` 비율을 무작위로
    골라 doc 별로 노이즈 유형 1개를 적용한다.
        - fx_drift     : 한쪽 금액 ±1~3% (환율/수수료 자연 편차)
        - posting_lag  : posting_date 7~20일 시프트 (선적-도착 lag)
        - partner_name : trading_partner 를 한글 회사명으로 (코드 형식 이탈)
        - partial_offset : 금액 ±5~12% (부분상계/분할)
    """
    rng = np.random.default_rng(seed)
    work = df.copy()
    work["posting_date"] = pd.to_datetime(work["posting_date"], errors="coerce")
    for col in ("debit_amount", "credit_amount"):
        work[col] = pd.to_numeric(work[col], errors="coerce").fillna(0.0)

    doc_id = work["document_id"].astype(str)
    normal_ic_doc_ids = sorted(set(doc_id[ic_mask]) - truth_docs)
    n_pick = int(len(normal_ic_doc_ids) * fraction)
    if n_pick <= 0:
        return work
    picked = set(rng.choice(normal_ic_doc_ids, size=n_pick, replace=False))

    kr_names = [
        "한국기계",
        "신동에프에이",
        "대성정밀",
        "동방산업",
        "우진테크",
        "삼화전자부품",
        "성진메탈",
        "광림",
        "태원물산",
        "한라정공",
    ]
    # doc → 노이즈 유형 (round-robin 분산)
    types = ["fx_drift", "posting_lag", "partner_name", "partial_offset"]
    doc_type = {d: types[i % len(types)] for i, d in enumerate(sorted(picked))}

    is_picked = doc_id.isin(picked)
    picked_ic = is_picked & ic_mask

    # 유형별 mask
    type_of_row = doc_id.map(doc_type)

    # fx_drift / partial_offset: doc 의 첫 IC 행 1개만 금액 스케일 (pair 불균형 유발)
    for kind, lo, hi in (("fx_drift", 0.01, 0.03), ("partial_offset", 0.05, 0.12)):
        rows = work.index[picked_ic & type_of_row.eq(kind)]
        # doc 별 첫 행만
        first_rows = (
            work.loc[rows].assign(_d=doc_id.loc[rows]).groupby("_d", sort=False).head(1).index
        )
        if len(first_rows):
            signs = rng.choice([-1.0, 1.0], size=len(first_rows))
            mags = rng.uniform(lo, hi, size=len(first_rows))
            factors = 1.0 + signs * mags
            for col in ("debit_amount", "credit_amount"):
                vals = work.loc[first_rows, col].to_numpy()
                work.loc[first_rows, col] = np.where(vals != 0, vals * factors, vals).round(2)

    # posting_lag: doc 의 첫 IC 행 date 만 시프트
    rows = work.index[picked_ic & type_of_row.eq("posting_lag")]
    first_rows = work.loc[rows].assign(_d=doc_id.loc[rows]).groupby("_d", sort=False).head(1).index
    if len(first_rows):
        days = rng.integers(7, 21, size=len(first_rows))
        work.loc[first_rows, "posting_date"] = work.loc[
            first_rows, "posting_date"
        ] + pd.to_timedelta(days, unit="D")

    # partner_name: 모든 IC 행의 trading_partner 를 한글명으로
    rows = work.index[picked_ic & type_of_row.eq("partner_name")]
    if len(rows):
        names = rng.choice(kr_names, size=len(rows))
        work.loc[rows, "trading_partner"] = names

    return work


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fractions",
        default="0.0,0.25,0.5,1.0",
        help="정상 IC doc 중 노이즈 적용 비율 목록 (ablation)",
    )
    parser.add_argument("--seed", type=int, default=20260601)
    args = parser.parse_args()
    fractions = [float(x) for x in args.fractions.split(",")]

    settings = get_settings()
    audit_rules = load_audit_rules()
    df, truth_docs, pair_map = _load()
    ic_mask = _ic_row_mask(df, pair_map)
    ic_docs = set(df.loc[ic_mask, "document_id"].astype(str))
    _print(
        f"IC 행={int(ic_mask.sum()):,} IC docs={len(ic_docs):,} truth∩IC docs="
        f"{len(truth_docs & ic_docs)}"
    )

    results: dict[str, Any] = {}
    for frac in fractions:
        tag = f"noise_{frac:.2f}"
        _print(f"=== {tag}: 노이즈 주입 + IC matcher 실행 ===")
        noisy = (
            df
            if frac == 0.0
            else _apply_noise(df, ic_mask, truth_docs, fraction=frac, seed=args.seed)
        )
        t0 = time.perf_counter()
        result = _run_matcher(noisy, settings, audit_rules)
        scores = result.scores.reindex(noisy.index, fill_value=0.0).astype(float)
        doc_score = _doc_scores(noisy, scores)
        m = _metrics(doc_score, ic_docs, truth_docs)
        m["case_tier"] = _case_tier_metrics(result, noisy, ic_docs, truth_docs)
        m["elapsed_sec"] = round(time.perf_counter() - t0, 1)
        results[tag] = m
        ct = m["case_tier"]
        _print(
            f"  [raw] recall={m['truth_recall']} FP={m['normal_fp_rate']:.3f} "
            f"| [case-tier] case_cnt={ct['ic_case_count']} fp_docs={ct['case_covered_normal_fp']} "
            f"review_cost={ct['review_cost_for_full_recall']} "
            f"p@100={ct['precision_at_k']['p@100']} elapsed={m['elapsed_sec']}s"
        )

    payload = {
        "probe": "ic_noise_robustness_A1",
        "dataset": CANDIDATE,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "detector_code_changed": False,
        "noise_applied_to": "normal_ic_docs_only_truth_untouched",
        "noise_types": ["fx_drift", "posting_lag", "partner_name", "partial_offset"],
        "ic_rows": int(ic_mask.sum()),
        "ic_docs": len(ic_docs),
        "truth_ic_docs": len(truth_docs),
        "results_by_noise_fraction": results,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _print(f"wrote {OUT.relative_to(ROOT).as_posix()}")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
