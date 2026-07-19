# DataSynth Agent Runbook

이 문서는 새 에이전트가 DataSynth 작업을 수행할 때 따르는 실행 절차서다.
`docs/datasynth`만 읽고도 NORMAL, PHASE1-1 recall, PHASE1 combo/tier, PHASE2 fraud overlay를 어디서 시작하고 어떤 gate로 끝내야 하는지 알 수 있게 한다.

## 1. 공통 규칙

### 1.1 작업 전 확인

1. 현재 요청이 어느 계층인지 분류한다.
   - NORMAL base.
   - PHASE1-1 개별 룰 recall.
   - PHASE1 combo/tier case assembly.
   - PHASE2 fraud scheme overlay.
   - Integrated usefulness benchmark overlay.
2. 기존 accepted dataset을 덮어쓰지 않는다.
3. Rust generator를 고친다. Python CSV 후처리로 생성 결함을 덧대지 않는다.
4. detector 성능을 보고 주입을 맞추지 않는다. 데이터 realism, 회계 실체, shortcut gate 실패만 피드백으로 사용한다.
5. REJECT가 나오면 멈추지 않는다. 실패 원인을 generator 또는 gate 정의 문제로 분류하고 다음 suffix로 반복한다.
6. 완료 후 `docs/debugging.md`와 `docs/datasynth`를 갱신한다.

### 1.2 공통 Rust 확인

```powershell
cd tools/datasynth
cargo check -p datasynth-cli
```

Rust 파일을 고쳤으면 최소한 위 명령은 실행한다.
profile 추가나 CLI argument parsing을 고쳤으면 관련 `cargo test`가 있으면 같이 실행한다.

### 1.3 공통 shortcut 검사

overlay dataset은 항상 다음을 실행한다.

```powershell
uv run python tools/scripts/scan_overlay_shortcuts.py <DATASET>
```

PHASE2 fraud overlay는 추가로 full-column leak scan이 필요하다.

```powershell
uv run python tools/scripts/audit_full_leak_scan.py <PHASE2_DATASET>
```

## 2. NORMAL base runbook

### 2.1 현재 기준

현재 accepted NORMAL:

`data/journal/primary/datasynth_semantic_v1_normal_20260703_v53_account_determination_r6`

역할:

- next PHASE1-1 recall과 PHASE1 combo/tier 재생성의 base.
- 다음 PHASE2 fraud overlay의 target base.

### 2.2 생성 profile

```powershell
cargo run -p datasynth-cli --bin datasynth-data -- generate `
  --profile normal-coa-v42 `
  --manipulation-source <SOURCE_NORMAL_OR_BASE> `
  --output <NORMAL_OUTPUT>
