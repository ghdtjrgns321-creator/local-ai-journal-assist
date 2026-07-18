# DataSynth 시나리오와 데이터셋

## Dataset 계층

현행 DataSynth 산출물은 목적별로 분리된다.

| 계층 | 설명 | 현재 기준 |
| --- | --- | --- |
| NORMAL | 정상 전표, 정상 master, 정상 flow, 정상 결산 산출물 | `datasynth_semantic_v1_normal_20260703_v53_account_determination_r6` |
| PHASE1-1 recall | 26개 최신 PHASE1-1 개별 룰의 standard/boundary 검증 overlay | `datasynth_semantic_v1_recall_20260630_v47_batchid_phase1_1_r1` |
| PHASE1 combo/tier | 켜진 룰 조합이 case 단위 HIGH/MEDIUM/LOW/CONTEXT tier로 조립되는지 검증하는 별도 overlay | `datasynth_semantic_v1_combo_tier_20260630_v47_batchid_r1j` |
| PHASE2 fraud | 14개 구조적 fraud scheme overlay | `datasynth_semantic_v1_phase2_fraud_20260614_v1_r4m_h` |
| Integrated usefulness Phase1 | 통합 쓸모 벤치마크 Phase1 3패턴 5벌 seed overlay | `datasynth_integrated_usefulness_phase1_20260701_v1g` |
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

### v45~v46b: 단일법인 전환과 관계사 거래 흔적 복구

v45 계열은 입사용 프로젝트 범위에 맞춰 journal을 단일법인 C001 기준으로 정리했다.
다만 단일법인 GL-only 제품이라는 뜻은 관계사 거래가 전혀 없다는 뜻이 아니다.
PHASE1/PHASE2가 `1150`, `4500`, `2050`, `2700` IC 계정을 해석하려면 정상 원장에도 소량의 관계사 거래 흔적이 필요하다.

v46b 기준은 다음과 같다.

- `company_code`는 C001 하나만 존재한다.
- C002/C003는 별도 회사 원장이 아니라 C001의 관계사 `trading_partner`로만 존재한다.
- 정상 IC row는 432행, 216문서, 전체 row share 약 0.12%다.
- IC GL prefix count는 1150=108, 4500=108, 2050=72, 2700=36이다.
- company-node graph cycle은 NORMAL에서 0이다. 순환/부정 graph는 overlay 영역이다.
- `master_data/related_parties.json`과 `intercompany/*.json` sidecar는 정상 trace로 존재한다.
- verifier 결과는 PASS 38 / MONITOR 1 / FAIL 0 / BLOCKED 0이다.

따라서 현재 NORMAL의 핵심 원칙은 "단일법인 C001 원장 + 관계사 거래 흔적 존재 + 회사간 순환 없음"이다.
과거 문서의 "NORMAL에는 관계사/IC 흔적 0" 표현은 폐기한다.

### v47: automated source batch/job identity 복구

v47은 v46b 위에서 자동 생성 계열 전표의 배치 정체성을 복구한 successor다.
`source_trust.py`는 `batch_id`와 `job_id` 중 하나라도 비면 자동 source 위장을 의심하는
`weak_identity` 경로를 켠다. 따라서 automated/recurring 계열에 한쪽만 채우는 것은 hollow fix다.

v47 기준:

- automated/recurring/batch/interface/system 계열 row는 `batch_id`와 `job_id`가 모두 채워진다.
- 같은 배치 실행에 속한 문서는 동일 id를 공유한다.
- manual/adjustment row는 `batch_id`와 `job_id`가 모두 비어 있다.
- `trusted_automated_mask` rate는 0.9761로 회복됐다.
- 정상 realism verifier는 42개 중 PASS 37 / BLOCKED 1 / MONITOR 1 / INFO 3이다.
  BLOCKED는 I05 duplicate artifact import path(`src.detection.duplicate_detector`) 문제로, 이번 batch/job
  변경의 데이터 회귀로 판정하지 않는다.

## PHASE1-1 recall overlay

PHASE1-1 recall overlay는 최신 `docs/spec/DETECTION_RULES.md` 기준 26개 개별 룰의 raw trigger
검증용이다. current accepted dataset은
`datasynth_semantic_v1_recall_20260630_v47_batchid_phase1_1_r1`이다.

핵심 구조:

- truth units 1,500.
- 26 current PHASE1-1 rules x standard/boundary control variants.
- standard 750 / 750 caught.
- boundary control 0 / 750 caught.
- rules 26 / 26.
- shortcut scan findings 0.
- CoA coverage PASS. `999998`은 L1-03 invalid-account standard 문서에만 허용.

