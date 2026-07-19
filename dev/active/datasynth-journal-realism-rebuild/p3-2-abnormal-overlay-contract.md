# P3-2 Abnormal Overlay Contract

## 목적

정상 baseline `datasynth_semantic_v1_normal_20260607_v29` 위에 PHASE1 39개 룰의 표준 위반과 evasion 케이스를 overlay/mutation으로 주입한다. 이 산출물은 PHASE1 catch/miss 성능 측정용이 아니라, P2-4 이후 룰별 측정이 가능한 부정 구조와 truth/provenance를 갖춘 입력 데이터셋이다.

정상 v29는 수정하지 않는다. P3-2는 별도 출력 디렉터리에 정상 행을 복사하고 변형 행/흐름을 추가한다.

## 완료 전 선언 체크리스트

| 항목 | 상태 | 완료 기준 |
| --- | --- | --- |
| 전 룰 runnable 보강 | DONE(v10) | v29에서 입력 부재로 skip된 룰의 필수 입력 컬럼이 P3-2 출력에 존재하고, 값이 구조적으로 의미 있게 채워진다. |
| 39룰 표준 위반 주입 | DONE(v10) | 아래 39개 룰별 표준 위반 건수 목록이 truth와 acceptance에 기록된다. |
| suppress/drop evasion 전수 주입 | DONE(v10) | `dev/active/phase1-evasion-injection-spec.md`의 39개 evasion 행이 모두 자연 단위로 주입된다. |
| truth/provenance/자연 단위 | DONE(v10) | 각 부정은 `document_id` XOR `flow_id+member_docs` 중 하나의 자연 단위만 갖고, base->mutated provenance를 sidecar에 기록한다. |
| 39/39 구조 발화 확인 | PENDING(P2-4 이후) | PHASE1 성능 측정이 아니라 룰별 smoke/probe로 `입력 갖춤 + 표준 위반 구조 탐지가능`을 증명한다. |
| 구조 탐지가능/오라클 0 | DONE(local scan) | journal/master 단일 컬럼 값으로 truth가 분리되지 않고, 탐지는 sidecar가 아니라 분개/흐름 구조로 가능하다. |
| anti-fitting | DONE(v10 설계) | detector threshold에 맞춘 튜닝이 아니라 실제 부정 메커니즘을 구현했음을 rule별 reason으로 남긴다. |
| 정상 v29 무손상 | PARTIAL | v29 원본은 불변이다. 출력 데이터의 정상 subset realism gate 29개 재실행은 별도 검증으로 남긴다. |
| 2+ 케이스 ripple 검증 | PENDING | 표준 위반과 evasion 각각 최소 2개 케이스를 end-to-end로 추적해 라벨/단위/정상 무손상을 확인한다. |

## 공통 산출 스키마

- `journal_entries*.csv`: detector 입력용 전표. truth/provenance 평문 컬럼을 넣지 않는다.
- `labels/p3_2_rule_truth.csv`: 자연 단위 truth. 필수 컬럼은 `rule_id`, `case_kind`, `natural_unit_type`, `natural_unit_id`, `member_document_ids`, `base_document_ids`, `mutation_family`, `mutation_reason`, `expected_surface`, `evasion_vector`, `structural_probe_expected`.
- `labels/p3_2_mutation_provenance.csv`: base row/document에서 어떤 필드를 왜 바꿨는지 기록한다. journal에는 직접 노출하지 않는다.
- `labels/p3_2_rule_coverage.json`: rule별 `input_ready`, `standard_injected`, `evasion_injected`, `structural_probe_ready`, `oracle_scan_pass`, `normal_regression_pass`.
- `reports/p3_2_overlay_acceptance.json|md`: 수치 리포트.

검증 카탈로그는 `dev/active/datasynth-journal-realism-rebuild/phase1-abnormal-overlay-test-catalog.md`를 따른다.

## 주입 볼륨 원칙

