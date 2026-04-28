"""ML Pipeline ?듯빀 ?뚯뒪??

Cold Start / ML ?ы븿 / Stacking / 媛以묒튂 ?먮룞 ?꾪솚??寃利?
pipeline.py??_try_ml_detection, _try_stacking_ensemble, _select_weights ???
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from src.detection.constants import LAYER_WEIGHTS_WITH_ML
from src.pipeline import AuditPipeline
from tests.modules.test_detection.conftest import make_detection_result

# ?? _select_weights ?⑥쐞 ?뚯뒪????????????????????????????????


class TestWeightSelection:
    """ML ?좊Т???곕Ⅸ 媛以묒튂 ?먮룞 ?꾪솚."""

    def test_weights_with_ml(self):
        """ml_* ?몃옓 議댁옱 ??LAYER_WEIGHTS_WITH_ML 諛섑솚."""
        results = [
            make_detection_result("layer_a"),
            make_detection_result("ml_supervised"),
        ]
        weights = AuditPipeline._select_weights(results)
        assert weights == LAYER_WEIGHTS_WITH_ML

    def test_weights_without_ml(self):
        """ml_* ?놁쓬 ??None (湲곕낯 LAYER_WEIGHTS)."""
        results = [
            make_detection_result("layer_a"),
            make_detection_result("layer_b"),
        ]
        assert AuditPipeline._select_weights(results) is None

    def test_weights_with_variance_only(self):
        """layer_d only does not override row-level weights."""
        results = [
            make_detection_result("layer_a"),
            make_detection_result("layer_d"),
        ]
        assert AuditPipeline._select_weights(results) is None

    def test_ml_takes_priority_over_variance(self):
        """ml_* + layer_d ?숈떆 議댁옱 ??ML 媛以묒튂 ?곗꽑."""
        results = [
            make_detection_result("layer_a"),
            make_detection_result("layer_d"),
            make_detection_result("ml_unsupervised"),
        ]
        weights = AuditPipeline._select_weights(results)
        assert weights == LAYER_WEIGHTS_WITH_ML


# ?? Cold Start ?뚯뒪??????????????????????????????????????????


class TestMLColdStart:
    """紐⑤뜽 ?놁쓣 ??graceful degradation."""

    def test_anonymous_skips_ml(self):
        """anonymous context ??ML ?몃옓 0媛?"""
        ctx = MagicMock(is_anonymous=True)
        pipeline = AuditPipeline.__new__(AuditPipeline)
        pipeline._ctx = ctx
        pipeline._settings = MagicMock()

        result = pipeline._try_ml_detection(pd.DataFrame({"a": [1, 2, 3]}))
        assert result == []

    def test_no_model_returns_empty(self):
        """ModelRegistry 濡쒕뱶 ?ㅽ뙣 ??鍮?由ъ뒪??"""
        ctx = MagicMock(is_anonymous=False)
        pipeline = AuditPipeline.__new__(AuditPipeline)
        pipeline._ctx = ctx
        pipeline._settings = MagicMock()

        # Why: lazy import?대?濡??먮낯 紐⑤뱢??patch
        with patch(
            "src.preprocessing.model_registry.ModelRegistry",
            side_effect=Exception("no registry"),
        ):
            result = pipeline._try_ml_detection(pd.DataFrame({"a": [1]}))
        assert result == []

    def test_anonymous_skips_stacking(self):
        """anonymous context ??stacking None."""
        ctx = MagicMock(is_anonymous=True)
        pipeline = AuditPipeline.__new__(AuditPipeline)
        pipeline._ctx = ctx
        pipeline._settings = MagicMock()

        result = pipeline._try_stacking_ensemble([], pd.DataFrame({"a": [1]}))
        assert result is None

    def test_stacking_no_model_returns_none(self):
        """Stacking 紐⑤뜽 ?놁쓬 ??None (湲곗〈 媛以묓빀 ?ъ슜)."""
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

