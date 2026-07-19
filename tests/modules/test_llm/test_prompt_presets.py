"""prompt_presets 단위 테스트.

감사 프리셋 12종 구조 검증 + 매칭 함수 테스트.
"""

from __future__ import annotations

import pytest

from src.llm.prompt_presets import (
    AUDIT_PRESETS,
    AuditPreset,
    get_presets_by_category,
    match_preset,
)
from src.llm.sql_validator import validate_sql


# ── 구조 검증 ────────────────────────────────────────────────

class TestPresetStructure:

    def test_total_count(self):
        assert len(AUDIT_PRESETS) == 12

    def test_required_fields(self):
        for key, preset in AUDIT_PRESETS.items():
            assert isinstance(preset, AuditPreset)
            assert preset.key == key
            assert preset.label
            assert preset.question
            assert preset.sql
            assert preset.category in ("basic", "process")
            assert len(preset.keywords) > 0

    def test_category_counts(self):
        basic = get_presets_by_category("basic")
        process = get_presets_by_category("process")
        assert len(basic) == 6
        assert len(process) == 6

    def test_all_sql_contain_batch_filter(self):
        """모든 프리셋 SQL에 upload_batch_id 조건 포함."""
        for key, preset in AUDIT_PRESETS.items():
            assert "upload_batch_id" in preset.sql, (
                f"{key} 프리셋에 upload_batch_id 누락"
            )


# ── SQL 유효성 ───────────────────────────────────────────────

class TestPresetSqlValidity:

    @pytest.mark.parametrize("key", list(AUDIT_PRESETS.keys()))
    def test_preset_passes_validator(self, key: str):
        """각 프리셋 SQL이 sql_validator를 통과해야 함."""
        preset = AUDIT_PRESETS[key]
        # Why: 프리셋 SQL은 ? 바인딩을 포함하므로 더미값으로 교체 후 검증
        sql = preset.sql.replace("?", "'test_batch_id'")
        result = validate_sql(sql, require_batch_filter=True)
        assert result.is_valid, (
            f"{key} 프리셋 SQL 검증 실패: {result.errors}"
        )


# ── 매칭 함수 ────────────────────────────────────────────────

class TestMatchPreset:

    def test_exact_match(self):
        preset = AUDIT_PRESETS["high_risk_overview"]
        result = match_preset(preset.question)
        assert result is not None
        assert result.key == "high_risk_overview"

    def test_keyword_match(self):
        result = match_preset("고위험 전표 보여줘")
        assert result is not None
        assert result.key == "high_risk_overview"

    def test_weekend_keyword(self):
        result = match_preset("주말에 처리된 전표")
        assert result is not None
        assert result.key == "weekend_midnight"

    def test_no_match(self):
        result = match_preset("오늘 날씨 어때?")
        assert result is None

    def test_case_insensitive(self):
        result = match_preset("BENFORD 편차 분석")
        assert result is not None
        assert result.key == "benford_deviation"


# ── 카테고리 필터 ────────────────────────────────────────────

class TestGetPresetsByCategory:

    def test_basic(self):
        presets = get_presets_by_category("basic")
        assert all(p.category == "basic" for p in presets)

    def test_process(self):
        presets = get_presets_by_category("process")
        assert all(p.category == "process" for p in presets)

    def test_empty_category(self):
        presets = get_presets_by_category("nonexistent")
        assert presets == []
