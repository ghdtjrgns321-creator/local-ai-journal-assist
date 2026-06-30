# DataSynth A-to-Z 이력

이 문서는 새 에이전트가 `docs/datasynth`만 읽고 DataSynth가 어디서 시작됐고, 어떤 문제가 있었고, 어떤 이유로 현재 NORMAL/PHASE1/PHASE2 계층으로 재구축됐는지 이해하기 위한 계보 문서다.

## 1. 채택 배경

프로젝트는 감사 전표 전수 분석을 검증할 합성 원장이 필요했다.
단순 샘플 CSV나 공개 회계 예제는 다음 조건을 만족하지 못했다.

- 계정, 전표, 거래처, 사용자, 승인, 증빙, 문서 흐름이 함께 있어야 한다.
- 정상과 위반/부정이 같은 모집단 안에 섞여야 한다.
- detector별 raw trigger와 ML shortcut을 동시에 검증할 수 있어야 한다.
- truth label은 존재하되, journal/master surface에는 정답이 새지 않아야 한다.
- 수십만 행 규모에서 full-population rule, graph, flow, ML surface를 실행할 수 있어야 한다.

이 조건 때문에 EY-ASU DataSynth 계열 Rust generator를 프로젝트 내부 `tools/datasynth/`에 두고, 프로젝트 요구에 맞는 materialized profile을 확장하는 방향을 택했다.

## 2. 초기 lineage: contract와 manipulation

초기에는 contract/manipulation 계열이 중심이었다.

| 계열 | 목적 | 현재 판단 |
| --- | --- | --- |
| `contract-v3` / v126 freeze | 과거 PHASE1 contract truth/sidecar 고정 | historical reference |
| `manipulation-v3~v7/fixed` | 다양한 조작 시나리오와 PHASE2 family 실험 | anti-fitting 교훈 source |
| `semanticfix*` | family shortcut 제거와 일부 realism 개선 | 현행 semantic rebuild 이전 중간 단계 |

이 계열에서 얻은 주요 교훈은 다음과 같다.

- 정답 token, scenario token, `mutation_*` 문구가 journal/master에 남으면 detector/ML이 구조가 아니라 답을 읽는다.
- 정상 모집단이 너무 깨끗하면 부정 overlay가 쉽게 들킨다.
- 정상 IC, 정상 duplicate-shaped control, 정상 reversal, 정상 신규계정 활동 같은 배경이 없으면 overlay surface 자체가 shortcut이 된다.
- reference만 바꾸는 패치는 IC/duplicate 구조를 고치지 못한다. document 단위 계정 배치와 flow membership을 고쳐야 한다.
- 특정 값, 특정 날짜, 특정 GL, 특정 amount bucket이 truth에만 몰리면 token이 아니어도 shortcut이다.

이후 덧대기 패치로는 정상과 부정이 모두 애매해진다는 판단에 따라 semantic NORMAL rebuild로 전환했다.

## 3. Semantic NORMAL rebuild

목표는 fraud/anomaly 없이 정상 원장부터 다시 만드는 것이었다.
정상 원장이 깨지면 PHASE1/PHASE2 모두 합성 artifact를 학습하기 때문이다.

### 3.1 주요 설계 원칙

- 정상 전표는 차대변 균형, 기간 정합, CoA/master 참조 무결성을 가져야 한다.
- 계정 subtype, business process, counterparty type, document type, line text family는 독립 샘플링하지 않고 transaction archetype에서 함께 뽑아야 한다.
- 자연 noise는 존재해야 하지만, 회계 실체를 깨면 안 된다.
- 재무제표 수준에서는 TB↔JE, BS equation, roll-forward, annual closing, subledger reconciliation이 맞아야 한다.
- 정상에도 batch, reversal, recurring, duplicate-shaped controls, IC trace, PHASE2 악용 가능 계정의 정상 활동이 있어야 한다.

### 3.2 v21~v25: 재무제표 정합

초기 NORMAL은 전표 단위 균형은 맞았지만 재무제표 정합이 비어 있었다.

주요 문제:

- TB가 JE에서 파생되지 않는 hollow pass.
- opening balance와 carry-forward가 dummy에 가까움.
- monthly BS equation이 당기손익을 자본에 포함하지 않아 매월 깨짐.
- subledger reconciliation이 실측 없이 0으로 기록됨.
- float 누적오차로 A01/M01/M05 잔차 발생.

수정:

- KRW는 원 단위 정수로 누적한다.
- 월말 등식은 `assets = liabilities + equity + current_ytd_income`으로 본다.
- annual closing entry는 P&L을 닫고 retained earnings residual을 정확히 흡수한다.
- subledger는 GL control-account line에서 거래처/auxiliary 단위로 파생한다.

결과:

- A01/M01/M02/M03/M04/M05/M07 hard gate가 닫혔다.

### 3.3 v26~v29: reference, reversal, SoD 오염 제거

주요 문제:

