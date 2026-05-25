"""Stage 1 artifact 의 0.80~0.89 구간을 Stage 2 critical combo 후보로 분석.

사용자 plan (2026-05-20) 기준 4개 critical combo 후보의 신규 승격 가능 수 + overlap
산출:

- approval_bypass_critical
- period_end_adjustment_critical
- embezzlement_concealment_critical
- fictitious_entry_critical

각 critical 정의는 "기존 high combo + 추가 독립 근거" 패턴.

후보 카운트는 0.80~0.89 구간에서만 계산한다 (이미 0.90 인 케이스는 제외).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# Rule ID 그룹 — Stage 2 critical 평가용
APPROVAL_BYPASS_RULES = {"L1-04", "L1-05", "L1-06", "L1-07"}
HIGH_AMOUNT_RULES = {"L4-03"}
CUTOFF_RULES = {"L3-11", "L1-08"}
MANUAL_CLOSING_RULES = {"L3-04"}
AFTER_HOURS_RULES = {"L3-05", "L3-06"}
MANUAL_ENTRY_RULES = {"L3-02"}
DUPLICATE_RULES = {"L2-02", "L2-03", "L2-03a", "L2-03b", "L2-03c", "L2-03d", "L2-05"}
REVENUE_OUTLIER_RULES = {"L4-01"}
RARE_ACCOUNT_RULES = {"L4-04"}
DESCRIPTION_WEAK_RULES = {"L3-08"}
SENSITIVE_ACCOUNT_RULES = {"L3-10"}
RELATED_PARTY_RULES = {"L3-03", "IC01", "IC02", "IC03"}

# 0.80 < score < 0.90 구간 정의
BAND_LO = 0.80
BAND_HI = 0.90


def _case_rule_ids(case: dict[str, Any]) -> set[str]:
    """case 의 raw_rule_hits 에서 unique rule_id set 추출."""
    hits = case.get("raw_rule_hits") or []
    return {str(h.get("rule_id")) for h in hits if h.get("rule_id")}


def _case_combo_policy_ids(case: dict[str, Any]) -> set[str]:
    """case 의 모든 topic 의 combo_policy_ids + fraud_combo_policy_ids 합집합."""
    ids: set[str] = set()
    breakdowns = case.get("topic_score_breakdown") or {}
    for topic_id, breakdown in breakdowns.items():
        if not isinstance(breakdown, dict):
            continue
        for key in ("combo_policy_ids", "fraud_combo_policy_ids", "floor_policy_ids"):
            for pid in breakdown.get(key) or ():
                ids.add(f"{topic_id}:{pid}")
    return ids


def _approval_bypass_critical(rules: set[str]) -> bool:
    """approval bypass + high_amount 필수 + (cutoff / manual closing / after-hours) 중 1개.

    Why: 사용자 우려 (2026-05-20) — high_amount 없는 approval+timing 결합은 4,000건 검토대상에
    너무 흔해서 즉시검토 인플레이션을 만든다. high_amount (L4-03) 를 hard requirement 로 고정.
    """

    has_bypass = bool(rules & APPROVAL_BYPASS_RULES)
    has_amount = bool(rules & HIGH_AMOUNT_RULES)
    if not (has_bypass and has_amount):
        return False
    has_supporting = bool(rules & (CUTOFF_RULES | MANUAL_CLOSING_RULES | AFTER_HOURS_RULES))
    return has_supporting


def _period_end_adjustment_critical(rules: set[str]) -> bool:
    """closing/cutoff seed + high_amount + (description/sensitive/rare OR manual/control).

    원안의 4신호 동시 (timing + amount + weak + manual) 는 너무 좁아서 fy2022/fy2023 모두
    5~6건. timing + amount 를 필수로 고정하고, 추가 신호를 OR 로 완화한다.
    """

    has_timing = bool(rules & (CUTOFF_RULES | MANUAL_CLOSING_RULES))
    has_amount = bool(rules & HIGH_AMOUNT_RULES)
    if not (has_timing and has_amount):
        return False
    has_extra = bool(
        rules
        & (
            DESCRIPTION_WEAK_RULES
            | SENSITIVE_ACCOUNT_RULES
            | RARE_ACCOUNT_RULES
            | MANUAL_ENTRY_RULES
            | APPROVAL_BYPASS_RULES
        )
    )
    return has_extra


def _embezzlement_concealment_critical(rules: set[str]) -> bool:
    """outflow/duplicate + approval bypass + high_amount — 원안 유지.

    조건이 명확히 도메인 정합이므로 변경 없음. fy2022 8 / fy2023 81 — 데이터 특성 차이.
    """

    return (
        bool(rules & DUPLICATE_RULES)
        and bool(rules & APPROVAL_BYPASS_RULES)
        and bool(rules & HIGH_AMOUNT_RULES)
    )


def _fictitious_entry_critical(rules: set[str]) -> bool:
    """revenue outlier + manual + (rare/duplicate OR closing/control).

    원안의 4신호 동시 (revenue + manual + rare/dup + closing/control) 는 너무 좁아서 0~1건.
    revenue outlier + manual 을 필수로 고정하고, 나머지 두 조건을 OR 로 완화한다.
    """

    has_revenue = bool(rules & REVENUE_OUTLIER_RULES)
    has_manual = bool(rules & MANUAL_ENTRY_RULES)
    if not (has_revenue and has_manual):
        return False
    has_rare_or_dup = bool(rules & (RARE_ACCOUNT_RULES | DUPLICATE_RULES))
    has_closing_or_control = bool(rules & (MANUAL_CLOSING_RULES | APPROVAL_BYPASS_RULES))
    return has_rare_or_dup or has_closing_or_control


CRITICAL_CHECKS: dict[str, Any] = {
    "approval_bypass_critical": _approval_bypass_critical,
    "period_end_adjustment_critical": _period_end_adjustment_critical,
    "embezzlement_concealment_critical": _embezzlement_concealment_critical,
    "fictitious_entry_critical": _fictitious_entry_critical,
}


def _analyze(artifact_path: Path) -> dict[str, Any]:
    with artifact_path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    cases = payload.get("cases", []) or []

    total = len(cases)
    in_band: list[dict[str, Any]] = []
    above_090 = 0
    for case in cases:
        score = float(case.get("priority_score", 0.0) or 0.0)
        if score >= BAND_HI:
            above_090 += 1
        elif score >= BAND_LO:
            in_band.append(case)

    primary_topic_counts: Counter = Counter()
    combo_policy_counts: Counter = Counter()
    rule_counts: Counter = Counter()

    critical_membership: dict[str, list[str]] = {key: [] for key in CRITICAL_CHECKS}

    for case in in_band:
        case_id = str(case.get("case_id"))
        primary_topic_counts[str(case.get("primary_topic") or "<none>")] += 1
        for pid in _case_combo_policy_ids(case):
            combo_policy_counts[pid] += 1
        rules = _case_rule_ids(case)
        for rid in rules:
            rule_counts[rid] += 1
        for name, check in CRITICAL_CHECKS.items():
            if check(rules):
                critical_membership[name].append(case_id)

    # overlap 계산
    membership_sets = {k: set(v) for k, v in critical_membership.items()}
    pairs = [
        ("approval_bypass_critical", "period_end_adjustment_critical"),
        ("approval_bypass_critical", "embezzlement_concealment_critical"),
        ("approval_bypass_critical", "fictitious_entry_critical"),
        ("period_end_adjustment_critical", "embezzlement_concealment_critical"),
        ("period_end_adjustment_critical", "fictitious_entry_critical"),
        ("embezzlement_concealment_critical", "fictitious_entry_critical"),
    ]
    overlaps = {f"{a} ∩ {b}": len(membership_sets[a] & membership_sets[b]) for a, b in pairs}
    union_all = set().union(*membership_sets.values())

    return {
        "artifact": str(artifact_path),
        "total_cases": total,
        "above_090_existing": above_090,
        "in_band_080_089": len(in_band),
        "primary_topic_in_band": dict(primary_topic_counts.most_common()),
        "rule_in_band_top20": dict(rule_counts.most_common(20)),
        "combo_policy_in_band_top20": dict(combo_policy_counts.most_common(20)),
        "critical_candidate_counts": {k: len(v) for k, v in critical_membership.items()},
        "critical_overlaps": overlaps,
        "critical_union_total": len(union_all),
    }


def _format_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"## Stage 2 candidate analysis — `{report['artifact']}`")
    lines.append("")
    lines.append(f"- total cases: {report['total_cases']}")
    lines.append(f"- already at 0.90+ (excluded from candidates): {report['above_090_existing']}")
    lines.append(f"- in 0.80~0.89 band (candidate pool): {report['in_band_080_089']}")
    lines.append("")
    lines.append("### Critical combo 신규 승격 가능 수 (0.80~0.89 구간에서만)")
    lines.append("")
    lines.append("| Critical                            | 신규 승격 후보 |")
    lines.append("|-------------------------------------|----------------|")
    for name, count in report["critical_candidate_counts"].items():
        lines.append(f"| {name:<35} | {count:>14} |")
    lines.append(
        f"| **union (중복 제거)**               | **{report['critical_union_total']:>10}** |"
    )
    lines.append("")
    lines.append("### Critical 간 overlap")
    lines.append("")
    lines.append("| Pair                                                | Overlap |")
    lines.append("|-----------------------------------------------------|---------|")
    for pair, overlap in report["critical_overlaps"].items():
        lines.append(f"| {pair:<51} | {overlap:>7} |")
    lines.append("")
    lines.append("### Primary topic distribution in 0.80~0.89")
    lines.append("")
    lines.append("| Topic                | Count |")
    lines.append("|----------------------|-------|")
    for topic, count in report["primary_topic_in_band"].items():
        lines.append(f"| {topic:<20} | {count:>5} |")
    lines.append("")
    lines.append("### Rule frequency in 0.80~0.89 (top 20)")
    lines.append("")
    lines.append("| Rule    | Count |")
    lines.append("|---------|-------|")
    for rule, count in report["rule_in_band_top20"].items():
        lines.append(f"| {rule:<7} | {count:>5} |")
    lines.append("")
    lines.append("### Combo policy frequency in 0.80~0.89 (top 20)")
    lines.append("")
    lines.append("| Combo policy                                    | Count |")
    lines.append("|-------------------------------------------------|-------|")
    for combo, count in report["combo_policy_in_band_top20"].items():
        lines.append(f"| {combo[:48]:<48} | {count:>5} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--out-md", type=Path, default=None)
    parser.add_argument("--out-json", type=Path, default=None)
    args = parser.parse_args(argv)

    report = _analyze(args.artifact)
    md = _format_markdown(report)
    if args.out_md:
        args.out_md.parent.mkdir(parents=True, exist_ok=True)
        args.out_md.write_text(md + "\n", encoding="utf-8")
    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
