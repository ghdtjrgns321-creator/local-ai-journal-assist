# Context A Rule Definition Table

목적: `DETECTION_RULES.md` 기준의 사용자 표시용 rule definition 원천 표.

정리 기준:

- UTF-8 정상 한글로 작성했다.
- `PHASE1_TOPIC_SCORING_V1_LOCK.md`와 충돌하는 표시 topic, scoring role, standalone 정책은 lock 문서를 우선했다.
- `L2-03a~d`는 별도 사용자 룰이 아니라 `L2-03`의 내부 reason code다.
- `Benford`는 `L4-02` alias다.
- `IC01~IC03`은 관계사 sidecar finding이다.
- `D01/D02`는 macro finding이다.
- `GR01/GR03`은 graph sidecar이며 v1 transaction detail 필수 범위 밖이다.
- `L3-05/L3-06/L3-08/L3-10/L3-12/L4-06`은 단독 위반처럼 표현하지 않는다.
- `L4-02/Benford` 표시 topic 정책: canonical은 `L4-02`, 사용자 표시는 Account/Process macro finding이며 `원장기록·데이터정합성`을 final topic, `수익·금액·모집단 통계 이상`을 secondary topic으로 둔다. Transaction row ranking은 만들지 않는다. B 컨텍스트 설명에서는 "모집단/계정 단위 분포 품질 검토"로 표현해 통계 탭 단독 룰처럼 오해하지 않게 한다.

## Presenter Surface Enum

`presenter_surface`는 구현 입력용 enum이며 아래 값만 허용한다.

| value | 의미 |
|---|---|
| `transaction_detail` | L1~L4 transaction detail에서 직접 표시 가능한 canonical rule |
| `context_badge` | 단독 위반이 아니라 다른 rule/case를 보강하는 badge/context |
| `account_process_macro` | 계정·월·모집단 단위 macro finding |
| `intercompany_sidecar` | 관계사 대사/금액/시차 sidecar finding |
| `graph_sidecar` | 그래프/연결 구조 sidecar finding |
| `drilldown_reason` | canonical rule 내부 reason code |

## Status Validation

status별 검증 기준은 분리한다.

| status | 포함 대상 | canonical_rule_id | scoring_role 요구 | standalone_rankable 의미 | 사용자 룰 수 포함 |
|---|---|---|---|---|---|
| `active` | L1~L4 canonical transaction rule | 자기 자신 | 필수 | transaction topic seed 가능 여부 | 포함 |
| `macro` | L4-02, D01, D02 같은 Account/Process finding | 자기 자신 | 필수, 보통 `macro_only` | transaction standalone ranking 금지 | L1~L4 canonical이면 포함, D01/D02는 제외 |
| `sidecar` | IC01~IC03, GR01/GR03 | 자기 자신 | 필수 | sidecar topic seed 가능 여부. IC01~IC03은 L1~L4 transaction rule 수에는 미포함이지만 관계사 topic seed 가능 | 제외 |
| `alias` | Benford처럼 canonical rule의 표시 alias | canonical rule 참조 | canonical에서 상속 가능 | canonical 정책을 따른다 | 제외 |
| `internal_reason_code` | L2-03a~d 같은 내부 reason code | canonical rule 참조 | canonical에서 상속 가능 | 단독 사용자 rule seed 아님 | 제외 |

## Count Policy

- L1~L4 canonical transaction rule count: 32개. `L1-01~L4-06` canonical rows 기준이며 `L3-12`를 포함하고 `L2-03a~d`는 제외한다.
- User-facing canonical rule count for Phase 1 transaction detail: 32개. `Benford` alias, `IC01~IC03`, `D01/D02`, `GR01/GR03`은 제외한다.
- "33개 룰" 표현이 legacy/display 문맥에서 나오면 `32개 canonical L1~L4 + Benford 표시 alias`로만 해석한다. 이 경우에도 `Benford`는 `L4-02` alias이므로 canonical coverage/test count에는 추가하지 않는다.
- Account/Process macro finding: `L4-02`, `D01`, `D02`. 단, `L4-02`는 32개 canonical L1~L4 count에는 포함된다.
- Sidecar finding: `IC01~IC03`, `GR01/GR03`.
- Alias/internal reason code는 사용자 룰 수와 coverage count에 포함하지 않는다.

