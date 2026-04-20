"""InsightGenerator 단위 테스트 — DuckDB :memory: + mock ChatClient."""

from __future__ import annotations

from unittest.mock import MagicMock

import duckdb
import pytest

from src.llm.insight_generator import InsightGenerator
from src.llm.models import BatchInsight

# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture()
def conn() -> duckdb.DuckDBPyConnection:
    """테스트용 general_ledger 테이블 + 샘플 데이터."""
    c = duckdb.connect(":memory:")
    c.execute(
        """
        CREATE TABLE general_ledger (
            document_id VARCHAR,
            company_code VARCHAR,
            gl_account VARCHAR,
            debit_amount DOUBLE,
            header_text VARCHAR,
            line_text VARCHAR,
            business_process VARCHAR,
            source VARCHAR,
            created_by VARCHAR,
            risk_level VARCHAR,
            flagged_rules VARCHAR
        )
        """
    )
    # (doc_id, company, account, amount, header, line, process, source, creator, risk, rules)
    rows = [
        ("D001", "C001", "4100", 85_000_000, "Revenue Adj Year End",
         None, "O2C", "Adjustment", "SA-005", "Critical", "L4-03,L4-01"),
        ("D002", "C001", "4100", 120_000_000, "Revenue Adj",
         None, "O2C", "Adjustment", "SA-005", "High", "L4-03,L4-01"),
        ("D003", "C002", "6100", 50_000_000, "Salary",
         None, "H2R", "Payroll", "U-010", "Medium", "L3-06"),
        ("D004", "C001", "4100", 30_000_000, "Normal Sales",
         None, "O2C", "Standard", "U-001", "Low", ""),
        ("D005", "C001", "4100", 200_000_000, "Year-End Revenue Booking",
         None, "O2C", "Adjustment", "SA-005", "Critical", "L4-03,L4-01,L2-01"),
        ("D006", "C001", "6100", 10_000_000, "Regular Payroll",
         None, "H2R", "Payroll", "U-011", None, None),
    ]
    c.executemany("INSERT INTO general_ledger VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    return c


@pytest.fixture()
def mock_client() -> MagicMock:
    """BatchInsight JSON을 반환하는 mock ChatClient."""
    client = MagicMock()
    payload = BatchInsight(
        summary=(
            "배치에 Critical 2건, High 1건이 식별되었습니다. "
            "L4-03과 L4-01 동시 플래그 전표가 3건으로 매출 기말 조정 위험이 높습니다."
        ),
        top_risks=[
            "L4-03 AND L4-01 동시 플래그 매출 기말 조정 전표 3건",
            "SA-005 한 사용자가 Critical 전표 다수 기표",
        ],
        significant_tx_opinions=[
            {
                "document_id": "D005",
                "account": "4100",
                "amount": 200_000_000,
                "business_rationale": (
                    "기말 Revenue Booking은 사업상 타당 가능하나 Adjustment 소스와 "
                    "Senior 단독 기표는 추가 검토 필요합니다(L4-03, L4-01)."
                ),
                "audit_flag": "high_risk",
            },
        ],
    )
    client.chat.return_value = payload.model_dump_json()
    return client


# ── 테스트 ──────────────────────────────────────────────────────


def test_aggregate_stats_counts_by_risk_level(conn):
    """risk_level별 카운트 + 차변합계 집계."""
    gen = InsightGenerator(conn, client=MagicMock())
    stats = gen._aggregate_stats()
    by_level = {s["risk_level"]: s for s in stats}
    assert by_level["Critical"]["n"] == 2
    assert by_level["High"]["n"] == 1
    assert by_level["Medium"]["n"] == 1
    assert "D006" not in [s["risk_level"] for s in stats]  # NULL 제외


def test_aggregate_rule_counts_topn(conn):
    """flagged_rules CSV unnest 후 Top 카운트."""
    gen = InsightGenerator(conn, client=MagicMock())
    counts = gen._aggregate_rule_counts(top_n=10)
    by_code = {c["rule_code"]: c["n"] for c in counts}
    assert by_code["L4-03"] == 3
    assert by_code["L4-01"] == 3
    assert by_code["L2-01"] == 1


def test_query_significant_tx_filters_c08_and_b01(conn):
    """L4-03 AND L4-01 둘 다 포함된 전표만 반환, 금액 내림차순."""
    gen = InsightGenerator(conn, client=MagicMock())
    sig = gen._query_significant_tx(limit=20)
    doc_ids = [r["document_id"] for r in sig]
    assert doc_ids == ["D005", "D002", "D001"]  # 200M > 120M > 85M
    assert "D003" not in doc_ids  # L3-06만 있음
    assert "D004" not in doc_ids  # 플래그 없음


def test_query_significant_tx_respects_limit(conn):
    """limit 파라미터가 LIMIT 절에 전달됨."""
    gen = InsightGenerator(conn, client=MagicMock())
    sig = gen._query_significant_tx(limit=2)
    assert len(sig) == 2


def test_generate_batch_insight_happy_path(conn, mock_client):
    """stats + sig_tx를 프롬프트에 담고 LLM 응답을 BatchInsight로 파싱."""
    gen = InsightGenerator(conn, client=mock_client)
    result = gen.generate_batch_insight()

    assert isinstance(result, BatchInsight)
    summary_lower = result.summary.lower()
    assert "critical" in summary_lower or "이상" in result.summary
    assert len(result.significant_tx_opinions) == 1
    assert result.significant_tx_opinions[0].audit_flag == "high_risk"
    assert mock_client.chat.called

    # 프롬프트에 유의적 거래 정보가 포함되는지
    call_args = mock_client.chat.call_args
    messages = call_args[0][0] if call_args[0] else call_args.kwargs["messages"]
    user_content = messages[-1]["content"]
    assert "L4-03" in user_content and "L4-01" in user_content


def test_generate_batch_insight_empty_data_graceful():
    """데이터가 비어도 예외 없이 호출 가능."""
    c = duckdb.connect(":memory:")
    c.execute("""
        CREATE TABLE general_ledger (
            document_id VARCHAR, company_code VARCHAR, gl_account VARCHAR,
            debit_amount DOUBLE, header_text VARCHAR, line_text VARCHAR,
            business_process VARCHAR, source VARCHAR, created_by VARCHAR,
            risk_level VARCHAR, flagged_rules VARCHAR
        )
    """)
    client = MagicMock()
    empty_insight = BatchInsight(
        summary="이상 전표가 식별되지 않았습니다.",
        top_risks=[],
        significant_tx_opinions=[],
    )
    client.chat.return_value = empty_insight.model_dump_json()

    gen = InsightGenerator(c, client=client)
    result = gen.generate_batch_insight()
    assert result.summary
    assert result.top_risks == []
    assert result.significant_tx_opinions == []
