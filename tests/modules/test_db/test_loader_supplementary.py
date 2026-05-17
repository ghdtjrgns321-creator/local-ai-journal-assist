"""loader_supplementary 테스트 — 실제 DataSynth JSON 로드 검증.

실제 data/journal/primary/datasynth/ 파일을 사용하여
JSON → DuckDB 적재 파이프라인 전체를 검증한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from src.db.loader_supplementary import (
    _extract_header,
    _load_json_file,
    _normalize_nested_doc,
    load_anomaly_labels_json,
    load_change_log,
    load_ic_matched_pairs,
    load_purchase_orders,
    load_supplementary,
    load_vendors,
)
from src.db.schema import initialize_schema
from src.db.schema_supplementary import (
    PURCHASE_ORDER_HEADERS_COLUMNS,
    PURCHASE_ORDER_LINES_COLUMNS,
)

DATASYNTH_DIR = Path("data/journal/primary/datasynth")
DATASYNTH_JOURNAL_CSV = DATASYNTH_DIR / "journal_entries.csv"
BATCH_ID = "test_sup_001"


@pytest.fixture()
def sup_conn():
    """보조 스키마 포함 in-memory DuckDB 커넥션."""
    conn = duckdb.connect(":memory:")
    initialize_schema(conn)
    yield conn
    conn.close()


# ── 유틸리티 테스트 ─────────────────────────────────────────


class TestLoadJsonFile:
    @pytest.mark.skipif(
        not DATASYNTH_JOURNAL_CSV.exists(),
        reason="plain datasynth fixture not available (intentionally retired)",
    )
    def test_existing_file(self):
        records = _load_json_file(DATASYNTH_DIR / "document_flows/purchase_orders.json")
        assert len(records) > 0
        assert "header" in records[0]

    def test_missing_file(self):
        result = _load_json_file(Path("nonexistent/file.json"))
        assert result == []


class TestExtractHeader:
    def test_flattens_header_and_scalars(self):
        record = {
            "header": {
                "document_id": "PO-001",
                "document_type": "NB",
                "document_references": [{"ref": "x"}],
            },
            "po_type": "standard",
            "vendor_id": "V-001",
            "items": [{"line_number": 1}],
        }
        header = _extract_header(record)
        assert header["document_id"] == "PO-001"
        assert header["po_type"] == "standard"
        assert header["vendor_id"] == "V-001"
        # list/dict 필드는 제외
        assert "document_references" not in header
        assert "items" not in header


class TestNormalizeNestedDoc:
    def test_empty_records(self):
        headers_df, lines_df, refs_df = _normalize_nested_doc(
            [], PURCHASE_ORDER_HEADERS_COLUMNS,
            lines_columns=PURCHASE_ORDER_LINES_COLUMNS,
        )
        assert headers_df.empty
        assert lines_df.empty
        assert refs_df.empty
        assert list(headers_df.columns) == PURCHASE_ORDER_HEADERS_COLUMNS
        assert list(lines_df.columns) == PURCHASE_ORDER_LINES_COLUMNS

    def test_null_items(self):
        """items가 None인 레코드도 처리 가능."""
        record = {
            "header": {"document_id": "PO-X", "document_type": "NB"},
            "items": None,
        }
        headers_df, lines_df, _refs_df = _normalize_nested_doc(
            [record], PURCHASE_ORDER_HEADERS_COLUMNS,
            lines_columns=PURCHASE_ORDER_LINES_COLUMNS,
        )
        assert len(headers_df) == 1
        assert lines_df.empty


# ── Document Flow 적재 테스트 ──────────────────────────────


class TestLoadPurchaseOrders:
    @pytest.mark.skipif(
        not (DATASYNTH_DIR / "document_flows/purchase_orders.json").exists(),
        reason="DataSynth 데이터 없음",
    )
    def test_load_real_data(self, sup_conn):
        n = load_purchase_orders(
            sup_conn,
            DATASYNTH_DIR / "document_flows/purchase_orders.json",
            BATCH_ID,
        )
        assert n > 0

        # header 테이블 검증
        headers = sup_conn.execute(
            "SELECT COUNT(*) FROM purchase_order_headers WHERE upload_batch_id = ?",
            [BATCH_ID],
        ).fetchone()[0]
        assert headers > 0

        # lines 테이블 검증
        lines = sup_conn.execute(
            "SELECT COUNT(*) FROM purchase_order_lines WHERE upload_batch_id = ?",
            [BATCH_ID],
        ).fetchone()[0]
        assert lines > 0

    def test_missing_file(self, sup_conn):
        n = load_purchase_orders(sup_conn, Path("no/file.json"), BATCH_ID)
        assert n == 0


# ── Master Data 적재 테스트 ────────────────────────────────


class TestLoadVendors:
    @pytest.mark.skipif(
        not (DATASYNTH_DIR / "master_data/vendors.json").exists(),
        reason="DataSynth 데이터 없음",
    )
    def test_load_real_data(self, sup_conn):
        n = load_vendors(
            sup_conn, DATASYNTH_DIR / "master_data/vendors.json", BATCH_ID,
        )
        assert n > 0
        row = sup_conn.execute(
            "SELECT vendor_id, name FROM vendors LIMIT 1",
        ).fetchone()
        assert row[0] is not None  # vendor_id 존재

    def test_duplicate_vendor_load_is_idempotent(self, sup_conn, tmp_path):
        vendors_path = tmp_path / "vendors.json"
        vendors_path.write_text(
            json.dumps(
                [
                    {
                        "vendor_id": "V-IDEMPOTENT",
                        "name": "Idempotent Vendor",
                        "is_active": True,
                    }
                ]
            ),
            encoding="utf-8",
        )

        first_count = load_vendors(sup_conn, vendors_path, BATCH_ID)
        second_count = load_vendors(sup_conn, vendors_path, "another_batch")
        saved = sup_conn.execute(
            "SELECT COUNT(*) FROM vendors WHERE vendor_id = ?",
            ["V-IDEMPOTENT"],
        ).fetchone()[0]

        assert first_count == 1
        assert second_count == 0
        assert saved == 1


# ── Labels 적재 테스트 ─────────────────────────────────────


class TestLoadAnomalyLabels:
    def test_load_and_decompose_type(self, sup_conn, tmp_path):
        labels_path = tmp_path / "anomaly_labels.json"
        labels_path.write_text(
            json.dumps(
                [
                    {
                        "anomaly_id": "ANO_TEST_DECOMPOSE",
                        "anomaly_type": {"Relational": "UnusualAccountPair"},
                        "document_id": "D1",
                    }
                ]
            ),
            encoding="utf-8",
        )

        n = load_anomaly_labels_json(
            sup_conn,
            labels_path,
            BATCH_ID,
        )
        assert n > 0
        row = sup_conn.execute(
            """
            SELECT anomaly_category, anomaly_subtype
            FROM anomaly_labels
            WHERE anomaly_id = 'ANO_TEST_DECOMPOSE'
            """,
        ).fetchone()
        # anomaly_type dict가 category/subtype으로 분해됐는지 검증
        assert row == ("Relational", "UnusualAccountPair")


# ── P1 테스트 ──────────────────────────────────────────────


class TestLoadChangeLog:
    @pytest.mark.skipif(
        not (DATASYNTH_DIR / "change_log.csv").exists(),
        reason="DataSynth 데이터 없음",
    )
    def test_load_csv(self, sup_conn):
        n = load_change_log(
            sup_conn, DATASYNTH_DIR / "change_log.csv", BATCH_ID,
        )
        assert n > 0


class TestLoadIcMatchedPairs:
    @pytest.mark.skipif(
        not (DATASYNTH_DIR / "intercompany/ic_matched_pairs.json").exists(),
        reason="DataSynth 데이터 없음",
    )
    def test_load_real_data(self, sup_conn):
        n = load_ic_matched_pairs(
            sup_conn,
            DATASYNTH_DIR / "intercompany/ic_matched_pairs.json",
            BATCH_ID,
        )
        assert n > 0


# ── 통합 테스트 ────────────────────────────────────────────


class TestLoadSupplementary:
    @pytest.mark.skipif(
        not DATASYNTH_DIR.exists(), reason="DataSynth 디렉토리 없음",
    )
    def test_full_load(self, sup_conn):
        counts = load_supplementary(sup_conn, DATASYNTH_DIR, BATCH_ID)
        # 최소한 document_flows + master_data는 적재되어야 함
        assert "purchase_orders" in counts
        assert "vendors" in counts
        assert counts["purchase_orders"] > 0
        assert counts["vendors"] > 0

    def test_empty_dir(self, sup_conn, tmp_path):
        """빈 디렉토리에서도 에러 없이 빈 dict 반환."""
        counts = load_supplementary(sup_conn, tmp_path, BATCH_ID)
        assert counts == {}

    def test_duplicate_anomaly_labels_do_not_abort_connection(self, sup_conn, tmp_path):
        labels_dir = tmp_path / "labels"
        labels_dir.mkdir()
        duplicate_rows = [
            {
                "anomaly_id": "ANO00000018",
                "anomaly_type": "Test",
                "document_id": "D1",
            },
            {
                "anomaly_id": "ANO00000018",
                "anomaly_type": "Test",
                "document_id": "D1",
            },
        ]
        (labels_dir / "anomaly_labels.json").write_text(
            json.dumps(duplicate_rows),
            encoding="utf-8",
        )

        load_supplementary(sup_conn, tmp_path, BATCH_ID)

        sup_conn.execute(
            """
            INSERT INTO upload_batches
            (upload_batch_id, file_name, row_count, anomaly_count, high_risk_count)
            VALUES (?, ?, ?, ?, ?)
            """,
            ["batch_after_duplicate_labels", "journal.csv", 1, 0, 0],
        )
        saved = sup_conn.execute(
            "SELECT COUNT(*) FROM upload_batches WHERE upload_batch_id = ?",
            ["batch_after_duplicate_labels"],
        ).fetchone()[0]
        assert saved == 1

    def test_duplicate_master_data_inside_outer_transaction_keeps_transaction_active(
        self,
        sup_conn,
        tmp_path,
    ):
        master_dir = tmp_path / "master_data"
        master_dir.mkdir()
        (master_dir / "vendors.json").write_text(
            json.dumps(
                [
                    {
                        "vendor_id": "V-OUTER-TXN",
                        "name": "Outer Txn Vendor",
                        "is_active": True,
                    }
                ]
            ),
            encoding="utf-8",
        )

        sup_conn.execute("BEGIN TRANSACTION")
        load_supplementary(sup_conn, tmp_path, BATCH_ID)
        load_supplementary(sup_conn, tmp_path, "another_batch")
        sup_conn.execute(
            """
            INSERT INTO upload_batches
            (upload_batch_id, file_name, row_count, anomaly_count, high_risk_count)
            VALUES (?, ?, ?, ?, ?)
            """,
            ["batch_after_outer_txn_duplicate", "journal.csv", 1, 0, 0],
        )
        sup_conn.execute("COMMIT")

        saved = sup_conn.execute(
            "SELECT COUNT(*) FROM upload_batches WHERE upload_batch_id = ?",
            ["batch_after_outer_txn_duplicate"],
        ).fetchone()[0]
        assert saved == 1
