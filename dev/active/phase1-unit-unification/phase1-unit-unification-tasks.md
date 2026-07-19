# PHASE1 단위 통일(P2) Tasks

## 전제

- P1이 완료되어 룰 메타데이터와 현행 PHASE1 출력 계약을 읽을 수 있어야 한다.
- 기준 정책은 [UNIT_MEASUREMENT_POLICY.md](../../../docs/spec/UNIT_MEASUREMENT_POLICY.md)다.
- 현재 범위 지도는 [phase1-unit-scope-analysis.md](phase1-unit-scope-analysis.md)를 따른다.
- 결정 lock과 설계 제안은 [phase1-unit-unification-plan.md](phase1-unit-unification-plan.md)를 따른다.

## 체크리스트

| 단계 | 상태 | 작업 | 의존 | 위험도 | 검증 |
| --- | --- | --- | --- | --- | --- |
| P2-0 | [ ] | 결정 lock, scoring 철학, mitigation 가드, R1/R2 제안 문서화 | P1 완료 | 낮음 | 문서 링크 확인, 코드 diff 없음 확인 |
| P2-1 | [ ] | `CaseGroupResult` 호환 유지 + 신규 document/flow unit 모델 additive 추가 | P2-0 | 높음 | 기존 artifact 역직렬화, 신규 `units` roundtrip, PHASE2 계약 필드 shape 확인 |
| P2-2 | [ ] | row-level detector 결과에서 document unit adapter 구성. row는 evidence pointer로만 연결 | P2-1 | 중간 | document-rule별 unit 생성 테스트, row denominator 금지 테스트 |
| P2-3 | [ ] | flow builder 구현. 기존 pair/cycle/set artifact 재사용, L2-02/L2-05 최소 링크키, deterministic `flow_id` | P2-1 | 높음 | flow id reload-safe 테스트, capped artifact `measurement_eligible` 테스트, R1 overlap 테스트 |
| P2-4 | [ ] | `composite_sort_score`, `priority_score`, topic score를 unit 단일 경로로 이동. case score는 derived만 | P2-2, P2-3 | 높음 | G1/G2 위반 탐지 테스트, per-unit corroboration 테스트, 기존 band/weight 유지 테스트 |
| P2-5 | [ ] | 기존 `cases` artifact와 PHASE2 overlay 호환 계층 유지. `phase1_case_id` 유지 + unit refs 추가 | P2-4 | 높음 | PHASE2 compatibility regression, legacy case consumer smoke |
| P2-6 | [ ] | dashboard/export/DB가 additive unit refs를 읽도록 확장. 기존 case 표시 유지 | P2-5 | 중간~높음 | dashboard import smoke, export schema regression, DB migration/backward compatibility |
| P2-7 | [ ] | case-truth 회귀 테스트를 unit 단위로 같거나 더 엄격하게 재작성. review population coverage 후속 연결 | P2-4, P2-5, P2-6 | 높음 | unit denominator/numerator tests, Benford/variance truth-denominator 금지, PHASE2 contract test |

## 세부 작업

### P2-0 결정 lock

- D1~D8 결정을 문서 기준으로 고정한다.
- G1~G5 mitigation 가드를 구현 완료 기준에 포함한다.
- R1/R2는 확정이 아니라 사용자 리뷰 대상 제안으로 남긴다.
- 검증: 문서 3종이 존재하고, 코드 파일 변경이 없어야 한다.

### P2-1 모델 additive 확장

- 신규 unit 모델은 `document`와 `flow`만 1차 unit type으로 허용한다.
- 기존 `CaseGroupResult` 필드는 PHASE2와 dashboard/export 호환을 위해 유지한다.
- case에는 독립 truth, denominator, 독립 score 필드를 새로 추가하지 않는다.
- 검증: legacy artifact load가 깨지지 않고, 신규 artifact는 `cases`와 `units`를 함께 가진다.

### P2-2 document unit adapter

- document-rule hit를 document unit으로 묶는다.
- row-level detail은 `RawRuleHitRef` 같은 증거 포인터로만 남긴다.
- flow member document의 document-rule hit는 R1 확정안에 따라 흡수 또는 예외 처리한다.
- 검증: row count가 numerator/denominator로 쓰이지 않는 테스트를 둔다.

### P2-3 flow builder

