"""WU-25 #86: XAI Narrative Report — 개별 전표 위험 사유서 자동 생성.

Why
---
파생변수 19종 + 탐지결과 조합은 감사인에게 수치 나열로는 의미 전달이 어렵다.
"왜 위험한가"를 1~3문장 자연어로 번역해 감사조서(ISA 230) 첨부 가능한
근거 자료를 생성한다. 룰 ID(L2-01, L3-06 등)를 사유서에 인용하여 추적성 확보.

Laziness 방어
-------------
LLM은 긴 JSON 배열 요청 시 중간 생략(Laziness) 또는 max_tokens 잘림으로
항목을 누락한다. 대응:
  1. 배치 크기 작게 (기본 15, settings.narrative_batch_size)
  2. requested_ids - received_ids diff 계산 → 누락분만 재귀 재시도
  3. max_retries 소진 시 수집분만 반환 + ERROR 로그

호출 주체: 대시보드 On-Demand (사용자 버튼 클릭 후 확인 다이얼로그)
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Iterator

import duckdb
import pandas as pd

from config.settings import get_settings
from src.feature.engine import EXPECTED_COLUMNS, FeatureCategory
from src.llm.api_client import ChatClient, get_chat_client
from src.llm.models import EntryNarrative, NarrativeBatch

logger = logging.getLogger(__name__)

# morpheme_tokens는 DB 미저장 → 제외. 실질 18종.
_FEATURE_CATS = (
    FeatureCategory.TIME,
    FeatureCategory.AMOUNT,
    FeatureCategory.PATTERN,
    FeatureCategory.TEXT,
)
FEATURE_COLUMNS: list[str] = [
    col
    for cat in _FEATURE_CATS
    for col in EXPECTED_COLUMNS[cat]
    if col != "morpheme_tokens"
]

_SYSTEM_PROMPT = (
    "You are an audit XAI assistant. For each journal entry, write a 1~3 sentence "
    "risk narrative in Korean (한국어). Cite triggered rule IDs (e.g., L2-01, L3-06) in "
    "parentheses. Be concise, evidence-based, and avoid speculation. "
    "Return one object per requested document_id."
)


def _chunked(seq: list, size: int) -> Iterator[list]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


class NarrativeReporter:
    """개별 전표 XAI 사유서 생성 + DuckDB 캐시."""

    def __init__(
        self,
        conn: duckdb.DuckDBPyConnection,
        client: ChatClient | None = None,
    ) -> None:
        self.conn = conn
        # Why: 대량 호출 → light 티어로 비용 최소화
        self.client = client if client is not None else get_chat_client("light")
        self._settings = get_settings()

    # ── 퍼블릭 ──────────────────────────────────────────────

    def generate_for_high_critical(self) -> int:
        """High/Critical 전표 중 캐시 미존재 건만 배치 생성. 신규 생성 건수 반환."""
        pending = self._select_pending()
        if not pending:
            return 0

        batch_size = self._settings.narrative_batch_size
        total_new = 0
        for batch_ids in _chunked(pending, batch_size):
            rows = self._fetch_entries(batch_ids)
            narratives = self._call_llm(rows)
            self._upsert_cache(narratives)
            total_new += len(narratives)

        return total_new

    def get_narratives(self, document_ids: list[str]) -> dict[str, str]:
        """캐시 우선 조회. 미존재 ID는 생성 후 저장하고 병합 반환."""
        if not document_ids:
            return {}

        cached = self._fetch_cache(document_ids)
        missing = [did for did in document_ids if did not in cached]
        if not missing:
            return cached

        batch_size = self._settings.narrative_batch_size
        for batch_ids in _chunked(missing, batch_size):
            rows = self._fetch_entries(batch_ids)
            narratives = self._call_llm(rows)
            self._upsert_cache(narratives)
            for n in narratives:
                cached[n.document_id] = n.rationale

        return cached

    # ── 내부 ────────────────────────────────────────────────

    def _select_pending(self) -> list[str]:
        """risk_level ∈ risk_levels AND 캐시 미존재 document_id 목록."""
        placeholders = ",".join(["?"] * len(self._settings.narrative_risk_levels))
        rows = self.conn.execute(
            f"""
            SELECT DISTINCT gl.document_id
            FROM general_ledger gl
            LEFT JOIN llm_narratives n USING (document_id)
            WHERE gl.risk_level IN ({placeholders})
              AND COALESCE(gl.anomaly_score, 0) > 0
              AND n.document_id IS NULL
            ORDER BY gl.document_id
            """,
            self._settings.narrative_risk_levels,
        ).fetchall()
        return [r[0] for r in rows]

    def _fetch_entries(self, document_ids: list[str]) -> pd.DataFrame:
        """파생변수 + 탐지결과 조회. 문서당 1행(다라인은 debit_amount 합산).

        Why: anomaly_score/risk_level/flagged_rules 및 파생변수 18종은
             score_aggregator / feature engine이 document 단위 동일 값으로
             기록한다 → ANY_VALUE가 안전. 라인별 상이 컬럼(debit_amount)만 SUM.
        """
        placeholders = ",".join(["?"] * len(document_ids))
        feature_sql = ", ".join(f"ANY_VALUE({c}) AS {c}" for c in FEATURE_COLUMNS)
        return self.conn.execute(
            f"""
            SELECT document_id,
                   ANY_VALUE(company_code)                        AS company_code,
                   ANY_VALUE(gl_account)                          AS gl_account,
                   COALESCE(ANY_VALUE(header_text),
                            ANY_VALUE(line_text), '')             AS description,
                   SUM(COALESCE(debit_amount, 0))                 AS debit_amount,
                   {feature_sql},
                   ANY_VALUE(anomaly_score)                       AS anomaly_score,
                   ANY_VALUE(risk_level)                          AS risk_level,
                   ANY_VALUE(flagged_rules)                       AS flagged_rules
            FROM general_ledger
            WHERE document_id IN ({placeholders})
            GROUP BY document_id
            """,
            document_ids,
        ).fetchdf()

    def _fetch_cache(self, document_ids: list[str]) -> dict[str, str]:
        placeholders = ",".join(["?"] * len(document_ids))
        rows = self.conn.execute(
            f"""
            SELECT document_id, narrative_text
            FROM llm_narratives
            WHERE document_id IN ({placeholders})
            """,
            document_ids,
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def _upsert_cache(self, narratives: Iterable[EntryNarrative]) -> None:
        tier = getattr(self.client, "model", "light")
        rows = [
            (n.document_id, n.rationale, ",".join(n.cited_rules), tier)
            for n in narratives
        ]
        if not rows:
            return
        # Why: DuckDB UPSERT는 ON CONFLICT 지원. entry_id 재생성 시 덮어쓰기.
        self.conn.executemany(
            """
            INSERT INTO llm_narratives (document_id, narrative_text, cited_rules, model_tier)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (document_id) DO UPDATE SET
                narrative_text = excluded.narrative_text,
                cited_rules    = excluded.cited_rules,
                model_tier     = excluded.model_tier,
                generated_at   = now()
            """,
            rows,
        )

    def _call_llm(
        self,
        rows: pd.DataFrame,
        max_retries: int | None = None,
    ) -> list[EntryNarrative]:
        """1 API 호출 + Laziness 방어 (누락 검증 + 재귀 재시도)."""
        if rows.empty:
            return []
        if max_retries is None:
            max_retries = self._settings.narrative_max_retries

        messages = self._build_prompt(rows)
        raw = self.client.chat(
            messages,
            format=NarrativeBatch.model_json_schema(),
        )
        try:
            parsed = NarrativeBatch.model_validate_json(raw)
            results = list(parsed.narratives)
        except Exception as exc:
            logger.error("NarrativeBatch JSON 파싱 실패: %s", exc)
            results = []

        # Why: LLM이 실제 플래그되지 않은 룰 ID를 인용(Hallucination)하면
        #      감사 증거로서의 신뢰성이 상실된다. cited_rules ⊆ flagged_rules
        #      교차 검증으로 허위 인용을 제거하고 경고 라벨을 부착한다.
        results = self._validate_cited_rules(results, rows)

        requested_ids = set(rows["document_id"])
        received_ids = {n.document_id for n in results}
        missing_ids = requested_ids - received_ids

        if missing_ids and max_retries > 0:
            logger.warning(
                "LLM 응답 누락 %d/%d건 — 누락분 재처리 (retry_left=%d)",
                len(missing_ids), len(requested_ids), max_retries,
            )
            missing_rows = rows[rows["document_id"].isin(missing_ids)]
            retry_results = self._call_llm(missing_rows, max_retries - 1)
            results.extend(retry_results)
        elif missing_ids:
            logger.error(
                "LLM 응답 누락 %d건 — 재시도 소진. 수집분(%d건)만 반환.",
                len(missing_ids), len(results),
            )

        return results

    @staticmethod
    def _validate_cited_rules(
        narratives: list[EntryNarrative],
        rows: pd.DataFrame,
    ) -> list[EntryNarrative]:
        """cited_rules ⊆ flagged_rules 교차 검증 — Hallucination 방어.

        LLM이 실제 플래그되지 않은 룰 ID를 인용한 경우:
        1. 허위 룰 ID를 cited_rules에서 제거
        2. 사유서 앞에 "[경고: 검증되지 않은 룰 참조 제거됨]" 라벨 부착
        3. 경고 로그 기록
        """
        if "flagged_rules" not in rows.columns:
            return narratives

        # Why: document_id → flagged_rules 매핑을 dict로 미리 구축하여 O(1) 조회
        #      iterrows() 대신 to_dict("records") 사용 — pandas 성능 최적화
        rules_by_doc: dict[str, set[str]] = {
            rec["document_id"]: {
                r.strip()
                for r in str(rec.get("flagged_rules") or "").split(",")
                if r.strip()
            }
            for rec in rows[["document_id", "flagged_rules"]].to_dict("records")
        }

        validated: list[EntryNarrative] = []
        for n in narratives:
            actual_rules = rules_by_doc.get(n.document_id, set())
            if not actual_rules and not n.cited_rules:
                validated.append(n)
                continue

            valid_cited = [r for r in n.cited_rules if r in actual_rules]
            hallucinated = [r for r in n.cited_rules if r not in actual_rules]

            if hallucinated:
                logger.warning(
                    "Hallucination 탐지 — doc=%s, 허위 룰=%s, 실제=%s",
                    n.document_id, hallucinated, sorted(actual_rules),
                )
                rationale = (
                    f"[경고: 검증되지 않은 룰 참조 제거됨 — {', '.join(hallucinated)}] "
                    + n.rationale
                )
                validated.append(
                    EntryNarrative(
                        document_id=n.document_id,
                        rationale=rationale,
                        cited_rules=valid_cited,
                    )
                )
            else:
                validated.append(n)

        return validated

    # ── 프롬프트 ────────────────────────────────────────────

    @staticmethod
    def _build_prompt(rows: pd.DataFrame) -> list[dict[str, str]]:
        """파생변수 18종 + 탐지결과를 JSON으로 직렬화한 프롬프트 생성."""
        # NaN/NaT → None 변환 후 JSON 직렬화
        payload = json.loads(rows.to_json(orient="records", date_format="iso"))
        user = (
            f"다음 {len(payload)}건의 전표에 대해 각각 위험 사유서를 생성하세요.\n"
            "각 사유서는 1~3문장, 한국어, 트리거된 룰 ID를 인용하세요.\n"
            "응답은 narratives 배열에 각 document_id별로 하나씩 포함해야 합니다.\n\n"
            f"{json.dumps(payload, ensure_ascii=False, default=str)}"
        )
        return [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]
