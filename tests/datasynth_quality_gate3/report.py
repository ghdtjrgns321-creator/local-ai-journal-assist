"""리포트 생성 — JSON + Markdown."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .models import QualityGateReport

TIER_NAMES = {
    1: "기본 무결성",
    2: "정량 벤치마크",
    3: "의미 정합성 (적요↔GL, header↔GL)",
    4: "교차 필드 정합성",
    5: "메타데이터 정합성",
}


def save_report(
    report: QualityGateReport, output_dir: Path | None = None,
) -> tuple[Path, Path]:
    """JSON + Markdown 저장."""
    if output_dir is None:
        output_dir = Path(__file__).parent / "results"
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "realism_report.json"
    md_path = output_dir / "realism_report.md"

    # --- JSON ---
    data = {
        "meta": {
            "generated_at": datetime.now().isoformat(),
            "data_file": report.data_file,
            "total_rows": report.total_rows,
            "total_documents": report.total_documents,
            "elapsed_seconds": round(report.elapsed_seconds, 1),
        },
        "overall_verdict": report.overall_verdict,
        "tiers": [],
    }
    for tier in report.tiers:
        tier_data = {
            "tier": tier.tier,
            "name": tier.name,
            "verdict": tier.verdict,
            "pass": tier.pass_count,
            "fail": tier.fail_count,
            "warning": tier.warning_count,
            "checks": [],
        }
        for c in tier.checks:
            tier_data["checks"].append({
                "check_id": c.check_id,
                "name": c.name,
                "status": c.status,
                "expected": c.expected,
                "actual": c.actual,
                "detail": c.detail,
                "elapsed_ms": round(c.elapsed_ms, 1),
            })
        data["tiers"].append(tier_data)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # --- Markdown ---
    lines = [
        "# 현실성 검증 품질 리포트 (QG3)",
        f"> 실행일: {datetime.now().strftime('%Y-%m-%d %H:%M')} | "
        f"소요: {report.elapsed_seconds:.1f}s | "
        f"판정: **{report.overall_verdict}**",
        "",
        "## 요약",
        "| Tier | 이름 | Pass | Fail | Warning | 판정 |",
        "|------|------|------|------|---------|------|",
    ]
    for tier in report.tiers:
        lines.append(
            f"| {tier.tier} | {tier.name} | {tier.pass_count} | "
            f"{tier.fail_count} | {tier.warning_count} | {tier.verdict} |"
        )

    for tier in report.tiers:
        lines.extend(["", f"## Tier {tier.tier}: {tier.name}"])
        lines.append("| ID | 체크 | 상태 | 기대 | 실측 |")
        lines.append("|-----|------|------|------|------|")
        for c in tier.checks:
            actual_short = c.actual[:80] + "..." if len(c.actual) > 80 else c.actual
            lines.append(
                f"| {c.check_id} | {c.name} | {c.status} "
                f"| {c.expected} | {actual_short} |"
            )

    fails = [
        c for t in report.tiers for c in t.checks
        if c.status in ("FAIL", "WARNING")
    ]
    if fails:
        lines.extend(["", "## 상세"])
        for c in fails:
            lines.append(f"\n### {c.check_id} {c.name} [{c.status}]")
            lines.append(f"- 기대: {c.expected}")
            lines.append(f"- 실측: {c.actual}")
            if c.detail:
                lines.append("- 상세:")
                lines.append("```json")
                lines.append(
                    json.dumps(c.detail, ensure_ascii=False, indent=2)[:2000]
                )
                lines.append("```")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return json_path, md_path
