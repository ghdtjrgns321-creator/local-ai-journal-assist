"""DuckDB 데이터 적재 — detection 파이프라인 출력물 → 4개 테이블.

Why: score_aggregator 출력(DataFrame + DetectionResult)을 DuckDB에 적재하여
     대시보드(07-dashboard)와 Text-to-SQL(08-llm)의 데이터 소스로 제공한다.
     load_all()이 트랜잭션으로 원자적 적재를 보장한다.

Gotcha — DuckDB pandas 직결합 변수 스코프:
    conn.execute("INSERT INTO t SELECT * FROM df")에서 SQL 내 'df'는
    파이썬 로컬 변수명을 Introspection으로 직접 참조한다.
    SQL 변수명 = 파이썬 로컬 변수명 100% 일치 필수. 불일치 시 Catalog Error.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import pandas as pd

from src.db.schema import (
    ANOMALY_FLAGS_COLUMNS,
    BENFORD_DIGITS_COLUMNS,
    BENFORD_SUMMARY_COLUMNS,
    GENERAL_LEDGER_COLUMNS,
)

logger = logging.getLogger(__name__)

# Why: TYPE_CHECKING 블록으로 순환 import 방지 + 런타임 비용 제거
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb

    from src.detection.base import DetectionResult
    from src.validation.models import BenfordResult


# ── 결과 dataclass ────────────────────────────────────────────


@dataclass
class LoadResult:
    """4개 테이블 적재 결과 통합."""

    batch_id: str
    general_ledger_rows: int
    anomaly_flags_rows: int
    benford_summary_rows: int
    benford_digits_rows: int
    elapsed_seconds: float
    warnings: list[str] = field(default_factory=list)

    @property
    def total_rows(self) -> int:
        return (
            self.general_ledger_rows
            + self.anomaly_flags_rows
            + self.benford_summary_rows
            + self.benford_digits_rows
        )

    @property
    def is_success(self) -> bool:
        return self.general_ledger_rows > 0


# ── public API ────────────────────────────────────────────────


def load_all(
    conn: duckdb.DuckDBPyConnection,
    df: pd.DataFrame,
    results: list[DetectionResult],
    batch_id: str,
) -> LoadResult:
    """4개 테이블 원자적 적재 (트랜잭션).

    Why: general_ledger만 적재되고 anomaly_flags 실패 시 불일치 방지.
    """
    start = time.monotonic()
    warnings: list[str] = []

    conn.execute("BEGIN TRANSACTION")
    try:
        gl_rows = load_general_ledger(conn, df, batch_id)
        af_rows = load_anomaly_flags(conn, results, df, batch_id)
        bs_rows, bd_rows, bf_warnings = load_benford(conn, results, batch_id)
        warnings.extend(bf_warnings)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    elapsed = time.monotonic() - start
    logger.info(
        "적재 완료 [%s]: GL=%d, AF=%d, BS=%d, BD=%d (%.2fs)",
        batch_id, gl_rows, af_rows, bs_rows, bd_rows, elapsed,
    )

    return LoadResult(
        batch_id=batch_id,
        general_ledger_rows=gl_rows,
        anomaly_flags_rows=af_rows,
        benford_summary_rows=bs_rows,
        benford_digits_rows=bd_rows,
        elapsed_seconds=elapsed,
        warnings=warnings,
    )


def load_general_ledger(
    conn: duckdb.DuckDBPyConnection,
    df: pd.DataFrame,
    batch_id: str,
) -> int:
    """DataFrame을 general_ledger 테이블에 적재한다.

    reindex로 DDL 컬럼 순서 정합성을 보장한다.
    StrEnum risk_level은 명시적 str 변환 후 적재한다.
    """
    if df.empty:
        return 0

    df = df.copy()

    # Why: score_aggregator의 classify_risk_level()이 RiskLevel StrEnum 반환.
    #      DuckDB Introspection이 StrEnum → VARCHAR 자동 변환을 보장하지 않음.
    if "risk_level" in df.columns:
        df["risk_level"] = df["risk_level"].astype(str)

    df["upload_batch_id"] = batch_id
    # Why: created_at은 DuckDB DEFAULT로 자동 생성 → reindex에서 제외
    gl_df = df.reindex(columns=GENERAL_LEDGER_COLUMNS)

    # Why: created_at은 DEFAULT이므로 INSERT 대상에서 제외.
    #      SELECT *는 DataFrame 컬럼 수와 DDL 컬럼 수 불일치 시 BinderError 발생.
    col_list = ", ".join(GENERAL_LEDGER_COLUMNS)
    conn.execute(f"INSERT INTO general_ledger ({col_list}) SELECT * FROM gl_df")
    return len(gl_df)


def load_anomaly_flags(
    conn: duckdb.DuckDBPyConnection,
    results: list[DetectionResult],
    df: pd.DataFrame,
    batch_id: str,
) -> int:
    """DetectionResult.details를 melt하여 anomaly_flags에 적재한다.

    Why: RuleFlag는 룰별 요약만 보유. 행별 score는 details DataFrame에만 존재.
         details(columns=룰ID, values=float)를 melt → score > 0인 행만 추출.
    """
    flags_df = _build_anomaly_flags_df(results, df, batch_id)
    if flags_df.empty:
        return 0

    af_cols = ", ".join(ANOMALY_FLAGS_COLUMNS)
    conn.execute(f"INSERT INTO anomaly_flags ({af_cols}) SELECT * FROM flags_df")
    return len(flags_df)


def load_benford(
    conn: duckdb.DuckDBPyConnection,
    results: list[DetectionResult],
    batch_id: str,
) -> tuple[int, int, list[str]]:
    """Benford 분석 결과를 summary + digits 2개 테이블에 적재한다.

    Returns:
        (summary_rows, digits_rows, warnings)
    """
    warnings: list[str] = []
    benford_result = _extract_benford(results)

    if benford_result is None:
        warnings.append("BenfordResult 없음 (C07 스킵 또는 layer_c 미실행) — 0행 적재")
        return 0, 0, warnings

    summary_df = _build_benford_summary_df(benford_result, batch_id)
    digits_df = _build_benford_digits_df(benford_result, batch_id)

    bs_cols = ", ".join(BENFORD_SUMMARY_COLUMNS)
    bd_cols = ", ".join(BENFORD_DIGITS_COLUMNS)
    conn.execute(f"INSERT INTO benford_summary ({bs_cols}) SELECT * FROM summary_df")
    conn.execute(f"INSERT INTO benford_digits ({bd_cols}) SELECT * FROM digits_df")

    return len(summary_df), len(digits_df), warnings


# ── private helpers ───────────────────────────────────────────


def _build_anomaly_flags_df(
    results: list[DetectionResult],
    df: pd.DataFrame,
    batch_id: str,
) -> pd.DataFrame:
    """DetectionResult.details → anomaly_flags DataFrame 변환.

    Why: melt 벡터화로 100만행 × 22룰도 수초 내 처리. apply(axis=1) 회피.
    """
    empty = pd.DataFrame(columns=ANOMALY_FLAGS_COLUMNS)

    if not results:
        return empty

    chunks: list[pd.DataFrame] = []
    for result in results:
        if result.details.empty:
            continue

        melted = result.details.melt(
            ignore_index=False, var_name="rule_code", value_name="score",
        )
        melted = melted[melted["score"] > 0].copy()
        if melted.empty:
            continue

        # Why: .values 사용 시 인덱스 정렬 우회 → 불일치 위험. 인덱스 기반 할당 사용.
        melted["document_id"] = df.loc[melted.index, "document_id"]
        melted["line_number"] = (
            df.loc[melted.index, "line_number"]
            if "line_number" in df.columns
            else None
        )
        melted["track_name"] = result.track_name
        melted["upload_batch_id"] = batch_id
        chunks.append(melted)

    if not chunks:
        return empty

    combined = pd.concat(chunks, ignore_index=True)
    return combined.reindex(columns=ANOMALY_FLAGS_COLUMNS)


def _extract_benford(results: list[DetectionResult]) -> BenfordResult | None:
    """results에서 layer_c의 BenfordResult를 추출한다.

    추출 경로: track_name="layer_c" → metadata["benford_result"]
    """
    for r in results:
        if r.track_name == "layer_c" and "benford_result" in r.metadata:
            return r.metadata["benford_result"]
    return None


def _build_benford_summary_df(
    br: BenfordResult,
    batch_id: str,
) -> pd.DataFrame:
    """BenfordResult → benford_summary 1행 DataFrame."""
    row = {
        "upload_batch_id": batch_id,
        "sample_size": br.sample_size,
        "mad": br.mad,
        "mad_conformity": br.mad_conformity,
        # DDL 컬럼명(chi2_p_value) = BenfordResult 필드명(chi2_p_value) — 동일
        "chi2_statistic": br.chi2_statistic,
        "chi2_p_value": br.chi2_p_value,
        "ks_statistic": br.ks_statistic,
        "ks_p_value": br.ks_p_value,
        "is_conforming": br.is_conforming,
        "confidence": br.confidence,
    }
    return pd.DataFrame([row]).reindex(columns=BENFORD_SUMMARY_COLUMNS)


def _build_benford_digits_df(
    br: BenfordResult,
    batch_id: str,
) -> pd.DataFrame:
    """BenfordResult → benford_digits 9행 DataFrame."""
    rows = []
    for digit in range(1, 10):
        obs = br.observed.get(digit, 0.0)
        exp = br.expected.get(digit, 0.0)
        rows.append({
            "upload_batch_id": batch_id,
            "digit": digit,
            "observed_freq": obs,
            "expected_freq": exp,
            "deviation": obs - exp,
        })
    return pd.DataFrame(rows).reindex(columns=BENFORD_DIGITS_COLUMNS)
