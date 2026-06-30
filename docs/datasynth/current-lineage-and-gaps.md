# DataSynth 현재 기준과 남은 Gap

이 문서는 `docs/datasynth` 하위 문서를 전수 대조한 결과, 과거 설명과 현재 accepted lineage가 달라진 부분 및 아직 닫히지 않은 문서·데이터 gap을 정리한다.

## 현재 accepted 기준

| 영역 | 현재 기준 | 판정 |
| --- | --- | --- |
| NORMAL | `datasynth_semantic_v1_normal_20260621_v46b` | Accepted |
| PHASE1-1 recall | `datasynth_semantic_v1_recall_20260622_v46b_phase1_1_r11` | Accepted |
| PHASE1 combo/tier | `datasynth_semantic_v1_combo_tier_20260622_v46b_r1z` | Accepted |
| PHASE2 fraud | `datasynth_semantic_v1_phase2_fraud_20260614_v1_r4m_h` + seed1 | Accepted, but base-sync pending |
| PHASE2 scale reference | `datasynth_semantic_v1_phase2_fraud_20260613_v1_r4l_b` | Reference only, not accepted |

## 과거 설명과 달라진 점

### 1. NORMAL 기준은 v43d가 아니라 v46b다

기존 문서는 v43d를 current NORMAL로 설명했다. v43d는 PHASE2 full-column leak을 닫은 중요한 base-history지만, 현재 NORMAL 기준은 v46b다.

v46b의 핵심 차이는 다음과 같다.

- `company_code`는 C001 하나만 존재한다.
- C002/C003는 별도 회사 원장이 아니라 C001의 관계사 `trading_partner`로 존재한다.
- 정상 IC GL trace가 존재한다: 1150=108, 4500=108, 2050=72, 2700=36.
- 정상 IC rows 432, IC docs 216, row share 0.001249.
- company-node graph cycle은 0이다.
- NORMAL verifier는 PASS 38 / MONITOR 1 / FAIL 0 / BLOCKED 0이다.

### 2. "단일법인"은 관계사 흔적 0이 아니다

기존 생성 원칙에는 단일법인이라는 이유로 `is_intercompany=true`, IC/RELATED surface, company-code trading partner가 NORMAL에서 0이어야 한다는 취지의 문장이 있었다. 이 해석은 폐기한다.

현재 원칙은 다음이다.

- 단일법인 GL-only: 여러 회사의 원장을 한 journal에 섞지 않는다.
- 관계사 거래 흔적: C001의 정상 거래처로 C002/C003가 소량 등장할 수 있다.
- IC 계정 흔적: `1150`, `4500`, `2050`, `2700`은 정상 모집단에 있어야 한다.
- 금지: NORMAL에서 회사-node 순환 graph, IC 대사 불일치, 부정 순환을 만들지 않는다.

### 3. PHASE1-1 recall은 39룰이 아니라 최신 26룰 기준이다

구버전 v42j_r3/r9/r10은 과거 룰 수와 legacy metadata 기준이다. 현재 PHASE1-1 recall accepted dataset은 r11이다.

r11 기준:

- active rules 26 / 26.
- truth units 1,500 = standard 750 + boundary control 750.
- standard 750 / 750 caught.
- boundary control 0 / 750 caught.
- shortcut scan findings 0.
- CoA coverage PASS.

### 4. PHASE1 combo/tier는 PHASE1-1 recall과 별도다

combo/tier는 개별 룰 발화 검증이 아니라 case assembly 검증이다.

accepted r1z 기준:

- truth rows 15 = buildable combo 13 + LOW 1 + CONTEXT 1.
- static combo/tier gate PASS.
- shortcut scan findings 0.
- actual case-builder gate PASS: 15 / 15.

중요한 판정 기준:

- 최종 case `priority_band`만으로 combo/tier 수락 여부를 판단하지 않는다.
- 같은 case에 broad normal signal이 섞이면 final band가 기대 tier보다 높아질 수 있다.
- 수락 기준은 expected topic의 actual topic score cut 충족 여부다.