첫 빌드는 룰별 표준 위반 2개 자연 단위, evasion 2개 자연 단위를 기본 목표로 한다. macro/graph/IC/duplicate/reversal 룰은 단일 document가 아니라 흐름 또는 모집단 단위로 주입한다. 룰별 최소 목표는 아래 표에 따른다. 이후 볼륨 확대는 detector 성능에 맞추지 않고 실제 회사 발생 빈도와 정상 배경 밀도에 맞춰 별도 결정한다.

## Rule Coverage Matrix

| rule_id | 자연 단위 | 표준 위반 최소 | evasion 최소 | 필수 입력/구조 | 표준 위반 메커니즘 | evasion 메커니즘 |
| --- | --- | ---: | ---: | --- | --- | --- |
| L1-01 | document | 2 | 2 | debit/credit amount | material imbalance document | 균형은 맞지만 허위 O2C/R2R 구조 |
| L1-02 | document | 2 | 2 | required fields | 필수 필드 결측 | 필수 필드는 정상값이나 의미/통제 위반 |
| L1-03 | document | 2 | 2 | CoA validity | 비사용/무효 계정 | 유효 계정으로 가공 매출/대여금 은폐 |
| L1-04 | document/flow | 2 | 2 | approval limit, approver authority | 승인한도 초과 승인 | 한도 직하 분할 승인 |
| L1-05 | document | 2 | 2 | created_by, approved_by | 자기 승인 | 공모자/system 승인으로 direct self-approval 회피 |
| L1-06 | user_behavior_flow | 2 | 2 | SoD role evidence | direct SoD conflict | 여러 사용자 ring 분산 |
| L1-07 | document/flow | 2 | 2 | approval required/missing | 승인 누락 | 승인 불필요 금액/automated source 위장 |
| L1-08 | document | 2 | 2 | posting_date, fiscal_period | 기간 불일치 | fiscal_period는 맞고 증빙/cutoff만 왜곡 |
| L1-09 | document | 2 | 2 | approval_date | 승인일 누락 | 승인일 존재하나 사후 승인 |
| L2-01 | flow | 2 | 2 | approval threshold, related docs | 한도 직하 단건/반복 | 더 작은 split으로 threshold 회피 |
| L2-02 | duplicate_flow | 2 | 2 | partner, amount, reference, date | 동일 지급 중복 | 정기 지급/다른 reference로 suppress/drop 유도 |
| L2-03 | duplicate_flow | 2 | 2 | duplicate pair features | exact/near duplicate JE | recurring/self-contained/different-reference 위장 |
| L2-04 | document | 2 | 2 | account/text/document_type | 비용 자산화 | 정상 CAPEX 문구와 문서유형으로 review-only 위장 |
| L2-05 | reversal_flow | 2 | 2 | original/reversal link, amount symmetry | 부정 reversal/zero-out | 정상 reason/link 또는 rolling zero-out 위장 |
| L3-01 | document | 2 | 2 | process/account/counterparty/text | semantic mismatch | 정상 semantic tuple로 허위 거래 |
| L3-02 | document | 2 | 2 | source/manual indicator | 수기 조정 고위험 | interface/batch source 위장 |
| L3-03 | intercompany_flow | 2 | 2 | related party/counterparty | 관계사 거래 | 고객/벤더 코드 또는 mapping_uncertain 위장 |
| L3-04 | document | 2 | 2 | is_period_end, posting_date | 기말/기초 결산 조작 | 기간 중 분산 posting |
| L3-05 | document | 2 | 2 | calendar/weekend | 주말/공휴일 posting | 평일 정상시간으로 우회 |
| L3-06 | document | 2 | 2 | posting hour | 심야 posting | 결산 야근/업무시간으로 우회 |
| L3-07 | document | 2 | 2 | document_date/posting_date | 장기 backdating | document_date도 맞춰 cutoff substance만 왜곡 |
| L3-08 | document | 2 | 2 | line/header text quality | 적요 결손/파손 | 정상 text family 사용 |
| L3-09 | reversal_flow/open_item | 2 | 2 | suspense/open item/clearing | 장기 미결 | 단기 clearing으로 은폐 |
| L3-10 | document | 2 | 2 | high-risk account map | 고위험 계정 사용 | 일반 prepaid/receivable/expense에 분산 |
| L3-11 | document/flow | 2 | 2 | revenue cutoff fields | 매출 cutoff mismatch | 문서상 날짜 정합, 실질 기간만 왜곡 |
| L3-12 | user_behavior_flow | 2 | 2 | user process scope | 업무범위 집중 | 여러 사용자 ring으로 분산 |
| L4-01 | macro_account_group | 2 groups | 2 groups | revenue monthly distribution | 매출 이상 변동 | 여러 고객/월로 smoothing |
| L4-02 | macro_account_group | 2 groups | 2 groups | Benford eligible amounts | Benford 왜곡 | 정상 첫자리 분포로 분산 |
| L4-03 | document/flow | 2 | 2 | peer amount distribution | 이상 고액 | p95 이하 split |
| L4-04 | document | 2 | 2 | debit/credit account pair frequency | 희소 계정쌍 | 흔한 계정쌍으로 허위 거래 |
| L4-05 | user_time_flow | 2 | 2 | time/user cluster | 비정상 시간대 집중 | 업무시간 소량 분산 |
| L4-06 | batch_flow | 2 | 2 | source/batch/job metadata | 비정상 batch posting | 정상 batch/interface 크기 위장 |
| IC01 | intercompany_flow | 2 | 2 | IC counterparty, rec/pay | unmatched IC counterpart | blank/nonstandard/vendor-like partner |
| IC02 | intercompany_flow | 2 | 2 | IC amount reconciliation | amount mismatch > tolerance | tolerance 이내 분산/FX 위장 |
| IC03 | intercompany_flow | 2 | 2 | IC date reconciliation | date gap > window | window 이내이나 실질 cutoff 왜곡 |
| GR01 | graph_flow | 2 cycles | 2 cycles | company graph edges | 3-hop+ circular flow | hop limit 밖/정상 settlement 위장 |
| GR03 | graph_flow | 2 pairs | 2 pairs | bilateral IC price fields | 양방향 price asymmetry | 세금/운임/FX처럼 보이게 분산 |
| D01 | macro_account_group | 2 groups | 2 groups | prior/current account activity | 계정 활동량 급변 | 여러 계정/신규 계정으로 smoothing |
| D02 | macro_account_group | 2 groups | 2 groups | monthly distribution history | 월별 분포 패턴 변화 | recurring/batch context에 섞어 smoothing |

