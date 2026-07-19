# DataSynth 현재 기준과 남은 Gap

이 문서는 `docs/datasynth` 하위 문서를 전수 대조한 결과, 과거 설명과 현재 accepted lineage가 달라진 부분 및 아직 닫히지 않은 문서·데이터 gap을 정리한다.

## 현재 accepted 기준

| 영역 | 현재 기준 | 판정 |
| --- | --- | --- |
| NORMAL | `datasynth_semantic_v1_normal_20260703_v53_account_determination_r6` | Accepted for batch/job identity + RBAC/SoD persona-process + approver master-authority + bounded L1-04 natural exception + annual closing semantic consistency + stable-account YoY volatility + account-pair determination realism successor |
| PHASE1-1 recall | `datasynth_semantic_v1_recall_20260630_v47_batchid_phase1_1_r1` | Accepted |
| PHASE1 combo/tier | `datasynth_semantic_v1_combo_tier_20260630_v47_batchid_r1j` | Accepted |
| Integrated usefulness all-fraud | `datasynth_integrated_usefulness_all_fraud_20260702_v1` | Combined benchmark dataset: integrated usefulness PHASE1 v1g + PHASE2 v1f in one journal |
| PHASE2 fraud | `datasynth_semantic_v1_phase2_fraud_20260614_v1_r4m_h` + seed1 | Accepted, but base-sync pending |
| PHASE2 scale reference | `datasynth_semantic_v1_phase2_fraud_20260613_v1_r4l_b` | Reference only, not accepted |
| Integrated usefulness Phase1 | `datasynth_integrated_usefulness_phase1_20260701_v1g` | Accepted |

## 과거 설명과 달라진 점

### 1. NORMAL 기준은 v43d/v46b/v52가 아니라 v53이다

기존 문서는 v43d, v46b 또는 v52를 current NORMAL로 설명했다. v43d는 PHASE2 full-column leak을 닫은 중요한 base-history이고, v46b는 단일법인+관계사 trace를 복구한 중요한 중간 accepted 기준이며, v52는 안정계정 연도 변동을 닫은 accepted 기준이다. 그러나 현재 NORMAL 기준은 `datasynth_semantic_v1_normal_20260703_v53_account_determination_r6`다.

v53은 v46b 이후 다음 successor들을 누적한 기준이다.

- `company_code`는 C001 하나만 존재한다.
- C002/C003는 별도 회사 원장이 아니라 C001의 관계사 `trading_partner`로 존재한다.
- 정상 IC GL trace가 존재한다: 1150=108, 4500=108, 2050=72, 2700=36.
- 정상 IC rows 432, IC docs 216, row share 0.001249.
- company-node graph cycle은 0이다.
- automated/recurring 계열은 `batch_id`와 `job_id`를 둘 다 가진다.
- RBAC/SoD persona-process 분포와 승인자 권한 master 정합을 가진다.
- annual closing line semantic이 연도별로 일관된다.
- D01을 오염시키던 안정 계정(이자·법인세 등) 연도 급변을 C07 gate로 잠근다.
- L4-04를 오염시키던 구체 계정쌍 파편화를 C06 gate로 잠근다.
- 최신 NORMAL verifier는 PASS 44 / MONITOR 1 / INFO 3 / FAIL 0이다.

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

### 5. PHASE2 r4m_h는 accepted지만 최신 NORMAL v53과 아직 동기화되지 않았다

r4m_h는 PHASE2 fraud overlay로 accepted다. 다만 NORMAL이 이후 단일법인+관계사 trace, v47 batch/job identity, v48 RBAC, v49 승인자 권한, v51 closing semantics, v52 안정계정 변동 제한, v53 계정쌍 결정까지 갱신되었으므로, 다음 PHASE2 재생성에서는 base를 v53으로 바꿔 같은 gate를 다시 통과해야 한다.

이 gap은 r4m_h가 실패라는 뜻이 아니다. r4m_h는 2026-06-14 기준 accepted fraud overlay이며, 현재 남은 일은 최신 NORMAL base 동기화다.

### 6. v47 batch/job identity successor

v46b는 automated/recurring 계열 전표의 `batch_id` 또는 `job_id`가 비어 있어
`source_trust.py`의 `trusted_automated_mask`가 자동 전표를 거의 신뢰하지 못했다.

v47 successor는 다음 원칙으로 수정했다.

- `source in {automated, recurring, batch, interface, system, auto, if, sys}`는 `batch_id`와 `job_id`를
  둘 다 가진다.
