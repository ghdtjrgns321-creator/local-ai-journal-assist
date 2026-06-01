"""PHASE2 native case 데이터 모델.

v7-plan S1 단일 출처 기반. dataclass(frozen=True) 로 immutable case 표현.
line_number_key 정규화는 S4 로 유예 — S1 에서는 canonicalize 결과를 그대로 보존한다.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Self

# Why: Phase2RowRef.index_label 의 runtime invariant 검증용 canonical prefix 집합.
# canonicalize_ref_key (src/services/phase2_ref_canonical.py) 의 prefix 와 동기화.
# prefix 추가/변경 시 양쪽 갱신 필수 — 두 위치가 일치하지 않으면 invariant 가 깨진다.
_CANONICAL_PREFIXES: tuple[str, ...] = ("n:", "b:", "i:", "f:", "d:", "ts:", "t:", "s:")


@dataclass(frozen=True)
class Phase2RowRef:
    """전표 row 위치 참조.

    invariant:
      - ``index_label`` 은 항상 canonical 문자열 (canonicalize_ref_key 결과).
        Phase2RowRef 외부에서 raw type (pd.Timestamp, int, tuple 등) 을 직접
        주입하면 hash 일관성이 깨진다. 반드시 ``make_row_ref`` 헬퍼를 사용하거나
        호출자가 직접 canonical 화한 문자열을 전달해야 한다.
      - ``line_number_key`` 도 canonical 문자열 ("0001" 과 1 의 dtype 차이를
        S4 까지 보존하기 위함).

    __post_init__ 가 runtime 에서 ``index_label`` 의 canonical 형식을 강제한다.
    문자열이 아니거나 canonical prefix 로 시작하지 않으면 TypeError / ValueError.
    """

    row_position: int
    index_label: str
    document_id: str | None
    line_number_key: str | None
    company_code: str | None

    def __post_init__(self) -> None:
        # Why: invariant 를 dataclass boundary 에서 강제 — 미래 builder / fixture
        # 가 raw 값 (int, str 그대로) 을 직접 주입하면 hash 가 조용히 깨진다.
        if not isinstance(self.index_label, str):
            raise TypeError(
                "Phase2RowRef.index_label must be canonical str "
                f"(make_row_ref 헬퍼 사용 권장). got {type(self.index_label).__name__}"
            )
        if not self.index_label.startswith(_CANONICAL_PREFIXES):
            raise ValueError(
                "Phase2RowRef.index_label must start with one of "
                f"{_CANONICAL_PREFIXES} (canonicalize_ref_key 결과). "
                f"got: {self.index_label!r}. make_row_ref 헬퍼를 사용하라."
            )


def make_row_ref(
    *,
    row_position: int,
    index_label: Any,
    document_id: str | None,
    raw_line_number: Any,
    company_code: str | None,
) -> Phase2RowRef:
    """raw 값을 canonical 화하여 Phase2RowRef 반환.

    - ``index_label`` 은 ``canonicalize_ref_key`` 통과 (raw → canonical string).
      Phase2RowRef.index_label 의 invariant 보장.
    - ``raw_line_number`` 도 canonicalize, None/NaN/NaT/pd.NA → None 으로 수렴.
    - canonicalize_ref_key 는 함수 내부에서 lazy import — circular dependency 방어.
    """
    from src.services.phase2_ref_canonical import canonicalize_ref_key

    canonical_index_label = canonicalize_ref_key(index_label)
    if raw_line_number is None:
        line_number_key: str | None = None
    else:
        canonical_key = canonicalize_ref_key(raw_line_number)
        # canonicalize 결과가 "n:" 이면 NaN/NaT/pd.NA 류 → None 으로 수렴
        line_number_key = None if canonical_key == "n:" else canonical_key
    return Phase2RowRef(
        row_position=row_position,
        index_label=canonical_index_label,
        document_id=document_id,
        line_number_key=line_number_key,
        company_code=company_code,
    )


@dataclass(frozen=True)
class Phase2CaseBase:
    """5 family 공통 case base.

    phase1_case_refs 는 S3 linker 가 채우는 cross-reference 이며, raw hash
    payload 에서는 제외, linked hash payload 에서는 정렬된 list 로 포함된다.
    """

    phase2_case_id: str
    batch_id: str
    family: str
    unit_type: str
    row_refs: tuple[Phase2RowRef, ...]
    evidence_tier: str
    case_generation_reason: dict[str, Any]
    family_score: float
    family_ecdf: float
    phase1_case_refs: tuple[str, ...] = ()

    def with_phase1_refs(self, refs: tuple[str, ...]) -> Self:
        """phase1_case_refs 를 정렬해 새 case 반환 (immutable replace).

        Self 반환 — DuplicateCase.with_phase1_refs(...) 가 DuplicateCase 로 좁혀져
        Phase2CaseSet 의 family-typed tuple 에 안전하게 들어간다.
        """
        return dataclasses.replace(self, phase1_case_refs=tuple(sorted(refs)))


@dataclass(frozen=True)
class DuplicateCase(Phase2CaseBase):
    """L2-03 중복 전표 — pair 단위 (left/right row_ref)."""

    pair_id: str = ""
    sub_rule: str = ""  # L2-03a / L2-03b / L2-03c / L2-03d
    left_ref: Phase2RowRef | None = None
    right_ref: Phase2RowRef | None = None
    pair_evidence_tier: str = ""


@dataclass(frozen=True)
class IntercompanyCase(Phase2CaseBase):
    """관계사 간 거래 — reciprocal / amount / timing / no_candidate role."""

    ic_role: str = ""
    counterparty_pair: tuple[str, str] | None = None
    amount_a: float | None = None
    amount_b: float | None = None
    amount_symmetry: float | None = None


@dataclass(frozen=True)
class RelationalCase(Phase2CaseBase):
    """관계 그래프 R01~R07 — edge_a, edge_b 두 노드 간 metric."""

    sub_rule: str = ""
    edge_a: str = ""
    edge_b: str = ""
    metric_name: str = ""
    metric_value: float = 0.0


@dataclass(frozen=True)
class UnsupervisedCase(Phase2CaseBase):
    """비지도 이상치 (VAE/IsolationForest) — row 단위 anomaly score."""

    anomaly_score: float = 0.0
    # [{feature_id, contrib, tag, label_ko}, ...] — SHAP/contrib 상위 피처
    top_features: tuple[dict, ...] = ()
    model_id: str = ""
    schema_hash: str = ""


@dataclass(frozen=True)
class TimeseriesCase(Phase2CaseBase):
    """시계열 anomaly (TS01 결산집중 / TS02 시점 컨텍스트) — window 단위."""

    sub_rule: str = ""
    subject: str = ""
    window_start: str = ""
    window_end: str = ""
    daily_count: int = 0
    # Why: expected_count 는 detector 가 실제 baseline (subject 별 trailing mean /
    # period 평균) 을 계산할 때만 양수. detector 가 산출하지 못하면 ``None`` —
    # 감사인 UI / case detail 에서 "—" (미산출) 표시. 0.0 fallback 은 daily_count
    # 30 대비 0 이라는 잘못된 baseline 으로 감사 판단을 호도하므로 사용 금지.
    expected_count: float | None = None
    z_score: float = 0.0
    window_count: int | None = None
    baseline_method: str | None = None
    baseline_window_days: int | None = None
    baseline_observation_count: int | None = None
    robust_z: float | None = None
    period_end_context: bool = False
    period_end_day_offset: int | None = None
    subject_period_end_historical_ratio: float | None = None
    subject_non_period_end_baseline_count: float | None = None
    period_end_expected_count: float | None = None
    period_end_lift: float | None = None
    amount_tail_context: float | None = None
    manual_or_adjustment_context: float | None = None
    after_hours_or_weekend_context: float | None = None
    round_amount_context: float | None = None
    rarity_context_count: int | None = None
    context_evidence_count: int | None = None
    subject_activity_rank: int | None = None
    subject_frequency_context: dict[str, Any] | None = None


# Phase2CaseSet.iter_all_cases_sorted 가 다섯 family 를 한 번에 순회하기 위한 묶음
_FAMILY_FIELD_NAMES: tuple[str, ...] = (
    "duplicate_cases",
    "intercompany_cases",
    "relational_cases",
    "unsupervised_cases",
    "timeseries_cases",
)


@dataclass(frozen=True)
class Phase2CaseSet:
    """5 family case 묶음. linked=False 가 raw, linked=True 가 phase1_case_refs 부착 상태."""

    duplicate_cases: tuple[DuplicateCase, ...] = ()
    intercompany_cases: tuple[IntercompanyCase, ...] = ()
    relational_cases: tuple[RelationalCase, ...] = ()
    unsupervised_cases: tuple[UnsupervisedCase, ...] = ()
    timeseries_cases: tuple[TimeseriesCase, ...] = ()
    linked: bool = False

    def iter_all_cases_sorted(self) -> Iterator[Phase2CaseBase]:
        """모든 family case 를 phase2_case_id 사전순으로 yield."""
        all_cases: list[Phase2CaseBase] = []
        for family_field in _FAMILY_FIELD_NAMES:
            all_cases.extend(getattr(self, family_field))
        # phase2_case_id 사전순 — hash payload 결정성 보장
        yield from sorted(all_cases, key=lambda c: c.phase2_case_id)

    def with_phase1_refs(self, refs_by_case_id: dict[str, tuple[str, ...]]) -> Phase2CaseSet:
        """각 case 에 phase1_case_refs 를 부착하고 linked=True 인 새 set 반환.

        refs_by_case_id 에 phase2_case_id 가 없는 case 는 기존 refs 유지.
        """
        updated: dict[str, tuple] = {}
        for family_field in _FAMILY_FIELD_NAMES:
            cases = getattr(self, family_field)
            new_cases = tuple(
                case.with_phase1_refs(refs_by_case_id[case.phase2_case_id])
                if case.phase2_case_id in refs_by_case_id
                else case
                for case in cases
            )
            updated[family_field] = new_cases
        return Phase2CaseSet(
            duplicate_cases=updated["duplicate_cases"],
            intercompany_cases=updated["intercompany_cases"],
            relational_cases=updated["relational_cases"],
            unsupervised_cases=updated["unsupervised_cases"],
            timeseries_cases=updated["timeseries_cases"],
            linked=True,
        )


__all__ = [
    "DuplicateCase",
    "IntercompanyCase",
    "Phase2CaseBase",
    "Phase2CaseSet",
    "Phase2RowRef",
    "RelationalCase",
    "TimeseriesCase",
    "UnsupervisedCase",
    "make_row_ref",
]
