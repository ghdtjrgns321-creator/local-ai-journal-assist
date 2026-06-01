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
_UNIT_TYPE = "row"
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
        기본 ``"hybrid_with_soft_repeated_normal_guard"`` 는 document-level review
        priority 표시 순서를 적용한다. q95 gate / VAE score / threshold 는 바꾸지
        않고, truth/scenario/owner metadata/PHASE1 rank 는 입력으로 쓰지 않는다.
        ``"native"`` 를 명시하면 기존 row queue 순서를 보존한다.

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

    cases: list[UnsupervisedCase] = []
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
        canonical_refs = (canonicalize_ref_key(label),)
        case_id = make_phase2_case_id(
            batch_id=batch_id,
            family=_FAMILY,
            unit_type=_UNIT_TYPE,
            canonical_refs=canonical_refs,
            evidence_signature=evidence_signature,
        )
        top_features = _extract_top_features(details.loc[label])
        anomaly_score = float(scores.loc[label])
        cases.append(
            UnsupervisedCase(
                phase2_case_id=case_id,
                batch_id=batch_id,
                family=_FAMILY,
                unit_type=_UNIT_TYPE,
                row_refs=(row_ref,),
                evidence_tier=_EVIDENCE_TIER,
                # Why: gate 종류 / 임계 / 실제 ecdf 분리.
                #   ecdf_gate 가 0.95 외 값일 때도 metadata 정합 유지.
                case_generation_reason={
                    "gate": "unsupervised_ecdf",
                    "threshold": ecdf_gate,
                    "ecdf": ecdf_value,
                },
                family_score=anomaly_score,
                family_ecdf=ecdf_value,
                # invariant #17 — phase1_case_refs default, S4 linker 부착 대상.
                anomaly_score=anomaly_score,
                top_features=top_features,
                model_id=model_id,
                schema_hash=schema_hash,
            )
        )
    return _apply_ordering_strategy(cases, df=df, ordering_strategy=ordering_strategy)


def _apply_ordering_strategy(
    cases: list[UnsupervisedCase],
    *,
    df: pd.DataFrame,
    ordering_strategy: UnsupervisedOrderingStrategy,
) -> tuple[UnsupervisedCase, ...]:
    if ordering_strategy == UNSUPERVISED_ORDERING_NATIVE:
        return tuple(cases)
    if ordering_strategy != UNSUPERVISED_ORDERING_SOFT_GUARD:
        raise ValueError(
            "unsupported unsupervised ordering_strategy: "
            f"{ordering_strategy!r}; expected 'native' or "
            f"{UNSUPERVISED_ORDERING_SOFT_GUARD!r}"
        )
    return tuple(_order_cases_by_soft_document_review_priority(cases, df))


def _order_cases_by_soft_document_review_priority(
    cases: list[UnsupervisedCase],
    df: pd.DataFrame,
) -> list[UnsupervisedCase]:
    """Default VAE family display order: document-level review priority.

    The q95 gate and row case generation stay unchanged. This ordering uses only
    runtime-observable case/GL context: row anomaly score, same-document case
    count, amount-tail percentile, and period-end proximity. It intentionally
    does not use truth labels, scenario labels, owner metadata, PHASE1 ranks, or
    matched results.
    """
    if len(cases) <= 1:
        return cases

    records = _unsupervised_document_records(cases, df)
    if not records:
        return sorted(
            cases,
            key=lambda case: (-float(case.family_score or 0.0), case.phase2_case_id),
        )

    amount_percentiles = _percentile_map(
        {doc: float(record["max_amount"]) for doc, record in records.items()}
    )
    scored_docs: list[tuple[str, float]] = []
    for doc, record in records.items():
        scores = record["scores"]
        max_score = max(scores) if scores else 0.0
        amount_tail = amount_percentiles.get(doc, 0.0)
        period_end = _period_end_score(record.get("min_period_end_proximity_days"))
        hybrid = (0.70 * max_score) + (0.20 * amount_tail) + (0.10 * period_end)
        repeated_proxy = min(float(record.get("case_count") or 0) / 5.0, 1.0)
        scored_docs.append((doc, hybrid * (1.0 - (0.12 * repeated_proxy))))

    doc_rank = {
        doc: rank
        for rank, (doc, _score) in enumerate(
            sorted(scored_docs, key=lambda item: (-float(item[1]), str(item[0])))
        )
    }
    fallback_rank = len(doc_rank)

    return sorted(
        cases,
        key=lambda case: (
            doc_rank.get(_case_document_id(case), fallback_rank),
            -float(case.family_score or 0.0),
            case.phase2_case_id,
        ),
    )


def _case_document_id(case: UnsupervisedCase) -> str | None:
    if not case.row_refs:
        return None
    value = case.row_refs[0].document_id
    if value in (None, ""):
        return None
    return str(value)


def _unsupervised_document_records(
    cases: list[UnsupervisedCase],
    df: pd.DataFrame,
) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for case in cases:
        doc = _case_document_id(case)
        if doc is None:
            continue
        ref = case.row_refs[0] if case.row_refs else None
        row_position = getattr(ref, "row_position", None) if ref is not None else None
        record = records.setdefault(
            doc,
            {
                "scores": [],
                "case_count": 0,
                "max_amount": 0.0,
                "min_period_end_proximity_days": None,
            },
        )
        record["scores"].append(float(case.family_score or 0.0))
        record["case_count"] += 1
        amount = _row_amount(df, row_position)
        if amount is not None:
            record["max_amount"] = max(float(record["max_amount"]), amount)
        period_end_days = _row_period_end_proximity_days(df, row_position)
        if period_end_days is not None:
            existing = record["min_period_end_proximity_days"]
            record["min_period_end_proximity_days"] = (
                period_end_days if existing is None else min(int(existing), period_end_days)
            )
    return records


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
