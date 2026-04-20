from __future__ import annotations

import pandas as pd

from src.detection.base import DetectionResult, RuleFlag
from src.metrics.ground_truth_evaluator import (
    build_ground_truth_report,
    normalize_results_by_track,
    overall_label_analysis,
    per_rule_label_analysis,
    uncovered_label_analysis,
)


def _make_result(track_name: str, details: pd.DataFrame) -> DetectionResult:
    flagged_indices = details.index[details.gt(0).any(axis=1)].tolist()
    return DetectionResult(
        track_name=track_name,
        flagged_indices=[int(idx) for idx in flagged_indices],
        scores=details.max(axis=1).fillna(0.0),
        rule_flags=[
            RuleFlag(
                rule_id=rule_id,
                rule_name=rule_id,
                severity=1,
                flagged_count=int((details[rule_id] > 0).sum()),
                total_count=len(details),
            )
            for rule_id in details.columns
        ],
        details=details,
        metadata={"elapsed": 0.1},
    )


class TestNormalizeResultsByTrack:
    def test_accepts_list(self):
        result = _make_result("layer_a", pd.DataFrame({"L1-01": [1.0]}))
        normalized = normalize_results_by_track([result])
        assert normalized["layer_a"] is result

    def test_accepts_mapping(self):
        result = _make_result("layer_a", pd.DataFrame({"L1-01": [1.0]}))
        normalized = normalize_results_by_track({"layer_a": result})
        assert normalized["layer_a"] is result


class TestGroundTruthEvaluator:
    def test_per_rule_label_analysis_counts_tp_fp_fn(self):
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D2", "D3"],
            }
        )
        result = _make_result(
            "layer_a",
            pd.DataFrame({"L1-01": [1.0, 0.0, 1.0]}, index=df.index),
        )
        labels = pd.DataFrame(
            {
                "document_id": ["D1", "D2"],
                "anomaly_type": ["UnbalancedEntry", "UnbalancedEntry"],
            }
        )

        analysis = per_rule_label_analysis(df, {"layer_a": result}, labels)
        a01 = next(item for item in analysis if item["rule_id"] == "L1-01")

        assert a01["tp_docs"] == 1
        assert a01["fp_docs"] == 1
        assert a01["fn_docs"] == 1
        assert a01["precision"] == 0.5
        assert a01["recall"] == 0.5

    def test_per_rule_label_analysis_marks_missing_rule_as_skipped(self):
        df = pd.DataFrame({"document_id": ["D1"]})
        labels = pd.DataFrame(
            {"document_id": ["D1"], "anomaly_type": ["UnbalancedEntry"]}
        )

        analysis = per_rule_label_analysis(df, {}, labels)
        a01 = next(item for item in analysis if item["rule_id"] == "L1-01")

        assert a01["status"] == "skipped"
        assert a01["reason"] == "rule missing in track layer_a"

    def test_overall_label_analysis_splits_phase1_and_phase23(self):
        df = pd.DataFrame({"document_id": ["D1", "D2", "D3"]})
        agg_df = pd.DataFrame({"anomaly_score": [0.8, 0.0, 0.7]})
        labels = pd.DataFrame(
            {
                "document_id": ["D1", "D2", "D3"],
                "anomaly_type": [
                    "UnbalancedEntry",
                    "FuturePhaseLabel",
                    "UnbalancedEntry",
                ],
            }
        )

        result = overall_label_analysis(df, agg_df, labels)

        assert result["total_labeled"] == 3
        assert result["total_flagged_docs"] == 2
        assert result["total_tp"] == 2
        assert result["phase1_labeled"] == 2
        assert result["phase1_tp"] == 2
        assert result["phase23_labeled"] == 1
        assert result["phase23_tp"] == 0

    def test_uncovered_label_analysis_returns_only_unmapped_types(self):
        labels = pd.DataFrame(
            {
                "document_id": ["D1", "D2", "D3"],
                "anomaly_type": [
                    "UnbalancedEntry",
                    "FuturePhaseLabel",
                    "FuturePhaseLabel",
                ],
            }
        )

        uncovered = uncovered_label_analysis(labels)

        assert uncovered == [{"anomaly_type": "FuturePhaseLabel", "count": 2}]

    def test_build_ground_truth_report_returns_rule_metrics(self):
        df = pd.DataFrame({"document_id": ["D1", "D2", "D3"]})
        agg_df = pd.DataFrame(
            {
                "anomaly_score": [0.8, 0.0, 0.7],
                "risk_level": ["High", "Normal", "Medium"],
            }
        )
        result = _make_result(
            "layer_a",
            pd.DataFrame({"L1-01": [1.0, 0.0, 1.0]}, index=df.index),
        )
        labels = pd.DataFrame(
            {
                "document_id": ["D1", "D2"],
                "anomaly_type": ["UnbalancedEntry", "UnbalancedEntry"],
            }
        )

        report = build_ground_truth_report(
            df,
            agg_df,
            {"layer_a": result},
            labels,
            upload_batch_id="batch_gt_01",
        )

        assert report.source_kind == "ground_truth"
        assert report.flagged_docs == 2
        assert report.high_risk_docs == 1
        assert report.rule_metrics[0].rule_code == "L1-01"
        assert report.rule_metrics[0].precision == 0.5
