"""배치 전표 이상 패턴 — L4-06.

Why: 금융권 IT 감사 가이드라인. 배치 전표는 대량 자동 처리로
     개별 검토가 부재하여 기말 집중·대량 동시 생성·금액 이상 패턴 탐지 필요.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.detection.source_trust import lone_automated_mask


def _nunique_documents(df: pd.DataFrame, mask: pd.Series) -> int:
    if "document_id" not in df.columns:
        return 0
    return int(df.loc[mask.reindex(df.index, fill_value=False), "document_id"].dropna().nunique())


def c13_batch_anomaly(
    df: pd.DataFrame,
    batch_sources: list[str] | None = None,
    period_end_ratio: float = 0.5,
    simultaneous_threshold: int = 50,
    amount_zscore: float = 3.0,
) -> pd.Series:
    """L4-06 배치 전표 이상: 3가지 하위 패턴 OR 결합.

    Why: 배치 전표는 자동 처리되므로 개별 승인 없이 대량 전기됨.
         기말 집중, 대량 동시 생성, 금액 이상 중 하나라도 해당하면 플래그.
    """
    if "source" not in df.columns:
        return pd.Series(False, index=df.index)

    sources = batch_sources or [
        "batch",
        "interface",
        "system",
        "auto",
        "automated",
        "if",
        "sys",
        "BATCH",
        "INTERFACE",
        "SYSTEM",
        "AUTO",
        "AUTOMATED",
        "IF",
        "SYS",
    ]
    source_values = df["source"].astype("string").str.strip().str.lower()
    is_batch = source_values.isin({str(source).strip().lower() for source in sources})
    if not is_batch.any():
        return pd.Series(False, index=df.index)

    period_end_flags = _batch_period_end_concentration(df, is_batch, period_end_ratio)
    simultaneous_flags = _batch_simultaneous_creation(df, is_batch, simultaneous_threshold)
    amount_outlier_flags = _batch_amount_outlier(df, is_batch, amount_zscore)
    # Why: 자동이라 주장하지만 배치 정체성(batch/job id)도 같은 날 동류 무리도 없는
    #      단독 전표 — source 위조(자동 위장) 의심. 정상 자동 전표는 무리지어 다닌다
    #      (v41 실측: 정상 자동 202,102 문서 중 82건만 해당). OPEN_ISSUES #16.
    lone_identity_flags = lone_automated_mask(
        df,
        source_tokens={str(source).strip().lower() for source in sources},
    ).reindex(df.index, fill_value=False)
    result = (
        period_end_flags | simultaneous_flags | amount_outlier_flags | lone_identity_flags
    ).astype(bool)

    multi_signal_flags = (
        period_end_flags.astype(int)
        + simultaneous_flags.astype(int)
        + amount_outlier_flags.astype(int)
        + lone_identity_flags.astype(int)
    ).ge(2)
    amount_only_flags = (
        amount_outlier_flags & ~period_end_flags & ~simultaneous_flags & ~lone_identity_flags
    )
    simultaneous_only_flags = (
        simultaneous_flags & ~period_end_flags & ~amount_outlier_flags & ~lone_identity_flags
    )
    period_end_only_flags = (
        period_end_flags & ~simultaneous_flags & ~amount_outlier_flags & ~lone_identity_flags
    )
    lone_identity_only_flags = (
        lone_identity_flags & ~period_end_flags & ~simultaneous_flags & ~amount_outlier_flags
    )

    score_series = pd.Series(0.0, index=df.index, dtype="float64")
    score_series.loc[amount_only_flags] = 0.25
    score_series.loc[period_end_only_flags] = 0.45
    score_series.loc[simultaneous_only_flags] = 0.45
    score_series.loc[lone_identity_only_flags] = 0.45
    score_series.loc[result & multi_signal_flags] = 0.65

    score_bucket = pd.Series("", index=df.index, dtype="object")
    score_bucket.loc[amount_only_flags] = "amount_outlier_only"
    score_bucket.loc[period_end_only_flags] = "period_end_concentration"
    score_bucket.loc[simultaneous_only_flags] = "simultaneous_creation"
    score_bucket.loc[lone_identity_only_flags] = "lone_batch_identity"
    score_bucket.loc[result & multi_signal_flags] = "multi_signal_batch"

    row_annotations: dict[object, dict[str, object]] = {}
    optional_columns = (
        "document_id",
        "source",
        "posting_date",
        "is_period_end",
        "debit_amount",
        "credit_amount",
    )
    for idx in result[result].index:
        reason_codes: list[str] = []
        if bool(period_end_flags.loc[idx]):
            reason_codes.append("period_end_concentration")
        if bool(simultaneous_flags.loc[idx]):
            reason_codes.append("simultaneous_creation")
        if bool(amount_outlier_flags.loc[idx]):
            reason_codes.append("amount_outlier")
        if bool(lone_identity_flags.loc[idx]):
            reason_codes.append("lone_batch_identity")
        annotation: dict[str, object] = {
            "reason_codes": reason_codes,
            "primary_reason": reason_codes[-1] if reason_codes else "batch_review",
            "score": round(float(score_series.loc[idx]), 4),
            "score_bucket": str(score_bucket.loc[idx] or "batch_review"),
        }
        for column in optional_columns:
            if column in df.columns:
                value = df.at[idx, column]
                annotation[column] = None if pd.isna(value) else value
        annotation_key = int(idx) if isinstance(idx, (int, np.integer)) else idx
        row_annotations[annotation_key] = annotation

    breakdown: dict[str, object] = {
        "batch_review_rows": int(result.sum()),
        "batch_source_rows": int(is_batch.sum()),
        "period_end_concentration_rows": int(period_end_flags.sum()),
        "simultaneous_creation_rows": int(simultaneous_flags.sum()),
        "amount_outlier_rows": int(amount_outlier_flags.sum()),
        "lone_batch_identity_rows": int(lone_identity_flags.sum()),
        "amount_outlier_only_rows": int((result & amount_only_flags).sum()),
        "period_end_only_rows": int((result & period_end_only_flags).sum()),
        "simultaneous_only_rows": int((result & simultaneous_only_flags).sum()),
        "lone_identity_only_rows": int((result & lone_identity_only_flags).sum()),
        "multi_signal_batch_rows": int((result & multi_signal_flags).sum()),
        "period_end_ratio_threshold": float(period_end_ratio),
        "simultaneous_threshold": int(simultaneous_threshold),
        "amount_zscore_threshold": float(amount_zscore),
        "score_bands": {
            "amount_outlier_only": 0.25,
            "period_end_concentration": 0.45,
            "simultaneous_creation": 0.45,
            "lone_batch_identity": 0.45,
            "multi_signal_batch": 0.65,
        },
    }
    if "document_id" in df.columns:
        breakdown.update(
            {
                "batch_review_docs": _nunique_documents(df, result),
                "period_end_concentration_docs": _nunique_documents(df, period_end_flags),
                "simultaneous_creation_docs": _nunique_documents(df, simultaneous_flags),
                "amount_outlier_docs": _nunique_documents(df, amount_outlier_flags),
                "amount_outlier_only_docs": _nunique_documents(df, result & amount_only_flags),
                "period_end_only_docs": _nunique_documents(df, result & period_end_only_flags),
                "simultaneous_only_docs": _nunique_documents(df, result & simultaneous_only_flags),
                "multi_signal_batch_docs": _nunique_documents(df, result & multi_signal_flags),
            }
        )

    result.attrs["score_series"] = score_series
    result.attrs["breakdown"] = breakdown
    result.attrs["row_annotations"] = row_annotations
    return result


def _batch_period_end_concentration(
    df: pd.DataFrame,
    is_batch: pd.Series,
    ratio: float,
) -> pd.Series:
    """배치 전표 중 기말 비율이 임계 초과 → 해당 배치 전표 전체 플래그.

    Why: 배치 런(batch run)을 하나의 감사 단위로 취급 (PCAOB AS 240 §32).
         기말 집중 비율이 높으면 해당 기간의 배치 처리 전체가 결산 조정 목적 의심.
         기말이 아닌 배치 행도 같은 자동화 프로세스의 산물이므로 함께 플래그.
    """
    if "is_period_end" not in df.columns:
        return pd.Series(False, index=df.index)
    batch_mask = is_batch.fillna(False)
    period_end = df["is_period_end"].fillna(False)
    batch_count = batch_mask.sum()
    if batch_count == 0:
        return pd.Series(False, index=df.index)
    # Why: 배치 전표 중 기말 비율 → 임계 초과 시 배치 전표 전체 플래그
    batch_period_ratio = (batch_mask & period_end).sum() / batch_count
    if batch_period_ratio > ratio:
        return batch_mask
    return pd.Series(False, index=df.index)


def _batch_simultaneous_creation(
    df: pd.DataFrame,
    is_batch: pd.Series,
    threshold: int,
) -> pd.Series:
    """같은 시각/일자에 배치 전표 N건 이상 → 해당 timestamp 배치 행 플래그.

    Why: 대량 동시 생성은 자동화 오류 또는 의도적 대량 전기 의심.
         GL은 한 전표가 수백 line일 수 있으므로 document_id가 있으면 전표 수 기준으로 센다.
    """
    if "posting_date" not in df.columns:
        return pd.Series(False, index=df.index)
    batch_only = df[is_batch.fillna(False)]
    if batch_only.empty:
        return pd.Series(False, index=df.index)
    # Why: 전표 건수 기준. document_id 없을 때만 row count로 graceful fallback.
    if "document_id" in batch_only.columns:
        daily_counts = batch_only.groupby("posting_date")["document_id"].nunique()
    else:
        daily_counts = batch_only.groupby("posting_date").size()
    flagged_dates = daily_counts.loc[daily_counts >= threshold].index.tolist()
    return is_batch & df["posting_date"].isin(flagged_dates)


def _batch_amount_outlier(
    df: pd.DataFrame,
    is_batch: pd.Series,
    zscore_threshold: float,
) -> pd.Series:
    """배치 전표 내 Z-score 이상치 → 해당 행 플래그.

    Why: 배치 내 금액이 동일 패턴을 벗어나면 수정·오입력 가능성.
    """
    batch_mask = is_batch.fillna(False)
    if not batch_mask.any():
        return pd.Series(False, index=df.index)
    base = df[["debit_amount", "credit_amount"]].fillna(0).max(axis=1)
    if "document_id" in df.columns:
        doc_amount = base.groupby(df["document_id"]).transform("max")
        batch_amounts = (
            pd.DataFrame(
                {
                    "document_id": df.loc[batch_mask, "document_id"],
                    "_doc_amount": doc_amount.loc[batch_mask],
                }
            )
            .dropna(subset=["document_id"])
            .drop_duplicates("document_id")["_doc_amount"]
        )
    else:
        doc_amount = base
        batch_amounts = base[batch_mask]
    std = batch_amounts.std()
    # Why: 급여·상각 등 동일 금액 배치는 std=0 → 이상치 없음으로 처리
    if std == 0 or np.isnan(std):
        return pd.Series(False, index=df.index)
    mean = batch_amounts.mean()
    zscores = ((doc_amount - mean) / std).abs()
    return batch_mask & (zscores > zscore_threshold)
