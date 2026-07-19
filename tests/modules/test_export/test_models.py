"""ExportFilter / ExportConfig / 컬럼 매핑 상수 테스트."""

from __future__ import annotations

from datetime import date

from src.export.models import (
    DETECTION_COLUMNS,
    DISCLAIMER,
    EXCLUDE_COLUMNS,
    HEADER_COLUMNS,
    LINE_COLUMNS,
    MASK_TARGETS,
    RISK_FILL_COLORS,
    ExportConfig,
    ExportFilter,
)


class TestExportFilter:
    """필터 dataclass 기본 동작."""

    def test_default_is_empty(self) -> None:
        assert ExportFilter().is_empty() is True

    def test_any_field_makes_non_empty(self) -> None:
        assert ExportFilter(company_codes=["C001"]).is_empty() is False
        assert ExportFilter(date_from=date(2026, 1, 1)).is_empty() is False
        assert ExportFilter(risk_levels=["High"]).is_empty() is False


class TestExportConfig:
    """기본값과 자유 메타."""

    def test_defaults(self) -> None:
        cfg = ExportConfig()
        assert cfg.mask_pii is False
        assert cfg.top_n == 50
        assert cfg.include_raw_data is True
        assert "데이터 분석" in cfg.report_title
        assert cfg.analyst_name == ""
        assert cfg.extra_meta == {}

    def test_extra_meta_isolated_per_instance(self) -> None:
        # Why: dataclass field(default_factory=dict)가 인스턴스 간 공유되지 않는지 회귀 방지.
        a = ExportConfig()
        b = ExportConfig()
        a.extra_meta["company"] = "ACME"
        assert "company" not in b.extra_meta


class TestColumnMappings:
    """컬럼 매핑 상수의 완전성과 충돌 부재."""

    def test_no_overlapping_keys(self) -> None:
        # Why: 동일 원본 컬럼이 두 매핑에 동시에 존재하면 rename이 모호해진다.
        common = HEADER_COLUMNS.keys() & LINE_COLUMNS.keys()
        assert common == set()
        common_det = HEADER_COLUMNS.keys() & DETECTION_COLUMNS.keys()
        assert common_det == set()

    def test_label_columns_excluded(self) -> None:
        # Why: 라벨 컬럼은 보고서에 절대 포함되면 안 됨.
        for label in ("is_fraud", "fraud_type", "is_anomaly", "anomaly_type"):
            assert label in EXCLUDE_COLUMNS
            assert label not in HEADER_COLUMNS
            assert label not in LINE_COLUMNS

    def test_mask_targets_subset_of_known_columns(self) -> None:
        # Why: 마스킹 대상은 실제 스키마에 존재하는 컬럼이어야 함.
        all_known = HEADER_COLUMNS.keys() | LINE_COLUMNS.keys()
        for col in MASK_TARGETS:
            assert col in all_known, f"unknown mask target: {col}"

    def test_mask_methods_valid(self) -> None:
        for method in MASK_TARGETS.values():
            assert method in {"hash", "partial"}

    def test_risk_fill_colors_have_three_levels(self) -> None:
        assert {"High", "Medium", "Low"} <= RISK_FILL_COLORS.keys()
        for hex_color in RISK_FILL_COLORS.values():
            # Why: openpyxl PatternFill은 6자리 RGB hex(또는 8자리 ARGB) 요구.
            assert len(hex_color) in (6, 8)
            int(hex_color, 16)  # parseable


class TestDisclaimer:
    """면책조항 문구의 핵심 키워드 보장."""

    def test_disclaimer_key_phrases(self) -> None:
        assert "감사 의견" in DISCLAIMER
        assert "데이터 분석" in DISCLAIMER
