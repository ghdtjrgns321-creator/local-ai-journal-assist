"""AuditTrail 단위 테스트.

테스트 그룹:
  - TestLog: 이벤트 6종 기록 + 병합 순서 방어
  - TestInvalidEvent: 잘못된 event_type 거부
  - TestGetTrail: batch_id 필터 + 시스템 이벤트 제외 + user_action 컬럼 추출
  - TestExportTrail: CSV 내보내기 (utf-8-sig, 부모 디렉토리 자동 생성)
  - TestGracefulDegradation: 테이블 DROP 후에도 호출측 미차단
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from src.db.audit_log import record_event
from src.db.connection import close_connection, get_connection
from src.export.audit_trail import VALID_EVENT_TYPES, AuditEvent, AuditTrail

# ── 공용 픽스처 ───────────────────────────────────────────────


@pytest.fixture
def audit_trail(tmp_path):
    """격리된 DuckDB + AuditTrail 반환.

    Why:
        tmp_path는 pytest 기본 픽스처로 테스트별 독립 디렉토리 제공.
        get_connection은 내부에서 initialize_schema()를 호출해
        audit_log 테이블을 포함한 전체 스키마를 구성한다.
    """
    db_path = str(tmp_path / "audit_test.duckdb")
    conn = get_connection(db_path)
    trail = AuditTrail(conn)
    yield trail, conn
    # Why: 싱글톤 캐시를 다음 테스트에서 재사용하지 않도록 정리
    close_connection()


def _make_event(
    event_type: str = "upload",
    user_action: str = "샘플 행동",
    batch_id: str | None = "BATCH_TEST",
    details: dict | None = None,
) -> AuditEvent:
    """테스트 간소화용 AuditEvent 팩토리."""
    return AuditEvent(
        event_type=event_type,  # type: ignore[arg-type]
        user_action=user_action,
        batch_id=batch_id,
        details=details or {},
    )


# ── 테스트 클래스 ─────────────────────────────────────────────


class TestLog:
    """AuditTrail.log() — 이벤트를 audit_log 테이블에 적재."""

    def test_six_event_types_inserted(self, audit_trail):
        """6종 이벤트가 각각 action 컬럼으로 저장된다."""
        trail, conn = audit_trail

        for event_type in sorted(VALID_EVENT_TYPES):
            trail.log(
                _make_event(
                    event_type=event_type,
                    user_action=f"{event_type} 액션",
                    batch_id=f"BATCH_{event_type}",
                )
            )

        # audit_log 테이블에서 WU-23 이벤트 6종만 개수 조회
        placeholders = ",".join("?" * len(VALID_EVENT_TYPES))
        sql = f"SELECT action FROM audit_log WHERE action IN ({placeholders})"
        rows = conn.execute(sql, sorted(VALID_EVENT_TYPES)).fetchall()
        actions = {row[0] for row in rows}
        assert actions == VALID_EVENT_TYPES

    def test_user_action_stored_in_details(self, audit_trail):
        """user_action이 details JSON의 'user_action' 키로 저장된다."""
        trail, conn = audit_trail
        trail.log(
            _make_event(
                event_type="upload",
                user_action="test.xlsx 업로드 완료",
                batch_id="BATCH_A",
                details={"filename": "test.xlsx", "rows": 1234},
            )
        )

        sql = "SELECT details FROM audit_log WHERE batch_id = ?"
        row = conn.execute(sql, ["BATCH_A"]).fetchone()
        assert row is not None
        details = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        assert details["user_action"] == "test.xlsx 업로드 완료"
        # 호출자가 넘긴 details의 다른 필드도 보존되어야 한다
        assert details["filename"] == "test.xlsx"
        assert details["rows"] == 1234

    def test_merge_order_defends_against_overwrite(self, audit_trail):
        """호출자가 details['user_action']을 넘겨도 정식 값이 살아남는다.

        Why:
            merged_details = {**event.details, "user_action": event.user_action}
            순서 덕분에 user_action이 최종값. 이 방어선이 유지되는지 회귀 테스트.
        """
        trail, conn = audit_trail
        trail.log(
            _make_event(
                event_type="filter",
                user_action="진짜 행동",
                batch_id="BATCH_DEFENSE",
                details={"user_action": "가짜 행동", "filter": "x>10"},
            )
        )

        row = conn.execute(
            "SELECT details FROM audit_log WHERE batch_id = ?",
            ["BATCH_DEFENSE"],
        ).fetchone()
        details = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        assert details["user_action"] == "진짜 행동"
        assert details["filter"] == "x>10"

    def test_context_fields_persisted(self, audit_trail):
        """batch_id, company_id, engagement_id가 올바른 컬럼에 저장된다."""
        trail, conn = audit_trail
        event = AuditEvent(
            event_type="analysis",
            user_action="파이프라인 실행",
            batch_id="BATCH_C",
            company_id="acme_corp",
            engagement_id="acme_corp_2025",
        )
        trail.log(event)

        row = conn.execute(
            """
            SELECT batch_id, company_id, engagement_id
            FROM audit_log
            WHERE action = 'analysis'
            """
        ).fetchone()
        assert row == ("BATCH_C", "acme_corp", "acme_corp_2025")


class TestInvalidEvent:
    """AuditTrail.log() — 잘못된 event_type은 거부."""

    def test_raises_value_error(self, audit_trail):
        trail, _conn = audit_trail
        with pytest.raises(ValueError, match="invalid event_type"):
            trail.log(
                AuditEvent(
                    event_type="delete",  # type: ignore[arg-type]
                    user_action="잘못된 타입",
                )
            )

    def test_rejected_event_not_inserted(self, audit_trail):
        """거부된 이벤트는 테이블에 들어가지 않는다."""
        trail, conn = audit_trail
        with pytest.raises(ValueError):
            trail.log(
                AuditEvent(
                    event_type="nope",  # type: ignore[arg-type]
                    user_action="rejected",
                    batch_id="BATCH_REJ",
                )
            )
        count = conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE batch_id = ?",
            ["BATCH_REJ"],
        ).fetchone()[0]
        assert count == 0


class TestGetTrail:
    """AuditTrail.get_trail() — 조회 + 필터링 + JSON 컬럼 추출."""

    def test_returns_only_user_events(self, audit_trail):
        """시스템 이벤트(detection_run 등)는 제외된다."""
        trail, conn = audit_trail

        # user 이벤트 3건
        for et in ["upload", "validate", "analysis"]:
            trail.log(
                _make_event(
                    event_type=et,
                    user_action=f"{et} 수행",
                    batch_id="BATCH_MIX",
                )
            )
        # 시스템 이벤트 1건 (record_event 직접 호출)
        record_event(
            conn,
            action="detection_run",
            batch_id="BATCH_MIX",
            details={"total": 100},
        )

        df = trail.get_trail("BATCH_MIX")
        assert len(df) == 3
        assert set(df["event_type"]) == {"upload", "validate", "analysis"}

    def test_batch_id_filter(self, audit_trail):
        """다른 batch_id는 결과에서 제외된다."""
        trail, _conn = audit_trail
        trail.log(_make_event(batch_id="BATCH_X", event_type="upload"))
        trail.log(_make_event(batch_id="BATCH_Y", event_type="upload"))

        df_x = trail.get_trail("BATCH_X")
        assert len(df_x) == 1
        assert (df_x["batch_id"] == "BATCH_X").all()

    def test_user_action_column_extracted(self, audit_trail):
        """DuckDB ->> 연산자로 user_action이 독립 컬럼으로 노출된다."""
        trail, _conn = audit_trail
        trail.log(
            _make_event(
                event_type="query",
                user_action="Text-to-SQL 실행",
                batch_id="BATCH_U",
            )
        )

        df = trail.get_trail("BATCH_U")
        assert "user_action" in df.columns
        # 값이 JSON 문자열이 아닌 원본 문자열이어야 함
        value = df["user_action"].iloc[0]
        assert value == "Text-to-SQL 실행"
        assert not value.startswith('"')  # JSON 직렬화 흔적 없음

    def test_ordered_by_created_at(self, audit_trail):
        """결과가 created_at → id(tie-breaker) 오름차순으로 정렬된다.

        Why:
            인메모리 DuckDB는 빠른 연속 INSERT에서 같은 created_at 값을
            공유할 수 있다. get_trail()의 ORDER BY에서 id가 tie-breaker로
            실질적 순서를 보장하므로, 테스트도 id 단조증가를 함께 검증해
            암묵적 가정을 코드에 명시한다.
        """
        trail, _conn = audit_trail
        order = ["upload", "validate", "analysis", "filter", "export"]
        for et in order:
            trail.log(_make_event(event_type=et, batch_id="BATCH_ORD"))

        df = trail.get_trail("BATCH_ORD")
        assert list(df["event_type"]) == order
        # tie-breaker 가정 명시 — id는 단조증가해야 함
        id_list = df["id"].tolist()
        assert id_list == sorted(id_list)


class TestExportTrail:
    """AuditTrail.export_trail() — CSV 생성."""

    def test_csv_created_with_bom(self, audit_trail, tmp_path):
        """utf-8-sig(BOM 포함) CSV가 생성된다."""
        trail, _conn = audit_trail
        trail.log(
            _make_event(
                event_type="export",
                user_action="감사조서 다운로드",
                batch_id="BATCH_E",
            )
        )
        output = tmp_path / "out" / "trail.csv"
        result = trail.export_trail("BATCH_E", output)

        assert result == output
        assert output.exists()
        # BOM(\xef\xbb\xbf)이 파일 선두에 존재해야 Excel 한글 인식
        with open(output, "rb") as f:
            head = f.read(3)
        assert head == b"\xef\xbb\xbf"

    def test_parent_directory_auto_created(self, audit_trail, tmp_path):
        """output_path의 부모 디렉토리가 없으면 자동 생성된다."""
        trail, _conn = audit_trail
        trail.log(_make_event(batch_id="BATCH_P"))

        deep_path = tmp_path / "a" / "b" / "c" / "trail.csv"
        assert not deep_path.parent.exists()

        trail.export_trail("BATCH_P", deep_path)
        assert deep_path.exists()

    def test_row_count_matches_get_trail(self, audit_trail, tmp_path):
        """CSV 행 수가 get_trail DataFrame과 일치한다."""
        trail, _conn = audit_trail
        for et in ["upload", "validate", "analysis"]:
            trail.log(_make_event(event_type=et, batch_id="BATCH_M"))

        output = tmp_path / "trail.csv"
        trail.export_trail("BATCH_M", output)

        df_from_csv = pd.read_csv(output, encoding="utf-8-sig")
        df_from_trail = trail.get_trail("BATCH_M")
        assert len(df_from_csv) == len(df_from_trail) == 3

    def test_empty_batch_produces_header_only_csv(self, audit_trail, tmp_path):
        """이벤트 0건인 batch_id도 헤더만 있는 CSV를 생성한다 (의도된 동작).

        Why:
            감사 도메인에서 "기록 0건"도 의미 있는 증거이므로 예외를 던지지
            않는다. WU-27 UI에서 필요 시 df.empty 체크로 다운로드 버튼을
            비활성화하는 방식이 더 자연스럽다. 미래에 누가 export_trail()에
            `raise ValueError`를 추가하면 이 테스트가 빨간불로 경고한다.
        """
        trail, _conn = audit_trail
        output = tmp_path / "empty_trail.csv"

        # 예외 없이 파일이 생성되어야 함
        result = trail.export_trail("BATCH_NONEXISTENT", output)
        assert result == output
        assert output.exists()

        # 헤더는 get_trail의 컬럼과 일치, 데이터 행은 0개
        df = pd.read_csv(output, encoding="utf-8-sig")
        assert len(df) == 0
        expected_columns = {
            "id", "event_type", "actor", "company_id", "engagement_id",
            "batch_id", "user_action", "details", "timestamp",
        }
        assert set(df.columns) == expected_columns


class TestGracefulDegradation:
    """log() 실패 시에도 호출측 흐름이 차단되지 않는다."""

    def test_missing_table_does_not_raise(self, audit_trail, caplog):
        """audit_log 테이블을 DROP 해도 log()는 예외를 전파하지 않는다.

        Why:
            기존 record_event가 execute_write 재시도 후 warning만 남기는
            graceful 설계를 따른다. AuditTrail은 그 동작을 상속해야 한다.
        """
        trail, conn = audit_trail
        conn.execute("DROP TABLE audit_log")

        # 예외가 전파되면 테스트 실패. warning 로그만 허용.
        import logging

        with caplog.at_level(logging.WARNING):
            trail.log(
                _make_event(
                    event_type="upload",
                    user_action="테이블 없음",
                    batch_id="BATCH_G",
                )
            )

        assert any("audit_log 기록 실패" in r.message for r in caplog.records)
