"""컬럼 자동 매핑 모듈 — Exact + Fuzzy + Pattern 3단계 전략.

ERP마다 "전표번호/belnr/Doc No" 등 표현이 다르므로,
별칭 사전(keywords.yaml) + rapidfuzz로 원본 컬럼명을 표준 스키마에 매핑한다.
헤더 없는 파일(숫자 인덱스 컬럼)은 데이터 패턴 기반 휴리스틱으로 추론한다.

알고리즘:
  1. fast path: 필수 9컬럼 정확 일치 → 동일 매핑 즉시 반환
  2. Phase 1 (Exact): keywords 별칭 + header_detector matched_keywords로 정확 일치
  3. Phase 2 (Fuzzy): 미매칭 컬럼만 rapidfuzz.process.extractOne
  4. Phase 3 (Pattern): 미매칭 + 숫자 컬럼명 → 데이터 값 패턴으로 표준 컬럼 추론
  5. greedy assign: 스코어 내림차순 1:1 할당 (충돌 해결)
  6. 3-tier 분류: mapping(>=80) / suggestions(40~80) / unmapped(<40)
"""

from __future__ import annotations

import re

import pandas as pd
from rapidfuzz import process as fuzz_process

from config.settings import get_keywords, get_schema, get_settings
from src.ingest._type_compat import infer_column_type, validate_type_compatibility
from src.ingest.models import (
    HeaderDetectionResult,
    MappingResult,
    ReadResult,
    ReviewItem,
)

# 중복 "금액" 퀵픽스 대상 키워드 (한/영/독)
_AMOUNT_KEYWORDS = {"금액", "amount", "amt", "betrag"}


# ── 내부 헬퍼 ──────────────────────────────────────────────


def _build_alias_map(keywords: dict) -> dict[str, str]:
    """keywords.yaml → {lowercase별칭: 표준컬럼명} 매핑 생성.

    Why: 별칭을 소문자로 정규화하여 대소문자 무관 정확 일치에 사용.
    하나의 별칭이 여러 표준 컬럼에 등록된 경우 마지막 것이 우선(YAML에서 방지).
    """
    alias_map: dict[str, str] = {}
    for standard_name, aliases in keywords.items():
        for alias in aliases:
            alias_map[alias.strip().lower()] = standard_name
    return alias_map


def _get_required_columns(schema: dict) -> set[str]:
    """schema.yaml에서 required=true 컬럼명 set 추출."""
    return {
        col["name"]
        for col in schema.get("columns", [])
        if col.get("required", False)
    }


def _get_all_standard_columns(schema: dict) -> set[str]:
    """schema.yaml의 전체 표준 컬럼명 set.

    Why: boolean 컬럼(is_fraud, is_anomaly 등)도 ML/DL 레이블로
    사용되므로 매핑 대상에 포함한다.
    """
    return {col["name"] for col in schema.get("columns", [])}


def _is_standard_schema(
    source_columns: list[str],
    required_columns: set[str],
) -> bool:
    """필수 9컬럼이 source에 모두 정확 포함 → fast path 판정.

    Why: DataSynth CSV처럼 이미 표준 스키마면 매핑 불필요.
    소스 무관 일반화: 필수 컬럼이 모두 있으면 fast path.
    """
    source_set = {col.strip().lower() for col in source_columns}
    return all(req.lower() in source_set for req in required_columns)


def _exact_match(
    source_columns: list[str],
    alias_map: dict[str, str],
    matched_keywords: list[str] | None,
) -> dict[str, tuple[str, float]]:
    """Phase 1: 정확 일치 매칭 — conf=1.0.

    header_detector의 matched_keywords + alias_map 모두 사용.
    Returns: {원본컬럼명: (표준컬럼명, 1.0)}
    """
    result: dict[str, tuple[str, float]] = {}

    # matched_keywords → {lowercase키워드: 원본표기} (header_detector가 찾은 것)
    kw_lower_map: dict[str, str] = {}
    if matched_keywords:
        for kw in matched_keywords:
            kw_lower_map[kw.strip().lower()] = kw

    for col in source_columns:
        col_lower = col.strip().lower()

        # alias_map에서 직접 매칭
        if col_lower in alias_map:
            result[col] = (alias_map[col_lower], 1.0)

    return result


