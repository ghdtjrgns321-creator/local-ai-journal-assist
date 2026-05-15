"""Sample 50 hits per WARNING rule and decompose detector vs truth coverage.

Usage:
  PYTHONPATH=. uv run python scripts/audit_v2_warning_rules.py
Output:
  - artifacts/contract_v2_warning_rule_sample_audit.csv (per-row sample with metadata)
  - artifacts/contract_v2_warning_rule_sample_summary.json (per-rule counts and FP rate)
"""

from __future__ import annotations

import json
import pickle
import random
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent
PKL = ROOT / "artifacts" / "phase1_contract_v2_case_input_20260514.pkl"
LABELS = ROOT / "data" / "journal" / "primary" / "datasynth_contract_v2" / "labels"
OUT_DIR = ROOT / "artifacts"
RULES = ["L4-04", "L4-05", "L3-06", "L2-05"]
PER_RULE_SAMPLE = 50
NORMAL_SAMPLE = 300
SEED = 20260514

random.seed(SEED)
rng = np.random.default_rng(SEED)


def truth_path(rule: str) -> Path:
    return LABELS / f"rule_truth_{rule.replace('-', '_')}.csv"


def load_truth(rule: str) -> set[str]:
    p = truth_path(rule)
    if not p.exists():
        return set()
    df = pd.read_csv(p, usecols=["document_id"], dtype=str)
    return set(df["document_id"].astype(str))


def get_layer(results, suffix: str):
    for r in results:
        if str(r.track_name).endswith(suffix):
            return r
    raise SystemExit(f"layer {suffix} not found")


def gather_row_annotations(metadata: dict, rule: str) -> dict:
    row_annotations = metadata.get("row_annotations", {})
    if rule in row_annotations:
        ra = row_annotations[rule]
        if isinstance(ra, dict):
            return ra
    return {}


def summarise(annotation: dict) -> str:
    if not annotation:
        return ""
    bucket = annotation.get("score_bucket") or annotation.get("bucket")
    reason = annotation.get("primary_reason") or annotation.get("reason_code")
    return f"{bucket or ''}/{reason or ''}".strip("/")


def pick_rule_result(results, rule: str):
    layer_c_rules = {
        "L3-04",
        "L3-05",
        "L3-06",
        "L3-07",
        "L1-08",
        "L3-08",
        "L4-03",
        "L4-04",
        "L3-09",
        "L2-05",
        "L4-05",
        "L4-06",
    }
    layer_b_rules = {
        "L4-01",
        "L2-01",
        "L1-04",
        "L2-02",
        "L2-03",
        "L1-05",
        "L1-06",
        "L3-02",
        "L1-07",
        "L1-09",
        "L3-10",
        "L3-12",
        "L3-03",
        "L2-04",
    }
    layer_a_rules = {"L1-01", "L1-02", "L1-03", "L3-01"}
    if rule in layer_c_rules:
        return get_layer(results, "layer_c")
    if rule in layer_b_rules:
        return get_layer(results, "layer_b")
    if rule in layer_a_rules:
        return get_layer(results, "layer_a")
    raise SystemExit(f"unmapped rule {rule}")


def _safe_div(a, b):
    return float(a / b) if b else None


