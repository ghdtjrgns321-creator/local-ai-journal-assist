"""임베딩 서비스 — OpenAI 임베딩 API + 인메모리 캐시 + 행렬 연산 유사도.

WU-21 NLP 탐지의 토대. NLP01~NLP05 룰이 공통으로 사용한다.

핵심 최적화 2가지
-----------------
1. **O(N) → O(U) 캐시**: 동일 텍스트가 N번 등장해도 API는 고유값(Unique) 만큼만 호출.
   10만 행 적요 → 수천 건 고유값 → API 비용·레이턴시 95%+ 절감.

2. **Vectorization**: 코사인 유사도를 numpy 행렬 곱으로 일괄 계산.
   파이썬 for 루프로 N회 호출 시 발생하는 hang을 방지.
   OpenAI text-embedding-3-* 는 기본 L2 정규화 → dot product = cosine similarity.

비식별화 정책
-------------
원본 적요 전문(header_text/line_text)을 외부 API에 전달 금지.
`sanitize_for_embedding()` 으로 morpheme_tokens(한글) join 또는 영문 stopword 제거 결과만 임베딩.
"""

from __future__ import annotations

import functools
import logging
import re
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from src.llm.api_client import EmbeddingClient

logger = logging.getLogger(__name__)

# Why: 영문 stopword 최소 집합 — 적요에서 의미 단어만 남기기 위한 보수적 필터
_EN_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "with",
    }
)

# Why: 영문 토큰 추출 — 알파벳/숫자만 단어 단위로
_RE_EN_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9]+")


# ── 비식별화 토큰화 ─────────────────────────────────────────────


def sanitize_for_embedding(
    text: object,
    morpheme_tokens: list[str] | None = None,
) -> str:
    """임베딩 입력 정제 — 비식별화 보장.

    우선순위
    --------
    1. morpheme_tokens(kiwipiepy 결과)이 있으면 공백 join → 한글 적요 비식별화
    2. 영문 적요면 알파벳/숫자 토큰만 추출 + stopword 제거
    3. 빈 결과 → 빈 문자열 반환 (호출자가 스킵 판단)

    Returns:
        공백 join된 토큰 문자열. 임베딩 API 입력으로 직접 사용 가능.
    """
    if morpheme_tokens:
        # 한글 적요: 형태소 토큰만 사용 → 원본 텍스트 차단
        return " ".join(t for t in morpheme_tokens if t)

    if text is None:
        return ""
    s = str(text).strip()
    if not s:
        return ""

    # 영문 토큰 추출 + stopword 제거 (소문자 비교)
    tokens = [t for t in _RE_EN_TOKEN.findall(s) if t.lower() not in _EN_STOPWORDS]
    return " ".join(tokens)


# ── 임베딩 서비스 ───────────────────────────────────────────────


