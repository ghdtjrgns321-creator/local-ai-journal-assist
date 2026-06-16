"""truth unit별 PHASE1 priority_band/rank 분해.

Why: 리콜 100%(detector score>0)만으로는 "감사인이 그 위반을 보게 되는가"를 알 수 없다.
     truth가 매칭된 case의 priority_band(high/medium/low)와 전역 rank를 분해해
     "위반이 우선순위로 올라오는가"를 정량화한다 (PHASE1_OPEN_ISSUES 우선순위 1의 위반측 보완).

입력: measure_phase1_current_p3_2.py 산출 디렉토리
  - truth_unit_measurement.csv (matched_case_rank 포함)
  - direct_phase1_checkpoint.json → case artifact 경로
출력: 같은 디렉토리에 truth_priority_band.json / truth_priority_band.md
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

TOP_NS = (100, 500, 1000)


def _ranked_case_bands(artifact_path: Path) -> list[str]:
    """measure 스크립트 _ranked_cases와 동일 정렬로 rank→priority_band 목록 생성."""
    with artifact_path.open(encoding="utf-8") as fp:
        artifact = json.load(fp)
    cases = artifact.get("cases", [])
    ranked = sorted(
        cases,
        key=lambda c: (
            -float(c.get("triage_rank_score") or c.get("priority_score") or 0.0),
            str(c.get("case_id", "")),
        ),
    )
    return [str(c.get("priority_band", "low") or "low") for c in ranked]


def analyze(measure_dir: Path) -> dict:
    measurement = pd.read_csv(measure_dir / "truth_unit_measurement.csv")
    checkpoint = json.loads(
        (measure_dir / "direct_phase1_checkpoint.json").read_text(encoding="utf-8")
    )
    artifact_path = Path(checkpoint["stages"]["phase1_case_builder"]["artifact_path"])
    bands = _ranked_case_bands(artifact_path)

    def band_of(rank: object) -> str:
        if pd.isna(rank):
            return "unmatched"
        index = int(rank) - 1
        return bands[index] if 0 <= index < len(bands) else "unmatched"

    measurement["case_band"] = measurement["matched_case_rank"].map(band_of)
    standard = measurement[measurement["case_kind"].eq("standard")]
    boundary = measurement[measurement["case_kind"].eq("boundary_control")]

    def _dist(frame: pd.DataFrame) -> dict:
        counts = frame["case_band"].value_counts().to_dict()
        return {band: int(counts.get(band, 0)) for band in ("high", "medium", "low", "unmatched")}

    rows = []
    for rule_id, grp in standard.groupby("rule_id"):
        ranks = grp["matched_case_rank"].dropna()
        rows.append(
            {
                "rule_id": rule_id,
                "standard_units": int(len(grp)),
                **{f"band_{k}": v for k, v in _dist(grp).items()},
                "best_rank": int(ranks.min()) if len(ranks) else None,
                "median_rank": int(ranks.median()) if len(ranks) else None,
                "worst_rank": int(ranks.max()) if len(ranks) else None,
            }
        )
    per_rule = pd.DataFrame(rows).sort_values("rule_id")

    std_ranks = standard["matched_case_rank"].dropna()
    summary = {
        "artifact_path": str(artifact_path),
        "total_cases": len(bands),
        "standard_total": int(len(standard)),
        "standard_band_distribution": _dist(standard),
        "standard_top_n_truth": {f"top{n}": int((std_ranks <= n).sum()) for n in TOP_NS},
        "boundary_control_total": int(len(boundary)),
        "boundary_control_matched_cases": int(boundary["matched_case_rank"].notna().sum()),
        "boundary_control_band_distribution": _dist(boundary),
    }

    (measure_dir / "truth_priority_band.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    md = (
        "# truth priority band 분해\n\n```\n"
        + json.dumps(summary, ensure_ascii=False, indent=2)
        + "\n```\n\n"
        + per_rule.to_markdown(index=False)
        + "\n"
    )
    (measure_dir / "truth_priority_band.md").write_text(md, encoding="utf-8")
    per_rule.to_csv(measure_dir / "truth_priority_band_per_rule.csv", index=False)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("measure_dir", type=Path)
    args = parser.parse_args()
    summary = analyze(args.measure_dir.resolve())
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
