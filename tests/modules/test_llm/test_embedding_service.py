"""EmbeddingService 단위 테스트 — WU-21 #88.

핵심 검증:
- O(U) 캐시 — 중복 텍스트는 API 1회만 호출
- 배치 분할 — batch_size 단위로 API 호출
- 빈 문자열 graceful 처리
- numpy 행렬 연산 — cosine_similarity_matrix / pairwise / find_nearest
- compute_group_anomaly — centroid 거리 기반 이상치
- sanitize_for_embedding — 비식별화 (morpheme join / 영문 토큰)
"""

from __future__ import annotations

import numpy as np
import pytest

from src.llm.embedding_service import (
    EmbeddingService,
    sanitize_for_embedding,
)


# ── Mock EmbeddingClient ──────────────────────────────────────


class _MockEmbedClient:
    """결정론적 임베딩 — 같은 텍스트는 같은 벡터, 호출 횟수 추적."""

    provider = "mock"

    def __init__(self, dim: int = 8) -> None:
        self.dim = dim
        self.call_count = 0
        self.calls: list[list[str]] = []

    def is_available(self) -> bool:
        return True

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.call_count += 1
        self.calls.append(list(texts))
        # Why: 텍스트 hash 기반 결정론 + L2 정규화 (OpenAI 동작 시뮬레이션)
        out = []
        for t in texts:
            seed = sum(ord(c) for c in t) or 1
            rng = np.random.default_rng(seed)
            v = rng.standard_normal(self.dim).astype(np.float32)
            v /= np.linalg.norm(v) + 1e-12
            out.append(v.tolist())
        return out


@pytest.fixture()
def lm_mock_client() -> _MockEmbedClient:
    return _MockEmbedClient(dim=8)


@pytest.fixture()
def lm_svc(lm_mock_client) -> EmbeddingService:
    return EmbeddingService(client=lm_mock_client, batch_size=3)


# ── sanitize_for_embedding ───────────────────────────────────


def test_sanitize_uses_morpheme_tokens_when_available():
    """morpheme_tokens가 있으면 join 결과만 사용 — 원본 텍스트 차단."""
    out = sanitize_for_embedding(
        "원본 적요 (비식별화 차단)",
        morpheme_tokens=["영업부", "법인카드", "식대"],
    )
    assert out == "영업부 법인카드 식대"


def test_sanitize_falls_back_to_english_tokenization():
    """morpheme 없으면 영문 토큰 + stopword 제거."""
    out = sanitize_for_embedding("Vendor Invoice INV-62393960 for Office")
    # "for"는 stopword 제거, INV-... 는 토큰 분리
    assert "Vendor" in out
    assert "Invoice" in out
    assert "for" not in out.split()


def test_sanitize_empty_returns_empty_string():
    assert sanitize_for_embedding("") == ""
    assert sanitize_for_embedding(None) == ""
    assert sanitize_for_embedding("", morpheme_tokens=[]) == ""


# ── O(U) 캐시 ────────────────────────────────────────────────


def test_embed_texts_dedupe_unique_calls(lm_svc, lm_mock_client):
    """100개 입력이 모두 같으면 API 호출은 1회 (배치 1개)."""
    texts = ["같은 텍스트"] * 100
    out = lm_svc.embed_texts(texts)
    assert out.shape == (100, 8)
    # 고유값 1개 → 배치 1회만
    assert lm_mock_client.call_count == 1
    assert lm_svc.cache_size == 1


def test_embed_texts_cache_hit_skips_api(lm_svc, lm_mock_client):
    """2회 호출 — 두 번째는 캐시 hit이라 API 0회."""
    lm_svc.embed_texts(["a", "b", "c"])
    initial_calls = lm_mock_client.call_count
    out2 = lm_svc.embed_texts(["a", "b", "c"])
    assert out2.shape == (3, 8)
    assert lm_mock_client.call_count == initial_calls  # 추가 호출 없음


def test_embed_texts_batches_unique_misses(lm_svc, lm_mock_client):
    """batch_size=3, 고유 미스 7개 → 호출 3회 (3+3+1)."""
    texts = [f"unique_{i}" for i in range(7)]
    lm_svc.embed_texts(texts)
    assert lm_mock_client.call_count == 3
    sizes = [len(c) for c in lm_mock_client.calls]
    assert sorted(sizes) == [1, 3, 3]


