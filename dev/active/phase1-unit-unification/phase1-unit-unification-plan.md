# PHASE1 단위 통일(P2) Plan

## 범위

P2는 PHASE1의 탐지·측정 단위를 `document`와 `flow`로 통일한다. 기존 `CaseGroupResult`와 artifact의 호환성은 유지하되, `case`는 표시 전용 집계 뷰로 강등한다. 점수는 더 이상 case가 독립적으로 산출하지 않고, document/flow unit에서 산출된 값을 읽어 파생 표시한다.

이 문서는 결정 lock, 위험 mitigation, R1/R2 설계, 구현 단계 P2-0~P2-7을 정리한다. R1/R2는 2026-06-04 사용자 리뷰로 확정됐다(아래 각 절의 "확정" 표기).

## 결정 Lock

| ID | 결정 |
| --- | --- |
| D1 | `CaseGroupResult`는 호환 목적으로 유지하고 신규 `document`/`flow` unit을 추가한다. `case`는 표시 전용 집계 뷰로 강등한다. |
| D2 | artifact schema는 additive 방식으로 확장한다. 기존 `cases`는 유지하고 `units`를 추가해 기존 artifact를 깨지 않는다. |
| D3 | 점수는 document/flow unit에 산출한다. case 점수는 unit 점수의 max/sum/count derived 값만 둔다. case가 독립 점수를 갖는 일은 제거한다. |
| D4 | flow builder는 detector가 이미 만든 pair/cycle/set artifact를 flow로 노출·재사용한다. row details에서 재추론하지 않는다. artifact가 없는 L2-02/L2-05만 최소 링크키 로직을 신규 작성한다. |
| D5 | L4-02 Benford는 32룰에 남기되 truth 분모가 아니다. 별도 분석 review population으로 분리한다. |
| D6 | D01/D02는 account/process review population으로 유지하고 truth 분모로 쓰지 않는다. |
| D7 | PHASE2 overlay는 P2에서 손대지 않는다. `phase1_case_id`를 유지하고 unit refs만 추가한다. `unit_id` 전환은 PHASE2 재설계 후속 P4로 미룬다. |
| D8 | row score는 증거 포인터와 내부/호환 score로 유지한다. truth 분모로 쓰지 않는다. |

## 점수 철학 Lock

- PHASE1 점수는 부정 확률이 아니라 감사인이 먼저 볼 triage 우선순위다.
- 목적, 공식 모양, 가중치, high/medium/low 밴드는 유지한다.
- 바뀌는 것은 점수가 붙는 단위다. 기존 case bucket이 아니라 document/flow unit에 붙인다.
- corroboration은 per-unit으로 재계산한다. 같은 전표 또는 같은 흐름에 서로 다른 독립 각도가 모일 때만 가산한다.
- 기존 사용자×월 같은 버킷에서 무관한 전표가 섞여 가짜 corroboration이 부풀던 효과를 제거한다.
- truth, owner, scenario 라벨이나 recall에 맞춘 점수 튜닝은 금지한다.

## 위험 Mitigation 가드

| ID | 가드 |
| --- | --- |
| G1 | case가 독립 점수를 가지면 P2는 미완성으로 본다. 구현 검증에서 D3 위반 여부를 직접 확인한다. |
| G2 | 점수 산출 경로는 unit 한 곳으로 제한한다. case, dashboard, export는 unit score 또는 derived 값만 읽는다. |
| G3 | PHASE2가 읽는 `CaseGroupResult` 필드의 모양과 의미를 고정한다. PHASE2 계약 호환 회귀 테스트를 둔다. |
| G4 | 기존 case-truth 회귀 테스트는 unit 단위로 같거나 더 엄격하게 재작성한다. 통과를 위해 약화하지 않는다. |
| G5 | Benford/variance는 truth 분모로 쓰지 않되, 계정/모집단 review signal이 사라지지 않도록 후속 P3-2에 별도 coverage 검증을 둔다. |

## R1 제안: 흐름/전표 겹침 카운트 규칙

### 문제

하나의 document가 flow의 member이면서 동시에 document-rule에 걸릴 수 있다. 이때 document 1건과 flow 1건을 모두 truth/측정 단위로 세면 `document XOR flow` disjoint 약속이 깨진다.

### 제안안

기본 규칙은 다음과 같이 둔다.

> document가 어떤 measurement-eligible flow의 member이면, 그 document의 document-rule hit는 flow unit 내부 증거로 흡수한다. 별도 document unit은 어떤 flow에도 속하지 않은 document만 생성한다.

