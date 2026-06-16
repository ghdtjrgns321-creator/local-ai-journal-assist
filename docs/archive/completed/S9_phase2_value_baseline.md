# S9 — Phase 2 ML 부가가치 baseline

> 측정 일자: 2026-05-15
> 데이터셋: `data/journal/primary/datasynth_manipulation_v3` (active manipulation v3)
> 입력 산출물: `artifacts/stage3_trivial_shortcut_baseline.json`, `artifacts/S5_circular_learning_overlap.json`, `artifacts/S8_stacking_oof_ablation.json`
> 검증 단위: document level (n=317,997, manipulated=420)

## 1. 측정 대상 baseline

| baseline | 정의 | 데이터 출처 |
|---|---|---|
| Trivial 단일 규칙 best | R1 (`local_amount > company p99.95(\|amount\|) × 1.5`) — Stage 3 의 7 trivial 룰 중 macro AP 최고 | S3 |
| Trivial OR(2) best | R1 ∨ R2 (`approved_by NULL/blank ∨ sod_violation`) — 2 규칙 OR 조합 중 macro AP 최고 | S3 |
| Trivial OR(3) best | R1 ∨ R2 ∨ R3 (`is_suspense_account=true`) — 3 규칙 OR 조합 중 macro AP 최고 | S3 |
| Phase1 aggregator | `score_aggregator.aggregate_scores` 의 layer-가중 합산 (실 운영 score) | S3 |
| Phase1 27룰 LR (OOF) | 27 활성 rule_id 의 hit boolean 을 입력으로 LogReg + GroupKFold OOF | S5 |
| Phase 2 ML 앙상블 (참고) | S8 ablation A — 6 트랙 (4 layer + supervised XGBoost + IsolationForest) Ridge stacking | S8 |

> 주의: Stage 3 baseline 은 top-K = n_pos = **420** (≈ 0.13% prevalence 의 정확한 hit 수 만큼) 에서 평가되었다. Stage 5 27 룰 LR 은 top-K = 1% = **3,179** 에서 평가되었다. 두 k 가 다르므로 **macro AUPRC** (threshold-free) 가 1차 비교 지표이고, F2 / scenario recall 은 각 baseline 의 원본 k 를 명시한다.

## 2. 핵심 비교 표

| Baseline | macro AUPRC | macro F2 | scenario recall (6개) | 통과 기준 |
|---|---:|---:|---|---|
| Trivial 단일 규칙 best (R1, k=420) | **0.1292** | 0.1282 | fictitious 1.000 / period_end 0 / embezz 0 / circular 0 / sod_bypass 0 / unusual_timing 0 | base |
| Trivial OR(2) best (R1+R2, k=420) | **0.1286** | 0.1282 | fictitious 1.000 / 그 외 0 | base |
| Trivial OR(3) best (R1+R2+R3, k=420) | **0.1219** | 0.1282 | fictitious 1.000 / 그 외 0 | base + 0.03 → ≥ 0.159 |
| Phase1 aggregator (k=420) | **0.1594** | 0.2726 | fictitious 0.857 / period_end 0.728 / embezz 0.026 / circular 0.529 / sod_bypass 0.655 / unusual_timing 0.952 | base + 0.03 → ≥ 0.159 |
| Phase1 27룰 LR OOF (k=3,179) | **0.4398** | 0.0679 (k=3,179) | fictitious 0.685 / period_end 1.000 / embezz 0.395 / circular 0.176 / sod_bypass 1.000 / unusual_timing 1.000 | base + 0.05 → ≥ 0.4898 |
| **Phase 2 ML 앙상블 목표** | **≥ 0.4898** | **≥ 0.118 (k=3,179)** | 모든 시나리오 recall ≥ Phase1 LR 동값 OR +0.03 | 룰 aggregate + 0.05 |
| (참고) S8 6 트랙 ablation A | 0.9988 | n/a | fictitious 1.000 / period_end 0.993 / embezz 0.992 / circular 0.983 / sod_bypass 0.981 / unusual_timing 0.968 | (설명: 본 데이터셋이 supervised 에 매우 우호적이라 0.99+ 도달. 일반화 보장 아님) |

