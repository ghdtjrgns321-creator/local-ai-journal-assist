"""WU-24 PDF 데이터분석 보고서 생성기.

Why:
    감사인이 결과를 인쇄/공유 가능한 단일 문서로 받기 위한 6섹션 PDF.
    감사조서가 아님을 표지 면책조항에서 명시한다.

설계 결정:
    - fpdf2 (한글 폰트 지원, 의존성 작음)
    - kaleido(차트 PNG 변환) hang 방지 → ThreadPoolExecutor + timeout
    - 차트 실패 시 표 fallback (대시보드 블로킹 방지)
    - 한글 폰트는 OS별 시스템 폰트를 순차 탐색
"""

from __future__ import annotations

import io
import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutTimeout
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd
from fpdf import FPDF

from src.detection.constants import get_track_display_label
from src.export.models import (
    DISCLAIMER,
    ExportConfig,
    ExportFilter,
)
from src.export.phase1_case_view import build_phase1_case_queue, summarize_phase1_case_result
from src.export.query_helper import build_where_clause, safe_query

if TYPE_CHECKING:
    import duckdb

    from src.pipeline import PipelineResult

logger = logging.getLogger(__name__)

# Why: OS별 한글 폰트 후보. malgun(맑은고딕) → NanumGothic → AppleGothic 순.
_FONT_CANDIDATES: list[Path] = [
    Path("C:/Windows/Fonts/malgun.ttf"),
    Path("C:/Windows/Fonts/NanumGothic.ttf"),
    Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    Path("/Library/Fonts/AppleGothic.ttf"),
    Path("/System/Library/Fonts/Supplemental/AppleGothic.ttf"),
]

_FONT_NAME = "Korean"
_KALEIDO_TIMEOUT_SEC = 10


