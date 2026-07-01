# DataSynth Fraud Overlay Realism Gate

이 문서는 fraud/abnormal overlay DataSynth의 회계 실질, shortcut 방지, label firewall, seed 다양성
수락 기준을 모은 운영 SoT다. NORMAL realism gate와 PHASE1 recall/combo gate와 분리한다.

## 적용 범위

| 계층 | 적용 gate |
| --- | --- |
| PHASE1-1 recall overlay | 개별 룰 standard/boundary raw trigger 검증, shortcut scan, CoA/orphan 검증 |
| PHASE1 combo/tier overlay | combo matrix 정합, case-builder observed tier 검증, shortcut scan |
| PHASE2 fraud overlay | 14개 fraud scheme coverage, 회계 실질, full-column leak scan, seed diversity |
| Integrated usefulness benchmark Phase1 overlay | 5벌 seed, 119건/seed, label firewall, 분포 누수, 날짜 coherence |

## 공통 원칙

- Rust generator에서 고친다. Python CSV 후처리로 데이터를 맞추지 않는다.
- detector 성능을 보고 주입 파라미터를 조정하지 않는다.
- truth/provenance/surface hint는 journal/master feature 입력으로 새지 않는다.
- 정상/부정 표면 필드는 정상 donor의 실제 조합을 상속한다. 독립 marginal sampling으로 정상에 없는 조합
  셀을 만들지 않는다.
- 반복 결함이 나오면 해당 검사를 gate로 승격한 뒤 다음 suffix를 생성한다.
- 빈 집합 PASS, hollow PASS, threshold 완화는 수락하지 않는다.

## PHASE1-1 Recall Overlay Gate

현재 accepted lineage:

- `data/journal/primary/datasynth_semantic_v1_recall_20260630_v47_batchid_phase1_1_r1`

필수 명령:

```powershell
uv run python tools/scripts/audit_overlay_injection.py <PHASE1_RECALL_DATASET>
uv run python tools/scripts/scan_overlay_shortcuts.py <PHASE1_RECALL_DATASET>
uv run python tools/scripts/measure_phase1_detector_catch.py <PHASE1_RECALL_DATASET> --expect-truth-units 1500
```

수락 기준:

- current PHASE1-1 rules 26/26.
- truth units 1,500.
- standard 750/750 caught.
- boundary control 0/750 caught.
- shortcut findings 0.
- CoA orphan 0. `999998`은 L1-03 invalid-account standard 전용일 때만 허용한다.

회귀로 gate에 박힌 항목:

- L1-03 외 룰에서 없는 계정을 쓰면 FAIL. `15110`, `25110`, `7600`, `8010`, `999998` 같은 계정은
  목적에 맞게 CoA 또는 invalid-account truth로 분리한다.
- source/batch/job 표면이 부정 전용이면 FAIL.
- boundary control이 detector에 잡히면 FAIL.

## PHASE1 Combo/Tier Overlay Gate

현재 accepted lineage:

- `data/journal/primary/datasynth_semantic_v1_combo_tier_20260630_v47_batchid_r1j`

필수 명령:

```powershell
uv run python tools/scripts/verify_phase1_combo_tier_gate.py --matrix-only
uv run python tools/scripts/verify_phase1_combo_tier_gate.py <PHASE1_COMBO_TIER_DATASET>
uv run python tools/scripts/scan_overlay_shortcuts.py <PHASE1_COMBO_TIER_DATASET>
uv run python tools/scripts/measure_phase1_combo_tier.py <PHASE1_COMBO_TIER_DATASET> --expect-truth-rows 15
```

수락 기준:

- buildable combo 13 + LOW + CONTEXT truth 15.
- out-of-scope combo truth 0.
- matrix/static gate PASS.
- shortcut findings 0.
- actual case-builder observed gate 15/15.
- acceptance는 final `priority_band` equality가 아니라 expected topic score cut 충족 여부로 판단한다.

회귀로 gate에 박힌 항목:

- L2-05 structural-reference fields가 measurement harness에서 누락되면 FAIL.
- flow-based combo는 실제 sidecar membership이 case-builder에 보여야 한다.
- LOW/CONTEXT가 unintended broad signal로 HIGH 승격되면 REJECT다.

