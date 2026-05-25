"""PHASE2 family score 분포 진단 metric — Layer 0.

family ranking role 자동 판정의 입력 metric 3종을 계산한다.

  row_nonzero_rate    — score > 0 인 행 / 전체 행. near-dormant 진단.
  rank_resolution     — unique rank 수 / 전체 행. coarse 진단.
  top_tail_resolution — q95+ tail 내부에서 largest tie block / top_tail_count
                         의 보수(1 - …). tail 변별력 진단.

본 metric 은 training 시점에 측정하고 `training_report.json` 의
`family_diagnostics` 에 pin 한다. inference 마다 재계산하면 family role 이
진동하므로 hysteresis 는 재학습 trigger 로만 통제한다.
(docs/PHASE2_GOVERNANCE_DESIGN.md §6.2 trigger matrix 정합)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

import numpy as np
import pandas as pd

FamilyRole = Literal["active-ranker", "coarse-booster", "near-dormant", "tail-only-fallback"]


@dataclass(frozen=True)
class FamilyDiagnostics:
    """단일 family score 분포 진단 결과."""

    row_nonzero_rate: float
    rank_resolution: float
    top_tail_resolution: float
    row_count: int
    nonzero_count: int

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)


def compute_row_nonzero_rate(scores: pd.Series) -> tuple[float, int]:
    """score > 0 인 행 비율 + 절대값.

    NaN 은 0 으로 본다(family score 미산출 = 0 으로 일관).
    """
    if scores.empty:
        return 0.0, 0
    clean = scores.fillna(0.0).astype(float)
    nonzero = int((clean > 0).sum())
    return float(nonzero / len(clean)), nonzero


def compute_rank_resolution(scores: pd.Series) -> float:
    """unique rank 수 / 전체 행 수.

    이산 점수(0.4/0.8 등)는 rank tie 블록이 커서 1 에 한참 못 미친다.
    1.0 에 가까울수록 RRF voter 로 적합. 0.01 미만은 coarse 로 판정.
    """
    if scores.empty:
        return 0.0
    clean = scores.fillna(0.0).astype(float)
    rank = clean.rank(method="min", ascending=False)
    unique_count = int(rank.nunique())
    return float(unique_count / len(clean))


def compute_top_tail_resolution(scores: pd.Series, q: float = 0.95) -> float:
    """q95+ tail 내부 분해능.

    1 - (largest_tie_block_at_or_above_q95 / top_tail_count) 형태.
    tail 자체가 한 점수로 묶이면 0, 모두 distinct 면 1 에 근접.
    near-dormant family(tail 자체가 비어 있음)는 0 반환.

    분모를 전체 n 이 아니라 tail count 로 잡는 이유: 희소 family 의 작은
    tail 도 internal 분해능을 정확히 평가하기 위함.
    (dev/active/phase2-family-ranking/phase2-family-ranking-plan.md §L0)
    """
    if scores.empty:
        return 0.0
    clean_arr = np.asarray(scores.fillna(0.0).astype(float).to_numpy(), dtype=float)
    threshold = float(np.quantile(clean_arr, q))
    tail_arr = clean_arr[clean_arr >= threshold]
    if tail_arr.size == 0:
        return 0.0
    if threshold <= 0.0:
        # tail 이 전부 0 이면 변별력 0 — positive 만 남겨서 다시 평가
        tail_arr = clean_arr[clean_arr > 0]
        if tail_arr.size == 0:
            return 0.0
    _unique, counts = np.unique(tail_arr, return_counts=True)
    largest_block = int(counts.max())
    return float(1.0 - largest_block / tail_arr.size)


def compute_family_diagnostics(scores: pd.Series, q: float = 0.95) -> FamilyDiagnostics:
    """단일 family score 에 대해 3 metric 일괄 계산."""
    rate, nonzero = compute_row_nonzero_rate(scores)
    return FamilyDiagnostics(
        row_nonzero_rate=rate,
        rank_resolution=compute_rank_resolution(scores),
        top_tail_resolution=compute_top_tail_resolution(scores, q=q),
        row_count=len(scores),
        nonzero_count=nonzero,
    )


def compute_all_family_diagnostics(
    family_scores: dict[str, pd.Series],
    q: float = 0.95,
) -> dict[str, FamilyDiagnostics]:
    """모든 family 에 대해 진단 일괄 계산."""
    return {
        family: compute_family_diagnostics(scores, q=q) for family, scores in family_scores.items()
    }


def classify_family_role(diagnostics: FamilyDiagnostics) -> FamilyRole:
    """L0 metric 기반 family role 자동 판정.

    임계값:
      row_nonzero_rate < 0.001                       → near-dormant
      rank_resolution < 0.01                          → coarse-booster
      top_tail_resolution < 0.5                       → coarse-booster
      top_tail_resolution < 0.2                       → tail-only-fallback (booster 보다 더 약함)
      else                                            → active-ranker

    임계값 변경은 `docs/PHASE2_GOVERNANCE_DESIGN.md` 결정 8 lock 후 PR 의무.
    """
    if diagnostics.row_nonzero_rate < 0.001:
        return "near-dormant"
    if diagnostics.top_tail_resolution < 0.2:
        return "tail-only-fallback"
    if diagnostics.rank_resolution < 0.01 or diagnostics.top_tail_resolution < 0.5:
        return "coarse-booster"
    return "active-ranker"


def classify_all_family_roles(
    diagnostics_by_family: dict[str, FamilyDiagnostics],
) -> dict[str, FamilyRole]:
    """모든 family role 일괄 판정. inference 시 active_set / booster_set 분리에 사용."""
    return {family: classify_family_role(diag) for family, diag in diagnostics_by_family.items()}


def serialize_diagnostics(
    diagnostics_by_family: dict[str, FamilyDiagnostics],
) -> dict[str, dict[str, float | int]]:
    """training_report.json 에 pin 할 JSON-safe payload."""
    return {family: diag.to_dict() for family, diag in diagnostics_by_family.items()}


def diagnostics_from_payload(
    payload: dict[str, dict[str, float | int]],
) -> dict[str, FamilyDiagnostics]:
    """training_report.json 의 family_diagnostics 를 dataclass 로 복원."""
    result: dict[str, FamilyDiagnostics] = {}
    for family, fields in payload.items():
        result[family] = FamilyDiagnostics(
            row_nonzero_rate=float(fields["row_nonzero_rate"]),
            rank_resolution=float(fields["rank_resolution"]),
            top_tail_resolution=float(fields["top_tail_resolution"]),
            row_count=int(fields["row_count"]),
            nonzero_count=int(fields["nonzero_count"]),
        )
    return result


def numpy_clip_safe_quantile(scores: pd.Series, q: float) -> float:
    """edge-case safe quantile — empty series 는 0 반환."""
    if scores.empty:
        return 0.0
    clean = scores.fillna(0.0).astype(float)
    return float(np.clip(clean.quantile(q), 0.0, np.inf))


# ──────────────────────────────────────────────────────────────────────────────
# Training report integration
# ──────────────────────────────────────────────────────────────────────────────

METADATA_KEY = "family_diagnostics"


def attach_family_diagnostics_to_metadata(
    metadata: dict[str, object],
    family_scores: dict[str, pd.Series],
    *,
    q: float = 0.95,
) -> dict[str, dict[str, float | int]]:
    """family scores 로 진단 + role 산출 → metadata 사전에 저장.

    Phase2TrainingReport.metadata 사전을 받아 in-place 로 갱신한다.
    실제 training service 호출은 Phase C dry-run / Phase E production cutover 에서 수행한다.

    Returns:
        직렬화된 family_diagnostics payload (metadata 에 저장된 동일 객체).
    """
    diagnostics = compute_all_family_diagnostics(family_scores, q=q)
    payload = serialize_diagnostics(diagnostics)
    roles = classify_all_family_roles(diagnostics)
    metadata[METADATA_KEY] = {
        "schema_version": 1,
        "q": q,
        "diagnostics": payload,
        "roles": dict(roles),
    }
    return payload


def read_family_diagnostics_from_metadata(
    metadata: dict[str, object],
) -> tuple[dict[str, FamilyDiagnostics], dict[str, FamilyRole]] | None:
    """metadata 에 pin 된 family_diagnostics 를 dataclass + role dict 로 복원.

    pinned payload 가 없으면 None 반환 (inference 시 active-set 결정 불가 → fallback 정책 적용).
    """
    raw = metadata.get(METADATA_KEY)
    if not isinstance(raw, dict):
        return None
    diagnostics_payload = raw.get("diagnostics") or {}
    roles_payload = raw.get("roles") or {}
    if not isinstance(diagnostics_payload, dict) or not isinstance(roles_payload, dict):
        return None
    diagnostics = diagnostics_from_payload(diagnostics_payload)
    roles: dict[str, FamilyRole] = {
        str(family): role for family, role in roles_payload.items() if role in _VALID_ROLES
    }
    return diagnostics, roles


_VALID_ROLES: frozenset[str] = frozenset(
    {"active-ranker", "coarse-booster", "near-dormant", "tail-only-fallback"}
)
