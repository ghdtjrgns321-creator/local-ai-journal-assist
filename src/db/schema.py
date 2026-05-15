"""DuckDB DDL 정의 — 5개 테이블 + 1 VIEW.

Source of truth: config/schema.yaml (DataSynth v1.2.0 PREVIEW 39개)
+ approval_level 파생 + 피처 19종 + 탐지 결과 3종 + ML 예약 7종.

Phase 2 예약 컬럼 (7개, nullable):
  - supervised_score, unsupervised_score, duplicate_score (ML 모델 출력)
  - supervised_model_id, unsupervised_model_id, duplicate_model_id (모델 추적)
  - ml_scored_at (점수 산출 시점)

  Phase 2b score_aggregator 확장에서 채워질 예정.
  Phase 1 데이터는 NULL 유지 (하위 호환성).
"""

from __future__ import annotations

import logging

import duckdb

logger = logging.getLogger(__name__)

# ── DDL ──────────────────────────────────────────────────────

SCHEMA_DDL: dict[str, str] = {
    "general_ledger": """
        CREATE TABLE IF NOT EXISTS general_ledger (
            -- 원본 — Header (config/schema.yaml 기준 39개)
            document_id VARCHAR NOT NULL,
            company_code VARCHAR,
            fiscal_year INTEGER,
            fiscal_period INTEGER NOT NULL,
            posting_date TIMESTAMP NOT NULL,
            posting_time TIME,
            document_date TIMESTAMP,
            document_type VARCHAR,
            currency VARCHAR,
            exchange_rate DOUBLE,
            reference VARCHAR,
            header_text VARCHAR,
            created_by VARCHAR,
            user_persona VARCHAR,
            source VARCHAR,
            business_process VARCHAR,
            ledger VARCHAR,
            approved_by VARCHAR,
            approval_date TIMESTAMP,
            -- 원본 — 레이블 (DataSynth 전용)
            is_fraud BOOLEAN,
            fraud_type VARCHAR,
            is_anomaly BOOLEAN,
            anomaly_type VARCHAR,
            sod_violation BOOLEAN,
            sod_conflict_type VARCHAR,
            -- 원본 — Line
            line_number INTEGER,
            gl_account VARCHAR,
            debit_amount DOUBLE DEFAULT 0,
            credit_amount DOUBLE DEFAULT 0,
            local_amount DOUBLE,
            cost_center VARCHAR,
            profit_center VARCHAR,
            line_text VARCHAR,
            tax_code VARCHAR,
            tax_amount DOUBLE,
            trading_partner VARCHAR,
            auxiliary_account_number VARCHAR,
            auxiliary_account_label VARCHAR,
            lettrage VARCHAR,
            lettrage_date TIMESTAMP,
            -- 파생 — DB 적재 시 생성
            approval_level INTEGER,
            document_number VARCHAR,    -- SAP 순차 전표번호 (선행0/알파벳 혼합 대비 VARCHAR)
            -- 파생변수 (38종, from feature/engine.py EXPECTED_COLUMNS, morpheme_tokens 제외)
            is_weekend BOOLEAN,
            is_after_hours BOOLEAN,
            is_period_end BOOLEAN,
            days_backdated INTEGER,
            fiscal_period_mismatch BOOLEAN,
            is_holiday BOOLEAN,
            time_zone_category VARCHAR,
            is_near_threshold BOOLEAN,
            near_threshold_amount DOUBLE,
            near_threshold_limit_amount DOUBLE,
            near_threshold_limit_resolved BOOLEAN,
            near_threshold_ratio_to_limit DOUBLE,
            near_threshold_gap_amount DOUBLE,
            near_threshold_gap_ratio DOUBLE,
            near_threshold_bucket VARCHAR,
            exceeds_threshold BOOLEAN,
            document_approval_amount DOUBLE,
            approver_limit_amount DOUBLE,
            approval_limit_resolved BOOLEAN,
            approver_can_approve_je BOOLEAN,
            approval_excess_amount DOUBLE,
            approval_excess_ratio DOUBLE,
            approval_excess_bucket VARCHAR,
            amount_zscore DOUBLE,
            amount_magnitude DOUBLE,
            is_round_number BOOLEAN,
            is_manual_je BOOLEAN,
            is_intercompany BOOLEAN,
            is_revenue_account BOOLEAN,
            first_digit INTEGER,
            is_suspense_account BOOLEAN,
            description_quality VARCHAR,
            description_line_missing BOOLEAN,
            description_header_missing BOOLEAN,
            description_both_missing BOOLEAN,
            description_line_missing_header_present BOOLEAN,
            description_is_missing_or_corrupted BOOLEAN,
            has_risk_keyword VARCHAR,
            -- 이상탐지 결과 (3종, from score_aggregator)
            anomaly_score DOUBLE,
            risk_level VARCHAR,
            flagged_rules VARCHAR,
            review_rules VARCHAR,
            -- ML 탐지 결과 (7종, Phase 2 예약 — nullable, Phase 1에서는 NULL)
            supervised_score DOUBLE,
            unsupervised_score DOUBLE,
            duplicate_score DOUBLE,
            supervised_model_id VARCHAR,
            unsupervised_model_id VARCHAR,
            duplicate_model_id VARCHAR,
            ml_scored_at TIMESTAMP,
            -- 메타
            upload_batch_id VARCHAR,
            created_at TIMESTAMP DEFAULT current_timestamp
        )
    """,
    "anomaly_flags": """
        CREATE TABLE IF NOT EXISTS anomaly_flags (
            upload_batch_id VARCHAR,
            document_id VARCHAR NOT NULL,
            line_number INTEGER,
            track_name VARCHAR NOT NULL,
            rule_code VARCHAR NOT NULL,
            score DOUBLE NOT NULL,
            created_at TIMESTAMP DEFAULT current_timestamp
        )
    """,
    "benford_summary": """
        CREATE TABLE IF NOT EXISTS benford_summary (
            upload_batch_id VARCHAR NOT NULL,
            sample_size INTEGER,
            mad DOUBLE,
            mad_conformity VARCHAR,
            chi2_statistic DOUBLE,
            chi2_p_value DOUBLE,
            ks_statistic DOUBLE,
            ks_p_value DOUBLE,
            is_conforming BOOLEAN,
            confidence VARCHAR,
            created_at TIMESTAMP DEFAULT current_timestamp
        )
    """,
    "benford_digits": """
        CREATE TABLE IF NOT EXISTS benford_digits (
            upload_batch_id VARCHAR NOT NULL,
            digit INTEGER NOT NULL,
            observed_freq DOUBLE,
            expected_freq DOUBLE,
            deviation DOUBLE,
            created_at TIMESTAMP DEFAULT current_timestamp
        )
    """,
    "ml_model_metadata": """
        CREATE TABLE IF NOT EXISTS ml_model_metadata (
            model_id VARCHAR PRIMARY KEY NOT NULL,
            model_type VARCHAR NOT NULL,
            model_version VARCHAR,
            train_batch_id VARCHAR,
            train_rows INTEGER,
            train_metrics JSON,
            hyperparameters JSON,
            created_at TIMESTAMP DEFAULT current_timestamp
        )
    """,
    # ── Whitelist (HITL 예외 처리) ──
    "whitelist_seq": """
        CREATE SEQUENCE IF NOT EXISTS whitelist_id_seq START 1
    """,
    "whitelist": """
        CREATE TABLE IF NOT EXISTS whitelist (
            id INTEGER DEFAULT nextval('whitelist_id_seq') PRIMARY KEY,
            batch_id VARCHAR NOT NULL,
            document_id VARCHAR NOT NULL,
            rule_code VARCHAR NOT NULL,
            reason VARCHAR,
            created_by VARCHAR DEFAULT 'auditor',
            created_at TIMESTAMP DEFAULT current_timestamp
        )
    """,
    # ── 업로드 배치 메타 (배치 이력 조회/복원) ──
    "upload_batches": """
        CREATE TABLE IF NOT EXISTS upload_batches (
            upload_batch_id VARCHAR PRIMARY KEY NOT NULL,
            file_name       VARCHAR,
            row_count       INTEGER NOT NULL,
            anomaly_count   INTEGER DEFAULT 0,
            high_risk_count INTEGER DEFAULT 0,
            phase2_training_report_id VARCHAR,
            phase2_inference_contract JSON,
            phase2_promotion_policy JSON,
            phase2_inference_mode VARCHAR,
            detector_statuses_json JSON,
            phase1_case_run_id VARCHAR,
            phase1_case_path VARCHAR,
            phase1_case_count INTEGER DEFAULT 0,
            phase1_macro_finding_count INTEGER DEFAULT 0,
            phase1_top_theme_ids JSON,
            phase1_case_schema_version VARCHAR,
            created_at      TIMESTAMP DEFAULT current_timestamp,
            warnings        VARCHAR
        )
    """,
    # ── Engagement 메타 (RC-3: DB 격리) ──
    "performance_reports": """
        CREATE TABLE IF NOT EXISTS performance_reports (
            report_id              VARCHAR PRIMARY KEY NOT NULL,
            upload_batch_id        VARCHAR NOT NULL,
            source_kind            VARCHAR NOT NULL,
            phase_scope            VARCHAR NOT NULL,
            metric_confidence      VARCHAR DEFAULT 'complete',
            total_docs             INTEGER DEFAULT 0,
            flagged_docs           INTEGER DEFAULT 0,
            high_risk_docs         INTEGER DEFAULT 0,
            high_risk_ratio        DOUBLE,
            precision              DOUBLE,
            recall                 DOUBLE,
            f1                     DOUBLE,
            whitelist_removed_docs INTEGER DEFAULT 0,
            false_positive_docs    INTEGER DEFAULT 0,
            confirmed_issue_docs   INTEGER DEFAULT 0,
            created_at             TIMESTAMP DEFAULT current_timestamp
        )
    """,
    "performance_rule_metrics": """
        CREATE TABLE IF NOT EXISTS performance_rule_metrics (
            report_id     VARCHAR NOT NULL,
            track_name    VARCHAR NOT NULL,
            rule_code     VARCHAR NOT NULL,
            label_docs    INTEGER DEFAULT 0,
            flagged_docs  INTEGER DEFAULT 0,
            tp_docs       INTEGER DEFAULT 0,
            fp_docs       INTEGER DEFAULT 0,
            fn_docs       INTEGER DEFAULT 0,
            precision     DOUBLE,
            recall        DOUBLE,
            f1            DOUBLE,
            breakdown_json VARCHAR,
            score_bands_json VARCHAR,
            created_at    TIMESTAMP DEFAULT current_timestamp
        )
    """,
    "engagement_meta": """
        CREATE TABLE IF NOT EXISTS engagement_meta (
            company_id     VARCHAR NOT NULL,
            engagement_id  VARCHAR NOT NULL,
            created_at     TIMESTAMP DEFAULT current_timestamp,
            schema_version INTEGER DEFAULT 1,
            UNIQUE (company_id, engagement_id)
        )
    """,
    # ── Trial Balance (WU-13: TB 교차검증) ──
    # NOTE: closing_balance는 기말 잔액이 아닌 '당기 순증감액(Net Change)'
    #       이월 기초전표(Opening Entry) 미포함 (Phase 1 제약)
    "trial_balance": """
        CREATE TABLE IF NOT EXISTS trial_balance (
            upload_batch_id VARCHAR NOT NULL,
            fiscal_year     INTEGER,
            fiscal_period   INTEGER,
            gl_account      VARCHAR,
            account_name    VARCHAR,
            opening_balance DOUBLE DEFAULT 0,
            debit_total     DOUBLE DEFAULT 0,
            credit_total    DOUBLE DEFAULT 0,
            closing_balance DOUBLE DEFAULT 0,
            created_at      TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (upload_batch_id, gl_account, fiscal_period)
        )
    """,
    # ── Audit Log (감사증적 — ISO 27001 / SOC 2 대응) ──
    # Why: "누가·언제·어떤 액션으로" 시스템을 변경했는지 감사 조서(workpaper)에
    #      증거로 제출하기 위한 단일 로그 테이블. 파이프라인 실행, whitelist 변경,
    #      검증 실패 등 모든 라이프사이클 이벤트를 단일 스키마로 누적한다.
    "audit_log_seq": """
        CREATE SEQUENCE IF NOT EXISTS audit_log_id_seq START 1
    """,
    "audit_log": """
        CREATE TABLE IF NOT EXISTS audit_log (
            id            BIGINT DEFAULT nextval('audit_log_id_seq') PRIMARY KEY,
            action        VARCHAR NOT NULL,
            -- system (src/db/audit_log.py::record_event 직접 호출):
            --   'detection_run' | 'whitelist_add' | 'whitelist_remove'
            --   | 'pipeline_validate_fail' | 'rule_config_change'
            -- user   (src/export/audit_trail.py::AuditTrail.log, WU-23):
            --   'upload' | 'validate' | 'analysis' | 'query' | 'filter' | 'export'
            --   details JSON 에 user_action(사람이 읽을 설명) 키가 포함됨
            actor         VARCHAR DEFAULT 'auditor',
            company_id    VARCHAR,
            engagement_id VARCHAR,
            batch_id      VARCHAR,
            target_id     VARCHAR,    -- document_id, rule_code, whitelist row id 등
            details       JSON,        -- 액션별 세부 파라미터 (설정 스냅샷, before/after)
            created_at    TIMESTAMP DEFAULT current_timestamp
        )
    """,
    "feedback_events_seq": """
        CREATE SEQUENCE IF NOT EXISTS feedback_event_id_seq START 1
    """,
    "feedback_events": """
        CREATE TABLE IF NOT EXISTS feedback_events (
            id            BIGINT DEFAULT nextval('feedback_event_id_seq') PRIMARY KEY,
            company_id    VARCHAR,
            engagement_id VARCHAR,
            batch_id      VARCHAR,
            document_id   VARCHAR,
            track_name    VARCHAR,
            rule_code     VARCHAR,
            event_type    VARCHAR NOT NULL,
            decision      VARCHAR NOT NULL,
            reason        VARCHAR,
            payload_json  JSON,
            created_by    VARCHAR DEFAULT 'auditor',
            created_at    TIMESTAMP DEFAULT current_timestamp
        )
    """,
    # ── LLM Narrative Report (WU-25: XAI 사유서 캐시) ──
    # Why: 동일 문서(document_id) 사유서 재생성 비용(light 모델 기준 수 초 + 토큰)을
    #      방지. entry 단위 PK + generated_at 인덱스로 최신 N건 조회 및 stale 정책 지원.
    "llm_narratives": """
        CREATE TABLE IF NOT EXISTS llm_narratives (
            document_id    VARCHAR PRIMARY KEY NOT NULL,
            narrative_text VARCHAR NOT NULL,
            cited_rules    VARCHAR,
            model_tier     VARCHAR NOT NULL,
            generated_at   TIMESTAMP DEFAULT current_timestamp
        )
    """,
    "llm_narratives_idx": """
        CREATE INDEX IF NOT EXISTS idx_llm_narratives_generated
            ON llm_narratives(generated_at DESC)
    """,
    # ── Phase 3 v2: Review Queue Narrator 캐시 (WU-31 Sprint A) ──
    # Why: candidate_id 단위 LLM 호출 결과를 UPSERT 캐시한다. input_hash가 동일하면
    #      재호출 없이 재사용해 비용·latency를 줄이고, citation_valid 플래그로 후순위
    #      판정·UI 표시에 활용. batch_id/priority_rank 인덱스는 대시보드 조회 패턴 대응.
    # Nullable 정책:
    #   - 필수(NOT NULL): candidate_id, batch_id, narrative_json, citation_valid,
    #     input_hash, model_tier — 캐시 row가 의미를 가지려면 반드시 채워져야 함.
    #   - 선택(NULL 허용): priority_rank/priority_score/confidence/journal_id —
    #     LLM 응답이 부분적으로 비어있거나 강등 처리된 경우를 위해 허용. 토큰/비용
    #     집계 컬럼(prompt_tokens/completion_tokens/cost_usd)은 모델·요금 정책에 따라
    #     수집 불가한 경우(예: 평가 하니스 외 일반 호출)를 위해 NULL 허용.
    #     Sprint B 캐시 writer는 NULL 값을 방어 쿼리(IS NULL/COALESCE)로 처리할 것.
    "review_narratives": """
        CREATE TABLE IF NOT EXISTS review_narratives (
            candidate_id          VARCHAR PRIMARY KEY NOT NULL,
            batch_id              VARCHAR NOT NULL,
            journal_id            VARCHAR,
            priority_rank         INTEGER,
            priority_score        DOUBLE,
            confidence            VARCHAR,
            narrative_json        JSON NOT NULL,
            citation_valid        BOOLEAN NOT NULL,
            input_hash            VARCHAR NOT NULL,
            model_tier            VARCHAR NOT NULL,
            prompt_tokens         INTEGER,
            completion_tokens     INTEGER,
            cost_usd              DOUBLE,
            created_at            TIMESTAMP DEFAULT current_timestamp
        )
    """,
    "review_narratives_batch_idx": """
        CREATE INDEX IF NOT EXISTS idx_review_narratives_batch
            ON review_narratives(batch_id)
    """,
    "review_narratives_rank_idx": """
        CREATE INDEX IF NOT EXISTS idx_review_narratives_rank
            ON review_narratives(priority_rank)
    """,
    # ── Phase 3 v2: 감사인 분류·메모 컬럼 (WU-31 Sprint E2) ──
    # Why: 감사인이 review queue candidate를 4종 결정값으로 분류하고 메모를 남길 수
    #      있어야 audit workpaper에 결과를 첨부할 수 있다. 기존 DB에서도 안전하게
    #      재실행 가능하도록 모든 ALTER는 IF NOT EXISTS 사용.
    # audit_decision 허용 값:
    #   'confirmed_high_risk' | 'under_review' | 'normal_exception'
    #   | 'false_positive' | NULL
    # NULL은 "감사인이 아직 분류하지 않음"을 의미한다. CHECK 제약은 두지 않고
    # 애플리케이션 레이어(cache.update_audit_decision)에서 enum을 강제한다.
    "review_narratives_audit_decision": """
        ALTER TABLE review_narratives
            ADD COLUMN IF NOT EXISTS audit_decision VARCHAR
    """,
    "review_narratives_audit_note": """
        ALTER TABLE review_narratives
            ADD COLUMN IF NOT EXISTS audit_note VARCHAR
    """,
    "review_narratives_reviewed_by": """
        ALTER TABLE review_narratives
            ADD COLUMN IF NOT EXISTS reviewed_by VARCHAR
    """,
    "review_narratives_reviewed_at": """
        ALTER TABLE review_narratives
            ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMP
    """,
    "review_narratives_decision_idx": """
        CREATE INDEX IF NOT EXISTS idx_review_narratives_decision
            ON review_narratives(audit_decision)
    """,
    "anomaly_flag_summary": """
        CREATE VIEW IF NOT EXISTS anomaly_flag_summary AS
        SELECT
            upload_batch_id,
            track_name,
            rule_code,
            COUNT(*) AS flagged_count,
            AVG(score) AS avg_score,
            MAX(score) AS max_score
        FROM anomaly_flags
        GROUP BY upload_batch_id, track_name, rule_code
    """,
}

