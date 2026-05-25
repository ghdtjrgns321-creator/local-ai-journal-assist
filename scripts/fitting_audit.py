"""Stage 1+2 진행 과정의 fitting 위험 전방위 진단.

사용자가 제기한 의문:
- embezzlement_concealment_critical 이 stage_0 에서는 0건인데 stage_1 후 갑자기 8~81건 잡힘
  → 정말 stage_1 머지가 새 case 를 만든 것인가, 아니면 같은 case 가 분포 이동만 한 것인가?

본 스크립트는 다음을 측정해서 fitting 여부를 데이터로 보여준다.

1. stage_0 의 모든 case (band 무관) 중 4종 critical 조건 매칭 카운트
2. stage_1 의 0.80~0.89 구간 case 중 같은 조건 매칭 카운트
3. case_id 매칭으로 stage_0 → stage_1 분포 이동표
4. stage_1 의 0.80~0.89 case 의 priority_adjustment_reasons 빈도 (어떤 floor 가 0.80 cluster)
5. critical 조건 만족 case 의 stage_0 priority_score 분포
6. fy2022 vs fy2023 데이터 특성 차이
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

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


def _case_rule_ids(case: dict[str, Any]) -> set[str]:
    hits = case.get("raw_rule_hits") or []
    return {str(h.get("rule_id")) for h in hits if h.get("rule_id")}


def _embezzlement(rules: set[str]) -> bool:
    return (
        bool(rules & DUPLICATE_RULES)
        and bool(rules & APPROVAL_BYPASS_RULES)
        and bool(rules & HIGH_AMOUNT_RULES)
    )


def _approval_bypass_refined(rules: set[str]) -> bool:
    has_bypass = bool(rules & APPROVAL_BYPASS_RULES)
    has_amount = bool(rules & HIGH_AMOUNT_RULES)
    if not (has_bypass and has_amount):
        return False
    return bool(rules & (CUTOFF_RULES | MANUAL_CLOSING_RULES | AFTER_HOURS_RULES))


def _approval_bypass_loose(rules: set[str]) -> bool:
    """원안 (2개 이상) — 비교용."""
    if not rules & APPROVAL_BYPASS_RULES:
        return False
    independent = sum(
        bool(rules & g)
        for g in (HIGH_AMOUNT_RULES, CUTOFF_RULES, MANUAL_CLOSING_RULES, AFTER_HOURS_RULES)
    )
    return independent >= 2


def _period_end_refined(rules: set[str]) -> bool:
    has_timing = bool(rules & (CUTOFF_RULES | MANUAL_CLOSING_RULES))
    has_amount = bool(rules & HIGH_AMOUNT_RULES)
    if not (has_timing and has_amount):
        return False
    return bool(
        rules
        & (
            DESCRIPTION_WEAK_RULES
            | SENSITIVE_ACCOUNT_RULES
            | RARE_ACCOUNT_RULES
            | MANUAL_ENTRY_RULES
            | APPROVAL_BYPASS_RULES
        )
    )


def _fictitious_refined(rules: set[str]) -> bool:
    has_revenue = bool(rules & REVENUE_OUTLIER_RULES)
    has_manual = bool(rules & MANUAL_ENTRY_RULES)
    if not (has_revenue and has_manual):
        return False
    has_rd = bool(rules & (RARE_ACCOUNT_RULES | DUPLICATE_RULES))
    has_cc = bool(rules & (MANUAL_CLOSING_RULES | APPROVAL_BYPASS_RULES))
    return has_rd or has_cc


CRITICAL_CHECKS = {
    "approval_bypass_critical (refined)": _approval_bypass_refined,
    "approval_bypass_critical (loose, 원안)": _approval_bypass_loose,
    "period_end_adjustment_critical (refined)": _period_end_refined,
    "embezzlement_concealment_critical (unchanged)": _embezzlement,
    "fictitious_entry_critical (refined)": _fictitious_refined,
}


def _band(score: float) -> str:
    if score >= 0.95:
        return ">=0.95"
    if score >= 0.90:
        return "0.90~0.94"
    if score >= 0.85:
        return "0.85~0.89"
    if score >= 0.80:
        return "0.80~0.84"
    if score >= 0.75:
        return "0.75~0.79"
    if score >= 0.60:
        return "0.60~0.74"
    if score >= 0.45:
        return "0.45~0.59"
    return "<0.45"


def _load_cases(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    return payload.get("cases", []) or []


def _audit(stage_0_path: Path, stage_1_path: Path, dataset_label: str) -> dict[str, Any]:
    s0 = _load_cases(stage_0_path)
    s1 = _load_cases(stage_1_path)
    s0_by_id = {str(c.get("case_id")): c for c in s0}
    s1_by_id = {str(c.get("case_id")): c for c in s1}

    report: dict[str, Any] = {"dataset": dataset_label}

    # 1. 전 case 대상 critical 조건 매칭 카운트 (band 무관)
    per_critical_all_cases: dict[str, dict[str, int]] = {}
    for name, check in CRITICAL_CHECKS.items():
        s0_count = sum(1 for c in s0 if check(_case_rule_ids(c)))
        s1_count = sum(1 for c in s1 if check(_case_rule_ids(c)))
        per_critical_all_cases[name] = {
            "stage_0_all_cases_matching": s0_count,
            "stage_1_all_cases_matching": s1_count,
        }
    report["per_critical_all_cases"] = per_critical_all_cases

    # 2. critical 조건 만족 case 들의 stage_0 priority_score 분포
    score_distribution: dict[str, dict[str, int]] = {}
    for name, check in CRITICAL_CHECKS.items():
        bands: Counter = Counter()
        for case in s0:
            if check(_case_rule_ids(case)):
                score = float(case.get("priority_score", 0.0) or 0.0)
                bands[_band(score)] += 1
        score_distribution[name] = dict(bands)
    report["stage_0_score_distribution_per_critical"] = score_distribution

    # 3. stage_1 의 0.80~0.89 case 의 priority_adjustment_reasons 빈도
    band_080_089_reasons: Counter = Counter()
    band_080_089_count = 0
    band_080_089_match_critical: Counter = Counter()
    for case in s1:
        score = float(case.get("priority_score", 0.0) or 0.0)
        if 0.80 <= score < 0.90:
            band_080_089_count += 1
            for reason in case.get("priority_adjustment_reasons") or []:
                band_080_089_reasons[reason] += 1
            rules = _case_rule_ids(case)
            for name, check in CRITICAL_CHECKS.items():
                if check(rules):
                    band_080_089_match_critical[name] += 1
    report["band_080_089_count"] = band_080_089_count
    report["band_080_089_reasons_top20"] = dict(band_080_089_reasons.most_common(20))
    report["band_080_089_match_critical"] = dict(band_080_089_match_critical)

    # 4. case_id 매칭 — embezzlement 조건 만족 case 들의 분포 이동
    embezzlement_movement: Counter = Counter()
    embezzlement_score_pairs: list[tuple[str, float, float]] = []
    for case_id, s1_case in s1_by_id.items():
        rules = _case_rule_ids(s1_case)
        if not _embezzlement(rules):
            continue
        s0_case = s0_by_id.get(case_id)
        s0_score = float(s0_case.get("priority_score", 0.0) or 0.0) if s0_case else 0.0
        s1_score = float(s1_case.get("priority_score", 0.0) or 0.0)
        s0_band = _band(s0_score)
        s1_band = _band(s1_score)
        embezzlement_movement[f"{s0_band} → {s1_band}"] += 1
        if len(embezzlement_score_pairs) < 20:
            embezzlement_score_pairs.append((case_id, s0_score, s1_score))
    report["embezzlement_movement"] = dict(embezzlement_movement)
    report["embezzlement_score_pairs_sample"] = [
        {"case_id": cid, "s0_score": s0, "s1_score": s1} for cid, s0, s1 in embezzlement_score_pairs
    ]

    return report


def _format_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = [f"## Fitting audit — {report['dataset']}", ""]
    lines.append("### 1. critical 조건 매칭 — stage_0 전체 vs stage_1 전체")
    lines.append("")
    lines.append("priority_score band 와 무관하게 raw_rule_hits 만으로 조건 만족 case 카운트.")
    lines.append("이 값이 stage_0/stage_1 에서 같으면 머지가 새 매칭을 만든 게 아니라 분포 이동.")
    lines.append("")
    lines.append("| Critical                                          | stage_0 | stage_1 |")
    lines.append("|---------------------------------------------------|---------|---------|")
    for name, counts in report["per_critical_all_cases"].items():
        lines.append(
            f"| {name[:48]:<48} | {counts['stage_0_all_cases_matching']:>7} | "
            f"{counts['stage_1_all_cases_matching']:>7} |"
        )
    lines.append("")
    lines.append("### 2. critical 조건 만족 case 의 stage_0 priority_score 분포")
    lines.append("")
    lines.append(
        "매칭 case 들이 stage_0 에서 어느 band 에 있었는지. 모두 0.75 였다면 자연 분포이동."
    )
    lines.append("")
    for name, bands in report["stage_0_score_distribution_per_critical"].items():
        lines.append(f"**{name}**:")
        lines.append("")
        if not bands:
            lines.append("(no matches)")
        else:
            lines.append("| Band       | Count |")
            lines.append("|------------|-------|")
            for band in (
                ">=0.95",
                "0.90~0.94",
                "0.85~0.89",
                "0.80~0.84",
                "0.75~0.79",
                "0.60~0.74",
                "0.45~0.59",
                "<0.45",
            ):
                count = bands.get(band, 0)
                if count:
                    lines.append(f"| {band:<10} | {count:>5} |")
        lines.append("")
    lines.append("### 3. stage_1 의 0.80~0.89 구간 형성 원인")
    lines.append("")
    lines.append(f"- 총 케이스: {report['band_080_089_count']}")
    lines.append("")
    lines.append("**priority_adjustment_reasons 빈도 (top 20)**:")
    lines.append("")
    lines.append("| Reason                                          | Count |")
    lines.append("|-------------------------------------------------|-------|")
    for reason, count in report["band_080_089_reasons_top20"].items():
        lines.append(f"| {reason[:48]:<48} | {count:>5} |")
    lines.append("")
    lines.append("**critical 매칭 분포**:")
    lines.append("")
    lines.append("| Critical                                          | Count |")
    lines.append("|---------------------------------------------------|-------|")
    for name, count in report["band_080_089_match_critical"].items():
        lines.append(f"| {name[:48]:<48} | {count:>5} |")
    lines.append("")
    lines.append("### 4. embezzlement_concealment 매칭 case 의 분포 이동 (stage_0 → stage_1)")
    lines.append("")
    lines.append("| Movement                       | Count |")
    lines.append("|--------------------------------|-------|")
    for movement, count in report["embezzlement_movement"].items():
        lines.append(f"| {movement:<30} | {count:>5} |")
    lines.append("")
    if report["embezzlement_score_pairs_sample"]:
        lines.append("**Sample (up to 20 cases)**:")
        lines.append("")
        lines.append("| case_id              | stage_0 | stage_1 |")
        lines.append("|----------------------|---------|---------|")
        for row in report["embezzlement_score_pairs_sample"]:
            lines.append(
                f"| {row['case_id'][:20]:<20} | {row['s0_score']:>7.3f} | {row['s1_score']:>7.3f} |"
            )
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-0", type=Path, required=True)
    parser.add_argument("--stage-1", type=Path, required=True)
    parser.add_argument("--label", required=True)
    args = parser.parse_args(argv)
    report = _audit(args.stage_0, args.stage_1, args.label)
    print(_format_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