```

주의:

- profile 이름은 `normal-coa-v42`지만 현행 v53 materialization도 이 계열 함수에서 확장된다.
- 출력 이름은 새 버전 suffix를 사용한다. 기존 accepted path를 덮어쓰지 않는다.

### 2.3 필수 gate

```powershell
uv run python tools/scripts/normal_data_realism_verifier_20260603.py <NORMAL_OUTPUT>
```

현행 v53 필수 확인:

- `E05B_RBAC_PERSONA_PROCESS_SCOPE` PASS.
- `E05C_APPROVER_MASTER_AUTHORITY` PASS.
- E05C approval-limit exceeded rate is nonzero and bounded.
- `M14_ANNUAL_CLOSING_SEMANTIC_CONSISTENCY` PASS.
- `C07_STABLE_ACCOUNT_YOY_VOLATILITY` PASS.
- `C06_ACCOUNT_PAIR_REUSE` PASS.
- O02 synthetic marker 0.

```powershell
uv run python tools/scripts/audit_balance_integrity.py <NORMAL_OUTPUT>
```

필수 수락 기준:

- FAIL 0, BLOCKED 0.
- balance audit PASS.
- fraud/anomaly/provenance contamination 0.
- `company_code`는 C001 하나.
- 정상 IC trace는 존재한다.
- company-node graph cycle은 0.
- annual closing semantic label 불일치 0.
- 안정 계정 YoY 급변 pair 0.
- recurring/automated 계정쌍 희소쌍 과발화 0.
- synthetic marker scan findings 0.

### 2.4 v46b K gate 기준

- IC rows > 0.
- IC docs > 0.
- `1150`, `4500`, `2050`, `2700` GL prefix가 모두 존재.
- C002/C003 partner row는 IC row에서만 허용.
- C001 self partner row는 0.
- related-party sidecar와 intercompany sidecar가 trace로 존재.

## 3. PHASE1-1 recall runbook

### 3.1 현재 기준

Accepted dataset:

`data/journal/primary/datasynth_semantic_v1_recall_20260630_v47_batchid_phase1_1_r1`

Base:

`data/journal/primary/datasynth_semantic_v1_normal_20260630_v47_batchid_r1`

SoT:

- `docs/spec/DETECTION_RULES.md`
- `dev/active/phase1-rule-basis-audit/phase1-rule-firing-matrix.md`
- `dev/active/datasynth-journal-realism-rebuild/r11-rule-3way-verification.md`

### 3.2 생성 profile

```powershell
cargo run --manifest-path tools/datasynth/Cargo.toml -p datasynth-cli -- generate `
  --profile phase1-recall-overlay `
  --manipulation-source data/journal/primary/datasynth_semantic_v1_normal_20260630_v47_batchid_r1 `
  --output <PHASE1_RECALL_OUTPUT>
```

### 3.3 필수 gate

```powershell
uv run python tools/scripts/audit_overlay_injection.py <PHASE1_RECALL_OUTPUT>
```

```powershell
uv run python tools/scripts/scan_overlay_shortcuts.py <PHASE1_RECALL_OUTPUT>
```

```powershell
uv run python tools/scripts/measure_phase1_detector_catch.py <PHASE1_RECALL_OUTPUT> --expect-truth-units 1500
```

수락 기준:

- active PHASE1-1 rules 26 / 26.
- truth units 1,500.
- standard 750 / 750 caught.
- boundary control 0 / 750 caught.
- shortcut findings 0.
- CoA coverage PASS.
- `999998`은 L1-03 invalid-account standard에만 허용.

### 3.4 REJECT 처리

- standard miss가 있으면 rule별 raw predicate와 datasynth variant가 맞는지 확인한다.
- boundary가 발화하면 boundary가 실제 임계 직하인지 확인한다.
- CoA 누락은 즉시 FAIL이다. L1-03 외 룰에서 없는 계정을 쓰면 L1-03 shortcut이 된다.
- shortcut finding은 token/format/range/value/nullness/조합 중 어느 유형인지 분류하고 generator에서 고친다.

## 4. PHASE1 combo/tier runbook

### 4.1 현재 기준

Accepted dataset:

`data/journal/primary/datasynth_semantic_v1_combo_tier_20260630_v47_batchid_r1j`

Base:

`data/journal/primary/datasynth_semantic_v1_normal_20260630_v47_batchid_r1`

SoT:

- `dev/active/phase1-rule-basis-audit/phase1-combo-tier-firing-matrix.md`
- `docs/spec/HIGH_COMBO_GROUNDING.md`
- `src/detection/topic_scoring.py`

### 4.2 생성 profile

```powershell
cargo run --manifest-path tools/datasynth/Cargo.toml -p datasynth-cli -- generate `
  --profile phase1-combo-tier-overlay `
  --manipulation-source data/journal/primary/datasynth_semantic_v1_normal_20260630_v47_batchid_r1 `
  --output <PHASE1_COMBO_TIER_OUTPUT>