단, 독립 이슈를 과도하게 흡수해 undercount하는 위험을 줄이기 위해 리뷰 대상 옵션을 둔다.

| 옵션 | 규칙 | 장점 | 위험 |
| --- | --- | --- | --- |
| R1-A 엄격 흡수 | flow member document의 모든 document-rule hit를 primary flow에 흡수 | disjoint 보장이 가장 단순하고 테스트가 명확함 | 동일 전표의 flow와 무관한 독립 document 이슈를 놓칠 수 있음 |
| R1-B catalog 예외 흡수 | 기본은 흡수하되, scenario catalog 또는 명시 라벨이 별도 document-natural truth item임을 말할 때만 독립 document unit 허용 | disjoint를 유지하면서 독립 이슈 undercount를 줄임 | scenario catalog 의존과 테스트 복잡도 증가 |

확정(2026-06-04): 탐지 시점에는 **R1-A**로 한다 — 라벨을 보지 않고 measurement-eligible flow에 항상 흡수한다. "한 전표에 독립 부정 2개" 우려는 **측정 시점에 catalog truth item과 evidence-coverage로 해결**한다(흡수된 hit는 flow 증거로 남아 cover되므로 undercount가 아니다). catalog/truth 라벨을 탐지 시점 selector로 쓰지 않는다(fitting 금지). 탐지 시점에 독립 document unit으로 분리해야 할 경우가 있으면, 그 트리거는 catalog 라벨이 아니라 구조적 근거(flow 메커니즘과 무관한 독립 hard 룰 위반 등)여야 한다.

### 엣지케이스 처리 제안

| 엣지케이스 | 제안 처리 |
| --- | --- |
| 한 document가 둘 이상 flow에 속함 | 모든 valid flow에는 evidence ref로 연결하되, truth/측정 owner는 primary flow 하나로만 지정한다. primary flow는 결정적 우선순위로 선택한다. |
| primary flow 선택 | confirmed flow-rule, review-only flow, scenario catalog match, 높은 severity/tier, 더 작은 flow cardinality, 안정적 `flow_id` 사전순 순서로 결정한다. |
| flow와 무관해 보이는 document-rule hit | 탐지 시점엔 라벨 안 보고 기본 흡수(measurement-eligible flow일 때). undercount 우려는 측정 시점 catalog truth × evidence-coverage로 해결한다. 탐지 시점 분리가 필요하면 트리거는 구조적 근거여야 하며 catalog 라벨이 아니다. |
| flow 점수와 흡수된 document 증거 | flow base score는 flow-rule에서 산출하고, 흡수된 document-rule hit는 같은 flow의 독립 evidence type일 때만 corroboration에 기여한다. 별도 numerator는 만들지 않는다. |
| dashboard 표시 | 흡수된 document-rule hit는 `absorbed_document_rule_hits` 또는 evidence refs로 표시한다. 사용자는 근거를 보되 측정 단위는 flow 하나로 유지한다. |

필요 필드는 `measurement_owner_unit_id`, `absorbed_document_ids`, `absorbed_rule_hits`, `cross_ref_flow_ids` 수준으로 충분하다. 이름은 구현 단계에서 기존 모델 컨벤션에 맞춰 정한다.

## R2 제안: flow artifact 완전성·재현성

### 현재 진단

| flow-rule | 현재 상태 | 완전성 판단 | 재현성 판단 |
| --- | --- | --- | --- |
| L2-02 중복 지급 | 독립 flow artifact 없음 | absent | 신규 결정적 link key 필요 |
| L2-03 중복 전표 | `duplicate_pair_artifact.top_pairs`는 cap/top-N subset. `truncated`와 cap 진단 존재 | bounded | 표시 artifact만으로 stable flow universe 보장 불충분 |
| L2-05 역분개/취소 | 구조적 참조와 one-to-one match는 있으나 flow artifact 없음 | absent | 신규 결정적 pair/set id 필요 |
| IC01~IC03 | candidate/unmatched/mismatch/reciprocal list가 상한으로 capped | bounded | retained pair 기준으로는 가능하나 전체 flow universe 보장 불충분 |
| GR01 순환 | cycle artifact 없음. edge cap, component skip metadata만 있음 | bounded/absent | canonical cycle id 필요 |

### 보완 설계

flow builder는 artifact completeness를 명시한다.

