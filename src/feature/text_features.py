"""텍스트 기반 감사 파생변수 생성 모듈.

L3-08 룰 + WU-19 NLP 기초 — description_quality, has_risk_keyword, morpheme_tokens.
ingest 완료된 표준 DataFrame을 입력으로 받는다.

핵심 설계 — 같은 원본 텍스트를 **2가지 버전**으로 정제:
  combined_text : strip()만 → description_quality (결손/파손 여부)
  cleaned_text  : 한글+영숫자 외 제거 → has_risk_keyword (은폐 패턴 관통)

WU-19: kiwipiepy 형태소 분석 — morpheme_tokens (list[str]).
  한국어만 분기 (`_has_korean`), Kiwi iterable 입력으로 C++ 멀티스레딩 활용.
  WU-21(NLP 탐지)·WU-11(description_quality 고도화)의 전처리 단계.
"""

from __future__ import annotations

import logging
import re

import numpy as np
import pandas as pd

from config.settings import AuditSettings, get_risk_keywords, get_settings

logger = logging.getLogger(__name__)

# 키워드 매칭 전용 — 한글+영숫자 외 모든 문자 제거
_RE_STRIP_ALL = re.compile(r"[^가-힣a-zA-Z0-9]")

# 노이즈 패턴: 자음/모음 단독, 특수문자만, 동일 문자 3회+ 반복, 다문자 패턴 3회+ 반복
_RE_JAMO_ONLY = re.compile(r"^[ㄱ-ㅎㅏ-ㅣ]+$")
_RE_SPECIAL_ONLY = re.compile(r"^[^가-힣a-zA-Z0-9]+$")
_RE_REPEAT_CHAR = re.compile(r"^(.)\1{2,}$")
# 한계: 공백 포함 반복("비품 비품 비품")은 TTR 체크에서 처리됨
_RE_REPEAT_WORD = re.compile(r"^(.{2,})\1{2,}$")  # "비품비품비품" (2글자+가 3회+ 반복)
_GARBAGE_TOKENS = frozenset({"x", "xx", "n/a", "na", "null", "none"})

# 한글 음절 탐지 — _has_korean 분기용 (kiwipiepy 호출 회피)
_RE_HANGUL = re.compile(r"[가-힣]")

# 의미 있는 형태소 태그 — WU-19 기본 정책
#   NNG(일반명사) / NNP(고유명사) / VV(동사) / VA(형용사)
#   NNB(의존명사)·MAG(부사)는 content density가 낮아 제외 (WU-21에서 필요시 확장)
_MORPHEME_TAGS = frozenset({"NNG", "NNP", "VV", "VA"})

# Kiwi 인스턴스 싱글톤 — 모듈 import 시 강제 로드 회피 (~1초/~100MB)
_KIWI_INSTANCE = None


# ── Private helpers ──────────────────────────────────────────────


def _combine_text(df: pd.DataFrame) -> pd.Series:
    """line_text + header_text 결합 (벡터화).

    둘 다 있으면 공백으로 concat — 정보 손실 방지.
    Why: "식대"(line) + "3월 영업부 법인카드"(header) → normal로 구제.
    """
    empty = pd.Series("", index=df.index)
    line = df["line_text"].fillna("") if "line_text" in df.columns else empty
    header = df["header_text"].fillna("") if "header_text" in df.columns else empty
    combined = (line.astype(str) + " " + header.astype(str)).str.strip()
    return combined.replace("", pd.NA)


def _text_field_missing(df: pd.DataFrame, column: str) -> pd.Series:
    """Return True when a text field is absent, null, or blank."""
    if column not in df.columns:
        return pd.Series(True, index=df.index)
    return df[column].isna() | df[column].astype(str).str.strip().eq("")


