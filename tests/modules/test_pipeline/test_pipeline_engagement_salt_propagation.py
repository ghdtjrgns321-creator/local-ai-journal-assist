"""AuditPipeline._build_phase1_case_artifact 의 engagement_salt 전파 회귀 가드.

Why: S3.next Phase B Followup — pipeline 이 PHASE1 builder 호출 시
``engagement_salt = f"{ctx.engagement_id}|{batch_id}"`` 를 전달해야
RawRuleHitRef hash 필드가 채워지고 linker hit hash direct path
(S6.next Phase 2 #79) 가 실효 작동. 이 통합 지점이 silent 누락되면
production attach 가 reload-safe 약속을 어기게 된다.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest

from src.pipeline import AuditPipeline


@pytest.fixture
def df_minimal() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "document_id": ["D1"],
            "posting_date": pd.to_datetime(["2026-04-30"]),
            "gl_account": ["410000"],
            "debit_amount": [100.0],
            "credit_amount": [0.0],
            "company_code": ["kr01"],
            "trading_partner": ["kr02"],
        }
    )


def _make_pipeline(engagement_id: str) -> AuditPipeline:
    """엔게이지먼트 ID 만 채운 최소 ctx 로 AuditPipeline 생성."""
    from types import SimpleNamespace

    ctx = SimpleNamespace(
        company_id="kr01",
        engagement_id=engagement_id,
        materiality_amount=0.0,
        phase1_case={"phase1_case": {}},
        db_path=None,
    )
    # __init__ 의 무거운 의존성을 우회하기 위해 object.__new__ 로 인스턴스 생성 후 ctx 만 주입.
    pipe = object.__new__(AuditPipeline)
    pipe._ctx = ctx  # type: ignore[attr-defined]
    return pipe


def test_pipeline_passes_engagement_salt_to_phase1_builder(df_minimal: pd.DataFrame) -> None:
    """invariant: ``_build_phase1_case_artifact`` 가 ``build_phase1_case_result`` 호출 시
    ``engagement_salt=f"{ctx.engagement_id}|{batch_id}"`` 를 전달.

    PHASE1 hit hash 필드의 reload-safe 약속 (S6.next Phase 2 #79) 의 진입점.
    """
    pipe = _make_pipeline(engagement_id="eng-007")
    captured: dict[str, Any] = {}

    def _capture_build_phase1(*args: Any, **kwargs: Any):
        captured.update(kwargs)
        # 후속 save_phase1_case_result / annotate_* 호출이 일찍 끝나도록 예외로 중단.
        raise RuntimeError("stop after capture")

    with patch("src.detection.phase1_case_builder.build_phase1_case_result", _capture_build_phase1):
        # _build_phase1_case_artifact 는 try/except 로 감싸 RuntimeError 를 warning 으로 흡수.
        pipe._build_phase1_case_artifact(  # type: ignore[attr-defined]
            df=df_minimal,
            results=[],
            batch_id="batch-042",
        )

    assert "engagement_salt" in captured, "build_phase1_case_result 가 engagement_salt kwarg 미수령"
    assert captured["engagement_salt"] == "eng-007|batch-042", (
        f"engagement_salt 가 ctx.engagement_id|batch_id 형식이 아님 — got: "
        f"{captured['engagement_salt']!r}"
    )


def test_pipeline_passes_empty_salt_when_engagement_id_absent(df_minimal: pd.DataFrame) -> None:
    """ctx.engagement_id 부재 → engagement_salt="" — PHASE1 builder backward compat."""
    pipe = _make_pipeline(engagement_id="")
    captured: dict[str, Any] = {}

    def _capture(*args: Any, **kwargs: Any):
        captured.update(kwargs)
        raise RuntimeError("stop")

    with patch("src.detection.phase1_case_builder.build_phase1_case_result", _capture):
        pipe._build_phase1_case_artifact(  # type: ignore[attr-defined]
            df=df_minimal,
            results=[],
            batch_id="batch-042",
        )

    # engagement_id 부재 → 빈 salt (PHASE1 builder 가 hash 산출 skip — invariant #71).
    assert captured.get("engagement_salt") == ""
