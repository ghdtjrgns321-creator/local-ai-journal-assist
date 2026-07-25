"""세션에 case set 이 없을 때 디스크 저장본으로 복원되는지 — Phase 2 재실행 방지.

Why: VAE 화면(분포·요약·ROC·목록)이 전부 in-memory case set 만 보고 있어, 앱을 재시작하면
     디스크에 case 3,368건이 멀쩡히 있는데도 "Phase 2 를 다시 돌려야" 하는 상태가 됐다
     (2026-07-25, 학습·추론 10분 재소요).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import streamlit as st

from dashboard._state import KEY_BATCH_ID, KEY_COMPANY_CONTEXT, KEY_PHASE2_RESULT
from dashboard.components import phase2_native_case_metrics as pncm
from src.services.phase2_case_store import save_phase2_case_set
from tests.modules.test_services.test_phase2_case_store import _make_case_set


@dataclass
class _Ctx:
    company_id: str
    engagement_id: str
    db_path: Path


def _saved_engagement(tmp_path: Path, batch_id: str) -> _Ctx:
    engagement_dir = tmp_path / "acme" / "engagements" / "FY2024"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    ctx = _Ctx("acme", "FY2024", engagement_dir / "audit.duckdb")
    result = save_phase2_case_set(
        ctx=ctx,
        batch_id=batch_id,
        case_set=_make_case_set(batch_id=batch_id),
        salt="acme|FY2024",
    )
    assert result.manifest_path is not None
    return ctx


def _use_state(monkeypatch, state: dict) -> None:
    monkeypatch.setattr(st, "session_state", state, raising=False)
    # cache_data 는 테스트 간 결과를 공유하므로 매번 비운다.
    pncm._load_case_set_cached.clear()


def test_restores_case_set_from_disk_when_session_empty(monkeypatch, tmp_path):
    ctx = _saved_engagement(tmp_path, "batch_restore")
    _use_state(monkeypatch, {KEY_COMPANY_CONTEXT: ctx, KEY_BATCH_ID: "batch_restore"})

    case_set = pncm.resolve_phase2_case_set_from_state()

    assert case_set is not None
    assert len(case_set.unsupervised_cases) == 1


def test_session_case_set_wins_over_disk(monkeypatch, tmp_path):
    """메모리에 있는 결과를 디스크 저장본이 덮어쓰지 않는다."""
    ctx = _saved_engagement(tmp_path, "batch_restore")
    in_memory = _make_case_set(batch_id="batch_restore")
    _use_state(
        monkeypatch,
        {
            KEY_COMPANY_CONTEXT: ctx,
            KEY_BATCH_ID: "batch_restore",
            KEY_PHASE2_RESULT: type("R", (), {"phase2_case_set": in_memory})(),
        },
    )

    assert pncm.resolve_phase2_case_set_from_state() is in_memory


def test_returns_none_when_batch_has_no_saved_cases(monkeypatch, tmp_path):
    ctx = _saved_engagement(tmp_path, "batch_restore")
    _use_state(monkeypatch, {KEY_COMPANY_CONTEXT: ctx, KEY_BATCH_ID: "other_batch"})

    assert pncm.resolve_phase2_case_set_from_state() is None


def test_returns_none_without_context_or_batch(monkeypatch):
    _use_state(monkeypatch, {})
    assert pncm.resolve_phase2_case_set_from_state() is None


def test_document_list_section_uses_restored_case_set(monkeypatch, tmp_path):
    """전표 목록이 세션 phase2_result 부재만으로 '추론 안 됨'을 띄우지 않는다."""
    from dashboard import tab_phase2
    from dashboard.components import phase2_native_case_panel

    ctx = _saved_engagement(tmp_path, "batch_docs")
    _use_state(monkeypatch, {KEY_COMPANY_CONTEXT: ctx, KEY_BATCH_ID: "batch_docs"})

    captured: dict = {}

    def _fake_panel(family, *, case_set, phase1_case_lookup=None, pr=None):
        captured["case_set"] = case_set

    monkeypatch.setattr(phase2_native_case_panel, "render_phase2_native_case_panel", _fake_panel)

    tab_phase2._render_phase2_family_case_section(
        "unsupervised",
        [],
        overlay_status=None,
        partition=None,
        phase2_result=None,
    )

    assert captured["case_set"] is not None
    assert len(captured["case_set"].unsupervised_cases) == 1
