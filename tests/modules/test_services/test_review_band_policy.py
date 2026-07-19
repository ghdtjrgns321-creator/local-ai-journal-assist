from __future__ import annotations

from src.services.review_band_policy import cutoff_count, rank_percentile_band


def test_rank_percentile_band_cutoffs_match_review_capacity() -> None:
    total = 41_129
    assert cutoff_count(total, 0.0125) == 515
    assert cutoff_count(total, 0.05) == 2_057
    assert cutoff_count(total, 0.25) == 10_283

    assert rank_percentile_band(1, total) == "immediate"
    assert rank_percentile_band(515, total) == "immediate"
    assert rank_percentile_band(516, total) == "review"
    assert rank_percentile_band(2_057, total) == "review"
    assert rank_percentile_band(2_058, total) == "candidate"
    assert rank_percentile_band(10_283, total) == "candidate"
    assert rank_percentile_band(10_284, total) == "none"


def test_rank_percentile_band_requires_valid_signal() -> None:
    assert rank_percentile_band(1, 100, has_signal=False) == "none"
    assert rank_percentile_band(None, 100) == "none"
    assert rank_percentile_band(0, 100) == "none"
