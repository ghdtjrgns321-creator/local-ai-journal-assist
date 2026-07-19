# DataSynth Dataset Variants (2026-05-17판 — 복원 보존본)

> **복원 경위 (2026-07-15)**: 원본은 `data/journal/primary/DATASET_VARIANTS.md`였다. 해당 경로는
> `.gitignore`의 `data/*` 규칙으로 git에 추적된 적이 없어 이력이 존재하지 않는다. 2026-07-15 이 파일을
> SoT 포인터로 축소하는 과정에서 원문을 백업 없이 덮어썼고, 이를 발견해 작업 세션의 읽기 출력에서
> 전문을 복원해 추적되는 위치에 보존한다.
>
> **복원본 신뢰도**: 원본 파일 크기 15,767 bytes / 289줄. 아래 본문은 덮어쓰기 전 읽어둔 전문이며
> 별도 대조 원본이 존재하지 않아 byte 단위 동일성은 검증 불가하다. 내용 누락 가능성이 0이라고
> 단언하지 않는다.
>
> **이 문서의 현재 가치**: 아래가 설명하는 `datasynth_contract_v2`, `datasynth_manipulation_v2/v3/v7`,
> `datasynth_contract_v3_candidate`는 2026-07-15 기준 `data/journal/primary/`에도
> `data/journal/archive/`에도 실물이 없다. 따라서 본 문서는 운영 기준이 아니라 계보 서술 기록이다.
> 현행 기준은 `docs/datasynth/current-lineage-and-gaps.md`를 본다.

---

이 문서는 `data/journal/primary/` 아래의 DataSynth 계열 데이터셋 차이를 정리한다.

2026-05-17 기준 active primary 데이터셋은 contract v2와 manipulation v7 fixed3를 기준으로 한다.

- `datasynth_contract_v2`
- `datasynth_manipulation_v2`
- `datasynth_manipulation_v7_candidate_fixed3`

이전 비교용 데이터셋(`datasynth`, `datasynth_contract`, `datasynth_manipulation`, `datasynth_semantic_v1`)은 `data/journal/archive/primary_legacy_20260514/`로 이동했다.

각 v2 폴더 내부에서도 active validation에 쓰지 않는 aggregate JSON 복제본과 generator auxiliary export는 `_archive_unused_20260514/`로 이동했다. 원장 연도별 split과 label 연도별 split은 프로젝트에서 사용하는 active 표면이므로 유지한다. 현재 사용 파일 목록은 각 폴더의 `README_ACTIVE_FILES.md`를 기준으로 한다.

## 요약

| dataset                                      | 목적                                         | journal 정책                                                                           | labels 정책                                         | 주요 사용처                                                 |
| -------------------------------------------- | -------------------------------------------- | -------------------------------------------------------------------------------------- | --------------------------------------------------- | ----------------------------------------------------------- |
| `datasynth_contract_v2`                      | semantic-clean 룰 계약 후보                  | semantic generator v2 journal, 직접 라벨 컬럼 제거                                     | v2 rule truth, sidecar taxonomy, manifest 포함      | 룰 계약 A축 전수 검증                                       |
| `datasynth_contract_v3_candidate`            | contract v2 accounting-substance repair 후보 | v2 journal/truth/sidecar 복사 후 P2P KR 대변 AP 의미 보정                              | v2 rule truth, sidecar taxonomy, manifest 포함      | v2 대체 전 비교 후보                                        |
| `datasynth_manipulation_v2`                  | semantic-clean 조작 truth 후보               | `datasynth_contract_v2`와 같은 journal schema/background, manipulation provenance 포함 | manipulation truth만 포함. contract rule truth 제외 | 조작 시나리오 평가, Phase2/3 synthetic 실험 후보            |
| `datasynth_manipulation_v3`                  | Rust 생성 manipulation v3 이전 최종본        | v2와 같은 background 위에 회계기간 정합성과 fictitious revenue 회계 실체 보강          | manipulation truth만 포함. contract rule truth 제외 | v7 fixed3 승격 후 회귀 비교 reference                       |
| `datasynth_manipulation_v7_candidate_fixed3` | Rust 생성 manipulation v7 active 최종본      | v5 fixed9 보존 + v7 targeted repair + period-end 발생액 line text 보존                 | manipulation truth만 포함. contract rule truth 제외 | active manipulation synthetic 기준, Phase2/3 synthetic 실험 |
| archived legacy datasets                     | 과거 비교용                                  | 변경 전 정책                                                                           | 변경 전 labels                                      | 필요 시 archive에서 비교                                    |

