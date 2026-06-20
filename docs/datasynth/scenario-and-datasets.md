# DataSynth 시나리오와 데이터셋

## Dataset 계층

현행 DataSynth 산출물은 목적별로 분리된다.

| 계층 | 설명 | 현재 기준 |
| --- | --- | --- |
| NORMAL | 정상 전표, 정상 master, 정상 flow, 정상 결산 산출물 | `datasynth_semantic_v1_normal_20260614_v43d` |
| PHASE1 recall | 39개 PHASE1 룰의 standard/boundary 검증 overlay | `datasynth_semantic_v1_recall_20260613_v42j_r3` |
| PHASE2 fraud | 14개 구조적 fraud scheme overlay | `datasynth_semantic_v1_phase2_fraud_20260614_v1_r4m_h` |
| historical contract | 과거 PHASE1 contract truth/sidecar freeze | `datasynth` v126 |
| historical manipulation | 과거 manipulation v2~v7/fixed 계열 | archive/reference only |

## NORMAL 진화 요약

### v21~v25: 재무제표와 결산 정합

v21은 `opening_balances.json`, `period_close/trial_balances.json`, annual closing entry를 켰지만 TB↔JE, BS equation, closing, subledger reconciliation 실패가 남았다.
v25에서 다음 원칙으로 hard gate를 닫았다.

- KRW 원 단위 정수 누적.
- 월말 BS equation은 `assets = liabilities + equity + current_ytd_income`.
- annual closing은 P&L 계정을 닫고 마지막 retained earnings line이 residual을 흡수.
- subledger는 GL control-account line의 거래처/auxiliary 상세에서 파생.
- contra account, retained deficit, P&L reverse balance는 diagnostic으로 분리.

v25 잔차는 A01 imbalance 0, M01 mismatch 0, M02 bad period 0, M05 closing bad 0, M07 reconciliation bad 0이다.

### v26~v29: 전표 메타, 역분개, SoD 정상 오염 제거

v28은 document number, same-role reference, 정상 reversal pair를 정리했다.
정상 역분개는 원전표 링크가 있는 월말 발생액과 익월 취소 pair로 생성하며, pair net은 0이어야 한다.

v29는 NORMAL에서 direct SoD marker를 제거했다.
`sod_violation=true`와 `sod_conflict_type`은 confirmed control failure marker이므로 NORMAL에는 두지 않는다.
정상 broad role context는 review context로만 남기고 PHASE1 L1-06 confirmed finding으로 승격하지 않는다.

### v30~v31: PHASE2 계정 정상 배경

v30은 PHASE2 악용 가능 14개 계정을 NORMAL에 넣었지만, 회사·연도·월별 완벽균일, 단일 거래처, 좁은 금액 범위, 전용 scenario 격리 때문에 rejected 처리됐다.
v31은 신규 계정을 기존 정상 archetype에 섞고, 빈 셀과 변동성, heavy-tail 금액, 거래처 분산을 갖도록 재생성했다.

v31c 기준:

- required 14 PHASE2 accounts missing 0.
- N07~N11 신규계정 자연화 PASS.
- 신규계정 normal-only, fraud/anomaly/provenance 0.

### v42j: 도메인 감사 결함 수정

2026-06-12~13 도메인 7구역 감사에서 다음 결함이 발견됐다.

- TB가 JE에서 파생되지 않는 hollow pass.
- opening balance 더미와 carry-forward 단절.
- subledger reconciliation이 실측 없이 difference 0 기록.
- taxable 10% VAT 오류.
- KRW 환율 marker.
- SoD flag 불일치.
- cost center master 체계 불일치.
- 연도 clone marker와 timestamp 집중.
- PHASE2 deny-list를 통과한 synthetic marker 컬럼.

v42j는 이 결함들을 수정했고, NORMAL verifier FAIL/BLOCKED 0, balance audit PASS를 달성했다.

### v43d: full-column leak fix

2026-06-14 full-column leak scan에서 PHASE2 r4l_b가 `original_document_id` non-null surface로 부정을 노출했다.
원인은 NORMAL에 linked reversal background가 충분하지 않은 것이다.

v43d는 linked normal reversal background 1,300쌍을 추가하고, NORMAL direct SoD marker 정책과 document-number gate를 조정했다.
검증 결과는 NORMAL realism verifier PASS 33 / MONITOR 1 / FAIL 0, balance audit PASS다.

## PHASE1 recall overlay

PHASE1 recall overlay는 PHASE1-1 39개 룰의 raw trigger 검증용이다.
current accepted dataset은 `datasynth_semantic_v1_recall_20260613_v42j_r3`이다.

핵심 구조:

- truth rows 2,160.
- 108 rule-variant pairs x standard/boundary control.
- output docs 325,365로 base와 동일.
- standard 1,080 / 1,080 caught.
- boundary control 0 / 1,080 caught.
- rules 39 / 39.
- shortcut scan findings 0.
- CoA coverage PASS. `999998`은 L1-03 invalid-account standard 문서에만 허용.

주의:

- v42j_r3는 PHASE1 룰 검증 전용이다.
- oracle scan에서 ML 관점의 raw marker가 일부 보고됐지만 PHASE1 detector가 쓰지 않는 표면이거나 PHASE1에 무해한 값으로 재판정됐다.
- PHASE2 ML dataset으로 재사용하면 안 된다.

## PHASE2 fraud overlay

PHASE2 overlay는 14개 real fraud scheme을 만든다.
scheme source of truth는 `docs/archive/completed/dev-prompts/phase2-fraud-scheme-catalog.md`와 `phase2_scheme_overlay.rs` 구현이다.

필수 coverage:

- FS01~FS14 모두 존재.
- scheme id, instance id, component role, member docs, evaluation stratum, omission amount 추적.
- flow/member sidecar 존재.
- low-trace omission scheme은 omission amount가 양수이고 복사 상수가 아니어야 한다.
- structural floor를 보존한다. FS01 repeated external fictitious customer, FS03 progressive cash withdrawal, FS05 3-company circular chain을 shortcut cleanup으로 없애면 실패다.

r4m_h accepted 이유:

- r4l_b full-column scan에서 발견된 L4~L7 누출을 수정했다.
- trading partner를 role-compatible normal partner pool에서 분산했다.
- auxiliary/supporting metadata를 donor 상속으로 채웠다.
- normal linked reversal background를 v43d에 추가했다.
- round amount marker를 자연 단수와 정상 support로 완화했다.
- representative와 seed1 모두 shortcut, regression, surface scan, full-column scan을 통과했다.

## Seed rotation

seed rotation은 단순히 document id나 company label만 바꾸는 것이 아니다.
검증 기준은 `(scheme_id, component_role, local_amount, posting_date, gl_account)` content difference와 scheme-company assignment vector 차이다.

accepted seed set은 다음을 만족해야 한다.

- representative/seed pair의 fraud content 차이가 50% 이상.
- seed끼리 동일 assignment vector가 0.
- density, scheme count, accounting mechanics는 보존.
- seed-only identifier, reference range, amount bucket, support metadata 조합, reversal link surface가 생기지 않음.

