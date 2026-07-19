"""Settings/YAML merge helpers for company-specific configuration."""

from __future__ import annotations

import copy
import logging
from typing import Any

from config.settings import AuditSettings

logger = logging.getLogger(__name__)

_GLOBAL_ONLY_OVERRIDE_FIELDS = {
    "max_file_size_mb",
    "allowed_extensions",
    "datasynth_label_mode",
    "datasynth_metadata_enforcement",
    "profile_dir",
    "duckdb_path",
    "detection_parallel_workers",
    "openai_api_key",
    "openai_timeout",
}
_ENGAGEMENT_BLOCKED_FIELDS = {
    "enable_llm_header_fallback",
    "enable_nlp_detection",
}
_LOCAL_FIRST_FORCED_VALUES = {
    "enable_nlp_detection": False,
}
_LEGACY_ALIAS_MAP = {
    "approval_amount_threshold": "approval_thresholds",
    "approval_threshold": "approval_thresholds",
}

COMPANY_OVERRIDE_ALLOWED_FIELDS = set(AuditSettings.model_fields) - _GLOBAL_ONLY_OVERRIDE_FIELDS
ENGAGEMENT_OVERRIDE_ALLOWED_FIELDS = COMPANY_OVERRIDE_ALLOWED_FIELDS - _ENGAGEMENT_BLOCKED_FIELDS


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge dictionaries. Lists are replaced, not extended."""
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
    """Resolve global defaults + company/engagement overrides + runtime edits."""
    base = AuditSettings()
    base_dict = base.model_dump()

    if company_overrides:
        base_dict = deep_merge(
            base_dict,
            normalize_settings_overrides(company_overrides, scope="company"),
        )

    if engagement_overrides:
        base_dict = deep_merge(
            base_dict,
            normalize_settings_overrides(engagement_overrides, scope="engagement"),
        )

    merged = AuditSettings.model_validate(base_dict)

    runtime = {}
    if preset_overrides:
        runtime.update(preset_overrides)
    if runtime_overrides:
        runtime.update(runtime_overrides)
    if runtime:
        merged = merged.model_copy(update=runtime)

    return merged.model_copy(update=_LOCAL_FIRST_FORCED_VALUES)


def resolve_yaml_config(
    global_config: dict[str, Any],
    company_config: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge global YAML config with company-specific YAML config."""
    if company_config is None:
        return copy.deepcopy(global_config)
    return deep_merge(global_config, company_config)


def normalize_settings_overrides(
    overrides: dict[str, Any],
    *,
    scope: str,
) -> dict[str, Any]:
    """Normalize legacy aliases and filter disallowed keys before persistence/use."""
    normalized = _normalize_legacy_aliases(overrides, scope)
    allowed = (
        COMPANY_OVERRIDE_ALLOWED_FIELDS
        if scope == "company"
        else ENGAGEMENT_OVERRIDE_ALLOWED_FIELDS
    )
    _warn_ignored_keys(normalized, allowed, scope)
    return {
        key: copy.deepcopy(_LOCAL_FIRST_FORCED_VALUES.get(key, value))
        for key, value in normalized.items()
        if key in allowed
    }


def _normalize_legacy_aliases(
    overrides: dict[str, Any],
    scope: str,
) -> dict[str, Any]:
    normalized = copy.deepcopy(overrides)
    for legacy_key, current_key in _LEGACY_ALIAS_MAP.items():
        if legacy_key not in normalized or current_key in normalized:
            continue
        normalized[current_key] = _coerce_legacy_value(
            current_key,
            normalized.pop(legacy_key),
        )
        logger.warning(
            "%s settings_overrides legacy key '%s' -> '%s'로 정규화",
            scope,
            legacy_key,
            current_key,
        )
    return normalized


def _coerce_legacy_value(current_key: str, raw_value: Any) -> Any:
    if current_key == "approval_thresholds":
        if isinstance(raw_value, list):
            return [int(v) for v in raw_value]
        return [int(raw_value)]
    return raw_value


def _warn_ignored_keys(
    overrides: dict[str, Any],
    allowed: set[str],
    scope: str,
) -> None:
    ignored = set(overrides) - allowed
    if ignored:
        logger.warning(
            "%s settings_overrides에서 허용되지 않는 키 %s 무시",
            scope,
            sorted(ignored),
        )
