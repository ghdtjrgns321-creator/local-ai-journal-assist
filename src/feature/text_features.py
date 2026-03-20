"""텍스트 기반 감사 파생변수 2개 생성 모듈.

C06 룰 대응 피처 — description_quality(적요 품질), has_risk_keyword(위험 키워드).
ingest 완료된 표준 DataFrame을 입력으로 받는다.

핵심 설계 — 같은 원본 텍스트를 **2가지 버전**으로 정제:
  combined_text : strip()만 → description_quality (공백 포함 원본 길이)
  cleaned_text  : 한글+영숫자 외 제거 → has_risk_keyword (은폐 패턴 관통)
"""

from __future__ import annotations

import logging
import re

import pandas as pd

from config.settings import AuditSettings, get_risk_keywords, get_settings

logger = logging.getLogger(__name__)

# 키워드 매칭 전용 — 한글+영숫자 외 모든 문자 제거
_RE_STRIP_ALL = re.compile(r"[^가-힣a-zA-Z0-9]")

# 노이즈 패턴: 자음/모음 단독, 특수문자만, 동일 문자 3회+ 반복
_RE_JAMO_ONLY = re.compile(r"^[ㄱ-ㅎㅏ-ㅣ]+$")
_RE_SPECIAL_ONLY = re.compile(r"^[^가-힣a-zA-Z0-9]+$")
_RE_REPEAT_CHAR = re.compile(r"^(.)\1{2,}$")


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
    )


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


# ── Public feature functions ─────────────────────────────────────


def add_description_quality(
    df: pd.DataFrame,
    min_length: int = 3,
) -> pd.DataFrame:
    """C06: 적요 품질 3단계 — missing / poor / normal.

    combined_text(strip 버전) 사용 — 공백 포함 원본 길이로 판정.
    판정 흐름: combine → NaN→missing → noise→poor → 짧음→poor → normal.
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


# ── Phase 2/3 stubs ─────────────────────────────────────────────


def add_semantic_similarity(df: pd.DataFrame) -> pd.DataFrame:
    """Phase 2: kiwipiepy + 임베딩 벡터 유사도 (미구현).

    TODO Phase 2: add_all_text_features에 연결.
    """
    logger.info("add_semantic_similarity: Phase 2 stub — no-op")
    return df


def add_semantic_anomaly(df: pd.DataFrame) -> pd.DataFrame:
    """Phase 3: Ollama LLM 문맥 이상 탐지 (미구현).

    TODO Phase 3: add_all_text_features에 연결.
    """
    logger.info("add_semantic_anomaly: Phase 3 stub — no-op")
    return df


# ── Orchestrator ─────────────────────────────────────────────────


def add_all_text_features(
    df: pd.DataFrame,
    settings: AuditSettings | None = None,
) -> pd.DataFrame:
    """텍스트 파생변수 2개를 한번에 추가. engine.py 진입점.

    Warning: df를 in-place로 수정하고 동일 객체를 반환한다.
    """
    s = settings or get_settings()

    add_description_quality(df, min_length=s.min_description_length)
    add_has_risk_keyword(df)

    return df
