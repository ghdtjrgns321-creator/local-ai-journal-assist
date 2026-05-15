"""§8.3 — v2 'too clean' normal data background audit.

목적: v2 semantic-clean 정책이 case 폭증의 원인인지 정량 분석.
산출물: artifacts/manipulation_v2_clean_background_audit.md
"""

from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ART = ROOT / "artifacts"

V1_CACHE = ART / "phase1_manipulation_case_input.pkl"
V2_CACHE = ART / "phase1_manipulation_v2_case_input.pkl"
V1_PROFILE = ART / "phase1_manipulation_profile.json"
V2_PROFILE = ART / "phase1_manipulation_v2_profile.json"

V1_MANIFEST = (
    ROOT / "data/journal/primary/datasynth_manipulation/MANIPULATION_DATASET_MANIFEST.json"
)
V2_MANIFEST = (
    ROOT / "data/journal/primary/datasynth_manipulation_v2/MANIPULATION_V2_DATASET_MANIFEST.json"
)
V1_GENSTATS = ROOT / "data/journal/primary/datasynth_manipulation/generation_statistics.json"
V2_GENSTATS = ROOT / "data/journal/primary/datasynth_manipulation_v2/generation_statistics.json"

V1_TRUTH = ROOT / "data/journal/primary/datasynth_manipulation/labels/manipulated_entry_truth.csv"
V2_TRUTH = (
    ROOT / "data/journal/primary/datasynth_manipulation_v2/labels/manipulated_entry_truth.csv"
)

OUT = ART / "manipulation_v2_clean_background_audit.md"


def _truth_doc_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    tr = pd.read_csv(path, low_memory=False)
    for col in ("document_id", "doc_id", "entry_id"):
        if col in tr.columns:
            return set(tr[col].astype(str).unique())
    return set()


def _load_cache(path: Path) -> dict:
    with open(path, "rb") as f:
        obj = pickle.load(f)
    if isinstance(obj, dict):
        return obj
    df = getattr(obj, "data", None)
    results = getattr(obj, "results", None) or []
    case = getattr(obj, "phase1_case_result", None)
    return {"df": df, "results": results, "phase1_case_result": case}


def _extract_rule_flags(df: pd.DataFrame) -> list[str]:
    return [
        c
        for c in df.columns
        if c.startswith("flag_") or c.startswith("rule_") or c.endswith("_flag")
    ]


def _detector_summary(results: list) -> list[dict]:
    rows = []
    for r in results:
        rule_id = getattr(r, "rule_id", None) or getattr(r, "name", None)
        if rule_id is None:
            continue
        flagged_rows = getattr(r, "flagged_rows", None)
        flag_count = None
        if flagged_rows is not None:
            try:
                flag_count = int(getattr(flagged_rows, "shape", [0])[0])
            except Exception:
                flag_count = None
        rows.append({"rule_id": rule_id, "flag_count": flag_count})
    return rows


def _case_size_distribution(case_result) -> dict:
    if case_result is None:
        return {"count": 0, "rows": []}
    cases = getattr(case_result, "cases", None) or []
    sizes = []
    for c in cases:
        sz = None
        for attr in ("row_count", "size", "n_rows", "rows", "evidence_rows"):
            v = getattr(c, attr, None)
            if v is None:
                continue
            if isinstance(v, (int, float)):
                sz = int(v)
                break
            if hasattr(v, "__len__"):
                sz = int(len(v))
                break
        if sz is not None:
            sizes.append(sz)
    sizes_sr = pd.Series(sizes) if sizes else pd.Series(dtype=int)
    return {
        "count": len(cases),
        "with_size": int(len(sizes_sr)),
        "mean": float(sizes_sr.mean()) if len(sizes_sr) else None,
        "median": float(sizes_sr.median()) if len(sizes_sr) else None,
        "p10": float(sizes_sr.quantile(0.10)) if len(sizes_sr) else None,
        "p90": float(sizes_sr.quantile(0.90)) if len(sizes_sr) else None,
        "max": int(sizes_sr.max()) if len(sizes_sr) else None,
        "single_row_pct": float((sizes_sr <= 1).mean() * 100) if len(sizes_sr) else None,
        "le2_pct": float((sizes_sr <= 2).mean() * 100) if len(sizes_sr) else None,
        "ge5_pct": float((sizes_sr >= 5).mean() * 100) if len(sizes_sr) else None,
    }


def _risk_dist(df: pd.DataFrame) -> dict:
    if df is None or "risk_level" not in df.columns:
        return {}
    vc = df["risk_level"].value_counts(dropna=False)
    return {str(k): int(v) for k, v in vc.items()}


