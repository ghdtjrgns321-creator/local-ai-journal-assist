"""IntercompanyMatcher — 내부거래 매칭 독립 트랙 (WU-07).

Why: L3-03(MVP)은 is_intercompany bool만 flag하여 recall 7%.
     양측 거래 대사(group-level matching)로 미매칭/금액불일치/시차이상 탐지.
     N:M 다대다 매칭 + 이종 통화 방어 적용.

Note: LAYER_WEIGHTS에 의도적 미등록 — 성능 평가 후 가중치 배분 예정 (WU-03 Stacking).
      FraudLayer의 기존 L3-03(IC 전표 존재 감지)은 하위 호환 목적으로 병존 유지.

PHASE2 internal probabilistic reconciliation surface (additive, 2026-05-24):
    `details` 에 `ic_unmatched_prob` / `ic_amount_prob` / `ic_timing_prob` 3개
    0~1 raw probability column 을 추가한다. canonical rule id (IC04 등) 는
    생성하지 않으며 SEVERITY_MAP / RULE_CODES / RULE_DETAIL_METADATA_REGISTRY /
    `_RULE_STYLE_SUB_DETECTORS` 는 변경 없다.
    DetectionResult.scores 는 기존 IC01~03 점수와 신규 prob column 의 row-wise
    max 로 통합되어 PHASE2 family overlay (zero-preserving ECDF + Noisy-OR) 에
    자연 흡수된다. metadata["probabilistic_reconciliation"] 에 contract tier /
    candidate count / capped / warnings / params 만 노출하고 pair queue 산출물은
    공개하지 않는다. Phase 1 rule hit / DataSynth truth / document_id 식별자는
    입력으로 사용하지 않는다.

PHASE2 internal reciprocal flow surface (additive, 2026-05-24):
    `details` 에 `ic_reciprocal_flow_prob` 0~1 raw probability column 을 추가한다.
    single-document structural(rec+pay 동시 + amount symmetry ≥ 0.95) + context
    (period_end/after_hours/round_amount) 가중평균이며 score 통합은 위와 동일.

PHASE2 sub-detector tier registry 등록 (2026-05-25, 옵션 2):
    `phase2_subdetector_tiers.yaml` 에 4개 internal prob column 을 추가 등록
    (ic_reciprocal_flow_prob=strong, ic_amount_prob=moderate,
    ic_unmatched_prob=weak, ic_timing_prob=weak). IntercompanyMatcher 의 score
    합성·output column 자체는 변경 없으며, family overlay 의 lane sort
    `ic_role_priority` secondary dim + `phase2_review_band` 승격 chain 만
    영향받는다. 자세한 계약은 docs/PHASE2_INTERFACE_DESIGN.md §4.3.2 참조.

PHASE2 IC pair artifact (additive, 2026-05-27, S5 Phase A):
    metadata 에 새 key ``ic_pair_artifact`` 를 추가한다. 5종 sanitized
    projection (candidate_pairs / unmatched_rows / mismatch_pairs /
    reciprocal_pairs / coverage) 으로 구성되며, 기존 row 단위 score / details /
    row_sidecar / probabilistic_reconciliation / reciprocal_flow metadata
    는 변경 0건 (회귀 보장 — invariant #52). 도메인 정당화:
        - reciprocal_pairs → ISA 550 ¶A20 (양방향 reconciliation) +
          PCAOB AS 2401 §B7 (intercompany unusual journal entries).
        - mismatch_pairs   → PCAOB AS 2401 .A6 (3) (금액 mismatch 의도성 증거).
        - unmatched_rows   → ISA 550 ¶A20 보조 (no_candidate weak signal).
    truth recall 조정 압력은 사용하지 않는다 (D044 PR 템플릿 -
    feedback_phase1_truth_recall_guard).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from config.settings import AuditSettings
from src.detection.base import BaseDetector, DetectionResult, validate_input
from src.detection.constants import SEVERITY_MAP
from src.detection.intercompany_rules import (
    _classify_rec_pay_prefixes,
    _doc_amount_symmetry,
    _gl_starts_with_any,
    compute_probabilistic_pair_scores,
    compute_reciprocal_flow_scores,
    ic01_unmatched_intercompany,
    ic02_amount_mismatch,
    ic03_timing_gap,
    load_candidate_blocking,
    load_contract_score_caps,
    load_ic_pairs,
    load_matching_weights,
    load_partner_format_policy,
    load_related_party_master,
    load_timing_domain,
    match_ic_groups,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_PROBABILISTIC_COLUMNS: tuple[str, ...] = (
    "ic_unmatched_prob",
    "ic_amount_prob",
    "ic_timing_prob",
)
_RECIPROCAL_FLOW_COLUMN: str = "ic_reciprocal_flow_prob"

_CANDIDATE_PAIR_CAP: int = 200  # operational visibility cap — 디버깅용
_UNMATCHED_ROW_CAP: int = 500
_MISMATCH_PAIR_CAP: int = 500
_RECIPROCAL_PAIR_CAP: int = 500


def _ic_json_safe(value: Any) -> Any:
    """duplicate_pair_features._json_safe 패턴 동일 — index label sanitization."""
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    return str(value)


def _ic_safe_str(value: Any) -> str:
    """document_id / partner 류 식별자 sanitization. None/NaN → 빈 문자열."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _ic_safe_float(value: Any) -> float:
    """금액/점수 sanitization. None/NaN/inf → 0.0."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    if np.isnan(f) or np.isinf(f):
        return 0.0
    return f


@dataclass
class IntercompanyPairArtifact:
    """IC matcher 가 산출하는 sanitized pair-level artifact (S5 Phase A).

    duplicate ``pair_artifact`` 패턴 정합 — JSON 직렬화 가능한 dict/list 만 보유.
    raw 적요 / partner 풀텍스트 / 전체 reference 는 노출하지 않으며, 수치 feature
    와 index label / document_id 식별자만 남긴다. case identity (ic_role) 만
    builder 가 사용한다.
    """

    schema_version: int = 1
    candidate_pairs: list[dict[str, Any]] = field(default_factory=list)
    unmatched_rows: list[dict[str, Any]] = field(default_factory=list)
    mismatch_pairs: list[dict[str, Any]] = field(default_factory=list)
    reciprocal_pairs: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": int(self.schema_version),
            "candidate_pairs": list(self.candidate_pairs),
            "unmatched_rows": list(self.unmatched_rows),
            "mismatch_pairs": list(self.mismatch_pairs),
            "reciprocal_pairs": list(self.reciprocal_pairs),
            "coverage": dict(self.coverage),
        }


def _empty_ic_pair_artifact() -> dict[str, Any]:
    """_empty_result 경로용 — 빈 artifact dict (builder graceful fallback 호환)."""
    return IntercompanyPairArtifact().to_dict()


def build_intercompany_pair_artifact(
    df: pd.DataFrame,
    pair_map: dict[str, str],
    match_df: pd.DataFrame,
    prob_scores: pd.DataFrame,
    prob_summary: dict,
    reciprocal_scores: pd.DataFrame,
    reciprocal_summary: dict,
    rule_results: dict[str, pd.Series],
    sidecar_columns: dict[str, pd.Series],
    settings: AuditSettings,
) -> IntercompanyPairArtifact:
    """IC matcher 5종 sanitized artifact (S5 Phase A).

    도메인 정당화:
        - reciprocal_pairs → ISA 550 ¶A20 (양방향 reconciliation) +
          PCAOB AS 2401 §B7 (intercompany unusual journal entries).
        - mismatch_pairs   → PCAOB AS 2401 .A6 (3) (금액 mismatch 의도성 증거).
        - unmatched_rows   → ISA 550 ¶A20 보조.
        - candidate_pairs  → 운영 가시화 / debug 용.

    truth recall 직접 조정 압력은 사용하지 않는다 (D044 — feedback_phase1_truth_recall_guard).
    """
    artifact = IntercompanyPairArtifact()

    # ── coverage 통계 ────────────────────────────────────────────
    ic_mask = df.get("is_intercompany", pd.Series(False, index=df.index)).fillna(False).astype(bool)
    total_ic_rows = int(ic_mask.sum())

    # ── reciprocal_pairs ───────────────────────────────────────
    artifact.reciprocal_pairs = _extract_reciprocal_pairs(df, pair_map, reciprocal_scores, settings)

    # ── mismatch_pairs (IC02 score > 0) ────────────────────────
    artifact.mismatch_pairs = _extract_mismatch_pairs(df, match_df, rule_results)

    # ── unmatched_rows (IC01 evidence_level truthy) ────────────
    artifact.unmatched_rows = _extract_unmatched_rows(df, sidecar_columns)

    # ── candidate_pairs (probabilistic candidate visibility) ───
    artifact.candidate_pairs = _extract_candidate_pairs(df, prob_scores)

    # ── coverage ──────────────────────────────────────────────
    artifact.coverage = {
        "total_ic_rows": total_ic_rows,
        "candidate_pair_count": len(artifact.candidate_pairs),
        "unmatched_row_count": len(artifact.unmatched_rows),
        "mismatch_pair_count": len(artifact.mismatch_pairs),
        "reciprocal_pair_count": len(artifact.reciprocal_pairs),
    }

    return artifact


def _extract_reciprocal_pairs(
    df: pd.DataFrame,
    pair_map: dict[str, str],
    reciprocal_scores: pd.DataFrame,
    settings: AuditSettings,
) -> list[dict[str, Any]]:
    """단일 document 안 receivable + payable 동시 + amount symmetry ≥ threshold.

    S5 Followup (2026-05-27): entry 에 양쪽 row 정보 보존.
      - ``receivable_indices`` / ``receivable_positions`` — rec_prefix 통과 row 의 label + position
      - ``payable_indices`` / ``payable_positions`` — pay_prefix 통과 row 의 label + position
      - ``row_index`` / ``row_position`` — legacy 호환 (rec 우선, 없으면 pay 의 첫 row)

    Why (Fix High #1): builder 가 receivable + payable 양쪽 row 를 모두 row_refs 로
    채워야 "무엇과 무엇이 reciprocal" 질문에 답할 수 있고, PHASE1 cross-ref 가 반대쪽
    row 의 hit 도 누락 없이 회수할 수 있다 (invariant #58).
    """
    if reciprocal_scores is None or reciprocal_scores.empty:
        return []
    if _RECIPROCAL_FLOW_COLUMN not in reciprocal_scores.columns:
        return []
    if "document_id" not in df.columns or "gl_account" not in df.columns:
        return []
    if not pair_map:
        return []

    # Why: reciprocal_scores 가 0 보다 큰 row 의 doc — structural pass (양쪽 존재 +
    # amount symmetry ≥ amount_similarity_min) 통과한 case 만 score > 0. 추가
    # threshold 는 surface 단에서 가하지 않는다 (ic_pair_artifact 는 case builder
    # 의 입력 surface — Gate 는 Phase B 가 ic_role 별로 별도 판단).
    flow_prob = reciprocal_scores[_RECIPROCAL_FLOW_COLUMN].reindex(df.index, fill_value=0.0)
    strong_mask = flow_prob > 0.0
    if not strong_mask.any():
        return []

    rec_prefixes, pay_prefixes = _classify_rec_pay_prefixes(pair_map)
    if not rec_prefixes or not pay_prefixes:
        return []

    is_rec = _gl_starts_with_any(df["gl_account"], rec_prefixes)
    is_pay = _gl_starts_with_any(df["gl_account"], pay_prefixes)

    debit = pd.to_numeric(df.get("debit_amount", 0.0), errors="coerce").fillna(0.0).abs()
    credit = pd.to_numeric(df.get("credit_amount", 0.0), errors="coerce").fillna(0.0).abs()

    strong_idx = df.index[strong_mask]
    doc_series = df.loc[strong_idx, "document_id"].astype(str)
    doc_series_full = df["document_id"].astype(str)

    # 도메인적으로 단일 document 안의 self-balanced rec+pay → doc 단위 집계.
    entries: list[dict[str, Any]] = []
    seen_docs: set[str] = set()
    for label in strong_idx:
        doc_id = _ic_safe_str(doc_series.loc[label]) if label in doc_series.index else ""
        if not doc_id or doc_id in seen_docs:
            continue
        doc_mask = doc_series_full == doc_id
        rec_mask = doc_mask & is_rec
        pay_mask = doc_mask & is_pay
        rec_amt = float(debit.loc[rec_mask].sum())
        pay_amt = float(credit.loc[pay_mask].sum())
        if rec_amt <= 0 or pay_amt <= 0:
            continue
        # Why: 양쪽 row 정보 보존 — receivable/payable 각각 label + position list.
        # position 은 np.flatnonzero 로 0-based row position 산출 (MultiIndex 안전).
        rec_labels = list(df.index[rec_mask])
        pay_labels = list(df.index[pay_mask])
        rec_positions = [int(p) for p in np.flatnonzero(rec_mask.to_numpy())]
        pay_positions = [int(p) for p in np.flatnonzero(pay_mask.to_numpy())]
        if not rec_labels or not pay_labels:
            # structural pass 가 boolean 마스크 단위라 양쪽 row 가 둘 다 있어야 의미.
            continue
        symmetry = float(
            _doc_amount_symmetry(
                pd.Series({doc_id: rec_amt}),
                pd.Series({doc_id: pay_amt}),
            ).iloc[0]
        )
        # legacy compat: 단일 representative row — rec 우선, 없으면 pay.
        legacy_label = rec_labels[0] if rec_labels else pay_labels[0]
        legacy_position = rec_positions[0] if rec_positions else pay_positions[0]
        entries.append(
            {
                "document_id": doc_id,
                "receivable_indices": [_ic_json_safe(label) for label in rec_labels],
                "receivable_positions": rec_positions,
                "payable_indices": [_ic_json_safe(label) for label in pay_labels],
                "payable_positions": pay_positions,
                "receivable_amount": _ic_safe_float(rec_amt),
                "payable_amount": _ic_safe_float(pay_amt),
                "amount_symmetry": _ic_safe_float(symmetry),
                # legacy compat — representative row 1개 (구 호출자 보호).
                "row_index": _ic_json_safe(legacy_label),
                "row_position": int(legacy_position),
            }
        )
        seen_docs.add(doc_id)
        if len(entries) >= _RECIPROCAL_PAIR_CAP:
            break
    return entries


def _extract_mismatch_pairs(
    df: pd.DataFrame,
    match_df: pd.DataFrame,
    rule_results: dict[str, pd.Series],
) -> list[dict[str, Any]]:
    """IC02 score > 0 인 row → mismatch_pairs entry. PCAOB AS 2401 .A6 (3).

    S5 Followup (2026-05-27): entry 에 ``left_position`` / ``right_position`` 추가
    (invariant #59). builder 가 MultiIndex/tuple label 환경에서도 position 직접
    사용으로 안전한 lookup 수행.
    """
    ic02 = rule_results.get("IC02")
    if ic02 is None or ic02.empty:
        return []
    severity = ic02.reindex(df.index, fill_value=0.0)
    target_idx = severity.index[severity > 0]
    if len(target_idx) == 0:
        return []
    if match_df is None or match_df.empty or "diff_ratio" not in match_df.columns:
        return []

    debit = pd.to_numeric(df.get("debit_amount", 0.0), errors="coerce").fillna(0.0).abs()
    credit = pd.to_numeric(df.get("credit_amount", 0.0), errors="coerce").fillna(0.0).abs()
    # Why: artifact entry 에 row_position 저장 — builder 가 df.iloc[position] 직접
    # 사용 → tuple/MultiIndex label 환경에서 label-based lookup 회피.
    severity_mask = severity > 0
    target_positions = np.flatnonzero(severity_mask.to_numpy())
    # row 자체 금액 — left amount 로 사용. right amount 는 counterpart 추정 불가하므로
    # diff_ratio 와 row amount 로 역산.
    entries: list[dict[str, Any]] = []
    for label, position in zip(target_idx, target_positions, strict=False):
        amount_a = float(max(debit.loc[label], credit.loc[label]))
        diff_ratio_row = (
            float(match_df.loc[label, "diff_ratio"]) if label in match_df.index else 0.0
        )
        # diff_ratio = |a - b| / max(|a|,|b|) → 작은 쪽 추정.
        # ratio = min/max ∈ [0,1] — diff_ratio 가 클수록 ratio 작음.
        ratio = max(0.0, 1.0 - diff_ratio_row)
        amount_b = amount_a * ratio if ratio > 0 else 0.0
        severity_value = _ic_safe_float(float(severity.loc[label]))
        entries.append(
            {
                "left_index": _ic_json_safe(label),
                "right_index": _ic_json_safe(label),  # counterpart row 식별 불가 — self 표기
                "left_position": int(position),
                "right_position": int(position),  # counterpart row 식별 불가 — self 표기
                "amount_a": _ic_safe_float(amount_a),
                "amount_b": _ic_safe_float(amount_b),
                "ratio": _ic_safe_float(ratio),
                "mismatch_severity": severity_value,
            }
        )
        if len(entries) >= _MISMATCH_PAIR_CAP:
            break
    return entries


def _extract_unmatched_rows(
    df: pd.DataFrame,
    sidecar_columns: dict[str, pd.Series],
) -> list[dict[str, Any]]:
    """IC01 evidence_level 가 truthy 인 row → unmatched_rows entry. ISA 550 ¶A20.

    S5 Followup (2026-05-27): entry 에 ``row_position`` 추가 (invariant #59).
    """
    evidence = sidecar_columns.get("ic01_evidence_level")
    if evidence is None or evidence.empty:
        return []
    evidence = evidence.reindex(df.index, fill_value="").astype(str)
    review_reason_series = sidecar_columns.get("ic01_review_reason")
    if review_reason_series is None:
        review_reason_series = pd.Series("", index=df.index, dtype="object")
    review_reason_series = review_reason_series.reindex(df.index, fill_value="").astype(str)

    target_mask = evidence != ""
    if not target_mask.any():
        return []

    doc_series = (
        df["document_id"].astype(str)
        if "document_id" in df.columns
        else pd.Series("", index=df.index, dtype="object")
    )
    # Why: position 동시 산출 — MultiIndex/tuple label 환경에서도 안전.
    target_labels = df.index[target_mask]
    target_positions = np.flatnonzero(target_mask.to_numpy())
    entries: list[dict[str, Any]] = []
    for label, position in zip(target_labels, target_positions, strict=False):
        entries.append(
            {
                "row_index": _ic_json_safe(label),
                "row_position": int(position),
                "document_id": _ic_safe_str(doc_series.loc[label]),
                "evidence_level": str(evidence.loc[label]),
                "review_reason": str(review_reason_series.loc[label]),
            }
        )
        if len(entries) >= _UNMATCHED_ROW_CAP:
            break
    return entries


def _extract_candidate_pairs(
    df: pd.DataFrame,
    prob_scores: pd.DataFrame,
) -> list[dict[str, Any]]:
    """probabilistic candidate row 의 sanitized projection (운영 가시화).

    S5 Followup (2026-05-27): entry 에 ``left_position`` / ``right_position`` 추가
    (invariant #59).
    """
    if prob_scores is None or prob_scores.empty:
        return []
    amount_col = (
        prob_scores.get("ic_amount_prob")
        if "ic_amount_prob" in prob_scores.columns
        else pd.Series(0.0, index=df.index)
    )
    timing_col = (
        prob_scores.get("ic_timing_prob")
        if "ic_timing_prob" in prob_scores.columns
        else pd.Series(0.0, index=df.index)
    )
    amount_col = amount_col.reindex(df.index, fill_value=0.0)
    timing_col = timing_col.reindex(df.index, fill_value=0.0)
    score = pd.concat([amount_col, timing_col], axis=1).max(axis=1)
    target_mask = score > 0
    target_idx = score.index[target_mask]
    if len(target_idx) == 0:
        return []
    # Why: position 동시 산출 — MultiIndex/tuple label 환경에서도 안전.
    target_positions = np.flatnonzero(target_mask.to_numpy())

    entries: list[dict[str, Any]] = []
    for label, position in zip(target_idx, target_positions, strict=False):
        entries.append(
            {
                "left_index": _ic_json_safe(label),
                "right_index": _ic_json_safe(label),  # counterpart 식별자 불가 → self
                "left_position": int(position),
                "right_position": int(position),  # counterpart 식별자 불가 → self
                "score": _ic_safe_float(float(score.loc[label])),
                "components": {
                    "amount_prob": _ic_safe_float(float(amount_col.loc[label])),
                    "timing_prob": _ic_safe_float(float(timing_col.loc[label])),
                },
            }
        )
        if len(entries) >= _CANDIDATE_PAIR_CAP:
            break
    return entries


class IntercompanyMatcher(BaseDetector):
    """내부거래 매칭 탐지기. DuplicateDetector _build_registry 패턴 준수."""

    def __init__(
        self,
        settings: AuditSettings | None = None,
        *,
        audit_rules: dict | None = None,
    ) -> None:
        super().__init__(settings)
        self._audit_rules = audit_rules or {}
        self._pair_map = load_ic_pairs(self._audit_rules)

    @property
    def track_name(self) -> str:
        return "intercompany"

    def detect(self, df: pd.DataFrame) -> DetectionResult:
        start = time.perf_counter()
        warnings: list[str] = []

        required = [
            "gl_account",
            "debit_amount",
            "credit_amount",
        ]
        missing = validate_input(df, required)
        if missing:
            warnings.append(f"필수 컬럼 누락: {missing}")
            return self._empty_result(df, warnings, time.perf_counter() - start)

        if not self._pair_map:
            warnings.append("intercompany.pairs 설정 비어있음 — IC 매칭 스킵")
            return self._empty_result(df, warnings, time.perf_counter() - start)

        work_df = self._ensure_intercompany_indicator(df)

        ic_count = work_df["is_intercompany"].fillna(False).sum()
        if ic_count < self._settings.ic_min_ic_rows:
            warnings.append(
                f"IC 행 {ic_count}건 < 최소 {self._settings.ic_min_ic_rows}건 — 스킵",
            )
            return self._empty_result(df, warnings, time.perf_counter() - start)

        # Why: match_ic_groups를 한 번만 호출하여 3개 서브룰에 공유 (O(n) → O(3n) 방지)
        match_df = match_ic_groups(
            work_df,
            self._pair_map,
            self._settings.ic_amount_tolerance,
            self._settings.ic_cross_currency_ratio_threshold,
        )

        rule_results: dict[str, pd.Series] = {}
        sidecar_columns: dict[str, pd.Series] = {}
        skipped: list[str] = []

        for rule_id, func, kwargs in self._build_registry(match_df):
            try:
                result = func(work_df, **kwargs)
                if rule_id == "IC01":
                    # IC01 returns (score, evidence_level, review_reason)
                    score_series, evidence_level, review_reason = result
                    rule_results[rule_id] = score_series
                    sidecar_columns["ic01_evidence_level"] = evidence_level
                    sidecar_columns["ic01_review_reason"] = review_reason
                else:
                    rule_results[rule_id] = result
            except Exception as exc:
                skipped.append(rule_id)
                warnings.append(f"{rule_id} 실행 실패: {exc}")
                self._logger.warning("%s 실행 실패: %s", rule_id, exc)

        prob_scores, prob_summary = self._compute_probabilistic_scores(work_df)
        warnings.extend(prob_summary.get("warnings", []))

        reciprocal_scores, reciprocal_summary = self._compute_reciprocal_flow_scores(work_df)
        warnings.extend(reciprocal_summary.get("warnings", []))

        elapsed = time.perf_counter() - start
        return self._build_result(
            work_df,
            rule_results,
            sidecar_columns,
            prob_scores,
            prob_summary,
            reciprocal_scores,
            reciprocal_summary,
            skipped,
            warnings,
            elapsed,
            match_df=match_df,
        )

    def _ensure_intercompany_indicator(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ensure ``is_intercompany`` from configured GL prefixes without mutating input."""
        gl_str = df["gl_account"].fillna("").astype(str).str.strip()
        prefixes = tuple(sorted(self._pair_map))
        inferred = gl_str.str.startswith(prefixes) if prefixes else pd.Series(False, index=df.index)
        if "is_intercompany" not in df.columns:
            work_df = df.copy()
            work_df["is_intercompany"] = inferred
            return work_df

        existing = df["is_intercompany"].fillna(False).astype(bool)
        combined = existing | inferred
        if combined.equals(existing):
            return df
        work_df = df.copy()
        work_df["is_intercompany"] = combined
        return work_df

    def _build_registry(
        self,
        match_df: pd.DataFrame,
    ) -> list[tuple[str, Callable, dict]]:
        """서브룰 레지스트리 — 사전 계산된 match_df를 공유."""
        s = self._settings
        related_party_master: set[str] | None = None
        if getattr(s, "ic_use_related_party_master", True):
            related_party_master = load_related_party_master(self._audit_rules)
        partner_format_policy = load_partner_format_policy(self._audit_rules)

        return [
            (
                "IC01",
                ic01_unmatched_intercompany,
                {
                    "match_df": match_df,
                    "related_party_master": related_party_master,
                    "partner_format_policy": partner_format_policy,
                },
            ),
            (
                "IC02",
                ic02_amount_mismatch,
                {
                    "match_df": match_df,
                    "amount_tolerance": s.ic_amount_tolerance,
                    "max_diff_ratio": s.ic_max_diff_ratio,
                },
            ),
            (
                "IC03",
                ic03_timing_gap,
                {
                    "match_df": match_df,
                    "date_window_days": s.ic_date_window_days,
                    "max_day_diff": s.ic_max_day_diff,
                },
            ),
        ]

    def _compute_probabilistic_scores(
        self,
        df: pd.DataFrame,
    ) -> tuple[pd.DataFrame, dict]:
        """Run probabilistic reconciliation; never raise — return summary on failure."""
        try:
            weights = load_matching_weights(self._audit_rules, self._settings)
            blocking = load_candidate_blocking(self._audit_rules, self._settings)
            caps = load_contract_score_caps(self._audit_rules, self._settings)
            timing_domain = load_timing_domain(self._audit_rules, self._settings)
            return compute_probabilistic_pair_scores(
                df,
                self._pair_map,
                weights=weights,
                blocking=blocking,
                max_day_diff=self._settings.ic_max_day_diff,
                caps=caps,
                timing_domain=timing_domain,
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("probabilistic reconciliation 실행 실패: %s", exc)
            empty = pd.DataFrame(
                {
                    col: pd.Series(0.0, index=df.index, dtype=float)
                    for col in _PROBABILISTIC_COLUMNS
                },
                index=df.index,
            )
            return empty, {
                "contract_tier": "L3_insufficient",
                "missing_reasons": ["probabilistic_runtime_error"],
                "pair_candidate_count": 0,
                "capped": False,
                "warnings": [f"probabilistic_runtime_error: {exc}"],
            }

    def _compute_reciprocal_flow_scores(
        self,
        df: pd.DataFrame,
    ) -> tuple[pd.DataFrame, dict]:
        """Run single-document reciprocal IC flow scoring; never raise."""
        try:
            return compute_reciprocal_flow_scores(
                df,
                self._pair_map,
                settings=self._settings,
                audit_rules=self._audit_rules,
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("reciprocal flow scoring 실행 실패: %s", exc)
            empty = pd.DataFrame(
                {_RECIPROCAL_FLOW_COLUMN: pd.Series(0.0, index=df.index, dtype=float)},
                index=df.index,
            )
            return empty, {
                "evaluated_ic_rows": 0,
                "structural_candidate_docs": 0,
                "context_boost_docs": 0,
                "score_q95": 0.0,
                "score_q99": 0.0,
                "score_max": 0.0,
                "warnings": [f"reciprocal_runtime_error: {exc}"],
            }

    def _build_result(
        self,
        df: pd.DataFrame,
        rule_results: dict[str, pd.Series],
        sidecar_columns: dict[str, pd.Series],
        prob_scores: pd.DataFrame,
        prob_summary: dict,
        reciprocal_scores: pd.DataFrame,
        reciprocal_summary: dict,
        skipped: list[str],
        warnings: list[str],
        elapsed: float,
        *,
        match_df: pd.DataFrame | None = None,
    ) -> DetectionResult:
        """룰 점수 + probabilistic + reciprocal_flow prob → scores/details/RuleFlag 통합."""
        if not rule_results and prob_scores.empty and reciprocal_scores.empty:
            return self._empty_result(df, warnings, elapsed)

        # Why: severity/5.0 정규화 (DuplicateDetector 패턴 동일)
        # details 는 numeric rule-score matrix 계약 (metrics/case_builder 가 > 0 비교).
        # 문자열 sidecar 는 metadata["row_sidecar"] 로 분리 — 평가/리포트 read 전용.
        details = pd.DataFrame(index=df.index)
        for rule_id, raw_scores in rule_results.items():
            severity_factor = SEVERITY_MAP[rule_id] / 5.0
            details[rule_id] = raw_scores.reindex(df.index, fill_value=0.0) * severity_factor

        # PHASE2 internal probabilistic columns — severity normalization 미적용 (raw 0~1)
        for col in _PROBABILISTIC_COLUMNS:
            if col in prob_scores.columns:
                details[col] = (
                    prob_scores[col]
                    .reindex(df.index, fill_value=0.0)
                    .clip(lower=0.0, upper=1.0)
                    .astype(float)
                )

        # PHASE2 internal reciprocal flow column — severity normalization 미적용 (raw 0~1)
        if _RECIPROCAL_FLOW_COLUMN in reciprocal_scores.columns:
            details[_RECIPROCAL_FLOW_COLUMN] = (
                reciprocal_scores[_RECIPROCAL_FLOW_COLUMN]
                .reindex(df.index, fill_value=0.0)
                .clip(lower=0.0, upper=1.0)
                .astype(float)
            )

        # IC01 evidence_level / review_reason sidecar — metadata 에 보관
        row_sidecar: dict[str, pd.Series] = {
            col: series.reindex(df.index, fill_value="").astype("object")
            for col, series in sidecar_columns.items()
        }

        scores = details.max(axis=1).fillna(0.0)
        flagged_indices = scores[scores > 0].index.tolist()

        # RuleFlag 는 canonical rule id (IC01~03) 만 — probabilistic / reciprocal column 미포함.
        rule_flags = [
            self._create_rule_flag(
                rule_id=rule_id,
                flagged_count=int((raw_scores > 0).sum()),
                total_count=len(df),
            )
            for rule_id, raw_scores in rule_results.items()
        ]

        # S5 Phase A — sanitized pair artifact (invariant #52: 기존 metadata 회귀 0건)
        artifact_match_df = match_df if match_df is not None else self._safe_match_df(df)
        ic_pair_artifact = build_intercompany_pair_artifact(
            df,
            self._pair_map,
            artifact_match_df,
            prob_scores,
            prob_summary,
            reciprocal_scores,
            reciprocal_summary,
            rule_results,
            sidecar_columns,
            self._settings,
        )

        return self._make_result(
            flagged_indices=flagged_indices,
            scores=scores,
            rule_flags=rule_flags,
            details=details,
            metadata={
                "elapsed": elapsed,
                "skipped_rules": skipped,
                "row_sidecar": row_sidecar,
                "probabilistic_reconciliation": prob_summary,
                "reciprocal_flow": reciprocal_summary,
                "ic_pair_artifact": ic_pair_artifact.to_dict(),
            },
            warnings=warnings,
        )

    def _safe_match_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """match_df 재계산 — _build_result 가 match_df 인자를 직접 받지 않으므로
        artifact 빌더용으로 한번 더 호출. detect() 의 match_df 결과와 동일.
        실패 시 빈 df 로 graceful fallback (artifact 의 mismatch_pairs 비어 있게).
        """
        try:
            return match_ic_groups(
                df,
                self._pair_map,
                self._settings.ic_amount_tolerance,
                self._settings.ic_cross_currency_ratio_threshold,
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("artifact match_df 재계산 실패: %s", exc)
            return pd.DataFrame(index=df.index)

    def _empty_result(
        self,
        df: pd.DataFrame,
        warnings: list[str],
        elapsed: float,
    ) -> DetectionResult:
        return self._make_result(
            flagged_indices=[],
            scores=pd.Series(0.0, index=df.index),
            rule_flags=[],
            details=pd.DataFrame(index=df.index),
            metadata={
                "elapsed": elapsed,
                "skipped_rules": [],
                "ic_pair_artifact": _empty_ic_pair_artifact(),
            },
            warnings=warnings,
        )
