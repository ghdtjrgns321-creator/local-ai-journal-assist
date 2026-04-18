"""WU-27 tab_export 헬퍼 단위 테스트.

Streamlit 렌더 로직(render)은 직접 테스트하지 않는다.
순수 헬퍼(필터 어댑트/설정 폼/해시/파일명/Exporter 래퍼)와
2-Step 캐시 무효화 로직을 검증한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from unittest.mock import MagicMock

import duckdb
import pandas as pd
import pytest

from dashboard import tab_export as te
from dashboard._state import (
    KEY_EXPORT_READY_DATA,
    KEY_EXPORT_READY_HASH,
    KEY_EXPORT_READY_MIME,
    KEY_EXPORT_READY_NAME,
)
from src.db.schema import initialize_schema
from src.export.models import ExportConfig, ExportFilter

BATCH = "WU27_TEST_BATCH"


# ── _build_filter ──────────────────────────────────────────────

def test_build_filter_empty_dict_returns_empty_exportfilter() -> None:
    ef = te._build_filter({})
    assert isinstance(ef, ExportFilter)
    assert ef.is_empty() is True


def test_build_filter_none_returns_empty_exportfilter() -> None:
    # Why: session_state에 KEY_FILTERS가 없을 때 None이 들어올 수 있음
    ef = te._build_filter(None)
    assert ef.is_empty() is True


def test_build_filter_partial_fields_passes_through() -> None:
    fs = {
        "risk_levels": ["High", "Medium"],
        "business_processes": ["P2P"],
        "company_codes": [],  # 빈 리스트 → None (is_empty 판정 정확도)
    }
    ef = te._build_filter(fs)
    assert ef.risk_levels == ["High", "Medium"]
    assert ef.business_processes == ["P2P"]
    assert ef.company_codes is None
    assert ef.is_empty() is False


def test_build_filter_parses_date_range_from_iso_strings() -> None:
    fs = {"date_range": ("2026-01-01", "2026-03-31")}
    ef = te._build_filter(fs)
    assert ef.date_from == date(2026, 1, 1)
    assert ef.date_to == date(2026, 3, 31)


def test_build_filter_tolerates_invalid_date_range() -> None:
    # Why: 사이드바 구현이 바뀌어 이상한 값이 들어와도 폭주하지 않아야 함
    fs = {"date_range": ("bogus", None)}
    ef = te._build_filter(fs)
    assert ef.date_from is None
    assert ef.date_to is None


# ── _build_config_from_form ────────────────────────────────────

def test_build_config_from_empty_form_uses_dataclass_defaults() -> None:
    cfg = te._build_config_from_form({})
    assert isinstance(cfg, ExportConfig)
    assert cfg.mask_pii is True   # UI 폼 기본 True
    assert cfg.top_n == 50
    assert cfg.include_raw_data is True


def test_build_config_from_full_form_maps_all_fields() -> None:
    cfg = te._build_config_from_form({
        "mask_pii": False,
        "top_n": 100,
        "include_raw_data": False,
        "report_title": "Q1 분석",
        "analyst_name": "김감사",
    })
    assert cfg.mask_pii is False
    assert cfg.top_n == 100
    assert cfg.include_raw_data is False
    assert cfg.report_title == "Q1 분석"
    assert cfg.analyst_name == "김감사"


# ── _settings_hash ─────────────────────────────────────────────

def test_settings_hash_is_stable_for_same_inputs() -> None:
    f = ExportFilter(risk_levels=["High"])
    c = ExportConfig(mask_pii=True, top_n=30)
    h1 = te._settings_hash("Excel", f, c, "B1")
    h2 = te._settings_hash("Excel", f, c, "B1")
    assert h1 == h2


def test_settings_hash_changes_when_any_field_changes() -> None:
    f1 = ExportFilter(risk_levels=["High"])
    f2 = ExportFilter(risk_levels=["High", "Medium"])
    c = ExportConfig()
    assert te._settings_hash("Excel", f1, c, "B1") != te._settings_hash("Excel", f2, c, "B1")
    assert te._settings_hash("Excel", f1, c, "B1") != te._settings_hash("PDF", f1, c, "B1")
    assert te._settings_hash("Excel", f1, c, "B1") != te._settings_hash("Excel", f1, c, "B2")


def test_settings_hash_handles_date_fields() -> None:
    # Why: date 객체가 dict 직렬화에서 TypeError를 내지 않아야 함
    f = ExportFilter(date_from=date(2026, 1, 1), date_to=date(2026, 3, 31))
    c = ExportConfig()
    h = te._settings_hash("Excel", f, c, "B1")
    assert isinstance(h, str) and len(h) == 40  # sha1 hex


# ── _sanitize_filename / _make_filename ────────────────────────

def test_sanitize_filename_replaces_special_chars() -> None:
    assert "/" not in te._sanitize_filename("a/b.txt")
    assert ":" not in te._sanitize_filename("x:y")
    # 한글·영숫자·하이픈·언더스코어·점은 유지
    assert te._sanitize_filename("감사_리포트-v2.0") == "감사_리포트-v2.0"


def test_sanitize_filename_never_returns_empty() -> None:
    # Why: 빈 결과물 파일명이 되면 OS 에러 — 기본값 "report" 보장
    assert te._sanitize_filename("") == "report"
    assert te._sanitize_filename("///") == "report"


def test_make_filename_includes_batch_and_ext() -> None:
    name = te._make_filename("Excel", "분석 보고서", "ENG_ab12")
    assert name.endswith(".xlsx")
    assert "ENG_ab12" in name
    assert "분석_보고서" in name


def test_make_filename_csv_has_csv_extension() -> None:
    assert te._make_filename("감사 증적 CSV", "title", "B1").endswith(".csv")


# ── _build_audit_event ─────────────────────────────────────────

def _fake_ctx(anonymous: bool = False):
    ctx = MagicMock()
    ctx.is_anonymous = anonymous
    ctx.company_id = "C001"
    ctx.engagement_id = "2026"
    return ctx


def test_build_audit_event_sets_export_type_and_metadata() -> None:
    event = te._build_audit_event("Excel", "B1", _fake_ctx(), "report.xlsx")
    assert event.event_type == "export"
    assert "Excel" in event.user_action
    assert event.batch_id == "B1"
    assert event.details["format"] == "Excel"
    assert event.details["file_name"] == "report.xlsx"
    assert event.company_id == "C001"


def test_build_audit_event_anonymous_ctx_omits_ids() -> None:
    event = te._build_audit_event("PDF", "B1", _fake_ctx(anonymous=True), "r.pdf")
    assert event.company_id is None
    assert event.engagement_id is None


# ── 캐시 무효화 로직 ───────────────────────────────────────────

def test_invalidate_cache_if_stale_clears_when_hash_mismatch(monkeypatch) -> None:
    fake_state: dict = {
        KEY_EXPORT_READY_DATA: b"old",
        KEY_EXPORT_READY_NAME: "old.xlsx",
        KEY_EXPORT_READY_MIME: "x/x",
        KEY_EXPORT_READY_HASH: "old_hash",
    }
    monkeypatch.setattr(te.st, "session_state", fake_state)
    te._invalidate_cache_if_stale("new_hash")
    assert fake_state[KEY_EXPORT_READY_DATA] is None
    assert fake_state[KEY_EXPORT_READY_HASH] is None


def test_invalidate_cache_if_stale_noop_when_hash_matches(monkeypatch) -> None:
    fake_state: dict = {
        KEY_EXPORT_READY_DATA: b"keep",
        KEY_EXPORT_READY_NAME: "keep.xlsx",
        KEY_EXPORT_READY_MIME: "x/x",
        KEY_EXPORT_READY_HASH: "h",
    }
    monkeypatch.setattr(te.st, "session_state", fake_state)
    te._invalidate_cache_if_stale("h")
    assert fake_state[KEY_EXPORT_READY_DATA] == b"keep"


def test_store_ready_populates_all_four_keys(monkeypatch) -> None:
    fake_state: dict = {}
    monkeypatch.setattr(te.st, "session_state", fake_state)
    te._store_ready(b"abc", "f.xlsx", "x/x", "h")
    assert fake_state[KEY_EXPORT_READY_DATA] == b"abc"
    assert fake_state[KEY_EXPORT_READY_NAME] == "f.xlsx"
    assert fake_state[KEY_EXPORT_READY_MIME] == "x/x"
    assert fake_state[KEY_EXPORT_READY_HASH] == "h"


# ── _export_to_bytes ───────────────────────────────────────────

@dataclass
class _StubPipelineResult:
    data: pd.DataFrame
    results: list
    risk_summary: dict
    batch_id: str
    elapsed: float = 1.0
    load_result: object | None = None
    warnings: list = None  # type: ignore[assignment]


@pytest.fixture
def conn():
    """격리된 DuckDB + 스키마 + 최소 샘플 데이터."""
    c = duckdb.connect(":memory:")
    initialize_schema(c)
    # 최소 GL 1건 (Exporter가 빈 데이터 graceful 처리하므로 많을 필요 없음)
    c.execute(
        """
        INSERT INTO general_ledger
          (document_id, company_code, fiscal_year, fiscal_period,
           posting_date, document_type, business_process,
           created_by, approved_by, debit_amount, credit_amount,
           gl_account, anomaly_score, risk_level, flagged_rules,
           line_number, upload_batch_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        ["D1", "C1", 2026, 1, "2026-01-15 10:00:00", "SA", "P2P",
         "alice", "bob", 1000.0, 0.0, "4100", 0.85, "High", "B05", 1, BATCH],
    )
    # audit_log 이벤트 1건 — CSV export 검증용
    c.execute(
        """
        INSERT INTO audit_log (action, actor, company_id, engagement_id, batch_id, details)
        VALUES (?,?,?,?,?, ?::JSON)
        """,
        ["upload", "tester", "C1", "2026", BATCH, '{"user_action": "test"}'],
    )
    yield c
    c.close()