def _jsonify(obj):
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _jsonify(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_jsonify(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return str(obj)


def _excerpt(obj):
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {k: _excerpt(v) for k, v in list(obj.items())[:20]}
    if isinstance(obj, list):
        return [_excerpt(x) for x in obj[:20]]
    return _jsonify(obj)


def main() -> None:
    print("Loading case_input pkl ...", flush=True)
    with open(PKL, "rb") as f:
        obj = pickle.load(f)
    df = obj["df"]
    results = obj["results"]
    print(f"  df rows={len(df):,} docs={df['document_id'].nunique():,}", flush=True)

    summary: dict = {"rules": {}}
    sample_rows: list[dict] = []

    for rule in RULES:
        print(f"\n=== {rule} ===", flush=True)
        result = pick_rule_result(results, rule)
        details = result.details
        if rule not in details.columns:
            raise SystemExit(f"{rule} not in details columns")
        flag = details[rule].astype(bool).to_numpy()
        hit_idx = np.flatnonzero(flag)
        print(f"  detector rows: {len(hit_idx):,}")
        if len(hit_idx) == 0:
            summary["rules"][rule] = {"detector_rows": 0}
            continue

        hit_df = df.iloc[hit_idx]
        hit_docs = set(hit_df["document_id"].astype(str))
        truth_docs = load_truth(rule)
        truth_hit = hit_docs & truth_docs
        detector_extra = hit_docs - truth_docs
        truth_missing = truth_docs - hit_docs
        print(f"  truth docs total      : {len(truth_docs):,}")
        print(f"  hit docs              : {len(hit_docs):,}")
        print(f"  truth_pos docs        : {len(truth_hit):,}")
        print(f"  detector_only docs    : {len(detector_extra):,}")
        print(f"  truth_only (missed)   : {len(truth_missing):,}")

        row_annotations = gather_row_annotations(result.metadata, rule)
        target_per_bucket = PER_RULE_SAMPLE // 2
        truth_pool = sorted(hit_docs & truth_docs)
        extra_pool = sorted(hit_docs - truth_docs)
        random.shuffle(truth_pool)
        random.shuffle(extra_pool)
        chosen_truth = truth_pool[:target_per_bucket]
        chosen_extra = extra_pool[:target_per_bucket]
        chosen = [(d, "truth_positive") for d in chosen_truth] + [
            (d, "detector_extra") for d in chosen_extra
        ]

        bucket_counter: Counter = Counter()
        hit_by_doc = hit_df.groupby("document_id").first()
        for doc_id, source_bucket in chosen:
            if doc_id not in hit_by_doc.index:
                continue
            row = hit_by_doc.loc[doc_id]
            ridx = row.name
            try:
                int_idx = int(row_annotations_key(hit_df, doc_id))
            except Exception:
                int_idx = None
            annotation = {}
            for cand in [int_idx, ridx]:
                if cand is None:
                    continue
                if cand in row_annotations:
                    annotation = row_annotations[cand]
                    break
            bucket = summarise(annotation)
            bucket_counter[bucket] += 1
            sample_rows.append(
                {
                    "rule_id": rule,
                    "doc_audit_bucket": source_bucket,
                    "document_id": doc_id,
                    "fiscal_year": row.get("fiscal_year"),
                    "fiscal_period": row.get("fiscal_period"),
                    "posting_date": str(row.get("posting_date")),
                    "document_type": row.get("document_type"),
                    "business_process": row.get("business_process"),
                    "semantic_scenario_id": row.get("semantic_scenario_id"),
                    "counterparty_type": row.get("counterparty_type"),
                    "source": row.get("source"),
                    "created_by": row.get("created_by"),
                    "approved_by": row.get("approved_by"),
                    "gl_account": row.get("gl_account"),
                    "debit_amount": row.get("debit_amount"),
                    "credit_amount": row.get("credit_amount"),
                    "time_zone_category": row.get("time_zone_category"),
                    "is_after_hours": row.get("is_after_hours"),
                    "is_weekend": row.get("is_weekend"),
                    "is_holiday": row.get("is_holiday"),
                    "is_period_end": row.get("is_period_end"),
                    "annotation_bucket": (
                        annotation.get("score_bucket") or annotation.get("bucket") or ""
                    ),
                    "annotation_primary_reason": (
                        annotation.get("primary_reason") or annotation.get("reason_code") or ""
                    ),
                    "annotation_score": annotation.get("score"),
                    "annotation_full": (
                        json.dumps(_jsonify(annotation), ensure_ascii=False) if annotation else ""
                    ),
                    "in_truth": doc_id in truth_docs,
                }
            )

        rb = result.metadata.get("rule_breakdowns", {})
        breakdown = rb.get(rule)
        summary["rules"][rule] = {
            "detector_rows": int(len(hit_idx)),
            "detector_docs": int(len(hit_docs)),
            "truth_docs": int(len(truth_docs)),
            "truth_pos_docs": int(len(truth_hit)),
            "detector_only_docs": int(len(detector_extra)),
            "truth_missed_docs": int(len(truth_missing)),
            "truth_recall": _safe_div(len(truth_hit), len(truth_docs)),
            "detector_precision_vs_truth": _safe_div(len(truth_hit), len(hit_docs)),
            "annotation_bucket_counts": dict(bucket_counter),
            "rule_breakdown_excerpt": _excerpt(breakdown),
        }

    print("\n=== Normal sample FP rate ===", flush=True)
    rule_hit_mask = np.zeros(len(df), dtype=bool)
    for rule in RULES:
        result = pick_rule_result(results, rule)
        rule_hit_mask |= result.details[rule].astype(bool).to_numpy()

    truth_docs_global = set(
        pd.read_csv(LABELS / "rule_truth.csv", usecols=["document_id"], dtype=str)["document_id"]
    )
    normal_mask = (~rule_hit_mask) & (
        ~df["document_id"].astype(str).isin(truth_docs_global).to_numpy()
    )
    print(f"  candidate normal rows: {normal_mask.sum():,}")
    normal_pool_idx = np.flatnonzero(normal_mask)
    sample_idx = rng.choice(
        normal_pool_idx, size=min(NORMAL_SAMPLE, len(normal_pool_idx)), replace=False
    )

    fp_counts = {rule: 0 for rule in RULES}
    for rule in RULES:
        result = pick_rule_result(results, rule)
        rule_flag = result.details[rule].astype(bool).to_numpy()
        fp_counts[rule] = int(rule_flag[sample_idx].sum())
    print("  fp_counts per rule:", fp_counts)
    summary["normal_sample"] = {
        "size": int(len(sample_idx)),
        "fp_counts": fp_counts,
        "fp_rate_per_rule": {k: _safe_div(v, len(sample_idx)) for k, v in fp_counts.items()},
    }

    sample_df = pd.DataFrame(sample_rows)
    sample_csv = OUT_DIR / "contract_v2_warning_rule_sample_audit.csv"
    sample_df.to_csv(sample_csv, index=False)
    summary_json = OUT_DIR / "contract_v2_warning_rule_sample_summary.json"
    with open(summary_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\nWrote {sample_csv} ({len(sample_df)} rows)")
    print(f"Wrote {summary_json}")


def row_annotations_key(hit_df: pd.DataFrame, doc_id: str):
    sub = hit_df[hit_df["document_id"].astype(str) == doc_id]
    return sub.index[0] if not sub.empty else None


if __name__ == "__main__":
    main()
