# DataSynth 검증과 테스트

## 검증 체계

검증은 목적별로 분리한다.

| 영역 | 검증 목적 | 대표 도구 |
| --- | --- | --- |
| NORMAL realism | 정상 원장이 회계·ERP·감사 데이터로 성립하는지 검증 | `normal_data_realism_verifier_20260603.py`, `audit_balance_integrity.py` |
| PHASE1-1 recall overlay | 개별 룰별 standard/boundary raw trigger와 shortcut 부재 검증 | `audit_overlay_injection.py`, `measure_phase1_detector_catch.py`, `scan_overlay_shortcuts.py` |
| PHASE1 combo/tier overlay | 켜진 룰 조합이 case 단위 HIGH/MEDIUM/LOW/CONTEXT tier로 조립되는지 검증 | `verify_phase1_combo_tier_gate.py`, `measure_phase1_combo_tier.py`, `scan_overlay_shortcuts.py` |
| PHASE2 fraud overlay | 부정 scheme coverage, 회계 실체, shortcut/leak 부재, seed 다양성 검증 | `phase2_shortcut_gate.py`, `verify_phase2_regression.py`, `scan_overlay_shortcuts.py`, `audit_full_leak_scan.py`, `verify_phase2_seed_diversity.py` |
| Integrated usefulness Phase1 overlay | 통합 쓸모 벤치마크 Phase1 3패턴 주입의 label firewall, 분포 누수, 날짜 coherence 검증 | `verify_integrated_usefulness_phase1.py`, `verify_injection_coherence.py` |
| historical quality gates | v126/v2/v3 등 과거 DataSynth 품질·ML fitting 방지 검증 | `tests/datasynth_quality_gate*` |

## NORMAL verifier

판정 모델:

| Verdict | 의미 |
| --- | --- |
| PASS | required fields가 있고 기준을 충족한다 |
| FAIL | required fields가 있고 hard invariant 또는 정상 범위를 위반한다 |
| BLOCKED | required field/master/sidecar가 없어 의미 있는 검사를 할 수 없다 |
| MONITOR | 강제 실패는 아니지만 후속 검토가 필요한 분포 또는 경제성 신호다 |

Gate 순서:

- Gate 0: 정상 전용 데이터 오염 제거, 회계·스키마 기본 불변 조건.
- Gate 1: joint semantics, 생성기 지문, document identity, reversal, IC/graph background.
- Gate 2: 전수 분포, 잔액, 경제성, 보조원장 정합.
- Diagnostic: 전문가/LLM 샘플, root cause attribution, low-support tuple analysis.

v46b acceptance snapshot:

- NORMAL realism verifier: PASS 38 / MONITOR 1 / FAIL 0 / BLOCKED 0.
- Balance audit: TB↔JE PASS, BS equation PASS, carry-forward PASS, subledger PASS.
- Normal contamination: fraud/anomaly/provenance marker 없음.
- Linked normal reversal background: PHASE2 L6 leak 방지용 정상 배경 존재.
- Automated source identity: automated/recurring/batch/interface/system rows have both `batch_id` and
  `job_id`, manual/adjustment rows keep both blank, and `trusted_automated_mask` rate is at least 0.90.
- Single-company scope: `company_code=[C001]` only.
- Related-party IC trace: IC rows 432, IC docs 216, row share 0.001249.
- IC GL coverage: 1150=108, 4500=108, 2050=72, 2700=36.
- Company-node graph cycle: 0.
- IC semantic coherence: B15/B16/H04 checked docs 216, bad docs 0.

## NORMAL 주요 검사 축

- A: 기본 회계 구조. 차대변 균형, 금액 양수/정수, 전표 단위 일관성.
- B: semantic coherence. 계정 subtype, line text family, document type, business process의 joint draw.
- C/D: 시간·분포. 결산월, 주말/심야, 연도 drift, timestamp 분산.
- E: 승인·SoD. NORMAL에는 direct confirmed SoD marker가 없어야 한다.
- F/G/H: 거래처, 계정, description, noise attribution.
- I/J: document number, reference, duplicate artifact, reversal pair.
- K: IC/graph normal background.
- L/M/N: 증빙·세무·잔액·경제성·신규계정 자연화.
- O: normal-only contamination과 synthetic marker scan.
- P: fixed-seed 전문가/LLM diagnostic.
- Source trust fast gate: full PHASE1 measurement 전에 E13 automated source identity와 L2-05
  structural-column preflight를 먼저 본다.

