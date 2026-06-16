"""Phase 1 evidence pointer schema models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RawRuleHitRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    severity: int
    document_id: str
    row_index: int  # legacy (row position)
    record_id: str | None = None
    score: float = 0.0
    signal_strength: float = 0.0
    normalized_score: float = 0.0
    evidence_strength: str = ""
    scoring_role: str = "primary"
    display_label: str = ""
    signal_status: str = "confirmed"
    detail: str | None = None
    evidence_type: str

    # ── S6.next Phase 1 (옵션 C) — engagement-scoped stable identifier ──
    # Why: PHASE2 native case 의 row_ref_map 과 동일 salt 로 hash 된 식별자를
    # PHASE1 결과 자체에 직접 포함시키기 위함. S4.next.2 linker 가 row_ref_map
    # sidecar 조회 없이 두 source 의 hash 비교만으로 cross-batch reload-safe
    # 매칭을 수행할 수 있다. 빌더가 engagement_salt 를 받지 못하면 default
    # (빈 문자열 / None) — 기존 caller backward compat (invariant #71).
    canonical_label_hash: str = ""
    doc_id_hash: str = ""
    line_number_key: str | None = None
    # ── S6.next Phase 2 — Phase 1 누락 보완 (invariant #74) ──
    # Why: company_doc key_mode (multi-company disambiguation) 가 row_ref_map
    # sidecar 없이도 hit 측 hash 만으로 동작하도록 추가. salt 미수령 시 빈 값
    # 유지 — 기존 caller backward compat.
    company_code_hash: str = ""


class CaseDocumentRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    posting_date: str | None = None
    created_by: str | None = None
    business_process: str | None = None
    gl_account: str | None = None
    counterparty: str | None = None
    amount: float = 0.0
    matched_rules: list[str] = Field(default_factory=list)
    evidence_tags: list[str] = Field(default_factory=list)