- 같은 실행 배치에 속한 문서는 같은 id를 공유하되, id 값 자체는 연도·회사·금액 리터럴을 드러내지 않는
  안정 hash 형식이다.
- `source in {manual, adjustment}`는 둘 다 빈칸으로 유지한다.
- PHASE1 combo/tier gate가 L2-05 ERP structural-reference path를 보려면
  `profile_phase1_v126.PHASE1_USECOLS`가 `original_document_id`/`reversal_document_id` 계열 컬럼을
  읽어야 한다. 이 컬럼 누락은 DataSynth 결함이 아니라 measurement harness 결함으로 판정되어 gate에
  반영했다.

검증 snapshot:

- NORMAL `trusted_automated_mask` rate: 0.9761.
- automated/recurring 등 자동 row의 `batch_id`와 `job_id` 동시 채움률: 1.0000.
- manual/adjustment row의 batch/job 채움률: 0.0000.
- PHASE1-1 recall v47: shortcut scan findings 0, truth units 1,500, detector catch script exit 0.
- PHASE1 combo/tier v47 r1j: static gate PASS, shortcut scan findings 0, actual case-builder gate 15/15 PASS.

### 7. v48 RBAC/SoD NORMAL successor

v48는 v47 batch/job successor 위에서 정상 회사의 권한분리와 persona-process 범위를 보정한 successor다.
v47은 direct SoD marker는 제거했지만 AP/AR/Treasury/Payroll 계열 persona가 여러 process를 처리하는
all-to-all 분포가 남아 있었다. v48는 생성기에서 전표 단위로 `created_by`, `approved_by`,
`user_persona`를 함께 재배정하고, 새 사용자를 `employees.json`에 등록한다.

검증 snapshot:

- Dataset: `data/journal/primary/datasynth_semantic_v1_normal_20260701_v48_rbac_r1`
- Report: `reports/normal_v48_rbac_r1_gate_v2.json`
- Realism verifier: PASS 40, MONITOR 1, INFO 3, FAIL 0.
- E05B RBAC gate: documents checked 111,522, scope bad docs 0, low-level over-breadth 0, all-to-all persona 0.
- Direct SoD/self-approval: 0.
- O02 synthetic marker scan: 0 findings after delegating RBAC structural columns to E05B.

### 8. v49 approver authority NORMAL successor

v49는 v48에서 새로 드러난 L1-04 정상 발화 결함을 닫은 successor다. v48은 H2R/O2C/P2P 수기 전표의
결재자 ID를 `HRMGR*`, `ARMGR*`, `APMGR*`로 만들었지만, employee master 등록 시 prefix 판정이 clerk로
떨어져 `can_approve_je=false`가 됐다. v49는 이 승인자 계열을 manager persona로 등록하고, 기존 master
항목도 재생성 시 현재 RBAC 배정과 동기화한다.

검증 snapshot:

- Dataset: `data/journal/primary/datasynth_semantic_v1_normal_20260702_v49_approver_r1`
- Report: `reports/normal_v49_approver_r1_gate.json`
- Realism verifier: PASS 41, MONITOR 1, INFO 3, FAIL 0.
- E05C approver master authority: approved docs checked 111,524, unresolved approver 0,
  unauthorized approver 0, approval-limit bad 0.
- H2R/O2C/P2P manual/adjustment 전표 1,748건은 전부 manager 승인자이며 `can_approve_je=true`.
- E05B RBAC scope, O02 marker, self-approval 모두 회귀 없음.

### 9. v50 bounded L1-04 natural exception NORMAL successor

v50은 v49에서 새로 드러난 "승인한도 초과 0건" 문제를 닫은 successor다. v49는 모든 승인 전표가
승인자 한도 안에 들어가 L1-04가 정상 baseline에서 영원히 발화하지 않는 죽은 룰 상태였다. v50은
employee master의 `approval_limit`을 일부 승인자의 실제 승인액 분포 기준으로 조정해, 비부정 운영 예외가
낮은 비율로 존재하도록 만들었다. 전표의 미사용 `approval_limit`/`approver_authority_limit` 표면 컬럼은
제거했고, feature/detector는 계속 `employees.json`의 `approval_limit`과 `can_approve_je`를 권위 원천으로
사용한다.

검증 snapshot:

