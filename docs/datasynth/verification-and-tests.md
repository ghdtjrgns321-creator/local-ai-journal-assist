# DataSynth 검증과 테스트

## 검증 체계

검증은 목적별로 분리한다.

| 영역 | 검증 목적 | 대표 도구 |
| --- | --- | --- |
| NORMAL realism | 정상 원장이 회계·ERP·감사 데이터로 성립하는지 검증 | `normal_data_realism_verifier_20260603.py`, `audit_balance_integrity.py` |
| PHASE1 recall overlay | 룰별 standard/boundary raw trigger와 shortcut 부재 검증 | `audit_overlay_injection.py`, `measure_phase1_detector_catch.py`, `scan_overlay_shortcuts.py` |
| PHASE2 fraud overlay | 부정 scheme coverage, 회계 실체, shortcut/leak 부재, seed 다양성 검증 | `phase2_shortcut_gate.py`, `verify_phase2_regression.py`, `scan_overlay_shortcuts.py`, `audit_full_leak_scan.py`, `verify_phase2_seed_diversity.py` |
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

v43d acceptance snapshot:

- NORMAL realism verifier: PASS 33 / MONITOR 1 / FAIL 0.
- Balance audit: TB↔JE PASS, BS equation PASS, carry-forward PASS, subledger PASS.
- Normal contamination: fraud/anomaly/provenance marker 없음.
- Linked normal reversal background: PHASE2 L6 leak 방지용 정상 배경 존재.

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

## PHASE1 recall 검증

현재 accepted dataset: `datasynth_semantic_v1_recall_20260613_v42j_r3`.

필수 검증:

```powershell
uv run python tools/scripts/audit_overlay_injection.py <PHASE1_RECALL_DATASET>
uv run python tools/scripts/scan_overlay_shortcuts.py <PHASE1_RECALL_DATASET>
uv run python tools/scripts/measure_phase1_detector_catch.py <PHASE1_RECALL_DATASET> --expect-truth-units 2160
```

수락 기준:

- 39 / 39 rules in truth.
- standard 1,080 / 1,080 caught.
- boundary control 0 / 1,080 caught.
- shortcut scan findings 0.
- CoA coverage PASS.
- output distinct docs = base distinct docs.
- report에 per-rule denominator/numerator와 control false positive가 포함.

v42j_r2는 detector recall 수치만 보면 통과했지만 CoA coverage gate에서 실패했다.
이후 CoA gate는 필수 수락 기준으로 승격됐다.

## PHASE2 overlay 검증

현재 accepted dataset: `datasynth_semantic_v1_phase2_fraud_20260614_v1_r4m_h`와 `..._seed1`.

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

## Historical quality gates

과거 품질 게이트는 현재 accepted lineage의 직접 수락 기준은 아니지만, regression 설계의 근거다.

- `tests/datasynth_quality_gate/results/quality_report.md`: 구조적 무결성, 도메인, cross-reference, distribution, label, metadata.
- `tests/datasynth_quality_gate2/results/ml_fitting_report.md`: feature leakage, distribution realism, cross-field consistency, reverse leakage, compound leakage, line-level GL pair.
- `tests/datasynth_quality_gate3/results/realism_report.md`: 기본 무결성, 정량 벤치마크, 의미 정합성, 교차 필드, 메타데이터.

이 문서들에는 v126/v2/v3 계열 수치가 남아 있다.
현행 semantic v43/r4m 설명에는 최신 verifier와 2026-06-14 full-column leak 결과를 우선 적용한다.

## 완료 전 체크

DataSynth 생성 작업은 다음을 모두 확인해야 완료다.

- 생성 profile과 source/output이 현재 목적과 맞는지 확인.
- output directory가 기존 accepted dataset을 덮어쓰지 않는지 확인.
- NORMAL/PHASE1/PHASE2 목적별 필수 게이트를 실행.
- 실패한 게이트가 있으면 데이터 수정 또는 gate 문서 갱신. 임계값 완화는 명시 승인 없이는 금지.
- `docs/debugging.md`에 accepted lineage, 실패 lineage, 수정, 검증 결과를 기록.
- 관련 `docs/datasynth` 문서와 원천 카탈로그를 최신화.

