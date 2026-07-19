"""S4 판정 — 조합 빌더 정확성 단위시험 (SoT: PHASE1_COMBO_BUILDER_SPEC §7).

S2 단위 데이터에 실제 파이프라인을 돌린 뒤 빌더를 3면으로 검증한다. exit 0 = HARD 축 전수 PASS.

- V0a (HARD): 엔진 evidence(unit.evidence_rows, 어휘 룰)가 독립 오라클
  (DetectionResult.details/review 채널 발화)의 부분집합인가 — 없는 발화를 만들어내지 않는가.
- V0b (실측 기록, FAIL 아님): 오라클 발화의 표면 커버리지 — 룰별 details 발화 문서 중
  어느 unit evidence 에도 안 실린 유실 문서 수. flow 승격 게이트(L2-05 context_score 등)
  정책의 결과라 S4(빌더 조회 정확성) 범위 밖 — 수치만 남겨 후속 결정 재료로 쓴다.
- V1/V2 (HARD): 결합 의미론 전수 — 몸통10×특징10 + 단독 20 = 120셀을 기본/엄격 모드로,
  unit 발화집합 입력 + 독립 재구현(_expected_match)과 대조. 입력은 공유하되 로직이 독립이라
  의미론 검증으로 성립하고, 입력 자체의 정확성은 V0a/V0b 가 별도 담당한다.
- V3 (HARD): 프리셋 4종 + build_combo_builder_result 뷰 정합(matched 수·rows·top_n 절단).
- V4 (HARD): 정답지 하한 — 어휘 룰 단독 선택 시 units 내 표적 문서는 반드시 일치.
  units 밖 표적 문서는 standalone 게이트 정책의 결과이므로 gate_excluded 로 기록만.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATASET = ROOT / "data/journal/unit/s2_unit_firing_20260717"
OUT = ROOT / "reports/s4_combo_builder/adjudication.json"


def _unit_documents(unit) -> set[str]:
    if unit.unit_type == "flow":
        return {str(d) for d in (getattr(unit, "member_document_ids", []) or [])}
    return {str(unit.unit_id)}


def _expected_match(fired: set[str], bodies: set[str], features: set[str], strict: bool) -> bool:
    """빌더 결합 의미론의 독립 재구현(엔진 미호출) — 스펙 §3."""
    if not bodies and not features:
        return False
    if strict:
        return (bodies | features) <= fired
    body_ok = not bodies or bool(bodies & fired)
    feature_ok = not features or bool(features & fired)
    return body_ok and feature_ok


def main() -> int:
    from src.export.phase1_case_view import resolve_phase1_case_result
    from src.export.phase1_combo_builder import (
        build_combo_builder_result,
        load_combo_vocabulary,
        match_units,
    )
    from src.pipeline import AuditPipeline

    vocab = load_combo_vocabulary()
    body_ids = sorted(vocab.body_ids)
    feature_ids = sorted(vocab.feature_ids)
    vocab_all = vocab.body_ids | vocab.feature_ids

    expected_csv = pd.read_csv(DATASET / "labels" / "s2_expected.csv", dtype=str)
    res = AuditPipeline(skip_db=True).run(str(DATASET / "journal_entries.csv"))
    doc_series = res.data["document_id"].astype(str)

    # ── 오라클: 문서별 발화 룰 집합 (s2_adjudicate_unit_firing 과 동일한 양 채널 독취)
    oracle: dict[str, set[str]] = {}

    def _collect(frame):
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            return
        for rule_id in frame.columns:
            scores = pd.to_numeric(frame[rule_id], errors="coerce").fillna(0.0)
            for doc in doc_series.reindex(scores[scores > 0].index).dropna():
                oracle.setdefault(str(doc), set()).add(str(rule_id))

    for result in res.results:
        _collect(getattr(result, "details", None))
        _collect((getattr(result, "metadata", None) or {}).get("review_score_series"))

    phase1 = resolve_phase1_case_result(res)
    if phase1 is None or not phase1.units:
        print("FAIL: phase1 units 없음 — 빌더 검증 불가")
        return 1
    units = list(phase1.units)

    failures: list[dict] = []

    # ── V0: unit별 발화집합 채널 교차검증 (어휘 20룰 교집합 기준)
    engine_fired: dict[str, set[str]] = {}
    oracle_fired: dict[str, set[str]] = {}
    # V0a (HARD): 엔진이 오라클에 없는 발화를 만들면 fabrication.
    # V0b (기록): 오라클 발화가 표면(unit evidence)에 안 실린 유실 — 룰별 문서 수 실측.
    v0a_fabrication = []
    for unit in units:
        uid = str(unit.unit_id)
        eng = {ref.rule_id for ref in unit.evidence_rows} & vocab_all
        ora = set()
        for doc in _unit_documents(unit):
            ora |= oracle.get(doc, set())
        ora &= vocab_all
        engine_fired[uid] = eng
        oracle_fired[uid] = ora
        if eng - ora:
            v0a_fabrication.append({"unit_id": uid, "engine_only": sorted(eng - ora)})
    if v0a_fabrication:
        failures.append({"axis": "V0a", "fabrications": v0a_fabrication})

    surfaced_docs: dict[str, set[str]] = {}  # rule_id -> unit evidence 로 커버된 문서
    for unit in units:
        docs = _unit_documents(unit)
        for rule_id in engine_fired[str(unit.unit_id)]:
            surfaced_docs.setdefault(rule_id, set()).update(docs)
    oracle_docs: dict[str, set[str]] = {}
    for doc, fired in oracle.items():
        for rule_id in fired & vocab_all:
            oracle_docs.setdefault(rule_id, set()).add(doc)
    v0b_coverage = []
    for rule_id in sorted(vocab_all):
        fired_docs = oracle_docs.get(rule_id, set())
        lost = fired_docs - surfaced_docs.get(rule_id, set())
        v0b_coverage.append(
            {
                "rule_id": rule_id,
                "oracle_fired_docs": len(fired_docs),
                "surfaced_docs": len(fired_docs) - len(lost),
                "lost_docs": len(lost),
                "lost_samples": sorted(lost)[:5],
            }
        )

    # ── V1/V2: 조합 셀 전수 — 몸통10×특징10 + 몸통만10 + 특징만10 = 120셀 × 2모드
    cells: list[tuple[set[str], set[str]]] = []
    cells += [({b}, {f}) for b in body_ids for f in feature_ids]
    cells += [({b}, set()) for b in body_ids]
    cells += [(set(), {f}) for f in feature_ids]

    cell_stats = {"basic": 0, "strict": 0}
    for strict in (False, True):
        tag = "strict" if strict else "basic"
        for bodies, features in cells:
            got = {
                str(u.unit_id)
                for u in match_units(units, bodies=bodies, features=features, strict=strict)
            }
            want = {
                uid
                for uid, fired in engine_fired.items()
                if _expected_match(fired, bodies, features, strict)
            }
            if got == want:
                cell_stats[tag] += 1
            else:
                failures.append(
                    {
                        "axis": "V2" if strict else "V1",
                        "bodies": sorted(bodies),
                        "features": sorted(features),
                        "engine_only": sorted(got - want),
                        "oracle_only": sorted(want - got),
                    }
                )

    # ── 빈 선택 계약: 양쪽 빈 선택 = 빈 결과
    if match_units(units, bodies=set(), features=set(), strict=False) != []:
        failures.append(
            {"axis": "V1", "cell": "empty-selection", "detail": "빈 선택이 빈 결과가 아님"}
        )

    # ── V3: 프리셋 4종 (기본 모드) + build_combo_builder_result 정합 + top_n 절단
    preset_rows = []
    for preset in vocab.presets:
        bodies = set(preset.get("bodies", []))
        features = set(preset.get("features", []))
        got_units = match_units(units, bodies=bodies, features=features, strict=False)
        got = {str(u.unit_id) for u in got_units}
        want = {
            uid
            for uid, fired in engine_fired.items()
            if _expected_match(fired, bodies, features, False)
        }
        view = build_combo_builder_result(res, bodies=bodies, features=features, top_n=5)
        view_ok = (
            view["available"] is True
            and view["matched"] == len(got_units)
            and len(view["rows"]) == min(5, len(got_units))
            and [r["unit_id"] for r in view["rows"]] == [str(u.unit_id) for u in got_units[:5]]
        )
        verdict = "PASS" if (got == want and view_ok) else "FAIL"
        preset_rows.append(
            {
                "preset_id": preset["preset_id"],
                "matched": len(got_units),
                "matched_unit_ids": sorted(got),
                "view_consistent": view_ok,
                "verdict": verdict,
            }
        )
        if verdict == "FAIL":
            failures.append(
                {
                    "axis": "V3",
                    "preset_id": preset["preset_id"],
                    "engine_only": sorted(got - want),
                    "oracle_only": sorted(want - got),
                    "view_consistent": view_ok,
                }
            )

    # ── V4: 정답지 하한 — 어휘 룰 단독 선택 시 units 내 표적 문서는 반드시 일치
    unit_docs_all: dict[str, str] = {}  # document_id -> unit_id
    for unit in units:
        for doc in _unit_documents(unit):
            unit_docs_all[doc] = str(unit.unit_id)

    v4_rows = []
    for rule_id, grp in expected_csv.groupby("rule_id"):
        if rule_id not in vocab_all:
            continue
        is_body = rule_id in vocab.body_ids
        bodies = {rule_id} if is_body else set()
        features = set() if is_body else {rule_id}
        matched_docs: set[str] = set()
        for u in match_units(units, bodies=bodies, features=features, strict=False):
            matched_docs |= _unit_documents(u)
        want_docs = set(grp["document_id"])
        in_units = {d for d in want_docs if d in unit_docs_all}
        gate_excluded = sorted(want_docs - in_units)
        missed = sorted(in_units - matched_docs)
        v4_rows.append(
            {
                "rule_id": rule_id,
                "group": "body" if is_body else "feature",
                "expected_docs": sorted(want_docs),
                "gate_excluded_docs": gate_excluded,
                "missed_in_units": missed,
                "verdict": "PASS" if not missed else "FAIL",
            }
        )
        if missed:
            failures.append({"axis": "V4", "rule_id": rule_id, "missed_in_units": missed})

    report = {
        "dataset": str(DATASET),
        "units_total": len(units),
        "v0a_fabrications": len(v0a_fabrication),
        "v0b_surface_coverage": v0b_coverage,
        "v1_cells_pass": f"{cell_stats['basic']}/{len(cells)}",
        "v2_cells_pass": f"{cell_stats['strict']}/{len(cells)}",
        "v3_presets": preset_rows,
        "v4_rules": v4_rows,
        "failures": failures,
        "verdict": "PASS" if not failures else "FAIL",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"V0a fabrication 검사: {len(units)} units, 위반 {len(v0a_fabrication)}")
    lost_rules = [c for c in v0b_coverage if c["lost_docs"]]
    for c in lost_rules:
        print(
            f"V0b 표면 유실: {c['rule_id']} — 발화 {c['oracle_fired_docs']} 중 "
            f"{c['lost_docs']} 유실 (기록만, FAIL 아님)"
        )
    print(f"V1 기본 모드: {cell_stats['basic']}/{len(cells)} 셀 일치")
    print(f"V2 엄격 모드: {cell_stats['strict']}/{len(cells)} 셀 일치")
    for row in preset_rows:
        print(f"V3 {row['preset_id']:<28} matched={row['matched']:>3} {row['verdict']}")
    n4 = sum(1 for r in v4_rows if r["verdict"] == "PASS")
    gate_total = sum(len(r["gate_excluded_docs"]) for r in v4_rows)
    print(
        f"V4 정답지 하한: {n4}/{len(v4_rows)} 룰 PASS (gate_excluded 문서 {gate_total}건 — 실측 기록)"
    )
    print(f"\nS4 판정: {report['verdict']} -> {OUT}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
