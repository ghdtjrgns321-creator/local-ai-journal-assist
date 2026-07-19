"""A안 셋째 다리 확장 과탐 측정 — 정상 데이터 phase1 case HIGH 비율.

용도: HIGH 조합1·2 셋째 다리 확장(A안) 전/후 동일 정상 데이터로 phase1 case 를
빌드하고 priority_band=high 비율을 측정한다. HARD 가드: HIGH <= 2.0%.

DataSynth truth recall 은 사용하지 않는다(feedback_phase1_truth_recall_guard).
band 은 case_tier 직접 매핑(_TIER_TO_BAND)이므로 high == case_tier HIGH.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import pandas as pd


def main(argv: list[str] | None = None) -> int:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0, help="행 제한(0=전체)")
    parser.add_argument("--label", default="run")
    args = parser.parse_args(argv)

    # Why: 측정은 case artifact 디스크 저장이 불필요하고, 대용량에서 model_dump_json
    #      직렬화가 OOM 을 낸다. 저장을 no-op 으로 패치해 in-memory case 만 얻는다.
    #      (_build_phase1_case_artifact 가 함수 내부 import 로 모듈 속성을 재참조하므로
    #       run() 호출 전 모듈 속성 패치가 적용된다.)
    import src.detection.phase1_case_builder as _pcb
    from src.pipeline import AuditPipeline

    _pcb.save_phase1_case_result = lambda result: Path("artifacts/_measure_no_save.json")

    # 전체 ingest(read→header→map→cast)를 거쳐야 L1 dtype 검증을 통과한다.
    # limit 은 head 슬라이스를 임시 CSV 로 만들어 run() 에 넘긴다.
    run_path: Path = args.csv
    tmp_path: Path | None = None
    if args.limit > 0:
        df_head = pd.read_csv(args.csv, low_memory=False).head(args.limit)
        tmp_path = args.csv.parent / f"_tmp_a_an_{args.limit}_journal_entries.csv"
        df_head.to_csv(tmp_path, index=False)
        run_path = tmp_path
    rows = sum(1 for _ in run_path.open(encoding="utf-8")) - 1

    pipeline = AuditPipeline(skip_db=True)
    try:
        result = pipeline.run(run_path)
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink()
    # Why: pipeline 내부 _build_phase1_case_artifact 는 케이스 빌드 후 디스크 저장
    #      (model_dump_json)을 시도하는데 대용량에서 OOM 가능. 측정은 저장이 불필요하므로
    #      detection 결과(result.results/result.data)로 케이스를 in-memory 로만 재빌드한다.
    case_result = result.phase1_case_result
    if case_result is None:
        from src.detection.phase1_case_builder import build_phase1_case_result

        case_result = build_phase1_case_result(
            result.data,
            result.results,
            company_id="measure",
            batch_id=result.batch_id,
            dataset_id=result.batch_id,
        )

    cases = case_result.cases
    total = len(cases)
    band = Counter(str(getattr(c, "priority_band", "") or "<unset>") for c in cases)
    # HIGH case 에서 발화한 combo policy id 분포 (셋째 다리 확장 효과 추적)
    combo: Counter = Counter()
    for c in cases:
        if str(getattr(c, "priority_band", "")) != "high":
            continue
        breakdowns = getattr(c, "topic_score_breakdown", None) or {}
        seen: set[str] = set()
        if isinstance(breakdowns, dict):
            for topic_id, bd in breakdowns.items():
                ids = []
                if isinstance(bd, dict):
                    ids = bd.get("combo_policy_ids", []) or []
                else:
                    ids = getattr(bd, "combo_policy_ids", []) or []
                for pid in ids:
                    key = f"{topic_id}:{pid}"
                    if key not in seen:
                        seen.add(key)
                        combo[key] += 1

    # 조합1(가공전표) HIGH 케이스의 2차정황 다리 분해 — 어떤 다리를 빼면 몇 건이 빠지나.
    secondary_legs = {
        "L4-04",
        "L3-03",
        "L3-04",
        "L3-10",
        "L1-05",
        "L1-09",
        "L3-11",
        "L2-03",
        "L2-03a",
        "L2-03b",
        "L2-03c",
        "L2-03d",
    }
    leg_freq: Counter = Counter()  # 각 다리가 등장한 fictitious-HIGH 케이스 수
    leg_combo: Counter = Counter()  # 케이스별 present 다리 집합(어느 조합으로 HIGH 됐나)
    fict_high = 0
    for c in cases:
        if str(getattr(c, "priority_band", "")) != "high":
            continue
        breakdowns = getattr(c, "topic_score_breakdown", None) or {}
        rev = breakdowns.get("revenue_statistical") if isinstance(breakdowns, dict) else None
        rev_ids = []
        if isinstance(rev, dict):
            rev_ids = rev.get("combo_policy_ids", []) or []
        elif rev is not None:
            rev_ids = getattr(rev, "combo_policy_ids", []) or []
        if not any("manual_adjustment + secondary_red_flag" in str(r) for r in rev_ids):
            continue
        fict_high += 1
        rule_ids = {str(getattr(h, "rule_id", "")) for h in (getattr(c, "raw_rule_hits", []) or [])}
        present = rule_ids & secondary_legs
        present_norm = {("L2-03" if x.startswith("L2-03") else x) for x in present}
        for leg in present_norm:
            leg_freq[leg] += 1
        leg_combo["+".join(sorted(present_norm))] += 1

    high = band.get("high", 0)
    ratio = (high / total * 100.0) if total else 0.0

    print(f"=== A안 과탐 측정 [{args.label}] ===")
    print(f"rows={rows}  cases={total}")
    print(f"band: {dict(band)}")
    print(f"HIGH={high}  HIGH비율={ratio:.3f}%  (HARD 가드 <= 2.0%)")
    print(f"가드: {'PASS' if ratio <= 2.0 else 'FAIL'}")
    print("HIGH combo policy 분포(top):")
    for key, cnt in combo.most_common(15):
        print(f"  {key}: {cnt}")
    print(f"\n조합1(가공전표) fictitious-HIGH 케이스={fict_high}")
    print("  2차정황 다리별 등장 케이스 수(다리 빼면 영향, 중복가능):")
    for leg, cnt in leg_freq.most_common():
        print(f"    {leg}: {cnt}")
    print("  2차정황 다리 조합별 케이스 수(이 조합으로 HIGH 됨):")
    for key, cnt in leg_combo.most_common(20):
        print(f"    [{key}]: {cnt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