- 정상 reference/document_number 재사용이 duplicate detector에 가짜 same-reference pair를 만들었다.
- 정상 reversal에 original document link가 없어 weak rolling-zero-out 경로로만 잡혔다.
- 정상에 `sod_violation=true` direct marker가 들어가 L1-06 confirmed finding이 6천 건 이상 발생했다.

수정:

- document_number는 전표별 고유, company/year/document_type 증가 체계로 정리했다.
- reference는 무관 전표끼리 재사용하지 않고 invoice→payment 같은 정당한 flow link에만 공유한다.
- 정상 reversal pair는 `original_document_id`/`reversal_document_id`를 가진다.
- NORMAL에서는 direct SoD marker를 제거한다. 정상 role 겸직은 context일 수 있지만 confirmed violation marker는 아니다.

### 3.4 v30~v31: PHASE2 악용 가능 계정 정상화

PHASE2 fraud scheme이 무형자산, 대여금, 대손충당금, 충당부채, 투자, 손상, 공사계약 계정을 사용하려면 이 계정들이 NORMAL에도 존재해야 했다.

v30f는 회계 정합은 맞았지만 rejected였다.

문제:

- 신규 계정이 회사×연도×월 셀마다 정확히 같은 건수로 생성됐다.
- 각 계정이 전용 scenario에 격리됐다.
- counterparty가 단일값 100%에 가까웠다.
- 금액이 좁은 선형 범위였다.

v31은 신규 계정을 기존 P2P/H2R/IC/TREASURY/MFG/R2R 흐름에 섞고, 빈 셀·heavy-tail 금액·거래처 분산을 넣었다.

### 3.5 v42~v43d: 도메인 감사와 full-column leak

도메인 감사에서 다음 문제가 닫혔다.

- taxable 10% VAT 오류.
- KRW 환율 marker.
- cost center master 불일치.
- 연도 clone marker와 timestamp 집중.
- PHASE2 deny-list를 통과한 synthetic marker 컬럼.
- `original_document_id` non-null이 PHASE2 overlay-only surface가 되는 L6 leak.

v43d는 linked normal reversal background를 추가해 PHASE2 reversal link가 부정 전용 표면이 되지 않게 했다.

### 3.6 v45~v46b: 단일법인 전환과 관계사 trace 복구

프로젝트 범위가 단일법인 C001 GL-only로 정리되면서 여러 회사의 원장을 한 journal에 섞지 않게 했다.
그러나 관계사 거래 흔적까지 제거하면 IC GL 계정과 detector 검증이 빈 모집단이 된다.

v46b 기준:

- `company_code`는 C001 하나.
- C002/C003는 별도 회사 원장이 아니라 C001의 관계사 trading partner.
- 정상 IC rows 432, IC docs 216.
- IC GL trace: 1150=108, 4500=108, 2050=72, 2700=36.
- company-node graph cycle 0.
- NORMAL realism verifier PASS 38 / MONITOR 1 / FAIL 0 / BLOCKED 0.

현재 NORMAL accepted 기준은 v46b다.

## 4. PHASE1-1 recall rebuild

최신 `docs/spec/DETECTION_RULES.md` 기준 PHASE1-1 개별 룰은 26개다.
과거 39룰 기반 r9/r10/r42j_r3는 최신 recall 검증 기준이 아니다.

### 4.1 사전 매트릭스

`dev/active/phase1-rule-basis-audit/phase1-rule-firing-matrix.md`에서 각 룰을 다음 4열로 대조했다.

- 설명 문장.
- detector predicate.
- datasynth standard variant.
- boundary control.

애매한 항목은 datasynth-needs-fix, description-needs-update, implementation-owned 등으로 분류했다.

### 4.2 r11 산출

Dataset:

`datasynth_semantic_v1_recall_20260622_v46b_phase1_1_r11`

Base:

`datasynth_semantic_v1_normal_20260621_v46b`

결과:

- active PHASE1-1 rules 26 / 26.
- truth units 1,500 = standard 750 + boundary 750.
- standard 750 / 750 caught.
- boundary control 0 / 750 caught.
- shortcut scan findings 0.
- CoA coverage PASS.

r11은 개별 룰 발화 전용이다. combo/tier나 PHASE2에 재사용하지 않는다.

## 5. PHASE1 combo/tier rebuild

PHASE1-1 개별 룰 발화가 닫힌 뒤, 별도 combo/tier dataset을 만들었다.
목적은 룰이 켜지는지 자체가 아니라, 켜진 룰 조합이 case 단위 HIGH/MEDIUM/LOW/CONTEXT tier로 조립되는지 확인하는 것이다.

### 5.1 사전 매트릭스

`dev/active/phase1-rule-basis-audit/phase1-combo-tier-firing-matrix.md`가 권위 문서다.

대상:

- buildable combo 13개.
- LOW control 1개.
- CONTEXT booster-only control 1개.
- out-of-scope combo 4개는 truth에 만들지 않는다.

### 5.2 r1i/r1l reject

r1i:

- static gate PASS.
- shortcut scan findings 0.
- actual case-builder gate FAIL: 1 / 15.