주의:

- r11은 PHASE1-1 개별 룰 발화 검증 전용이다.
- combo/tier case 조립 검증과 PHASE2 ML 학습에는 재사용하지 않는다.
- 근거 문서:
  `dev/active/datasynth-journal-realism-rebuild/r11-rule-3way-verification.md`,
  `dev/active/datasynth-journal-realism-rebuild/phase1-rule-recall-overlay-verification.md`.

## PHASE1 combo/tier overlay

combo/tier overlay는 r11 이후 별도로 생성한다.
권위 문서는 `dev/active/phase1-rule-basis-audit/phase1-combo-tier-firing-matrix.md`이다.
current accepted dataset은 `datasynth_semantic_v1_combo_tier_20260630_v47_batchid_r1j`이다.

목적:

- 개별 룰이 켜지는지가 아니라, 같은 case 그룹에서 켜진 룰 조합이 `topic_scoring.py`의
  combo floor와 `compute_topic_tiers()`를 통해 의도한 tier로 승격 또는 비승격되는지 검증한다.
- 생성 단위는 단일 전표가 아니라 `(theme_id, case_key)` case이다.
- flow 포함 combo는 중복쌍, 역분개쌍, 가수금 open item 같은 member 문서가 실제 flow sidecar에
  연결되어 같은 case로 묶여야 한다.

대상:

- buildable combo scheme 13개:
  `HIGH-1`, `HIGH-2`, `HIGH-3`, `HIGH-4`, `HIGH-5`, `HIGH-7`, `HIGH-9`,
  `M-4A-1`, `M-4A-2`, `M-4A-4`, `M-4B-1`, `M-4B-2`, `M-4B-3`.
- control scheme 2개: `LOW`, `CONTEXT`.
- 생성 금지/out-of-scope 4개:
  `HIGH-6`, `HIGH-8`, `HIGH-10`, `M-4A-3`.

필수 truth:

- `combo_scheme_id`
- `case_kind`
- `expected_case_tier`
- `expected_policy_id`
- `expected_topic`
- `expected_rule_ids`
- `expected_detector_outcome`
- `natural_unit_id`
- `member_document_ids`
- `source_contract`

검증:

- static gate: `uv run python tools/scripts/verify_phase1_combo_tier_gate.py --matrix-only`
- dataset gate: `uv run python tools/scripts/verify_phase1_combo_tier_gate.py <PHASE1_COMBO_TIER_DATASET>`
- shortcut scan: `uv run python tools/scripts/scan_overlay_shortcuts.py <PHASE1_COMBO_TIER_DATASET>`
- observed case-builder gate:
  `uv run python tools/scripts/measure_phase1_combo_tier.py <PHASE1_COMBO_TIER_DATASET> --expect-truth-rows 15`

r1l 결과:

- truth rows 15 = buildable combo scheme 13 + LOW 1 + CONTEXT 1.
- expected tier counts: HIGH 6, MEDIUM 7, LOW 1, CONTEXT 1.
- out-of-scope scheme truth 0.
- combo/tier static gate PASS.
- shortcut scan findings 0.
- actual case-builder gate FAIL: passed rows 7 / 15, failed rows 8 / 15.

historical r1l REJECT 원인:

- 일부 flow-based combo에서 `L2-05`가 detector row로는 발화하지만 companion rule과 같은 observed
  case rule set으로 노출되지 않는다.
- 일부 MEDIUM/LOW controls가 normal baseline broad flags 또는 unintended combo legs와 결합해 high case로
  승격된다.
- 따라서 r1l은 accepted combo/tier recall dataset이 아니다.

r1z ACCEPT:

- static combo/tier gate PASS.
- shortcut scan findings 0.
- actual case-builder gate PASS: truth rows 15, passed rows 15, failed rows 0.
- `measure_phase1_combo_tier.py`의 authoritative 기준은 expected combo topic의 actual topic score cut이다.
  최종 case `priority_band`는 정상 broad signal이 같은 case에 섞이면 더 높아질 수 있으므로 combo/tier
  truth 자체의 acceptance 기준으로 쓰지 않는다.

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

현재 gap:

- r4m_h는 accepted PHASE2 fraud overlay지만, 최신 NORMAL v53 account-determination successor 위에서 재생성된 산출물은 아니다.
- v53의 단일법인+관계사 흔적, batch/job identity, RBAC/승인권한, closing semantics, stable-account, account-pair determination 기준을 PHASE2에 반영하려면, r4m_h의 regression/shortcut/full-column/seed gate를 유지한 상태로 base를 v53으로 교체해 재검증해야 한다.
- 이 gap은 r4m_h를 폐기한다는 뜻이 아니라, PHASE2 overlay의 최신 base 동기화가 아직 별도 작업이라는 뜻이다.