@pytest.fixture
def pipeline_result():
    df = pd.DataFrame({"document_id": ["D1"], "anomaly_score": [0.85]})
    return _StubPipelineResult(
        data=df,
        results=[],
        risk_summary={"High": 1},
        batch_id=BATCH,
    )


def test_export_to_bytes_excel_returns_xlsx_signature(conn, pipeline_result) -> None:
    """Excel: PK\\x03\\x04 (ZIP 시그니처 — xlsx는 zip 기반)"""
    data = te._export_to_bytes(
        "Excel", pipeline_result, ExportFilter(), ExportConfig(include_raw_data=False), conn,
    )
    assert data[:4] == b"PK\x03\x04"
    assert len(data) > 1000


def test_export_to_bytes_pdf_returns_pdf_signature(conn, pipeline_result) -> None:
    """PDF: %PDF- 시작"""
    data = te._export_to_bytes(
        "PDF", pipeline_result, ExportFilter(), ExportConfig(), conn,
    )
    assert data[:5] == b"%PDF-"


def test_export_to_bytes_csv_returns_utf8_bom(conn, pipeline_result) -> None:
    """CSV: UTF-8 BOM(\\xef\\xbb\\xbf) 포함 + AuditTrail 경로 사용"""
    data = te._export_to_bytes(
        "감사 증적 CSV", pipeline_result, ExportFilter(), ExportConfig(), conn,
    )
    assert data[:3] == b"\xef\xbb\xbf"
    # user_action 컬럼 헤더가 포함되어야 — AuditTrail.get_trail() 경로 증빙
    assert b"user_action" in data


