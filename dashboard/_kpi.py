"""KPI·데이터 품질 계산 — 순수 pandas 함수 (Streamlit 의존 없음).

Why: tab_summary.py에서 @st.cache_data로 래핑하여 필터 변경 시만 재계산.
     Streamlit 비의존이므로 단위 테스트에서 직접 호출 가능.
"""

from __future__ import annotations

import pandas as pd


def compute_kpis(df: pd.DataFrame) -> dict[str, int | float]:
    """KPI 6개 계산. 전표(document_id) 단위 중복 제거 포함.

    Returns:
        total_docs, total_lines, anomaly_docs, anomaly_rate,
        anomaly_amount, fraud_suspect
    """
    total_docs = df["document_id"].nunique() if "document_id" in df.columns else 0
    total_lines = len(df)

    is_anomaly = df["risk_level"] != "Normal" if "risk_level" in df.columns else pd.Series(False, index=df.index)
    anomaly_docs = df.loc[is_anomaly, "document_id"].nunique() if "document_id" in df.columns else 0
    anomaly_rate = anomaly_docs / max(total_docs, 1) * 100

    # Why: 라인 수준 debit_amount를 전표별 합산 후 전체 합계.
    #      동일 전표의 여러 라인이 각각 High로 잡혀도 전표 금액은 1회만 계산.
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

    # Why: 나머지 KPI가 전표(document_id) 단위이므로 fraud_suspect도 통일.
    #      감사인이 "부정 의심 N건"을 읽을 때 전표 단위를 기대.
    fraud_suspect = 0
    if "flagged_rules" in df.columns and "document_id" in df.columns:
        has_b_rule = df["flagged_rules"].str.contains(r"B\d{2}", na=False)
        fraud_suspect = df.loc[has_b_rule, "document_id"].nunique()

    return {
        "total_docs": total_docs,
        "total_lines": total_lines,
        "anomaly_docs": anomaly_docs,
        "anomaly_rate": round(anomaly_rate, 1),
        "anomaly_amount": anomaly_amount,
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
