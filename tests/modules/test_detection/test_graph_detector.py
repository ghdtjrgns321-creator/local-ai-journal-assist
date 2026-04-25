"""GraphDetector 단위 테스트 — WU-22.

15개 테스트: Basic(3) + GR01 순환(6) + GR03 이전가격(2) + OOM 방어(3) + Edge(1)

핵심 검증:
- networkx 기반 N-hop 순환 탐지 (GR01)
- 양방향 IC 엣지 가격 asymmetry (GR03)
- OOM Trap 방어: pre-filter + from_pandas_edgelist 강제 + max_edges 안전장치
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from config.settings import get_settings
from src.detection.base import DetectionResult
from src.detection.graph_detector import GraphDetector


# ── 공용 헬퍼 ──────────────────────────────────────────────────


def _make_df(rows: list[dict]) -> pd.DataFrame:
    """테스트용 DataFrame 생성 — 필수 컬럼 기본값 주입."""
    df = pd.DataFrame(rows)
    if "posting_date" in df.columns:
        df["posting_date"] = pd.to_datetime(df["posting_date"])
    defaults = {
        "debit_amount": 0.0,
        "credit_amount": 0.0,
        "is_intercompany": False,
        "trading_partner": None,
        "company_code": "C001",
        "gl_account": "1000",
        "document_id": None,
    }
    for col, default in defaults.items():
        if col not in df.columns:
            df[col] = default
    return df


def _settings_override(**overrides):
    """get_settings() 복제 후 필드 덮어쓰기."""
    base = get_settings().model_copy(update=overrides)
    return base


def _cycle_df_3hop() -> pd.DataFrame:
    """A→B→C→A 3-hop 순환 전표 (금액 > min_amount 기본 1천만원)."""
    return _make_df([
        # A(C001) → B(C002): 2천만원 차변 C001 계정 / 대변 trading_partner=C002
        {"document_id": "D001", "company_code": "C001", "trading_partner": "C002",
         "gl_account": "4500", "credit_amount": 20_000_000,
         "is_intercompany": True, "posting_date": "2024-03-01"},
        # B(C002) → C(C003)
        {"document_id": "D002", "company_code": "C002", "trading_partner": "C003",
         "gl_account": "4500", "credit_amount": 20_000_000,
         "is_intercompany": True, "posting_date": "2024-03-05"},
        # C(C003) → A(C001): 순환 완성
        {"document_id": "D003", "company_code": "C003", "trading_partner": "C001",
         "gl_account": "4500", "credit_amount": 20_000_000,
         "is_intercompany": True, "posting_date": "2024-03-10"},
        # 노이즈: 순환에 참여하지 않는 독립 거래
        {"document_id": "D099", "company_code": "C001", "trading_partner": "VENDOR_X",
         "gl_account": "5100", "debit_amount": 15_000_000,
         "is_intercompany": False, "posting_date": "2024-03-15"},
    ])


def _cycle_df_2hop() -> pd.DataFrame:
    """A↔B 2-hop 양방향 순환."""
    return _make_df([
        {"document_id": "D101", "company_code": "C001", "trading_partner": "C002",
         "gl_account": "4500", "credit_amount": 30_000_000,
         "is_intercompany": True, "posting_date": "2024-03-01"},
        {"document_id": "D102", "company_code": "C002", "trading_partner": "C001",
         "gl_account": "4500", "credit_amount": 30_000_000,
         "is_intercompany": True, "posting_date": "2024-03-05"},
    ])


# ── Basic (3개) ────────────────────────────────────────────────


class TestBasic:
    """기본 인터페이스 검증."""

    def test_track_name(self):
        """#1: track_name은 'graph'."""
        assert GraphDetector().track_name == "graph"

    def test_returns_detection_result(self):
        """#2: detect() 반환 타입은 DetectionResult."""
        result = GraphDetector().detect(_cycle_df_3hop())
        assert isinstance(result, DetectionResult)
        assert result.track_name == "graph"

    def test_scores_range(self):
        """#3: 모든 scores 0.0~1.0 범위."""
        result = GraphDetector().detect(_cycle_df_3hop())
        assert result.scores.between(0.0, 1.0).all()


# ── GR01: 순환거래 탐지 (6개) ─────────────────────────────────


