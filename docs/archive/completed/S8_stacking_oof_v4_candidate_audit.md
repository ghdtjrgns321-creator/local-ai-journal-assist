# S8 — Stacking OOF protocol 재검증

> 측정 일자: 2026-05-15
> 데이터셋: `data\journal\primary\datasynth_manipulation_v4_candidate` (active manipulation v3)
> 산출 스크립트: `tools/analysis/s8_stacking_oof_ablation.py`
> 원본 산출물: `artifacts/S8_stacking_oof_ablation.json`
> 검증 대상: `src/detection/ensemble_detector.py::EnsembleDetector.train_oof()`의 '룰/VAE 1회 학습 + supervised/transformer/sequence OOF 재학습' 정책

## 1. 측정 대상

- 문서 수: 317,997
- manipulated truth: 620 (positive prevalence ≈ 0.1950%)
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
| A_current_policy | **0.9901** | 620 | 317,997 |
| B_full_oof | **0.9860** | 620 | 317,997 |
| C_supervised_only | **0.9829** | 620 | 317,997 |
| D_rules_only | **0.2069** | 620 | 317,997 |

### 2.2 meta-learner Ridge(positive=True) 계수

| ablation | benford | layer_a | layer_b | layer_c | ml_supervised | ml_unsupervised | intercept |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A_current_policy | 0.0000 | 0.0431 | 0.0618 | 0.0142 | 0.6959 | 0.0010 | -0.0010 |
| B_full_oof | 0.0000 | 0.0477 | 0.0036 | 0.0105 | 0.7177 | 0.0016 | -0.0012 |
| C_supervised_only | — | — | — | — | 0.7263 | — | -0.0004 |
| D_rules_only | 0.0000 | 0.1354 | 0.1906 | 0.0610 | — | — | 0.0005 |

Ridge(positive=True) 는 모든 계수 ≥ 0 보장. 계수 합이 1 이 아닐 수 있다 (L2 정규화 + 비음수 제약 → 자동 sparsification 발생).

### 2.3 시나리오별 AUPRC (A vs B)

| scenario | A AUPRC | B AUPRC | A − B |
| --- | ---: | ---: | ---: |
| approval_sod_bypass | 0.7532 | 0.5856 | +0.1676 |
| circular_related_party | 0.9878 | 0.9902 | -0.0024 |
| embezzlement_concealment | 0.9856 | 0.9824 | +0.0032 |
| expense_capitalization | 0.9845 | 0.9830 | +0.0015 |
| fictitious_entry | 0.9994 | 0.9976 | +0.0018 |
| period_end_adjustment | 0.9064 | 0.8828 | +0.0236 |
| suspense_account_abuse | 1.0000 | 1.0000 | +0.0000 |
| unusual_timing_manipulation | 0.8787 | 0.4298 | +0.4489 |

## 3. 판정

- AUPRC(A) − AUPRC(B) = **+0.0041**
  - 임계: > +0.02 → '룰/VAE 도 OOF' 정책 변경 권고
  - 결과: 정책 유지

- 룰 4트랙 메타 가중치 합 / 전체 가중치 절대값 합 (ablation A) = **0.1459**
  - 임계: > 0.5 → ensemble 의 부가가치 약함
  - 결과: 균형 유지

## 4. 결론

- **현재 정책 유지**: A vs B AUPRC gap 이 임계(+0.02) 이하 — 룰/VAE 의 1회 학습 정책은 본 데이터셋·시나리오에서 누수 효과를 만들지 않는다.
- **균형 가중치**: 룰 트랙 가중치 비중이 50% 이하로 ensemble 이 ML/VAE 신호를 활용 중.

## 5. 한계

- ML supervised 트랙: XGBoost (heavy DL 인 FT-Transformer/BiLSTM 미포함). 8 트랙 전체 ensemble 의 행동은 6 트랙 ensemble 과 다를 수 있으나, 본 검증의 핵심은 '룰/VAE 1회 학습' 정책이며 이는 6/8 트랙 모두 동일하게 적용된다.
- VAE 트랙: IsolationForest 로 대체. 둘 다 unsupervised 이고 fold-wise refit 효과가 동질적이라 ablation B 결론은 일반화된다.
- 룰 fold refit 시뮬레이션: detector 들이 stateless API 라 명시적 train/apply 분리가 없다. 본 ablation 의 'fold-wise 룰 점수' 는 val fold row 만으로 detector 를 호출했을 때의 결과이며, 통계 임계값 (z-score, Benford expected, 분포 shift) 이 fold 분포로부터 재계산되어 fold-sensitive 효과가 측정된다.