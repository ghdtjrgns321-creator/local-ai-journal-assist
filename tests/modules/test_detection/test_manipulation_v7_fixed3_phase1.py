import json
from pathlib import Path

EVALUATION_JSON = Path("artifacts/phase1_manipulation_v7_fixed3_evaluation.json")


def _load_payload() -> dict:
    assert EVALUATION_JSON.exists(), (
        "Run tools/scripts/phase1_manipulation_v7_fixed3_evaluation.py before this test."
    )
    return json.loads(EVALUATION_JSON.read_text(encoding="utf-8"))


def test_phase1_manipulation_v7_fixed3_truth_split_and_guards() -> None:
    payload = _load_payload()
    validation = payload["validation"]

    assert validation["scenario_truth_sum"] == 620
    assert validation["queue_entered_truth_documents"] == 540
    assert validation["queue_unentered_truth_documents"] == 80
    assert validation["queue_entered_plus_unentered"] == 620
    assert validation["scenario_ranked_sum"] == 540
    assert validation["top_n_monotonic_non_decreasing"] is True
    assert validation["phase1_top_100_recall_guard_pct"] == 16.77
    assert validation["phase1_top_1000_recall_guard_pct"] == 51.13


def test_phase1_manipulation_v7_fixed3_top_n_recovery_is_document_based() -> None:
    payload = _load_payload()
    by_top = {row["top_n_cases"]: row for row in payload["top_n_recovery"]}

    assert by_top[100]["caught_truth_documents"] == 104
    assert by_top[100]["covered_unique_documents"] == 4428
    assert by_top[1_000]["caught_truth_documents"] == 317
    assert by_top[41_129]["caught_truth_documents"] == 540
    assert by_top[41_129]["doc_recall_original_pct"] == 87.1
    assert by_top[41_129]["doc_recall_queue_entered_pct"] == 100.0


def test_phase1_manipulation_v7_fixed3_scenario_matrix_matches_ts13() -> None:
    payload = _load_payload()
    rows = {
        row["manipulation_scenario"]: row for row in payload["scenario_distribution"]
    }

    assert sum(row["truth_documents"] for row in rows.values()) == 620
    assert sum(row["queue_entered_documents"] for row in rows.values()) == 540
    assert sum(row["queue_unentered_documents"] for row in rows.values()) == 80
    assert rows["embezzlement_concealment"]["queue_unentered_documents"] == 39
    assert rows["fictitious_entry"]["queue_unentered_documents"] == 32
    assert rows["period_end_adjustment_manipulation"]["queue_unentered_documents"] == 8
    assert rows["circular_related_party_transaction"]["queue_unentered_documents"] == 1