def _clean_for_keyword(series: pd.Series) -> pd.Series:
    """키워드 매칭 전용 정제 — 한글+영숫자 외 제거.

    Why: "상 품 권", "[상품권]", "상품/권" → "상품권"으로 통일.
    description_quality에서는 사용하지 않음 (strip 원본 길이 사용).
    NaN/None → fillna("") → 빈 문자열 → _match_risk_level에서 "low" 반환.
    """
    return series.fillna("").astype(str).str.replace(_RE_STRIP_ALL, "", regex=True)


def _is_noise_pattern(text: str) -> bool:
    """노이즈 패턴 탐지 — noise는 poor에 병합.

    자음/모음 단독(ㅋㅋㅋ), 특수문자만(...), 동일 문자 반복(aaa).
    """
    if not text:
        return False
    normalized = text.strip().lower()
    return bool(
        normalized in _GARBAGE_TOKENS
        or _RE_JAMO_ONLY.match(text)
        or _RE_SPECIAL_ONLY.match(text)
        or _RE_REPEAT_CHAR.match(text)
        or _RE_REPEAT_WORD.match(text)
    )


def _compute_ttr(text: str) -> float:
    """어휘 다양성 (Type-Token Ratio) — unique_tokens / total_tokens.

    Phase 2: Python split() 사용 (kiwipiepy는 Phase 3).
    빈 텍스트 → 0.0 (poor 판정 유도).
    """
    tokens = text.split()
    if len(tokens) == 0:
        return 0.0
    return len(set(tokens)) / len(tokens)


def _compute_entropy(text: str) -> float:
    """문자 단위 Shannon Entropy — H = -sum(p(c) * log2(p(c))).

    Why: 극저 엔트로피("aaaa" → H≈0)는 의도적 난독화·패딩 의심.
    Counter(CPython C구현) + np.log2 벡터 연산으로 빈도 계산 최적화.
    성능 한계: add_description_quality의 map() 행별 콜백 내 호출 — Phase 2에서 벡터화 고려.
    빈 문자열 → 0.0 (poor 판정 유도).
    """
    if len(text) == 0:
        return 0.0
    from collections import Counter

    counts = np.array(list(Counter(text).values()), dtype=float)
    probs = counts / counts.sum()
    return float(-np.sum(probs * np.log2(probs)))


def _match_risk_level(
    cleaned: str,
    high: list[str],
    medium: list[str],
) -> str:
    """정제 텍스트에 대해 부분 매칭 — high 우선.

    Why: 한 전표에 high+medium 키워드가 동시 존재할 때 위험도 과소평가 방지.
    """
    for kw in high:
        if kw in cleaned:
            return "high"
    for kw in medium:
        if kw in cleaned:
            return "medium"
    return "low"


# ── WU-19: kiwipiepy 형태소 분석 ─────────────────────────────────


def _has_korean(text: object) -> bool:
    """한글 음절 1자라도 포함되어 있으면 True.

    Why: kiwipiepy는 한글 전용 — 영문/숫자만 있는 적요는 Kiwi 호출 자체를 회피해야
    불필요한 C++ 레이어 진입 비용을 줄일 수 있다.

    `pd.isna`는 None·np.nan·pd.NA·float('nan')을 모두 True로 판정하므로 하나의 가드로
    통합한다. list 등 pd.isna가 TypeError를 내는 타입은 정상 str 경로로 처리.
    """
    try:
        if pd.isna(text):
            return False
    except (TypeError, ValueError):
        pass
    return bool(_RE_HANGUL.search(str(text)))


def _get_kiwi():
    """Kiwi 인스턴스 싱글톤 + lazy import.

    Why: Kiwi 로딩은 ~1초, ~100MB 메모리. 모듈 import 시점에 강제 로드하면 테스트/CI
    부담이 커지고, nlp 그룹 미설치 환경에서는 text_features 모듈 자체가 import 실패.
    Lazy load + 싱글톤으로 두 문제를 동시에 해결한다.
    """
    global _KIWI_INSTANCE
    if _KIWI_INSTANCE is None:
        try:
            from kiwipiepy import Kiwi
        except ImportError as e:  # pragma: no cover - 환경 의존
            raise ImportError(
                "kiwipiepy가 설치되지 않았습니다. `uv sync --group nlp` 실행 필요."
            ) from e
        _KIWI_INSTANCE = Kiwi()
    return _KIWI_INSTANCE