## PHASE2 Fraud Overlay Gate

현재 accepted lineage:

- `data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260614_v1_r4m_h`
- seed check: `..._r4m_h_seed1`
- scale reference: `data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260613_v1_r4l_b`

주의: r4m_h는 accepted fraud overlay지만 최신 NORMAL v47 batch/job successor 위에서 재생성된 산출물은
아니다. 다음 PHASE2 fraud overlay는 v47 또는 그 successor base 위에서 아래 gate를 다시 통과해야 한다.

필수 명령:

```powershell
uv run python tools/scripts/phase2_shortcut_gate.py <PHASE2_DATASET> <PHASE2_SCALE_REFERENCE>
uv run python tools/scripts/audit_balance_integrity.py <NORMAL_BASE>
uv run python tools/scripts/verify_phase2_regression.py <PHASE2_DATASET> <NORMAL_BASE>
uv run python tools/scripts/scan_overlay_shortcuts.py <PHASE2_DATASET>
uv run python tools/scripts/audit_full_leak_scan.py <PHASE2_DATASET>
uv run python tools/scripts/verify_phase2_seed_diversity.py <REPRESENTATIVE> <SEED1> <SEED2> <SEED3> <SEED4> <SEED5>
uv run python tools/scripts/audit_full_leak_scan.py <SEED1>
```

수락 기준:

- `phase2_shortcut_gate.py`: 모든 gate PASS, FAIL 0.
- `verify_phase2_regression.py`: base unchanged 0, label consistency 0/0/0, 14 schemes present,
  self-cancel 0, fraud imbalance 0.
- `scan_overlay_shortcuts.py`: findings 0.
- `audit_full_leak_scan.py`: representative와 최소 seed1에서 NEW leak candidates 0.
- `verify_phase2_seed_diversity.py`: pairwise fraud-content difference 50% 이상, identical assignment vector 0.

필수 회계 실질 gate:

- 같은 문서 안 같은 GL 차변/대변 자기상쇄 0.
- 같은 계정 same-side split으로 라인 수를 채우는 fitting 0.
- scheme별 계정 subtype은 catalog whitelist와 일치.
- FS01/FS05/FS09 매출 효과, FS03 현금 유출, FS07 재고/COGS 효과, FS11 IC 비대칭 등 scheme별 경제 효과가
  실제 분개에 남아야 한다.
- FS10/FS12/FS13 부작위 금액은 작위 거래 규모에서 파생하고 상수 복사 금지.
- FS03은 초기 소액에서 후기 대액으로 점증하되 누적 규모를 reference 대비 0.5~2.0배 범위로 보존한다.
- FS01 반복 외부 고객, FS03 점증 출금, FS05 3-company circular chain 같은 구조 floor를 shortcut 제거로
  지우면 FAIL.

필수 shortcut/leak gate:

- single-column shortcut: precision/recall/lift 기준을 넘는 표면값, nullness, format, range 없음.
- multi-column combination: 정상에 없는 source/user/document/counterparty 조합 셀 없음.
- full-column leak: trading_partner concentration, auxiliary nullness, event/supporting_doc fraud-only cell,
  reversal-link non-null overlay boundary, exact round amount bucket 없음.
- document id, document number, reference, batch/job id는 정상 형식과 같은 generator/donor 표면을 사용한다.
- `is_synthetic`, `is_mutated`, `line_number`, `ledger`, `anomaly_type`은 S2/S15 gate 대상이다.
- seed rotation은 document id만 바꾸면 FAIL. 금액, 날짜, 고객/거래처, 회사/partner 배치가 content 기준으로
  달라져야 한다.

## Integrated Usefulness Benchmark Phase1 Gate

현재 accepted lineage:

- `data/journal/primary/datasynth_integrated_usefulness_phase1_20260701_v1g`

필수 명령:

```powershell
uv run python tools/scripts/verify_injection_coherence.py --self-test
uv run python tools/scripts/verify_integrated_usefulness_phase1.py <IUB_PHASE1_DATASET> --base <NORMAL_BASE>
uv run python tools/scripts/verify_injection_coherence.py <IUB_PHASE1_DATASET>
```

수락 기준:

