"""Tier 3: PHASE1 단위(unit) disjoint denominator 검증.

UNIT_MEASUREMENT_POLICY: 각 문서는 최대 하나의 자연 단위(document XOR flow)에만 속한다.
flow 단위(중복지급·역분개·IC·graph)의 구성 문서는 흐름 단위로 흡수(R1)되어 별도 document
단위로 중복 카운트되면 안 된다. 빌드된 Phase1CaseResult artifact를 로드해 전수 검사한다.

검사:
  1) 같은 document_id 가 2개 이상 unit 에 member 로 등장하는가 (중복 카운트)
  2) document-type unit 문서집합 ∩ flow-type unit 문서집합 = ∅ (R1 흡수)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _unit_documents(unit) -> set[str]:
    docs = {str(d) for d in (getattr(unit, "member_document_ids", None) or []) if str(d)}
    for hit in getattr(unit, "evidence_rows", None) or []:
        doc = str(getattr(hit, "document_id", "") or "")
        if doc:
            docs.add(doc)
    if str(getattr(unit, "unit_type", "")) == "document" and getattr(unit, "unit_id", ""):
        docs.add(str(getattr(unit, "unit_id")))
    return docs


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "artifact", type=Path, nargs="?", help="phase1_case artifact json (생략 시 최신)"
    )
    args = ap.parse_args(argv)

    from src.detection.phase1_case_builder import Phase1CaseResult

    path = args.artifact
    if path is None:
        cand = sorted(
            (ROOT / "artifacts" / "phase1_cases" / "_anonymous").glob("phase1case_*.json"),
            key=lambda p: p.stat().st_mtime,
        )
        if not cand:
            raise SystemExit("artifact 없음")
        path = cand[-1]
    print(f"[disjoint] artifact: {path}")
    result = Phase1CaseResult.model_validate_json(Path(path).read_text(encoding="utf-8"))
    units = list(getattr(result, "units", []) or [])
    if not units:
        raise SystemExit("[disjoint] units 0 — hollow (빌드 실패 의심)")

    by_type = defaultdict(int)
    doc_to_units: dict[str, list[str]] = defaultdict(list)
    type_doc_sets: dict[str, set[str]] = defaultdict(set)
    for u in units:
        ut = str(getattr(u, "unit_type", ""))
        by_type[ut] += 1
        docs = _unit_documents(u)
        type_doc_sets[ut] |= docs
        uid = str(getattr(u, "unit_id", ""))
        for d in docs:
            doc_to_units[d].append(f"{ut}:{uid}")

    multi = {d: us for d, us in doc_to_units.items() if len(set(us)) > 1}
    doc_set = type_doc_sets.get("document", set())
    flow_set = type_doc_sets.get("flow", set())
    overlap = doc_set & flow_set

    summary = {
        "artifact": str(path),
        "total_units": len(units),
        "units_by_type": dict(by_type),
        "distinct_member_documents": len(doc_to_units),
        "documents_in_multiple_units": len(multi),
        "document_x_flow_overlap": len(overlap),
        "disjoint_pass": len(multi) == 0 and len(overlap) == 0,
    }
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    if multi:
        print("[disjoint] VIOLATION 샘플(최대 10):")
        for d, us in list(multi.items())[:10]:
            print(f"  {d} -> {sorted(set(us))}")
    out = Path(path).parent / "unit_disjoint_check.json"
    out.write_text(
        json.dumps(
            {**summary, "multi_sample": {d: sorted(set(u)) for d, u in list(multi.items())[:50]}},
            ensure_ascii=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"[disjoint] wrote {out}")
    return 0 if summary["disjoint_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
