"""Stage 7 (PHASE1↔PHASE2 통합) 3큐 빌더 회귀 테스트.

단위(synthetic base_df) + 통합(V7 fixed3 캐시) 두 계층.

회귀 metric 정책: feedback_phase1_truth_recall_guard 준수 — truth recall 은
informational only 이며 PHASE1/PHASE2 변경의 정당화 사유로 사용하지 않는다.
본 테스트의 recall 값은 코드 회귀(implementation regression) 감지에만 쓴다.
"""

from __future__ import annotations

import importlib.util
import pickle
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "tools" / "scripts" / "phase1_phase2_integration_stage7.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("stage7_integration", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def stage7() -> Any:
    return _load_module()


# ── 합성 base_df ────────────────────────────────────────────


def _make_base_df() -> pd.DataFrame:
    """5 case 합성 base_df. doc_ids_joined / truth_match 컬럼 포함."""
    return pd.DataFrame(
        {
            "case_id": ["C1", "C2", "C3", "C4", "C5"],
            "phase1_composite_sort_score": [0.9, 0.7, 0.5, 0.3, 0.1],
            "phase1_triage_rank_score": [0.9, 0.8, 0.6, 0.4, 0.2],
            "phase2_unsupervised_selection_score_max": [0.1, 0.4, 0.95, np.nan, 0.7],
            "phase2_unsupervised_score_max": [0.1, 0.4, 0.95, np.nan, 0.7],
            "phase2_timeseries_score_max": [0.5, 0.1, 0.2, 0.4, 0.3],
            "phase2_relational_score_max": [0.0, 0.8, 0.0, 0.0, 0.2],
            "phase2_duplicate_score_max": [0.6, 0.0, 0.1, 0.3, 0.0],
            "phase2_intercompany_score_max": [np.nan, np.nan, np.nan, np.nan, np.nan],
            "total_amount": [1000.0, 800.0, 700.0, 600.0, 500.0],
            "rule_count": [3, 2, 2, 1, 1],
            "document_count": [1, 1, 1, 1, 1],
            "primary_topic": ["t1", "t2", "t1", "t3", "t2"],
            "primary_theme": ["a", "b", "a", "c", "b"],
            "document_ids_joined": ["d1", "d2;d3", "d4", "d5", "d6"],
            "case_contains_truth_doc": [True, False, True, False, True],
        }
    )


# ── PHASE1 단독 큐 (V1 lock 회귀) ──────────────────────────────


def test_build_phase1_queue_sort_order(stage7: Any) -> None:
    df = stage7.build_phase1_queue(_make_base_df())
    # composite_sort_score 내림차순으로 정렬되어야 한다.
    assert df["case_id"].tolist() == ["C1", "C2", "C3", "C4", "C5"]
    assert df["review_rank"].tolist() == [1, 2, 3, 4, 5]


def test_build_phase1_queue_v1_lock_keys_only(stage7: Any) -> None:
    """PHASE1 단독 큐는 phase2 컬럼이 정렬에 영향을 주지 않는다."""
    base = _make_base_df()
    # PHASE2 score 순서를 임의로 뒤집어도 정렬 결과 동일.
    base_shuffled = base.copy()
    base_shuffled["phase2_unsupervised_selection_score_max"] = (
        base_shuffled["phase2_unsupervised_selection_score_max"].iloc[::-1].to_numpy()
    )
    out_a = stage7.build_phase1_queue(base)
    out_b = stage7.build_phase1_queue(base_shuffled)
    assert out_a["case_id"].tolist() == out_b["case_id"].tolist()


# ── PHASE2 단독 큐 ───────────────────────────────────────────


def test_build_phase2_queue_sort_order(stage7: Any) -> None:
    df = stage7.build_phase2_queue(_make_base_df())
    # PHASE2 5-family Noisy-OR score 내림차순.
    assert df["case_id"].tolist() == ["C1", "C2", "C3", "C5", "C4"]
    assert df["phase2_review_rank"].tolist() == [1, 2, 3, 4, 5]
    assert "phase2_internal_noisy_or_score" in df.columns
    assert df.loc[0, "phase2_review_band"] == "immediate"


# ── 통합 큐 (RRF k=60) ───────────────────────────────────────


