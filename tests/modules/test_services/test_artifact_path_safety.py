"""`artifact_path_safety` 의 batch_id 검증과 경로 합성 계약 검증.

Why: PHASE2 case set / overlay 파일은 `<engagement_dir>` 하위에 batch_id 를
이름으로 사용한다. path traversal · separator 주입을 막아야 한다.
invariant #6 — `safe_batch_artifact_file` 은 S1 에서 미사용, 테스트만 유지.
"""

from __future__ import annotations

from pathlib import Path

from src.services.artifact_path_safety import (
    is_safe_batch_id,
    safe_batch_artifact_dir,
    safe_batch_artifact_file,
)


def test_safe_batch_id_alphanumeric():
    assert is_safe_batch_id("batch001")
    assert is_safe_batch_id("ABC123")


def test_safe_batch_id_with_dot_dash_underscore():
    # `.`, `-`, `_` 는 허용 character set 에 포함.
    assert is_safe_batch_id("batch.001")
    assert is_safe_batch_id("batch-001")
    assert is_safe_batch_id("batch_001")
    assert is_safe_batch_id("v1.0.0-rc.1")


def test_safe_batch_id_rejects_forward_slash():
    # path separator 차단.
    assert not is_safe_batch_id("batch/001")


def test_safe_batch_id_rejects_backslash():
    # Windows separator 차단.
    assert not is_safe_batch_id("batch\\001")


def test_safe_batch_id_rejects_dot_dot():
    # parent traversal 차단.
    assert not is_safe_batch_id("..")


def test_safe_batch_id_rejects_single_dot():
    # 현재 디렉토리 self-reference 차단.
    assert not is_safe_batch_id(".")


def test_safe_batch_id_rejects_empty():
    assert not is_safe_batch_id("")


def test_safe_batch_id_rejects_over_128_chars():
    # 길이 상한 128 초과 거부.
    assert is_safe_batch_id("a" * 128)
    assert not is_safe_batch_id("a" * 129)


def test_safe_batch_artifact_dir_correct_path(tmp_path: Path):
    # <engagement_dir>/phase2_cases/<batch_id>/ 합성.
    result = safe_batch_artifact_dir(tmp_path, "batch001")
    assert result == tmp_path / "phase2_cases" / "batch001"


def test_safe_batch_artifact_dir_returns_none_for_unsafe_batch(tmp_path: Path):
    assert safe_batch_artifact_dir(tmp_path, "../escape") is None
    assert safe_batch_artifact_dir(tmp_path, "with/slash") is None
    assert safe_batch_artifact_dir(tmp_path, "") is None


def test_safe_batch_artifact_file_default_json_suffix(tmp_path: Path):
    # default `.json` suffix 로 phase2_overlays/<batch_id>.json 합성.
    result = safe_batch_artifact_file(tmp_path, "batch001")
    assert result == tmp_path / "phase2_overlays" / "batch001.json"


def test_safe_batch_artifact_file_rejects_other_suffix(tmp_path: Path):
    # whitelist 외 suffix 거부.
    assert safe_batch_artifact_file(tmp_path, "batch001", suffix=".txt") is None
    assert safe_batch_artifact_file(tmp_path, "batch001", suffix=".jsonl") is None
    assert safe_batch_artifact_file(tmp_path, "batch001", suffix="") is None


def test_safe_batch_artifact_file_returns_none_for_unsafe_batch(tmp_path: Path):
    assert safe_batch_artifact_file(tmp_path, "../escape") is None
    assert safe_batch_artifact_file(tmp_path, "with/slash") is None
    assert safe_batch_artifact_file(tmp_path, "") is None
