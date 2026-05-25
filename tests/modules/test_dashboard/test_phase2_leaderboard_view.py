from __future__ import annotations

from dashboard.components.phase2_leaderboard_view import (
    build_leaderboard_frame,
    build_promotion_decision_frame,
)


def test_build_leaderboard_frame_allows_null_schema_hash():
    snapshot = {
        "leaderboard_artifact": {
            "rows": [
                {
                    "family": "timeseries",
                    "trial": "baseline_core",
                    "preset": "balanced",
                    "status": "completed",
                    "metric": {"name": "burst_detection_rate", "value": 0.62},
                    "elapsed_sec": 1.2,
                    "schema_hash": None,
                    "metadata": {"metric_interpretation": "rule_proxy_score"},
                }
            ]
        }
    }

    frame = build_leaderboard_frame(snapshot)

    assert list(frame["family"]) == ["timeseries"]
    assert list(frame["schema_hash"]) == ["-"]
    assert list(frame["metric_interpretation"]) == ["rule_proxy_score"]


def test_build_promotion_decision_frame_shows_family_decisions():
    snapshot = {
        "promotion_decision_artifact": {
            "family_decisions": {
                "duplicate": {
                    "eligible_for_promotion": True,
                    "required_completed_trials": 2,
                    "family_min_metric": 0.05,
                    "reasons": [],
                },
                "supervised": {
                    "eligible_for_promotion": False,
                    "required_completed_trials": 2,
                    "family_min_metric": 0.1,
                    "reasons": ["low_signal_fallback"],
                },
            }
        }
    }

    frame = build_promotion_decision_frame(snapshot)

    assert set(frame["family"]) == {"duplicate", "supervised"}
    supervised = frame[frame["family"] == "supervised"].iloc[0]
    assert supervised["eligible_for_promotion"] == "no"
    assert supervised["reasons"] == "low_signal_fallback"
