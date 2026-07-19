"""WU-24 데이터분석 보고서 — 필터/설정 모델과 컬럼 매핑 상수.

Why:
    Excel/PDF Exporter가 공통으로 참조하는 데이터 모델과 컬럼 매핑을 한곳에 모은다.
    감사조서가 아닌 "데이터 분석 결과 보고서" 산출을 목표로 하므로 면책조항 등
    중립 표현 상수도 함께 둔다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

# Why: 한 곳에서 보고서 명칭을 바꿀 수 있도록 상수화. Excel/PDF/대시보드가 공유.
DEFAULT_REPORT_TITLE: str = "데이터 분석 결과 보고서"

# Why: 감사인이 보고서를 자신의 감사조서에 첨부할 때 명시할 면책 문구.
#      "감사 의견을 구성하지 않는다"를 강조해 도구의 역할 한계를 분명히 한다.
DISCLAIMER: str = (
    "본 보고서는 자동화된 데이터 분석 결과이며, "
    "전문가적 감사 의견을 구성하지 않습니다. "
    "감사인의 독립적 판단에 의한 검토가 필요합니다."
)


@dataclass
class ExportFilter:
    """대시보드 필터 상태 → Exporter WHERE 절로 전달."""

    company_codes: list[str] | None = None
    business_processes: list[str] | None = None
    risk_levels: list[str] | None = None  # ["High", "Medium"] 등
    date_from: date | None = None
    date_to: date | None = None
    document_types: list[str] | None = None

    def is_empty(self) -> bool:
        """모든 필드가 None이면 True (필터 미적용)."""
        return all(
            v is None
            for v in (
                self.company_codes,
                self.business_processes,
                self.risk_levels,
                self.date_from,
                self.date_to,
                self.document_types,
            )
        )


@dataclass
class ExportConfig:
    """내보내기 옵션."""

    mask_pii: bool = False
    top_n: int = 50  # PDF 이상 전표 테이블 건수 + Excel anomalies 정렬 제한 안내
    include_raw_data: bool = True  # Excel 원본 데이터 시트 포함 여부
    include_phase1_cases: bool = True  # PHASE1 case queue 요약 포함 여부
    report_title: str = DEFAULT_REPORT_TITLE
    analyst_name: str = ""  # 표지 표시용 (마스킹 대상 아님)
    extra_meta: dict = field(default_factory=dict)  # 회사명·기간 등 자유 메타


# ── 컬럼 매핑 ────────────────────────────────────────────────
# Why: 09-export.md §35-110의 한글 헤더 정책을 그대로 코드화.
#      DataFrame.rename(columns=...)에 직접 사용한다.

HEADER_COLUMNS: dict[str, str] = {
    "document_id": "전표ID",
    "company_code": "회사코드",
    "fiscal_year": "회계연도",
    "fiscal_period": "회계기간",
    "posting_date": "전기일시",
    "document_date": "증빙일",
    "document_type": "전표유형",
    "currency": "통화",
    "exchange_rate": "환율",
    "reference": "참조번호",
    "header_text": "전표 적요",
    "created_by": "작성자",
    "user_persona": "사용자 유형",
    "source": "전표 소스",
    "business_process": "비즈니스 프로세스",
    "ledger": "원장",
    "approved_by": "승인자",
    "approval_date": "승인일시",
}

LINE_COLUMNS: dict[str, str] = {
    "line_number": "라인번호",
    "gl_account": "계정과목",
    "debit_amount": "차변금액",
    "credit_amount": "대변금액",
    "local_amount": "현지통화금액",
    "cost_center": "코스트센터",
    "profit_center": "프로핏센터",
    "line_text": "라인 적요",
    "tax_code": "세금코드",
    "tax_amount": "세액",
    "trading_partner": "거래처",
    "auxiliary_account_number": "보조계정번호",
    "auxiliary_account_label": "보조계정명",
    "lettrage": "조정ID",
    "lettrage_date": "조정일자",
}

DETECTION_COLUMNS: dict[str, str] = {
    "anomaly_score": "이상점수",
    "risk_level": "위험등급",
    "flagged_rules": "탐지규칙",
}

# Why: DataSynth 라벨 컬럼은 외부 보고서에 노출 금지. (정답 라벨 누설 방지)
EXCLUDE_COLUMNS: frozenset[str] = frozenset(
    {"is_fraud", "fraud_type", "is_anomaly", "anomaly_type", "sod_violation", "sod_conflict_type"}
)

# Why: PII 마스킹 대상과 방식. masking.mask_dataframe()이 참조.
#      "hash" → SHA-256 앞 8자리, "partial" → 뒤 4자리 ****
MASK_TARGETS: dict[str, str] = {
    "created_by": "hash",
    "approved_by": "hash",
    "auxiliary_account_number": "partial",
    "auxiliary_account_label": "partial",
}

# Why: 위험등급별 셀 배경색 (openpyxl ARGB hex).
#      Excel/PDF 렌더에서 공통 사용해 두 포맷의 색감 일관성 유지.
RISK_FILL_COLORS: dict[str, str] = {
    "High": "FFC7CE",  # 연한 빨강
    "Medium": "FFEB9C",  # 노랑
    "Low": "C6EFCE",  # 연두
}
