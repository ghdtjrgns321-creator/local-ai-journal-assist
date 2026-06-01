from __future__ import annotations

from dashboard.components.phase2_subdetector_grid import build_subdetector_grid_frame


def test_build_subdetector_grid_frame_shows_all_twenty_display_subdetectors():
    partition_summary = {
        "families": {
            "timeseries": {
                "sub_detectors": {
                    "TS01": {"label": "transaction_burst", "hit_count": 14340},
                    "TS02": {"label": "unusual_frequency", "hit_count": 293024},
                }
            },
            "relational": {
                "sub_detectors": {
                    "R04": {"label": "missing_relationship", "hit_count": 0}
                }
            },
            "intercompany": {
                "ui_meta": {
                    "active_sub_detectors": ["IC01"],
                    "zero_hit_sub_detectors": ["IC02", "IC03"],
                },
                "sub_detectors": {
                    "IC01": {"label": "unmatched_intercompany", "hit_count": 16},
                    "IC02": {"label": "amount_mismatch", "hit_count": 0},
                    "IC03": {"label": "timing_gap", "hit_count": 0},
                },
            },
        }
    }

    frame = build_subdetector_grid_frame(partition_summary)

    assert len(frame) == 20
    assert frame["hit_count"].isna().sum() == 0
    assert {"R05", "R06", "R07"}.issubset(set(frame["sub_detector"]))
    assert {
        "ic_reciprocal_flow_prob",
        "ic_amount_prob",
        "ic_unmatched_prob",
        "ic_timing_prob",
    }.issubset(set(frame["sub_detector"]))
    r04 = frame[frame["sub_detector"] == "R04"].iloc[0]
    assert r04["hit_count"] == 0
    ic02 = frame[frame["sub_detector"] == "IC02"].iloc[0]
    assert ic02["meta"] == "carry-over (matched-pair data 미보유)"
    ic01 = frame[frame["sub_detector"] == "IC01"].iloc[0]
    assert ic01["meta"] == "active sidecar unmatched-reference"
