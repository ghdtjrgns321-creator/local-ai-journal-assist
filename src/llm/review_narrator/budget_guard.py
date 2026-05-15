"""Phase 3 v2 Review Narrator — Budget Guard (Sprint F).

스펙 §4 비용 가드:
    budget 초과 감지 시 candidate 선정 N을 자동 축소 (20 → 10 → 5).

호출 패턴
--------
1. `guard = BudgetGuard(initial_n=20, max_usd=1.0)`
2. candidate 1건 호출 후 `guard.record(cost_usd=0.05)` → 누적 비용 갱신.
3. 다음 candidate 처리 전 `effective_n = guard.current_n()` → 축소된 N 사용.
4. `guard.exhausted` True면 더 이상 호출 금지.

축소 정책 (스펙 §9 리스크 표):
- 누적 비용이 max_usd × 0.5 초과 → N=10
- 누적 비용이 max_usd × 0.8 초과 → N=5
- 누적 비용이 max_usd 도달 → exhausted=True (호출 중단)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Why: §4 N 축소 단계 명시. 단일 진실 공급원으로 두면 정책 변경 시 본 상수만 수정.
_REDUCTION_STEPS: tuple[tuple[float, int], ...] = (
    (0.5, 10),  # 50% 사용 → N=10
    (0.8, 5),  # 80% 사용 → N=5
)


@dataclass
class BudgetGuard:
    """누적 비용 기반 N 자동 축소기.

    Attributes:
        initial_n: 시작 candidate 수 (기본 20).
        max_usd: 본 batch에서 허용된 최대 비용 (USD).
        cost_so_far: 누적 비용 (USD). record() 호출로 증가.
        call_count: 누적 호출 수 (디버깅·테스트용).
    """

    initial_n: int = 20
    max_usd: float = 1.0
    cost_so_far: float = field(default=0.0)
    call_count: int = field(default=0)

    def record(self, *, cost_usd: float | None) -> None:
        """1회 호출 결과를 가드에 등록. None/음수는 0으로 처리(graceful)."""
        delta = max(float(cost_usd or 0.0), 0.0)
        self.cost_so_far += delta
        self.call_count += 1
        if delta == 0.0 and cost_usd is not None:
            # Why: 비용이 0이라고 잘못 보고된 케이스도 호출은 발생한 것으로 카운트
            logger.debug("BudgetGuard.record: cost_usd=%r → 0으로 처리", cost_usd)

    @property
    def exhausted(self) -> bool:
        """누적 비용이 한도에 도달했는가."""
        return self.cost_so_far >= self.max_usd

    def current_n(self) -> int:
        """현재 누적 비용에 맞춰 축소된 N을 반환.

        exhausted 상태에서는 0을 반환해 호출부가 명시적으로 중단할 수 있도록 한다.
        """
        if self.max_usd <= 0:
            return self.initial_n
        if self.exhausted:
            return 0
        ratio = self.cost_so_far / self.max_usd
        reduced = self.initial_n
        for threshold, new_n in _REDUCTION_STEPS:
            if ratio >= threshold:
                reduced = min(reduced, new_n)
        return reduced

    def snapshot(self) -> dict[str, float | int | bool]:
        """현재 상태 요약 — audit_log/리포트용."""
        return {
            "initial_n": self.initial_n,
            "current_n": self.current_n(),
            "max_usd": self.max_usd,
            "cost_so_far": round(self.cost_so_far, 6),
            "call_count": self.call_count,
            "exhausted": self.exhausted,
        }
