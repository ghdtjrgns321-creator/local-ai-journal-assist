"""Tests for company settings merge helpers."""

from __future__ import annotations

import logging

from config.settings import AuditSettings
from src.company.merger import (
    COMPANY_OVERRIDE_ALLOWED_FIELDS,
    ENGAGEMENT_OVERRIDE_ALLOWED_FIELDS,
    deep_merge,
    normalize_settings_overrides,
    resolve_settings,
    resolve_yaml_config,
)


class TestDeepMerge:
    def test_simple(self):
        base = {"a": 1, "b": 2}
        override = {"b": 99, "c": 3}
        result = deep_merge(base, override)
        assert result == {"a": 1, "b": 99, "c": 3}

    def test_nested(self):
        base = {"x": {"a": 1, "b": 2}, "y": 10}
        override = {"x": {"b": 99}}
        result = deep_merge(base, override)
        assert result == {"x": {"a": 1, "b": 99}, "y": 10}

    def test_list_replace(self):
        base = {"items": [1, 2, 3]}
        override = {"items": [99]}
        result = deep_merge(base, override)
        assert result["items"] == [99]

    def test_immutability(self):
        base = {"a": {"b": 1}}
        override = {"a": {"b": 2}}
        deep_merge(base, override)
        assert base["a"]["b"] == 1


class TestNormalizeSettingsOverrides:
    def test_company_legacy_alias_normalized(self):
        result = normalize_settings_overrides(
            {"approval_amount_threshold": 50_000_000},
            scope="company",
        )
        assert result["approval_thresholds"] == [50_000_000]
        assert "approval_amount_threshold" not in result

    def test_unknown_key_ignored(self, caplog):
        with caplog.at_level(logging.WARNING):
            result = normalize_settings_overrides(
                {"nonexistent_key": 42, "zscore_threshold": 2.2},
                scope="company",
            )
        assert result == {"zscore_threshold": 2.2}
        assert "허용되지 않는 키" in caplog.text

    def test_engagement_scope_is_narrower(self):
        assert "enable_llm_header_fallback" in COMPANY_OVERRIDE_ALLOWED_FIELDS
        assert "enable_llm_header_fallback" not in ENGAGEMENT_OVERRIDE_ALLOWED_FIELDS


class TestResolveSettings:
    def test_no_overrides(self):
        s = resolve_settings()
        default = AuditSettings()
        assert s.fuzzy_threshold == default.fuzzy_threshold

    def test_company_only(self):
        s = resolve_settings(company_overrides={"zscore_threshold": 2.0})
        assert s.zscore_threshold == 2.0

    def test_full_chain(self):
        s = resolve_settings(
            company_overrides={"zscore_threshold": 2.5},
            engagement_overrides={"zscore_threshold": 2.0},
            preset_overrides={"fuzzy_threshold": 90},
        )
        assert s.zscore_threshold == 2.0
        assert s.fuzzy_threshold == 90

    def test_legacy_company_alias_applied(self):
        s = resolve_settings(
            company_overrides={"approval_amount_threshold": 50_000_000},
        )
        assert s.approval_thresholds == [50_000_000]

    def test_disallowed_key_not_applied(self):
        s = resolve_settings(company_overrides={"openai_api_key": "secret"})
        assert s.openai_api_key == AuditSettings().openai_api_key

    def test_runtime_overrides_applied(self):
        s = resolve_settings(runtime_overrides={"fuzzy_threshold": 95})
        assert s.fuzzy_threshold == 95


class TestResolveYamlConfig:
    def test_none_returns_global_copy(self):
        g = {"a": [1, 2]}
        result = resolve_yaml_config(g, None)
        assert result == g
        result["a"].append(3)
        assert g["a"] == [1, 2]

    def test_merge(self):
        g = {"patterns": {"x": [1], "y": [2]}}
        c = {"patterns": {"x": [99]}}
        result = resolve_yaml_config(g, c)
        assert result["patterns"]["x"] == [99]
        assert result["patterns"]["y"] == [2]
