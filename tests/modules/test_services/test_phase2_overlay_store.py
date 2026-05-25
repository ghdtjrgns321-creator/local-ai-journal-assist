"""Phase 2 overlay store round-trip tests."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.services.phase2_overlay_store import (
    SCHEMA_VERSION,
    OverlayStatus,
    load_phase2_overlay_status,
    load_phase2_overlays,
    save_phase2_overlays,
)


def _make_ctx(tmp_path: Path, company_id: str = "acme", engagement_id: str = "FY2024"):
    """`db_path.parent` 가 engagement 폴더가 되도록 가짜 ctx 를 만든다."""
    engagement_dir = tmp_path / company_id / "engagements" / engagement_id
    engagement_dir.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        company_id=company_id,
        engagement_id=engagement_id,
        db_path=engagement_dir / "audit.duckdb",
    )


def _sample_overlay(case_id: str = "case_001") -> dict:
    return {
        "phase1_case_id": case_id,
        "phase2_family_scores": {"duplicate": 0.7, "timeseries": 0.4},
        "phase2_adjusted_priority": 0.81,
        "precision_adjustment_reason": "family_score_overlay",
        "detector_statuses": [],
        "phase2_inference_contract": None,
        "phase2_training_report_id": "report_xyz",
        "family_contributions": [
            {
                "family": "duplicate",
                "score": 0.7,
                "ecdf": 0.92,
                "evidence_tier": "strong",
                "evidence_tier_weight": 3,
                "sub_detectors": [{"code": "L2-03a", "label": "exact_duplicate_amount"}],
            }
        ],
        "top_family": "duplicate",
        "coverage_breadth_q95": 1,
        "max_family_ecdf": 0.92,
        "max_evidence_tier": "strong",
        "lane_membership": ["duplicate"],
        "coverage_gap_families": [],
    }


def test_save_and_load_round_trip(tmp_path):
    """저장한 overlay 가 동일 내용으로 복원되어야 한다."""
    ctx = _make_ctx(tmp_path)
    overlays = [_sample_overlay("case_001"), _sample_overlay("case_002")]

    written = save_phase2_overlays(
        ctx=ctx,
        batch_id="batch_2024_001",
        overlays=overlays,
        phase2_training_report_id="report_xyz",
        phase2_partition="2024",
    )

    assert written is not None
    assert written.exists()

    loaded = load_phase2_overlays(ctx=ctx, batch_id="batch_2024_001")
    assert loaded == overlays


def test_load_missing_file_returns_none(tmp_path):
    """파일이 없으면 None — 에러 없이 graceful fallback."""
    ctx = _make_ctx(tmp_path)
    assert load_phase2_overlays(ctx=ctx, batch_id="missing_batch") is None


def test_load_rejects_stale_training_report_id(tmp_path):
    """E9/P1c: overlay 의 phase2_training_report_id 가 expected 와 다르면 None.

    Why: 재학습 후 batch_meta 의 새 report_id 와 overlay 파일의 이전 report_id 가
    어긋나면 stale overlay 가 새 model basis 와 함께 표시되는 것을 막아야 한다.
    """
    ctx = _make_ctx(tmp_path)
    overlays = [_sample_overlay()]
    save_phase2_overlays(
        ctx=ctx,
        batch_id="batch_stale",
        overlays=overlays,
        phase2_training_report_id="report_old",
    )

    # expected 와 일치 — 정상 attach
    same = load_phase2_overlays(
        ctx=ctx,
        batch_id="batch_stale",
        expected_training_report_id="report_old",
    )
    assert same == overlays

    # expected 와 불일치 — attach 거부
    stale = load_phase2_overlays(
        ctx=ctx,
        batch_id="batch_stale",
        expected_training_report_id="report_new",
    )
    assert stale is None

    # expected=None 이면 검증 스킵 (CLI/마이그레이션 호환)
    backward_compat = load_phase2_overlays(ctx=ctx, batch_id="batch_stale")
    assert backward_compat == overlays


def test_schema_version_mismatch_returns_none(tmp_path):
    """schema_version 이 다르면 None (호환성 가드)."""
    ctx = _make_ctx(tmp_path)
    overlay_path = tmp_path / "acme" / "engagements" / "FY2024" / "phase2_overlays"
    overlay_path.mkdir(parents=True, exist_ok=True)
    (overlay_path / "batch_x.json").write_text(
        json.dumps(
            {
                "schema_version": "0.9",
                "batch_id": "batch_x",
                "overlays": [_sample_overlay()],
            }
        ),
        encoding="utf-8",
    )

    assert load_phase2_overlays(ctx=ctx, batch_id="batch_x") is None


def test_corrupted_json_returns_none(tmp_path):
    """JSON 파싱 실패 시 None — best-effort."""
    ctx = _make_ctx(tmp_path)
    overlay_path = tmp_path / "acme" / "engagements" / "FY2024" / "phase2_overlays"
    overlay_path.mkdir(parents=True, exist_ok=True)
    (overlay_path / "batch_corrupt.json").write_text("{not valid json", encoding="utf-8")

    assert load_phase2_overlays(ctx=ctx, batch_id="batch_corrupt") is None


def test_company_isolation(tmp_path):
    """다른 회사/engagement ctx 는 다른 경로 — 서로 영향 없어야 한다."""
    ctx_a = _make_ctx(tmp_path, company_id="acme", engagement_id="FY2024")
    ctx_b = _make_ctx(tmp_path, company_id="other", engagement_id="FY2024")

    save_phase2_overlays(
        ctx=ctx_a,
        batch_id="batch_shared_id",
        overlays=[_sample_overlay("acme_case")],
    )

    # ctx_b 로 같은 batch_id 조회 — None 이어야 한다.
    assert load_phase2_overlays(ctx=ctx_b, batch_id="batch_shared_id") is None

    # ctx_a 로 조회하면 정상.
    loaded = load_phase2_overlays(ctx=ctx_a, batch_id="batch_shared_id")
    assert loaded is not None
    assert loaded[0]["phase1_case_id"] == "acme_case"


def test_save_with_none_ctx_returns_none(tmp_path):
    """ctx 가 None 이면 저장 스킵 (best-effort)."""
    assert save_phase2_overlays(ctx=None, batch_id="b1", overlays=[]) is None


def test_save_with_empty_batch_id_returns_none(tmp_path):
    """batch_id 가 빈 문자열이면 저장 스킵."""
    ctx = _make_ctx(tmp_path)
    assert save_phase2_overlays(ctx=ctx, batch_id="", overlays=[]) is None


def test_persisted_schema_version_is_pinned(tmp_path):
    """저장 파일이 현재 SCHEMA_VERSION 으로 기록되어야 한다."""
    ctx = _make_ctx(tmp_path)
    written = save_phase2_overlays(ctx=ctx, batch_id="batch_pin", overlays=[_sample_overlay()])
    assert written is not None
    payload = json.loads(written.read_text(encoding="utf-8"))
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["batch_id"] == "batch_pin"


def test_empty_overlays_round_trip(tmp_path):
    """빈 overlay 리스트 저장/복원이 동작해야 한다."""
    ctx = _make_ctx(tmp_path)
    written = save_phase2_overlays(ctx=ctx, batch_id="batch_empty", overlays=[])
    assert written is not None
    loaded = load_phase2_overlays(ctx=ctx, batch_id="batch_empty")
    assert loaded == []


@pytest.mark.parametrize(
    "tag, payload",
    [
        ("missing_overlays_key", {"schema_version": SCHEMA_VERSION, "batch_id": "x"}),
        ("non_list_overlays", {"schema_version": SCHEMA_VERSION, "overlays": {}}),
    ],
)
def test_invalid_payload_returns_none(tmp_path, tag, payload):
    """overlays 가 누락되거나 list 가 아니면 None."""
    del tag
    ctx = _make_ctx(tmp_path)
    overlay_path = tmp_path / "acme" / "engagements" / "FY2024" / "phase2_overlays"
    overlay_path.mkdir(parents=True, exist_ok=True)
    (overlay_path / "batch_invalid.json").write_text(json.dumps(payload), encoding="utf-8")

    assert load_phase2_overlays(ctx=ctx, batch_id="batch_invalid") is None


# ── P2: OverlayLoadResult diagnostic status 별 단위 테스트 ──────


def test_status_loaded_success(tmp_path):
    """정상 저장 + 정합 → LOADED + overlays 포함."""
    ctx = _make_ctx(tmp_path)
    overlays = [_sample_overlay("case_001")]
    save_phase2_overlays(
        ctx=ctx,
        batch_id="batch_ok",
        overlays=overlays,
        phase2_training_report_id="report_x",
    )
    result = load_phase2_overlay_status(ctx=ctx, batch_id="batch_ok")
    assert result.status == OverlayStatus.LOADED
    assert result.overlays == overlays
    assert result.path is not None
    assert result.metadata.get("phase2_training_report_id") == "report_x"


def test_status_ctx_missing():
    """ctx=None → CTX_MISSING."""
    result = load_phase2_overlay_status(ctx=None, batch_id="batch_x")
    assert result.status == OverlayStatus.CTX_MISSING
    assert result.overlays is None
    assert "ctx" in result.message.lower()


def test_status_ctx_missing_db_path_none(tmp_path):
    """ctx 는 있지만 db_path 가 None → CTX_MISSING."""
    del tmp_path
    ctx = SimpleNamespace(company_id="acme", engagement_id="FY", db_path=None)
    result = load_phase2_overlay_status(ctx=ctx, batch_id="batch_x")
    assert result.status == OverlayStatus.CTX_MISSING


def test_status_unsafe_batch_id(tmp_path):
    """batch_id 가 path traversal 포함 → UNSAFE_BATCH_ID."""
    ctx = _make_ctx(tmp_path)
    for unsafe in ("..", "../escape", "with/slash", "with\\back", ""):
        result = load_phase2_overlay_status(ctx=ctx, batch_id=unsafe)
        assert result.status == OverlayStatus.UNSAFE_BATCH_ID, f"failed for {unsafe!r}"


def test_status_missing_file(tmp_path):
    """파일 없음 → MISSING + path 노출."""
    ctx = _make_ctx(tmp_path)
    result = load_phase2_overlay_status(ctx=ctx, batch_id="batch_absent")
    assert result.status == OverlayStatus.MISSING
    assert result.path is not None
    assert result.overlays is None


def test_status_parse_error(tmp_path):
    """JSON 파싱 실패 → PARSE_ERROR."""
    ctx = _make_ctx(tmp_path)
    overlay_dir = tmp_path / "acme" / "engagements" / "FY2024" / "phase2_overlays"
    overlay_dir.mkdir(parents=True, exist_ok=True)
    (overlay_dir / "batch_bad.json").write_text("{not valid", encoding="utf-8")
    result = load_phase2_overlay_status(ctx=ctx, batch_id="batch_bad")
    assert result.status == OverlayStatus.PARSE_ERROR


def test_status_invalid_payload_root_not_dict(tmp_path):
    """payload root 가 dict 가 아니면 INVALID_PAYLOAD."""
    ctx = _make_ctx(tmp_path)
    overlay_dir = tmp_path / "acme" / "engagements" / "FY2024" / "phase2_overlays"
    overlay_dir.mkdir(parents=True, exist_ok=True)
    (overlay_dir / "batch_arr.json").write_text("[1, 2, 3]", encoding="utf-8")
    result = load_phase2_overlay_status(ctx=ctx, batch_id="batch_arr")
    assert result.status == OverlayStatus.INVALID_PAYLOAD


def test_status_invalid_payload_overlays_not_list(tmp_path):
    """overlays key 가 list 가 아니면 INVALID_PAYLOAD."""
    ctx = _make_ctx(tmp_path)
    overlay_dir = tmp_path / "acme" / "engagements" / "FY2024" / "phase2_overlays"
    overlay_dir.mkdir(parents=True, exist_ok=True)
    (overlay_dir / "batch_o.json").write_text(
        json.dumps({"schema_version": SCHEMA_VERSION, "batch_id": "batch_o", "overlays": {}}),
        encoding="utf-8",
    )
    result = load_phase2_overlay_status(ctx=ctx, batch_id="batch_o")
    assert result.status == OverlayStatus.INVALID_PAYLOAD


def test_status_schema_mismatch(tmp_path):
    """schema_version 다르면 SCHEMA_MISMATCH + metadata 에 expected/got."""
    ctx = _make_ctx(tmp_path)
    overlay_dir = tmp_path / "acme" / "engagements" / "FY2024" / "phase2_overlays"
    overlay_dir.mkdir(parents=True, exist_ok=True)
    (overlay_dir / "batch_sv.json").write_text(
        json.dumps(
            {
                "schema_version": "0.9",
                "batch_id": "batch_sv",
                "overlays": [_sample_overlay()],
            }
        ),
        encoding="utf-8",
    )
    result = load_phase2_overlay_status(ctx=ctx, batch_id="batch_sv")
    assert result.status == OverlayStatus.SCHEMA_MISMATCH
    assert result.metadata.get("expected") == SCHEMA_VERSION
    assert result.metadata.get("got") == "0.9"


def test_status_batch_id_mismatch(tmp_path):
    """파일 안 batch_id 와 요청 batch_id 다르면 BATCH_ID_MISMATCH."""
    ctx = _make_ctx(tmp_path)
    overlay_dir = tmp_path / "acme" / "engagements" / "FY2024" / "phase2_overlays"
    overlay_dir.mkdir(parents=True, exist_ok=True)
    (overlay_dir / "batch_x.json").write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "batch_id": "DIFFERENT",
                "overlays": [_sample_overlay()],
            }
        ),
        encoding="utf-8",
    )
    result = load_phase2_overlay_status(ctx=ctx, batch_id="batch_x")
    assert result.status == OverlayStatus.BATCH_ID_MISMATCH
    assert result.metadata.get("expected") == "batch_x"
    assert result.metadata.get("got") == "DIFFERENT"


def test_status_training_report_mismatch(tmp_path):
    """expected_training_report_id 가 payload 와 다르면 TRAINING_REPORT_MISMATCH."""
    ctx = _make_ctx(tmp_path)
    save_phase2_overlays(
        ctx=ctx,
        batch_id="batch_tr",
        overlays=[_sample_overlay()],
        phase2_training_report_id="report_old",
    )
    result = load_phase2_overlay_status(
        ctx=ctx,
        batch_id="batch_tr",
        expected_training_report_id="report_new",
    )
    assert result.status == OverlayStatus.TRAINING_REPORT_MISMATCH
    assert result.metadata.get("expected") == "report_new"
    assert result.metadata.get("got") == "report_old"


def test_load_phase2_overlays_backward_compat_returns_list_on_loaded(tmp_path):
    """기존 호출자가 받는 list/None 시그니처가 유지되는지."""
    ctx = _make_ctx(tmp_path)
    overlays = [_sample_overlay()]
    save_phase2_overlays(ctx=ctx, batch_id="bw", overlays=overlays)
    assert load_phase2_overlays(ctx=ctx, batch_id="bw") == overlays
    assert load_phase2_overlays(ctx=ctx, batch_id="missing_one") is None
