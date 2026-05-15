# Rule Detail Metadata v1 Completion

Updated: 2026-05-08
Status: Completed implementation record

This document records the completed Rule Detail Metadata v1 implementation. It is a completion note only; it does not change the locked v1 contract in `docs/RULE_DETAIL_METADATA_V1_LOCK.md`.

## 1. 구현 범위

Rule Detail Metadata v1 구현은 다음 범위로 완료되었다.

- Metadata registry/accessor
  - `RuleDetailMetadata`, `DisplayCopy`, `ColumnSources` 최소 v1 schema를 정의했다.
  - `RuleStatus`, `PresenterSurface`, `ScoringRole` enum 계약을 고정했다.
  - `RULE_DETAIL_METADATA_REGISTRY`에 L1~L4 canonical rule, alias, internal reason code, macro, sidecar, graph sidecar metadata를 등록했다.
  - `canonicalize_rule_id()`, `get_rule_detail_metadata()`, `get_canonical_transaction_rule_ids()`, `include_in_l1_l4_transaction_count()`, `can_render_row_violation_detail()`, `can_generate_standalone_violation_copy()` accessor를 제공했다.
  - registry validation에서 canonical count, alias/internal reason exclusion, surface/row-detail gating, standalone-copy 금지, required ledger column schema 검증을 수행한다.

- Export row-detail gating
  - `src/export/phase1_case_view.py`에서 rule document/detail export 진입점에 metadata 기반 canonicalization과 row-detail gating을 적용했다.
  - `presenter_surface=transaction_detail`이고 `allow_row_violation_detail=True`인 rule만 row violation detail을 생성한다.
  - `L4-02`, `Benford`, `D01`, `D02`, `GR01`, `GR03` 등 non-transaction surface는 row detail export에서 제외한다.
  - `L2-03a~d`는 export 요청 시 `L2-03`으로 canonicalize하여 별도 detail heading/count를 만들지 않는다.

- Dashboard Phase1 topic rule display 적용
  - `dashboard/tab_phase1.py`에서 Phase1 topic rule 표시와 rule count/selector 경로에 metadata count/canonicalization 정책을 반영했다.
  - topic rule 목록은 canonical L1~L4 transaction count 정책을 기준으로 구성한다.
  - `Benford` alias와 `L2-03a~d` internal reason code는 별도 표시 항목으로 분리하지 않는다.
  - `D01/D02` macro rule은 topic rule selector의 canonical transaction rule 표시에서 제외한다.

- `phase1_case_builder` seed/canonicalization 적용
  - `src/detection/phase1_case_builder.py`에서 raw hit 처리, topic seed, ranking/case selection에 metadata 기반 canonical ID와 surface policy를 적용했다.
  - `standalone_rankable`, `allow_topic_seed`, `scoring_role`, `presenter_surface` 정책으로 context/booster/combo-only rule이 단독 violation case로 표시되지 않도록 했다.
  - `IC01~IC03`는 intercompany sidecar/topic seed로 허용하되 L1~L4 transaction count/detail에는 포함하지 않는다.
  - `L4-02`, `D01`, `D02`는 account/process macro 성격으로 처리한다.
  - `GR01/GR03`는 graph sidecar 성격으로 처리한다.

- Ruff 정리
  - `dashboard/tab_phase1.py` 및 touched files에 대해 ruff 통과 상태를 확인한 결과를 기록한다.

## 2. 최종 정책 요약

- Canonical L1~L4 transaction/detail rule count는 32이다.
- Legacy 33 rule 표현은 `32 canonical + Benford display alias`로 해석한다.
- `Benford`는 `L4-02`의 display alias이며 별도 canonical count를 만들지 않는다.
- `L2-03a`, `L2-03b`, `L2-03c`, `L2-03d`는 모두 `L2-03` internal reason code로 canonicalize한다.
- `L4-02`는 canonical count 32에 포함하지만 row violation detail에서는 제외한다.
- `D01/D02`는 account/process macro rule이며 L1~L4 transaction count/detail에 포함하지 않는다.
- `IC01~IC03`는 sidecar/topic seed가 가능하지만 transaction count/detail에는 포함하지 않는다.
- `GR01/GR03`는 graph sidecar로 처리한다.
- Context/booster/combo-only rule은 단독 위반 표시를 금지한다.

## 3. 변경 파일 목록

Implementation files:

- `src/detection/rule_detail_metadata.py`
- `src/export/phase1_case_view.py`
- `dashboard/tab_phase1.py`
- `src/detection/phase1_case_builder.py`

Related tests:

- `tests/modules/test_detection/test_rule_detail_metadata.py`
- `tests/modules/test_export/test_phase1_case_view.py`
- `tests/modules/test_dashboard/test_tab_phase1.py`
- `tests/modules/test_detection/test_phase1_case_builder.py`

## 4. 검증 결과

아래 결과는 완료 시점에 제공된 검증 결과를 기록한 것이다. 본 문서 작성 중 테스트를 새로 실행하지 않았다.

- `tests/modules/test_detection/test_rule_detail_metadata.py`: 9 passed
- `tests/modules/test_export/test_phase1_case_view.py`: 24 passed
- `tests/modules/test_dashboard/test_tab_phase1.py`: 6 passed
- `tests/modules/test_detection/test_phase1_case_builder.py`: 61 passed
- Targeted integration: 100 passed
- Dashboard suite: 150 passed
- Export suite: 106 passed
- Detection suite: 1016 passed, 2 warnings
- `ruff dashboard/tab_phase1.py`: passed
- `ruff` touched files: passed

## 5. 남은 fallback/후속 정리

아래 항목은 v1 완료 이후 정리 가능한 fallback 또는 후속 작업으로 남긴다.

- `phase1_case_builder` legacy maps
- Export `_MACRO_RULES` / `_REVIEW_CONTEXT_RULES` fallback
- Dashboard legacy rule name/detail maps
- Context D nested schema는 v1 이후로 보류

## 6. 금지 파일 미수정 확인

이번 완료 기록 작성 범위에서는 아래 금지 파일을 수정하지 않았다.

- `dashboard/tab_overview.py`
- `dashboard/tab_summary.py`
- `dashboard/styles.py`