class EmbeddingService:
    """OpenAI 임베딩 + dict 캐시 + 행렬 연산 유사도.

    인스턴스 단위로 캐시를 보유하므로 짧은 파이프라인 1회 실행 내에서만 공유된다.
    프로세스 전역 캐시는 `get_embedding_service()` 싱글톤이 담당.
    """

    def __init__(
        self,
        client: "EmbeddingClient | None" = None,
        *,
        batch_size: int = 100,
    ) -> None:
        # Why: client는 lazy 초기화 — 테스트 mock 주입 + API 키 없는 환경 graceful 동작
        self._client = client
        self._cache: dict[str, list[float]] = {}
        self._batch_size = batch_size

    # ── 클라이언트 lazy load ──

    def _get_client(self) -> "EmbeddingClient":
        """API 클라이언트 lazy 초기화. 키 미설정/연결 실패 시 RuntimeError."""
        if self._client is None:
            from src.llm.api_client import get_embedding_client

            self._client = get_embedding_client()
        return self._client

    @property
    def cache_size(self) -> int:
        """현재 캐시된 고유 텍스트 수 — 디버깅/모니터링용."""
        return len(self._cache)

    # ── 핵심: O(U) 배치 임베딩 ──

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        """배치 임베딩 — 캐시 미스인 고유 텍스트만 API 호출.

        성능
        ----
        - 입력 N개 → API 호출은 고유값 U개만 (U ≤ N)
        - 빈 문자열은 zero vector로 대체 (API 호출 회피)
        - 결과는 (N, D) numpy float32 행렬 — 행렬 연산 즉시 사용 가능

        Returns:
            shape=(len(texts), embedding_dim) float32 행렬.
            입력이 모두 빈 문자열이면 (len(texts), 0) 반환.
        """
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)

        # Why: 빈 문자열은 API 호출 대상에서 제외 — 비용·오류 방지
        unique_misses = list({t for t in texts if t and t not in self._cache})

        if unique_misses:
            client = self._get_client()
            for i in range(0, len(unique_misses), self._batch_size):
                batch = unique_misses[i : i + self._batch_size]
                vectors = client.embed(batch)
                self._cache.update(zip(batch, vectors))

        # Why: 차원 결정 — 캐시에서 첫 비-empty 텍스트의 벡터 길이 사용
        first_vec = next(
            (self._cache[t] for t in texts if t and t in self._cache),
            None,
        )
        if first_vec is None:
            return np.zeros((len(texts), 0), dtype=np.float32)

        dim = len(first_vec)
        out = np.zeros((len(texts), dim), dtype=np.float32)
        for idx, text in enumerate(texts):
            if text and text in self._cache:
                out[idx] = self._cache[text]
        return out

    # ── Vectorized 유사도 ──

    @staticmethod
    def cosine_similarity_matrix(
        mat_a: np.ndarray,
        mat_b: np.ndarray,
        *,
        assume_normalized: bool = True,
    ) -> np.ndarray:
        """(N, D) @ (M, D).T → (N, M) 코사인 유사도 행렬.

        OpenAI text-embedding-3-* 는 unit length 정규화되어 반환되므로
        기본값 `assume_normalized=True` 에서 dot product만으로 cosine similarity 성립.
        직접 계산한 centroid 등 정규화가 깨진 벡터는 False 로 호출하면 재정규화 수행.
        """
        if mat_a.size == 0 or mat_b.size == 0:
            return np.zeros((mat_a.shape[0], mat_b.shape[0]), dtype=np.float32)

        if not assume_normalized:
            mat_a = _l2_normalize(mat_a)
            mat_b = _l2_normalize(mat_b)
        return mat_a @ mat_b.T

    @staticmethod
    def cosine_similarity_pairwise(
        mat_a: np.ndarray,
        mat_b: np.ndarray,
        *,
        assume_normalized: bool = True,
    ) -> np.ndarray:
        """(N, D) vs (N, D) 행단위 1:1 코사인 유사도 → (N,)."""
        if mat_a.size == 0 or mat_b.size == 0:
            return np.zeros(mat_a.shape[0], dtype=np.float32)

        if not assume_normalized:
            mat_a = _l2_normalize(mat_a)
            mat_b = _l2_normalize(mat_b)
        return np.einsum("ij,ij->i", mat_a, mat_b)

    # ── 그룹/이상치/근접 검색 ──

    def compute_group_anomaly(
        self,
        embeddings: np.ndarray,
    ) -> np.ndarray:
        """그룹 centroid 거리 기반 이상치 점수 (NLP03 용).

        centroid는 평균 후 정규화 깨지므로 재정규화 필수.
        반환값: 1.0 - cosine_similarity → 거리. 빈 입력은 빈 배열.
        """
        if embeddings.size == 0 or embeddings.shape[0] < 2:
            return np.zeros(embeddings.shape[0], dtype=np.float32)

        centroid = embeddings.mean(axis=0, keepdims=True)
        centroid = _l2_normalize(centroid)
        # Why: embeddings는 이미 정규화된 가정 — assume_normalized=True
        sims = (embeddings @ centroid.T).ravel()
        return (1.0 - sims).astype(np.float32, copy=False)

    def find_nearest(
        self,
        query_vec: np.ndarray,
        corpus_mat: np.ndarray,
        top_k: int = 5,
    ) -> tuple[np.ndarray, np.ndarray]:
        """corpus 중 query에 가장 가까운 top_k 인덱스 + 유사도.

        Returns:
            (indices, similarities) — 둘 다 길이 min(top_k, len(corpus)).
        """
        if corpus_mat.size == 0:
            return np.array([], dtype=np.int64), np.array([], dtype=np.float32)

        sims = corpus_mat @ query_vec
        k = min(top_k, sims.shape[0])
        # Why: argpartition은 부분 정렬로 O(N) — 전체 정렬보다 빠름
        idx_partition = np.argpartition(-sims, k - 1)[:k]
        ordered = idx_partition[np.argsort(-sims[idx_partition])]
        return ordered, sims[ordered]


# ── 유틸 ────────────────────────────────────────────────────────


def _l2_normalize(mat: np.ndarray) -> np.ndarray:
    """L2 정규화 — 0벡터 방어를 위해 epsilon 추가."""
    norms = np.linalg.norm(mat, axis=-1, keepdims=True)
    return mat / (norms + 1e-12)


# ── 팩토리 (싱글톤) ─────────────────────────────────────────────


@functools.lru_cache(maxsize=1)
def get_embedding_service() -> EmbeddingService:
    """프로세스 전역 EmbeddingService 싱글톤.

    Why: 캐시를 프로세스 단위로 재사용하여 반복 호출 비용 최소화.
         테스트에서는 직접 EmbeddingService(client=mock_client) 생성 권장.
    """
    return EmbeddingService()