아래 legacy 섹션의 경로는 과거 active 위치를 설명한 기록이다. 현재 파일 위치는 모두 `data/journal/archive/primary_legacy_20260514/` 아래다.

## `datasynth`

원본 production baseline 데이터셋이다.

- 경로: `data/journal/primary/datasynth/`
- source freeze: `v126`
- rows: `1,109,435`
- documents: `319,193`
- columns: `52`
- years: `2022`, `2023`, `2024`
- 직접 라벨 컬럼 포함:
  - `is_fraud`
  - `fraud_type`
  - `is_anomaly`
  - `anomaly_type`

`datasynth`는 원본 기준점으로 유지하는 데이터셋이다. 계약 검증이나 ML/DL 평가에 직접 쓰기보다는, 목적별 파생본을 만들기 위한 source dataset으로 본다.

## `datasynth_contract`

룰 계약, 회귀 테스트, sidecar/context 검증을 위한 파생 데이터셋이다.

- 경로: `data/journal/primary/datasynth_contract/`
- source dataset: `data/journal/primary/datasynth/`
- source freeze: `v126`
- rows: `1,109,435`
- documents: `319,193`
- columns: `49`
- label files: `1,442`
- journal 문서 제거: 없음
- journal에서 제거한 직접 라벨 컬럼:
  - `is_fraud`
  - `fraud_type`
  - `is_anomaly`
  - `anomaly_type`
- 포함 labels:
  - contract truth
  - sidecar context
  - manifest log
- 제외 labels:
  - manipulation truth

`datasynth_contract`는 탐지 룰이 기대한 계약대로 동작하는지 확인하기 위한 데이터셋이다. fraud-label ML 학습용 truth로 사용하면 안 된다.

## `datasynth_manipulation`

실제 조작 또는 주입 이슈 truth만 남긴 평가/실험용 파생 데이터셋이다.

- 경로: `data/journal/primary/datasynth_manipulation/`
- source dataset: `data/journal/primary/datasynth/`
- source freeze: `v126`
- rows: `1,095,158`
- documents: `317,505`
- columns: `49`
- label files: `38`
- 제거한 contract-only fixture documents: `1,688`
- 제거한 contract buckets:
  - `control_gap`
  - `hard_error`
  - `review_required`
  - `system_policy_exception`
- journal에서 제거한 직접 라벨 컬럼:
  - `is_fraud`
  - `fraud_type`
  - `is_anomaly`
  - `anomaly_type`
- 포함 labels:
  - `anomaly_labels`
  - `manipulated_entry_truth`
  - `revenue_manipulation_*`
- 제외 labels:
  - contract-only rule truth

`datasynth_manipulation`은 조작 시나리오 평가와 synthetic ML/DL 실험에 사용하는 데이터셋이다. contract-only rule truth는 제외되어 있다.

## `datasynth_contract_v2`

semantic-clean generator 재작업 이후의 룰 계약 후보 데이터셋이다.

- 경로: `data/journal/primary/datasynth_contract_v2/`
- source policy: semantic-clean DataSynth v2
- rows: `1,077,767`
- documents: `317,997`
- columns: `53`
- years: `2022`, `2023`, `2024`
- 포함 labels:
  - `rule_truth_*`
  - `contract_rule_truth_taxonomy*`
  - `contract_sidecar_taxonomy*`
  - contract sidecar context
- 제외 labels:
  - manipulation-only truth

