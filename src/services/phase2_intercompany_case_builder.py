"""PHASE2 intercompany family case builder (v7-plan S5 Phase B).

Why: IntercompanyMatcher 가 metadata.ic_pair_artifact 로 산출한 4종 sanitized
projection 중 reciprocal_pairs + mismatch_pairs 만 IntercompanyCase tuple 로
변환한다. unmatched_rows / timing-only candidate 단독은 case 화하지 않는다
(invariant #54, Δ5).

도메인 정당화:
    - reciprocal_flow → ISA 550 ¶A20 (양방향 reconciliation) +
      PCAOB AS 2401 §B7 (intercompany unusual journal entries). 단일 doc
      안 receivable+payable + amount symmetry → strong evidence.
    - amount_mismatch → PCAOB AS 2401 .A6 (3) (금액 mismatch 의도성 증거).

evidence_signature 는 ``f"ic_role={role}"`` 만 — raw 금액 / score / symmetry /
ratio 는 case identity 가 아니므로 절대 포함하지 않는다 (invariant #55).
builder 자체는 detection_result + df + batch_id 만 사용 — PHASE1 prior 접근
금지 (invariant #56). phase1_case_refs 는 default () 로 두고 linker (S4) 가
부착한다.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.detection.base import DetectionResult
from src.models.phase2_case import IntercompanyCase, Phase2RowRef, make_row_ref
from src.services.phase2_case_id import make_phase2_case_id

_FAMILY = "intercompany"
_UNIT_TYPE = "pair"
_ROLE_RECIPROCAL = "reciprocal_flow"
_ROLE_MISMATCH = "amount_mismatch"
_TIER_RECIPROCAL = "strong"
_TIER_MISMATCH = "moderate"


def _resolve_row_position(df: pd.DataFrame, label: Any) -> int | None:
    """df.index.get_loc(label) 결과를 int row_position 으로 환원.

    duplicate builder 의 _resolve_row_position 패턴 동일.
    """
    try:
        pos = df.index.get_loc(label)
    except (KeyError, TypeError):
        return None
    if isinstance(pos, int):
        return pos
    if isinstance(pos, slice):
        return int(pos.start) if pos.start is not None else None
    if isinstance(pos, np.ndarray) and pos.dtype == bool:
        nonzero = np.flatnonzero(pos)
        return int(nonzero[0]) if nonzero.size else None
    try:
        return int(pos[0])  # type: ignore[index]
    except (TypeError, IndexError):
        return None


def _column_value(df: pd.DataFrame, column: str, position: int) -> Any:
    """선택적 컬럼 값 안전 조회. 컬럼 부재 / NaN → None."""
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


def _make_ref(df: pd.DataFrame, label: Any) -> Phase2RowRef | None:
    """label → Phase2RowRef. df 조회 실패 시 None.

    legacy 경로 (artifact entry 에 position 정보 없는 구 schema) 만 사용. MultiIndex
    환경에서는 ``_make_ref_from_position`` 을 우선 사용해야 한다 (invariant #59).
    """
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


def _make_ref_from_position(
    df: pd.DataFrame,
    *,
    position: int,
) -> Phase2RowRef | None:
    """artifact entry 의 row_position 으로 ``df.index[position]`` 을 source of truth.

    Why (invariant #59 + #60): ``_ic_json_safe`` 가 MultiIndex tuple 을 str 평탄화
    ("('DOC100', 0)") 하므로 artifact 의 ``index_label`` 을 그대로 ``make_row_ref``
    에 넣으면 canonicalize 가 ``"s:('DOC100', 0)"`` 으로 가공된다. S1/S4 의 row_ref_map
    + label-based linker 는 ``df.index[position]`` 을 canonicalize 한 결과
    (``"t:(s:DOC100|i:0)"``) 를 expected canonical 로 본다. 두 표현이 어긋나면
    full-population row_ref_map 도입 시 label hash 매칭이 깨진다.

    따라서 builder 는 artifact 의 label 을 무시하고 ``df.index[position]`` 자체를
    canonicalize → make_row_ref 에 주입. artifact 의 ``*_indices`` 는 display/debug
    payload 로만 사용한다.
    """
    if position < 0 or position >= len(df):
        return None
    document_id = _column_value(df, "document_id", position)
    raw_line_number = _column_value(df, "line_number", position)
    company_code = _column_value(df, "company_code", position)
    # source of truth: df.index[position] — MultiIndex tuple 도 그대로 보존되어
    # canonicalize_ref_key 가 t:(s:...|i:...) 같은 canonical 표현을 만든다.
    actual_label = df.index[position]
    return make_row_ref(
        row_position=position,
        index_label=actual_label,
        document_id=str(document_id) if document_id is not None else None,
        raw_line_number=raw_line_number,
        company_code=str(company_code) if company_code is not None else None,
    )


def _counterparty_pair(
    df: pd.DataFrame,
    left_ref: Phase2RowRef,
    right_ref: Phase2RowRef,
) -> tuple[str, str] | None:
    """trading_partner / company_code 컬럼에서 counterparty pair 추출."""
    if "company_code" not in df.columns and "trading_partner" not in df.columns:
        return None
    left = _column_value(df, "trading_partner", left_ref.row_position)
    right = _column_value(df, "trading_partner", right_ref.row_position)
    if left is None:
        left = _column_value(df, "company_code", left_ref.row_position)
    if right is None:
        right = _column_value(df, "company_code", right_ref.row_position)
    if left is None and right is None:
        return None
    return (str(left or ""), str(right or ""))


def _build_case(
    *,
    batch_id: str,
    ic_role: str,
    tier: str,
    row_refs: tuple[Phase2RowRef, ...],
    family_score: float,
    counterparty_pair: tuple[str, str] | None,
    amount_a: float | None,
    amount_b: float | None,
    amount_symmetry: float | None,
) -> IntercompanyCase:
    canonical_refs = tuple(ref.index_label for ref in row_refs)
    # case identity 만 — raw 금액 / symmetry / ratio 절대 포함 금지 (invariant #55)
    evidence_signature = f"ic_role={ic_role}"
    case_id = make_phase2_case_id(
        batch_id=batch_id,
        family=_FAMILY,
        unit_type=_UNIT_TYPE,
        canonical_refs=canonical_refs,
        evidence_signature=evidence_signature,
    )
    return IntercompanyCase(
        phase2_case_id=case_id,
        batch_id=batch_id,
        family=_FAMILY,
        unit_type=_UNIT_TYPE,
        row_refs=row_refs,
        evidence_tier=tier,
        case_generation_reason={
            "gate": f"ic_{tier}_evidence",
            "ic_role": ic_role,
        },
        family_score=float(family_score),
        family_ecdf=0.0,  # S3 store / ECDF 결합에서 별도 계산
        ic_role=ic_role,
        counterparty_pair=counterparty_pair,
        amount_a=amount_a,
        amount_b=amount_b,
        amount_symmetry=amount_symmetry,
    )


def _build_reciprocal_case(
    entry: dict[str, Any],
    *,
    df: pd.DataFrame,
    batch_id: str,
) -> IntercompanyCase | None:
    """reciprocal_pairs entry → IntercompanyCase(ic_role='reciprocal_flow').

    S5 Followup (2026-05-27): 양쪽 row 보존 (invariant #58).
      - ``receivable_indices`` + ``receivable_positions`` 의 row 들과
        ``payable_indices`` + ``payable_positions`` 의 row 들을 모두 row_refs 로 포함.
      - artifact 가 doc 안 양쪽 row 를 모두 보유 → "무엇과 무엇이 reciprocal" 답 가능.
      - PHASE1 cross-ref (S4 linker) 가 양쪽 모두에서 hit 회수.
      - 구 schema (``row_index`` 만 보유) 는 legacy fallback 으로 graceful 처리.
    """
    rec_indices = entry.get("receivable_indices") or []
    rec_positions = entry.get("receivable_positions") or []
    pay_indices = entry.get("payable_indices") or []
    pay_positions = entry.get("payable_positions") or []

    # legacy graceful fallback — 구 schema entry (row_index 만 보유)
    if not rec_indices and not pay_indices:
        legacy_label = entry.get("row_index")
        legacy_pos = entry.get("row_position")
        if legacy_label is None:
            return None
        # row_position 있으면 position-based, 없으면 label-based (구 호출자).
        if legacy_pos is not None:
            ref = _make_ref_from_position(df, position=int(legacy_pos))
        else:
            ref = _make_ref(df, legacy_label)
        if ref is None:
            return None
        refs: tuple[Phase2RowRef, ...] = (ref,)
        counterparty = _counterparty_pair(df, ref, ref)
    else:
        # Why: rec_indices / pay_indices 는 artifact 의 display payload — index_label
        # 은 df.index[position] (source of truth) 에서 _make_ref_from_position 이 직접 추출.
        rec_refs: list[Phase2RowRef] = []
        for position in rec_positions:
            ref = _make_ref_from_position(df, position=int(position))
            if ref is not None:
                rec_refs.append(ref)
        pay_refs: list[Phase2RowRef] = []
        for position in pay_positions:
            ref = _make_ref_from_position(df, position=int(position))
            if ref is not None:
                pay_refs.append(ref)
        all_refs: tuple[Phase2RowRef, ...] = (*rec_refs, *pay_refs)
        if not all_refs:
            return None
        refs = all_refs
        # counterparty_pair 는 receivable 측 첫 row + payable 측 첫 row.
        if rec_refs and pay_refs:
            counterparty = _counterparty_pair(df, rec_refs[0], pay_refs[0])
        elif rec_refs:
            counterparty = _counterparty_pair(df, rec_refs[0], rec_refs[0])
        else:
            counterparty = _counterparty_pair(df, pay_refs[0], pay_refs[0])

    rec_amt = float(entry.get("receivable_amount") or 0.0)
    pay_amt = float(entry.get("payable_amount") or 0.0)
    symmetry = float(entry.get("amount_symmetry") or 0.0)
    return _build_case(
        batch_id=batch_id,
        ic_role=_ROLE_RECIPROCAL,
        tier=_TIER_RECIPROCAL,
        row_refs=refs,
        family_score=symmetry,
        counterparty_pair=counterparty,
        amount_a=rec_amt,
        amount_b=pay_amt,
        amount_symmetry=symmetry,
    )


def _build_mismatch_case(
    entry: dict[str, Any],
    *,
    df: pd.DataFrame,
    batch_id: str,
) -> IntercompanyCase | None:
    """mismatch_pairs entry → IntercompanyCase(ic_role='amount_mismatch').

    S5 Followup (2026-05-27): artifact 가 ``left_position`` / ``right_position`` 을
    함께 보유하면 position 기반 lookup 우선 — MultiIndex/tuple label 환경에서도
    안전 (invariant #59). 구 schema 는 legacy fallback (``_make_ref``) 으로 graceful.
    """
    left_label = entry.get("left_index")
    right_label = entry.get("right_index")
    if left_label is None or right_label is None:
        return None
    left_pos = entry.get("left_position")
    right_pos = entry.get("right_position")
    if left_pos is not None and right_pos is not None:
        left_ref = _make_ref_from_position(df, position=int(left_pos))
        right_ref = _make_ref_from_position(df, position=int(right_pos))
    else:
        # legacy schema fallback — artifact label 로 label-based lookup.
        left_ref = _make_ref(df, left_label)
        right_ref = _make_ref(df, right_label)
    if left_ref is None or right_ref is None:
        return None
    amount_a = float(entry.get("amount_a") or 0.0)
    amount_b = float(entry.get("amount_b") or 0.0)
    ratio = float(entry.get("ratio") or 0.0)
    severity = float(entry.get("mismatch_severity") or 0.0)
    counterparty = _counterparty_pair(df, left_ref, right_ref)
    # row_refs duplicate (left == right) 방어 — 같은 label 이면 단일 ref.
    if left_ref.index_label == right_ref.index_label:
        row_refs: tuple[Phase2RowRef, ...] = (left_ref,)
    else:
        row_refs = (left_ref, right_ref)
    return _build_case(
        batch_id=batch_id,
        ic_role=_ROLE_MISMATCH,
        tier=_TIER_MISMATCH,
        row_refs=row_refs,
        family_score=severity,
        counterparty_pair=counterparty,
        amount_a=amount_a,
        amount_b=amount_b,
        amount_symmetry=ratio,
    )


def build_intercompany_cases(
    *,
    batch_id: str,
    detection_result: DetectionResult,
    df: pd.DataFrame,
) -> tuple[IntercompanyCase, ...]:
    """ic_pair_artifact 의 reciprocal_pairs + mismatch_pairs → IntercompanyCase.

    Args:
        batch_id: 분석 배치 식별자.
        detection_result: ``IntercompanyMatcher`` 가 산출한 DetectionResult.
            ``metadata.ic_pair_artifact`` 의 5종 list 중 reciprocal_pairs 와
            mismatch_pairs 만 case 화한다 (invariant #54).
        df: detection 대상 GL DataFrame.

            **Row lookup 정책 (S5 Followup 2, invariant #59 + #60)**:

            - artifact entry 가 position 필드 (``row_position`` /
              ``receivable_positions`` / ``payable_positions`` /
              ``left_position`` / ``right_position``) 를 보유하면 **position 우선** —
              ``df.iloc`` / ``df.index[position]`` 을 source of truth 로 사용.
              MultiIndex / tuple label 환경에서도 안전 + S1/S4 row_ref_map 의
              canonical identity (``t:(...)``) 와 일관.
            - artifact entry 가 position 필드 없이 legacy schema (``row_index``
              / ``left_index`` / ``right_index`` 만) 라면 **label-based fallback** —
              ``_make_ref(df, label)`` 가 ``df.index.get_loc(label)`` 로 lookup.
              MultiIndex 환경에서는 ``_ic_json_safe`` 평탄화로 lookup 실패 가능
              (호출자 책임).

            artifact 의 ``*_indices`` / ``*_index`` 필드는 display / debug payload
            로만 보존되며 join key 가 아니다. ``row_refs[*].index_label`` 의 source
            of truth 는 항상 ``df.index[position]`` (invariant #60).

    Returns:
        Gate 통과한 IntercompanyCase tuple. ic_pair_artifact 부재 / 빈 entry →
        빈 tuple graceful fallback (invariant #57).
    """
    if detection_result is None or getattr(detection_result, "track_name", "") != _FAMILY:
        return ()
    metadata = getattr(detection_result, "metadata", None) or {}
    if not isinstance(metadata, dict):
        return ()
    artifact = metadata.get("ic_pair_artifact")
    if not isinstance(artifact, dict):
        return ()

    cases: list[IntercompanyCase] = []

    # reciprocal_flow — strong evidence tier
    for entry in artifact.get("reciprocal_pairs", []):
        if not isinstance(entry, dict):
            continue
        case = _build_reciprocal_case(entry, df=df, batch_id=batch_id)
        if case is not None:
            cases.append(case)

    # amount_mismatch — moderate evidence tier
    for entry in artifact.get("mismatch_pairs", []):
        if not isinstance(entry, dict):
            continue
        case = _build_mismatch_case(entry, df=df, batch_id=batch_id)
        if case is not None:
            cases.append(case)

    # unmatched_rows / candidate_pairs (timing-only) → Gate 차단 (invariant #54)

    return tuple(cases)


__all__ = ["build_intercompany_cases"]
