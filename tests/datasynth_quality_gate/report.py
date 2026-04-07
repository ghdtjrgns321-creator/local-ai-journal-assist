"""품질 게이트 리포트 생성.

JSON + Markdown 이중 출력. 자동화 파이프라인은 JSON을, 사람은 Markdown을 소비.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .models import QualityGateReport


def to_json(report: QualityGateReport) -> str:
    """JSON 문자열 반환."""
    data = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data_file": report.data_file,
            "total_rows": report.total_rows,
            "total_documents": report.total_documents,
            "elapsed_seconds": round(report.elapsed_seconds, 2),
        },
        "summary": {
            f"tier{t.tier}": {
                "name": t.name,
                "pass": t.pass_count,
                "fail": t.fail_count,
                "warning": t.warning_count,
                "skip": t.skip_count,
                "verdict": t.verdict,
            }
            for t in report.tiers
        },
        "overall_verdict": report.overall_verdict,
        "checks": [
            {
                "check_id": c.check_id,
                "tier": c.tier,
                "name": c.name,
                "status": c.status,
                "expected": c.expected,
                "actual": c.actual,
                "detail": c.detail,
                "elapsed_ms": round(c.elapsed_ms, 1),
            }
            for t in report.tiers
            for c in t.checks
        ],
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


def to_markdown(report: QualityGateReport) -> str:
    """Markdown 문자열 반환."""
    lines: list[str] = []
    lines.append("# DataSynth 전수 품질검사 리포트")
    lines.append(
        f"> 실행일: {datetime.now().strftime('%Y-%m-%d %H:%M')} | "
        f"소요: {report.elapsed_seconds:.1f}s | "
        f"판정: **{report.overall_verdict}**"
    )
    lines.append("")

    # 요약 테이블
    lines.append("## 요약")
    lines.append("| Tier | 이름 | Pass | Fail | Warning | Skip | 판정 |")
    lines.append("|------|------|------|------|---------|------|------|")
    for t in report.tiers:
        lines.append(
            f"| T{t.tier} | {t.name} | {t.pass_count} | {t.fail_count} | "
            f"{t.warning_count} | {t.skip_count} | {t.verdict} |"
        )
    lines.append("")

    # Tier별 상세
    for t in report.tiers:
        lines.append(f"## Tier {t.tier}: {t.name}")
        lines.append("| ID    | 체크 | 상태 | 기대 | 실측 |")
        lines.append("|-------|------|------|------|------|")
        for c in t.checks:
            # 긴 값은 50자로 잘라서 표시
            exp_short = c.expected[:50] + "..." if len(c.expected) > 50 else c.expected
            act_short = c.actual[:50] + "..." if len(c.actual) > 50 else c.actual
            lines.append(
                f"| {c.check_id} | {c.name} | {c.status} | {exp_short} | {act_short} |"
            )
        lines.append("")

    # 실패/경고 상세
    failures = [
        c
        for t in report.tiers
        for c in t.checks
        if c.status in ("FAIL", "WARNING")
    ]
    if failures:
        lines.append("## 실패/경고 항목 상세")
        for c in failures:
            lines.append(f"### {c.check_id} {c.name} [{c.status}]")
            lines.append(f"- 기대: {c.expected}")
            lines.append(f"- 실측: {c.actual}")
            if c.detail:
                sample = json.dumps(c.detail, ensure_ascii=False, indent=2)
                if len(sample) > 500:
                    sample = sample[:500] + "\n  ..."
                lines.append(f"- 상세:\n```json\n{sample}\n```")
            lines.append("")

    return "\n".join(lines)


def save_report(
    report: QualityGateReport, output_dir: Path | None = None
) -> tuple[Path, Path]:
    """JSON + Markdown 파일 저장."""
    if output_dir is None:
        output_dir = Path(__file__).resolve().parent / "results"
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "quality_report.json"
    md_path = output_dir / "quality_report.md"

    json_path.write_text(to_json(report), encoding="utf-8")
    md_path.write_text(to_markdown(report), encoding="utf-8")

    return json_path, md_path