def _fuzzy_match(
    unmatched_columns: list[str],
    alias_map: dict[str, str],
    data_df: pd.DataFrame | None = None,
    schema_type_map: dict[str, str] | None = None,
) -> dict[str, tuple[str, float]]:
    """Phase 2: rapidfuzz extractOne — 미매칭 컬럼만 퍼지 매칭.

    data_df와 schema_type_map이 주어지면 타입 호환성 검증을 수행하여
    비호환 매칭(예: str→float)을 스코어 0으로 차단한다.

    Returns: {원본컬럼명: (표준컬럼명, 0~100 스코어)}
    """
    result: dict[str, tuple[str, float]] = {}

    if not alias_map:
        return result

    # rapidfuzz choices = 별칭 리스트
    choices = list(alias_map.keys())

    for col in unmatched_columns:
        col_stripped = col.strip()
        if not col_stripped:
            continue

        match = fuzz_process.extractOne(col_stripped.lower(), choices)
        if match is not None:
            matched_alias, score, _ = match
            standard_name = alias_map[matched_alias]

            # 타입 호환성 검증 — 비호환이면 스코어 0 (차단)
            if data_df is not None and schema_type_map is not None and col in data_df.columns:
                target_type = schema_type_map.get(standard_name)
                if target_type:
                    source_type = infer_column_type(data_df[col])
                    if not validate_type_compatibility(source_type, target_type):
                        # 차단: 결과에 포함하지 않음 (unmapped로 분류)
                        continue

            result[col] = (standard_name, score)

    return result


# ── Phase 3: 데이터 패턴 기반 휴리스틱 ────────────────────

# Why: 헤더 없는 파일은 컬럼명이 "0","1","2"라 fuzzy match 불가능.
#      샘플 데이터의 값 패턴(날짜, 금액, 코드 등)으로 표준 컬럼을 추론한다.

_DATE_RE = re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}$")
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")
_DOC_ID_RE = re.compile(r"^[A-Z]{1,3}\d{4}[-]?\d+$")
_ACCOUNT_RE = re.compile(r"^\d{4,6}$")
_COMPANY_RE = re.compile(r"^[A-Z]\d{3,4}$")
# Why: document_type은 SAP 전표유형 코드 2~3자리 영문 대문자
_DOC_TYPE_RE = re.compile(r"^[A-Z]{2,3}$")


def _data_pattern_suggest(
    unmatched: list[str],
    data_df: pd.DataFrame,
    already_assigned: set[str],
) -> dict[str, tuple[str, float]]:
    """데이터 값 패턴으로 표준 컬럼을 추론한다.

    각 미매핑 컬럼의 상위 100행 샘플을 분석하여
    가장 적합한 표준 컬럼을 confidence와 함께 반환한다.

    Returns: {원본컬럼명: (표준컬럼명, 스코어 0~100)}
    """
    result: dict[str, tuple[str, float]] = {}
    assigned = set(already_assigned)

    # 각 컬럼의 패턴 분석 결과를 수집
    column_profiles: list[tuple[str, str, float]] = []

    for col in unmatched:
        if col not in data_df.columns:
            # 숫자 인덱스 컬럼 — 위치로 접근
            try:
                idx = int(col)
                if idx < data_df.shape[1]:
                    series = data_df.iloc[:, idx]
                else:
                    continue
            except (ValueError, IndexError):
                continue
        else:
            series = data_df[col]

        suggestion = _classify_series(series)
        if suggestion:
            std_col, score = suggestion
            column_profiles.append((col, std_col, score))

    # 스코어 내림차순 정렬 후 1:1 할당 (중복 방지)
    column_profiles.sort(key=lambda x: x[2], reverse=True)
    for col, std_col, score in column_profiles:
        if std_col not in assigned:
            result[col] = (std_col, score)
            assigned.add(std_col)

    return result


