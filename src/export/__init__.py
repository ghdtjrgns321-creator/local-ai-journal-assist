"""데이터분석 보고서 export 패키지 (WU-23~27).

Why:
    감사인이 자신의 감사조서에 첨부할 ``데이터 분석 결과 보고서``를
    Excel/PDF로 출력하고, 모든 사용자 활동을 audit_log에 누적한다.
    이 도구는 감사조서를 직접 산출하지 않으며, 분석 결과를 객관적으로
    정리한 보조 자료를 생성한다 (ISA 230 준수는 감사인의 책임).

구성 모듈:
    - audit_trail:    사용자 활동 기록 (WU-23)
    - audit_evidence: 개별 전표의 분석 증거 문구 생성
    - models:         ExportFilter, ExportConfig, 컬럼 매핑 상수
    - masking:        PII 마스킹 (작성자/승인자 SHA-256, 보조계정 부분 치환)
    - excel_exporter: Excel 5~6시트 보고서 (WU-24)
    - pdf_exporter:   PDF 6섹션 보고서 (WU-24)
"""

from src.export.audit_evidence import (
    RULE_LEGAL_BASIS,
    AuditEvidence,
    build_evidence_report,
    build_evidence_row,
    format_narrative,
)
from src.export.audit_trail import (
    VALID_EVENT_TYPES,
    AuditEvent,
    AuditTrail,
    EventType,
)
from src.export.excel_exporter import ExcelExporter
from src.export.masking import mask_dataframe
from src.export.models import (
    DEFAULT_REPORT_TITLE,
    DETECTION_COLUMNS,
    DISCLAIMER,
    EXCLUDE_COLUMNS,
    HEADER_COLUMNS,
    LINE_COLUMNS,
    MASK_TARGETS,
    RISK_FILL_COLORS,
    ExportConfig,
    ExportFilter,
)
from src.export.pdf_exporter import PDFExporter
from src.export.query_helper import build_where_clause, safe_query
from src.export.label_splitter import split_label_columns, split_label_csv

__all__ = [
    # audit_trail
    "AuditEvent",
    "AuditTrail",
    "EventType",
    "VALID_EVENT_TYPES",
    # audit_evidence
    "AuditEvidence",
    "RULE_LEGAL_BASIS",
    "build_evidence_report",
    "build_evidence_row",
    "format_narrative",
    # models
    "DEFAULT_REPORT_TITLE",
    "DETECTION_COLUMNS",
    "DISCLAIMER",
    "EXCLUDE_COLUMNS",
    "ExportConfig",
    "ExportFilter",
    "HEADER_COLUMNS",
    "LINE_COLUMNS",
    "MASK_TARGETS",
    "RISK_FILL_COLORS",
    # masking
    "mask_dataframe",
    "split_label_columns",
    "split_label_csv",
    # exporters
    "ExcelExporter",
    "PDFExporter",
    # query_helper
    "build_where_clause",
    "safe_query",
]
