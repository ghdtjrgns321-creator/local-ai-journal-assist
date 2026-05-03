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

_RESTORED_CORE_TRACKS: frozenset[str] = frozenset({
    "layer_a",
    "layer_b",
    "layer_c",
    "benford",
    "duplicate",
    "intercompany",
})


def list_batches(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Return persisted upload batch metadata."""
    return execute_preset(conn, "list_batches", params=())


def load_batch(conn: duckdb.DuckDBPyConnection, batch_id: str):
    """Restore a previously loaded batch into a PipelineResult."""
    from src.pipeline import PipelineResult

    data = execute_preset(conn, "batch_ledger", batch_id=batch_id)
    if data.empty:
        raise ValueError(f"배치를 찾을 수 없습니다: {batch_id}")

    results = _reconstruct_detection_results(conn, batch_id, data)
    risk_summary = (
        data["risk_level"].value_counts().to_dict()
        if "risk_level" in data.columns else {}
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
        phase1_macro_finding_count=int(
            phase1_meta.get("phase1_macro_finding_count", 0) or 0
        ),
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
    doc_to_idx: dict[str, int] = {}
    if "document_id" in data.columns:
        doc_to_idx = (
            pd.Series(range(total_rows), index=data["document_id"])
            .groupby(level=0)
            .first()
            .to_dict()
        )
    flags_df = flags_df.copy()
    flags_df["_row_index"] = flags_df["document_id"].map(doc_to_idx)
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
            rule_flags.append(RuleFlag(
                rule_id=rule_code,
                rule_name=RULE_CODES.get(rule_code, rule_code),
                severity=SEVERITY_MAP.get(rule_code, 3),
                flagged_count=int((scores > 0).sum()),
                total_count=total_rows,
            ))

        details = pd.DataFrame(rule_columns)
        track_scores = details.max(axis=1) if not details.empty else pd.Series(dtype=float)
        flagged_indices = list(track_scores[track_scores > 0].index)
        profile = get_detector_profile(track_name)

        results.append(DetectionResult(
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
        ))

    return results


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


def _normalize_detector_status_snapshot(snapshot: list[dict]) -> list[dict]:
    order = {str(name): idx for idx, name in enumerate(DETECTOR_DISPLAY_ORDER)}
    normalized: list[dict] = []
    for item in snapshot:
        track_name = str(item.get("track_name") or "")
        if not track_name:
            continue
        profile = get_detector_profile(track_name)
        normalized.append({
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
        })
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
