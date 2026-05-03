"""Developer-only helpers for clearing persisted phase analysis artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class PhaseResetResult:
    phase: str
    batch_id: str
    affected_rows: dict[str, int]

    @property
    def total_affected(self) -> int:
        return sum(self.affected_rows.values())


_PHASE1_GL_COLUMNS = [
    "anomaly_score",
    "risk_level",
    "flagged_rules",
    "review_rules",
]

_PHASE2_GL_COLUMNS = [
    "supervised_score",
    "unsupervised_score",
    "duplicate_score",
    "supervised_model_id",
    "unsupervised_model_id",
    "duplicate_model_id",
    "ml_scored_at",
]


def reset_phase1_analysis(conn, batch_id: str) -> PhaseResetResult:
    """Clear persisted Phase 1 artifacts for one upload batch.

    Phase 2/3 depend on Phase 1 output, so they are cleared as part of this reset.
    Raw ledger rows stay in place and are converted back to an unanalyzed state.
    """
    _require_batch_id(batch_id)
    affected: dict[str, int] = {}
    conn.execute("BEGIN TRANSACTION")
    try:
        affected.update(_reset_phase3_no_tx(conn, batch_id).affected_rows)
        affected.update(_reset_phase2_no_tx(conn, batch_id).affected_rows)
        affected["anomaly_flags"] = _count_batch_rows(conn, "anomaly_flags", batch_id)
        affected["benford_summary"] = _count_batch_rows(conn, "benford_summary", batch_id)
        affected["benford_digits"] = _count_batch_rows(conn, "benford_digits", batch_id)
        affected["performance_reports"] = _count_performance_reports(conn, batch_id)
        affected["phase1_artifacts"] = _count_phase1_artifacts(batch_id)

        conn.execute("DELETE FROM anomaly_flags WHERE upload_batch_id = ?", [batch_id])
        conn.execute("DELETE FROM benford_summary WHERE upload_batch_id = ?", [batch_id])
        conn.execute("DELETE FROM benford_digits WHERE upload_batch_id = ?", [batch_id])
        _delete_performance_reports(conn, batch_id)
        _set_general_ledger_columns_null(conn, batch_id, _PHASE1_GL_COLUMNS)
        _reset_upload_batch_phase1_meta(conn, batch_id)
        _delete_phase1_artifacts(batch_id)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return PhaseResetResult("phase1", batch_id, affected)


def reset_phase2_analysis(conn, batch_id: str) -> PhaseResetResult:
    """Clear persisted Phase 2 artifacts for one upload batch."""
    _require_batch_id(batch_id)
    conn.execute("BEGIN TRANSACTION")
    try:
        result = _reset_phase2_no_tx(conn, batch_id)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return result


def reset_phase3_analysis(conn, batch_id: str) -> PhaseResetResult:
    """Clear persisted Phase 3 LLM artifacts for one upload batch."""
    _require_batch_id(batch_id)
    conn.execute("BEGIN TRANSACTION")
    try:
        result = _reset_phase3_no_tx(conn, batch_id)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return result


def _reset_phase2_no_tx(conn, batch_id: str) -> PhaseResetResult:
    affected = {
        "general_ledger_phase2_rows": _count_non_null_batch_rows(
            conn,
            "general_ledger",
            batch_id,
            _PHASE2_GL_COLUMNS,
        ),
        "ml_model_metadata": _count_ml_model_metadata(conn, batch_id),
    }
    affected.update(_delete_phase2_performance_reports(conn, batch_id))
    if _table_exists(conn, "ml_model_metadata"):
        conn.execute("DELETE FROM ml_model_metadata WHERE train_batch_id = ?", [batch_id])
    _set_general_ledger_columns_null(conn, batch_id, _PHASE2_GL_COLUMNS)
    conn.execute(
        """
        UPDATE upload_batches
        SET
            phase2_training_report_id = NULL,
            phase2_inference_contract = NULL,
            phase2_promotion_policy = NULL,
            phase2_inference_mode = NULL
        WHERE upload_batch_id = ?
        """,
        [batch_id],
    )
    return PhaseResetResult("phase2", batch_id, affected)


def _reset_phase3_no_tx(conn, batch_id: str) -> PhaseResetResult:
    affected: dict[str, int] = {}
    if _table_exists(conn, "llm_narratives"):
        affected["llm_narratives"] = _count_llm_narratives_for_batch(conn, batch_id)
        conn.execute(
            """
            DELETE FROM llm_narratives
            WHERE document_id IN (
                SELECT DISTINCT document_id
                FROM general_ledger
                WHERE upload_batch_id = ?
            )
            """,
            [batch_id],
        )
    if _column_exists(conn, "upload_batches", "phase3_insight_json"):
        affected["phase3_insight_json"] = _count_upload_batch_phase3(conn, batch_id)
        conn.execute(
            """
            UPDATE upload_batches
            SET phase3_insight_json = NULL
            WHERE upload_batch_id = ?
            """,
            [batch_id],
        )
    return PhaseResetResult("phase3", batch_id, affected)


def _reset_upload_batch_phase1_meta(conn, batch_id: str) -> None:
    conn.execute(
        """
        UPDATE upload_batches
        SET
            anomaly_count = 0,
            high_risk_count = 0,
            detector_statuses_json = NULL,
            phase1_case_run_id = NULL,
            phase1_case_path = NULL,
            phase1_case_count = 0,
            phase1_macro_finding_count = 0,
            phase1_top_theme_ids = NULL,
            phase1_case_schema_version = NULL,
            warnings = NULL
        WHERE upload_batch_id = ?
        """,
        [batch_id],
    )


def _delete_performance_reports(conn, batch_id: str) -> None:
    conn.execute(
        """
        DELETE FROM performance_rule_metrics
        WHERE report_id IN (
            SELECT report_id
            FROM performance_reports
            WHERE upload_batch_id = ?
        )
        """,
        [batch_id],
    )
    conn.execute("DELETE FROM performance_reports WHERE upload_batch_id = ?", [batch_id])


def _delete_phase2_performance_reports(conn, batch_id: str) -> dict[str, int]:
    if not _table_exists(conn, "performance_reports"):
        return {"phase2_performance_reports": 0, "phase2_performance_rule_metrics": 0}
    report_ids = [
        row[0]
        for row in conn.execute(
            """
            SELECT report_id
            FROM performance_reports
            WHERE upload_batch_id = ? AND lower(phase_scope) LIKE 'phase2%'
            """,
            [batch_id],
        ).fetchall()
    ]
    if not report_ids:
        return {"phase2_performance_reports": 0, "phase2_performance_rule_metrics": 0}

    placeholders = ", ".join(["?"] * len(report_ids))
    metric_count = 0
    if _table_exists(conn, "performance_rule_metrics"):
        metric_count = int(
            conn.execute(
                f"""
                SELECT COUNT(*)
                FROM performance_rule_metrics
                WHERE report_id IN ({placeholders})
                """,
                report_ids,
            ).fetchone()[0]
        )
        conn.execute(
            f"DELETE FROM performance_rule_metrics WHERE report_id IN ({placeholders})",
            report_ids,
        )
    conn.execute(
        """
        DELETE FROM performance_reports
        WHERE upload_batch_id = ? AND lower(phase_scope) LIKE 'phase2%'
        """,
        [batch_id],
    )
    return {
        "phase2_performance_reports": len(report_ids),
        "phase2_performance_rule_metrics": metric_count,
    }


def _set_general_ledger_columns_null(
    conn,
    batch_id: str,
    columns: list[str],
) -> None:
    existing = _column_set(conn, "general_ledger")
    assignments = [f"{col} = NULL" for col in columns if col in existing]
    if not assignments:
        return
    conn.execute(
        f"UPDATE general_ledger SET {', '.join(assignments)} WHERE upload_batch_id = ?",
        [batch_id],
    )


def _require_batch_id(batch_id: str) -> None:
    if not str(batch_id or "").strip():
        raise ValueError("batch_id is required")


def _count_batch_rows(conn, table_name: str, batch_id: str) -> int:
    if not _table_exists(conn, table_name):
        return 0
    return int(
        conn.execute(
            f"SELECT COUNT(*) FROM {table_name} WHERE upload_batch_id = ?",
            [batch_id],
        ).fetchone()[0]
    )


def _count_non_null_batch_rows(
    conn,
    table_name: str,
    batch_id: str,
    columns: list[str],
) -> int:
    existing = _column_set(conn, table_name)
    predicates = [f"{col} IS NOT NULL" for col in columns if col in existing]
    if not predicates:
        return 0
    return int(
        conn.execute(
            f"""
            SELECT COUNT(*)
            FROM {table_name}
            WHERE upload_batch_id = ? AND ({' OR '.join(predicates)})
            """,
            [batch_id],
        ).fetchone()[0]
    )


def _count_performance_reports(conn, batch_id: str) -> int:
    if not _table_exists(conn, "performance_reports"):
        return 0
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM performance_reports WHERE upload_batch_id = ?",
            [batch_id],
        ).fetchone()[0]
    )


def _count_llm_narratives_for_batch(conn, batch_id: str) -> int:
    return int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM llm_narratives
            WHERE document_id IN (
                SELECT DISTINCT document_id
                FROM general_ledger
                WHERE upload_batch_id = ?
            )
            """,
            [batch_id],
        ).fetchone()[0]
    )