def _tokenize_kiwi(texts: list[str]) -> list[list[str]]:
    """배치 토큰화 — Kiwi iterable 입력으로 C++ 멀티스레딩(GIL 해제) 활용.

    Why:
      - `kiwi.tokenize(list[str])`는 내부적으로 GIL을 해제하고 C++ 레이어에서
        병렬 토큰화 → 수십만 전표 규모에서 Python for-loop 오버헤드 누적 방지.
      - 한국어 없는 행은 미리 걸러내 Kiwi 호출 자체를 회피.
      - 원본 인덱스 보존을 위해 (idx, text) 쌍으로 필터링 → 결과 역매핑.
    """
    # 1) 전체 결과를 빈 리스트로 초기화 (영문/빈값 → [])
    results: list[list[str]] = [[] for _ in range(len(texts))]

    # 2) 반복 적요가 많으므로 unique 텍스트 단위로만 Kiwi를 호출한다.
    text_to_indices: dict[str, list[int]] = {}
    for i, text in enumerate(texts):
        if _has_korean(text):
            text_to_indices.setdefault(text, []).append(i)

    # 3) 한국어가 하나라도 있을 때만 Kiwi 싱글톤 로드 + 배치 호출
    if text_to_indices:
        unique_texts = list(text_to_indices.keys())
        kiwi = _get_kiwi()
        for text, tokens in zip(unique_texts, kiwi.tokenize(unique_texts)):
            forms = [t.form for t in tokens if t.tag in _MORPHEME_TAGS]
            for idx in text_to_indices[text]:
                results[idx] = forms

    return results


# ── Public feature functions ─────────────────────────────────────


def add_description_quality(
    df: pd.DataFrame,
    min_length: int = 3,
    ttr_threshold: float = 0.3,
    entropy_threshold: float = 1.0,
) -> pd.DataFrame:
    """L3-08: 적요 결손/파손 3단계 — missing / corrupted / normal.

    Phase 1에서는 설명의 의미적 충분성을 판단하지 않는다.
    공백/누락은 missing, 특수문자·자모·명백한 반복 문자열은 corrupted,
    그 외는 normal로 둔다. min_length/ttr/entropy 인자는 과거 API 호환용으로만 유지한다.
    """
    _ = (min_length, ttr_threshold, entropy_threshold)
    combined = _combine_text(df)
    text_cols = [col for col in ("line_text", "header_text", "description") if col in df.columns]

    def _classify(text: object) -> str:
        if pd.isna(text):
            return "missing"
        s = str(text)
        if _is_noise_pattern(s):
            return "corrupted"
        return "normal"

    df["description_quality"] = combined.map(_classify)
    if text_cols:
        per_field_noise = pd.Series(False, index=df.index)
        any_present = pd.Series(False, index=df.index)
        all_present_noise = pd.Series(True, index=df.index)
        for col in text_cols:
            values = df[col]
            present = values.notna() & values.astype(str).str.strip().ne("")
            noise = (
                values.fillna("").astype(str).map(lambda value: _is_noise_pattern(value.strip()))
            )
            any_present = any_present | present
            all_present_noise = all_present_noise & (~present | noise)
            per_field_noise = per_field_noise | (present & noise)
        # Handles cases like line_text='x' and header_text='x'. The combined
        # string is "x x", but every populated source field is still garbage.
        df.loc[
            any_present & per_field_noise & all_present_noise,
            "description_quality",
        ] = "corrupted"
    add_description_diagnostics(df)
    return df


