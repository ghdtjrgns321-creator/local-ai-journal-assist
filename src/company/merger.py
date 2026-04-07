"""3계층 설정 해소(Resolution) — deep_merge + AuditSettings 생성.

해소 체인:
  글로벌 기본값 (AuditSettings 기본값)
    → deep_merge(회사 settings_overrides)
    → deep_merge(연도 settings_overrides)
    → model_copy(update=preset/runtime overrides)
    = 최종 AuditSettings 인스턴스
"""

from __future__ import annotations

import copy
import logging
from typing import Any

from config.settings import AuditSettings

logger = logging.getLogger(__name__)


def deep_merge(
    base: dict[str, Any], override: dict[str, Any]
) -> dict[str, Any]:
    """딕셔너리 재귀 병합. 리스트는 replace (append 아님).

    규칙:
      - override에 키 존재 & 양쪽 dict → 재귀 merge
      - override에 키 존재 & 그 외 → 전체 교체 (리스트 포함)
      - override에 키 없음 → base 값 유지

    Returns:
        새 딕셔너리 (base, override 모두 불변)
    """
    result = copy.deepcopy(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = deep_merge(result[key], val)
        else:
            result[key] = copy.deepcopy(val)
    return result


def resolve_settings(
    *,
    company_overrides: dict[str, Any] | None = None,
    engagement_overrides: dict[str, Any] | None = None,
    preset_overrides: dict[str, Any] | None = None,
    runtime_overrides: dict[str, Any] | None = None,
) -> AuditSettings:
    """3+1 계층 설정 해소 → 최종 AuditSettings 인스턴스.

    Layer 1: AuditSettings() 기본값 (env 포함)
    Layer 2: company_overrides (deep_merge)
    Layer 3: engagement_overrides (deep_merge)
    Layer 4: preset + runtime (model_copy, 비영속)
    """
    base = AuditSettings()
    base_dict = base.model_dump()

    if company_overrides:
        _warn_unknown_keys(company_overrides, base_dict, "company")
        base_dict = deep_merge(base_dict, company_overrides)

    if engagement_overrides:
        _warn_unknown_keys(engagement_overrides, base_dict, "engagement")
        base_dict = deep_merge(base_dict, engagement_overrides)

    # Why: Layer 1~3은 model_validate로 전체 검증. Layer 4는 model_copy로
    # env_file 재로드 등 부작용 없이 비영속 오버라이드만 적용.
    merged = AuditSettings.model_validate(base_dict)

    runtime = {}
    if preset_overrides:
        runtime.update(preset_overrides)
    if runtime_overrides:
        runtime.update(runtime_overrides)
    if runtime:
        merged = merged.model_copy(update=runtime)

    return merged


def resolve_yaml_config(
    global_config: dict[str, Any],
    company_config: dict[str, Any] | None,
) -> dict[str, Any]:
    """YAML 설정 파일(keywords, audit_rules, risk_keywords) 머지.

    회사별 파일이 None이면 글로벌 그대로 반환.
    """
    if company_config is None:
        return copy.deepcopy(global_config)
    return deep_merge(global_config, company_config)


def _warn_unknown_keys(
    overrides: dict[str, Any],
    base: dict[str, Any],
    source: str,
) -> None:
    """AuditSettings에 없는 키 감지 → 경고 로그 (오타 방지)."""
    unknown = set(overrides.keys()) - set(base.keys())
    if unknown:
        logger.warning(
            "%s settings_overrides에 알 수 없는 키: %s (무시됨)",
            source,
            sorted(unknown),
        )
