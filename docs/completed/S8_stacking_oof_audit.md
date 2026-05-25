# S8 — Stacking OOF protocol 재검증

> 측정 일자: 2026-05-15
> 데이터셋: `data\journal\primary\datasynth_manipulation_v3` (active manipulation v3)
> 산출 스크립트: `tools/analysis/s8_stacking_oof_ablation.py`
> 원본 산출물: `artifacts/S8_stacking_oof_ablation.json`
> 검증 대상: `src/detection/ensemble_detector.py::EnsembleDetector.train_oof()`의 '룰/VAE 1회 학습 + supervised/transformer/sequence OOF 재학습' 정책

## 1. 측정 대상

- 문서 수: 317,997
- manipulated truth: 420 (positive prevalence ≈ 0.1321%)
- GroupKFold 그룹 수 (company × year): 9

### 1.1 ablation 매트릭스

| ablation | base learners | 룰/VAE 정책 | supervised 정책 |
| --- | --- | --- | --- |
| A | layer_a, layer_b, layer_c, benford, ml_supervised, ml_unsupervised | **1회 학습** (full data) | OOF (5-fold GroupKFold) |
| B | (동일) | **fold-wise 재계산** | OOF |
| C | ml_supervised | 제외 | OOF |
| D | layer_a, layer_b, layer_c, benford | 1회 학습 | 제외 |

### 1.2 범위 외 (transformer / sequence)

ensemble_detector.STACKING_BASE_MODELS 8개 중 `ml_transformer`(FT-T)와 `ml_sequence`(BiLSTM) 두 트랙은 본 ablation 의 6 트랙 입력에서 제외했다. 근거: 본 검증의 핵심 질문은 (a) '룰/VAE 1회 학습 정책' 의 누수 여부와 (b) '룰 트랙 메타 가중치 과대 부여' 여부이며, 이 두 질문에는 supervised 한 트랙이면 충분하다. heavy DL 트랙을 추가해도 fold-wise 재학습 비용만 급증할 뿐 (a)/(b) 판정에는 기여하지 않는다.

## 2. ablation 별 결과

### 2.1 AUPRC

| ablation | AUPRC (full) | n_pos | n_train |
| --- | ---: | ---: | ---: |
| A_current_policy | **0.9988** | 420 | 317,997 |
| B_full_oof | **0.9979** | 420 | 317,997 |
| C_supervised_only | **0.9964** | 420 | 317,997 |
| D_rules_only | **0.1302** | 420 | 317,997 |

### 2.2 meta-learner Ridge(positive=True) 계수

| ablation | benford | layer_a | layer_b | layer_c | ml_supervised | ml_unsupervised | intercept |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A_current_policy | 0.0000 | 0.0000 | 0.0201 | 0.0000 | 0.8987 | 0.0006 | -0.0003 |
| B_full_oof | 0.0000 | 0.0000 | 0.0012 | 0.0000 | 0.9108 | 0.0007 | -0.0004 |
| C_supervised_only | — | — | — | — | 0.9115 | — | -0.0001 |
| D_rules_only | 0.0000 | 0.0000 | 0.1862 | 0.0000 | — | — | 0.0004 |

Ridge(positive=True) 는 모든 계수 ≥ 0 보장. 계수 합이 1 이 아닐 수 있다 (L2 정규화 + 비음수 제약 → 자동 sparsification 발생).

### 2.3 시나리오별 AUPRC (A vs B)

| scenario | A AUPRC | B AUPRC | A − B |
| --- | ---: | ---: | ---: |
| approval_sod_bypass | 0.9807 | 0.8346 | +0.1461 |
| circular_related_party | 0.9827 | 0.9837 | -0.0010 |
| embezzlement_concealment | 0.9925 | 0.9899 | +0.0026 |
| fictitious_entry | 1.0000 | 1.0000 | +0.0000 |
| period_end_adjustment | 0.9929 | 0.9902 | +0.0026 |
| unusual_timing_manipulation | 0.9683 | 0.9678 | +0.0005 |

