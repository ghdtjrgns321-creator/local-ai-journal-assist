# DataSynth NORMAL 생성 원칙

이 문서는 P3-1 NORMAL baseline 재구축에서 합의한 생성 원칙과 v20~v30 수정 내역을 정리한다.
목표는 fraud/anomaly가 없는 정상 원장을 먼저 회계적으로 자연스럽게 만들고, 이후 P3-2/P3-3 위반
데이터를 이 정상 모집단 위에 얹는 것이다.

## 비협상 원칙

- 정상 데이터에는 `is_fraud`, `is_anomaly`, mutation/provenance 정답 컬럼 값이 들어가면 안 된다.
- 검증 점수를 맞추기 위한 Python 후처리는 금지한다. 생성 원인은 Rust `tools/datasynth/`에서 고친다.
- DataSynth 수정 후에는 산출물 종류에 맞는 검증 게이트를 자동 실행 대상으로 삼는다. NORMAL은
  [normal-data-realism-test-catalog.md](./normal-data-realism-test-catalog.md), PHASE1 overlay는
  [phase1-abnormal-overlay-test-catalog.md](./phase1-abnormal-overlay-test-catalog.md) 및
  [phase1-rule-recall-overlay-verification.md](./phase1-rule-recall-overlay-verification.md), PHASE2 fraud
  overlay는 [phase2-overlay-verification-catalog.md](./phase2-overlay-verification-catalog.md)를 기준으로 한다.
  PHASE2 shortcut 제거 작업은 `tools/scripts/phase2_shortcut_gate.py DATASET_PATH [REFERENCE]` exit 0과,
  seed 회전 산출물이 있으면 `tools/scripts/verify_phase2_seed_diversity.py` exit 0까지 포함한다.
- 새 버그가 발견되거나 같은 유형으로 재발 가능성이 있으면, 해당 수정은 완료 전에 관련 검증
  카탈로그에 regression gate로 승격한다. 콘솔 검증이나 `docs/debugging.md` 기록만으로 완료 처리하지 않는다.
- 정상 전표는 document 단위 차변 합계와 대변 합계가 맞아야 한다.
- 계정 subtype, business_process, counterparty_type, document_type, line_text_family는 독립 샘플링하지
  않고 거래 archetype 단위로 함께 뽑는다.
- 자연 noise는 존재해야 하지만 계정/프로세스/정답 라벨의 shortcut이 되면 안 된다.
- 세무 처리는 랜덤이 아니라 거래 archetype과 증빙 성격에 따라 과세/영세/면세/비과세가 결정되어야 한다.
- 내부거래, 정상 반복거래, batch 전표, 연말마감 전표처럼 이후 룰 검증의 정상 비교군이 될 구조를
  소량 샘플이 아니라 충분한 모집단으로 생성한다.
- 재무제표 정합은 전표 단위 균형과 별개로 검증한다. TB, roll-forward, closing, subledger는 hollow
  PASS가 아니라 산출물 기반 숫자로 판정한다.

## v20까지 닫은 축

- `is_intercompany`를 journal CSV에 출력하고 정상 IC matched pair를 36개월 x 3법인에 분산 생성했다.
- 정상 회사 노드 기반 3-hop cycle 배경을 생성해 GraphDetector smoke가 0/skip이 아니게 했다.
- IC 계정은 COA에 존재하는 `1150`, `2050`, `4500`, `2700` 계열과 `trading_partner=회사코드` 구조로
  맞췄다.
- 정상 batch 전표는 급여 지급, vendor payment, 감가상각 run으로 매월 생성한다.
- O02 synthetic marker scan에서 IC 구조 필드는 K01~K07 전용 검증으로 분리하고, 비구조 단일값 marker는
  별도 FAIL로 잡는다.

## v21에서 추가한 축

- `opening_balances.json`과 `period_close/trial_balances.json` 산출을 켰다.
- 다법인 TB 검증을 위해 `PeriodTrialBalance.company_code`를 출력한다.
- TB는 계정별 차변/대변 총액이 아니라 순잔액을 정상 잔액 방향에 표시한다.
- tax backfill과 최종 semantic/balance hard gate 이후 재무제표/TB를 다시 산출해 최종 journal과 TB가
  같은 원장을 보도록 했다.
- 연말 명시 closing entry를 생성한다. 마감 전표는 `batch_type=annual_closing`, `reference=CLOSE-*`로
  식별하며, 일반 R2R 전표와 구분한다.
