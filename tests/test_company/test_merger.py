"""RC-0-3: deep_merge, resolve_settings, resolve_yaml_config 테스트."""

from __future__ import annotations

import logging

from config.settings import AuditSettings
from src.company.merger import deep_merge, resolve_settings, resolve_yaml_config


class TestDeepMerge:
    """딕셔너리 재귀 병합 테스트."""

    def test_simple(self):
        """flat dict 병합."""
        base = {"a": 1, "b": 2}
        override = {"b": 99, "c": 3}
        result = deep_merge(base, override)
        assert result == {"a": 1, "b": 99, "c": 3}

    def test_nested(self):
        """2단계 중첩 dict 병합."""
        base = {"x": {"a": 1, "b": 2}, "y": 10}
        override = {"x": {"b": 99}}
        result = deep_merge(base, override)
        assert result == {"x": {"a": 1, "b": 99}, "y": 10}

    def test_list_replace(self):
        """리스트는 append가 아닌 replace."""
        base = {"items": [1, 2, 3]}
        override = {"items": [99]}
        result = deep_merge(base, override)
        assert result["items"] == [99]

    def test_empty_override(self):
        """빈 override → base 그대로."""
        base = {"a": 1}
        result = deep_merge(base, {})
        assert result == {"a": 1}

    def test_immutability(self):
        """원본 dict 불변."""
        base = {"a": {"b": 1}}
        override = {"a": {"b": 2}}
        deep_merge(base, override)
        assert base["a"]["b"] == 1  # base 변경 없음


class TestResolveSettings:
    """3+1 계층 설정 해소 테스트."""

    def test_no_overrides(self):
        """오버라이드 없음 → 기본값."""
        s = resolve_settings()
        default = AuditSettings()
        assert s.fuzzy_threshold == default.fuzzy_threshold

    def test_company_only(self):
        """회사 오버라이드만 적용."""
        s = resolve_settings(company_overrides={"zscore_threshold": 2.0})
        assert s.zscore_threshold == 2.0

    def test_full_chain(self):
        """글로벌 + 회사 + 연도 + 프리셋."""
        s = resolve_settings(
            company_overrides={"zscore_threshold": 2.5},
            engagement_overrides={"zscore_threshold": 2.0},
            preset_overrides={"fuzzy_threshold": 90},
        )
        # Why: engagement wins over company
        assert s.zscore_threshold == 2.0
        assert s.fuzzy_threshold == 90

    def test_engagement_wins_over_company(self):
        """동일 키 충돌 시 engagement 우선."""
        s = resolve_settings(
            company_overrides={"balance_tolerance": 5.0},
            engagement_overrides={"balance_tolerance": 0.5},
        )
        assert s.balance_tolerance == 0.5

    def test_unknown_key_warns(self, caplog):
        """미지원 키 → 경고 로그."""
        with caplog.at_level(logging.WARNING):
            resolve_settings(company_overrides={"nonexistent_key": 42})
        assert "알 수 없는 키" in caplog.text

    def test_runtime_overrides_applied(self):
        """runtime_overrides는 model_copy로 최종 적용."""
        s = resolve_settings(runtime_overrides={"fuzzy_threshold": 95})
        assert s.fuzzy_threshold == 95


class TestResolveYamlConfig:
    """YAML 설정 머지 테스트."""

    def test_none_returns_global_copy(self):
        """company_config=None → 글로벌 deepcopy."""
        g = {"a": [1, 2]}
        result = resolve_yaml_config(g, None)
        assert result == g
        # 독립 복사 확인
        result["a"].append(3)
        assert g["a"] == [1, 2]

    def test_merge(self):
        """dict 내부 deep_merge."""
        g = {"patterns": {"x": [1], "y": [2]}}
        c = {"patterns": {"x": [99]}}
        result = resolve_yaml_config(g, c)
        assert result["patterns"]["x"] == [99]
        assert result["patterns"]["y"] == [2]