def _normal_rule_hit_counts(df: pd.DataFrame, truth_docs: set[str]) -> dict:
    if df is None:
        return {}
    if "document_id" in df.columns:
        norm = df[~df["document_id"].astype(str).isin(truth_docs)]
    else:
        norm = df
    flag_cols = _extract_rule_flags(df)
    out = {}
    for c in flag_cols:
        try:
            cnt = int(norm[c].fillna(False).astype(bool).sum())
        except Exception:
            try:
                cnt = int(pd.to_numeric(norm[c], errors="coerce").fillna(0).gt(0).sum())
            except Exception:
                continue
        out[c] = cnt
    return dict(sorted(out.items(), key=lambda kv: -kv[1])[:60])


def _profile_rule_signal(profile_path: Path) -> dict:
    if not profile_path.exists():
        return {}
    with open(profile_path, encoding="utf-8") as f:
        prof = json.load(f)
    out = {}
    for key in (
        "rule_hit_counts",
        "rule_flag_counts",
        "rule_signal_summary",
        "rule_hits",
        "flag_counts",
    ):
        if key in prof:
            out[key] = prof[key]
    if "rules" in prof and isinstance(prof["rules"], list):
        out["rules_preview"] = prof["rules"][:5]
    if "summary" in prof:
        out["summary"] = prof["summary"]
    if "phase1_case_summary" in prof:
        out["phase1_case_summary"] = prof["phase1_case_summary"]
    if "case_summary" in prof:
        out["case_summary"] = prof["case_summary"]
    if "topic_distribution" in prof:
        out["topic_distribution"] = prof["topic_distribution"]
    return out


def main() -> None:
    print("[1/6] loading v1 cache...")
    v1 = _load_cache(V1_CACHE)
    print(f"  v1 df shape={None if v1['df'] is None else v1['df'].shape}")
    print(f"  v1 results n={len(v1['results'])}")

    print("[2/6] loading v2 cache...")
    v2 = _load_cache(V2_CACHE)
    print(f"  v2 df shape={None if v2['df'] is None else v2['df'].shape}")
    print(f"  v2 results n={len(v2['results'])}")

    v1_truth = _truth_doc_ids(V1_TRUTH)
    v2_truth = _truth_doc_ids(V2_TRUTH)
    print(f"  v1 truth_docs={len(v1_truth)}  v2 truth_docs={len(v2_truth)}")

    print("[3/6] risk_level distributions...")
    v1_risk = _risk_dist(v1["df"])
    v2_risk = _risk_dist(v2["df"])

    print("[4/6] normal-row rule-hit counts...")
    v1_rule = _normal_rule_hit_counts(v1["df"], v1_truth)
    v2_rule = _normal_rule_hit_counts(v2["df"], v2_truth)

    print("[5/6] detector summaries...")
    v1_det = _detector_summary(v1["results"])
    v2_det = _detector_summary(v2["results"])

    print("[6/6] case size distribution...")
    v1_case = _case_size_distribution(v1.get("phase1_case_result"))
    v2_case = _case_size_distribution(v2.get("phase1_case_result"))
    print(f"  v1 case_count={v1_case.get('count')}  v2 case_count={v2_case.get('count')}")

    v1_prof = _profile_rule_signal(V1_PROFILE)
    v2_prof = _profile_rule_signal(V2_PROFILE)

    with open(V1_GENSTATS) as f:
        v1_gs = json.load(f)
    with open(V2_GENSTATS) as f:
        v2_gs = json.load(f)
    with open(V1_MANIFEST) as f:
        v1_man = json.load(f)
    with open(V2_MANIFEST) as f:
        v2_man = json.load(f)

    payload = {
        "v1_risk": v1_risk,
        "v2_risk": v2_risk,
        "v1_normal_rule_hits": v1_rule,
        "v2_normal_rule_hits": v2_rule,
        "v1_detector_summary": v1_det,
        "v2_detector_summary": v2_det,
        "v1_case_size": v1_case,
        "v2_case_size": v2_case,
        "v1_profile_signal": v1_prof,
        "v2_profile_signal": v2_prof,
        "v1_genstats": v1_gs,
        "v2_genstats": v2_gs,
        "v1_manifest_stats": v1_man.get("stats"),
        "v2_manifest_stats": v2_man.get("stats"),
        "v1_truth_docs": len(v1_truth),
        "v2_truth_docs": len(v2_truth),
    }
    out_json = ART / "manipulation_v2_clean_background_audit.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    print(f"WROTE {out_json}")


if __name__ == "__main__":
    main()