def _count_upload_batch_phase3(conn, batch_id: str) -> int:
    return int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM upload_batches
            WHERE upload_batch_id = ? AND phase3_insight_json IS NOT NULL
            """,
            [batch_id],
        ).fetchone()[0]
    )


def _count_ml_model_metadata(conn, batch_id: str) -> int:
    if not _table_exists(conn, "ml_model_metadata"):
        return 0
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM ml_model_metadata WHERE train_batch_id = ?",
            [batch_id],
        ).fetchone()[0]
    )


def _count_phase1_artifacts(batch_id: str) -> int:
    return len(_phase1_artifact_paths(batch_id))


def _delete_phase1_artifacts(batch_id: str) -> None:
    for path in _phase1_artifact_paths(batch_id):
        try:
            path.unlink()
        except OSError:
            continue


def _phase1_artifact_paths(batch_id: str) -> list[Path]:
    artifacts_dir = PROJECT_ROOT / "artifacts" / "phase1_cases"
    if not batch_id or not artifacts_dir.exists():
        return []
    return list(artifacts_dir.glob(f"**/phase1case_*_{batch_id}_*.json"))


def _table_exists(conn, table_name: str) -> bool:
    return bool(
        conn.execute(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_name = ?
            """,
            [table_name],
        ).fetchone()
    )


def _column_set(conn, table_name: str) -> set[str]:
    if not _table_exists(conn, table_name):
        return set()
    return set(
        conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = ?
            """,
            [table_name],
        ).fetchdf()["column_name"]
    )


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    return column_name in _column_set(conn, table_name)