- annual closing은 모든 P&L 계정을 닫는 정상 결산 전표이므로 일반 line role allowlist와 revenue
  customer-counterparty rule의 좁은 예외로 처리한다.
- IC buyer expense cost center는 IC 전용 `CC100` 하드코딩을 제거하고 일반 정상 cost center pool과
  겹치게 했다.
- 계정 분류표에서 `4500`은 IC receivable, `5300`은 비용 계정으로 분류되도록 보정했다.

## 현재 v21 검증 상태

> 2026-06-05 v25에서 M01~M07 hard gate는 재검증 완료했다. 아래 v21 상태는 v22~v25 수정 전 진단 기록이다.

산출물:

- Dataset: `data/journal/primary/datasynth_semantic_v1_normal_20260605_v21`
- Report JSON: `artifacts/datasynth_normal_semantic_v1_realism_gate_audit_20260605_v21.json`
- Report MD: `artifacts/datasynth_normal_semantic_v1_realism_gate_audit_20260605_v21.md`

현재 verifier 요약은 `PASS 18`, `FAIL 5`, `MONITOR 1`, `BLOCKED 2`다.

닫힌 항목:

- normal-only contamination: PASS
- tax treatment: PASS
- natural noise rates: PASS
- amount/grid dominance: PASS
- O02 synthetic marker scan: PASS
- K01~K07 IC/Graph normal background: PASS
- J08 batch explainability: PASS
- M03 roll-forward arithmetic: PASS
- M04 period continuity: PASS

남은 항목:

- A01: annual closing 8개 전표가 원 단위 정수 기준 2~7원 불균형이다.
- M01: TB와 journal-derived GL 합계 차이가 최대 22원 남아 있다.
- M02: 기말 회계등식이 108개 period 전부 FAIL이다.
- M05: annual closing은 생성되지만 9개 company-year 중 8개가 P&L to retained earnings 검증에 실패한다.
- M07: AR/AP/Inventory/FA subledger reconciliation 5건 전부 Unreconciled다.
- M06: negative normal balance count는 MONITOR다. 과도한 현금/채권/부채 방향 전환이 실제 정상분포인지
  별도 분포 검토가 필요하다.

## 2차 작업

1. annual closing 정밀화
   - closing entry 생성 시 모든 금액을 KRW 원 단위로 정규화하거나, 마지막 retained earnings 라인이
     residual을 흡수하도록 한다.
   - verifier는 `batch_type=annual_closing`과 `reference=CLOSE-*` 기준으로만 closing을 식별한다.
   - 수락 기준: A01 imbalance 0, M05 closing_bad 0.

2. M01/M02 재무제표 equation 정합
   - TB 산출과 verifier가 같은 회계기간 기준을 사용하도록 고정한다.
   - BS 계정은 opening + fiscal period 누적, P&L 계정은 월별/연말 closing 이후 상태를 명확히 분리한다.
   - 수락 기준: M01 max diff <= 1원, M02 bad periods 0.

3. M07 subledger architecture
   - 현재 subledger는 일부 document flow만 만들고, GL은 31만 정상 JE 전체를 포함한다. 그래서 AR/AP/FA/Inventory
     control balance와 subledger balance가 구조적으로 맞을 수 없다.
   - 2차에서는 control account에 닿는 모든 정상 JE가 subledger event를 만들거나, subledger-backed
     거래와 non-subledger GL을 계정/프로세스에서 분리해야 한다.
   - 수락 기준: AR/AP/Inventory/FA hard gate reconciled, max diff <= 1원.

4. B17/P01
   - explicit archetype_id를 생성기에 추가하거나 verifier의 inferred mode를 구현한다.
   - 고정 seed 샘플 전문가/LLM diagnostic review를 별도 산출물로 남긴다.

## v22~v25에서 닫은 재무제표 정합 축

산출물:

- Dataset: `data/journal/primary/datasynth_semantic_v1_normal_20260605_v25`
- Config: `artifacts/datasynth_semantic_v1_normal_20260605_v25_config.json`
- Report JSON: `artifacts/datasynth_normal_semantic_v1_realism_gate_audit_20260605_v25.json`
- Report MD: `artifacts/datasynth_normal_semantic_v1_realism_gate_audit_20260605_v25.md`

최종 verifier 요약은 `PASS 24`, `BLOCKED 2`다. `B17`은 explicit archetype_id 부재, `P01`은 전문가/LLM
고정 seed 샘플 review 미구현 때문에 diagnostic BLOCKED로 남긴다. hard realism gate 실패는 없다.

적용 원칙:

