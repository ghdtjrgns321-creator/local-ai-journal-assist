# S9 — Zero-day (Hold-out fraud type) protocol 대안

> 측정 일자: 2026-05-15
> 입력 산출물: `docs/raw-plan/05a-detection-ml.md`, `docs/raw-plan/05-detection.md`, `data/journal/primary/datasynth_manipulation_v3/labels/manipulated_entry_truth.csv`, `data/journal/primary/datasynth_manipulation_v2/labels/manipulated_entry_truth.csv`
> 검증 단위: zero-day 평가 protocol 의 v3 active dataset 적용 가능성

## 1. raw-plan 의 원래 hold-out 설계

`docs/raw-plan/05-detection.md:1293` + `docs/raw-plan/05a-detection-ml.md:38` 의 D027 에서 정의된 protocol:

> **Hold-out Fraud Type**: 8개 유형 중 6개 훈련, 2개(`suspense_account_abuse`, `expense_capitalization`) 미지 유형 테스트 → VAE zero-day 탐지 증명

원래 8 fraud type:

| 유형 | 비중 |
|---|---:|
| duplicate_payment | 20% |
| fictitious_transaction | 20% |
| revenue_manipulation | 15% |
| split_transaction | 15% |
| timing_anomaly | 10% |
| unauthorized_access | 10% |
| **suspense_account_abuse** (hold-out) | 5% |
| **expense_capitalization** (hold-out) | 5% |

목적: VAE 가 training 에 본 적 없는 fraud type 을 reconstruction error 로 탐지할 수 있음을 증명 (zero-day capability 검증).

## 2. v3 dataset 의 manipulation 시나리오 갭

### 2.1 v3 manipulation truth 시나리오 (전수)

| scenario | n_pos |
|---|---:|
| fictitious_entry | 168 |
| period_end_adjustment_manipulation | 92 |
| embezzlement_concealment | 76 |
| circular_related_party_transaction | 34 |
| approval_sod_bypass | 29 |
| unusual_timing_manipulation | 21 |

### 2.2 raw-plan 8 type vs v3 6 scenario 매핑

| raw-plan fraud_type | v3 scenario 매핑 | 매핑 신뢰도 |
|---|---|---|
| duplicate_payment | (없음) — `embezzlement_concealment` 의 부분 | 부분 |
| fictitious_transaction | `fictitious_entry` | 높음 |
| revenue_manipulation | (없음) — `period_end_adjustment_manipulation` 의 부분 | 부분 |
| split_transaction | (없음) | 없음 |
| timing_anomaly | `unusual_timing_manipulation` | 높음 |
| unauthorized_access | `approval_sod_bypass` | 높음 |
| **suspense_account_abuse** | (없음) | **없음 — hold-out 후보 부재** |
| **expense_capitalization** | (없음) | **없음 — hold-out 후보 부재** |

→ **결론**: raw-plan 의 hold-out 2 type 은 v3 manipulation truth 에 단 하나도 존재하지 않는다. D027 protocol 은 v3 active dataset 위에서 그대로 실행 불가.

### 2.3 v2 manipulation truth 와 cross hold-out 가능성

`data/journal/primary/datasynth_manipulation_v2/labels/manipulated_entry_truth.csv` 점검:

```
v2 scenario 분포 (count):
  fictitious_entry: 168
  period_end_adjustment_manipulation: 92
  embezzlement_concealment: 76
  circular_related_party_transaction: 34
  approval_sod_bypass: 29
  unusual_timing_manipulation: 21
v2 ∩ v3 = 6 시나리오 모두 일치
v2 only = []
v3 only = []
```

→ **v2 와 v3 는 manipulation taxonomy 가 동일 (count, scenario 명 모두 일치)**. v2/v3 cross hold-out 으로는 zero-day fraud type 을 만들 수 없다. 두 dataset 은 generation 방식만 다르며 (v2=Python materialize, v3=Rust candidate fixed) 라벨 분포는 같다.

## 3. 대안 zero-day protocol 후보

### 3.1 후보 A — v3 내 prevalence 하위 2개 시나리오 hold-out

가장 적은 두 시나리오를 hold-out 으로 분리:

| hold-out 후보 | n_pos | prevalence (vs 전체 doc) | n_pos / hold-out 합 |
|---|---:|---:|---:|
| `unusual_timing_manipulation` | 21 | 0.0066% | 50 (50/420 = 11.9%) |
| `approval_sod_bypass` | 29 | 0.0091% | (50 합) |

**장점**:
- 즉시 적용 가능. 추가 데이터 생성 없음.
- raw-plan 의 5%+5% = 10% 분배 비율과 유사 (v3 hold-out 50/420 = 11.9% ≈ 12%).
- 각 시나리오가 독립적 manipulation pattern 이므로 zero-day 검증 의도와 부합.

