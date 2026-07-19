"""audit_evidence — 감사 증거 템플릿 단위 테스트 (묶음 3)."""

from __future__ import annotations

import pandas as pd
import pytest

from src.export.audit_evidence import (
    RULE_LEGAL_BASIS,
    AuditEvidence,
    build_evidence_report,
    build_evidence_row,
    format_narrative,
)


class TestFormatNarrative:
    def test_basic_structure(self):
        text = format_narrative(
            document_id="D001",
            score=0.85,
            risk="High",
            rules=["L3-04"],
            top_features=[("amount", 0.4), ("gl_account", 0.2)],
        )
        assert "D001" in text
        assert "High" in text
        assert "0.850" in text
        assert "L3-04" in text
        # 법규 근거가 포함됨
        assert "ISA 240" in text
        # Top-K 피처 표시
        assert "amount" in text
        assert "0.400" in text
        assert "재검토 권고" in text

    def test_empty_rules_shows_ml_only(self):
        text = format_narrative(
            document_id="D002",
            score=0.55,
            risk="Medium",
            rules=[],
            top_features=[("amount", 0.3)],
        )
        assert "ML 모델 단독 판정" in text

    def test_empty_top_features_omitted(self):
        text = format_narrative(
            document_id="D003",
            score=0.4,
            risk="Low",
            rules=["L2-02"],
            top_features=[],
        )
        # top_features 섹션이 나오지 않아야 함
        assert "VAE 재구성 오차" not in text
        assert "L2-02" in text

    def test_unknown_rule_id(self):
        text = format_narrative(
            document_id="D004",
            score=0.5,
            risk="Medium",
            rules=["ZZ99"],  # 미등록 룰
            top_features=[],
        )
        assert "ZZ99" in text
        assert "미등록 룰" in text


class TestBuildEvidenceRow:
    def test_full_row(self):
        row = pd.Series({
            "document_id": "D100",
            "anomaly_score": 0.92,
            "risk_level": "High",
            "flagged_rules": "L3-04,L2-05",
            "ML02_top_feature_1": "amount",
            "ML02_top_feature_1_contrib": 0.5,
            "ML02_top_feature_2": "gl_account",
            "ML02_top_feature_2_contrib": 0.3,
            "ML02_top_feature_3": "posting_time",
            "ML02_top_feature_3_contrib": 0.1,
        })
        ev = build_evidence_row(row)
        assert isinstance(ev, AuditEvidence)
        assert ev.document_id == "D100"
        assert ev.anomaly_score == 0.92
        assert ev.violated_rules == ["L3-04", "L2-05"]
        assert len(ev.top_features) == 3
        assert ev.top_features[0] == ("amount", 0.5)

    def test_missing_vae_columns(self):
        # Why: VAE Top-K 컬럼이 없어도 crash 없이 동작
        row = pd.Series({
            "document_id": "D200",
            "anomaly_score": 0.3,
            "risk_level": "Low",
            "flagged_rules": "L3-05",
        })
        ev = build_evidence_row(row)
        assert ev.top_features == []
        assert "L3-05" in ev.narrative

    def test_empty_flagged_rules(self):
        row = pd.Series({
            "document_id": "D300",
            "anomaly_score": 0.1,
            "risk_level": "Normal",
            "flagged_rules": "",
        })
        ev = build_evidence_row(row)
        assert ev.violated_rules == []

    def test_nan_top_feature_skipped(self):
        # Why: NaN 피처 기여도는 스킵 (pd.NA 방어)
        row = pd.Series({
            "document_id": "D400",
            "anomaly_score": 0.7,
            "risk_level": "Medium",
            "flagged_rules": "L2-02",
            "ML02_top_feature_1": "amount",
            "ML02_top_feature_1_contrib": 0.5,
            "ML02_top_feature_2": None,
            "ML02_top_feature_2_contrib": None,
        })
        ev = build_evidence_row(row)
        assert len(ev.top_features) == 1


class TestBuildEvidenceReport:
    def test_filters_by_min_score(self):
        df = pd.DataFrame({
            "document_id": ["D1", "D2", "D3"],
            "anomaly_score": [0.1, 0.5, 0.9],
            "risk_level": ["Normal", "Medium", "High"],
            "flagged_rules": ["", "L2-02", "L3-04"],
        })
        evidences = build_evidence_report(df, min_score=0.5)
        assert len(evidences) == 2
        assert {e.document_id for e in evidences} == {"D2", "D3"}

    def test_empty_df_returns_empty_list(self):
        df = pd.DataFrame({
            "anomaly_score": [],
            "risk_level": [],
            "flagged_rules": [],
            "document_id": [],
        })
        assert build_evidence_report(df) == []

    def test_no_anomaly_score_column_returns_empty(self):
        df = pd.DataFrame({"x": [1, 2, 3]})
        assert build_evidence_report(df) == []


class TestLegalBasisCoverage:
    """RULE_LEGAL_BASIS가 핵심 룰 ID를 커버하는지."""

    @pytest.mark.parametrize("rule_id", ["L1-01", "L2-02", "L2-05", "L3-04", "L4-02", "ML02", "EN01"])
    def test_core_rules_have_basis(self, rule_id):
        assert rule_id in RULE_LEGAL_BASIS
        assert len(RULE_LEGAL_BASIS[rule_id]) > 0
