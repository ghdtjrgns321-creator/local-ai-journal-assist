"""하이브리드 Text-to-SQL 엔진 — 프리셋 1순위 → LLM 2순위.

자연어 질문 → SQL 생성 → sql_validator 검증 → DuckDB 실행 → DataFrame 반환.
CompanyContext 기반으로 DB 커넥션과 LLM 클라이언트를 통합 관리한다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import pandas as pd

from src.db.schema import SCHEMA_DDL
from src.llm.prompt_presets import AUDIT_PRESETS, match_preset
from src.llm.sql_validator import TABLE_WHITELIST, validate_sql

if TYPE_CHECKING:
    import duckdb

    from src.context import CompanyContext
    from src.llm.api_client import ChatClient

logger = logging.getLogger(__name__)


# ── 결과 모델 ────────────────────────────────────────────────

@dataclass(frozen=True)
class SQLResult:
    """Text-to-SQL 실행 결과.

    frozen=True: sql/source/error/preset_key는 불변.
    result_df는 mutable이지만 호출자가 직접 수정하지 않을 것을 전제.
    """

    sql: str
    result_df: pd.DataFrame | None
    source: Literal["preset", "llm", "failed"]
    error: str | None = None
    preset_key: str | None = None


# ── SQL 응답 스키마 (Structured Output) ──────────────────────

_SQL_RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "sql": {"type": "string"},
    },
    "required": ["sql"],
    "additionalProperties": False,
}


# ── 메인 엔진 ────────────────────────────────────────────────

class AuditTextToSQL:
    """하이브리드 Text-to-SQL 엔진.

    1순위: 프리셋 키워드 매칭 → 템플릿 SQL 파라미터 바인딩 실행
    2순위: LLM SQL 생성 → sql_validator 검증 → 파라미터 바인딩 실행
    3순위: 모두 실패 시 SQLResult(source="failed")
    """

    def __init__(
        self,
        ctx: CompanyContext,
        client: ChatClient | None = None,
        conn: duckdb.DuckDBPyConnection | None = None,
    ) -> None:
        self.ctx = ctx
        self._client = client
        self._conn = conn
        self._ddl_context = self._build_ddl_context()

    @property
    def conn(self):
        """DB 커넥션 lazy 초기화."""
        if self._conn is None:
            from src.db.connection import get_connection
            self._conn = get_connection(str(self.ctx.db_path))
        return self._conn

    @property
    def client(self):
        """LLM 클라이언트 lazy 초기화. 미가용 시 None 유지."""
        if self._client is None:
            self._client = self._try_get_client()
        return self._client

    def ask(
        self,
        question: str,
        *,
        batch_id: str | None = None,
        llm_enabled: bool = True,
    ) -> SQLResult:
        """자연어 질문 → SQL → 실행 → DataFrame.

        Args:
            question: 자연어 질문.
            batch_id: 배치 격리 키 (upload_batch_id).
            llm_enabled: False면 프리셋 매칭만 시도, LLM 호출 차단.
                Why: `self.client`는 lazy @property라 ``_client=None`` 할당으로는
                차단 불가. 호출자가 명시적으로 false를 전달해야 토글 OFF가 보장된다.

        Returns:
            SQLResult with sql, result_df, source.
        """
        # 1순위: 프리셋 매칭
        preset = match_preset(question)
        if preset is not None:
            return self._execute_preset(preset, batch_id)

        # 2순위: LLM SQL 생성 — llm_enabled=False면 프로퍼티 참조 자체 차단
        if llm_enabled and self.client is not None:
            return self._generate_and_execute(question, batch_id)

        # 3순위: 실패
        error_msg = (
            "프리셋 미매칭 — LLM 비활성"
            if not llm_enabled
            else "프리셋 미매칭 + LLM 미가용"
        )
        return SQLResult(
            sql="",
            result_df=None,
            source="failed",
            error=error_msg,
        )

    # ── 내부 메서드 ──────────────────────────────────────────

    def _execute_preset(self, preset, batch_id: str | None) -> SQLResult:
        """프리셋 SQL에 batch_id 파라미터 바인딩 후 실행."""
        sql = preset.sql

        # Why: batch_id 없이 ? 바인딩 SQL 실행 시 DuckDB 오류 → 명확한 메시지
        if batch_id is None and "?" in sql:
            return SQLResult(
                sql=sql, result_df=None, source="failed",
                error="batch_id 미제공 — 업로드 배치를 먼저 선택하세요",
                preset_key=preset.key,
            )

        try:
            # Why: sql.replace() 대신 DuckDB 파라미터 바인딩으로 SQL Injection 방지
            param_count = sql.count("?")
            params = [batch_id] * param_count if param_count > 0 else []
            df = self.conn.execute(sql, params).fetchdf()
            return SQLResult(
                sql=sql,
                result_df=df,
                source="preset",
                preset_key=preset.key,
            )
        except Exception as e:
            logger.warning("프리셋 실행 실패 [%s]: %s", preset.key, e)
            return SQLResult(
                sql=sql, result_df=None, source="failed",
                error=f"프리셋 실행 오류: {e}",
                preset_key=preset.key,
            )

    def _generate_and_execute(
        self, question: str, batch_id: str | None,
    ) -> SQLResult:
        """LLM으로 SQL 생성 → 검증 → 실행."""
        try:
            raw_sql = self._generate_sql(question)
        except Exception as e:
            logger.warning("LLM SQL 생성 실패: %s", e)
            return SQLResult(sql="", result_df=None, source="failed",
                             error=f"SQL 생성 오류: {e}")

        # Why: 검증기에서 배치 격리 키 누락도 차단
        validation = validate_sql(raw_sql, conn=self.conn,
                                  require_batch_filter=True)
        if not validation.is_valid:
            logger.warning("SQL 검증 실패: %s", validation.errors)
            return SQLResult(
                sql=raw_sql, result_df=None, source="failed",
                error=f"SQL 검증 실패: {'; '.join(validation.errors)}",
            )

        try:
            # Why: LLM SQL의 ? 플레이스홀더에 batch_id 바인딩
            param_count = validation.sql.count("?")
            params = [batch_id] * param_count if batch_id and param_count else []
            df = self.conn.execute(validation.sql, params).fetchdf()
            return SQLResult(sql=validation.sql, result_df=df, source="llm")
        except Exception as e:
            logger.warning("SQL 실행 실패: %s", e)
            return SQLResult(
                sql=validation.sql, result_df=None, source="failed",
                error=f"SQL 실행 오류: {e}",
            )

    def _generate_sql(self, question: str) -> str:
        """LLM에 DDL + few-shot 프롬프트 → SQL 생성."""
        system_prompt = self._build_system_prompt()
        # Why: batch_id를 프롬프트에 직접 삽입하지 않음 (Prompt Injection 방지)
        # LLM에는 ? 플레이스홀더 사용을 지시, 실행 시 파라미터 바인딩
        user_prompt = self._build_user_prompt(question)

        response = self.client.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            format=_SQL_RESPONSE_SCHEMA,
        )

        parsed = json.loads(response)
        return parsed["sql"]

    def _build_system_prompt(self) -> str:
        """시스템 프롬프트: DDL + 도메인 용어 + few-shot + 제약."""
        # Why: basic/process 균형 샘플링으로 LLM 편향 방지
        presets = list(AUDIT_PRESETS.values())
        basic = [p for p in presets if p.category == "basic"][:3]
        process = [p for p in presets if p.category == "process"][:3]
        few_shot = "\n".join(
            f"Q: {p.question}\nSQL: {p.sql}"
            for p in basic + process
        )

        return f"""당신은 DuckDB SQL 전문가입니다. 감사 데이터 분석용 SELECT 쿼리만 생성합니다.

