"""Phase 3 v2 Review Narrator — 평가 하니스 (Sprint F).

스펙 §평가 기준 측정 도구:
- 인용 정합성: citation_validator 통과율 ≥ 99%
- 우선순위 일치도: 감사인 라벨 N=50 vs LLM rank Spearman ρ ≥ 0.6
- Latency p95: reasoning ≤ 8s, light ≤ 2s
- 비용: candidate 1건당 평균 토큰·USD

본 모듈은 통계 계산만 담당한다. 실제 LLM 호출은 호출자(`test_eval.py`)가
narrate() 결과 리스트를 만들어 본 모듈에 전달한다. 이렇게 분리하면 mock과
실제 호출 양쪽 모두 동일 분석 로직을 통과시킬 수 있다.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from scipy.stats import spearmanr

from src.llm.review_narrator.narrator import NarratorResult

logger = logging.getLogger(__name__)


@dataclass
class CallSample:
    """단일 candidate 호출 결과 + 측정 메타.

    `narrate()` 호출자(평가 하니스)가 wall-clock latency와 토큰/비용을
    측정해 본 dataclass로 모아 둔다.
    """

    candidate_id: str
    result: NarratorResult
    latency_seconds: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost_usd: float | None = None
    auditor_rank: int | None = None  # 감사인 라벨 순위 (Spearman용)


@dataclass
class EvalReport:
    """평가 하니스 종합 결과."""

    total_calls: int
    citation_pass_count: int
    citation_pass_rate: float
    spearman_rho: float | None = None
    spearman_p_value: float | None = None
    latency_p50_reasoning: float | None = None
    latency_p95_reasoning: float | None = None
    latency_p50_light: float | None = None
    latency_p95_light: float | None = None
    avg_prompt_tokens: float | None = None
    avg_completion_tokens: float | None = None
    total_cost_usd: float = 0.0
    avg_cost_usd: float | None = None
    failed_calls: int = 0
    per_tier_counts: dict[str, int] = field(default_factory=dict)

    def meets_citation_threshold(self, threshold: float = 0.99) -> bool:
        return self.citation_pass_rate >= threshold

    def meets_spearman_threshold(self, threshold: float = 0.6) -> bool:
        return self.spearman_rho is not None and self.spearman_rho >= threshold

    def meets_latency_thresholds(
        self, *, reasoning_p95: float = 8.0, light_p95: float = 2.0
    ) -> bool:
        ok = True
        if self.latency_p95_reasoning is not None:
            ok = ok and self.latency_p95_reasoning <= reasoning_p95
        if self.latency_p95_light is not None:
            ok = ok and self.latency_p95_light <= light_p95
        return ok


# ── 통계 헬퍼 ────────────────────────────────────────────────


def _percentile(values: list[float], p: float) -> float | None:
    """p ∈ [0,100] 백분위. 빈 입력은 None."""
    if not values:
        return None
    sorted_vals = sorted(values)
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = (p / 100.0) * (len(sorted_vals) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_vals) - 1)
    frac = rank - lower
    return sorted_vals[lower] + frac * (sorted_vals[upper] - sorted_vals[lower])


def _mean(values: Iterable[float | None]) -> float | None:
    """None 제외 평균. 모두 None이면 None."""
    cleaned = [float(v) for v in values if v is not None]
    if not cleaned:
        return None
    return sum(cleaned) / len(cleaned)


# ── 핵심 평가 함수 ───────────────────────────────────────────


def evaluate_samples(samples: list[CallSample]) -> EvalReport:
    """CallSample 리스트 → EvalReport.

    - citation_pass_rate: NarratorResult.citation_result.is_valid True 비율
    - spearman_rho: auditor_rank ↔ narrative.priority_rank 상관 (둘 다 있는 샘플만)
    - latency_p50/p95: model_tier 별 분리 측정 (reasoning vs light)
    - per_tier_counts: 호출 tier 분포 (reasoning/light/failed)
    """
    if not samples:
        return EvalReport(
            total_calls=0,
            citation_pass_count=0,
            citation_pass_rate=0.0,
        )

    citation_passes = sum(1 for s in samples if s.result.citation_result.is_valid)
    failed = sum(1 for s in samples if s.result.call_status == "failed")
    per_tier: dict[str, int] = {}
    for s in samples:
        per_tier[s.result.model_tier] = per_tier.get(s.result.model_tier, 0) + 1

    reasoning_latencies = [s.latency_seconds for s in samples if s.result.model_tier == "reasoning"]
    light_latencies = [s.latency_seconds for s in samples if s.result.model_tier == "light"]

    # Spearman: auditor_rank와 priority_rank가 모두 있는 샘플만 사용
    paired = [
        (s.auditor_rank, s.result.narrative.priority_rank)
        for s in samples
        if s.auditor_rank is not None
    ]
    rho: float | None = None
    p_value: float | None = None
    if len(paired) >= 2:
        a_rank = [p[0] for p in paired]
        l_rank = [p[1] for p in paired]
        # Why: 동률(tied rank) 비율이 높으면 Spearman ρ 신뢰도가 떨어진다. 30% 초과 시
        #      운영자가 결과 해석을 신중히 하도록 경고를 로그에 남긴다.
        tie_ratio = 1.0 - len(set(l_rank)) / len(l_rank)
        if tie_ratio > 0.3:
            logger.warning(
                "Spearman: priority_rank ties %.0f%% — ρ 신뢰도 저하",
                tie_ratio * 100,
            )
        # Why: scipy.stats.spearmanr는 동률에 자동 대응. 표본 ≥2 필수.
        #      반환 객체의 속성 명이 scipy 버전에 따라 .correlation/.statistic으로
        #      다르고 인덱싱은 Pyright 타입 추론을 실패시킨다. getattr 다중 폴백.
        sp_result = spearmanr(a_rank, l_rank)
        rho_raw = getattr(sp_result, "correlation", None)
        if rho_raw is None:
            rho_raw = getattr(sp_result, "statistic", None)
        p_raw = getattr(sp_result, "pvalue", None)
        if rho_raw is None:
            # Why: scipy API가 향후 변경되어 두 속성 모두 사라진 경우, 침묵하지 말고
            #      운영자에게 버전 확인을 즉시 알린다.
            logger.warning(
                "spearmanr 결과 속성 미인식 — scipy 버전 확인 필요: %s",
                type(sp_result),
            )
        else:
            rho = float(rho_raw)
        if p_raw is not None:
            p_value = float(p_raw)

    tokens_p = [s.prompt_tokens for s in samples]
    tokens_c = [s.completion_tokens for s in samples]
    costs = [s.cost_usd for s in samples if s.cost_usd is not None]

    return EvalReport(
        total_calls=len(samples),
        citation_pass_count=citation_passes,
        citation_pass_rate=citation_passes / len(samples),
        spearman_rho=rho,
        spearman_p_value=p_value,
        latency_p50_reasoning=_percentile(reasoning_latencies, 50),
        latency_p95_reasoning=_percentile(reasoning_latencies, 95),
        latency_p50_light=_percentile(light_latencies, 50),
        latency_p95_light=_percentile(light_latencies, 95),
        avg_prompt_tokens=_mean(tokens_p),
        avg_completion_tokens=_mean(tokens_c),
        total_cost_usd=round(sum(costs), 6),
        avg_cost_usd=_mean(costs),
        failed_calls=failed,
        per_tier_counts=per_tier,
    )


# ── 결과 저장 ────────────────────────────────────────────────


def save_eval_report(
    report: EvalReport,
    *,
    output_dir: Path,
    run_label: str | None = None,
) -> Path:
    """EvalReport를 JSON으로 저장.

    저장 경로: `output_dir/YYYYMMDD/eval_<label>_<HHMMSS>_<uuid6>.json`
    `uuid6`는 동일 초·동일 label 동시 호출 시 파일 덮어쓰기를 막는 6자리 무작위 접미사.
    호출자가 `test-results/phase3_review_narrator_eval/`를 output_dir로 넘긴다.
    """
    now = datetime.now()
    day_dir = output_dir / now.strftime("%Y%m%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    label = run_label or "default"
    suffix = uuid.uuid4().hex[:6]
    file_path = day_dir / f"eval_{label}_{now.strftime('%H%M%S')}_{suffix}.json"
    payload = {
        "generated_at": now.isoformat(timespec="seconds"),
        "label": label,
        "report": asdict(report),
        "thresholds_met": {
            "citation_99": report.meets_citation_threshold(),
            "spearman_06": report.meets_spearman_threshold(),
            "latency": report.meets_latency_thresholds(),
        },
    }
    file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("eval report saved: %s", file_path)
    return file_path


__all__ = [
    "CallSample",
    "EvalReport",
    "evaluate_samples",
    "save_eval_report",
]
