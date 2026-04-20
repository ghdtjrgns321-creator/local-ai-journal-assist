"""NarrativeReporter 단위 테스트 — 캐시, 배치, Laziness 재시도 방어 검증."""

from __future__ import annotations

from unittest.mock import MagicMock

import duckdb
import pytest

from src.db.schema import initialize_schema
from src.llm.models import EntryNarrative, NarrativeBatch
from src.llm.narrative_report import NarrativeReporter

# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture()
def conn() -> duckdb.DuckDBPyConnection:
    """initialize_schema로 실제 프로덕션 DDL 적용 + 샘플 데이터."""
    c = duckdb.connect(":memory:")
    initialize_schema(c)

    base_row = {
        "posting_date": "2026-03-31 12:00:00",
        "fiscal_period": 3,
        "document_id": "",
        "risk_level": "High",
        "anomaly_score": 0.8,
        "flagged_rules": "L2-01,L3-06",
        "debit_amount": 50_000_000,
        "credit_amount": 0,
        "gl_account": "4100",
        "company_code": "C001",
        "header_text": "Test Entry",
    }
    for did, risk in [
        ("D001", "High"), ("D002", "Critical"), ("D003", "Critical"),
        ("D004", "Low"),           # 대상 외
        ("D005", None),            # 대상 외
    ]:
        row = {**base_row, "document_id": did, "risk_level": risk}
        cols = ", ".join(row.keys())
        placeholders = ", ".join(["?"] * len(row))
        c.execute(
            f"INSERT INTO general_ledger ({cols}) VALUES ({placeholders})",
            list(row.values()),
        )
    return c


def _make_client(narratives_by_call: list[list[EntryNarrative]]) -> MagicMock:
    """chat()가 호출될 때마다 narratives_by_call 순서대로 JSON 반환."""
    client = MagicMock()
    client.model = "gpt-5.4-mini"
    responses = [
        NarrativeBatch(narratives=ns).model_dump_json() for ns in narratives_by_call
    ]
    client.chat.side_effect = responses
    return client


def _narrative(doc_id: str) -> EntryNarrative:
    return EntryNarrative(
        document_id=doc_id,
        rationale=f"{doc_id} 위험 사유: L2-01/L3-06 플래그.",
        cited_rules=["L2-01", "L3-06"],
    )


# ── 테스트 ──────────────────────────────────────────────────────


def test_select_pending_filters_risk_levels(conn):
    """risk_level ∈ ['High','Critical'] 만 대상."""
    reporter = NarrativeReporter(conn, client=_make_client([[]]))
    pending = reporter._select_pending()
    assert set(pending) == {"D001", "D002", "D003"}


def test_select_pending_excludes_cached(conn):
    """llm_narratives 캐시 존재 ID는 제외."""
    conn.execute(
        "INSERT INTO llm_narratives (document_id, narrative_text, model_tier) "
        "VALUES ('D002', 'cached', 'light')"
    )
    reporter = NarrativeReporter(conn, client=_make_client([[]]))
    pending = reporter._select_pending()
    assert "D002" not in pending
    assert set(pending) == {"D001", "D003"}


def test_generate_for_high_critical_happy_path(conn, monkeypatch):
    """3건을 배치 15 크기로 1회 호출, 모두 캐시에 저장."""
    client = _make_client([[_narrative("D001"), _narrative("D002"), _narrative("D003")]])
    reporter = NarrativeReporter(conn, client=client)

    n_new = reporter.generate_for_high_critical()
    assert n_new == 3
    assert client.chat.call_count == 1

    cached = conn.execute(
        "SELECT document_id, narrative_text FROM llm_narratives ORDER BY document_id"
    ).fetchall()
    assert [r[0] for r in cached] == ["D001", "D002", "D003"]
    assert all("L2-01" in r[1] or "위험" in r[1] for r in cached)


