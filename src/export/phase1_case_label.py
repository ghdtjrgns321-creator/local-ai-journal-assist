"""Phase1 case 자연어 라벨 변환 헬퍼.

case_key_parts(dict)를 감사인이 읽을 수 있는 한 줄 문장으로 변환한다.
theme별 case_key 구성은 src/detection/phase1_case_builder.py:_make_case_key_parts
와 1:1 매칭. 새 theme이 추가되면 case_natural_label 분기를 함께 추가.
"""

from __future__ import annotations

from typing import Any


_DOCUMENT_TYPE_LABELS: dict[str, str] = {
    "SA": "수기조정",
    "DR": "매출채권",
    "KR": "매입채무",
    "KZ": "대금지급",
    "DZ": "대금수금",
    "WE": "자재입고",
    "AA": "고정자산",
    "HR": "인건비",
    "IC": "관계사거래",
    "SU": "재고이동",
}

_AMOUNT_BAND_LABELS: dict[str, str] = {
    "1B+": "10억 이상",
    "100M-1B": "1~10억",
    "10M-100M": "1천만~1억",
    "<10M": "1천만 미만",
}

_USER_PERSONA_LABELS: dict[str, str] = {
    "JUNIOR_CLERK": "주니어 직원",
    "CONTROLLER": "통제자",
    "TREASURY": "자금부",
    "ADMIN": "관리자",
    "SHARED_USER": "공용 ID",
    "EXTERNAL": "외부",
    "UNKNOWN_PERSONA": "권한 미상",
}

# Why: ERP 표준 business_process 약어. 감사인은 "P2P"보다 "구매·지급"을 빨리 인식.
_BUSINESS_PROCESS_LABELS: dict[str, str] = {
    "P2P": "구매·지급",
    "O2C": "수주·수금",
    "R2R": "결산·재무",
    "H2R": "인사·급여",
    "I2I": "재고·물류",
    "F2A": "고정자산",
    "T2C": "자금·트레저리",
    "M2D": "원가·제조",
}

# Why: gl_account 첫자리 기반 fallback 매핑. account_family 컬럼이 없을 때만 적용.
_GL_FIRST_DIGIT_LABELS: dict[str, str] = {
    "1": "자산",
    "2": "부채",
    "3": "자본",
    "4": "수익",
    "5": "비용/원가",
    "6": "비용",
    "7": "비용",
    "8": "기타",
    "9": "기타",
}


def _format_amount_short(value: float) -> str:
    """한국식 단위 약어로 금액 표기 (조/억/만/원)."""
    if not value:
        return "0원"
    abs_v = abs(float(value))
    if abs_v >= 1_000_000_000_000:
        return f"{value / 1_000_000_000_000:.1f}조"
    if abs_v >= 100_000_000:
        return f"{value / 100_000_000:.1f}억"
    if abs_v >= 10_000:
        return f"{value / 10_000:.0f}만"
    return f"{value:,.0f}원"


def _format_period_month(value: Any) -> str:
    """'2022-03' → '2022년 3월'. 형식이 다르면 원본 유지."""
    if not value:
        return "기간 미상"
    text = str(value).strip()
    if len(text) >= 7 and text[4] == "-":
        try:
            year = text[:4]
            month = int(text[5:7])
            return f"{year}년 {month}월"
        except (ValueError, IndexError):
            return text
    return text


def _format_document_type(value: Any) -> str:
    """'SA' → '수기조정(SA)'. 매핑이 없으면 코드만."""
    if not value:
        return ""
    code = str(value).strip().upper()
    name = _DOCUMENT_TYPE_LABELS.get(code)
    return f"{name}({code})" if name else code


def _format_account_family(value: Any) -> str:
    """account_family 코드를 한글 계정 분류로. 숫자 prefix는 첫자리 기준 매핑."""
    if not value:
        return "계정 미상"
    text = str(value).strip()
    upper = text.upper()
    if upper.startswith("UNKNOWN"):
        return "계정 미상"
    if text.isdigit():
        first = text[:1]
        if first in _GL_FIRST_DIGIT_LABELS:
            label = _GL_FIRST_DIGIT_LABELS[first]
            return f"{label} 계정({text})"
    return text


def _format_amount_band(value: Any) -> str:
    code = str(value or "").upper()
    return _AMOUNT_BAND_LABELS.get(code, code or "금액 미상")


def _format_period_window(value: Any) -> str:
    """기말 윈도우 라벨. 'PE-5d-IN' / 'OUT' 키워드로 분기."""
    text = str(value or "").upper()
    if not text:
        return "기간 미상"
    if "OUT" in text:
        return "기말 외 기간"
    if "IN" in text:
        return "기말 근접 기간"
    return text


def _format_persona(value: Any) -> str:
    code = str(value or "").upper()
    return _USER_PERSONA_LABELS.get(code, code or "권한 미상")