def add_description_diagnostics(df: pd.DataFrame) -> pd.DataFrame:
    """Add Phase 1 operational diagnostics for description coverage.

    These columns do not make the L3-08 rule smarter. They explain whether the hit came
    from both fields being empty, a line-only gap, or explicit corruption.
    """
    line_missing = _text_field_missing(df, "line_text")
    header_missing = _text_field_missing(df, "header_text")

    df["description_line_missing"] = line_missing
    df["description_header_missing"] = header_missing
    df["description_both_missing"] = line_missing & header_missing
    df["description_line_missing_header_present"] = line_missing & ~header_missing
    df["description_is_missing_or_corrupted"] = df["description_quality"].isin(
        ["missing", "corrupted", "poor"]
    )
    return df


def build_description_quality_profile(
    df: pd.DataFrame,
    group_cols: tuple[str, ...] = ("source", "business_process", "document_type"),
) -> pd.DataFrame:
    """Summarize description coverage by available operational dimensions.

    Intended for Phase 1 diagnostics, not for changing L3-08 flags.
    """
    if "description_quality" not in df.columns:
        add_description_quality(df)

    available = [col for col in group_cols if col in df.columns]
    if not available:
        available = ["__all__"]
        work = df.copy()
        work["__all__"] = "all"
    else:
        work = df

    metrics = [
        "description_both_missing",
        "description_line_missing_header_present",
        "description_is_missing_or_corrupted",
    ]
    missing_metrics = [col for col in metrics if col not in work.columns]
    if missing_metrics:
        add_description_diagnostics(work)

    grouped = work.groupby(available, dropna=False)
    profile = grouped.agg(
        row_count=("description_quality", "size"),
        missing_or_corrupted_rows=("description_is_missing_or_corrupted", "sum"),
        both_missing_rows=("description_both_missing", "sum"),
        line_missing_header_present_rows=("description_line_missing_header_present", "sum"),
    ).reset_index()

    denominator = profile["row_count"].where(profile["row_count"] > 0, 1)
    profile["missing_or_corrupted_rate"] = profile["missing_or_corrupted_rows"] / denominator
    profile["both_missing_rate"] = profile["both_missing_rows"] / denominator
    profile["line_missing_header_present_rate"] = (
        profile["line_missing_header_present_rows"] / denominator
    )
    if "__all__" in profile.columns:
        profile = profile.drop(columns=["__all__"])
    return profile


def add_has_risk_keyword(
    df: pd.DataFrame,
    risk_kw: dict[str, list[str]] | None = None,
) -> pd.DataFrame:
    """L3-08: 위험 키워드 등급 — high / medium / low.

    cleaned_text(완전 정제 버전) 사용 — 은폐 패턴 관통.
    risk_kw 직접 주입 가능 (테스트 용이), 미지정 시 YAML 로드.
    """
    kw = risk_kw or get_risk_keywords()
    high = kw.get("high_risk", [])
    medium = kw.get("medium_risk", [])

    combined = _combine_text(df)
    cleaned = _clean_for_keyword(combined)

    df["has_risk_keyword"] = cleaned.map(lambda t: _match_risk_level(t, high, medium))
    return df


def add_morpheme_features(df: pd.DataFrame) -> pd.DataFrame:
    """WU-19: 한국어 형태소 토큰 리스트 컬럼 추가.

    출력:
      morpheme_tokens (list[str]) — 명사+동사 형태소 (NNG/NNP/VV/VA)

    입력 분기:
      - 한국어 포함 → kiwipiepy로 토큰화 후 의미 태그만 필터
      - 영문/빈값/NaN → [] (WU-21 다운스트림에서 len(tokens) == 0으로 판단)

    Why: WU-21(NLP 탐지), WU-11(description_quality 고도화)의 전처리 단계.
    이 함수는 토큰 리스트만 제공하고 멈춘다 — noun_count·morpheme_ttr·임베딩 등
    파생 지표는 각 다운스트림 WU에서 계산 (YAGNI).
    """
    combined = _combine_text(df)  # 기존 helper 재사용 (line + header concat)
    texts = combined.fillna("").astype(str).tolist()
    df["morpheme_tokens"] = _tokenize_kiwi(texts)
    return df


