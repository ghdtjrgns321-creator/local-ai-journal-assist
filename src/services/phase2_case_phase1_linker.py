"""PHASE1 ↔ PHASE2 cross-reference linker (v7-plan S4 + S4.next + S4.next.2).

Why: PHASE2 native case 가 PHASE1 case_id 와 어떤 row 에서 만나는지 부착하는 단방향
linker. ``key_mode`` 로 매칭 알고리즘을 분기한다:

- ``"position"`` (S4 MVP): row_position 등가만 사용. row-level precision. 동일
  in-memory df 한정 (sort / reset_index / multi-company concat 후에는 약함).
- ``"doc_id"`` (S4.next): document_id 등가. document-level precision —
  **row 단위가 아니라 document 단위로 cross-reference 함**. row order / position
  변형 / store reload 에 안전하지만, PHASE2 row 가 DOC1 line 2 이고 PHASE1 hit 가
  DOC1 의 다른 line 이어도 같은 PHASE1 case 가 link 된다 (의도된 looser 매칭 —
  같은 document 안에서 의심 신호와 anomaly 가 함께 있을 때 같이 봐야 함).
  duplicate pair / VAE row 단위 evidence 의 row-level 정확성이 필요한 경우
  cross-reference 가 과하게 붙을 수 있다 — line-level 정밀도는 ``doc_line`` mode
  사용.
- ``"doc_line"`` (S4.next.2 + S6.next Phase 2): (document_id_hash, normalized
  line_number_key) 페어로 매칭. multi-line 전표 안에서 row-precise.
  **salt 필수, row_ref_map 은 fallback 용**. PHASE1 hit 가 ``doc_id_hash`` +
  ``line_number_key`` 를 직접 보유 (S6.next Phase 1) 하면 row_ref_map sidecar
  없이 hit hash direct 매칭. hit hash 부재 시 row_ref_map[position] 조회로 fallback.
- ``"company_doc"`` (S4.next.2 + S6.next Phase 2): (company_code_hash,
  document_id_hash) 페어로 매칭. multi-company concat 환경에서 회사 disambiguation.
  salt 필수, row_ref_map 은 fallback. PHASE1 hit 의 ``company_code_hash`` +
  ``doc_id_hash`` 가용 시 hit hash direct.
- ``"label"`` (S4.next.2 + S6.next Phase 2): canonical_label_hash 직접 비교 —
  row-precise. row order 변형 (sort / reset_index) 흡수. salt 필수, row_ref_map
  은 fallback. PHASE1 hit 의 ``canonical_label_hash`` 가용 시 hit hash direct
  → cross-batch / cross-process reload-safe.
- ``"auto"``: 우선순위 ``label`` > ``doc_id`` > ``position``. **label 분기 조건**
  (S6.next Phase 2 #79): salt 가용 + PHASE1 hit coverage 100% (hit 의
  ``canonical_label_hash`` 우선, 없으면 row_ref_map fallback). PHASE1 hit 가 모두
  canonical_label_hash 보유하면 row_ref_map 부재해도 label 채택. partial coverage
  시 silent unmatched 위험이 있어 label 회피하고 doc_id 또는 position 으로 fallback.
  명시 호출 (``label`` / ``doc_line`` / ``company_doc``) 은 coverage 검사 없이
  호출자 의도 존중 — invariant #51.

핵심 invariant (v7-plan §S4 #33~38, §S4.next #39~44, §S4.next.2 #45~49,
§S6.next Phase 2 #74~79):
- PHASE1 priority_score / priority_rank / composite_sort_score 변경 금지 (read-only).
- PHASE2 family_score / family_ecdf / case_generation_reason 변경 금지.
- phase1_case_refs 는 정렬된 tuple — input 순서 무관, idempotent.
- 각 case 의 row_refs row_position 이 cross-reference 대상.
- key_mode invalid 입력 → ValueError 즉시 (silent fallback 금지, #44).
- ``doc_line`` / ``company_doc`` / ``label`` 호출 시 **salt 만 필수** (#78).
  row_ref_map 은 fallback 용 — None / empty 허용. PHASE1 hit hash 보유 시 sidecar
  없이 매칭.
- diagnostics 에 ``key_mode_used`` / ``match_precision`` 기록 (#41).

## Match precision matrix

| mode          | match_precision |
|---------------|-----------------|
| ``position``  | ``"row"``       |
| ``label``     | ``"row"``       |
| ``doc_line``  | ``"row"``       |
| ``company_doc``| ``"document"``  |
| ``doc_id``    | ``"document"``  |

## Pipeline attach 정책 (S6.next Phase 2 — hit hash direct path conditional unlock)

S6.next Phase 1 (PHASE1 `RawRuleHitRef` schema 확장 — canonical_label_hash /
doc_id_hash / line_number_key / company_code_hash 직접 보유) + S6.next Phase 2
(linker 가 hit hash 우선 + row_ref_map fallback) 로 **진짜 cross-batch /
cross-process reload-safe path 가 production 가용**.

pipeline attach 허용 조건 (Phase 2 unlock):

1. PHASE1 builder 호출 시 ``engagement_salt`` 명시 — PHASE1 hit 가 stable
   identifier hash 직접 보유.
2. PHASE2 store 가 동일 salt 로 row_ref_map.jsonl 저장 (또는 호출 시 같은 salt
   직접 전달).
3. linker 가 hash 기반 mode (``label`` / ``doc_line`` / ``company_doc``) 또는
   ``auto`` 로 호출 — hit hash direct path 활성.

위 조건 충족 시 row order 변형 (sort / reset_index) / multi-company concat /
store reload 모두 안전. salt 불일치만 호출자 책임 (silent zero-match, #77).

**여전히 제약**:
- ``position`` 단독 mode — 동일 in-memory df 한정.
- ``doc_id`` 단독 mode — document-level looser 매칭 (row-precise 아님).
- PHASE1 hit 가 hash 필드 부재 (engagement_salt 미전달) + row_ref_map 도 부재 →
  매칭 0 silent. 호출자가 diagnostics 의 phase1_hit_count / unmatched_phase2_count
  로 확인.

S6.next.next (deferred): row_ref_map deprecation 검토 — PHASE1 hit hash 보급
완료 후 sidecar 의존 단계적 제거.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.models.phase1_case import Phase1CaseResult
from src.models.phase2_case import Phase2CaseSet, Phase2RowRef
from src.services.phase2_ref_canonical import normalize_line_number_key
from src.services.phase2_ref_pseudonymize import hash_ref_key

# Why: empty short-circuit 검사용 family field 목록.
# Phase2CaseSet._FAMILY_FIELD_NAMES 와 동기화 (private 라 import 하지 않고 복제).
_FAMILY_FIELD_NAMES: tuple[str, ...] = (
    "unsupervised_cases",
    "timeseries_cases",
)


@dataclass(frozen=True)
class LinkerResult:
    """linker 산출 — linked case_set + 진단 dict.

    diagnostics keys:
      - linked_count: phase1_case_refs 가 1개 이상 부착된 PHASE2 case 수
      - phase1_hit_count: needed key (position / doc_id / doc_line / company_doc / label)
        와 교집합인 PHASE1 raw_rule_hit 수
      - unmatched_phase2_count: phase1_case_refs 가 빈 PHASE2 case 수
      - key_mode_used: 실제 사용된 매칭 모드
        ("position" | "doc_id" | "doc_line" | "company_doc" | "label")
      - match_precision: "row" (position / doc_line / label) | "document"
        (doc_id / company_doc) — 호출자가 looser 매칭인지 row-precise 인지 즉시 판별.
    """

    case_set: Phase2CaseSet
    diagnostics: dict[str, Any]


# Why: 외부 noisy default 로 silent fallback 하지 않도록 허용값을 frozenset 으로 잠근다.
# S4.next.2 — doc_line / company_doc / label 추가.
_ALLOWED_KEY_MODES: frozenset[str] = frozenset(
    {"position", "doc_id", "doc_line", "company_doc", "label", "auto"}
)

# Why: 이 mode 들은 hash 비교 기반 — engagement-scoped salt 가 **필수** (#78).
# row_ref_map.jsonl entries 는 **fallback 용** (legacy): PHASE1 hit 가 hash 필드
# (canonical_label_hash / doc_id_hash / line_number_key / company_code_hash) 직접
# 보유 시 (S6.next Phase 1) sidecar 없이 hit hash direct 매칭. row_ref_map 부재
# (None / empty list) 도 허용. 명시 호출 시 ``salt`` 누락이면 silent fallback 없이
# ValueError (이전 #45 의 row_ref_map 필수 강제는 #78 으로 정정 — Phase 2 unlock).
_HASH_MAP_REQUIRED_MODES: frozenset[str] = frozenset({"doc_line", "company_doc", "label"})

# Why: 각 mode 의 매칭 정밀도. diagnostics 에 기록하여 looser 매칭 (document-level)
# 인지 row-precise 인지 호출자가 즉시 알 수 있게 한다.
_MATCH_PRECISION: dict[str, str] = {
    "position": "row",
    "label": "row",
    "doc_line": "row",
    "doc_id": "document",
    "company_doc": "document",
}


def link_phase2_to_phase1(
    *,
    case_set: Phase2CaseSet,
    phase1: Phase1CaseResult,
    row_ref_map: list[dict[str, Any]] | None = None,
    salt: str | None = None,
    key_mode: str = "auto",
) -> LinkerResult:
    """PHASE2 case_set 에 PHASE1 case_id cross-reference 부착.

    Args:
        case_set: PHASE2 native case 묶음 (5 family).
        phase1: PHASE1 case-centric 결과 — read-only. PHASE1 builder 가
            ``engagement_salt`` 와 함께 호출되어 ``RawRuleHitRef.canonical_label_hash``
            / ``doc_id_hash`` / ``line_number_key`` / ``company_code_hash`` 직접 보유
            시 linker 가 hit hash direct path 사용 (S6.next Phase 1 + 2).
        row_ref_map: ``<engagement_dir>/phase2_cases/<batch_id>/row_ref_map.jsonl``
            의 entries (position → hash 식별자). **S6.next Phase 2 이후 fallback 용
            (legacy)** — PHASE1 hit 가 hash 필드 직접 보유 시 row_ref_map 없이도
            매칭 가능. None / empty list 허용 (invariant #78).
        salt: engagement-scoped salt — hit hash 와 row_ref_map hash 가 같은 salt 로
            만들어졌어야 매칭 정상 (invariant #77). **hash 기반 mode 에서 필수**
            (row_ref_map 부재 여부 무관).
        key_mode: ``"position"`` | ``"doc_id"`` | ``"doc_line"`` | ``"company_doc"`` |
            ``"label"`` | ``"auto"``. default ``"auto"``.

    Returns:
        LinkerResult.case_set 은 with_phase1_refs 적용된 linked=True case_set,
        diagnostics 는 매칭 카운트 + ``key_mode_used`` + ``match_precision``.

    Raises:
        ValueError: ``key_mode`` 가 허용 외 값일 때 (#44), 또는 hash 기반 mode 에서
        ``salt`` 가 누락되었을 때 (#78). row_ref_map 누락은 더 이상 ValueError 가
        아니다 (fallback 미사용 → hit hash direct path).
    """
    # invariant #44 — invalid key_mode 는 silent fallback 없이 즉시 거절.
    if key_mode not in _ALLOWED_KEY_MODES:
        raise ValueError(f"key_mode must be one of {sorted(_ALLOWED_KEY_MODES)}, got: {key_mode!r}")

    # S6.next Phase 2 (invariant #78) — hash 기반 mode 는 salt 만 필수.
    # row_ref_map 은 fallback 용 — PHASE1 hit 가 hash 필드 직접 보유 시 (S6.next
    # Phase 1) row_ref_map 없이도 매칭 가능. None / empty list 모두 허용.
    # hit hash 와 row_ref_map 모두 부재면 매칭 0 (silent — 호출자가 진단 확인).
    if key_mode in _HASH_MAP_REQUIRED_MODES:
        if salt is None or not str(salt).strip():
            raise ValueError(f"key_mode={key_mode!r} requires non-empty salt")

    # auto resolution (#48) — 우선순위 label > doc_id > position.
    if key_mode == "auto":
        resolved_key_mode = _resolve_auto_key_mode(case_set, phase1, row_ref_map, salt)
    else:
        resolved_key_mode = key_mode

    # ── empty short-circuit ─────────────────────────────────────────────
    # case_set 자체가 비어 있으면 with_phase1_refs 호출도 생략 — 동일 객체 반환.
    has_any_case = any(len(getattr(case_set, field)) > 0 for field in _FAMILY_FIELD_NAMES)
    if not has_any_case:
        return LinkerResult(
            case_set=case_set,
            diagnostics={
                "linked_count": 0,
                "phase1_hit_count": 0,
                "unmatched_phase2_count": 0,
                "key_mode_used": resolved_key_mode,
                "match_precision": _MATCH_PRECISION.get(resolved_key_mode, "row"),
            },
        )

    # dispatch — 각 mode 별 매칭 함수 호출.
    if resolved_key_mode == "doc_line":
        return _link_via_doc_line(
            case_set=case_set, phase1=phase1, row_ref_map=row_ref_map or [], salt=str(salt)
        )
    if resolved_key_mode == "company_doc":
        return _link_via_company_doc(
            case_set=case_set, phase1=phase1, row_ref_map=row_ref_map or [], salt=str(salt)
        )
    if resolved_key_mode == "label":
        return _link_via_label(
            case_set=case_set, phase1=phase1, row_ref_map=row_ref_map or [], salt=str(salt)
        )
    if resolved_key_mode == "doc_id":
        return _link_via_doc_id(case_set=case_set, phase1=phase1)
    # default fallback — position equality.
    return _link_via_position(case_set=case_set, phase1=phase1)


def _resolve_auto_key_mode(
    case_set: Phase2CaseSet,
    phase1: Phase1CaseResult,
    row_ref_map: list[dict[str, Any]] | None,
    salt: str | None,
) -> str:
    """``auto`` 분기 해석 — 우선순위 label > doc_id > position (#48, #51, #79).

    1. salt 가용 + PHASE1 hit coverage 100% (hit hash 우선, row_ref_map fallback,
       invariant #76) → 가장 strict 인 ``label`` 채택. row_ref_map 부재해도 PHASE1
       hit 가 모두 canonical_label_hash 가용하면 label 진입 (S6.next Phase 2 #79).
    2. partial coverage → label 의 silent unmatched 위험. doc_id / position fallback.
    3. salt 없거나 partial coverage → 모든 PHASE2 ref 의 document_id 가 truthy 면
       ``doc_id``.
    4. 하나라도 None / 빈 문자열이면 ``position`` fallback.

    Args:
        phase1: PHASE1 hit coverage 검사용 (hit hash 우선, row_ref_map fallback).
    """
    # 1) salt 가용성 — label 후보. row_ref_map 없어도 hit hash coverage 충분하면 label.
    if salt is not None and str(salt).strip():
        if _has_full_phase1_position_coverage(phase1, row_ref_map or []):
            return "label"
        # partial coverage — label 진입 시 silent unmatched → doc_id / position 으로 fallback.
    # 2) document_id 가용성 — doc_id 차선.
    for case in case_set.iter_all_cases_sorted():
        for ref in case.row_refs:
            if not ref.document_id:
                return "position"
    return "doc_id"


def _has_full_phase1_position_coverage(
    phase1: Phase1CaseResult,
    row_ref_map: list[dict[str, Any]],
) -> bool:
    """PHASE1 raw_rule_hits 의 모든 hit 가 label 매칭 가능한지 검사.

    invariant #76 — hit hash 필드 우선:
    1. ``canonical_label_hash`` 가 truthy → row_ref_map 없이도 직접 매칭 가능 (PASS).
    2. 빈 값 → row_ref_map[position] 으로 보완 가능해야 함.

    Why: ``_build_position_to_entry`` 결과의 keys 를 재사용 — coverage 검사와 매칭
    인덱스가 동일 position 정규화 (``int(entry["position"])``) 를 공유한다. 두
    helper 의 position 허용 범위가 어긋나면 ``{"position": "10"}`` 같은 문자열
    숫자 entry 에서 explicit label 은 매칭 가능한데 auto 는 fallback 하는 비정합
    이 발생한다. 단일 출처로 묶어 차단.

    PHASE1 hit 0 인 경우 (빈 phase1) → coverage 검사 무의미, True (label 자동 채택).
    hit 측 hash 도 없고 row_ref_map 에도 없는 hit 이 하나라도 있으면 False —
    label 의 silent unmatched 위험.
    """
    if not phase1.cases:
        return True  # 검사할 hit 없음
    rrm_positions = _build_position_to_entry(row_ref_map).keys()
    for phase1_case in phase1.cases:
        for hit in phase1_case.raw_rule_hits:
            # invariant #76 — hit 의 canonical_label_hash 가용하면 row_ref_map 없이도 OK.
            if getattr(hit, "canonical_label_hash", ""):
                continue
            # 없으면 row_ref_map 에서 보완 가능해야 함.
            if hit.row_index not in rrm_positions:
                return False
    return True


# ---------------------------------------------------------------------------
# 공통 helper — case_set 순회 + ref 수집
# ---------------------------------------------------------------------------


def _iter_phase2_refs(case_set: Phase2CaseSet) -> list[tuple[Any, Phase2RowRef]]:
    """case_set 의 모든 ref 를 (case, ref) 쌍으로."""
    items: list[tuple[Any, Phase2RowRef]] = []
    for case in case_set.iter_all_cases_sorted():
        for ref in case.row_refs:
            items.append((case, ref))
    return items


def _build_position_to_entry(row_ref_map: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """row_ref_map entries → ``position`` → entry dict 인덱스.

    position 키 부재 entry 는 skip (방어적). 결정성을 위해 동일 position 이 여러
    번 등장하면 첫 entry 보존.
    """
    out: dict[int, dict[str, Any]] = {}
    for entry in row_ref_map:
        if "position" not in entry:
            continue
        try:
            pos = int(entry["position"])
        except (TypeError, ValueError):
            continue
        if pos not in out:
            out[pos] = entry
    return out


def _finalize_linked_result(
    *,
    case_set: Phase2CaseSet,
    refs_by_case_id: dict[str, tuple[str, ...]],
    phase1_hit_count: int,
    key_mode_used: str,
) -> LinkerResult:
    """refs_by_case_id 부착 후 LinkerResult 생성 — diagnostics 계산 포함."""
    linked_count = sum(1 for refs in refs_by_case_id.values() if refs)
    unmatched_count = sum(1 for refs in refs_by_case_id.values() if not refs)
    linked_case_set = case_set.with_phase1_refs(refs_by_case_id)
    return LinkerResult(
        case_set=linked_case_set,
        diagnostics={
            "linked_count": linked_count,
            "phase1_hit_count": phase1_hit_count,
            "unmatched_phase2_count": unmatched_count,
            "key_mode_used": key_mode_used,
            "match_precision": _MATCH_PRECISION.get(key_mode_used, "row"),
        },
    )


# ---------------------------------------------------------------------------
# position 매칭 (S4 MVP)
# ---------------------------------------------------------------------------


def _link_via_position(
    *,
    case_set: Phase2CaseSet,
    phase1: Phase1CaseResult,
) -> LinkerResult:
    """row_position 등가 매칭 — S4 MVP 알고리즘."""
    # ── Pass 1 — needed_positions 수집 ──────────────────────────────────
    needed_positions: set[int] = set()
    for _case, ref in _iter_phase2_refs(case_set):
        needed_positions.add(ref.row_position)

    # ── Pass 2 — position → set[phase1_case_id] inverse index ───────────
    position_to_phase1_ids: dict[int, set[str]] = {}
    phase1_hit_count = 0
    for phase1_case in phase1.cases:
        for hit in phase1_case.raw_rule_hits:
            if hit.row_index in needed_positions:
                position_to_phase1_ids.setdefault(hit.row_index, set()).add(phase1_case.case_id)
                phase1_hit_count += 1

    # ── Pass 3 — refs_by_case_id 조립 (stale refs 방지) ─────────────────
    refs_by_case_id: dict[str, tuple[str, ...]] = {}
    for case in case_set.iter_all_cases_sorted():
        matched: set[str] = set()
        for ref in case.row_refs:
            matched.update(position_to_phase1_ids.get(ref.row_position, set()))
        refs_by_case_id[case.phase2_case_id] = tuple(sorted(matched))

    return _finalize_linked_result(
        case_set=case_set,
        refs_by_case_id=refs_by_case_id,
        phase1_hit_count=phase1_hit_count,
        key_mode_used="position",
    )


# ---------------------------------------------------------------------------
# doc_id 매칭 (S4.next)
# ---------------------------------------------------------------------------


def _link_via_doc_id(
    *,
    case_set: Phase2CaseSet,
    phase1: Phase1CaseResult,
) -> LinkerResult:
    """document_id 등가 매칭 — row order / position 변형 무관 (S4.next).

    PHASE2 ref / PHASE1 hit 의 ``document_id`` truthy 검사 — None / 빈 문자열은
    매칭 후보에서 제외 (invariant #40, #42).
    """
    # ── Pass 1 — needed_doc_ids 수집 ────────────────────────────────────
    needed_doc_ids: set[str] = set()
    for _case, ref in _iter_phase2_refs(case_set):
        if ref.document_id:
            needed_doc_ids.add(ref.document_id)

    # ── Pass 2 — document_id → set[phase1_case_id] inverse index ────────
    doc_id_to_phase1_ids: dict[str, set[str]] = {}
    phase1_hit_count = 0
    for phase1_case in phase1.cases:
        for hit in phase1_case.raw_rule_hits:
            if hit.document_id and hit.document_id in needed_doc_ids:
                doc_id_to_phase1_ids.setdefault(hit.document_id, set()).add(phase1_case.case_id)
                phase1_hit_count += 1

    # ── Pass 3 — refs_by_case_id 조립 (stale refs 방지) ─────────────────
    refs_by_case_id: dict[str, tuple[str, ...]] = {}
    for case in case_set.iter_all_cases_sorted():
        matched: set[str] = set()
        for ref in case.row_refs:
            if ref.document_id:
                matched.update(doc_id_to_phase1_ids.get(ref.document_id, set()))
        refs_by_case_id[case.phase2_case_id] = tuple(sorted(matched))

    return _finalize_linked_result(
        case_set=case_set,
        refs_by_case_id=refs_by_case_id,
        phase1_hit_count=phase1_hit_count,
        key_mode_used="doc_id",
    )


# ---------------------------------------------------------------------------
# doc_line 매칭 (S4.next.2)
# ---------------------------------------------------------------------------


def _phase2_doc_line_key(ref: Phase2RowRef, *, salt: str) -> tuple[str, str] | None:
    """PHASE2 ref → (doc_id_hash, normalized line_number_key) 매칭 키.

    document_id / line_number_key 둘 다 truthy 일 때만 후보 반환 — None 이면 skip.
    """
    if not ref.document_id or not ref.line_number_key:
        return None
    normalized = normalize_line_number_key(ref.line_number_key)
    if not normalized:
        return None
    return (hash_ref_key(ref.document_id, salt=salt), normalized)


def _phase1_doc_line_key(
    hit: Any, position_to_entry: dict[int, dict[str, Any]]
) -> tuple[str, str] | None:
    """PHASE1 hit → (doc_id_hash, normalized line_number_key) 매칭 키.

    invariant #75 — hit 의 hash 필드 우선. PHASE1 빌더가 engagement_salt 를 받고
    산출한 hash 가 있으면 row_ref_map sidecar 없이도 직접 매칭. 빈 값이면 (구
    schema 결과) row_ref_map entry 의 hash 로 fallback — store 가 같은 salt 로
    hash 한 값이라 동일 input 이 동일 hash 로 일치.
    """
    # Hit 측 hash 우선 (Phase 1 산출물 — 동일 engagement_salt 가정).
    direct_doc = getattr(hit, "doc_id_hash", "") or ""
    direct_line = getattr(hit, "line_number_key", None)
    if direct_doc and direct_line:
        normalized = normalize_line_number_key(direct_line)
        if normalized:
            return (direct_doc, normalized)
    # Fallback — row_ref_map entry (구 schema PHASE1 결과 backward compat).
    entry = position_to_entry.get(hit.row_index)
    if entry is None:
        return None
    doc_hash = entry.get("doc_id_hash")
    line_key = entry.get("line_number_key")
    if not doc_hash or not line_key:
        return None
    normalized = normalize_line_number_key(line_key)
    if not normalized:
        return None
    return (doc_hash, normalized)


def _link_via_doc_line(
    *,
    case_set: Phase2CaseSet,
    phase1: Phase1CaseResult,
    row_ref_map: list[dict[str, Any]],
    salt: str,
) -> LinkerResult:
    """(document_id_hash, normalized line_number_key) 페어 매칭 — line-level precision.

    multi-line 전표 내에서 정확한 row 매칭. invariant #46.
    """
    position_to_entry = _build_position_to_entry(row_ref_map)

    # ── Pass 1 — needed keys 수집 ──────────────────────────────────────
    needed_keys: set[tuple[str, str]] = set()
    for _case, ref in _iter_phase2_refs(case_set):
        key = _phase2_doc_line_key(ref, salt=salt)
        if key is not None:
            needed_keys.add(key)

    # ── Pass 2 — key → set[phase1_case_id] inverse index ───────────────
    key_to_phase1_ids: dict[tuple[str, str], set[str]] = {}
    phase1_hit_count = 0
    for phase1_case in phase1.cases:
        for hit in phase1_case.raw_rule_hits:
            hit_key = _phase1_doc_line_key(hit, position_to_entry)
            if hit_key is not None and hit_key in needed_keys:
                key_to_phase1_ids.setdefault(hit_key, set()).add(phase1_case.case_id)
                phase1_hit_count += 1

    # ── Pass 3 — refs_by_case_id 조립 ──────────────────────────────────
    refs_by_case_id: dict[str, tuple[str, ...]] = {}
    for case in case_set.iter_all_cases_sorted():
        matched: set[str] = set()
        for ref in case.row_refs:
            key = _phase2_doc_line_key(ref, salt=salt)
            if key is not None:
                matched.update(key_to_phase1_ids.get(key, set()))
        refs_by_case_id[case.phase2_case_id] = tuple(sorted(matched))

    return _finalize_linked_result(
        case_set=case_set,
        refs_by_case_id=refs_by_case_id,
        phase1_hit_count=phase1_hit_count,
        key_mode_used="doc_line",
    )


# ---------------------------------------------------------------------------
# company_doc 매칭 (S4.next.2)
# ---------------------------------------------------------------------------


def _phase2_company_doc_key(ref: Phase2RowRef, *, salt: str) -> tuple[str, str] | None:
    """PHASE2 ref → (company_code_hash, doc_id_hash) 매칭 키."""
    if not ref.company_code or not ref.document_id:
        return None
    return (
        hash_ref_key(ref.company_code, salt=salt),
        hash_ref_key(ref.document_id, salt=salt),
    )


def _phase1_company_doc_key(
    hit: Any, position_to_entry: dict[int, dict[str, Any]]
) -> tuple[str, str] | None:
    """PHASE1 hit → (company_code_hash, doc_id_hash) 매칭 키.

    invariant #75 — hit 의 hash 필드 우선, 빈 값이면 row_ref_map fallback.
    Phase 1 빌더가 engagement_salt 를 받으면 (S6.next Phase 2 산출물) company_code
    도 hash 산출하여 hit 에 보유. 그 경우 row_ref_map 없이도 직접 매칭 가능.
    """
    # Hit 측 hash 우선 (S6.next Phase 2 추가 필드).
    direct_company = getattr(hit, "company_code_hash", "") or ""
    direct_doc = getattr(hit, "doc_id_hash", "") or ""
    if direct_company and direct_doc:
        return (direct_company, direct_doc)
    # Fallback — row_ref_map entry (구 schema / partial fields).
    entry = position_to_entry.get(hit.row_index)
    if entry is None:
        return None
    company_hash = entry.get("company_code_hash")
    doc_hash = entry.get("doc_id_hash")
    if not company_hash or not doc_hash:
        return None
    return (company_hash, doc_hash)


def _link_via_company_doc(
    *,
    case_set: Phase2CaseSet,
    phase1: Phase1CaseResult,
    row_ref_map: list[dict[str, Any]],
    salt: str,
) -> LinkerResult:
    """(company_code_hash, document_id_hash) 페어 매칭 — multi-company disambiguation.

    invariant #47.
    """
    position_to_entry = _build_position_to_entry(row_ref_map)

    needed_keys: set[tuple[str, str]] = set()
    for _case, ref in _iter_phase2_refs(case_set):
        key = _phase2_company_doc_key(ref, salt=salt)
        if key is not None:
            needed_keys.add(key)

    key_to_phase1_ids: dict[tuple[str, str], set[str]] = {}
    phase1_hit_count = 0
    for phase1_case in phase1.cases:
        for hit in phase1_case.raw_rule_hits:
            hit_key = _phase1_company_doc_key(hit, position_to_entry)
            if hit_key is not None and hit_key in needed_keys:
                key_to_phase1_ids.setdefault(hit_key, set()).add(phase1_case.case_id)
                phase1_hit_count += 1

    refs_by_case_id: dict[str, tuple[str, ...]] = {}
    for case in case_set.iter_all_cases_sorted():
        matched: set[str] = set()
        for ref in case.row_refs:
            key = _phase2_company_doc_key(ref, salt=salt)
            if key is not None:
                matched.update(key_to_phase1_ids.get(key, set()))
        refs_by_case_id[case.phase2_case_id] = tuple(sorted(matched))

    return _finalize_linked_result(
        case_set=case_set,
        refs_by_case_id=refs_by_case_id,
        phase1_hit_count=phase1_hit_count,
        key_mode_used="company_doc",
    )


# ---------------------------------------------------------------------------
# label 매칭 (S4.next.2) — 가장 strict
# ---------------------------------------------------------------------------


def _phase2_label_key(ref: Phase2RowRef, *, salt: str) -> str | None:
    """PHASE2 ref → canonical_label_hash 매칭 키.

    Phase2RowRef.index_label 은 invariant 상 이미 canonical string (make_row_ref
    통과) — 추가 canonicalize 없이 hash_ref_key 적용.
    """
    if not ref.index_label:
        return None
    return hash_ref_key(ref.index_label, salt=salt)


def _phase1_label_key(hit: Any, position_to_entry: dict[int, dict[str, Any]]) -> str | None:
    """PHASE1 hit → canonical_label_hash 매칭 키.

    invariant #75 — hit 의 hash 필드 우선. Phase 1 빌더가 engagement_salt 로 산출한
    canonical_label_hash 가 있으면 row_ref_map sidecar 없이 직접 사용 — pipeline
    attach 시 row_ref_map 의존을 제거할 수 있다. 빈 값이면 row_ref_map entry 의
    hash 로 fallback (구 schema PHASE1 결과 backward compat).
    """
    # Hit 측 hash 우선.
    direct_hash = getattr(hit, "canonical_label_hash", "") or ""
    if direct_hash:
        return direct_hash
    # Fallback — row_ref_map entry.
    entry = position_to_entry.get(hit.row_index)
    if entry is None:
        return None
    label_hash = entry.get("canonical_label_hash")
    if not label_hash:
        return None
    return label_hash


def _link_via_label(
    *,
    case_set: Phase2CaseSet,
    phase1: Phase1CaseResult,
    row_ref_map: list[dict[str, Any]],
    salt: str,
) -> LinkerResult:
    """canonical_label_hash 직접 비교 — 가장 strict, row-precise.

    cross-engagement / out-of-process 시나리오에서도 동일 row 식별이 가능.
    invariant #46.
    """
    position_to_entry = _build_position_to_entry(row_ref_map)

    needed_keys: set[str] = set()
    for _case, ref in _iter_phase2_refs(case_set):
        key = _phase2_label_key(ref, salt=salt)
        if key is not None:
            needed_keys.add(key)

    key_to_phase1_ids: dict[str, set[str]] = {}
    phase1_hit_count = 0
    for phase1_case in phase1.cases:
        for hit in phase1_case.raw_rule_hits:
            hit_key = _phase1_label_key(hit, position_to_entry)
            if hit_key is not None and hit_key in needed_keys:
                key_to_phase1_ids.setdefault(hit_key, set()).add(phase1_case.case_id)
                phase1_hit_count += 1

    refs_by_case_id: dict[str, tuple[str, ...]] = {}
    for case in case_set.iter_all_cases_sorted():
        matched: set[str] = set()
        for ref in case.row_refs:
            key = _phase2_label_key(ref, salt=salt)
            if key is not None:
                matched.update(key_to_phase1_ids.get(key, set()))
        refs_by_case_id[case.phase2_case_id] = tuple(sorted(matched))

    return _finalize_linked_result(
        case_set=case_set,
        refs_by_case_id=refs_by_case_id,
        phase1_hit_count=phase1_hit_count,
        key_mode_used="label",
    )


__all__ = ["LinkerResult", "link_phase2_to_phase1"]
