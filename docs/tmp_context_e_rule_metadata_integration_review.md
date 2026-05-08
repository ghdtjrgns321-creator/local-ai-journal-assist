# Context E: RuleDetailMetadata Integration Gate Review

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.
## 1. 최종 판정

**CONDITIONAL GO**

A/B/C/D의 핵심 정책은 대체로 같은 방향이다. 특히 `canonical_rule_id`, `presenter_surface`, `status`, `standalone_rankable=False`, macro/sidecar 제외 정책은 문서상으로는 정합성이 있다.

다만 구현 착수 전에 반드시 정리해야 할 차이가 있다. 현재 코드와 테스트에는 macro, sidecar, internal reason code가 transaction row detail 또는 "위반"성 문구로 노출될 수 있는 경로가 남아 있다. 또한 대시보드의 "33개 룰" 정의가 A의 count 정책과 충돌한다. 이 항목들을 먼저 확정하지 않으면 메타데이터를 추가해도 UI/export/case_builder가 서로 다른 기준으로 동작할 가능성이 높다.

구현 착수 가능 여부: **조건부 가능**. 아래 필수 수정사항을 설계에 반영한 뒤 구현에 들어가야 한다.

## 2. 필수 수정사항

1. **rule count 정책을 하나로 고정**
   - A 기준: L1~L4 canonical transaction rule count는 32개.
   - `Benford`는 `L4-02` alias.
   - `D01/D02`, `IC01~IC03`, `GR01/GR03`는 L1~L4 transaction rule count에서 제외.
   - 현재 `dashboard/tab_phase1.py`는 `D01/D02`를 포함해 "전체 33개 룰"로 다루는 흐름이 있어 구현 전에 기준을 수정해야 한다.

2. **`L2-03a~d` internal reason code 정책을 코드 경계에서 강제**
   - A/D: `L2-03a~d`는 `L2-03`의 drilldown reason이며 독립 룰로 표시하거나 count하면 안 된다.
   - 현재 `src/detection/rule_scoring.py`에는 `L2-03a~d`가 registry entry로 존재하고 primary처럼 사용될 수 있다.
   - metadata accessor에서 `canonical_rule_id=L2-03`, `status=internal_reason_code`, `presenter_surface=drilldown_reason`, `include_in_l1_l4_transaction_count=False`를 강제해야 한다.

3. **`Benford` alias 정책을 구현 전 확정**
   - A/B/D: `Benford -> L4-02`.
   - `Benford`는 별도 transaction rule count에 포함하지 않는다.
   - export/dashboard/topic 표시에서 `requested_rule_id=Benford`를 추적하더라도 canonical 집계와 표시 표면은 `L4-02` 기준으로 통일해야 한다.

4. **macro/sidecar/reason row detail 차단**
   - `L4-02`, `Benford`, `D01`, `D02`, `GR01`, `GR03`는 macro/sidecar 성격이며 transaction row violation detail에 들어가면 안 된다.
   - `IC01~IC03`는 intercompany sidecar로 L1~L4 transaction count와 섞이면 안 된다.
   - `src/export/phase1_case_view.py`의 현재 rule document builder/test 흐름은 macro/sidecar/reason code까지 row-level evidence builder 대상으로 볼 여지가 있다.
   - export와 dashboard는 `presenter_surface` 기반으로 row detail 허용 여부를 먼저 판단해야 한다.

5. **standalone false 룰의 단독 위반 표시 방지**
   - 적용 대상: `L3-05`, `L3-06`, `L3-08`, `L3-10`, `L3-12`, `L4-06`, `L4-02/Benford`, `D01/D02`, `GR01/GR03`.
   - `L4-05`도 현재 문서/코드상 context 성격이므로 같은 보호가 필요하다.
   - 이 룰들은 단독 case seed, Top-N seed, transaction violation summary로 표시되지 않아야 한다.

