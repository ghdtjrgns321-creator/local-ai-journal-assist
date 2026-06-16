"""PHASE2 native case set 의 디스크 영속화 (save / load).

Why: PHASE2 family-native case 는 in-memory 만으로는 dashboard refresh / 재로딩
시 손실된다. engagement 폴더 `<engagement_dir>/phase2_cases/<batch_id>/` 아래
manifest.json + family.jsonl 로 결정적 직렬화하여 case_set 을 복원 가능하게
만든다. schema 1.1 부터 row_ref_map.jsonl 은 legacy linker fallback artifact 로
명시적으로 생성 또는 생략할 수 있다. raw / linked hash 와 row_ref_map 비식별화는
v7-plan S3 invariant #18~28 의 단일 출처.

## 민감 artifact 정책 (S3 lock)

본 모듈이 생성하는 `<engagement_dir>/phase2_cases/<batch_id>/` 디렉토리는
**민감 artifact** 다. 접근 격리는 engagement_dir 자체의 회사별 파일시스템 권한에
의존한다.

- `row_ref_map.jsonl` 을 생성하는 경우 식별자 (canonical_label / document_id / company_code) 는
  engagement-scoped salt 로 `hash_ref_key` 통과 → S4 linker 의 cross-reference
  단계에서만 사용. 외부 노출 표면이 최소화됨.
- `<family>.jsonl` 은 `_case_to_canonical_dict(case)` 결과를 그대로 직렬화하므로
  case 안의 row_refs / left_ref / right_ref / counterparty_pair 에 **raw
  document_id / company_code 가 그대로 포함된다**. 감사인 UI / 디버깅이 원본
  식별자를 필요로 하기 때문에 의도된 동작이다.
- 따라서 본 artifact 디렉토리는 회사별 권한 격리 외부로 배포 / 복사 금지. 외부
  배포가 필요한 경우 별도 비식별화 export 파이프라인을 별도 정의해야 한다.
- row_ref_map 만 비식별화한 이유: PHASE1 raw_rule_hits 와의 cross-reference 표면
  (Δ19 lazy two-pass inverse index) 에서 노출되는 키 집합을 줄이기 위함.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.models.phase2_case import (
    DuplicateCase,
    IntercompanyCase,
    Phase2CaseSet,
    Phase2RowRef,
    RelationalCase,
    TimeseriesCase,
    UnsupervisedCase,
)
from src.services.artifact_path_safety import safe_batch_artifact_dir
from src.services.phase2_case_hash import (
    _RAW_HASH_EXCLUDED_FIELDS,
    _case_to_canonical_dict,
    compute_linked_case_hash,
    compute_raw_case_hash,
)
from src.services.phase2_ref_pseudonymize import hash_ref_key

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.1"
_SUPPORTED_SCHEMA_VERSIONS: frozenset[str] = frozenset({"1.0", SCHEMA_VERSION})
_ROW_REF_MAP_STATUS_GENERATED = "generated"
_ROW_REF_MAP_STATUS_OMITTED = "omitted"
_ROW_REF_MAP_ALLOWED_STATUSES: frozenset[str] = frozenset(
    {_ROW_REF_MAP_STATUS_GENERATED, _ROW_REF_MAP_STATUS_OMITTED}
)

# Why: family 이름 → Phase2CaseSet 의 tuple 필드명 매핑.
#      jsonl 파일명과 케이스셋 attribute 를 한 줄에서 관리.
_FAMILY_TO_ATTR: dict[str, str] = {
    "duplicate": "duplicate_cases",
    "intercompany": "intercompany_cases",
    "relational": "relational_cases",
    "unsupervised": "unsupervised_cases",
    "timeseries": "timeseries_cases",
}

# Why: load 시 family 이름 → dataclass 매핑. row_refs 재구성을 위해 사용.
_FAMILY_TO_DATACLASS: dict[str, type] = {
    "duplicate": DuplicateCase,
    "intercompany": IntercompanyCase,
    "relational": RelationalCase,
    "unsupervised": UnsupervisedCase,
    "timeseries": TimeseriesCase,
}


class CaseStoreStatus:
    """save / load 진단 상태. UI 는 status 별로 다른 안내 메시지를 분기한다."""

    SAVED = "saved"
    LOAD_SUCCESS = "load_success"
    MISSING = "missing"
    SCHEMA_MISMATCH = "schema_mismatch"
    BATCH_ID_MISMATCH = "batch_id_mismatch"
    INVALID_PAYLOAD = "invalid_payload"
    UNSAFE_BATCH_ID = "unsafe_batch_id"
    CTX_MISSING = "ctx_missing"
    SALT_MISSING = "salt_missing"
    # Why: load 시 manifest 가 기록한 hash 와 실제 sidecar / case_set 의 hash 가
    #      일치하는지 재계산 검증. S4.next linker 가 row_ref_map 의 hash 식별자에
    #      의존할 예정이므로 missing / 변조 상태에서 LOAD_SUCCESS 를 반환하지 않는다.
    #      S4 MVP linker 는 row_ref_map 을 사용하지 않지만 sidecar 무결성은 본 단계
    #      에서 미리 보장한다 (S4.next attach 시점 추가 가드 불필요).
    ROW_REF_MAP_MISSING = "row_ref_map_missing"
    ROW_REF_MAP_HASH_MISMATCH = "row_ref_map_hash_mismatch"
    CASE_HASH_MISMATCH = "case_hash_mismatch"
    # Why: store key_mode 가 linker capability 와 어긋나면 manifest 가 잘못된
    # 신호를 발사한다. silent 통과 대신 명시 status 로 차단.
    UNSAFE_KEY_MODE = "unsafe_key_mode"


# Why: store 가 manifest 에 기록할 수 있는 key_mode 허용 집합 —
# phase2_case_phase1_linker._ALLOWED_KEY_MODES 와 동기화 (minus "auto").
# "auto" 는 linker runtime resolution 결과 (resolved mode 중 하나) 로 기록되어야
# 하므로 저장 enum 에서는 제외. S4.next.2 — doc_line / company_doc / label 추가.
_STORE_ALLOWED_KEY_MODES: frozenset[str] = frozenset(
    {"position", "doc_id", "doc_line", "company_doc", "label"}
)


@dataclass(frozen=True)
class Phase2CaseStoreResult:
    """case store 호출 진단 결과.

    diagnostics 는 status 별 추가 컨텍스트 — expected/got 값, 경로, 사유 등.
    """

    status: str
    manifest_path: Path | None
    case_set: Phase2CaseSet | None = None
    raw_case_hash: str | None = None
    linked_case_hash: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 공통 helper
# ---------------------------------------------------------------------------


def _engagement_dir(ctx: Any) -> Path | None:
    """`ctx.db_path` 의 parent 를 engagement 디렉토리로 해석한다.

    ctx 가 None / db_path 부재 → None. overlay store 의 동일 helper 와 정합.
    """
    if ctx is None:
        return None
    db_path = getattr(ctx, "db_path", None)
    if db_path is None:
        return None
    try:
        return Path(db_path).parent
    except (TypeError, ValueError):
        return None


def _is_valid_salt(salt: str | None) -> bool:
    """salt 가 non-empty + non-whitespace 인지 검증. hash_ref_key 호출 전 게이트."""
    if not salt:
        return False
    return bool(salt.strip())


def _canonical_jsonl_line(payload: dict[str, Any]) -> str:
    """jsonl 1 줄용 결정적 JSON 직렬화 — sort_keys + 압축 separator + default=str."""
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


# ---------------------------------------------------------------------------
# row_ref_map 빌드
# ---------------------------------------------------------------------------


def _row_ref_entry(ref: Phase2RowRef, *, salt: str) -> dict[str, Any]:
    """단일 Phase2RowRef → row_ref_map jsonl entry.

    invariant #18 — canonical_label / doc_id / company_code 는 hash_ref_key 통과.
    invariant #19 — line_number_key 는 hash 안 함 (canonical string 그대로).
    Phase2RowRef.index_label 은 make_row_ref 가 이미 canonicalize 한 결과이므로
    여기서 재호출하지 않는다 (strict canonicalize → "s:i:10" 이중 prefix 방지).
    """
    return {
        "position": ref.row_position,
        "canonical_label_hash": hash_ref_key(ref.index_label, salt=salt),
        "doc_id_hash": hash_ref_key(ref.document_id, salt=salt) if ref.document_id else None,
        "company_code_hash": (
            hash_ref_key(ref.company_code, salt=salt) if ref.company_code else None
        ),
        "line_number_key": ref.line_number_key,
    }


def _collect_unique_row_refs(case_set: Phase2CaseSet) -> dict[int, Phase2RowRef]:
    """모든 case 의 row_refs + DuplicateCase.left_ref/right_ref 를 position 기준 dedup.

    invariant #28 — 같은 position 이 여러 case 에 등장해도 1 entry.
    먼저 등장한 ref 를 보존 (iter_all_cases_sorted 순회 순서가 결정적).
    """
    by_position: dict[int, Phase2RowRef] = {}
    for case in case_set.iter_all_cases_sorted():
        for ref in case.row_refs:
            if ref.row_position not in by_position:
                by_position[ref.row_position] = ref
        # DuplicateCase 의 left_ref / right_ref 도 dedup 대상에 포함.
        # 보통 row_refs 와 동일 ref 라 dedup 효과로 처리되지만,
        # row_refs 와 별개로 채워진 경우를 안전하게 흡수.
        if isinstance(case, DuplicateCase):
            for extra in (case.left_ref, case.right_ref):
                if extra is None:
                    continue
                if extra.row_position not in by_position:
                    by_position[extra.row_position] = extra
    return by_position


def _build_row_ref_map(case_set: Phase2CaseSet, *, salt: str) -> list[dict[str, Any]]:
    """case_set 전체에서 unique row_ref entry 리스트 (position 사전순)."""
    by_position = _collect_unique_row_refs(case_set)
    return [_row_ref_entry(by_position[pos], salt=salt) for pos in sorted(by_position.keys())]


# ---------------------------------------------------------------------------
# family jsonl 직렬화
# ---------------------------------------------------------------------------


def _case_to_jsonl_payload(case: Any, *, linked: bool) -> dict[str, Any]:
    """case → jsonl payload. linked=False 면 phase1_case_refs 키 제외."""
    if linked:
        return _case_to_canonical_dict(case)
    return _case_to_canonical_dict(case, exclude=_RAW_HASH_EXCLUDED_FIELDS)


def _write_family_jsonls(base_dir: Path, case_set: Phase2CaseSet) -> None:
    """비어있지 않은 family 의 jsonl 만 생성 (invariant #23)."""
    for family, attr in _FAMILY_TO_ATTR.items():
        cases = getattr(case_set, attr)
        if not cases:
            continue
        path = base_dir / f"{family}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for case in cases:
                payload = _case_to_jsonl_payload(case, linked=case_set.linked)
                f.write(_canonical_jsonl_line(payload) + "\n")


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------


def save_phase2_case_set(
    *,
    ctx: Any,
    batch_id: str,
    case_set: Phase2CaseSet,
    salt: str,
    key_mode: str = "position",
    phase2_training_report_id: str | None = None,
    phase2_partition: str | None = None,
    write_row_ref_map: bool = True,
) -> Phase2CaseStoreResult:
    """case_set 을 engagement 폴더에 manifest + jsonl 로 저장한다.

    Args:
        key_mode: manifest 가 기록하는 linker capability 표식 — 운영자에게
            현재 linker 가 어떤 식별자 우선순위로 cross-reference 했는지 알린다.
            **linker 의 ``_ALLOWED_KEY_MODES`` (minus "auto") 와 동기화** — 두 enum
            이 어긋나면 운영자 / orchestrator 가 manifest 를 잘못 해석한다.
            허용:
              - "position":    S4 MVP — row_position 등가 (row-level).
              - "doc_id":      S4.next — document_id 등가 (document-level).
              - "doc_line":    S4.next.2 — (doc_id_hash, normalized line_number_key) (row-level).
              - "company_doc": S4.next.2 — (company_code_hash, doc_id_hash) (document-level).
              - "label":       S4.next.2 — canonical_label_hash 직접 (row-level, strict).
            기본값 "position" — S4 MVP linker capability 와 정합. ``"auto"`` 는
            linker runtime resolution 결과로만 의미 있으므로 store 입력으로는 거절.
        write_row_ref_map: True 이면 legacy linker fallback 용 `row_ref_map.jsonl`
            을 생성하고 manifest 에 hash 를 기록한다. False 이면 schema 1.1
            manifest 에 `row_ref_map_status="omitted"` 를 기록하고 load 시 sidecar
            무결성 검증을 건너뛴다. 기본값 True 로 기존 저장 계약을 보존한다.

    실패 케이스는 모두 status 로 분기하고 manifest_path=None 으로 반환한다.
    """
    # invariant — store key_mode 가 linker 와 sync. unknown enum 입력은 silent 통과 금지.
    if key_mode not in _STORE_ALLOWED_KEY_MODES:
        return Phase2CaseStoreResult(
            status=CaseStoreStatus.UNSAFE_KEY_MODE,
            manifest_path=None,
            diagnostics={
                "expected": sorted(_STORE_ALLOWED_KEY_MODES),
                "got": key_mode,
            },
        )
    # 1) salt 검증 — invariant #24, hash_ref_key 호출 전에 차단.
    if not _is_valid_salt(salt):
        return Phase2CaseStoreResult(
            status=CaseStoreStatus.SALT_MISSING,
            manifest_path=None,
            diagnostics={"reason": "salt is empty or whitespace-only"},
        )

    # 2) ctx → engagement_dir 해석 — invariant #26.
    engagement_dir = _engagement_dir(ctx)
    if engagement_dir is None:
        return Phase2CaseStoreResult(
            status=CaseStoreStatus.CTX_MISSING,
            manifest_path=None,
            diagnostics={"reason": "ctx or ctx.db_path is missing"},
        )

    # 3) batch_id 안전성 — invariant #25.
    base_dir = safe_batch_artifact_dir(engagement_dir, batch_id)
    if base_dir is None:
        return Phase2CaseStoreResult(
            status=CaseStoreStatus.UNSAFE_BATCH_ID,
            manifest_path=None,
            diagnostics={"batch_id": str(batch_id) if batch_id else ""},
        )

    base_dir.mkdir(parents=True, exist_ok=True)

    # 4) row_ref_map.jsonl — unique position dedup + hash.
    # schema 1.1 부터 sidecar 는 legacy fallback 으로 optional. 기본은 generated 로
    # 두어 기존 artifact/load 계약을 유지한다.
    row_ref_count = len(_collect_unique_row_refs(case_set))
    row_ref_map_hash: str | None = None
    row_ref_map_status = _ROW_REF_MAP_STATUS_OMITTED
    if write_row_ref_map:
        row_ref_entries = _build_row_ref_map(case_set, salt=salt)
        row_ref_serialized = "".join(
            _canonical_jsonl_line(entry) + "\n" for entry in row_ref_entries
        )
        (base_dir / "row_ref_map.jsonl").write_text(row_ref_serialized, encoding="utf-8")
        row_ref_map_hash = "sha256:" + hashlib.sha256(row_ref_serialized.encode()).hexdigest()
        row_ref_count = len(row_ref_entries)
        row_ref_map_status = _ROW_REF_MAP_STATUS_GENERATED
    else:
        # Avoid stale fallback artifacts when a caller intentionally writes an omitted manifest
        # for an existing batch directory.
        stale_row_ref_path = base_dir / "row_ref_map.jsonl"
        if stale_row_ref_path.exists():
            stale_row_ref_path.unlink()

    # 5) family.jsonl — invariant #23 (빈 family 미생성).
    _write_family_jsonls(base_dir, case_set)

    # 6) hash 계산 — invariant #20~22.
    raw_hash = compute_raw_case_hash(case_set)
    linked_hash = compute_linked_case_hash(case_set) if case_set.linked else None

    # 7) manifest.json 작성.
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "batch_id": batch_id,
        "written_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "row_count": row_ref_count,
        "case_counts": {
            family: len(getattr(case_set, attr)) for family, attr in _FAMILY_TO_ATTR.items()
        },
        "row_ref_map_hash": row_ref_map_hash,
        "row_ref_map_status": row_ref_map_status,
        "key_mode": key_mode,
        "raw_case_hash": raw_hash,
        "linked_case_hash": linked_hash,
        "phase2_training_report_id": phase2_training_report_id,
        "phase2_partition": phase2_partition,
    }
    manifest_path = base_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return Phase2CaseStoreResult(
        status=CaseStoreStatus.SAVED,
        manifest_path=manifest_path,
        case_set=case_set,
        raw_case_hash=raw_hash,
        linked_case_hash=linked_hash,
    )


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------