```

### 4.3 필수 gate

생성 전 matrix gate:

```powershell
uv run python tools/scripts/verify_phase1_combo_tier_gate.py --matrix-only
```

생성 후:

```powershell
uv run python tools/scripts/verify_phase1_combo_tier_gate.py <PHASE1_COMBO_TIER_OUTPUT>
```

```powershell
uv run python tools/scripts/scan_overlay_shortcuts.py <PHASE1_COMBO_TIER_OUTPUT>
```

```powershell
uv run python tools/scripts/measure_phase1_combo_tier.py <PHASE1_COMBO_TIER_OUTPUT> --expect-truth-rows 15
```

수락 기준:

- truth rows 15.
- buildable combo 13 + LOW + CONTEXT.
- out-of-scope combo 0.
- static gate PASS.
- shortcut findings 0.
- actual case-builder gate 15 / 15.
- PHASE1 measurement harness reads L2-05 structural-reference fields. If
  `profile_phase1_v126.PHASE1_USECOLS` drops `original_document_id`/`reversal_document_id` family
  columns, related-party reversal combos can false-fail even when the dataset is correct.

### 4.4 중요한 판정 규칙

combo/tier acceptance는 final case `priority_band` equality가 아니다.
같은 case에 broad normal signal이 섞이면 final band가 올라갈 수 있다.
따라서 expected topic의 actual topic score가 expected tier cut을 넘는지를 본다.

### 4.5 REJECT 처리

- static gate PASS인데 actual FAIL이면 member docs가 같은 case로 묶이는지 본다.
- flow-based combo는 sidecar membership이 실제 case-builder에서 보이는지 확인한다.
- LOW/CONTEXT가 HIGH로 승격되면 unintended rule leg와 broad normal signal을 분리한다.
- shortcut scan이 user/source/date/reference를 잡으면 normal donor에 실제 존재하는 표면만 사용한다.

## 5. PHASE2 fraud overlay runbook

### 5.1 현재 기준

Accepted dataset:

`data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260614_v1_r4m_h`

Seed:

`data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260614_v1_r4m_h_seed1`

Scale reference:

`data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260613_v1_r4l_b`

주의:

- r4m_h는 accepted이지만 최신 NORMAL v53 account-determination successor 위에서 재생성된 것은 아니다.
- 다음 PHASE2 run은 v53 account-determination successor base 위에서 같은 gate를 다시 통과해야 한다.

### 5.2 생성 profile

```powershell
cargo run --manifest-path tools/datasynth/Cargo.toml -p datasynth-cli -- generate `
  --profile phase2-fraud-r1 `
  --manipulation-source <NORMAL_BASE> `
  --output <PHASE2_OUTPUT>
```

호환 profile:

```powershell
cargo run --manifest-path tools/datasynth/Cargo.toml -p datasynth-cli -- generate `
  --profile phase2-real-schemes `
  --manipulation-source <NORMAL_BASE> `
  --output <PHASE2_OUTPUT>
```

### 5.3 필수 gate

세부 수락 기준은 [Fraud Overlay Realism Gate](./fraud-overlay-realism-gate.md)를 따른다.

```powershell
uv run python tools/scripts/phase2_shortcut_gate.py <PHASE2_OUTPUT> <PHASE2_SCALE_REFERENCE>
```

```powershell
uv run python tools/scripts/verify_phase2_regression.py <PHASE2_OUTPUT> <NORMAL_BASE>
```

```powershell
uv run python tools/scripts/scan_overlay_shortcuts.py <PHASE2_OUTPUT>
```

```powershell
uv run python tools/scripts/audit_full_leak_scan.py <PHASE2_OUTPUT>
```

seed가 있으면 최소 seed1에도 full-column scan을 실행한다.

```powershell
uv run python tools/scripts/audit_full_leak_scan.py <PHASE2_SEED1>
```

seed rotation 검증:

```powershell
uv run python tools/scripts/verify_phase2_seed_diversity.py `
  <REPRESENTATIVE> <SEED1> <SEED2> <SEED3> <SEED4> <SEED5>
```

### 5.4 필수 수락 기준