def test_export_to_bytes_csv_raises_when_batch_missing(conn) -> None:
    pr = _StubPipelineResult(
        data=pd.DataFrame(), results=[], risk_summary={}, batch_id="",
    )
    with pytest.raises(ValueError, match="batch_id"):
        te._export_to_bytes("감사 증적 CSV", pr, ExportFilter(), ExportConfig(), conn)


def test_export_to_bytes_csv_raises_when_trail_empty() -> None:
    """audit_log에 해당 batch_id 사용자 이벤트가 없으면 ValueError.

    Why: 헤더만 있는 빈 CSV는 업스트림 로깅 누락 신호. 감사인에게 혼동 주지 않고
         명시적 재실행을 유도한다.
    """
    c = duckdb.connect(":memory:")
    initialize_schema(c)
    # GL만 있고 audit_log는 비어 있는 상태
    pr = _StubPipelineResult(
        data=pd.DataFrame(), results=[], risk_summary={}, batch_id="NO_TRAIL_BATCH",
    )
    with pytest.raises(ValueError, match="감사 증적이 없습니다"):
        te._export_to_bytes("감사 증적 CSV", pr, ExportFilter(), ExportConfig(), c)
    c.close()


def test_export_to_bytes_unknown_format_raises(conn, pipeline_result) -> None:
    with pytest.raises(ValueError, match="지원하지 않는 포맷"):
        te._export_to_bytes("XML", pipeline_result, ExportFilter(), ExportConfig(), conn)


# ── _parse_date 회귀 (내부지만 타임존/타입 이슈 방어) ──────────

def test_parse_date_accepts_date_datetime_and_iso_string() -> None:
    from datetime import datetime as _dt
    assert te._parse_date(date(2026, 1, 1)) == date(2026, 1, 1)
    assert te._parse_date(_dt(2026, 1, 1, 10, 30)) == date(2026, 1, 1)
    assert te._parse_date("2026-01-01") == date(2026, 1, 1)
    assert te._parse_date(None) is None
    assert te._parse_date("") is None
    assert te._parse_date("not a date") is None
