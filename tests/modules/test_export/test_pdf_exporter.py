"""PDFExporter 단위 테스트.

테스트 그룹:
    - TestBasicExport: 파일 생성, 한글 폰트 등록, 면책조항 텍스트 포함
    - TestEmptyData: 빈 배치에서 graceful 처리
    - TestSafeChart: kaleido timeout fallback 동작 확인 (mock)
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb
import pandas as pd
import pytest

pytest.importorskip("fpdf")

from src.db.schema import initialize_schema  # noqa: E402
from src.export.pdf_exporter import _FONT_CANDIDATES, PDFExporter  # noqa: E402

BATCH = "TEST_BATCH_PDF"


@dataclass
class _StubPipelineResult:
    data: pd.DataFrame
    results: list
    risk_summary: dict
    batch_id: str
    elapsed: float = 1.5
    load_result: object | None = None
    warnings: list = None  # type: ignore[assignment]


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "pdf_test.duckdb"
    c = duckdb.connect(str(db_path))
    initialize_schema(c)
    _seed(c)
    yield c
    c.close()


def _seed(c: duckdb.DuckDBPyConnection) -> None:
    rows = [
        ("D001", "C001", "P2P", "2026-01-01 10:00:00", 0.85, "High", "B05"),
        ("D002", "C001", "O2C", "2026-01-02 11:00:00", 0.50, "Medium", "C03"),
        ("D003", "C002", "TRE", "2026-01-03 14:00:00", 0.10, "Normal", ""),
    ]
    for r in rows:
        c.execute(
            """
            INSERT INTO general_ledger
              (document_id, company_code, business_process, posting_date,
               anomaly_score, risk_level, flagged_rules,
               line_number, fiscal_period, debit_amount, credit_amount,
               upload_batch_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            [*r, 1, 1, 100.0, 0.0, BATCH],
        )
    c.execute(
        "INSERT INTO benford_summary (upload_batch_id, sample_size, mad, "
        "mad_conformity, chi2_statistic, chi2_p_value, is_conforming, confidence) "
        "VALUES (?,?,?,?,?,?,?,?)",
        [BATCH, 3, 0.02, "close", 0.5, 0.95, True, "low"],
    )
    for digit in range(1, 10):
        c.execute(
            "INSERT INTO benford_digits "
            "(upload_batch_id, digit, observed_freq, expected_freq, deviation) "
            "VALUES (?,?,?,?,?)",
            [BATCH, digit, 0.11, 0.10, 0.01],
        )
    c.execute(
        "INSERT INTO anomaly_flags "
        "(upload_batch_id, document_id, line_number, track_name, rule_code, score) "
        "VALUES (?,?,?,?,?,?)",
        [BATCH, "D001", 1, "layer_b", "B05", 0.9],
    )


@pytest.fixture
def pipeline_result():
    df = pd.DataFrame({"document_id": ["D001"]})
    return _StubPipelineResult(
        data=df,
        results=[],
        risk_summary={"High": 1, "Medium": 1, "Low": 0, "Normal": 1},
        batch_id=BATCH,
        warnings=[],
    )


# ── Tests ────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def has_korean_font() -> bool:
    return any(p.exists() for p in _FONT_CANDIDATES)


class TestBasicExport:
    def test_creates_pdf_file(self, conn, pipeline_result, tmp_path, has_korean_font):
        if not has_korean_font:
            pytest.skip("한글 폰트 미설치 환경 — PDF 생성 불가")
        out = tmp_path / "report.pdf"
        result = PDFExporter(conn).export(pipeline_result, out)
        assert result == out
        assert out.exists()
        assert out.stat().st_size > 1000  # 빈 PDF는 ~500B 이하

    def test_pdf_starts_with_signature(
        self, conn, pipeline_result, tmp_path, has_korean_font
    ):
        if not has_korean_font:
            pytest.skip("한글 폰트 미설치")
        out = tmp_path / "report.pdf"
        PDFExporter(conn).export(pipeline_result, out)
        # Why: 모든 PDF는 "%PDF-" magic으로 시작
        with out.open("rb") as f:
            assert f.read(5) == b"%PDF-"


class TestEmptyData:
    def test_unknown_batch_does_not_crash(self, conn, tmp_path, has_korean_font):
        if not has_korean_font:
            pytest.skip("한글 폰트 미설치")
        empty_pr = _StubPipelineResult(
            data=pd.DataFrame(),
            results=[],
            risk_summary={},
            batch_id="NONEXISTENT",
            warnings=[],
        )
        out = tmp_path / "empty.pdf"
        PDFExporter(conn).export(empty_pr, out)
        assert out.exists()


class TestSafeChart:
    def test_safe_chart_returns_none_on_timeout(self, conn):
        """차트 렌더가 timeout을 초과하면 None 반환 (대시보드 블로킹 방지)."""
        exporter = PDFExporter(conn)

        class _SlowFig:
            def to_image(self, format: str) -> bytes:  # noqa: A002
                import time

                time.sleep(30)  # _KALEIDO_TIMEOUT_SEC(10) 초과 — 강제 timeout
                return b""

        # Why: timeout 임계를 짧게 재설정하여 테스트 시간 단축
        import src.export.pdf_exporter as pe

        original = pe._KALEIDO_TIMEOUT_SEC
        pe._KALEIDO_TIMEOUT_SEC = 1
        try:
            result = exporter._safe_chart_to_png(_SlowFig())
            assert result is None
        finally:
            pe._KALEIDO_TIMEOUT_SEC = original

    def test_safe_chart_returns_none_on_exception(self, conn):
        exporter = PDFExporter(conn)

        class _BrokenFig:
            def to_image(self, format: str) -> bytes:  # noqa: A002
                raise RuntimeError("kaleido not installed")

        result = exporter._safe_chart_to_png(_BrokenFig())
        assert result is None
