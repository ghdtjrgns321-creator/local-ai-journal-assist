from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from src.detection.base import DetectionResult, RuleFlag
from src.detection.phase1_case_builder import build_phase1_case_result
from src.export.phase1_case_view import (
    build_phase1_case_drilldown,
    build_phase1_case_queue,
    resolve_phase1_case_result,
    summarize_phase1_case_result,
)


def _make_pipeline_result() -> SimpleNamespace:
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1", "DOC-2"],
            "posting_date": pd.to_datetime(["2026-04-30", "2026-04-28"]),
            "created_by": ["kim", "lee"],
            "business_process": ["P2P", "R2R"],
            "gl_account": ["111000", "410000"],
            "debit_amount": [20_000_000.0, 5_000_000.0],
            "credit_amount": [0.0, 0.0],
            "auxiliary_account_number": ["V001", None],
            "company_code": ["kr01", "kr01"],
            "document_type": ["KR", "SA"],
        }
    )
    details = pd.DataFrame(
        {
            "L1-05": [0.8, 0.0],
            "L1-07": [0.8, 0.0],
            "L3-04": [0.0, 0.6],
        },
        index=df.index,
    )
    detection_result = DetectionResult(
        track_name="layer_b",
        flagged_indices=[0, 1],
        scores=details.max(axis=1),
        rule_flags=[
            RuleFlag("L1-05", "SelfApproval", 4, 1, len(df)),
            RuleFlag("L1-07", "SkippedApproval", 4, 1, len(df)),
            RuleFlag("L3-04", "PeriodEndLarge", 3, 1, len(df)),
        ],
        details=details,
        metadata={},
    )
    phase1 = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={"phase1_case": {"top_n_cases": 50, "top_n_per_theme": 10}},
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )
    artifact_root = Path("C:/Users/ghdtj/workspace/portfolio/local-ai-assist/.tmp_phase1_case_view_tests")
    artifact_root.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_root / "phase1_case.json"
    artifact_path.write_text(phase1.model_dump_json(indent=2), encoding="utf-8")
    return SimpleNamespace(
        phase1_case_result=phase1,
        phase1_case_path=str(artifact_path),
        phase1_case_run_id=phase1.run_id,
        phase1_case_count=len(phase1.cases),
        phase1_top_theme_ids=[theme.theme_id for theme in phase1.theme_summaries[:3]],
    )


def test_summarize_phase1_case_result_returns_theme_summary() -> None:
    pipeline_result = _make_pipeline_result()

    summary = summarize_phase1_case_result(pipeline_result)

    assert summary["available"] is True
    assert summary["run_id"] == pipeline_result.phase1_case_run_id
    assert summary["case_count"] == pipeline_result.phase1_case_count
    assert summary["top_theme_labels"]
    assert summary["themes"]


def test_build_phase1_case_queue_and_drilldown_return_projection_rows() -> None:
    pipeline_result = _make_pipeline_result()

    queue = build_phase1_case_queue(pipeline_result, top_n=1)
    drilldown = build_phase1_case_drilldown(pipeline_result, queue[0]["case_id"])

    assert len(queue) == 1
    assert queue[0]["primary_theme_label"]
    assert queue[0]["representative_explanation"]
    assert drilldown is not None
    assert drilldown["case"]["case_id"] == queue[0]["case_id"]
    assert drilldown["documents"]
    assert drilldown["raw_rule_hits"]


def test_resolve_phase1_case_result_loads_from_artifact_when_memory_missing() -> None:
    pipeline_result = _make_pipeline_result()
    pipeline_result.phase1_case_result = None

    loaded = resolve_phase1_case_result(pipeline_result)

    assert loaded is not None
    assert loaded.run_id == pipeline_result.phase1_case_run_id
    assert loaded.cases


def test_resolve_phase1_case_result_returns_none_when_artifact_is_missing() -> None:
    pipeline_result = _make_pipeline_result()
    pipeline_result.phase1_case_result = None
    pipeline_result.phase1_case_path = str(
        Path("C:/Users/ghdtj/workspace/portfolio/local-ai-assist/.tmp_phase1_case_view_tests/missing.json")
    )

    loaded = resolve_phase1_case_result(pipeline_result)

    assert loaded is None