`datasynth_contract_v2`는 A축 룰 계약 전수 검증용 후보이다. 2026-05-14 기준 strict A축 대조에서 34개 룰 과탐/미탐 0건을 확인했다.

## `datasynth_contract_v3_candidate`

`datasynth_contract_v2`를 바로 덮지 않고, 회계 실체 repair만 적용한 비교 후보이다.

- 경로: `data/journal/primary/datasynth_contract_v3_candidate/`
- source dataset: `data/journal/primary/datasynth_contract_v2/`
- generator command:
  - `cargo run -p datasynth-cli --bin datasynth-data -- generate --profile contract-v3 --contract-source data/journal/primary/datasynth_contract_v2 --output data/journal/primary/datasynth_contract_v3_candidate`
- 적용 repair:
  - P2P `KR` vendor invoice 대변 라인은 AP 계정(`2000`)과 `매입채무 인식` line text로 고정.
  - 구매/입고/비용성 line text는 대변이 아니라 차변 라인 의미로만 남기기 위한 좁은 repair.
- 검증:
  - P2P `KR` 대변 63,347 rows 전부 `gl_account=2000`.
  - P2P `KR` 대변 구매/입고/비용성 line text 0 rows.
  - `check_datasynth_required_truth.py data/journal/primary/datasynth_contract_v3_candidate` 통과, failures 0.
- 상태: candidate. v2 active contract를 대체하려면 Phase1 strict A축 재실행과 detection result 비교가 필요하다.

2026-05-14 추가 보강:

- `document_flows` sidecar에 journal reference가 가리키는 `PO/GR/VI/PAY/SO/CI/DLV-*` 문서 ID를 materialize했다.
- employee master와 승인 route를 정렬해 Phase1 독립증빙 기준 `document_flow_orphan_rows=0`, `approval_matrix_gap_rows=184`로 축소했다.
- 남은 approval gap은 `SkippedApproval`, `SelfApproval`, `ExceededApprovalLimit`, `JustBelowThreshold` 계약 검증용 소량 fixture이다.
- 보강 스크립트: `tools/scripts/repair_contract_v2_master_flow_coverage.py`
- 보강 리포트: `data/journal/primary/datasynth_contract_v2/CONTRACT_V2_MASTER_FLOW_COVERAGE_REPAIR_REPORT.json`
- required truth gate: `tools/scripts/check_datasynth_required_truth.py data/journal/primary/datasynth_contract_v2` 통과
- `tools/scripts/refresh_contract_sidecar_truth.py`는 stale Phase1 cache를 기본 사용하지 않으며, `--phase1-cache`를 명시한 경우에만 detector hit 기반으로 `rule_truth_*`를 정렬한다.

## `datasynth_manipulation_v2`

`datasynth_contract_v2`와 같은 semantic-clean journal/background 위에 manipulation-only truth를 올린 후보 데이터셋이다.

- 경로: `data/journal/primary/datasynth_manipulation_v2/`
- source dataset: `data/journal/primary/datasynth_contract_v2/`
- rows: `1,077,767`
- documents: `317,997`
- columns: `53`
- manipulation truth documents: `420`
- years: `2022`, `2023`, `2024`
- 포함 labels:
  - `anomaly_labels`
  - `manipulated_entry_truth`
  - `manipulated_entry_scenario_summary`
- 제외 labels:
  - `rule_truth*`
  - contract sidecar/taxonomy files
- 생성 스크립트:
  - `tools/scripts/materialize_datasynth_manipulation_v2.py`
- 검증 스크립트:
  - `tools/scripts/check_datasynth_manipulation_truth.py`
  - `tools/scripts/evaluate_manipulation_v2_phase1_surface.py`

`datasynth_manipulation_v2`의 manipulation truth는 Phase1 룰 정답지가 아니라 조작 시나리오 truth이다. Phase1에서 truth 문서가 일부 Normal로 남을 수 있으며, 이는 룰 계약 실패가 아니라 downstream ranking/ML 실험 표면으로 해석한다. 2026-05-15 기준 기본 manipulation 평가는 v3를 우선 사용한다.

