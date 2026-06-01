"""DataFrame → DuckDB 적재 — 4개 테이블 트랜잭션 적재.

Why: detection 파이프라인 출력물(DataFrame + DetectionResult + BenfordResult)을
     DuckDB 4개 테이블에 원자적으로 적재하여 대시보드·Text-to-SQL이 조회한다.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src.db.schema import (
    ANOMALY_FLAGS_COLUMNS,
    BENFORD_DIGITS_COLUMNS,
    BENFORD_SUMMARY_COLUMNS,
    GENERAL_LEDGER_COLUMNS,
    ML_RESERVED_COLUMNS,
    TRIAL_BALANCE_COLUMNS,
)

logger = logging.getLogger(__name__)

# ── 승인 레벨 파생 (generation_principles.md §11 기준) ───────


def _derive_approval_level(
    df: pd.DataFrame,
    thresholds: list[int] | None = None,
) -> pd.Series:
    """전표 단위 차변 합산 → 전결규정 승인 레벨 (1~N).

    Why: 복식부기에서 sum(debit) = sum(credit)이므로 한쪽만 합산하면
         전표의 총 거래 금액(Total Transaction Value)을 구할 수 있다.

    경계 규칙: doc_amount <= thresholds[i] 이면 레벨 i+1.
               모든 임계값 초과 시 max_level(N)에 캡.
    """
    if thresholds is None:
        from config.settings import get_settings

        thresholds = get_settings().approval_thresholds

    if not thresholds:
        raise ValueError("approval_thresholds가 비어 있습니다.")

    # Why: 복식부기 — 차변 합계 = 대변 합계이므로 debit만 합산
    debit = pd.to_numeric(df["debit_amount"], errors="coerce").fillna(0)
    if "credit_amount" in df.columns:
        credit = pd.to_numeric(df["credit_amount"], errors="coerce").fillna(0)
        doc_debit = debit.groupby(df["document_id"]).transform("sum")
        doc_credit = credit.groupby(df["document_id"]).transform("sum")
        doc_amount = pd.concat([doc_debit, doc_credit], axis=1).max(axis=1)
    else:
        doc_amount = debit.groupby(df["document_id"]).transform("sum")

    max_level = len(thresholds)
    level = pd.Series(max_level, index=df.index)
    for i in range(max_level - 1, -1, -1):
        level = level.where(doc_amount > thresholds[i], i + 1)
    return level


# ── 결과 dataclass ───────────────────────────────────────────


@dataclass
class LoadResult:
    """코어 + 보조 테이블 적재 결과 통합."""

    batch_id: str
    general_ledger_rows: int
    anomaly_flags_rows: int
    benford_summary_rows: int
    benford_digits_rows: int
    elapsed_seconds: float
    trial_balance_rows: int = 0
    supplementary_counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def total_rows(self) -> int:
        return (
            self.general_ledger_rows
            + self.anomaly_flags_rows
            + self.benford_summary_rows
            + self.benford_digits_rows
            + self.trial_balance_rows
            + sum(self.supplementary_counts.values())
        )

    @property
    def is_success(self) -> bool:
        return self.general_ledger_rows > 0


# ── 적재 함수 ────────────────────────────────────────────────


def load_all(
    conn,
    df: pd.DataFrame,
    batch_id: str,
    results: list | None = None,
    *,
    file_name: str = "",
    tb_df: pd.DataFrame | None = None,
    datasynth_dir: Path | None = None,
    phase2_training_report_id: str | None = None,
    phase2_inference_contract: dict | None = None,
    phase2_promotion_policy: dict | None = None,
    phase2_inference_mode: str | None = None,
    detector_statuses: list[dict] | None = None,
    phase1_case_ref: dict | None = None,
) -> LoadResult:
    """코어 + 보조 테이블 원자적 적재 (트랜잭션).

    Why: general_ledger만 적재되고 나머지 실패 시 불일치 방지.
         upload_batches에 배치 메타를 기록하여 재시작 후 이력 조회 지원.
         datasynth_dir가 제공되면 보조 데이터(document_flows, master_data 등)도 적재.
    """
    if results is None:
        results = []

    start = time.monotonic()
    warnings: list[str] = []
    sup_counts: dict[str, int] = {}

    conn.execute("BEGIN TRANSACTION")
    try:
        gl_rows = load_general_ledger(conn, df, batch_id)
        af_rows = load_anomaly_flags(conn, results, df, batch_id)
        bs_rows, bd_rows, bf_warnings = load_benford(conn, results, batch_id)
        warnings.extend(bf_warnings)
        tb_rows = load_trial_balance(conn, tb_df, batch_id) if tb_df is not None else 0

        # Why: DataSynth 보조 데이터 적재 (document_flows, master_data, labels 등)
        if datasynth_dir is not None:
            from src.db.loader_supplementary import load_supplementary

            sup_counts = load_supplementary(conn, datasynth_dir, batch_id)

        # Why: 배치 메타 기록 — Streamlit 재시작 후 이력 조회/복원용
        high_count = int(df["risk_level"].eq("High").sum()) if "risk_level" in df.columns else 0
        conn.execute(
            "INSERT INTO upload_batches "
            "("
            "upload_batch_id, file_name, row_count, anomaly_count, high_risk_count, "
            "phase2_training_report_id, phase2_inference_contract, phase2_promotion_policy, "
            "phase2_inference_mode, detector_statuses_json, "
            "phase1_case_run_id, phase1_case_path, phase1_case_count, "
            "phase1_macro_finding_count, phase1_top_theme_ids, phase1_case_schema_version, "
            "warnings"
            ") "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                batch_id,
                file_name,
                gl_rows,
                af_rows,
                high_count,
                phase2_training_report_id,
                _serialize_json_value(phase2_inference_contract),
                _serialize_json_value(phase2_promotion_policy),
                phase2_inference_mode,
                _serialize_json_value(detector_statuses),
                (phase1_case_ref or {}).get("phase1_case_run_id"),
                (phase1_case_ref or {}).get("phase1_case_path"),
                int((phase1_case_ref or {}).get("phase1_case_count", 0) or 0),
                int((phase1_case_ref or {}).get("phase1_macro_finding_count", 0) or 0),
                _serialize_json_value((phase1_case_ref or {}).get("top_theme_ids")),
                (phase1_case_ref or {}).get("phase1_case_schema_version"),
                ";".join(bf_warnings),
            ],
        )

        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    elapsed = time.monotonic() - start
    return LoadResult(
        batch_id=batch_id,
        general_ledger_rows=gl_rows,
        anomaly_flags_rows=af_rows,
        benford_summary_rows=bs_rows,
        benford_digits_rows=bd_rows,
        elapsed_seconds=elapsed,
        trial_balance_rows=tb_rows,
        supplementary_counts=sup_counts,
        warnings=warnings,
    )


def update_upload_batch_meta(
    conn,
    batch_id: str,
    *,
    phase2_training_report_id: str | None = None,
    phase2_inference_contract: dict | None = None,
    phase2_promotion_policy: dict | None = None,
    phase2_inference_mode: str | None = None,
    detector_statuses: list[dict] | None = None,
) -> None:
    """Update persisted batch-level analysis metadata after inference completes."""
    _ensure_upload_batch_meta_columns(conn)
    conn.execute(
        """
        UPDATE upload_batches
        SET
            phase2_training_report_id = ?,
            phase2_inference_contract = ?,
            phase2_promotion_policy = ?,
            phase2_inference_mode = ?,
            detector_statuses_json = ?
        WHERE upload_batch_id = ?
        """,
        [
            phase2_training_report_id,
            _serialize_json_value(phase2_inference_contract),
            _serialize_json_value(phase2_promotion_policy),
            phase2_inference_mode,
            _serialize_json_value(detector_statuses),
            batch_id,
        ],
    )


_UPLOAD_BATCH_META_COLUMNS: dict[str, str] = {
    "phase2_training_report_id": "VARCHAR",
    "phase2_inference_contract": "JSON",
    "phase2_promotion_policy": "JSON",
    "phase2_inference_mode": "VARCHAR",
    "detector_statuses_json": "JSON",
}


def _ensure_upload_batch_meta_columns(conn) -> None:
    """Backfill Phase2 metadata columns for older engagement DB files.

    Older `audit.duckdb` files can have `upload_batches` without the Phase2
    restore columns. The inference service treats DB provenance persistence as
    best-effort, so a missing column used to drop all Phase2 metadata silently
    and refresh would show the inference button again.
    """
    existing = set(
        conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'upload_batches'"
        ).fetchdf()["column_name"]
    )
    for column, dtype in _UPLOAD_BATCH_META_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE upload_batches ADD COLUMN {column} {dtype}")


def _serialize_json_value(value):
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=str)


def load_general_ledger(conn, df: pd.DataFrame, batch_id: str) -> int:
    """DataFrame을 general_ledger 테이블에 적재.

    1. approval_level 파생 (전결규정 6단계)
    2. reindex로 DDL 컬럼 순서 정합성 보장
    3. StrEnum risk_level → str 명시적 변환
    """
    df = df.copy()
    df["upload_batch_id"] = batch_id

    # Why: approval_level은 DataSynth에 없는 파생 컬럼
    if "approval_level" not in df.columns:
        df["approval_level"] = _derive_approval_level(df)

    # Why: StrEnum → VARCHAR 자동 변환 미보장
    if "risk_level" in df.columns:
        df["risk_level"] = df["risk_level"].astype(str)

    gl_df = df.reindex(columns=GENERAL_LEDGER_COLUMNS)
    _fill_required_gl_fields(gl_df)

    # Why: reindex가 누락 ML 예약 컬럼에 NaN을 넣으면
    # VARCHAR는 'nan' 문자열 삽입, DOUBLE/TIMESTAMP도 방어적으로 None 통일
    for col in ML_RESERVED_COLUMNS:
        if col in gl_df.columns:
            gl_df[col] = gl_df[col].where(gl_df[col].notna(), None)

    col_list = ", ".join(GENERAL_LEDGER_COLUMNS)
    conn.execute(f"INSERT INTO general_ledger ({col_list}) SELECT * FROM gl_df")
    return len(gl_df)


def _fill_required_gl_fields(gl_df: pd.DataFrame) -> None:
    """Fill DB NOT NULL columns from nearby source fields before insert."""
    if "posting_date" in gl_df.columns:
        gl_df["posting_date"] = pd.to_datetime(gl_df["posting_date"], errors="coerce")
    if "document_date" in gl_df.columns:
        gl_df["document_date"] = pd.to_datetime(gl_df["document_date"], errors="coerce")

    if {"posting_date", "document_date"} <= set(gl_df.columns):
        missing_posting = gl_df["posting_date"].isna()
        if missing_posting.any():
            gl_df.loc[missing_posting, "posting_date"] = gl_df.loc[missing_posting, "document_date"]
            logger.warning(
                "posting_date missing for %d GL rows; filled from document_date",
                int(missing_posting.sum()),
            )

    if {"fiscal_period", "posting_date"} <= set(gl_df.columns):
        period = pd.to_numeric(gl_df["fiscal_period"], errors="coerce")
        missing_period = period.isna()
        if missing_period.any():
            period = period.where(~missing_period, gl_df["posting_date"].dt.month)
            logger.warning(
                "fiscal_period missing for %d GL rows; filled from posting_date month",
                int(missing_period.sum()),
            )
        gl_df["fiscal_period"] = period.fillna(0).astype("Int64")

    if "company_code" in gl_df.columns:
        missing_company = gl_df["company_code"].isna()
        if missing_company.any():
            mode = gl_df.loc[~missing_company, "company_code"].mode(dropna=True)
            fallback = mode.iloc[0] if not mode.empty else "UNKNOWN"
            gl_df.loc[missing_company, "company_code"] = fallback
            logger.warning(
                "company_code missing for %d GL rows; filled with %s",
                int(missing_company.sum()),
                fallback,
            )


def load_anomaly_flags(
    conn,
    results: list,
    df: pd.DataFrame,
    batch_id: str,
) -> int:
    """DetectionResult.details를 melt하여 anomaly_flags 테이블에 적재."""
    flags_df = _build_anomaly_flags_df(results, df, batch_id)
    if flags_df.empty:
        return 0
    af_cols = ", ".join(ANOMALY_FLAGS_COLUMNS)
    conn.execute(f"INSERT INTO anomaly_flags ({af_cols}) SELECT * FROM flags_df")
    return len(flags_df)


def load_benford(
    conn,
    results: list,
    batch_id: str,
) -> tuple[int, int, list[str]]:
    """Benford 분석 결과를 benford_summary + benford_digits에 적재."""
    warnings: list[str] = []
    benford = _extract_benford(results)

    if benford is None:
        warnings.append("BenfordResult 없음 — benford 테이블 0행 적재")
        return 0, 0, warnings

    summary_df = _build_benford_summary_df(benford, batch_id)
    bs_cols = ", ".join(BENFORD_SUMMARY_COLUMNS)
    conn.execute(f"INSERT INTO benford_summary ({bs_cols}) SELECT * FROM summary_df")

    digits_df = _build_benford_digits_df(benford, batch_id)
    bd_cols = ", ".join(BENFORD_DIGITS_COLUMNS)
    conn.execute(f"INSERT INTO benford_digits ({bd_cols}) SELECT * FROM digits_df")

    return len(summary_df), len(digits_df), warnings


def load_trial_balance(conn, tb_df: pd.DataFrame | None, batch_id: str) -> int:
    """Trial Balance를 trial_balance 테이블에 적재.

    Why: WU-13 TB 교차검증에서 생성된 계정별 집계 결과를 DB에 보존.
         대시보드 조회 및 YoY 비교용.
    """
    if tb_df is None or tb_df.empty:
        return 0
    tb_df = tb_df.copy()
    tb_df["upload_batch_id"] = batch_id
    tb_load = tb_df.reindex(columns=TRIAL_BALANCE_COLUMNS)
    col_list = ", ".join(TRIAL_BALANCE_COLUMNS)
    conn.execute(f"INSERT INTO trial_balance ({col_list}) SELECT * FROM tb_load")
    return len(tb_load)


# ── 내부 헬퍼 ────────────────────────────────────────────────


def _build_anomaly_flags_df(
    results: list,
    df: pd.DataFrame,
    batch_id: str,
) -> pd.DataFrame:
    """DetectionResult.details → anomaly_flags DataFrame 변환."""
    empty = pd.DataFrame(columns=ANOMALY_FLAGS_COLUMNS)
    if not results:
        return empty

    chunks: list[pd.DataFrame] = []
    for result in results:
        if not hasattr(result, "details") or result.details.empty:
            continue
        melted = result.details.melt(
            ignore_index=False,
            var_name="rule_code",
            value_name="score",
        )
        melted["score"] = pd.to_numeric(melted["score"], errors="coerce")
        melted = melted[melted["score"] > 0].copy()
        if melted.empty:
            continue
        melted["document_id"] = df.loc[melted.index, "document_id"]
        melted["line_number"] = (
            df.loc[melted.index, "line_number"] if "line_number" in df.columns else None
        )
        melted["track_name"] = result.track_name
        melted["upload_batch_id"] = batch_id
        chunks.append(melted)

    if not chunks:
        return empty
    combined = pd.concat(chunks, ignore_index=True)
    return combined.reindex(columns=ANOMALY_FLAGS_COLUMNS)


def _extract_benford(results: list):
    """results에서 BenfordResult를 추출.

    Why: Benford 독립 트랙(track_name='benford') 또는
         layer_c 내장 benford_result 두 경로 모두 지원.
    """
    # 1순위: 독립 benford 트랙
    for r in results:
        if (
            hasattr(r, "track_name")
            and r.track_name == "benford"
            and hasattr(r, "metadata")
            and "benford_result" in r.metadata
        ):
            return r.metadata["benford_result"]
    # 2순위: layer_c 내장 (레거시)
    for r in results:
        if (
            hasattr(r, "track_name")
            and r.track_name == "layer_c"
            and hasattr(r, "metadata")
            and "benford_result" in r.metadata
        ):
            return r.metadata["benford_result"]
    return None


def _build_benford_summary_df(br, batch_id: str) -> pd.DataFrame:
    """BenfordResult → benford_summary DataFrame (배치당 1행)."""
    return pd.DataFrame(
        [
            {
                "upload_batch_id": batch_id,
                "sample_size": br.sample_size,
                "mad": br.mad,
                "mad_conformity": br.mad_conformity,
                "chi2_statistic": br.chi2_statistic,
                "chi2_p_value": br.chi2_p_value,
                "ks_statistic": br.ks_statistic,
                "ks_p_value": br.ks_p_value,
                "is_conforming": br.is_conforming,
                "confidence": br.confidence,
            }
        ]
    ).reindex(columns=BENFORD_SUMMARY_COLUMNS)


def _build_benford_digits_df(br, batch_id: str) -> pd.DataFrame:
    """BenfordResult → benford_digits DataFrame (자릿수별 9행)."""
    rows = []
    for digit in range(1, 10):
        obs = br.observed.get(digit, 0.0)
        exp = br.expected.get(digit, 0.0)
        rows.append(
            {
                "upload_batch_id": batch_id,
                "digit": digit,
                "observed_freq": obs,
                "expected_freq": exp,
                "deviation": obs - exp,
            }
        )
    return pd.DataFrame(rows).reindex(columns=BENFORD_DIGITS_COLUMNS)