| 필드 | 의미 |
| --- | --- |
| `artifact_completeness` | `complete`, `bounded`, `absent`, `skipped` 중 하나 |
| `truncated` / `cap_reason` | cap, sampling, component skip 등으로 전체 모집단이 아니었는지 |
| `source_artifact_schema` | 어떤 detector artifact에서 왔는지 |
| `candidate_count` / `retained_count` / `member_count` | 전체 후보와 보존된 flow 규모 |
| `measurement_eligible` | truth/측정 분모에 들어갈 수 있는지 |

`measurement_eligible=true`는 full identity가 있거나 P2에서 명시적으로 재구성 가능한 flow에만 허용한다. capped 표시용 subset만 있는 flow는 review display에는 남길 수 있으나 truth denominator로 쓰지 않는다.

확정(2026-06-04): 단, 측정에 쓰이는 flow-rule(중복·IC·순환)의 목표는 "bounded → 측정 제외"가 아니라 "cap을 올리거나 제거해 `complete`로 재구성"하는 것이다. `measurement_eligible=false`는 불가피할 때의 fallback이며, 그 경우 coverage 구멍 크기(`candidate_count` 대비 `retained_count`)를 명시 리포트한다. capped subset을 정상 상태로 방치하지 않는다.

### L2-02 최소 링크키 제안

L2-02는 artifact가 없으므로 D4의 예외로 최소 링크키를 새로 둔다.

- `flow_type`: `duplicate_payment`
- link key: 정규화 거래처, 금액 minor-unit 또는 허용오차 bucket, 근접기간 bucket, 정규화 reference 또는 지급 문서 유형
- member 조건: 같은 link key에 속한 서로 다른 document가 2개 이상
- `flow_id`: `p1_flow_l202_v1_` + stable hash
- hash 입력: company/engagement scope, normalized link key, 정렬된 member document id 목록

### L2-05 최소 링크키 제안

L2-05는 구조적 참조를 우선하고, 없을 때만 기존 one-to-one matching 결과와 zero-out set을 사용한다.

| 우선순위 | 링크 방식 | flow 구성 |
| --- | --- | --- |
| 1 | ERP 구조적 참조 | original document와 reversal document pair |
| 2 | one-to-one reversal match | 계정, 절대금액, 부호 반대, 근접일, context hash가 맞는 pair |
| 3 | rolling zero-out set | 계정/작성자/기간 window에서 net amount가 허용오차 내 0에 가까운 document set |

`flow_id`는 `p1_flow_l205_v1_` + stable hash로 만들고, hash 입력은 link type, normalized key, 정렬된 member document id 목록이다.

### deterministic flow_id 규칙

- 실행 순서, row index 순서, DataFrame partition 순서에 의존하지 않는다.
- company/engagement scope, rule id, flow type, normalized link key, 정렬된 member document id를 입력으로 사용한다.
- 금액은 minor unit 또는 정책 허용오차 bucket으로 정규화한다.
- 날짜는 명시 bucket 또는 canonical ISO date/window로 정규화한다.
- 민감한 원문 텍스트를 그대로 id에 넣지 않고 stable hash만 노출한다.
- hash prefix에 schema version을 포함한다.

## 단계 계획

| 단계 | 목적 | 주요 파일/영역 | 의존 |
| --- | --- | --- | --- |
| P2-0 | 결정 lock과 계약 문서화 | `dev/active/phase1-unit-unification/**` | P1 완료 전제 |
| P2-1 | additive unit 모델 추가 | `src/models/phase1_case.py`, artifact schema | P2-0 |
| P2-2 | document unit adapter | `src/detection/**`, case builder 주변 | P2-1 |
| P2-3 | flow builder와 deterministic `flow_id` | duplicate/IC/graph/reversal detector artifact, pipeline | P2-1 |
| P2-4 | scoring을 unit 단일 경로로 이동 | score aggregator, priority/topic score, config | P2-2, P2-3 |
| P2-5 | case compatibility layer | `CaseGroupResult`, pipeline artifact, PHASE2 overlay boundary | P2-4 |
| P2-6 | dashboard/export/DB additive 소비 | dashboard, exports, DB/schema/query | P2-5 |
| P2-7 | 회귀·계약 테스트 강화 | tests, fixtures, compatibility checks | P2-4~P2-6 |

P2-1/P2-2/P2-3까지 완료되면 후속 P3-2의 review population coverage 설계 착수가 가능하다. P2-4 점수 이동, P2-5/P2-6 호환 계층, P2-7 테스트 강화는 그 뒤 순서로 진행한다.
