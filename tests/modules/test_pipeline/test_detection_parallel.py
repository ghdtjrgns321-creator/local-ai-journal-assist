"""탐지기 병렬 실행 헬퍼 + 프로파일링 단위 테스트 (묶음 2)."""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pytest

from src.detection.base import BaseDetector, DetectionResult
from src.pipeline import (
    _run_detectors_parallel,
    collect_detection_profile,
    format_detection_profile,
)


class _FakeDetector(BaseDetector):
    """테스트용 더미 탐지기 — 지정 시간만큼 sleep 후 고정 결과 반환."""

    def __init__(self, track: str, sleep_sec: float = 0.0, fail: bool = False):
        super().__init__(settings=None)
        self._track = track
        self._sleep = sleep_sec
        self._fail = fail

    @property
    def track_name(self) -> str:
        return self._track

    def detect(self, df: pd.DataFrame) -> DetectionResult:
        if self._sleep > 0:
            time.sleep(self._sleep)
        if self._fail:
            raise RuntimeError(f"{self._track} intentional failure")
        scores = pd.Series(0.0, index=df.index, name=self._track)
        return DetectionResult(
            track_name=self._track,
            flagged_indices=[],
            scores=scores,
            rule_flags=[],
            details=pd.DataFrame({self._track: scores}),
            metadata={"elapsed": self._sleep},
            warnings=[],
        )


@pytest.fixture()
def sample_df() -> pd.DataFrame:
    return pd.DataFrame({"x": np.arange(10)})


class TestRunDetectorsParallel:
    def test_sequential_mode_preserves_order(self, sample_df):
        detectors = [
            _FakeDetector("a"),
            _FakeDetector("b"),
            _FakeDetector("c"),
        ]
        results, warns = _run_detectors_parallel(
            detectors, sample_df, max_workers=None,
        )
        assert [r.track_name for r in results] == ["a", "b", "c"]
        assert warns == []

    def test_parallel_runner_sets_detector_profile_metadata(self, sample_df):
        detectors = [_FakeDetector("layer_a")]
        results, _ = _run_detectors_parallel(detectors, sample_df, max_workers=None)
        result = results[0]
        assert result.metadata["display_name"] == "Layer A"
        assert result.metadata["maturity"] == "production"
        assert result.metadata["default_enabled"] is True
        assert result.metadata["activation_requirements"] == []
        assert result.metadata["run_status"] == "executed"

    def test_parallel_mode_preserves_input_order(self, sample_df):
        # Why: 병렬 완료 순서가 달라도 입력 순서를 보장해야 downstream 로직이 안전
        detectors = [
            _FakeDetector("slow", sleep_sec=0.05),
            _FakeDetector("fast", sleep_sec=0.0),
            _FakeDetector("medium", sleep_sec=0.02),
        ]
        results, _ = _run_detectors_parallel(
            detectors, sample_df, max_workers=4,
        )
        assert [r.track_name for r in results] == ["slow", "fast", "medium"]

    def test_parallel_faster_than_sequential(self, sample_df):
        # Why: 3개 탐지기 × 0.1초 sleep → 순차 0.3초, 병렬 0.1~0.15초
        detectors = [
            _FakeDetector(f"det_{i}", sleep_sec=0.1) for i in range(3)
        ]
        t0 = time.perf_counter()
        _run_detectors_parallel(detectors, sample_df, max_workers=None)
        seq_time = time.perf_counter() - t0

        t0 = time.perf_counter()
        _run_detectors_parallel(detectors, sample_df, max_workers=4)
        par_time = time.perf_counter() - t0
        # 병렬이 순차의 절반 이하여야 의미 있음
        assert par_time < seq_time * 0.7

    def test_failed_detector_isolated(self, sample_df):
        detectors = [
            _FakeDetector("ok1"),
            _FakeDetector("bad", fail=True),
            _FakeDetector("ok2"),
        ]
        results, warns = _run_detectors_parallel(
            detectors, sample_df, max_workers=4,
        )
        # 실패한 탐지기는 결과에서 빠지고 warns에 기록
        track_names = {r.track_name for r in results}
        assert track_names == {"ok1", "ok2"}
        assert any("bad" in w for w in warns)

    def test_progress_callback_called_per_detector(self, sample_df):
        detectors = [_FakeDetector(f"d_{i}") for i in range(4)]
        calls: list[tuple[int, int, str]] = []
        _run_detectors_parallel(
            detectors, sample_df, max_workers=None,
            progress_callback=lambda c, t, n: calls.append((c, t, n)),
        )
        assert len(calls) == 4
        assert calls[-1][0] == 4  # completed == total
        assert all(c[1] == 4 for c in calls)  # total 일관성

    def test_progress_callback_exception_isolated(self, sample_df):
        # Why: callback이 예외를 던져도 탐지는 정상 완료되어야 함
        detectors = [_FakeDetector(f"d_{i}") for i in range(3)]

        def bad_callback(c, t, n):
            raise ValueError("ui error")

        results, _ = _run_detectors_parallel(
            detectors, sample_df, max_workers=None,
            progress_callback=bad_callback,
        )
        assert len(results) == 3

    def test_empty_detectors(self, sample_df):
        results, warns = _run_detectors_parallel(
            [], sample_df, max_workers=4,
        )
        assert results == []
        assert warns == []


class TestCollectDetectionProfile:
    def test_basic_profile(self):
        results = [
            DetectionResult(
                track_name="fast", flagged_indices=[],
                scores=pd.Series(dtype=float), rule_flags=[],
                details=pd.DataFrame(),
                metadata={"elapsed": 0.5},
            ),
            DetectionResult(
                track_name="slow", flagged_indices=[],
                scores=pd.Series(dtype=float), rule_flags=[],
                details=pd.DataFrame(),
                metadata={"elapsed": 2.0},
            ),
        ]
        profile = collect_detection_profile(results)
        assert profile == {"fast": 0.5, "slow": 2.0}

    def test_missing_elapsed_defaults_zero(self):
        results = [
            DetectionResult(
                track_name="no_meta", flagged_indices=[],
                scores=pd.Series(dtype=float), rule_flags=[],
                details=pd.DataFrame(),
                metadata={},
            ),
        ]
        profile = collect_detection_profile(results)
        assert profile["no_meta"] == 0.0

    def test_format_profile_table(self):
        profile = {"a": 1.0, "b": 3.0, "c": 6.0}
        text = format_detection_profile(profile)
        # 가장 느린 c가 맨 위 (내림차순 정렬)
        assert "c" in text.split("\n")[2]
        assert "Total" in text

    def test_format_empty_profile(self):
        assert "없음" in format_detection_profile({})
