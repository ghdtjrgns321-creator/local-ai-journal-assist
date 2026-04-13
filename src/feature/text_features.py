"""텍스트 기반 감사 파생변수 생성 모듈.

C06 룰 + WU-19 NLP 기초 — description_quality, has_risk_keyword, morpheme_tokens.
ingest 완료된 표준 DataFrame을 입력으로 받는다.

핵심 설계 — 같은 원본 텍스트를 **2가지 버전**으로 정제:
  combined_text : strip()만 → description_quality (공백 포함 원본 길이)
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
    return bool(
        _RE_JAMO_ONLY.match(text)
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
    # 1) 한글이 있는 행만 인덱스와 함께 추출
    korean_indices: list[int] = []
    korean_texts: list[str] = []
    for i, text in enumerate(texts):
        if _has_korean(text):
            korean_indices.append(i)
            korean_texts.append(text)

    # 2) 전체 결과를 빈 리스트로 초기화 (영문/빈값 → [])
    results: list[list[str]] = [[] for _ in range(len(texts))]

    # 3) 한국어가 하나라도 있을 때만 Kiwi 싱글톤 로드 + 배치 호출
    if korean_texts:
        kiwi = _get_kiwi()
        for idx, tokens in zip(korean_indices, kiwi.tokenize(korean_texts)):
            results[idx] = [t.form for t in tokens if t.tag in _MORPHEME_TAGS]

    return results


# ── Public feature functions ─────────────────────────────────────


def add_description_quality(
    df: pd.DataFrame,
    min_length: int = 3,
    ttr_threshold: float = 0.3,
    entropy_threshold: float = 1.0,
) -> pd.DataFrame:
    """C06: 적요 품질 3단계 — missing / poor / normal.

    combined_text(strip 버전) 사용 — 공백 포함 원본 길이로 판정.
    판정 흐름: NaN→missing → noise→poor → 짧음→poor → TTR<0.3→poor → entropy<1.0→poor → normal.
    """
    combined = _combine_text(df)

    def _classify(text: object) -> str:
        if pd.isna(text):
            return "missing"
        s = str(text)
        if _is_noise_pattern(s):
            return "poor"
        if len(s) < min_length:
            return "poor"
        # Phase 2: TTR + Entropy 체크 (길이 통과한 텍스트만)
        if _compute_ttr(s) < ttr_threshold:
            return "poor"
        if _compute_entropy(s) < entropy_threshold:
            return "poor"
        return "normal"

    df["description_quality"] = combined.map(_classify)
    return df


def add_has_risk_keyword(
    df: pd.DataFrame,
    risk_kw: dict[str, list[str]] | None = None,
) -> pd.DataFrame:
    """C06: 위험 키워드 등급 — high / medium / low.

    cleaned_text(완전 정제 버전) 사용 — 은폐 패턴 관통.
    risk_kw 직접 주입 가능 (테스트 용이), 미지정 시 YAML 로드.
    """
    kw = risk_kw or get_risk_keywords()
    high = kw.get("high_risk", [])
    medium = kw.get("medium_risk", [])

    combined = _combine_text(df)
    cleaned = _clean_for_keyword(combined)

    df["has_risk_keyword"] = cleaned.map(
        lambda t: _match_risk_level(t, high, medium)
    )
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


# ── Phase 2/3 stubs ─────────────────────────────────────────────


def add_semantic_similarity(df: pd.DataFrame) -> pd.DataFrame:
    """Phase 2: kiwipiepy + 임베딩 벡터 유사도 (미구현).

    TODO Phase 2: add_all_text_features에 연결.
    """
    logger.info("add_semantic_similarity: Phase 2 stub — no-op")
    return df


def add_semantic_anomaly(df: pd.DataFrame) -> pd.DataFrame:
    """Phase 3: OpenAI LLM 문맥 이상 탐지 (미구현).

    TODO Phase 3: add_all_text_features에 연결.
    """
    logger.info("add_semantic_anomaly: Phase 3 stub — no-op")
    return df


# ── Orchestrator ─────────────────────────────────────────────────


def add_all_text_features(
    df: pd.DataFrame,
    settings: AuditSettings | None = None,
    risk_kw: dict | None = None,
) -> pd.DataFrame:
    """텍스트 파생변수를 한번에 추가. engine.py 진입점.

    생성 컬럼:
      - description_quality : missing / poor / normal (C06)
      - has_risk_keyword    : high / medium / low (C06)
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
    add_morpheme_features(df)

    return df