**단점 (n 부족 caveat)**:
- `unusual_timing_manipulation` n=21 → recall 한 단위 변동이 4.76 pp. AUPRC 95% 신뢰구간이 약 ±0.10 ~ ±0.15 (bootstrap 추정). 단일 dataset 에서의 측정값은 noise floor 가 높다.
- `approval_sod_bypass` n=29 → recall 한 단위 변동 3.45 pp. 마찬가지로 통계적으로 약함.
- **합 50 건은 fraud detection 평가의 통상 minimum (≥ 100)** 미만. binomial 분포 기준 95% 신뢰구간이 ± 14 pp 수준.
- 두 시나리오 모두 v3 에서 단일 manipulation_subtype 에 가까움 → zero-day 라기보다는 'specific subtype hold-out' 에 가깝다.
- 본 두 시나리오는 S5 결과 기준 Phase1 27룰 LR recall = 1.000 으로 룰만으로도 다 잡힌다 → VAE zero-day capability 측정에 약점 부각이 어렵다.

**적용 권고**:
- proof-of-concept (POC) 수준에서만 사용. 통계적 유의성 주장 금지.
- 결과 보고 시 `n=50` 에 대한 binomial 95% CI 함께 명시.
- VAE recall + IsolationForest recall 만 비교. 단일 supervised model 평가에는 부적합 (training set 에 본 적 없는 type 평가 의도).

### 3.2 후보 B — v3 내 manipulation_subtype 단위 hold-out

`v3/labels/manipulated_entry_truth.csv` 의 `manipulation_subtype` 컬럼을 활용. 각 시나리오에 1-3 개 subtype 이 있다. 일부 subtype 만 hold-out:

```
subtype 분포 예시 (sample):
  approval_sod_bypass: self_approval_sod (29)  → 단일 subtype
  fictitious_entry: 다중 subtype (round_amount, related_party_round, ...)
```

**장점**:
- subtype 단위 hold-out 은 같은 시나리오 내에서 본 적 없는 변형을 평가하므로 zero-day 의도와 더 부합.
- 시나리오의 5 / 6 subtype 만 학습 → 1 subtype 평가. 시나리오 내에서 generalization test.

**단점**:
- subtype 분포가 균등하지 않다. 단일 subtype 만 갖는 시나리오 (approval_sod_bypass) 는 적용 불가.
- subtype 단위 라벨이 raw-plan 의 'fraud_type' 단위 hold-out 의도와 다른 추상화 레벨.
- 구현 시 fold 정의 + KFold 와의 결합 필요 (hold-out 구간 + within-train CV).

**적용 권고**:
- 후보 A 보다 통계적 noise 가 더 높을 가능성. 단일 subtype 의 n 이 5 미만일 수 있음.
- 후보 A 와 병행 사용은 권고하지 않음. 둘 중 택일.

### 3.3 후보 C — DataSynth 재생성으로 hold-out type 재추가

원래 D027 의 의도를 살리려면 v3 (또는 v4) 에 `suspense_account_abuse` 와 `expense_capitalization` 두 시나리오를 manipulation_scenario 로 추가 생성해야 한다. 다만:

- v3 contract dataset 에는 `expense_capitalization_plausible_cases (33)` + `expense_capitalization_normal_capex_controls (90)` 의 sidecar 가 이미 존재한다 (`docs/completed/datasynth_contract_sidecar_taxonomy_v126.csv:62`).
- v3 contract dataset 의 `rule_truth_L3_09` (suspense aging) 도 이미 존재한다.
- 그러나 둘 다 **rule contract truth** 이지 **manipulation truth** 가 아니다 → fraud injection 으로 라벨된 것이 아니라 룰 발화 정답지로 만들어졌다.

**전환 옵션**:
1. **단순 재라벨**: `expense_capitalization_plausible_cases` 33 건 + `rule_truth_L3_09` 의 일부를 manipulation_scenario 로 격상. 비용: 라벨 매핑 코드 + manifest 갱신.
2. **신규 manipulation 생성**: Rust DataSynth 의 manipulation v4 profile 추가. 비용: profile 설계 + 빌드 + truth 생성 + Phase1 회귀 검증.

**적용 권고**:
- 옵션 1 은 현재 dataset 구조 변경 + provenance 혼선 위험 (contract truth 와 manipulation truth 의 의미가 다르다 — provenance lock 위반 가능).
- 옵션 2 는 raw-plan 의도와 가장 부합하지만 데이터 재생성 cycle (Rust 빌드 + 검증) 이 필요하고 manipulation v3 lock 변경.
- 단기 (1 sprint) 에는 후보 A + n 부족 caveat 로 진행하고, 장기 (Phase 2 ML 정식 평가 직전) 에는 옵션 2 채택을 검토.

