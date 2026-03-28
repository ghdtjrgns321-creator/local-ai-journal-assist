"""감사 파이프라인 오케스트레이터 — Ingest → Validate → Feature → Detection → DB."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src.detection.base import DetectionResult

logger = logging.getLogger(__name__)
_TEXT_EXT = frozenset({".csv", ".tsv", ".txt", ".dat"})
_EXCEL_EXT = frozenset({".xlsx", ".xls", ".xlsb"})


@dataclass
class PipelineResult:
    """전체 파이프라인 실행 결과."""
    data: pd.DataFrame
    results: list[DetectionResult]
    risk_summary: dict[str, int]
    batch_id: str
    load_result: object | None
    elapsed: float
    warnings: list[str] = field(default_factory=list)
    # Why: 재탐지 시 피처 생성 단계를 건너뛰기 위해 피처 완료 시점 DF 캐싱
    featured_data: pd.DataFrame | None = field(default=None, repr=False)


class AuditPipeline:
    """감사 파이프라인 오케스트레이터."""

    def __init__(
        self, settings=None, *, skip_db: bool = False, conn=None,
        progress_callback=None,
    ) -> None:
        from config.settings import get_settings
        self._settings = settings or get_settings()
        self._skip_db = skip_db
        self._conn = conn
        # Why: 대시보드에서 st.progress 연동용. (pct: float, msg: str) → None
        self._progress = progress_callback or (lambda pct, msg: None)

    def run(self, path: str | Path) -> PipelineResult:
        """파일 경로 → 전체 파이프라인 실행."""
        start = time.monotonic()
        warns: list[str] = []
        df, w = self._ingest(path)
        warns.extend(w)
        return self._execute(df, uuid.uuid4().hex[:12], start, warns)

    def run_from_dataframe(self, df: pd.DataFrame) -> PipelineResult:
        """DataFrame 직접 입력 (ingest 생략).

        Why: 외부 df 원본 보호를 위해 copy() 후 파이프라인 진입.
        """
        return self._execute(df.copy(), uuid.uuid4().hex[:12], time.monotonic(), [])

    def redetect(
        self,
        df: pd.DataFrame,
        batch_id: str = "",
        weights: dict[str, float] | None = None,
        thresholds: dict[str, float] | None = None,
    ) -> PipelineResult:
        """피처 생성 완료 DF에서 detection + aggregate만 재실행.

        Why: 설정 변경 후 재탐지 시 _generate_features 중복 실행을 방지하여
             컬럼 충돌(_x, _y) 및 데이터 오염 차단.
        """
        start = time.monotonic()
        df = df.copy()
        results, warns = self._run_detection(df)

        from src.detection.score_aggregator import aggregate_scores
        agg_df = aggregate_scores(
            df, results, weights=weights, thresholds=thresholds, settings=self._settings,
        )
        for col in agg_df.columns:
            df[col] = agg_df[col].values

        risk_summary = df["risk_level"].value_counts().to_dict() if "risk_level" in df.columns else {}
        elapsed = time.monotonic() - start
        bid = batch_id or uuid.uuid4().hex[:12]
        logger.info("재탐지 완료: %.2fs, batch=%s", elapsed, bid)
        return PipelineResult(
            data=df, results=results, risk_summary=risk_summary,
            batch_id=bid, load_result=None, elapsed=elapsed, warnings=warns,
        )

    def _execute(
        self, df: pd.DataFrame, batch_id: str, start: float, warns: list[str],
    ) -> PipelineResult:
        """validate → feature → detection → aggregate → db."""
        self._progress(0.30, "데이터 검증 중...")
        df, w = self._validate(df)
        warns.extend(w)

        self._progress(0.45, "피처 생성 중...")
        df, w = self._generate_features(df)
        warns.extend(w)

        # Why: 재탐지(redetect)용 클린 DF 스냅샷 — detection 결과 컬럼 미포함 상태
        featured_snapshot = df.copy()

        self._progress(0.65, "탐지 룰 실행 중...")
        results, w = self._run_detection(df)
        warns.extend(w)

        self._progress(0.80, "점수 집계 중...")
        # Why: aggregate_scores는 별도 DF 반환. .values로 인덱스 불일치 방어.
        from src.detection.score_aggregator import aggregate_scores
        agg_df = aggregate_scores(df, results)
        for col in agg_df.columns:
            df[col] = agg_df[col].values

        load_result = None
        if not self._skip_db:
            self._progress(0.90, "DB 적재 중...")
            load_result, w = self._load_db(df, batch_id, results)
            warns.extend(w)

        risk_summary = df["risk_level"].value_counts().to_dict() if "risk_level" in df.columns else {}
        elapsed = time.monotonic() - start
        self._progress(1.0, "완료!")
        logger.info("파이프라인 완료: %.2fs, batch=%s", elapsed, batch_id)
        return PipelineResult(
            data=df, results=results, risk_summary=risk_summary,
            batch_id=batch_id, load_result=load_result, elapsed=elapsed, warnings=warns,
            featured_data=featured_snapshot,
        )

    def _ingest(self, path: str | Path) -> tuple[pd.DataFrame, list[str]]:
        """Full ingest pipeline: read → header detect → map → cast.

        Why: 기존 pd.read_csv 직접 호출 방식에서 전체 ingest 파이프라인으로 교체.
             외부 데이터(BPI, SAP 등)의 컬럼 매핑과 인코딩 감지를 자동 처리.
        """
        from src.ingest.column_mapper import auto_map_columns, prepare_dataframe
        from src.ingest.file_validator import validate_file
        from src.ingest.header_detector import detect_headers
        from src.ingest.reader_api import read_file
        from src.ingest.sheet_scorer import score_sheets
        from src.ingest.type_caster import cast_dataframe

        path = Path(path)
        warns: list[str] = []

        # Why: 파이프라인 진입 전 5단계 파일 검증 (확장자→빈파일→크기→무결성)
        validation = validate_file(path)
        if not validation.is_valid:
            raise ValueError("; ".join(validation.errors))
        warns.extend(validation.warnings)

        self._progress(0.05, "파일 읽는 중...")
        read_result = read_file(path)

        # Why: Parquet은 타입이 이미 확정된 포맷이므로 헤더 탐지 불필요
        if read_result.source_format == "parquet":
            sheet_name = read_result.active_sheet
            data_df = read_result.raw_data[sheet_name]
            source_columns = list(data_df.columns)
            matched_keywords: list[str] = []
        else:
            self._progress(0.08, "헤더 탐지 중...")
            header_results = detect_headers(read_result)
            sheet_scores = score_sheets(read_result, header_results)

            recommended = next((s for s in sheet_scores if s.recommended), None)
            sheet_name = recommended.sheet_name if recommended else read_result.active_sheet

            header_result = header_results[sheet_name]
            raw_df = read_result.raw_data[sheet_name]

            if header_result.header_row is not None:
                source_columns, data_df = prepare_dataframe(raw_df, header_result.header_row)
                matched_keywords = header_result.matched_keywords
            else:
                warns.append("헤더 탐지 실패 — 첫 행을 헤더로 사용")
                source_columns = [str(c) for c in raw_df.columns]
                data_df = raw_df
                matched_keywords = []

        self._progress(0.12, "컬럼 매핑 중...")
        mapping_result = auto_map_columns(
            source_columns, matched_keywords, data_df=data_df,
        )

        if mapping_result.missing_required:
            warns.append(f"필수 컬럼 미매핑: {mapping_result.missing_required}")

        # Why: CLI/test 모드에서는 사용자 확인 없이 best-effort 매핑 적용
        all_mapping = {**mapping_result.mapping, **mapping_result.suggestions}
        df = data_df.rename(columns=all_mapping)

        self._progress(0.15, "타입 캐스팅 중...")
        cast_result = cast_dataframe(df)
        df = cast_result.data
        warns.extend(cast_result.warnings)
        if cast_result.errors:
            warns.extend(cast_result.errors)

        return df, warns

    def _validate(self, df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
        from src.validation import validate_accounting, validate_schema
        warns: list[str] = []
        sr = validate_schema(df)
        if not sr.is_valid:
            raise ValueError(f"L1 구조 검증 실패: {[e.get('check', str(e)) for e in sr.errors]}")
        if sr.warnings:
            warns.extend(w.get("issue", str(w)) for w in sr.warnings)
        acct = validate_accounting(df)
        if not acct.balance_check:
            warns.append(f"대차불일치 {len(acct.unbalanced_docs)}건 (차이 {acct.balance_diff:.2f})")
        if acct.duplicate_entries > 0:
            warns.append(f"중복 행 {acct.duplicate_entries}건")
        return df, warns

    def _generate_features(self, df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
        from config.settings import get_audit_rules
        from src.feature.engine import generate_all_features
        feat = generate_all_features(df, settings=self._settings, rules=get_audit_rules())
        warns = [f"피처 미생성: {feat.missing_columns}"] if feat.missing_columns else []
        return feat.data, warns

    def _run_detection(self, df: pd.DataFrame) -> tuple[list[DetectionResult], list[str]]:
        from src.detection.anomaly_layer import AnomalyDetector
        from src.detection.benford_detector import BenfordDetector
        from src.detection.fraud_layer import FraudLayer
        from src.detection.integrity_layer import IntegrityDetector
        warns: list[str] = []
        results: list[DetectionResult] = []
        for det in [IntegrityDetector(self._settings), FraudLayer(self._settings),
                     AnomalyDetector(self._settings), BenfordDetector(self._settings)]:
            try:
                results.append(det.detect(df))
            except Exception:
                logger.warning("탐지 실패: %s", det.track_name, exc_info=True)
                warns.append(f"탐지 실패: {det.track_name}")
        return results, warns

    def _load_db(self, df, batch_id, results) -> tuple[object | None, list[str]]:
        conn, own_conn = self._conn, self._conn is None
        try:
            if own_conn:
                from src.db.connection import get_connection
                conn = get_connection()
            from src.db.loader import load_all
            return load_all(conn, df, batch_id, results), []
        except Exception:
            logger.warning("DB 적재 실패", exc_info=True)
            return None, ["DB 적재 실패"]
        finally:
            # Why: 자체 생성 커넥션만 close. 주입된 커넥션(own_conn=False)은 호출자 관리.
            # close_connection()은 전역 싱글톤 리셋 → 다음 get_connection()이 재생성.
            if own_conn and conn is not None:
                from src.db.connection import close_connection
                close_connection()