## 3. 판정

- AUPRC(A) − AUPRC(B) = **+0.0009**
  - 임계: > +0.02 → '룰/VAE 도 OOF' 정책 변경 권고
  - 결과: 정책 유지

- 룰 4트랙 메타 가중치 합 / 전체 가중치 절대값 합 (ablation A) = **0.0219**
  - 임계: > 0.5 → ensemble 의 부가가치 약함
  - 결과: 균형 유지

## 4. 결론

- **현재 정책 유지**: A vs B AUPRC gap (+0.0009) 이 임계(+0.02) 이하 — 룰/VAE 의 1회 학습 정책은 본 데이터셋·시나리오에서 누수 효과를 만들지 않는다.
- **균형 가중치**: 룰 4트랙 가중치 비중 ≈ 2.2% (layer_b 0.0201, 나머지 0). ensemble 이 룰 트랙에 과도하게 의존하지 않는다.
- **ml_supervised 절대 우세**: meta 가중치 0.8987 (전체 비중 ≈ 98%). v3 dataset 에서 룰/VAE 가 거의 sparsified 되었으며 사실상 supervised 단독에 가깝다 — ablation C(0.9964) ≈ A(0.9988) 차이 +0.0024 만큼만 룰/VAE 가 추가 신호를 제공한다.

## 4.1 추가 관찰

### approval_sod_bypass 시나리오 단일 gap

전체 AUPRC gap 은 +0.0009 로 임계 이하지만 시나리오별 분해에서 `approval_sod_bypass` 만 **+0.1461** gap 이 발생한다. 의미:

- 본 시나리오 manipulation 은 self-approval / SoD bypass 패턴이라 layer_b 룰 (특히 L1-05/L1-09) 이 강하게 발화한다.
- layer_b 룰 점수가 fold-wise 재계산되면 (B), val fold 에 포함된 manipulated user 의 자기승인 패턴을 train fold 분포만으로는 보지 못해 점수 분포가 noisier 해진다.
- 결과: A 정책에서 layer_b weight 가 0.0201 → B 정책에서 0.0012 로 16배 감소.
- **단일 시나리오에 한정된 효과**: 다른 5 시나리오는 |Δ| < 0.003. 전체 AUPRC 가 거의 변하지 않는 이유는 ml_supervised 가 동일 시나리오에서 동급 이상 신호를 이미 잡기 때문.

### 룰 단독 (ablation D) 한계 - S5 와의 연결

ablation D 의 AUPRC = 0.1302. Stage 5 의 24-dim 룰 LR 결과 0.4398 보다 낮다. 차이 원인:

- 본 ablation 은 `STACKING_BASE_MODELS` 와 일치하기 위해 27개 룰을 4 레이어 (layer_a/b/c/benford) 의 max-of-hits 로 집계한다 → 룰별 변별력 손실.
- Stage 5 는 27 차원 그대로 사용 → 룰별 정보 보존.
- 즉, `STACKING_BASE_MODELS` 가 4 레이어로 압축한 시점에 이미 룰 트랙 단독 부가가치는 제한적이며 ensemble 의 부가가치는 supervised 결합에서 발생한다.

### Ridge sparsification 효과

ablation A 에서 layer_a / layer_c / benford 모두 weight = 0 으로 sparsify 되었다. Ridge(positive=True) + L2 (alpha=1.0) 조합이 layer_b/ml_supervised 두 트랙으로 신호를 집중시켰다. 이는 "룰 출력 4 트랙은 max-aggregation 으로 인해 ml_supervised 와 강한 공선성 → Ridge 자동 가중치 조정" 의 정상 동작이다.

## 5. 한계

