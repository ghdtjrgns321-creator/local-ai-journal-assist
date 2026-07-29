"""특정 scheme의 표면화된 부정 문서가 '어느 룰에' 걸려 올라왔는지 실측한다.

배경: 순환거래(FS05)·유령급여(FS14)는 전표 단독으로는 구분점이 없다고 서술해 왔는데
실측 표면화가 각각 47~64%·61~72%다. 그렇다면 올라온 문서는 무엇에 걸린 것인지를
룰 단위로 확인해야 서술이 성립한다.

사용: uv run python tools/scripts/diag_scheme_surfacing_rules.py [<fraud_dir>] [<scheme> ...]
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_DIR = ROOT / "data/journal/primary/datasynth_semantic_v1_phase2_fraud_s10_20260718_r1"
DEFAULT_SCHEMES = ["FS05", "FS14"]


def main() -> int:
    from src.export.phase1_case_view import resolve_phase1_case_result
    from src.pipeline import AuditPipeline

    fraud_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DIR
    schemes = sys.argv[2:] or DEFAULT_SCHEMES

    prov = pd.read_csv(fraud_dir / "labels/phase2_scheme_provenance.csv", dtype=str)
    res = AuditPipeline(skip_db=True).run(str(fraud_dir / "journal_entries.csv"))
    phase1 = resolve_phase1_case_result(res)
    units = list(phase1.units) if phase1 else []

    # 문서 → 표면에서 그 문서에 붙은 룰 집합
    doc_rules: dict[str, set[str]] = {}
    for unit in units:
        docs = (
            {str(d) for d in (getattr(unit, "member_document_ids", []) or [])}
            if unit.unit_type == "flow"
            else {str(unit.unit_id)}
        )
        rules = {ref.rule_id for ref in unit.evidence_rows}
        for d in docs:
            doc_rules.setdefault(d, set()).update(rules)

    for scheme in schemes:
        sub = prov[prov["scheme_id"] == scheme]
        docs = set(sub["document_id"])
        role_of = dict(zip(sub["document_id"], sub["component_role"], strict=False))
        surfaced = {d for d in docs if d in doc_rules}

        print(f"\n{'=' * 70}\n{scheme}: 표면화 {len(surfaced)}/{len(docs)}")

        rule_counter: Counter = Counter()
        for d in surfaced:
            rule_counter.update(doc_rules[d])
        print("  표면화를 만든 룰 (문서 수):")
        for rule_id, n in rule_counter.most_common():
            print(f"    {rule_id:<10} {n}")

        print("  component_role 별 표면화:")
        roles: dict[str, list[int]] = {}
        for d in docs:
            r = role_of.get(d, "?")
            hit, tot = roles.setdefault(r, [0, 0])
            roles[r] = [hit + (1 if d in surfaced else 0), tot + 1]
        for r, (hit, tot) in sorted(roles.items(), key=lambda kv: -kv[1][1]):
            print(f"    {r:<30} {hit}/{tot}")

        # 단일 룰만으로 올라온 문서 — "그 룰 하나가 유일한 근거"인 사례
        solo = Counter()
        for d in surfaced:
            if len(doc_rules[d]) == 1:
                solo.update(doc_rules[d])
        if solo:
            print("  단일 룰 근거로만 올라온 문서:")
            for rule_id, n in solo.most_common():
                print(f"    {rule_id:<10} {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