def _classify_series(series: pd.Series) -> tuple[str, float] | None:
    """단일 컬럼의 샘플 값을 분석하여 (표준컬럼명, 스코어)를 반환."""
    sample = series.dropna().head(100)
    if len(sample) == 0:
        return None

    str_vals = sample.astype(str).str.strip()
    n = len(str_vals)

    # 1) 날짜 패턴 — YYYY-MM-DD / YYYY/MM/DD
    date_rate = sum(1 for v in str_vals if _DATE_RE.match(v)) / n
    if date_rate > 0.7:
        return ("posting_date", 75)  # 두 번째 날짜 컬럼은 greedy에서 document_date로

    # 2) 전표번호 패턴 — JE2025-0001, SA20250105 등
    docid_rate = sum(1 for v in str_vals if _DOC_ID_RE.match(v)) / n
    if docid_rate > 0.7:
        return ("document_id", 85)

    # 3) 4자리 연도
    year_rate = sum(1 for v in str_vals if _YEAR_RE.match(v)) / n
    if year_rate > 0.7:
        return ("fiscal_year", 80)

    # 4) 회사코드 — C001, A1234 등
    company_rate = sum(1 for v in str_vals if _COMPANY_RE.match(v)) / n
    if company_rate > 0.7:
        return ("company_code", 80)

    # 5) 전표유형 — SA, KR, KZ, DR 등 2~3자리 영문 대문자
    doctype_rate = sum(1 for v in str_vals if _DOC_TYPE_RE.match(v)) / n
    if doctype_rate > 0.7:
        return ("document_type", 75)

    # 6) 숫자 분석 — 금액, 계정코드, 기간 등
    numeric = pd.to_numeric(sample, errors="coerce")
    numeric_rate = numeric.notna().sum() / n
    if numeric_rate > 0.7:
        non_null = numeric.dropna()
        abs_vals = non_null.abs()
        median_val = abs_vals.median()
        max_val = abs_vals.max()
        n_unique = non_null.nunique()

        # 6a) 소수 정수 (1~12) — fiscal_period
        if max_val <= 12 and n_unique <= 12 and (non_null % 1 == 0).all():
            return ("fiscal_period", 70)

        # 6b) 계정코드 — 4~6자리 정수, unique 다수
        acct_rate = sum(1 for v in str_vals if _ACCOUNT_RE.match(v)) / n
        if acct_rate > 0.7 and n_unique >= 3:
            return ("gl_account", 80)

        # 6c) 금액 — 큰 수 + 0 혼재
        # Why: 차변/대변은 한쪽이 0인 패턴이 많음
        has_zeros = (non_null == 0).any()
        if median_val >= 10000 or (has_zeros and max_val >= 10000):
            return ("debit_amount", 70)  # 두 번째 금액 컬럼은 greedy에서 credit_amount로

    # 7) 한글 텍스트 — 적요(line_text)
    korean_rate = sum(1 for v in str_vals if re.search(r"[가-힣]", v)) / n
    if korean_rate > 0.5:
        return ("line_text", 75)

    return None


def _data_pattern_suggest_second_pass(
    result: dict[str, tuple[str, float]],
    unmatched: list[str],
    data_df: pd.DataFrame,
    already_assigned: set[str],
) -> dict[str, tuple[str, float]]:
    """1차 패턴 매칭에서 중복된 타입의 두 번째 컬럼을 처리.

    Why: posting_date/document_date, debit/credit처럼
    동일 패턴이 2개 컬럼에 나타나는 경우를 해결한다.
    1차에서 posting_date로 잡힌 것 다음에 오는 날짜 컬럼은 document_date로,
    debit_amount 다음의 금액 컬럼은 credit_amount로 할당한다.
    """
    assigned = already_assigned | {std for std, _ in result.values()}
    remaining = [c for c in unmatched if c not in result]

    for col in remaining:
        try:
            idx = int(col)
            if idx < data_df.shape[1]:
                series = data_df.iloc[:, idx]
            else:
                continue
        except (ValueError, IndexError):
            if col in data_df.columns:
                series = data_df[col]
            else:
                continue

        sample = series.dropna().head(100)
        if len(sample) == 0:
            continue

        str_vals = sample.astype(str).str.strip()
        n = len(str_vals)

        # 날짜 → document_date (posting_date가 이미 할당된 경우)
        date_rate = sum(1 for v in str_vals if _DATE_RE.match(v)) / n
        if date_rate > 0.7 and "posting_date" in assigned and "document_date" not in assigned:
            result[col] = ("document_date", 75)
            assigned.add("document_date")
            continue

        # 금액 → credit_amount (debit_amount가 이미 할당된 경우)
        numeric = pd.to_numeric(sample, errors="coerce")
        numeric_rate = numeric.notna().sum() / n
        if numeric_rate > 0.7:
            non_null = numeric.dropna()
            abs_vals = non_null.abs()
            max_val = abs_vals.max()
            has_zeros = (non_null == 0).any()
            if (abs_vals.median() >= 10000 or (has_zeros and max_val >= 10000)):
                if "debit_amount" in assigned and "credit_amount" not in assigned:
                    result[col] = ("credit_amount", 70)
                    assigned.add("credit_amount")

    return result