6. **B 문구를 UI/export copy의 우선 소스로 사용**
   - B는 대부분 "검토 신호", "보조 근거", "맥락" 표현을 사용해 정책과 맞는다.
   - 현재 dashboard의 `L4-02` 관련 "벤포드 위반", "인위적 금액 조작의 통계적 증거" 계열 문구는 macro/context 정책에 비해 단정적이다.
   - metadata 적용 시 B 문구로 치환하거나, forbidden-copy validator로 차단해야 한다.

7. **C column metadata의 required 범위 축소**
   - C에 나온 일부 컬럼은 ledger schema에 없거나 derived/sidecar output이다.
   - 예: `approved_at`, `upload_batch_id`, `target_document_id`, `counterpart_document_id`, `graph_finding_id`, `counterparty`, `amount`, `difference_value`, `anomaly_score`, `risk_level`.
   - `required_ledger_columns`, `optional_ledger_columns`, `derived_columns`, `sidecar_output_columns`를 분리해야 한다.

8. **D schema를 1차 구현 범위에 맞게 줄이기**
   - D의 nested Pydantic schema는 방향은 좋지만 첫 구현으로는 과하다.
   - 필수 필드는 `rule_id`, `canonical_rule_id`, `status`, `presenter_surface`, `topic`, `scoring_role`, `standalone_rankable`, `include_in_l1_l4_transaction_count`, `allow_row_violation_detail`, `display_copy`, `column_sources`, `conflict_note` 정도로 시작하는 것이 안전하다.

## 3. 권장 수정사항

1. `RuleDetailMetadata` 파일명과 accessor명을 먼저 고정한다.
   - 후보가 `rule_detail_metadata.py`, `rule_display_metadata.py`, `rule_metadata_api.py`로 분산될 수 있다.
   - 구현 전 하나의 모듈명과 public API를 정해야 한다.

2. `phase1_case_builder`의 기존 hard-coded label/action map을 한 번에 제거하지 않는다.
   - 먼저 metadata accessor를 추가하고, 기존 map은 fallback으로 둔 뒤 단계적으로 치환한다.

3. `RawRuleHitRef` 모델 변경은 후순위로 둔다.
   - 1차 구현은 case/export projection 단계에서 `canonical_rule_id`, `presenter_surface`, `status`를 보강하는 방식이 안전하다.

4. `L4-02` macro context 흐름을 명확히 한다.
   - LOCK은 `L4-02/Benford`가 macro/context 성격이라고 보지만, case builder의 macro context 연결은 주로 `D01/D02/GR01/GR03` 중심이다.
   - `L4-02`를 account/process queue에만 둘지, transaction case의 macro context에도 붙일지 결정해야 한다.

5. legacy artifact 대응을 추가한다.
   - 과거 저장 데이터에 `scoring_role`이 없거나 잘못 들어간 경우에도 metadata가 최종 표시 표면을 교정해야 한다.

## 4. 충돌표