- KRW 금액은 TB 집계, roll-forward, closing, verifier 비교에서 원 단위 정수로 누적한다. float 잔차를
  회계 오류로 만들지 않는다.
- `AccumulatedDepreciation` subtype은 asset 계정이어도 정상 대변잔액 계정으로 생성한다.
- M02 월말 회계등식은 `assets = liabilities + equity + current_ytd_income`으로 본다. 월별 soft-close에서는
  손익계정이 아직 이익잉여금으로 닫히지 않았기 때문이다. 연말 closing 후에는 M05가 P&L to retained
  earnings를 별도 확인한다.
- annual closing entry는 손익계정 라인별 원 단위 누계로 만들고, 마지막 retained earnings 라인이 실제
  잔여 차이를 정확히 받는다. 별도 인위적 plug 전표가 아니라 정상 결산 전표다.
- NORMAL baseline의 M07 보조원장은 최종 GL control-account 라인의 거래처/auxiliary 상세에서 파생한다.
  정상 기준에서는 subledger=GL이 맞으며, 보조원장 불일치는 P3-3 오류/부정 주입 대상이다.
- 월말 정상잔액 재분류 전표(`batch_type=monthly_balance_reclass`)를 R2R 시스템 전표로 생성한다. 은행
  overdraft, 차변성 미지급, 대변성 자산 잔액을 결산 때 단기차입/선급·미수성 계정으로 정리하는 정상
  실무를 반영한다.
- M06은 contra 계정, 이익잉여금 누적결손, 손익계정 기간 중 역방향 누계를 diagnostic으로 분리한다.
  BS hard 반대잔액은 정상 실무상 소수 허용하되, period-account 기준 2% 초과 또는 특정 계정 과집중이면
  MONITOR/FAIL이다.

v25 주요 잔차:

- A01: imbalance 0, max 0원.
- M01: checked 39,636 lines, mismatches 0, max diff 0원.
- M02: 108 periods, bad 0, max equation diff 1원.
- M03/M04: 38,978 period-account, roll-forward/continuity bad 0.
- M05: 9 company-year, closing_bad 0.
- M06: hard negative balance 434 / 38,978 = 1.11%, threshold 2% 이내. retained deficit 99,
  income-statement reverse balance 7,926, contra 890은 diagnostic으로 분리.
- M07: 5 reconciliations, bad 0, max diff 0원.

## v26~v28에서 닫은 전표 메타/흐름 현실성 축

산출물:

- Dataset: `data/journal/primary/datasynth_semantic_v1_normal_20260606_v28`
- Config: `artifacts/datasynth_semantic_v1_normal_20260606_v28_config.json`
- Report JSON: `artifacts/datasynth_normal_semantic_v1_realism_gate_audit_20260606_v28.json`
- Report MD: `artifacts/datasynth_normal_semantic_v1_realism_gate_audit_20260606_v28.md`

적용 원칙:

- semantic 필드는 CoA fallback에 기대지 않고 IC/closing/reclass 같은 시스템 전표 라인에도 원천에서 채운다.
- `document_number`는 company/year/document_type별 증가 번호 체계로 고유하게 생성한다.
- `reference` 공유는 같은 role 전표의 우연 재사용이 아니라 invoice→payment, accrual→reversal 같은 정상 흐름
  링크에만 허용한다.
- `R2R_REVERSAL`은 독립 랜덤 샘플링하지 않는다. 정상 역분개는 반드시 원전표가 있는 월말 발생액→익월 취소
  pair로 생성하고, `original_document_id`, `reversal_document_id`, `reversal_type`,
  `reversal_reason_code`를 출력한다.
- 역분개 pair는 GL 계정별로 합산했을 때 net 0이어야 하며, 정상 baseline에서는 unlinked reversal 문서를
  허용하지 않는다. 원전표 없는 역분개나 보조 참조 불일치는 P3-3 오류/부정 주입 대상이다.

v28 주요 잔차:

- Realism verifier: `PASS 28`, `INFO 3`, FAIL/BLOCKED 0.
- J04/J07: reversal scenario docs 99, linked 99, checked pairs 99, unlinked 0, missing original 0,
  bad time order 0, bad pair net 0, max pair net 0원.
- B17: raw tuple missing rows 0, `R2R_REVERSAL` 99 docs/198 rows가 `ACCRUED_LIABILITIES`와
  `OPEX_PROFESSIONAL_FEES`의 `REVERSAL` family로 채워짐.