def test_embed_texts_skips_empty_strings(lm_svc, lm_mock_client):
    """빈 문자열은 zero vector 반환 + API 호출 회피."""
    out = lm_svc.embed_texts(["valid", "", "valid"])
    assert out.shape == (3, 8)
    # 두 번째 행은 zero vector
    assert np.allclose(out[1], 0.0)
    # 호출은 'valid' 1회만
    assert lm_mock_client.call_count == 1


def test_embed_empty_input_returns_empty_array(lm_svc):
    out = lm_svc.embed_texts([])
    assert out.shape == (0, 0)


# ── 행렬 연산 유사도 ─────────────────────────────────────────


def test_cosine_similarity_matrix_shape_and_values():
    """(N, D) @ (M, D).T → (N, M). 동일 벡터는 1.0."""
    mat_a = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    mat_b = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]], dtype=np.float32)
    sims = EmbeddingService.cosine_similarity_matrix(mat_a, mat_b)
    assert sims.shape == (2, 3)
    assert sims[0, 0] == pytest.approx(1.0)  # 동일
    assert sims[0, 1] == pytest.approx(0.0)  # 직교
    assert sims[1, 1] == pytest.approx(1.0)
    assert sims[0, 2] == pytest.approx(1.0)


def test_cosine_similarity_pairwise_row_by_row():
    """1:1 행 단위 cosine. 동일이면 1.0, 직교면 0.0."""
    mat_a = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    mat_b = np.array([[1.0, 0.0], [1.0, 0.0]], dtype=np.float32)
    sims = EmbeddingService.cosine_similarity_pairwise(mat_a, mat_b)
    assert sims.shape == (2,)
    assert sims[0] == pytest.approx(1.0)
    assert sims[1] == pytest.approx(0.0)


def test_cosine_similarity_handles_unnormalized_input():
    """assume_normalized=False 시 재정규화 적용."""
    mat = np.array([[2.0, 0.0]], dtype=np.float32)  # 정규화 안된 벡터
    target = np.array([[1.0, 0.0]], dtype=np.float32)
    sims = EmbeddingService.cosine_similarity_matrix(
        mat, target, assume_normalized=False,
    )
    assert sims[0, 0] == pytest.approx(1.0)


def test_compute_group_anomaly_outlier_has_higher_distance(lm_svc):
    """정상 군집 + 이상치 1개 — 이상치 거리가 가장 큼."""
    # 정상 군집: 비슷한 방향 5개
    base = np.array([1.0, 0.0], dtype=np.float32)
    normal = np.tile(base, (5, 1))
    # 이상치: 정반대 방향
    outlier = np.array([[-1.0, 0.0]], dtype=np.float32)
    embeddings = np.concatenate([normal, outlier], axis=0)

    distances = lm_svc.compute_group_anomaly(embeddings)
    assert distances.shape == (6,)
    # 이상치(마지막)가 가장 큰 거리
    assert distances[-1] == max(distances)


def test_find_nearest_returns_topk_in_order(lm_svc):
    """top_k=2: 가장 가까운 2개를 유사도 내림차순으로 반환."""
    corpus = np.array([
        [1.0, 0.0],   # query와 동일 → top 1
        [0.0, 1.0],   # 직교
        [0.95, 0.31], # query와 매우 가까움 → top 2 (정규화 근사)
    ], dtype=np.float32)
    # 정규화
    corpus = corpus / np.linalg.norm(corpus, axis=1, keepdims=True)

    query = np.array([1.0, 0.0], dtype=np.float32)
    indices, sims = lm_svc.find_nearest(query, corpus, top_k=2)
    assert indices.tolist() == [0, 2]
    assert sims[0] >= sims[1]


def test_find_nearest_handles_empty_corpus(lm_svc):
    out_idx, out_sims = lm_svc.find_nearest(
        np.array([1.0, 0.0], dtype=np.float32),
        np.zeros((0, 2), dtype=np.float32),
        top_k=5,
    )
    assert out_idx.size == 0
    assert out_sims.size == 0