| rule_id | canonical_rule_id | status | rule_name | detection_purpose | evidence_type | final_topic | secondary_topics | scoring_role | standalone_rankable | presenter_surface | source_sections | conflict_note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| L1-01 | L1-01 | active | 차대변 균형 | 차변/대변 불균형으로 원장 구조 오류와 입력 통제 실패 후보를 탐지 | data_integrity_failure | 원장기록·데이터정합성 | - | primary | Yes | transaction_detail | DETECTION_RULES §2.0.3, §L1-01; LOCK Topic Policy | - |
| L1-02 | L1-02 | active | 필수필드 누락 | 핵심 필드 누락으로 감사추적·분석 가능성이 저해되는 전표를 탐지 | data_integrity_failure | 원장기록·데이터정합성 | - | primary | Yes | transaction_detail | DETECTION_RULES §L1-02; LOCK Topic Policy | - |
| L1-03 | L1-03 | active | 무효 계정 | CoA 밖 계정, 비정상 형식, 예약/placeholder 계정 등 계정 유효성 오류를 탐지 | logic_mismatch | 계정분류·거래실질 불일치 | - | primary | Yes | transaction_detail | DETECTION_RULES §L1-03; LOCK Topic Policy | - |
| L1-04 | L1-04 | active | 승인한도 초과 | 승인자 권한 한도 초과 또는 비승인권자 승인으로 승인 체계 미작동을 탐지 | control_failure | 승인·권한·업무분장 통제 | - | primary | Yes | transaction_detail | DETECTION_RULES §L1-04; LOCK Topic Policy | - |
| L1-05 | L1-05 | active | 자기 승인 | 작성자와 승인자가 동일한 자기승인 및 업무분장 통제 위반을 탐지 | control_failure | 승인·권한·업무분장 통제 | 중복·상계·자금유출 | primary | Yes | transaction_detail | DETECTION_RULES §L1-05; LOCK Topic Policy | - |
| L1-06 | L1-06 | active | 직무분리 위반 | 직접 확인 가능한 SoD conflict를 확정 통제 위반 신호로 탐지 | control_failure | 승인·권한·업무분장 통제 | - | primary | Yes | transaction_detail | DETECTION_RULES §L1-06; LOCK Topic Policy | L3-12 업무범위 집중과 분리 |
| L1-07 | L1-07 | active | 승인 생략 | 승인 절차 없이 처리된 전표, 특히 한도 초과 또는 수기 전표의 승인 생략을 탐지 | control_failure | 승인·권한·업무분장 통제 | 중복·상계·자금유출 | primary | Yes | transaction_detail | DETECTION_RULES §L1-07; LOCK Topic Policy | - |
| L1-08 | L1-08 | active | 기간 불일치 | 회계연도/기간과 전기일 불일치로 cutoff·기간귀속 오류 후보를 탐지 | data_integrity_failure | 결산·기간귀속·입력시점 | 원장기록·데이터정합성 | primary | Yes | transaction_detail | DETECTION_RULES §2.0.3, §L1-08; LOCK Locked Corrections/Topic Policy | DETECTION_RULES/RELATIONSHIP는 원장 정합성 primary로 설명하나 LOCK은 v1 final_topic을 결산·기간귀속으로 고정 |
| L1-09 | L1-09 | active | 승인일 누락 | 승인자는 있으나 승인일이 없어 승인 추적성이 훼손된 전표를 탐지 | control_failure | 승인·권한·업무분장 통제 | - | primary | Yes | transaction_detail | DETECTION_RULES §L1-09; LOCK Topic Policy | - |
| L2-01 | L2-01 | active | 승인한도 직하 | 승인한도 바로 아래 금액 반복·분할로 승인 우회 또는 자금유출 은폐 가능성을 탐지 | duplicate_or_outflow | 중복·상계·자금유출 | 승인·권한·업무분장 통제 | primary | Yes | transaction_detail | DETECTION_RULES §L2-01; LOCK Locked Corrections/Topic Policy | 승인통제 성격이 강하지만 LOCK은 final_topic을 중복·상계·자금유출로 고정 |
| L2-02 | L2-02 | active | 중복 지급 | 동일 거래처·금액·참조정보 기반 이중 지급 후보를 탐지 | duplicate_or_outflow | 중복·상계·자금유출 | - | primary | Yes | transaction_detail | DETECTION_RULES §L2-02; LOCK Topic Policy | - |
| L2-03 | L2-03 | active | 중복 전표 | 정확·유사·분할·시차 중복 전표 후보를 사용자 표시상 하나의 중복 전표 룰로 탐지 | duplicate_or_outflow | 중복·상계·자금유출 | - | primary | Yes | transaction_detail | DETECTION_RULES §2.0.3, §L2-03; LOCK Topic Policy | L2-03a~d는 내부 reason code로만 표시 |
| L2-03a | L2-03 | internal_reason_code | 정확 중복 | L2-03 내부의 exact duplicate reason code | duplicate_or_outflow | 중복·상계·자금유출 | - | primary | No | drilldown_reason | DETECTION_RULES §2.0.3, §L2-03; RELATIONSHIP §4.2 | 외부 rule_id는 L2-03으로 통합 |
| L2-03b | L2-03 | internal_reason_code | 유사 중복 | L2-03 내부의 fuzzy/similar duplicate reason code | duplicate_or_outflow | 중복·상계·자금유출 | - | primary | No | drilldown_reason | DETECTION_RULES §2.0.3, §L2-03; RELATIONSHIP §4.2 | 외부 rule_id는 L2-03으로 통합 |
| L2-03c | L2-03 | internal_reason_code | 분할 후보 | L2-03 내부의 split candidate reason code | duplicate_or_outflow | 중복·상계·자금유출 | - | primary | No | drilldown_reason | DETECTION_RULES §2.0.3, §L2-03; RELATIONSHIP §4.2 | 외부 rule_id는 L2-03으로 통합 |
| L2-03d | L2-03 | internal_reason_code | 시차 중복 | L2-03 내부의 delayed duplicate reason code | duplicate_or_outflow | 중복·상계·자금유출 | - | primary | No | drilldown_reason | DETECTION_RULES §2.0.3, §L2-03; RELATIONSHIP §4.2 | 외부 rule_id는 L2-03으로 통합 |
| L2-04 | L2-04 | active | 비용 자산화 | 비용/자산 계정 조합의 거래 실질 불일치 및 자산화 검토 후보를 탐지 | logic_mismatch | 계정분류·거래실질 불일치 | - | primary | Yes | transaction_detail | DETECTION_RULES §2.0.3, §L2-04; LOCK Topic Policy | L2 계층이지만 사용자 topic/evidence는 logic_mismatch |
| L2-05 | L2-05 | active | 역분개 패턴 | 역분개·상계·반제·되돌림 패턴으로 은폐 또는 정리 후보를 탐지 | duplicate_or_outflow | 중복·상계·자금유출 | - | primary | Yes | transaction_detail | DETECTION_RULES §L2-05; LOCK Topic Policy | - |
| L3-01 | L3-01 | active | 계정 분류 불일치 | 업무 프로세스와 계정 분류가 맞지 않는 전표 모집단을 탐지 | logic_mismatch | 계정분류·거래실질 불일치 | - | primary | Yes | transaction_detail | DETECTION_RULES §L3-01; RELATIONSHIP §4.1; LOCK Topic Policy | - |
| L3-02 | L3-02 | active | 수기 전표 | 자동 프로세스 밖 수기/조정 전표 모집단을 탐지 | control_failure | 승인·권한·업무분장 통제 | - | primary | Yes | transaction_detail | DETECTION_RULES §L3-02; LOCK Topic Policy | - |
| L3-03 | L3-03 | active | 관계사 거래 검토 신호 | 관계사·내부거래 모집단과 순환거래 후보의 seed를 탐지 | intercompany_structure | 관계사·내부거래·순환구조 | 계정분류·거래실질 불일치 | booster | No | context_badge | DETECTION_RULES §L3-03; LOCK Topic Policy | 단독 위반처럼 표현 금지 |
| L3-04 | L3-04 | active | 기말/기초 결산 검토 후보군 | 보고기간 말·기초 결산 조정성 전표를 탐지 | timing_anomaly | 결산·기간귀속·입력시점 | - | primary | Yes | transaction_detail | DETECTION_RULES §L3-04; LOCK Topic Policy | - |
| L3-05 | L3-05 | active | 주말/공휴일 전기 | 비영업일 전기 활동을 탐지 | timing_anomaly | 결산·기간귀속·입력시점 | 승인·권한·업무분장 통제 | booster | No | context_badge | DETECTION_RULES §L3-05; LOCK Locked Corrections/Topic Policy | 단독 위반처럼 표현 금지; v1 standalone queue 금지 |
| L3-06 | L3-06 | active | 심야 전기 | 심야 시간대 입력 활동을 탐지 | timing_anomaly | 결산·기간귀속·입력시점 | 승인·권한·업무분장 통제 | booster | No | context_badge | DETECTION_RULES §L3-06; LOCK Locked Corrections/Topic Policy | 단독 위반처럼 표현 금지; v1 standalone queue 금지 |
| L3-07 | L3-07 | active | 전기일-문서일 장기 괴리 | 전표일과 전기일 사이 과도한 괴리를 탐지 | timing_anomaly | 결산·기간귀속·입력시점 | - | primary | Yes | transaction_detail | DETECTION_RULES §L3-07; LOCK Topic Policy | - |
| L3-08 | L3-08 | active | 적요 결손/파손 신호 | 적요 누락·깨짐으로 설명 추적성이 약한 전표를 탐지 | timing_anomaly | 원장기록·데이터정합성 | 결산·기간귀속·입력시점 | booster | No | context_badge | DETECTION_RULES §2.0.3, §L3-08; LOCK Topic Policy | DETECTION_RULES는 timing_anomaly theme로 설명하나 LOCK은 final_topic을 원장기록으로 고정; 단독 위반처럼 표현 금지 |
| L3-09 | L3-09 | active | 가수금 장기체류 | 가수금·미정리 계정 장기 체류 또는 정산 불일치 후보를 탐지 | logic_mismatch | 계정분류·거래실질 불일치 | - | primary | Yes | transaction_detail | DETECTION_RULES §L3-09; LOCK Topic Policy | - |
| L3-10 | L3-10 | active | 고위험 계정 사용 | 민감·고위험 계정 접촉 후보를 탐지 | logic_mismatch | 계정분류·거래실질 불일치 | 승인·권한·업무분장 통제; 수익·금액·모집단 통계 이상 | booster | No | context_badge | DETECTION_RULES §L3-10; LOCK Topic Policy | 단독 위반처럼 표현 금지 |
| L3-11 | L3-11 | active | 매출 컷오프 불일치 | 매출 인식 시점과 기간귀속 불일치 후보를 탐지 | timing_anomaly | 결산·기간귀속·입력시점 | - | primary | Yes | transaction_detail | DETECTION_RULES §L3-11; LOCK Topic Policy | - |
| L3-12 | L3-12 | active | 업무범위 집중 검토 | 한 사용자의 과도한 업무범위 집중을 review-only 신호로 탐지 | access_scope_review | 승인·권한·업무분장 통제 | 중복·상계·자금유출 | combo_only | No | context_badge | DETECTION_RULES §L3-12; RELATIONSHIP §7.2; LOCK Topic Policy | L1-06 direct SoD와 분리; 확정 위반 아님; 단독 위반처럼 표현 금지 |
| L4-01 | L4-01 | active | 매출 이상 변동 | 매출 계정의 비정상 변동과 매출 조작 후보를 탐지 | statistical_outlier | 수익·금액·모집단 통계 이상 | - | primary | Yes | transaction_detail | DETECTION_RULES §L4-01; LOCK Topic Policy | - |
| L4-02 | L4-02 | macro | Benford 위반 | 계정/모집단의 첫째 자리 분포 이상을 모집단/계정 단위 분포 품질 검토로 탐지 | statistical_outlier | 원장기록·데이터정합성 | 수익·금액·모집단 통계 이상 | macro_only | No | account_process_macro | DETECTION_RULES §L4-02; LOCK macro_only/Topic Policy | Transaction ranking에서는 row score 0; 표시 topic은 원장기록 primary, 수익·금액 secondary로 확정 |
| Benford | L4-02 | alias | Benford 독립 트랙 | `L4-02`와 같은 Benford 분포 finding의 표시 alias | statistical_outlier | 원장기록·데이터정합성 | 수익·금액·모집단 통계 이상 | macro_only | No | account_process_macro | DETECTION_RULES §1.2, §L4-02; LOCK macro_only | canonical_rule_id는 L4-02 |
| L4-03 | L4-03 | active | 이상 고액 | 모집단 대비 고액 또는 z-score 이상 금액 후보를 탐지 | statistical_outlier | 수익·금액·모집단 통계 이상 | - | primary | Yes | transaction_detail | DETECTION_RULES §L4-03; LOCK Topic Policy | 단독으로 부정 결론은 내리지 않지만 topic seed 가능 |
| L4-04 | L4-04 | active | 희소 차대 계정쌍 | 드문 차변-대변 계정 조합으로 거래 실질 불일치 후보를 탐지 | logic_mismatch | 계정분류·거래실질 불일치 | 관계사·내부거래·순환구조 | primary | Yes | transaction_detail | DETECTION_RULES §L4-04; LOCK Topic Policy | - |
| L4-05 | L4-05 | active | 비정상 시간대 집중 | 특정 사용자/시간대의 야간·비근무일 입력 집중을 탐지 | timing_anomaly | 결산·기간귀속·입력시점 | 승인·권한·업무분장 통제 | booster | No | context_badge | DETECTION_RULES §L4-05; RELATIONSHIP §4.1; LOCK Topic Policy | 통계 산출 룰이나 감사 해석은 timing_anomaly; 단독 위반처럼 표현 금지 |
| L4-06 | L4-06 | active | 배치성 자동 전표 검토 신호 | 자동/배치 전표 이상 모집단과 독립 보강 신호 결합을 탐지 | statistical_outlier | 수익·금액·모집단 통계 이상 | - | combo_only | No | context_badge | DETECTION_RULES §L4-06; LOCK Topic Policy | 단독 위반처럼 표현 금지; combo-only |
| IC01 | IC01 | sidecar | 고확신 미대사 예외 후보 | 관계사 상대방 코드가 실제 회사코드와 대사되지 않는 예외를 탐지 | intercompany_structure | 관계사·내부거래·순환구조 | - | primary | Yes | intercompany_sidecar | DETECTION_RULES §L3-03 IC 계약; LOCK Topic Policy | L1~L4 transaction rule 수에는 미포함이지만 관계사 topic seed는 가능 |
| IC02 | IC02 | sidecar | 금액 불일치 검토 후보 | 관계사 거래 쌍의 금액 차이를 탐지 | intercompany_structure | 관계사·내부거래·순환구조 | - | primary | Yes | intercompany_sidecar | DETECTION_RULES §L3-03 IC 계약; LOCK Topic Policy | L1~L4 transaction rule 수에는 미포함이지만 관계사 topic seed는 가능 |
| IC03 | IC03 | sidecar | 시차 불일치 검토 후보 | 관계사 거래 쌍의 전기일 또는 기간 차이를 탐지 | intercompany_structure | 관계사·내부거래·순환구조 | - | primary | Yes | intercompany_sidecar | DETECTION_RULES §L3-03 IC 계약; LOCK Topic Policy | L1~L4 transaction rule 수에는 미포함이지만 관계사 topic seed는 가능 |
| D01 | D01 | macro | 계정과목 거래 활동량 급변 | 전기 대비 계정 활동량 급변 계정 검토 큐를 생성 | macro_finding | 계정분류·거래실질 불일치 | 관계사·내부거래·순환구조; 수익·금액·모집단 통계 이상 | macro_only | No | account_process_macro | DETECTION_RULES §2.5, §D01; LOCK macro_only/Topic Policy | Transaction standalone 제외 |
| D02 | D02 | macro | 월별 분포 패턴 변화 | 전기 대비 월별 계정 분포·계절성 변화 계정/월 검토 큐를 생성 | macro_finding | 결산·기간귀속·입력시점 | 관계사·내부거래·순환구조; 수익·금액·모집단 통계 이상 | macro_only | No | account_process_macro | DETECTION_RULES §2.5, §D02; LOCK macro_only/Topic Policy | Transaction standalone 제외 |
| GR01 | GR01 | sidecar | 순환 구조 그래프 신호 | N-hop 관계사 순환 구조 또는 round-trip 거래 후보를 graph sidecar로 탐지 | intercompany_structure | 관계사·내부거래·순환구조 | - | macro_only | No | graph_sidecar | DETECTION_RULES §L3-03/Phase 3 graph; RELATIONSHIP §7.7; LOCK Topic Policy | v1 transaction detail 필수 범위 밖 |
| GR03 | GR03 | sidecar | 그룹 관계 비대칭 그래프 신호 | 관계사 가격·흐름 비대칭 등 그래프 기반 구조 이상 후보를 sidecar로 탐지 | intercompany_structure | 관계사·내부거래·순환구조 | - | macro_only | No | graph_sidecar | DETECTION_RULES §L3-03/Phase 3 graph; RELATIONSHIP §7.7; LOCK Topic Policy | v1 transaction detail 필수 범위 밖 |
