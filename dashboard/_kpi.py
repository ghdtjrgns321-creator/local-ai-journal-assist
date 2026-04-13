"""KPI·데이터 품질 계산 — 순수 pandas 함수 (Streamlit 의존 없음).

Why: tab_summary.py에서 @st.cache_data로 래핑하여 필터 변경 시만 재계산.
     Streamlit 비의존이므로 단위 테스트에서 직접 호출 가능.
"""

from __future__ import annotations

import pandas as pd


def _format_krw(value: float) -> str:
    """금액을 한국식 축약 형태로 변환 (조/억/만).

    Why: ₩5,766,465,070,813 같은 원시 숫자는 직관적 파악 불가.
         "₩5.8조" 형태가 감사인 보고서에서도 표준.
    """
    abs_val = abs(value)
    sign = "-" if value < 0 else ""
    if abs_val >= 1e12:
        return f"{sign}₩{abs_val / 1e12:.1f}조"
    if abs_val >= 1e8:
        return f"{sign}₩{abs_val / 1e8:.0f}억"
    if abs_val >= 1e4:
        return f"{sign}₩{abs_val / 1e4:.0f}만"
    return f"{sign}₩{abs_val:,.0f}"


def compute_kpis(df: pd.DataFrame) -> dict[str, int | float | str]:
    """KPI 계산. 전표(document_id) 단위 중복 제거 포함.

    Returns:
        total_docs, total_lines, anomaly_docs, anomaly_rate,
        anomaly_amount, anomaly_amount_fmt, total_amount, total_amount_fmt,
        high_risk_docs, fraud_suspect
    """
    total_docs = df["document_id"].nunique() if "document_id" in df.columns else 0
    total_lines = len(df)

    is_anomaly = df["risk_level"] != "Normal" if "risk_level" in df.columns else pd.Series(False, index=df.index)
    anomaly_docs = df.loc[is_anomaly, "document_id"].nunique() if "document_id" in df.columns else 0
    anomaly_rate = anomaly_docs / max(total_docs, 1) * 100

    # Why: 전체 거래액 = 분모. 이상 금액만 보여주면 규모감 파악 불가.
    total_amount = 0.0
    if "debit_amount" in df.columns and "document_id" in df.columns:
        total_amount = df.groupby("document_id")["debit_amount"].sum().sum()

    # Why: 라인 수준 debit_amount를 전표별 합산 후 전체 합계.
    anomaly_amount = 0.0
    if "risk_level" in df.columns and "debit_amount" in df.columns:
        high_medium = df[df["risk_level"].isin(["High", "Medium"])]
        if not high_medium.empty and "document_id" in df.columns:
            anomaly_amount = (
                high_medium
                .groupby("document_id")["debit_amount"]
                .sum()
                .sum()
            )

    # Why: 고위험(High) 전표만 별도 집계 — 감사인이 집중해야 할 대상.
    high_risk_docs = 0
    if "risk_level" in df.columns and "document_id" in df.columns:
        high_risk_docs = df.loc[df["risk_level"] == "High", "document_id"].nunique()

    # Why: 나머지 KPI가 전표(document_id) 단위이므로 fraud_suspect도 통일.
    fraud_suspect = 0
    if "flagged_rules" in df.columns and "document_id" in df.columns:
        has_b_rule = df["flagged_rules"].str.contains(r"B\d{2}", na=False)
        fraud_suspect = df.loc[has_b_rule, "document_id"].nunique()

    # Why: 이상 금액이 총액의 몇 %인지 — 규모감을 한눈에 전달.
    amount_ratio = anomaly_amount / max(total_amount, 1) * 100

    return {
        "total_docs": total_docs,
        "total_lines": total_lines,
        "anomaly_docs": anomaly_docs,
        "anomaly_rate": round(anomaly_rate, 1),
        "anomaly_amount": anomaly_amount,
        "anomaly_amount_fmt": _format_krw(anomaly_amount),
        "total_amount": total_amount,
        "total_amount_fmt": _format_krw(total_amount),
        "amount_ratio": round(amount_ratio, 1),
        "high_risk_docs": high_risk_docs,
        "fraud_suspect": fraud_suspect,
    }


def compute_quality(df: pd.DataFrame) -> dict[str, float | int]:
    """기초 데이터 품질 지표 3개. 전체 EDA는 WU6(tab_eda.py)에서 구현."""
    completeness = (1 - df.isnull().mean().mean()) * 100 if not df.empty else 0.0
    return {
        "completeness": round(completeness, 1),
        "total_columns": len(df.columns),
        "total_rows": len(df),
    }
