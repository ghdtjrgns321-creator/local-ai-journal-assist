"""PHASE2 case overlay 영속화 (engagement 별 JSON 파일).

Why: `phase2_case_overlays` 는 `phase2_inference_service` 가 메모리에 attach 하지만,
DB 의 `upload_batch` 메타 에는 저장되지 않는다. 결과적으로 dashboard 가 새로고침되거나
같은 batch 를 재로드할 때 overlay 가 사라져 KPI · 검토 Lane 이 빈 상태가 된다.

본 모듈은 engagement 폴더에 JSON 파일로 overlay 를 저장/복원한다.
경로: ``<engagement_dir>/phase2_overlays/<batch_id>.json``.

Read/write 는 best-effort 다. 파일이 없거나 손상되면 ``None`` 을 반환할 뿐,
inference 실패로 이어지지 않는다.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0"
_OVERLAY_DIR_NAME = "phase2_overlays"


# Why: load_phase2_overlay_status 가 반환하는 진단 상태. UI 가 status 별로 안내 메시지와
#      next action 을 분기한다 (D5/D6/D7/D12/D14 등). 새 status 추가 시 tab_phase2 의
#      메시지 분기도 동시에 갱신해야 한다.
class OverlayStatus:
    LOADED = "loaded"
    MISSING = "missing"
    SCHEMA_MISMATCH = "schema_mismatch"
    BATCH_ID_MISMATCH = "batch_id_mismatch"
    TRAINING_REPORT_MISMATCH = "training_report_mismatch"
    INVALID_PAYLOAD = "invalid_payload"
    PARSE_ERROR = "parse_error"
    UNSAFE_BATCH_ID = "unsafe_batch_id"
    CTX_MISSING = "ctx_missing"


@dataclass(frozen=True)
class OverlayLoadResult:
    """phase2 overlay 로더 진단 결과.

    Args:
        status: ``OverlayStatus`` 상수 중 하나.
        overlays: ``status == LOADED`` 인 경우에만 비어있지 않을 수 있다.
        message: 로깅·UI 진단용 한 줄 영어 메시지 (사용자 한국어 메시지는 UI 가 별도 매핑).
        path: 시도한 overlay 파일 경로 (없으면 None).
        metadata: 추가 진단 데이터 (expected/got 값 등).
    """

    status: str
    overlays: list[dict[str, Any]] | None = None
    message: str = ""
    path: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# Why: 파일명에 그대로 사용되므로 path traversal · separator 를 차단한다.
#      batch_id 는 시스템 내부 식별자(UUID/타임스탬프 기반)라 영숫자·_·-·. 만 허용.
_SAFE_BATCH_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


def _is_safe_batch_id(batch_id: str) -> bool:
    if not batch_id or len(batch_id) > 128:
        return False
    if batch_id in {".", ".."}:
        return False
    return bool(_SAFE_BATCH_ID_PATTERN.fullmatch(batch_id))


def _overlay_dir(ctx: Any) -> Path | None:
    """`ctx.db_path` 의 parent 를 engagement 폴더로 간주.

    ctx 가 None 이거나 db_path attribute 가 없으면 ``None`` 을 반환한다.
    """
    if ctx is None:
        return None
    db_path = getattr(ctx, "db_path", None)
    if db_path is None:
        return None
    try:
        return Path(db_path).parent / _OVERLAY_DIR_NAME
    except (TypeError, ValueError):
        return None


def _overlay_path(ctx: Any, batch_id: str) -> Path | None:
    """`<engagement_dir>/phase2_overlays/<batch_id>.json` 경로.

    Why: batch_id 가 path separator(``/`` ``\\``) 나 parent traversal(``..``)
    을 포함하면 None 반환. helper 가 public 이므로 호출자 신뢰에만 의존하지 않는다.
    """
    base = _overlay_dir(ctx)
    if base is None or not _is_safe_batch_id(batch_id):
        return None
    return base / f"{batch_id}.json"


def save_phase2_overlays(
    *,
    ctx: Any,
    batch_id: str,
    overlays: list[dict[str, Any]],
    phase2_training_report_id: str | None = None,
    phase2_partition: str | None = None,
) -> Path | None:
    """Overlay 리스트를 JSON 파일로 저장. 실패 시 None 반환 (best-effort).

    Args:
        ctx: ``db_path`` attribute 를 가진 CompanyContext.
        batch_id: 저장 대상 batch.
        overlays: ``Phase2CaseOverlay.to_dict()`` 결과 리스트.
        phase2_training_report_id: 추적용 메타.
        phase2_partition: 추적용 메타 (예: ``"2024"`` / ``"전체"``).

    Returns:
        저장 성공 시 파일 경로, 실패/스킵 시 None.
    """
    target = _overlay_path(ctx, batch_id)
    if target is None:
        return None
    payload = {
        "schema_version": SCHEMA_VERSION,
        "batch_id": batch_id,
        "written_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "phase2_training_report_id": phase2_training_report_id,
        "phase2_partition": phase2_partition,
        "overlays": list(overlays) if overlays else [],
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return target
    except (OSError, TypeError, ValueError):
        logger.warning(
            "phase2 overlay 저장 실패 — batch_id=%s path=%s",
            batch_id,
            target,
            exc_info=True,
        )
        return None


def load_phase2_overlay_status(
    *,
    ctx: Any,
    batch_id: str,
    expected_training_report_id: str | None = None,
) -> OverlayLoadResult:
    """진단 정보가 포함된 overlay 로딩 결과를 반환.

    UI 가 ``status`` 별로 분기해 D5/D6/D7/D12/D14 메시지를 다르게 표시한다.
    경로/시도 결과/메타데이터를 함께 담아 추적 가능하게 한다.

    Args:
        expected_training_report_id: 호출자가 비교 기준을 넘기면 일치 강제. None 이면
            검증 스킵 (CLI / 마이그레이션 / 테스트 호환).
    """
    # 1) ctx 존재성
    if ctx is None:
        return OverlayLoadResult(
            status=OverlayStatus.CTX_MISSING,
            message="ctx is None — engagement directory cannot be resolved",
        )

    # 2) batch_id 안전성 (path traversal / separator 방지)
    if not _is_safe_batch_id(batch_id):
        return OverlayLoadResult(
            status=OverlayStatus.UNSAFE_BATCH_ID,
            message="batch_id is empty or contains unsafe characters",
            metadata={"batch_id": str(batch_id) if batch_id else ""},
        )

    target = _overlay_path(ctx, batch_id)
    if target is None:
        # ctx 는 있지만 db_path 가 없어 경로 해석 실패.
        return OverlayLoadResult(
            status=OverlayStatus.CTX_MISSING,
            message="ctx.db_path is missing — overlay directory cannot be resolved",
        )

    # 3) 파일 존재성
    if not target.exists():
        return OverlayLoadResult(
            status=OverlayStatus.MISSING,
            message="overlay file not found",
            path=target,
        )

    # 4) JSON 파싱
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("phase2 overlay JSON 파싱 실패 — path=%s", target, exc_info=True)
        return OverlayLoadResult(
            status=OverlayStatus.PARSE_ERROR,
            message=f"failed to read/parse overlay JSON: {exc}",
            path=target,
        )

    if not isinstance(payload, dict):
        return OverlayLoadResult(
            status=OverlayStatus.INVALID_PAYLOAD,
            message="payload root is not a JSON object",
            path=target,
        )

    # 5) schema 검증
    schema = str(payload.get("schema_version") or "")
    if schema != SCHEMA_VERSION:
        logger.warning(
            "phase2 overlay schema 불일치 — expected=%s got=%s path=%s",
            SCHEMA_VERSION,
            schema,
            target,
        )
        return OverlayLoadResult(
            status=OverlayStatus.SCHEMA_MISMATCH,
            message="schema_version mismatch",
            path=target,
            metadata={"expected": SCHEMA_VERSION, "got": schema},
        )

    # 6) batch_id 일치
    persisted_batch_id = str(payload.get("batch_id") or "")
    if persisted_batch_id != batch_id:
        logger.warning(
            "phase2 overlay batch_id 불일치 — expected=%s got=%s path=%s",
            batch_id,
            persisted_batch_id,
            target,
        )
        return OverlayLoadResult(
            status=OverlayStatus.BATCH_ID_MISMATCH,
            message="payload batch_id does not match requested batch_id",
            path=target,
            metadata={"expected": batch_id, "got": persisted_batch_id},
        )

    # 7) training_report_id 일치 (재학습 stale 차단)
    if expected_training_report_id:
        persisted_report_id = str(payload.get("phase2_training_report_id") or "")
        if persisted_report_id and persisted_report_id != expected_training_report_id:
            logger.warning(
                "phase2 overlay training_report_id 불일치 — expected=%s got=%s path=%s",
                expected_training_report_id,
                persisted_report_id,
                target,
            )
            return OverlayLoadResult(
                status=OverlayStatus.TRAINING_REPORT_MISMATCH,
                message="phase2_training_report_id mismatch — retrained model",
                path=target,
                metadata={
                    "expected": expected_training_report_id,
                    "got": persisted_report_id,
                },
            )

    # 8) overlays list 유효성
    overlays = payload.get("overlays")
    if not isinstance(overlays, list):
        return OverlayLoadResult(
            status=OverlayStatus.INVALID_PAYLOAD,
            message="`overlays` key is missing or not a list",
            path=target,
        )

    return OverlayLoadResult(
        status=OverlayStatus.LOADED,
        overlays=overlays,
        message="loaded",
        path=target,
        metadata={
            "phase2_training_report_id": payload.get("phase2_training_report_id"),
            "phase2_partition": payload.get("phase2_partition"),
            "written_at": payload.get("written_at"),
        },
    )


def load_phase2_overlays(
    *,
    ctx: Any,
    batch_id: str,
    expected_training_report_id: str | None = None,
) -> list[dict[str, Any]] | None:
    """Backward-compat: list/None 반환 thin wrapper.

    Why: 신규 호출자는 ``load_phase2_overlay_status`` 로 진단 정보까지 받지만,
    기존 호출자(테스트 / dashboard 기존 경로)는 list/None 시그니처를 유지한다.
    """
    result = load_phase2_overlay_status(
        ctx=ctx,
        batch_id=batch_id,
        expected_training_report_id=expected_training_report_id,
    )
    if result.status != OverlayStatus.LOADED:
        return None
    return result.overlays
