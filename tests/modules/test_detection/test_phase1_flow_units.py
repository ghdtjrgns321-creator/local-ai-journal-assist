"""PHASE1 P2-3a flow unit adapter tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from src.detection.base import DetectionResult, RuleFlag
from src.detection.phase1_case_builder import build_phase1_case_result


def _config() -> dict:
    return {
        "phase1_case": {
            "top_n_cases": 50,
            "top_n_per_theme": 10,
            "priority_band": {"high": 0.90, "medium": 0.75},
            "topic_scoring": {},
        }
    }


def _df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "document_id": ["D-A", "D-B", "D-C", "D-D"],
            "posting_date": pd.to_datetime(
                ["2026-04-01", "2026-04-02", "2026-04-03", "2026-04-04"]
            ),
            "company_code": ["C001", "C002", "C001", "C003"],
            "trading_partner": ["C002", "C001", "C003", "C001"],
            "gl_account": ["410000", "410000", "120000", "220000"],
            "debit_amount": [100.0, 100.0, 250.0, 0.0],
            "credit_amount": [0.0, 0.0, 0.0, 250.0],
            "business_process": ["R2R", "R2R", "P2P", "P2P"],
        },
        index=[10, 11, 12, 13],
    )


def _l202_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "document_id": ["P-A", "P-B", "P-C", "P-D", "P-E", "P-E"],
            "posting_date": pd.to_datetime(
                [
                    "2026-04-01",
                    "2026-04-03",
                    "2026-01-05",
                    "2026-02-05",
                    "2026-04-05",
                    "2026-04-05",
                ]
            ),
            "company_code": ["C001"] * 6,
            "trading_partner": ["V001", "V001", "V002", "V002", "V003", "V003"],
            "vendor_id": ["V001", "V001", "V002", "V002", "V003", "V003"],
            "gl_account": ["510000"] * 6,
            "debit_amount": [1000.0, 1000.0, 500.0, 500.0, 300.0, 300.0],
            "credit_amount": [0.0] * 6,
            "reference": ["INV-77", "INV-77", "RENT-JAN", "RENT-FEB", "INV-88", "INV-88"],
            "document_type": ["KZ", "KZ", "KZ", "KZ", "KZ", "KZ"],
            "business_process": ["P2P"] * 6,
            "source": ["manual", "manual", "recurring", "recurring", "manual", "manual"],
        },
        index=[100, 101, 102, 103, 104, 105],
    )


def _l205_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "document_id": ["R-A", "R-B", "R-C", "R-D"],
            "posting_date": pd.to_datetime(
                ["2026-04-30", "2026-05-01", "2026-04-15", "2026-04-20"]
            ),
            "company_code": ["C001"] * 4,
            "trading_partner": ["", "", "", ""],
            "gl_account": ["620000", "620000", "630000", "630000"],
            "debit_amount": [700.0, 0.0, 300.0, 100.0],
            "credit_amount": [0.0, 700.0, 0.0, 0.0],
            "reference": ["ACCR-APR", "ACCR-APR", "MISC-1", "MISC-2"],
            "document_type": ["SA", "SA", "SA", "SA"],
            "created_by": ["u01", "u01", "u02", "u03"],
            "source": ["manual", "manual", "manual", "manual"],
            "line_text": ["monthly accrual", "monthly accrual reversal", "misc", "misc"],
            "reversal_document_id": ["R-B", "", "", ""],
        },
        index=[200, 201, 202, 203],
    )


def _ic_absorption_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "document_id": ["IC-A", "IC-B", "DOC-C"],
            "posting_date": pd.to_datetime(["2026-04-01", "2026-04-02", "2026-04-03"]),
            "company_code": ["C001", "C002", "C001"],
            "trading_partner": ["C002", "C001", ""],
            "gl_account": ["115000", "205000", "410000"],
            "debit_amount": [100.0, 0.0, 50.0],
            "credit_amount": [0.0, 100.0, 0.0],
            "business_process": ["R2R", "R2R", "R2R"],
        },
        index=[300, 301, 302],
    )


def _build(result: DetectionResult):
    return build_phase1_case_result(
        _df(),
        [result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config=_config(),
        generated_at=datetime(2026, 6, 4, 0, 0, 0, tzinfo=UTC),
    )


def _build_with_df(df: pd.DataFrame, result: DetectionResult):
    return build_phase1_case_result(
        df,
        [result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config=_config(),
        generated_at=datetime(2026, 6, 4, 0, 0, 0, tzinfo=UTC),
    )


def _flow_units(result: DetectionResult):
    return [unit for unit in _build(result).units if unit.unit_type == "flow"]


def _flow_units_for_df(df: pd.DataFrame, result: DetectionResult):
    return [unit for unit in _build_with_df(df, result).units if unit.unit_type == "flow"]


def test_l202_duplicate_payment_cross_document_link_key_builds_flow_unit() -> None:
    df = _l202_df()
    details = pd.DataFrame({"L2-02": [0.9, 0.9, 0.0, 0.0, 0.9, 0.9]}, index=df.index)
    result = DetectionResult(
        track_name="fraud",
        flagged_indices=[100, 101, 104, 105],
        scores=details["L2-02"],
        rule_flags=[RuleFlag("L2-02", "Duplicate Payment", 4, 4, len(details))],
        details=details,
        metadata={},
    )

    flows = _flow_units_for_df(df, result)

    assert len(flows) == 1
    flow = flows[0]
    assert flow.flow_type == "duplicate_payment"
    assert flow.member_document_ids == ["P-A", "P-B"]
    assert flow.link_key["rule_id"] == "L2-02"
    assert flow.link_key["reference_norm"] == "inv77"
    assert flow.artifact_completeness == "complete"
    assert flow.measurement_eligible is True
    assert {hit.rule_id for hit in flow.evidence_rows} == {"L2-02"}


def test_l202_duplicate_payment_suppresses_same_document_and_routine_repetition() -> None:
    df = _l202_df()
    details = pd.DataFrame({"L2-02": [0.9, 0.9, 0.9, 0.9, 0.9, 0.9]}, index=df.index)
    result = DetectionResult(
        track_name="fraud",
        flagged_indices=df.index.tolist(),
        scores=details["L2-02"],
        rule_flags=[RuleFlag("L2-02", "Duplicate Payment", 4, 6, len(details))],
        details=details,
        metadata={},
    )

    flows = _flow_units_for_df(df, result)

    assert {tuple(flow.member_document_ids) for flow in flows} == {("P-A", "P-B")}
    assert all(len(flow.member_document_ids) >= 2 for flow in flows)


def test_l205_structural_reversal_pair_builds_complete_flow_unit() -> None:
    df = _l205_df()
    details = pd.DataFrame({"L2-05": [0.8, 0.8, 0.0, 0.0]}, index=df.index)
    result = DetectionResult(
        track_name="anomaly",
        flagged_indices=[200, 201],
        scores=details["L2-05"],
        rule_flags=[RuleFlag("L2-05", "Reversal Pattern", 4, 2, len(details))],
        details=details,
        metadata={},
    )

    flows = _flow_units_for_df(df, result)

    assert len(flows) == 1
    flow = flows[0]
    assert flow.flow_type == "reversal"
    assert flow.member_document_ids == ["R-A", "R-B"]
    assert flow.link_key["rule_id"] == "L2-05"
    assert flow.link_key["link_type"] == "structural_reference"
    assert flow.artifact_completeness == "complete"
    assert flow.measurement_eligible is True
    assert flow.priority_band == "low"
    assert flow.priority_score < 0.75


def test_case_priority_is_derived_from_l205_flow_score() -> None:
    df = _l205_df()
    details = pd.DataFrame({"L2-05": [0.8, 0.8, 0.0, 0.0]}, index=df.index)
    result = DetectionResult(
        track_name="anomaly",
        flagged_indices=[200, 201],
        scores=details["L2-05"],
        rule_flags=[RuleFlag("L2-05", "Reversal Pattern", 4, 2, len(details))],
        details=details,
        metadata={},
    )

    phase1 = _build_with_df(df, result)
    flow = next(unit for unit in phase1.units if unit.unit_type == "flow")
    case = phase1.cases[0]

    assert case.priority_score == flow.priority_score
    assert case.composite_sort_score == flow.composite_sort_score
    assert case.priority_band == "low"


def test_l205_unrelated_positive_rows_do_not_build_flow_unit() -> None:
    df = _l205_df().drop(columns=["reversal_document_id"])
    details = pd.DataFrame({"L2-05": [0.0, 0.0, 0.8, 0.8]}, index=df.index)
    result = DetectionResult(
        track_name="anomaly",
        flagged_indices=[202, 203],
        scores=details["L2-05"],
        rule_flags=[RuleFlag("L2-05", "Reversal Pattern", 4, 2, len(details))],
        details=details,
        metadata={},
    )

    assert _flow_units_for_df(df, result) == []


def test_duplicate_pair_artifact_builds_reload_safe_bounded_flow_unit() -> None:
    details = pd.DataFrame({"L2-03": [0.8, 0.8, 0.0, 0.0]}, index=_df().index)
    result = DetectionResult(
        track_name="duplicate",
        flagged_indices=[10, 11],
        scores=details["L2-03"],
        rule_flags=[RuleFlag("L2-03", "Duplicate Entry", 4, 2, len(details))],
        details=details,
        metadata={
            "pair_artifact": {
                "schema_version": 1,
                "total_candidate_pairs": 3,
                "candidate_pairs_after_caps": 3,
                "retained_pairs": 1,
                "truncated": False,
                "truncation_reason": None,
                "top_pairs": [
                    {
                        "rule_id": "L2-03a",
                        "rule_source": "exact_duplicate_amount",
                        "pair_score": 0.95,
                        "left_index": 10,
                        "right_index": 11,
                        "left_document_id": "D-A",
                        "right_document_id": "D-B",
                        "features": {"amount_similarity": 1.0, "date_similarity": 0.95},
                    }
                ],
            }
        },
    )

    first = _flow_units(result)
    second = _flow_units(result)

    assert len(first) == 1
    assert first[0].flow_id == second[0].flow_id
    assert first[0].unit_id == first[0].flow_id
    assert first[0].flow_type == "duplicate_entry"
    assert first[0].member_document_ids == ["D-A", "D-B"]
    assert first[0].link_key["rule_source"] == "exact_duplicate_amount"
    assert first[0].artifact_completeness == "complete"
    assert first[0].measurement_eligible is True
    assert first[0].candidate_count == 1
    assert first[0].retained_count == 1
    assert first[0].cap_reason is None
    assert {hit.rule_id for hit in first[0].evidence_rows} == {"L2-03"}


def test_duplicate_pair_artifact_skips_single_document_member_flow() -> None:
    details = pd.DataFrame({"L2-03": [0.8, 0.8, 0.0, 0.0]}, index=_df().index)
    result = DetectionResult(
        track_name="duplicate",
        flagged_indices=[10, 11],
        scores=details["L2-03"],
        rule_flags=[RuleFlag("L2-03", "Duplicate Entry", 4, 2, len(details))],
        details=details,
        metadata={
            "pair_artifact": {
                "schema_version": 1,
                "total_candidate_pairs": 1,
                "candidate_pairs_after_caps": 1,
                "retained_pairs": 1,
                "truncated": False,
                "truncation_reason": None,
                "top_pairs": [
                    {
                        "rule_id": "L2-03a",
                        "rule_source": "exact_duplicate_amount",
                        "pair_score": 0.95,
                        "left_index": 10,
                        "right_index": 11,
                        "left_document_id": "D-A",
                        "right_document_id": "D-A",
                        "features": {"amount_similarity": 1.0},
                    }
                ],
            }
        },
    )

    assert _flow_units(result) == []


def test_complete_duplicate_artifact_does_not_repeat_artifact_gap_per_flow() -> None:
    details = pd.DataFrame({"L2-03": [0.8, 0.8, 0.8, 0.8]}, index=_df().index)
    result = DetectionResult(
        track_name="duplicate",
        flagged_indices=[10, 11, 12, 13],
        scores=details["L2-03"],
        rule_flags=[RuleFlag("L2-03", "Duplicate Entry", 4, 4, len(details))],
        details=details,
        metadata={
            "pair_artifact": {
                "schema_version": 1,
                "total_candidate_pairs": 2,
                "candidate_pairs_after_caps": 2,
                "retained_pairs": 2,
                "truncated": False,
                "truncation_reason": None,
                "top_pairs": [
                    {
                        "rule_id": "L2-03a",
                        "rule_source": "exact_duplicate_amount",
                        "pair_score": 0.95,
                        "left_index": 10,
                        "right_index": 11,
                        "left_document_id": "D-A",
                        "right_document_id": "D-B",
                        "features": {"amount_similarity": 1.0},
                    },
                    {
                        "rule_id": "L2-03d",
                        "rule_source": "time_shifted_duplicate",
                        "pair_score": 0.85,
                        "left_index": 12,
                        "right_index": 13,
                        "left_document_id": "D-C",
                        "right_document_id": "D-D",
                        "features": {"date_distance_days": 1},
                    },
                ],
            }
        },
    )

    flows = _flow_units(result)

    assert len(flows) == 2
    assert {flow.artifact_completeness for flow in flows} == {"complete"}
    assert {flow.measurement_eligible for flow in flows} == {True}
    assert sum(flow.candidate_count - flow.retained_count for flow in flows) == 0


def test_intercompany_artifact_no_longer_builds_flow_unit() -> None:
    """IC(ic_pair_artifact)는 PHASE1-2 family 귀속 — flow unit 미생성(2026-06-21 완전 제거)."""
    details = pd.DataFrame({"IC02": [0.0, 0.7, 0.0, 0.0]}, index=_df().index)
    result = DetectionResult(
        track_name="intercompany_matcher",
        flagged_indices=[11],
        scores=details["IC02"],
        rule_flags=[RuleFlag("IC02", "IC amount mismatch", 4, 1, len(details))],
        details=details,
        metadata={
            "ic_pair_artifact": {
                "schema_version": 1,
                "candidate_pairs": [],
                "unmatched_rows": [],
                "mismatch_pairs": [
                    {
                        "left_index": 11,
                        "right_index": 11,
                        "left_position": 1,
                        "right_position": 1,
                        "amount_a": 100.0,
                        "amount_b": 80.0,
                        "ratio": 0.8,
                        "mismatch_severity": 0.7,
                    }
                ],
                "reciprocal_pairs": [],
                "coverage": {
                    "candidate_pair_count": 0,
                    "unmatched_row_count": 0,
                    "mismatch_pair_count": 1,
                    "reciprocal_pair_count": 0,
                },
            }
        },
    )

    flows = _flow_units(result)

    assert flows == []


def test_intercompany_structural_artifact_no_longer_builds_flow_unit() -> None:
    """IC 구조 flow(unmatched/reciprocal)도 PHASE1-2 family 귀속 — flow unit 미생성(2026-06-21)."""
    details = pd.DataFrame(
        {"IC01": [0.6, 0.0, 0.0, 0.0], "IC03": [0.0, 0.0, 0.7, 0.7]},
        index=_df().index,
    )
    result = DetectionResult(
        track_name="intercompany_matcher",
        flagged_indices=[10, 12, 13],
        scores=details.max(axis=1),
        rule_flags=[
            RuleFlag("IC01", "IC unmatched", 3, 1, len(details)),
            RuleFlag("IC03", "IC reciprocal", 3, 2, len(details)),
        ],
        details=details,
        metadata={
            "ic_pair_artifact": {
                "schema_version": 1,
                "candidate_pairs": [{"left_position": 0, "right_position": 0}] * 200,
                "unmatched_rows": [
                    {
                        "row_index": 10,
                        "row_position": 0,
                        "document_id": "D-A",
                        "evidence_level": "review",
                        "review_reason": "mapping_uncertain",
                    }
                ],
                "mismatch_pairs": [],
                "reciprocal_pairs": [
                    {
                        "document_id": "D-C",
                        "receivable_positions": [2],
                        "payable_positions": [3],
                        "receivable_amount": 250.0,
                        "payable_amount": 250.0,
                        "amount_symmetry": 1.0,
                    }
                ],
                "coverage": {
                    "candidate_pair_count": 200,
                    "candidate_pair_available_count": 6411,
                    "unmatched_row_count": 1,
                    "mismatch_pair_count": 0,
                    "reciprocal_pair_count": 1,
                    "candidate_pair_truncated": True,
                },
            }
        },
    )

    flows = _flow_units(result)

    assert flows == []


@pytest.mark.skip(
    reason="IC flow 문서흡수 검증 — IC/GR PHASE1 제거(2026-06-14). 일반 흡수 커버리지는 "
    "L2-02 flow 로 repoint 예정(후속)."
)
def test_eligible_flow_absorbs_member_document_rule_hits() -> None:
    df = _ic_absorption_df()
    details = pd.DataFrame(
        {
            "IC03": [0.7, 0.7, 0.0],
            "L3-03": [1.0, 1.0, 0.0],
        },
        index=df.index,
    )
    result = DetectionResult(
        track_name="intercompany_matcher",
        flagged_indices=[300, 301],
        scores=details.max(axis=1),
        rule_flags=[
            RuleFlag("IC03", "IC reciprocal", 3, 2, len(details)),
            RuleFlag("L3-03", "IC review signal", 3, 2, len(details)),
        ],
        details=details,
        metadata={
            "ic_pair_artifact": {
                "schema_version": 1,
                "candidate_pairs": [],
                "unmatched_rows": [],
                "mismatch_pairs": [],
                "reciprocal_pairs": [
                    {
                        "document_id": "IC-A",
                        "receivable_positions": [0],
                        "payable_positions": [1],
                        "receivable_amount": 100.0,
                        "payable_amount": 100.0,
                        "amount_symmetry": 1.0,
                    }
                ],
                "coverage": {
                    "candidate_pair_count": 0,
                    "unmatched_row_count": 0,
                    "mismatch_pair_count": 0,
                    "reciprocal_pair_count": 1,
                },
            }
        },
    )

    phase1 = _build_with_df(df, result)

    document_units = [unit for unit in phase1.units if unit.unit_type == "document"]
    flows = [unit for unit in phase1.units if unit.unit_type == "flow"]
    assert document_units == []
    assert len(flows) == 1
    flow = flows[0]
    assert flow.measurement_eligible is True
    assert flow.absorbed_document_ids == ["IC-A", "IC-B"]
    assert {hit.rule_id for hit in flow.absorbed_rule_hits} == {"L3-03"}
    assert {hit.rule_id for hit in flow.evidence_rows} == {"IC03", "L3-03"}


@pytest.mark.skip(
    reason="IC flow 문서흡수 검증 — IC/GR PHASE1 제거(2026-06-14). 일반 흡수 커버리지는 "
    "L2-02 flow 로 repoint 예정(후속)."
)
def test_document_hits_absorb_into_one_primary_flow_when_document_has_multiple_flows() -> None:
    df = _ic_absorption_df()
    ic_details = pd.DataFrame(
        {
            "IC03": [0.7, 0.7, 0.0],
            "L3-03": [1.0, 1.0, 0.0],
        },
        index=df.index,
    )
    ic_result = DetectionResult(
        track_name="intercompany_matcher",
        flagged_indices=[300, 301],
        scores=ic_details.max(axis=1),
        rule_flags=[
            RuleFlag("IC03", "IC reciprocal", 3, 2, len(ic_details)),
            RuleFlag("L3-03", "IC review signal", 3, 2, len(ic_details)),
        ],
        details=ic_details,
        metadata={
            "ic_pair_artifact": {
                "schema_version": 1,
                "candidate_pairs": [],
                "unmatched_rows": [],
                "mismatch_pairs": [],
                "reciprocal_pairs": [
                    {
                        "document_id": "IC-A",
                        "receivable_positions": [0],
                        "payable_positions": [1],
                        "receivable_amount": 100.0,
                        "payable_amount": 100.0,
                        "amount_symmetry": 1.0,
                    }
                ],
                "coverage": {
                    "candidate_pair_count": 0,
                    "unmatched_row_count": 0,
                    "mismatch_pair_count": 0,
                    "reciprocal_pair_count": 1,
                },
            }
        },
    )
    graph_details = pd.DataFrame({"GR01": [0.8, 0.8, 0.0]}, index=df.index)
    graph_result = DetectionResult(
        track_name="graph",
        flagged_indices=[300, 301],
        scores=graph_details["GR01"],
        rule_flags=[RuleFlag("GR01", "Circular graph", 4, 2, len(graph_details))],
        details=graph_details,
        metadata={
            "gr01_cycle_instances": [
                {
                    "cycle_id": "cycle-a",
                    "nodes": ["C001", "C002"],
                    "row_positions": [0, 1],
                    "document_ids": ["IC-A", "IC-B"],
                }
            ]
        },
    )

    phase1 = build_phase1_case_result(
        df,
        [ic_result, graph_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config=_config(),
        generated_at=datetime(2026, 6, 4, 0, 0, 0, tzinfo=UTC),
    )

    flows = [unit for unit in phase1.units if unit.unit_type == "flow"]
    absorbing_flows = [flow for flow in flows if flow.absorbed_rule_hits]
    assert len(absorbing_flows) == 1
    assert absorbing_flows[0].flow_type == "graph_circular"
    assert {hit.rule_id for hit in absorbing_flows[0].absorbed_rule_hits} == {"L3-03"}
    assert len(absorbing_flows[0].cross_ref_flow_ids) == 1
    assert sum(len(flow.absorbed_rule_hits) for flow in flows) == 2


def test_graph_details_no_longer_build_flow_unit() -> None:
    """GR(graph details)은 PHASE1-2 family 귀속 — flow unit 미생성(2026-06-21 완전 제거)."""
    details = pd.DataFrame({"GR01": [0.8, 0.8, 0.0, 0.0]}, index=_df().index)
    result = DetectionResult(
        track_name="graph",
        flagged_indices=[10, 11],
        scores=details["GR01"],
        rule_flags=[RuleFlag("GR01", "Circular graph", 4, 2, len(details))],
        details=details,
        metadata={
            "gr01_cycles_found": 1,
            "gr01_edges_built": 2,
            "gr01_edges_prefiltered": 5,
            "gr01_max_edges_raised": 1,
            "coverage_issues": [
                {
                    "rule_id": "GR01",
                    "kind": "coverage_limited",
                    "reason": "max_edges_threshold_raised",
                }
            ],
        },
    )

    flows = _flow_units(result)

    assert flows == []


def test_graph_cycle_artifact_no_longer_builds_flow() -> None:
    """GR cycle artifact 도 PHASE1-2 family 귀속 — flow unit 미생성(2026-06-21 완전 제거)."""
    details = pd.DataFrame({"GR01": [0.8, 0.8, 0.8, 0.0]}, index=_df().index)
    result = DetectionResult(
        track_name="graph",
        flagged_indices=[10, 11, 12],
        scores=details["GR01"],
        rule_flags=[RuleFlag("GR01", "Circular graph", 4, 3, len(details))],
        details=details,
        metadata={
            "gr01_cycles_found": 2,
            "gr01_edges_built": 3,
            "gr01_edges_prefiltered": 3,
            "gr01_cycle_instances": [
                {
                    "cycle_id": "cycle-a",
                    "nodes": ["C001", "C002", "C003"],
                    "row_positions": [0, 1],
                    "document_ids": ["D-A", "D-B"],
                },
                {
                    "cycle_id": "cycle-b",
                    "nodes": ["C001", "C003"],
                    "row_positions": [2],
                    "document_ids": ["D-C"],
                },
            ],
        },
    )

    flows = _flow_units(result)

    assert flows == []
