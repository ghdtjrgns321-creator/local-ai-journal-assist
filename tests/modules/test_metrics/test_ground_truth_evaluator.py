from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd

from src.detection.base import DetectionResult, RuleFlag
from src.metrics.ground_truth_evaluator import (
    build_benford_population_benchmarks,
    build_ground_truth_report,
    normalize_results_by_track,
    overall_label_analysis,
    per_rule_label_analysis,
    uncovered_label_analysis,
)


def _make_result(
    track_name: str,
    details: pd.DataFrame,
    metadata: dict | None = None,
) -> DetectionResult:
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
        metadata={"elapsed": 0.1, **(metadata or {})},
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
                "document_id": ["D1", "D1", "D2", "D2", "D3", "D3"],
                "debit_amount": [100.0, 0.0, 50.0, 0.0, 100.0, 0.0],
                "credit_amount": [0.0, 90.0, 0.0, 50.0, 0.0, 0.0],
            }
        )
        result = _make_result(
            "layer_a",
            pd.DataFrame({"L1-01": [1.0, 1.0, 0.0, 0.0, 1.0, 1.0]}, index=df.index),
        )
        labels = pd.DataFrame(
            {
                "document_id": ["D1", "D2"],
                "anomaly_type": ["UnbalancedEntry", "UnbalancedEntry"],
            }
        )

        analysis = per_rule_label_analysis(df, {"layer_a": result}, labels)
        a01 = next(item for item in analysis if item["rule_id"] == "L1-01")

        assert a01["tp_docs"] == 2
        assert a01["fp_docs"] == 0
        assert a01["fn_docs"] == 0
        assert a01["precision"] == 1.0
        assert a01["recall"] == 1.0

    def test_l1_01_uses_actual_imbalance_ground_truth(self):
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D1", "D2", "D2", "D3", "D3"],
                "debit_amount": [100.0, 0.0, 50.0, 0.0, 200.0, 0.0],
                "credit_amount": [0.0, 90.0, 0.0, 50.0, 0.0, 20.0],
            }
        )
        result = _make_result(
            "layer_a",
            pd.DataFrame({"L1-01": [1.0, 1.0, 0.0, 0.0, 1.0, 1.0]}, index=df.index),
        )
        labels = pd.DataFrame(
            {
                "document_id": ["D1", "D2", "D3"],
                "anomaly_type": [
                    "UnbalancedEntry",
                    "RoundingError",
                    "FuturePhaseLabel",
                ],
            }
        )

        analysis = per_rule_label_analysis(df, {"layer_a": result}, labels)
        a01 = next(item for item in analysis if item["rule_id"] == "L1-01")

        assert a01["label_types"] == ["UnbalancedEntry"]
        assert a01["label_docs"] == 2
        assert a01["tp_docs"] == 2
        assert a01["fp_docs"] == 0
        assert a01["fn_docs"] == 0

    def test_per_rule_label_analysis_marks_missing_rule_as_skipped(self):
        df = pd.DataFrame({"document_id": ["D1"]})
        labels = pd.DataFrame(
            {"document_id": ["D1"], "anomaly_type": ["UnbalancedEntry"]}
        )

        analysis = per_rule_label_analysis(df, {}, labels)
        a01 = next(item for item in analysis if item["rule_id"] == "L1-01")

        assert a01["status"] == "skipped"
        assert a01["reason"] == "rule missing in L1"

    def test_l4_01_is_reported_as_coverage_anchor(self):
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D2", "D3", "D4"],
                "source": ["automated", "manual", "automated", "automated"],
            }
        )
        result = _make_result(
            "layer_b",
            pd.DataFrame(
                {
                    "L4-01": [1.0, 1.0, 0.0, 1.0],
                    "L3-02": [0.0, 1.0, 0.0, 0.0],
                },
                index=df.index,
            ),
        )
        labels = pd.DataFrame(
            {
                "document_id": ["D1", "D3"],
                "anomaly_type": ["RevenueManipulation", "RevenueManipulation"],
                "metadata_json": [
                    json.dumps({
                        "revenue_subtype": "high_value_revenue_outlier",
                        "is_l401_direct_truth": True,
                    }),
                    json.dumps({"revenue_subtype": "period_end_push"}),
                ],
            }
        )

        analysis = per_rule_label_analysis(df, {"layer_b": result}, labels)
        l401 = next(item for item in analysis if item["rule_id"] == "L4-01")

        assert l401["status"] == "coverage_anchor"
        assert l401["rule_objective"] == "High-value revenue z-score outlier"
        assert l401["broad_fraud_type"] == "RevenueManipulation"
        assert l401["expected_coverage"] == "partial / anchor"
        assert l401["tp_docs"] == 1
        assert l401["fp_docs"] == 2
        assert l401["fn_docs"] == 0
        assert l401["overlap_docs"] == 1
        assert l401["standalone_docs"] == 2
        assert l401["review_queue_docs"] == 2

    def test_l4_01_does_not_fallback_to_broad_revenue_labels_without_direct_truth(self):
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D2", "D3"],
                "source": ["automated", "manual", "automated"],
            }
        )
        result = _make_result(
            "layer_b",
            pd.DataFrame({"L4-01": [1.0, 0.0, 1.0]}, index=df.index),
        )
        labels = pd.DataFrame(
            {
                "document_id": ["D1", "D2"],
                "anomaly_type": ["RevenueManipulation", "RevenueManipulation"],
                "metadata_json": [
                    json.dumps({"entity_target": "DOC-001"}),
                    json.dumps({"revenue_subtype": "manual_revenue_entry"}),
                ],
            }
        )

        analysis = per_rule_label_analysis(df, {"layer_b": result}, labels)
        l401 = next(item for item in analysis if item["rule_id"] == "L4-01")

        assert l401["status"] == "coverage_anchor"
        assert l401["label_docs"] == 0
        assert l401["tp_docs"] == 0
        assert l401["fp_docs"] == 2
        assert l401["fn_docs"] == 0
        assert l401["recall"] is None
        assert "do not fall back to broad RevenueManipulation" in l401["reason"]

    def test_l4_02_ignores_legacy_document_labels_for_rule_metrics(self):
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D2"],
                "fiscal_year": [2024, 2024],
            }
        )
        result = _make_result(
            "benford",
            pd.DataFrame({"L4-02": [0.0, 0.0]}, index=df.index),
        )
        labels = pd.DataFrame(
            {
                "document_id": ["D1"],
                "anomaly_type": ["BenfordViolation"],
            }
        )

        analysis = per_rule_label_analysis(df, {"benford": result}, labels)
        l402 = next(item for item in analysis if item["rule_id"] == "L4-02")

        assert l402["status"] == "population"
        assert l402["label_docs"] == 0
        assert l402["recall"] is None
        assert l402["precision"] is None

    def test_l1_04_keeps_approval_excess_bands(self):
        df = pd.DataFrame({"document_id": ["D1", "D2", "D3", "D4", "D5", "D6"]})
        result = _make_result(
            "layer_b",
            pd.DataFrame({"L1-04": [0.45, 0.60, 0.75, 0.90, 0.90, 0.60]}, index=df.index),
            metadata={
                "row_annotations": {
                    "L1-04": {
                        0: {"bucket": "boundary"},
                        1: {"bucket": "moderate"},
                        2: {"bucket": "severe"},
                        3: {"bucket": "critical"},
                        4: {"bucket": "non_approver"},
                        5: {"bucket": "unresolved_limit"},
                    }
                }
            },
        )
        labels = pd.DataFrame({"document_id": ["D3"], "anomaly_type": ["ExceededApprovalLimit"]})

        analysis = per_rule_label_analysis(df, {"layer_b": result}, labels)
        l104 = next(item for item in analysis if item["rule_id"] == "L1-04")

        assert l104["score_bands"] == {
            "boundary_docs": 1,
            "moderate_docs": 1,
            "severe_docs": 1,
            "critical_docs": 1,
            "non_approver_docs": 1,
            "unresolved_limit_docs": 1,
        }

    def test_l1_05_keeps_review_immediate_and_escalated_bands(self):
        df = pd.DataFrame({"document_id": ["D1", "D2", "D3", "D4"]})
        result = _make_result(
            "layer_b",
            pd.DataFrame({"L1-05": [0.4, 0.8, 0.8, 0.0]}, index=df.index),
            metadata={
                "row_annotations": {
                    "L1-05": {
                        0: {"bucket": "review"},
                        1: {"bucket": "immediate"},
                        2: {"bucket": "escalated_materiality"},
                    }
                }
            },
        )
        labels = pd.DataFrame({"document_id": ["D2"], "anomaly_type": ["SelfApproval"]})

        analysis = per_rule_label_analysis(df, {"layer_b": result}, labels)
        l105 = next(item for item in analysis if item["rule_id"] == "L1-05")

        assert l105["score_bands"] == {
            "review_docs": 1,
            "immediate_docs": 1,
            "escalated_docs": 1,
        }
        assert l105["review_queue_docs"] == 1

    def test_l1_06_counts_only_immediate_band(self):
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D2", "D3", "D4"],
                "created_by": ["U1", "U1", "U2", "U2"],
                "business_process": ["TRE", "P2P", "R2R", "P2P"],
            }
        )
        result = _make_result(
            "layer_b",
            pd.DataFrame({"L1-06": [0.8, 0.8, 0.0, 0.0]}, index=df.index),
            metadata={
                "rule_breakdowns": {
                    "L1-06": {
                        "immediate_rows": 2,
                        "review_rows": 0,
                        "corroborated_review_rows": 0,
                        "work_scope_review_rows_excluded": 2,
                    }
                }
            },
        )
        labels = pd.DataFrame(
            {
                "document_id": ["D1"],
                "anomaly_type": ["SegregationOfDutiesViolation"],
            }
        )

        analysis = per_rule_label_analysis(df, {"layer_b": result}, labels)
        l106 = next(item for item in analysis if item["rule_id"] == "L1-06")

        assert l106["score_bands"] == {"immediate_docs": 2}
        assert l106["breakdown"]["immediate_rows"] == 2
        assert l106["breakdown"]["review_rows"] == 0
        assert l106["breakdown"]["work_scope_review_rows_excluded"] == 2
        assert l106["flagged_docs"] == 2
        assert l106["fp_docs"] == 1
        assert l106["review_queue_docs"] == 0

    def test_review_score_series_counts_as_operational_detection(self):
        df = pd.DataFrame({"document_id": ["D1", "D2"]})
        result = _make_result(
            "layer_b",
            pd.DataFrame({"L1-05": [0.0, 0.0]}, index=df.index),
            metadata={
                "review_score_series": pd.DataFrame(
                    {"L1-05": [0.4, 0.0]},
                    index=df.index,
                ),
                "row_annotations": {"L1-05": {0: {"bucket": "review"}}},
            },
        )
        labels = pd.DataFrame({"document_id": ["D1"], "anomaly_type": ["SelfApproval"]})

        analysis = per_rule_label_analysis(df, {"layer_b": result}, labels)
        l105 = next(item for item in analysis if item["rule_id"] == "L1-05")

        assert l105["flagged_docs"] == 1
        assert l105["tp_docs"] == 1
        assert l105["fn_docs"] == 0

    def test_l3_02_keeps_population_and_priority_bands(self):
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D2", "D3", "D4"],
                "source": ["manual", "adjustment", "manual", "automated"],
            }
        )
        result = _make_result(
            "layer_b",
            pd.DataFrame({"L3-02": [0.35, 0.60, 0.75, 0.0]}, index=df.index),
            metadata={
                "rule_breakdowns": {
                    "L3-02": {
                        "manual_rows": 2,
                        "adjustment_rows": 1,
                        "priority_rows": 2,
                        "control_bypass_rows": 1,
                    }
                }
            },
        )
        labels = pd.DataFrame({"document_id": [], "anomaly_type": []})

        analysis = per_rule_label_analysis(df, {"layer_b": result}, labels)
        l302 = next(item for item in analysis if item["rule_id"] == "L3-02")

        assert l302["status"] == "population"
        assert l302["score_bands"] == {
            "manual_population_docs": 1,
            "priority_docs": 1,
            "control_bypass_docs": 1,
        }
        assert l302["breakdown"]["control_bypass_rows"] == 1
        assert l302["review_queue_docs"] == 2

    def test_l3_04_keeps_closing_priority_bands(self):
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D2", "D3", "D4"],
                "is_period_end": [True, True, True, False],
            }
        )
        result = _make_result(
            "layer_c",
            pd.DataFrame({"L3-04": [0.45, 0.65, 0.80, 0.0]}, index=df.index),
            metadata={
                "rule_breakdowns": {
                    "L3-04": {
                        "flagged_rows": 3,
                        "priority_rows": 2,
                        "bucket_counts": {
                            "closing_manual": 1,
                            "closing_priority": 1,
                            "closing_high_amount": 1,
                        },
                    }
                }
            },
        )
        labels = pd.DataFrame(
            {"document_id": ["D3"], "anomaly_type": ["RushedPeriodEnd"]}
        )

        analysis = per_rule_label_analysis(df, {"layer_c": result}, labels)
        l304 = next(item for item in analysis if item["rule_id"] == "L3-04")

        assert l304["score_bands"] == {
            "closing_low_docs": 1,
            "closing_priority_docs": 1,
            "closing_high_docs": 1,
        }
        assert l304["breakdown"]["priority_rows"] == 2
        assert l304["review_queue_docs"] == 2

    def test_l3_09_keeps_suspense_aging_bands(self):
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D2", "D3", "D4"],
                "is_suspense_account": [True, True, True, False],
            }
        )
        result = _make_result(
            "layer_c",
            pd.DataFrame({"L3-09": [0.45, 0.60, 0.80, 0.0]}, index=df.index),
            metadata={
                "rule_breakdowns": {
                    "L3-09": {
                        "flagged_rows": 3,
                        "aging_bucket_counts": {
                            "aging_30_60": 1,
                            "aging_60_90": 1,
                            "aging_over_90": 1,
                        },
                        "open_amount_bucket_counts": {
                            "open_amount_low": 1,
                            "open_amount_medium": 1,
                            "open_amount_high": 1,
                        },
                    }
                }
            },
        )
        labels = pd.DataFrame(
            {"document_id": ["D3"], "anomaly_type": ["SuspenseAccountAbuse"]}
        )

        analysis = per_rule_label_analysis(df, {"layer_c": result}, labels)
        l309 = next(item for item in analysis if item["rule_id"] == "L3-09")

        assert l309["status"] == "population"
        assert l309["score_bands"] == {
            "suspense_aging_review_docs": 1,
            "suspense_aging_priority_docs": 1,
            "suspense_aging_high_docs": 1,
        }
        assert l309["breakdown"]["open_amount_bucket_counts"]["open_amount_high"] == 1
        assert l309["review_queue_docs"] == 2

    def test_l2_03_keeps_confidence_bands_and_review_queue(self):
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D2", "D3", "D4"],
                "gl_account": ["5100", "5100", "6200", "6200"],
            }
        )
        result = _make_result(
            "layer_b",
            pd.DataFrame({"L2-03": [0.90, 0.75, 0.55, 0.0]}, index=df.index),
            metadata={
                "rule_breakdowns": {
                    "L2-03": {
                        "reason_counts": {
                            "reference_duplicate": 1,
                            "split_duplicate": 1,
                            "near_duplicate": 1,
                        },
                        "confidence_band_counts": {
                            "high": 1,
                            "medium": 1,
                            "low": 1,
                        },
                    }
                }
            },
        )
        labels = pd.DataFrame(
            {
                "document_id": ["D1"],
                "anomaly_type": ["DuplicateEntry"],
            }
        )

        analysis = per_rule_label_analysis(df, {"layer_b": result}, labels)
        l203 = next(item for item in analysis if item["rule_id"] == "L2-03")

        assert l203["score_bands"] == {
            "high_confidence_docs": 1,
            "medium_confidence_docs": 1,
            "low_confidence_docs": 1,
        }
        assert l203["breakdown"]["confidence_band_counts"]["high"] == 1
        assert l203["breakdown"]["reason_counts"]["reference_duplicate"] == 1
        assert l203["review_queue_docs"] == 2
        assert l203["status"] == "coverage_anchor"
        assert l203["truth_basis"] == (
            "DuplicateEntry/ExactDuplicateAmount labels with confidence-band review queue"
        )
        assert "high/medium/low confidence bands" in l203["reason"]

    def test_l2_01_keeps_threshold_proximity_bands(self):
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D2", "D3", "D4"],
            }
        )
        result = _make_result(
            "layer_b",
            pd.DataFrame({"L2-01": [0.45, 0.60, 0.75, 0.0]}, index=df.index),
            metadata={
                "row_annotations": {
                    "L2-01": {
                        0: {"bucket": "lower_band"},
                        1: {"bucket": "close_band"},
                        2: {"bucket": "razor_band"},
                    }
                }
            },
        )
        labels = pd.DataFrame(
            {"document_id": ["D3"], "anomaly_type": ["JustBelowThreshold"]}
        )

        analysis = per_rule_label_analysis(df, {"layer_b": result}, labels)
        l201 = next(item for item in analysis if item["rule_id"] == "L2-01")

        assert l201["score_bands"] == {
            "lower_band_docs": 1,
            "close_band_docs": 1,
            "razor_band_docs": 1,
        }
        assert l201["review_queue_docs"] == 2

    def test_l2_02_keeps_reference_and_fallback_bands(self):
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D2", "D3", "D4"],
            }
        )
        result = _make_result(
            "layer_b",
            pd.DataFrame({"L2-02": [0.90, 0.70, 0.60, 0.0]}, index=df.index),
            metadata={
                "row_annotations": {
                    "L2-02": {
                        0: {"reason_code": "reference_match"},
                        1: {"reason_code": "mixed_reference_fallback"},
                        2: {"reason_code": "blank_reference_fallback"},
                    }
                }
            },
        )
        labels = pd.DataFrame(
            {"document_id": ["D1"], "anomaly_type": ["DuplicatePayment"]}
        )

        analysis = per_rule_label_analysis(df, {"layer_b": result}, labels)
        l202 = next(item for item in analysis if item["rule_id"] == "L2-02")

        assert l202["score_bands"] == {
            "reference_match_docs": 1,
            "mixed_reference_fallback_docs": 1,
            "blank_reference_fallback_docs": 1,
        }
        assert l202["review_queue_docs"] == 2
        assert l202["status"] == "coverage_anchor"
        assert l202["truth_basis"] == (
            "DuplicatePayment labels; detector evidence is document-pair based"
        )
        assert "pair-oriented" in l202["reason"]

    def test_l2_03_score_bands_use_document_max_score(self):
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D1", "D2", "D3"],
            }
        )
        result = _make_result(
            "layer_b",
            pd.DataFrame({"L2-03": [0.90, 0.55, 0.75, 0.0]}, index=df.index),
        )
        labels = pd.DataFrame(
            {"document_id": ["D1"], "anomaly_type": ["DuplicateEntry"]}
        )

        analysis = per_rule_label_analysis(df, {"layer_b": result}, labels)
        l203 = next(item for item in analysis if item["rule_id"] == "L2-03")

        assert l203["score_bands"] == {
            "high_confidence_docs": 1,
            "medium_confidence_docs": 1,
            "low_confidence_docs": 0,
        }
        assert l203["review_queue_docs"] == 1

    def test_l2_05_keeps_reversal_interpretation_bands(self):
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D2", "D3"],
                "gl_account": ["1000", "1000", "2000"],
            }
        )
        result = _make_result(
            "layer_c",
            pd.DataFrame({"L2-05": [0.90, 0.55, 0.0]}, index=df.index),
            metadata={
                "rule_breakdowns": {
                    "L2-05": {
                        "high_confidence_count": 1,
                        "candidate_count": 1,
                    }
                },
                "row_annotations": {
                    "L2-05": {
                        0: {"interpretation_code": "high_confidence_reversal"},
                        1: {
                            "interpretation_code": (
                                "candidate_reversal_clearing_reclass"
                            )
                        },
                    }
                },
            },
        )
        labels = pd.DataFrame(
            {
                "document_id": ["D1"],
                "anomaly_type": ["ReversedAmount"],
            }
        )

        analysis = per_rule_label_analysis(df, {"layer_c": result}, labels)
        l205 = next(item for item in analysis if item["rule_id"] == "L2-05")

        assert l205["score_bands"] == {
            "high_confidence_reversal_docs": 1,
            "candidate_clearing_reclass_docs": 1,
        }
        assert l205["breakdown"]["high_confidence_count"] == 1
        assert l205["breakdown"]["candidate_count"] == 1
        assert l205["review_queue_docs"] == 1
        assert l205["status"] == "coverage_anchor"
        assert l205["truth_basis"] == (
            "confirmed ReversedAmount labels for high-confidence reversals; "
            "clearing/reclass candidates are review population"
        )
        assert "candidate clearing/reclass" in l205["reason"]

    def test_l3_03_keeps_population_and_ic_graph_overlap_bands(self):
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D2", "D3", "D4"],
                "is_intercompany": [True, True, False, True],
            }
        )
        layer_b = _make_result(
            "layer_b",
            pd.DataFrame({"L3-03": [0.4, 0.4, 0.0, 0.4]}, index=df.index),
            metadata={
                "rule_breakdowns": {
                    "L3-03": {
                        "ic_population_rows": 3,
                        "ic_population_docs": 3,
                    }
                }
            },
        )
        intercompany = _make_result(
            "intercompany",
            pd.DataFrame({"IC01": [0.0, 0.8, 0.0, 0.0]}, index=df.index),
        )
        graph = _make_result(
            "graph",
            pd.DataFrame({"GR01": [0.0, 0.0, 0.0, 0.8]}, index=df.index),
        )
        labels = pd.DataFrame(
            {
                "document_id": ["D4"],
                "anomaly_type": ["CircularIntercompany"],
            }
        )

        analysis = per_rule_label_analysis(
            df,
            {"layer_b": layer_b, "intercompany": intercompany, "graph": graph},
            labels,
        )
        l303 = next(item for item in analysis if item["rule_id"] == "L3-03")

        assert l303["status"] == "population"
        assert l303["score_bands"] == {
            "ic_population_docs": 3,
            "ic_exception_overlap_docs": 1,
            "graph_overlap_docs": 1,
        }
        assert l303["breakdown"]["ic_population_docs"] == 3
        assert l303["review_queue_docs"] == 3

    def test_l3_06_keeps_confirmed_and_normal_context_bands(self):
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D2", "D3"],
                "is_after_hours": [True, True, False],
            }
        )
        result = _make_result(
            "layer_c",
            pd.DataFrame({"L3-06": [0.45, 0.20, 0.0]}, index=df.index),
            metadata={
                "rule_breakdowns": {
                    "L3-06": {
                        "confirmed_after_hours_rows": 1,
                        "normal_system_context_rows": 1,
                    }
                }
            },
        )
        labels = pd.DataFrame(
            {
                "document_id": ["D1"],
                "anomaly_type": ["AfterHoursPosting"],
            }
        )

        analysis = per_rule_label_analysis(df, {"layer_c": result}, labels)
        l306 = next(item for item in analysis if item["rule_id"] == "L3-06")

        assert l306["score_bands"] == {
            "confirmed_after_hours_docs": 1,
            "normal_system_context_docs": 1,
        }
        assert l306["breakdown"]["normal_system_context_rows"] == 1
        assert l306["review_queue_docs"] == 1

    def test_l3_07_keeps_direction_and_gap_size_bands(self):
        df = pd.DataFrame({"document_id": ["D1", "D2", "D3", "D4"]})
        result = _make_result(
            "layer_c",
            pd.DataFrame({"L3-07": [0.45, 0.60, 0.75, 0.0]}, index=df.index),
            metadata={
                "row_annotations": {
                    "L3-07": {
                        0: {
                            "direction": "late_posting",
                            "bucket": "late_moderate_gap",
                        },
                        1: {
                            "direction": "forward_date_gap",
                            "bucket": "forward_large_gap",
                        },
                        2: {
                            "direction": "late_posting",
                            "bucket": "late_extreme_gap",
                        },
                    }
                }
            },
        )
        labels = pd.DataFrame({"document_id": ["D3"], "anomaly_type": ["BackdatedEntry"]})

        analysis = per_rule_label_analysis(df, {"layer_c": result}, labels)
        l307 = next(item for item in analysis if item["rule_id"] == "L3-07")

        assert l307["score_bands"] == {
            "late_posting_docs": 2,
            "forward_date_gap_docs": 1,
            "moderate_gap_docs": 1,
            "large_gap_docs": 1,
            "extreme_gap_docs": 1,
        }
        assert l307["review_queue_docs"] == 3

    def test_l3_08_keeps_description_quality_bands(self):
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D2", "D3", "D4"],
                "description_quality": ["missing", "corrupted", "poor", "normal"],
            }
        )
        result = _make_result(
            "layer_c",
            pd.DataFrame({"L3-08": [0.45, 0.55, 0.50, 0.0]}, index=df.index),
            metadata={
                "rule_breakdowns": {
                    "L3-08": {
                        "missing_rows": 1,
                        "corrupted_rows": 1,
                        "poor_legacy_rows": 1,
                    }
                }
            },
        )
        labels = pd.DataFrame(
            {
                "document_id": ["D1", "D2"],
                "anomaly_type": [
                    "MissingOrCorruptedDescription",
                    "MissingOrCorruptedDescription",
                ],
            }
        )

        analysis = per_rule_label_analysis(df, {"layer_c": result}, labels)
        l308 = next(item for item in analysis if item["rule_id"] == "L3-08")

        assert l308["score_bands"] == {
            "missing_description_docs": 1,
            "corrupted_description_docs": 1,
            "poor_legacy_docs": 1,
        }
        assert l308["breakdown"]["poor_legacy_rows"] == 1
        assert l308["review_queue_docs"] == 3

    def test_l3_10_keeps_sensitive_account_signal_bands(self):
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D2", "D3", "D4"],
                "gl_account": ["1190", "1190", "1190", "5100"],
            }
        )
        result = _make_result(
            "layer_b",
            pd.DataFrame({"L3-10": [0.65, 0.35, 0.20, 0.0]}, index=df.index),
            metadata={
                "rule_breakdowns": {
                    "L3-10": {
                        "priority_case_rows": 1,
                        "raw_signal_rows": 1,
                        "normal_control_candidate_rows": 1,
                    }
                },
                "row_annotations": {
                    "L3-10": {
                        0: {"signal_category": "priority_case"},
                        1: {"signal_category": "raw_signal"},
                        2: {"signal_category": "normal_control_candidate"},
                    }
                },
            },
        )
        labels = pd.DataFrame({"document_id": [], "anomaly_type": []})

        analysis = per_rule_label_analysis(df, {"layer_b": result}, labels)
        l310 = next(item for item in analysis if item["rule_id"] == "L3-10")

        assert l310["score_bands"] == {
            "raw_sensitive_touch_docs": 1,
            "priority_case_docs": 1,
            "normal_control_docs": 1,
        }
        assert l310["breakdown"]["raw_signal_rows"] == 1
        assert l310["review_queue_docs"] == 1

    def test_l2_04_keeps_immediate_and_review_bands(self):
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D2", "D3", "D4"],
                "gl_account": ["1500", "6100", "1500", "6100"],
            }
        )
        result = _make_result(
            "layer_b",
            pd.DataFrame({"L2-04": [0.80, 0.80, 0.65, 0.0]}, index=df.index),
            metadata={
                "rule_breakdowns": {
                    "L2-04": {
                        "immediate_rows": 2,
                        "review_rows": 1,
                        "immediate_docs": 2,
                        "review_docs": 1,
                        "normal_context_suppressed_docs": 1,
                    }
                }
            },
        )
        labels = pd.DataFrame(
            {
                "document_id": ["D1"],
                "anomaly_type": ["ImproperCapitalization"],
            }
        )

        analysis = per_rule_label_analysis(df, {"layer_b": result}, labels)
        l204 = next(item for item in analysis if item["rule_id"] == "L2-04")

        assert l204["score_bands"] == {"immediate_docs": 2, "review_docs": 1}
        assert l204["breakdown"]["normal_context_suppressed_docs"] == 1
        assert l204["review_queue_docs"] == 1
        assert l204["status"] == "coverage_anchor"
        assert l204["label_types"] == ["ExpenseCapitalization", "ImproperCapitalization"]
        assert l204["truth_display"] == "ExpenseCapitalization family"
        assert "family coverage" in l204["reason"]

    def test_l2_04_score_bands_use_document_max_score(self):
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D1", "D2", "D3"],
                "gl_account": ["1500", "6100", "1500", "6100"],
            }
        )
        result = _make_result(
            "layer_b",
            pd.DataFrame({"L2-04": [0.80, 0.65, 0.65, 0.0]}, index=df.index),
        )
        labels = pd.DataFrame(
            {"document_id": ["D1"], "anomaly_type": ["ImproperCapitalization"]}
        )

        analysis = per_rule_label_analysis(df, {"layer_b": result}, labels)
        l204 = next(item for item in analysis if item["rule_id"] == "L2-04")

        assert l204["score_bands"] == {"immediate_docs": 1, "review_docs": 1}
        assert l204["review_queue_docs"] == 1

    def test_l3_05_keeps_calendar_review_bands(self):
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D2", "D3", "D4"],
                "is_weekend": [True, False, True, False],
                "is_holiday": [False, True, True, False],
            }
        )
        result = _make_result(
            "layer_c",
            pd.DataFrame({"L3-05": [0.40, 0.35, 0.45, 0.0]}, index=df.index),
            metadata={
                "rule_breakdowns": {
                    "L3-05": {
                        "calendar_review_docs": 3,
                        "weekend_only_docs": 1,
                        "weekday_holiday_docs": 1,
                        "weekend_holiday_docs": 1,
                    }
                }
            },
        )
        labels = pd.DataFrame(
            {
                "document_id": ["D1"],
                "anomaly_type": ["WeekendPosting"],
            }
        )

        analysis = per_rule_label_analysis(df, {"layer_c": result}, labels)
        l305 = next(item for item in analysis if item["rule_id"] == "L3-05")

        assert l305["status"] == "population"
        assert l305["score_bands"] == {
            "calendar_review_docs": 3,
            "weekend_docs": 2,
            "weekday_holiday_docs": 1,
            "weekend_holiday_docs": 1,
        }
        assert l305["breakdown"]["weekday_holiday_docs"] == 1
        assert l305["review_queue_docs"] == 3

    def test_l3_11_keeps_cutoff_review_bands(self):
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D2", "D3", "D4"],
                "gl_account": ["4100", "5100", "4100", "4100"],
            }
        )
        result = _make_result(
            "evidence",
            pd.DataFrame({"L3-11": [0.28, 0.38, 0.62, 0.0]}, index=df.index),
            metadata={
                "rule_breakdowns": {
                    "L3-11": {
                        "cutoff_review_docs": 3,
                        "revenue_cutoff_docs": 2,
                        "expense_cutoff_docs": 1,
                        "period_end_weighted_docs": 1,
                    }
                }
            },
        )
        labels = pd.DataFrame(
            {
                "document_id": ["D2", "D3"],
                "anomaly_type": ["RevenueCutoffMismatch", "ExpenseCutoffMismatch"],
            }
        )

        analysis = per_rule_label_analysis(df, {"evidence": result}, labels)
        l311 = next(item for item in analysis if item["rule_id"] == "L3-11")

        assert l311["status"] == "population"
        assert l311["score_bands"] == {
            "cutoff_review_docs": 3,
            "cutoff_priority_docs": 2,
            "cutoff_high_docs": 1,
        }
        assert l311["breakdown"]["period_end_weighted_docs"] == 1
        assert l311["review_queue_docs"] == 3

    def test_l3_01_keeps_exact_and_category_review_bands(self):
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D2", "D3", "D4"],
                "gl_account": ["4100", "1200", "4100", "1000"],
            }
        )
        result = _make_result(
            "layer_a",
            pd.DataFrame({"L3-01": [0.65, 0.45, 0.40, 0.0]}, index=df.index),
            metadata={
                "rule_breakdowns": {
                    "L3-01": {
                        "exact_denied_docs": 1,
                        "category_mismatch_docs": 1,
                        "strict_allowed_mismatch_docs": 1,
                        "keyword_suppressed_docs": 1,
                    }
                }
            },
        )
        labels = pd.DataFrame(
            {
                "document_id": ["D1"],
                "anomaly_type": ["MisclassifiedAccount"],
            }
        )

        analysis = per_rule_label_analysis(df, {"layer_a": result}, labels)
        l301 = next(item for item in analysis if item["rule_id"] == "L3-01")

        assert l301["score_bands"] == {
            "exact_denied_docs": 1,
            "category_review_docs": 2,
        }
        assert l301["breakdown"]["strict_allowed_mismatch_docs"] == 1
        assert l301["review_queue_docs"] == 2

    def test_l4_05_keeps_behavior_bands_and_review_queue(self):
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D1", "D2", "D3", "D4"],
                "created_by": ["u1", "u1", "u2", "u3", "u4"],
            }
        )
        result = _make_result(
            "layer_c",
            pd.DataFrame({"L4-05": [0.45, 0.65, 0.55, 0.50, 0.0]}, index=df.index),
            metadata={
                "rule_breakdowns": {
                    "L4-05": {
                        "behavior_review_docs": 3,
                        "rapid_approval_docs": 1,
                    }
                },
                "row_annotations": {
                    "L4-05": {
                        0: {"reason_codes": ["sigma_outlier"]},
                        1: {"reason_codes": ["sigma_outlier", "rapid_approval"]},
                        2: {"reason_codes": ["high_context_midnight"]},
                        3: {"reason_codes": ["low_volume_midnight"]},
                    }
                },
            },
        )
        labels = pd.DataFrame(
            {
                "document_id": ["D1"],
                "anomaly_type": ["AbnormalHoursConcentration"],
            }
        )

        analysis = per_rule_label_analysis(df, {"layer_c": result}, labels)
        l405 = next(item for item in analysis if item["rule_id"] == "L4-05")

        assert l405["status"] == "coverage_anchor"
        assert l405["truth_display"] == "abnormal-hours behavior review"
        assert l405["score_bands"] == {
            "behavior_review_docs": 3,
            "sigma_outlier_docs": 1,
            "low_volume_midnight_docs": 1,
            "high_context_midnight_docs": 1,
            "rapid_approval_docs": 1,
        }
        assert l405["review_queue_docs"] == 3
        assert l405["rule_objective"] == "User-level abnormal-hours behavior concentration"

    def test_l4_03_keeps_high_amount_review_bands_and_queue(self):
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D2", "D3", "D4"],
                "amount_zscore": [3.5, 4.5, 6.5, 1.0],
            }
        )
        result = _make_result(
            "layer_c",
            pd.DataFrame({"L4-03": [0.45, 0.60, 0.75, 0.0]}, index=df.index),
            metadata={
                "rule_breakdowns": {
                    "L4-03": {
                        "high_amount_review_docs": 3,
                        "review_zscore_docs": 1,
                        "strong_zscore_docs": 1,
                        "extreme_zscore_docs": 1,
                    }
                },
                "row_annotations": {
                    "L4-03": {
                        0: {"bucket": "review_zscore"},
                        1: {"bucket": "strong_zscore"},
                        2: {"bucket": "extreme_zscore"},
                    }
                },
            },
        )
        labels = pd.DataFrame(
            {
                "document_id": ["D2"],
                "anomaly_type": ["UnusuallyHighAmount"],
            }
        )

        analysis = per_rule_label_analysis(df, {"layer_c": result}, labels)
        l403 = next(item for item in analysis if item["rule_id"] == "L4-03")

        assert l403["status"] == "coverage_anchor"
        assert l403["truth_display"] == "high-amount confirmed subset"
        assert l403["score_bands"] == {
            "high_amount_review_docs": 3,
            "review_zscore_docs": 1,
            "strong_zscore_docs": 1,
            "extreme_zscore_docs": 1,
        }
        assert l403["review_queue_docs"] == 3
        assert l403["rule_objective"] == "High-amount positive z-score review anchor"

    def test_l4_04_keeps_rare_pair_review_bands_and_queue(self):
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D1", "D2", "D3"],
                "gl_account": ["1000", "2000", "3000", "4000"],
            }
        )
        result = _make_result(
            "layer_c",
            pd.DataFrame({"L4-04": [0.40, 0.40, 0.40, 0.0]}, index=df.index),
            metadata={
                "rule_breakdowns": {
                    "L4-04": {
                        "rare_pair_review_docs": 2,
                        "ordinary_rare_pair_docs": 2,
                        "large_doc_distinct_pair_docs": 1,
                    }
                },
                "row_annotations": {
                    "L4-04": {
                        0: {"reason_codes": ["rare_account_pair"]},
                        1: {"reason_codes": ["rare_account_pair"]},
                        2: {"reason_codes": ["rare_account_pair", "large_doc_distinct_pair"]},
                    }
                },
            },
        )
        labels = pd.DataFrame(
            {
                "document_id": ["D2"],
                "anomaly_type": ["UnusualAccountPair"],
            }
        )

        analysis = per_rule_label_analysis(df, {"layer_c": result}, labels)
        l404 = next(item for item in analysis if item["rule_id"] == "L4-04")

        assert l404["status"] == "coverage_anchor"
        assert l404["truth_display"] == "rare account-pair review population"
        assert l404["score_bands"] == {
            "rare_pair_review_docs": 2,
            "ordinary_rare_pair_docs": 2,
            "large_doc_distinct_pair_docs": 1,
        }
        assert l404["review_queue_docs"] == 2
        assert l404["rule_objective"] == "Rare debit-credit account-pair review anchor"

    def test_l4_06_keeps_batch_auxiliary_bands_and_review_queue(self):
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D1", "D2", "D3", "D4"],
                "source": ["batch", "batch", "automated", "interface", "manual"],
            }
        )
        result = _make_result(
            "layer_c",
            pd.DataFrame({"L4-06": [0.40, 0.40, 0.40, 0.40, 0.0]}, index=df.index),
            metadata={
                "rule_breakdowns": {
                    "L4-06": {
                        "batch_review_docs": 3,
                        "period_end_concentration_docs": 1,
                        "simultaneous_creation_docs": 2,
                        "amount_outlier_docs": 1,
                    }
                },
                "row_annotations": {
                    "L4-06": {
                        0: {"reason_codes": ["period_end_concentration"]},
                        1: {"reason_codes": ["simultaneous_creation"]},
                        2: {"reason_codes": ["simultaneous_creation", "amount_outlier"]},
                        3: {"reason_codes": ["period_end_concentration"]},
                    }
                },
            },
        )
        labels = pd.DataFrame({"document_id": [], "anomaly_type": []})

        analysis = per_rule_label_analysis(df, {"layer_c": result}, labels)
        l406 = next(item for item in analysis if item["rule_id"] == "L4-06")

        assert l406["status"] == "coverage_anchor"
        assert l406["truth_display"] == "batch-processing auxiliary review"
        assert l406["score_bands"] == {
            "batch_review_docs": 3,
            "period_end_concentration_docs": 2,
            "simultaneous_creation_docs": 2,
            "amount_outlier_docs": 1,
        }
        assert l406["review_queue_docs"] == 3
        assert l406["rule_objective"] == "Batch-processing anomaly auxiliary evidence"

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
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D1", "D2", "D2", "D3", "D3"],
                "debit_amount": [100.0, 0.0, 50.0, 0.0, 100.0, 0.0],
                "credit_amount": [0.0, 90.0, 0.0, 50.0, 0.0, 0.0],
            }
        )
        agg_df = pd.DataFrame(
            {
                "anomaly_score": [0.8, 0.8, 0.0, 0.0, 0.7, 0.7],
                "risk_level": ["High", "High", "Normal", "Normal", "Medium", "Medium"],
            }
        )
        result = _make_result(
            "layer_a",
            pd.DataFrame({"L1-01": [1.0, 1.0, 0.0, 0.0, 1.0, 1.0]}, index=df.index),
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
        assert report.rule_metrics[0].precision == 1.0

    def test_build_benford_population_benchmarks_uses_sidecars(self):
        labels_dir = Path(".tmp_metric_benford_sidecars_1") / "labels"
        if labels_dir.parent.exists():
            shutil.rmtree(labels_dir.parent)
        labels_dir.mkdir(parents=True)
        try:
            pd.DataFrame({
                "fiscal_year": [2024, 2024],
                "company_code": ["C001", "C002"],
                "gl_account": ["1000", "2000"],
            }).to_csv(labels_dir / "benford_finding_truth_2024.csv", index=False)
            pd.DataFrame({
                "fiscal_year": [2024],
                "company_code": ["C003"],
                "gl_account": ["3000"],
            }).to_csv(labels_dir / "benford_normal_groups_2024.csv", index=False)
            pd.DataFrame({
                "document_id": ["D1"],
                "line_number": [1],
            }).to_csv(labels_dir / "benford_drilldown_candidates_2024.csv", index=False)
            pd.DataFrame({
                "fiscal_year": [2024, 2024],
                "company_code": ["C001", "C004"],
                "gl_account": ["1000", "4000"],
            }).to_csv(labels_dir / "benford_adversarial_holdout_2024.csv", index=False)

            df = pd.DataFrame({
                "fiscal_year": [2024, 2024, 2024],
                "document_id": ["D1", "D2", "D3"],
                "line_number": [1, 1, 1],
                "company_code": ["C001", "C002", "C003"],
                "gl_account": ["1000", "2000", "3000"],
            })
            result = _make_result(
                "benford",
                pd.DataFrame({"L4-02": [0.0, 0.0, 0.0]}, index=df.index),
                metadata={
                    "benford_findings": [
                        {"company_code": "C001", "gl_account": "1000.0"},
                        {"company_code": "C003", "gl_account": "3000"},
                    ],
                    "benford_candidate_indices": [0, 1],
                },
            )

            metrics = build_benford_population_benchmarks(df, result, labels_dir)
            by_name = {metric.benchmark: metric for metric in metrics}

            assert by_name["contract_findings"].hit_count == 1
            assert by_name["contract_findings"].miss_count == 1
            assert by_name["contract_findings"].extra_count == 1
            assert by_name["normal_group_controls"].hit_count == 1
            assert by_name["drilldown_candidate_rows"].precision == 0.5
            assert by_name["drilldown_candidate_rows"].recall == 1.0
            assert by_name["adversarial_holdout"].hit_count == 1
            assert by_name["adversarial_holdout"].miss_count == 1
        finally:
            shutil.rmtree(labels_dir.parent, ignore_errors=True)

    def test_build_ground_truth_report_attaches_benford_benchmarks(self):
        labels_dir = Path(".tmp_metric_benford_sidecars_2") / "labels"
        if labels_dir.parent.exists():
            shutil.rmtree(labels_dir.parent)
        labels_dir.mkdir(parents=True)
        try:
            pd.DataFrame({
                "fiscal_year": [2024],
                "company_code": ["C001"],
                "gl_account": ["1000"],
            }).to_csv(labels_dir / "benford_finding_truth_2024.csv", index=False)

            df = pd.DataFrame({
                "fiscal_year": [2024],
                "document_id": ["D1"],
                "line_number": [1],
                "debit_amount": [100.0],
                "credit_amount": [0.0],
            })
            agg_df = pd.DataFrame({"anomaly_score": [0.0]})
            result = _make_result(
                "benford",
                pd.DataFrame({"L4-02": [0.0]}, index=df.index),
                metadata={
                    "benford_findings": [
                        {"company_code": "C001", "gl_account": "1000"},
                    ],
                },
            )
            labels = pd.DataFrame({"document_id": [], "anomaly_type": []})

            report = build_ground_truth_report(
                df,
                agg_df,
                {"benford": result},
                labels,
                upload_batch_id="batch_benford",
                labels_dir=labels_dir,
                fiscal_year=2024,
            )

            assert report.benford_benchmarks
            assert report.benford_benchmarks[0].benchmark == "contract_findings"
        finally:
            shutil.rmtree(labels_dir.parent, ignore_errors=True)

    def test_build_ground_truth_report_marks_missing_benford_sidecars(self):
        labels_dir = Path(".tmp_metric_benford_missing_sidecars") / "labels"
        if labels_dir.parent.exists():
            shutil.rmtree(labels_dir.parent)
        labels_dir.mkdir(parents=True)
        try:
            df = pd.DataFrame({
                "fiscal_year": [2024],
                "document_id": ["D1"],
                "line_number": [1],
                "debit_amount": [100.0],
                "credit_amount": [0.0],
            })
            agg_df = pd.DataFrame({"anomaly_score": [0.0]})
            result = _make_result(
                "benford",
                pd.DataFrame({"L4-02": [0.0]}, index=df.index),
                metadata={"benford_findings": []},
            )
            labels = pd.DataFrame({"document_id": [], "anomaly_type": []})

            report = build_ground_truth_report(
                df,
                agg_df,
                {"benford": result},
                labels,
                upload_batch_id="batch_benford_missing",
                labels_dir=labels_dir,
                fiscal_year=2024,
            )

            assert report.benford_benchmarks
            assert report.benford_benchmarks[0].benchmark == "sidecars_missing"
            assert "unavailable" in report.benford_benchmarks[0].note
        finally:
            shutil.rmtree(labels_dir.parent, ignore_errors=True)

    def test_build_ground_truth_report_marks_missing_analytical_review_sidecars(self):
        labels_dir = Path(".tmp_metric_missing_variance_sidecars") / "labels"
        if labels_dir.parent.exists():
            shutil.rmtree(labels_dir.parent)
        labels_dir.mkdir(parents=True)
        try:
            df = pd.DataFrame({
                "fiscal_year": [2024],
                "company_code": ["C001"],
                "gl_account": ["1000"],
                "document_id": ["D1"],
            })
            agg_df = pd.DataFrame({"anomaly_score": [0.0]}, index=df.index)
            variance_result = _make_result(
                "layer_d",
                pd.DataFrame({"D01": [0.0], "D02": [0.0]}, index=df.index),
                metadata={
                    "account_activity_variance": [
                        {"company_code": "C001", "gl_account": "1000"},
                    ],
                    "d02_account_diagnostics": [],
                },
            )
            labels = pd.DataFrame({"document_id": [], "anomaly_type": []})

            report = build_ground_truth_report(
                df,
                agg_df,
                {"layer_d": variance_result},
                labels,
                upload_batch_id="batch_variance_missing_sidecars",
                labels_dir=labels_dir,
                fiscal_year=2024,
            )

            by_rule = {metric.rule_code: metric for metric in report.analytical_review_metrics}
            assert by_rule["D01"].review_groups == 1
            assert by_rule["D01"].truth_groups == 0
            assert "benchmark unavailable" in by_rule["D01"].note
            assert by_rule["D02"].review_groups == 0
            assert "benchmark unavailable" in by_rule["D02"].note
        finally:
            shutil.rmtree(labels_dir.parent, ignore_errors=True)

    def test_build_ground_truth_report_attaches_variance_account_review_metrics(self):
        labels_dir = Path(".tmp_metric_variance_sidecars") / "labels"
        if labels_dir.parent.exists():
            shutil.rmtree(labels_dir.parent)
        labels_dir.mkdir(parents=True)
        try:
            pd.DataFrame({
                "fiscal_year": [2024],
                "company_code": ["C001"],
                "gl_account": ["1000"],
            }).to_csv(labels_dir / "account_activity_variance_truth_2024.csv", index=False)
            pd.DataFrame({
                "fiscal_year": [2024],
                "company_code": ["C002"],
                "gl_account": ["2000"],
            }).to_csv(
                labels_dir / "account_activity_variance_normal_controls_2024.csv",
                index=False,
            )
            pd.DataFrame({
                "fiscal_year": [2024, 2024],
                "company_code": ["C001", "C002"],
                "gl_account": ["1000", "2000"],
            }).to_csv(
                labels_dir / "account_activity_variance_review_population_2024.csv",
                index=False,
            )
            pd.DataFrame({
                "fiscal_year": [2024],
                "company_code": ["C001"],
                "gl_account": ["3000"],
            }).to_csv(
                labels_dir / "monthly_pattern_shift_confirmed_anomalies_2024.csv",
                index=False,
            )
            pd.DataFrame({
                "fiscal_year": [2024],
                "company_code": ["C001"],
                "gl_account": ["3000"],
            }).to_csv(
                labels_dir / "monthly_pattern_shift_review_population_2024.csv",
                index=False,
            )

            df = pd.DataFrame({
                "fiscal_year": [2024, 2024, 2024],
                "company_code": ["C001", "C002", "C001"],
                "gl_account": ["1000", "2000", "3000"],
                "document_id": ["D1", "D2", "D3"],
                "debit_amount": [100.0, 200.0, 300.0],
                "credit_amount": [0.0, 0.0, 0.0],
            })
            agg_df = pd.DataFrame({"anomaly_score": [0.0, 0.0, 0.0]}, index=df.index)
            variance_result = _make_result(
                "layer_d",
                pd.DataFrame({"D01": [0.0, 0.0, 0.0], "D02": [0.0, 0.0, 0.0]}, index=df.index),
                metadata={
                    "account_activity_variance": [
                        {"company_code": "C001", "gl_account": "1000"},
                        {"company_code": "C002", "gl_account": "2000"},
                    ],
                    "d02_account_diagnostics": [
                        {"company_code": "C001", "gl_account": "3000", "flagged": True},
                    ],
                },
            )
            labels = pd.DataFrame({"document_id": [], "anomaly_type": []})

            report = build_ground_truth_report(
                df,
                agg_df,
                {"layer_d": variance_result},
                labels,
                upload_batch_id="batch_variance",
                labels_dir=labels_dir,
                fiscal_year=2024,
            )

            by_rule = {metric.rule_code: metric for metric in report.analytical_review_metrics}
            assert by_rule["D01"].truth_covered == 1
            assert by_rule["D01"].normal_control_review_groups == 1
            assert by_rule["D01"].review_population_covered == 2
            assert by_rule["D02"].truth_covered == 1
            assert by_rule["D02"].truth_coverage == 1.0
        finally:
            shutil.rmtree(labels_dir.parent, ignore_errors=True)
