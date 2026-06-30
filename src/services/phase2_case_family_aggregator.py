"""Aggregate Phase 2 detector row scores into Phase 1 case overlay inputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.detection.base import DetectionResult
from src.models.phase1_case import Phase1CaseResult
from src.models.phase2_case import Phase2CaseSet, UnsupervisedCase
from src.services.phase2_family_diagnostics import (
    classify_all_family_roles,
    compute_all_family_diagnostics,
    numpy_clip_safe_quantile,
)
from src.services.unsupervised_reason_tags import resolve_tag

_TRACK_TO_FAMILY = {
    "ml_unsupervised": "unsupervised",
    "timeseries": "timeseries",
    "relational": "relational",
    "intercompany": "intercompany",
}

_UNSUPERVISED_SUBDETECTOR = ("VAE-01", "audit_vae_reconstruction")


@dataclass
class Phase2CaseFamilyOverlayInputs:
    family_scores_by_case: dict[str, dict[str, float]] = field(default_factory=dict)
    family_ecdf_by_case: dict[str, dict[str, float]] = field(default_factory=dict)
    family_top_subdetectors_by_case: dict[str, dict[str, list[tuple[str, str]]]] = field(
        default_factory=dict
    )
    family_review_only_by_case: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    family_roles: dict[str, str] = field(default_factory=dict)
    family_q95_thresholds: dict[str, float] = field(default_factory=dict)
    # relational lane sort 보조용 case별 R05/R06 연속 raw score depth (0~1).
    # severity factor (0.6) 복원 후 max(R05, R06). sort tie-break 전용, score 미반영.
    # R05/R06 미hit case 는 dict 에서 누락 → sort_lane 에서 0.0 fallback.
    relational_continuity_depth_by_case: dict[str, float] = field(default_factory=dict)
    # PHASE2 unsupervised (ML02 / VAE) explanation surface. score 입력에 절대 사용 금지.
    # {case_id: {family: [{feature, contrib, tag, label_ko, evidence_type}, ...]}}
    family_explanation_features_by_case: dict[str, dict[str, list[dict[str, Any]]]] = field(
        default_factory=dict
    )
    # PHASE2 unsupervised document-case review context. display-only, score/ranking 입력 금지.
    family_document_context_by_case: dict[str, dict[str, dict[str, Any]]] = field(
        default_factory=dict
    )

    def has_family_signal(self) -> bool:
        return any(bool(scores) for scores in self.family_scores_by_case.values())


def build_phase2_case_family_overlay_inputs(
    df: pd.DataFrame | None,
    detection_results: list[DetectionResult] | None,
    phase1: Phase1CaseResult | None,
    *,
    case_set: Phase2CaseSet | None = None,
) -> Phase2CaseFamilyOverlayInputs:
    """Return case-level Phase 2 family inputs for ``build_phase2_case_overlays``.

    The aggregation is intentionally display/explainability-only. It does not alter
    PHASE1 priority or PHASE1↔PHASE2 queue ordering.
    """

    inputs = Phase2CaseFamilyOverlayInputs()
    if df is None or phase1 is None or not detection_results:
        return inputs

    family_score_series = _family_score_series(detection_results, df.index)
    if not family_score_series:
        return inputs

    family_ecdf_series = {
        family: _zero_preserving_ecdf(scores) for family, scores in family_score_series.items()
    }
    diagnostics = compute_all_family_diagnostics(family_score_series)
    inputs.family_roles = {
        str(family): str(role) for family, role in classify_all_family_roles(diagnostics).items()
    }
    inputs.family_q95_thresholds = {
        family: numpy_clip_safe_quantile(scores, 0.95)
        for family, scores in family_score_series.items()
    }

    label_by_position = {position: label for position, label in enumerate(df.index)}
    positions_by_doc = _positions_by_document(df)
    result_by_family = {
        _TRACK_TO_FAMILY[result.track_name]: result
        for result in detection_results
        if result.track_name in _TRACK_TO_FAMILY
    }
    intercompany_review_only = _intercompany_review_only_sidecar(detection_results, df.index)
    unsupervised_cases_by_label = _unsupervised_cases_by_label(case_set, label_by_position)

    for case in phase1.cases:
        labels = _case_index_labels(case, label_by_position, positions_by_doc)
        if not labels:
            continue
        case_scores: dict[str, float] = {}
        case_ecdfs: dict[str, float] = {}
        case_subdetectors: dict[str, list[tuple[str, str]]] = {}
        for family, scores in family_score_series.items():
            if family == "unsupervised" and unsupervised_cases_by_label:
                document_cases = _unsupervised_cases_for_labels(
                    labels,
                    unsupervised_cases_by_label,
                )
                if document_cases:
                    representative = _representative_unsupervised_case(document_cases)
                    case_scores[family] = float(representative.family_score or 0.0)
                    case_ecdfs[family] = float(representative.family_ecdf or 0.0)
                    case_subdetectors[family] = [_UNSUPERVISED_SUBDETECTOR]
                    explanation = _unsupervised_document_explanation_features(representative)
                    if explanation:
                        inputs.family_explanation_features_by_case[case.case_id] = {
                            "unsupervised": explanation,
                        }
                    inputs.family_document_context_by_case[case.case_id] = {
                        "unsupervised": _unsupervised_document_context(representative),
                    }
                    continue
            selected = scores.reindex(labels).fillna(0.0)
            max_score = float(selected.max()) if not selected.empty else 0.0
            if max_score <= 0:
                continue
            case_scores[family] = max_score
            ecdf_selected = family_ecdf_series[family].reindex(labels).fillna(0.0)
            case_ecdfs[family] = float(ecdf_selected.max()) if not ecdf_selected.empty else 0.0
            subdetectors = _top_subdetectors_for_case(
                result_by_family.get(family),
                labels,
                family=family,
            )
            if subdetectors:
                case_subdetectors[family] = subdetectors
        review_only_meta = _review_only_meta_for_case(intercompany_review_only, labels)
        if case_scores:
            inputs.family_scores_by_case[case.case_id] = case_scores
            inputs.family_ecdf_by_case[case.case_id] = case_ecdfs
        if case_subdetectors:
            inputs.family_top_subdetectors_by_case[case.case_id] = case_subdetectors
        if review_only_meta:
            inputs.family_review_only_by_case[case.case_id] = {"intercompany": review_only_meta}
        if "relational" in case_scores:
            depth = _relational_continuity_depth_for_case(
                result_by_family.get("relational"),
                labels,
            )
            if depth > 0:
                inputs.relational_continuity_depth_by_case[case.case_id] = depth
        # PHASE2 unsupervised explanation surface — score 입력 비허용.
        if "unsupervised" in case_scores and case.case_id not in (
            inputs.family_explanation_features_by_case
        ):
            unsupervised_result = result_by_family.get("unsupervised")
            explanation = _unsupervised_explanation_features_for_case(
                unsupervised_result,
                labels,
                family_score_series.get("unsupervised"),
            )
            if explanation:
                inputs.family_explanation_features_by_case[case.case_id] = {
                    "unsupervised": explanation,
                }
    return inputs


def _unsupervised_cases_by_label(
    case_set: Phase2CaseSet | None,
    label_by_position: dict[int, Any],
) -> dict[Any, list[UnsupervisedCase]]:
    if case_set is None:
        return {}
    cases = tuple(getattr(case_set, "unsupervised_cases", ()) or ())
    by_label: dict[Any, list[UnsupervisedCase]] = {}
    for case in cases:
        if str(getattr(case, "unit_type", "")) != "document":
            continue
        for ref in getattr(case, "row_refs", ()) or ():
            label = label_by_position.get(int(getattr(ref, "row_position", -1)))
            if label is not None:
                by_label.setdefault(label, []).append(case)
    return by_label


def _unsupervised_cases_for_labels(
    labels: list[Any],
    cases_by_label: dict[Any, list[UnsupervisedCase]],
) -> tuple[UnsupervisedCase, ...]:
    selected: dict[str, UnsupervisedCase] = {}
    for label in labels:
        for case in cases_by_label.get(label, ()):
            selected[case.phase2_case_id] = case
    return tuple(selected.values())


def _representative_unsupervised_case(
    cases: tuple[UnsupervisedCase, ...],
) -> UnsupervisedCase:
    return max(
        cases,
        key=lambda case: (
            float(case.family_score or 0.0),
            float(case.family_ecdf or 0.0),
            str(case.phase2_case_id),
        ),
    )


def _unsupervised_document_explanation_features(case: UnsupervisedCase) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    for item in tuple(getattr(case, "top_features", ()) or ()):
        payload = dict(item)
        feature_id = str(payload.get("feature_id") or payload.get("feature") or "").strip()
        if not feature_id:
            continue
        payload["feature_id"] = feature_id
        payload.setdefault("feature", feature_id)
        features.append(payload)
    return features


def _unsupervised_document_context(case: UnsupervisedCase) -> dict[str, Any]:
    features = _unsupervised_document_explanation_features(case)
    return {
        "unit_type": case.unit_type,
        "evidence_row_count": int(case.evidence_row_count),
        "top_score_mean": case.top_score_mean,
        "score_spread": case.score_spread,
        "amount_tail_context": case.amount_tail_context,
        "period_end_context": case.period_end_context,
        "account_rarity_context": case.account_rarity_context,
        "process_rarity_context": case.process_rarity_context,
        "repeated_normal_pressure": case.repeated_normal_pressure,
        "max_score_top_features": [dict(item) for item in case.max_score_top_features],
        "reason_tags": sorted(
            {
                str(feature.get("tag") or "").strip()
                for feature in features
                if str(feature.get("tag") or "").strip()
            }
        ),
    }


_UNSUPERVISED_TOP_K = 3
_UNSUPERVISED_FEATURE_COL_PREFIX = "ML02_top_feature_"
_UNSUPERVISED_CONTRIB_SUFFIX = "_contrib"


# SEVERITY_MAP[code]/5.0 — R05/R06 severity 가 향후 분기될 경우에도 code 단위
# severity factor 로 raw 복원되도록 dict 으로 잠근다. 0 / 음수 fallback 으로
# 0-division 방어.
_RELATIONAL_CONTINUITY_CODES: tuple[str, ...] = ("R05", "R06")


def _relational_continuity_severity_factors() -> dict[str, float]:
    from src.detection.constants import SEVERITY_MAP

    factors: dict[str, float] = {}
    for code in _RELATIONAL_CONTINUITY_CODES:
        sev = SEVERITY_MAP.get(code, 0)
        factor = float(sev) / 5.0 if sev > 0 else 0.0
        factors[code] = factor
    return factors


def _relational_continuity_depth_for_case(
    result: DetectionResult | None,
    labels: list[Any],
) -> float:
    """case label set 의 R05/R06 details 에서 raw score depth (0~1) 추출.

    severity_factor 로 곱해진 details 값을 ``SEVERITY_MAP[code]/5.0`` 로 복원해
    ``max(R05_raw, R06_raw)`` 를 반환한다. R05/R06 severity 가 분기되어도 정합.
    lane sort tie-break 전용이며 score 에 절대 재반영하지 않는다.

    R05/R06 column 미존재·case label 미매칭·factor=0 (severity 미등록) 인 경우
    0.0 fallback.
    """
    if result is None:
        return 0.0
    details = result.details
    if details is None or details.empty or not labels:
        return 0.0
    factors = _relational_continuity_severity_factors()
    depth = 0.0
    for code in _RELATIONAL_CONTINUITY_CODES:
        if code not in details.columns:
            continue
        factor = factors.get(code, 0.0)
        if factor <= 0:
            continue
        try:
            selected = details[code].reindex(labels).fillna(0.0)
        except (KeyError, TypeError):
            continue
        if selected.empty:
            continue
        raw_max = float(selected.max()) / factor
        if raw_max > depth:
            depth = raw_max
    return min(depth, 1.0)


def _unsupervised_explanation_features_for_case(
    result: DetectionResult | None,
    labels: list[Any],
    score_series: pd.Series | None,
) -> list[dict[str, Any]]:
    """case 의 max-score row 에서 ML02 top-K 재구성 기여 피처를 reason tag 로 변환.

    overlay/narrator 표시 전용. score 입력으로 사용하면 안 된다.

    Returns:
        ``[{feature, contrib, tag, label_ko, evidence_type}]`` (최대 ``_UNSUPERVISED_TOP_K`` 개).
        details / score series 가 비었거나 row 매칭이 없으면 빈 리스트.
    """
    if result is None or score_series is None:
        return []
    details = result.details
    if details is None or details.empty:
        return []
    # case 라벨에서 가장 높은 unsupervised score 행을 대표로 선택
    selected_scores = score_series.reindex(labels).dropna()
    if selected_scores.empty:
        return []
    representative_label = selected_scores.idxmax()
    if representative_label not in details.index:
        return []
    row = details.loc[representative_label]
    explanations: list[dict[str, Any]] = []
    for idx in range(1, _UNSUPERVISED_TOP_K + 1):
        feature_col = f"{_UNSUPERVISED_FEATURE_COL_PREFIX}{idx}"
        contrib_col = f"{feature_col}{_UNSUPERVISED_CONTRIB_SUFFIX}"
        if feature_col not in details.columns:
            continue
        feature_value = row.get(feature_col)
        if feature_value is None or (isinstance(feature_value, float) and pd.isna(feature_value)):
            continue
        feature_name = str(feature_value).strip()
        if not feature_name:
            continue
        contrib_raw = row.get(contrib_col) if contrib_col in details.columns else 0.0
        try:
            contrib = float(contrib_raw) if contrib_raw is not None else 0.0
        except (TypeError, ValueError):
            contrib = 0.0
        tag = resolve_tag(feature_name)
        explanations.append(
            {
                "feature": feature_name,
                "contrib": contrib,
                "tag": tag.tag,
                "label_ko": tag.label_ko,
                "evidence_type": tag.evidence_type,
            }
        )
    return explanations


def _family_score_series(
    detection_results: list[DetectionResult],
    index: pd.Index,
) -> dict[str, pd.Series]:
    series_by_family: dict[str, pd.Series] = {}
    for result in detection_results:
        family = _TRACK_TO_FAMILY.get(result.track_name)
        if not family:
            continue
        scores = pd.to_numeric(result.scores, errors="coerce").reindex(index).fillna(0.0)
        if family in series_by_family:
            series_by_family[family] = pd.concat([series_by_family[family], scores], axis=1).max(
                axis=1
            )
        else:
            series_by_family[family] = scores.astype(float)
    return series_by_family


def _zero_preserving_ecdf(scores: pd.Series) -> pd.Series:
    clean = pd.to_numeric(scores, errors="coerce").fillna(0.0).astype(float)
    positive = clean > 0
    ecdf = pd.Series(0.0, index=clean.index, dtype=float)
    if positive.any():
        ecdf.loc[positive] = clean.loc[positive].rank(method="average", pct=True)
    return ecdf


def _positions_by_document(df: pd.DataFrame) -> dict[str, list[int]]:
    if "document_id" not in df.columns:
        return {}
    result: dict[str, list[int]] = {}
    document_ids = df["document_id"].fillna("").astype(str).str.strip().tolist()
    for position, document_id in enumerate(document_ids):
        if document_id:
            result.setdefault(document_id, []).append(position)
    return result


def _case_index_labels(
    case: Any,
    label_by_position: dict[int, Any],
    positions_by_doc: dict[str, list[int]],
) -> list[Any]:
    positions: set[int] = set()
    for hit in getattr(case, "raw_rule_hits", []) or []:
        row_index = getattr(hit, "row_index", None)
        if isinstance(row_index, int):
            positions.add(row_index)
        document_id = str(getattr(hit, "document_id", "") or "").strip()
        positions.update(positions_by_doc.get(document_id, []))
    for document in getattr(case, "documents", []) or []:
        document_id = str(getattr(document, "document_id", "") or "").strip()
        positions.update(positions_by_doc.get(document_id, []))
    return [
        label_by_position[position]
        for position in sorted(positions)
        if position in label_by_position
    ]


def _top_subdetectors_for_case(
    result: DetectionResult | None,
    labels: list[Any],
    *,
    family: str,
) -> list[tuple[str, str]]:
    if result is None:
        return [_UNSUPERVISED_SUBDETECTOR] if family == "unsupervised" else []
    if family == "unsupervised":
        return [_UNSUPERVISED_SUBDETECTOR]
    details = result.details
    if details is None or details.empty:
        return []
    # Why: details column 중 phase2_subdetector_tiers.yaml 에 (family, code) 로 등록된
    #      canonical sub-detector 만 overlay 의 sub_detectors entry 로 노출한다.
    #      등록되지 않은 column 은 family score contributor 로만 동작하고 sub-detector
    #      직렬화에서는 제외해 `evidence_tier=None` 가짜 entry 가 새지 않게 한다.
    #      (2026-05-25 옵션 2 적용: IntercompanyMatcher 의 ic_reciprocal_flow_prob /
    #      ic_amount_prob / ic_unmatched_prob / ic_timing_prob 4개 column 은
    #      phase2_subdetector_tiers.yaml 에 등록됐으므로 본 화이트리스트를 통과하여
    #      sub_detectors entry 로 정상 노출되며, lane sort 의 ic_role_priority 차원
    #      과 phase2_review_band 승격 chain 에 사용된다.)
    registered_codes = _registered_subdetector_codes_for_family(family)
    selected = details.reindex(labels)
    codes: list[tuple[str, str]] = []
    for column in selected.columns:
        code = str(column)
        if registered_codes is not None and code not in registered_codes:
            continue
        numeric = pd.to_numeric(selected[column], errors="coerce").fillna(0.0)
        if float(numeric.max()) > 0:
            codes.append((code, code))
    return codes


def _registered_subdetector_codes_for_family(family: str) -> set[str] | None:
    """Return tier-registered sub-detector codes for ``family`` (None on registry failure).

    Why: tier registry 로드가 실패해도 detector 자체는 동작해야 하므로 None 폴백을
         두고 registry 가용 시에만 화이트리스트 필터를 적용한다.
    """
    try:
        from src.services.subdetector_tiers import get_subdetector_tier_index
    except ImportError:
        return None
    try:
        index = get_subdetector_tier_index()
    except Exception:  # noqa: BLE001
        return None
    return {code for (registered_family, code) in index.keys() if registered_family == family}


def _intercompany_review_only_sidecar(
    detection_results: list[DetectionResult],
    index: pd.Index,
) -> pd.DataFrame:
    for result in detection_results:
        if result.track_name != "intercompany":
            continue
        metadata = result.metadata or {}
        row_sidecar = metadata.get("row_sidecar") if isinstance(metadata, dict) else None
        if not isinstance(row_sidecar, dict):
            continue
        evidence = row_sidecar.get("ic01_evidence_level")
        if not isinstance(evidence, pd.Series):
            continue
        evidence_level = (
            evidence.reindex(index, fill_value="").fillna("").astype(str).str.strip().str.lower()
        )
        reason_source = row_sidecar.get("ic01_review_reason")
        if isinstance(reason_source, pd.Series):
            reasons = reason_source.reindex(index, fill_value="").fillna("").astype(str)
        else:
            reasons = pd.Series("", index=index, dtype="object")
        if result.details is not None and "IC01" in result.details.columns:
            ic01_score = (
                pd.to_numeric(result.details["IC01"], errors="coerce")
                .reindex(index, fill_value=0.0)
                .fillna(0.0)
            )
        else:
            ic01_score = pd.Series(0.0, index=index, dtype=float)
        # review / review_stale 모두 details 점수 0(확정 위반 아님)인 review-only 신호.
        # review_stale는 aggregator에서 Medium floor를 받지만 IC01 details는 0이므로 동일 집계.
        review_only = evidence_level.isin({"review", "review_stale"}) & ic01_score.le(0.0)
        return pd.DataFrame(
            {
                "review_only": review_only,
                "review_reason": reasons,
            },
            index=index,
        )
    return pd.DataFrame(
        {
            "review_only": pd.Series(False, index=index, dtype=bool),
            "review_reason": pd.Series("", index=index, dtype="object"),
        },
        index=index,
    )


def _review_only_meta_for_case(
    review_only_frame: pd.DataFrame,
    labels: list[Any],
) -> dict[str, Any]:
    if review_only_frame.empty or not labels:
        return {}
    selected = review_only_frame.reindex(labels)
    mask = selected["review_only"].fillna(False).astype(bool)
    count = int(mask.sum())
    if count <= 0:
        return {}
    reasons = sorted(
        {
            str(reason).strip()
            for reason in selected.loc[mask, "review_reason"].fillna("").astype(str)
            if str(reason).strip()
        }
    )
    return {
        "review_only_count": count,
        "review_reasons": reasons,
    }
