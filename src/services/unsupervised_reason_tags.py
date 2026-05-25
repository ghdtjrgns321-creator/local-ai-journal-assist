"""PHASE2 unsupervised (VAE / ML02) reason tag loader.

config/unsupervised_reason_tags.yaml 의 매핑을 dataclass 로 노출한다.
VAE detector 가 산출한 per-row top-K 재구성 기여 피처 이름을 audit
narrator·dashboard 가 표시할 reason tag 로 변환한다.

본 모듈은 **overlay/narrator 표시 전용**이다. score / threshold / ranking 에
사용해서는 안 된다. 매핑 변경은 fitting risk 가 없는 표시 어휘 변경에 한정한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "unsupervised_reason_tags.yaml"

FALLBACK_TAG = "feature_pattern_outlier"
FALLBACK_LABEL_KO = "피처 패턴 이상"
EVIDENCE_TYPE = "statistical_outlier"


@dataclass(frozen=True)
class ReasonTag:
    """단일 reason tag 메타."""

    feature_key: str
    tag: str
    label_ko: str
    evidence_type: str = EVIDENCE_TYPE


@dataclass(frozen=True)
class ReasonTagIndex:
    """exact → prefix → contains 순으로 매칭하는 인덱스.

    feature 명은 ColumnTransformer get_feature_names_out() 산출 (`num__amount`,
    `cat_low__counterparty_xxxxx`) 가 들어올 수 있어 prefix `<group>__` 를
    제거한 후 비교한다.
    """

    mappings: tuple[ReasonTag, ...]
    fallback: ReasonTag

    def resolve(self, feature_name: str) -> ReasonTag:
        """feature 명에 매칭되는 ReasonTag 를 반환. 미매칭은 fallback."""
        normalized = _normalize_feature_name(feature_name)
        # 1) exact
        for entry in self.mappings:
            if entry.feature_key == normalized:
                return entry
        # 2) prefix
        for entry in self.mappings:
            if normalized.startswith(entry.feature_key):
                return entry
        # 3) contains
        for entry in self.mappings:
            if entry.feature_key in normalized:
                return entry
        return self.fallback


def _normalize_feature_name(feature_name: str) -> str:
    """ColumnTransformer prefix(`<group>__`) 제거 후 lowercase."""
    name = str(feature_name or "").strip()
    if not name:
        return ""
    if "__" in name:
        name = name.split("__", 1)[1]
    return name.lower()


def load_reason_tags(path: Path | None = None) -> ReasonTagIndex:
    """YAML 로딩 + 누락 필드 검증.

    Returns:
        ReasonTagIndex.
    """
    target = path or CONFIG_PATH
    payload = yaml.safe_load(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{target} root must be a mapping")

    raw_mappings = payload.get("mappings") or []
    if not isinstance(raw_mappings, list) or not raw_mappings:
        raise ValueError("mappings must be a non-empty list")

    evidence_type = str(payload.get("evidence_type") or EVIDENCE_TYPE)
    mappings: list[ReasonTag] = []
    seen_keys: set[str] = set()
    for index, entry in enumerate(raw_mappings):
        if not isinstance(entry, dict):
            raise ValueError(f"mappings[{index}] must be a mapping")
        feature_key = _required_str(entry, "feature_key", index)
        tag = _required_str(entry, "tag", index)
        label_ko = _required_str(entry, "label_ko", index)
        if feature_key in seen_keys:
            raise ValueError(f"mappings[{index}] duplicate feature_key={feature_key}")
        seen_keys.add(feature_key)
        mappings.append(
            ReasonTag(
                feature_key=feature_key,
                tag=tag,
                label_ko=label_ko,
                evidence_type=evidence_type,
            )
        )

    fallback_payload = payload.get("fallback") or {}
    if not isinstance(fallback_payload, dict):
        raise ValueError("fallback must be a mapping")
    fallback_tag = str(fallback_payload.get("tag") or FALLBACK_TAG)
    fallback_label = str(fallback_payload.get("label_ko") or FALLBACK_LABEL_KO)
    fallback = ReasonTag(
        feature_key="",
        tag=fallback_tag,
        label_ko=fallback_label,
        evidence_type=evidence_type,
    )

    return ReasonTagIndex(mappings=tuple(mappings), fallback=fallback)


def _required_str(entry: dict, key: str, index: int) -> str:
    value = entry.get(key)
    if value is None or not str(value).strip():
        raise ValueError(f"mappings[{index}] missing field={key}")
    return str(value).strip().lower() if key == "feature_key" else str(value).strip()


@lru_cache(maxsize=1)
def get_reason_tag_index() -> ReasonTagIndex:
    """Process-level cache 된 reason tag index."""
    return load_reason_tags()


def resolve_tag(feature_name: str) -> ReasonTag:
    """feature 명을 ReasonTag 로 변환. 미매칭은 fallback."""
    return get_reason_tag_index().resolve(feature_name)