def _format_company_pair(value: Any) -> str:
    text = str(value or "")
    if "+" in text:
        left, right = text.split("+", 1)
        return f"{left} → {right}"
    return text or "회사쌍 미상"


def _is_unknown(value: Any) -> bool:
    text = str(value or "").strip().upper()
    return not text or text.startswith("UNKNOWN")


def _format_counterparty(value: Any) -> str:
    if _is_unknown(value):
        return "거래처 미상"
    return str(value).strip()


def _format_user(value: Any) -> str:
    if _is_unknown(value):
        return "작성자 미상"
    return str(value).strip()


def _format_process(value: Any) -> str:
    if _is_unknown(value):
        return "프로세스 미상"
    text = str(value).strip()
    upper = text.upper()
    name = _BUSINESS_PROCESS_LABELS.get(upper)
    return f"{name}({upper})" if name else text


def case_natural_label(
    theme_id: str,
    parts: dict[str, Any] | None,
    *,
    doc_count: int = 0,
    total_amount: float = 0.0,
) -> str:
    """case_key_parts → 자연어 한 줄.

    doc_count·total_amount는 라벨 끝에 'N건 · X억' 형태로 덧붙인다.
    """
    parts = parts or {}
    suffix = _trailing_metric(doc_count, total_amount)
    theme = str(theme_id or "").lower()

    if theme == "logic_mismatch":
        body = _logic_mismatch(parts)
    elif theme == "control_failure":
        body = _control_failure(parts)
    elif theme == "access_scope_review":
        body = _access_scope_review(parts)
    elif theme == "timing_anomaly":
        body = _timing_anomaly(parts)
    elif theme == "duplicate_or_outflow":
        body = _duplicate_or_outflow(parts)
    elif theme == "intercompany_structure":
        body = _intercompany_structure(parts)
    elif theme == "statistical_outlier":
        body = _statistical_outlier(parts)
    elif theme == "data_integrity_failure":
        body = _data_integrity_failure(parts)
    else:
        joined = " · ".join(str(v) for v in parts.values() if v)
        body = joined or "미분류 case"

    return f"{body}{suffix}"


def _trailing_metric(doc_count: int, total_amount: float) -> str:
    chunks: list[str] = []
    if doc_count:
        chunks.append(f"{doc_count:,}건")
    if total_amount:
        chunks.append(_format_amount_short(total_amount))
    return " · " + " / ".join(chunks) if chunks else ""


def _logic_mismatch(parts: dict[str, Any]) -> str:
    period = _format_period_month(parts.get("period_month"))
    doc_type = _format_document_type(parts.get("document_type"))
    family = _format_account_family(parts.get("account_family"))
    head = period
    if doc_type:
        head = f"{head} {doc_type} 전표"
    return f"{head}의 {family} 위반"


def _control_failure(parts: dict[str, Any]) -> str:
    user = _format_user(parts.get("created_by"))
    period = _format_period_month(parts.get("period_month"))
    process = _format_process(parts.get("business_process"))
    return f"{user}가 {period} {process}에서 통제 위반"


def _access_scope_review(parts: dict[str, Any]) -> str:
    user = _format_user(parts.get("created_by"))
    persona = _format_persona(parts.get("user_persona"))
    period = _format_period_month(parts.get("period_month"))
    return f"{user}({persona})의 {period} 권한범위 위반"


def _timing_anomaly(parts: dict[str, Any]) -> str:
    user = _format_user(parts.get("created_by"))
    family = _format_account_family(parts.get("account_family"))
    window = _format_period_window(parts.get("period_window"))
    return f"{user}의 {window} {family} 의심거래"


def _duplicate_or_outflow(parts: dict[str, Any]) -> str:
    counterparty = _format_counterparty(parts.get("counterparty"))
    band = _format_amount_band(parts.get("amount_band"))
    near = str(parts.get("near_period") or "").upper()
    near_suffix = " · 기말 근접" if near and "PE" in near and "OUT" not in near else ""
    return f"{counterparty}와 {band} 거래 중복·유출 의심{near_suffix}"


def _intercompany_structure(parts: dict[str, Any]) -> str:
    pair = _format_company_pair(parts.get("company_pair"))
    counterparty = _format_counterparty(parts.get("counterparty"))
    period = _format_period_month(parts.get("period_month"))
    return f"{pair} 그룹 {counterparty}와 {period} 거래"


def _statistical_outlier(parts: dict[str, Any]) -> str:
    process = _format_process(parts.get("business_process"))
    family = _format_account_family(parts.get("account_family"))
    period = _format_period_month(parts.get("period_month"))
    return f"{period} {process} {family} 통계 이상"


def _data_integrity_failure(parts: dict[str, Any]) -> str:
    company = parts.get("company") or "회사 미상"
    doc_type = _format_document_type(parts.get("document_type"))
    if doc_type:
        return f"{company} {doc_type} 전표 데이터 정합성 오류"
    return f"{company} 데이터 정합성 오류"
