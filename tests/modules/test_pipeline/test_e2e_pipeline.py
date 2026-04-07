"""Pipeline E2E 테스트 — DataSynth 1M행 전체 파이프라인.

독립 실행 스크립트 (pytest 아님). 1M행 처리에 수십 초 소요.
실행: uv run python tests/test_pipeline/test_e2e_pipeline.py
결과: tests/test_pipeline/test-results/e2e-pipeline-datasynth.md
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from src.pipeline import AuditPipeline, PipelineResult

# ── 경로 상수 ──────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_CSV = PROJECT_ROOT / "data/journal/primary/datasynth/journal_entries.csv"
OUTPUT_DIR = Path(__file__).resolve().parent / "test-results"
OUTPUT_MD = OUTPUT_DIR / "e2e-pipeline-datasynth.md"


def run_pipeline() -> PipelineResult:
    """파이프라인 전체 실행 (DB 적재 제외)."""
    return AuditPipeline(skip_db=True).run(DATA_CSV)


def generate_report(result: PipelineResult) -> str:
    """PipelineResult → Markdown 리포트."""
    lines: list[str] = []
    lines.append("# Pipeline E2E 테스트 — DataSynth")
    lines.append(f"\n실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"소요 시간: {result.elapsed:.2f}초")
    lines.append(f"Batch ID: `{result.batch_id}`")
    lines.append(f"입력 행수: {len(result.data):,}")

    # 위험도 분포
    lines.append("\n## 위험도 분포\n")
    lines.append("| 등급 | 건수 | 비율 |")
    lines.append("|------|------|------|")
    total = len(result.data)
    for level in ["High", "Medium", "Low", "Normal"]:
        # Why: risk_level은 RiskLevel(StrEnum) — .value_counts() 키가 enum 또는 문자열
        count = sum(v for k, v in result.risk_summary.items() if str(k) == level)
        pct = count / total * 100 if total else 0
        lines.append(f"| {level:8s} | {count:>8,} | {pct:6.2f}% |")

    # 레이어별 탐지 요약
    lines.append("\n## 레이어별 탐지 요약\n")
    lines.append("| 트랙 | 플래그 행수 | 실행 룰 | 소요시간(초) |")
    lines.append("|------|-----------|---------|------------|")
    for r in result.results:
        lines.append(
            f"| {r.track_name:10s} | {r.flagged_count:>10,} | "
            f"{r.total_rules_run:>7} | {r.elapsed_seconds:>10.3f} |"
        )

    # 룰별 플래그 건수
    lines.append("\n## 룰별 플래그 건수\n")
    lines.append("| 룰 ID | 룰명 | 심각도 | 플래그 건수 | 플래그율 |")
    lines.append("|-------|------|--------|-----------|---------|")
    for r in result.results:
        for rf in sorted(r.rule_flags, key=lambda x: x.rule_id):
            if rf.flagged_count > 0:
                lines.append(
                    f"| {rf.rule_id} | {rf.rule_name[:20]} | {rf.severity} | "
                    f"{rf.flagged_count:>9,} | {rf.flag_rate:>7.2%} |"
                )

    # Warnings
    if result.warnings:
        lines.append("\n## Warnings\n")
        for w in result.warnings:
            lines.append(f"- {w}")

    # Anomaly Score 분포
    lines.append("\n## Anomaly Score 통계\n")
    if "anomaly_score" in result.data.columns:
        score = result.data["anomaly_score"]
        lines.append(f"- Mean: {score.mean():.4f}")
        lines.append(f"- Median: {score.median():.4f}")
        lines.append(f"- Max: {score.max():.4f}")
        lines.append(f"- >0.5 건수: {(score > 0.5).sum():,}")
        lines.append(f"- >0.7 건수: {(score > 0.7).sum():,}")

    return "\n".join(lines) + "\n"


def main():
    """E2E 파이프라인 실행 + 리포트 저장."""
    print(f"DataSynth E2E 시작: {DATA_CSV}")
    print(f"파일 크기: {DATA_CSV.stat().st_size / 1024 / 1024:.0f}MB")

    result = run_pipeline()

    print(f"\n완료: {result.elapsed:.2f}초")
    print(f"행수: {len(result.data):,}")
    print(f"위험도 분포: {result.risk_summary}")
    print(f"Warnings: {len(result.warnings)}건")

    report = generate_report(result)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_MD.write_text(report, encoding="utf-8")
    print(f"\n리포트 저장: {OUTPUT_MD}")


if __name__ == "__main__":
    main()