- L2-05 read-only: structural reference FlowUnit 99, rolling zero-out FlowUnit 1. 구조 경로는 복구됐지만
  현 detector 의미상 structural reference rows는 `high_confidence_reversal`로 분류된다. 정상 데이터 자체는
  fraud/anomaly가 아니므로 이 label을 확정 위반으로 표현하지 않는 책임은 Phase1 presentation/queue 의미론에
  남아 있다.

## v29에서 닫은 direct SoD 정상 오염

산출물:

- Dataset: `data/journal/primary/datasynth_semantic_v1_normal_20260607_v29`
- Config: `artifacts/datasynth_semantic_v1_normal_20260607_v29_config.json`
- Report JSON: `artifacts/datasynth_normal_semantic_v1_realism_gate_audit_20260607_v29.json`
- Report MD: `artifacts/datasynth_normal_semantic_v1_realism_gate_audit_20260607_v29.md`

적용 원칙:

- NORMAL baseline에는 `sod_violation=true`와 `sod_conflict_type` direct marker를 생성하지 않는다.
  SoD 위반은 통제 실패 finding이므로 P3-2/P3-3 abnormal/truth 시나리오에서만 명시 주입한다.
- `anomalous_assignment_rate=0.0`이면 anomalous process user 최소 floor를 적용하지 않는다. 정상 profile에서
  conflict 전용 사용자를 보장하기 위한 floor는 fitting이며, L1-06 confirmed queue를 오염시킨다.
- 정상의 현실적 role breadth는 `compatible_extension_rate` 기반의 허용 가능한 겸직으로만 표현한다.
  direct conflict 마커 없이 남는 broad work-scope 신호는 L3-12 같은 review context로 다뤄야 하며 L1-06
  confirmed finding으로 승격하지 않는다.
- 기본 DataSynth internal control 설정도 direct SoD와 anomalous assignment는 0을 기본값으로 둔다. 필요한
  위반은 abnormal generation config/truth layer가 명시적으로 켠다.

v29 주요 잔차:

- Realism verifier: `PASS 29`, `INFO 3`, FAIL/BLOCKED 0.
- E05_SOD_DIRECT_MARKER: 320,312 documents checked, `sod_violation=true` 0 docs,
  `sod_conflict_type` nonblank 0 docs.
- L1-06 read-only 재측정: v28 `6,327` docs / `18,533` rows → v29 `0` docs / `0` rows.
- A01, M01~M07, K01~K07, B15/B16/H04, J04/J07는 PASS 유지.

## v30에서 추가한 PHASE2 계정 정상 배경

산출물:

- Dataset: `data/journal/primary/datasynth_semantic_v1_normal_20260610_v30f`
- Report JSON: `artifacts/datasynth_normal_semantic_v1_realism_gate_audit_20260610_v30f.json`
- Report MD: `artifacts/datasynth_normal_semantic_v1_realism_gate_audit_20260610_v30f.md`

적용 원칙:

- `dev/active/phase2-fraud-scheme-catalog.md` §2.1의 PHASE2 악용 가능 계정군은 부정 주입 전에 NORMAL
  baseline에 정상 활동으로 존재해야 한다.
- v30은 fraud/anomaly/truth를 주입하지 않는다. 신규 계정은 회사·연도·월에 분산된 정상 R2R/O2C/P2P/H2R/
  TREASURY/MFG 전표로만 추가한다.
- 신규 계정 전표도 차대변 균형, raw semantic tuple, 전표번호/참조 정책, TB/closing/roll-forward 정합을
  통과해야 한다.
- 계정 확장 때문에 생기는 손익은 정상 연말 closing entry로 `3200` 이익잉여금에 반영한다. TB는 v29의 기존
  정합을 보존하고 v30 확장 전표 delta만 원 단위로 반영한다.
- 신규 정상 흐름의 상대 계정이 COA에 없으면 journal을 바꾸지 않고 master를 보강한다. v30에서는
  공사계약 수익 상대계정 `412100`을 supporting normal revenue account로 추가했다.

v30f 주요 잔차:

- Realism verifier: `PASS 29`, `INFO 3`, FAIL/BLOCKED/MONITOR 0.
- O01: `is_fraud=true`, `is_anomaly=true`, `fraud_type` nonblank, mutation/provenance nonblank 모두 0.
- A01: imbalance 0, max 0원.
- I01/I03/I04: duplicate document number 0, bad document number format 0, same-role reference reuse 0.
- O02 synthetic marker scan: high-risk marker 0.
- M01: checked 41,256 lines, mismatch 0, max diff 0원.
- M02: 108 periods, bad 0, max equation diff 1원.
- M03/M04: 40,851 period-account, roll-forward/continuity bad 0.
- M05: 9 company-year, closing_bad 0.
- M06: hard negative balance 607 / 40,851 = 1.49%, threshold 2% 이내.
- M07: 5 reconciliations, bad 0, max diff 0원.
- Required 14 PHASE2 accounts: missing 0. 각 계정은 432~864 rows, 3개 회사, 3개 연도, 12개월에 분산.
- Journal orphan GL account rows: 0.

