"""현실성 검증 품질 게이트 데이터 모델."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CheckResult:
    """개별 체크 결과."""

    check_id: str
    tier: int
    name: str
    status: str  # PASS / FAIL / WARNING / SKIP
    expected: str
    actual: str
    detail: dict[str, Any] | None = None
    elapsed_ms: float = 0.0


@dataclass
class TierSummary:
    """Tier별 요약."""

    tier: int
    name: str
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def pass_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "PASS")

    @property
    def fail_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "FAIL")

    @property
    def warning_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "WARNING")

    @property
    def skip_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "SKIP")

    @property
    def verdict(self) -> str:
        if self.fail_count > 0:
            return "FAIL"
        if self.warning_count > 0:
            return "WARNING"
        return "PASS"


@dataclass
class QualityGateReport:
    """전체 리포트."""

    data_file: str
    total_rows: int
    total_documents: int
    tiers: list[TierSummary] = field(default_factory=list)
    elapsed_seconds: float = 0.0

    @property
    def overall_verdict(self) -> str:
        for t in self.tiers:
            if t.verdict == "FAIL":
                return "FAIL"
        if any(t.verdict == "WARNING" for t in self.tiers):
            return "WARNING"
        return "PASS"
