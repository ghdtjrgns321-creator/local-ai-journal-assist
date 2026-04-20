"""WU-25 #78 + #80: 감사 배치 자연어 요약 + 유의적 거래 합리성 평가.

Why
---
탐지 파이프라인이 산출한 수치(risk_level 카운트, flagged_rules 등)만으로는
감사인이 "이 배치에서 무엇이 가장 위험한가"를 즉각 파악하기 어렵다.
LLM reasoning 티어로 수치를 자연어 요약 + L4-03(이상고액) AND L4-01(매출이상)
동시 플래그 전표에 대한 사업상 합리성 보조 의견(ISA 240 §32(c))을 생성.

호출 주체: 대시보드 On-Demand (파이프라인에서 자동 호출하지 않음).
"""

from __future__ import annotations

import json
import logging

import duckdb

from config.settings import get_settings
from src.llm.api_client import ChatClient, get_chat_client
from src.llm.models import BatchInsight

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a senior audit analyst. Input accounting data is in English (SAP format); "
    "respond entirely in Korean (한국어). Always cite rule IDs (e.g., L4-03, L4-01) in rationales. "
    "Focus on material risk. temperature=0.1."
)


class InsightGenerator:
    """배치 요약 + 유의적 거래 평가 — reasoning 티어 1회 호출."""

    def __init__(
        self,
        conn: duckdb.DuckDBPyConnection,
        client: ChatClient | None = None,
    ) -> None:
        self.conn = conn
        self.client = client if client is not None else get_chat_client("reasoning")

    # ── 퍼블릭 ──────────────────────────────────────────────

    def generate_batch_insight(self) -> BatchInsight:
        """배치 전체 요약 + L4-03 AND L4-01 유의적 거래 평가."""
        stats = self._aggregate_stats()
        rule_stats = self._aggregate_rule_counts()
        sig_tx = self._query_significant_tx()
        messages = self._build_prompt(stats, rule_stats, sig_tx)

        raw = self.client.chat(
            messages,
            format=BatchInsight.model_json_schema(),
        )
        return BatchInsight.model_validate_json(raw)

    # ── DuckDB 집계 ─────────────────────────────────────────

    def _aggregate_stats(self) -> list[dict]:
        """risk_level별 카운트 + 차변금액 합계."""
        rows = self.conn.execute(
            """
            SELECT risk_level,
                   COUNT(*)          AS n,
                   SUM(debit_amount) AS total_debit
            FROM general_ledger
            WHERE risk_level IS NOT NULL
            GROUP BY risk_level
            ORDER BY n DESC
            """,
        ).fetchall()
        return [
            {"risk_level": r[0], "n": int(r[1]), "total_debit": float(r[2] or 0)}
            for r in rows
        ]

    def _aggregate_rule_counts(self, top_n: int = 10) -> list[dict]:
        """flagged_rules CSV를 unnest하여 룰 코드별 플래그 건수 Top N."""
        # Why: 공백 혼입(" L4-03")과 빈 토큰 방어 위해 trim + NULLIF 필터
        rows = self.conn.execute(
            """
            SELECT rule_code, COUNT(*) AS n
            FROM (
                SELECT trim(UNNEST(string_split(flagged_rules, ','))) AS rule_code
                FROM general_ledger
                WHERE flagged_rules IS NOT NULL AND flagged_rules != ''
            )
            WHERE rule_code != ''
            GROUP BY rule_code
            ORDER BY n DESC
            LIMIT ?
            """,
            [top_n],
        ).fetchall()
        return [{"rule_code": r[0], "n": int(r[1])} for r in rows]

    def _query_significant_tx(self, limit: int | None = None) -> list[dict]:
        """L4-03 AND L4-01 동시 플래그 전표 Top N (금액 내림차순).

        Why: LIKE '%L4-03%'는 'C080', 'C08A' 등 미래 룰 코드와 False positive
             발생. list_contains + string_split로 정확 매칭.

        PII 방어: created_by(작성자 ID)는 외부 API에 전달하면 개인정보 유출이므로
        조회하지 않는다. description(적요)은 감사 판단에 필수이므로 포함하되,
        LLM 프롬프트에서만 사용한다 (Export/저장 경로 아님).
        """
        if limit is None:
            limit = get_settings().insight_significant_tx_top_n
        rows = self.conn.execute(
            """
            SELECT document_id, company_code, gl_account, debit_amount,
                   COALESCE(header_text, line_text, '') AS description,
                   business_process, source, flagged_rules
            FROM general_ledger
            WHERE list_contains(string_split(flagged_rules, ','), 'L4-03')
              AND list_contains(string_split(flagged_rules, ','), 'L4-01')
            ORDER BY debit_amount DESC NULLS LAST
            LIMIT ?
            """,
            [limit],
        ).fetchall()
        cols = [
            "document_id", "company_code", "gl_account", "debit_amount",
            "description", "business_process", "source",
            "flagged_rules",
        ]
        return [dict(zip(cols, r)) for r in rows]

    # ── 프롬프트 ────────────────────────────────────────────

    @staticmethod
    def _build_prompt(
        stats: list[dict],
        rule_stats: list[dict],
        sig_tx: list[dict],
    ) -> list[dict[str, str]]:
        user = (
            "감사 배치 분석 결과입니다.\n\n"
            f"[위험도별 집계]\n{json.dumps(stats, ensure_ascii=False, default=str)}\n\n"
            f"[탐지 룰 Top]\n{json.dumps(rule_stats, ensure_ascii=False)}\n\n"
            f"[L4-03 AND L4-01 유의적 거래 Top {len(sig_tx)}건]\n"
            f"{json.dumps(sig_tx, ensure_ascii=False, default=str)}\n\n"
            "요구사항:\n"
            "1. summary: 배치 전체 이상 프로필을 3~5문장으로 요약\n"
            "2. top_risks: 가장 중요한 리스크 포인트 3~5개 (룰 ID 인용)\n"
            "3. significant_tx_opinions: 각 유의적 거래에 대한 사업상 합리성 평가\n"
            "   (business_rationale 1~2문장, audit_flag: reasonable/questionable/high_risk)"
        )
        return [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]
