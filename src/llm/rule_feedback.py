"""WU-30: 감사규칙 피드백 루프 — audit_rules.yaml 자동 제안 + 사용자 승인 저장.

Why
---
`config/audit_rules.yaml`의 5개 패턴(수기전표/가계정 키워드/가계정 코드/매출 계정/IC 식별자)은
회사별 CoA·적요 관행에 따라 달라진다. LLM이 새 데이터의 빈발 패턴을 집계·분석해
신규 룰 후보를 제안 → 사용자가 승인/거부 → 회사별 오버라이드에만 저장하여 Data Flywheel
입구를 자동화한다. 전역 `config/audit_rules.yaml`은 절대 수정하지 않는다.

핵심 안전장치
-------------
1. `propose()` / `apply()` 완전 분리 — 자동 반영 금지
2. 카테고리별 Top-K 집계 쿼리로 Prompt Overflow 방지
3. 3-way 중복검사: 전역 ∪ 회사 override 와 교집합인 제안은 저장 스킵
4. deep_merge(merger.py)가 리스트를 replace하므로, 회사 override에는
   "merged_현재_전체 + 신규" 전체 리스트를 저장해야 전역 값이 유실되지 않는다
5. 모든 승인/거부 이벤트는 `rule_feedback_log.jsonl`에 append-only 기록
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from config.settings import get_audit_rules
from src.company.merger import resolve_yaml_config
from src.company.repository import CompanyRepository
from src.hitl.feedback_store import build_feedback_event, record_feedback_event
from src.llm.api_client import ChatClient, get_chat_client
from src.llm.models import (
    RuleCategory,
    RuleFeedbackReport,
    RuleSuggestion,
)

logger = logging.getLogger(__name__)

# Why: actor 값이 그대로 jsonl 감사로그에 기록되므로 화이트리스트 패턴으로
#      로그 위변조/인젝션 방어. 영문/숫자/기본 특수문자 64자 이내.
_ACTOR_PATTERN = re.compile(r"^[A-Za-z0-9_\-@.]{1,64}$")
_TOPK_MAX = 1000


@dataclass(frozen=True)
class ApplyResult:
    """apply() 반환값 — 경로 + 실제 저장된/스킵된 건수."""

    path: Path
    applied: int
    skipped: int


def _validate_actor(actor: str) -> None:
    """actor 문자열이 감사로그에 안전하게 기록 가능한지 검증."""
    if not _ACTOR_PATTERN.match(actor or ""):
        raise ValueError(f"actor 포맷 불일치 (영문/숫자/._-@, 1~64자): {actor!r}")


_SYSTEM_PROMPT = (
    "You are a senior audit rule engineer. Accounting data is English SAP format; "
    "respond in Korean (한국어). Your job: propose NEW entries for audit_rules.yaml. "
    "Do not duplicate entries already listed in [기존 룰]. If a category has no "
    "meaningful pattern, return no suggestions for it. Every suggestion MUST include "
    "1~5 evidence samples drawn from the provided data. temperature=0.1."
)


class RuleFeedbackEngine:
    """감사룰 피드백 루프 엔진 — reasoning 티어 1회 호출로 5개 카테고리 제안."""

    def __init__(
        self,
        conn: duckdb.DuckDBPyConnection,
        existing_rules: dict[str, Any],
        client: ChatClient | None = None,
        *,
        topk: int = 20,
    ) -> None:
        """엔진 생성.

        Parameters
        ----------
        conn : 분석 대상 회사의 DuckDB 연결 (general_ledger 테이블 필수)
        existing_rules : resolve_yaml_config 결과 = 전역+회사 머지된 현재 룰 dict
        client : None이면 get_chat_client('reasoning') 자동 생성 (비가용 시 RuntimeError)
        topk : 카테고리별 빈도 집계 상위 K (Prompt Overflow 방지)

        Raises
        ------
        ValueError : topk가 int가 아니거나 [1, 1000] 범위를 벗어남
        """
        # Why: topk가 쿼리에 실리므로 생성자에서 타입/범위 강제 → SQL 파라미터 바인딩의
        #      두 번째 방어선. 매우 큰 값으로 LLM 프롬프트가 터지는 것도 함께 방지.
        if not isinstance(topk, int) or topk < 1 or topk > _TOPK_MAX:
            raise ValueError(f"topk must be int in [1, {_TOPK_MAX}], got {topk!r}")
        self.conn = conn
        self.existing = existing_rules.get("patterns", {}) if existing_rules else {}
        self.client = client if client is not None else get_chat_client("reasoning")
        self.topk = topk

    # ── 퍼블릭 ──────────────────────────────────────────────

    def propose(self) -> RuleFeedbackReport:
        """5개 카테고리 일괄 LLM 호출 → 중복 제거 후 RuleFeedbackReport 반환."""
        samples: dict[str, list[dict]] = {
            RuleCategory.MANUAL_SOURCE_CODES.value: self._sample_manual_sources(),
            RuleCategory.SUSPENSE_KEYWORDS.value: self._sample_suspense_keywords(),
            RuleCategory.SUSPENSE_ACCOUNT_CODES.value: self._sample_suspense_codes(),
            RuleCategory.REVENUE_ACCOUNT_PREFIXES.value: self._sample_revenue_prefixes(),
            RuleCategory.INTERCOMPANY_IDENTIFIERS.value: self._sample_intercompany(),
        }
        messages = self._build_prompt(samples, self.existing)
        raw = self.client.chat(
            messages,
            format=RuleFeedbackReport.model_json_schema(),
        )
        report = RuleFeedbackReport.model_validate_json(raw)

        # 메타 주입 + 코드 레벨 이중 중복 필터
        report.generated_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        report.sample_summary = {cat: len(rows) for cat, rows in samples.items()}
        report.suggestions = self._filter_duplicates(report.suggestions)
        return report

    def apply(
        self,
        suggestions: list[RuleSuggestion],
        company_id: str,
        repo: CompanyRepository,
        *,
        actor: str = "auditor",
        engagement_id: str | None = None,
        batch_id: str | None = None,
    ) -> ApplyResult:
        """승인된 제안을 회사별 `audit_rules.yaml` 오버라이드에 저장.

        Why deep_merge가 리스트 replace이므로 회사 override에는
        "머지된 현재 전체 + 신규" 리스트 전체를 담아야 전역 값 유실이 없다.

        Returns:
            ApplyResult(path, applied, skipped) — 실제 저장된 건수와 스킵된 건수.
            suggestions가 비어 있으면 path만 유효(파일 생성 안함), applied=skipped=0.

        Raises:
            ValueError : actor가 화이트리스트 패턴(_ACTOR_PATTERN)에 맞지 않음
        """
        _validate_actor(actor)
        if not suggestions:
            return ApplyResult(
                path=repo.company_dir(company_id) / "audit_rules.yaml",
                applied=0,
                skipped=0,
            )

        # 1) 전역 + 기존 회사 override 머지본 = 현재 사용 중 룰
        global_rules = get_audit_rules()
        existing_override = repo.load_company_audit_rules(company_id) or {}
        merged = resolve_yaml_config(global_rules, existing_override)
        patterns = merged.setdefault("patterns", {})

        applied: list[RuleSuggestion] = []
        for s in suggestions:
            if self._merge_into_patterns(patterns, s):
                applied.append(s)

        # 2) 회사 override yaml에는 머지된 전체 리스트를 그대로 저장
        #    (전역 리스트가 deep_merge로 replace되어도 유실 없음)
        override_to_save = dict(existing_override)
        override_to_save["patterns"] = patterns
        path = repo.save_company_yaml(company_id, "audit_rules.yaml", override_to_save)

        # 3) 전역 설정 캐시 무효화 (lru_cache) — monkeypatch로 교체된 경우 속성 없음
        clear_fn = getattr(get_audit_rules, "cache_clear", None)
        if callable(clear_fn):
            clear_fn()

        # 4) 감사 로그 append (실제 저장된 것만)
        _append_log(repo, company_id, applied, actor=actor, action="approved")
        _record_feedback_events(
            self.conn,
            company_id=company_id,
            engagement_id=engagement_id,
            batch_id=batch_id,
            actor=actor,
            action="approved",
            suggestions=applied,
        )

        logger.info(
            "rule_feedback 적용: company=%s, 저장 %d건, 스킵 %d건",
            company_id,
            len(applied),
            len(suggestions) - len(applied),
        )
        return ApplyResult(
            path=path,
            applied=len(applied),
            skipped=len(suggestions) - len(applied),
        )

    @staticmethod
    def log_rejections(
        suggestions: list[RuleSuggestion],
        company_id: str,
        repo: CompanyRepository,
        *,
        actor: str = "auditor",
        conn: duckdb.DuckDBPyConnection | None = None,
        engagement_id: str | None = None,
        batch_id: str | None = None,
    ) -> None:
        """거부된 제안을 감사 로그에만 기록 (yaml 변경 없음).

        Why 정적 메서드로 노출 — 거부는 LLM client가 전혀 필요 없으므로
             대시보드가 엔진을 재생성하지 않아도 되도록 분리한다.

        Raises:
            ValueError : actor 포맷 불일치
        """
        _validate_actor(actor)
        _append_log(repo, company_id, suggestions, actor=actor, action="rejected")
        _record_feedback_events(
            conn,
            company_id=company_id,
            engagement_id=engagement_id,
            batch_id=batch_id,
            actor=actor,
            action="rejected",
            suggestions=suggestions,
        )

    # ── DuckDB 카테고리별 샘플링 (Top-K 집계 전용) ───────────

    def _sample_manual_sources(self) -> list[dict]:
        """source 컬럼 빈도 Top-K — 기존 manual_source_codes 미포함만."""
        rows = self.conn.execute(
            """
            SELECT source, COUNT(*) AS n
            FROM general_ledger
            WHERE source IS NOT NULL AND source != ''
            GROUP BY source
            ORDER BY n DESC
            LIMIT ?
            """,
            [self.topk],
        ).fetchall()
        existing = {s.lower() for s in self.existing.get("manual_source_codes", [])}
        out: list[dict] = []
        for src, n in rows:
            if src.lower() in existing:
                continue
            evidence = self._fetch_evidence_by_source(src)
            out.append({"value": src, "count": int(n), "evidence": evidence})
        return out

    def _sample_suspense_keywords(self) -> list[dict]:
        """header_text 빈도 Top-K — 빈발 적요만 추려 LLM에 전달."""
        # Why: 원시 행 대신 distinct header_text 집계로 Prompt Overflow 방지.
        #      2배 페치 없이 LIMIT로 직접 제한하여 불필요한 전송량 제거.
        rows = self.conn.execute(
            """
            SELECT header_text, COUNT(*) AS n
            FROM general_ledger
            WHERE header_text IS NOT NULL AND header_text != ''
            GROUP BY header_text
            ORDER BY n DESC
            LIMIT ?
            """,
            [self.topk],
        ).fetchall()
        out: list[dict] = []
        for text, n in rows:
            evidence = self._fetch_evidence_by_header(text)
            out.append({"value": text, "count": int(n), "evidence": evidence})
        return out

    def _sample_suspense_codes(self) -> list[dict]:
        """gl_account 중 가계정성 적요 비율이 높은 코드 Top-K."""
        existing_codes = set(self.existing.get("suspense_account_codes", []))
        rows = self.conn.execute(
            """
            SELECT gl_account,
                   COUNT(*) AS n,
                   AVG(CASE WHEN lower(COALESCE(header_text,'')) LIKE '%suspense%'
                              OR lower(COALESCE(header_text,'')) LIKE '%clearing%'
                              OR lower(COALESCE(header_text,'')) LIKE '%temporary%'
                              OR header_text LIKE '%가수금%'
                              OR header_text LIKE '%가지급%'
                              OR header_text LIKE '%임시%'
                         THEN 1.0 ELSE 0.0 END) AS suspense_ratio
            FROM general_ledger
            WHERE gl_account IS NOT NULL
            GROUP BY gl_account
            HAVING suspense_ratio >= 0.2 AND n >= 3
            ORDER BY suspense_ratio DESC, n DESC
            LIMIT ?
            """,
            [self.topk],
        ).fetchall()
        out: list[dict] = []
        for code, n, ratio in rows:
            if code in existing_codes:
                continue
            evidence = self._fetch_evidence_by_account(code)
            out.append(
                {
                    "value": code,
                    "count": int(n),
                    "suspense_ratio": round(float(ratio), 3),
                    "evidence": evidence,
                }
            )
        return out

    def _sample_revenue_prefixes(self) -> list[dict]:
        """gl_account 1자리 prefix별 대변 합계 Top 5 — 기존 prefix 제외."""
        existing = set(self.existing.get("revenue_account_prefixes", []))
        rows = self.conn.execute(
            """
            SELECT SUBSTR(gl_account, 1, 1) AS pfx,
                   SUM(credit_amount) AS credit_total,
                   COUNT(*) AS n
            FROM general_ledger
            WHERE gl_account IS NOT NULL AND credit_amount > 0
            GROUP BY pfx
            ORDER BY credit_total DESC
            LIMIT 5
            """,
        ).fetchall()
        out: list[dict] = []
        for pfx, total, n in rows:
            if pfx in existing or not pfx:
                continue
            evidence = self._fetch_evidence_by_prefix(pfx)
            out.append(
                {
                    "value": pfx,
                    "count": int(n),
                    "credit_total": float(total or 0),
                    "evidence": evidence,
                }
            )
        return out

    def _sample_intercompany(self) -> list[dict]:
        """IC 키워드가 포함된 전표의 (차변계정, 대변계정) 쌍 Top-K.

        Why: 동일 document_id 내에서 debit>0 행의 gl_account와 credit>0 행의
             gl_account를 JOIN으로 짝지어 공출현 빈도를 센다.
        """
        existing_pairs = {
            (p.get("receivable"), p.get("payable"))
            for p in self.existing.get("intercompany", {}).get("pairs", [])
        }
        rows = self.conn.execute(
            """
            WITH ic_docs AS (
                SELECT DISTINCT document_id
                FROM general_ledger
                WHERE lower(COALESCE(header_text,'')) LIKE '%intercompany%'
                   OR lower(COALESCE(header_text,'')) LIKE '%ic %'
                   OR lower(COALESCE(header_text,'')) LIKE '% ic'
                   OR header_text LIKE '%관계사%'
            ),
            dr AS (
                SELECT document_id, gl_account
                FROM general_ledger
                WHERE document_id IN (SELECT document_id FROM ic_docs)
                  AND debit_amount > 0 AND gl_account IS NOT NULL
            ),
            cr AS (
                SELECT document_id, gl_account
                FROM general_ledger
                WHERE document_id IN (SELECT document_id FROM ic_docs)
                  AND credit_amount > 0 AND gl_account IS NOT NULL
            )
            SELECT dr.gl_account AS receivable,
                   cr.gl_account AS payable,
                   COUNT(*) AS n
            FROM dr JOIN cr USING (document_id)
            GROUP BY receivable, payable
            ORDER BY n DESC
            LIMIT ?
            """,
            [self.topk],
        ).fetchall()
        out: list[dict] = []
        for rec, pay, n in rows:
            if (rec, pay) in existing_pairs:
                continue
            evidence = self._fetch_evidence_by_ic_pair(rec, pay)
            out.append(
                {
                    "receivable": rec,
                    "payable": pay,
                    "count": int(n),
                    "evidence": evidence,
                }
            )
        return out

    # ── Evidence 조회 헬퍼 ──────────────────────────────────

    def _fetch_evidence_by_source(self, source: str, limit: int = 3) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT document_id, gl_account,
                   COALESCE(header_text, line_text, '') AS description,
                   debit_amount, credit_amount
            FROM general_ledger
            WHERE source = ?
            LIMIT ?
            """,
            [source, limit],
        ).fetchall()
        return [self._row_to_evidence(r) for r in rows]

    def _fetch_evidence_by_header(self, text: str, limit: int = 3) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT document_id, gl_account,
                   COALESCE(header_text, line_text, '') AS description,
                   debit_amount, credit_amount
            FROM general_ledger
            WHERE header_text = ?
            LIMIT ?
            """,
            [text, limit],
        ).fetchall()
        return [self._row_to_evidence(r) for r in rows]

    def _fetch_evidence_by_account(self, code: str, limit: int = 3) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT document_id, gl_account,
                   COALESCE(header_text, line_text, '') AS description,
                   debit_amount, credit_amount
            FROM general_ledger
            WHERE gl_account = ?
            LIMIT ?
            """,
            [code, limit],
        ).fetchall()
        return [self._row_to_evidence(r) for r in rows]

    def _fetch_evidence_by_prefix(self, pfx: str, limit: int = 3) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT document_id, gl_account,
                   COALESCE(header_text, line_text, '') AS description,
                   debit_amount, credit_amount
            FROM general_ledger
            WHERE SUBSTR(gl_account, 1, 1) = ? AND credit_amount > 0
            ORDER BY credit_amount DESC
            LIMIT ?
            """,
            [pfx, limit],
        ).fetchall()
        return [self._row_to_evidence(r) for r in rows]

    def _fetch_evidence_by_ic_pair(
        self,
        receivable: str,
        payable: str,
        limit: int = 3,
    ) -> list[dict]:
        """IC 쌍 증거: 동일 document_id 안에서 두 계정이 동시에 등장한 전표만."""
        # Why: 단순 IN 필터는 해당 계정을 가진 모든 전표를 섞어 반환하므로
        #      쌍의 실제 근거가 아닌 일반 거래가 evidence로 오염될 수 있다.
        #      document_id 레벨 EXISTS 서브쿼리로 "두 계정이 동시에 나타난 전표"로 한정.
        rows = self.conn.execute(
            """
            WITH ic_docs AS (
                SELECT document_id FROM general_ledger
                WHERE gl_account = ? AND debit_amount > 0
                INTERSECT
                SELECT document_id FROM general_ledger
                WHERE gl_account = ? AND credit_amount > 0
            )
            SELECT document_id, gl_account,
                   COALESCE(header_text, line_text, '') AS description,
                   debit_amount, credit_amount
            FROM general_ledger
            WHERE document_id IN (SELECT document_id FROM ic_docs)
              AND gl_account IN (?, ?)
            ORDER BY document_id
            LIMIT ?
            """,
            [receivable, payable, receivable, payable, limit],
        ).fetchall()
        return [self._row_to_evidence(r) for r in rows]

    @staticmethod
    def _row_to_evidence(row: tuple) -> dict:
        return {
            "document_id": row[0],
            "gl_account": row[1] or "",
            "description": row[2] or "",
            "debit_amount": float(row[3] or 0),
            "credit_amount": float(row[4] or 0),
        }

    # ── 프롬프트 / 중복 필터 / 병합 ─────────────────────────

    @staticmethod
    def _build_prompt(
        samples: dict[str, list[dict]],
        existing: dict[str, Any],
    ) -> list[dict[str, str]]:
        user = (
            "감사룰 제안을 위해 아래 데이터와 기존 룰을 참고하세요.\n\n"
            f"[기존 룰]\n{json.dumps(existing, ensure_ascii=False)}\n\n"
            f"[카테고리별 빈발 후보]\n{json.dumps(samples, ensure_ascii=False, default=str)}\n\n"
            "요구사항:\n"
            "1. 각 카테고리마다 유의미한 신규 값이 있으면 RuleSuggestion으로 제안\n"
            "2. 기존 룰에 있는 값은 제안하지 말 것 (중복 금지)\n"
            "3. 제안마다 evidence_samples 1~5건 필수 (위 후보의 evidence 배열 사용)\n"
            "4. IC 카테고리는 intercompany_pair 필드에 {receivable, payable} 중첩, "
            "   그 외 카테고리는 proposed_value(string)만 사용\n"
            "5. confidence는 low/medium/high 중 하나, rationale은 한국어 1~3문장\n"
            "6. 충돌 가능성(정규식/접두사 겹침)이 있으면 conflicts_with_existing에 기재\n"
        )
        return [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]

    def _filter_duplicates(
        self,
        suggestions: list[RuleSuggestion],
    ) -> list[RuleSuggestion]:
        """기존 룰(전역 머지본)과의 중복을 코드 레벨에서 한 번 더 제거."""
        manual = {s.lower() for s in self.existing.get("manual_source_codes", [])}
        sk = set(self.existing.get("suspense_keywords", []))
        sc = set(self.existing.get("suspense_account_codes", []))
        rp = set(self.existing.get("revenue_account_prefixes", []))
        pairs = {
            (p.get("receivable"), p.get("payable"))
            for p in self.existing.get("intercompany", {}).get("pairs", [])
        }
        kept: list[RuleSuggestion] = []
        for s in suggestions:
            if s.category == RuleCategory.MANUAL_SOURCE_CODES:
                if s.proposed_value.lower() in manual:
                    continue
            elif s.category == RuleCategory.SUSPENSE_KEYWORDS:
                if s.proposed_value in sk:
                    continue
            elif s.category == RuleCategory.SUSPENSE_ACCOUNT_CODES:
                if s.proposed_value in sc:
                    continue
            elif s.category == RuleCategory.REVENUE_ACCOUNT_PREFIXES:
                if s.proposed_value in rp:
                    continue
            elif s.category == RuleCategory.INTERCOMPANY_IDENTIFIERS:
                pair = s.intercompany_pair
                if pair is None or (pair.receivable, pair.payable) in pairs:
                    continue
            kept.append(s)
        return kept

    @staticmethod
    def _merge_into_patterns(
        patterns: dict[str, Any],
        s: RuleSuggestion,
    ) -> bool:
        """head-merged 'patterns' dict에 제안 1건을 append (중복 시 False).

        Why: 전역 ∪ 회사 override 머지본이 입력이므로 여기서 중복 검사 = 3-way 최종 필터.
        """
        if s.category == RuleCategory.MANUAL_SOURCE_CODES:
            return _append_unique(patterns, "manual_source_codes", s.proposed_value)
        if s.category == RuleCategory.SUSPENSE_KEYWORDS:
            return _append_unique(patterns, "suspense_keywords", s.proposed_value)
        if s.category == RuleCategory.SUSPENSE_ACCOUNT_CODES:
            return _append_unique(patterns, "suspense_account_codes", s.proposed_value)
        if s.category == RuleCategory.REVENUE_ACCOUNT_PREFIXES:
            return _append_unique(patterns, "revenue_account_prefixes", s.proposed_value)
        if s.category == RuleCategory.INTERCOMPANY_IDENTIFIERS:
            pair = s.intercompany_pair
            if pair is None:
                return False
            ic = patterns.setdefault("intercompany", {}).setdefault("pairs", [])
            new = {"receivable": pair.receivable, "payable": pair.payable}
            if any(
                p.get("receivable") == new["receivable"] and p.get("payable") == new["payable"]
                for p in ic
            ):
                return False
            ic.append(new)
            return True
        return False


# ── 모듈 레벨 헬퍼 ───────────────────────────────────────────


def _append_unique(patterns: dict[str, Any], key: str, value: str) -> bool:
    """patterns[key] 리스트에 value를 append. 이미 존재하면 False."""
    if not value:
        return False
    lst = patterns.setdefault(key, [])
    if value in lst:
        return False
    lst.append(value)
    return True


def _append_log(
    repo: CompanyRepository,
    company_id: str,
    suggestions: list[RuleSuggestion],
    *,
    actor: str,
    action: str,
) -> None:
    """`data/companies/{id}/rule_feedback_log.jsonl` append-only 기록.

    Why 모듈 함수로 분리 — 거부(log_rejections) 경로에서 엔진/LLM client 없이도 호출 가능.
    """
    if not suggestions:
        return
    log_path = repo.company_dir(company_id) / "rule_feedback_log.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    with open(log_path, "a", encoding="utf-8") as f:
        for s in suggestions:
            f.write(
                json.dumps(
                    {
                        "timestamp": ts,
                        "actor": actor,
                        "action": action,
                        "category": s.category.value,
                        "proposed_value": s.proposed_value,
                        "intercompany_pair": (
                            s.intercompany_pair.model_dump() if s.intercompany_pair else None
                        ),
                        "confidence": s.confidence,
                        "rationale": s.rationale,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def _record_feedback_events(
    conn: duckdb.DuckDBPyConnection | None,
    *,
    company_id: str,
    engagement_id: str | None,
    batch_id: str | None,
    actor: str,
    action: str,
    suggestions: list[RuleSuggestion],
) -> None:
    """Mirror rule feedback decisions into normalized feedback events."""
    if conn is None or not suggestions:
        return
    decision = "approved" if action == "approved" else "rejected"
    for suggestion in suggestions:
        first_evidence = suggestion.evidence_samples[0] if suggestion.evidence_samples else None
        payload = {
            "category": suggestion.category.value,
            "proposed_value": suggestion.proposed_value,
            "confidence": suggestion.confidence,
            "rationale": suggestion.rationale,
            "intercompany_pair": (
                suggestion.intercompany_pair.model_dump()
                if suggestion.intercompany_pair is not None
                else None
            ),
        }
        record_feedback_event(
            conn,
            build_feedback_event(
                event_type="rule_feedback",
                decision=decision,
                company_id=company_id,
                engagement_id=engagement_id,
                batch_id=batch_id,
                document_id=(first_evidence.document_id if first_evidence else None),
                reason=suggestion.rationale,
                payload=payload,
                created_by=actor,
            ),
        )
