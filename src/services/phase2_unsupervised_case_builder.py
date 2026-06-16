"""PHASE2 unsupervised (VAE / ML02) case builder.

Why: VAE / IsolationForest detector 의 row 단위 anomaly score + 상위 기여
피처를 family-native ``UnsupervisedCase`` tuple 로 변환한다. invariant #11~17
(tuple 반환 / canonical refs / evidence identity / phase1 단방향 / gate /
graceful empty / phase1_case_refs default) 를 모두 만족해야 한다.

evidence_signature 는 ``model={model_id}|schema={schema_hash}`` 만 — anomaly
score / threshold 는 case identity 가 아니므로 절대 포함하지 않는다 (invariant
#13). PHASE1 입력은 본 builder 내부에서 접근하지 않으며, S3 linker 가 추후
``phase1_case_refs`` 를 부착한다 (invariant #14, #17).
"""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd

from src.detection.base import DetectionResult
from src.models.phase2_case import Phase2RowRef, UnsupervisedCase, make_row_ref
from src.services.phase2_case_id import make_phase2_case_id
from src.services.phase2_ref_canonical import canonicalize_ref_key
from src.services.unsupervised_reason_tags import resolve_tag

_UNSUPERVISED_TOP_K = 3
_FEATURE_COL_PREFIX = "ML02_top_feature_"
_CONTRIB_SUFFIX = "_contrib"
_FAMILY = "unsupervised"
_UNIT_TYPE = "document"
_EVIDENCE_TIER = "ml_quantile"
UNSUPERVISED_ORDERING_NATIVE = "native"
UNSUPERVISED_ORDERING_SOFT_GUARD = "hybrid_with_soft_repeated_normal_guard"
UNSUPERVISED_ORDERING_DEFAULT = UNSUPERVISED_ORDERING_SOFT_GUARD
UnsupervisedOrderingStrategy = Literal["native", "hybrid_with_soft_repeated_normal_guard"]


def build_unsupervised_cases(
    *,
    batch_id: str,
    detection_result: DetectionResult,
    df: pd.DataFrame,
    model_id: str,
    schema_hash: str,
    ecdf_gate: float = 0.95,
    ordering_strategy: UnsupervisedOrderingStrategy = UNSUPERVISED_ORDERING_DEFAULT,
) -> tuple[UnsupervisedCase, ...]:
    """unsupervised DetectionResult 를 ``UnsupervisedCase`` tuple 로 변환.

    Gate: zero_preserving ECDF 가 ``ecdf_gate`` (기본 0.95) 이상인 row 만 case 화.
    빈 details / scores 는 빈 tuple 로 graceful fallback (invariant #16).

    Ordering:
        기본 ``"hybrid_with_soft_repeated_normal_guard"`` 시그니처는 이전 진단
        호환을 위해 남아 있지만, 현재 product ordering 은 context 필드를 쓰지 않는
        document max-score order 이다. q95 gate / VAE score / threshold 는 바꾸지
        않고, truth/scenario/owner metadata/PHASE1 rank 는 입력으로 쓰지 않는다.
        ``"native"`` 도 row-native 가 아니라 document max-score order 이다.

    Returns:
        ``tuple[UnsupervisedCase, ...]`` — list 가 아니라 tuple (invariant #11).
    """
    scores = detection_result.scores
    details = detection_result.details
    # invariant #16 — metadata/scores/details 어느 하나라도 비면 빈 tuple.
    if scores is None or details is None:
        return ()
    if scores.empty or details.empty:
        return ()

    ecdf_series = _zero_preserving_ecdf(scores)
    evidence_signature = f"model={model_id}|schema={schema_hash}"

    records: list[dict[str, Any]] = []
    for label in scores.index:
        ecdf_value = float(ecdf_series.loc[label])
        # invariant #15 — gate 미달 row 는 case 화하지 않는다.
        if ecdf_value < ecdf_gate:
            continue
        if label not in details.index:
            continue

        row_ref = _make_unsupervised_ref(df, label)
        # invariant #16 — df 에 부재한 label 은 graceful skip (KeyError 회피).
        if row_ref is None:
            continue
        records.append(
            {
                "label": label,
                "row_ref": row_ref,
                "score": float(scores.loc[label]),
                "ecdf": ecdf_value,
                "top_features": _extract_top_features(details.loc[label]),
            }
        )
    if not records:
        return ()

    grouped = _group_records_by_document(records)
    context_by_group = _document_context_by_group(grouped, df)
    cases: list[UnsupervisedCase] = []
    for group_key, group_records in grouped.items():
        max_record = _max_score_record(group_records)
        scores_in_group = [float(record["score"]) for record in group_records]
        ecdfs_in_group = [float(record["ecdf"]) for record in group_records]
        row_refs = tuple(record["row_ref"] for record in group_records)
        grouping_mode = "document_id" if group_key[0] == "document" else "fallback_row_identity"
        doc_key = dict(group_key[1])
        canonical_refs = (
            canonicalize_ref_key((doc_key["company_code"], doc_key["document_id"]))
            if group_key[0] == "document"
            else str(doc_key["index_label"]),
        )
        case_id = make_phase2_case_id(
            batch_id=batch_id,
            family=_FAMILY,
            unit_type=_UNIT_TYPE,
            canonical_refs=canonical_refs,
            evidence_signature=evidence_signature,
        )
        anomaly_score = max(scores_in_group)
        family_ecdf = max(ecdfs_in_group)
        context = context_by_group.get(group_key, {})
        cases.append(
            UnsupervisedCase(
                phase2_case_id=case_id,
                batch_id=batch_id,
                family=_FAMILY,
                unit_type=_UNIT_TYPE,
                row_refs=row_refs,
                evidence_tier=_EVIDENCE_TIER,
                # Why: gate 종류 / 임계 / 실제 ecdf 분리.
                #   ecdf_gate 가 0.95 외 값일 때도 metadata 정합 유지.
                case_generation_reason={
                    "gate": "unsupervised_ecdf",
                    "threshold": ecdf_gate,
                    "ecdf": family_ecdf,
                    "document_grouping": grouping_mode,
                    "ordering_context_policy": "context_fields_display_only",
                    "evidence_rows": _evidence_row_trace(group_records),
                },
                family_score=anomaly_score,
                family_ecdf=family_ecdf,
                # invariant #17 — phase1_case_refs default, S4 linker 부착 대상.
                anomaly_score=anomaly_score,
                top_features=_merge_top_features(group_records),
                max_score_top_features=tuple(max_record["top_features"]),
                model_id=model_id,
                schema_hash=schema_hash,
                document_id=str(doc_key["document_id"]) if group_key[0] == "document" else None,
                evidence_row_count=len(group_records),
                top_score_mean=float(np.mean(scores_in_group)),
                score_spread=max(scores_in_group) - min(scores_in_group),
                max_score_row_ref=max_record["row_ref"],
                amount_tail_context=context.get("amount_tail_context"),
                period_end_context=context.get("period_end_context"),
                account_rarity_context=context.get("account_rarity_context"),
                process_rarity_context=context.get("process_rarity_context"),
                repeated_normal_pressure=0.0,
            )
        )
    return _apply_ordering_strategy(cases, df=df, ordering_strategy=ordering_strategy)