## Seed rotation

seed rotation은 단순히 document id나 company label만 바꾸는 것이 아니다.
검증 기준은 `(scheme_id, component_role, local_amount, posting_date, gl_account)` content difference와 scheme-company assignment vector 차이다.

accepted seed set은 다음을 만족해야 한다.

- representative/seed pair의 fraud content 차이가 50% 이상.
- seed끼리 동일 assignment vector가 0.
- density, scheme count, accounting mechanics는 보존.
- seed-only identifier, reference range, amount bucket, support metadata 조합, reversal link surface가 생기지 않음.

## Integrated usefulness Phase1 overlay

통합 쓸모 벤치마크 Phase1 overlay는 별도 목적의 fraud/abnormal 생성물이다. PHASE1-1 개별 룰 recall이나
PHASE1 combo/tier 검증용이 아니다. SoT는
`dev/active/integrated-usefulness-benchmark/GENERATION_HANDOFF.md`와 pattern specs다.

current accepted dataset:

- `data/journal/primary/datasynth_integrated_usefulness_phase1_20260701_v1g`

생성 범위:

- `INJECTION_POPULATION.md`에서 `io=in`, `Ph=1`인 119건.
- seed_0~seed_4 5벌, 총 595 document unit.
- generated patterns:
  - `fabricated_revenue`
  - `expense_capitalization`
  - `account_misclassification`

v1g acceptance:

- label/provenance/surface hint journal 노출 0.
- exact-value oracle findings 0.
- categorical distribution leak findings 0.
- source/batch/job 분포 누수 0.
- `weak_signal=true` row manual 0, batch blank 0.
- `approval_date >= document_date`, `posting_date >= document_date`, `settlement_date >= posting_date`.
- `verify_injection_coherence.py` accidents 0.

v1e~v1g에서 gate로 승격된 회귀:

- v1e: fraud `source=manual` 100%, `batch_id/job_id` blank 100% 분포 누수.
- v1f_b: O2C weak만 고쳐 R2R weak manual 잔존.
- v1f_c: `approval_date < document_date` 관계형 누수.

따라서 향후 같은 overlay를 재생성할 때는 `verify_integrated_usefulness_phase1.py`와
`verify_injection_coherence.py`를 모두 실행한다.

## Integrated usefulness Phase2 overlay

통합 쓸모 벤치마크 Phase2 overlay는 상태 의존 부정/오류 패턴을 만든다. 기존 PHASE2 FS01~FS14 fraud
overlay와 목적이 다르며, SoT는 `dev/active/integrated-usefulness-benchmark` 하위 문서다.

current accepted dataset:

- `data/journal/primary/datasynth_integrated_usefulness_phase2_20260701_v1f`

base:

- `data/journal/primary/datasynth_semantic_v1_normal_20260630_v47_batchid_r7`

생성 범위:

- `INJECTION_POPULATION.md`에서 `io=in`, `Ph=2`인 108건.
- seed_0~seed_4 5벌, 총 truth 540.
- generated patterns:
  - `embezzlement_concealment`
  - `approval_sod`
  - `circular_transaction`

accepted v1f 요약:

- truth documents 1,735.
- embezzlement는 4문서 flow, approval SoD는 1문서, circular는 3문서 graph.
- source pattern coverage: 가공전표, 비용자산화, 계정분류, 횡령은폐, 승인SoD, 순환거래.
- label/provenance/surface hint journal 노출 0.
- exact-value oracle findings 0.
- categorical distribution leak findings 0.
- temporal coherence findings 0.
- broader coherence oracle accidents 0.

v1b~v1f에서 gate로 승격된 회귀:

- event/scenario/header/line/tax 표면값이 fraud-only가 되면 reject.
- `settlement_date < posting_date` 같은 관계형 누수는 reject.
- approval SoD는 `sod_violation=true` 마커가 아니라 `created_by == approved_by` 구조로 표현한다.
- 정상 데이터에 존재하지 않는 actor, partner, clearance key를 만들어 쓰면 reject.

base 제약:

- v47 batch/job normal은 journal 기준 open AR 계정이 없다.
- v1f는 없는 AR을 새로 만들지 않고 실재 open clearing reference를 사용했다.
- normal에 open AR sidecar/journal 표현이 추가되면 Phase2 donor pool을 AR 전용으로 좁힌다.