## Acceptance 원칙

1. `input_ready=true`는 입력 컬럼 존재만이 아니라 값이 해당 룰 구조를 표현할 수 있을 때만 인정한다.
2. `structural_probe_ready=true`는 sidecar truth를 제외한 journal/master/flow 컬럼만으로 표준 위반이 규칙적으로 재현될 때만 인정한다.
3. evasion 케이스는 반드시 주입하지만, 표준 룰이 evasion을 잡는 것을 목표로 하지 않는다. evasion은 suppress/drop/weak-signal 경계를 측정하기 위한 별도 truth다.
4. 단일 컬럼 값이 `N>=5` 및 `normal==0`으로 truth를 분리하면 FAIL이다. 단, sidecar truth/provenance 파일은 검사 대상 feature surface가 아니다.
5. 정상 realism gate는 정상 subset 기준으로 PASS해야 한다. 부정 subset은 해당 부정의 의도된 위반만 실패해야 한다.

## v10 산출 기록

- 출력 데이터셋: `data/journal/primary/datasynth_semantic_v1_p3_2_overlay_20260607_v10`
- 정상 base: `data/journal/primary/datasynth_semantic_v1_normal_20260607_v29`
- truth units: 156 (`39 rules * standard 2 + evasion 2`)
- truth member documents: 746
- overlay rows: 1,492
- output rows: 984,520
- journal columns: 64
- journal forbidden truth/provenance columns: 0
- 전 컬럼 local oracle scan: 0 findings (`reports/p3_2_overlay_local_scan.json`)
- PHASE1 detector catch/miss 및 per-rule actual fire 측정: P2-4 이후 별도 실행