### 2.1 통과 기준 적용 규칙

- **macro AUPRC (필수)**: Phase 2 ML 앙상블의 OOF macro AUPRC 가 룰 aggregate (= Phase1 27룰 LR OOF, **0.4398**) + 0.05 = **0.4898** 이상이어야 한다. 미달 시 ML 추가 가치 부재.
- **macro F2 (필수)**: 같은 k(top-1%) 에서 Phase1 27룰 LR (0.0679) + 0.05 = **0.118** 이상.
- **scenario recall (체크 가드)**: 6 시나리오 각각에 대해 (a) Phase1 LR recall 동값 이상이거나, (b) Phase1 LR recall 대비 +0.03 이상 손실 없이 다른 시나리오 recall 이 +0.03 이상 향상되어야 함.
- **시나리오 균형**: macro 평균을 만족하더라도 단일 시나리오 recall 이 0.5 미만이면 review queue 운영상 위험 → S8 의 `embezzlement_concealment` (룰 LR 0.395) 가 1차 개선 우선 순위.

## 3. 시사점

### 3.1 trivial baseline 은 사실상 단일 시나리오 (fictitious_entry) 만 잡는다

- R1 (금액 outlier) 단독으로 fictitious_entry recall = 1.0 (168/168 caught). 그러나 다른 5 시나리오는 모두 recall = 0 → trivial 룰의 macro AP 가 0.13 에 머무는 원인.
- Trivial OR(3) 을 시도해도 macro AP 가 오히려 0.122 로 감소. fictitious 1개를 제외하면 trivial 룰은 v3 manipulation 을 거의 탐지 못한다.
- 즉 **Phase 2 ML 의 도전 과제는 fictitious 가 아니라 나머지 5 시나리오의 recall 확보**다.

### 3.2 Phase1 룰 27 차원 LR 이 trivial 대비 3.4 배 (0.13 → 0.44) 도약

- 27 차원 (L1-L4 활성 rule_id) LR 은 trivial 단일 룰 대비 macro AUPRC +0.31. Phase1 룰의 다중 시나리오 커버 (period_end_adjustment, sod_bypass, unusual_timing 모두 recall=1) 가 핵심.
- 다만 룰 27 차원의 단일 룰 univariate AUPRC 분포는 fictitious 가 dominate (S5 §4 top-5 predictive rules 참조) → Phase 2 ML 은 이 의존도를 줄여야 한다.

### 3.3 S8 ablation A 의 0.9988 은 baseline 이 아니라 상한선 추정

- S8 의 6 트랙 ensemble 은 supervised XGBoost (engineered features) 가 weight 0.90 으로 절대 우세 → v3 의 manipulation injection 이 일부 메타 컬럼 (sod_violation, has_attachment, posting_date 시간대) 에 직접 신호를 남겨 supervised 가 사실상 라벨 shortcut 을 학습.
- **이 0.99 수치를 Phase 2 ML 목표로 삼으면 안 된다**. 본 baseline 표의 통과 기준은 Phase1 룰 aggregate + 0.05 = 0.49 가 합리적 floor 이며, 0.99 는 synthetic data 특이성에서 비롯된 ceiling 추정으로 해석한다.

### 3.4 시나리오별 약점 진단

| 시나리오 | n_pos | trivial best | Phase1 aggregator | Phase1 LR @1% | 약점 |
|---|---:|---:|---:|---:|---|
| fictitious_entry | 168 | 1.000 | 0.857 | 0.685 | trivial 로도 충분, 룰 LR 이 오히려 조금 낮음 (top-K 차이) |
| period_end_adjustment | 92 | 0 | 0.728 | 1.000 | 룰 aggregator/LR 가 잘 잡음 |
| embezzlement_concealment | 76 | 0 | 0.026 | 0.395 | **모든 baseline 이 약함**. Phase 2 ML 1차 타겟 |
| circular_related_party | 34 | 0 | 0.529 | 0.176 | 룰 aggregator 0.53 > 룰 LR 0.18 (LR top-1% 추가 신호 약함). Phase 2 ML 2차 타겟 |
| approval_sod_bypass | 29 | 0 | 0.655 | 1.000 | 룰 LR 가 잘 잡음 |
| unusual_timing_manipulation | 21 | 0 | 0.952 | 1.000 | 룰 LR 가 잘 잡음 |

