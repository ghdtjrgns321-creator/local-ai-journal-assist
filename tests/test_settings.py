"""config/settings.py 단위 테스트."""

from config.settings import (
    AuditSettings,
    get_phase1_case,
    get_keywords,
    get_risk_keywords,
    get_schema,
    get_settings,
)


class TestAuditSettings:
    """AuditSettings 기본값 및 인스턴스 확인."""

    def test_singleton(self):
        """get_settings()는 동일 인스턴스를 반환해야 한다."""
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_default_values(self):
        """기본값이 올바르게 설정되어야 한다."""
        s = AuditSettings()
        assert s.max_file_size_mb == 100
        assert s.fuzzy_threshold == 80
        assert s.approval_thresholds == [10_000_000, 100_000_000, 1_000_000_000, 5_000_000_000, 10_000_000_000, 50_000_000_000]
        # computed_field: 최고 한도와 자동 동기화
        assert s.approval_threshold == 50_000_000_000
        assert s.midnight_start == 22
        assert s.midnight_end == 6
        assert s.period_end_margin_days == 5
        assert s.enable_evidence_detection is False
        assert s.enable_variance_detection is True
        assert ".xlsx" in s.allowed_extensions

    def test_env_prefix(self, monkeypatch):
        """AUDIT_ 접두사 환경변수로 오버라이드 가능해야 한다."""
        monkeypatch.setenv("AUDIT_FUZZY_THRESHOLD", "90")
        s = AuditSettings()
        assert s.fuzzy_threshold == 90


class TestYamlLoaders:
    """YAML 파일 로드 테스트."""

    def test_schema_has_columns(self):
        """schema.yaml에 columns 키가 존재해야 한다."""
        schema = get_schema()
        assert "columns" in schema
        assert len(schema["columns"]) > 0

    def test_schema_required_fields(self):
        """필수 컬럼(DETECTION_RULES.md 부록 B 기준)이 존재해야 한다."""
        schema = get_schema()
        names = [col["name"] for col in schema["columns"]]
        for required in ["document_id", "posting_date", "gl_account", "debit_amount", "credit_amount"]:
            assert required in names

    def test_keywords_has_standard_columns(self):
        """keywords.yaml에 주요 표준 컬럼 키가 존재해야 한다."""
        kw = get_keywords()
        for key in ["document_id", "posting_date", "gl_account", "debit_amount", "credit_amount"]:
            assert key in kw
            assert isinstance(kw[key], list)

    def test_risk_keywords_has_levels(self):
        """risk_keywords.yaml에 high_risk, medium_risk 키가 존재해야 한다."""
        rk = get_risk_keywords()
        assert "high_risk" in rk
        assert "medium_risk" in rk
        assert len(rk["high_risk"]) > 0

    def test_phase1_case_has_required_sections(self):
        """phase1_case.yaml 기본 구조가 존재해야 한다."""
        cfg = get_phase1_case()
        assert "phase1_case" in cfg
        phase1 = cfg["phase1_case"]
        assert phase1["secondary_tag_min_score"] == 0.40
        assert phase1["priority_band"]["high"] == 0.75
        assert phase1["priority_band"]["medium"] == 0.45
        assert phase1["counterparty_columns"][0] == "auxiliary_account_number"
        assert phase1["priority_weights"]["control"] == 0.25
        assert phase1["priority_weights"]["outflow"] == 0.15
        assert phase1["timing_priority"]["l304_only_penalty"] == 0.20
        assert phase1["timing_priority"]["l304_repeat_pattern_min_months"] == 3