2026-05-14 기준 `datasynth_contract_v2` master/document-flow 보강 후 다시 materialize했다. contract rule truth와 sidecar files는 포함하지 않고, manipulation-only truth 420건과 provenance 필드만 유지한다.

추가로 contract-only approval fixture가 manipulation background에 unlabeled anomaly로 남지 않도록 materialize 단계에서 non-truth approval fixture를 정상 승인 route로 중화한다. 2026-05-14 검증 기준 approval/limit issue union은 142개 문서이며 모두 manipulation truth 문서다.

이후 B1/B3 회귀 분석을 반영해 manipulation truth 문서에 회계 실체 mutation을 추가했다.

- circular truth 34개 문서 전부에 IC GL prefix(`1150`, `2050` 등)를 부여
- fictitious truth 168개 문서 전부에 DR 11xx / CR 4xxx revenue pattern 부여
- embezzlement truth 76개 문서 전부에 DR `1200/1250` / CR `1000` cash leakage pattern 부여
- 일부 embezzlement 문서는 duplicate card reference 및 approval-limit near-threshold surface 부여
- manifest에 operational noise floor 지표를 명시

2026-05-14 full Phase1 및 case builder 기준 확인:

- detector warning: 0
- manipulation truth 420건 전부 `score > 0` 및 rule/review 표면에 진입
- top-500 case truth capture: 305 / 420
- `fictitious_entry` expected topic 진입: 144 / 168
- `embezzlement_concealment` expected topic 진입: 76 / 76
- `circular_related_party_transaction` L3-03 hit: 34 / 34
- `circular_related_party_transaction` expected topic 진입: 34 / 34

## `datasynth_manipulation_v3`

Rust 단일 명령으로 생성한 v3 최종본이다.

- 경로: `data/journal/primary/datasynth_manipulation_v3/`
- source dataset: `data/journal/primary/datasynth_contract_v2/`
- rows: `1,077,767`
- documents: `317,997`
- columns: `53`
- manipulation truth documents: `420`
- 생성 명령:
  - `cargo run -p datasynth-cli --bin datasynth-data -- generate --profile manipulation-v3 --output data/journal/primary/datasynth_manipulation_v3 --manipulation-source data/journal/primary/datasynth_contract_v2`
- raw-data guard:
  - `tools/scripts/audit_manipulation_v3_mutation_guards.py`
- T8 approval gap 원인분리:
  - `tools/scripts/analyze_contract_v2_master_flow_gap.py`

fitting 방지를 위해 v3에서는 다음을 고정했다.

- `unusual_timing_manipulation`은 이미 야간/주말/manual posting 실체가 있으므로 DataSynth에서 더 강화하지 않았다.
- `circular_related_party_transaction`은 이미 IC cycle 실체가 있으므로 high-cash 동시 hit 유도 mutation을 추가하지 않았다.
- `fictitious_entry`만 회계 실체 보강 대상으로 삼았다. 금액은 detector threshold가 아니라 회사별 매출계정 상위 분위수(`p99.95 * 1.5`) 기준으로 정하고, DR 11xx / CR 4xxx 구조와 batch posting cluster를 생성했다.

2026-05-14 검증:

- manipulation truth gate: pass, failures 0
- Guard 1 회계 실체: pass
- Guard 2 정상 배경 fitting 차단: pass
- Guard 3 다른 시나리오 topic 회귀: 새 baseline으로 재설정
- Phase1 measure-only:
  - score/rule/review hit docs: 420 / 420
  - Top500 truth capture: 272 / 420
  - `fictitious_entry` expected topic 진입: 168 / 168
  - `circular_related_party_transaction` expected topic 진입: 22 / 34
  - `embezzlement_concealment` expected topic 진입: 42 / 76
  - `unusual_timing_manipulation` expected topic 진입: 11 / 21

2026-05-15 승격:

