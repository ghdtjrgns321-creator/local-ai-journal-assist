"""PHASE2 case store (save / load) 의 디스크 영속화 계약 검증.

Why: v7-plan S3 invariant #18~28 — manifest schema 정합, row_ref_map 비식별화,
빈 family jsonl 미생성, salt/ctx/batch_id 안전성 가드, raw/linked hash 정합,
load roundtrip 의 canonical string 보존을 단위 테스트로 잠근다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.models.phase2_case import (
    Phase2CaseSet,
    Phase2RowRef,
    RelationalCase,
    UnsupervisedCase,
    make_row_ref,
)
from src.services.phase2_case_hash import (
    compute_linked_case_hash,
    compute_raw_case_hash,
)
from src.services.phase2_case_id import make_phase2_case_id
from src.services.phase2_case_store import (
    SCHEMA_VERSION,
    CaseStoreStatus,
    load_phase2_case_set,
    save_phase2_case_set,
)
from src.services.phase2_ref_pseudonymize import hash_ref_key

# ---------------------------------------------------------------------------
# Fixtures / 헬퍼
# ---------------------------------------------------------------------------


class _MockCtx:
    """CompanyContext 흉내. db_path 의 parent 가 engagement_dir 로 해석된다."""

    def __init__(self, db_path: Path | None) -> None:
        self.db_path = db_path


@pytest.fixture
def ctx(tmp_path: Path) -> _MockCtx:
    return _MockCtx(tmp_path / "audit.duckdb")


@pytest.fixture
def salt() -> str:
    return "engagement-001|batch-001"


@pytest.fixture
def batch_id() -> str:
    return "batch-001"


def _make_row_ref(
    *,
    row_position: int,
    index_label: Any = None,
    document_id: str | None = "DOC001",
    raw_line_number: Any = "0001",
    company_code: str | None = "C01",
) -> Phase2RowRef:
    """테스트용 row_ref 생성 helper — make_row_ref 통과로 canonical key 보존."""
    if index_label is None:
        index_label = row_position
    return make_row_ref(
        row_position=row_position,
        index_label=index_label,
        document_id=document_id,
        raw_line_number=raw_line_number,
        company_code=company_code,
    )


def _make_relational_case(
    *,
    batch_id: str,
    left_pos: int = 10,
    right_pos: int = 11,
    sub_rule: str = "L2-03a",
) -> RelationalCase:
    """RelationalCase fixture (case 인프라 generic pair fixture) — 두 row_ref 포함."""
    left = _make_row_ref(row_position=left_pos, index_label=left_pos)
    right = _make_row_ref(
        row_position=right_pos,
        index_label=right_pos,
        document_id="DOC002",
        raw_line_number="0002",
    )
    # Phase2RowRef.index_label 은 이미 canonical — production builder 와
    # 동일하게 재호출 없이 그대로 사용 (이중 prefix 방지, invariant #31).
    canonical_refs = (left.index_label, right.index_label)
    case_id = make_phase2_case_id(
        batch_id=batch_id,
        family="relational",
        unit_type="pair",
        canonical_refs=canonical_refs,
        evidence_signature=f"sub_rule={sub_rule}",
    )
    return RelationalCase(
        phase2_case_id=case_id,
        batch_id=batch_id,
        family="relational",
        unit_type="pair",
        row_refs=(left, right),
        evidence_tier="strong",
        case_generation_reason={"gate": "evidence_tier_strong"},
        family_score=0.95,
        family_ecdf=0.0,
        phase1_case_refs=(),
        sub_rule=sub_rule,
    )


def _make_unsupervised_case(
    *,
    batch_id: str,
    row_pos: int = 20,
    model_id: str = "model-A",
    schema_hash: str = "schema-A",
) -> UnsupervisedCase:
    """UnsupervisedCase fixture — document 단위 anomaly review case."""
    ref = _make_row_ref(
        row_position=row_pos,
        index_label=row_pos,
        document_id="DOC020",
        raw_line_number="0020",
        company_code="C03",
    )
    # Phase2RowRef.index_label 은 이미 canonical — 재호출 없이 그대로 사용.
    canonical_refs = (ref.index_label,)
    case_id = make_phase2_case_id(
        batch_id=batch_id,
        family="unsupervised",
        unit_type="document",
        canonical_refs=canonical_refs,
        evidence_signature=f"model={model_id}|schema={schema_hash}",
    )
    return UnsupervisedCase(
        phase2_case_id=case_id,
        batch_id=batch_id,
        family="unsupervised",
        unit_type="document",
        row_refs=(ref,),
        evidence_tier="ml_quantile",
        case_generation_reason={"gate": "unsupervised_ecdf", "threshold": 0.95},
        family_score=0.88,
        family_ecdf=0.97,
        phase1_case_refs=(),
        anomaly_score=0.88,
        document_id="DOC020",
        evidence_row_count=1,
        max_score_row_ref=ref,
        top_features=({"feature_id": "f1", "contrib": 0.5, "tag": "tag_a", "label_ko": "라벨A"},),
        max_score_top_features=(
            {"feature_id": "f1", "contrib": 0.5, "tag": "tag_a", "label_ko": "라벨A"},
        ),
        model_id=model_id,
        schema_hash=schema_hash,
    )


def _make_case_set(
    *,
    batch_id: str,
    linked: bool = False,
    with_unsupervised: bool = True,
    with_relational: bool = True,
) -> Phase2CaseSet:
    """duplicate + unsupervised 만 채운 case_set fixture (S3 범위)."""
    relational_cases = (_make_relational_case(batch_id=batch_id),) if with_relational else ()
    unsupervised_cases = (_make_unsupervised_case(batch_id=batch_id),) if with_unsupervised else ()
    case_set = Phase2CaseSet(
        relational_cases=relational_cases,
        unsupervised_cases=unsupervised_cases,
    )
    if linked:
        refs_by_case_id = {
            case.phase2_case_id: (f"p1_ref_{case.phase2_case_id[:6]}",)
            for case in case_set.iter_all_cases_sorted()
        }
        case_set = case_set.with_phase1_refs(refs_by_case_id)
    return case_set


# ---------------------------------------------------------------------------
# save 테스트 (14개)
# ---------------------------------------------------------------------------


def test_save_creates_phase2_cases_directory_under_engagement(
    ctx: _MockCtx, salt: str, batch_id: str, tmp_path: Path
) -> None:
    """`<engagement_dir>/phase2_cases/<batch_id>/` 디렉토리가 생성되는지."""
    case_set = _make_case_set(batch_id=batch_id)
    result = save_phase2_case_set(ctx=ctx, batch_id=batch_id, case_set=case_set, salt=salt)
    assert result.status == CaseStoreStatus.SAVED
    assert result.manifest_path is not None
    expected_dir = tmp_path / "phase2_cases" / batch_id
    assert expected_dir.is_dir()
    assert result.manifest_path == expected_dir / "manifest.json"


def test_save_writes_manifest_with_required_fields(ctx: _MockCtx, salt: str, batch_id: str) -> None:
    """manifest.json 에 schema_version / batch_id / case_counts / hash 등 필수 키."""
    case_set = _make_case_set(batch_id=batch_id)
    result = save_phase2_case_set(
        ctx=ctx,
        batch_id=batch_id,
        case_set=case_set,
        salt=salt,
        phase2_training_report_id="tr-001",
        phase2_partition="2024",
    )
    assert result.status == CaseStoreStatus.SAVED
    assert result.manifest_path is not None
    payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    for key in (
        "schema_version",
        "batch_id",
        "written_at",
        "row_count",
        "case_counts",
        "row_ref_map_hash",
        "row_ref_map_status",
        "key_mode",
        "raw_case_hash",
        "linked_case_hash",
        "phase2_training_report_id",
        "phase2_partition",
    ):
        assert key in payload, f"manifest missing key: {key}"
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["batch_id"] == batch_id
    assert payload["phase2_training_report_id"] == "tr-001"
    assert payload["phase2_partition"] == "2024"
    assert payload["row_ref_map_status"] == "generated"
    assert isinstance(payload["row_ref_map_hash"], str)
    # S4 MVP linker capability 와 정합 — default 는 "position".
    # S4.next 에서 label fallback 구현 후 default 가 "label" 로 승격될 예정.
    assert payload["key_mode"] == "position"


def test_save_default_key_mode_is_position_for_s4_mvp(
    ctx: _MockCtx, salt: str, batch_id: str
) -> None:
    """key_mode default 는 S4 MVP linker capability ("position") 와 정합 — 미래 변경 차단."""
    case_set = Phase2CaseSet(relational_cases=(_make_relational_case(batch_id=batch_id),))
    # key_mode 명시 안 함 — default 적용.
    result = save_phase2_case_set(ctx=ctx, batch_id=batch_id, case_set=case_set, salt=salt)
    assert result.status == CaseStoreStatus.SAVED
    assert result.manifest_path is not None
    payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert payload["key_mode"] == "position", (
        "S4 MVP linker 는 position-only. manifest key_mode default 가 'label' 이면 "
        "운영자가 label fallback 가용한 것으로 오해할 수 있다."
    )


def test_save_explicit_key_mode_preserved_in_manifest(
    ctx: _MockCtx, salt: str, batch_id: str
) -> None:
    """현재 linker capability 인 'position' / 'doc_id' 명시 입력은 manifest 에 그대로 기록.

    'label' / 'doc_line' / 'company_doc' 은 S4.next.2 deferred —
    test_save_rejects_deferred_key_modes 에서 별도 거절 검증.
    """
    case_set = Phase2CaseSet(relational_cases=(_make_relational_case(batch_id=batch_id),))
    for explicit_mode in ("position", "doc_id"):
        result = save_phase2_case_set(
            ctx=ctx,
            batch_id=batch_id + f"-{explicit_mode}",
            case_set=case_set,
            salt=salt,
            key_mode=explicit_mode,
        )
        assert result.status == CaseStoreStatus.SAVED
        assert result.manifest_path is not None
        payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
        assert payload["key_mode"] == explicit_mode


def test_save_writes_family_jsonl_for_each_nonempty_family(
    ctx: _MockCtx, salt: str, batch_id: str
) -> None:
    """duplicate / unsupervised case 가 있으면 두 family jsonl 모두 생성."""
    case_set = _make_case_set(batch_id=batch_id)
    result = save_phase2_case_set(ctx=ctx, batch_id=batch_id, case_set=case_set, salt=salt)
    assert result.manifest_path is not None
    base_dir = result.manifest_path.parent
    assert (base_dir / "relational.jsonl").exists()
    assert (base_dir / "unsupervised.jsonl").exists()
    # 각 jsonl 의 행 수 == case 개수
    dup_lines = (base_dir / "relational.jsonl").read_text(encoding="utf-8").strip().splitlines()
    unsup_lines = (base_dir / "unsupervised.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(dup_lines) == 1
    assert len(unsup_lines) == 1


def test_save_skips_jsonl_for_empty_family(ctx: _MockCtx, salt: str, batch_id: str) -> None:
    """비어있는 family (intercompany / timeseries) 의 jsonl 은 생성 안 함."""
    case_set = _make_case_set(batch_id=batch_id)
    result = save_phase2_case_set(ctx=ctx, batch_id=batch_id, case_set=case_set, salt=salt)
    assert result.manifest_path is not None
    base_dir = result.manifest_path.parent
    assert not (base_dir / "intercompany.jsonl").exists()
    assert not (base_dir / "timeseries.jsonl").exists()


def test_save_writes_row_ref_map_with_dedup_by_position(
    ctx: _MockCtx, salt: str, batch_id: str
) -> None:
    """같은 row_position 이 여러 case 에 등장해도 row_ref_map 에는 1 entry 만."""
    # 동일 row_position(10) 을 두 duplicate case 가 공유하도록 구성
    dup1 = _make_relational_case(batch_id=batch_id, left_pos=10, right_pos=11)
    dup2 = _make_relational_case(batch_id=batch_id, left_pos=10, right_pos=12, sub_rule="L2-03b")
    case_set = Phase2CaseSet(relational_cases=(dup1, dup2))
    result = save_phase2_case_set(ctx=ctx, batch_id=batch_id, case_set=case_set, salt=salt)
    assert result.manifest_path is not None
    base_dir = result.manifest_path.parent
    rows = [
        json.loads(line)
        for line in (base_dir / "row_ref_map.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    positions = [row["position"] for row in rows]
    assert positions == sorted(set(positions))  # unique + sorted
    assert set(positions) == {10, 11, 12}


def test_save_row_ref_map_pseudonymizes_doc_id_with_salt(
    ctx: _MockCtx, salt: str, batch_id: str
) -> None:
    """row_ref_map 의 doc_id_hash 는 hash_ref_key(salt=...) 결과여야 한다."""
    case_set = _make_case_set(batch_id=batch_id, with_unsupervised=False)
    result = save_phase2_case_set(ctx=ctx, batch_id=batch_id, case_set=case_set, salt=salt)
    assert result.manifest_path is not None
    rows = [
        json.loads(line)
        for line in (result.manifest_path.parent / "row_ref_map.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    # 첫 row 의 document_id = "DOC001". document_id 는 이미 string 이라 hash_ref_key
    # 가 raw string 을 그대로 받는다 (canonicalize 미적용 — store spec).
    expected_hash = hash_ref_key("DOC001", salt=salt)
    doc_hashes = {row["doc_id_hash"] for row in rows}
    assert expected_hash in doc_hashes
    # raw 원문이 포함되지 않음 (invariant #18)
    serialized = (result.manifest_path.parent / "row_ref_map.jsonl").read_text(encoding="utf-8")
    assert "DOC001" not in serialized
    assert "DOC002" not in serialized


def test_save_row_ref_map_pseudonymizes_company_code_with_salt(
    ctx: _MockCtx, salt: str, batch_id: str
) -> None:
    """company_code_hash 도 hash_ref_key 결과 — raw 원문 없음."""
    case_set = _make_case_set(batch_id=batch_id, with_unsupervised=False)
    result = save_phase2_case_set(ctx=ctx, batch_id=batch_id, case_set=case_set, salt=salt)
    assert result.manifest_path is not None
    serialized = (result.manifest_path.parent / "row_ref_map.jsonl").read_text(encoding="utf-8")
    # company_code 도 이미 string 이라 hash_ref_key 가 raw 값을 그대로 받는다.
    expected_hash = hash_ref_key("C01", salt=salt)
    assert expected_hash in serialized
    assert "C01" not in serialized


def test_save_row_ref_map_preserves_line_number_key_unhashed(
    ctx: _MockCtx, salt: str, batch_id: str
) -> None:
    """line_number_key 는 canonical string 그대로 (hash 안 함, invariant #19)."""
    case_set = _make_case_set(batch_id=batch_id, with_unsupervised=False)
    result = save_phase2_case_set(ctx=ctx, batch_id=batch_id, case_set=case_set, salt=salt)
    assert result.manifest_path is not None
    rows = [
        json.loads(line)
        for line in (result.manifest_path.parent / "row_ref_map.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    line_keys = {row["line_number_key"] for row in rows}
    # "0001" → canonicalize → "s:0001" (S1 normalization 미적용)
    assert "s:0001" in line_keys
    assert "s:0002" in line_keys


def test_save_can_omit_row_ref_map_with_manifest_status(
    ctx: _MockCtx, salt: str, batch_id: str
) -> None:
    """schema 1.1 — 명시 요청 시 row_ref_map sidecar 를 생략할 수 있다."""
    case_set = _make_case_set(batch_id=batch_id, with_unsupervised=False)
    result = save_phase2_case_set(
        ctx=ctx,
        batch_id=batch_id,
        case_set=case_set,
        salt=salt,
        write_row_ref_map=False,
    )
    assert result.status == CaseStoreStatus.SAVED
    assert result.manifest_path is not None
    base_dir = result.manifest_path.parent
    payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["row_ref_map_status"] == "omitted"
    assert payload["row_ref_map_hash"] is None
    assert payload["row_count"] == 2
    assert not (base_dir / "row_ref_map.jsonl").exists()


def test_save_omitted_row_ref_map_removes_stale_sidecar(
    ctx: _MockCtx, salt: str, batch_id: str
) -> None:
    """같은 batch 를 optional mode 로 재저장하면 이전 row_ref_map 파일을 남기지 않는다."""
    case_set = _make_case_set(batch_id=batch_id, with_unsupervised=False)
    generated = save_phase2_case_set(ctx=ctx, batch_id=batch_id, case_set=case_set, salt=salt)
    assert generated.manifest_path is not None
    assert (generated.manifest_path.parent / "row_ref_map.jsonl").exists()

    omitted = save_phase2_case_set(
        ctx=ctx,
        batch_id=batch_id,
        case_set=case_set,
        salt=salt,
        write_row_ref_map=False,
    )

    assert omitted.status == CaseStoreStatus.SAVED
    assert omitted.manifest_path is not None
    assert not (omitted.manifest_path.parent / "row_ref_map.jsonl").exists()


def test_save_returns_unsafe_batch_id_status_for_path_traversal(ctx: _MockCtx, salt: str) -> None:
    """`../traversal` 같은 unsafe batch_id 는 status=UNSAFE_BATCH_ID, manifest_path=None."""
    case_set = _make_case_set(batch_id="safe")
    result = save_phase2_case_set(ctx=ctx, batch_id="../traversal", case_set=case_set, salt=salt)
    assert result.status == CaseStoreStatus.UNSAFE_BATCH_ID
    assert result.manifest_path is None


def test_save_returns_salt_missing_for_whitespace_salt(ctx: _MockCtx, batch_id: str) -> None:
    """공백전용 salt → SALT_MISSING (hash 호출 전에 차단, invariant #24)."""
    case_set = _make_case_set(batch_id=batch_id)
    result = save_phase2_case_set(ctx=ctx, batch_id=batch_id, case_set=case_set, salt="   \t\n")
    assert result.status == CaseStoreStatus.SALT_MISSING
    assert result.manifest_path is None


def test_save_returns_ctx_missing_when_db_path_absent(salt: str, batch_id: str) -> None:
    """ctx 가 None 또는 db_path 부재 → CTX_MISSING (invariant #26)."""
    case_set = _make_case_set(batch_id=batch_id)
    result_none = save_phase2_case_set(ctx=None, batch_id=batch_id, case_set=case_set, salt=salt)
    assert result_none.status == CaseStoreStatus.CTX_MISSING
    result_no_db = save_phase2_case_set(
        ctx=_MockCtx(db_path=None), batch_id=batch_id, case_set=case_set, salt=salt
    )
    assert result_no_db.status == CaseStoreStatus.CTX_MISSING


def test_save_manifest_raw_case_hash_matches_compute_raw_case_hash(
    ctx: _MockCtx, salt: str, batch_id: str
) -> None:
    """manifest.raw_case_hash == compute_raw_case_hash(case_set) (invariant #20)."""
    case_set = _make_case_set(batch_id=batch_id)
    result = save_phase2_case_set(ctx=ctx, batch_id=batch_id, case_set=case_set, salt=salt)
    assert result.manifest_path is not None
    payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert payload["raw_case_hash"] == compute_raw_case_hash(case_set)


def test_save_manifest_linked_case_hash_null_when_not_linked(
    ctx: _MockCtx, salt: str, batch_id: str
) -> None:
    """case_set.linked == False → linked_case_hash null (invariant #21)."""
    case_set = _make_case_set(batch_id=batch_id, linked=False)
    result = save_phase2_case_set(ctx=ctx, batch_id=batch_id, case_set=case_set, salt=salt)
    assert result.manifest_path is not None
    payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert payload["linked_case_hash"] is None


def test_save_manifest_linked_case_hash_set_when_linked(
    ctx: _MockCtx, salt: str, batch_id: str
) -> None:
    """case_set.linked == True → linked_case_hash == compute_linked_case_hash (invariant #22)."""
    case_set = _make_case_set(batch_id=batch_id, linked=True)
    result = save_phase2_case_set(ctx=ctx, batch_id=batch_id, case_set=case_set, salt=salt)
    assert result.manifest_path is not None
    payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert payload["linked_case_hash"] is not None
    assert payload["linked_case_hash"] == compute_linked_case_hash(case_set)


# ---------------------------------------------------------------------------
# load 테스트 (8개)
# ---------------------------------------------------------------------------


def test_load_returns_missing_for_nonexistent_batch(ctx: _MockCtx, batch_id: str) -> None:
    """저장된 적 없는 batch_id → status=MISSING."""
    result = load_phase2_case_set(ctx=ctx, batch_id=batch_id)
    assert result.status == CaseStoreStatus.MISSING
    assert result.case_set is None


def test_load_returns_schema_mismatch_for_wrong_schema_version(
    ctx: _MockCtx, salt: str, batch_id: str
) -> None:
    """manifest 의 schema_version 이 다르면 status=SCHEMA_MISMATCH."""
    case_set = _make_case_set(batch_id=batch_id)
    save_result = save_phase2_case_set(ctx=ctx, batch_id=batch_id, case_set=case_set, salt=salt)
    assert save_result.manifest_path is not None
    payload = json.loads(save_result.manifest_path.read_text(encoding="utf-8"))
    payload["schema_version"] = "0.9"
    save_result.manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    result = load_phase2_case_set(ctx=ctx, batch_id=batch_id)
    assert result.status == CaseStoreStatus.SCHEMA_MISMATCH


def test_load_accepts_legacy_schema_1_0_with_generated_row_ref_map(
    ctx: _MockCtx, salt: str, batch_id: str
) -> None:
    """schema 1.0 artifact 는 row_ref_map_status 없이도 generated 로 해석한다."""
    case_set = _make_case_set(batch_id=batch_id)
    save_result = save_phase2_case_set(ctx=ctx, batch_id=batch_id, case_set=case_set, salt=salt)
    assert save_result.manifest_path is not None
    payload = json.loads(save_result.manifest_path.read_text(encoding="utf-8"))
    payload["schema_version"] = "1.0"
    payload.pop("row_ref_map_status", None)
    save_result.manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    result = load_phase2_case_set(ctx=ctx, batch_id=batch_id)

    assert result.status == CaseStoreStatus.LOAD_SUCCESS
    assert result.diagnostics["row_ref_map_status"] == "generated"


def test_load_returns_batch_id_mismatch_for_inconsistent_manifest(
    ctx: _MockCtx, salt: str, batch_id: str
) -> None:
    """manifest.batch_id 가 디렉토리명과 다르면 status=BATCH_ID_MISMATCH."""
    case_set = _make_case_set(batch_id=batch_id)
    save_result = save_phase2_case_set(ctx=ctx, batch_id=batch_id, case_set=case_set, salt=salt)
    assert save_result.manifest_path is not None
    payload = json.loads(save_result.manifest_path.read_text(encoding="utf-8"))
    payload["batch_id"] = "different-batch"
    save_result.manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    result = load_phase2_case_set(ctx=ctx, batch_id=batch_id)
    assert result.status == CaseStoreStatus.BATCH_ID_MISMATCH


def test_load_returns_invalid_payload_for_corrupt_jsonl(
    ctx: _MockCtx, salt: str, batch_id: str
) -> None:
    """family jsonl 의 한 줄이 corrupt → status=INVALID_PAYLOAD."""
    case_set = _make_case_set(batch_id=batch_id)
    save_result = save_phase2_case_set(ctx=ctx, batch_id=batch_id, case_set=case_set, salt=salt)
    assert save_result.manifest_path is not None
    base_dir = save_result.manifest_path.parent
    (base_dir / "relational.jsonl").write_text("not a json line\n", encoding="utf-8")
    result = load_phase2_case_set(ctx=ctx, batch_id=batch_id)
    assert result.status == CaseStoreStatus.INVALID_PAYLOAD


def test_load_roundtrip_preserves_case_count_per_family(
    ctx: _MockCtx, salt: str, batch_id: str
) -> None:
    """save → load 후 family 별 case 개수 보존."""
    case_set = _make_case_set(batch_id=batch_id)
    save_phase2_case_set(ctx=ctx, batch_id=batch_id, case_set=case_set, salt=salt)
    result = load_phase2_case_set(ctx=ctx, batch_id=batch_id)
    assert result.status == CaseStoreStatus.LOAD_SUCCESS
    assert result.case_set is not None
    assert len(result.case_set.relational_cases) == len(case_set.relational_cases)
    assert len(result.case_set.unsupervised_cases) == len(case_set.unsupervised_cases)
    assert len(result.case_set.intercompany_cases) == 0
    assert len(result.case_set.timeseries_cases) == 0


def test_load_roundtrip_preserves_case_ids(ctx: _MockCtx, salt: str, batch_id: str) -> None:
    """save → load 후 phase2_case_id 가 모두 보존."""
    case_set = _make_case_set(batch_id=batch_id)
    save_phase2_case_set(ctx=ctx, batch_id=batch_id, case_set=case_set, salt=salt)
    result = load_phase2_case_set(ctx=ctx, batch_id=batch_id)
    assert result.case_set is not None
    original_ids = {c.phase2_case_id for c in case_set.iter_all_cases_sorted()}
    loaded_ids = {c.phase2_case_id for c in result.case_set.iter_all_cases_sorted()}
    assert original_ids == loaded_ids


def test_load_preserves_phase1_case_refs_when_linked(
    ctx: _MockCtx, salt: str, batch_id: str
) -> None:
    """linked=True 로 저장된 case_set 은 load 시 phase1_case_refs 보존 + linked=True."""
    case_set = _make_case_set(batch_id=batch_id, linked=True)
    save_phase2_case_set(ctx=ctx, batch_id=batch_id, case_set=case_set, salt=salt)
    result = load_phase2_case_set(ctx=ctx, batch_id=batch_id)
    assert result.case_set is not None
    assert result.case_set.linked is True
    # 모든 case 가 비어있지 않은 phase1_case_refs 를 가진다
    for case in result.case_set.iter_all_cases_sorted():
        assert len(case.phase1_case_refs) >= 1


def test_load_row_refs_have_canonical_string_index_label(
    ctx: _MockCtx, salt: str, batch_id: str
) -> None:
    """load 후 row_refs[*].index_label 은 canonical string (invariant #27)."""
    case_set = _make_case_set(batch_id=batch_id)
    save_phase2_case_set(ctx=ctx, batch_id=batch_id, case_set=case_set, salt=salt)
    result = load_phase2_case_set(ctx=ctx, batch_id=batch_id)
    assert result.case_set is not None
    for case in result.case_set.iter_all_cases_sorted():
        for ref in case.row_refs:
            assert isinstance(ref.index_label, str)
            # canonical prefix 중 하나로 시작
            assert ref.index_label.split(":", 1)[0] in {
                "n",
                "b",
                "i",
                "f",
                "d",
                "ts",
                "t",
                "s",
            }


def test_load_accepts_omitted_row_ref_map_when_manifest_declares_omitted(
    ctx: _MockCtx, salt: str, batch_id: str
) -> None:
    """schema 1.1 optional path — omitted manifest 는 sidecar 없이 load 성공."""
    case_set = _make_case_set(batch_id=batch_id)
    save_phase2_case_set(
        ctx=ctx,
        batch_id=batch_id,
        case_set=case_set,
        salt=salt,
        write_row_ref_map=False,
    )

    result = load_phase2_case_set(ctx=ctx, batch_id=batch_id)

    assert result.status == CaseStoreStatus.LOAD_SUCCESS
    assert result.case_set is not None
    assert result.diagnostics["row_ref_map_status"] == "omitted"
    assert result.diagnostics["row_ref_map_hash"] is None


def test_load_rejects_unknown_row_ref_map_status(ctx: _MockCtx, salt: str, batch_id: str) -> None:
    """manifest 의 row_ref_map_status 가 알 수 없는 값이면 payload 오류로 차단."""
    case_set = _make_case_set(batch_id=batch_id)
    save_result = save_phase2_case_set(ctx=ctx, batch_id=batch_id, case_set=case_set, salt=salt)
    assert save_result.manifest_path is not None
    payload = json.loads(save_result.manifest_path.read_text(encoding="utf-8"))
    payload["row_ref_map_status"] = "partial"
    save_result.manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    result = load_phase2_case_set(ctx=ctx, batch_id=batch_id)

    assert result.status == CaseStoreStatus.INVALID_PAYLOAD
    assert result.diagnostics["got"] == "partial"


# ---------------------------------------------------------------------------
# Wave 3 Followup — 무결성 검증 (row_ref_map / case hash 재계산)
# ---------------------------------------------------------------------------


def test_load_returns_row_ref_map_missing_when_jsonl_deleted(
    ctx: _MockCtx, salt: str, batch_id: str
) -> None:
    """row_ref_map.jsonl 부재 → ROW_REF_MAP_MISSING. S4 linker sidecar 가드."""
    case_set = Phase2CaseSet(relational_cases=(_make_relational_case(batch_id=batch_id),))
    save_result = save_phase2_case_set(ctx=ctx, batch_id=batch_id, case_set=case_set, salt=salt)
    assert save_result.status == CaseStoreStatus.SAVED
    # row_ref_map 삭제 시뮬레이션
    assert save_result.manifest_path is not None
    (save_result.manifest_path.parent / "row_ref_map.jsonl").unlink()

    load_result = load_phase2_case_set(ctx=ctx, batch_id=batch_id)
    assert load_result.status == CaseStoreStatus.ROW_REF_MAP_MISSING
    assert load_result.case_set is None


def test_load_returns_row_ref_map_hash_mismatch_when_jsonl_tampered(
    ctx: _MockCtx, salt: str, batch_id: str
) -> None:
    """row_ref_map.jsonl 변조 → ROW_REF_MAP_HASH_MISMATCH. manifest 와 sha256 불일치."""
    case_set = Phase2CaseSet(relational_cases=(_make_relational_case(batch_id=batch_id),))
    save_result = save_phase2_case_set(ctx=ctx, batch_id=batch_id, case_set=case_set, salt=salt)
    assert save_result.status == CaseStoreStatus.SAVED
    # 마지막 줄 변조
    assert save_result.manifest_path is not None
    row_ref_path = save_result.manifest_path.parent / "row_ref_map.jsonl"
    row_ref_path.write_text(
        row_ref_path.read_text(encoding="utf-8") + '{"position":9999,"tampered":true}\n',
        encoding="utf-8",
    )

    load_result = load_phase2_case_set(ctx=ctx, batch_id=batch_id)
    assert load_result.status == CaseStoreStatus.ROW_REF_MAP_HASH_MISMATCH
    assert load_result.diagnostics.get("expected") != load_result.diagnostics.get("got")


def test_load_returns_case_hash_mismatch_when_family_jsonl_tampered(
    ctx: _MockCtx, salt: str, batch_id: str
) -> None:
    """family jsonl 변조 → CASE_HASH_MISMATCH. raw_case_hash 재계산으로 감지."""
    case_set = Phase2CaseSet(relational_cases=(_make_relational_case(batch_id=batch_id),))
    save_result = save_phase2_case_set(ctx=ctx, batch_id=batch_id, case_set=case_set, salt=salt)
    assert save_result.status == CaseStoreStatus.SAVED
    # relational.jsonl 의 case dict 의 family_score 만 변조 (파싱은 가능, hash 만 변경)
    assert save_result.manifest_path is not None
    dup_path = save_result.manifest_path.parent / "relational.jsonl"
    original = dup_path.read_text(encoding="utf-8")
    # JSON 으로 파싱 후 재직렬화 — manifest 의 row_ref_map_hash 영향 없도록
    line = json.loads(original.strip())
    line["family_score"] = 0.01
    dup_path.write_text(
        json.dumps(line, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    # row_ref_map 은 변조 안 함. case 의 row_refs 자체는 그대로이며 family_score
    # 만 바꿔 family jsonl 의 hash 만 흔든다. 본 테스트는 case_hash 검증 통과 확인.
    load_result = load_phase2_case_set(ctx=ctx, batch_id=batch_id)
    # row_ref_map 은 변조 안 했으므로 통과, case hash 단계에서 잡혀야 함.
    assert load_result.status == CaseStoreStatus.CASE_HASH_MISMATCH
    assert load_result.diagnostics.get("kind") == "raw"


def test_load_returns_case_hash_mismatch_for_linked_when_linked_jsonl_tampered(
    ctx: _MockCtx, salt: str, batch_id: str
) -> None:
    """linked case_set 변조 → CASE_HASH_MISMATCH (kind=linked). linked hash 재계산 감지."""
    case = _make_relational_case(batch_id=batch_id)
    case_set = Phase2CaseSet(
        relational_cases=(case.with_phase1_refs(("case-a",)),),
        linked=True,
    )
    save_result = save_phase2_case_set(ctx=ctx, batch_id=batch_id, case_set=case_set, salt=salt)
    assert save_result.status == CaseStoreStatus.SAVED
    # phase1_case_refs 만 변조 — raw 는 phase1_case_refs 제외하므로 raw 통과, linked 에서만 깨짐.
    assert save_result.manifest_path is not None
    dup_path = save_result.manifest_path.parent / "relational.jsonl"
    line = json.loads(dup_path.read_text(encoding="utf-8").strip())
    line["phase1_case_refs"] = ["case-z"]  # 다른 ref
    dup_path.write_text(
        json.dumps(line, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    load_result = load_phase2_case_set(ctx=ctx, batch_id=batch_id)
    assert load_result.status == CaseStoreStatus.CASE_HASH_MISMATCH
    assert load_result.diagnostics.get("kind") == "linked"


# ---------------------------------------------------------------------------
# store key_mode enum — linker capability 와 동기화
# ---------------------------------------------------------------------------


def test_save_accepts_doc_id_key_mode(ctx: _MockCtx, salt: str, batch_id: str) -> None:
    """linker S4.next capability 의 'doc_id' 도 manifest 에 그대로 기록."""
    case_set = Phase2CaseSet(relational_cases=(_make_relational_case(batch_id=batch_id),))
    result = save_phase2_case_set(
        ctx=ctx, batch_id=batch_id, case_set=case_set, salt=salt, key_mode="doc_id"
    )
    assert result.status == CaseStoreStatus.SAVED
    assert result.manifest_path is not None
    payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert payload["key_mode"] == "doc_id"


def test_save_rejects_unknown_key_modes(ctx: _MockCtx, salt: str, batch_id: str) -> None:
    """linker 가 모르는 임의 key_mode 입력은 UNSAFE_KEY_MODE 로 거절.

    S4.next.2 부터 ``doc_line`` / ``label`` / ``company_doc`` 은 허용되므로 enum 외
    값만 거절. silent 통과 시 manifest 가 linker capability 를 잘못 신호.
    """
    case_set = Phase2CaseSet(relational_cases=(_make_relational_case(batch_id=batch_id),))
    for unknown_mode in ("bogus", "row_position", "label2"):
        result = save_phase2_case_set(
            ctx=ctx,
            batch_id=batch_id + f"-{unknown_mode}",
            case_set=case_set,
            salt=salt,
            key_mode=unknown_mode,
        )
        assert result.status == CaseStoreStatus.UNSAFE_KEY_MODE, (
            f"unknown key_mode {unknown_mode!r} should be rejected by store"
        )
        assert result.manifest_path is None
        assert "expected" in result.diagnostics
        assert result.diagnostics["got"] == unknown_mode


def test_save_rejects_auto_key_mode(ctx: _MockCtx, salt: str, batch_id: str) -> None:
    """'auto' 는 linker runtime resolution 결과로만 의미. manifest 에는 resolved 값
    ('position' / 'doc_id' / 'doc_line' / 'company_doc' / 'label') 이 기록되어야
    하므로 'auto' 직접 입력은 거절.
    """
    case_set = Phase2CaseSet(relational_cases=(_make_relational_case(batch_id=batch_id),))
    result = save_phase2_case_set(
        ctx=ctx, batch_id=batch_id, case_set=case_set, salt=salt, key_mode="auto"
    )
    assert result.status == CaseStoreStatus.UNSAFE_KEY_MODE


# ---------------------------------------------------------------------------
# S4.next.2 — store key_mode enum 확장 (doc_line / company_doc / label)
# ---------------------------------------------------------------------------


def test_save_accepts_doc_line_key_mode(ctx: _MockCtx, salt: str, batch_id: str) -> None:
    """S4.next.2 도입 — 'doc_line' 도 manifest 에 그대로 기록 (#49)."""
    case_set = Phase2CaseSet(relational_cases=(_make_relational_case(batch_id=batch_id),))
    result = save_phase2_case_set(
        ctx=ctx, batch_id=batch_id, case_set=case_set, salt=salt, key_mode="doc_line"
    )
    assert result.status == CaseStoreStatus.SAVED
    assert result.manifest_path is not None
    payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert payload["key_mode"] == "doc_line"


def test_save_accepts_company_doc_key_mode(ctx: _MockCtx, salt: str, batch_id: str) -> None:
    """S4.next.2 도입 — 'company_doc' 도 manifest 에 그대로 기록 (#49)."""
    case_set = Phase2CaseSet(relational_cases=(_make_relational_case(batch_id=batch_id),))
    result = save_phase2_case_set(
        ctx=ctx, batch_id=batch_id, case_set=case_set, salt=salt, key_mode="company_doc"
    )
    assert result.status == CaseStoreStatus.SAVED
    assert result.manifest_path is not None
    payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert payload["key_mode"] == "company_doc"


def test_save_accepts_label_key_mode(ctx: _MockCtx, salt: str, batch_id: str) -> None:
    """S4.next.2 도입 — 'label' 도 manifest 에 그대로 기록 (#49)."""
    case_set = Phase2CaseSet(relational_cases=(_make_relational_case(batch_id=batch_id),))
    result = save_phase2_case_set(
        ctx=ctx, batch_id=batch_id, case_set=case_set, salt=salt, key_mode="label"
    )
    assert result.status == CaseStoreStatus.SAVED
    assert result.manifest_path is not None
    payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert payload["key_mode"] == "label"
