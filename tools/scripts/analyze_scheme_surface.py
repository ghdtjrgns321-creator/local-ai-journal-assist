"""PHASE2 fraud scheme(FS01~14)별 PHASE1 surface 특성화.

Why: PHASE1 fixture 리콜(r23)은 순환 구조라 현실 부정 수법 탐지력을 말하지 못한다.
     PHASE2용 현실 부정 데이터에 PHASE1을 돌려 scheme별로 무엇이 후보로 올라오고
     무엇이 PHASE2 몫인지 역할 경계를 기록한다. **특성화 전용 — 이 결과로 PHASE1을
     튜닝하지 않는다** (truth recall 직접 추구 금지, PHASE2 이관 원칙).

입력:
  - dataset labels/phase2_scheme_truth.csv (scheme별 member_document_ids)
  - measure_phase1_current_p3_2.py 산출 디렉토리 (rule_hits.csv + checkpoint→case artifact)
출력: measure 디렉토리에 scheme_surface.json / scheme_surface.md
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

TOP_NS = (100, 500, 1000)


def _ranked_cases(artifact_path: Path) -> list[dict]:
    with artifact_path.open(encoding="utf-8") as fp:
        artifact = json.load(fp)
    return sorted(
        artifact.get("cases", []),
        key=lambda c: (
            -float(c.get("triage_rank_score") or c.get("priority_score") or 0.0),
            str(c.get("case_id", "")),
        ),
    )


def _case_documents(case: dict) -> set[str]:
    docs = {
        str(doc.get("document_id", ""))
        for doc in case.get("documents", []) or []
        if doc.get("document_id")
    }
    docs.update(
        str(hit.get("document_id", ""))
        for hit in case.get("raw_rule_hits", []) or []
        if hit.get("document_id")
    )
    return docs


def analyze(dataset_dir: Path, measure_dir: Path) -> dict:
    schemes = pd.read_csv(dataset_dir / "labels" / "phase2_scheme_truth.csv")
    schemes["member_document_ids"] = schemes["member_document_ids"].map(json.loads)
    hits = pd.read_csv(measure_dir / "rule_hits.csv", dtype={"document_id": str})
    checkpoint = json.loads(
        (measure_dir / "direct_phase1_checkpoint.json").read_text(encoding="utf-8")
    )
    ranked = _ranked_cases(Path(checkpoint["stages"]["phase1_case_builder"]["artifact_path"]))
    # 문서→(rank, band) 역인덱스: 한 문서가 여러 case면 최상위 rank 유지
    doc_best: dict[str, tuple[int, str]] = {}
    for rank, case in enumerate(ranked, start=1):
        band = str(case.get("priority_band", "low") or "low")
        for doc in _case_documents(case):
            if doc not in doc_best:
                doc_best[doc] = (rank, band)

    rows = []
    for _, scheme in schemes.iterrows():
        docs = {str(d) for d in scheme["member_document_ids"]}
        scheme_hits = hits[hits["document_id"].isin(sorted(docs))]
        rule_counts = scheme_hits.groupby("rule_id")["document_id"].nunique().to_dict()
        matched = [(doc_best[d][0], doc_best[d][1]) for d in docs if d in doc_best]
        best_rank = min((r for r, _ in matched), default=None)
        bands = sorted({b for _, b in matched})
        rows.append(
            {
                "scheme_id": str(scheme["scheme_id"]),
                "fraud_type": str(scheme.get("fraud_type", "")),
                "severity": str(scheme.get("severity", "")),
                "member_docs": len(docs),
                "docs_with_rule_hit": int(scheme_hits["document_id"].nunique()),
                "hit_rules": json.dumps(rule_counts, ensure_ascii=False, sort_keys=True),
                "docs_in_cases": len(matched),
                "best_case_rank": best_rank,
                "case_bands": "|".join(bands),
                **{f"in_top{n}": bool(best_rank and best_rank <= n) for n in TOP_NS},
            }
        )
    per_scheme = pd.DataFrame(rows).sort_values("scheme_id")
    summary = {
        "schemes_total": int(len(per_scheme)),
        "schemes_with_any_rule_hit": int((per_scheme["docs_with_rule_hit"] > 0).sum()),
        "schemes_in_any_case": int((per_scheme["docs_in_cases"] > 0).sum()),
        **{f"schemes_in_top{n}": int(per_scheme[f"in_top{n}"].sum()) for n in TOP_NS},
        "total_cases": len(ranked),
    }
    (measure_dir / "scheme_surface.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    md = (
        "# PHASE2 scheme별 PHASE1 surface 특성화 (튜닝 금지 — 역할 경계 기록)\n\n```\n"
        + json.dumps(summary, ensure_ascii=False, indent=2)
        + "\n```\n\n"
        + per_scheme.to_markdown(index=False)
        + "\n"
    )
    (measure_dir / "scheme_surface.md").write_text(md, encoding="utf-8")
    per_scheme.to_csv(measure_dir / "scheme_surface_per_scheme.csv", index=False)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_dir", type=Path)
    parser.add_argument("measure_dir", type=Path)
    args = parser.parse_args()
    summary = analyze(args.dataset_dir.resolve(), args.measure_dir.resolve())
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