class TestGR01Circular:
    """GR01 — DFS/Johnson N-hop 순환 탐지."""

    def test_detects_3hop_cycle(self):
        """#4: A→B→C→A 3-hop 순환 탐지 → 순환 참여 3행 모두 flag."""
        df = _cycle_df_3hop()
        result = GraphDetector().detect(df)
        # 순환 참여 3행(D001, D002, D003)은 flagged, 독립 거래(D099)는 미flagged
        cycle_idx = df[df["document_id"].isin(["D001", "D002", "D003"])].index
        noise_idx = df[df["document_id"] == "D099"].index
        assert (result.scores.loc[cycle_idx] > 0).all(), "순환 참여 행이 flag되지 않음"
        assert (result.scores.loc[noise_idx] == 0).all(), "독립 거래가 오flag됨"

    def test_detects_2hop_cycle(self):
        """#5: A↔B 2-hop 양방향 순환 탐지."""
        df = _cycle_df_2hop()
        result = GraphDetector().detect(df)
        assert (result.scores > 0).all(), "2-hop 순환 양측 모두 flag되어야 함"

    def test_respects_max_cycle_length(self):
        """#6: max_cycle_length=2로 제한하면 3-hop 순환은 탐지 안 됨."""
        df = _cycle_df_3hop()
        settings = _settings_override(graph_gr01_max_cycle_length=2)
        result = GraphDetector(settings).detect(df)
        # 3-hop cycle은 length_bound=2를 초과 → GR01 미flag
        gr01_details = result.details.get("GR01")
        if gr01_details is not None:
            assert (gr01_details == 0).all(), "length_bound 초과 cycle이 flag됨"

    def test_no_cycle_returns_zero_scores(self):
        """#7: 순환 없는 DataFrame → scores 전부 0."""
        df = _make_df([
            {"document_id": f"D{i}", "company_code": "C001",
             "trading_partner": f"V{i}", "gl_account": "5100",
             "debit_amount": 20_000_000, "is_intercompany": False,
             "posting_date": "2024-03-01"}
            for i in range(5)
        ])
        result = GraphDetector().detect(df)
        assert (result.scores == 0).all(), "순환 없는데 flag됨"

    def test_prefilter_excludes_below_min_amount(self):
        """#8: min_amount 미만 행은 사전 필터링됨 → 작은 cycle 미탐."""
        df = _make_df([
            # 모든 금액이 min_amount(1천만원) 미만
            {"document_id": "D001", "company_code": "C001", "trading_partner": "C002",
             "gl_account": "4500", "credit_amount": 100_000,
             "is_intercompany": True, "posting_date": "2024-03-01"},
            {"document_id": "D002", "company_code": "C002", "trading_partner": "C001",
             "gl_account": "4500", "credit_amount": 100_000,
             "is_intercompany": True, "posting_date": "2024-03-05"},
        ])
        result = GraphDetector().detect(df)
        # 사전 필터로 엣지 0개 → cycle 탐지 불가
        assert (result.scores == 0).all()
        assert result.metadata.get("gr01_edges_built", 0) == 0

    def test_implicit_edge_from_document_id_fallback(self):
        """#9: trading_partner NULL이지만 동일 document_id로 partner 복구."""
        df = _make_df([
            # 동일 document_id의 차/대 양측 — trading_partner NULL
            {"document_id": "DOC_A", "company_code": "C001", "trading_partner": None,
             "gl_account": "4500", "credit_amount": 20_000_000,
             "is_intercompany": True, "posting_date": "2024-03-01"},
            {"document_id": "DOC_A", "company_code": "C002", "trading_partner": None,
             "gl_account": "4500", "debit_amount": 20_000_000,
             "is_intercompany": True, "posting_date": "2024-03-01"},
            # 반대 방향 문서로 cycle 완성
            {"document_id": "DOC_B", "company_code": "C002", "trading_partner": None,
             "gl_account": "4500", "credit_amount": 20_000_000,
             "is_intercompany": True, "posting_date": "2024-03-02"},
            {"document_id": "DOC_B", "company_code": "C001", "trading_partner": None,
             "gl_account": "4500", "debit_amount": 20_000_000,
             "is_intercompany": True, "posting_date": "2024-03-02"},
        ])
        result = GraphDetector().detect(df)
        # implicit edge 복구 메트릭 > 0
        assert result.metadata.get("gr01_implicit_edges", 0) > 0, (
            "implicit edge 복구 실패"
        )


# ── GR03: 양방향 이전가격 이상 (2개) ─────────────────────────


