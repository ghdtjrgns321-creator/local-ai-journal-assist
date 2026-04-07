"""감사 파이프라인 오케스트레이터 — Ingest → Validate → Feature → Detection → DB."""

from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src.context import CompanyContext, ContextFactory
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
        self,
        context: CompanyContext | None = None,
        settings=None,
        *,
        skip_db: bool = False,
        conn=None,
        progress_callback=None,
        repo=None,
    ) -> None:
        # Why: context 우선 → settings 폴백 → anonymous 폴백 (하위 호환)
        if context is not None:
            self._ctx = context
        elif settings is not None:
            self._ctx = ContextFactory.from_settings(settings)
        else:
            self._ctx = ContextFactory.create_anonymous()
        self._settings = self._ctx.settings
        self._skip_db = skip_db
        self._conn = conn
        # Why: 대시보드에서 st.progress 연동용. (pct: float, msg: str) → None
        self._progress = progress_callback or (lambda pct, msg: None)
        # Why: Layer D(전기 대비 변동 탐지)에서 전기 engagement 탐색용.
        #      None이면 Layer D 자동 스킵 (하위 호환).
        self._repo = repo

    def _make_batch_id(self) -> str:
        """engagement 접두사 포함 batch_id 생성."""
        eid = self._ctx.engagement_id
        if self._ctx.is_anonymous:
            return uuid.uuid4().hex[:8]
        # Why: engagement_id에 "-", "/" 등 특수문자 → 파일 경로/SQL 에러 방지
        safe_eid = re.sub(r"[^a-zA-Z0-9]", "_", eid)
        return f"{safe_eid}_{uuid.uuid4().hex[:8]}"

    def run(self, path: str | Path) -> PipelineResult:
        """파일 경로 → 전체 파이프라인 실행."""
        start = time.monotonic()
        warns: list[str] = []
        df, w = self._ingest(path)
        warns.extend(w)
        return self._execute(df, self._make_batch_id(), start, warns)

    def run_from_dataframe(self, df: pd.DataFrame) -> PipelineResult:
        """DataFrame 직접 입력 (ingest 생략).

        Why: 외부 df 원본 보호를 위해 copy() 후 파이프라인 진입.
        """
        return self._execute(df.copy(), self._make_batch_id(), time.monotonic(), [])

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

        # Why: weights 미지정 시 Layer D 유무에 따라 가중치 자동 선택
        if weights is None:
            has_variance = any(r.track_name == "layer_d" for r in results)
            if has_variance:
                from src.detection.constants import LAYER_WEIGHTS_WITH_PRIOR
                weights = LAYER_WEIGHTS_WITH_PRIOR

        from src.detection.score_aggregator import aggregate_scores
        agg_df = aggregate_scores(
            df, results, weights=weights, thresholds=thresholds, settings=self._settings,
        )
        for col in agg_df.columns:
            df[col] = agg_df[col].values

        risk_summary = df["risk_level"].value_counts().to_dict() if "risk_level" in df.columns else {}
        elapsed = time.monotonic() - start
        bid = batch_id or self._make_batch_id()
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
        from src.detection.constants import LAYER_WEIGHTS_WITH_PRIOR
        from src.detection.score_aggregator import aggregate_scores
        # Why: Layer D 결과가 있으면 기존회사 가중치(5레이어) 사용, 없으면 기본(4레이어)
        has_variance = any(r.track_name == "layer_d" for r in results)
        weights = LAYER_WEIGHTS_WITH_PRIOR if has_variance else None
        agg_df = aggregate_scores(df, results, weights=weights)
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
            schema=self._ctx.schema,
            keywords=self._ctx.keywords,
        )

        if mapping_result.missing_required:
            warns.append(f"필수 컬럼 미매핑: {mapping_result.missing_required}")

        # Why: CLI/test 모드에서는 사용자 확인 없이 best-effort 매핑 적용
        all_mapping = {**mapping_result.mapping, **mapping_result.suggestions}
        df = data_df.rename(columns=all_mapping)

        self._progress(0.15, "타입 캐스팅 중...")
        cast_result = cast_dataframe(
            df,
            schema=self._ctx.schema,
            settings=self._ctx.settings,
            cleaning_config=self._ctx.cleaning_config,
        )
        df = cast_result.data
        warns.extend(cast_result.warnings)
        if cast_result.errors:
            warns.extend(cast_result.errors)

        return df, warns

    def _validate(self, df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
        from src.validation import validate_accounting, validate_schema
        warns: list[str] = []
        sr = validate_schema(df, schema=self._ctx.schema, settings=self._ctx.settings)
        if not sr.is_valid:
            # Why: 열 수 불일치 등으로 필수 컬럼에 NaN이 생긴 행을 드롭하고
            #      경고로 표시. 정상 행은 파이프라인을 계속 진행한다.
            not_null_errors = [e for e in sr.errors if e.get("check") == "not_nullable"]
            other_errors = [e for e in sr.errors if e.get("check") != "not_nullable"]

            if not_null_errors and not other_errors:
                # NaN 행만 드롭하여 복구 시도
                required_cols = [col for col in df.columns
                                 if col in {"document_id", "posting_date", "debit_amount",
                                            "credit_amount", "gl_account", "document_type",
                                            "fiscal_year", "fiscal_period", "document_date",
                                            "company_code"}]
                before = len(df)
                df = df.dropna(subset=required_cols, how="any").reset_index(drop=True)
                dropped = before - len(df)
                if dropped > 0:
                    warns.append(f"필수 컬럼 결측 {dropped}행 제거 (원본 {before}행 → {len(df)}행)")
                if len(df) == 0:
                    raise ValueError("L1 구조 검증 실패: 모든 행이 필수 컬럼 결측")
            else:
                raise ValueError(
                    f"L1 구조 검증 실패: {[e.get('check', str(e)) for e in sr.errors]}",
                )
        if sr.warnings:
            warns.extend(w.get("issue", str(w)) for w in sr.warnings)
        acct = validate_accounting(df)
        if not acct.balance_check:
            warns.append(f"대차불일치 {len(acct.unbalanced_docs)}건 (차이 {acct.balance_diff:.2f})")
        if acct.duplicate_entries > 0:
            warns.append(f"중복 행 {acct.duplicate_entries}건")
        return df, warns

    def _generate_features(self, df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
        from src.feature.engine import generate_all_features
        feat = generate_all_features(
            df,
            settings=self._ctx.settings,
            rules=self._ctx.audit_rules,
            risk_keywords=self._ctx.risk_keywords,
        )
        warns = [f"피처 미생성: {feat.missing_columns}"] if feat.missing_columns else []
        return feat.data, warns

    def _run_detection(self, df: pd.DataFrame) -> tuple[list[DetectionResult], list[str]]:
        from src.detection.anomaly_layer import AnomalyDetector
        from src.detection.benford_detector import BenfordDetector
        from src.detection.fraud_layer import FraudLayer
        from src.detection.integrity_layer import IntegrityDetector
        warns: list[str] = []
        results: list[DetectionResult] = []
        for det in [
            IntegrityDetector(self._ctx.settings, chart_of_accounts=self._ctx.chart_of_accounts, schema=self._ctx.schema),
            FraudLayer(self._ctx.settings, audit_rules=self._ctx.audit_rules),
            AnomalyDetector(self._ctx.settings),
            BenfordDetector(self._ctx.settings),
        ]:
            try:
                results.append(det.detect(df))
            except Exception:
                logger.warning("탐지 실패: %s", det.track_name, exc_info=True)
                warns.append(f"탐지 실패: {det.track_name}")

        # Why: Layer D는 기존회사 전용 — 조건 불충족 시 None 반환으로 graceful 스킵
        variance_result = self._try_variance_detection(df)
        if variance_result is not None:
            results.append(variance_result)

        return results, warns

    def _try_variance_detection(self, df: pd.DataFrame) -> DetectionResult | None:
        """Layer D(전기 대비 변동) 실행 시도. 조건 불충족 시 None."""
        if self._ctx.is_anonymous:
            return None
        if self._ctx.fiscal_year is None:
            return None
        if self._repo is None:
            logger.debug("repo 미주입 — Layer D 스킵")
            return None

        try:
            from src.detection.prior_data_loader import find_prior_engagement, load_prior_summary
            from src.detection.variance_layer import VarianceDetector

            prior = find_prior_engagement(
                self._repo, self._ctx.company_id, self._ctx.fiscal_year,
            )
            if prior is None:
                logger.info("전기 engagement 없음 — Layer D 스킵")
                return None

            prior_db_path = self._repo.db_path(self._ctx.company_id, prior.engagement_id)

            # Why: _run_detection은 _load_db 이전에 호출되므로 self._conn이 None일 수 있음.
            #      ConnectionManager 캐시를 통해 당기 DB 커넥션을 확보하여 ATTACH 기반으로 사용.
            conn = self._conn
            if conn is None:
                from src.db.connection import get_connection
                conn = get_connection(path=str(self._ctx.db_path))

            prior_summary = load_prior_summary(conn, prior_db_path, prior.fiscal_year)
            if prior_summary is None:
                return None

            det = VarianceDetector(self._ctx.settings, prior_summary=prior_summary)
            return det.detect(df)

        except Exception:
            logger.warning("Layer D 실행 실패 — 스킵", exc_info=True)
            return None

    def _load_db(self, df, batch_id, results) -> tuple[object | None, list[str]]:
        conn, own_conn = self._conn, self._conn is None
        try:
            if own_conn:
                from src.db.connection import get_connection
                # Why: 회사 프로파일 없는 폴백(anonymous/legacy) → :memory: 사용
                #      동일 파일에 동시 쓰기 시 DuckDB File Lock 방지
                if self._ctx.is_anonymous:
                    conn = get_connection(path=":memory:")
                else:
                    conn = get_connection(path=str(self._ctx.db_path))
            from src.db.loader import load_all
            lr = load_all(conn, df, batch_id, results)

            # Why: engagement_meta에 현재 engagement 기록 (named만)
            if not self._ctx.is_anonymous:
                self._upsert_engagement_meta(conn)

            return lr, []
        except Exception:
            logger.warning("DB 적재 실패", exc_info=True)
            return None, ["DB 적재 실패"]
        finally:
            # Why: anonymous :memory: 커넥션만 직접 close.
            #      named DB 커넥션은 ConnectionManager 캐시가 관리.
            if own_conn and conn is not None and self._ctx.is_anonymous:
                conn.close()

    def _upsert_engagement_meta(self, conn) -> None:
        """engagement_meta 테이블에 현재 engagement 기록 (중복 방지)."""
        # Why: UNIQUE(company_id, engagement_id) 제약으로 DB 레벨 중복 방어
        conn.execute(
            """
            INSERT INTO engagement_meta (company_id, engagement_id, schema_version)
            VALUES (?, ?, 1)
            ON CONFLICT DO NOTHING
            """,
            [self._ctx.company_id, self._ctx.engagement_id],
        )