# ── 컬럼 상수 (loader.py reindex용, created_at 제외) ────────

GENERAL_LEDGER_COLUMNS: list[str] = [
    "document_id",
    "company_code",
    "fiscal_year",
    "fiscal_period",
    "posting_date",
    "posting_time",
    "document_date",
    "document_type",
    "currency",
    "exchange_rate",
    "reference",
    "header_text",
    "created_by",
    "user_persona",
    "source",
    "business_process",
    "ledger",
    "approved_by",
    "approval_date",
    "is_fraud",
    "fraud_type",
    "is_anomaly",
    "anomaly_type",
    "sod_violation",
    "sod_conflict_type",
    "line_number",
    "gl_account",
    "debit_amount",
    "credit_amount",
    "local_amount",
    "cost_center",
    "profit_center",
    "line_text",
    "tax_code",
    "tax_amount",
    "trading_partner",
    "auxiliary_account_number",
    "auxiliary_account_label",
    "lettrage",
    "lettrage_date",
    "approval_level",
    "is_weekend",
    "is_after_hours",
    "is_period_end",
    "days_backdated",
    "fiscal_period_mismatch",
    "is_holiday",
    "time_zone_category",
    "is_near_threshold",
    "near_threshold_amount",
    "near_threshold_limit_amount",
    "near_threshold_limit_resolved",
    "near_threshold_ratio_to_limit",
    "near_threshold_gap_amount",
    "near_threshold_gap_ratio",
    "near_threshold_bucket",
    "exceeds_threshold",
    "document_approval_amount",
    "approver_limit_amount",
    "approval_limit_resolved",
    "approver_can_approve_je",
    "approval_excess_amount",
    "approval_excess_ratio",
    "approval_excess_bucket",
    "amount_zscore",
    "amount_magnitude",
    "is_round_number",
    "is_manual_je",
    "is_intercompany",
    "is_revenue_account",
    "first_digit",
    "is_suspense_account",
    "description_quality",
    "description_line_missing",
    "description_header_missing",
    "description_both_missing",
    "description_line_missing_header_present",
    "description_is_missing_or_corrupted",
    "has_risk_keyword",
    "anomaly_score",
    "risk_level",
    "flagged_rules",
    "review_rules",
    # ML Phase 2 예약 (nullable)
    "supervised_score",
    "unsupervised_score",
    "duplicate_score",
    "supervised_model_id",
    "unsupervised_model_id",
    "duplicate_model_id",
    "ml_scored_at",
    "upload_batch_id",
]