class PDFExporter:
    """DuckDB 기반 데이터분석 보고서 PDF 생성기."""

    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self._conn = conn

    # ── public API ────────────────────────────────────────────
    def export(
        self,
        pipeline_result: PipelineResult,
        output_path: Path,
        filters: ExportFilter | None = None,
        config: ExportConfig | None = None,
    ) -> Path:
        """PDF 파일을 생성하고 경로를 반환한다."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(
            self.export_bytes(
                pipeline_result,
                filters=filters,
                config=config,
            )
        )
        return output_path

    def export_bytes(
        self,
        pipeline_result: PipelineResult,
        filters: ExportFilter | None = None,
        config: ExportConfig | None = None,
    ) -> bytes:
        filters = filters or ExportFilter()
        config = config or ExportConfig()

        pdf = FPDF()
        self._register_korean_font(pdf)
        pdf.set_auto_page_break(auto=True, margin=15)

        where_sql, params = build_where_clause(filters, pipeline_result.batch_id)

        self._render_cover(pdf, pipeline_result, config)
        self._render_summary(pdf, pipeline_result, config)
        self._render_process_distribution(pdf, where_sql, params)
        self._render_benford(pdf, pipeline_result.batch_id)
        self._render_top_anomalies(pdf, where_sql, params, config.top_n)
        self._render_rules_and_sod(pdf, pipeline_result.batch_id)

        rendered = pdf.output()
        if isinstance(rendered, str):
            return rendered.encode("latin-1")
        return bytes(rendered)

    # ── 섹션 ──────────────────────────────────────────────────
    def _render_cover(self, pdf: FPDF, pr: PipelineResult, config: ExportConfig) -> None:
        pdf.add_page()
        pdf.set_font(_FONT_NAME, size=22)
        pdf.ln(40)
        pdf.cell(0, 12, config.report_title, align="C", new_x="LMARGIN", new_y="NEXT")

        pdf.set_font(_FONT_NAME, size=11)
        pdf.ln(20)
        pdf.cell(0, 8, f"배치 ID: {pr.batch_id}", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 8, f"총 행 수: {len(pr.data):,}", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 8, f"분석 소요(초): {pr.elapsed:.2f}", new_x="LMARGIN", new_y="NEXT")
        if config.analyst_name:
            pdf.cell(0, 8, f"분석자: {config.analyst_name}", new_x="LMARGIN", new_y="NEXT")

        pdf.ln(50)
        pdf.set_font(_FONT_NAME, size=9, style="I")
        # multi_cell로 줄바꿈 자동 처리
        pdf.multi_cell(0, 6, DISCLAIMER, align="L")

    def _render_summary(self, pdf: FPDF, pr: PipelineResult, config: ExportConfig) -> None:
        pdf.add_page()
        self._section_title(pdf, "1. 분석 요약")

        rows = [("위험 등급", "건수")]
        for risk in ("High", "Medium", "Low", "Normal"):
            rows.append((risk, str(pr.risk_summary.get(risk, 0))))
        self._render_table(pdf, rows, col_widths=[60, 40])
        phase1_summary = summarize_phase1_case_result(pr)
        if config.include_phase1_cases and phase1_summary.get("available"):
            pdf.ln(6)
            pdf.set_font(_FONT_NAME, size=11, style="B")
            pdf.cell(0, 7, "PHASE1 Case Queue", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font(_FONT_NAME, size=10)
            pdf.cell(
                0,
                7,
                f"Case 수: {phase1_summary['case_count']}",
                new_x="LMARGIN",
                new_y="NEXT",
            )
            pdf.cell(
                0,
                7,
                f"Top Themes: {', '.join(phase1_summary.get('top_theme_labels', []))}",
                new_x="LMARGIN",
                new_y="NEXT",
            )
            top_cases = build_phase1_case_queue(pr, top_n=3)
            if top_cases:
                phase1_rows = [("Case ID", "Theme", "Amount")]
                phase1_rows.extend(
                    (
                        str(case["case_id"]),
                        str(case["primary_theme_label"]),
                        f"{case['total_amount']:,.0f}",
                    )
                    for case in top_cases
                )
                self._render_table(pdf, phase1_rows, col_widths=[50, 55, 45])

    def _render_process_distribution(self, pdf: FPDF, where_sql: str, params: list[Any]) -> None:
        pdf.add_page()
        self._section_title(pdf, "2. 비즈니스 프로세스/시간 분포")

        sql = f"""
            SELECT business_process AS 프로세스,
                   COUNT(*) AS 행수,
                   ROUND(AVG(anomaly_score), 4) AS 평균이상점수
            FROM general_ledger
            WHERE 1=1 {where_sql}
            GROUP BY business_process
            ORDER BY 행수 DESC
        """
        df = self._safe_query(sql, params)
        if df.empty:
            pdf.cell(0, 8, "데이터 없음", new_x="LMARGIN", new_y="NEXT")
            return
        rows = [tuple(str(c) for c in df.columns)]
        rows.extend(tuple(str(v) for v in row) for _, row in df.iterrows())
        self._render_table(pdf, rows, col_widths=[60, 40, 50])

    def _render_benford(self, pdf: FPDF, batch_id: str) -> None:
        pdf.add_page()
        self._section_title(pdf, "3. Benford 분석")

        summary = self._safe_query(
            "SELECT mad, mad_conformity, chi2_p_value, is_conforming, confidence "
            "FROM benford_summary WHERE upload_batch_id = ?",
            [batch_id],
        )
        if summary.empty:
            pdf.cell(0, 8, "Benford 분석 데이터 없음", new_x="LMARGIN", new_y="NEXT")
            return
        s = summary.iloc[0]
        pdf.set_font(_FONT_NAME, size=10)
        pdf.cell(0, 7, f"MAD: {s['mad']} ({s['mad_conformity']})", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 7, f"Chi-square p-value: {s['chi2_p_value']}", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(
            0,
            7,
            f"적합 판정: {'예' if s['is_conforming'] else '아니오'} (신뢰도: {s['confidence']})",
            new_x="LMARGIN",
            new_y="NEXT",
        )

        digits = self._safe_query(
            "SELECT digit, observed_freq, expected_freq, deviation "
            "FROM benford_digits WHERE upload_batch_id = ? ORDER BY digit",
            [batch_id],
        )
        if not digits.empty:
            pdf.ln(4)
            rows = [tuple(str(c) for c in digits.columns)]
            rows.extend(tuple(str(v) for v in row) for _, row in digits.iterrows())
            self._render_table(pdf, rows, col_widths=[20, 35, 35, 35])

    def _render_top_anomalies(
        self, pdf: FPDF, where_sql: str, params: list[Any], top_n: int
    ) -> None:
        pdf.add_page()
        self._section_title(pdf, f"4. 이상 전표 상위 {top_n}건")
        sql = f"""
            SELECT document_id, company_code, posting_date,
                   risk_level, ROUND(anomaly_score, 3) AS score, flagged_rules
            FROM general_ledger
            WHERE risk_level IS NOT NULL AND risk_level <> 'Normal'
              {where_sql}
            ORDER BY anomaly_score DESC NULLS LAST
            LIMIT ?
        """
        df = self._safe_query(sql, [*params, top_n])
        if df.empty:
            pdf.cell(0, 8, "이상 전표 없음", new_x="LMARGIN", new_y="NEXT")
            return
        rows = [tuple(str(c) for c in df.columns)]
        rows.extend(tuple(str(v) for v in row) for _, row in df.iterrows())
        self._render_table(pdf, rows, col_widths=[35, 25, 35, 20, 20, 50])

    def _render_rules_and_sod(self, pdf: FPDF, batch_id: str) -> None:
        pdf.add_page()
        self._section_title(pdf, "5. 탐지 규칙 통계 + 직무분리 요약")

        rules = self._safe_query(
            """
            SELECT track_name, rule_code, COUNT(*) AS 탐지건수,
                   ROUND(AVG(score), 3) AS 평균점수
            FROM anomaly_flags
            WHERE upload_batch_id = ?
            GROUP BY track_name, rule_code
            ORDER BY track_name, rule_code
            """,
            [batch_id],
        )
        if rules.empty:
            pdf.cell(0, 8, "탐지 규칙 데이터 없음", new_x="LMARGIN", new_y="NEXT")
        else:
            if {"track_name", "rule_code"}.issubset(rules.columns):
                rules.insert(
                    0,
                    "rule_group",
                    [
                        get_track_display_label(track_name, rule_code)
                        for track_name, rule_code in zip(
                            rules["track_name"],
                            rules["rule_code"],
                            strict=True,
                        )
                    ],
                )
                rules = rules.drop(columns=["track_name"])
            rows = [tuple(str(c) for c in rules.columns)]
            rows.extend(tuple(str(v) for v in row) for _, row in rules.iterrows())
            self._render_table(pdf, rows, col_widths=[35, 30, 35, 35])

        sod = self._safe_query(
            """
            SELECT rule_code AS SoD규칙, COUNT(*) AS 위반건수
            FROM anomaly_flags
            WHERE upload_batch_id = ? AND rule_code IN ('L1-05', 'L1-06', 'L1-07')
            GROUP BY rule_code
            ORDER BY rule_code
            """,
            [batch_id],
        )
        pdf.ln(6)
        pdf.set_font(_FONT_NAME, size=11, style="B")
        pdf.cell(0, 7, "직무분리(SoD) 위반 요약", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(_FONT_NAME, size=10)
        if sod.empty:
            pdf.cell(0, 7, "SoD 위반 없음", new_x="LMARGIN", new_y="NEXT")
            return
        rows = [tuple(str(c) for c in sod.columns)]
        rows.extend(tuple(str(v) for v in row) for _, row in sod.iterrows())
        self._render_table(pdf, rows, col_widths=[60, 40])

    # ── helpers ───────────────────────────────────────────────
    def _register_korean_font(self, pdf: FPDF) -> None:
        """OS별 한글 폰트 탐색 후 등록. 미발견 시 RuntimeError."""
        for path in _FONT_CANDIDATES:
            if path.exists():
                # Why: fpdf2 v2.5.1+에서 uni=True는 deprecated, 기본이 unicode임
                pdf.add_font(_FONT_NAME, "", str(path))
                # B(굵게)/I(기울임)는 동일 파일 재사용 (별도 폰트 부재 시 최선)
                pdf.add_font(_FONT_NAME, "B", str(path))
                pdf.add_font(_FONT_NAME, "I", str(path))
                pdf.set_font(_FONT_NAME, size=10)
                logger.info("PDF 한글 폰트 등록: %s", path)
                return
        raise RuntimeError(
            f"한글 폰트를 찾을 수 없습니다. 후보: {[str(p) for p in _FONT_CANDIDATES]}"
        )

    def _section_title(self, pdf: FPDF, title: str) -> None:
        pdf.set_font(_FONT_NAME, size=14, style="B")
        pdf.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        pdf.set_font(_FONT_NAME, size=10)

    def _render_table(
        self, pdf: FPDF, rows: list[tuple[str, ...]], col_widths: list[float]
    ) -> None:
        """단순 표 렌더링 — 첫 행은 헤더, 나머지는 데이터.

        Why:
            kaleido 의존을 피하고 항상 동작하는 fallback. 차트 대신 표만으로도
            보고서로서 충분한 정보를 제공.
            col_widths 길이가 실제 컬럼 수와 다르면 균등 분배로 fallback해
            쿼리 결과 컬럼 변경 시 IndexError로 PDF 전체가 깨지는 것을 막는다.
        """
        if not rows:
            return
        n_cols = len(rows[0])
        if len(col_widths) != n_cols:
            page_w = pdf.w - pdf.l_margin - pdf.r_margin
            col_widths = [page_w / n_cols] * n_cols
            logger.warning("_render_table col_widths 불일치 → 균등 분배 (n_cols=%d)", n_cols)

        pdf.set_font(_FONT_NAME, size=9, style="B")
        for i, value in enumerate(rows[0]):
            pdf.cell(col_widths[i], 7, value, border=1, align="C")
        pdf.ln()

        pdf.set_font(_FONT_NAME, size=9)
        for row in rows[1:]:
            for i, value in enumerate(row):
                # Why: 셀 폭 초과 텍스트 잘림 — 안전 컷
                text = value if len(value) <= 40 else value[:37] + "..."
                pdf.cell(col_widths[i], 6, text, border=1)
            pdf.ln()

    def _safe_query(self, sql: str, params: list[Any]) -> pd.DataFrame:
        """query_helper.safe_query 위임."""
        return safe_query(self._conn, sql, params)

    def _safe_chart_to_png(self, fig: Any) -> bytes | None:
        """Plotly 차트 → PNG bytes. timeout/예외 시 None.

        Why:
            kaleido는 특정 환경(컨테이너 등)에서 프로세스가 죽지 않고
            무한 대기하는 고질 버그가 있어 PDF 생성을 블로킹할 수 있다.
            ThreadPoolExecutor로 강제 시간제한을 적용하고 실패 시 표로 fallback.
        """
        try:
            with ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(fig.to_image, format="png")
                return future.result(timeout=_KALEIDO_TIMEOUT_SEC)
        except (FutTimeout, Exception) as exc:  # noqa: BLE001
            logger.warning("차트 렌더링 실패 → 표 fallback: %s", exc)
            return None

    def _embed_chart_or_fallback(
        self,
        pdf: FPDF,
        fig: Any,
        fallback_rows: list[tuple[str, ...]],
        col_widths: list[float],
        width_mm: float = 180,
    ) -> None:
        """차트 임베드 시도 → 실패 시 표 출력.

        Why:
            모든 차트 호출은 이 메서드를 경유 (직접 `fig.to_image` 금지).
        """
        png = self._safe_chart_to_png(fig)
        if png:
            pdf.image(io.BytesIO(png), w=width_mm)
        else:
            pdf.set_font(_FONT_NAME, size=9, style="I")
            pdf.cell(0, 6, "[차트 렌더링 생략됨 — 아래 표 참조]", new_x="LMARGIN", new_y="NEXT")
            self._render_table(pdf, fallback_rows, col_widths)


__all__ = ["PDFExporter"]