class TestGR03TransferPricing:
    """GR03 — 양방향 IC 엣지 price asymmetry."""

    def test_bidirectional_price_asymmetry_flagged(self):
        """#10: A→B 평균 1천만원, B→A 평균 5천만원 → asymmetry flag."""
        df = _make_df([
            # A→B 방향: 평균 1천만원 (3건)
            {"document_id": f"D_AB{i}", "company_code": "C001", "trading_partner": "C002",
             "gl_account": "4500", "credit_amount": 10_000_000,
             "is_intercompany": True, "posting_date": "2024-03-01"}
            for i in range(3)
        ] + [
            # B→A 방향: 평균 5천만원 (3건) — 5배 차이
            {"document_id": f"D_BA{i}", "company_code": "C002", "trading_partner": "C001",
             "gl_account": "4500", "credit_amount": 50_000_000,
             "is_intercompany": True, "posting_date": "2024-03-05"}
            for i in range(3)
        ])
        result = GraphDetector().detect(df)
        gr03 = result.details.get("GR03")
        assert gr03 is not None
        assert (gr03 > 0).any(), "양방향 가격 편차가 flag되지 않음"

    def test_no_bidirectional_no_flag(self):
        """#11: 단방향만 존재 → GR03 미flag."""
        df = _make_df([
            {"document_id": f"D_AB{i}", "company_code": "C001", "trading_partner": "C002",
             "gl_account": "4500", "credit_amount": 10_000_000 * (i + 1),
             "is_intercompany": True, "posting_date": "2024-03-01"}
            for i in range(3)
        ])
        result = GraphDetector().detect(df)
        gr03 = result.details.get("GR03")
        if gr03 is not None:
            assert (gr03 == 0).all(), "단방향인데 GR03 flag됨"


# ── OOM 방어 검증 (3개) ───────────────────────────────────────


    def test_reference_pair_asymmetry_with_different_ic_gl_flagged(self):
        df = _make_df([
            {"document_id": "D_A", "company_code": "C001", "trading_partner": "C002",
             "reference": "IC-REF-1", "gl_account": "1150", "debit_amount": 13_600_000,
             "is_intercompany": True, "posting_date": "2024-03-01"},
            {"document_id": "D_A", "company_code": "C001", "trading_partner": "C002",
             "reference": "IC-REF-1", "gl_account": "4900", "credit_amount": 15_100_000,
             "is_intercompany": False, "posting_date": "2024-03-01"},
            {"document_id": "D_A", "company_code": "C001", "trading_partner": None,
             "reference": "IC-REF-1", "gl_account": "2100", "debit_amount": 1_500_000,
             "is_intercompany": False, "posting_date": "2024-03-01"},
            {"document_id": "D_B", "company_code": "C002", "trading_partner": "C001",
             "reference": "IC-REF-1", "gl_account": "2050", "credit_amount": 11_400_000,
             "is_intercompany": True, "posting_date": "2024-03-01"},
            {"document_id": "D_B", "company_code": "C002", "trading_partner": "C001",
             "reference": "IC-REF-1", "gl_account": "6300", "debit_amount": 11_400_000,
             "is_intercompany": False, "posting_date": "2024-03-01"},
        ])
        result = GraphDetector().detect(df)
        gr03 = result.details.get("GR03")
        assert gr03 is not None
        assert (gr03.loc[df["document_id"].isin(["D_A", "D_B"])] > 0).any()