ANOMALY_FLAGS_COLUMNS: list[str] = [
    "upload_batch_id",
    "document_id",
    "line_number",
    "track_name",
    "rule_code",
    "score",
]

BENFORD_SUMMARY_COLUMNS: list[str] = [
    "upload_batch_id",
    "sample_size",
    "mad",
    "mad_conformity",
    "chi2_statistic",
    "chi2_p_value",
    "ks_statistic",
    "ks_p_value",
    "is_conforming",
    "confidence",
]

BENFORD_DIGITS_COLUMNS: list[str] = [
    "upload_batch_id",
    "digit",
    "observed_freq",
    "expected_freq",
    "deviation",
]

ML_MODEL_METADATA_COLUMNS: list[str] = [
    "model_id",
    "model_type",
    "model_version",
    "train_batch_id",
    "train_rows",
    "train_metrics",
    "hyperparameters",
]

# Why: loader.py에서 reindex 후 NaN→None 변환 대상 (Phase 1에서 항상 NULL)
WHITELIST_COLUMNS: list[str] = [
    "batch_id",
    "document_id",
    "rule_code",
    "reason",
    "created_by",
]

ENGAGEMENT_META_COLUMNS: list[str] = [
    "company_id",
    "engagement_id",
    "created_at",
    "schema_version",
]

