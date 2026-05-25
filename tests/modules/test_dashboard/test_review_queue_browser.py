"""Review Queue parquet 뷰어 컴포넌트 단위 테스트.

대상: dashboard/components/review_queue_browser.py
검증 포커스:
1. parquet 파일 로드 (정상/누락)
2. KPI 영역 — truth 라벨 있을 때 메인 KPI 표시, 없을 때 보조 라인만
3. 통합 큐 표 컬럼 순서 (순위 + 통합/PHASE1/PHASE2 등급 우선)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from dashboard.components import review_queue_browser as rqb

# ── 큐 DataFrame 생성 helper ──────────────────────────────────


def _make_phase1_queue(n: int = 3) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "review_rank": list(range(1, n + 1)),
            "phase1_review_band": ["review"] * n,
            "case_id": [f"C{i}" for i in range(n)],
            "primary_topic": ["t1"] * n,
            "primary_theme": ["a"] * n,
            "phase1_composite_sort_score": [0.9 - 0.1 * i for i in range(n)],
            "phase1_priority_score": [0.8 - 0.1 * i for i in range(n)],
            "total_amount": [1000.0 - 100 * i for i in range(n)],
            "document_count": [1] * n,
            "rule_count": [2] * n,
        }
    )


def _make_integrated_queue(n: int = 3) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "review_rank": list(range(1, n + 1)),
            "rrf_rank": list(range(1, n + 1)),
            "phase12_review_band": ["review"] * n,
            "phase1_review_band": ["immediate"] * n,
            "phase2_review_band": ["candidate"] * n,
            "rank_phase1": list(range(1, n + 1)),
            "rank_phase2": list(range(1, n + 1)),
            "rrf_score": [0.03 - 0.001 * i for i in range(n)],
            "case_id": [f"C{i}" for i in range(n)],
            "primary_topic": ["t1"] * n,
            "primary_theme": ["a"] * n,
            "phase1_composite_sort_score": [0.9 - 0.1 * i for i in range(n)],
            "phase2_unsupervised_selection_score_max": [0.7 - 0.1 * i for i in range(n)],
            "total_amount": [1000.0 - 100 * i for i in range(n)],
            "document_count": [1] * n,
        }
    )


# ── load_queue ───────────────────────────────────────────────


def test_load_queue_reads_parquet(tmp_path: Path) -> None:
    df = _make_phase1_queue()
    df.to_parquet(tmp_path / "queue_phase1.parquet", index=False)
    out = rqb.load_queue(tmp_path, "phase1")
    assert out is not None
    assert out["review_rank"].tolist() == [1, 2, 3]


def test_load_queue_returns_none_if_missing(tmp_path: Path) -> None:
    assert rqb.load_queue(tmp_path, "integrated") is None


# ── load_integration_report ──────────────────────────────────


def test_load_integration_report_returns_none_for_missing(tmp_path: Path) -> None:
    assert rqb.load_integration_report(tmp_path / "missing.json") is None


def test_load_integration_report_handles_invalid_json(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert rqb.load_integration_report(bad) is None


def test_load_integration_report_reads_valid_json(tmp_path: Path) -> None:
    good = tmp_path / "ok.json"
    good.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
    out = rqb.load_integration_report(good)
    assert out == {"hello": "world"}


# ── KPI / 표시 정책 ─────────────────────────────────────────


class _StreamlitSpy:
    """st.markdown / st.caption / st.dataframe / st.info / st.warning 호출 기록."""

    def __init__(self) -> None:
        self.markdown_calls: list[dict[str, Any]] = []
        self.caption_calls: list[str] = []
        self.dataframe_calls: list[Any] = []
        self.info_calls: list[str] = []
        self.warning_calls: list[str] = []

    def markdown(self, body: str, **kwargs: Any) -> None:
        self.markdown_calls.append({"body": body, **kwargs})

    def caption(self, body: str) -> None:
        self.caption_calls.append(body)

    def dataframe(self, df: Any, **kwargs: Any) -> None:
        self.dataframe_calls.append(df)

    def info(self, msg: str) -> None:
        self.info_calls.append(msg)

    def warning(self, msg: str) -> None:
        self.warning_calls.append(msg)


@pytest.fixture
def st_spy(monkeypatch: pytest.MonkeyPatch) -> _StreamlitSpy:
    spy = _StreamlitSpy()
    for attr in ("markdown", "caption", "dataframe", "info", "warning"):
        monkeypatch.setattr(
            f"dashboard.components.review_queue_browser.st.{attr}", getattr(spy, attr)
        )
    return spy


def _make_report_with_recall(kind: str, *, top_n: int, recall: float) -> dict[str, Any]:
    return {
        "informational_truth_signal": {
            "doc_recall_by_queue": {
                kind: [
                    {
                        "top_n": top_n,
                        "matched_truth_docs": int(recall * 620),
                        "total_truth_docs": 620,
                        "recall": recall,
                    }
                ]
            }
        }
    }


def test_render_kpi_shows_main_when_truth_present(st_spy: _StreamlitSpy) -> None:
    df = _make_integrated_queue()
    report = _make_report_with_recall("integrated", top_n=500, recall=0.45)
    rqb.render_kpi(df, kind="integrated", integration_report=report, top_n_for_kpi=500)
    # 메인 KPI markdown 호출에 회수율 45.0% 가 들어가야 한다.
    main = next((c for c in st_spy.markdown_calls if "검증 라벨 매칭 전표" in c["body"]), None)
    assert main is not None
    assert "45.0%" in main["body"]
    assert "기준 전체 620건" in main["body"]
    # 보조 라인은 caption.
    assert any("검토 case" in c for c in st_spy.caption_calls)


def test_render_kpi_hides_main_when_no_truth(st_spy: _StreamlitSpy) -> None:
    df = _make_integrated_queue()
    rqb.render_kpi(df, kind="integrated", integration_report=None)
    # 메인 markdown 없음.
    main = [c for c in st_spy.markdown_calls if "검증 라벨 매칭 전표" in c["body"]]
    assert main == []
    # 보조 라인은 여전히 표시.
    assert any("검토 case" in c for c in st_spy.caption_calls)


def test_render_kpi_hides_main_when_total_zero(st_spy: _StreamlitSpy) -> None:
    df = _make_integrated_queue()
    report = {
        "informational_truth_signal": {
            "doc_recall_by_queue": {
                "integrated": [
                    {"top_n": 500, "matched_truth_docs": 0, "total_truth_docs": 0, "recall": 0.0}
                ]
            }
        }
    }
    rqb.render_kpi(df, kind="integrated", integration_report=report)
    main = [c for c in st_spy.markdown_calls if "검증 라벨 매칭 전표" in c["body"]]
    assert main == []


def test_render_kpi_does_not_expose_rrf_name(st_spy: _StreamlitSpy) -> None:
    """알고리즘 이름은 UI 본문에 노출되지 않는다."""
    df = _make_integrated_queue()
    report = _make_report_with_recall("integrated", top_n=500, recall=0.30)
    rqb.render_kpi(df, kind="integrated", integration_report=report)
    body_text = " ".join(c["body"] for c in st_spy.markdown_calls) + " ".join(st_spy.caption_calls)
    assert "RRF" not in body_text
    assert "k=60" not in body_text
    assert "Noisy" not in body_text
    assert "부정" not in body_text


# ── render_queue_browser ─────────────────────────────────────


def test_render_queue_browser_warns_if_file_missing(tmp_path: Path, st_spy: _StreamlitSpy) -> None:
    rqb.render_queue_browser(tmp_path, kind="integrated", integration_report=None)
    assert any("queue_integrated.parquet" in w for w in st_spy.warning_calls)
    assert st_spy.dataframe_calls == []


def test_render_queue_browser_info_when_no_queue_dir(st_spy: _StreamlitSpy) -> None:
    # Why: source 인자가 None 이면 사용자 친화 안내 표시.
    rqb.render_queue_browser(None, kind="integrated", integration_report=None)
    assert any("Phase 2 추론 결과" in m for m in st_spy.info_calls)


def test_render_queue_browser_displays_dataframe(tmp_path: Path, st_spy: _StreamlitSpy) -> None:
    _make_integrated_queue().to_parquet(tmp_path / "queue_integrated.parquet", index=False)
    rqb.render_queue_browser(tmp_path, kind="integrated", integration_report=None)
    assert len(st_spy.dataframe_calls) == 1
    displayed = st_spy.dataframe_calls[0]
    # 통합 탭 컬럼 순서: 순위와 3개 검토 등급을 먼저 표시.
    expected = [
        "순위",
        "통합 등급",
        "PHASE1 등급",
        "PHASE2 등급",
        "주요 관점",
        "세부 관점",
        "합계 금액",
        "전표 수",
    ]
    assert list(displayed.columns) == expected
    assert displayed.loc[0, "통합 등급"] == "즉시검토"
    assert displayed.loc[0, "PHASE1 등급"] == "즉시검토"
    assert displayed.loc[0, "PHASE2 등급"] == "즉시검토"


def test_render_queue_browser_phase1_columns(tmp_path: Path, st_spy: _StreamlitSpy) -> None:
    _make_phase1_queue().to_parquet(tmp_path / "queue_phase1.parquet", index=False)
    rqb.render_queue_browser(tmp_path, kind="phase1", integration_report=None)
    assert len(st_spy.dataframe_calls) == 1
    displayed = st_spy.dataframe_calls[0]
    assert "순위" in displayed.columns
    assert "PHASE1 등급" in displayed.columns
    assert "phase1_composite_sort_score" not in displayed.columns
    assert displayed.loc[0, "PHASE1 등급"] == "검토대상"


def test_format_df_uses_rank_percentile_bands_for_phase2() -> None:
    df = pd.DataFrame(
        {
            "phase2_review_rank": [1, 2, 3, 4, 5],
            "phase2_review_band": ["candidate"] * 5,
            "primary_topic": ["t"] * 5,
            "primary_theme": ["a"] * 5,
            "total_amount": [1.0] * 5,
            "document_count": [1] * 5,
        }
    )
    displayed = rqb._format_df_for_display(df, "phase2")
    assert displayed.loc[0, "PHASE2 등급"] == "즉시검토"
    assert displayed.loc[1, "PHASE2 등급"] == "참고후보"
