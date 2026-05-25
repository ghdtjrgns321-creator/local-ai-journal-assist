"""PHASE1 case priority_score 분포 측정 스크립트.

Stage 0~4 진행 시 동일 기준으로 priority_score 분포를 측정해서
docs/PHASE1_SCORE_DISTRIBUTION_LOG.md 에 누적 기록하기 위한 도구.

DataSynth truth recall 은 보조 기록일 뿐 튜닝 기준으로 사용하지 않는다
(feedback_phase1_truth_recall_guard.md).

Artifact size limit: artifact 전체를 메모리에 로드 (json.load) 한다. 검증된 한계는
약 700MB (fy2023 627MB 통과, ~16GB RAM 환경 가정). 그 이상의 artifact 가 필요하면
streaming parser (ijson) 도입으로 전환할 것.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

BINS: tuple[tuple[str, float], ...] = (
    (">=0.95", 0.95),
    (">=0.90", 0.90),
    (">=0.85", 0.85),
    (">=0.80", 0.80),
    (">=0.75", 0.75),
    (">=0.60", 0.60),
    (">=0.45", 0.45),
    (">=0.00", 0.0),
)

TOP_N_LIMITS = (50, 100, 200, 500, 1000)


def _load_cases(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    cases = payload.get("cases", [])
    if not isinstance(cases, list):
        raise ValueError(f"cases must be a list, got {type(cases).__name__}")
    return cases


def _bin_counts(scores: Iterable[float]) -> dict[str, int]:
    sorted_scores = sorted(scores, reverse=True)
    counts: dict[str, int] = {}
    for label, threshold in BINS:
        counts[label] = sum(1 for s in sorted_scores if s >= threshold)
    return counts


def _top_n_cutoffs(scores: Iterable[float]) -> dict[str, float]:
    sorted_scores = sorted(scores, reverse=True)
    cutoffs: dict[str, float] = {}
    for n in TOP_N_LIMITS:
        if len(sorted_scores) >= n:
            cutoffs[f"Top {n} cutoff"] = sorted_scores[n - 1]
        else:
            cutoffs[f"Top {n} cutoff"] = float("nan")
    return cutoffs


def _facet_count_above(
    cases: list[dict[str, Any]],
    *,
    threshold: float,
    field: str,
    is_list: bool = False,
    nested_topic_breakdown: bool = False,
) -> Counter:
    """Count cases above threshold faceted by `field`.

    - is_list=True: field is a list, expand each item.
    - nested_topic_breakdown=True: field comes from topic_score_breakdown[topic][field].
    """

    counter: Counter = Counter()
    for case in cases:
        score = float(case.get("priority_score", 0.0) or 0.0)
        if score < threshold:
            continue
        if nested_topic_breakdown:
            breakdowns = case.get("topic_score_breakdown") or {}
            seen: set[str] = set()
            for topic_id, bd in breakdowns.items():
                if not isinstance(bd, dict):
                    continue
                for pid in bd.get(field, ()) or ():
                    key = f"{topic_id}:{pid}"
                    if key in seen:
                        continue
                    seen.add(key)
                    counter[key] += 1
            if not seen:
                counter["<none>"] += 1
            continue
        value = case.get(field)
        if value is None:
            counter["<none>"] += 1
        elif is_list:
            items = list(value) if isinstance(value, (list, tuple)) else []
            if not items:
                counter["<none>"] += 1
            for item in items:
                counter[str(item)] += 1
        else:
            counter[str(value)] += 1
    return counter


def _band_distribution(cases: list[dict[str, Any]]) -> Counter:
    counter: Counter = Counter()
    for case in cases:
        counter[str(case.get("priority_band") or "<unset>")] += 1
    return counter


def _index_by_case_id(cases: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(c.get("case_id")): c for c in cases if c.get("case_id")}


def _movement_table(
    baseline_cases: list[dict[str, Any]],
    current_cases: list[dict[str, Any]],
    *,
    threshold: float = 0.75,
) -> dict[str, Any]:
    """0.75+ 검토대상 그룹의 이동을 추적."""

    baseline_index = _index_by_case_id(baseline_cases)
    current_index = _index_by_case_id(current_cases)
    moves: Counter = Counter()
    dropped_below_threshold: list[dict[str, Any]] = []
    promoted_to_critical: list[dict[str, Any]] = []
    for case_id, base in baseline_index.items():
        base_score = float(base.get("priority_score", 0.0) or 0.0)
        if base_score < threshold:
            continue
        new = current_index.get(case_id)
        if new is None:
            moves["disappeared"] += 1
            continue
        new_score = float(new.get("priority_score", 0.0) or 0.0)
        if new_score < threshold:
            moves["dropped_below_threshold"] += 1
            if len(dropped_below_threshold) < 25:
                dropped_below_threshold.append(
                    {
                        "case_id": case_id,
                        "base_score": base_score,
                        "new_score": new_score,
                        "primary_topic": base.get("primary_topic"),
                        "reasons": base.get("priority_adjustment_reasons", [])[:5],
                    }
                )
            continue
        if base_score < 0.90 <= new_score:
            moves["promoted_to_critical"] += 1
            if len(promoted_to_critical) < 25:
                promoted_to_critical.append(
                    {
                        "case_id": case_id,
                        "base_score": base_score,
                        "new_score": new_score,
                        "primary_topic": new.get("primary_topic"),
                        "reasons": new.get("priority_adjustment_reasons", [])[:5],
                    }
                )
        elif new_score > base_score:
            moves["raised_within_review"] += 1
        elif new_score < base_score:
            moves["lowered_within_review"] += 1
        else:
            moves["unchanged"] += 1
    new_above_threshold = sum(
        1
        for cid, new in current_index.items()
        if cid not in baseline_index and float(new.get("priority_score", 0.0) or 0.0) >= threshold
    )
    moves["newly_added_above_threshold"] = new_above_threshold
    return {
        "moves": dict(moves),
        "dropped_below_threshold_sample": dropped_below_threshold,
        "promoted_to_critical_sample": promoted_to_critical,
    }


def _format_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"## Measurement — {report['stage_label']}")
    lines.append("")
    lines.append(f"- artifact: `{report['artifact']}`")
    lines.append(f"- total cases: {report['total_cases']}")
    if report.get("baseline_artifact"):
        lines.append(f"- baseline: `{report['baseline_artifact']}`")
    lines.append("")
    lines.append("### Distribution (누적 카운트, `>= threshold`)")
    lines.append("")
    lines.append("각 Bin 은 해당 임계값 이상의 케이스 수 (`>=0.85` 는 `>=0.90` 을 포함).")
    lines.append("")
    lines.append("| Bin       | Count |")
    lines.append("|-----------|-------|")
    for label, count in report["bin_counts"].items():
        lines.append(f"| {label:<9} | {count:>5} |")
    lines.append("")
    lines.append("### Top N cutoffs")
    lines.append("")
    lines.append("| Rank        | priority_score |")
    lines.append("|-------------|----------------|")
    for label, value in report["top_n_cutoffs"].items():
        value_str = "—" if value != value else f"{value:.4f}"  # NaN check
        lines.append(f"| {label:<11} | {value_str:>14} |")
    lines.append("")
    lines.append("### priority_band (current artifact thresholds)")
    lines.append("")
    lines.append("| Band   | Count |")
    lines.append("|--------|-------|")
    for band, count in sorted(report["band_distribution"].items()):
        lines.append(f"| {band:<6} | {count:>5} |")
    lines.append("")
    lines.append("### 0.90+ by primary_topic")
    lines.append("")
    if report["topic_above_090"]:
        lines.append("| Topic                | Count |")
        lines.append("|----------------------|-------|")
        for key, count in report["topic_above_090"].most_common():
            lines.append(f"| {key:<20} | {count:>5} |")
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("### 0.90+ by priority_adjustment_reasons (top 20)")
    lines.append("")
    if report["reasons_above_090"]:
        lines.append("| Reason                                          | Count |")
        lines.append("|-------------------------------------------------|-------|")
        for key, count in report["reasons_above_090"].most_common(20):
            lines.append(f"| {key[:48]:<48} | {count:>5} |")
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("### 0.90+ by combo_policy_ids (top 20)")
    lines.append("")
    if report["combo_above_090"]:
        lines.append("| Combo policy                                    | Count |")
        lines.append("|-------------------------------------------------|-------|")
        for key, count in report["combo_above_090"].most_common(20):
            lines.append(f"| {key[:48]:<48} | {count:>5} |")
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("### 0.75+ by primary_topic (검토대상)")
    lines.append("")
    if report["topic_above_075"]:
        lines.append("| Topic                | Count |")
        lines.append("|----------------------|-------|")
        for key, count in report["topic_above_075"].most_common():
            lines.append(f"| {key:<20} | {count:>5} |")
    lines.append("")
    if report.get("movement"):
        lines.append("### Movement vs baseline (threshold 0.75)")
        lines.append("")
        lines.append("| Move                          | Count |")
        lines.append("|-------------------------------|-------|")
        for key, count in report["movement"]["moves"].items():
            lines.append(f"| {key:<29} | {count:>5} |")
        lines.append("")
        if report["movement"]["dropped_below_threshold_sample"]:
            lines.append("#### Dropped below 0.75 sample (up to 25)")
            lines.append("")
            lines.append("| case_id | base | new | topic | reasons |")
            lines.append("|---------|------|-----|-------|---------|")
            for row in report["movement"]["dropped_below_threshold_sample"]:
                reasons = ", ".join(row["reasons"]) if row["reasons"] else ""
                lines.append(
                    f"| {row['case_id']} | {row['base_score']:.3f} "
                    f"| {row['new_score']:.3f} | {row['primary_topic']} | {reasons[:40]} |"
                )
            lines.append("")
        if report["movement"]["promoted_to_critical_sample"]:
            lines.append("#### Promoted to 0.90+ sample (up to 25)")
            lines.append("")
            lines.append("| case_id | base | new | topic | reasons |")
            lines.append("|---------|------|-----|-------|---------|")
            for row in report["movement"]["promoted_to_critical_sample"]:
                reasons = ", ".join(row["reasons"]) if row["reasons"] else ""
                lines.append(
                    f"| {row['case_id']} | {row['base_score']:.3f} "
                    f"| {row['new_score']:.3f} | {row['primary_topic']} | {reasons[:40]} |"
                )
            lines.append("")
    return "\n".join(lines)


def _measure(
    artifact: Path,
    *,
    stage_label: str,
    baseline: Path | None = None,
) -> dict[str, Any]:
    cases = _load_cases(artifact)
    scores = [float(c.get("priority_score", 0.0) or 0.0) for c in cases]
    report: dict[str, Any] = {
        "stage_label": stage_label,
        "artifact": str(artifact),
        "total_cases": len(cases),
        "bin_counts": _bin_counts(scores),
        "top_n_cutoffs": _top_n_cutoffs(scores),
        "band_distribution": _band_distribution(cases),
        "topic_above_090": _facet_count_above(cases, threshold=0.90, field="primary_topic"),
        "reasons_above_090": _facet_count_above(
            cases, threshold=0.90, field="priority_adjustment_reasons", is_list=True
        ),
        "combo_above_090": _facet_count_above(
            cases,
            threshold=0.90,
            field="combo_policy_ids",
            nested_topic_breakdown=True,
        ),
        "topic_above_075": _facet_count_above(cases, threshold=0.75, field="primary_topic"),
    }
    if baseline is not None and baseline.exists():
        baseline_cases = _load_cases(baseline)
        report["baseline_artifact"] = str(baseline)
        report["movement"] = _movement_table(baseline_cases, cases)
    return report


def main(argv: list[str] | None = None) -> int:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--stage-label", required=True)
    parser.add_argument("--baseline", type=Path, default=None)
    parser.add_argument("--out-md", type=Path, default=None)
    parser.add_argument("--out-json", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.artifact.exists():
        print(f"error: artifact not found: {args.artifact}", file=sys.stderr)
        return 2
    report = _measure(args.artifact, stage_label=args.stage_label, baseline=args.baseline)
    md = _format_markdown(report)
    if args.out_md:
        args.out_md.parent.mkdir(parents=True, exist_ok=True)
        args.out_md.write_text(md + "\n", encoding="utf-8")
    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        serializable = {
            key: dict(value) if isinstance(value, Counter) else value
            for key, value in report.items()
        }
        args.out_json.write_text(
            json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
