from __future__ import annotations

from dashboard.components.phase2_family_matrix import build_family_matrix_frame


def test_build_family_matrix_frame_shows_active_and_dormant_families():
    snapshot = {
        "inference_contract": {
            "required_models": [
                "unsupervised",
                "timeseries",
                "relational",
                "intercompany",
            ],
            "model_versions": {
                "timeseries": {"model_version": None, "schema_hash": None},
            },
        }
    }
    partition_summary = {
        "families": {
            "unsupervised": {"high_count_q95": 30374},
            "intercompany": {
                "metric_interpretation": "rule_proxy_score",
                "score_distribution": {"nonzero_count": 16},
                "ui_meta": {
                    "metric_confidence": "sidecar_unmatched_reference_only",
                    "active_sub_detectors": ["IC01"],
                    "zero_hit_sub_detectors": ["IC02", "IC03"],
                },
            },
        }
    }

    frame = build_family_matrix_frame(snapshot, partition_summary)

    assert len(frame) == 8
    assert set(frame["state"]) == {"active", "dormant"}
    assert frame["state"].value_counts().to_dict() == {"active": 4, "dormant": 4}
    ic_row = frame[frame["family"] == "intercompany"].iloc[0]
    assert ic_row["note"] == "active, IC01 only"
    assert ic_row["metric_confidence"] == "sidecar_unmatched_reference_only"
    supervised_row = frame[frame["family"] == "supervised"].iloc[0]
    assert supervised_row["block_reason"] == "low_signal_fallback"


def test_build_family_matrix_frame_labels_unsupervised_q95_not_truth_recall():
    frame = build_family_matrix_frame(
        None,
        {"families": {"unsupervised": {"high_count_q95": 22689}}},
    )

    row = frame[frame["family"] == "unsupervised"].iloc[0]
    assert row["metric"] == "ECDF high q95 count"
    assert row["metric_value"] == "22,689"
    assert "recall" not in row["metric_interpretation"].lower()
