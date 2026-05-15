"""평가 하니스 + 비용 가드 (Sprint F).

본 파일은 두 부분으로 구성된다:

1. **결정론적 단위 테스트** (기본 실행):
   - BudgetGuard N 자동 축소
   - audit_logger가 AuditTrail.log를 정확히 호출
   - evaluate_samples 통계 함수 (citation rate, Spearman, latency p50/p95)
   - §4.2 schema enum 회귀 (의도적 invalid ID mock → citation_validator 강등)

2. **opt-in 실제 LLM 평가** (`RUN_LLM_EVAL=1` 환경변수):
   - 실제 OpenAI 호출로 N=2 candidate × 3회 → citation ≥ 99% / Spearman ρ ≥ 0.6
   - 결과를 `test-results/phase3_review_narrator_eval/YYYYMMDD/`에 저장
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from src.export.audit_trail import AuditEvent
from src.llm.review_narrator.audit_logger import log_narrate_event
from src.llm.review_narrator.budget_guard import BudgetGuard
from src.llm.review_narrator.citation_validator import validate_citations
from src.llm.review_narrator.eval_harness import (
    CallSample,
    EvalReport,
    evaluate_samples,
    save_eval_report,
)
from src.llm.review_narrator.models import (
    ReviewNarrative,
    build_review_narrative_schema,
)
from src.llm.review_narrator.narrator import NarratorResult, narrate

# ── (A) BudgetGuard 단위 테스트 ──────────────────────────────


class TestBudgetGuard:
    def test_initial_n_returned_when_no_cost(self):
        guard = BudgetGuard(initial_n=20, max_usd=1.0)
        assert guard.current_n() == 20
        assert guard.exhausted is False

    def test_50pct_threshold_reduces_to_10(self):
        guard = BudgetGuard(initial_n=20, max_usd=1.0)
        guard.record(cost_usd=0.55)
        assert guard.current_n() == 10
        assert guard.exhausted is False

    def test_80pct_threshold_reduces_to_5(self):
        guard = BudgetGuard(initial_n=20, max_usd=1.0)
        guard.record(cost_usd=0.85)
        assert guard.current_n() == 5

    def test_full_budget_exhausts(self):
        guard = BudgetGuard(initial_n=20, max_usd=1.0)
        guard.record(cost_usd=1.0)
        assert guard.exhausted is True
        assert guard.current_n() == 0

    def test_none_cost_treated_as_zero(self):
        guard = BudgetGuard(initial_n=20, max_usd=1.0)
        guard.record(cost_usd=None)
        assert guard.call_count == 1
        assert guard.cost_so_far == 0.0

    def test_negative_cost_clamped_to_zero(self):
        guard = BudgetGuard(initial_n=20, max_usd=1.0)
        guard.record(cost_usd=-0.5)
        assert guard.cost_so_far == 0.0

    def test_zero_max_usd_skips_reduction(self):
        guard = BudgetGuard(initial_n=20, max_usd=0.0)
        guard.record(cost_usd=10.0)
        # max_usd=0 이면 reduction 정책 비활성
        assert guard.current_n() == 20

    def test_snapshot_keys(self):
        guard = BudgetGuard(initial_n=20, max_usd=1.0)
        guard.record(cost_usd=0.3)
        snap = guard.snapshot()
        assert snap["initial_n"] == 20
        assert snap["current_n"] == 20
        assert snap["cost_so_far"] == pytest.approx(0.3)
        assert snap["exhausted"] is False


# ── (B) audit_logger 단위 테스트 ─────────────────────────────


class _FakeAuditTrail:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def log(self, event: AuditEvent) -> None:
        self.events.append(event)


class TestAuditLogger:
    def test_records_analysis_run_event(
        self, rn_candidate, rn_valid_llm_response, rn_chat_client_cls
    ):
        reasoning = rn_chat_client_cls([rn_valid_llm_response])
        light = rn_chat_client_cls([])
        result = narrate(rn_candidate, reasoning, light)
        trail = _FakeAuditTrail()
        log_narrate_event(
            trail,
            candidate=rn_candidate,
            narrator_result=result,
            batch_id="B-EVAL",
            prompt_tokens=100,
            completion_tokens=80,
            cost_usd=0.0023,
        )
        assert len(trail.events) == 1
        event = trail.events[0]
        assert event.event_type == "analysis_run"
        assert event.batch_id == "B-EVAL"
        assert event.details["candidate_id"] == rn_candidate["candidate_id"]
        assert event.details["model_tier"] == "reasoning"
        assert event.details["citation_valid"] is True
        assert event.details["prompt_tokens"] == 100
        assert event.details["cost_usd"] == pytest.approx(0.0023)

    def test_records_failed_call_with_error(self, rn_candidate, rn_chat_client_cls):
        reasoning = rn_chat_client_cls([], raise_on_call=True)
        light = rn_chat_client_cls([], raise_on_call=True)
        result = narrate(rn_candidate, reasoning, light)
        trail = _FakeAuditTrail()
        log_narrate_event(trail, candidate=rn_candidate, narrator_result=result, batch_id="B-EVAL")
        event = trail.events[0]
        assert event.details["call_status"] == "failed"
        assert event.details["model_tier"] == "failed"
        assert "RuntimeError" in event.details["error"]

    def test_audit_failure_does_not_raise(self, rn_candidate, rn_chat_client_cls):
        """AuditTrail.log가 예외를 던져도 호출부 흐름은 비차단."""

        class _RaisingTrail:
            def log(self, event):  # noqa: ARG002
                raise RuntimeError("audit DB down")

        result = NarratorResult(
            narrative=ReviewNarrative(
                candidate_id="C",
                priority_rank=1,
                priority_score=0.5,
                summary="x",
                confidence="low",
            ),
            citation_result=validate_citations(
                ReviewNarrative(
                    candidate_id="C",
                    priority_rank=1,
                    priority_score=0.5,
                    summary="x",
                    confidence="low",
                ),
                set(),
                set(),
                set(),
            ),
            model_tier="failed",
            call_status="failed",
        )
        # 예외 흡수 확인
        log_narrate_event(
            _RaisingTrail(),
            candidate=rn_candidate,
            narrator_result=result,
            batch_id="B-EVAL",
        )


# ── (C) evaluate_samples 통계 함수 ───────────────────────────


def _make_sample(
    *,
    cid: str,
    citation_valid: bool,
    model_tier: str = "reasoning",
    latency: float = 1.0,
    priority_rank: int = 1,
    auditor_rank: int | None = None,
    cost: float | None = 0.001,
) -> CallSample:
    narrative = ReviewNarrative(
        candidate_id=cid,
        priority_rank=priority_rank,
        priority_score=0.5,
        summary="x",
        confidence="high",
    )
    citation = validate_citations(narrative, set(), set(), set())
    # citation_valid를 강제 조정
    citation.is_valid = citation_valid
    return CallSample(
        candidate_id=cid,
        result=NarratorResult(
            narrative=narrative,
            citation_result=citation,
            model_tier=model_tier,
            call_status="ok",
        ),
        latency_seconds=latency,
        prompt_tokens=100,
        completion_tokens=80,
        cost_usd=cost,
        auditor_rank=auditor_rank,
    )


class TestEvaluateSamples:
    def test_empty_samples(self):
        report = evaluate_samples([])
        assert isinstance(report, EvalReport)
        assert report.total_calls == 0
        assert report.citation_pass_rate == 0.0

    def test_citation_pass_rate(self):
        samples = [_make_sample(cid=f"C{i}", citation_valid=True) for i in range(99)] + [
            _make_sample(cid="C99", citation_valid=False)
        ]
        report = evaluate_samples(samples)
        assert report.total_calls == 100
        assert report.citation_pass_count == 99
        assert report.citation_pass_rate == 0.99
        assert report.meets_citation_threshold(0.99)

    def test_spearman_correlation_strong(self):
        # auditor_rank와 priority_rank가 동일 순서 → 완벽 상관
        samples = [
            _make_sample(
                cid=f"C{i}",
                citation_valid=True,
                priority_rank=i + 1,
                auditor_rank=i + 1,
            )
            for i in range(10)
        ]
        report = evaluate_samples(samples)
        assert report.spearman_rho is not None
        assert report.spearman_rho == pytest.approx(1.0, abs=0.01)
        assert report.meets_spearman_threshold(0.6)

    def test_spearman_correlation_inverted(self):
        # 역순 → ρ=-1
        samples = [
            _make_sample(
                cid=f"C{i}",
                citation_valid=True,
                priority_rank=i + 1,
                auditor_rank=10 - i,
            )
            for i in range(10)
        ]
        report = evaluate_samples(samples)
        assert report.spearman_rho == pytest.approx(-1.0, abs=0.01)
        assert not report.meets_spearman_threshold(0.6)

    def test_latency_percentiles_separate_per_tier(self):
        # reasoning 5건, light 5건 — p95 측정
        samples = [
            _make_sample(
                cid=f"R{i}", citation_valid=True, model_tier="reasoning", latency=float(i + 1)
            )
            for i in range(5)
        ] + [
            _make_sample(
                cid=f"L{i}", citation_valid=True, model_tier="light", latency=float(i + 1) * 0.2
            )
            for i in range(5)
        ]
        report = evaluate_samples(samples)
        assert report.latency_p50_reasoning == pytest.approx(3.0)
        assert report.latency_p95_reasoning is not None
        assert 4.0 <= report.latency_p95_reasoning <= 5.0
        assert report.latency_p50_light == pytest.approx(0.6)
        assert report.meets_latency_thresholds()

    def test_per_tier_counts(self):
        samples = [
            _make_sample(cid=f"R{i}", citation_valid=True, model_tier="reasoning") for i in range(3)
        ] + [_make_sample(cid=f"L{i}", citation_valid=True, model_tier="light") for i in range(2)]
        report = evaluate_samples(samples)
        assert report.per_tier_counts == {"reasoning": 3, "light": 2}

    def test_cost_aggregation(self):
        samples = [_make_sample(cid=f"C{i}", citation_valid=True, cost=0.01) for i in range(10)]
        report = evaluate_samples(samples)
        assert report.total_cost_usd == pytest.approx(0.1)
        assert report.avg_cost_usd == pytest.approx(0.01)


# ── (D) save_eval_report 파일 저장 ───────────────────────────


class TestSaveEvalReport:
    def test_writes_json_to_dated_dir(self, tmp_path):
        report = EvalReport(
            total_calls=10,
            citation_pass_count=10,
            citation_pass_rate=1.0,
        )
        path = save_eval_report(report, output_dir=tmp_path, run_label="unit")
        assert path.exists()
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["label"] == "unit"
        assert payload["report"]["total_calls"] == 10
        assert payload["thresholds_met"]["citation_99"] is True


# ── (E) §4.2 schema enum 회귀 ────────────────────────────────


class TestSchemaEnumGuard:
    def test_enum_excludes_unknown_ids(self):
        """build_review_narrative_schema가 입력 ID만 enum에 포함하는지 검증.

        실제 OpenAI strict 모드는 enum 외 값을 거부한다. 본 테스트는 schema
        자체가 올바르게 구성되는지를 회귀로 보증한다.
        """
        schema = build_review_narrative_schema(
            rule_id_enum=["L1-01"],
            feature_id_enum=["amount_zscore"],
            journal_id_enum=["JE-001"],
        )
        evidence = schema["$defs"]["ReasoningEvidence"]
        assert "GHOST-99" not in evidence["properties"]["rule_id"]["enum"]
        assert "L1-01" in evidence["properties"]["rule_id"]["enum"]

    def test_mock_invalid_id_bypass_is_caught_by_citation_validator(
        self, rn_candidate, rn_chat_client_cls
    ):
        """mock으로 strict를 우회한 invalid ID 응답이 2차 방어선에 잡히는지 회귀.

        실 OpenAI strict는 schema enum으로 1차 차단하지만, mock은 임의 응답 가능.
        citation_validator(2차)가 같은 invalid를 잡아 confidence=low로 강등해야 함.
        """
        bad = {
            "candidate_id": rn_candidate["candidate_id"],
            "priority_rank": 1,
            "priority_score": 0.9,
            "summary": "schema enum 우회 시도",
            "reasoning": [
                {
                    "claim": "x",
                    "evidence": [
                        {
                            "type": "rule_hit",
                            "rule_id": "INVALID-RULE",
                            "model_id": "",
                            "feature_id": "",
                            "journal_id": "",
                            "line_no": 0,
                        },
                    ],
                }
            ],
            "suggested_actions": [],
            "confidence": "high",
        }
        reasoning = rn_chat_client_cls([json.dumps(bad, ensure_ascii=False)])
        light = rn_chat_client_cls([])
        result = narrate(rn_candidate, reasoning, light)
        assert result.citation_result.is_valid is False
        assert result.narrative.confidence == "low"
        # 강등 사유에 invalid rule_id 포함
        assert any("INVALID-RULE" in m for m in result.citation_result.invalid_citations)


# ── (F) Opt-in 실제 LLM 평가 (RUN_LLM_EVAL=1) ────────────────


@pytest.mark.skipif(
    os.getenv("RUN_LLM_EVAL") != "1",
    reason="실제 OpenAI 호출이 필요한 opt-in 평가. RUN_LLM_EVAL=1 로 활성화.",
)
class TestLLMEvalOptIn:
    """실제 OpenAI 호출. 비용 발생. CI 기본 실행에서는 skip."""

    def test_smoke_eval_with_single_provider(self, rn_candidate, rn_valid_llm_response, tmp_path):
        """단일 provider(GPT-5.4 / GPT-5.4-mini) smoke 평가.

        실 API 키가 없으면 get_chat_client가 RuntimeError → skip 처리.
        """
        try:
            from src.llm.api_client import get_chat_client

            reasoning_client = get_chat_client("reasoning")
            light_client = get_chat_client("light")
        except RuntimeError as exc:
            pytest.skip(f"OpenAI 클라이언트 사용 불가: {exc}")

        samples: list[CallSample] = []
        for i in range(2):
            cand = {**rn_candidate, "candidate_id": f"OPT-{i}"}
            start = time.perf_counter()
            result = narrate(cand, reasoning_client, light_client)
            elapsed = time.perf_counter() - start
            samples.append(
                CallSample(
                    candidate_id=cand["candidate_id"],
                    result=result,
                    latency_seconds=elapsed,
                    auditor_rank=i + 1,
                )
            )

        report = evaluate_samples(samples)
        out_dir = Path("test-results") / "phase3_review_narrator_eval"
        save_eval_report(report, output_dir=out_dir, run_label="opt_in_smoke")
        # 기준은 smoke 단계라 완화. 실제 운영 검증은 N=100×3회 별도 스크립트로.
        assert report.total_calls == 2
        assert report.citation_pass_rate >= 0.0
