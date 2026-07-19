"""Stage 2-A 의 priority_floors 신규 0.90 entry 효과 시뮬레이션.

YAML 의 `priority_floors` 중 `min_priority_score >= 0.90` entry 를 동적으로 추출하여
stage_1 artifact 의 raw_rule_hits 에 매칭 시도한다.

매칭 규칙:
- rule_id, min_raw_score: case 의 raw_rule_hits 중 해당 rule 의 score 확인.
- required_rules (AND): case 의 rule_id set 이 모두 포함해야 함.
- required_rules_any (OR, 신설 schema): case 의 rule_id set 중 1개 이상.
- labels / missing_fields: annotation 기반 매칭은 artifact 에 없어서 보수적으로 무시.

본 도구는 D060 (2026-05-20) 원칙 5조 정합성 검증용. 1회 측정만 수행하고 결과로
entry 조건을 재조정하지 않는다.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path("config/phase1_case.yaml")
NEW_CRITICAL_THRESHOLD = 0.90


def _load_critical_entries(config_path: Path) -> list[dict[str, Any]]:
    with config_path.open("r", encoding="utf-8") as fh:
        config = yaml.safe_load(fh) or {}
    floors = (config.get("phase1_case") or {}).get("priority_floors") or []
    critical: list[dict[str, Any]] = []
    for entry in floors:
        if not isinstance(entry, dict):
            continue
        try:
            score = float(entry.get("min_priority_score", 0.0))
        except (TypeError, ValueError):
            continue
        if score >= NEW_CRITICAL_THRESHOLD:
            critical.append(entry)
    return critical


def _case_rule_score(case: dict[str, Any], rule_id: str) -> float | None:
    """case 의 raw_rule_hits 중 rule_id 에 해당하는 max score."""
    best: float | None = None
    for hit in case.get("raw_rule_hits") or []:
        if str(hit.get("rule_id")) != rule_id:
            continue
        try:
            score = float(hit.get("score", 0.0))
        except (TypeError, ValueError):
            continue
        if best is None or score > best:
            best = score
    return best


def _case_rule_ids(case: dict[str, Any]) -> set[str]:
    return {str(h.get("rule_id")) for h in case.get("raw_rule_hits") or [] if h.get("rule_id")}


def _case_rule_hit_labels(case: dict[str, Any], rule_id: str) -> set[str]:
    """case 의 raw_rule_hits 중 rule_id 의 display_label set (소문자)."""

    labels: set[str] = set()
    for hit in case.get("raw_rule_hits") or []:
        if str(hit.get("rule_id")) != rule_id:
            continue
        label = str(hit.get("display_label") or "").strip().lower()
        if label:
            labels.add(label)
    return labels


def _entry_matches(case: dict[str, Any], entry: dict[str, Any]) -> bool:
    rule_id = str(entry.get("rule_id") or "").strip()
    if not rule_id:
        return False
    rule_score = _case_rule_score(case, rule_id)
    if rule_score is None:
        return False
    min_raw = entry.get("min_raw_score")
    if min_raw is not None:
        try:
            if rule_score < float(min_raw):
                return False
        except (TypeError, ValueError):
            return False

    # labels 매칭 (_apply_priority_floors 와 동일 의미). artifact 의 display_label 사용.
    labels_required = {
        str(label).strip().lower() for label in entry.get("labels", []) or [] if str(label).strip()
    }
    if labels_required:
        case_labels = _case_rule_hit_labels(case, rule_id)
        if not (labels_required & case_labels):
            return False

    case_rules = _case_rule_ids(case)

    required_rules = {
        str(r).strip() for r in entry.get("required_rules", []) or [] if str(r).strip()
    }
    if required_rules:
        match_mode = str(entry.get("required_rules_match", "all")).strip().lower()
        if match_mode == "any":
            if not (required_rules & case_rules):
                return False
        else:
            if not required_rules.issubset(case_rules):
                return False

    required_any = {
        str(r).strip() for r in entry.get("required_rules_any", []) or [] if str(r).strip()
    }
    if required_any:
        if not (required_any & case_rules):
            return False

    return True


def _simulate(stage_1_path: Path, config_path: Path) -> dict[str, Any]:
    entries = _load_critical_entries(config_path)
    with stage_1_path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    cases = payload.get("cases") or []

    matches_per_entry: dict[str, list[str]] = {}
    new_score_per_case: dict[str, float] = {}
    case_reasons: dict[str, list[str]] = {}

    for case in cases:
        case_id = str(case.get("case_id"))
        current_score = float(case.get("priority_score", 0.0) or 0.0)
        for entry in entries:
            reason = str(entry.get("reason") or f"floor:{entry.get('rule_id')}")
            if _entry_matches(case, entry):
                matches_per_entry.setdefault(reason, []).append(case_id)
                if current_score < NEW_CRITICAL_THRESHOLD:
                    new_score_per_case[case_id] = max(
                        new_score_per_case.get(case_id, current_score),
                        NEW_CRITICAL_THRESHOLD,
                    )
                    case_reasons.setdefault(case_id, []).append(reason)

    promoted_case_ids = sorted(new_score_per_case.keys())
    already_critical = sum(
        1 for c in cases if float(c.get("priority_score", 0.0) or 0.0) >= NEW_CRITICAL_THRESHOLD
    )
    band_before = Counter()
    for c in cases:
        s = float(c.get("priority_score", 0.0) or 0.0)
        if s >= 0.95:
            band_before[">=0.95"] += 1
        elif s >= 0.90:
            band_before["0.90~0.94"] += 1
        elif s >= 0.85:
            band_before["0.85~0.89"] += 1
        elif s >= 0.80:
            band_before["0.80~0.84"] += 1
        elif s >= 0.75:
            band_before["0.75~0.79"] += 1
        else:
            band_before["<0.75"] += 1
    band_after = Counter(band_before)
    for case_id in promoted_case_ids:
        case = next(c for c in cases if str(c.get("case_id")) == case_id)
        old_score = float(case.get("priority_score", 0.0) or 0.0)
        if 0.85 <= old_score < 0.90:
            band_after["0.85~0.89"] -= 1
        elif 0.80 <= old_score < 0.85:
            band_after["0.80~0.84"] -= 1
        elif 0.75 <= old_score < 0.80:
            band_after["0.75~0.79"] -= 1
        else:
            band_after["<0.75"] -= 1
        band_after["0.90~0.94"] += 1

    score_movement_examples: list[dict[str, Any]] = []
    for case_id in promoted_case_ids[:20]:
        case = next(c for c in cases if str(c.get("case_id")) == case_id)
        score_movement_examples.append(
            {
                "case_id": case_id,
                "stage_1_score": float(case.get("priority_score", 0.0) or 0.0),
                "stage_2_score": 0.90,
                "reasons_added": case_reasons.get(case_id, []),
                "primary_topic": case.get("primary_topic"),
                "rule_ids": sorted(_case_rule_ids(case)),
            }
        )

    return {
        "stage_1_artifact": str(stage_1_path),
        "config_path": str(config_path),
        "total_cases": len(cases),
        "already_at_090": already_critical,
        "entries_evaluated": [
            {
                "reason": e.get("reason"),
                "rule_id": e.get("rule_id"),
                "min_raw_score": e.get("min_raw_score"),
                "required_rules": e.get("required_rules") or [],
                "required_rules_any": e.get("required_rules_any") or [],
                "matched_case_count": len(matches_per_entry.get(e.get("reason", ""), [])),
            }
            for e in entries
        ],
        "newly_promoted_count": len(promoted_case_ids),
        "newly_promoted_by_reason": {
            reason: len(set(ids) & set(promoted_case_ids))
            for reason, ids in matches_per_entry.items()
        },
        "band_before": dict(band_before),
        "band_after": dict(band_after),
        "movement_examples": score_movement_examples,
    }


def _format_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("## Stage 2-A critical 시뮬레이션")
    lines.append("")
    lines.append(f"- stage_1 artifact: `{report['stage_1_artifact']}`")
    lines.append(f"- config: `{report['config_path']}`")
    lines.append(f"- total cases: {report['total_cases']}")
    lines.append(f"- already at 0.90+: {report['already_at_090']}")
    lines.append(f"- newly promoted to 0.90+: **{report['newly_promoted_count']}**")
    lines.append("")
    lines.append("### Entries evaluated (priority_floors min_priority_score >= 0.90)")
    lines.append("")
    lines.append(
        "| Reason                                          | rule_id | min_raw | matches |"
    )
    lines.append(
        "|-------------------------------------------------|---------|---------|---------|"
    )
    for e in report["entries_evaluated"]:
        reason = str(e.get("reason") or "")
        rule_id = str(e.get("rule_id") or "")
        min_raw = e.get("min_raw_score")
        min_raw_str = "" if min_raw is None else str(min_raw)
        lines.append(
            f"| {reason[:48]:<48} | {rule_id:<7} | "
            f"{min_raw_str:<7} | {e.get('matched_case_count', 0):>7} |"
        )
    lines.append("")
    lines.append("### Newly promoted by reason")
    lines.append("")
    lines.append("| Reason                                          | Newly promoted |")
    lines.append("|-------------------------------------------------|----------------|")
    for reason, count in report["newly_promoted_by_reason"].items():
        lines.append(f"| {reason[:48]:<48} | {count:>14} |")
    lines.append("")
    lines.append("### Band before → after")
    lines.append("")
    lines.append("| Band      | Before | After |")
    lines.append("|-----------|--------|-------|")
    for band in (">=0.95", "0.90~0.94", "0.85~0.89", "0.80~0.84", "0.75~0.79", "<0.75"):
        before = report["band_before"].get(band, 0)
        after = report["band_after"].get(band, 0)
        lines.append(f"| {band:<9} | {before:>6} | {after:>5} |")
    lines.append("")
    if report["movement_examples"]:
        lines.append("### Movement examples (up to 20)")
        lines.append("")
        lines.append("| case_id | stage_1 | stage_2 | reasons | rule_ids |")
        lines.append("|---------|---------|---------|---------|----------|")
        for row in report["movement_examples"]:
            reasons = ", ".join(row["reasons_added"])
            rules = ", ".join(row["rule_ids"][:8])
            lines.append(
                f"| {row['case_id'][:24]:<24} | {row['stage_1_score']:.3f} | "
                f"{row['stage_2_score']:.3f} | {reasons[:30]:<30} | {rules[:40]} |"
            )
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-1", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--out-md", type=Path, default=None)
    parser.add_argument("--out-json", type=Path, default=None)
    args = parser.parse_args(argv)

    report = _simulate(args.stage_1, args.config)
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
