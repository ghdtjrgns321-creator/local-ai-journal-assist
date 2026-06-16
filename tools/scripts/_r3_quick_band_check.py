"""R3 경량 검증 — case 아티팩트 저장(2.12GB write, OOM 원인)을 생략하고
build 결과의 band 분포 + macro_context 발화 건수를 메모리에서 직접 집계.

사용법:
  uv run python tools/scripts/_r3_quick_band_check.py <dataset_dir>
일회성 진단 스크립트 (검증 후 삭제).
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.scripts.measure_phase1_current_p3_2 as M  # noqa: E402


def main() -> int:
    dataset = Path(sys.argv[1])
    # Why: 2.12GB case 아티팩트 write_text 가 OOM 원인 → 저장만 no-op 으로 대체.
    #      build/scoring 로직은 그대로 → band 분포는 실제값.
    M.save_phase1_case_result = lambda result: Path("artifacts/_r3_quick/skipped.json")

    out = ROOT / "artifacts" / "_r3_quick"
    out.mkdir(parents=True, exist_ok=True)
    result, _df = M.run_current_phase1(dataset, output_dir=out)
    cases = result.phase1_case_result.cases

    bands = Counter(c.priority_band for c in cases)
    macro_lifted = 0
    macro_examples: list[tuple[str, str, float]] = []
    for case in cases:
        tb = case.topic_score_breakdown or {}
        for topic_id, bd in tb.items():
            mcs = float(bd.get("macro_context_score", 0.0) or 0.0) if isinstance(bd, dict) else 0.0
            if mcs > 0:
                macro_lifted += 1
                if len(macro_examples) < 10:
                    macro_examples.append((case.case_id, topic_id, mcs))
                break

    print("=== R3 quick band check ===")
    print(f"dataset: {dataset.name}")
    print(f"total cases: {len(cases)}")
    print(f"bands: {dict(bands)}")
    print(f"cases with macro_context_score>0 (R3 ① 발화): {macro_lifted}")
    print("macro examples (case_id, topic, macro_context_score):")
    for cid, tid, mcs in macro_examples:
        print(f"  {cid} {tid} {mcs:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
