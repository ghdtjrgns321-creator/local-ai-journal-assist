"""PHASE2 relational family case builder (v7-plan S6 Phase C).

Why: RelationalDetector 가 metadata.relational_edge_artifact 로 산출한 edge 단위
projection 을 RelationalCase tuple 로 변환한다. row 단위 details/scores 가 아니라
edge 단위 grouping 이 case identity 기준 — 같은 (rule, edge_a, edge_b) 의 여러 row
가 한 case 로 묶인다.

    Gate (invariant #64):
    evidence_tier == "strong"
        OR (
            evidence_tier == "moderate"
            AND positive_metric_count >= 20
            AND family_ecdf >= 0.95
        )
    family_ecdf 는 edge artifact 안의 positive metric_value 분포에서
    zero-preserving ECDF 로 계산한다. 이 값은 native edge artifact 내부의
    상대적 tail 위치이며, DataSynth truth 라벨을 보지 않는다.

evidence_signature (invariant #64):
    ``f"sub_rule={rule_id}|edge_a={edge_a}|edge_b={edge_b}"`` — case identity 만.
    metric_value / raw score 절대 포함 금지.

PHASE1 prior 접근 0건 (invariant #67). phase1_case_refs default () — linker (S4)
가 부착한다.

도메인 정당화:
    - PCAOB AS 2401 §B7 — journal entries reflecting unusual relationships
      (relational graph 단위로 unusual relationship 을 가시화).
    - ISA 240 §32 — management override via unusual relationships.
"""

from __future__ import annotations

import dataclasses
from collections import Counter, defaultdict
from typing import Any

import numpy as np
import pandas as pd

from src.detection.base import DetectionResult
from src.models.phase2_case import Phase2RowRef, RelationalCase, make_row_ref
from src.services.phase2_case_id import make_phase2_case_id
from src.services.phase2_family_policy import (
    RELATIONAL_CONTEXT_LANE_SUB_RULES,
    RELATIONAL_MODERATE_AUDIT_BUSINESS_LANE_SUB_RULES,
    RELATIONAL_PRIMARY_DENOMINATOR_STATUS,
    RELATIONAL_PRIMARY_METADATA_BACKLOG,
    RELATIONAL_PRODUCT_ROLE,
    RELATIONAL_REVIEW_SURFACE_NAME,
    RELATIONAL_REVIEW_SURFACE_POLICY,
    RELATIONAL_STRUCTURAL_LANE_SUB_RULES,
)

_FAMILY = "relational"
_UNIT_TYPE = "edge"
_MODERATE_ECDF_GATE = 0.95
_MODERATE_MIN_POSITIVE_EDGES = 20
_AUDIT_CONTEXT_PREFIX = 50