## PHASE1-1 개별 룰 recall 검증

현재 accepted dataset: `datasynth_semantic_v1_recall_20260630_v47_batchid_phase1_1_r1`.

필수 검증:

```powershell
uv run python tools/scripts/audit_overlay_injection.py <PHASE1_RECALL_DATASET>
uv run python tools/scripts/scan_overlay_shortcuts.py <PHASE1_RECALL_DATASET>
uv run python tools/scripts/measure_phase1_detector_catch.py <PHASE1_RECALL_DATASET> --expect-truth-units 1500
```

수락 기준:

- 26 / 26 current PHASE1-1 rules in truth.
- standard 750 / 750 caught.
- boundary control 0 / 750 caught.
- shortcut scan findings 0.
- CoA coverage PASS.
- output distinct docs = base distinct docs.
- report에 per-rule denominator/numerator와 control false positive가 포함.

r11은 detector-only 개별 룰 발화용이다. combo/tier truth는 이 데이터셋에 섞지 않는다.
세부 3자 대조는 `dev/active/datasynth-journal-realism-rebuild/r11-rule-3way-verification.md`와
`dev/active/datasynth-journal-realism-rebuild/phase1-rule-recall-overlay-verification.md`를 따른다.

## PHASE1 combo/tier overlay 검증

combo/tier overlay는 PHASE1-1 개별 룰 발화가 닫힌 뒤 만드는 별도 데이터셋이다.
권위 매트릭스는 `dev/active/phase1-rule-basis-audit/phase1-combo-tier-firing-matrix.md`이다.
현재 accepted dataset은 `datasynth_semantic_v1_combo_tier_20260630_v47_batchid_r1j`이다.

생성 목적:

- 개별 룰이 아니라, 같은 `(theme_id, case_key)` case 안에 켜진 룰 조합이
  `topic_scoring.py`의 combo floor와 `compute_topic_tiers()`를 통해 의도한 tier로 조립되는지 검증한다.
- HIGH/MEDIUM combo 13개 in-scope scheme, LOW standalone primary, CONTEXT booster-only negative case를
  별도 truth로 가진다.
- GL-only 범위 밖인 `HIGH-6`, `HIGH-8`, `HIGH-10`, `§4a-3 split-invoice`는 억지 생성하지 않는다.

사전 static gate:

```powershell
uv run python tools/scripts/verify_phase1_combo_tier_gate.py --matrix-only
```

생성 후 필수 검증:

```powershell
uv run python tools/scripts/verify_phase1_combo_tier_gate.py <PHASE1_COMBO_TIER_DATASET>
uv run python tools/scripts/scan_overlay_shortcuts.py <PHASE1_COMBO_TIER_DATASET>
uv run python tools/scripts/measure_phase1_combo_tier.py <PHASE1_COMBO_TIER_DATASET> --expect-truth-rows 15
```

수락 기준:

- `DEFAULT_COMBO_FLOORS`의 12개 policy가 매트릭스와 일치.
- `verify_phase1_combo_tier_gate.py`가 L2-05 structural-reference preflight를 통과한다.
  - measurement harness `PHASE1_USECOLS`에는 `original_document_id`, `reversal_document_id`,
    `reference_document_id`, `reversed_document_id`, `reverse_document_id`, `reversal_reason`,
    `reversal_reason_code`가 있어야 한다.
  - dataset journal에는 최소 `original_document_id`, `reversal_document_id`, `reversal_reason`,
    `reversal_reason_code`가 있어야 한다.
- in-scope buildable scheme 13개 + `LOW` + `CONTEXT` truth가 존재.
- out-of-scope scheme 4개가 truth에 존재하지 않음.
- 각 combo truth의 `expected_rule_ids`가 r11 26룰 안에 있고, policy별 필수 all/any leg를 충족.
- `expected_case_tier`, `expected_policy_id`, `expected_topic`이 매트릭스와 일치.
- standard case는 기대 rule set이 실제 case-builder 후보 case에 잡히고, 기대 topic score가
  expected tier cut 이상이어야 한다. 최종 `priority_band`는 같은 case에 섞인 독립 broad signal 때문에
  더 높아질 수 있으므로 combo/tier acceptance의 유일 기준으로 쓰지 않는다.
- boundary/negative case는 의도한 하위 tier 또는 CONTEXT로 떨어진다.
- shortcut scan findings 0.