UPLOAD_BATCHES_COLUMNS: list[str] = [
    "upload_batch_id",
    "file_name",
    "row_count",
    "anomaly_count",
    "high_risk_count",
    "warnings",
]

PERFORMANCE_REPORTS_COLUMNS: list[str] = [
    "report_id",
    "upload_batch_id",
    "source_kind",
    "phase_scope",
    "metric_confidence",
    "total_docs",
    "flagged_docs",
    "high_risk_docs",
    "high_risk_ratio",
    "precision",
    "recall",
    "f1",
    "whitelist_removed_docs",
    "false_positive_docs",
    "confirmed_issue_docs",
]

PERFORMANCE_RULE_METRICS_COLUMNS: list[str] = [
    "report_id",
    "track_name",
    "rule_code",
    "label_docs",
    "flagged_docs",
    "tp_docs",
    "fp_docs",
    "fn_docs",
    "precision",
    "recall",
    "f1",
]

TRIAL_BALANCE_COLUMNS: list[str] = [
    "upload_batch_id",
    "fiscal_year",
    "fiscal_period",
    "gl_account",
    "account_name",
    "opening_balance",
    "debit_total",
    "credit_total",
    "closing_balance",
]

AUDIT_LOG_COLUMNS: list[str] = [
    "action",
    "actor",
    "company_id",
    "engagement_id",
    "batch_id",
    "target_id",
    "details",
]

