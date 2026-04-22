"""WU-27 Export 탭 — 분석 결과를 Excel/PDF/감사 증적 CSV로 내보내기.

2-Step UI 패턴 (중요):
  1) "보고서 생성" 버튼 클릭 시에만 무거운 Exporter 실행 → bytes를 session_state에 캐싱
  2) 다운로드 버튼은 캐시된 bytes만 서빙 (재생성 없음)

Why:
    st.download_button(data=_export_to_bytes(...))처럼 직접 바인딩하면
    체크박스 하나 토글해도 스크립트가 재실행되면서 수십초 걸리는 Excel/PDF
    생성이 백그라운드에서 헛돈다(메모리 폭주). Streamlit의 반복 렌더링 특성상
    "비용이 큰 작업은 사용자 명시적 액션 뒤에만 실행"이 원칙.

다운로드 종류:
    - Excel: ExcelExporter (5~6시트)
    - PDF:   PDFExporter (6섹션)
    - 감사 증적 CSV: AuditTrail.get_trail() 전용.
      ⚠️ `audit_log_by_batch` 프리셋 금지 — 시스템 이벤트(detection_run 등)가
      섞여 감사인에게 혼동을 준다. TASKS.md WU-27 주의 블록 참조.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

import streamlit as st

from dashboard._state import (
    KEY_BATCH_ID,
    KEY_COMPANY_CONTEXT,
    KEY_EXPORT_FORMAT,
    KEY_EXPORT_READY_DATA,
    KEY_EXPORT_READY_HASH,
    KEY_EXPORT_READY_MIME,
    KEY_EXPORT_READY_NAME,
    KEY_FILTERS,
)
from src.export.audit_trail import AuditEvent, AuditTrail
from src.export.excel_exporter import ExcelExporter
from src.export.models import DEFAULT_REPORT_TITLE, ExportConfig, ExportFilter
from src.export.pdf_exporter import PDFExporter

if TYPE_CHECKING:
    import duckdb

    from src.context import CompanyContext
    from src.pipeline import PipelineResult

logger = logging.getLogger(__name__)

# ── 상수 ───────────────────────────────────────────────────────
FORMAT_EXCEL = "Excel"
FORMAT_PDF = "PDF"
FORMAT_CSV = "감사 증적 CSV"
FORMAT_OPTIONS = (FORMAT_EXCEL, FORMAT_PDF, FORMAT_CSV)

_MIME_MAP: dict[str, str] = {
    FORMAT_EXCEL: (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ),
    FORMAT_PDF: "application/pdf",
    FORMAT_CSV: "text/csv",
}
_EXT_MAP: dict[str, str] = {FORMAT_EXCEL: "xlsx", FORMAT_PDF: "pdf", FORMAT_CSV: "csv"}


# ── 순수 헬퍼 (테스트 대상) ────────────────────────────────────

def _build_filter(filter_state: dict | None) -> ExportFilter:
    """사이드바 FilterState dict → ExportFilter.

    Why: FilterState는 7~9개 차원을 가지나, ExportFilter는 Exporter가 지원하는
    6개 필드만 수용. 겹치는 필드는 전달하고 date_range(tuple[str, str])는
    date_from/date_to(date)로 파싱한다.
    """
    fs = filter_state or {}

    def _nonempty(v: Any) -> Any:
        """빈 리스트/문자열/None → None. ExportFilter.is_empty()가 제대로 동작하도록."""
        if v in (None, "", [], ()):
            return None
        return v

    date_from, date_to = None, None
    dr = fs.get("date_range")
    if dr and isinstance(dr, (tuple, list)) and len(dr) == 2:
        # Why: ISO 문자열 또는 date 객체 모두 수용 — 사이드바 구현이 바뀌어도 내성.
        date_from = _parse_date(dr[0])
        date_to = _parse_date(dr[1])

    return ExportFilter(
        company_codes=_nonempty(fs.get("company_codes")),
        business_processes=_nonempty(fs.get("business_processes")),
        risk_levels=_nonempty(fs.get("risk_levels")),
        document_types=_nonempty(fs.get("document_types")),
        date_from=date_from,
        date_to=date_to,
    )


def _parse_date(value: Any) -> date | None:
    """ISO 문자열/date/datetime 입력을 date로 통일."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def _build_config_from_form(form: dict[str, Any]) -> ExportConfig:
    """UI 폼 dict → ExportConfig. 누락된 키는 dataclass 기본값 사용."""
    return ExportConfig(
        mask_pii=bool(form.get("mask_pii", True)),
        top_n=int(form.get("top_n", 50)),
        include_raw_data=bool(form.get("include_raw_data", True)),
        include_phase1_cases=bool(form.get("include_phase1_cases", True)),
        report_title=str(form.get("report_title") or DEFAULT_REPORT_TITLE),
        analyst_name=str(form.get("analyst_name") or ""),
    )