- L2-03, IC01~IC03, GR01은 기존 detector artifact를 source로 삼는다.
- L2-02와 L2-05는 artifact가 없으므로 최소 링크키 로직을 신규 작성한다.
- flow artifact에는 completeness, truncation, cap reason, measurement eligibility를 남긴다.
- `flow_id`는 reload-safe deterministic hash로 생성한다.
- 검증: 같은 입력을 재실행해도 같은 `flow_id`가 생성되고, capped artifact가 truth denominator로 들어가지 않는다.

### P2-4 unit scoring

- 점수 산출 함수는 unit을 입력으로 받는 단일 경로가 된다.
- 기존 공식, 가중치, high/medium/low band는 유지한다.
- corroboration은 같은 unit 내부의 독립 evidence type만 가산한다.
- case는 unit score의 max/sum/count derived 표시만 가진다.
- 검증: case 독립 점수가 남아 있으면 실패하는 테스트를 둔다.

### P2-5 compatibility layer

- 기존 `cases` artifact shape는 유지한다.
- `case_key`, `phase1_case_id`, PHASE2가 읽는 필드 의미는 고정한다.
- case에는 관련 unit refs와 derived score만 연결한다.
- 검증: PHASE2 overlay가 기존 계약으로 로드되고, unit refs가 없어도 legacy path가 graceful하게 동작한다.

### P2-6 dashboard/export/DB

- dashboard와 export는 기존 case 중심 표시를 유지하되, 상세에는 unit refs를 노출할 수 있게 한다.
- DB/schema 변경은 additive 방식으로 설계한다.
- Benford/variance/account/process review population은 truth denominator가 아니라 별도 coverage 대상으로 유지한다.
- 검증: 기존 export 컬럼이 사라지지 않고, 신규 unit 컬럼이 없는 legacy artifact도 읽힌다.

### P2-7 테스트 강화

- 기존 case-truth 테스트를 unit-truth 테스트로 재작성한다.
- document/flow disjoint, R1 overlap, R2 completeness, PHASE2 compatibility를 회귀 테스트로 둔다.
- 통과를 위해 기대값을 약화하지 않는다.
- 후속 P3-2에서 Benford/variance review population coverage 검증을 이어받을 수 있게 TODO를 명확히 남긴다.

## 의존 순서

P2-0 이후 P2-1을 먼저 수행한다. P2-2와 P2-3은 P2-1 위에서 병렬 검토가 가능하지만, P2-4 점수 이동 전에 둘 다 완료되어야 한다. P2-1/P2-2/P2-3까지 완료되면 후속 P3-2 착수가 가능하다. P2-4 이후 P2-5와 P2-6을 진행하고, P2-7에서 계약·회귀 테스트를 닫는다.

## 완료 기준

- `document`와 `flow`만 truth/측정 unit으로 쓰인다.
- row는 evidence pointer로만 쓰인다.
- case는 표시 전용 aggregate view이며 독립 점수를 갖지 않는다.
- PHASE2가 읽는 legacy `CaseGroupResult` 계약은 깨지지 않는다.
- Benford/variance/account/process review population은 사라지지 않지만 truth denominator로도 들어가지 않는다.

## 후속 추적 — datasynth normal-data 트랙 (P2 범위 밖, 잊지 않기 위해 임시 기록)

아래는 normal-data 현실성 검증(P3-1)에서 BLOCKED로 남긴 항목이다. P2(phase1 코드) 작업 항목이
아니라 datasynth-journal-realism-rebuild 트랙 소관이며, 유실 방지를 위해 여기 기록한다. 닫히는
시점에 datasynth 트랙으로 이관한다.

| 항목 | 닫는 조건 | 우선순위 |
| --- | --- | --- |
| B17 archetype coverage | datasynth 데이터에 explicit `archetype_id`를 넣는 시점에 닫는다. joint draw가 실제로 됐는지 검증하는 수단이다. | 중간 |
| M01_M07 TB/subledger/roll-forward | 잔액·보조원장(opening/closing balance, subledger) 데이터가 생성되면 별도 verifier로 닫는다. | 중간 |
| P01 전문가/LLM 샘플 리뷰 | fixed-seed stratified 샘플 하니스로 형식화한다(현재는 수동 검토만 수행). diagnostic 전용, pass/fail 권한 없음. | 낮음 |
| O02 scan 확장 | 현재 3개 패턴(값→시나리오 순도, timestamp 클러스터, 시나리오 내 금액 지배)에 user→process 순도, reference prefix 순도 차원을 추가한다. | 낮음 |

> batch 볼륨(J08)은 v19에서 현실적 모집단(월별×법인×연도, 324건)으로 닫혔고 verifier가 60건 미만이면
> FAIL하도록 강화됨. 더 이상 추적 불필요.