def _row_ref_from_dict(payload: dict[str, Any]) -> Phase2RowRef:
    """jsonl row_ref dict → Phase2RowRef. index_label 은 canonical string 그대로 (invariant #27)."""
    return Phase2RowRef(
        row_position=int(payload.get("row_position", 0)),
        # invariant #27 — index_label 은 canonicalize 결과 string 으로 고정.
        # raw 타입 복원 없이 그대로 둔다. 부재 시 "n:" (None canonical) 로 안전 기본.
        index_label=str(payload.get("index_label") or "n:"),
        document_id=payload.get("document_id"),
        line_number_key=payload.get("line_number_key"),
        company_code=payload.get("company_code"),
    )


def _restore_row_refs(field_value: Any) -> Any:
    """payload 의 row_refs 필드 (list of dict) → tuple[Phase2RowRef, ...]."""
    if field_value is None:
        return None
    if isinstance(field_value, dict):
        return _row_ref_from_dict(field_value)
    if isinstance(field_value, list):
        return tuple(_row_ref_from_dict(item) for item in field_value)
    return field_value


def _case_from_dict(family: str, payload: dict[str, Any]) -> Any:
    """jsonl line dict → 해당 family dataclass 인스턴스."""
    cls = _FAMILY_TO_DATACLASS[family]
    kwargs: dict[str, Any] = {}
    for f_name, f_value in payload.items():
        if f_name == "row_refs":
            kwargs[f_name] = _restore_row_refs(f_value) or ()
        elif f_name in {"left_ref", "right_ref", "max_score_row_ref"}:
            kwargs[f_name] = _restore_row_refs(f_value)
        elif f_name == "phase1_case_refs":
            kwargs[f_name] = tuple(f_value) if isinstance(f_value, list) else ()
        elif f_name == "counterparty_pair" and isinstance(f_value, list):
            # IntercompanyCase 의 counterparty_pair 는 tuple[str, str] 이지만 JSON 은 list.
            kwargs[f_name] = tuple(f_value)
        elif f_name in {"top_features", "max_score_top_features"} and isinstance(f_value, list):
            # UnsupervisedCase feature trace fields are tuple[dict, ...].
            kwargs[f_name] = tuple(f_value)
        else:
            kwargs[f_name] = f_value
    return cls(**kwargs)