# ── WU-21: 임베딩 기반 의미 피처 ─────────────────────────────────


def add_semantic_similarity(
    df: pd.DataFrame,
    embedding_service: object | None = None,
    *,
    min_group_size: int = 5,
) -> pd.DataFrame:
    """WU-21 #88: gl_account 그룹 내 적요 임베딩 코사인 유사도.

    추가 컬럼:
      - semantic_similarity (float, 0.0~1.0): 그룹 centroid와 각 행의 코사인 유사도.
        값이 낮을수록 같은 계정 내에서 적요가 이질적 → 계정 오분류·위장거래 의심.

    동작:
      - morpheme_tokens(있으면) → 비식별화 입력 → 임베딩
      - gl_account별 그룹 centroid → 각 행과의 cosine
      - min_group_size 미만 그룹은 NaN (신뢰도 부족)
      - 임베딩 서비스 불가 시 NaN 컬럼 + warning (graceful)

    Why: ISA 315 사업체와 환경 이해 — 같은 계정에서 적요 패턴이 급변하면
         경제적 실질이 다른 거래 의심.
    """
    if "gl_account" not in df.columns:
        logger.warning("add_semantic_similarity: gl_account 컬럼 없음 — 스킵")
        df["semantic_similarity"] = np.nan
        return df

    svc = _resolve_embedding_service(embedding_service)
    if svc is None:
        df["semantic_similarity"] = np.nan
        return df

    # 비식별화 입력 준비
    sanitized = _sanitize_rows(df)
    valid_mask = sanitized.str.len() > 0
    if not valid_mask.any():
        df["semantic_similarity"] = np.nan
        return df

    try:
        valid_texts = sanitized[valid_mask].tolist()
        embeddings = svc.embed_texts(valid_texts)
    except Exception as exc:
        logger.warning("add_semantic_similarity 임베딩 실패 — 스킵: %s", exc)
        df["semantic_similarity"] = np.nan
        return df

    if embeddings.size == 0:
        df["semantic_similarity"] = np.nan
        return df

    # gl_account별 centroid 거리 → 유사도
    similarity = pd.Series(np.nan, index=df.index, dtype=float)
    valid_idx = df.index[valid_mask]
    valid_groups = df.loc[valid_idx, "gl_account"].astype(str)

    for account, positions in _group_positions(valid_groups).items():
        if len(positions) < min_group_size:
            continue
        # Why: positions는 valid_texts(=embeddings) 내 위치
        group_emb = embeddings[positions]
        # centroid는 정규화 깨지므로 재정규화 후 dot
        centroid = group_emb.mean(axis=0)
        norm = np.linalg.norm(centroid) + 1e-12
        centroid = centroid / norm
        sims = group_emb @ centroid  # (G,) 1회 행렬 곱
        # valid_idx[positions] → 원본 df index 매핑
        target_idx = valid_idx[positions]
        similarity.loc[target_idx] = sims.astype(float)

    df["semantic_similarity"] = similarity
    return df


