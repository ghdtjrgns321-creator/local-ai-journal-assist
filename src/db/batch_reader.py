"""DB에서 배치 데이터를 읽어 PipelineResult를 복원.

Why: Streamlit 재시작 시 session_state가 소멸되므로,
     DB에 저장된 이전 분석 결과를 다시 불러와야 한다.
     anomaly_flags에서 Pseudo DetectionResult를 역산하여
     대시보드 차트가 정상 작동하도록 보장.
"""

from __future__ import annotations

import logging

import duckdb
import pandas as pd

from src.db.performance_store import load_latest_report
from src.db.queries import execute_preset
from src.detection.base import DetectionResult, RuleFlag
from src.detection.constants import (
    DETECTOR_DISPLAY_ORDER,
    RULE_CODES,
    SEVERITY_MAP,
    get_detector_profile,
)

logger = logging.getLogger(__name__)

_RESTORED_CORE_TRACKS: frozenset[str] = frozenset({
    "layer_a",
    "layer_b",
    "layer_c",
    "benford",
    "duplicate",
    "intercompany",
})


def list_batches(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """upload_batches 테이블에서 배치 목록 조회 (최신순)."""
    return execute_preset(conn, "list_batches", params=())


def load_batch(conn: duckdb.DuckDBPyConnection, batch_id: str):
    """DB에서 배치 데이터를 읽어 PipelineResult를 재구성.

    Returns:
        PipelineResult (featured_data=None, elapsed=0.0)

    Raises:
        ValueError: batch_id에 해당하는 데이터가 없을 때.
    """
    # Why: 순환 임포트 방지 — pipeline이 db.loader를 임포트하므로 지연 임포트 필수
    from src.pipeline import PipelineResult

    # 1. general_ledger 조회
    data = execute_preset(conn, "batch_ledger", batch_id=batch_id)
    if data.empty:
        raise ValueError(f"배치를 찾을 수 없습니다: {batch_id}")

    # 2. anomaly_flags에서 Pseudo DetectionResult 역산
    results = _reconstruct_detection_results(conn, batch_id, data)

    # 3. risk_summary 계산
    risk_summary = (
        data["risk_level"].value_counts().to_dict()
        if "risk_level" in data.columns else {}
    )

    # 4. 메타 조회 — file_name 복원
    meta = execute_preset(conn, "batch_meta", params=(batch_id,))
    file_name = meta.iloc[0]["file_name"] if not meta.empty else ""
    performance_report = load_latest_report(conn, batch_id)
    if performance_report is None:
        from src.metrics.operational_evaluator import evaluate_operational_report_from_db
        performance_report = evaluate_operational_report_from_db(
            conn,
            upload_batch_id=batch_id,
        )

    return PipelineResult(
        data=data,
        results=results,
        risk_summary=risk_summary,
        batch_id=batch_id,
        load_result=None,
        elapsed=0.0,
        featured_data=None,
        file_name=file_name,
        detector_statuses=_build_detector_statuses(results),
        performance_report=performance_report,
    )


def _reconstruct_detection_results(
    conn: duckdb.DuckDBPyConnection, batch_id: str, data: pd.DataFrame,
) -> list[DetectionResult]:
    """anomaly_flags 테이블에서 track별 Pseudo DetectionResult를 역산.

    Why: 빈 리스트로 두면 대시보드의 룰별 위반 건수 차트가 깨진다.
         anomaly_flags를 track_name별로 그룹화하고, data의 document_id로
         행 인덱스를 역매핑하여 실제 점수를 details에 채운다.
    """
    flags_df = execute_preset(conn, "batch_flags", batch_id=batch_id)
    if flags_df.empty:
        return []

    total_rows = len(data)
    # Why: anomaly_flags의 document_id → data의 row index 역매핑
    doc_to_idx: dict[str, int] = {}
    if "document_id" in data.columns:
        for idx, doc_id in enumerate(data["document_id"]):
            doc_to_idx.setdefault(doc_id, idx)

    results: list[DetectionResult] = []

    for track_name, track_group in flags_df.groupby("track_name"):
        rule_flags: list[RuleFlag] = []
        rule_columns: dict[str, pd.Series] = {}

        for rule_code, rule_group in track_group.groupby("rule_code"):
            # Why: document_id → row index 매핑으로 실제 점수 채우기
            scores = pd.Series(0.0, index=range(total_rows))
            for _, flag_row in rule_group.iterrows():
                idx = doc_to_idx.get(flag_row["document_id"])
                if idx is not None:
                    scores.iloc[idx] = max(scores.iloc[idx], flag_row["score"])

            rule_columns[rule_code] = scores
            rule_flags.append(RuleFlag(
                rule_id=rule_code,
                rule_name=RULE_CODES.get(rule_code, rule_code),
                severity=SEVERITY_MAP.get(rule_code, 3),
                flagged_count=int((scores > 0).sum()),
                total_count=total_rows,
            ))

        details = pd.DataFrame(rule_columns)

        # Why: scores는 track 내 모든 룰의 max (원본과 동일 패턴)
        track_scores = details.max(axis=1) if not details.empty else pd.Series(dtype=float)
        flagged_indices = list(track_scores[track_scores > 0].index)

        results.append(DetectionResult(
            track_name=track_name,
            flagged_indices=flagged_indices,
            scores=track_scores,
            rule_flags=rule_flags,
            details=details,
            metadata={
                "elapsed": 0.0,
                "restored_from_db": True,
                "display_name": get_detector_profile(track_name).display_name,
                "maturity": str(get_detector_profile(track_name).maturity),
                "default_enabled": get_detector_profile(track_name).default_enabled,
                "activation_requirements": list(get_detector_profile(track_name).activation_requirements),
                "run_status": "executed",
            },
        ))

    return results


def _build_detector_statuses(results: list[DetectionResult]) -> list[dict]:
    """DB 복원 배치용 탐지기 상태 스냅샷 생성."""
    result_map = {result.track_name: result for result in results}
    statuses: list[dict] = []
    for track_name in DETECTOR_DISPLAY_ORDER:
        track_name = str(track_name)
        profile = get_detector_profile(track_name)
        result = result_map.get(track_name)
        if result is None:
            if track_name in _RESTORED_CORE_TRACKS:
                statuses.append({
                    "track_name": track_name,
                    "display_name": profile.display_name,
                    "maturity": str(profile.maturity),
                    "default_enabled": profile.default_enabled,
                    "activation_requirements": list(profile.activation_requirements),
                    "run_status": "executed",
                    "reason": "restored_without_flag_rows",
                    "flagged_docs": 0,
                    "rules_run": 0,
                    "elapsed_sec": 0.0,
                })
                continue
            statuses.append({
                "track_name": track_name,
                "display_name": profile.display_name,
                "maturity": str(profile.maturity),
                "default_enabled": profile.default_enabled,
                "activation_requirements": list(profile.activation_requirements),
                "run_status": "unknown",
                "reason": "restored batch without runtime snapshot",
                "flagged_docs": 0,
                "rules_run": 0,
                "elapsed_sec": 0.0,
            })
            continue
        statuses.append({
            "track_name": track_name,
            "display_name": result.display_name,
            "maturity": result.maturity,
            "default_enabled": result.default_enabled,
            "activation_requirements": result.activation_requirements,
            "run_status": result.run_status,
            "reason": result.skip_reason,
            "flagged_docs": result.flagged_count,
            "rules_run": result.total_rules_run,
            "elapsed_sec": round(result.elapsed_seconds, 3),
        })
    return statuses
