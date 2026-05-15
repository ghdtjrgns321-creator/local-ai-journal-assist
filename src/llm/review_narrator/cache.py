"""Phase 3 v2 Review Narrator — review_narratives 캐시 UPSERT.

스펙 §4 (호출 전략) + §5 (DDL):
- candidate_id PK 단위 UPSERT.
- input_hash가 동일하면 LLM 재호출 없이 캐시 재사용.
- input이 변경되면 (priority/feature/메타 변경) 자동 무효화 + 재호출 트리거.

`compute_input_hash`는 candidate dict의 canonical JSON(SHA-256) → 16진 hex.
딕셔너리 key 순서 무관 결정성을 위해 `sort_keys=True`.

호출부 책임:
- LLM 호출 전: `read_narrative(conn, candidate_id, input_hash)`로 hit 확인 → 미스 시
  narrator.narrate() 호출 → `upsert_narrative()` 저장.
- 비용/토큰 메타는 호출자가 알 때만 주입(없으면 NULL).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC
from typing import Any

import duckdb

from src.llm.review_narrator.narrator import NarratorResult

logger = logging.getLogger(__name__)


def compute_input_hash(candidate: dict) -> str:
    """candidate dict의 결정론적 SHA-256 hex.

    Why: dict key 순서/공백 차이로 hash가 흔들리면 캐시가 무용지물이 된다.
        `sort_keys=True` + `ensure_ascii=False`로 canonical 직렬화.
    """
    canonical = json.dumps(candidate, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def read_narrative(conn: duckdb.DuckDBPyConnection, candidate_id: str) -> dict[str, Any] | None:
    """캐시에서 candidate 1건 조회. 없으면 None.

    Returns: {candidate_id, batch_id, journal_id, priority_rank, priority_score,
              confidence, narrative_json(dict), citation_valid, input_hash,
              model_tier, prompt_tokens, completion_tokens, cost_usd}
    """
    row = conn.execute(
        """
        SELECT candidate_id, batch_id, journal_id, priority_rank, priority_score,
               confidence, narrative_json, citation_valid, input_hash, model_tier,
               prompt_tokens, completion_tokens, cost_usd
        FROM review_narratives
        WHERE candidate_id = ?
        """,
        [candidate_id],
    ).fetchone()
    if row is None:
        return None
    return {
        "candidate_id": row[0],
        "batch_id": row[1],
        "journal_id": row[2],
        "priority_rank": row[3],
        "priority_score": row[4],
        "confidence": row[5],
        "narrative_json": json.loads(row[6]) if isinstance(row[6], str) else row[6],
        "citation_valid": row[7],
        "input_hash": row[8],
        "model_tier": row[9],
        "prompt_tokens": row[10],
        "completion_tokens": row[11],
        "cost_usd": row[12],
    }


def upsert_narrative(
    conn: duckdb.DuckDBPyConnection,
    candidate: dict,
    narrator_result: NarratorResult,
    *,
    batch_id: str,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    cost_usd: float | None = None,
) -> dict[str, Any]:
    """candidate 1건의 narrate 결과를 review_narratives에 UPSERT.

    동일 candidate_id에 input_hash가 같은 row가 이미 있으면 INSERT/UPDATE 모두 건너뛰고
    `{reused: True}` 반환. 다르면 새 값으로 덮어쓴다.

    동시성 가정 (중요)
    ----------------
    본 함수는 SELECT → INSERT/UPDATE 2-step으로 구현되어 있다.
    이는 created/updated/reused 3-state를 정확히 판별하기 위함이며, **단일 writer
    프로세스 전제**에서만 race-free이다. DuckDB는 기본적으로 단일 writer만 허용하지만,
    멀티 프로세스로 확장될 경우 `ON CONFLICT (candidate_id) DO UPDATE` SQL로 전환하고
    state는 RETURNING 또는 별도 audit 로그로 판별해야 한다.

    Returns: {"created": bool, "updated": bool, "reused": bool, "input_hash": str}
    """
    input_hash = compute_input_hash(candidate)
    candidate_id = candidate.get("candidate_id", "")
    if not candidate_id:
        raise ValueError("candidate dict에 candidate_id가 없음")

    existing = conn.execute(
        "SELECT input_hash FROM review_narratives WHERE candidate_id = ?",
        [candidate_id],
    ).fetchone()

    if existing is not None and existing[0] == input_hash:
        logger.debug("review_narratives cache hit: %s", candidate_id)
        return {
            "created": False,
            "updated": False,
            "reused": True,
            "input_hash": input_hash,
        }

    narrative = narrator_result.narrative
    narrative_json = narrative.model_dump_json()
    journal_id = candidate.get("journal_ref", {}).get("journal_id") or None
    citation_valid = narrator_result.citation_result.is_valid

    if existing is None:
        conn.execute(
            """
            INSERT INTO review_narratives (
                candidate_id, batch_id, journal_id,
                priority_rank, priority_score, confidence,
                narrative_json, citation_valid, input_hash, model_tier,
                prompt_tokens, completion_tokens, cost_usd
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                candidate_id,
                batch_id,
                journal_id,
                narrative.priority_rank,
                narrative.priority_score,
                narrative.confidence,
                narrative_json,
                citation_valid,
                input_hash,
                narrator_result.model_tier,
                prompt_tokens,
                completion_tokens,
                cost_usd,
            ],
        )
        return {
            "created": True,
            "updated": False,
            "reused": False,
            "input_hash": input_hash,
        }

    # input_hash 다름 → UPDATE
    conn.execute(
        """
        UPDATE review_narratives SET
            batch_id = ?, journal_id = ?,
            priority_rank = ?, priority_score = ?, confidence = ?,
            narrative_json = ?, citation_valid = ?, input_hash = ?, model_tier = ?,
            prompt_tokens = ?, completion_tokens = ?, cost_usd = ?
        WHERE candidate_id = ?
        """,
        [
            batch_id,
            journal_id,
            narrative.priority_rank,
            narrative.priority_score,
            narrative.confidence,
            narrative_json,
            citation_valid,
            input_hash,
            narrator_result.model_tier,
            prompt_tokens,
            completion_tokens,
            cost_usd,
            candidate_id,
        ],
    )
    return {
        "created": False,
        "updated": True,
        "reused": False,
        "input_hash": input_hash,
    }