def add_account_semantic(
    df: pd.DataFrame,
    chat_client: object | None = None,
    *,
    max_accounts: int = 200,
) -> pd.DataFrame:
    """WU-21 #85: GL 계정명 카테고리 분류 + 적요 교차 검증.

    추가 컬럼:
      - account_category (str): revenue/expense/asset/liability/equity/suspense/payroll/...
      - account_desc_match (bool): 적요(combined_text)에 카테고리 시그널이 있는가

    실행:
      - 기본 active path에서는 외부 client를 자동 생성하지 않고 graceful skip한다.
      - 테스트/실험에서 명시 주입한 client가 있을 때만 계정 카테고리 분류를 수행한다.
      - 결과는 dict 캐시 → DataFrame.map으로 일괄 적용한다.

    client 부재 시 graceful skip: 컬럼 NaN/False.
    """
    if "gl_account" not in df.columns:
        logger.warning("add_account_semantic: gl_account 컬럼 없음 — 스킵")
        df["account_category"] = pd.NA
        df["account_desc_match"] = False
        return df

    unique_accounts = df["gl_account"].dropna().astype(str).unique().tolist()
    if not unique_accounts:
        df["account_category"] = pd.NA
        df["account_desc_match"] = False
        return df

    # Why: 비용 상한 — 너무 많은 계정 수면 사용자 확인 후 수동 확장
    if len(unique_accounts) > max_accounts:
        logger.warning(
            "add_account_semantic: 고유 gl_account %d개 > max_accounts %d — 상위 %d개만 처리",
            len(unique_accounts),
            max_accounts,
            max_accounts,
        )
        unique_accounts = unique_accounts[:max_accounts]

    client = _resolve_chat_client(chat_client)
    if client is None:
        df["account_category"] = pd.NA
        df["account_desc_match"] = False
        return df

    try:
        category_map = _classify_accounts_with_client(client, unique_accounts)
    except Exception as exc:
        logger.warning("add_account_semantic client 분류 실패 — 스킵: %s", exc)
        df["account_category"] = pd.NA
        df["account_desc_match"] = False
        return df

    df["account_category"] = df["gl_account"].astype(str).map(category_map)

    # 적요-카테고리 교차 검증 (가벼운 키워드 매칭으로 1차 시그널만)
    combined = _combine_text(df).fillna("").astype(str).str.lower()
    df["account_desc_match"] = [
        _category_in_text(cat, txt) if pd.notna(cat) else False
        for cat, txt in zip(df["account_category"], combined)
    ]
    return df


# ── WU-21 헬퍼 ──────────────────────────────────────────────────


def _resolve_embedding_service(svc: object | None):
    """Return an explicitly injected embedding service, or None."""
    if svc is not None:
        return svc
    logger.info("EmbeddingService 자동 초기화 비활성 — semantic_similarity 스킵")
    return None


def _resolve_chat_client(client: object | None):
    """Return an explicitly injected classification client, or None."""
    if client is not None:
        return client
    logger.info("ChatClient 자동 초기화 비활성 — account_semantic 스킵")
    return None


def _sanitize_rows(df: pd.DataFrame) -> pd.Series:
    """각 행의 임베딩 입력 문자열 — 비식별화 보장.

    morpheme_tokens 있으면 우선 사용, 없으면 combined_text(영문) 토큰화.
    """
    combined = _combine_text(df).fillna("")
    if "morpheme_tokens" in df.columns:
        return pd.Series(
            [
                _sanitize_for_embedding(text, morpheme_tokens=tokens)
                for text, tokens in zip(combined, df["morpheme_tokens"])
            ],
            index=df.index,
            dtype="string",
        )
    return pd.Series(
        [_sanitize_for_embedding(text) for text in combined],
        index=df.index,
        dtype="string",
    )


def _sanitize_for_embedding(text: object, morpheme_tokens: object | None = None) -> str:
    """Local minimal sanitizer used when an injected embedding service is supplied."""
    if isinstance(morpheme_tokens, (list, tuple)):
        tokens = [str(token).strip() for token in morpheme_tokens if str(token).strip()]
        if tokens:
            return " ".join(tokens)
    return str(text or "").strip()


def _group_positions(group_series: pd.Series) -> dict[str, np.ndarray]:
    """그룹 키 → 해당 행의 0-based positional index 배열.

    Why: embeddings 배열이 valid_texts 순서로 정렬되어 있으므로,
         원본 df index가 아닌 positional index로 슬라이싱해야 함.
    """
    out: dict[str, list[int]] = {}
    for pos, key in enumerate(group_series.tolist()):
        out.setdefault(str(key), []).append(pos)
    return {k: np.asarray(v, dtype=np.int64) for k, v in out.items()}