def _greedy_assign(
    candidates: dict[str, tuple[str, float]],
    threshold: int,
    low_threshold: int,
) -> tuple[dict[str, str], dict[str, str], dict[str, float], list[str]]:
    """스코어 내림차순 1:1 할당 + 3-tier 분류.

    Why: 두 원본 컬럼이 같은 표준 컬럼에 매핑될 때, 스코어가 높은 쪽 우선.
    이미 할당된 표준 컬럼에 매핑 시도하는 후순위 원본은 unmapped로 분류.

    Returns: (mapping, suggestions, confidence, unmapped)
    """
    mapping: dict[str, str] = {}
    suggestions: dict[str, str] = {}
    confidence: dict[str, float] = {}
    unmapped: list[str] = []

    # 스코어 내림차순 정렬
    sorted_items = sorted(
        candidates.items(),
        key=lambda x: x[1][1],
        reverse=True,
    )

    assigned_standards: set[str] = set()

    for source_col, (standard_col, score) in sorted_items:
        # 이미 다른 원본이 이 표준 컬럼을 차지 → 충돌 해결: unmapped
        if standard_col in assigned_standards:
            unmapped.append(source_col)
            continue

        conf_normalized = score / 100.0  # 0~100 → 0.0~1.0

        if score >= threshold:
            mapping[source_col] = standard_col
            confidence[source_col] = conf_normalized
            assigned_standards.add(standard_col)
        elif score >= low_threshold:
            suggestions[source_col] = standard_col
            confidence[source_col] = conf_normalized
            assigned_standards.add(standard_col)
        else:
            unmapped.append(source_col)

    return mapping, suggestions, confidence, unmapped


# ── 공개 API ───────────────────────────────────────────────


def prepare_dataframe(
    raw_df: pd.DataFrame,
    header_row: int,
) -> tuple[list[str], pd.DataFrame]:
    """raw DataFrame + 헤더 행 인덱스 → (컬럼명 리스트, 데이터 DataFrame).

    Why: header_detector가 찾은 행을 컬럼명으로 설정하고,
    그 아래 행들만 데이터로 추출하는 중간 단계.
    """
    # 헤더 행에서 컬럼명 추출 — NaN은 빈 문자열로 대체
    header_values = raw_df.iloc[header_row]
    columns = [
        str(v).strip() if pd.notna(v) else ""
        for v in header_values
    ]

    # 중복 컬럼명 방어 — ERP 파일에서 "금액", "금액" 등 드물지 않음
    # Why: 중복 시 pandas 컬럼 선택이 모호해져 조용한 데이터 손실 가능
    from collections import Counter

    non_empty = [c for c in columns if c]
    counts = Counter(non_empty)
    duplicates = {c for c, n in counts.items() if n > 1}
    if duplicates:
        import warnings

        warnings.warn(
            f"중복 컬럼명 감지: {sorted(duplicates)}. 접미사(_2, _3...)를 붙입니다.",
            stacklevel=2,
        )
        seen: dict[str, int] = {}
        deduped: list[str] = []
        for c in columns:
            if c in duplicates:
                seen[c] = seen.get(c, 0) + 1
                deduped.append(c if seen[c] == 1 else f"{c}_{seen[c]}")
            else:
                deduped.append(c)
        columns = deduped

    # 헤더 행 아래부터 데이터
    data_df = raw_df.iloc[header_row + 1:].reset_index(drop=True)
    data_df.columns = columns

    # 빈 컬럼명("") 제거 — 의미 없는 빈 열
    non_empty_cols = [c for c in columns if c]
    data_df = data_df[non_empty_cols]

    return non_empty_cols, data_df