r1i rejection snapshot:

- `uv run python tools/scripts/verify_phase1_combo_tier_gate.py data/journal/primary/datasynth_semantic_v1_combo_tier_20260622_v46b_r1i`
  PASS.
- `uv run python tools/scripts/scan_overlay_shortcuts.py data/journal/primary/datasynth_semantic_v1_combo_tier_20260622_v46b_r1i`
  findings 0.
- `uv run python tools/scripts/measure_phase1_combo_tier.py data/journal/primary/datasynth_semantic_v1_combo_tier_20260622_v46b_r1i --expect-truth-rows 15`
  FAIL: passed rows 1 / 15, failed rows 14 / 15.
- truth rows 15: 13 buildable combo schemes, LOW control, CONTEXT control.
- expected tier counts: HIGH 6, MEDIUM 7, LOW 1, CONTEXT 1.

결론: static truth gate와 shortcut scan만으로는 combo/tier acceptance가 아니다. r1i는 member rule
legs를 같은 observed case에 엮지 못했고, LOW/CONTEXT controls도 full case-builder 실행 후 high로
승격되는 문제가 있어 accepted dataset으로 쓰면 안 된다.

r1l rejection snapshot:

- `uv run python tools/scripts/verify_phase1_combo_tier_gate.py data/journal/primary/datasynth_semantic_v1_combo_tier_20260622_v46b_r1l`
  PASS.
- `uv run python tools/scripts/scan_overlay_shortcuts.py data/journal/primary/datasynth_semantic_v1_combo_tier_20260622_v46b_r1l`
  findings 0.
- `uv run python tools/scripts/measure_phase1_combo_tier.py data/journal/primary/datasynth_semantic_v1_combo_tier_20260622_v46b_r1l --expect-truth-rows 15`
  FAIL: passed rows 7 / 15, failed rows 8 / 15.
- r1l closes the r1j surface leaks and improves natural case grouping, but still fails actual
  case-builder acceptance:
  - related-party reversal and suspense reversal flow combos do not consistently expose `L2-05` with
    the companion rule in the same observed case.
  - selected MEDIUM/LOW controls still become HIGH after full case-builder scoring.

r1z acceptance snapshot:

- `uv run python tools/scripts/verify_phase1_combo_tier_gate.py data/journal/primary/datasynth_semantic_v1_combo_tier_20260622_v46b_r1z`
  PASS.
- `uv run python tools/scripts/scan_overlay_shortcuts.py data/journal/primary/datasynth_semantic_v1_combo_tier_20260622_v46b_r1z`
  findings 0.
- `uv run python tools/scripts/measure_phase1_combo_tier.py data/journal/primary/datasynth_semantic_v1_combo_tier_20260622_v46b_r1z --expect-truth-rows 15`
  PASS: truth rows 15, passed rows 15, failed rows 0.
- `measure_phase1_combo_tier.py` now evaluates actual case-builder topic score cut for the expected
  combo topic rather than requiring the final case `priority_band` to equal the expected combo tier.
  This prevents unrelated broad signals in the same case from turning a correctly surfaced MEDIUM
  combo into a false REJECT.

v47 batch/job successor acceptance snapshot:

- `uv run python tools/scripts/verify_phase1_combo_tier_gate.py data/journal/primary/datasynth_semantic_v1_combo_tier_20260630_v47_batchid_r1j`
  PASS.
- `uv run python tools/scripts/scan_overlay_shortcuts.py data/journal/primary/datasynth_semantic_v1_combo_tier_20260630_v47_batchid_r1j`
  findings 0.
- `uv run python tools/scripts/measure_phase1_combo_tier.py data/journal/primary/datasynth_semantic_v1_combo_tier_20260630_v47_batchid_r1j --expect-truth-rows 15`
  PASS: truth rows 15, passed rows 15, failed rows 0.
- `profile_phase1_v126.PHASE1_USECOLS` must include L2-05 structural-reference fields:
  `original_document_id`, `reversal_document_id`, `reference_document_id`, `reversed_document_id`,
  `reverse_document_id`, `reversal_reason`, `reversal_reason_code`.
  If these fields are dropped by the measurement harness, valid ERP-link reversal docs are false
  rejected as missing `L2-05` even though the raw dataset is correct.

Current acceptance is open: r1j is the accepted PHASE1 combo/tier overlay.

## PHASE2 overlay 검증