원인:

- member rule legs가 같은 observed case에 묶이지 않았다.
- LOW/CONTEXT control이 broad normal flags와 결합해 high로 승격됐다.

r1l:

- static gate PASS.
- shortcut scan findings 0.
- actual case-builder gate FAIL: 7 / 15.

원인:

- flow 기반 `L2-05` companion 노출이 충분하지 않았다.
- MEDIUM/LOW 일부가 unintended HIGH leg와 결합했다.

### 5.3 r1z accept

Dataset:

`datasynth_semantic_v1_combo_tier_20260622_v46b_r1z`

결과:

- truth rows 15.
- static combo/tier gate PASS.
- shortcut scan findings 0.
- actual case-builder gate PASS: 15 / 15.

중요한 수락 기준:

- 최종 case `priority_band` equality만 보지 않는다.
- 같은 case에 unrelated broad signal이 섞이면 final band가 더 높아질 수 있다.
- expected topic의 actual topic score cut 충족 여부가 combo/tier acceptance의 핵심이다.

## 6. PHASE2 fraud overlay

PHASE2는 14개 구조적 fraud scheme을 NORMAL 위에 overlay한다.
목적은 detector recall을 맞추는 것이 아니라 shortcut 없이 실제 부정 메커니즘이 정상 모집단 안에 존재하도록 만드는 것이다.

### 6.1 r1~r3 계열 교훈

주요 문제:

- 자기상쇄 분개: 같은 GL에 차변/대변을 동시에 넣어 경제 실질 0.
- `delivery_date`가 overlay에만 채워져 부정 전용 표면.
- component role을 카탈로그에 없는 이름으로 발명.
- `unrecognized_amount_krw`가 FS10/FS12/FS13에서 동일 상수로 복사.

수정:

- 역분개/반품은 별도 document와 reversal/original link로 표현한다.
- O2C 정상 base에 delivery date를 전파한다.
- component role은 scheme catalog 문자열과 1:1로 맞춘다.
- 부작위 미인식 금액은 instance 작위 금액에서 파생한다.

### 6.2 r4 계열 shortcut cleanup

주요 문제:

- reference/document_number/document_id 범위가 truth 전용.
- batch/job/reversal metadata가 truth 전용.
- approval/user/counterparty/source 조합이 정상에 없는 셀을 만들었다.
- 소액 부정이 없어 금액 자릿수로 분리됐다.
- shortcut을 없애려다 scheme과 무관한 대여금/계약자산을 여러 scheme에 끼워 넣었다.
- same-side split으로 같은 계정을 같은 방향에 여러 줄로 쪼개 라인 수를 맞췄다.
- seed rotation이 document id나 assignment만 바꾸고 실제 fraud content를 바꾸지 않았다.

수정:

- normal donor inheritance: 부수 metadata 묶음은 정상 문서에서 통째 상속한다.
- scheme-account whitelist: 각 scheme에 회계적으로 맞는 계정만 허용한다.
- same-side split 금지: 자연스러운 2라인 분개는 그대로 둔다.
- 소액은 FS03 점증 횡령, FS04 소액 비용화, FS14 급여 등 실제 메커니즘에서만 나온다.
- full-column leak scan을 representative와 최소 seed1에 실행한다.

### 6.3 r4m_h accept

Accepted PHASE2 fraud overlay:

`datasynth_semantic_v1_phase2_fraud_20260614_v1_r4m_h`

Seed:

`datasynth_semantic_v1_phase2_fraud_20260614_v1_r4m_h_seed1`

통과 기준:

- shortcut gate 17/17 PASS.
- regression: base unchanged 0, label consistency 0/0/0, 14 schemes, self-cancel 0, fraud imbalance 0.
- surface shortcut scan findings 0.
- full-column leak scan NEW leak candidates 0.
- seed1도 동일 검증 PASS.

현재 gap:

- r4m_h는 v46b NORMAL 위에서 재생성된 산출물은 아니다.
- 다음 PHASE2 작업은 v46b base 위에서 r4m_h 검증 세트를 유지한 채 재동기화해야 한다.

## 7. 현재 문서 체계

`docs/datasynth`는 다음 역할로 나뉜다.

| 문서 | 역할 |
| --- | --- |
| `README.md` | current 기준 인덱스 |
| `generation-principles.md` | 생성 원칙과 anti-fitting 정책 |
| `generation-flow.md` | Rust profile, 생성 흐름, 명령 패턴 |
| `scenario-and-datasets.md` | NORMAL/PHASE1/PHASE2 dataset별 설명 |
| `verification-and-tests.md` | gate와 수락 기준 |
| `decisions-and-history.md` | 큰 결정과 accepted/legacy 판단 |
| `current-lineage-and-gaps.md` | 현재 기준과 남은 gap |
| `end-to-end-history.md` | 전체 계보와 실패/수정 역사 |
| `agent-runbook.md` | 새 에이전트 실행 절차 |
| `failure-patterns.md` | 반복 결함과 회귀 gate 사전 |
