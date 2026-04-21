from __future__ import annotations


def test_upload_batches_includes_phase2_columns(db_conn):
    cols = db_conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'upload_batches'"
    ).fetchdf()
    ddl_cols = set(cols["column_name"])
    assert {
        "phase2_training_report_id",
        "phase2_inference_contract",
        "phase2_promotion_policy",
        "phase2_inference_mode",
        "detector_statuses_json",
    }.issubset(ddl_cols)