def test_batch_size_splits_calls(conn, monkeypatch):
    """batch_size=2 시 3건 → 2회 호출 (2건 + 1건)."""
    monkeypatch.setattr(
        "src.llm.narrative_report.get_settings",
        lambda: type("S", (), {
            "narrative_batch_size": 2,
            "narrative_max_retries": 2,
            "narrative_risk_levels": ["High", "Critical"],
        })(),
    )
    client = _make_client([
        [_narrative("D001"), _narrative("D002")],
        [_narrative("D003")],
    ])
    reporter = NarrativeReporter(conn, client=client)

    n_new = reporter.generate_for_high_critical()
    assert n_new == 3
    assert client.chat.call_count == 2


def test_idempotent_rerun_hits_cache(conn):
    """동일 배치 2회 호출 시 2회째 API 호출 0건."""
    client = _make_client([[_narrative("D001"), _narrative("D002"), _narrative("D003")]])
    reporter = NarrativeReporter(conn, client=client)

    first = reporter.generate_for_high_critical()
    second = reporter.generate_for_high_critical()
    assert first == 3
    assert second == 0
    assert client.chat.call_count == 1


def test_get_narratives_mixes_cache_and_generation(conn):
    """일부는 캐시 HIT, 나머지는 신규 생성."""
    conn.execute(
        "INSERT INTO llm_narratives (document_id, narrative_text, model_tier) "
        "VALUES ('D001', '캐시된 사유서 D001', 'light')"
    )
    client = _make_client([[_narrative("D002")]])
    reporter = NarrativeReporter(conn, client=client)

    result = reporter.get_narratives(["D001", "D002"])
    assert result["D001"] == "캐시된 사유서 D001"
    assert "D002" in result["D002"]
    assert client.chat.call_count == 1  # D001은 캐시 HIT


def test_laziness_missing_triggers_retry(conn):
    """15건 요청 → 10건만 응답 → 누락 5건 재호출 → 최종 전체 반환."""
    client = MagicMock()
    client.model = "gpt-5.4-mini"

    # 1차 호출: 3건 중 2건만 반환 (D001, D002)
    # 2차 호출(재시도): 누락된 D003 반환
    responses = [
        NarrativeBatch(narratives=[_narrative("D001"), _narrative("D002")]).model_dump_json(),
        NarrativeBatch(narratives=[_narrative("D003")]).model_dump_json(),
    ]
    client.chat.side_effect = responses

    reporter = NarrativeReporter(conn, client=client)
    n_new = reporter.generate_for_high_critical()
    assert n_new == 3
    assert client.chat.call_count == 2  # 초기 1회 + 재시도 1회

    cached_ids = {r[0] for r in conn.execute("SELECT document_id FROM llm_narratives").fetchall()}
    assert cached_ids == {"D001", "D002", "D003"}


def test_laziness_retry_exhausted_returns_partial(conn, monkeypatch, caplog):
    """max_retries=1 재시도 소진 시 수집분만 반환 + ERROR 로그."""
    import logging
    caplog.set_level(logging.ERROR)

    # Why: 실제 settings.narrative_max_retries=2를 덮어 테스트 시나리오 강제.
    monkeypatch.setattr(
        "src.llm.narrative_report.get_settings",
        lambda: type("S", (), {
            "narrative_batch_size": 15,
            "narrative_max_retries": 1,
            "narrative_risk_levels": ["High", "Critical"],
        })(),
    )

    client = MagicMock()
    client.model = "gpt-5.4-mini"
    # 1차: D001만 반환 (D002, D003 누락)
    # 2차(재시도 1회 소진): [] 반환 → 누락 유지
    client.chat.side_effect = [
        NarrativeBatch(narratives=[_narrative("D001")]).model_dump_json(),
        NarrativeBatch(narratives=[]).model_dump_json(),
    ]
    reporter = NarrativeReporter(conn, client=client)

    n_new = reporter.generate_for_high_critical()
    assert n_new == 1
    assert client.chat.call_count == 2  # 초기 1회 + 재시도 1회 (소진)
    assert any("재시도 소진" in rec.message for rec in caplog.records)