class TestOOMDefense:
    """OOM Trap 방어 3중 장치 검증."""

    def test_uses_from_pandas_edgelist_not_loop(self, monkeypatch):
        """#12: 그래프 구축 시 nx.from_pandas_edgelist 사용 + 소스에 금지 패턴 없음.

        검증 전략:
        1. 런타임: monkeypatch로 from_pandas_edgelist 호출 ≥ 1회 확인
        2. 정적: graph_rules.py 소스에 iterrows/apply/직접 add_edge 루프 부재 확인
        """
        import inspect

        import networkx as nx
        from src.detection import graph_rules

        from_pandas_calls = {"count": 0}
        orig_from_pandas = nx.from_pandas_edgelist

        def counting_from_pandas(*args, **kwargs):
            from_pandas_calls["count"] += 1
            return orig_from_pandas(*args, **kwargs)

        monkeypatch.setattr(graph_rules.nx, "from_pandas_edgelist", counting_from_pandas)
        GraphDetector().detect(_cycle_df_3hop())
        assert from_pandas_calls["count"] >= 1, (
            "nx.from_pandas_edgelist가 호출되지 않음 — 벡터화 위반"
        )

        # 정적 검증: 소스에 금지 패턴 부재 (주석 제외)
        import re
        source = inspect.getsource(graph_rules)
        # 한 줄 주석(# ...) 과 docstring 제거
        code_lines = []
        in_docstring = False
        for line in source.splitlines():
            stripped = line.lstrip()
            if stripped.startswith('"""') or stripped.startswith("'''"):
                in_docstring = not in_docstring
                continue
            if in_docstring or stripped.startswith("#"):
                continue
            # 라인 끝 주석 제거
            code_only = re.sub(r"#.*$", "", line)
            code_lines.append(code_only)
        code = "\n".join(code_lines)
        assert ".iterrows(" not in code, "iterrows 직접 호출 금지"
        assert ".add_edge(" not in code, "add_edge 직접 호출 금지 (from_pandas_edgelist 사용)"

    def test_auto_raises_min_amount_when_edges_exceed_safeguard(self):
        """#13: max_edges 초과 시 min_amount 자동 상향 + warning."""
        # 1000행을 min_amount 이상 금액으로 생성, max_edges=50으로 제한
        df = _make_df([
            {"document_id": f"D{i}", "company_code": f"C{i % 10:03d}",
             "trading_partner": f"C{(i + 1) % 10:03d}", "gl_account": "4500",
             "credit_amount": 10_000_000 + i,  # 순차 증가
             "is_intercompany": True, "posting_date": "2024-03-01"}
            for i in range(1000)
        ])
        settings = _settings_override(graph_gr01_max_edges=50)
        result = GraphDetector(settings).detect(df)
        assert result.metadata.get("gr01_edges_built", 0) <= 50, (
            "max_edges 안전장치 작동 실패"
        )
        assert any("엣지 수" in w or "edges" in w.lower() for w in result.warnings), (
            "엣지 수 초과 warning 미발생"
        )

    def test_sparse_large_component_not_skipped_by_node_count_only(self):
        """Large sparse components are processed unless both caps are exceeded."""
        rows = [
            {"document_id": "D_AB", "company_code": "A", "trading_partner": "B",
             "gl_account": "4500", "credit_amount": 20_000_000,
             "is_intercompany": True, "posting_date": "2024-03-01"},
            {"document_id": "D_BA", "company_code": "B", "trading_partner": "A",
             "gl_account": "4500", "credit_amount": 20_000_000,
             "is_intercompany": True, "posting_date": "2024-03-02"},
        ]
        rows.extend(
            {
                "document_id": f"D_CHAIN_{i}",
                "company_code": f"N{i}",
                "trading_partner": f"N{i + 1}",
                "gl_account": "4500",
                "credit_amount": 20_000_000,
                "is_intercompany": True,
                "posting_date": "2024-03-03",
            }
            for i in range(20)
        )
        rows.append({
            "document_id": "D_CONNECT",
            "company_code": "B",
            "trading_partner": "N0",
            "gl_account": "4500",
            "credit_amount": 20_000_000,
            "is_intercompany": True,
            "posting_date": "2024-03-03",
        })
        df = _make_df(rows)
        settings = _settings_override(
            graph_gr01_max_component_size=5,
            graph_gr01_max_component_edges=100,
        )
        result = GraphDetector(settings).detect(df)
        assert result.metadata.get("gr01_skipped_components", 0) == 0
        assert result.details["GR01"].loc[[0, 1]].gt(0).all()

    def test_dense_large_component_still_skipped(self):
        """Components that exceed both node and edge caps are still skipped."""
        df = _make_df([
            {"document_id": f"D{i}", "company_code": f"C{i % 8}",
             "trading_partner": f"C{(i + 1) % 8}", "gl_account": "4500",
             "credit_amount": 20_000_000, "is_intercompany": True,
             "posting_date": "2024-03-01"}
            for i in range(40)
        ])
        settings = _settings_override(
            graph_gr01_max_component_size=5,
            graph_gr01_max_component_edges=10,
        )
        result = GraphDetector(settings).detect(df)
        assert result.metadata.get("gr01_skipped_components", 0) == 1
        assert result.scores.sum() == 0.0

    @pytest.mark.slow
    def test_large_dataset_memory_bounded(self):
        """#14: 100k 행 DataFrame에서 실행 시간 < 15초 + 엣지 수 상한 이하."""
        import time

        rng = np.random.default_rng(42)
        n = 100_000
        df = _make_df([
            {
                "document_id": f"D{i}",
                "company_code": f"C{rng.integers(0, 10):03d}",
                "trading_partner": f"V{rng.integers(0, 50):03d}",
                "gl_account": "4500",
                "credit_amount": float(rng.integers(1_000, 20_000_000)),
                "is_intercompany": bool(rng.integers(0, 2)),
                "posting_date": "2024-03-01",
            }
            for i in range(n)
        ])
        start = time.perf_counter()
        result = GraphDetector().detect(df)
        elapsed = time.perf_counter() - start
        assert elapsed < 15.0, f"실행 시간 초과: {elapsed:.2f}s"
        assert result.metadata.get("gr01_edges_built", 0) <= 50_000


# ── Edge Cases (1개) ──────────────────────────────────────────


class TestEdgeCases:
    def test_empty_dataframe_raises(self):
        """#15: 빈 DataFrame → ValueError (BaseDetector 규약)."""
        df = pd.DataFrame(columns=["company_code", "trading_partner"])
        with pytest.raises(ValueError):
            GraphDetector().detect(df)

    def test_result_scores_index_matches_input(self):
        """#16: scores.index == df.index."""
        df = _cycle_df_3hop()
        result = GraphDetector().detect(df)
        assert result.scores.index.equals(df.index)
