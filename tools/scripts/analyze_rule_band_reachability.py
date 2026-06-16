"""39룰 전수 priority band 도달성 분석.

Why: truth가 low에 깔린 룰이 "이번 fixture에서 약했던 것"인지 "구조적으로 high/medium에
     도달할 수 없는 것(설계 결함 후보)"인지 구분한다. 전체 case에서 룰별로:
     - 단독(case에 그 룰만 존재) 도달 상한
     - 결합(다른 룰과 동반) 도달 상한
     을 실측하면, 단독·결합 모두 medium 임계(0.75) 미달인 룰이 구조적 도달 불가 후보다.

입력: measure_phase1_current_p3_2.py 산출 디렉토리 (checkpoint → case artifact)
출력: 디렉토리에 rule_band_reachability.{json,csv}
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

MEDIUM = 0.75
HIGH = 0.90


def analyze(measure_dir: Path) -> pd.DataFrame:
    checkpoint = json.loads(
        (measure_dir / "direct_phase1_checkpoint.json").read_text(encoding="utf-8")
    )
    artifact_path = Path(checkpoint["stages"]["phase1_case_builder"]["artifact_path"])
    with artifact_path.open(encoding="utf-8") as fp:
        artifact = json.load(fp)

    stats: dict[str, dict] = defaultdict(
        lambda: {
            "cases": 0,
            "high": 0,
            "medium": 0,
            "solo_cases": 0,
            "solo_max": 0.0,
            "combo_max": 0.0,
        }
    )
    for case in artifact.get("cases", []):
        score = float(case.get("priority_score") or 0.0)
        band = str(case.get("priority_band", "low") or "low")
        rules = {
            str(hit.get("rule_id"))
            for hit in case.get("raw_rule_hits", []) or []
            if hit.get("rule_id")
        }
        solo = len(rules) == 1
        for rule in rules:
            entry = stats[rule]
            entry["cases"] += 1
            if band == "high":
                entry["high"] += 1
            elif band == "medium":
                entry["medium"] += 1
            if solo:
                entry["solo_cases"] += 1
                entry["solo_max"] = max(entry["solo_max"], score)
            else:
                entry["combo_max"] = max(entry["combo_max"], score)

    rows = []
    for rule, entry in sorted(stats.items()):
        solo_reach = (
            "high"
            if entry["solo_max"] >= HIGH
            else "medium"
            if entry["solo_max"] >= MEDIUM
            else "low"
        )
        combo_reach = (
            "high"
            if entry["combo_max"] >= HIGH
            else "medium"
            if entry["combo_max"] >= MEDIUM
            else "low"
        )
        rows.append(
            {
                "rule_id": rule,
                "cases": entry["cases"],
                "case_high": entry["high"],
                "case_medium": entry["medium"],
                "solo_cases": entry["solo_cases"],
                "solo_max_priority": round(entry["solo_max"], 4),
                "solo_reach": solo_reach,
                "combo_max_priority": round(entry["combo_max"], 4),
                "combo_reach": combo_reach,
            }
        )
    df = pd.DataFrame(rows)
    df.to_csv(measure_dir / "rule_band_reachability.csv", index=False)
    summary = {
        "artifact_path": str(artifact_path),
        "rules_measured": int(len(df)),
        "rules_combo_unreachable": sorted(
            df.loc[
                df["combo_reach"].eq("low") & df["case_high"].eq(0) & df["case_medium"].eq(0),
                "rule_id",
            ]
        ),
        "rules_solo_only_low": sorted(
            df.loc[df["solo_reach"].eq("low") & df["combo_reach"].ne("low"), "rule_id"]
        ),
    }
    (measure_dir / "rule_band_reachability.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return df


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("measure_dir", type=Path)
    args = parser.parse_args()
    df = analyze(args.measure_dir.resolve())
    print(df.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
