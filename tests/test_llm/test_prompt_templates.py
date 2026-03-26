"""prompt_templates.py 테스트 — EDAProfile → LLM 컨텍스트 변환 검증."""

from __future__ import annotations

import json

import pytest

from src.eda.models import ColumnProfile, EDAProfile
from src.llm.prompt_templates import build_preprocessing_prompt, profile_to_llm_context


# ── profile_to_llm_context ──


class TestProfileToLlmContext:
    def test_basic_structure(self, lm_eda_profile):
        """기본 출력 구조 검증 — total_rows, columns 등."""
        ctx = profile_to_llm_context(lm_eda_profile)
        assert ctx["total_rows"] == 10_000
        assert ctx["total_columns"] == 4
        assert ctx["duplicate_rows"] == 5
        assert "columns" in ctx
        assert len(ctx["columns"]) == 4

    def test_numeric_column_flags(self, lm_eda_profile):
        """수치형 컬럼의 해석 플래그 검증."""
        ctx = profile_to_llm_context(lm_eda_profile)
        debit = ctx["columns"]["debit_amount"]

        # skewness=8.7 > threshold(2.0) → True
        assert debit["is_highly_skewed"] is True
        assert debit["skewness"] == 8.7

        # outlier_rate = 500/10000 = 0.05 < threshold(0.10) → False
        assert debit["has_many_outliers"] is False
        assert debit["outlier_rate"] == 0.05

    def test_numeric_low_skew(self, lm_eda_profile):
        """왜도 낮은 수치형 — is_highly_skewed=False."""
        ctx = profile_to_llm_context(lm_eda_profile)
        credit = ctx["columns"]["credit_amount"]

        # skewness=1.2 < threshold(2.0) → False
        assert credit["is_highly_skewed"] is False

    def test_categorical_column_flags(self, lm_eda_profile):
        """범주형 컬럼의 해석 플래그 검증."""
        ctx = profile_to_llm_context(lm_eda_profile)
        gl = ctx["columns"]["gl_account"]

        # cardinality=4200 > threshold(50) → True
        assert gl["is_high_cardinality"] is True
        assert gl["cardinality"] == 4200

    def test_datetime_column(self, lm_eda_profile):
        """datetime 컬럼 — min/max/range 포함."""
        ctx = profile_to_llm_context(lm_eda_profile)
        dt = ctx["columns"]["posting_date"]
        assert dt["dtype_group"] == "datetime"
        assert dt["min_date"] == "2025-01-01"
        assert dt["date_range_days"] == 364

    def test_missing_rate_flag(self):
        """missing_rate > threshold → is_high_missing=True."""
        profile = EDAProfile(
            total_rows=100,
            total_columns=1,
            memory_bytes=800,
            duplicate_rows=0,
            columns={
                "sparse_col": ColumnProfile(
                    name="sparse_col",
                    dtype="float64",
                    dtype_group="numeric",
                    missing_rate=0.25,  # > 0.10 threshold
                    unique_count=50,
                    mean=100.0,
                    median=90.0,
                    std=30.0,
                    skewness=0.5,
                    kurtosis=2.0,
                    q1=70.0,
                    q3=120.0,
                    iqr=50.0,
                    outlier_count=2,
                    min_val=0.0,
                    max_val=300.0,
                ),
            },
        )
        ctx = profile_to_llm_context(profile)
        assert ctx["columns"]["sparse_col"]["is_high_missing"] is True

    def test_json_serializable(self, lm_eda_profile):
        """출력이 JSON 직렬화 가능한지 확인."""
        ctx = profile_to_llm_context(lm_eda_profile)
        json_str = json.dumps(ctx, ensure_ascii=False)
        assert isinstance(json_str, str)
        parsed = json.loads(json_str)
        assert parsed["total_rows"] == 10_000

    def test_empty_profile(self):
        """빈 프로파일 처리."""
        profile = EDAProfile(
            total_rows=0,
            total_columns=0,
            memory_bytes=0,
            duplicate_rows=0,
            columns={},
        )
        ctx = profile_to_llm_context(profile)
        assert ctx["total_rows"] == 0
        assert ctx["columns"] == {}

    def test_boolean_column(self):
        """boolean 컬럼 — true_rate 포함."""
        profile = EDAProfile(
            total_rows=100,
            total_columns=1,
            memory_bytes=100,
            duplicate_rows=0,
            columns={
                "is_weekend": ColumnProfile(
                    name="is_weekend",
                    dtype="bool",
                    dtype_group="boolean",
                    missing_rate=0.0,
                    unique_count=2,
                    true_rate=0.28,
                ),
            },
        )
        ctx = profile_to_llm_context(profile)
        assert ctx["columns"]["is_weekend"]["true_rate"] == 0.28

    def test_settings_threshold_respected(self, lm_eda_profile, monkeypatch):
        """heuristic 임계값 변경 시 판정 결과 변동 검증."""
        from config import settings

        # 캐시 클리어 후 임계값 변경
        settings.get_settings.cache_clear()

        monkeypatch.setenv("AUDIT_HEURISTIC_SKEWNESS_THRESHOLD", "10.0")
        settings.get_settings.cache_clear()

        try:
            ctx = profile_to_llm_context(lm_eda_profile)
            # skewness=8.7 < new threshold(10.0) → False
            assert ctx["columns"]["debit_amount"]["is_highly_skewed"] is False
        finally:
            # 원래 설정 복원
            monkeypatch.delenv("AUDIT_HEURISTIC_SKEWNESS_THRESHOLD", raising=False)
            settings.get_settings.cache_clear()


# ── build_preprocessing_prompt ──


class TestBuildPreprocessingPrompt:
    def test_returns_two_messages(self, lm_eda_profile):
        """시스템 + 유저 메시지 2개 반환."""
        ctx = profile_to_llm_context(lm_eda_profile)
        messages = build_preprocessing_prompt(ctx)
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_system_prompt_contains_rules(self, lm_eda_profile):
        """시스템 프롬프트에 핵심 규칙 포함."""
        ctx = profile_to_llm_context(lm_eda_profile)
        messages = build_preprocessing_prompt(ctx)
        system = messages[0]["content"]
        assert "tree_model" in system
        assert "distance_model" in system
        assert "imputer" in system.lower() or "결측치" in system

    def test_user_prompt_contains_profile(self, lm_eda_profile):
        """유저 프롬프트에 EDA 프로파일 데이터 포함."""
        ctx = profile_to_llm_context(lm_eda_profile)
        messages = build_preprocessing_prompt(ctx)
        user = messages[1]["content"]
        assert "10,000" in user  # total_rows
        assert "debit_amount" in user or "columns" in user

    def test_user_prompt_is_valid_text(self, lm_eda_profile):
        """유저 프롬프트가 비어있지 않은 유효한 텍스트."""
        ctx = profile_to_llm_context(lm_eda_profile)
        messages = build_preprocessing_prompt(ctx)
        assert len(messages[1]["content"]) > 100
