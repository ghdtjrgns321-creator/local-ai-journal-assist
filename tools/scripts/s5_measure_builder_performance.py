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
    surfaced: set[str] = set()
    fraud_rule_hits: dict[str, set[str]] = {}  # rule_id -> fraud docs
    for unit in units:
        docs = unit_docs(unit)
        hit_frauds = docs & fraud_docs
        if not hit_frauds:
            continue
        surfaced |= hit_frauds
        for ref in unit.evidence_rows:
            fraud_rule_hits.setdefault(ref.rule_id, set()).update(hit_frauds)

    scheme_surfaced = {s: sorted(d for d in surfaced if doc_scheme[d] == s) for s in schemes}

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

    # 3) 몸통 전체 OR (빌더 상한)
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
        "fraud_rule_distribution": {
            r: len(v) for r, v in sorted(fraud_rule_hits.items(), key=lambda kv: -len(kv[1]))
        },
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
        for row in rep["presets"]:
            print(
                f"프리셋 {row['preset_id']:<28} 적중 {row['fraud_docs_hit']:>3} / 표면 {row['matched_docs']:>6}"
                f" (밀도 {row['fraud_density']:.4f}) schemes={len(row['schemes_hit'])}"
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
