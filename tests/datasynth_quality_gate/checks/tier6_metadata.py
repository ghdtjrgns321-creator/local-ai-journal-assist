"""Tier 6: 메타데이터 교차검증 — Rust 출력 JSON과 CSV 데이터 간 정합성."""
from __future__ import annotations

import json
import time
from pathlib import Path

import duckdb

from ..models import CheckResult

_DATA_ROOT = Path("data/journal/primary/datasynth")


def _elapsed(start: float) -> float:
    return (time.perf_counter() - start) * 1000


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _skip(check_id: str, name: str, reason: str = "파일 없음") -> CheckResult:
    return CheckResult(
        check_id=check_id, tier=6, name=name,
        status="SKIP", expected="-", actual=reason,
    )


# ---------------------------------------------------------------------------
# T6-01 ~ T6-05
# ---------------------------------------------------------------------------

def t6_01(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """generation_statistics.total_entries == CSV DISTINCT document_id."""
    s = time.perf_counter()
    stats = _load_json(_DATA_ROOT / "generation_statistics.json")
    if stats is None:
        return _skip("T6-01", "gen_stats 전표수")

    expected_entries = stats.get("total_entries", 0)
    actual_docs = con.execute(
        "SELECT COUNT(DISTINCT document_id) FROM je"
    ).fetchone()[0]

    # Why: Rust는 header 기준 카운트, CSV는 line 기준이므로 DISTINCT 비교
    diff = abs(expected_entries - actual_docs)
    # 허용: duplicate_entries(anomaly injection)로 인한 차이
    status = "PASS" if diff <= expected_entries * 0.02 else "WARNING"

    return CheckResult(
        check_id="T6-01", tier=6, name="gen_stats 전표수",
        status=status,
        expected=f"stats.total_entries={expected_entries:,}",
        actual=f"csv_distinct_docs={actual_docs:,} (diff={diff:,})",
        elapsed_ms=_elapsed(s),
    )


def t6_02(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """generation_statistics.total_line_items == CSV 총 행수."""
    s = time.perf_counter()
    stats = _load_json(_DATA_ROOT / "generation_statistics.json")
    if stats is None:
        return _skip("T6-02", "gen_stats 행수")

    expected_lines = stats.get("total_line_items", 0)
    actual_rows = con.execute("SELECT COUNT(*) FROM je").fetchone()[0]

    diff = abs(expected_lines - actual_rows)
    status = "PASS" if diff <= expected_lines * 0.02 else "WARNING"

    return CheckResult(
        check_id="T6-02", tier=6, name="gen_stats 행수",
        status=status,
        expected=f"stats.total_line_items={expected_lines:,}",
        actual=f"csv_rows={actual_rows:,} (diff={diff:,})",
        elapsed_ms=_elapsed(s),
    )


def t6_03(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """balance_validation 정합 — entries_processed ≈ CSV document 수."""
    s = time.perf_counter()
    bv = _load_json(_DATA_ROOT / "balance_validation.json")
    if bv is None:
        return _skip("T6-03", "balance_validation")

    processed = bv.get("entries_processed", 0)
    error_count = bv.get("validation_error_count", 0)
    actual_docs = con.execute(
        "SELECT COUNT(DISTINCT document_id) FROM je"
    ).fetchone()[0]

    # Why: balance tracker가 검증한 전표 수가 CSV 전표 수와 유사해야 함
    coverage = processed / actual_docs * 100 if actual_docs > 0 else 0
    status = "PASS" if coverage >= 90 else "WARNING"

    return CheckResult(
        check_id="T6-03", tier=6, name="balance_validation",
        status=status,
        expected="coverage≥90%",
        actual=f"processed={processed:,}/{actual_docs:,} ({coverage:.1f}%), errors={error_count:,}",
        elapsed_ms=_elapsed(s),
    )


def t6_04(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """run_manifest 완전성 — 필수 키 존재 + seed/config_hash 확인."""
    s = time.perf_counter()
    manifest = _load_json(_DATA_ROOT / "run_manifest.json")
    if manifest is None:
        return _skip("T6-04", "run_manifest")

    required_keys = ["run_id", "seed", "config_hash", "started_at", "completed_at"]
    missing = [k for k in required_keys if k not in manifest]
    has_seed = "seed" in manifest and manifest["seed"] is not None

    status = "PASS" if not missing and has_seed else "WARNING"

    return CheckResult(
        check_id="T6-04", tier=6, name="run_manifest",
        status=status,
        expected=f"필수 {len(required_keys)}키 + seed",
        actual=f"missing={missing}" if missing else f"OK (seed={manifest.get('seed')})",
        elapsed_ms=_elapsed(s),
    )


def t6_05(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """change_log 행수 교차검증 — CSV 행수 확인."""
    s = time.perf_counter()
    cl_path = _DATA_ROOT / "change_log.csv"
    if not cl_path.exists():
        return _skip("T6-05", "change_log 행수")

    try:
        cl_count = con.execute("SELECT COUNT(*) FROM change_log").fetchone()[0]
    except Exception:
        return _skip("T6-05", "change_log 행수", "테이블 미로드")

    # Why: change_log는 전표의 ~5% × 1.5건 ≈ 전표수 × 0.075
    actual_docs = con.execute(
        "SELECT COUNT(DISTINCT document_id) FROM je"
    ).fetchone()[0]
    expected_min = int(actual_docs * 0.01)  # 최소 1%
    expected_max = int(actual_docs * 0.20)  # 최대 20%

    status = "PASS" if expected_min <= cl_count <= expected_max else "WARNING"

    return CheckResult(
        check_id="T6-05", tier=6, name="change_log 행수",
        status=status,
        expected=f"{expected_min:,}~{expected_max:,}건",
        actual=f"{cl_count:,}건",
        elapsed_ms=_elapsed(s),
    )


# ---------------------------------------------------------------------------
# 엔트리포인트
# ---------------------------------------------------------------------------

def run_tier6(con: duckdb.DuckDBPyConnection) -> list[CheckResult]:
    """Tier 6 전체 체크 실행."""
    return [fn(con) for fn in [t6_01, t6_02, t6_03, t6_04, t6_05]]
