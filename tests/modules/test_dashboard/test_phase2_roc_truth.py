"""VAE ROC 정답 라벨 해소 — hidden 정책으로 라벨이 제거된 상태에서도 평가가 되는지.

Why: 파이프라인이 datasynth_label_mode="hidden" 으로 is_fraud 를 제거해, fraud 데이터셋을
     넣어도 ROC 가 "부정 라벨 없음"으로 떨어졌다(2026-07-25). DB general_ledger 는 컬럼이
     스키마에 늘 있고 값만 NULL 이라 "컬럼 존재 = 라벨 있음"으로 판정하면 이 사고가 재발한다.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pytest

from dashboard.components.phase2_roc_truth import resolve_roc_truth


@dataclass
class _PR:
    data: pd.DataFrame | None = None
    featured_data: pd.DataFrame | None = None
    file_name: str = ""


def _ledger(labels) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "document_id": ["D1", "D1", "D2", "D3"],
            "gl_account": ["1000", "2000", "1000", "3000"],
            "is_fraud": labels,
        }
    )


def test_inline_labels_are_used_when_present():
    truth, note = resolve_roc_truth(_PR(data=_ledger([True, False, False, False])))
    assert truth is not None
    assert bool(truth.loc["D1"]) and not bool(truth.loc["D2"])
    assert "분석 데이터" in note


def test_all_null_label_column_is_not_treated_as_labels(tmp_path):
    """DB 로드본(컬럼 존재·전부 NULL)을 '라벨 있음'으로 착각하지 않는다 — 사고 재발 방지."""
    pr = _PR(data=_ledger([pd.NA] * 4))
    truth, note = resolve_roc_truth(pr)
    assert truth is None
    assert "원본" in note


def test_falls_back_to_source_csv_labels(tmp_path):
    """라벨이 제거된 데이터라도 원본 CSV 경로가 있으면 전표 단위 정답을 복원한다."""
    src = tmp_path / "journal_entries_2022.csv"
    pd.DataFrame(
        {
            "document_id": ["D1", "D1", "D2", "D3"],
            "amount": [1, 2, 3, 4],
            "is_fraud": [True, True, False, False],
        }
    ).to_csv(src, index=False)

    body = _ledger([pd.NA] * 4).drop(columns=["is_fraud"])
    truth, note = resolve_roc_truth(_PR(data=body, file_name=str(src)))

    assert truth is not None
    assert bool(truth.loc["D1"]) is True
    assert bool(truth.loc["D2"]) is False
    assert "평가 전용" in note


def test_no_label_and_no_source_returns_reason():
    body = _ledger([pd.NA] * 4).drop(columns=["is_fraud"])
    truth, note = resolve_roc_truth(_PR(data=body, file_name="does_not_exist_2099.csv"))
    assert truth is None
    assert "hidden" in note


def test_source_csv_without_labels_reports_missing_label():
    pytest.importorskip("streamlit")
    truth, note = resolve_roc_truth(_PR(data=None, file_name=""))
    assert truth is None
    assert "ROC를 그릴 수 없습니다" in note
