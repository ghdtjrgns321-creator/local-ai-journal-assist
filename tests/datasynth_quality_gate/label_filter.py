"""라벨 제외 공통 유틸.

DataSynth가 의도적으로 주입한 이상 전표를 품질 체크에서 제외하기 위한 모듈.
체크 항목별로 어떤 anomaly_type을 제외해야 하는지 LABEL_EXCLUSION_MAP으로 관리.
"""
from __future__ import annotations

import pandas as pd


# 체크ID → 제외할 anomaly_type 리스트 매핑
# DataSynth가 의도적으로 주입한 이상값이 정상 품질 체크를 오염시키지 않도록 사전 제외
LABEL_EXCLUSION_MAP: dict[str, list[str]] = {
    "T1-04": ["ReversedAmount", "UnusuallyLowAmount", "RoundDollarManipulation"],
    "T1-05": ["UnbalancedEntry", "RoundingError", "CurrencyError", "DecimalError",
              "TransposedDigits", "ReversedAmount", "JustBelowThreshold"],
    "T1-09": ["UnbalancedEntry", "MissingField"],
    "T1-12": ["InvalidAccount", "DormantAccountActivity"],
    "T1-13": ["MissingField"],
    "T1-14": ["MissingField"],
    # Why: CircularIntercompany는 debit+credit 동시 양수가 의도된 이상
    "T2-02": ["CircularIntercompany", "UnbalancedEntry"],
    # Why: LatePosting/BackdatedEntry가 posting_date를 변경하여 period/year 불일치 유발
    "T2-04": ["WrongPeriod", "LatePosting", "BackdatedEntry", "TimingAnomaly"],
    "T2-05": ["WrongPeriod", "LatePosting", "BackdatedEntry"],
    "T2-06": ["FutureDatedEntry", "BackdatedEntry", "RushedPeriodEnd", "WrongPeriod"],
    "T2-07": ["InvalidAccount", "DormantAccountActivity", "MisclassifiedAccount"],
    "T2-14": ["UnmatchedIntercompany", "CircularIntercompany"],
    "T2-18": ["ExceededApprovalLimit", "JustBelowThreshold"],
    "T2-19": ["LateApproval", "SkippedApproval", "LatePosting", "RushedPeriodEnd", "WrongPeriod"],
    "T2-20": ["ManualOverride", "SelfApproval"],
    "T2-21": ["MisclassifiedAccount", "ImproperCapitalization"],
    "T2-23": ["ReversedAmount"],
    "T2-24": ["ReversedAmount", "ImproperCapitalization", "RevenueManipulation"],
    "T2-28": ["SegregationOfDutiesViolation"],
    "T3-09": ["SelfApproval", "SegregationOfDutiesViolation", "ManualOverride"],
    "T3-10": ["SegregationOfDutiesViolation"],
    "T3-12": ["ExceededApprovalLimit"],
    "T3-13": ["SelfApproval", "SkippedApproval"],
    "T3-15": ["DuplicatePayment"],
    "T3-16": ["DuplicatePayment"],
}


def exclude_labeled(
    df: pd.DataFrame,
    labels_df: pd.DataFrame,
    anomaly_types: list[str],
) -> pd.DataFrame:
    """특정 anomaly_type에 해당하는 document_id를 df에서 제외.

    Args:
        df: 원본 데이터프레임 (document_id 컬럼 필수)
        labels_df: 라벨 데이터프레임 (document_id, anomaly_type 컬럼 필수)
        anomaly_types: 제외할 anomaly_type 목록
    """
    if labels_df.empty or not anomaly_types:
        return df

    # 해당 anomaly_type의 document_id 집합
    exclude_ids = set(
        labels_df.loc[
            labels_df["anomaly_type"].isin(anomaly_types), "document_id"
        ]
    )
    if not exclude_ids:
        return df

    return df[~df["document_id"].isin(exclude_ids)].reset_index(drop=True)


def exclude_all_anomaly(df: pd.DataFrame) -> pd.DataFrame:
    """is_anomaly=True 또는 is_fraud=True인 행 제외.

    라벨 컬럼이 없으면 원본 그대로 반환 (graceful degradation).
    """
    mask = pd.Series(False, index=df.index)

    if "is_anomaly" in df.columns:
        mask = mask | df["is_anomaly"].fillna(False).astype(bool)
    if "is_fraud" in df.columns:
        mask = mask | df["is_fraud"].fillna(False).astype(bool)

    return df[~mask].reset_index(drop=True)
