"""anomaly_flags row index 매핑이 (document_id, line_number) 기준으로 동작하는지 검증.

이전 버전은 doc_id 만으로 doc 첫 row 에 score 를 몰아넣어, 첫 라인이 아닌 위반
라인이 화면에서 첫 라인으로 잘못 강조되는 회귀가 있었다.
"""

from __future__ import annotations

import pandas as pd

from src.db.batch_reader import _resolve_flag_row_indices


def _make_ledger() -> pd.DataFrame:
    """doc_A 는 3 라인, doc_B 는 2 라인."""
    return pd.DataFrame(
        [
            {"document_id": "doc_A", "line_number": 1},
            {"document_id": "doc_A", "line_number": 2},
            {"document_id": "doc_A", "line_number": 3},
            {"document_id": "doc_B", "line_number": 1},
            {"document_id": "doc_B", "line_number": 2},
        ]
    )


def test_exact_doc_line_match_resolves_to_correct_row():
    ledger = _make_ledger()
    # doc_A line 3 위반(예: L1-02 적요 누락 라인) — 결과 row index 는 ledger 의 2 (0-based).
    flags = pd.DataFrame(
        [{"document_id": "doc_A", "line_number": 3, "rule_code": "L1-02", "score": 0.9}]
    )
    indices = _resolve_flag_row_indices(ledger, flags)
    assert indices.tolist() == [2.0]


def test_multiple_lines_in_same_document_get_distinct_indices():
    """이전 버그: 같은 doc 두 라인 위반이 모두 doc 첫 row(0)로 합쳐졌음."""
    ledger = _make_ledger()
    flags = pd.DataFrame(
        [
            {"document_id": "doc_A", "line_number": 1, "rule_code": "L1-02", "score": 0.5},
            {"document_id": "doc_A", "line_number": 3, "rule_code": "L1-02", "score": 0.9},
        ]
    )
    indices = _resolve_flag_row_indices(ledger, flags)
    assert indices.tolist() == [0.0, 2.0], (
        "doc_A 두 라인 위반은 ledger row 0 과 2 로 분리되어야 함"
    )


def test_missing_line_number_falls_back_to_first_row():
    """flag 의 line_number 가 NaN 이면 doc 첫 row 로 fallback (호환성)."""
    ledger = _make_ledger()
    flags = pd.DataFrame(
        [{"document_id": "doc_B", "line_number": None, "rule_code": "L1-01", "score": 0.7}]
    )
    indices = _resolve_flag_row_indices(ledger, flags)
    assert indices.tolist() == [3.0], "doc_B 첫 row 는 ledger index 3"


def test_unknown_document_id_returns_nan():
    """ledger 에 없는 doc_id 는 NaN — 호출부에서 dropna 한다."""
    ledger = _make_ledger()
    flags = pd.DataFrame(
        [{"document_id": "doc_GHOST", "line_number": 1, "rule_code": "L1-01", "score": 0.5}]
    )
    indices = _resolve_flag_row_indices(ledger, flags)
    assert indices.isna().all()


def test_string_line_number_is_coerced():
    """line_number 가 문자열로 저장된 옛 batch 도 정수로 강제 변환되어 매칭."""
    ledger = _make_ledger()
    flags = pd.DataFrame(
        [{"document_id": "doc_A", "line_number": "2", "rule_code": "L3-01", "score": 0.6}]
    )
    indices = _resolve_flag_row_indices(ledger, flags)
    assert indices.tolist() == [1.0]


def test_flags_without_line_number_column_falls_back_per_row():
    """flags_df 에 line_number 컬럼 자체가 없는 경우도 길이 보존하며 fallback."""
    ledger = _make_ledger()
    flags = pd.DataFrame(
        [
            {"document_id": "doc_A", "rule_code": "L1-01", "score": 0.5},
            {"document_id": "doc_B", "rule_code": "L1-08", "score": 0.7},
        ]
    )
    indices = _resolve_flag_row_indices(ledger, flags)
    # 두 row 모두 doc 첫 row index 로 fallback (doc_A=0, doc_B=3)
    assert indices.tolist() == [0.0, 3.0]
