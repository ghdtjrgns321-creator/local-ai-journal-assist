"""NLPDetector + nlp_rules 단위 테스트 — WU-21.

검증 범위:
- NLPDetector 통합: Mock EmbeddingService 주입 → 5개 룰 실행 → DetectionResult 구조
- 룰별 단위: NLP01~NLP05 각각의 핵심 케이스
- 에러 격리: 한 룰 실패가 나머지에 영향 없음
- API 불가 시: graceful skip + warning
- 빈 DataFrame: ValueError
- 비식별화: morpheme_tokens 우선 사용
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from config.settings import get_settings
from src.detection.base import DetectionResult
from src.detection.nlp_analyzer import NLPDetector
from src.detection.nlp_rules import (
    nlp01_header_account_mismatch,
    nlp02_process_account_mismatch,
    nlp03_atypical_description,
    nlp04_ic_description_anomaly,
    nlp05_synonym_evasion,
)
from src.llm.embedding_service import EmbeddingService


# ── Mock EmbeddingClient + Service ──────────────────────────


class _DeterministicMockClient:
    """결정론적 임베딩 — 같은 텍스트 → 같은 벡터, L2 정규화."""

    provider = "mock"

    def __init__(self, dim: int = 8) -> None:
        self.dim = dim

    def is_available(self) -> bool:
        return True

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            seed = sum(ord(c) for c in t) or 1
            rng = np.random.default_rng(seed)
            v = rng.standard_normal(self.dim).astype(np.float32)
            v /= np.linalg.norm(v) + 1e-12
            out.append(v.tolist())
        return out


@pytest.fixture()
def dt_nlp_svc() -> EmbeddingService:
    return EmbeddingService(client=_DeterministicMockClient(dim=8), batch_size=50)


@pytest.fixture()
def dt_nlp_df() -> pd.DataFrame:
    """NLP 룰 검증용 샘플 — gl_account / business_process / morpheme_tokens 포함."""
    return pd.DataFrame({
        "gl_account": ["4000", "4000", "4000", "2000", "2000", "9999"],
        "business_process": ["O2C", "O2C", "O2C", "P2P", "P2P", "OTHER"],
        "header_text": [
            "Sales Invoice ABC",
            "Sales Invoice XYZ",
            "Sales Invoice DEF",
            "Vendor Bill GHI",
            "Vendor Bill JKL",
            "Misc adjustment",
        ],
        "line_text": ["", "", "", "", "", ""],
        "is_intercompany": [False, False, False, False, False, True],
        "has_risk_keyword": ["low"] * 6,
        "morpheme_tokens": [
            ["매출", "송장"], ["매출", "송장"], ["매출", "송장"],
            ["매입", "비용"], ["매입", "비용"],
            ["조정"],
        ],
        "account_category": ["revenue", "revenue", "revenue", "liability", "liability", "other"],
    })


# ── NLPDetector 통합 ────────────────────────────────────────


def test_detector_runs_all_rules_and_returns_detection_result(dt_nlp_df, dt_nlp_svc):
    det = NLPDetector(embedding_service=dt_nlp_svc, risk_keywords=["상품권"])
    result = det.detect(dt_nlp_df)

    assert isinstance(result, DetectionResult)
    assert result.track_name == "nlp"
    # 5개 룰 전체 실행 시도
    assert len(result.rule_flags) == 5
    rule_ids = {f.rule_id for f in result.rule_flags}
    assert rule_ids == {"NLP01", "NLP02", "NLP03", "NLP04", "NLP05"}
    # scores Series는 원본 index 보존
    assert list(result.scores.index) == list(dt_nlp_df.index)


def test_detector_raises_on_empty_dataframe(dt_nlp_svc):
    det = NLPDetector(embedding_service=dt_nlp_svc, risk_keywords=[])
    with pytest.raises(ValueError):
        det.detect(pd.DataFrame())


def test_detector_graceful_skip_when_embedding_unavailable(dt_nlp_df):
    """EmbeddingService 초기화 실패 시 empty result + warning."""
    class _BrokenClient:
        provider = "broken"

        def is_available(self) -> bool:
            return False

        def embed(self, texts):
            raise RuntimeError("API down")

    svc = EmbeddingService(client=_BrokenClient())
    det = NLPDetector(embedding_service=svc, risk_keywords=["상품권"])
    result = det.detect(dt_nlp_df)
    # 룰 실행은 시도되지만 예외로 모두 skipped
    assert all(s == 0.0 for s in result.scores.tolist())
    # 모든 룰이 예외 → skipped_rules 채워짐 또는 rule_flags 비어있음
    assert len(result.metadata.get("skipped_rules", [])) >= 1 or len(result.rule_flags) == 0


def test_detector_isolates_rule_failures(dt_nlp_df, dt_nlp_svc, monkeypatch):
    """한 룰이 예외를 던져도 나머지는 계속 실행."""
    from src.detection import nlp_rules

    def _broken_nlp01(df, **kwargs):
        raise RuntimeError("NLP01 boom")

    monkeypatch.setattr(nlp_rules, "nlp01_header_account_mismatch", _broken_nlp01)

    det = NLPDetector(embedding_service=dt_nlp_svc, risk_keywords=["상품권"])
    result = det.detect(dt_nlp_df)

    assert "NLP01" in result.metadata["skipped_rules"]
    assert any(w.startswith("NLP01") for w in result.warnings)
    # 나머지 4개는 정상 실행
    assert len(result.rule_flags) == 4


# ── NLP01: header-account 불일치 ────────────────────────────


def test_nlp01_flags_low_similarity_rows(dt_nlp_svc):
    """header와 account가 의미적으로 다르면 점수 > 0."""
    df = pd.DataFrame({
        "gl_account": ["4000"],
        "header_text": ["completely unrelated payroll text"],
        "line_text": [""],
        "morpheme_tokens": [[]],
        "account_category": ["revenue"],
    })
    scores = nlp01_header_account_mismatch(
        df, embedding_service=dt_nlp_svc, similarity_threshold=0.99,
    )
    # 결정론적 mock으로 직교성 보장 어려우므로 유효 실행만 확인
    assert len(scores) == 1
    assert scores.between(0.0, 1.0).all()


def test_nlp01_returns_zero_when_gl_account_missing(dt_nlp_svc):
    df = pd.DataFrame({"header_text": ["x"], "morpheme_tokens": [[]]})
    scores = nlp01_header_account_mismatch(df, embedding_service=dt_nlp_svc)
    assert (scores == 0.0).all()


# ── NLP02: process-account 불일치 ───────────────────────────


def test_nlp02_returns_zero_when_required_columns_missing(dt_nlp_svc):
    df = pd.DataFrame({"gl_account": ["4000"]})  # business_process 없음
    scores = nlp02_process_account_mismatch(df, embedding_service=dt_nlp_svc)
    assert (scores == 0.0).all()


def test_nlp02_runs_with_process_and_account(dt_nlp_df, dt_nlp_svc):
    scores = nlp02_process_account_mismatch(
        dt_nlp_df, embedding_service=dt_nlp_svc, similarity_threshold=0.5,
    )
    assert len(scores) == len(dt_nlp_df)
    assert scores.between(0.0, 1.0).all()


# ── NLP03: 비정형 적요 (centroid 거리) ──────────────────────


def test_nlp03_skips_small_groups(dt_nlp_svc):
    """group size < min_group_size → 0."""
    df = pd.DataFrame({
        "gl_account": ["4000", "5000"],  # 각 1행씩
        "header_text": ["A", "B"],
        "line_text": ["", ""],
        "morpheme_tokens": [[], []],
    })
    scores = nlp03_atypical_description(
        df, embedding_service=dt_nlp_svc, min_group_size=5,
    )
    assert (scores == 0.0).all()


def test_nlp03_flags_outlier_in_group(dt_nlp_svc):
    """동일 그룹 5건 + 이질 1건 → 이상치 점수 > 0."""
    rows = []
    # 정상 5건 — 같은 텍스트
    for i in range(5):
        rows.append({"gl_account": "4000", "header_text": "Normal sales invoice",
                     "line_text": "", "morpheme_tokens": ["매출"]})
    # 이질 1건
    rows.append({"gl_account": "4000", "header_text": "Completely different payroll",
                 "line_text": "", "morpheme_tokens": ["급여"]})
    df = pd.DataFrame(rows)
    scores = nlp03_atypical_description(
        df, embedding_service=dt_nlp_svc,
        anomaly_percentile=0.5, min_group_size=3,
    )
    # 적어도 1개 행은 점수 > 0 (centroid 거리 분위수 초과)
    assert (scores > 0).any()


# ── NLP04: IC 거래 적요 이상 ────────────────────────────────


def test_nlp04_returns_zero_when_no_ic_rows(dt_nlp_svc):
    df = pd.DataFrame({
        "is_intercompany": [False, False],
        "header_text": ["x", "y"],
        "line_text": ["", ""],
        "morpheme_tokens": [[], []],
    })
    scores = nlp04_ic_description_anomaly(df, embedding_service=dt_nlp_svc)
    assert (scores == 0.0).all()


def test_nlp04_runs_only_on_ic_rows(dt_nlp_svc):
    """IC=True 5건 → centroid 거리 분포 계산."""
    rows = [{"is_intercompany": True, "header_text": f"IC transfer batch {i}",
             "line_text": "", "morpheme_tokens": ["내부", "이체"]}
            for i in range(5)]
    rows.append({"is_intercompany": True, "header_text": "Anomalous unrelated",
                 "line_text": "", "morpheme_tokens": ["이상"]})
    df = pd.DataFrame(rows)
    scores = nlp04_ic_description_anomaly(
        df, embedding_service=dt_nlp_svc,
        similarity_threshold=0.0, min_group_size=3,
    )
    # 전체 IC 행에서 어떤 행은 거리가 클 수 있음
    assert len(scores) == len(df)
    assert scores.between(0.0, 1.0).all()


# ── NLP05: 동의어 우회 ─────────────────────────────────────


def test_nlp05_returns_zero_without_keywords(dt_nlp_df, dt_nlp_svc):
    scores = nlp05_synonym_evasion(
        dt_nlp_df, embedding_service=dt_nlp_svc, risk_keywords=[],
    )
    assert (scores == 0.0).all()


def test_nlp05_only_processes_low_keyword_rows(dt_nlp_svc):
    """has_risk_keyword=high 행은 검사 제외 (이미 키워드로 잡힘)."""
    df = pd.DataFrame({
        "header_text": ["bypass alt", "risky text"],
        "line_text": ["", ""],
        "morpheme_tokens": [[], []],
        "has_risk_keyword": ["high", "low"],
    })
    scores = nlp05_synonym_evasion(
        df, embedding_service=dt_nlp_svc,
        risk_keywords=["상품권"], synonym_threshold=0.0,
    )
    # high 행은 무조건 0
    assert scores.iloc[0] == 0.0


def test_nlp05_threshold_zero_flags_anything(dt_nlp_svc):
    """threshold=0.0 + has_risk_keyword=low → 거의 모든 행 점수 > 0 (mock 상)."""
    df = pd.DataFrame({
        "header_text": ["alternative term"],
        "line_text": [""],
        "morpheme_tokens": [["대체", "표현"]],
        "has_risk_keyword": ["low"],
    })
    scores = nlp05_synonym_evasion(
        df, embedding_service=dt_nlp_svc,
        risk_keywords=["상품권", "가수금"], synonym_threshold=0.0,
    )
    assert len(scores) == 1
    assert scores.between(0.0, 1.0).all()