→ Phase 2 ML 의 부가가치 측정은 **embezzlement_concealment** 와 **circular_related_party_transaction** 의 recall 개선 폭으로 정의된다.

## 4. Phase 2 ML 부가가치 게이트 (요약)

```
필수 1: ensemble OOF macro AUPRC ≥ 0.4898
필수 2: ensemble OOF macro F2 @ top-1% ≥ 0.118
필수 3: embezzlement_concealment recall @ top-1% ≥ 0.395 + 0.10 = 0.495
필수 4: circular_related_party recall @ top-1% ≥ 0.176 + 0.10 = 0.276
조건 5: 다른 4 시나리오 recall 손실 |Δ| < 0.05
필수 6: ensemble OOF macro AUPRC / trivial_10feature macro AUPRC ≤ 4.0
        (4배 초과 시 shortcut 의심으로 마킹하고 DataSynth v4 빌드 전까지 BLOCK)
```

위 6개 게이트 모두 통과 시 Phase 2 ML 앙상블이 룰 aggregate 대비 부가가치를 가진 것으로 인정. 5개 이하 통과 시 'Phase1 룰 + score_aggregator' 만으로 운영하고 Phase 2 ML 은 보조 신호로만 활용 (S8 ablation D 결과처럼 Ridge meta 가 자동으로 사실상 룰만 사용).

필수 6의 `trivial_10feature macro AUPRC` 는 `tools/analysis/compute_trivial_baseline.py` 로 재산정한다. 입력 참조는 `artifacts/stage3_trivial_shortcut_baseline.json` 의 historical macro AP 와 `artifacts/S4_scenario_recall.csv` 이며, 산정 fold 는 ensemble 평가와 동일한 GroupKFold(company_code × fiscal_year, 5-fold, shuffle 없음)를 사용한다.

S4 P4 `Δrecall ≥ 0.05` gate 와 필수 6 anti-shortcut cap 은 **OR 조건이 아니라 AND 조건**이다. 즉 시나리오별 recall 개선이 충분해도 ensemble/trivial macro AUPRC 비율이 4.0을 넘으면 DataSynth v4 전까지 promotion 은 BLOCK 이고, 반대로 비율이 4.0 이하라도 S4 P4 Δrecall 미달 시 BLOCK 이다.

## 5. 한계

- macro AUPRC 정의: 각 시나리오의 negative pool 을 (전체 negative + 다른 시나리오의 positive) 가 아닌 (전체 negative) 로 정의했다. one-vs-rest 가 아닌 in-scenario AP 에 가깝다. 다른 시나리오 positive 가 같은 row 에 동시에 라벨되는 경우는 v3 에 없으므로 (manipulation truth 는 1 doc = 1 scenario) 영향 없다.
- macro F2 의 k 의존성: top-1% (k=3,179) 와 top-K=n_pos (k=420) 사이에서 F2 값이 크게 변한다. 본 표는 baseline 별 원본 k 를 유지했으며, Phase 2 ML 평가 시에는 두 k 모두에서 동일 게이트 (P1 27룰 LR + 0.05) 를 적용하길 권고.
- Phase 2 ML 의 'OOF' 정의는 S8 audit 에 따라 '룰/VAE 1회 학습 + supervised/transformer/sequence GroupKFold OOF' 정책 (`ensemble_detector.train_oof`) 을 재사용. S8 검증 결과 본 정책은 leakage-free (AUPRC gap < 0.001).
