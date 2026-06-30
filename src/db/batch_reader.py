"""Restore persisted batch data and runtime metadata from DuckDB."""

from __future__ import annotations

import json
import logging
from pathlib import Path

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
PROJECT_ROOT = Path(__file__).resolve().parents[2]

_RESTORED_CORE_TRACKS: frozenset[str] = frozenset(
    {
        "layer_a",
        "layer_b",
        "layer_c",
        "benford",
        "intercompany",
    }
)


def list_batches(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Return persisted upload batch metadata."""
    return execute_preset(conn, "list_batches", params=())


def load_batch(conn: duckdb.DuckDBPyConnection, batch_id: str):
    """Restore a previously loaded batch into a PipelineResult."""
    from src.ingest.text_mojibake import repair_dataframe_text_mojibake
    from src.pipeline import PipelineResult

    data = execute_preset(conn, "batch_ledger", batch_id=batch_id)
    if data.empty:
        raise ValueError(f"배치를 찾을 수 없습니다: {batch_id}")
    data = repair_dataframe_text_mojibake(data)

    results = _reconstruct_detection_results(conn, batch_id, data)
    risk_summary = (
        data["risk_level"].value_counts().to_dict() if "risk_level" in data.columns else {}
    )

    meta = execute_preset(conn, "batch_meta", params=(batch_id,))
    row = meta.iloc[0] if not meta.empty else None
    file_name = row["file_name"] if row is not None else ""
    phase2_training_report_id = row.get("phase2_training_report_id") if row is not None else None
    phase2_inference_contract = _parse_json_meta(
        row.get("phase2_inference_contract") if row is not None else None
    )
    phase2_promotion_policy = _parse_json_meta(
        row.get("phase2_promotion_policy") if row is not None else None
    )
    phase2_inference_mode = row.get("phase2_inference_mode") if row is not None else None
    detector_statuses_snapshot = _parse_json_meta(
        row.get("detector_statuses_json") if row is not None else None
    )
    phase1_meta = _phase1_case_meta_from_row(row, batch_id)

    performance_report = load_latest_report(conn, batch_id)
    if performance_report is None:
        from src.metrics.operational_evaluator import evaluate_operational_report_from_db

        performance_report = evaluate_operational_report_from_db(
            conn,
            upload_batch_id=batch_id,
        )

    result = PipelineResult(
        data=data,
        results=results,
        risk_summary=risk_summary,
        batch_id=batch_id,
        load_result=None,
        elapsed=0.0,
        featured_data=None,
        file_name=file_name,
        detector_statuses=_build_detector_statuses(
            results,
            detector_statuses_snapshot=detector_statuses_snapshot,
        ),
        performance_report=performance_report,
        phase1_case_path=phase1_meta.get("phase1_case_path"),
        phase1_case_run_id=phase1_meta.get("phase1_case_run_id"),
        phase1_case_count=int(phase1_meta.get("phase1_case_count", 0) or 0),
        phase1_macro_finding_count=int(phase1_meta.get("phase1_macro_finding_count", 0) or 0),
        phase1_top_theme_ids=list(phase1_meta.get("phase1_top_theme_ids") or []),
    )
    setattr(
        result,
        "phase1_case_schema_version",
        phase1_meta.get("phase1_case_schema_version"),
    )
    setattr(result, "phase2_training_report_id", phase2_training_report_id)
    setattr(result, "phase2_inference_contract", phase2_inference_contract)
    setattr(result, "phase2_promotion_policy", phase2_promotion_policy)
    setattr(result, "phase2_inference_mode", phase2_inference_mode)
    return result


def _reconstruct_detection_results(
    conn: duckdb.DuckDBPyConnection,
    batch_id: str,
    data: pd.DataFrame,
) -> list[DetectionResult]:
    """Rebuild pseudo DetectionResult objects from persisted anomaly flags."""
    flags_df = execute_preset(conn, "batch_flags", batch_id=batch_id)
    if flags_df.empty:
        return []

    total_rows = len(data)
    flags_df = flags_df.copy()
    flags_df["_row_index"] = _resolve_flag_row_indices(data, flags_df)
    flags_df = flags_df.dropna(subset=["_row_index"])
    flags_df["_row_index"] = flags_df["_row_index"].astype(int)

    results: list[DetectionResult] = []
    for track_name, track_group in flags_df.groupby("track_name"):
        rule_flags: list[RuleFlag] = []
        rule_columns: dict[str, pd.Series] = {}

        for rule_code, rule_group in track_group.groupby("rule_code"):
            scores = pd.Series(0.0, index=range(total_rows))
            max_scores = rule_group.groupby("_row_index")["score"].max()
            scores.iloc[max_scores.index.to_numpy()] = max_scores.to_numpy()

            rule_columns[rule_code] = scores
            rule_flags.append(
                RuleFlag(
                    rule_id=rule_code,
                    rule_name=RULE_CODES.get(rule_code, rule_code),
                    severity=SEVERITY_MAP.get(rule_code, 3),
                    flagged_count=int((scores > 0).sum()),
                    total_count=total_rows,
                )
            )

        details = pd.DataFrame(rule_columns)
        track_scores = details.max(axis=1) if not details.empty else pd.Series(dtype=float)
        flagged_indices = list(track_scores[track_scores > 0].index)
        profile = get_detector_profile(track_name)

        results.append(
            DetectionResult(
                track_name=track_name,
                flagged_indices=flagged_indices,
                scores=track_scores,
                rule_flags=rule_flags,
                details=details,
                metadata={
                    "elapsed": 0.0,
                    "restored_from_db": True,
                    "display_name": profile.display_name,
                    "maturity": str(profile.maturity),
                    "default_enabled": profile.default_enabled,
                    "activation_requirements": list(profile.activation_requirements),
                    "run_status": "executed",
                },
            )
        )

    return results


def _resolve_flag_row_indices(
    data: pd.DataFrame,
    flags_df: pd.DataFrame,
) -> pd.Series:
    """anomaly_flags row 를 ledger DataFrame 의 row index 로 매핑.

    Why: 같은 document_id 안에서도 line_number 가 다른 라인이 별도 위반을 가질 수
         있다(L1-02 적요 누락 등 행 단위 위반은 특정 라인에
         만). 이전 구현은 doc_id 만 보고 doc 의 첫 row 에 score 를 부여해, 첫 라인이
         아닌 위반 라인이 화면에서 첫 라인으로 이동하는 버그가 있었다.

    매핑 우선순위:
        1) (document_id, line_number) 정확 매칭 — line_number 가 양쪽에 있고 ledger에
           실제 존재하는 경우.
        2) document_id 만 매칭 — flag 또는 ledger 한쪽에 line_number 가 비어 있을 때
           안전 fallback. doc 의 첫 row 로 매핑하고 warning 로그.
        3) ledger 에 doc_id 자체가 없으면 NaN — 호출부에서 dropna.
    """
    total_rows = len(data)
    if "document_id" not in data.columns:
        return pd.Series([pd.NA] * len(flags_df), dtype="Float64")

    doc_first_idx: dict[str, int] = (
        pd.Series(range(total_rows), index=data["document_id"].astype(str))
        .groupby(level=0)
        .first()
        .to_dict()
    )

    doc_line_to_idx: dict[tuple[str, int], int] = {}
    if "line_number" in data.columns:
        line_series = pd.to_numeric(data["line_number"], errors="coerce")
        for idx, (doc_id, line_no) in enumerate(
            zip(data["document_id"].astype(str), line_series, strict=False)
        ):
            if pd.isna(line_no):
                continue
            doc_line_to_idx[(doc_id, int(line_no))] = idx

    flag_doc_ids = flags_df.get("document_id", pd.Series(dtype=str)).astype(str)
    # Why: flags_df 에 line_number 컬럼이 아예 없으면 .get() 의 default 가 길이 0
    #      Series 라 zip(strict=False) 시 아무 row 도 처리되지 않는다. flag_doc_ids
    #      길이에 맞춰 NaN 으로 broadcast 해야 doc_id 만으로 fallback 매칭 가능.
    if "line_number" in flags_df.columns:
        flag_line_numbers = pd.to_numeric(flags_df["line_number"], errors="coerce")
    else:
        flag_line_numbers = pd.Series([float("nan")] * len(flag_doc_ids), index=flag_doc_ids.index)

    fallback_count = 0
    indices: list[float] = []
    for doc_id, line_no in zip(flag_doc_ids, flag_line_numbers, strict=False):
        if not pd.isna(line_no):
            key = (doc_id, int(line_no))
            mapped = doc_line_to_idx.get(key)
            if mapped is not None:
                indices.append(float(mapped))
                continue
        # fallback: doc 첫 row
        first_idx = doc_first_idx.get(doc_id)
        if first_idx is None:
            indices.append(float("nan"))
        else:
            indices.append(float(first_idx))
            fallback_count += 1

    if fallback_count:
        logger.debug(
            "anomaly_flags row 매핑: %d 건이 (doc, line) 정확 매칭 실패해 doc 첫 row 로 fallback",
            fallback_count,
        )
    return pd.Series(indices, index=flags_df.index, dtype="Float64")


def _build_detector_statuses(
    results: list[DetectionResult],
    *,
    detector_statuses_snapshot: list[dict] | None = None,
) -> list[dict]:
    """Build detector statuses for restored batches."""
    if detector_statuses_snapshot:
        return _normalize_detector_status_snapshot(detector_statuses_snapshot)

    result_map = {result.track_name: result for result in results}
    statuses: list[dict] = []
    for track_name in DETECTOR_DISPLAY_ORDER:
        track_name = str(track_name)
        profile = get_detector_profile(track_name)
        result = result_map.get(track_name)
        if result is None:
            if track_name in _RESTORED_CORE_TRACKS:
                statuses.append(
                    {
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
                    }
                )
                continue
            statuses.append(
                {
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
                }
            )
            continue

        statuses.append(
            {
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
            }
        )
    return statuses


def _normalize_detector_status_snapshot(snapshot: list[dict]) -> list[dict]:
    order = {str(name): idx for idx, name in enumerate(DETECTOR_DISPLAY_ORDER)}
    normalized: list[dict] = []
    for item in snapshot:
        track_name = str(item.get("track_name") or "")
        if not track_name:
            continue
        profile = get_detector_profile(track_name)
        normalized.append(
            {
                "track_name": track_name,
                "display_name": item.get("display_name", profile.display_name),
                "maturity": item.get("maturity", str(profile.maturity)),
                "default_enabled": item.get("default_enabled", profile.default_enabled),
                "activation_requirements": list(
                    item.get("activation_requirements", profile.activation_requirements)
                ),
                "run_status": item.get("run_status", "unknown"),
                "reason": item.get("reason"),
                "flagged_docs": int(item.get("flagged_docs", 0) or 0),
                "rules_run": int(item.get("rules_run", 0) or 0),
                "elapsed_sec": float(item.get("elapsed_sec", 0.0) or 0.0),
            }
        )
    return sorted(normalized, key=lambda item: order.get(item["track_name"], 999))


def _phase1_case_meta_from_row(row, batch_id: str) -> dict[str, object]:
    if row is None:
        return {}

    top_theme_ids = _parse_json_meta(row.get("phase1_top_theme_ids"))
    meta = {
        "phase1_case_run_id": row.get("phase1_case_run_id"),
        "phase1_case_path": row.get("phase1_case_path"),
        "phase1_case_count": int(row.get("phase1_case_count", 0) or 0),
        "phase1_macro_finding_count": int(row.get("phase1_macro_finding_count", 0) or 0),
        "phase1_top_theme_ids": list(top_theme_ids or []),
        "phase1_case_schema_version": row.get("phase1_case_schema_version"),
    }
    path = str(meta.get("phase1_case_path") or "")
    if path and Path(path).exists():
        return meta

    recovered = _recover_phase1_case_meta_from_artifacts(batch_id)
    if recovered:
        return recovered
    return meta


def _recover_phase1_case_meta_from_artifacts(batch_id: str) -> dict[str, object] | None:
    artifacts_dir = PROJECT_ROOT / "artifacts" / "phase1_cases"
    if not batch_id or not artifacts_dir.exists():
        return None

    candidates = sorted(
        artifacts_dir.glob(f"**/phase1case_*_{batch_id}_*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.debug("failed to inspect phase1 case artifact: %s", path, exc_info=True)
            continue

        if payload.get("batch_id") != batch_id and payload.get("dataset_id") != batch_id:
            continue
        themes = payload.get("theme_summaries") or []
        return {
            "phase1_case_run_id": payload.get("run_id"),
            "phase1_case_path": str(path),
            "phase1_case_count": len(payload.get("cases") or []),
            "phase1_macro_finding_count": int(
                (payload.get("metadata") or {}).get("macro_finding_count", 0) or 0
            ),
            "phase1_top_theme_ids": [
                theme.get("theme_id") for theme in themes[:3] if theme.get("theme_id")
            ],
            "phase1_case_schema_version": payload.get("schema_version"),
        }
    return None


def _parse_json_meta(value):
    if value in (None, "", b""):
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        logger.debug("failed to parse persisted batch json meta", exc_info=True)
        return None
