"""키워드 학습 모듈 — 사용자 수동 매핑에서 새 별칭을 추출.

Why: 사용자가 mapping_review UI에서 수동으로 확정한 매핑을
회사 keywords.yaml에 자동 추가하면, 다음 업로드 시
auto_map_columns Phase 1(Exact Match)에서 즉시 매칭된다.

충돌 정책: 동일 별칭이 이미 다른 표준 컬럼에 등록되어 있으면
기존 등록을 삭제하고 사용자의 최신 선택으로 덮어쓴다 (Overwrite).
"""

from __future__ import annotations

import copy
import logging

logger = logging.getLogger(__name__)


def learn_from_mapping(
    user_overrides: dict[str, str],
    existing_keywords: dict[str, list[str]] | None,
    global_keywords: dict[str, list[str]],
) -> dict[str, list[str]] | None:
    """사용자 수동 매핑에서 새 별칭을 추출하여 회사 keywords에 머지.

    Args:
        user_overrides: {원본컬럼명: 표준컬럼명} — 사용자가 확정한 매핑
        existing_keywords: 회사 keywords.yaml (None이면 아직 없음)
        global_keywords: 글로벌 config/keywords.yaml

    Returns:
        갱신된 회사 keywords dict, 학습할 새 별칭이 없으면 None
    """
    if not user_overrides:
        return None

    # 회사 keywords 복사본 (없으면 빈 dict로 시작)
    merged = copy.deepcopy(existing_keywords) if existing_keywords else {}
    added_count = 0

    for source_col, standard_col in user_overrides.items():
        alias = source_col.strip().lower()
        if not alias or not standard_col:
            continue

        # 글로벌 keywords에 이미 등록된 별칭이면 스킵
        if _alias_exists_in(alias, standard_col, global_keywords):
            continue

        # 회사 keywords에 이미 같은 위치에 등록되어 있으면 스킵
        if _alias_exists_in(alias, standard_col, merged):
            continue

        # 충돌 해결: 동일 별칭이 다른 표준 컬럼에 등록되어 있으면 제거
        _remove_alias_from_all(alias, merged)

        # 새 별칭 추가
        if standard_col not in merged:
            merged[standard_col] = []
        merged[standard_col].append(alias)
        added_count += 1

        logger.info(
            "키워드 학습: '%s' → %s (회사 keywords에 추가)",
            source_col, standard_col,
        )

    if added_count == 0:
        return None

    logger.info("총 %d개 새 별칭 학습 완료", added_count)
    return merged


def _alias_exists_in(
    alias: str,
    standard_col: str,
    keywords: dict[str, list[str]],
) -> bool:
    """alias가 keywords의 standard_col 별칭 리스트에 이미 있는지 확인."""
    aliases = keywords.get(standard_col, [])
    return alias in [a.strip().lower() for a in aliases]


def _remove_alias_from_all(
    alias: str,
    keywords: dict[str, list[str]],
) -> None:
    """모든 표준 컬럼에서 해당 alias를 제거 (충돌 방지).

    Why: 사용자가 '부서코드'를 department_code에서 cost_center로
    재매핑하면, department_code의 '부서코드' 별칭을 삭제해야
    1:N 충돌이 발생하지 않는다.
    """
    for standard_col, aliases in keywords.items():
        normalized = [a.strip().lower() for a in aliases]
        if alias in normalized:
            # 해당 별칭의 모든 occurrence를 제거 (방어적 처리)
            original = list(aliases)
            keywords[standard_col] = [
                a for a in aliases if a.strip().lower() != alias
            ]
            removed_count = len(original) - len(keywords[standard_col])
            logger.debug(
                "충돌 해결: '%s' → %s 에서 %d건 제거",
                alias, standard_col, removed_count,
            )
