"""시퀀스 빌더 — 2D 피처 행렬을 사용자-시간 기반 3D 윈도우로 변환.

Why: BiLSTM은 시퀀스 입력이 필요하다. 동일 입력자(created_by)의
시간순 전표를 슬라이딩 윈도우로 묶어 '반복 패턴'을 학습시킨다.
라벨은 윈도우 마지막 항목(target step)의 값을 사용한다 (방식 A).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class SequenceResult:
    """시퀀스 빌딩 결과."""

    X_seq: np.ndarray  # (n_windows, seq_len, n_features) float32
    y_seq: np.ndarray  # (n_windows,) int64 — 마지막 항목의 라벨
    mask: np.ndarray  # (n_windows, seq_len) bool — True=유효, False=패딩
    original_indices: np.ndarray  # (n_windows,) int — 마지막 항목의 원본 위치 인덱스


def build_sequences(
    X: np.ndarray,
    y: np.ndarray | None,
    user_ids: np.ndarray,
    timestamps: np.ndarray,
    seq_len: int = 16,
    stride: int = 1,
) -> SequenceResult:
    """2D 피처 행렬 → 사용자별 시간순 슬라이딩 윈도우 3D 변환.

    Args:
        X: (N, n_features) 전처리 완료 피처 행렬
        y: (N,) 라벨. None이면 추론 모드 (y_seq=0)
        user_ids: (N,) 입력자 ID (시퀀스 그룹 키)
        timestamps: (N,) 시간 정보 (정렬 기준, np.datetime64 또는 숫자)
        seq_len: 윈도우 길이 (기본 16)
        stride: 슬라이딩 보폭 (기본 1)

    Returns:
        SequenceResult — X_seq, y_seq, mask, original_indices
    """
    X = np.asarray(X, dtype=np.float32)
    n_samples, n_features = X.shape

    if n_samples == 0:
        return _empty_result(n_features, seq_len)

    # Why: 사용자별 그룹 → 시간순 정렬을 위해 고유 사용자 목록 추출
    unique_users = np.unique(user_ids)

    windows_X: list[np.ndarray] = []
    windows_y: list[int] = []
    windows_mask: list[np.ndarray] = []
    windows_orig_idx: list[int] = []

    for user in unique_users:
        user_mask = user_ids == user
        user_positions = np.where(user_mask)[0]  # 원본 배열의 위치 인덱스

        # Why: 시간순 정렬 — tie-break는 원본 위치 순서 유지
        ts_values = timestamps[user_positions]
        sort_order = np.argsort(ts_values, kind="stable")
        sorted_positions = user_positions[sort_order]

        user_X = X[sorted_positions]
        user_y = y[sorted_positions] if y is not None else None
        n = len(user_X)

        if n >= seq_len:
            # 정상: 슬라이딩 윈도우
            _build_sliding_windows(
                user_X,
                user_y,
                sorted_positions,
                seq_len,
                stride,
                n_features,
                windows_X,
                windows_y,
                windows_mask,
                windows_orig_idx,
            )
        else:
            # 부족: 앞쪽 제로 패딩 + mask=False
            _build_padded_window(
                user_X,
                user_y,
                sorted_positions,
                seq_len,
                n_features,
                windows_X,
                windows_y,
                windows_mask,
                windows_orig_idx,
            )

    if not windows_X:
        return _empty_result(n_features, seq_len)

    return SequenceResult(
        X_seq=np.stack(windows_X),
        y_seq=np.array(windows_y, dtype=np.int64),
        mask=np.stack(windows_mask),
        original_indices=np.array(windows_orig_idx, dtype=np.intp),
    )


def _build_sliding_windows(
    user_X: np.ndarray,
    user_y: np.ndarray | None,
    sorted_positions: np.ndarray,
    seq_len: int,
    stride: int,
    n_features: int,
    out_X: list,
    out_y: list,
    out_mask: list,
    out_idx: list,
) -> None:
    """seq_len 이상인 사용자의 슬라이딩 윈도우 생성."""
    n = len(user_X)
    for start in range(0, n - seq_len + 1, stride):
        end = start + seq_len
        out_X.append(user_X[start:end])
        # Why: 방식 A — 마지막 항목의 라벨이 시퀀스 라벨
        out_y.append(int(user_y[end - 1]) if user_y is not None else 0)
        out_mask.append(np.ones(seq_len, dtype=bool))
        out_idx.append(int(sorted_positions[end - 1]))


def _build_padded_window(
    user_X: np.ndarray,
    user_y: np.ndarray | None,
    sorted_positions: np.ndarray,
    seq_len: int,
    n_features: int,
    out_X: list,
    out_y: list,
    out_mask: list,
    out_idx: list,
) -> None:
    """seq_len 미만 사용자의 제로 패딩 윈도우 생성 (1개)."""
    n = len(user_X)
    pad_len = seq_len - n

    # Why: 앞쪽을 0으로 채워 attention이 유효한 뒤쪽에만 집중하도록 유도
    padded_X = np.zeros((seq_len, n_features), dtype=np.float32)
    padded_X[pad_len:] = user_X

    mask = np.zeros(seq_len, dtype=bool)
    mask[pad_len:] = True

    out_X.append(padded_X)
    out_y.append(int(user_y[-1]) if user_y is not None else 0)
    out_mask.append(mask)
    out_idx.append(int(sorted_positions[-1]))


def _empty_result(n_features: int, seq_len: int) -> SequenceResult:
    """빈 입력에 대한 빈 결과 반환."""
    return SequenceResult(
        X_seq=np.empty((0, seq_len, n_features), dtype=np.float32),
        y_seq=np.empty(0, dtype=np.int64),
        mask=np.empty((0, seq_len), dtype=bool),
        original_indices=np.empty(0, dtype=np.intp),
    )