# 카테고리 → 시그널 키워드 (account_desc_match 1차 매칭용)
_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "revenue": ("매출", "수익", "sales", "revenue", "income"),
    "expense": ("비용", "expense", "cost", "fee"),
    "asset": ("자산", "asset", "investment"),
    "liability": ("부채", "liability", "loan", "차입"),
    "equity": ("자본", "equity", "capital"),
    "suspense": ("가수금", "가지급", "임시", "suspense", "temp", "tbd"),
    "payroll": ("급여", "임금", "payroll", "salary", "wage"),
    "tax": ("세금", "부가세", "tax", "vat"),
    "cash": ("현금", "예금", "cash", "bank"),
}


def _category_in_text(category: object, text: str) -> bool:
    """카테고리 시그널 키워드가 적요에 있으면 True.

    Why: 분류 결과가 적요와 의미적으로 정합인지 1차 키워드 매칭 검증.
         최종 임베딩 유사도 검증은 NLP01 룰이 담당 — 여기는 빠른 보조 신호.
    """
    cat = str(category).lower() if pd.notna(category) else ""
    keywords = _CATEGORY_KEYWORDS.get(cat, ())
    if not keywords:
        return False
    return any(kw in text for kw in keywords)


def _classify_accounts_with_client(client: object, accounts: list[str]) -> dict[str, str]:
    """Classify GL account codes/names with an explicitly injected client.

    Returns:
        {account_str: category} 매핑. 실패 분만 누락.
    """
    schema = {
        "type": "object",
        "properties": {
            "classifications": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "account": {"type": "string"},
                        "category": {
                            "type": "string",
                            "enum": list(_CATEGORY_KEYWORDS.keys()) + ["other"],
                        },
                    },
                },
            }
        },
    }
    prompt = (
        "You classify accounting GL account codes/names into one of these categories: "
        f"{', '.join(_CATEGORY_KEYWORDS.keys())}, other. "
        "Return JSON {classifications: [{account, category}, ...]} for every input account.\n\n"
        f"Accounts: {accounts}"
    )
    raw = client.chat(
        messages=[
            {"role": "system", "content": "You are an audit assistant. Reply with strict JSON."},
            {"role": "user", "content": prompt},
        ],
        format=schema,
    )
    import json

    parsed = json.loads(raw)
    out: dict[str, str] = {}
    for item in parsed.get("classifications", []):
        acc = item.get("account")
        cat = item.get("category")
        if acc and cat:
            out[str(acc)] = str(cat)
    return out


# ── Orchestrator ─────────────────────────────────────────────────


def add_all_text_features(
    df: pd.DataFrame,
    settings: AuditSettings | None = None,
    risk_kw: dict | None = None,
    *,
    include_morpheme_tokens: bool = True,
) -> pd.DataFrame:
    """텍스트 파생변수를 한번에 추가. engine.py 진입점.

    생성 컬럼:
      - description_quality : missing / corrupted / normal (L3-08)
      - description_*        : L3-08 운영 진단용 결손/파손 coverage flags
      - has_risk_keyword    : high / medium / low (NLP/semantic 보조 피처)
      - morpheme_tokens     : list[str] — WU-19 형태소 토큰 (WU-21 전처리)

    Warning: df를 in-place로 수정하고 동일 객체를 반환한다.
    """
    s = settings or get_settings()

    add_description_quality(
        df,
        min_length=s.min_description_length,
        ttr_threshold=s.ttr_threshold,
        entropy_threshold=s.entropy_threshold,
    )
    add_has_risk_keyword(df, risk_kw=risk_kw)
    if include_morpheme_tokens:
        add_morpheme_features(df)

    return df