## 4. 권고 - 단기 (즉시 적용)

**채택**: 후보 A — `unusual_timing_manipulation` (21) + `approval_sod_bypass` (29) 두 시나리오를 hold-out.

**구현 protocol**:
1. Phase 2 ML training 에서 위 2 시나리오를 **train fold 에서 완전히 제외**한다 (train fold 의 모든 doc 에서 위 시나리오 라벨된 doc 을 제거).
2. test fold 는 6 시나리오 모두 포함하되, hold-out 2 시나리오의 recall 을 **별도 보고**한다.
3. VAE / IsolationForest / Ensemble 의 hold-out recall 을 95% binomial CI 와 함께 보고.
4. 통과 기준: hold-out 2 시나리오 합산 recall ≥ 0.5 (즉 50 건 중 25 건 이상). 이는 'random baseline (~1%)' 대비 충분한 부가가치이며, 동시에 Phase1 룰 (recall=1.0) 대비 zero-day 손실을 정량화한다.

**한계 명시 의무**:
- 보고서 모든 hold-out 결과에 `n=50, 95% CI ≈ ±0.14` 명시.
- 'fraud type 자체가 본 적 없는 zero-day' 가 아니라 '시나리오 단위 hold-out' 임을 명시 (training data 에 다른 5 시나리오 가 있으므로 부분적 cross-scenario transfer 가 가능).

**구현 상태 (2026-05-15)**:
- `src/services/phase2_training_service.py` 기본 옵션 `DEFAULT_HOLD_OUT_SCENARIOS = ('unusual_timing_manipulation', 'approval_sod_bypass')`.
- `mutation_type` 은 학습 feature 가 아니라 split 전용 context 로만 보존한다.
- hold-out doc 은 train fold 에서 제거하고 calibration/test fold 에 강제 포함한다. Calibration row cap 은 일반 calibration row 에만 적용하고 hold-out row 는 cap 으로 제거하지 않는다.
- `src/evaluation/phase2_report.py` 가 hold-out recall, binomial 95% CI, pass/fail, mandatory caveat 를 산출한다.
- PHASE3 Review Queue Narrator candidate 입력은 별도 경로이며 hold-out scenario doc 을 필터링하지 않는다.

## 5. 권고 - 장기 (Phase 2 ML 정식 평가 전)

**채택 검토**: 후보 C 옵션 2 — DataSynth manipulation v4 profile 에 raw-plan 의 두 hold-out 유형 추가.

**구현 단계**:
1. `tools/datasynth/crates/datasynth-cli/src/manipulation_v4.rs` 신규 (v3 의 6 시나리오 + 추가 2 시나리오).
2. 추가 시나리오 설계:
   - `suspense_account_abuse`: gl_account ∈ suspense list (가수금/미결산/임시계정) 에 장기 미결제 잔액 누적. 라벨 n ≥ 100 권고.
   - `expense_capitalization`: 비용 계정 → 자산 계정 변환 패턴 (잘못된 자본화). 라벨 n ≥ 100 권고.
3. v4 generation + Phase1 룰 회귀 검증 (S5 reproducer 와 동일 protocol).
4. v4 hold-out protocol 으로 raw-plan D027 정식 적용.

**비용 추정**: Rust profile 설계 + 빌드 + 검증 약 2-3 일 작업 (v3 → v4 migration report 1건 작성 포함).

## 6. 의사결정 입력 표

| 옵션 | 가용성 | 통계적 신뢰성 | raw-plan 의도 부합 | 구현 비용 |
|---|---|---|---|---|
| 후보 A (v3 prevalence 하위 2개 hold-out) | 즉시 | 낮음 (n=50, ±14pp) | 부분 (zero-day type 아닌 scenario hold-out) | 0 (코드 변경만) |
| 후보 B (manipulation_subtype hold-out) | 즉시 | 매우 낮음 (n<10 가능) | 부분 (subtype 단위) | 1 일 |
| 후보 C 옵션 1 (contract truth 재라벨) | 1-2 일 | 중간 (n≈33-100) | 낮음 (provenance 혼선) | 1-2 일 |
| 후보 C 옵션 2 (manipulation v4 신규 생성) | 2-3 일 | 높음 (n≥100 가능) | **높음 (raw-plan 의도 정확 재현)** | 2-3 일 |

**권고 우선순위**: 단기 = 후보 A. 장기 = 후보 C 옵션 2.
