"""Rank-percentile review band policy for case-level review queues.

The bands are user-facing review-capacity labels, not fraud thresholds.
They are based on case rank within a queue so the UI scales when the
engagement population changes.
"""

from __future__ import annotations

from math import ceil

RANK_BAND_THRESHOLDS: tuple[tuple[str, float], ...] = (
    ("immediate", 0.0125),
    ("review", 0.05),
    ("candidate", 0.25),
)

RANK_BAND_LABELS: dict[str, str] = {
    "immediate": "즉시검토",
    "review": "검토대상",
    "candidate": "참고후보",
    "none": "후순위",
}


def rank_percentile_band(
    rank: int | float | None,
    total_cases: int,
    *,
    has_signal: bool = True,
) -> str:
    """Return review band from 1-based queue rank and total case count.

    Bands:
      - immediate: top 1.25%
      - review: top 5%
      - candidate: top 25%
      - none: outside top 25%, invalid rank, or no signal
    """

    if not has_signal or total_cases <= 0 or rank is None:
        return "none"
    try:
        rank_value = int(rank)
    except (TypeError, ValueError):
        return "none"
    if rank_value <= 0:
        return "none"

    for band, ratio in RANK_BAND_THRESHOLDS:
        if rank_value <= cutoff_count(total_cases, ratio):
            return band
    return "none"


def cutoff_count(total_cases: int, ratio: float) -> int:
    """Ceiling count for a rank percentile cutoff."""

    if total_cases <= 0 or ratio <= 0:
        return 0
    return max(1, int(ceil(total_cases * ratio)))


def rank_band_caption(total_cases: int) -> str:
    """Human-readable cutoff summary for UI captions."""

    immediate = cutoff_count(total_cases, 0.0125)
    review = cutoff_count(total_cases, 0.05)
    candidate = cutoff_count(total_cases, 0.25)
    return (
        "case 순위 기준: 즉시검토 상위 1.25% "
        f"({immediate:,}건), 검토대상 상위 5% ({review:,}건), "
        f"참고후보 상위 25% ({candidate:,}건)"
    )
