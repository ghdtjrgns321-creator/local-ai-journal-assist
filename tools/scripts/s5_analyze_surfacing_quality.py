"""S5 보조 — 표면화된 부정 문서가 '무엇에 걸려' 올라왔는지 분해한다.

문제: 표면 커버리지는 "부정 문서가 목록에 오른 비율"이라 어떤 성격의 신호가 올렸는지를
말해주지 않는다. 순환거래(FS05) 실측에서 표면화 문서 다수가 휴일·수기 같은 모양 신호
하나에만 걸려 올라온 것이 확인돼, 이를 전 scheme으로 전수 분해한다.

분류 기준은 새로 만들지 않고 **프로젝트 자체 어휘**를 쓴다 (config/combo_builder.yaml):
  - 몸통(bodies) 10종 = 조작 대상. 금감원 확정 1건 이상 AND 기준서 240 조작대상 조항 매핑
  - 특징(features) 10종 = 부정 전표의 모양. 기준서 240 특징 목록 매핑
  - 그 외 = 빌더 어휘 밖 룰 (데이터 정합성·모집단 신호 등)

문서별 3분류:
  BODY_AND_FEATURE  조작 대상 + 모양이 함께 걸림
  BODY_ONLY         조작 대상만
  FEATURE_ONLY      모양뿐 — 그 수법을 짚은 것이 아니라 정황에 걸린 것
  OTHER_ONLY        어휘 밖 룰만

scheme↔몸통 대응은 문서화된 기대 매핑이 없으므로 **판정하지 않는다.** 대신 scheme별로
실제 발화한 몸통 룰의 이름과 건수를 그대로 싣어, 대응 여부를 읽는 사람이 보게 한다.

사용: uv run python tools/scripts/s5_analyze_surfacing_quality.py <fraud_dir> [<fraud_dir2> ...]
출력: reports/s5_fraud_overlay/surfacing_quality_<dataset>.json
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "reports/s5_fraud_overlay"


def classify(rules: set[str], bodies: set[str], features: set[str]) -> str:
    has_body = bool(rules & bodies)
    has_feature = bool(rules & features)
    if has_body and has_feature:
        return "BODY_AND_FEATURE"
    if has_body:
        return "BODY_ONLY"
    if has_feature:
        return "FEATURE_ONLY"
    return "OTHER_ONLY"


def analyze(fraud_dir: Path) -> dict:
    from src.export.phase1_case_view import resolve_phase1_case_result
    from src.export.phase1_combo_builder import load_combo_vocabulary
    from src.pipeline import AuditPipeline

    vocab = load_combo_vocabulary()
    bodies, features = set(vocab.body_ids), set(vocab.feature_ids)

    prov = pd.read_csv(fraud_dir / "labels" / "phase2_scheme_provenance.csv", dtype=str)
    fraud_docs = set(prov["document_id"])
    doc_scheme = dict(zip(prov["document_id"], prov["scheme_id"], strict=False))
    scheme_totals = prov.groupby("scheme_id")["document_id"].nunique().to_dict()

    res = AuditPipeline(skip_db=True).run(str(fraud_dir / "journal_entries.csv"))
    phase1 = resolve_phase1_case_result(res)
    units = list(phase1.units) if phase1 else []

    doc_rules: dict[str, set[str]] = {}
    for unit in units:
        docs = (
            {str(d) for d in (getattr(unit, "member_document_ids", []) or [])}
            if unit.unit_type == "flow"
            else {str(unit.unit_id)}
        )
        hit = docs & fraud_docs
        if not hit:
            continue
        rules = {ref.rule_id for ref in unit.evidence_rows}
        for d in hit:
            doc_rules.setdefault(d, set()).update(rules)

    overall: Counter = Counter()
    per_scheme: dict[str, dict] = {}
    for doc, rules in doc_rules.items():
        kind = classify(rules, bodies, features)
        overall[kind] += 1
        s = doc_scheme[doc]
        entry = per_scheme.setdefault(
            s,
            {
                "total": scheme_totals.get(s, 0),
                "surfaced": 0,
                "kinds": Counter(),
                "bodies": Counter(),
            },
        )
        entry["surfaced"] += 1
        entry["kinds"][kind] += 1
        entry["bodies"].update(rules & bodies)

    surfaced_total = sum(overall.values())
    return {
        "dataset": fraud_dir.name,
        "fraud_docs_total": len(fraud_docs),
        "surfaced": surfaced_total,
        "vocabulary": {"bodies": sorted(bodies), "features": sorted(features)},
        "overall": {
            "counts": dict(overall),
            "feature_only_share": (
                round(overall["FEATURE_ONLY"] / surfaced_total, 4) if surfaced_total else 0.0
            ),
        },
        "per_scheme": {
            s: {
                "total": v["total"],
                "surfaced": v["surfaced"],
                "kinds": dict(v["kinds"]),
                "fired_bodies": dict(v["bodies"].most_common()),
            }
            for s, v in sorted(per_scheme.items())
        },
    }


def main() -> int:
    dirs = [Path(a) for a in sys.argv[1:]]
    if not dirs:
        print("usage: s5_analyze_surfacing_quality.py <fraud_dir> [...]")
        return 2
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for d in dirs:
        rep = analyze(d)
        out = OUT_DIR / f"surfacing_quality_{d.name}.json"
        out.write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
        o = rep["overall"]["counts"]
        print(f"=== {d.name}  표면화 {rep['surfaced']}/{rep['fraud_docs_total']}")
        for k in ("BODY_AND_FEATURE", "BODY_ONLY", "FEATURE_ONLY", "OTHER_ONLY"):
            print(f"    {k:<18} {o.get(k, 0)}")
        print(f"    특징만 비중 {rep['overall']['feature_only_share']:.1%}")
        print(f"    -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
