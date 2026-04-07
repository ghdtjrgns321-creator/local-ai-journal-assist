"""ML Fitting 방지 품질 게이트 러너."""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import duckdb

from .models import CheckResult, QualityGateReport, TierSummary
from .report import TIER_NAMES, save_report

_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "journal" / "primary" / "datasynth"
_CSV_PATH = _DATA_DIR / "journal_entries.csv"


def _load_data(con: duckdb.DuckDBPyConnection) -> tuple[int, int]:
    """CSV 로드 후 (행수, 전표수) 반환."""
    print(f"  CSV 로드: {_CSV_PATH}")
    con.execute(f"""
        CREATE TABLE je AS
        SELECT * FROM read_csv_auto('{_CSV_PATH.as_posix()}', all_varchar=true)
    """)
    total_rows = con.execute("SELECT COUNT(*) FROM je").fetchone()[0]
    total_docs = con.execute(
        "SELECT COUNT(DISTINCT document_id) FROM je"
    ).fetchone()[0]
    print(f"  총 {total_rows:,}행, {total_docs:,} 전표 로드 완료")
    return total_rows, total_docs


def _run_tier(tier_num: int, con: duckdb.DuckDBPyConnection) -> TierSummary:
    """특정 Tier 실행."""
    name = TIER_NAMES.get(tier_num, f"Tier {tier_num}")
    summary = TierSummary(tier=tier_num, name=name)
    start = time.perf_counter()

    try:
        if tier_num == 1:
            from .checks.tier1_leakage import run_tier1
            checks = run_tier1(con)
        elif tier_num == 2:
            from .checks.tier2_distribution import run_tier2
            checks = run_tier2(con)
        elif tier_num == 3:
            from .checks.tier3_crossfield import run_tier3
            checks = run_tier3(con)
        elif tier_num == 4:
            from .checks.tier4_reverse_leakage import run_tier4
            checks = run_tier4(con)
        elif tier_num == 5:
            from .checks.tier5_compound import run_tier5
            checks = run_tier5(con)
        elif tier_num == 6:
            from .checks.tier6_line_structure import run_tier6
            checks = run_tier6(con)
        else:
            checks = [CheckResult(
                check_id=f"L{tier_num}-00", tier=tier_num,
                name="미구현", status="SKIP",
                expected="", actual="미구현 Tier",
            )]
    except Exception as e:
        elapsed = (time.perf_counter() - start) * 1000
        checks = [CheckResult(
            check_id=f"L{tier_num}-ERR", tier=tier_num,
            name="실행 오류", status="FAIL",
            expected="정상 실행", actual=str(e)[:200],
            elapsed_ms=elapsed,
        )]
        print(f"  [ERROR] Tier {tier_num} 실행 실패: {e}")

    summary.checks = checks
    elapsed_s = time.perf_counter() - start

    status_counts = (
        f"Pass={summary.pass_count} Fail={summary.fail_count} "
        f"Warning={summary.warning_count} Skip={summary.skip_count}"
    )
    print(f"  {status_counts} [{elapsed_s:.1f}s] >> {summary.verdict}")
    return summary


def run(tiers: list[int] | None = None) -> QualityGateReport:
    """품질 게이트 실행."""
    overall_start = time.perf_counter()

    con = duckdb.connect()
    print("\n[데이터 로드]")
    total_rows, total_docs = _load_data(con)

    report = QualityGateReport(
        data_file=str(_CSV_PATH),
        total_rows=total_rows,
        total_documents=total_docs,
    )

    tier_list = tiers or [1, 2, 3, 4, 5, 6]
    for tier_num in tier_list:
        print(f"\n[Tier {tier_num}: {TIER_NAMES.get(tier_num, '?')}]")
        summary = _run_tier(tier_num, con)
        report.tiers.append(summary)

    report.elapsed_seconds = time.perf_counter() - overall_start

    print("\n[리포트 저장]")
    json_path, md_path = save_report(report)
    print(f"  JSON: {json_path}")
    print(f"  MD:   {md_path}")

    verdict_display = report.overall_verdict
    print(f"\n{'=' * 60}")
    print(f"판정: {verdict_display} ({report.elapsed_seconds:.1f}s)")
    print(f"{'=' * 60}")

    con.close()
    return report


def main() -> None:
    """CLI 진입점."""
    parser = argparse.ArgumentParser(description="ML Fitting 방지 품질 게이트")
    parser.add_argument("--tiers", type=int, nargs="+", default=None)
    args = parser.parse_args()

    print("=" * 60)
    print("ML Fitting 방지 품질검사 (datasynth_quality_gate2)")
    print("=" * 60)
    run(tiers=args.tiers)
