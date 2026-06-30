"""Small display helpers for the PHASE1 Streamlit tab."""

from __future__ import annotations

# Row risk_level and case priority_band are separate axes. Case labels use a
# diamond marker to avoid implying that every row inside a high-priority case is
# row-level High risk.
BAND_LABELS = {
    "high": "◆ 즉시검토",
    "medium": "◆ 검토대상",
    "low": "◆ 참고후보",
}
CASE_PRIORITY_HIGH = 0.90
CASE_PRIORITY_MEDIUM = 0.75
CASE_IMMEDIATE_REVIEW_RATIO = 0.035
ROW_RISK_LABELS = {
    "High": "● 행 High",
    "Medium": "● 행 Medium",
    "Low": "● 행 Low",
    "Normal": "● 행 Normal",
}


def format_band_cell(value: object) -> str:
    code = str(value or "low").lower()
    return BAND_LABELS.get(code, code)


def display_priority_band_from_score(score: object, fallback: object = "low") -> str:
    """Return the current UI band from priority_score, ignoring stale artifact bands."""

    if score is None or score == "":
        code = str(fallback or "low").lower()
        return code if code in BAND_LABELS else "low"
    try:
        numeric_score = float(score or 0.0)
    except (TypeError, ValueError):
        code = str(fallback or "low").lower()
        return code if code in BAND_LABELS else "low"
    if numeric_score >= CASE_PRIORITY_HIGH:
        return "high"
    if numeric_score >= CASE_PRIORITY_MEDIUM:
        return "medium"
    return "low"


def format_row_risk_cell(value: object) -> str:
    code = str(value or "Normal").strip().title()
    return ROW_RISK_LABELS.get(code, code)
