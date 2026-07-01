from __future__ import annotations

from dashboard.components.phase2_subdetector_grid import build_subdetector_grid_frame


def test_build_subdetector_grid_frame_shows_all_timeseries_display_subdetectors():
    partition_summary = {
        "families": {
            "timeseries": {
                "sub_detectors": {
                    "TS01": {"label": "transaction_burst", "hit_count": 14340},
                    "TS02": {"label": "unusual_frequency", "hit_count": 293024},
                }
            },
        }
    }

    frame = build_subdetector_grid_frame(partition_summary)

    assert len(frame) == 2
    assert frame["hit_count"].isna().sum() == 0
    assert {"TS01", "TS02"}.issubset(set(frame["sub_detector"]))
    ts02 = frame[frame["sub_detector"] == "TS02"].iloc[0]
    assert ts02["hit_count"] == 293024