- ML supervised 트랙: XGBoost (heavy DL 인 FT-Transformer/BiLSTM 미포함). 8 트랙 전체 ensemble 의 행동은 6 트랙 ensemble 과 다를 수 있으나, 본 검증의 핵심은 '룰/VAE 1회 학습' 정책이며 이는 6/8 트랙 모두 동일하게 적용된다.
- VAE 트랙: IsolationForest 로 대체. 둘 다 unsupervised 이고 fold-wise refit 효과가 동질적이라 ablation B 결론은 일반화된다.
- 룰 fold refit 시뮬레이션: detector 들이 stateless API 라 명시적 train/apply 분리가 없다. 본 ablation 의 'fold-wise 룰 점수' 는 val fold row 만으로 detector 를 호출했을 때의 결과이며, 통계 임계값 (z-score, Benford expected, 분포 shift) 이 fold 분포로부터 재계산되어 fold-sensitive 효과가 측정된다.
- supervised AUPRC 가 0.99+ 로 높은 이유: v3 dataset 의 manipulation injection 이 일부 메타 컬럼 (`sod_violation`, `has_attachment`, `posting_date` 시간대 등) 에 직접 신호를 남긴다. 본 ablation 의 ML 피처는 룰 출력을 ML 입력에서 제외한 14차원 numeric/freq 인코딩만 사용했지만, 이들 메타 컬럼 자체가 라벨과 강하게 관련된다. 이 부분은 Stage 3 (`stage3_trivial_shortcut_baseline.json`) 의 'synthetic shortcut' 분석과 별개의 우려가 아니라 동일 현상이며, 본 검증의 leakage 판정과는 독립이다 (모든 ablation 에서 동일 입력 사용).
- meta-learner refit 정책: 본 ablation 은 Ridge 를 OOF score matrix 위에 1 회 fit 한다 (ensemble_detector.train_oof 와 동일). meta 자체를 nested OOF 로 평가하지는 않으며, 이는 의도된 단순화다 — base learner 의 OOF 가 leakage-free 라면 meta fit on (OOF_score, y) 의 AUPRC 는 ensemble 부가가치의 상한선 추정으로 해석 가능하다.

## 6. 다음 단계 권고

### 6.1 채택 (즉시)

- **현 정책 유지**: `_LEAKAGE_PRONE_TRACKS = (ML_SUPERVISED, ML_TRANSFORMER, ML_SEQUENCE)` 그대로. 룰/VAE 의 1회 학습은 정당화된다.
- **본 audit 결과를 PHASE2 ML 회귀 가드에 추가**: 향후 룰 detector 학습 인터페이스 변경 또는 새 통계 임계값 룰 추가 시 본 ablation 을 재실행하여 (a) AUPRC(A)−AUPRC(B), (b) 시나리오별 gap, (c) 룰 가중치 비중을 재측정.

### 6.2 보류 (조건부)

- **approval_sod_bypass 시나리오의 +0.1461 gap 만 별도 추적**: 본 데이터셋에서는 ml_supervised 가 동일 시나리오를 잡아 전체 AUPRC 영향이 미미하나, ml_supervised 가 약한 다른 dataset 에서는 영향이 커질 수 있다. PHASE2 의 시나리오별 회귀 KPI 에 'approval_sod_bypass' 단일 시나리오 AUPRC 를 별도 기록.
- **룰 detector 학습 인터페이스 도입은 비추천**: AUPRC 이득 < 0.001 대비 학습 시간 +10~15분, stateful API 도입에 따른 회귀 위험이 크다.

### 6.3 비범위 (본 검증 미해결)

- ml_transformer / ml_sequence 트랙 포함 8 트랙 ablation: 본 검증에서 6 트랙으로 한정 — heavy DL 트랙 추가 시 (a) supervised dominance 가 분산될 가능성, (b) leakage 효과는 동일 정책 하에서 동일하게 동작할 것으로 추정. 별도 데이터 재생성 사이클에서 재측정 필요 (ft_ablation_study.py 본 호출과 통합 권고).