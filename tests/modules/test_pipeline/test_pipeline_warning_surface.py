from __future__ import annotations

import pandas as pd
import pytest

# Why: pipeline 측 coverage warning 변환 및 format_phase1_rule_coverage 유틸이
# 아직 구현되지 않아 해당 테스트는 기능 구현 후 활성화한다.
pytest.skip(
    "pipeline coverage warning 변환 + format_phase1_rule_coverage 미구현",
    allow_module_level=True,
)

from src.detection.base import DetectionResult  # noqa: E402
from src.pipeline import AuditPipeline, format_phase1_rule_coverage  # noqa: E402,F401


def test_pipeline_surfaces_detector_coverage_warnings(monkeypatch, small_gl_df) -> None:
    detector_result = DetectionResult(
        track_name="layer_b",
        flagged_indices=[],
        scores=pd.Series(0.0, index=small_gl_df.index),
        rule_flags=[],
        details=pd.DataFrame(index=small_gl_df.index),
        metadata={
            "elapsed": 0.01,
            "skipped_rules": ["L4-01"],
            "coverage_issues": [
                {
                    "rule_id": "L4-01",
                    "kind": "missing_prerequisites",
                    "missing_inputs": ["amount_zscore"],
                    "affected_rows": int(len(small_gl_df)),
                }
            ],
        },
        warnings=["L4-01 실행 스킵: 필수 입력 누락 ['amount_zscore']"],
    )

    monkeypatch.setattr(
        AuditPipeline,
        "_run_detection",
        lambda self, df: ([detector_result], []),
    )
    monkeypatch.setattr(
        AuditPipeline,
        "_generate_features",
        lambda self, df: (df, []),
    )

    result = AuditPipeline(skip_db=True).redetect(small_gl_df)
    assert any("L4-01 실행 스킵" in warning for warning in result.warnings)
    assert any("[분석범위제한]" in warning for warning in result.warnings)


def test_format_phase1_rule_coverage_lists_skipped_and_partial_rules(small_gl_df) -> None:
    detector_result = DetectionResult(
        track_name="layer_c",
        flagged_indices=[],
        scores=pd.Series(0.0, index=small_gl_df.index),
        rule_flags=[],
        details=pd.DataFrame(index=small_gl_df.index),
        metadata={
            "elapsed": 0.01,
            "skipped_rules": ["L3-04"],
            "coverage_issues": [
                {
                    "rule_id": "L3-04",
                    "kind": "missing_prerequisites",
                    "missing_inputs": ["is_period_end"],
                    "affected_rows": int(len(small_gl_df)),
                },
                {
                    "rule_id": "L4-05",
                    "kind": "partial_input_coverage",
                    "subcheck": "rapid_approval",
                    "low_coverage_inputs": ["approval_date"],
                    "coverage_ratio": 0.7002,
                    "available_rows": 700,
                    "affected_rows": int(len(small_gl_df)),
                },
            ],
        },
        warnings=[],
    )

    rendered = format_phase1_rule_coverage([detector_result])
    assert "layer_c" in rendered
    assert "L3-04" in rendered
    assert "skipped" in rendered
    assert "is_period_end" in rendered
    assert "L4-05" in rendered
    assert "partial" in rendered
    assert "approval_date" in rendered
    assert "70.0%" in rendered