def _suggest_amount_split(columns: list[str]) -> list[ReviewItem]:
    """인접한 중복 "금액" 컬럼 2개 → 차변/대변 추천.

    Why: ERP 덤프에서 "금액", "금액_2"가 인접하면 실무상
    왼쪽=차변, 오른쪽=대변 패턴이 대부분이다.

    조건: 정확히 2개 중복(원본_2 패턴) + _AMOUNT_KEYWORDS 포함 + 인접 위치.
    3개 이상 중복은 모호하므로 추천하지 않는다.
    action="review" — 자동 적용이 아닌 사용자 확인 추천.
    """
    items: list[ReviewItem] = []

    for i, col in enumerate(columns):
        # "{이름}_2" 패턴 탐지 — prepare_dataframe이 붙인 접미사
        if not col.endswith("_2"):
            continue

        base_name = col[:-2]  # "_2" 제거

        # 금액 키워드 포함 여부 (대소문자 무시)
        if not any(kw in base_name.lower() for kw in _AMOUNT_KEYWORDS):
            continue

        # 원본(첫 번째)이 바로 앞에 인접해야 함
        if i == 0 or columns[i - 1] != base_name:
            continue

        # 3개 이상 중복 확인 — _3이 존재하면 모호하므로 스킵
        suffix_3 = f"{base_name}_3"
        if suffix_3 in columns:
            continue

        # 추천 생성: 왼쪽=debit_amount, 오른쪽=credit_amount
        # Why: 인접 패턴은 실무 ERP에서 높은 정확도이나, 시트 변형 가능성이 있어
        # 자동 적용(1.0)이 아닌 0.8로 설정 → action="review"와 함께 사용자 확인 유도
        items.append(ReviewItem(
            column=base_name,
            action="review",
            confidence=0.8,
            reason=f"인접 중복 '{base_name}' 감지 → 차변금액(debit_amount) 추천",
            target_type="debit_amount",
        ))
        items.append(ReviewItem(
            column=col,
            action="review",
            confidence=0.8,
            reason=f"인접 중복 '{base_name}' 감지 → 대변금액(credit_amount) 추천",
            target_type="credit_amount",
        ))

    return items


def _build_review_items(
    mapping: dict[str, str],
    suggestions: dict[str, str],
    confidence: dict[str, float],
    unmapped: list[str],
    exact_results: dict[str, tuple[str, float]],
    data_df: pd.DataFrame | None,
    schema_type_map: dict[str, str] | None,
) -> list[ReviewItem]:
    """매핑 결과로부터 ReviewItem 리스트를 생성."""
    items: list[ReviewItem] = []

    for col, std in mapping.items():
        conf = confidence.get(col, 1.0)
        if col in exact_results:
            reason = f"키워드 정확 일치: {col} → {std}"
        else:
            pct = round(conf * 100)
            reason = f"fuzzy 매칭 ({pct}%): {col} → {std}"
        items.append(ReviewItem(column=col, action="auto", confidence=conf, reason=reason))

    for col, std in suggestions.items():
        conf = confidence.get(col, 0.0)
        pct = round(conf * 100)
        reason = f"fuzzy 매칭 ({pct}%): {col} → {std} — 확인 필요"
        items.append(ReviewItem(column=col, action="review", confidence=conf, reason=reason))

    for col in unmapped:
        # TODO: 타입 비호환 차단 컬럼과 단순 unmapped 미구분 — Phase 1c UI 직전에 _fuzzy_match 차단 사유 반환으로 개선
        src_type = None
        tgt_type = None
        if data_df is not None and schema_type_map is not None and col in data_df.columns:
            src_type = infer_column_type(data_df[col])
        reason = "자동 매핑 불가 — 수동 지정 필요"
        items.append(ReviewItem(
            column=col, action="review", confidence=0.0, reason=reason,
            source_type=src_type, target_type=tgt_type,
        ))

    return items


