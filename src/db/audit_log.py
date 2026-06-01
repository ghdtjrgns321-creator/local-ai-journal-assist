"""감사 이벤트 기록 — execute_write() 재시도 래퍼 위에 얇게 구성.

Why:
    ISO 27001 / SOC 2 대응을 위해 시스템 라이프사이클 이벤트(파이프라인 실행,
    whitelist 변경, 검증 실패 등)를 단일 audit_log 테이블에 누적한다.

    DuckDB는 single-writer 데이터베이스라 파이프라인이 무거운 적재 중일 때
    UI에서 동시에 INSERT를 시도하면 IOException(file lock)이 즉시 발생한다.
    이를 방어하기 위해 raw conn.execute() 대신 src.db.queries.execute_write()를
    경유한다 — 0.1s → 0.2s → 0.3s 지수 백오프 3회 재시도가 내장되어 있다.

    감사 로그는 본 흐름(파이프라인/UI)을 절대 차단해선 안 되므로
    재시도까지 실패해도 호출측에 예외를 전파하지 않고 warning만 기록한다.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from src.db.queries import execute_write

if TYPE_CHECKING:
    import duckdb

logger = logging.getLogger(__name__)


def record_event(
    conn: duckdb.DuckDBPyConnection,
    *,
    action: str,
    company_id: str | None = None,
    engagement_id: str | None = None,
    batch_id: str | None = None,
    target_id: str | None = None,
    details: dict | None = None,
    actor: str = "auditor",
) -> None:
    """audit_log INSERT — 락 충돌 시 자동 재시도, 최종 실패 시 graceful.

    Args:
        conn: DuckDB 커넥션 (engagement DB).
        action: 이벤트 유형 — 'detection_run' | 'whitelist_add' |
                'whitelist_remove' | 'pipeline_validate_fail' |
                'rule_config_change' 등.
        company_id, engagement_id, batch_id: 컨텍스트 식별자 (옵션).
        target_id: 액션 대상 — document_id, rule_code, whitelist row id 등.
        details: 액션별 세부 파라미터. JSON 직렬화 가능해야 함.
        actor: 사용자 식별자 (Phase 1은 'auditor' 고정, 향후 인증 도입 시 user_id).
    """
    # Why: numpy/pandas 타입이 섞여 들어올 수 있으므로 default=str로 안전 직렬화
    payload = json.dumps(details or {}, ensure_ascii=False, default=str)
    try:
        execute_write(
            conn,
            "insert_audit_log",
            (action, actor, company_id, engagement_id, batch_id, target_id, payload),
        )
    except Exception:
        # Why: execute_write 내부 재시도(IOException/TransactionException 3회)도
        #      실패한 경우만 도달. 호출측 흐름은 계속 진행해야 한다.
        logger.warning("audit_log 기록 실패: action=%s", action, exc_info=True)