def _settings_hash(
    fmt: str,
    filters: ExportFilter,
    config: ExportConfig,
    batch_id: str | None,
) -> str:
    """포맷/필터/설정/배치ID 스냅샷의 SHA-1 해시 — 캐시 무효화 키."""
    # Why: dataclass → dict 직렬화. date는 isoformat으로 안정 문자열화.
    payload = {
        "fmt": fmt,
        "batch_id": batch_id,
        "filter": _stringify(asdict(filters)),
        "config": _stringify(asdict(config)),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _stringify(obj: Any) -> Any:
    """dict/list 내부의 date/datetime을 isoformat 문자열로 정규화."""
    if isinstance(obj, dict):
        return {k: _stringify(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_stringify(v) for v in obj]
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    return obj


def _sanitize_filename(name: str) -> str:
    """파일명 안전 문자만 유지 — 한글·영숫자·하이픈·언더스코어·점."""
    cleaned = re.sub(r"[^\w가-힣.\-]", "_", name.strip())
    # Why: 과도한 연속 언더스코어 압축 + 최대 80자 제한(파일시스템 호환)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_.")
    return cleaned[:80] or "report"


def _make_filename(fmt: str, title: str, batch_id: str | None) -> str:
    """{sanitized_title}_{batch_id}_{yyyymmdd_HHMMSS}.{ext}"""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bid = _sanitize_filename(batch_id or "nobatch")
    base = _sanitize_filename(title)
    ext = _EXT_MAP[fmt]
    return f"{base}_{bid}_{stamp}.{ext}"


def _build_audit_event(
    fmt: str,
    batch_id: str | None,
    ctx: CompanyContext,
    file_name: str,
) -> AuditEvent:
    """다운로드 이벤트 AuditEvent 생성 — on_click 콜백에서 사용."""
    return AuditEvent(
        event_type="export",
        user_action=f"{fmt} 다운로드",
        details={"format": fmt, "file_name": file_name},
        batch_id=batch_id,
        company_id=ctx.company_id if not ctx.is_anonymous else None,
        engagement_id=ctx.engagement_id if not ctx.is_anonymous else None,
    )


# ── Exporter 실행 (bytes 생성) ────────────────────────────────

def _export_to_bytes(
    fmt: str,
    pipeline_result: PipelineResult,
    filters: ExportFilter,
    config: ExportConfig,
    conn: duckdb.DuckDBPyConnection,
) -> bytes:
    """포맷에 따라 Exporter 실행 → bytes 반환. tmp 파일 누수 방지 컨텍스트 사용."""
    # Why: 알 수 없는 포맷은 _EXT_MAP KeyError 대신 의미 있는 ValueError로 조기 거부
    if fmt not in FORMAT_OPTIONS:
        raise ValueError(f"지원하지 않는 포맷: {fmt}")
    if fmt == FORMAT_CSV:
        return _export_audit_csv(pipeline_result.batch_id, conn)

    if fmt == FORMAT_EXCEL:
        return ExcelExporter(conn).export_bytes(pipeline_result, filters, config)
    return PDFExporter(conn).export_bytes(pipeline_result, filters, config)


def _export_audit_csv(
    batch_id: str | None,
    conn: duckdb.DuckDBPyConnection,
) -> bytes:
    """AuditTrail.get_trail() → utf-8-sig CSV bytes.

    ⚠️ `audit_log_by_batch` 프리셋 사용 금지. 프리셋은 detection_run 등
    시스템 이벤트를 포함해 다운로드 파일에 혼동을 준다.
    """
    if not batch_id:
        # Why: 배치 없이는 증적이 존재할 수 없음 — 빈 CSV 반환보다 명시적 오류가 안전
        raise ValueError("batch_id 없음 — 파이프라인 실행 후 다시 시도하세요.")
    df = AuditTrail(conn).get_trail(batch_id)
    if df.empty:
        # Why: 헤더만 있는 빈 CSV는 감사인에게 "파이프라인은 돌았는데 기록이 왜 없나"
        #      혼동을 준다. AuditTrail 미주입·로깅 실패 등 업스트림 누락 신호이므로
        #      명시적으로 거부해 재실행을 유도.
        raise ValueError(
            f"배치 {batch_id}의 감사 증적이 없습니다. "
            "파이프라인을 다시 실행한 뒤 시도하세요.",
        )
    # Why: Excel에서 한글이 깨지지 않도록 BOM 포함
    return df.to_csv(index=False).encode("utf-8-sig")


# ── 캐시 관리 ──────────────────────────────────────────────────

def _invalidate_cache_if_stale(current_hash: str) -> None:
    """session_state의 export 캐시가 stale이면 초기화."""
    ss = st.session_state
    if ss.get(KEY_EXPORT_READY_HASH) != current_hash:
        for key in (
            KEY_EXPORT_READY_DATA,
            KEY_EXPORT_READY_NAME,
            KEY_EXPORT_READY_MIME,
            KEY_EXPORT_READY_HASH,
        ):
            ss[key] = None


def _store_ready(data: bytes, file_name: str, mime: str, current_hash: str) -> None:
    """생성 성공 시 session_state 캐시 갱신."""
    ss = st.session_state
    ss[KEY_EXPORT_READY_DATA] = data
    ss[KEY_EXPORT_READY_NAME] = file_name
    ss[KEY_EXPORT_READY_MIME] = mime
    ss[KEY_EXPORT_READY_HASH] = current_hash


# ── 렌더 ───────────────────────────────────────────────────────

def _render_filter_form(filter_state: dict) -> ExportFilter:
    """ExportFilter UI — 사이드바 FilterState 기본값 주입."""
    with st.expander("내보내기 필터", expanded=False):
        st.caption("사이드바 필터 값을 기본으로 로드했습니다. 필요 시 조정하세요.")
        # Why: 사이드바 필터가 이미 df 기반으로 구축되므로 여기서는 그대로 전달
        # 복잡한 UI를 덧붙이지 않고 현재 사이드바 상태를 적용한다.
        ef = _build_filter(filter_state)
        if ef.is_empty():
            st.caption("현재 필터: (전체)")
        else:
            summary = []
            if ef.risk_levels:
                summary.append(f"위험등급 {ef.risk_levels}")
            if ef.business_processes:
                summary.append(f"프로세스 {ef.business_processes}")
            if ef.date_from or ef.date_to:
                summary.append(f"기간 {ef.date_from}~{ef.date_to}")
            if ef.company_codes:
                summary.append(f"회사 {ef.company_codes}")
            if ef.document_types:
                summary.append(f"문서유형 {ef.document_types}")
            st.caption("현재 필터: " + " / ".join(summary))
    return ef


def _render_config_form() -> ExportConfig:
    """ExportConfig UI."""
    with st.expander("보고서 옵션", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            report_title = st.text_input(
                "보고서 제목", value=DEFAULT_REPORT_TITLE, key="export_report_title",
            )
            analyst_name = st.text_input(
                "분석자", value="", key="export_analyst_name",
            )
            mask_pii = st.checkbox(
                "PII 마스킹", value=True, key="export_mask_pii",
                help="작성자/승인자 SHA-256 해싱 + 보조계정 부분 치환",
            )
        with col2:
            top_n = st.slider(
                "이상 전표 표시 상한", min_value=10, max_value=200, value=50, step=10,
                key="export_top_n",
            )
            include_raw_data = st.checkbox(
                "원본 데이터 시트 포함 (Excel)", value=True, key="export_include_raw",
            )
            include_phase1_cases = st.checkbox(
                "PHASE1 case 요약 포함", value=True, key="export_include_phase1",
            )
    return _build_config_from_form({
        "mask_pii": mask_pii,
        "top_n": top_n,
        "include_raw_data": include_raw_data,
        "include_phase1_cases": include_phase1_cases,
        "report_title": report_title,
        "analyst_name": analyst_name,
    })


def _get_conn(ctx: CompanyContext) -> duckdb.DuckDBPyConnection:
    """CompanyContext.db_path로 공유 커넥션 획득 (tab_chat과 동일 패턴)."""
    from src.db.connection import get_connection

    return get_connection(str(ctx.db_path))


def render(result: PipelineResult | None) -> None:
    """Export 탭 엔트리포인트. app.py에서 호출."""
    if result is None:
        st.info("파이프라인을 먼저 실행하세요.")
        return

    ctx: CompanyContext | None = st.session_state.get(KEY_COMPANY_CONTEXT)
    batch_id: str | None = st.session_state.get(KEY_BATCH_ID) or result.batch_id

    if ctx is None or ctx.is_anonymous:
        st.warning("회사/연도를 먼저 선택하세요.")
        return
    if not batch_id:
        st.info("배치 ID가 없어 내보낼 수 없습니다.")
        return

    st.subheader("분석 결과 내보내기")
    st.caption("메인 분석 흐름의 마지막 단계입니다. 현재 필터와 선택한 옵션을 기준으로 보고서와 감사 증적 파일을 생성합니다.")

    fmt = st.radio(
        "포맷",
        options=FORMAT_OPTIONS,
        horizontal=True,
        key=KEY_EXPORT_FORMAT,
    )

    filter_state = st.session_state.get(KEY_FILTERS, {}) or {}
    filters = _render_filter_form(filter_state)
    config = _render_config_form()

    current_hash = _settings_hash(fmt, filters, config, batch_id)
    _invalidate_cache_if_stale(current_hash)

    # Step A — 생성 버튼
    if st.button("📋 보고서 생성", type="primary", use_container_width=True):
        with st.spinner(f"{fmt} 보고서를 생성 중..."):
            try:
                conn = _get_conn(ctx)
                data = _export_to_bytes(fmt, result, filters, config, conn)
                file_name = _make_filename(fmt, config.report_title, batch_id)
                mime = _MIME_MAP[fmt]
                _store_ready(data, file_name, mime, current_hash)
                st.success(f"{file_name} 생성 완료 ({len(data):,} bytes)")
            except Exception as exc:
                logger.exception("Export 생성 실패")
                st.error(f"생성 실패: {exc}")
                return

    # Step B — 다운로드 버튼 (캐시된 bytes만 서빙)
    ss = st.session_state
    if ss.get(KEY_EXPORT_READY_DATA) is not None:
        file_name = ss[KEY_EXPORT_READY_NAME]
        st.download_button(
            label=f"📥 {file_name} 다운로드",
            data=ss[KEY_EXPORT_READY_DATA],
            file_name=file_name,
            mime=ss[KEY_EXPORT_READY_MIME],
            use_container_width=True,
            on_click=_on_download_click,
            kwargs={"fmt": fmt, "file_name": file_name, "ctx": ctx, "batch_id": batch_id},
        )
    else:
        st.caption("'보고서 생성'을 눌러 파일을 만든 뒤 다운로드 버튼이 활성화됩니다.")


def _on_download_click(
    *, fmt: str, file_name: str, ctx: CompanyContext, batch_id: str,
) -> None:
    """다운로드 버튼 on_click — AuditTrail에 export 이벤트 기록.

    Why: 생성(Step A) 단계에서 로깅하면 다운로드 안 해도 이벤트가 남아 혼동.
         실제 브라우저 다운로드 트리거 시점에 기록한다.
    """
    try:
        conn = _get_conn(ctx)
        AuditTrail(conn).log(_build_audit_event(fmt, batch_id, ctx, file_name))
    except Exception:  # pragma: no cover — 방어적
        logger.warning("Export AuditTrail.log 실패", exc_info=True)