- `datasynth_manipulation_v3_rust_candidate_fixed`를 `datasynth_manipulation_v3`로 승격했다.
- 기존 Python materialize 후보는 `data/journal/archive/primary_legacy_20260515/datasynth_manipulation_v3_python_candidate/`에 보존했다.
- 실패/중간 Rust 후보는 같은 archive 아래로 이동했다.
- 승격 판단은 기존 Python 후보의 stale `fiscal_period` 재현보다 회계기간 정합성을 우선한다는 결정에 따른다.

## 선택 기준

룰 검증, 회귀 테스트, sidecar/context 검증이 목적이면 `datasynth_contract` 또는 신규 후보인 `datasynth_contract_v2`를 사용한다.

2026-05-15 당시 조작/이상 truth 기반 평가, synthetic ML/DL 실험, manipulation scenario 검증의 기본 후보는 `datasynth_manipulation_v3`였다. 2026-05-17 이후 기본 후보는 아래 v7 fixed3 승격 내용을 따른다.

2026-05-17 승격:

- `datasynth_manipulation_v7_candidate_fixed3`를 active manipulation 기준으로 승격했다.
- v7 fixed3는 manipulation truth 620건을 유지하고, v4에서 추가한 hold-out 2개 시나리오(`suspense_account_abuse`, `expense_capitalization`)를 포함한다.
- 최종 재생성 기준 검증:
  - manipulation truth check: pass, truth docs 620, label docs 620, missing provenance 0.
  - V7 quality verification: GO, hard failures 0, soft failures 0.
  - `period_end_adjustment_manipulation` expense line 92개 전부 발생액/환입 의미 line_text 포함.
- `datasynth_manipulation_v3`는 회귀 비교 reference로 유지한다.
- 조작/이상 truth 기반 평가, synthetic ML/DL 실험, manipulation scenario 검증이 목적이면 `datasynth_manipulation_v7_candidate_fixed3`를 기본 후보로 사용한다. v2/v3는 비교 기준으로 유지한다.

원본 freeze 기준점 확인이나 파생 데이터셋 생성 근거 확인이 목적이면 `datasynth`를 사용한다.

## 주의

`datasynth_contract`와 `datasynth_manipulation`은 모두 journal에서 직접 라벨 누수 컬럼을 제거한 상태다. 따라서 두 파생본의 `journal_entries.csv` 컬럼 수는 모두 `49`개다.

v2 계열은 semantic/provenance 컬럼이 추가되어 `journal_entries.csv` 컬럼 수가 `53`개다. 직접 라벨 누수 컬럼은 없고, manipulation truth 문서에는 mutation provenance가 채워진다.

두 파생본의 핵심 차이는 journal schema가 아니라 다음 두 가지다.

1. 어떤 label truth를 포함하는가
2. contract-only fixture 문서를 제거했는가

---

## 2026-05-16 — manipulation v4 candidate

- Status: candidate only, not active.
- Candidate path: `data/journal/primary/datasynth_manipulation_v4_candidate/`
- Active manipulation dataset is now `data/journal/primary/datasynth_manipulation_v7_candidate_fixed3/`; v4 remains a historical candidate.
- Active contract dataset remains: `data/journal/primary/datasynth_contract_v2/`
- Truth docs: 620 = v3 six scenarios 420 + hold-out scenarios 200.
- New hold-out scenarios: `suspense_account_abuse` 100 docs, `expense_capitalization` 100 docs.
- Promotion rule: do not promote solely because Phase2 metrics improve. Promote only after accepting the new truth taxonomy and the Phase2 supervised-feature measurement profile.
- Main artifacts:
  - `artifacts/manipulation_v4_candidate_guard.json`
  - `artifacts/manipulation_v4_migration_report.md`
  - `artifacts/S4_scenario_detectability_v4_candidate_data.json`
  - `artifacts/S5_circular_learning_v4_candidate_overlap.json`
  - `artifacts/S8_stacking_oof_v4_candidate_ablation.json`