- truth rows 595.
- seed_0~seed_4 각각 119.
- Phase1 generated patterns 3종 존재: fabricated_revenue, expense_capitalization, account_misclassification.
- journal label/provenance/surface hint 노출 0.
- CoA orphan 0.
- truth docs document balance 0.
- exact-value oracle findings 0.
- categorical distribution leak findings 0.
- temporal coherence findings 0.
- broader injection coherence oracle accidents 0.

회귀로 gate에 박힌 항목:

- v1e: `source=manual` 100%, `batch_id/job_id` blank 100% 분포 누수. `verify_integrated_usefulness_phase1.py`
  distribution scan으로 방지한다.
- v1f_b: weak O2C만 고쳐 R2R weak manual이 잔존. weak_signal 전체에서 manual/blank batch artifact를
  금지한다.
- v1f_c: `approval_date < document_date` temporal relation leak. `verify_integrated_usefulness_phase1.py`
  temporal check와 `verify_injection_coherence.py`로 방지한다.

## Integrated Usefulness Benchmark Phase2 Gate

현재 accepted lineage:

- `data/journal/primary/datasynth_integrated_usefulness_phase2_20260701_v1f`

필수 명령:

```powershell
uv run python tools/scripts/verify_injection_coherence.py --self-test
uv run python tools/scripts/verify_integrated_usefulness_phase2.py <IUB_PHASE2_DATASET> --base <NORMAL_BASE>
uv run python tools/scripts/verify_injection_coherence.py <IUB_PHASE2_DATASET>
```

수락 기준:

- truth rows 540.
- seed_0~seed_4 각각 108.
- Phase2 generated patterns 3종 존재:
  - `embezzlement_concealment`
  - `approval_sod`
  - `circular_transaction`
- 원천 6패턴 coverage 존재:
  가공전표, 비용자산화, 계정분류, 횡령은폐, 승인SoD, 순환거래.
- natural unit shape:
  - 횡령은폐는 2개 이상 member docs, accepted v1f는 4개.
  - 승인SoD는 1개 이상 member docs.
  - 순환거래는 3개 이상 member docs, accepted v1f는 3개.
- journal label/provenance/surface hint 노출 0.
- CoA orphan 0.
- truth docs document balance 0.
- exact-value oracle findings 0.
- categorical distribution leak findings 0.
- temporal coherence findings 0.
- `verify_injection_coherence.py` accidents 0.

회귀로 gate에 박힌 항목:

- `source`, `batch_id`, `tax_treatment`, `event_type`, `semantic_scenario_id`, `header_text`, `line_text` 같은
  표면값은 fraud-only 값이 되면 FAIL이다. donor 정상 표면을 상속한다.
- `approval_date < document_date`, `posting_date < document_date`, `settlement_date < posting_date`는 FAIL이다.
- approval SoD는 `sod_violation=true` 같은 직접 마커를 쓰지 않고 `created_by == approved_by` 관계로 표현한다.
- approval actor는 정상 데이터에서 `created_by`와 `approved_by` 양쪽에 실제 등장하는 사용자만 사용한다.
- clearing은 실재 normal open reference를 사용해야 한다. 없는 AR/clearing key를 만들어 갚으면
  `verify_injection_coherence.py`의 `INV-CLEAR`/`INV-AR-EXISTS`에서 FAIL이다.

알려진 base 제약:

- v47 batch/job normal에는 journal 기준 `amount_open > 0`인 AR 계정이 없다.
- accepted v1f는 없는 AR을 새로 만들지 않고, 현행 coherence oracle이 검증하는 실재 open clearing
  reference를 사용했다.
- 향후 normal에 실재 open AR 표현이 추가되면 Phase2 donor pool을 AR 전용으로 좁혀야 한다.

## 완료 전 공통 체크리스트

- 목적 계층과 base dataset이 맞는지 확인한다.
- accepted dataset을 덮어쓰지 않는다.
- generator profile과 output suffix를 기록한다.
- 해당 계층 필수 gate를 모두 실행한다.
- FAIL이 있으면 완료 선언하지 않고 다음 suffix에서 수정한다.
- `docs/debugging.md`, `docs/datasynth/verification-and-tests.md`, 이 문서를 함께 갱신한다.