- FS01~FS14 모두 존재.
- self-cancel 0.
- fraud imbalance 0.
- base unchanged 0.
- label consistency 0/0/0.
- shortcut gate all PASS.
- surface shortcut findings 0.
- full-column leak NEW candidates 0.
- seed가 있으면 seed-only shortcut/leak 0.
- seed diversity는 content 차이와 assignment vector 차이를 가져야 한다.

### 5.5 REJECT 처리

- full-column leak이 나오면 S2 whitelist 통과 여부와 무관하게 FAIL이다.
- donor metadata는 독립 marginal 샘플링하지 않는다. 정상 조합을 통째 상속한다.
- scheme-account mismatch를 shortcut cleanup으로 만들면 FAIL이다.
- 라인 수를 맞추기 위해 same-side split을 만들면 FAIL이다.
- 부작위 금액을 상수로 복사하면 FAIL이다.
- seed가 document id만 바꾸고 fraud content가 같으면 FAIL이다.

## 6. Integrated usefulness Phase1 overlay runbook

### 6.1 현재 기준

Accepted dataset:

`data/journal/primary/datasynth_integrated_usefulness_phase1_20260701_v1g`

Base:

`data/journal/primary/datasynth_semantic_v1_normal_20260630_v47_batchid_r7`

SoT:

- `dev/active/integrated-usefulness-benchmark/GENERATION_HANDOFF.md`
- `dev/active/integrated-usefulness-benchmark/INJECTION_POPULATION.md`
- `dev/active/integrated-usefulness-benchmark/pattern_specs/`
- `dev/active/integrated-usefulness-benchmark/COHERENCE_ORACLE_SPEC.md`

### 6.2 생성 profile

```powershell
cargo run --manifest-path tools/datasynth/Cargo.toml -p datasynth-cli -- generate `
  --profile integrated-usefulness-phase1-overlay `
  --contract-source data/journal/primary/datasynth_semantic_v1_normal_20260630_v47_batchid_r7 `
  --output <IUB_PHASE1_OUTPUT>
```

### 6.3 필수 gate

```powershell
uv run python tools/scripts/verify_injection_coherence.py --self-test
```

```powershell
uv run python tools/scripts/verify_integrated_usefulness_phase1.py `
  <IUB_PHASE1_OUTPUT> `
  --base data/journal/primary/datasynth_semantic_v1_normal_20260630_v47_batchid_r7
```

```powershell
uv run python tools/scripts/verify_injection_coherence.py <IUB_PHASE1_OUTPUT>
```

수락 기준:

- truth rows 595, seed_0~seed_4 각각 119.
- 3 generated patterns 모두 존재.
- label/provenance/surface hint journal 노출 0.
- exact-value oracle findings 0.
- distribution leak findings 0.
- temporal coherence findings 0.
- coherence oracle accidents 0.

### 6.4 REJECT 처리

- `source`, `batch_id`, `job_id`가 fraud-only 또는 fraud-dominant이면 donor 상속을 고친다.
- `weak_signal=true` 행은 manual/blank batch artifact를 만들면 안 된다.
- `approval_date < document_date`, `posting_date < document_date`, `settlement_date < posting_date`는
  relationship leak으로 처리한다.
- `verify_injection_coherence.py --self-test`가 실패하면 dataset 판정 전에 오라클 자체를 먼저 고친다.

## 7. 완료 보고 양식

새 accepted dataset이 생기면 다음을 보고한다.

- dataset path.
- base path.
- Rust profile과 생성 명령.
- truth row/unit count.
- 실행한 gate 명령과 핵심 수치.
- REJECT iteration이 있었다면 suffix별 실패 원인과 수정.
- 남은 gap.
- 갱신한 문서 목록.

완료 조건:

- 관련 gate가 전부 PASS.
- 실패를 숨기거나 hollow PASS로 둔갑시키지 않음.
- `docs/debugging.md`와 `docs/datasynth` 갱신.