FEEDBACK_EVENTS_COLUMNS: list[str] = [
    "company_id",
    "engagement_id",
    "batch_id",
    "document_id",
    "track_name",
    "rule_code",
    "event_type",
    "decision",
    "reason",
    "payload_json",
    "created_by",
]

ML_RESERVED_COLUMNS: list[str] = [
    "supervised_score",
    "unsupervised_score",
    "duplicate_score",
    "supervised_model_id",
    "unsupervised_model_id",
    "duplicate_model_id",
    "ml_scored_at",
]

REVIEW_NARRATIVES_COLUMNS: list[str] = [
    "candidate_id",
    "batch_id",
    "journal_id",
    "priority_rank",
    "priority_score",
    "confidence",
    "narrative_json",
    "citation_valid",
    "input_hash",
    "model_tier",
    "prompt_tokens",
    "completion_tokens",
    "cost_usd",
    # Sprint E2 — 감사인 분류·메모 (Phase 3 v2)
    "audit_decision",
    "audit_note",
    "reviewed_by",
    "reviewed_at",
]

# Why: cache.update_audit_decision이 외부 입력값을 받기 전에 검증해 잘못된
#      decision 문자열이 DB에 들어가는 것을 차단한다. NULL은 별도 처리.
AUDIT_DECISION_VALUES: frozenset[str] = frozenset(
    {
        "confirmed_high_risk",
        "under_review",
        "normal_exception",
        "false_positive",
    }
)


# ── 초기화 ───────────────────────────────────────────────────


def initialize_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """모든 테이블 DDL + VIEW 실행. 멱등성 보장."""
    for name, ddl in SCHEMA_DDL.items():
        conn.execute(ddl)

    # Why: DataSynth 보조 데이터(document_flows, master_data 등) 테이블도 함께 생성
    from src.db.schema_supplementary import initialize_supplementary_schema

    initialize_supplementary_schema(conn)

    total = len(SCHEMA_DDL)
    logger.info("DuckDB 스키마 초기화 완료 (%d개 코어 + 보조 오브젝트)", total)