## 테이블 DDL
{self._ddl_context}

## 도메인 용어
- business_process: P2P(매입), O2C(매출), R2R(결산), H2R(인사), TRE(자금), A2R(자산)
- user_persona: automated_system, junior_accountant, senior_accountant, controller, manager
- fraud_type: DuplicatePayment, FictitiousTransaction, RevenueManipulation 등 16종
- risk_level: HIGH, MEDIUM, LOW
- source: batch, interface, manual, system

## 제약 조건
- SELECT 쿼리만 생성 (INSERT/UPDATE/DELETE/DROP 금지)
- upload_batch_id 조건은 ? 플레이스홀더로 작성 (WHERE upload_batch_id = ?)
- LIMIT 절 필수 (최대 1000)
- 서브쿼리 최대 3단계
- 허용 테이블: {', '.join(sorted(TABLE_WHITELIST))}

## few-shot 예시
{few_shot}"""

    @staticmethod
    def _build_user_prompt(question: str) -> str:
        """사용자 프롬프트 — batch_id는 포함하지 않음."""
        return (
            f"{question}\n"
            "반드시 WHERE 절에 upload_batch_id = ? 조건을 포함하세요."
        )

    def _build_ddl_context(self) -> str:
        """화이트리스트 테이블의 DDL만 추출."""
        parts = []
        for name, ddl in SCHEMA_DDL.items():
            if name.lower() in TABLE_WHITELIST:
                parts.append(ddl.strip())
        return "\n\n".join(parts)

    def _try_get_client(self):
        """settings에서 OpenAI 클라이언트 생성. 미가용 시 None."""
        try:
            api_key = self.ctx.settings.openai_api_key
            if not api_key:
                return None
            from src.llm.api_client import OpenAIClient
            client = OpenAIClient(
                api_key=api_key,
                model=self.ctx.settings.openai_light_model,
            )
            if not client.is_available():
                logger.warning("OpenAI 미가용 — 프리셋 전용 모드")
                return None
            return client
        except Exception as e:
            logger.warning("LLM 클라이언트 초기화 실패: %s", e)
            return None


# ── 팩토리 ───────────────────────────────────────────────────

def create_text_to_sql(
    ctx: CompanyContext,
    client: ChatClient | None = None,
    conn: duckdb.DuckDBPyConnection | None = None,
) -> AuditTextToSQL:
    """CompanyContext → AuditTextToSQL 인스턴스 팩토리.

    LLM 미가용(키 미설정) 시에도 인스턴스 생성 성공 — ask()에서 프리셋 폴백.
    """
    return AuditTextToSQL(ctx=ctx, client=client, conn=conn)