| rule_id | source_a | source_b | source_c | source_d | conflict_type | resolution |
|---|---|---|---|---|---|---|
| GLOBAL_COUNT | 32 canonical L1~L4 + `Benford` alias. `D/IC/GR` 제외 | 같은 방향 | surface별 컬럼 분리 | count flag 제안 | 구현/대시보드 count 충돌 | transaction count는 32로 고정하고 legacy "33"은 별도 display alias 설명으로만 유지 |
| SOURCE_A_FILE | A 파일에 이전 E 초안이 함께 존재 | 독립 문서 | 독립 문서 | 독립 문서 | source hygiene | A 원본 영역과 E 산출물을 분리하고, 구현 입력은 A 정의표 부분만 사용 |
| L2-03a~d | `L2-03` internal reason code | drilldown 문구 | drilldown reason 컬럼 | row detail 금지 | scoring registry와 표시 정책 충돌 | canonical은 `L2-03`, status는 `internal_reason_code`, count/export row detail 제외 |
| Benford | `L4-02` alias | alias/macro 문구 | account/process macro | alias validation | 별도 룰처럼 표시될 위험 | canonical 집계는 `L4-02`, requested id만 audit용으로 보존 |
| L4-02 | macro/account-process | macro review signal | macro columns | row detail false | dashboard/export에서 위반 copy 가능 | account/process macro surface만 허용, transaction detail 금지 |
| D01/D02 | macro, count 제외 | macro review | account/process macro | macro status | dashboard 33개 룰 포함 | L1~L4 rule count와 분리하고 Analytical Review 영역으로 이동 |
| IC01~IC03 | sidecar, count 제외, topic seed 가능 | sidecar guidance | intercompany sidecar columns | sidecar status | scoring registry상 primary와 혼동 가능 | sidecar topic seed는 허용하되 transaction count/detail 제외 |
| GR01/GR03 | graph sidecar | graph context | graph sidecar columns | sidecar/macro-like | queue map과 macro set 적용 범위 불일치 | graph sidecar 전용 surface로 두고 transaction count/detail 제외 |
| L3-05/L3-06 | booster, standalone false | context-only copy | context badge | standalone copy 금지 | 단독 승인 위반처럼 보일 위험 | primary hit가 있을 때만 context badge로 표시 |
| L3-08 | booster/context, standalone false | context-only copy | `violation_details` 언급 가능 | standalone copy 금지 | context 룰에 violation 필드명 혼입 | `context_details` 또는 `evidence_summary`로 제한 |
| L3-10 | booster/context, standalone false | context-only copy | context badge | standalone copy 금지 | legacy export set에서 명시 누락 가능 | metadata 기반 gating으로 legacy 누락 보정 |
| L4-05 | context 성격, standalone false 필요 | context-only copy | context badge | standalone copy 금지 | 일부 코드에서 primary성 copy 가능 | standalone false 및 context badge 정책 명시 |
| L3-12 | combo-only, standalone false | combo/context copy | context badge | standalone copy 금지 | 접근권한 위반처럼 오해 가능 | L1-06 등 primary와 결합될 때만 보조 근거로 표시 |
| L4-06 | combo/context, standalone false | context-only copy | `upload_batch_id` 등 비스키마 컬럼 | standalone copy 금지 | required column 과잉 | 비스키마 필드는 optional/derived로 하향 |

## 5. 누락표

| rule_id | missing_source | missing_field | required_before_implementation |
|---|---|---|---|
| ALL | D/implementation | 최종 registry module name, public accessor name | Yes |
| ALL | tests | metadata coverage and validation tests | Yes |
| ALL | C | ledger required vs derived vs sidecar output 구분 | Yes |
| L2-03a~d | tests/code contract | canonicalization, count exclusion, row detail exclusion | Yes |
| Benford | tests/code contract | alias no-double-count, macro-only display | Yes |
| L4-02/D01/D02 | export tests | row detail denial, macro queue routing | Yes |
| GR01/GR03 | dashboard/export tests | graph sidecar exclusion from transaction rule count | Yes |
| IC01~IC03 | dashboard/export tests | sidecar count exclusion while topic seed remains possible | Yes |
| L3-10/L4-05 | export tests | legacy hit with missing scoring_role still becomes context badge | Yes |
| L4-06 | C | `upload_batch_id` source/fallback | Yes |
| L1-09 | C | `approved_at` vs actual `approval_date` mapping | Yes |
| D01/D02/L4-02 | C | macro grouping keys such as company/account/period | Yes |

## 6. 구현 리스크

| code area | risk | mitigation |
|---|---|---|
| `dashboard/tab_phase1.py` | 33개 룰 count와 `D01/D02` 포함 정책이 A와 충돌 | metadata count accessor를 먼저 만들고 dashboard count/selector를 그 accessor로 교체 |
| `dashboard/tab_phase1.py` | `L4-02` copy가 macro 신호를 단정적 위반처럼 표현 | B 문구를 우선 적용하고 forbidden terms validator 추가 |
| `src/export/phase1_case_view.py` | macro/sidecar/reason code가 rule document detail로 export될 수 있음 | `allow_row_violation_detail`과 `presenter_surface`를 export 진입점에서 검사 |
| `src/detection/rule_scoring.py` | `L2-03a~d`가 registry entry로 있어 독립 룰처럼 보일 수 있음 | scoring registry는 유지하되 metadata canonicalizer가 표시/count를 교정 |
| `src/detection/topic_scoring.py` | `IC01~IC03`가 primary topic seed로 동작해 transaction primary와 섞일 수 있음 | topic seed 허용과 L1~L4 count/export 제외를 별도 flag로 분리 |
| `src/detection/phase1_case_builder.py` | hard-coded label/action map과 metadata copy가 충돌할 수 있음 | metadata accessor를 우선 사용하고 기존 map은 fallback으로 단계적 제거 |
| `src/models/phase1_case.py` | raw hit model에 canonical/surface/status 필드가 없음 | 모델 변경 전 projection 단계에서 metadata-enriched view를 생성 |
| tests | 기존 export coverage test가 macro/sidecar/reason builder 포함을 기대할 수 있음 | row-detail coverage와 macro/sidecar/reason coverage를 별도 테스트로 분리 |