# ── Sprint E2: 감사인 분류 UPDATE ──────────────────────────────


def update_audit_decision(
    conn: duckdb.DuckDBPyConnection,
    candidate_id: str,
    decision: str | None,
    note: str | None,
    user: str,
) -> dict[str, Any]:
    """감사인 분류·메모를 review_narratives에 저장한다.

    Sprint E2 워크플로우:
        감사인이 review queue candidate를 4종 결정값으로 분류하고 메모를 남기면,
        본 함수가 ``audit_decision`` / ``audit_note`` / ``reviewed_by`` /
        ``reviewed_at`` 4컬럼을 UPDATE한다. narrative_json 등 LLM 응답 필드는
        건드리지 않으므로 분류만 갱신할 때 안전하다.

    Args:
        conn: review_narratives DDL 마이그레이션이 적용된 DuckDB 연결.
        candidate_id: 분류 대상 candidate PK. 행이 존재하지 않으면 KeyError.
        decision: 4종 enum (`AUDIT_DECISION_VALUES`) 또는 None(분류 해제).
        note: 자유 메모. 빈 문자열·None 모두 허용 (None → NULL).
        user: 분류를 수행한 감사인 식별자. 빈 문자열 거부.

    Returns:
        {"updated": True, "candidate_id", "decision", "reviewed_at": iso8601}.

    Raises:
        ValueError: invalid decision 값 또는 빈 user.
        KeyError: candidate_id 행이 존재하지 않음.
    """
    # Why: hook(ruff)이 모듈 상단의 datetime/AUDIT_DECISION_VALUES import를 미사용으로
    #      제거하는 것을 방지하기 위해 본 함수 내에서 import한다. 본 헬퍼만 사용하므로
    #      함수 스코프 import가 더 안전.
    from datetime import datetime

    from src.db.schema import AUDIT_DECISION_VALUES

    if not user:
        raise ValueError("reviewed_by(user) is empty")
    if decision is not None and decision not in AUDIT_DECISION_VALUES:
        raise ValueError(
            f"invalid audit_decision: {decision!r}. allowed: "
            f"{sorted(AUDIT_DECISION_VALUES)} or None"
        )

    exists = conn.execute(
        "SELECT 1 FROM review_narratives WHERE candidate_id = ?",
        [candidate_id],
    ).fetchone()
    if exists is None:
        raise KeyError(f"candidate_id not found in review_narratives: {candidate_id!r}")

    reviewed_at = datetime.now(UTC).replace(tzinfo=None)
    conn.execute(
        """
        UPDATE review_narratives SET
            audit_decision = ?,
            audit_note = ?,
            reviewed_by = ?,
            reviewed_at = ?
        WHERE candidate_id = ?
        """,
        [decision, note, user, reviewed_at, candidate_id],
    )
    logger.info(
        "review_narratives audit_decision updated: %s → %s (by %s)",
        candidate_id,
        decision,
        user,
    )
    return {
        "updated": True,
        "candidate_id": candidate_id,
        "decision": decision,
        "reviewed_at": reviewed_at.isoformat(timespec="seconds"),
    }


def read_audit_decision(
    conn: duckdb.DuckDBPyConnection,
    candidate_id: str,
) -> dict[str, Any] | None:
    """저장된 감사인 분류·메모 4컬럼 조회. 행 없으면 None.

    카드 재진입 시 라디오·메모 위젯 기본값 복원에 사용한다.
    """
    row = conn.execute(
        """
        SELECT audit_decision, audit_note, reviewed_by, reviewed_at
        FROM review_narratives
        WHERE candidate_id = ?
        """,
        [candidate_id],
    ).fetchone()
    if row is None:
        return None
    return {
        "audit_decision": row[0],
        "audit_note": row[1],
        "reviewed_by": row[2],
        "reviewed_at": row[3],
    }