def _build_schema_type_map(schema: dict) -> dict[str, str]:
    """schema에서 {표준컬럼명: 타입문자열} 맵 생성."""
    return {
        col["name"]: col["type"]
        for col in schema.get("columns", [])
    }


def auto_map_columns(
    source_columns: list[str],
    matched_keywords: list[str] | None = None,
    *,
    data_df: pd.DataFrame | None = None,
    schema: dict | None = None,
    keywords: dict | None = None,
    settings_override: dict | None = None,
) -> MappingResult:
    """원본 컬럼명 리스트 → MappingResult (Exact → Fuzzy → 3-tier).

    Note:
        중복 금액 퀵픽스(_suggest_amount_split)는 map_columns() 퍼사드에서만
        실행된다. prepare_dataframe의 dedup 접미사(_2)에 의존하기 때문.
        이 함수를 직접 호출하면 금액 퀵픽스가 포함되지 않는다.

    Args:
        source_columns: 원본 컬럼명 리스트
        matched_keywords: header_detector가 매칭한 키워드 (Phase 1 활용)
        data_df: 헤더 아래 데이터 DataFrame (타입 호환성 검증용, None이면 스킵)
        schema: schema.yaml dict (테스트 시 주입, None이면 자동 로드)
        keywords: keywords.yaml dict (테스트 시 주입, None이면 자동 로드)
        settings_override: threshold 등 오버라이드 (테스트용)
    """
    # 설정 로드
    if schema is None:
        schema = get_schema()
    if keywords is None:
        keywords = get_keywords()

    settings = get_settings()
    threshold = settings.fuzzy_threshold
    low_threshold = settings.fuzzy_low_threshold
    if settings_override:
        threshold = settings_override.get("fuzzy_threshold", threshold)
        low_threshold = settings_override.get("fuzzy_low_threshold", low_threshold)

    required_columns = _get_required_columns(schema)
    all_standard = _get_all_standard_columns(schema)

    # 빈 리스트 방어
    if not source_columns:
        return MappingResult(
            mapping={},
            suggestions={},
            confidence={},
            unmapped=[],
            missing_required=sorted(required_columns),
            needs_review=bool(required_columns),
        )

    # fast path: 필수 컬럼이 모두 정확 일치 → 동일 매핑 즉시 반환
    if _is_standard_schema(source_columns, required_columns):
        identity_mapping = {
            col: col for col in source_columns
            if col.lower() in {s.lower() for s in all_standard}
        }
        identity_conf = {col: 1.0 for col in identity_mapping}
        unmapped_cols = [
            col for col in source_columns
            if col not in identity_mapping
        ]
        return MappingResult(
            mapping=identity_mapping,
            suggestions={},
            confidence=identity_conf,
            unmapped=unmapped_cols,
            missing_required=[],
            needs_review=False,
        )

    # Phase 1: 정확 일치
    alias_map = _build_alias_map(keywords)
    exact_results = _exact_match(source_columns, alias_map, matched_keywords)

    # Phase 2: 미매칭 컬럼만 fuzzy (타입 호환성 검증 포함)
    matched_sources = set(exact_results.keys())
    unmatched = [col for col in source_columns if col not in matched_sources]
    schema_type_map = _build_schema_type_map(schema) if data_df is not None else None
    fuzzy_results = _fuzzy_match(
        unmatched, alias_map,
        data_df=data_df, schema_type_map=schema_type_map,
    )

    # 합치기 — exact는 score 100으로 통일
    all_candidates: dict[str, tuple[str, float]] = {}
    for src, (std, _) in exact_results.items():
        all_candidates[src] = (std, 100.0)  # exact → score 100
    for src, (std, score) in fuzzy_results.items():
        all_candidates[src] = (std, score)

    # Phase 3: 데이터 패턴 기반 추론 (헤더 없는 파일용)
    # Why: 컬럼명이 "0","1","2" 같은 숫자 인덱스면 fuzzy match 불가.
    #      데이터 값 패턴(날짜, 금액, 코드)으로 표준 컬럼을 추론한다.
    #      score=0인 fuzzy 결과는 무의미하므로 "매칭됨"으로 취급하지 않는다.
    if data_df is not None:
        meaningful_sources = {
            src for src, (_, score) in all_candidates.items() if score > 0
        }
        still_unmatched = [c for c in source_columns if c not in meaningful_sources]
        if still_unmatched:
            # Why: score=0인 fuzzy 결과의 표준 컬럼은 실질적 할당이 아님
            assigned_standards = {
                std for std, score in all_candidates.values() if score > 0
            }
            pattern_results = _data_pattern_suggest(
                still_unmatched, data_df, assigned_standards,
            )
            # 2차 패스: 동일 패턴 중복(날짜↔날짜, 금액↔금액) 해결
            pattern_results = _data_pattern_suggest_second_pass(
                pattern_results, still_unmatched, data_df,
                assigned_standards,
            )
            for src, (std, score) in pattern_results.items():
                all_candidates[src] = (std, score)

    # greedy 1:1 할당 + 3-tier 분류
    mapping, suggestions, confidence, unmapped_list = _greedy_assign(
        all_candidates, threshold, low_threshold,
    )

    # source_columns 중 candidates에 아예 없는 것도 unmapped에 추가
    all_candidate_sources = set(all_candidates.keys())
    for col in source_columns:
        if col not in all_candidate_sources and col not in unmapped_list:
            unmapped_list.append(col)

    # missing_required: 필수 컬럼 중 mapping에 포함되지 않은 것
    mapped_standards = set(mapping.values())
    missing_required = sorted(required_columns - mapped_standards)

    needs_review = bool(suggestions or missing_required)

    # ReviewItem 생성 — 투명성 레이어
    review_items = _build_review_items(
        mapping, suggestions, confidence, unmapped_list,
        exact_results, data_df, schema_type_map,
    )

    return MappingResult(
        mapping=mapping,
        suggestions=suggestions,
        confidence=confidence,
        unmapped=unmapped_list,
        missing_required=missing_required,
        needs_review=needs_review,
        review_items=review_items,
    )