운영 기준은 [Fraud Overlay Realism Gate](./fraud-overlay-realism-gate.md)를 따른다.

현재 accepted dataset: `datasynth_semantic_v1_phase2_fraud_20260614_v1_r4m_h`와 `..._seed1`.

주의: 이 PHASE2 accepted overlay는 v47 batch/job successor NORMAL 기준으로 재생성된 산출물이 아니다.
최신 NORMAL과 PHASE2를 동기화할 때는 아래 gate를 동일하게 적용하되, base path를 v47로 바꾸고
normal twin/IC trace 분포가 새 base와 충돌하지 않는지 다시 확인한다.

필수 검증 명령:

```powershell
uv run python tools/scripts/phase2_shortcut_gate.py `
  <PHASE2_DATASET> `
  <PHASE2_SCALE_REFERENCE>

uv run python tools/scripts/audit_balance_integrity.py `
  <NORMAL_BASE>

uv run python tools/scripts/verify_phase2_regression.py `
  <PHASE2_DATASET> `
  <NORMAL_BASE>

uv run python tools/scripts/scan_overlay_shortcuts.py `
  <PHASE2_DATASET>

uv run python tools/scripts/audit_full_leak_scan.py `
  <PHASE2_DATASET>

uv run python tools/scripts/verify_phase2_seed_diversity.py `
  <PHASE2_DATASET> `
  <SEED1> `
  <SEED2> `
  <SEED3> `
  <SEED4> `
  <SEED5>

uv run python tools/scripts/audit_full_leak_scan.py `
  <SEED1>
```

수락 기준:

- shortcut gate 17/17 PASS, FAIL 0.
- normal base balance audit PASS.
- regression: base unchanged 0, label consistency 0/0/0, 14 schemes present, self-cancel 0, fraud imbalance 0.
- surface shortcut scan findings 0.
- full-column leak scan NEW leak candidates 0.
- representative와 seed pair diversity PASS.
- 최소 seed1에서도 full-column scan PASS.

## Full-column leak scan

`audit_full_leak_scan.py`는 2026-06-14에 추가된 전수 누출 스캔이다.
기존 shortcut gate는 사람이 의심한 컬럼만 검사했기 때문에 `semantic_account_subtype`, auxiliary fields, reversal link 같은 미등록 표면을 놓칠 수 있었다.

스캔 차원:

- 범주형 값별 fraud-only 또는 high precision/high recall.
- null/populated rule.
- 수치형 반복값과 round amount bucket.
- 시각 집중.
- 전체 컬럼 결측률 차.
- 2컬럼 조합.

1차 도구 결과 19건 중 10건은 결측률 차이만 큰 false positive로 판정됐다.
현재 도구는 precision >= 25% 또는 recall >= 25% 및 lift >= 5 같은 식별력 가드를 적용한다.

r4l_b에서 재현된 진짜 누출:

- L4: `trading_partner=V-000001` concentration.
- L5a/L5b: `invoice_amount`, `supply_amount`, `auxiliary_account_number` nullness.
- L5c: fraud-only `(event_type, supporting_doc_type)` 조합.
- L6: `original_document_id` non-null이 overlay-only.
- L7: 일부 exact round amount marker.

r4m_h는 이 누출을 제거해 representative와 seed1 모두 NEW leak candidates 0을 달성했다.

## Integrated Usefulness Phase1 overlay 검증

현재 accepted dataset: `datasynth_integrated_usefulness_phase1_20260701_v1g`.

이 overlay는 PHASE1 detector recall용이 아니라 통합 쓸모 벤치마크의 Phase1 3패턴
`fabricated_revenue`, `expense_capitalization`, `account_misclassification` 생성 정합을 검증한다.
검증은 rule-blind generation mechanics와 coherence를 본다.

필수 검증 명령:

```powershell
uv run python tools/scripts/verify_injection_coherence.py --self-test

uv run python tools/scripts/verify_integrated_usefulness_phase1.py `
  <IUB_PHASE1_DATASET> `
  --base <NORMAL_BASE>

uv run python tools/scripts/verify_injection_coherence.py `
  <IUB_PHASE1_DATASET>
