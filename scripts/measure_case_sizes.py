"""스트리밍으로 PHASE1 case JSON에서 case당 row/document 수 분포 측정."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

V1_CASE = (
    ROOT
    / "artifacts/phase1_cases/_anonymous/phase1case__anonymous_datasynth_v126_profiled_phase1_20260508T105341Z.json"
)
V2_CASE = (
    ROOT
    / "artifacts/phase1_cases/_anonymous/phase1case__anonymous_datasynth_v126_profiled_phase1_20260514T070952Z.json"
)


def measure(path: Path, label: str) -> dict:
    print(f"[{label}] reading {path.name} ({path.stat().st_size / 1e6:.1f} MB)...")
    with open(path, encoding="utf-8") as f:
        obj = json.load(f)
    cases = obj.get("cases") or obj.get("case_records") or []
    print(
        f"  cases container key={'cases' if obj.get('cases') is not None else 'case_records'} count={len(cases)}"
    )
    if cases and isinstance(cases, list):
        sample = cases[0]
        print(f"  sample case top-level keys: {list(sample.keys())[:30]}")

    n_rows_list: list[int] = []
    n_docs_list: list[int] = []
    flagged_rules_count: list[int] = []
    primary_themes: list[str] = []
    priority_bands: list[str] = []
    priority_scores: list[float] = []

    for c in cases:
        # 시도1: rows / documents 직접
        rows_attr = c.get("rows") or c.get("evidence_rows") or c.get("row_entries")
        docs_attr = c.get("documents") or c.get("document_ids") or c.get("doc_ids")
        if rows_attr is None:
            evi = c.get("evidence") or c.get("evidence_set") or {}
            if isinstance(evi, dict):
                rows_attr = (
                    evi.get("rows")
                    or evi.get("row_ids")
                    or evi.get("row_indices")
                    or evi.get("row_entries")
                )
                docs_attr = docs_attr or evi.get("documents") or evi.get("document_ids")
        # 시도2: row_signals/row_refs 카운트
        if rows_attr is None:
            rows_attr = c.get("row_signals") or c.get("row_refs") or c.get("row_summaries")

        n_rows = (
            len(rows_attr)
            if rows_attr is not None and hasattr(rows_attr, "__len__")
            else (int(rows_attr) if isinstance(rows_attr, (int, float)) else None)
        )
        n_docs = (
            len(docs_attr)
            if docs_attr is not None and hasattr(docs_attr, "__len__")
            else (int(docs_attr) if isinstance(docs_attr, (int, float)) else None)
        )

        if n_rows is None:
            for k in ("row_count", "n_rows", "case_row_count", "evidence_row_count"):
                v = c.get(k)
                if isinstance(v, (int, float)):
                    n_rows = int(v)
                    break
        if n_docs is None:
            for k in ("document_count", "n_documents", "doc_count"):
                v = c.get(k)
                if isinstance(v, (int, float)):
                    n_docs = int(v)
                    break

        if n_rows is not None:
            n_rows_list.append(int(n_rows))
        if n_docs is not None:
            n_docs_list.append(int(n_docs))

        fr = c.get("flagged_rules") or c.get("rules") or c.get("rule_ids")
        if fr is not None and hasattr(fr, "__len__"):
            flagged_rules_count.append(len(fr))

        pt = c.get("primary_theme") or c.get("theme_id") or c.get("theme")
        if pt:
            primary_themes.append(str(pt))

        pb = c.get("priority_band") or c.get("band")
        if pb:
            priority_bands.append(str(pb))
        ps = c.get("priority_score") or c.get("score")
        if isinstance(ps, (int, float)):
            priority_scores.append(float(ps))

    def stats(s: list, name: str) -> dict:
        if not s:
            return {"name": name, "n": 0}
        sr = pd.Series(s)
        return {
            "name": name,
            "n": int(len(sr)),
            "mean": round(float(sr.mean()), 3),
            "median": round(float(sr.median()), 3),
            "p10": round(float(sr.quantile(0.10)), 3),
            "p25": round(float(sr.quantile(0.25)), 3),
            "p75": round(float(sr.quantile(0.75)), 3),
            "p90": round(float(sr.quantile(0.90)), 3),
            "p99": round(float(sr.quantile(0.99)), 3),
            "max": int(sr.max()),
            "eq1_pct": round(float((sr == 1).mean() * 100), 2),
            "le2_pct": round(float((sr <= 2).mean() * 100), 2),
            "le3_pct": round(float((sr <= 3).mean() * 100), 2),
            "ge5_pct": round(float((sr >= 5).mean() * 100), 2),
            "ge10_pct": round(float((sr >= 10).mean() * 100), 2),
        }

    out = {
        "label": label,
        "path": str(path),
        "case_count": len(cases),
        "rows_per_case": stats(n_rows_list, "rows"),
        "docs_per_case": stats(n_docs_list, "docs"),
        "rules_per_case": stats(flagged_rules_count, "rules"),
        "theme_counts": dict(Counter(primary_themes).most_common(20)),
        "band_counts": dict(Counter(priority_bands).most_common()),
        "priority_score_stats": stats(priority_scores, "priority_score"),
    }
    return out


def main() -> None:
    res = {}
    if V1_CASE.exists():
        res["v1_evidence"] = measure(V1_CASE, "v1_evidence")
    if V2_CASE.exists():
        res["v2_clean"] = measure(V2_CASE, "v2_clean")

    out_json = ROOT / "artifacts/case_size_v1_vs_v2.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(f"WROTE {out_json}")
    # Echo key stats
    for k, v in res.items():
        print(f"\n=== {k} ===")
        print(f"  case_count={v['case_count']}")
        print(f"  rows_per_case={v['rows_per_case']}")
        print(f"  docs_per_case={v['docs_per_case']}")
        print(f"  rules_per_case={v['rules_per_case']}")


if __name__ == "__main__":
    main()