v30f 재판정:

- N07~N11 신규 gate 적용 후 v30f는 REJECT다. 회계정합은 맞지만 신규 14계정이 회사/연도/월 셀당
  완벽균일, 전용 scenario 격리, 단일 counterparty, 좁은 금액 범위를 보여 "계정=shortcut" 위험이 남았다.
- 신규 계정 정상 배경은 전표 수만 채우면 안 된다. 기존 정상 archetype에 섞이고, 일부 셀은 0건이어야 하며,
  거래처와 금액 분포도 기존 계정군처럼 자연스럽게 퍼져야 한다.

## v31에서 닫은 PHASE2 계정 자연화/N-gate

산출물:

- Dataset: `data/journal/primary/datasynth_semantic_v1_normal_20260610_v31c`
- Report JSON: `artifacts/datasynth_normal_semantic_v1_realism_gate_audit_20260610_v31c.json`
- Report MD: `artifacts/datasynth_normal_semantic_v1_realism_gate_audit_20260610_v31c.md`

적용 원칙:

- v31은 v30f를 복사한 뒤 v30 신규계정 확장 문서를 제거하고, 같은 14계정을 자연화된 정상 활동으로
  재생성한다. 기존 정상 v29/v30의 비신규계정 흐름은 유지한다.
- 신규계정 회사/연도/월 분포는 deterministic fixed count가 아니라 회사 규모, 계절성, 계정 성격에 따라
  빈 셀과 변동성을 가진다.
- 금액은 좁은 선형 범위가 아니라 heavy-tail 분포로 생성한다. 단일 금액/round-grid dominance가 계정
  shortcut이 되면 안 된다.
- A계정군은 전용 scenario에 가두지 않고 `P2P_VENDOR_INVOICE`, `A2R_ASSET_ACQUISITION`,
  `A2R_DEPRECIATION`, `H2R_PAYROLL_ACCRUAL`, `TRE_LOAN_DRAWDOWN`, `TRE_INTEREST_PAYMENT`,
  `R2R_ACCRUAL`, `R2R_CLOSING_ENTRY` 같은 기존 정상 archetype에 섞는다.
- contract assets/liabilities와 WIP처럼 본질적으로 전용 흐름이 자연스러운 계정은 전용 archetype을 유지하되,
  건수/거래처/금액의 완벽균일성은 허용하지 않는다.
- `document_number`의 company/year/document_type 체계는 row의 실제 `document_type`과 반드시 일치해야 한다.
  v31b의 `C001-2022-KR-*` 번호와 `SA` row type 불일치가 I01에서 잡혔고, v31c에서 수정했다.

v31c 주요 잔차:

- Realism verifier: `PASS 34`, `INFO 3`, FAIL/BLOCKED/MONITOR 0.
- O01: fraud/anomaly/provenance nonblank 0.
- A01: imbalance 0, max 0원.
- I01/I03/I04: duplicate document number 0, bad document number format 0, same-role reference reuse 0.
- O02 synthetic marker scan: high-risk marker 0.
- M01: checked 41,472 lines, mismatch 0, max diff 0원.
- M02: 108 periods, bad 0, max equation diff 1원.
- M03/M04: 41,049 period-account, roll-forward/continuity bad 0.
- M05: 9 company-year, closing_bad 0.
- M06: hard negative balance 644 / 41,049 = 1.57%, threshold 2% 이내.
- M07: 5 reconciliations, bad 0, max diff 0원.
- N07: all 14 new accounts PASS. Cell-count std range 2.17~4.53, empty cells range 15~29.
- N08: all 14 new accounts PASS. Top trading-partner share max 45.6%, no single counterparty 100%.
- N09: all 14 new accounts PASS. max/p50 range 31.55~44.87, unique amounts per account equal row count.
- N10: all 11 woven-required accounts PASS. Dedicated-flow accounts `116100`, `231100`, `123100` are exempt but still pass
  N07~N09.
- N11: all 14 new accounts normal-only, fraud/anomaly/provenance 0.