def test_build_integrated_queue_has_rrf_columns(stage7: Any) -> None:
    """Noisy-OR voter 채택 (2026-05-19, TS-15) — 2-way RRF columns 만 노출.

    이전 5-way hierarchical RRF (V7 fixed3 -6.45pp reject) 의 family 별 rank
    컬럼은 더 이상 노출되지 않는다. 5 family ECDF 는 Noisy-OR 로 미리 결합되어
    `phase2_internal_noisy_or` 단일 voter 로 들어간다.
    """
    df = stage7.build_integrated_queue(_make_base_df())
    for col in (
        "rank_phase1_composite",
        "rank_phase2_internal_noisy_or",
        "phase2_internal_noisy_or_score",
        "rrf_score",
        "rrf_rank",
        "review_rank",
        "phase12_review_band",
    ):
        assert col in df.columns
    # 이전 5-way rank 컬럼은 제거됨
    for legacy_col in (
        "rank_phase2_unsupervised",
        "rank_phase2_timeseries",
        "rank_phase2_relational",
        "rank_phase2_duplicate",
        "rank_phase2_intercompany",
    ):
        assert legacy_col not in df.columns, (
            f"legacy 5-way RRF column {legacy_col} should be removed after Noisy-OR voter adoption"
        )


def test_build_integrated_queue_rrf_default_k_60(stage7: Any) -> None:
    """default k 가 60 인지 (TS-12 §6.1 결정)."""
    assert stage7.RRF_K == 60


def test_build_integrated_queue_uses_both_signals(stage7: Any) -> None:
    """통합 큐 는 PHASE1 단독 정렬과 달라야 한다.

    Noisy-OR voter 채택 (TS-15, 2026-05-19) 후 PHASE2 5-family score 가
    실제로 통합 큐 순위에 반영되어야 한다. PHASE1 단독 순위와 통합 순위가
    동일하면 PHASE2 voter 가 0 영향이라는 뜻이므로 회귀 실패.
    """
    base = _make_base_df()
    base["phase1_composite_sort_score"] = [0.5] * len(base)
    p1 = stage7.build_phase1_queue(base)["case_id"].tolist()
    integ = stage7.build_integrated_queue(base)["case_id"].tolist()
    assert p1 != integ, (
        f"통합 큐가 PHASE1 단독과 동일 — PHASE2 Noisy-OR voter 가 ranking 에 영향 없음. "
        f"phase1={p1} integrated={integ}"
    )
    assert integ[:3] == ["C1", "C2", "C3"]


# ── measure_doc_recall ───────────────────────────────────────


def test_measure_doc_recall_basic(stage7: Any) -> None:
    df = stage7.build_phase1_queue(_make_base_df())
    truth = {"d1", "d4"}
    res = stage7.measure_doc_recall(df, truth, top_n=2)
    # TOP 2 = C1(d1) + C2(d2;d3). truth 교집합 = {d1} = 1.
    assert res["matched_truth_docs"] == 1
    assert res["total_truth_docs"] == 2
    assert res["recall"] == pytest.approx(0.5)


def test_measure_doc_recall_full(stage7: Any) -> None:
    df = stage7.build_phase1_queue(_make_base_df())
    truth = {"d1", "d2", "d4", "d6"}
    res = stage7.measure_doc_recall(df, truth, top_n=5)
    # 전체에서 d1/d2/d4/d6 모두 등장 → recall 1.0
    assert res["recall"] == pytest.approx(1.0)


# ── 통합 (V7 fixed3 캐시 기반 회귀) ────────────────────────────


PHASE1_CACHE = ROOT / "artifacts" / "stage7_phase1_case_result.pkl"
PHASE2_CACHE = ROOT / "artifacts" / "stage7_phase2_by_doc.parquet"
TRUTH_PATH = (
    ROOT
    / "data"
    / "journal"
    / "primary"
    / "datasynth_manipulation_v7_candidate_fixed3"
    / "labels"
    / "manipulated_entry_truth.csv"
)
LEGACY_QUEUE = (
    ROOT
    / "data"
    / "companies"
    / "_ci_baseline"
    / "engagements"
    / "2026"
    / "review_queue"
    / "v1"
    / "queue.parquet"
)

_INT_REQUIRED = [PHASE1_CACHE, PHASE2_CACHE, TRUTH_PATH]


def _has_integration_fixtures() -> bool:
    return all(p.exists() for p in _INT_REQUIRED)


pytestmark_integration = pytest.mark.skipif(
    not _has_integration_fixtures(),
    reason="V7 fixed3 캐시 미존재 — 통합 회귀 테스트 스킵",
)


@pytest.fixture(scope="module")
def integration_base_df(stage7: Any) -> pd.DataFrame:
    if not _has_integration_fixtures():
        pytest.skip("V7 fixed3 캐시 미존재")
    with PHASE1_CACHE.open("rb") as fh:
        phase1_result = pickle.load(fh)
    phase2_by_doc = pd.read_parquet(PHASE2_CACHE)
    truth = pd.read_csv(TRUTH_PATH)
    truth_docs = set(truth["document_id"].astype(str))
    # overlays 는 정렬에 영향 없으므로 빈 리스트로 충분.
    return stage7._build_base_rows(phase1_result, phase2_by_doc, [], truth_docs)