## 7. 테스트 보강안

1. **metadata registry coverage**
   - A/B/C/D의 모든 `rule_id`가 registry에 존재하는지 검증한다.
   - `canonical_rule_id`, `status`, `presenter_surface`, `standalone_rankable`, `include_in_l1_l4_transaction_count`가 누락되지 않아야 한다.

2. **canonicalization**
   - `L2-03a~d -> L2-03`.
   - `Benford -> L4-02`.
   - alias/internal reason code가 count를 증가시키지 않는지 검증한다.

3. **surface gating**
   - `transaction_detail`만 row violation detail을 생성할 수 있다.
   - `context_badge`, `account_process_macro`, `intercompany_sidecar`, `graph_sidecar`, `drilldown_reason`은 row violation detail을 만들 수 없다.

4. **standalone false seed 방지**
   - `L3-05`, `L3-06`, `L3-08`, `L3-10`, `L3-12`, `L4-06`, `L4-02/Benford`, `D01/D02`, `GR01/GR03`만 있는 입력은 case seed 또는 Top-N seed가 되지 않아야 한다.

5. **sidecar 분리**
   - `IC01~IC03`는 intercompany topic seed에는 사용할 수 있지만 L1~L4 transaction rule count와 row detail에는 포함되지 않아야 한다.

6. **copy guard**
   - macro/context/alias/reason copy에는 "위반", "부정", "조작", "통제 실패 확정" 같은 단정 표현이 들어가면 실패한다.
   - 단, direct primary control 룰의 사용자 문구에는 제한적으로 허용한다.

7. **column source validation**
   - ledger required column은 `config/schema.yaml` 및 실제 case/export 입력에서 확인 가능한 컬럼만 허용한다.
   - derived/sidecar/macro output 컬럼은 ledger required로 선언되면 실패한다.

8. **legacy artifact 대응**
   - 저장된 hit에 `scoring_role`이 없거나 잘못 들어간 경우에도 metadata가 `L3-10`, `L4-05`, `L4-02`, `D01/D02`, `IC01~IC03`의 surface를 올바르게 교정하는지 검증한다.

## 8. 구현 착수 순서

1. A/B/C/D 산출물의 source hygiene를 정리하고, 최종 count/naming/API 정책을 문서에 고정한다.
2. metadata validation 테스트를 먼저 추가한다.
3. `RuleDetailMetadata` 최소 schema와 enum을 추가한다.
4. A의 rule identity/policy 필드를 registry 초안으로 적재한다.
5. `canonical_rule_id`, alias, internal reason code, count exclusion validation을 구현한다.
6. B의 display copy를 추가하고 forbidden-copy validation을 붙인다.
7. C의 column metadata를 `required_ledger`, `optional_ledger`, `derived`, `sidecar_output`으로 나눠 추가한다.
8. export 진입점에 `presenter_surface`와 `allow_row_violation_detail` gating을 적용한다.
9. dashboard의 rule count, selector, label, detail copy를 metadata accessor 기반으로 교체한다.
10. case builder의 label/action/finding scope를 metadata accessor로 단계적으로 교체한다.
11. macro/sidecar/account-process queue 표시를 transaction detail과 분리한다.
12. targeted test suite를 실행하고 기존 충돌 테스트를 새 정책 기준으로 갱신한다.