def _evidence_row_trace(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Display-only evidence row score/ecdf trace for document detail ordering."""
    rows: list[dict[str, Any]] = []
    for record in sorted(
        records,
        key=lambda item: (
            -float(item.get("score") or 0.0),
            -float(item.get("ecdf") or 0.0),
            int(getattr(item.get("row_ref"), "row_position", 0) or 0),
        ),
    ):
        row_ref = record["row_ref"]
        rows.append(
            {
                "row_position": int(row_ref.row_position),
                "score": float(record["score"]),
                "ecdf": float(record["ecdf"]),
            }
        )
    return rows


def _group_records_by_document(
    records: list[dict[str, Any]],
) -> dict[tuple[str, tuple[tuple[str, str | None], ...]], list[dict[str, Any]]]:
    grouped: dict[tuple[str, tuple[tuple[str, str | None], ...]], list[dict[str, Any]]] = {}
    for record in records:
        row_ref = record["row_ref"]
        document_id = str(row_ref.document_id or "").strip()
        company_code = str(row_ref.company_code or "").strip() or None
        key = (
            (
                "document",
                (
                    ("company_code", company_code),
                    ("document_id", document_id),
                ),
            )
            if document_id
            else (
                "fallback",
                (
                    ("company_code", company_code),
                    ("index_label", str(row_ref.index_label)),
                ),
            )
        )
        grouped.setdefault(key, []).append(record)
    return grouped


def _max_score_record(records: list[dict[str, Any]]) -> dict[str, Any]:
    return max(
        records,
        key=lambda record: (
            float(record["score"]),
            -int(getattr(record["row_ref"], "row_position", 0) or 0),
        ),
    )


def _merge_top_features(records: list[dict[str, Any]]) -> tuple[dict, ...]:
    by_feature: dict[tuple[str, str], dict] = {}
    for record in records:
        for feature in record["top_features"]:
            copied = dict(feature)
            key = (str(copied.get("feature_id") or ""), str(copied.get("tag") or ""))
            current = by_feature.get(key)
            if current is None or abs(float(copied.get("contrib") or 0.0)) > abs(
                float(current.get("contrib") or 0.0)
            ):
                by_feature[key] = copied
    features = list(by_feature.values())
    features.sort(
        key=lambda feature: (
            -abs(float(feature.get("contrib") or 0.0)),
            str(feature.get("feature_id") or ""),
            str(feature.get("tag") or ""),
        )
    )
    return tuple(features[:_UNSUPERVISED_TOP_K])


def _document_context_by_group(
    grouped: dict[tuple[str, tuple[tuple[str, str | None], ...]], list[dict[str, Any]]],
    df: pd.DataFrame,
) -> dict[tuple[str, tuple[tuple[str, str | None], ...]], dict[str, float | None]]:
    max_amounts = {
        key: max(_row_amount(df, record["row_ref"].row_position) or 0.0 for record in records)
        for key, records in grouped.items()
    }
    amount_percentiles = _percentile_map({str(key): value for key, value in max_amounts.items()})
    account_counts = _value_counts_for_context(df, "gl_account")
    process_counts = _value_counts_for_context(df, "business_process")
    return {
        key: {
            "amount_tail_context": amount_percentiles.get(str(key), 0.0),
            "period_end_context": _group_period_end_context(records, df),
            "account_rarity_context": _group_rarity_context(
                records,
                df,
                "gl_account",
                account_counts,
            ),
            "process_rarity_context": _group_rarity_context(
                records,
                df,
                "business_process",
                process_counts,
            ),
        }
        for key, records in grouped.items()
    }


def _group_period_end_context(records: list[dict[str, Any]], df: pd.DataFrame) -> float:
    days = [
        _row_period_end_proximity_days(df, record["row_ref"].row_position)
        for record in records
    ]
    valid = [day for day in days if day is not None]
    if not valid:
        return 0.0
    return _period_end_score(min(valid))


def _group_rarity_context(
    records: list[dict[str, Any]],
    df: pd.DataFrame,
    column: str,
    counts: pd.Series | None = None,
) -> float | None:
    if column not in df.columns or df.empty:
        return None
    if counts is None:
        counts = _value_counts_for_context(df, column)
    values: list[str] = []
    for record in records:
        value = _column_value(df, column, record["row_ref"].row_position)
        if value is not None and str(value).strip():
            values.append(str(value).strip())
    if counts.empty or not values:
        return None
    rarest_count = min(int(counts.get(value, len(df))) for value in values)
    return float(1.0 / rarest_count) if rarest_count > 0 else None


def _value_counts_for_context(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns or df.empty:
        return pd.Series(dtype="int64")
    counts = df[column].dropna().astype(str).str.strip()
    return counts[counts != ""].value_counts()


def _apply_ordering_strategy(
    cases: list[UnsupervisedCase],
    *,
    df: pd.DataFrame,
    ordering_strategy: UnsupervisedOrderingStrategy,
) -> tuple[UnsupervisedCase, ...]:
    del df
    if ordering_strategy in {
        UNSUPERVISED_ORDERING_NATIVE,
        UNSUPERVISED_ORDERING_SOFT_GUARD,
    }:
        return tuple(
            sorted(
                cases,
                key=lambda case: (-float(case.family_score or 0.0), case.phase2_case_id),
            )
        )
    raise ValueError(
        "unsupported unsupervised ordering_strategy: "
        f"{ordering_strategy!r}; expected 'native' or "
        f"{UNSUPERVISED_ORDERING_SOFT_GUARD!r}"
    )


def _row_amount(df: pd.DataFrame, row_position: int | None) -> float | None:
    if row_position is None or row_position < 0 or row_position >= len(df):
        return None
    value = _column_value(df, "amount", row_position)
    if value is None:
        return None
    try:
        amount = abs(float(value))
    except (TypeError, ValueError):
        return None
    return amount if np.isfinite(amount) else None


def _row_period_end_proximity_days(
    df: pd.DataFrame,
    row_position: int | None,
) -> int | None:
    if row_position is None or row_position < 0 or row_position >= len(df):
        return None
    value = _column_value(df, "period_end_proximity_days", row_position)
    if value is None:
        return None
    try:
        days = int(value)
    except (TypeError, ValueError):
        return None
    return days if days >= 0 else None


def _period_end_score(days: int | None) -> float:
    if days is None:
        return 0.0
    return float(max(0.0, 1.0 - min(float(days), 30.0) / 30.0))


def _percentile_map(values_by_doc: dict[str, float]) -> dict[str, float]:
    if not values_by_doc:
        return {}
    ordered = sorted(values_by_doc.items(), key=lambda item: (item[1], str(item[0])))
    n = len(ordered)
    return {doc: (idx + 1) / n for idx, (doc, _value) in enumerate(ordered)}


def _zero_preserving_ecdf(scores: pd.Series) -> pd.Series:
    """0 score 는 ECDF 0 으로 보존, 양수만 percentile rank 부여.

    Why: VAE/IsolationForest score 가 0 으로 클리핑되는 row 가 다수일 때,
    전체 분포에 0 을 섞으면 percentile 이 인위적으로 올라가 gate 가 오작동한다.
    """
    if scores.empty:
        return scores.astype(float)
    # Why: .loc[mask] 는 pyright 가 Series 로 narrow. scores[scores>0] 은 ndarray 추론.
    positive: pd.Series = scores.loc[scores > 0]
    if positive.empty:
        return pd.Series(0.0, index=scores.index)
    ranks = positive.rank(method="max", pct=True)
    ecdf = pd.Series(0.0, index=scores.index)
    ecdf.loc[positive.index] = ranks
    return ecdf.astype(float)


def _column_value(df: pd.DataFrame, column: str, position: int) -> Any:
    """선택적 컬럼 값의 null-safe 조회. 컬럼 부재 / NaN / NaT / pd.NA → None.

    Why: ``str(NaN)`` 은 ``"nan"`` 문자열을 만들어 Phase2RowRef 에 가짜 식별자를
    심는다. duplicate builder 의 동일 패턴 (`_column_value`) 과 정렬.
    """
    if column not in df.columns:
        return None
    value = df[column].iat[position]
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _make_unsupervised_ref(df: pd.DataFrame, label: Any) -> Phase2RowRef | None:
    """df row label → Phase2RowRef. label 미존재 시 None (호출자 skip).

    Why: details.index 에는 있지만 df.index 에 없는 label 이 들어오면
    ``get_loc`` 이 KeyError. invariant #16 (graceful fallback) 을 지키려면
    예외 전파 대신 None 반환으로 호출자가 건너뛰게 한다.
    """
    try:
        raw_pos = df.index.get_loc(label)
    except (KeyError, TypeError):
        return None
    # Why: get_loc 이 int / slice / ndarray (boolean mask) 반환 가능.
    if isinstance(raw_pos, slice):
        pos = int(raw_pos.start) if raw_pos.start is not None else 0
    elif isinstance(raw_pos, np.ndarray):
        nonzero = raw_pos.nonzero()[0]
        if len(nonzero) == 0:
            return None
        pos = int(nonzero[0])
    else:
        pos = int(raw_pos)

    raw_line_number = _column_value(df, "line_number", pos)
    doc_value = _column_value(df, "document_id", pos)
    company_value = _column_value(df, "company_code", pos)
    return make_row_ref(
        row_position=pos,
        index_label=label,
        document_id=str(doc_value) if doc_value is not None else None,
        raw_line_number=raw_line_number,
        company_code=str(company_value) if company_value is not None else None,
    )


def _extract_top_features(row: pd.Series) -> tuple[dict, ...]:
    """ML02_top_feature_{1..3} 슬롯에서 feature/contrib/reason tag dict 추출.

    NaN / 빈 문자열 feature_name 슬롯은 건너뛴다. 최대 ``_UNSUPERVISED_TOP_K`` 개.
    반환 형식: ``tuple[dict, ...]`` — frozen dataclass 안에 mutable list 가
    들어가지 않도록 tuple 로 동결.
    """
    features: list[dict] = []
    for k in range(1, _UNSUPERVISED_TOP_K + 1):
        feature_col = f"{_FEATURE_COL_PREFIX}{k}"
        contrib_col = f"{feature_col}{_CONTRIB_SUFFIX}"
        if feature_col not in row.index:
            continue
        feature_value = row.get(feature_col)
        if feature_value is None or (isinstance(feature_value, float) and pd.isna(feature_value)):
            continue
        feature_name = str(feature_value).strip()
        if not feature_name:
            continue
        contrib_raw = row.get(contrib_col) if contrib_col in row.index else 0.0
        try:
            contrib = float(contrib_raw) if contrib_raw is not None else 0.0
        except (TypeError, ValueError):
            contrib = 0.0
        tag = resolve_tag(feature_name)
        features.append(
            {
                "feature_id": feature_name,
                "contrib": contrib,
                "tag": tag.tag,
                "label_ko": tag.label_ko,
                "evidence_type": tag.evidence_type,
            }
        )
    return tuple(features)


__all__ = [
    "UNSUPERVISED_ORDERING_DEFAULT",
    "UNSUPERVISED_ORDERING_NATIVE",
    "UNSUPERVISED_ORDERING_SOFT_GUARD",
    "build_unsupervised_cases",
]
