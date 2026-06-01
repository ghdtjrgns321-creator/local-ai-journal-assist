"""PHASE2 duplicate family case builder (v7-plan S2).

Why: DuplicatePairDetector 가 metadata.pair_artifact.top_pairs 로 산출한 pair
feature 를 PHASE2 native DuplicateCase tuple 로 변환한다. evidence tier gate
(strong / moderate) 를 통과한 pair 만 case 화하며 evidence_signature 는
case identity (sub_rule) 만 담는다. raw 금액 / pair_score / threshold 는
signature 에 포함하지 않는다 (invariant #13).

builder 자체는 detection_result + df + batch_id 만 사용 — PHASE1 prior 접근
금지 (invariant #14). phase1_case_refs 는 default () 로 두고 linker (S4) 가
부착한다 (invariant #17).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.detection.base import DetectionResult
from src.models.phase2_case import DuplicateCase, Phase2RowRef, make_row_ref
from src.services.duplicate_pair_tier import classify_pair_evidence_tier
from src.services.phase2_case_id import make_phase2_case_id

# evidence tier gate — weak 는 case 화하지 않음 (invariant #15)
_ALLOWED_TIERS: frozenset[str] = frozenset({"strong", "moderate"})


def _resolve_row_position(df: pd.DataFrame, label: Any) -> int | None:
    """df.index.get_loc(label) 결과를 int row_position 으로 환원.

    duplicate label 발생 시 첫 occurrence 를 반환 (slice / boolean array).
    label 부재 시 None.
    """
    try:
        pos = df.index.get_loc(label)
    except (KeyError, TypeError):
        return None
    if isinstance(pos, int):
        return pos
    if isinstance(pos, slice):
        # 동일 label 다중 occurrence — slice 의 start 가 첫 위치.
        return int(pos.start) if pos.start is not None else None
    # boolean mask (numpy array) 인 경우 첫 True index.
    if isinstance(pos, np.ndarray) and pos.dtype == bool:
        nonzero = np.flatnonzero(pos)
        return int(nonzero[0]) if nonzero.size else None
    # 그 외 array-like 는 첫 원소.
    try:
        return int(pos[0])  # type: ignore[index]
    except (TypeError, IndexError):
        return None


def _column_value(df: pd.DataFrame, column: str, position: int) -> Any:
    """선택적 컬럼 값 안전 조회. 컬럼 부재 / NaN 은 None."""
    if column not in df.columns:
        return None
    value = df[column].iat[position]
    if value is None:
        return None
    # pandas scalar NaN 가드 (numeric / datetime 류)
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _make_pair_ref(df: pd.DataFrame, label: Any) -> Phase2RowRef | None:
    """label → Phase2RowRef. df 조회 실패 시 None."""
    position = _resolve_row_position(df, label)
    if position is None:
        return None
    document_id = _column_value(df, "document_id", position)
    raw_line_number = _column_value(df, "line_number", position)
    company_code = _column_value(df, "company_code", position)
    return make_row_ref(
        row_position=position,
        index_label=label,
        document_id=str(document_id) if document_id is not None else None,
        raw_line_number=raw_line_number,
        company_code=str(company_code) if company_code is not None else None,
    )


def _build_single_case(
    *,
    batch_id: str,
    pair: dict[str, Any],
    df: pd.DataFrame,
) -> DuplicateCase | None:
    """단일 pair → DuplicateCase. tier weak / row 조회 실패 시 None."""
    features = pair.get("features")
    tier = classify_pair_evidence_tier(features if isinstance(features, dict) else None)
    if tier not in _ALLOWED_TIERS:
        return None

    left_label = pair.get("left_index")
    right_label = pair.get("right_index")
    if left_label is None or right_label is None:
        return None

    left_ref = _make_pair_ref(df, left_label)
    right_ref = _make_pair_ref(df, right_label)
    if left_ref is None or right_ref is None:
        return None

    sub_rule = str(pair.get("rule_id") or "")
    # case identity 만 — pair_score / amount / threshold 절대 포함 금지 (invariant #13)
    evidence_signature = f"sub_rule={sub_rule}"
    # Phase2RowRef.index_label 은 make_row_ref 가 이미 canonical 화. 재호출 시
    # strict canonicalize 가 "s:i:10" 처럼 이중 prefix 를 부착하므로 그대로 사용.
    canonical_refs = (left_ref.index_label, right_ref.index_label)
    case_id = make_phase2_case_id(
        batch_id=batch_id,
        family="duplicate",
        unit_type="pair",
        canonical_refs=canonical_refs,
        evidence_signature=evidence_signature,
    )
    pair_score = float(pair.get("pair_score") or 0.0)

    return DuplicateCase(
        phase2_case_id=case_id,
        batch_id=batch_id,
        family="duplicate",
        unit_type="pair",
        row_refs=(left_ref, right_ref),
        evidence_tier=tier,
        case_generation_reason={
            "gate": f"evidence_tier_{tier}",
            "pair_evidence_tier": tier,
        },
        family_score=pair_score,
        family_ecdf=0.0,  # S3 store / ECDF 결합에서 별도 계산
        pair_id=str(pair.get("pair_id") or case_id),
        sub_rule=sub_rule,
        left_ref=left_ref,
        right_ref=right_ref,
        pair_evidence_tier=tier,
    )


def _case_skip_reason(pair: dict[str, Any], df: pd.DataFrame) -> str | None:
    """Return why a pair cannot become a case, or None when case-grade."""
    features = pair.get("features")
    tier = classify_pair_evidence_tier(features if isinstance(features, dict) else None)
    if tier not in _ALLOWED_TIERS:
        return "weak_pair_evidence_tier"

    left_label = pair.get("left_index")
    right_label = pair.get("right_index")
    if left_label is None or right_label is None:
        return "missing_pair_index"

    if _make_pair_ref(df, left_label) is None or _make_pair_ref(df, right_label) is None:
        return "pair_index_not_joinable_to_df"
    return None


def build_duplicate_cases(
    *,
    batch_id: str,
    detection_result: DetectionResult,
    df: pd.DataFrame,
) -> tuple[DuplicateCase, ...]:
    """duplicate detector pair_artifact 를 DuplicateCase tuple 로 변환.

    Args:
        batch_id: 분석 배치 식별자. case_id payload 에 그대로 들어감.
        detection_result: ``DuplicatePairDetector`` 가 산출한 DetectionResult.
            ``metadata.pair_artifact.top_pairs`` 를 읽는다.
        df: detection 대상 GL DataFrame. ``df.index`` 가 pair label 의 join 키.

    Returns:
        tier gate (strong / moderate) 통과 pair 의 DuplicateCase tuple.
        pair_artifact 미존재 / top_pairs 빈 / 모든 pair weak → 빈 tuple
        graceful fallback (invariant #16).
    """
    metadata = getattr(detection_result, "metadata", None) or {}
    if not isinstance(metadata, dict):
        return ()
    artifact = metadata.get("pair_artifact")
    if not isinstance(artifact, dict):
        metadata["duplicate_case_builder_diagnostics"] = {
            "top_pairs": 0,
            "case_count": 0,
            "no_case_reason": "missing_pair_artifact",
        }
        return ()
    top_pairs = artifact.get("top_pairs")
    if not isinstance(top_pairs, list) or not top_pairs:
        coverage = artifact.get("coverage") if isinstance(artifact.get("coverage"), dict) else {}
        row_hits = int(coverage.get("row_score_hit_count") or len(detection_result.flagged_indices))
        reason = "empty_pair_artifact_top_pairs"
        if row_hits > 0:
            reason = str(artifact.get("truncation_reason") or reason)
        metadata["duplicate_case_builder_diagnostics"] = {
            "top_pairs": 0,
            "case_count": 0,
            "row_score_hit_count": row_hits,
            "no_case_reason": reason,
        }
        return ()

    cases: list[DuplicateCase] = []
    skip_counts: dict[str, int] = {}
    for pair in top_pairs:
        if not isinstance(pair, dict):
            skip_counts["invalid_pair_payload"] = skip_counts.get("invalid_pair_payload", 0) + 1
            continue
        skip_reason = _case_skip_reason(pair, df)
        if skip_reason is not None:
            skip_counts[skip_reason] = skip_counts.get(skip_reason, 0) + 1
            continue
        case = _build_single_case(batch_id=batch_id, pair=pair, df=df)
        if case is not None:
            cases.append(case)
    no_case_reason = None
    if not cases:
        no_case_reason = (
            max(skip_counts, key=skip_counts.get) if skip_counts else "no_case_grade_pair"
        )
    metadata["duplicate_case_builder_diagnostics"] = {
        "top_pairs": len(top_pairs),
        "case_count": len(cases),
        "skipped_pair_counts": skip_counts,
        "no_case_reason": no_case_reason,
    }
    return tuple(cases)


__all__ = ["build_duplicate_cases"]