```

수락 기준:

- truth rows 595.
- seed_0~seed_4 각각 119.
- generated pattern 3종 모두 존재.
- journal label/provenance/surface hint 노출 0.
- CoA orphan 0.
- truth docs balanced.
- same-document same-GL debit/credit self-cancel 0.
- exact-value oracle findings 0.
- categorical distribution leak findings 0.
- temporal coherence findings 0.
- `verify_injection_coherence.py` accidents 0.

최근 gate 승격:

- `source=manual` 100% 및 `batch_id/job_id` blank 100% 분포 누수는
  `verify_integrated_usefulness_phase1.py`의 distribution scan으로 막는다.
- `weak_signal=true` 행은 manual/blank batch artifact가 없어야 한다.
- `approval_date < document_date`, `posting_date < document_date`, `settlement_date < posting_date`는
  temporal coherence failure다.
- 더 넓은 사고 검사는 `verify_injection_coherence.py`로 별도 실행한다. 이 오라클은 `--self-test`가
  PASS해야 사용한다.

## Integrated Usefulness Phase2 overlay 검증

현재 accepted dataset: `datasynth_integrated_usefulness_phase2_20260701_v1f`.

이 overlay는 통합 쓸모 벤치마크의 Phase2 상태의존 3패턴을 검증한다. PHASE1 detector recall용이나
기존 FS01~FS14 PHASE2 fraud overlay가 아니다. SoT는
`dev/active/integrated-usefulness-benchmark/GENERATION_HANDOFF.md`,
`INJECTION_POPULATION.md`, `pattern_specs/04~06`이다.

필수 검증 명령:

```powershell
uv run python tools/scripts/verify_injection_coherence.py --self-test

uv run python tools/scripts/verify_integrated_usefulness_phase2.py `
  <IUB_PHASE2_DATASET> `
  --base <NORMAL_BASE>

uv run python tools/scripts/verify_injection_coherence.py `
  <IUB_PHASE2_DATASET>
```

수락 기준:

- truth rows 540.
- seed_0~seed_4 각각 108.
- Phase2 generated pattern 3종 모두 존재.
- 원천 6패턴 coverage 모두 존재.
- journal label/provenance/surface hint 노출 0.
- CoA orphan 0.
- truth docs balanced.
- exact-value oracle findings 0.
- categorical distribution leak findings 0.
- temporal coherence findings 0.
- `verify_injection_coherence.py` accidents 0.

최근 gate 승격:

- direct marker 금지: `is_fraud`, `fraud_type`, `mutation_*`, `detection_surface_hints`는 journal 미노출.
- fraud-only 표면값 금지: source, batch/job, event/scenario, header/line text, tax treatment, settlement date.
- 관계형 날짜 누수 금지: approval/document/posting/settlement 순서 위반 0.
- 상태참조: original document id 실존, cleared reference 정합, open item 유지.
- approval SoD는 직접 마커가 아니라 `created_by == approved_by` 관계로 표현하며, actor는 정상 데이터에서
  실제로 등장하는 사용자여야 한다.

## Historical quality gates

과거 품질 게이트는 현재 accepted lineage의 직접 수락 기준은 아니지만, regression 설계의 근거다.

- `tests/datasynth_quality_gate/results/quality_report.md`: 구조적 무결성, 도메인, cross-reference, distribution, label, metadata.
- `tests/datasynth_quality_gate2/results/ml_fitting_report.md`: feature leakage, distribution realism, cross-field consistency, reverse leakage, compound leakage, line-level GL pair.
- `tests/datasynth_quality_gate3/results/realism_report.md`: 기본 무결성, 정량 벤치마크, 의미 정합성, 교차 필드, 메타데이터.

이 문서들에는 v126/v2/v3 계열 수치가 남아 있다.
현행 NORMAL v47 batch/job successor, PHASE1 recall v47, PHASE1 combo/tier r1j, PHASE2 r4m 설명에는 최신 verifier와 2026-06-14 full-column leak 결과를 우선 적용한다.

## 완료 전 체크

DataSynth 생성 작업은 다음을 모두 확인해야 완료다.

- 생성 profile과 source/output이 현재 목적과 맞는지 확인.
- output directory가 기존 accepted dataset을 덮어쓰지 않는지 확인.
- NORMAL/PHASE1/PHASE2 목적별 필수 게이트를 실행.
- 실패한 게이트가 있으면 데이터 수정 또는 gate 문서 갱신. 임계값 완화는 명시 승인 없이는 금지.
- `docs/debugging.md`에 accepted lineage, 실패 lineage, 수정, 검증 결과를 기록.
- 관련 `docs/datasynth` 문서와 원천 카탈로그를 최신화.
