"""PHASE1 case contracts for PHASE2 precision overlays and PHASE3 prompts.

본 모듈은 PHASE2 standalone 추론이 끝난 뒤 PHASE1 case 와 결합되는
**overlay-only 계약** 을 정의한다.

- ``PHASE2_CASE_FEATURE_COLUMNS`` — case-level ML-safe feature 목록.
  rule_id / theme / composite_sort_score 와 직접 매핑되지 않는 다양성
  메트릭(diversity_count, evidence_type_count, theme_entropy) 과 case
  메타(row_count, total_amount, repeat_*, *_score, has_*) 로 구성된다.
- ``PROVENANCE_ONLY_FIELDS`` — display/debug 전용. PHASE2 의 row matrix
  나 case feature 학습 입력으로 흐르면 ``enforce_phase2_case_feature_firewall``
  이 ``ValueError`` 를 발생시킨다.
- ``Phase2CaseOverlay`` — PHASE2 family score 와 evidence tier 를 case
  단위로 묶는 overlay 객체. PHASE1 ``priority_score`` 를 덮어쓰지 않는다
  (``phase2_adjusted_priority`` 는 표시용 overlay 값일 뿐 ranking key 가
  아니다).

호출 흐름: ``run_phase2_inference`` → standalone detection → row score 산출
→ ``build_phase2_case_family_overlay_inputs`` (post-step) → 본 모듈의
``build_phase2_case_overlays`` 가 overlay 부착. PHASE1 결과가 없으면
overlay 자체가 빈 리스트로 반환되며, PHASE2 standalone score 산출에는
영향이 없다.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from math import log2
from typing import Any

import pandas as pd

from src.models.phase1_case import CaseGroupResult, Phase1CaseResult

PROVENANCE_ONLY_FIELDS = (
    "phase1_case_id",
    "primary_theme",
    "secondary_tags",
    "top_rule_ids",
    "raw_rule_hits",
    "representative_explanation",
    "review_focus",
    "risk_narrative",
    "recommended_audit_actions",
    "rule_evidence_summary",
    "phase1_case_priority",
    "phase1_base_priority",
    "phase1_priority_adjustments",
)

PHASE2_CASE_FEATURE_COLUMNS = (
    "rule_diversity_count",
    "evidence_type_count",
    "theme_entropy",
    "cross_process_flag",
    "cross_user_flag",
    "cross_counterparty_flag",
    "repeat_months",
    "repeat_score",
    "document_count",
    "row_count",
    "total_amount",
    "amount_score",
    "control_score",
    "logic_score",
    "timing_score",
    "behavior_score",
    "has_control_failure",
    "has_high_materiality",
    "has_repeat_pattern",
)

_FORBIDDEN_FEATURE_COLUMNS = frozenset(PROVENANCE_ONLY_FIELDS)
_ALLOWED_FEATURE_DTYPES = frozenset("biufc?")


@dataclass(frozen=True)
class Phase2CaseOverlay:
    """Case-level PHASE2 overlay that preserves the original PHASE1 priority.

    family_contributions / top_family / coverage_breadth_q95 / max_family_ecdf /
    max_evidence_tier / lane_membership / coverage_gap_families 는 family signal
    을 lane·overlay·tie-break 으로 노출하기 위한 explainability 필드다. RRF
    voter 로는 사용하지 않으며 primary PHASE1+VAE 2-way RRF 결과를 덮어쓰지
    않는다. (docs/spec/PHASE2_GOVERNANCE_DESIGN.md 결정 8)
    """

    phase1_case_id: str
    phase2_family_scores: dict[str, float] = field(default_factory=dict)
    phase2_adjusted_priority: float | None = None
    precision_adjustment_reason: str = "phase2_not_applied"
    detector_statuses: list[dict[str, Any]] = field(default_factory=list)
    phase2_inference_contract: dict[str, Any] | None = None
    phase2_training_report_id: str | None = None
    family_contributions: list[dict[str, Any]] = field(default_factory=list)
    family_review_only: dict[str, dict[str, Any]] = field(default_factory=dict)
    top_family: str | None = None
    coverage_breadth_q95: int = 0
    max_family_ecdf: float | None = None
    max_evidence_tier: str | None = None
    lane_membership: list[str] = field(default_factory=list)
    coverage_gap_families: list[str] = field(default_factory=list)
    # D062 (2026-05-21): PHASE2 단독 큐 3등급 + 신호없음. 정렬 키 아님, 표시/필터/KPI 용.
    phase2_review_band: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_phase2_case_feature_frame(phase1: Phase1CaseResult) -> pd.DataFrame:
    """Return ML-safe case features without direct rule/theme identifier leakage."""
    rows = [_case_feature_row(case) for case in phase1.cases]
    if not rows:
        return enforce_phase2_case_feature_firewall(
            pd.DataFrame(columns=PHASE2_CASE_FEATURE_COLUMNS)
        )
    frame = pd.DataFrame(rows)
    frame = frame.set_index("phase1_case_id", drop=True)
    frame.index.name = "phase1_case_id"
    return enforce_phase2_case_feature_firewall(frame)


def enforce_phase2_case_feature_firewall(df: pd.DataFrame) -> pd.DataFrame:
    """Return PHASE2 case ML features after enforcing the allowlist contract."""
    forbidden = sorted(set(df.columns) & _FORBIDDEN_FEATURE_COLUMNS)
    if forbidden:
        raise ValueError(
            "PHASE2 case feature firewall blocked provenance columns: " + ", ".join(forbidden)
        )

    frame = df.reindex(columns=PHASE2_CASE_FEATURE_COLUMNS).copy()
    invalid_types = [
        col
        for col in frame.columns
        if not frame.empty and frame[col].dtype.kind not in _ALLOWED_FEATURE_DTYPES
    ]
    if invalid_types:
        raise TypeError(
            "PHASE2 case feature firewall allows only numeric/boolean features: "
            + ", ".join(invalid_types)
        )
    return frame


def build_phase2_case_provenance(phase1: Phase1CaseResult) -> list[dict[str, Any]]:
    """Return display/debug provenance that must not be used as ML features."""
    return [_case_provenance_row(case) for case in phase1.cases]


def build_phase2_case_overlays(
    phase1: Phase1CaseResult | None,
    *,
    family_scores_by_case: dict[str, dict[str, float]] | None = None,
    family_ecdf_by_case: dict[str, dict[str, float]] | None = None,
    family_top_subdetectors_by_case: dict[str, dict[str, list[tuple[str, str]]]] | None = None,
    family_review_only_by_case: dict[str, dict[str, dict[str, Any]]] | None = None,
    family_roles: dict[str, str] | None = None,
    family_q95_thresholds: dict[str, float] | None = None,
    detector_statuses: list[dict[str, Any]] | None = None,
    phase2_inference_contract: dict[str, Any] | None = None,
    phase2_training_report_id: str | None = None,
    family_explanation_features_by_case: (dict[str, dict[str, list[dict[str, Any]]]] | None) = None,
    family_document_context_by_case: dict[str, dict[str, dict[str, Any]]] | None = None,
    relational_continuity_depth_by_case: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Build neutral overlays keyed by PHASE1 case id.

    이 함수는 PHASE1 `priority_score` 를 덮어쓰지 않는다. 신규 필드
    (family_contributions, top_family, coverage_breadth_q95, max_family_ecdf,
    max_evidence_tier, lane_membership, coverage_gap_families) 는 family signal
    을 lane/overlay/tie-break 으로 노출하기 위한 explainability 용도이며,
    primary PHASE1+VAE 2-way RRF 결과를 변경하지 않는다.
    (docs/spec/PHASE2_GOVERNANCE_DESIGN.md 결정 8 / dev/active/phase2-family-ranking)

    Args:
        family_scores_by_case: ``{case_id: {family: score}}`` — case 의 max family score.
        family_ecdf_by_case: ``{case_id: {family: ecdf}}`` — case 의 family ECDF score.
        family_top_subdetectors_by_case: ``{case_id: {family: [(code, label), ...]}}``
            — case 에 hit 된 sub-detector 목록. evidence_tier lookup 에 사용.
        family_review_only_by_case: ``{case_id: {family: {review_only_count, review_reasons}}}``
            — confirmed score 로 승격하지 않는 review-only 신호 표시 메타.
        family_roles: ``{family: role}`` — Phase B `classify_family_role` 결과.
        family_q95_thresholds: ``{family: q95}`` — coverage_breadth_q95 계산용.
    """
    if phase1 is None:
        return []

    family_scores_by_case = family_scores_by_case or {}
    family_ecdf_by_case = family_ecdf_by_case or {}
    family_top_subdetectors_by_case = family_top_subdetectors_by_case or {}
    family_review_only_by_case = family_review_only_by_case or {}
    family_roles = family_roles or {}
    family_q95_thresholds = family_q95_thresholds or {}
    detector_statuses = detector_statuses or []
    family_explanation_features_by_case = family_explanation_features_by_case or {}
    family_document_context_by_case = family_document_context_by_case or {}
    relational_continuity_depth_by_case = relational_continuity_depth_by_case or {}
    coverage_gap = sorted(family for family, role in family_roles.items() if role == "near-dormant")

    overlays: list[dict[str, Any]] = []
    for case in phase1.cases:
        family_scores = family_scores_by_case.get(case.case_id, {})
        family_ecdf = family_ecdf_by_case.get(case.case_id, {})
        family_subdetectors = family_top_subdetectors_by_case.get(case.case_id, {})
        family_review_only = family_review_only_by_case.get(case.case_id, {})
        contributions = _build_family_contributions(
            family_scores=family_scores,
            family_ecdf=family_ecdf,
            family_subdetectors=family_subdetectors,
            family_review_only=family_review_only,
            family_roles=family_roles,
            relational_continuity_depth=float(
                relational_continuity_depth_by_case.get(case.case_id, 0.0) or 0.0
            ),
        )
        _attach_explanation_features(
            contributions, family_explanation_features_by_case.get(case.case_id)
        )
        _attach_document_context(contributions, family_document_context_by_case.get(case.case_id))
        top_family = _select_top_family(contributions)
        breadth = _coverage_breadth_q95(
            family_scores, family_q95_thresholds, family_roles=family_roles
        )
        max_ecdf = _max_family_ecdf(contributions)
        max_tier = _max_evidence_tier_token(contributions)
        lanes = _lane_membership(contributions, family_roles)
        adjusted = _adjusted_priority(case.priority_score, family_scores)
        reason = "family_score_overlay" if family_scores else "phase2_not_applied"
        # D062: 표시/필터/KPI 용 3등급 분류 (정렬 키 아님).
        review_band = classify_phase2_review_band(
            max_evidence_tier=max_tier,
            coverage_breadth_q95=breadth,
            max_family_ecdf=max_ecdf,
            family_contributions=contributions,
            has_phase2_signal=bool(family_scores),
        )
        overlays.append(
            Phase2CaseOverlay(
                phase1_case_id=case.case_id,
                phase2_family_scores=family_scores,
                phase2_adjusted_priority=adjusted,
                precision_adjustment_reason=reason,
                detector_statuses=detector_statuses,
                phase2_inference_contract=phase2_inference_contract,
                phase2_training_report_id=phase2_training_report_id,
                family_contributions=contributions,
                family_review_only=family_review_only,
                top_family=top_family,
                coverage_breadth_q95=breadth,
                max_family_ecdf=max_ecdf,
                max_evidence_tier=max_tier,
                lane_membership=lanes,
                coverage_gap_families=coverage_gap,
                phase2_review_band=review_band,
            ).to_dict()
        )
    return overlays


