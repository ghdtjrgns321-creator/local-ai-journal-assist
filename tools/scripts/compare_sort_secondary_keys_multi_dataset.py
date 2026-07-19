"""§9.3 multi-dataset composite_sort_score 안정성 검증.

audit_sort_secondary_keys.py 의 dataset 별 출력 JSON 을 모아 가중치 lock 가능 여부를 판정한다.

판정 규칙 (feedback_phase1_truth_recall_guard 정합):
- max_primary_rule_score 방향 일관성: 모든 dataset, useful topic 에서 truth_median > nontruth_median (+1) 또는 동률 (0). -1 발생 시 lock 불가.
- audit_evidence_score / corroboration_score / independent_evidence_count: +1 또는 0 만 허용. -1 발생 시 가중치 인하 후보.
- AB_C3 vs AB_C0 손실 ≤ 5/topic (도메인 충돌 가드).
- approval_control:high 가드는 비율 기반 (Top200 truth_doc / high_case 모집단 ≥ 2.5%) 로 환산해 report 한다.

Layer C SOFT WARN (baseline 회귀만 차단):
- 가중치 lock 사유로 truth recall 직접 사용 금지.
- multi-dataset 모두에서 baseline 대비 회귀가 발생하면 가중치 조정 또는 PHASE2 이관 필요.
"""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

USEFUL_TOPICS_WITH_TRUTH = {
    "approval_control",
    "duplicate_outflow",
    "revenue_statistical",
    "closing_timing",
    "intercompany_cycle",
    "ledger_integrity",
    "account_logic",
}

PRIMARY_KEY = "max_primary_rule_score"
SECONDARY_KEYS = ("audit_evidence_score", "corroboration_score", "independent_evidence_count")
GUARDED_LOSS_PER_TOPIC = 5
HIGH_BAND_RATIO_THRESHOLD = 0.025  # 2.5% of high-band cases