def _read_family_jsonl(base_dir: Path, family: str) -> list[dict[str, Any]] | None:
    """family jsonl 을 dict list 로 읽는다. 미존재 → 빈 list. 파싱 실패 → None."""
    path = base_dir / f"{family}.jsonl"
    if not path.exists():
        return []
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return [json.loads(line) for line in lines]
    except (OSError, json.JSONDecodeError):
        return None


def load_phase2_case_set(
    *,
    ctx: Any,
    batch_id: str,
) -> Phase2CaseStoreResult:
    """저장된 case_set 을 manifest + jsonl 에서 복원한다."""
    # 1) ctx / batch_id 게이트.
    engagement_dir = _engagement_dir(ctx)
    if engagement_dir is None:
        return Phase2CaseStoreResult(
            status=CaseStoreStatus.CTX_MISSING,
            manifest_path=None,
            diagnostics={"reason": "ctx or ctx.db_path is missing"},
        )
    base_dir = safe_batch_artifact_dir(engagement_dir, batch_id)
    if base_dir is None:
        return Phase2CaseStoreResult(
            status=CaseStoreStatus.UNSAFE_BATCH_ID,
            manifest_path=None,
            diagnostics={"batch_id": str(batch_id) if batch_id else ""},
        )

    manifest_path = base_dir / "manifest.json"
    if not manifest_path.exists():
        return Phase2CaseStoreResult(
            status=CaseStoreStatus.MISSING,
            manifest_path=manifest_path,
            diagnostics={"reason": "manifest.json not found"},
        )

    # 2) manifest 파싱.
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return Phase2CaseStoreResult(
            status=CaseStoreStatus.INVALID_PAYLOAD,
            manifest_path=manifest_path,
            diagnostics={"reason": f"manifest parse error: {exc}"},
        )
    if not isinstance(manifest, dict):
        return Phase2CaseStoreResult(
            status=CaseStoreStatus.INVALID_PAYLOAD,
            manifest_path=manifest_path,
            diagnostics={"reason": "manifest root is not a JSON object"},
        )

    # 3) schema_version 검증.
    schema = str(manifest.get("schema_version") or "")
    if schema not in _SUPPORTED_SCHEMA_VERSIONS:
        return Phase2CaseStoreResult(
            status=CaseStoreStatus.SCHEMA_MISMATCH,
            manifest_path=manifest_path,
            diagnostics={"expected": sorted(_SUPPORTED_SCHEMA_VERSIONS), "got": schema},
        )

    # 4) batch_id 일치 검증.
    persisted_batch = str(manifest.get("batch_id") or "")
    if persisted_batch != batch_id:
        return Phase2CaseStoreResult(
            status=CaseStoreStatus.BATCH_ID_MISMATCH,
            manifest_path=manifest_path,
            diagnostics={"expected": batch_id, "got": persisted_batch},
        )

    # 5) family jsonl 읽기 + dataclass 재구성.
    family_payloads: dict[str, list[dict[str, Any]]] = {}
    for family in _FAMILY_TO_ATTR:
        payload_list = _read_family_jsonl(base_dir, family)
        if payload_list is None:
            return Phase2CaseStoreResult(
                status=CaseStoreStatus.INVALID_PAYLOAD,
                manifest_path=manifest_path,
                diagnostics={"reason": f"failed to parse {family}.jsonl"},
            )
        family_payloads[family] = payload_list

    try:
        family_cases: dict[str, tuple] = {
            family: tuple(_case_from_dict(family, p) for p in payloads)
            for family, payloads in family_payloads.items()
        }
    except (TypeError, KeyError, ValueError) as exc:
        return Phase2CaseStoreResult(
            status=CaseStoreStatus.INVALID_PAYLOAD,
            manifest_path=manifest_path,
            diagnostics={"reason": f"family payload decode error: {exc}"},
        )

    # 6) Phase2CaseSet 조립. linked 는 manifest.linked_case_hash 존재 여부로 추론.
    linked_case_hash = manifest.get("linked_case_hash")
    case_set = Phase2CaseSet(
        duplicate_cases=family_cases["duplicate"],
        intercompany_cases=family_cases["intercompany"],
        relational_cases=family_cases["relational"],
        unsupervised_cases=family_cases["unsupervised"],
        timeseries_cases=family_cases["timeseries"],
        linked=linked_case_hash is not None,
    )

    # 7) row_ref_map.jsonl 무결성 검증.
    #    schema 1.0 은 sidecar mandatory. schema 1.1 은 manifest 가 omitted 를
    #    명시한 경우에만 sidecar 없이 load 성공을 허용한다.
    row_ref_map_path = base_dir / "row_ref_map.jsonl"
    row_ref_map_status = str(manifest.get("row_ref_map_status") or "")
    if not row_ref_map_status:
        # Legacy schema 1.0 manifests did not carry status; presence of hash means generated.
        row_ref_map_status = _ROW_REF_MAP_STATUS_GENERATED
    if row_ref_map_status not in _ROW_REF_MAP_ALLOWED_STATUSES:
        return Phase2CaseStoreResult(
            status=CaseStoreStatus.INVALID_PAYLOAD,
            manifest_path=manifest_path,
            diagnostics={
                "reason": "invalid row_ref_map_status",
                "expected": sorted(_ROW_REF_MAP_ALLOWED_STATUSES),
                "got": row_ref_map_status,
            },
        )
    actual_row_ref_hash: str | None = None
    if row_ref_map_status == _ROW_REF_MAP_STATUS_GENERATED:
        if not row_ref_map_path.exists():
            return Phase2CaseStoreResult(
                status=CaseStoreStatus.ROW_REF_MAP_MISSING,
                manifest_path=manifest_path,
                diagnostics={"reason": "row_ref_map.jsonl not found"},
            )
        try:
            row_ref_serialized = row_ref_map_path.read_text(encoding="utf-8")
        except OSError as exc:
            return Phase2CaseStoreResult(
                status=CaseStoreStatus.INVALID_PAYLOAD,
                manifest_path=manifest_path,
                diagnostics={"reason": f"row_ref_map read error: {exc}"},
            )
        actual_row_ref_hash = "sha256:" + hashlib.sha256(row_ref_serialized.encode()).hexdigest()
        expected_row_ref_hash = str(manifest.get("row_ref_map_hash") or "")
        if actual_row_ref_hash != expected_row_ref_hash:
            return Phase2CaseStoreResult(
                status=CaseStoreStatus.ROW_REF_MAP_HASH_MISMATCH,
                manifest_path=manifest_path,
                diagnostics={
                    "expected": expected_row_ref_hash,
                    "got": actual_row_ref_hash,
                },
            )

    # 8) case_set hash 재계산 검증 — family jsonl 변조 감지.
    manifest_raw_hash = manifest.get("raw_case_hash")
    actual_raw_hash = compute_raw_case_hash(case_set)
    if manifest_raw_hash != actual_raw_hash:
        return Phase2CaseStoreResult(
            status=CaseStoreStatus.CASE_HASH_MISMATCH,
            manifest_path=manifest_path,
            diagnostics={
                "kind": "raw",
                "expected": manifest_raw_hash,
                "got": actual_raw_hash,
            },
        )
    if linked_case_hash is not None:
        actual_linked_hash = compute_linked_case_hash(case_set)
        if linked_case_hash != actual_linked_hash:
            return Phase2CaseStoreResult(
                status=CaseStoreStatus.CASE_HASH_MISMATCH,
                manifest_path=manifest_path,
                diagnostics={
                    "kind": "linked",
                    "expected": linked_case_hash,
                    "got": actual_linked_hash,
                },
            )

    return Phase2CaseStoreResult(
        status=CaseStoreStatus.LOAD_SUCCESS,
        manifest_path=manifest_path,
        case_set=case_set,
        raw_case_hash=actual_raw_hash,
        linked_case_hash=linked_case_hash,
        diagnostics={
            "phase2_training_report_id": manifest.get("phase2_training_report_id"),
            "phase2_partition": manifest.get("phase2_partition"),
            "written_at": manifest.get("written_at"),
            "key_mode": manifest.get("key_mode"),
            "row_ref_map_hash": actual_row_ref_hash,
            "row_ref_map_status": row_ref_map_status,
        },
    )


__all__ = [
    "CaseStoreStatus",
    "Phase2CaseStoreResult",
    "SCHEMA_VERSION",
    "load_phase2_case_set",
    "save_phase2_case_set",
]