def _zero_preserving_edge_ecdf(edges: list[dict[str, Any]]) -> dict[int, float]:
    """edge metric_value 기반 zero-preserving ECDF.

    Why: relational native gate 의 moderate 조건은 family tail(q95+) 보강을
    요구한다. 기존에는 family_ecdf=0.0 placeholder 때문에 moderate edge 가
    항상 탈락했다. 여기서는 artifact 전체의 positive metric_value 만 rank 하며,
    raw amount / threshold / truth label 은 사용하지 않는다. 단, moderate gate 는
    positive edge sample 이 너무 작으면 q95 의미가 약하므로 별도 최소 표본을
    요구한다.
    """
    score_by_position: dict[int, float] = {}
    for idx, entry in enumerate(edges):
        if not isinstance(entry, dict):
            continue
        try:
            score = float(entry.get("metric_value") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        if score > 0.0:
            score_by_position[idx] = score
    if not score_by_position:
        return {}
    scores = pd.Series(score_by_position, dtype=float)
    ranks = scores.rank(method="max", pct=True)
    return {int(idx): float(value) for idx, value in ranks.items()}


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


def _make_ref_from_position(
    df: pd.DataFrame,
    *,
    position: int,
) -> Phase2RowRef | None:
    """artifact entry 의 row_position 으로 ``df.index[position]`` 을 source of truth.

    Why (invariant #66 + S5 invariant #59/#60): artifact 의 row_indices 는 sanitized
    display payload (MultiIndex tuple → str 평탄화). builder 는 그 label 을 무시하고
    ``df.index[position]`` 을 직접 canonicalize → make_row_ref. 이렇게 해야 S4
    linker 의 label hash 매칭과 일관성을 갖는다.
    """
    if position < 0 or position >= len(df):
        return None
    document_id = _column_value(df, "document_id", position)
    raw_line_number = _column_value(df, "line_number", position)
    company_code = _column_value(df, "company_code", position)
    # source of truth: df.index[position] — MultiIndex / tuple label 도 그대로
    # 보존되어 canonicalize_ref_key 가 t:(s:...|i:...) 같은 canonical 표현을 만든다.
    actual_label = df.index[position]
    return make_row_ref(
        row_position=position,
        index_label=actual_label,
        document_id=str(document_id) if document_id is not None else None,
        raw_line_number=raw_line_number,
        company_code=str(company_code) if company_code is not None else None,
    )


def _gate_pass(
    evidence_tier: str,
    family_ecdf: float,
    *,
    positive_metric_count: int,
) -> bool:
    """Δ5 Gate — strong OR (moderate AND family_ecdf >= 0.95).

    family_ecdf 는 edge artifact positive metric_value 분포에서 계산된다.
    moderate edge 는 q95+ tail 이면서 최소 positive edge 표본을 만족해야
    case-grade review candidate 로 승격된다.
    """
    if evidence_tier == "strong":
        return True
    if (
        evidence_tier == "moderate"
        and positive_metric_count >= _MODERATE_MIN_POSITIVE_EDGES
        and family_ecdf >= _MODERATE_ECDF_GATE
    ):
        return True
    return False


def _build_case_from_edge(
    entry: dict[str, Any],
    *,
    df: pd.DataFrame,
    batch_id: str,
    family_ecdf: float,
    positive_metric_count: int,
) -> RelationalCase | None:
    """relational_edge_artifact.edges entry → RelationalCase.

    Gate 통과 못 하면 None 반환.
    """
    evidence_tier = str(entry.get("evidence_tier") or "")
    if not _gate_pass(
        evidence_tier,
        family_ecdf,
        positive_metric_count=positive_metric_count,
    ):
        return None

    row_positions = entry.get("row_positions") or []
    refs: list[Phase2RowRef] = []
    for position in row_positions:
        try:
            pos_int = int(position)
        except (TypeError, ValueError):
            continue
        ref = _make_ref_from_position(df, position=pos_int)
        if ref is not None:
            refs.append(ref)
    if not refs:
        return None

    rule_id = str(entry.get("rule_id") or "")
    edge_a = str(entry.get("edge_a") or "")
    edge_b = str(entry.get("edge_b") or "")
    metric_name = str(entry.get("metric_name") or "")
    metric_value = float(entry.get("metric_value") or 0.0)

    row_refs = tuple(refs)
    canonical_refs = tuple(ref.index_label for ref in row_refs)
    # case identity 만 — metric_value 절대 포함 금지 (invariant #64).
    evidence_signature = f"sub_rule={rule_id}|edge_a={edge_a}|edge_b={edge_b}"
    case_id = make_phase2_case_id(
        batch_id=batch_id,
        family=_FAMILY,
        unit_type=_UNIT_TYPE,
        canonical_refs=canonical_refs,
        evidence_signature=evidence_signature,
    )
    return RelationalCase(
        phase2_case_id=case_id,
        batch_id=batch_id,
        family=_FAMILY,
        unit_type=_UNIT_TYPE,
        row_refs=row_refs,
        evidence_tier=evidence_tier,
        case_generation_reason={
            "gate": (
                f"relational_{evidence_tier}_evidence"
                if evidence_tier == "strong"
                else "relational_moderate_family_ecdf_q95"
            ),
            "sub_rule": rule_id,
            "family_ecdf": family_ecdf,
            "positive_metric_count": positive_metric_count,
        },
        family_score=metric_value,
        family_ecdf=family_ecdf,
        sub_rule=rule_id,
        edge_a=edge_a,
        edge_b=edge_b,
        metric_name=metric_name,
        metric_value=metric_value,
    )


def _tier_rank(case: RelationalCase) -> int:
    return {"strong": 3, "moderate": 2, "ml_quantile": 1, "weak": 0}.get(
        str(case.evidence_tier).lower(),
        -1,
    )


def _current_review_order(cases: list[RelationalCase]) -> list[RelationalCase]:
    return sorted(
        cases,
        key=lambda case: (
            -_tier_rank(case),
            -float(case.family_score or 0.0),
            case.phase2_case_id,
        ),
    )


def _count_bucket(value: int) -> str:
    if value <= 1:
        return "1"
    if value <= 3:
        return "2_3"
    if value <= 10:
        return "4_10"
    if value <= 50:
        return "11_50"
    return "51_plus"


def _account_class(value: str) -> str:
    text = str(value or "")
    if text.startswith(("1", "2")):
        return "balance_sheet"
    if text.startswith(("4", "5", "6", "7", "8")):
        return "income_statement"
    if text:
        return "other_account"
    return "blank_account"


def _age_bucket(days: float | int | None) -> str:
    if days is None or not np.isfinite(float(days)):
        return "unknown_age"
    value = float(days)
    if value <= 30:
        return "new_0_30"
    if value <= 90:
        return "new_31_90"
    if value <= 365:
        return "known_91_365"
    return "known_365_plus"


def _gap_bucket(days: float | int | None) -> str:
    if days is None or not np.isfinite(float(days)):
        return "unknown_gap"
    value = float(days)
    if value >= 365:
        return "dormant_365_plus"
    if value >= 180:
        return "dormant_180_364"
    if value >= 90:
        return "gap_90_179"
    return "recent"


def _mode_text(df: pd.DataFrame, positions: list[int], column: str, default: str) -> str:
    if column not in df.columns or not positions:
        return default
    values = df.iloc[positions][column].dropna().astype(str)
    if values.empty:
        return default
    mode = values.mode()
    return str(mode.iat[0]) if not mode.empty else default


def _context_series(df: pd.DataFrame) -> dict[str, pd.Series]:
    out: dict[str, pd.Series] = {}
    if {"trading_partner", "posting_date"}.issubset(df.columns):
        work = df[["trading_partner", "posting_date"]].copy()
        work["_position"] = np.arange(len(df), dtype=int)
        work["posting_date"] = pd.to_datetime(work["posting_date"], errors="coerce")
        work = work.sort_values(["trading_partner", "posting_date", "_position"])
        first_seen = work.groupby("trading_partner")["posting_date"].transform("min")
        work["days_since_partner_first_seen"] = (work["posting_date"] - first_seen).dt.days
        age = pd.Series(np.nan, index=np.arange(len(df), dtype=int), dtype=float)
        age.loc[work["_position"].to_numpy()] = work[
            "days_since_partner_first_seen"
        ].to_numpy()
        out["days_since_partner_first_seen"] = age
    if {"gl_account", "posting_date"}.issubset(df.columns):
        work = df[["gl_account", "posting_date"]].copy()
        work["_position"] = np.arange(len(df), dtype=int)
        work["posting_date"] = pd.to_datetime(work["posting_date"], errors="coerce")
        work = work.sort_values(["gl_account", "posting_date", "_position"])
        work["dormant_gap_days"] = work.groupby("gl_account")["posting_date"].diff().dt.days
        gap = pd.Series(np.nan, index=np.arange(len(df), dtype=int), dtype=float)
        gap.loc[work["_position"].to_numpy()] = work["dormant_gap_days"].to_numpy()
        out["dormant_gap_days"] = gap
    return out


def _case_positions(case: RelationalCase, df_len: int) -> list[int]:
    return [
        ref.row_position
        for ref in case.row_refs
        if 0 <= ref.row_position < df_len
    ]


def _case_documents(case: RelationalCase) -> set[str]:
    return {
        str(ref.document_id)
        for ref in case.row_refs
        if getattr(ref, "document_id", None) not in (None, "")
    }


def _audit_context_key(
    case: RelationalCase,
    *,
    df: pd.DataFrame,
    context: dict[str, pd.Series],
) -> tuple[str, str, str, str, str]:
    positions = _case_positions(case, len(df))
    if case.sub_rule == "R01" and "days_since_partner_first_seen" in context and positions:
        values = context["days_since_partner_first_seen"].iloc[positions]
        timing_bucket = _age_bucket(float(values.min()) if values.notna().any() else None)
    elif case.sub_rule == "R02" and "dormant_gap_days" in context and positions:
        values = context["dormant_gap_days"].iloc[positions]
        timing_bucket = _gap_bucket(float(values.max()) if values.notna().any() else None)
    else:
        timing_bucket = "other_timing"
    account = _mode_text(df, positions, "gl_account", "")
    return (
        str(case.sub_rule),
        timing_bucket,
        _account_class(account),
        _count_bucket(len(_case_documents(case))),
        case.phase2_case_id,
    )


def _business_process_key(case: RelationalCase, *, df: pd.DataFrame) -> tuple[str, str]:
    positions = _case_positions(case, len(df))
    return (_mode_text(df, positions, "business_process", "unknown"), case.phase2_case_id)


def _case_text_values(case: RelationalCase, *, df: pd.DataFrame, column: str) -> list[str]:
    positions = _case_positions(case, len(df))
    if not positions or column not in df.columns:
        return []
    return [str(value) for value in df.iloc[positions][column].dropna().tolist()]


def _contains_any(values: list[str], tokens: tuple[str, ...]) -> bool:
    upper_values = [value.upper() for value in values]
    return any(token in value for token in tokens for value in upper_values)


def _employee_vendor_profile_score(case: RelationalCase, *, df: pd.DataFrame) -> tuple[int, int]:
    """Observable hidden relationship profile score for first-review ordering.

    Uses only auditor-visible GL context: reference/counterparty text, P2P
    process, account class, and document support. Truth labels, scenario labels,
    owner metadata, PHASE1 rank, and matched-result membership are not inputs.
    """
    reference_values = _case_text_values(case, df=df, column="reference")
    partner_values = _case_text_values(case, df=df, column="trading_partner")
    process = _mode_text(df, _case_positions(case, len(df)), "business_process", "unknown")
    account = _mode_text(df, _case_positions(case, len(df)), "gl_account", "")
    relationship_text = _contains_any(
        reference_values + partner_values,
        ("EMPLOYEE", "STAFF", "PERSONNEL", "VENDOR", "SUPPLIER", "REIMBURSE"),
    )
    p2p_process = process.upper() in {"P2P", "PROCURE_TO_PAY", "PURCHASE_TO_PAY"}
    balance_sheet = _account_class(account) == "balance_sheet"
    multi_doc_support = len(_case_documents(case)) >= 2
    return (
        int(relationship_text)
        + int(p2p_process)
        + int(balance_sheet)
        + int(multi_doc_support),
        int(relationship_text),
    )


def _employee_vendor_profile_lane(
    current: list[RelationalCase],
    *,
    df: pd.DataFrame,
) -> list[RelationalCase]:
    candidates = [
        case for case in current if _employee_vendor_profile_score(case, df=df)[1] > 0
    ]
    return sorted(
        candidates,
        key=lambda case: (
            -_employee_vendor_profile_score(case, df=df)[0],
            -_employee_vendor_profile_score(case, df=df)[1],
            case.sub_rule not in {"R01", "R03", "R07"},
            -_tier_rank(case),
            -float(case.family_score or 0.0),
            case.phase2_case_id,
        ),
    )


def _balance_by_key(
    cases: list[RelationalCase],
    key_by_case: dict[str, tuple[str, ...]],
) -> list[RelationalCase]:
    by_bucket: dict[tuple[str, ...], list[RelationalCase]] = defaultdict(list)
    for case in cases:
        by_bucket[key_by_case[case.phase2_case_id]].append(case)
    out: list[RelationalCase] = []
    cursor = 0
    order = sorted(by_bucket)
    while len(out) < len(cases):
        moved = False
        for bucket_key in order:
            bucket = by_bucket[bucket_key]
            if cursor < len(bucket):
                out.append(bucket[cursor])
                moved = True
        if not moved:
            break
        cursor += 1
    return out


def _moderate_audit_then_business_lane(
    current: list[RelationalCase],
    *,
    df: pd.DataFrame,
) -> list[RelationalCase]:
    moderate_tail = [
        case
        for case in current
        if case.sub_rule in {"R01", "R02"}
        and case.evidence_tier == "moderate"
        and int(case.case_generation_reason.get("positive_metric_count", 0)) >= 20
        and float(case.family_ecdf or 0.0) >= _MODERATE_ECDF_GATE
    ]
    context = _context_series(df)
    audit_key_by_case = {
        case.phase2_case_id: _audit_context_key(case, df=df, context=context)
        for case in moderate_tail
    }
    business_key_by_case = {
        case.phase2_case_id: _business_process_key(case, df=df)
        for case in moderate_tail
    }
    audit_rows = _balance_by_key(moderate_tail, audit_key_by_case)
    business_rows = _balance_by_key(moderate_tail, business_key_by_case)
    selected = audit_rows[:_AUDIT_CONTEXT_PREFIX]
    selected_ids = {case.phase2_case_id for case in selected}
    selected.extend(case for case in business_rows if case.phase2_case_id not in selected_ids)
    selected_ids = {case.phase2_case_id for case in selected}
    selected.extend(case for case in audit_rows if case.phase2_case_id not in selected_ids)
    return selected


def _interleave_lanes(
    structural_lane: list[RelationalCase],
    moderate_lane: list[RelationalCase],
    *,
    total: int,
) -> list[RelationalCase]:
    out: list[RelationalCase] = []
    cursors = [0, 0]
    lanes = [structural_lane, moderate_lane]
    while len(out) < total:
        moved = False
        for lane_idx, lane in enumerate(lanes):
            cursor = cursors[lane_idx]
            if cursor < len(lane):
                out.append(lane[cursor])
                cursors[lane_idx] += 1
                moved = True
                if len(out) >= total:
                    break
        if not moved:
            break
    return out


def sort_relational_cases_for_review_surface(
    cases: list[RelationalCase] | tuple[RelationalCase, ...],
    *,
    df: pd.DataFrame,
) -> tuple[RelationalCase, ...]:
    """Product default relational review surface order.

    Truth/scenario labels are intentionally not inputs. The 1:1 structural/moderate
    split is an audit review surface policy, not a fixed5 recall-maximizing selector.
    """
    current = _current_review_order(list(cases))
    profile_prefix = _employee_vendor_profile_lane(current, df=df)[:100]
    structural_lane = [
        case for case in current if case.sub_rule in {"R03", "R07"}
    ]
    moderate_lane = _moderate_audit_then_business_lane(current, df=df)
    selected = _interleave_lanes(structural_lane, moderate_lane, total=len(current))
    profile_ids = {case.phase2_case_id for case in profile_prefix}
    selected = [case for case in selected if case.phase2_case_id not in profile_ids]
    selected_ids = profile_ids | {case.phase2_case_id for case in selected}
    ordered = (
        profile_prefix
        + selected
        + [case for case in current if case.phase2_case_id not in selected_ids]
    )
    by_id_counts: Counter[str] = Counter(case.phase2_case_id for case in ordered)
    annotated: list[RelationalCase] = []
    for ordinal, case in enumerate(ordered, start=1):
        reason = dict(case.case_generation_reason)
        reason.update(
            {
                "relational_review_surface_policy": RELATIONAL_REVIEW_SURFACE_POLICY,
                "relational_review_surface_name": RELATIONAL_REVIEW_SURFACE_NAME,
                "relational_product_role": RELATIONAL_PRODUCT_ROLE,
                "relational_role_scope": "relationship_review_surface_primary_pending",
                "relational_primary_denominator_status": (
                    RELATIONAL_PRIMARY_DENOMINATOR_STATUS
                ),
                "relational_primary_recall_pending_reason": (
                    "relationship-primary denominator is unavailable in fixed5 v3.2d; "
                    "do not treat this as family retirement"
                ),
                "relational_primary_metadata_backlog": RELATIONAL_PRIMARY_METADATA_BACKLOG,
                "relational_structural_lane_sub_rules": RELATIONAL_STRUCTURAL_LANE_SUB_RULES,
                "relational_moderate_audit_business_lane_sub_rules": (
                    RELATIONAL_MODERATE_AUDIT_BUSINESS_LANE_SUB_RULES
                ),
                "relational_context_lane_sub_rules": RELATIONAL_CONTEXT_LANE_SUB_RULES,
                "relational_employee_vendor_profile_prefix_size": 100,
                "relational_employee_vendor_profile_prefix_inputs": (
                    "reference/trading_partner text, business_process, account_class, "
                    "document_support"
                ),
                "relational_primary_recall_tuning_allowed": False,
                "relational_primary_recall_tuning_blocked_until_metadata": True,
                "relational_review_surface_rank": ordinal,
                "relational_review_surface_duplicate_id_count": by_id_counts[
                    case.phase2_case_id
                ],
            }
        )
        annotated.append(dataclasses.replace(case, case_generation_reason=reason))
    return tuple(annotated)


def build_relational_cases(
    *,
    batch_id: str,
    detection_result: DetectionResult,
    df: pd.DataFrame,
) -> tuple[RelationalCase, ...]:
    """relational_edge_artifact.edges → RelationalCase tuple.

    Args:
        batch_id: 분석 배치 식별자.
        detection_result: ``RelationalDetector`` 가 산출한 DetectionResult.
            ``metadata.relational_edge_artifact`` 만 소비 — 기존 row 단위 details
            / scores 는 builder 가 사용하지 않는다 (invariant #61 정합).
        df: detection 대상 GL DataFrame. row_refs 의 source of truth.

    Returns:
        Gate 통과한 RelationalCase tuple. artifact 부재 / 빈 edges → 빈 tuple
        graceful fallback (invariant #68).
    """
    if detection_result is None or getattr(detection_result, "track_name", "") != _FAMILY:
        return ()
    metadata = getattr(detection_result, "metadata", None) or {}
    if not isinstance(metadata, dict):
        return ()
    artifact = metadata.get("relational_edge_artifact")
    if not isinstance(artifact, dict):
        return ()
    edges = artifact.get("edges")
    if not isinstance(edges, list) or not edges:
        return ()

    cases: list[RelationalCase] = []
    edge_ecdf_by_position = _zero_preserving_edge_ecdf(edges)
    positive_metric_count = len(edge_ecdf_by_position)
    for idx, entry in enumerate(edges):
        if not isinstance(entry, dict):
            continue
        case = _build_case_from_edge(
            entry,
            df=df,
            batch_id=batch_id,
            family_ecdf=edge_ecdf_by_position.get(idx, 0.0),
            positive_metric_count=positive_metric_count,
        )
        if case is not None:
            cases.append(case)
    return sort_relational_cases_for_review_surface(cases, df=df)


__all__ = [
    "RELATIONAL_PRODUCT_ROLE",
    "RELATIONAL_REVIEW_SURFACE_NAME",
    "RELATIONAL_REVIEW_SURFACE_POLICY",
    "build_relational_cases",
    "sort_relational_cases_for_review_surface",
]