@pytest.fixture(scope="module")
def integration_truth_docs() -> set[str]:
    if not _has_integration_fixtures():
        pytest.skip("V7 fixed3 캐시 미존재")
    truth = pd.read_csv(TRUTH_PATH)
    return set(truth["document_id"].astype(str))


@pytestmark_integration
def test_integration_phase1_row_count(stage7: Any, integration_base_df: pd.DataFrame) -> None:
    df = stage7.build_phase1_queue(integration_base_df)
    assert len(df) == 41129


@pytestmark_integration
def test_integration_phase2_row_count(stage7: Any, integration_base_df: pd.DataFrame) -> None:
    df = stage7.build_phase2_queue(integration_base_df)
    assert len(df) == 41129


@pytestmark_integration
def test_integration_integrated_row_count(stage7: Any, integration_base_df: pd.DataFrame) -> None:
    df = stage7.build_integrated_queue(integration_base_df)
    assert len(df) == 41129


@pytestmark_integration
def test_integration_phase1_queue_matches_legacy_v1_lock(
    stage7: Any, integration_base_df: pd.DataFrame
) -> None:
    """queue_phase1 의 정렬이 legacy queue.parquet 와 정확 일치 (V1 lock 회귀)."""
    if not LEGACY_QUEUE.exists():
        pytest.skip("legacy queue.parquet 미존재")
    new_phase1 = stage7.build_phase1_queue(integration_base_df)
    legacy = pd.read_parquet(LEGACY_QUEUE)
    # case_id 순서 동일해야 한다.
    assert new_phase1["case_id"].tolist() == legacy["case_id"].tolist()


@pytestmark_integration
def test_integration_doc_recall_integrated_top1000(
    stage7: Any,
    integration_base_df: pd.DataFrame,
    integration_truth_docs: set[str],
) -> None:
    """Noisy-OR separated 채택 (TS-15) 후 V7 fixed3 production run baseline.

    informational only — feedback_phase1_truth_recall_guard 준수.
    """
    df = stage7.build_integrated_queue(integration_base_df)
    res = stage7.measure_doc_recall(df, integration_truth_docs, top_n=1000)
    assert res["recall"] == pytest.approx(0.5226, abs=0.005)


@pytestmark_integration
def test_integration_doc_recall_integrated_top100(
    stage7: Any,
    integration_base_df: pd.DataFrame,
    integration_truth_docs: set[str],
) -> None:
    """Noisy-OR separated 채택 (TS-15) 후 V7 fixed3 fixture baseline.

    Zero-preserving ECDF semantics 에서는 local V7 fixture 의 TOP 100 recall 이
    legacy PHASE1+VAE 2-way 와 동률이다. truth recall 은 informational only.
    """
    df = stage7.build_integrated_queue(integration_base_df)
    res = stage7.measure_doc_recall(df, integration_truth_docs, top_n=100)
    assert res["recall"] == pytest.approx(0.1661, abs=0.005)


@pytestmark_integration
def test_integration_doc_recall_integrated_top500(
    stage7: Any,
    integration_base_df: pd.DataFrame,
    integration_truth_docs: set[str],
) -> None:
    """Noisy-OR separated TOP 500 recall baseline."""
    df = stage7.build_integrated_queue(integration_base_df)
    res = stage7.measure_doc_recall(df, integration_truth_docs, top_n=500)
    assert res["recall"] == pytest.approx(0.4323, abs=0.005)


@pytestmark_integration
def test_integration_doc_recall_integrated_top2000(
    stage7: Any,
    integration_base_df: pd.DataFrame,
    integration_truth_docs: set[str],
) -> None:
    """Noisy-OR separated TOP 2000 recall baseline."""
    df = stage7.build_integrated_queue(integration_base_df)
    res = stage7.measure_doc_recall(df, integration_truth_docs, top_n=2000)
    assert res["recall"] == pytest.approx(0.6306, abs=0.005)


@pytestmark_integration
def test_integration_doc_recall_phase2_top1000(
    stage7: Any,
    integration_base_df: pd.DataFrame,
    integration_truth_docs: set[str],
) -> None:
    df = stage7.build_phase2_queue(integration_base_df)
    res = stage7.measure_doc_recall(df, integration_truth_docs, top_n=1000)
    assert res["recall"] == pytest.approx(0.3887, abs=0.005)
