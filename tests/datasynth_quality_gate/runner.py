"""DataSynth 전수 품질검사 오케스트레이터."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import duckdb

from .models import CheckResult, QualityGateReport, TierSummary
from .report import save_report

# Why: 프로젝트 루트 기준 상대 경로
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data" / "journal" / "primary" / "datasynth"
CSV_PATH = DATA_DIR / "journal_entries.csv"
LABELS_PATH = DATA_DIR / "labels" / "anomaly_labels.csv"
CHANGE_LOG_PATH = DATA_DIR / "change_log.csv"
COA_PATH = DATA_DIR / "chart_of_accounts.json"

TIER_NAMES = {
    1: "구조적 무결성",
    2: "값 도메인 + 비즈니스 논리",
    3: "교차검증",
    4: "분포 + config 정합",
    5: "라벨 + Silent Failure + 메타데이터",
    6: "메타데이터 교차검증",
}


def _load_data(con: duckdb.DuckDBPyConnection) -> None:
    """CSV 및 보조 데이터를 DuckDB 테이블로 로드."""
    if not CSV_PATH.exists():
        print(f"  [FAIL] CSV 파일 없음: {CSV_PATH}")
        sys.exit(1)

    print(f"  CSV 로드: {CSV_PATH}")
    con.execute(f"""
        CREATE TABLE je AS
        SELECT * FROM read_csv_auto('{CSV_PATH.as_posix()}',
                                     header=true, sample_size=-1)
    """)
    row_count = con.execute("SELECT COUNT(*) FROM je").fetchone()[0]
    print(f"  → {row_count:,}행 로드 완료")

    # 라벨
    if LABELS_PATH.exists():
        con.execute(f"""
            CREATE TABLE labels AS
            SELECT * FROM read_csv_auto('{LABELS_PATH.as_posix()}',
                                         header=true, sample_size=-1)
        """)
        label_count = con.execute("SELECT COUNT(*) FROM labels").fetchone()[0]
        print(f"  → 라벨 {label_count:,}건 로드")

    # change_log — Stage 2 이후 생성. 없으면 SKIP
    if CHANGE_LOG_PATH.exists():
        con.execute(f"""
            CREATE TABLE change_log AS
            SELECT * FROM read_csv_auto('{CHANGE_LOG_PATH.as_posix()}',
                                         header=true, sample_size=-1)
        """)
        cl_count = con.execute("SELECT COUNT(*) FROM change_log").fetchone()[0]
        print(f"  → change_log {cl_count:,}건 로드")

    # CoA — CSV 우선, JSON 폴백
    coa_csv = PROJECT_ROOT / "config" / "chart_of_accounts.csv"
    if coa_csv.exists():
        con.execute(f"""
            CREATE TABLE coa AS
            SELECT CAST(gl_account AS VARCHAR) as gl_account
            FROM read_csv_auto('{coa_csv.as_posix()}', header=true)
            WHERE gl_account IS NOT NULL
        """)
        coa_count = con.execute("SELECT COUNT(*) FROM coa").fetchone()[0]
        print(f"  → CoA {coa_count:,}건 로드 (CSV)")
    elif COA_PATH.exists():
        con.execute(f"""
            CREATE TABLE coa AS
            SELECT CAST(account_number AS VARCHAR) as gl_account
            FROM read_json_auto('{COA_PATH.as_posix()}')
        """)
        coa_count = con.execute("SELECT COUNT(*) FROM coa").fetchone()[0]
        print(f"  → CoA {coa_count:,}건 로드 (JSON)")


def _run_tier(tier_num: int, con: duckdb.DuckDBPyConnection) -> TierSummary:
    """지정된 Tier 실행. 미구현 Tier는 SKIP 처리."""
    checks: list[CheckResult] = []

    # Why: 동적 import로 필요한 Tier만 로드. 미구현 모듈은 SKIP
    try:
        if tier_num == 1:
            from .checks.tier1_structural import run_tier1
            checks = run_tier1(con, con)
        elif tier_num == 2:
            from .checks.tier2_domain import run_tier2
            checks = run_tier2(con, con)
        elif tier_num == 3:
            from .checks.tier3_crossref import run_tier3
            checks = run_tier3(con)
        elif tier_num == 4:
            from .checks.tier4_distribution import run_tier4
            checks = run_tier4(con)
        elif tier_num == 5:
            from .checks.tier5_label import run_tier5
            checks = run_tier5(con)
        elif tier_num == 6:
            from .checks.tier6_metadata import run_tier6
            checks = run_tier6(con)
    except ImportError:
        # Why: Tier 3~5 등 미구현 모듈은 SKIP으로 기록
        checks = [
            CheckResult(
                check_id=f"T{tier_num}-00",
                tier=tier_num,
                name=f"Tier {tier_num} 모듈 미구현",
                status="SKIP",
                expected="모듈 존재",
                actual="ImportError -- 미구현",
            )
        ]

    return TierSummary(
        tier=tier_num,
        name=TIER_NAMES.get(tier_num, f"Tier {tier_num}"),
        checks=checks,
    )


def run(
    tiers: list[int] | None = None,
    stop_on_fail: bool = True,
) -> QualityGateReport:
    """전수검사 실행."""
    start = time.perf_counter()
    tiers = tiers or [1, 2, 3, 4, 5]

    print("=" * 70)
    print("DataSynth 전수 품질검사")
    print("=" * 70)

    # DuckDB 로드
    con = duckdb.connect(":memory:")
    print("\n[데이터 로드]")
    _load_data(con)

    total_rows = con.execute("SELECT COUNT(*) FROM je").fetchone()[0]
    total_docs = con.execute(
        "SELECT COUNT(DISTINCT document_id) FROM je"
    ).fetchone()[0]

    report = QualityGateReport(
        data_file=str(CSV_PATH),
        total_rows=total_rows,
        total_documents=total_docs,
    )

    # Tier 순차 실행
    for tier_num in sorted(tiers):
        print(f"\n[Tier {tier_num}: {TIER_NAMES.get(tier_num, '')}]")
        tier_start = time.perf_counter()

        try:
            summary = _run_tier(tier_num, con)
        except Exception as e:
            print(f"  [ERROR] Tier {tier_num} 실행 실패: {e}")
            summary = TierSummary(
                tier=tier_num, name=TIER_NAMES.get(tier_num, "")
            )
            report.tiers.append(summary)
            if stop_on_fail:
                print("  → stop_on_fail: 후속 Tier 중단")
                break
            continue

        report.tiers.append(summary)
        tier_elapsed = time.perf_counter() - tier_start

        # 콘솔 요약
        print(
            f"  Pass={summary.pass_count} Fail={summary.fail_count} "
            f"Warning={summary.warning_count} Skip={summary.skip_count} "
            f"[{tier_elapsed:.1f}s] → {summary.verdict}"
        )

        # T1 blocking — FAIL 시 후속 차단
        if tier_num == 1 and summary.verdict == "FAIL" and stop_on_fail:
            print("  [BLOCKED] Tier 1 FAIL -- 후속 Tier 차단")
            break

    con.close()

    report.elapsed_seconds = time.perf_counter() - start

    # 리포트 저장
    print("\n[리포트 저장]")
    json_path, md_path = save_report(report)
    print(f"  JSON: {json_path}")
    print(f"  MD:   {md_path}")

    # 최종 요약
    print(f"\n{'=' * 70}")
    print(f"판정: {report.overall_verdict} ({report.elapsed_seconds:.1f}s)")
    print(f"{'=' * 70}")

    return report


def main() -> None:
    """CLI 엔트리포인트."""
    parser = argparse.ArgumentParser(description="DataSynth 전수 품질검사")
    parser.add_argument(
        "--tiers",
        type=str,
        default="1,2,3,4,5,6",
        help="실행할 Tier (예: 1,2,3)",
    )
    parser.add_argument(
        "--no-stop",
        action="store_true",
        help="Tier 1 실패해도 계속 실행",
    )
    args = parser.parse_args()

    tiers = [int(t.strip()) for t in args.tiers.split(",")]
    report = run(tiers=tiers, stop_on_fail=not args.no_stop)

    sys.exit(0 if report.overall_verdict != "FAIL" else 1)


if __name__ == "__main__":
    main()