- Dataset: `data/journal/primary/datasynth_semantic_v1_normal_20260702_v50_approval_noise_r2`
- Report: `reports/normal_v50_approval_noise_r2_gate.json`
- Realism verifier: PASS 41, MONITOR 1, INFO 3, FAIL 0.
- E05C: approved docs checked 111,524, unauthorized/unresolved approver 0, approval-limit exceeded docs 178
  (`0.1596%`, allowed range `0.05%~2.0%`).
- Feature path smoke: `add_exceeds_threshold()` produced 178 distinct L1-04 documents.
- O02 marker, E05B RBAC scope, self-approval all passed with no regression.

### 10. v51 annual closing semantic consistency NORMAL successor

v51은 v50에서 새로 드러난 annual closing semantic label 회귀를 닫은 successor다. v50은 M05 금액 대사는
통과했지만, 2022 수익 closing 라인이 `SERVICE_REVENUE`, 2023 비용 closing 라인이 `COGS_*`/`OPEX_*`,
2024 closing 라인의 `line_text_family`가 `payroll`로 남아 L4-03 수행중요성 threshold 산출을 왜곡했다.

검증 snapshot:

- Dataset: `data/journal/primary/datasynth_semantic_v1_normal_20260702_v51_closing_semantics_r1`
- Report: `reports/normal_v51_closing_semantics_r1_gate.json`
- Regression evidence: `reports/normal_v50_approval_noise_r2_gate_with_m14.json`
- Realism verifier: PASS 42, MONITOR 1, INFO 3, FAIL 0.
- M14: P&L closing lines checked 642, retained earnings lines checked 3, bad subtype/family 0,
  bad reconciliation years 0, max reconciliation diff 0 KRW.
- L4-03 threshold smoke: 2022/2023/2024 all `threshold_basis=closing_ni`, unset 0.

### 11. v52 stable-account YoY volatility NORMAL successor

v52는 v51에서 드러난 D01 정상 macro queue 오염을 닫은 successor다. D01 detector는 정상 작동했지만,
NORMAL에서 법인세비용·이자비용 같은 안정 계정 세부코드가 연도별로 난수처럼 배정되어 일부 계정이
8배를 넘게 급변했다.

검증 snapshot:

- Dataset: `data/journal/primary/datasynth_semantic_v1_normal_20260703_v52_stable_account_r2`
- Report: `reports/normal_v52_stable_account_r2_gate.json`
- Regression evidence: `reports/normal_v51_closing_semantics_r1_gate_with_c07.json`
- Realism verifier: PASS 43, MONITOR 1, INFO 3, FAIL 0.
- C07: checked year pairs 26, bad year pairs 0, max change ratio 4.5312.
- Direct smoke: interest expense ratios 1.2041x/1.2374x, income tax expense ratios 2.0559x/4.5312x.

### 12. v53 account-determination / L4-04 rare-pair fragmentation NORMAL successor

v53은 v52에서 드러난 L4-04 정상 rare-pair 오염을 닫은 successor다. L4-04 detector는 같은 engagement에서
드문 차대 계정쌍을 찾는데, NORMAL 생성기가 같은 의미 거래의 구체 계정을 매번 다른 번호로 흩뿌리면
정상 반복/자동 전표가 대량 희소쌍으로 오판된다.

검증 snapshot:

- Dataset: `data/journal/primary/datasynth_semantic_v1_normal_20260703_v53_account_determination_r6`
- Report: `reports/normal_v53_account_determination_r6_gate_v2.json`
- Regression evidence: `reports/normal_v52_stable_account_r2_gate_with_c06.json`
- Realism verifier: PASS 44, MONITOR 1, INFO 3, FAIL 0.
- C06: L4-04-like rare doc rate 0.129%, recurring rare doc rate 0.244%,
  automated rare doc rate 0.105%, fragmented rare pair rate 0.0%.
- v52 regression: L4-04-like rare doc rate 7.59%, recurring rare doc rate 10.3%,
  automated rare doc rate 6.21%, fragmented rare pair rate 98.1%.
- A01/M01/M02/M05/M11/M12/M14/J04_J07/E13/E05C/K02/B18 모두 무회귀 PASS.

### 8. Integrated usefulness all-fraud combined dataset

`datasynth_integrated_usefulness_all_fraud_20260702_v1` combines the existing integrated usefulness fraud
datasets into one journal:

- PHASE1 source: `datasynth_integrated_usefulness_phase1_20260701_v1g`
- PHASE2 source: `datasynth_integrated_usefulness_phase2_20260701_v1f`
- Base lineage: `datasynth_semantic_v1_normal_20260630_v47_batchid_r7`

