"""PHASE2 sub-detector evidence_tier loader.

config/phase2_subdetector_tiers.yaml 을 dataclass 로 노출한다. tier 변경은
docs/spec/DECISION.md D044 fitting-risk check 통과 후에만 허용된다.

본 모듈은 tie-break ladder (Phase2 family ranking Layer 4 §5) 에서만 사용되며,
truth recall 향상 목적으로 호출되어서는 안 된다.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "phase2_subdetector_tiers.yaml"

Tier = Literal["strong", "moderate", "weak", "ml_quantile"]
SourceType = Literal["standard", "distribution"]

# tier ranking 가중치 — tie-break ladder #5 에서 desc 정렬에 사용
TIER_ORDER: dict[str, int] = {"strong": 3, "moderate": 2, "weak": 1, "ml_quantile": 0}


@dataclass(frozen=True)
class SubdetectorTier:
    """단일 sub-detector 의 tier 메타.

    tier 의미는 config/phase2_subdetector_tiers.yaml 상단 주석 참조.

    role lock 필드 (결정 9, 2026-05-25): 분석 영역(family)별 운영 역할 고정.
    optional — 기존 항목 호환 위해 None 허용. 명시된 항목은 단독 ranker 추격 금지.
    """

    family: str
    code: str
    label: str
    tier: Tier
    source_type: SourceType
    source_citation: str
    distribution_metric: str
    rationale: str
    # ── 결정 9 메타 (timeseries TS01/TS02 부터 적용, 다른 항목은 None) ──
    role_lock: str | None = None
    ranker_use: str | None = None
    do_not_tune_for_top_recall: bool = False
    coverage_profile: str | None = None
    batch_local_ecdf_caveat: str | None = None

    @property
    def tier_weight(self) -> int:
        return TIER_ORDER[self.tier]

    @property
    def is_context_lane_locked(self) -> bool:
        """role_lock == 'context_lane' 여부 — UI badge·dashboard caption 분기용."""
        return self.role_lock == "context_lane"


def load_subdetector_tiers(path: Path | None = None) -> dict[tuple[str, str], SubdetectorTier]:
    """YAML 로딩 + 누락·잘못된 tier 검증.

    Returns:
        dict[(family, code) -> SubdetectorTier].
    """
    target = path or CONFIG_PATH
    payload = yaml.safe_load(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{target} root must be a mapping")

    allowed_tiers = set(payload.get("allowed_tiers") or [])
    allowed_sources = set(payload.get("allowed_source_types") or [])
    if allowed_tiers != set(TIER_ORDER):
        raise ValueError(
            f"allowed_tiers mismatch: yaml={sorted(allowed_tiers)} expected={sorted(TIER_ORDER)}"
        )
    if not allowed_sources:
        raise ValueError("allowed_source_types must not be empty")

    entries = payload.get("sub_detectors") or []
    if not isinstance(entries, list):
        raise ValueError("sub_detectors must be a list")

    result: dict[tuple[str, str], SubdetectorTier] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"sub_detectors[{index}] must be a mapping")
        item = _build_tier_entry(entry, allowed_tiers, allowed_sources, index)
        key = (item.family, item.code)
        if key in result:
            raise ValueError(f"duplicate sub_detector {key}")
        result[key] = item
    return result


def _build_tier_entry(
    entry: dict,
    allowed_tiers: set[str],
    allowed_sources: set[str],
    index: int,
) -> SubdetectorTier:
    required_fields = (
        "family",
        "code",
        "label",
        "tier",
        "source_type",
        "source_citation",
        "distribution_metric",
        "rationale",
    )
    missing = [field for field in required_fields if not entry.get(field)]
    if missing:
        raise ValueError(f"sub_detectors[{index}] missing fields: {missing}")
    tier = entry["tier"]
    source_type = entry["source_type"]
    if tier not in allowed_tiers:
        raise ValueError(f"sub_detectors[{index}] invalid tier={tier}")
    if source_type not in allowed_sources:
        raise ValueError(f"sub_detectors[{index}] invalid source_type={source_type}")
    # 결정 9 optional 메타 — 명시된 항목만 채움 (context_lane 락 대상에만 설정).
    role_lock_value = entry.get("role_lock")
    ranker_use_value = entry.get("ranker_use")
    coverage_profile_value = entry.get("coverage_profile")
    batch_local_caveat_value = entry.get("batch_local_ecdf_caveat")
    do_not_tune_flag = bool(entry.get("do_not_tune_for_top_recall", False))
    return SubdetectorTier(
        family=str(entry["family"]),
        code=str(entry["code"]),
        label=str(entry["label"]),
        tier=tier,
        source_type=source_type,
        source_citation=str(entry["source_citation"]).strip(),
        distribution_metric=str(entry["distribution_metric"]).strip(),
        rationale=str(entry["rationale"]).strip(),
        role_lock=str(role_lock_value).strip() if role_lock_value else None,
        ranker_use=str(ranker_use_value).strip() if ranker_use_value else None,
        do_not_tune_for_top_recall=do_not_tune_flag,
        coverage_profile=str(coverage_profile_value).strip() if coverage_profile_value else None,
        batch_local_ecdf_caveat=(
            str(batch_local_caveat_value).strip() if batch_local_caveat_value else None
        ),
    )


@lru_cache(maxsize=1)
def get_subdetector_tier_index() -> dict[tuple[str, str], SubdetectorTier]:
    """Process-level cache 된 tier index. 테스트는 `load_subdetector_tiers` 직접 호출."""
    return load_subdetector_tiers()


def max_tier_weight(codes: list[tuple[str, str]]) -> int:
    """주어진 (family, code) 리스트 중 최대 tier_weight 반환.

    tie-break ladder #5 (max_subdetector_evidence_tier) 에서 사용.
    빈 리스트는 0 (ml_quantile 동치).
    """
    if not codes:
        return 0
    index = get_subdetector_tier_index()
    weights = [index[key].tier_weight for key in codes if key in index]
    return max(weights) if weights else 0
