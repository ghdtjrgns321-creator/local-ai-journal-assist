from __future__ import annotations

import src.db.analysis_reset as analysis_reset
from src.db.analysis_reset import (
    reset_phase1_analysis,
    reset_phase2_analysis,
    reset_phase3_analysis,
)
from src.db.loader import load_all, update_upload_batch_meta


def test_reset_phase1_clears_detection_artifacts_and_keeps_ledger_rows(
    monkeypatch,
    tmp_path,
    db_conn,
    db_sample_df,
    db_detection_results,
    db_benford_results,
):
    batch_id = "batch_reset_phase1"
    artifact_dir = tmp_path / "artifacts" / "phase1_cases" / "kr01"
    artifact_dir.mkdir(parents=True)
    artifact_path = artifact_dir / f"phase1case_kr01_{batch_id}_20260503T010000Z.json"
    artifact_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(analysis_reset, "PROJECT_ROOT", tmp_path)

    load_all(
        db_conn,
        db_sample_df,
        batch_id,
        db_detection_results + db_benford_results,
        phase1_case_ref={
            "phase1_case_run_id": "run_001",
            "phase1_case_path": "artifacts/phase1_cases/run_001.json",
            "phase1_case_count": 2,
            "phase1_macro_finding_count": 1,
            "top_theme_ids": ["approval_control"],
            "phase1_case_schema_version": "1.0",
        },
    )

    result = reset_phase1_analysis(db_conn, batch_id)

    assert result.phase == "phase1"
    assert db_conn.execute(
        "SELECT COUNT(*) FROM general_ledger WHERE upload_batch_id = ?",
        [batch_id],
    ).fetchone()[0] == len(db_sample_df)
    assert db_conn.execute(
        "SELECT COUNT(*) FROM anomaly_flags WHERE upload_batch_id = ?",
        [batch_id],
    ).fetchone()[0] == 0
    assert db_conn.execute(
        "SELECT COUNT(*) FROM benford_summary WHERE upload_batch_id = ?",
        [batch_id],
    ).fetchone()[0] == 0
    row = db_conn.execute(
        """
        SELECT anomaly_score, risk_level, flagged_rules
        FROM general_ledger
        WHERE upload_batch_id = ?
        LIMIT 1
        """,
        [batch_id],
    ).fetchone()
    assert row == (None, None, None)
    meta = db_conn.execute(
        """
        SELECT anomaly_count, high_risk_count, phase1_case_run_id, phase1_case_count
        FROM upload_batches
        WHERE upload_batch_id = ?
        """,
        [batch_id],
    ).fetchone()
    assert meta == (0, 0, None, 0)
    assert not artifact_path.exists()


def test_reset_phase2_clears_ml_columns_and_phase2_batch_meta(
    db_conn,
    db_sample_df,
):
    batch_id = "batch_reset_phase2"
    df = db_sample_df.copy()
    df["supervised_score"] = [0.9, 0.9, 0.1]
    df["supervised_model_id"] = ["m1", "m1", "m1"]
    load_all(db_conn, df, batch_id)
    update_upload_batch_meta(
        db_conn,
        batch_id,
        phase2_training_report_id="train_001",
        phase2_inference_contract={"required_models": ["supervised"]},
        phase2_promotion_policy={"selection_mode": "best_per_family"},
        phase2_inference_mode="training_contract",
    )

    result = reset_phase2_analysis(db_conn, batch_id)

    assert result.phase == "phase2"
    row = db_conn.execute(
        """
        SELECT supervised_score, supervised_model_id
        FROM general_ledger
        WHERE upload_batch_id = ?
        LIMIT 1
        """,
        [batch_id],
    ).fetchone()
    assert row == (None, None)
    meta = db_conn.execute(
        """
        SELECT phase2_training_report_id, phase2_inference_contract,
               phase2_promotion_policy, phase2_inference_mode
        FROM upload_batches
        WHERE upload_batch_id = ?
        """,
        [batch_id],
    ).fetchone()
    assert meta == (None, None, None, None)


def test_reset_phase3_deletes_llm_narratives_for_batch_documents(
    db_conn,
    db_sample_df,
):
    batch_id = "batch_reset_phase3"
    load_all(db_conn, db_sample_df, batch_id)
    db_conn.execute(
        """
        INSERT INTO llm_narratives
        (document_id, narrative_text, cited_rules, model_tier)
        VALUES
        ('JE-001', 'text', 'L1-01', 'light'),
        ('OTHER', 'text', 'L1-01', 'light')
        """
    )

    result = reset_phase3_analysis(db_conn, batch_id)

    assert result.phase == "phase3"
    rows = db_conn.execute(
        "SELECT document_id FROM llm_narratives ORDER BY document_id"
    ).fetchdf()
    assert rows["document_id"].tolist() == ["OTHER"]