### 5. PHASE2 r4m_h는 accepted지만 최신 NORMAL v46b와 아직 동기화되지 않았다

r4m_h는 PHASE2 fraud overlay로 accepted다. 다만 v46b NORMAL이 이후 단일법인+관계사 trace 기준으로 갱신되었으므로, 다음 PHASE2 재생성에서는 base를 v46b로 바꿔 같은 gate를 다시 통과해야 한다.

이 gap은 r4m_h가 실패라는 뜻이 아니다. r4m_h는 2026-06-14 기준 accepted fraud overlay이며, 현재 남은 일은 최신 NORMAL base 동기화다.

## 현재 문서에 반영한 사항

- `README.md`: current table을 v46b/r11/r1z로 갱신하고 PHASE2 base-sync 주의사항을 추가했다.
- `scenario-and-datasets.md`: v45~v46b 단일법인+관계사 trace 진화와 PHASE2 base-sync gap을 추가했다.
- `generation-principles.md`: 단일법인 원칙을 "관계사 흔적 0"이 아니라 "C001 원장 안의 정상 IC trace 존재"로 수정했다.
- `generation-flow.md`: `phase1-combo-tier-overlay` profile과 r11/r1z 흐름을 추가했다.
- `verification-and-tests.md`: v46b NORMAL snapshot과 r1z acceptance 기준을 반영했다.
- `decisions-and-history.md`: v46b, r11, r1z를 최신 accepted lineage로 추가했다.
- `end-to-end-history.md`: DataSynth 채택 배경부터 v46b/r11/r1z/r4m_h까지의 A-to-Z 계보를 추가했다.
- `agent-runbook.md`: NORMAL/PHASE1-1/combo-tier/PHASE2별 생성 명령, gate, REJECT 처리 절차를 추가했다.
- `failure-patterns.md`: 반복 결함과 gate 승격 원칙을 사전 형태로 추가했다.

## 남은 Gap

| Gap | 영향 | 다음 조치 |
| --- | --- | --- |
| PHASE2 overlay가 v46b NORMAL 위에서 재생성되지 않음 | PHASE2 accepted lineage와 최신 NORMAL base가 다름 | r4m_h gate 세트를 유지하고 v46b base로 PHASE2 재생성 |
| `dev/active/datasynth-journal-realism-rebuild` 문서와 `docs/datasynth` 문서가 병존 | 상세 근거와 현행 요약이 나뉘어 있음 | `docs/datasynth`는 운영 SoT, active 문서는 상세 근거로 링크 유지 |
| PHASE1 r11/r1z는 최신이나 historical v42j_r3 설명이 일부 남음 | 신규 작업자가 구버전 dataset을 current로 오해할 수 있음 | v42j_r3는 decisions/history에서 legacy로만 참조 |
| PHASE2 seed rotation은 r4m_h/seed1만 문서화 | seed 다양성 전체 set의 최신 상태가 부족함 | 다음 PHASE2 재생성 때 representative + seed set 전체 결과를 같은 표로 기록 |
| NORMAL M06 MONITOR 잔존 | hard fail은 아니지만 balance-direction diagnostic이 계속 남음 | 다음 NORMAL major run에서 MONITOR 상세 분해와 유지/해소 판단 기록 |

## 업데이트 규칙

새 accepted dataset이 생기면 다음 문서를 함께 갱신한다.

1. `docs/datasynth/README.md` current 기준 표.
2. `docs/datasynth/scenario-and-datasets.md` 해당 계층 evolution 섹션.
3. `docs/datasynth/verification-and-tests.md` acceptance snapshot과 명령.
4. `docs/datasynth/decisions-and-history.md` accepted lineage와 legacy 표.
5. 이 문서의 현재 기준 표와 남은 Gap.
6. `docs/debugging.md`의 run-level 상세 기록.
