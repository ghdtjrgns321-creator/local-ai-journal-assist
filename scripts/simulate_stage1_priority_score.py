"""Stage 1 적용 효과를 기존 artifact 에 시뮬레이션.

전체 파이프라인 재실행이 부담스러울 때, stage_0 artifact 의 priority_adjustment_reasons
와 topic_scores 를 이용해서 Stage 1 머지 로직 (max(topic, legacy_floor)) 만 적용한
artifact 를 생성한다.

가정:
- artifact 의 priority_adjustment_reasons 에 priority_floors 가 평가한 reason 이 이미
  포함되어 있다 (stage_0 에서 _apply_priority_floors 가 호출되었기 때문).
- topic_scoring 으로 덮이기 직전의 legacy_priority_score 는 priority_adjustment_reasons
  의 reason 으로부터 priority_floors 의 min_priority_score 를 역추론한다.
- macro_reasons 는 priority_adjustment_reasons 에 ``macro_context=`` 접두어로 들어있다.
  Stage 1 의 use_topic_scoring=True 분기에서는 이 reason 을 audit 사유에서도 제외한다.

한계:
- stage_0 artifact 에는 raw_rule_hits.annotation 의 missing_fields 가 저장되지 않아
  multiple_core_required_fields_missing floor 가 stage_0 에서 평가되었는지는
  priority_adjustment_reasons 에서만 확인 가능하다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path("config/phase1_case.yaml")


def load_floor_reason_score(config_path: Path) -> dict[str, float]:
    """config/phase1_case.yaml 의 priority_floors 에서 reason → min_priority_score 매핑 추출.

    config drift 방지를 위해 하드코딩이 아니라 yaml 을 단일 출처로 사용한다.
    같은 reason 이 여러 floor entry 에 있으면 최대값을 채택한다.
    """

    with config_path.open("r", encoding="utf-8") as fh:
        config = yaml.safe_load(fh) or {}
    floors = (config.get("phase1_case") or {}).get("priority_floors") or []
    mapping: dict[str, float] = {}
    for entry in floors:
        if not isinstance(entry, dict):
            continue
        reason = entry.get("reason")
        score = entry.get("min_priority_score")
        if not reason or score is None:
            continue
        try:
            value = float(score)
        except (TypeError, ValueError):
            continue
        existing = mapping.get(reason, 0.0)
        if value > existing:
            mapping[reason] = value
    return mapping


def _legacy_floor_score(reasons: list[str], floor_reason_score: dict[str, float]) -> float:
    """priority_adjustment_reasons 에서 priority_floor 최댓값 역추론."""
    best = 0.0
    for reason in reasons:
        score = floor_reason_score.get(reason, 0.0)
        if score > best:
            best = score
    return best


def _strip_macro_reasons(reasons: list[str]) -> list[str]:
    """use_topic_scoring=True 경로에서 audit 사유에 노출하지 않을 macro_reasons 제거."""
    return [r for r in reasons if not r.startswith("macro_context=")]


def _simulate_case(case: dict[str, Any], floor_reason_score: dict[str, float]) -> dict[str, Any]:
    """한 case 에 Stage 1 머지 + macro_reasons 분기 적용."""
    reasons = list(case.get("priority_adjustment_reasons", []) or [])
    floor_score = _legacy_floor_score(reasons, floor_reason_score)
    topic_max = max(
        (float(v) for v in (case.get("topic_scores") or {}).values()),
        default=float(case.get("priority_score", 0.0) or 0.0),
    )
    new_priority_score = max(topic_max, floor_score)

    new_reasons = _strip_macro_reasons(reasons)
    new_band = (
        "high" if new_priority_score >= 0.90 else "medium" if new_priority_score >= 0.75 else "low"
    )

    new_case = dict(case)
    new_case["priority_score"] = new_priority_score
    new_case["priority_band"] = new_band
    new_case["priority_adjustment_reasons"] = new_reasons
    return new_case


def simulate_artifact(
    artifact_path: Path,
    output_path: Path,
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> dict[str, int]:
    floor_reason_score = load_floor_reason_score(config_path)
    with artifact_path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)

    cases = payload.get("cases", []) or []
    new_cases = [_simulate_case(case, floor_reason_score) for case in cases]
    payload["cases"] = new_cases

    summary = {
        "input_cases": len(cases),
        "ge_095": sum(1 for c in new_cases if c["priority_score"] >= 0.95),
        "ge_090": sum(1 for c in new_cases if c["priority_score"] >= 0.90),
        "ge_085": sum(1 for c in new_cases if c["priority_score"] >= 0.85),
        "ge_080": sum(1 for c in new_cases if c["priority_score"] >= 0.80),
        "ge_075": sum(1 for c in new_cases if c["priority_score"] >= 0.75),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return summary


def main(argv: list[str] | None = None) -> int:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    summary = simulate_artifact(args.artifact, args.output)
    print(f"input: {args.artifact}")
    print(f"output: {args.output}")
    for key, value in summary.items():
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