# D062 (2026-05-21): PHASE2/통합 3등급 분류 정책.
# `config/phase2_review_band.yaml` 은 **정책 잠금 문서**다. 본 helper 는 yaml 을 직접 로드하지 않고
# 동일 의미를 가진 코드 상수를 사용한다 (D060 5조 5번 정합 — count 보고 임계 재조정 금지).
# yaml 변경 시 본 상수도 동기 변경하며, 두 출처가 동일함을 PR 단위로 보장한다.
# Stage7 측정 스크립트가 family 이름을 `unsupervised` → `ml_unsupervised` 로 alias 변환하므로
# 두 이름 모두 ML-only family 로 인정한다.
_ML_ONLY_FAMILIES: frozenset[str] = frozenset({"unsupervised", "ml_unsupervised"})
_PHASE2_IMMEDIATE_COVERAGE_MIN: int = 2
_PHASE2_REVIEW_COVERAGE_MIN: int = 2
_PHASE2_ML_QUANTILE_ECDF_MIN: float = 0.995


def classify_phase2_review_band(
    *,
    max_evidence_tier: str | None,
    coverage_breadth_q95: int,
    max_family_ecdf: float | None,
    family_contributions: list[dict[str, Any]],
    has_phase2_signal: bool,
) -> str:
    """PHASE2 단독 큐 표시 등급 분류 (D062).

    Returns: "immediate" / "review" / "candidate" / "none".

    정책 정의는 ``config/phase2_review_band.yaml`` 참조. yaml 임계는 도메인 잠금이며
    count 보고 재조정 금지 (D060 5조 5번).
    """

    tier = (max_evidence_tier or "").strip().lower()
    breadth = int(coverage_breadth_q95 or 0)
    ecdf = float(max_family_ecdf or 0.0)

    if tier == "strong" and breadth >= _PHASE2_IMMEDIATE_COVERAGE_MIN:
        return "immediate"

    if tier == "strong" and breadth < _PHASE2_IMMEDIATE_COVERAGE_MIN:
        return "review"
    if tier == "moderate" and breadth >= _PHASE2_REVIEW_COVERAGE_MIN:
        return "review"
    if (
        tier == "ml_quantile"
        and ecdf >= _PHASE2_ML_QUANTILE_ECDF_MIN
        and breadth >= _PHASE2_REVIEW_COVERAGE_MIN
        and _has_ml_only_contribution(family_contributions)
    ):
        return "review"

    if has_phase2_signal:
        return "candidate"
    return "none"