The merge keeps base rows single-copy, appends only PHASE1 truth-document rows to the PHASE2 full journal, and
preserves separate PHASE1/PHASE2 truth sidecars plus `integrated_usefulness_all_truth.csv/json`.

Acceptance snapshot:

- PHASE1 gate failures 0.
- PHASE2 gate failures 0.
- Combined truth rows 1,135; combined truth documents 2,330.
- Final journal documents 113,836 = base 111,506 + PHASE1 595 + PHASE2 1,735.
- Truth document overlap 0; full/yearly missing truth docs 0; journal label columns exposed 0.
- `verify_injection_coherence.py` self-test PASS and dataset accidents 0.

Note: this combined dataset is not regenerated on top of v48 RBAC NORMAL. It intentionally combines the already
accepted v47-base integrated usefulness PHASE1/PHASE2 datasets.

### 7. Integrated usefulness Phase1 v1g

통합 쓸모 벤치마크 Phase1 overlay는 r7 normal 위에 3개 Phase1 패턴을 5벌 seed로 주입한다.
처음 PASS였던 v1e는 exact-value oracle만 통과했을 뿐, 이후 두 종류의 누수가 발견되어 gate에 승격했다.

- v1e 분포 누수:
  - fraud `source=manual` 100%, normal 약 10%.
  - fraud `batch_id/job_id` blank 100%, normal blank 약 12%.
- v1f 계열 수정:
  - weak 편승형은 batched non-manual donor에서 source/batch/job을 상속.
  - `verify_integrated_usefulness_phase1.py`에 categorical distribution leak scan 추가.
- v1g 날짜 coherence 수정:
  - `approval_date < document_date` 관계형 누수를 제거.
  - `verify_integrated_usefulness_phase1.py`에 temporal coherence check 추가.
  - `verify_injection_coherence.py --self-test`와 dataset oracle을 필수 실행한다.

v1g 검증 snapshot:

- truth rows 595.
- seed_0~seed_4 각각 119.
- exact-value oracle findings 0.
- distribution leak findings 0.
- temporal coherence findings 0.
- coherence oracle accidents 0.

## 현재 문서에 반영한 사항

- `README.md`: current table을 v47 successor로 갱신하고 PHASE2 base-sync 주의사항을 추가했다.
- `scenario-and-datasets.md`: v45~v46b 단일법인+관계사 trace 진화와 PHASE2 base-sync gap을 추가했다.
- `generation-principles.md`: 단일법인 원칙을 "관계사 흔적 0"이 아니라 "C001 원장 안의 정상 IC trace 존재"로 수정했다.
- `generation-flow.md`: `phase1-combo-tier-overlay` profile과 v47 흐름을 추가했다.
- `verification-and-tests.md`: v51 NORMAL snapshot과 r1j acceptance 기준을 반영했다.
- `fraud-overlay-realism-gate.md`: fraud/abnormal overlay 운영 gate와 Integrated usefulness Phase1 v1g 회귀항목을 추가했다.
- `decisions-and-history.md`: v46b, r11, r1z, v47 successor를 최신 accepted lineage로 추가했다.
- `end-to-end-history.md`: DataSynth 채택 배경부터 v46b/r11/r1z/r4m_h와 v47 successor까지의 A-to-Z 계보를 추가했다.
- `agent-runbook.md`: NORMAL/PHASE1-1/combo-tier/PHASE2별 생성 명령, gate, REJECT 처리 절차를 추가했다.
- `failure-patterns.md`: 반복 결함과 gate 승격 원칙을 사전 형태로 추가했다.

## 남은 Gap

| Gap | 영향 | 다음 조치 |
| --- | --- | --- |
| PHASE2 overlay가 v53 NORMAL 위에서 재생성되지 않음 | PHASE2 accepted lineage와 최신 NORMAL base가 다름 | r4m_h gate 세트를 유지하고 v53 base로 PHASE2 재생성 |
| `dev/active/datasynth-journal-realism-rebuild` 문서와 `docs/datasynth` 문서가 병존 | 상세 근거와 현행 요약이 나뉘어 있음 | `docs/datasynth`는 운영 SoT, active 문서는 상세 근거로 링크 유지 |
| PHASE1 v47 successor가 최신이나 historical v42j_r3/r11/r1z 설명이 일부 남음 | 신규 작업자가 구버전 dataset을 current로 오해할 수 있음 | v42j_r3는 decisions/history에서 legacy로만 참조하고 r11/r1z는 predecessor로 표시 |
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
