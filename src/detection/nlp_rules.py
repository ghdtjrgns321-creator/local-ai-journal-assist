"""NLPDetector 룰 함수 — NLP01~NLP05 (WU-21).

5개 서브룰
----------
- NLP01: header_text 의미 vs gl_account 분류 불일치 (ISA 315/240 경제적 실질)
- NLP02: business_process vs gl_account 분류 불일치
- NLP03: 비정형 적요 — gl_account 그룹 centroid 거리 상위 분위수
- NLP04: IC 거래 적요 패턴 이상 — 정상 IC 클러스터와 거리
- NLP05: risk keyword의 동의어/은어 우회 — 임베딩 유사도 매칭

성능 원칙
---------
- 모든 코사인 유사도는 numpy 행렬 곱으로 일괄 계산 (for 루프 금지)
- 임베딩은 EmbeddingService가 캐시 + O(U) 호출 보장
- 그룹 처리는 pandas groupby + numpy fancy indexing 활용
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from src.detection.boolean_utils import bool_column

if TYPE_CHECKING:
    from src.llm.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


# ── 공용 헬퍼 ───────────────────────────────────────────────────


def _sanitize_series(
    df: pd.DataFrame,
    text_col: str | None = None,
    morpheme_col: str = "morpheme_tokens",
) -> pd.Series:
    """비식별화 토큰 문자열 Series.

    morpheme_tokens가 있으면 우선 사용 (한글 적요).
    없으면 text_col에서 영문 토큰 추출. text_col=None이면 line_text+header_text.
    """
    from src.llm.embedding_service import sanitize_for_embedding

    if text_col is not None and text_col in df.columns:
        base = df[text_col].fillna("").astype(str)
    else:
        line = df.get("line_text", pd.Series("", index=df.index)).fillna("")
        header = df.get("header_text", pd.Series("", index=df.index)).fillna("")
        base = (line.astype(str) + " " + header.astype(str)).str.strip()

    has_morpheme = morpheme_col in df.columns
    return pd.Series(
        [
            sanitize_for_embedding(
                text,
                morpheme_tokens=df[morpheme_col].iloc[i] if has_morpheme else None,
            )
            for i, text in enumerate(base)
        ],
        index=df.index,
        dtype="string",
    )


def _embed_with_positions(
    svc: EmbeddingService,
    series: pd.Series,
) -> tuple[np.ndarray, np.ndarray]:
    """비어있지 않은 텍스트만 임베딩 → (embeddings, positional_idx).

    positional_idx: series 내 0-based 위치. 빈 문자열은 제외.
    """
    texts = series.tolist()
    valid_pos = np.asarray(
        [i for i, t in enumerate(texts) if t and len(str(t)) > 0],
        dtype=np.int64,
    )
    if valid_pos.size == 0:
        return np.zeros((0, 0), dtype=np.float32), valid_pos

    valid_texts = [texts[i] for i in valid_pos]
    embeddings = svc.embed_texts(valid_texts)
    return embeddings, valid_pos


# ── NLP01: header-account 의미 불일치 ──────────────────────────


def nlp01_header_account_mismatch(
    df: pd.DataFrame,
    *,
    embedding_service: EmbeddingService,
    similarity_threshold: float = 0.30,
) -> pd.Series:
    """NLP01: header_text 의미와 gl_account 카테고리의 임베딩 유사도 < threshold.

    로직:
      1. 각 행: header 텍스트(morpheme join) → embed
      2. 각 행: account_category(없으면 gl_account 코드) → embed
      3. 행단위 1:1 cosine — assume_normalized=True (OpenAI L2 정규화)
      4. similarity < threshold → 점수 = (threshold - similarity) / threshold (0~1)

    필수 컬럼: gl_account
    선택 컬럼: account_category (있으면 의미 분류 사용), morpheme_tokens
    """
    scores = pd.Series(0.0, index=df.index, dtype=float)
    if "gl_account" not in df.columns:
        return scores

    # 1. 행별 적요 임베딩
    header_series = _sanitize_series(df)
    header_emb, valid_pos = _embed_with_positions(embedding_service, header_series)
    if header_emb.size == 0:
        return scores

    # 2. 각 행의 account 라벨 임베딩 — 카테고리 우선, 없으면 코드
    if "account_category" in df.columns:
        account_labels = df["account_category"].fillna("").astype(str)
    else:
        account_labels = df["gl_account"].fillna("").astype(str)

    valid_labels = account_labels.iloc[valid_pos].tolist()
    label_emb = embedding_service.embed_texts(valid_labels)
    if label_emb.size == 0 or label_emb.shape != header_emb.shape:
        return scores

    # 3. 1:1 cosine — 행 단위 dot product
    sims = embedding_service.cosine_similarity_pairwise(
        header_emb,
        label_emb,
        assume_normalized=True,
    )

    # 4. 임계 미만 → 점수화
    deficit = np.clip((similarity_threshold - sims) / max(similarity_threshold, 1e-9), 0.0, 1.0)
    target_idx = df.index[valid_pos]
    scores.loc[target_idx] = deficit.astype(float)
    return scores


# ── NLP02: process-account 의미 불일치 ─────────────────────────


def nlp02_process_account_mismatch(
    df: pd.DataFrame,
    *,
    embedding_service: EmbeddingService,
    similarity_threshold: float = 0.30,
) -> pd.Series:
    """NLP02: business_process와 gl_account 카테고리의 임베딩 유사도 < threshold.

    예: business_process="O2C"(매출) + gl_account=2000(매입채무) → 부정합.
    카테고리가 없으면 코드 비교로 폴백 (정확도 떨어지나 graceful).
    """
    scores = pd.Series(0.0, index=df.index, dtype=float)
    required = {"business_process", "gl_account"}
    if not required.issubset(df.columns):
        return scores

    process = df["business_process"].fillna("").astype(str)
    if "account_category" in df.columns:
        account_labels = df["account_category"].fillna("").astype(str)
    else:
        account_labels = df["gl_account"].fillna("").astype(str)

    valid_mask = (process.str.len() > 0) & (account_labels.str.len() > 0)
    if not valid_mask.any():
        return scores

    valid_idx = df.index[valid_mask]
    proc_texts = process[valid_mask].tolist()
    acc_texts = account_labels[valid_mask].tolist()

    proc_emb = embedding_service.embed_texts(proc_texts)
    acc_emb = embedding_service.embed_texts(acc_texts)
    if proc_emb.size == 0 or acc_emb.size == 0 or proc_emb.shape != acc_emb.shape:
        return scores

    sims = embedding_service.cosine_similarity_pairwise(proc_emb, acc_emb)
    deficit = np.clip((similarity_threshold - sims) / max(similarity_threshold, 1e-9), 0.0, 1.0)
    scores.loc[valid_idx] = deficit.astype(float)
    return scores


# ── NLP03: 비정형 적요 (centroid 거리 이상치) ──────────────────


def nlp03_atypical_description(
    df: pd.DataFrame,
    *,
    embedding_service: EmbeddingService,
    anomaly_percentile: float = 0.95,
    min_group_size: int = 5,
) -> pd.Series:
    """NLP03: gl_account 그룹 내 centroid 거리 상위 분위수 → 비정형.

    같은 계정 내에서 적요가 군집과 멀면 의미적 이상.
    그룹 규모가 min_group_size 미만이면 신뢰도 부족 → 스킵.
    """
    scores = pd.Series(0.0, index=df.index, dtype=float)
    if "gl_account" not in df.columns:
        return scores

    series = _sanitize_series(df)
    embeddings, valid_pos = _embed_with_positions(embedding_service, series)
    if embeddings.size == 0:
        return scores

    valid_idx = df.index[valid_pos]
    valid_groups = df.loc[valid_idx, "gl_account"].fillna("").astype(str)

    # 그룹별 처리 — embeddings 행 인덱스로 fancy slicing
    for account, mask in valid_groups.groupby(valid_groups).groups.items():
        positions = np.asarray(
            [valid_idx.get_loc(i) for i in mask],
            dtype=np.int64,
        )
        if positions.size < min_group_size:
            continue

        group_emb = embeddings[positions]
        # compute_group_anomaly: 1 - cosine to centroid
        distances = embedding_service.compute_group_anomaly(group_emb)

        # 분위수 임계 — 그룹 내 상위 5%만 플래그
        if distances.size < 2:
            continue
        threshold_dist = float(np.quantile(distances, anomaly_percentile))
        if threshold_dist <= 0:
            continue

        # 거리 정규화: threshold 초과분 / (1.0 - threshold) → 0~1
        anomaly_scores = np.clip(
            (distances - threshold_dist) / max(1.0 - threshold_dist, 1e-9),
            0.0,
            1.0,
        )
        target_idx = valid_idx[positions]
        scores.loc[target_idx] = anomaly_scores.astype(float)

    return scores


# ── NLP04: IC 거래 적요 패턴 이상 ──────────────────────────────


def nlp04_ic_description_anomaly(
    df: pd.DataFrame,
    *,
    embedding_service: EmbeddingService,
    similarity_threshold: float = 0.50,
    min_group_size: int = 5,
) -> pd.Series:
    """NLP04: IC 거래(is_intercompany=True) 적요가 정상 IC 클러스터 centroid와 거리 큰 행.

    필수 컬럼: is_intercompany
    """
    scores = pd.Series(0.0, index=df.index, dtype=float)
    if "is_intercompany" not in df.columns:
        return scores

    ic_mask = bool_column(df, "is_intercompany")
    if ic_mask.sum() < min_group_size:
        return scores

    ic_df = df.loc[ic_mask]
    series = _sanitize_series(ic_df)
    embeddings, valid_pos = _embed_with_positions(embedding_service, series)
    if embeddings.size == 0 or valid_pos.size < min_group_size:
        return scores

    # IC 전체 클러스터 centroid 거리
    distances = embedding_service.compute_group_anomaly(embeddings)
    if distances.size == 0:
        return scores

    # threshold = 1 - similarity_threshold (유사도 임계 → 거리 임계)
    distance_threshold = 1.0 - similarity_threshold
    over = np.clip(
        (distances - distance_threshold) / max(1.0 - distance_threshold, 1e-9),
        0.0,
        1.0,
    )

    target_idx = ic_df.index[valid_pos]
    scores.loc[target_idx] = over.astype(float)
    return scores


# ── NLP05: risk keyword 동의어 우회 ────────────────────────────


def nlp05_synonym_evasion(
    df: pd.DataFrame,
    *,
    embedding_service: EmbeddingService,
    risk_keywords: list[str],
    synonym_threshold: float = 0.70,
) -> pd.Series:
    """NLP05: has_risk_keyword=low인데 risk keyword 임베딩과 유사도 > threshold → 우회 의심.

    예: "상품권" 키워드 등록 → 적요 "기프트카드"가 임베딩상 유사 → 플래그.
    """
    scores = pd.Series(0.0, index=df.index, dtype=float)
    if not risk_keywords:
        return scores

    # has_risk_keyword=low 행만 검사 (기존 키워드 매칭으로 잡힌 행은 중복 회피)
    if "has_risk_keyword" in df.columns:
        candidate_mask = df["has_risk_keyword"].fillna("low").astype(str) == "low"
    else:
        candidate_mask = pd.Series(True, index=df.index)
    if not candidate_mask.any():
        return scores

    candidate_df = df.loc[candidate_mask]
    series = _sanitize_series(candidate_df)
    desc_emb, valid_pos = _embed_with_positions(embedding_service, series)
    if desc_emb.size == 0:
        return scores

    # 키워드 임베딩은 캐시에 영구 저장 (반복 호출 비용 0)
    keyword_emb = embedding_service.embed_texts(list(risk_keywords))
    if keyword_emb.size == 0 or keyword_emb.shape[1] != desc_emb.shape[1]:
        return scores

    # (N, D) @ (K, D).T → (N, K) — 한 번에 모든 쌍 계산
    sim_matrix = embedding_service.cosine_similarity_matrix(desc_emb, keyword_emb)
    # 행별 최대 유사도 — 가장 가까운 키워드에 매칭
    max_sims = sim_matrix.max(axis=1)

    # threshold 초과분만 점수화
    over = np.clip(
        (max_sims - synonym_threshold) / max(1.0 - synonym_threshold, 1e-9),
        0.0,
        1.0,
    )
    target_idx = candidate_df.index[valid_pos]
    scores.loc[target_idx] = over.astype(float)
    return scores