def load_audit(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def topic_top200_truth(topic_data: dict[str, Any], candidate_key: str, *, top_n: int = 200) -> int:
    """Top200 unique truth_doc — candidates 또는 all_band_candidates 둘 다 시도."""

    candidates = topic_data.get("candidates") or {}
    all_band = topic_data.get("all_band_candidates") or {}
    if candidate_key.startswith("AB_"):
        bucket = all_band
    else:
        bucket = candidates
    inner = bucket.get(candidate_key)
    if not inner:
        return 0
    leaf = inner.get(str(top_n)) or inner.get(top_n)
    if isinstance(leaf, dict):
        return int(leaf.get("top_n_truth_docs") or 0)
    return 0


def collect_consistency(audits: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """{aux_key: {topic: {dataset: direction}}} 형태로 정리."""

    aux_keys = set()
    for audit in audits.values():
        aux_keys.update((audit.get("consistency") or {}).keys())

    out: dict[str, dict[str, Any]] = {}
    for key in sorted(aux_keys):
        topic_map: dict[str, dict[str, int]] = {}
        for dataset_label, audit in audits.items():
            topic_directions = (audit.get("consistency") or {}).get(key, {})
            for topic_id, direction in topic_directions.items():
                if topic_id not in USEFUL_TOPICS_WITH_TRUTH:
                    continue
                topic_map.setdefault(topic_id, {})[dataset_label] = int(direction)
        out[key] = topic_map
    return out


def topic_baseline_composite_loss(audit: dict[str, Any]) -> dict[str, dict[str, int]]:
    """{topic: {AB_C0, AB_C3, delta}} - AB_C3 - AB_C0 손실 측정."""

    losses: dict[str, dict[str, int]] = {}
    for topic_id, td in (audit.get("topics") or {}).items():
        ab_c0 = topic_top200_truth(td, "AB_C0_baseline")
        ab_c3 = topic_top200_truth(td, "AB_C3_composite_phase1")
        losses[topic_id] = {
            "AB_C0_baseline": ab_c0,
            "AB_C3_composite": ab_c3,
            "delta": ab_c3 - ab_c0,
        }
    return losses


def high_band_ratio(audit: dict[str, Any], topic_id: str) -> dict[str, float | int]:
    """approval_control:high 가드를 비율로 환산."""

    td = (audit.get("topics") or {}).get(topic_id) or {}
    high_cases = int(td.get("high_case_count") or 0)
    if high_cases == 0:
        return {"high_cases": 0, "top200_truth": 0, "ratio": 0.0}
    c3 = topic_top200_truth(td, "C3_composite_phase1")
    return {
        "high_cases": high_cases,
        "top200_truth": c3,
        "ratio": c3 / high_cases if high_cases else 0.0,
    }


def consistency_verdict(
    consistency: dict[str, dict[str, dict[str, int]]],
) -> dict[str, dict[str, Any]]:
    """가중치 lock 가능 여부 판정."""

    verdict: dict[str, dict[str, Any]] = {}
    for key, topic_map in consistency.items():
        flags: list[str] = []
        negative_hits: list[str] = []
        for topic_id, dataset_directions in topic_map.items():
            # 방향 집합
            dirs = set(dataset_directions.values())
            if -1 in dirs:
                negative_hits.append(topic_id)
            if dirs == {0}:
                flags.append(f"{topic_id}=neutral_all")
        verdict[key] = {
            "topic_directions": topic_map,
            "negative_hits": negative_hits,
            "flags": flags,
            "universal_positive": (
                key == PRIMARY_KEY
                and not negative_hits
                and any(
                    1 in dataset_directions.values() for dataset_directions in topic_map.values()
                )
            ),
        }
    return verdict


def render_markdown(report: dict[str, Any], dataset_order: list[str]) -> str:
    parts: list[str] = []
    parts.append("# PHASE1 composite_sort_score Multi-Dataset Lock\n")
    parts.append(f"- 측정일: {report['generated_at']}")
    parts.append(f"- 데이터셋: {', '.join(dataset_order)}")
    parts.append(
        "- 정책: feedback_phase1_truth_recall_guard — 가중치는 도메인 정합성으로만 정당화, truth recall 은 회귀 방지선"
    )
    parts.append("")

    parts.append("## 1. consistency 검증\n")
    parts.append(
        f"PHASE1 가중치 후보 키 중 `{PRIMARY_KEY}` 는 +3 universal positive 가 lock 조건.\n"
    )

    headers = ["topic"] + dataset_order + ["판정"]
    parts.append("### 1.1 max_primary_rule_score 방향")
    parts.append("")
    parts.append("| " + " | ".join(headers) + " |")
    parts.append("|" + "|".join("---" for _ in headers) + "|")
    for topic_id, directions in report["consistency"][PRIMARY_KEY]["topic_directions"].items():
        row = [topic_id]
        for ds in dataset_order:
            row.append(str(directions.get(ds, "·")))
        row.append(
            "OK" if all(directions.get(ds, 0) >= 0 for ds in dataset_order) else "REGRESSION"
        )
        parts.append("| " + " | ".join(row) + " |")
    parts.append("")

    for key in SECONDARY_KEYS:
        v = report["consistency"].get(key)
        if not v:
            continue
        parts.append(f"### 1.2 {key} 방향 (보조 가중치)")
        parts.append("")
        parts.append("| " + " | ".join(headers) + " |")
        parts.append("|" + "|".join("---" for _ in headers) + "|")
        for topic_id, directions in v["topic_directions"].items():
            row = [topic_id]
            for ds in dataset_order:
                row.append(str(directions.get(ds, "·")))
            ok = all(directions.get(ds, 0) >= 0 for ds in dataset_order)
            row.append("OK" if ok else "REGRESSION")
            parts.append("| " + " | ".join(row) + " |")
        parts.append("")

    parts.append("## 2. AB_C0 vs AB_C3 도메인 충돌 가드 (손실 ≤5/topic)\n")
    parts.append(
        "| topic | " + " | ".join(f"{ds} ΔAB" for ds in dataset_order) + " | 최대손실 | 판정 |"
    )
    parts.append("|" + "|".join(["---"] * (len(dataset_order) + 3)) + "|")
    for topic_id in sorted(USEFUL_TOPICS_WITH_TRUTH):
        deltas: list[int] = []
        row = [topic_id]
        for ds in dataset_order:
            loss = report["topic_losses"][ds].get(topic_id, {})
            delta = loss.get("delta")
            deltas.append(delta if isinstance(delta, int) else 0)
            if delta is None:
                row.append("·")
            else:
                row.append(
                    f"{loss.get('AB_C0_baseline', 0)}→{loss.get('AB_C3_composite', 0)} ({delta:+d})"
                )
        max_loss = -min(deltas) if deltas else 0
        row.append(str(max_loss))
        row.append(
            "OK" if max_loss <= GUARDED_LOSS_PER_TOPIC else f"WARN (>{GUARDED_LOSS_PER_TOPIC})"
        )
        parts.append("| " + " | ".join(row) + " |")
    parts.append("")

    parts.append("## 3. approval_control:high 비율 가드 (≥ 2.5%)\n")
    parts.append("| dataset | high_cases | Top200 truth_doc | 비율 | 판정 |")
    parts.append("|---|---:|---:|---:|---|")
    for ds in dataset_order:
        info = report["approval_high_ratio"][ds]
        ratio = info.get("ratio", 0.0)
        verdict = "OK" if ratio >= HIGH_BAND_RATIO_THRESHOLD else "WARN"
        parts.append(
            f"| {ds} | {info.get('high_cases', 0)} | {info.get('top200_truth', 0)} | "
            f"{ratio:.2%} | {verdict} |"
        )
    parts.append("")

    parts.append("## 4. 종합 판정\n")
    verdict_lines = report["verdict"]["lines"]
    for line in verdict_lines:
        parts.append(f"- {line}")
    parts.append("")
    parts.append(f"**최종**: {report['verdict']['final']}\n")
    return "\n".join(parts)


def build_report(
    audits: dict[str, dict[str, Any]],
    dataset_order: list[str],
    *,
    generated_at: str,
) -> dict[str, Any]:
    consistency = collect_consistency(audits)
    verdict = consistency_verdict(consistency)
    losses = {ds: topic_baseline_composite_loss(audit) for ds, audit in audits.items()}
    approval_ratios = {
        ds: high_band_ratio(audit, "approval_control") for ds, audit in audits.items()
    }

    # 종합 판정
    lines: list[str] = []
    final = "LOCK"

    # 1) max_primary_rule_score 음수 방향이 있는 데이터셋 발견
    primary_neg = verdict[PRIMARY_KEY]["negative_hits"]
    if primary_neg:
        final = "DEFER"
        lines.append(
            f"`{PRIMARY_KEY}` 가 {primary_neg} 도메인에서 -방향 발생 — universal positive 가정 무너짐. PHASE2 ML 이관 검토."
        )
    else:
        lines.append(f"`{PRIMARY_KEY}` universal positive 유지 (모든 dataset/topic 에서 +/0).")

    # 2) AB_C3 손실 가드 (도메인 충돌)
    over_loss: list[tuple[str, str, int]] = []
    for ds, topic_losses in losses.items():
        for topic_id, info in topic_losses.items():
            if topic_id not in USEFUL_TOPICS_WITH_TRUTH:
                continue
            delta = info.get("delta", 0)
            if delta < -GUARDED_LOSS_PER_TOPIC:
                over_loss.append((ds, topic_id, delta))
    if over_loss:
        final = "DEFER" if final == "LOCK" else final
        lines.append(f"AB_C3 - AB_C0 손실 >5 발생: {over_loss}. 도메인 충돌 가드 위반.")
    else:
        lines.append(f"AB_C3 - AB_C0 손실 모든 dataset/topic 에서 ≤{GUARDED_LOSS_PER_TOPIC}.")

    # 3) approval_control:high 비율 가드 (절대값 12 → 비율 2.5%)
    weak_ratio: list[tuple[str, float]] = []
    for ds, info in approval_ratios.items():
        if info.get("high_cases", 0) == 0:
            continue
        if info.get("ratio", 0.0) < HIGH_BAND_RATIO_THRESHOLD:
            weak_ratio.append((ds, info.get("ratio", 0.0)))
    if weak_ratio:
        # SOFT WARN — 가중치 lock 자체를 막지는 않음 (Layer C)
        lines.append(
            f"approval_control:high Top200 truth_doc 비율 <2.5%: {weak_ratio} (Layer C SOFT WARN)"
        )
    else:
        lines.append("approval_control:high Top200 truth_doc 비율 모든 dataset 에서 ≥2.5%.")

    # 4) secondary keys neutral/negative
    for key in SECONDARY_KEYS:
        v = verdict.get(key, {})
        if v.get("negative_hits"):
            lines.append(
                f"`{key}` 가 {v['negative_hits']} 도메인에서 -방향 — 보조 가중치 인하 후보."
            )

    if final == "LOCK":
        lines.append("→ 가중치 lock 안정. PHASE1 composite_sort_score 가중치 유지.")
    else:
        lines.append("→ 가중치 lock 보류. 본 보고서 §1·§2 표 참고하여 정책 조정 또는 PHASE2 이관.")

    return {
        "generated_at": generated_at,
        "datasets": dataset_order,
        "audit_paths": {ds: audits[ds].get("case_artifact") for ds in dataset_order},
        "truth_paths": {ds: audits[ds].get("truth_csv") for ds in dataset_order},
        "case_totals": {ds: audits[ds].get("case_total") for ds in dataset_order},
        "truth_totals": {ds: audits[ds].get("truth_total") for ds in dataset_order},
        "consistency": verdict,
        "topic_losses": losses,
        "approval_high_ratio": approval_ratios,
        "verdict": {"lines": lines, "final": final},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--audit",
        action="append",
        nargs=2,
        metavar=("LABEL", "JSON"),
        required=True,
        help="audit_sort_secondary_keys.py 의 출력 JSON 과 dataset 라벨 — --audit v126 path 식",
    )
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-md", type=Path, required=True)
    parser.add_argument("--generated-at", type=str, default="")
    args = parser.parse_args()

    audits: dict[str, dict[str, Any]] = {}
    dataset_order: list[str] = []
    for label, path_str in args.audit:
        path = Path(path_str)
        if not path.exists():
            raise SystemExit(f"audit JSON not found: {path}")
        audits[label] = load_audit(path)
        dataset_order.append(label)

    generated_at = args.generated_at or "today"
    report = build_report(audits, dataset_order, generated_at=generated_at)

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    args.out_md.write_text(render_markdown(report, dataset_order), encoding="utf-8")
    print(f"wrote {args.out_json}")
    print(f"wrote {args.out_md}")
    print(f"verdict: {report['verdict']['final']}")
    for line in report["verdict"]["lines"]:
        print(f"  - {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
