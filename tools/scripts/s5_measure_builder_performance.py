"""S5 측정 — fraud overlay 데이터셋에서 조합 빌더의 부정 표면화 성능 실측.

사용: uv run python tools/scripts/s5_measure_builder_performance.py <fraud_dir> [<fraud_dir2> ...]
복수 데이터셋(시드 회전본)을 주면 마지막에 합산(aggregate) 섹션을 출력한다.

측정 3면 (PHASE1 역할 원칙 — 부정 "확정"이 아니라 검토 표면화가 목적):
  1) 표면 커버리지: 주입 부정 문서가 검토 표면(units)에 오르는 비율 + 부정 문서 발화 룰 분포.
  2) 프리셋 4종별: scheme별 부정 적중(표면화) / matched 총량(감사인 작업량) / 부정 밀도.
  3) 빌더 전체 어휘(몸통 전체 OR × 특징 없음): 빌더 표면의 상한 커버리지.

주의: 전수 파이프라인 실행이라 데이터셋당 수 분 소요 — 10분 캡 대비 백그라운드 실행 권장.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "reports/s5_fraud_overlay"


def measure_dataset(fraud_dir: Path) -> dict:
    from src.export.phase1_case_view import resolve_phase1_case_result
    from src.export.phase1_combo_builder import load_combo_vocabulary, match_units
    from src.pipeline import AuditPipeline

    vocab = load_combo_vocabulary()
    prov = pd.read_csv(fraud_dir / "labels" / "phase2_scheme_provenance.csv", dtype=str)
    fraud_docs = set(prov["document_id"])
    doc_scheme = dict(zip(prov["document_id"], prov["scheme_id"], strict=False))
    schemes = sorted(prov["scheme_id"].unique())

    res = AuditPipeline(skip_db=True).run(str(fraud_dir / "journal_entries.csv"))
    phase1 = resolve_phase1_case_result(res)
    if phase1 is None or not phase1.units:
        return {"dataset": fraud_dir.name, "error": "phase1 units 없음"}
    units = list(phase1.units)

    def unit_docs(unit) -> set[str]:
        if unit.unit_type == "flow":
            return {str(d) for d in (getattr(unit, "member_document_ids", []) or [])}
        return {str(unit.unit_id)}

    # 1) 표면 커버리지 + 부정 문서 발화 룰 분포
    #    룰별로 정상 문서 적중도 함께 센다 — 부정만 세면 "정상에도 똑같이 발화하는 룰"이
    #    커버리지를 부풀린다(실측 L3-04: 부정 43.0% vs 정상 44.5%).
    surfaced: set[str] = set()
    fraud_rule_hits: dict[str, set[str]] = {}  # rule_id -> 그 룰이 실제로 발화한 fraud docs
    normal_rule_hits: dict[str, set[str]] = {}  # rule_id -> 그 룰이 실제로 발화한 normal docs
    doc_rules: dict[str, set[str]] = {}  # fraud doc -> 그 문서를 표면에 올린 룰들
    for unit in units:
        docs = unit_docs(unit)
        hit_frauds = docs & fraud_docs
        rule_ids = {ref.rule_id for ref in unit.evidence_rows}

        # 판별력(lift)은 룰이 **실제로 발화한 전표**만 센다. flow unit 의 나머지 전표까지
        # 그 룰의 공으로 돌리면 묶음이 큰 룰일수록 발현율이 부풀고(실측 L3-09 35→53건),
        # "발현율"이라는 이름과 재는 것이 어긋난다. 표면 커버리지는 반대로 묶음 기준이
        # 맞다 — 묶음이 목록에 오르면 그 안의 전표는 실제로 감사인이 보게 되므로
        # 아래 surfaced/doc_rules 는 unit 단위를 유지한다.
        for ref in unit.evidence_rows:
            ref_doc = str(ref.document_id) if getattr(ref, "document_id", None) else None
            if ref_doc is None and len(docs) == 1:
                ref_doc = next(iter(docs))  # 단일 전표 unit 은 unit_id 가 곧 그 전표
            if ref_doc is None:
                continue  # flow unit 인데 귀속 전표 불명 — 세지 않는다
            bucket = fraud_rule_hits if ref_doc in fraud_docs else normal_rule_hits
            bucket.setdefault(ref.rule_id, set()).add(ref_doc)

        if not hit_frauds:
            continue
        surfaced |= hit_frauds
        for doc in hit_frauds:
            doc_rules.setdefault(doc, set()).update(rule_ids)

    # 판별력(lift) = 부정 발화율 / 정상 발화율. lift <= 1.0 이면 그 룰은 부정을 정상보다
    # 더 자주 지목하지 않으므로 표면화 근거로 셀 수 없다. 임계를 손으로 정하지 않고
    # "정상보다 나은가"라는 최소 조건만 쓴다.
    fraud_total = len(fraud_docs)
    normal_total = len(set(res.data["document_id"].astype(str))) - fraud_total
    rule_power = {}
    for rule_id in sorted(set(fraud_rule_hits) | set(normal_rule_hits)):
        f_hit = len(fraud_rule_hits.get(rule_id, set()))
        n_hit = len(normal_rule_hits.get(rule_id, set()))
        f_rate = f_hit / fraud_total if fraud_total else 0.0
        n_rate = n_hit / normal_total if normal_total else 0.0
        rule_power[rule_id] = {
            "fraud_docs": f_hit,
            "fraud_rate": round(f_rate, 4),
            "normal_docs": n_hit,
            "normal_rate": round(n_rate, 4),
            "lift": round(f_rate / n_rate, 3) if n_rate > 0 else None,
        }
    uninformative = sorted(
        r for r, p in rule_power.items() if p["lift"] is not None and p["lift"] <= 1.0
    )
    surfaced_informative = {doc for doc, rules in doc_rules.items() if rules - set(uninformative)}

    scheme_surfaced = {s: sorted(d for d in surfaced if doc_scheme[d] == s) for s in schemes}
    scheme_informative = {
        s: len([d for d in surfaced_informative if doc_scheme[d] == s]) for s in schemes
    }

    # 2) 프리셋별 측정
    preset_rows = []
    for preset in vocab.presets:
        matched = match_units(
            units,
            bodies=set(preset.get("bodies", [])),
            features=set(preset.get("features", [])),
            strict=False,
        )
        matched_docs: set[str] = set()
        for u in matched:
            matched_docs |= unit_docs(u)
        hit = matched_docs & fraud_docs
        per_scheme = {s: len([d for d in hit if doc_scheme[d] == s]) for s in schemes}
        preset_rows.append(
            {
                "preset_id": preset["preset_id"],
                "matched_units": len(matched),
                "matched_docs": len(matched_docs),
                "fraud_docs_hit": len(hit),
                "fraud_density": round(len(hit) / len(matched_docs), 5) if matched_docs else 0.0,
                "schemes_hit": sorted(s for s, c in per_scheme.items() if c > 0),
                "per_scheme_hits": per_scheme,
            }
        )

    # 3) any-rule 발화 축 — 부정 vs 정상 문서 대비.
    #    표면화(검토 목록 등재)와 구분되는 원시 축이다. 탐지기가 걸기만 하면 카운트하므로
    #    빌더 어휘 밖 룰과 표면에 오르지 못한 발화까지 포함한다.
    row_docs = res.data["document_id"].astype(str)
    fired_labels: set = set()
    for r in res.results:
        fired_labels |= set(r.flagged_indices)
    valid_labels = [lbl for lbl in fired_labels if lbl in row_docs.index]
    fired_docs = set(row_docs.loc[valid_labels]) if valid_labels else set()
    all_docs = set(row_docs)
    normal_docs = all_docs - fraud_docs
    any_rule = {
        "documents_total": len(all_docs),
        "fraud_fired": len(fired_docs & fraud_docs),
        "fraud_rate": round(len(fired_docs & fraud_docs) / len(fraud_docs), 4)
        if fraud_docs
        else 0.0,
        "normal_fired": len(fired_docs & normal_docs),
        "normal_rate": round(len(fired_docs & normal_docs) / len(normal_docs), 4)
        if normal_docs
        else 0.0,
    }

    # 4) 몸통 전체 OR (빌더 상한)
    all_bodies = match_units(units, bodies=set(vocab.body_ids), features=set(), strict=False)
    all_body_docs: set[str] = set()
    for u in all_bodies:
        all_body_docs |= unit_docs(u)
    body_hit = all_body_docs & fraud_docs

    return {
        "dataset": fraud_dir.name,
        "fraud_docs_total": len(fraud_docs),
        "schemes": schemes,
        "surface_coverage": {
            "surfaced_fraud_docs": len(surfaced),
            "rate": round(len(surfaced) / len(fraud_docs), 4) if fraud_docs else 0.0,
            "per_scheme": {s: len(v) for s, v in scheme_surfaced.items()},
            "missed_docs": sorted(fraud_docs - surfaced),
        },
        # 무정보 룰(lift <= 1.0) 발화만으로 오른 문서를 뺀 커버리지. 감사인이 그 룰을 골라도
        # 정상 모집단이 같은 비율로 딸려오므로 검토 목록이 되지 않는다.
        "surface_coverage_informative": {
            "uninformative_rules": uninformative,
            "surfaced_fraud_docs": len(surfaced_informative),
            "rate": round(len(surfaced_informative) / len(fraud_docs), 4) if fraud_docs else 0.0,
            "per_scheme": scheme_informative,
            "schemes_lost": sorted(
                s for s in schemes if len(scheme_surfaced[s]) > 0 and scheme_informative[s] == 0
            ),
            # Why: PHASE2 상보성 측정의 분모. surface_coverage.missed_docs 는 r9 에서 0~2건이라
            #      "VAE 가 PHASE1 미표면을 얼마나 건지나"를 잴 수 없다(2026-07-28). 무정보 룰을
            #      뺀 미표면(30여 건)이 실제로 감사인에게 안 보이는 부정이므로 이쪽을 분모로 쓴다.
            "missed_docs": sorted(fraud_docs - surfaced_informative),
        },
        "rule_discriminating_power": rule_power,
        "fraud_rule_distribution": {
            r: len(v) for r, v in sorted(fraud_rule_hits.items(), key=lambda kv: -len(kv[1]))
        },
        "any_rule_firing": any_rule,
        "presets": preset_rows,
        "all_bodies_or": {
            "matched_docs": len(all_body_docs),
            "fraud_docs_hit": len(body_hit),
            "rate": round(len(body_hit) / len(fraud_docs), 4) if fraud_docs else 0.0,
        },
    }


def main() -> int:
    dirs = [Path(a) for a in sys.argv[1:]]
    if not dirs:
        print("usage: s5_measure_builder_performance.py <fraud_dir> [...]")
        return 2
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    reports = []
    for d in dirs:
        print(f"=== {d.name} ===")
        rep = measure_dataset(d)
        reports.append(rep)
        out = OUT_DIR / f"builder_performance_{d.name}.json"
        out.write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
        if "error" in rep:
            print("ERROR:", rep["error"])
            continue
        sc = rep["surface_coverage"]
        print(
            f"표면 커버리지: {sc['surfaced_fraud_docs']}/{rep['fraud_docs_total']} ({sc['rate']:.1%})"
        )
        si = rep["surface_coverage_informative"]
        print(
            f"  판별력 있는 룰만: {si['surfaced_fraud_docs']}/{rep['fraud_docs_total']}"
            f" ({si['rate']:.1%}) · 무정보 룰 {si['uninformative_rules']}"
            f" · 표면 소멸 scheme {si['schemes_lost']}"
        )
        for row in rep["presets"]:
            print(
                f"프리셋 {row['preset_id']:<28} 적중 {row['fraud_docs_hit']:>3} / 표면 {row['matched_docs']:>6}"
                f" (밀도 {row['fraud_density']:.4f}) schemes={len(row['schemes_hit'])}"
            )
        ar = rep["any_rule_firing"]
        print(
            f"any-rule 발화: 부정 {ar['fraud_fired']} ({ar['fraud_rate']:.1%})"
            f" vs 정상 {ar['normal_fired']} ({ar['normal_rate']:.1%})"
        )
        ab = rep["all_bodies_or"]
        print(
            f"몸통 전체 OR: 적중 {ab['fraud_docs_hit']} / 표면 {ab['matched_docs']} ({ab['rate']:.1%})"
        )
        print(f"-> {out}")

    valid = [r for r in reports if "error" not in r]
    if len(valid) > 1:
        agg = {
            "datasets": [r["dataset"] for r in valid],
            "surface_coverage_rates": [r["surface_coverage"]["rate"] for r in valid],
            "preset_hit_totals": {
                p["preset_id"]: sum(
                    row["fraud_docs_hit"]
                    for r in valid
                    for row in r["presets"]
                    if row["preset_id"] == p["preset_id"]
                )
                for p in valid[0]["presets"]
            },
            "fraud_docs_total": sum(r["fraud_docs_total"] for r in valid),
        }
        (OUT_DIR / "builder_performance_aggregate.json").write_text(
            json.dumps(agg, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print("\n=== seed 합산 ===")
        print(json.dumps(agg, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
