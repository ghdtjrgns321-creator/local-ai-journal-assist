# PHASE1 단위 통일(P2) Context

## 목적

PHASE1 단위 통일(P2)은 기존 `case` 중심 산출물을 유지하면서, 탐지·truth·측정의 1차 단위를 `document`와 `flow`로 분리하는 리팩터다. `row`는 증거 포인터로만 남기고, 기존 `case`는 감사인이 화면에서 보는 GROUP BY 집계 뷰로 강등한다.

이 문서는 P2 구현 전에 필요한 기준 문서, 현재 상태, ripple 영향을 한 곳에 연결한다. 코드 변경은 이 문서 작성 범위에 포함하지 않는다.

## 기준 문서

- 단위 정책 SoT: [UNIT_MEASUREMENT_POLICY.md](../../../docs/spec/UNIT_MEASUREMENT_POLICY.md)
- 현재 범위 분석: [phase1-unit-scope-analysis.md](phase1-unit-scope-analysis.md)
- 운영 룰 기준: [DETECTION_RULES.md](../../../docs/spec/DETECTION_RULES.md)
- 룰 상세 메타데이터 기준: [RULE_DETAIL_METADATA_V1_LOCK.md](../../../docs/spec/RULE_DETAIL_METADATA_V1_LOCK.md)

## 단위 정책 요약

P2의 목표 상태는 다음 3층 모델이다.

| 층 | 목표 의미 | P2에서의 처리 |
| --- | --- | --- |
| `row` | 전표 내부 증거 포인터 | `document_id + row_index` 참조로 유지. truth 분모 금지 |
| `document` / `flow` | 탐지·truth·측정 1차 단위 | unit 객체로 신규 추가. score 산출 위치 |
| aggregate view | 표시용 GROUP BY | 기존 `case` 호환 유지. 독립 점수·정답·분모 금지 |

룰의 `document-rule` / `flow-rule` 분류는 구현 경로를 정하기 위한 태그다. 이 분류 자체는 측정 분모가 아니며, truth item은 항상 `document XOR flow`로만 귀속한다.

## 현재 지도 요약

상세 지도는 [phase1-unit-scope-analysis.md](phase1-unit-scope-analysis.md)를 기준으로 한다.

| 영역 | 현재 상태 | P2 영향 |
| --- | --- | --- |
| 탐지기 출력 | 대부분 `DetectionResult`의 row-level `scores`, `flags`, `details` 중심 | row를 unit으로 승격하지 않고 document/flow unit 생성 입력으로만 사용 |
| flow 후보 | 중복, IC, 순환은 pair/cycle/set 성격이 있으나 artifact 또는 `case_key`로 암묵 존재 | flow를 1차 객체로 노출하고 결정적 `flow_id` 부여 |
| case builder | `CaseGroupResult`가 증거 묶음, 집계 버킷, 점수 컨테이너를 동시에 담당 | 모델 호환은 유지하되 case를 표시 전용 집계 뷰로 강등 |
| scoring | `composite_sort_score`, `priority_score`, topic score가 case/row 맥락에 붙음 | 점수 단일 경로를 unit으로 이동. case는 max/sum/count derived만 보유 |
| queue/dashboard/export | `case_key`, `priority_score`, `CaseGroupResult` 필드를 직접 소비 | additive schema로 기존 필드를 유지하고 `unit_refs`를 추가 |
| PHASE2 overlay | `phase1_case_id` 중심 링크 | P2에서는 건드리지 않고 unit refs만 추가. unit_id 전환은 후속 P4 |

## flow artifact 상태 요약

R2 설계 검토를 위해 현재 flow-rule detector artifact를 확인했다.

| 룰/영역 | 현재 artifact 상태 | P2 판단 |
| --- | --- | --- |
| L2-03 중복 전표 | `duplicate_pair_artifact.top_pairs`는 cap/top-N 적용된 표시용 subset이며 `truncated`, cap 진단이 있음 | 전체 flow universe로 보기 부족. full identity 또는 deterministic reconstruction 계층 필요 |
| IC01~IC03 | `IntercompanyPairArtifact`의 candidate/unmatched/mismatch/reciprocal list가 상한으로 잘림 | capped artifact이므로 measurement eligible flow 생성을 위해 completeness 표시와 full-source 보강 필요 |
| GR01 순환 | row score와 metadata 중심. 그래프 edge cap, component skip이 있고 안정적 cycle artifact가 없음 | canonical cycle artifact와 stable `flow_id` 필요 |
| L2-02 중복 지급 | 독립 flow artifact 없음 | 예외적으로 최소 링크키 로직 신규 작성 필요 |
| L2-05 역분개/취소 | 구조적 참조와 one-to-one matching은 있으나 artifact가 없음 | 예외적으로 최소 링크키와 결정적 pair/set flow 생성 필요 |

## ripple 요약

아래 소비자는 P2에서 깨질 위험이 높다. 전수 목록은 [phase1-unit-scope-analysis.md](phase1-unit-scope-analysis.md)의 ripple-search 절을 기준으로 한다.

| 소비자 | 주요 의존 | P2 가드 |
| --- | --- | --- |
| `dashboard/**` | `case_key`, `priority_score`, topic score, evidence rows | 기존 case 필드 유지. unit 점수와 unit refs를 additive로 노출 |
| `exports/**` | case 중심 CSV/PDF/Excel 필드 | 기존 export shape 유지 후 unit refs 추가. case score는 derived 표시만 |
| `src/services/**` PHASE2 | `phase1_case_id`, CaseGroupResult 의미 | `phase1_case_id` 계약 유지. PHASE2 호환 회귀 테스트 필수 |
| `tests/**` | case-truth, row score, priority ordering 기대값 | unit 단위로 같거나 더 엄격하게 재작성. 약화 금지 |
| `config/**` | case_key 전략, scoring weight/band | 공식과 밴드는 유지하되 적용 단위만 unit으로 이동 |

## 작업 경계

- 이번 P2 계획화 범위는 설계 문서 작성까지다.
- PHASE2 overlay의 unit 전환은 후속 P4로 미룬다.
- Benford(L4-02), variance/account/process review population은 truth 분모로 넣지 않는다.
- DataSynth 진행 작업은 건드리지 않는다.