def _has_ml_only_contribution(contributions: list[dict[str, Any]]) -> bool:
    """ML-only family (unsupervised) 가 양수 신호로 기여했는지 확인."""

    for entry in contributions or []:
        family = str(entry.get("family") or "").strip().lower()
        if family not in _ML_ONLY_FAMILIES:
            continue
        try:
            score = float(entry.get("score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        if score > 0:
            return True
    return False


PHASE12_REVIEW_BANDS: tuple[str, ...] = ("immediate", "review", "candidate", "none")


def classify_phase12_review_band(phase1_band: str | None, phase2_band: str | None) -> str:
    """PHASE1+2 통합 큐 표시 등급 분류 (D062).

    정책: "max band 를 취하되 즉시검토만 교집합".

      - 통합 즉시검토: P1 immediate AND P2 immediate
      - 통합 검토대상: 위 외에서 둘 중 하나라도 immediate 이거나 review
      - 통합 후보:     위 외에서 둘 중 하나라도 candidate
      - 통합 신호없음:  양측 모두 none
    """

    p1 = (phase1_band or "none").strip().lower()
    p2 = (phase2_band or "none").strip().lower()

    if p1 == "immediate" and p2 == "immediate":
        return "immediate"
    if "immediate" in (p1, p2) or "review" in (p1, p2):
        return "review"
    if "candidate" in (p1, p2):
        return "candidate"
    return "none"


def _build_family_contributions(
    *,
    family_scores: dict[str, float],
    family_ecdf: dict[str, float],
    family_subdetectors: dict[str, list[tuple[str, str]]],
    family_review_only: dict[str, dict[str, Any]],
    family_roles: dict[str, str],
    relational_continuity_depth: float = 0.0,
) -> list[dict[str, Any]]:
    """family 별 기여 정보를 dict 리스트로 직렬화.

    리턴 항목 형태:
      {family, score, ecdf, role, evidence_tier, evidence_tier_weight, sub_detectors}

    relational family entry 에 한해 ``relational_continuity_depth`` 가 부착되며
    lane sort tie-break 전용이다 (score 재반영 금지).
    """
    from src.services.subdetector_tiers import (
        get_subdetector_tier_index,
    )

    tier_index = get_subdetector_tier_index()
    entries: list[dict[str, Any]] = []
    seen_families: set[str] = set()
    for family, score in family_scores.items():
        seen_families.add(str(family))
        sub_codes = family_subdetectors.get(family, [])
        family_tier_weight = 0
        family_evidence_tier: str | None = None
        sub_detector_entries: list[dict[str, Any]] = []
        for code, label in sub_codes:
            key = (family, code)
            tier_item = tier_index.get(key)
            sub_tier = tier_item.tier if tier_item is not None else None
            sub_weight = tier_item.tier_weight if tier_item is not None else 0
            sub_detector_entries.append(
                {
                    "code": code,
                    "label": label,
                    "evidence_tier": sub_tier,
                    "evidence_tier_weight": sub_weight,
                }
            )
            if sub_weight > family_tier_weight:
                family_tier_weight = sub_weight
                family_evidence_tier = sub_tier
        entry = {
            "family": family,
            "score": float(score) if score is not None else 0.0,
            "ecdf": float(family_ecdf.get(family, 0.0)),
            "role": family_roles.get(family, "unknown"),
            "evidence_tier": family_evidence_tier,
            "evidence_tier_weight": family_tier_weight,
            "sub_detectors": sub_detector_entries,
        }
        if str(family) == "relational" and relational_continuity_depth > 0:
            entry["relational_continuity_depth"] = float(relational_continuity_depth)
        _attach_review_only_meta(entry, family_review_only.get(family))
        entries.append(entry)
    for family, review_meta in family_review_only.items():
        if family in seen_families:
            continue
        count = int(review_meta.get("review_only_count") or 0)
        if count <= 0:
            continue
        entry = {
            "family": family,
            "score": 0.0,
            "ecdf": float(family_ecdf.get(family, 0.0)),
            "role": family_roles.get(family, "unknown"),
            "evidence_tier": None,
            "evidence_tier_weight": 0,
            "sub_detectors": [
                {
                    "code": "IC01",
                    "label": "IC01 review-only",
                    "evidence_tier": None,
                    "evidence_tier_weight": 0,
                    "review_only": True,
                }
            ],
        }
        _attach_review_only_meta(entry, review_meta)
        entries.append(entry)
    # tier weight 우선, 동률은 ecdf 우선으로 정렬 (narrator·dashboard 가독성)
    entries.sort(
        key=lambda item: (item["evidence_tier_weight"], item["ecdf"], item["score"]),
        reverse=True,
    )
    return entries


_UNSUPERVISED_EVIDENCE_TYPE = "statistical_outlier"


def _attach_explanation_features(
    contributions: list[dict[str, Any]],
    explanation_by_family: dict[str, list[dict[str, Any]]] | None,
) -> None:
    """family entry 에 explanation_features + evidence_type 부착.

    현재는 unsupervised family 만 지원. 다른 family 는 no-op.

    가드:
      - 본 메타는 표시 전용. score / threshold / ranking 에 사용 금지.
      - 매칭 entry 가 없으면 no-op (다른 entry 절대 수정 안 함).
      - explanation_features 가 비어있으면 evidence_type 도 부착하지 않음.
    """
    if not explanation_by_family:
        return
    unsupervised_features = explanation_by_family.get("unsupervised")
    if not unsupervised_features:
        return
    for entry in contributions:
        if str(entry.get("family")) != "unsupervised":
            continue
        entry["explanation_features"] = list(unsupervised_features)
        entry["evidence_type"] = _UNSUPERVISED_EVIDENCE_TYPE


_UNSUPERVISED_DOCUMENT_CONTEXT_FIELDS: tuple[str, ...] = (
    "unit_type",
    "evidence_row_count",
    "top_score_mean",
    "score_spread",
    "amount_tail_context",
    "period_end_context",
    "account_rarity_context",
    "process_rarity_context",
    "repeated_normal_pressure",
    "reason_tags",
)


def _attach_document_context(
    contributions: list[dict[str, Any]],
    context_by_family: dict[str, dict[str, Any]] | None,
) -> None:
    """Attach unsupervised document-case context as display-only contribution fields."""
    if not context_by_family:
        return
    unsupervised_context = context_by_family.get("unsupervised")
    if not isinstance(unsupervised_context, dict) or not unsupervised_context:
        return
    context = {
        key: value
        for key, value in unsupervised_context.items()
        if key not in {"document_id", "max_score_row_ref"}
    }
    for entry in contributions:
        if str(entry.get("family")) != "unsupervised":
            continue
        entry["document_context"] = context
        for field_name in _UNSUPERVISED_DOCUMENT_CONTEXT_FIELDS:
            if field_name in context:
                entry[field_name] = context[field_name]
        if "max_score_top_features" in context:
            entry["max_score_top_features"] = context["max_score_top_features"]
        return


def _select_top_family(contributions: list[dict[str, Any]]) -> str | None:
    if not contributions:
        return None
    top = contributions[0]
    if top["score"] <= 0 and top["ecdf"] <= 0:
        return None
    return str(top["family"])


def _attach_review_only_meta(entry: dict[str, Any], review_meta: dict[str, Any] | None) -> None:
    count = int((review_meta or {}).get("review_only_count") or 0)
    reasons = (review_meta or {}).get("review_reasons") or []
    entry["review_only_count"] = count
    entry["review_reasons"] = [str(reason) for reason in reasons if str(reason).strip()]
    entry["review_only"] = count > 0


def _coverage_breadth_q95(
    family_scores: dict[str, float],
    q95_thresholds: dict[str, float],
    family_roles: dict[str, str] | None = None,
) -> int:
    """family 가 자체 q95 임계 이상 진입한 개수.

    - near-dormant family 는 카운트에서 제외 (q95=0 이면 score=0 도 매칭되어 모든
      case 의 breadth 를 부풀리는 문제 방지). docs/spec/PHASE2_GOVERNANCE_DESIGN.md
      결정 8 §8.6 정합.
    - threshold ≤ 0 일 때는 positive guard 적용: 실제 score > 0 인 경우만 카운트.
    """
    if not q95_thresholds:
        return 0
    family_roles = family_roles or {}
    count = 0
    for family, score in family_scores.items():
        if family_roles.get(family) == "near-dormant":
            continue
        if family not in q95_thresholds:
            continue
        threshold = float(q95_thresholds[family])
        score_value = float(score)
        if threshold <= 0:
            if score_value > 0:
                count += 1
        elif score_value >= threshold:
            count += 1
    return count


def _max_family_ecdf(contributions: list[dict[str, Any]]) -> float | None:
    if not contributions:
        return None
    values = [entry["ecdf"] for entry in contributions if entry.get("ecdf") is not None]
    return max(values) if values else None


def _max_evidence_tier_token(contributions: list[dict[str, Any]]) -> str | None:
    if not contributions:
        return None
    best = contributions[0].get("evidence_tier")
    return str(best) if best else None


def _lane_membership(
    contributions: list[dict[str, Any]],
    family_roles: dict[str, str],
) -> list[str]:
    """case 가 노출될 lane 목록.

    rule: family 가 (a) review-only 신호를 갖거나, (b) near-dormant 가 아니고
    raw score>0 또는 ECDF≥0.95 (=q95 진입) 일 때 해당 lane 에 노출.
    near-dormant family 는 원칙적으로 lane 진입하지 않으며 별도 coverage_gap_families
    로 표시하되, review-only 신호는 확인용 lane 에 남긴다.

    ECDF 가 [0,1) 인 정상 case 까지 lane 으로 잡히는 것을 막기 위해 임계를
    0.95 로 고정한다. ECDF q95 는 정의상 0.95 이므로 family 별 thresholds 를
    별도 전달하지 않는다.
    """
    lanes: list[str] = []
    for entry in contributions:
        family = str(entry["family"])
        if int(entry.get("review_only_count") or 0) > 0:
            lanes.append(family)
            continue
        if family_roles.get(family) == "near-dormant":
            continue
        score = float(entry.get("score") or 0.0)
        ecdf = float(entry.get("ecdf") or 0.0)
        if score > 0 or ecdf >= 0.95:
            lanes.append(family)
    return sorted(set(lanes))


def _case_feature_row(case: CaseGroupResult) -> dict[str, Any]:
    evidence_counter = Counter(hit.evidence_type for hit in case.raw_rule_hits)
    business_processes = {
        str(doc.business_process).strip() for doc in case.documents if doc.business_process
    }
    users = {str(doc.created_by).strip() for doc in case.documents if doc.created_by}
    counterparties = {str(doc.counterparty).strip() for doc in case.documents if doc.counterparty}
    return {
        "phase1_case_id": case.case_id,
        "rule_diversity_count": len({hit.rule_id for hit in case.raw_rule_hits}),
        "evidence_type_count": len(set(case.evidence_types)),
        "theme_entropy": _entropy(evidence_counter),
        "cross_process_flag": len(business_processes) > 1,
        "cross_user_flag": len(users) > 1,
        "cross_counterparty_flag": len(counterparties) > 1,
        "repeat_months": int(case.repeat_months),
        "repeat_score": float(case.repeat_score),
        "document_count": int(case.document_count),
        "row_count": int(case.row_count),
        "total_amount": float(case.total_amount),
        "amount_score": float(case.amount_score),
        "control_score": float(case.control_score),
        "logic_score": float(case.logic_score),
        "timing_score": float(case.timing_score),
        "behavior_score": float(case.behavior_score),
        "has_control_failure": bool(case.has_control_failure),
        "has_high_materiality": bool(case.has_high_materiality),
        "has_repeat_pattern": bool(case.has_repeat_pattern),
    }


def _case_provenance_row(case: CaseGroupResult) -> dict[str, Any]:
    return {
        "phase1_case_id": case.case_id,
        "primary_theme": case.primary_theme,
        "secondary_tags": list(case.secondary_tags),
        "top_rule_ids": _top_rule_ids(case),
        "raw_rule_hits": [hit.model_dump() for hit in case.raw_rule_hits],
        "representative_explanation": case.representative_explanation,
        "review_focus": list(case.review_focus),
        "risk_narrative": case.risk_narrative,
        "recommended_audit_actions": list(case.recommended_audit_actions),
        "rule_evidence_summary": list(case.rule_evidence_summary),
        "phase1_case_priority": case.priority_score,
        "phase1_base_priority": case.base_priority_score,
        "phase1_priority_adjustments": {
            "topside_bonus": case.topside_bonus,
            "weak_evidence_bonus": case.weak_evidence_bonus,
            "reasons": list(case.priority_adjustment_reasons),
        },
    }


def _top_rule_ids(case: CaseGroupResult, limit: int = 5) -> list[str]:
    counts = Counter(hit.rule_id for hit in case.raw_rule_hits)
    return [rule_id for rule_id, _ in counts.most_common(limit)]


def _entropy(counter: Counter[str]) -> float:
    total = sum(counter.values())
    if total <= 0:
        return 0.0
    return float(-sum((count / total) * log2(count / total) for count in counter.values()))


def _adjusted_priority(base_priority: float, family_scores: dict[str, float]) -> float | None:
    if not family_scores:
        return None
    mean_score = sum(float(score) for score in family_scores.values()) / len(family_scores)
    return max(0.0, min((float(base_priority) * 0.7) + (mean_score * 0.3), 1.0))


def _feature_columns() -> list[str]:
    return list(PHASE2_CASE_FEATURE_COLUMNS)


# ──────────────────────────────────────────────────────────────────────────────
# Tie-break ladder — primary RRF 동률/near-tie 한정 보조 정렬
#
# 거버넌스 가드 (docs/spec/PHASE2_GOVERNANCE_DESIGN.md 결정 8):
#   Tie-break ladder는 primary RRF의 동률 또는 near-tie 보조 정렬에만 사용하며,
#   primary queue의 기본 순위를 뒤집는 별도 weighted score로 사용하지 않는다.
#
# 동률 정의: primary RRF score 차이 ≤ near_tie_eps (기본 1e-9 — float 정밀도)
# Ladder 비교 방식: lexicographic 만, weight 가중합 금지.
# ──────────────────────────────────────────────────────────────────────────────


_TIER_RANK_FOR_SORT: dict[str, int] = {
    "strong": 3,
    "moderate": 2,
    "weak": 1,
    "ml_quantile": 0,
}


def apply_phase2_tie_break(
    primary_scores: dict[str, float],
    overlays_by_case: dict[str, dict[str, Any]],
    *,
    total_amounts_by_case: dict[str, float] | None = None,
    strong_subdetector_count_by_case: dict[str, int] | None = None,
    near_tie_eps: float = 1e-9,
) -> list[str]:
    """primary RRF score 정렬 + 동률/near-tie 한정 6단 ladder 적용.

    Ladder (lexicographic):
      1. primary_rrf_score                  desc
      2. coverage_breadth_q95               desc
      3. strong_subdetector_count           desc
      4. max_family_ecdf                    desc
      5. max_evidence_tier_weight           desc (strong>moderate>weak>ml_quantile)
      6. abs(total_amount)                  desc

    Args:
        primary_scores: ``{case_id: primary_rrf_score}``.
        overlays_by_case: ``{case_id: Phase2CaseOverlay.to_dict()}``.
        total_amounts_by_case: ``{case_id: total_amount}`` (없으면 0 으로 처리).
        strong_subdetector_count_by_case: ``{case_id: strong_count}`` (없으면 overlay 의
            contributions 에서 직접 count).
        near_tie_eps: primary score 동률 판정 임계. 기본 1e-9.

    Returns:
        case_id 정렬된 list. primary score 차이가 near_tie_eps 초과인 영역은
        primary 순위를 그대로 유지하며, 차이가 임계 이내인 그룹 내부에서만
        ladder 비교를 적용한다.
    """
    total_amounts = total_amounts_by_case or {}
    strong_counts = strong_subdetector_count_by_case or {}
    case_ids = list(primary_scores.keys())

    sort_keys: dict[str, tuple] = {}
    for case_id in case_ids:
        overlay = overlays_by_case.get(case_id, {})
        sort_keys[case_id] = (
            float(primary_scores[case_id]),
            int(overlay.get("coverage_breadth_q95", 0) or 0),
            int(strong_counts.get(case_id, _count_strong_subdetectors(overlay))),
            float(overlay.get("max_family_ecdf") or 0.0),
            _TIER_RANK_FOR_SORT.get(str(overlay.get("max_evidence_tier") or ""), 0),
            abs(float(total_amounts.get(case_id, 0.0))),
        )

    # primary 순위로 먼저 정렬한 뒤 near-tie 그룹 내부에서만 ladder 적용
    by_primary = sorted(case_ids, key=lambda cid: sort_keys[cid][0], reverse=True)
    result: list[str] = []
    group: list[str] = []
    group_anchor: float | None = None
    for case_id in by_primary:
        score = sort_keys[case_id][0]
        if group_anchor is None or abs(score - group_anchor) <= near_tie_eps:
            group.append(case_id)
            if group_anchor is None:
                group_anchor = score
        else:
            result.extend(_sort_within_group(group, sort_keys))
            group = [case_id]
            group_anchor = score
    if group:
        result.extend(_sort_within_group(group, sort_keys))
    return result


def _sort_within_group(group: list[str], sort_keys: dict[str, tuple]) -> list[str]:
    """near-tie 그룹 내부 ladder 비교 — primary 동률 한정."""
    if len(group) <= 1:
        return list(group)
    return sorted(group, key=lambda cid: sort_keys[cid], reverse=True)


def _count_strong_subdetectors(overlay: dict[str, Any]) -> int:
    """case 내부 strong tier sub-detector 개수.

    같은 family 안의 strong sub-detector 가 2개 이상이면 그대로 누적된다
    (`_build_family_contributions` 가 sub_detector 별 evidence_tier 를 채움).
    """
    contributions = overlay.get("family_contributions") or []
    strong = 0
    for entry in contributions:
        for sub in entry.get("sub_detectors") or []:
            if isinstance(sub, dict) and sub.get("evidence_tier") == "strong":
                strong += 1
    return strong
