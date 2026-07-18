"""PHASE1-1 조합 빌더 엔진 — tier 폐지 후 주 검토 표면.

SoT: docs/spec/PHASE1_COMBO_BUILDER_SPEC.md. 어휘(몸통/특징)·프리셋은 config/combo_builder.yaml.
엔진은 phase1.units(전표/흐름) 위 순수 조회다 — 등급을 만들지 않는다(판단 주체 = 감사인).
결합 의미론(§3): 기본 = 그룹 내 OR / 그룹 간 AND, 엄격 모드 = 선택 룰 전부 발화.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "combo_builder.yaml"


@dataclass(frozen=True)
class ComboVocabulary:
    """빌더에 노출되는 어휘 전체. bodies/features 항목은 YAML dict 그대로(라벨·근거 포함)."""

    bodies: tuple[dict[str, Any], ...]
    features: tuple[dict[str, Any], ...]
    presets: tuple[dict[str, Any], ...]

    @property
    def body_ids(self) -> frozenset[str]:
        return frozenset(item["rule_id"] for item in self.bodies)

    @property
    def feature_ids(self) -> frozenset[str]:
        return frozenset(item["rule_id"] for item in self.features)


def load_combo_vocabulary(path: Path | None = None) -> ComboVocabulary:
    """YAML 어휘 로드 + 무결성 검증. 프리셋 features: all 은 특징 전체로 해소."""
    raw = yaml.safe_load((path or _CONFIG_PATH).read_text(encoding="utf-8"))
    bodies = tuple(raw["bodies"])
    features = tuple(raw["features"])
    body_ids = [b["rule_id"] for b in bodies]
    feature_ids = [f["rule_id"] for f in features]
    if len(set(body_ids)) != len(body_ids) or len(set(feature_ids)) != len(feature_ids):
        raise ValueError("combo_builder.yaml: 몸통/특징 rule_id 중복")
    overlap = set(body_ids) & set(feature_ids)
    if overlap:
        raise ValueError(f"combo_builder.yaml: 몸통·특징 겹침 금지 위반 {sorted(overlap)}")

    presets: list[dict[str, Any]] = []
    for preset in raw.get("presets", []):
        resolved = dict(preset)
        if resolved.get("features") == "all":
            resolved["features"] = list(feature_ids)
        unknown = (set(resolved.get("bodies", [])) - set(body_ids)) | (
            set(resolved.get("features", [])) - set(feature_ids)
        )
        if unknown:
            raise ValueError(f"프리셋 {preset.get('preset_id')}: 어휘 밖 rule_id {sorted(unknown)}")
        presets.append(resolved)
    return ComboVocabulary(bodies=bodies, features=features, presets=tuple(presets))


def _fired_rule_ids(unit: Any) -> set[str]:
    return {ref.rule_id for ref in unit.evidence_rows}


def _builder_sort_key(unit: Any) -> tuple[float, int, float, int]:
    """tier(band) 없는 정렬 — 기존 sort 축 재사용: triage_rank → time_severity → 금액 → 근거 수."""
    return (
        unit.triage_rank_score,
        unit.time_severity_score,
        unit.total_amount,
        len(unit.evidence_rows),
    )


def match_units(
    units: list[Any],
    *,
    bodies: set[str] | frozenset[str],
    features: set[str] | frozenset[str],
    strict: bool = False,
) -> list[Any]:
    """선택 조합에 걸리는 unit 목록(정렬 완료).

    기본 모드: (몸통 미선택 or 선택 몸통 중 1+ 발화) AND (특징 미선택 or 선택 특징 중 1+ 발화).
    엄격 모드: 선택한 룰 전부 발화. 양쪽 다 빈 선택 = 빈 결과(안내는 UI 몫).
    """
    selected_bodies = set(bodies)
    selected_features = set(features)
    if not selected_bodies and not selected_features:
        return []
    matched = []
    for unit in units:
        fired = _fired_rule_ids(unit)
        if strict:
            if (selected_bodies | selected_features) <= fired:
                matched.append(unit)
            continue
        body_ok = not selected_bodies or bool(selected_bodies & fired)
        feature_ok = not selected_features or bool(selected_features & fired)
        if body_ok and feature_ok:
            matched.append(unit)
    matched.sort(key=_builder_sort_key, reverse=True)
    return matched


def build_combo_builder_result(
    pr: Any,
    *,
    bodies: list[str] | set[str],
    features: list[str] | set[str],
    strict: bool = False,
    top_n: int | None = None,
    vocabulary: ComboVocabulary | None = None,
) -> dict[str, Any]:
    """대시보드용 결과 뷰. 선택은 어휘 안에서만 허용(밖이면 ValueError — UI 버그 조기 검출)."""
    from src.export.phase1_case_view import _unit_row, resolve_phase1_case_result

    vocab = vocabulary or load_combo_vocabulary()
    unknown = (set(bodies) - vocab.body_ids) | (set(features) - vocab.feature_ids)
    if unknown:
        raise ValueError(f"어휘 밖 선택: {sorted(unknown)}")

    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None:
        return {"available": False, "matched": 0, "rows": []}
    units = match_units(phase1.units, bodies=set(bodies), features=set(features), strict=strict)
    matched = len(units)
    if top_n is not None:
        units = units[:top_n]
    return {
        "available": True,
        "matched": matched,
        "rows": [_unit_row(unit, phase1) for unit in units],
        "selection": {"bodies": sorted(bodies), "features": sorted(features), "strict": strict},
    }
