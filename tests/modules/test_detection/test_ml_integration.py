"""ML Pipeline 통합 테스트.

Cold Start / ML 포함 / Stacking / 가중치 자동 전환을 검증.
pipeline.py의 _try_ml_detection, _try_stacking_ensemble, _select_weights 대상.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.detection.base import DetectionResult
from src.detection.constants import LAYER_WEIGHTS_WITH_ML, LAYER_WEIGHTS_WITH_PRIOR
from src.pipeline import AuditPipeline
from tests.modules.test_detection.conftest import make_detection_result


# ── _select_weights 단위 테스트 ──────────────────────────────


class TestWeightSelection:
    """ML 유무에 따른 가중치 자동 전환."""

    def test_weights_with_ml(self):
        """ml_* 트랙 존재 → LAYER_WEIGHTS_WITH_ML 반환."""
        results = [
            make_detection_result("layer_a"),
            make_detection_result("ml_supervised"),
        ]
        weights = AuditPipeline._select_weights(results)
        assert weights == LAYER_WEIGHTS_WITH_ML

    def test_weights_without_ml(self):
        """ml_* 없음 → None (기본 LAYER_WEIGHTS)."""
        results = [
            make_detection_result("layer_a"),
            make_detection_result("layer_b"),
        ]
        assert AuditPipeline._select_weights(results) is None

    def test_weights_with_variance_only(self):
        """layer_d만 있으면 LAYER_WEIGHTS_WITH_PRIOR."""
        results = [
            make_detection_result("layer_a"),
            make_detection_result("layer_d"),
        ]
        weights = AuditPipeline._select_weights(results)
        assert weights == LAYER_WEIGHTS_WITH_PRIOR

    def test_ml_takes_priority_over_variance(self):
        """ml_* + layer_d 동시 존재 → ML 가중치 우선."""
        results = [
            make_detection_result("layer_a"),
            make_detection_result("layer_d"),
            make_detection_result("ml_unsupervised"),
        ]
        weights = AuditPipeline._select_weights(results)
        assert weights == LAYER_WEIGHTS_WITH_ML


# ── Cold Start 테스트 ────────────────────────────────────────


class TestMLColdStart:
    """모델 없을 때 graceful degradation."""

    def test_anonymous_skips_ml(self):
        """anonymous context → ML 트랙 0개."""
        ctx = MagicMock(is_anonymous=True)
        pipeline = AuditPipeline.__new__(AuditPipeline)
        pipeline._ctx = ctx
        pipeline._settings = MagicMock()

        result = pipeline._try_ml_detection(pd.DataFrame({"a": [1, 2, 3]}))
        assert result == []

    def test_no_model_returns_empty(self):
        """ModelRegistry 로드 실패 → 빈 리스트."""
        ctx = MagicMock(is_anonymous=False)
        pipeline = AuditPipeline.__new__(AuditPipeline)
        pipeline._ctx = ctx
        pipeline._settings = MagicMock()

        # Why: lazy import이므로 원본 모듈을 patch
        with patch(
            "src.preprocessing.model_registry.ModelRegistry",
            side_effect=Exception("no registry"),
        ):
            result = pipeline._try_ml_detection(pd.DataFrame({"a": [1]}))
        assert result == []

    def test_anonymous_skips_stacking(self):
        """anonymous context → stacking None."""
        ctx = MagicMock(is_anonymous=True)
        pipeline = AuditPipeline.__new__(AuditPipeline)
        pipeline._ctx = ctx
        pipeline._settings = MagicMock()

        result = pipeline._try_stacking_ensemble([], pd.DataFrame({"a": [1]}))
        assert result is None

    def test_stacking_no_model_returns_none(self):
        """Stacking 모델 없음 → None (기존 가중합 사용)."""
        ctx = MagicMock(is_anonymous=False)
        pipeline = AuditPipeline.__new__(AuditPipeline)
        pipeline._ctx = ctx
        pipeline._settings = MagicMock()

        with patch(
            "src.preprocessing.model_registry.ModelRegistry",
            side_effect=Exception("no registry"),
        ):
            result = pipeline._try_stacking_ensemble([], pd.DataFrame({"a": [1]}))
        assert result is None
