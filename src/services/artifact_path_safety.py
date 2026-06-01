"""PHASE2 artifact 경로 합성 — batch_id 안전성 검증 + 디렉토리/파일 경로.

Why: PHASE2 case set 디렉토리(`<engagement_dir>/phase2_cases/<batch_id>/`) 와
overlay 파일(`<engagement_dir>/phase2_overlays/<batch_id>.json`) 은 batch_id
를 그대로 파일시스템 이름에 사용한다. path traversal · separator 주입을
차단하려면 단일 검증 함수가 필요하다. `phase2_overlay_store.py` 의 private
`_is_safe_batch_id` 를 PR-pre-1 에서 본 모듈로 통합 마이그레이션한다.

`safe_batch_artifact_file` 은 S1 (phase2-native-cases) 범위에서 case store 가
호출하지 않는다. overlay store 마이그레이션(PR-pre-1)에서
`phase2_overlay_store.py` 가 private 헬퍼 대신 본 함수를 호출하도록 전환할 때
활성화된다. S1 에서는 단위 테스트만 유지하고 사용처는 없다.
"""

from __future__ import annotations

import re
from pathlib import Path

# Why: batch_id 는 시스템 내부 식별자(UUID/타임스탬프 기반) 라 영숫자·_·-·. 만
#      허용. `/`, `\`, `..` 같은 path traversal 요소는 모두 거부.
SAFE_BATCH_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")

# Why: phase2_overlays/<batch_id>.json 은 JSON payload 전용. 다른 suffix 는
#      포맷 가정이 다르므로 거부한다.
_ALLOWED_FILE_SUFFIXES = frozenset({".json"})

_MAX_BATCH_ID_LEN = 128
_CASE_DIR_NAME = "phase2_cases"
_OVERLAY_DIR_NAME = "phase2_overlays"


def is_safe_batch_id(batch_id: str) -> bool:
    """batch_id 가 파일시스템에 안전한지 검사한다.

    Args:
        batch_id: 검증 대상 문자열.

    Returns:
        길이 ∈ [1, 128], `.`/`..` 제외, 영숫자·_·-·. 만 사용했을 때 True.
    """
    if not batch_id or len(batch_id) > _MAX_BATCH_ID_LEN:
        return False
    if batch_id in {".", ".."}:
        return False
    return bool(SAFE_BATCH_ID_PATTERN.fullmatch(batch_id))


def safe_batch_artifact_dir(engagement_dir: Path, batch_id: str) -> Path | None:
    """`<engagement_dir>/phase2_cases/<batch_id>/` 경로를 안전 검증 후 반환.

    Args:
        engagement_dir: engagement 루트 디렉토리.
        batch_id: 합성 대상 batch.

    Returns:
        검증 통과 시 합성 경로, 실패 시 None.
    """
    if not is_safe_batch_id(batch_id):
        return None
    return Path(engagement_dir) / _CASE_DIR_NAME / batch_id


def safe_batch_artifact_file(
    engagement_dir: Path, batch_id: str, suffix: str = ".json"
) -> Path | None:
    """`<engagement_dir>/phase2_overlays/<batch_id>{suffix}` 경로를 안전 검증 후 반환.

    NOTE: S1 (phase2-native-cases) 범위에서 case store 가 호출하지 않는다.
    overlay store 마이그레이션(PR-pre-1)에서 `phase2_overlay_store.py` 가
    private `_is_safe_batch_id` 대신 본 함수를 호출하도록 전환할 때 활성화된다.
    S1 에서는 본 함수의 단위 테스트만 유지하고 사용처는 없다.

    Args:
        engagement_dir: engagement 루트 디렉토리.
        batch_id: 합성 대상 batch.
        suffix: 파일 확장자 (whitelist `.json` 만 허용).

    Returns:
        검증 통과 시 합성 경로, 실패 시 None.
    """
    if not is_safe_batch_id(batch_id):
        return None
    if suffix not in _ALLOWED_FILE_SUFFIXES:
        return None
    return Path(engagement_dir) / _OVERLAY_DIR_NAME / f"{batch_id}{suffix}"
