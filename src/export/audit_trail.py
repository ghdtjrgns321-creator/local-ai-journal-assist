"""WU-23 사용자 활동 기록기 — 기존 audit_log 테이블을 재사용하는 OOP 래퍼.

Why:
    가이드(docs/pre-plan/09-export.md §374-407)는 새 audit_trail 테이블과
    AuditTrail 클래스를 요구하지만, 프로젝트에는 이미
      - src/db/schema.py::audit_log 테이블
      - src/db/audit_log.py::record_event() 함수 (재시도+graceful)
    가 존재해 시스템 이벤트(detection_run 등)를 기록 중이다.

    중복 테이블을 만드는 대신 기존 audit_log를 재사용하고,
    AuditTrail은 record_event의 OOP 래퍼로 구현한다.
    이벤트 타입은 action 컬럼 값으로 구분한다:
      - system (record_event 직접 호출): detection_run, whitelist_add, ...
      - user   (AuditTrail.log):         upload, validate, analysis,
                                          query, filter, export

    user_action(사람이 읽을 설명)은 audit_log 스키마 변경을 피하기 위해
    details JSON에 병합 저장하되, 조회(get_trail) 시 DuckDB의 JSON 연산자
    '->>'로 독립 컬럼처럼 노출해 호출측 부담을 제거한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal, get_args

import pandas as pd

from src.db.audit_log import record_event

if TYPE_CHECKING:
    import duckdb


# ── 이벤트 타입 정의 ──────────────────────────────────────────
# Why: EventType Literal이 단일 진실 공급원(single source of truth).
#      VALID_EVENT_TYPES는 typing.get_args()로 자동 파생하므로
#      이벤트 타입 추가 시 Literal 한 곳만 고치면 된다.
EventType = Literal["upload", "validate", "analysis", "query", "filter", "export"]

VALID_EVENT_TYPES: frozenset[str] = frozenset(get_args(EventType))


@dataclass
class AuditEvent:
    """감사 활동 이벤트 — audit_log 테이블의 한 행과 1:1 매핑.

    Attributes:
        event_type: 6종 중 하나. action 컬럼에 저장된다.
        user_action: 사람이 읽을 수 있는 행동 설명.
                     예: "test.xlsx 업로드 (1234행)"
        details: 이벤트별 메타데이터. JSON 직렬화 가능해야 함.
        batch_id: 업로드 배치 식별자 (같은 파일 업로드에서 나온 이벤트 묶음).
        company_id, engagement_id: 다중 회사 환경용 컨텍스트.
        timestamp: dataclass 생성 시각. DB는 created_at DEFAULT current_timestamp
                   를 쓰므로 이 값은 애플리케이션 레벨 디버깅·트레이싱용.
    """

    event_type: EventType
    user_action: str
    details: dict = field(default_factory=dict)
    batch_id: str | None = None
    company_id: str | None = None
    engagement_id: str | None = None
    timestamp: datetime = field(default_factory=datetime.now)


class AuditTrail:
    """감사 활동 기록기 — engagement별 DuckDB에 사용자 이벤트를 누적."""

    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Args:
            conn: CompanyContext.db_path로 연 engagement별 DuckDB 커넥션.
        """
        self._conn = conn

    def log(self, event: AuditEvent) -> None:
        """이벤트를 audit_log 테이블에 기록.

        Graceful: record_event가 재시도 후 warning만 남기므로 호출측 미차단.
        단, 잘못된 event_type은 조기에 ValueError로 거부한다(쓰레기 기록 방지).
        """
        if event.event_type not in VALID_EVENT_TYPES:
            raise ValueError(
                f"invalid event_type: {event.event_type!r}. "
                f"허용: {sorted(VALID_EVENT_TYPES)}"
            )

        # Why: details가 먼저, user_action이 나중에 와야 호출자가 실수로
        #      details={"user_action": "딴소리"}를 넘겨도 정식 값이 살아남는다.
        merged_details = {**event.details, "user_action": event.user_action}

        record_event(
            self._conn,
            action=event.event_type,
            company_id=event.company_id,
            engagement_id=event.engagement_id,
            batch_id=event.batch_id,
            details=merged_details,
        )

    def get_trail(self, batch_id: str) -> pd.DataFrame:
        """특정 batch_id의 사용자 이벤트 조회 (시스템 이벤트 제외).

        Why:
            DuckDB의 '->>' JSON 연산자로 user_action을 독립 컬럼처럼 노출해
            호출측에서 json.loads/apply 없이 바로 DataFrame 컬럼으로 쓴다.
        """
        # Why: placeholder 문자열과 파라미터 리스트를 같은 변수에서 파생시켜
        #      개수 불일치 가능성을 원천 차단한다.
        user_event_types = sorted(VALID_EVENT_TYPES)
        placeholders = ",".join("?" * len(user_event_types))
        sql = f"""
            SELECT id,
                   action AS event_type,
                   actor,
                   company_id,
                   engagement_id,
                   batch_id,
                   details ->> 'user_action' AS user_action,
                   details,
                   created_at AS timestamp
            FROM audit_log
            WHERE batch_id = ?
              AND action IN ({placeholders})
            ORDER BY created_at ASC, id ASC
        """
        params = [batch_id, *user_event_types]
        return self._conn.execute(sql, params).df()

    def export_trail(self, batch_id: str, output_path: Path) -> Path:
        """감사 활동 로그를 CSV로 내보내기.

        encoding='utf-8-sig'는 BOM을 포함해 Excel에서 한글이 깨지지 않는다.
        """
        df = self.get_trail(batch_id)
        # Why: output_path가 tmp/a/b/c/trail.csv처럼 깊어도 부모 자동 생성
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path, index=False, encoding="utf-8-sig")
        return output_path
