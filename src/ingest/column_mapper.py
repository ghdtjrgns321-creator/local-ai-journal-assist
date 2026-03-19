"""컬럼 자동 매핑 모듈 — Exact + Fuzzy 2단계 전략.

ERP마다 "전표번호/belnr/Doc No" 등 표현이 다르므로,
별칭 사전(keywords.yaml) + rapidfuzz로 원본 컬럼명을 표준 스키마에 매핑한다.

알고리즘:
  1. fast path: 필수 9컬럼 정확 일치 → 동일 매핑 즉시 반환
  2. Phase 1 (Exact): keywords 별칭 + header_detector matched_keywords로 정확 일치
  3. Phase 2 (Fuzzy): 미매칭 컬럼만 rapidfuzz.process.extractOne
  4. greedy assign: 스코어 내림차순 1:1 할당 (충돌 해결)
  5. 3-tier 분류: mapping(>=80) / suggestions(40~80) / unmapped(<40)
"""

from __future__ import annotations

import pandas as pd
from rapidfuzz import process as fuzz_process

from config.settings import get_keywords, get_schema, get_settings
from src.ingest.models import HeaderDetectionResult, MappingResult, ReadResult


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
    """schema.yaml의 전체 표준 컬럼명 set (label 컬럼 제외).

    Why: is_label=true인 컬럼(is_fraud, is_anomaly)은 DataSynth 전용이므로
    매핑 대상에서 제외. schema에 is_label 필드가 없으면 type=bool을 폴백으로 사용.
    """
    return {
        col["name"]
        for col in schema.get("columns", [])
        if not col.get("is_label", col.get("type") == "bool")
    }


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
) -> dict[str, tuple[str, float]]:
    """Phase 2: rapidfuzz extractOne — 미매칭 컬럼만 퍼지 매칭.

    Returns: {원본컬럼명: (표준컬럼명, 0~100 스코어)}
    스코어 0인 경우(빈 별칭 리스트 등)는 결과에 포함하지 않음.
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
            result[col] = (standard_name, score)

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


def auto_map_columns(
    source_columns: list[str],
    matched_keywords: list[str] | None = None,
    *,
    schema: dict | None = None,
    keywords: dict | None = None,
    settings_override: dict | None = None,
) -> MappingResult:
    """원본 컬럼명 리스트 → MappingResult (Exact → Fuzzy → 3-tier).

    Args:
        source_columns: 원본 컬럼명 리스트
        matched_keywords: header_detector가 매칭한 키워드 (Phase 1 활용)
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

    # Phase 2: 미매칭 컬럼만 fuzzy
    matched_sources = set(exact_results.keys())
    unmatched = [col for col in source_columns if col not in matched_sources]
    fuzzy_results = _fuzzy_match(unmatched, alias_map)

    # 합치기 — exact는 score 100으로 통일
    all_candidates: dict[str, tuple[str, float]] = {}
    for src, (std, _) in exact_results.items():
        all_candidates[src] = (std, 100.0)  # exact → score 100
    for src, (std, score) in fuzzy_results.items():
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

    return MappingResult(
        mapping=mapping,
        suggestions=suggestions,
        confidence=confidence,
        unmapped=unmapped_list,
        missing_required=missing_required,
        needs_review=needs_review,
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

        # prepare_dataframe → 컬럼 추출
        source_columns, _ = prepare_dataframe(raw_df, header_result.header_row)

        # auto_map_columns
        results[sheet_name] = auto_map_columns(
            source_columns,
            matched_keywords=header_result.matched_keywords,
            schema=schema,
            keywords=keywords,
        )

    return results