def test_json_parse_failure_graceful(conn):
    """LLM이 깨진 JSON 반환 시 파싱 실패를 흡수하고 재시도 진행."""
    client = MagicMock()
    client.model = "gpt-5.4-mini"
    full = NarrativeBatch(
        narratives=[_narrative("D001"), _narrative("D002"), _narrative("D003")],
    ).model_dump_json()
    client.chat.side_effect = [
        "this is not json at all",
        full,
        NarrativeBatch(narratives=[]).model_dump_json(),
    ]
    reporter = NarrativeReporter(conn, client=client)
    n_new = reporter.generate_for_high_critical()
    assert n_new == 3


def test_upsert_overwrites_existing(conn):
    """동일 document_id 재생성 시 narrative_text 덮어쓰기."""
    conn.execute(
        "INSERT INTO llm_narratives (document_id, narrative_text, model_tier) "
        "VALUES ('D001', 'old', 'light')"
    )
    new_narr = EntryNarrative(document_id="D001", rationale="new rationale", cited_rules=["L2-01"])
    client = _make_client([[]])
    reporter = NarrativeReporter(conn, client=client)
    reporter._upsert_cache([new_narr])

    row = conn.execute(
        "SELECT narrative_text FROM llm_narratives WHERE document_id='D001'"
    ).fetchone()
    assert row[0] == "new rationale"


# ── Hallucination 교차검증 테스트 ──────────────────────────────


def test_validate_cited_rules_removes_hallucinated():
    """cited_rules에 flagged_rules에 없는 룰이 포함되면 제거 + 경고 라벨 부착."""
    import pandas as pd

    rows = pd.DataFrame([{"document_id": "D001", "flagged_rules": "L2-01,L3-06"}])
    narr = EntryNarrative(
        document_id="D001",
        rationale="위험 사유",
        cited_rules=["L2-01", "X99"],
    )
    result = NarrativeReporter._validate_cited_rules([narr], rows)
    assert result[0].cited_rules == ["L2-01"]
    assert "[경고:" in result[0].rationale
    assert "X99" in result[0].rationale


def test_validate_cited_rules_no_hallucination_passthrough():
    """Hallucination이 없으면 원본 그대로 반환."""
    import pandas as pd

    rows = pd.DataFrame([{"document_id": "D001", "flagged_rules": "L2-01,L3-06"}])
    narr = EntryNarrative(
        document_id="D001",
        rationale="정상 사유",
        cited_rules=["L2-01"],
    )
    result = NarrativeReporter._validate_cited_rules([narr], rows)
    assert result[0].cited_rules == ["L2-01"]
    assert "[경고:" not in result[0].rationale
    assert result[0].rationale == "정상 사유"


def test_validate_cited_rules_all_hallucinated():
    """cited_rules 전부 허위이면 빈 리스트로 반환 + 경고."""
    import pandas as pd

    rows = pd.DataFrame([{"document_id": "D001", "flagged_rules": "L2-01"}])
    narr = EntryNarrative(
        document_id="D001",
        rationale="사유서",
        cited_rules=["X01", "X02"],
    )
    result = NarrativeReporter._validate_cited_rules([narr], rows)
    assert result[0].cited_rules == []
    assert "X01" in result[0].rationale
    assert "X02" in result[0].rationale


def test_validate_cited_rules_missing_column_passthrough():
    """flagged_rules 컬럼이 없으면 검증 스킵 — 원본 그대로 반환."""
    import pandas as pd

    rows = pd.DataFrame([{"document_id": "D001"}])
    narr = EntryNarrative(
        document_id="D001",
        rationale="사유서",
        cited_rules=["L2-01"],
    )
    result = NarrativeReporter._validate_cited_rules([narr], rows)
    assert result[0].cited_rules == ["L2-01"]