def map_columns(
    read_result: ReadResult,
    header_results: dict[str, HeaderDetectionResult],
    *,
    schema: dict | None = None,
    keywords: dict | None = None,
) -> dict[str, MappingResult]:
    """멀티시트 퍼사드 — ReadResult + 헤더 탐지 결과 → 시트별 MappingResult.

    detect_headers() 패턴과 동일: {시트명: MappingResult}.
    헤더 탐지 실패(header_row=None)인 시트는 빈 MappingResult 반환.
    """
    if schema is None:
        schema = get_schema()
    if keywords is None:
        keywords = get_keywords()

    results: dict[str, MappingResult] = {}

    for sheet_name, raw_df in read_result.raw_data.items():
        header_result = header_results.get(sheet_name)

        # 헤더 탐지 실패 → 빈 결과
        if header_result is None or header_result.header_row is None:
            required = _get_required_columns(schema)
            results[sheet_name] = MappingResult(
                mapping={},
                suggestions={},
                confidence={},
                unmapped=[],
                missing_required=sorted(required),
                needs_review=True,
            )
            continue

        # prepare_dataframe → 컬럼 추출 + 데이터
        source_columns, data_df = prepare_dataframe(raw_df, header_result.header_row)

        # auto_map_columns (data_df 전달 → 타입 호환성 검증)
        mapping_result = auto_map_columns(
            source_columns,
            matched_keywords=header_result.matched_keywords,
            data_df=data_df,
            schema=schema,
            keywords=keywords,
        )

        # 중복 "금액" 퀵픽스 — prepare_dataframe이 붙인 _2 접미사 기반
        amount_items = _suggest_amount_split(source_columns)
        if amount_items:
            mapping_result.review_items.extend(amount_items)
            mapping_result.needs_review = True

        results[sheet_name] = mapping_result

    return results
