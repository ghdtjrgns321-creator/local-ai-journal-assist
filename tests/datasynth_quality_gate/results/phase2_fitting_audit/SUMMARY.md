# Phase 2 Fitting Audit — SUMMARY

> 측정 일자: 2026-05-15
> 데이터셋: `data/journal/primary/datasynth_manipulation_v3` (Rust candidate fixed, active manipulation v3)
> 대상: PHASE2 ML 학습/평가 파이프라인의 fitting risk 종합 진단
> Stage 0~9 산출 통합 결과
> 단일 entry-point 문서: [`docs/spec/PHASE2_FITTING_AUDIT.md`](../../../../docs/spec/PHASE2_FITTING_AUDIT.md)

## 1. Executive Summary (3~5줄)

v3 dataset 위에서 Stage 0~9 의 10개 진단을 통합한 결과, PHASE2 ML 학습 파이프라인은 17 위험 항목 중 **GREEN 3 / YELLOW 10 / RED 4** 분포로 **YELLOW (조건부 GO)** 판정. 4 RED 는 모두 (a) DataSynth v3 의 합성 shortcut 패턴 (`f_manual` 1.0 포화, 4/6 시나리오 trivial 80%+ recall, `unusual_timing` degenerate) 또는 (b) BiLSTM cross-user temporal context leakage 75% 1 가지에 집중되며 명시적 완화안이 정의되어 있다. PHASE2 진행 시 (i) `S0+S1` 13컬럼 deny-list 강제, (ii) `S2` GroupKFold(document_id, fallback to user) 정책, (iii) `S4` P1~P5 평가 protocol 강제, (iv) BiLSTM 트랙 일시 보류, (v) trivial baseline + Phase1 룰 aggregate 동시 보고를 모든 평가 cycle 에 의무화한다.

## 2. GREEN/YELLOW/RED 종합 판정

### 판정 기준

- **GREEN**: 측정값이 임계 안에 있고 mitigation 불필요 또는 이미 적용 완료
- **YELLOW**: 측정값이 위험 신호이나 mitigation 이 정의되었거나 적용 가능 (조건부 GO)
- **RED**: 측정값이 임계를 초과하고 mitigation 미적용 시 PHASE2 결과를 신뢰할 수 없음 (BLOCK)

### 종합 판정: **YELLOW (조건부 GO)**

| 색 | 개수 | 위험 ID |
|---|---:|---|
| GREEN | 3 | L-01, L-13, L-16 |
| YELLOW | 10 | L-02, L-03, L-04, L-05, L-06, L-07, L-11, L-12, L-14, L-17 |
| RED | 4 | L-08, L-09, L-10, L-15 |

**근거**:
- RED 4건 모두 mitigation 경로 정의되어 PHASE2 진행 자체는 가능 (RED→YELLOW 전환 가능).
- 단, RED mitigation 미적용 시 PHASE2 ML 의 macro AUPRC 향상폭이 합성 shortcut 에 의한 것인지 실제 판별력인지 구분 불가 → 평가 결과 신뢰성 RED.
- BiLSTM 트랙은 mitigation (S7 §5.1, §5.2) 적용 후 재측정 통과까지 PHASE2 본 평가에서 제외 (S7 §5.4 기준).

## 3. 17 위험 카탈로그

각 위험은 `[상태]`, `[근거 산출]`, `[완화안]` 3행 구조.

### L-01 — Stage 0 라벨 누수 컬럼 18개 (`mutation_*`, `detection_surface_hints`, `document_number`, `header_text`, `reference`, `ip_address`, `delivery_date`, `settlement_status`, …)

| 행 | 내용 |
|---|---|
| 상태 | **GREEN** — Stage 1 deny-list 13 컬럼 강제 적용으로 잔여 단일 컬럼 AUROC < 0.99 확인 |
| 근거 산출 | `tests/datasynth_quality_gate/results/phase2_fitting_audit/S0_column_classification.md`, `S1_leakage_columns_audit.json`, `S1_leakage_enforcement_plan.md` (round 1 기준 잔여 0건) |
| 완화안 | `phase2_training_service` 의 feature 후보 컬럼 목록에서 13 컬럼 영구 제외 + 회귀 테스트 (잔여 단일 컬럼 AUROC > 0.99 시 자동 deny 추가, 반복 한도 3회) |

### L-02 — `ip_address` 단일 컬럼 AUROC 0.9824 (deny-list 포함됨)

| 행 | 내용 |
|---|---|
| 상태 | **YELLOW** — S1 deny-list 에 포함되어 직접 입력 불가하나, 파생 피처 (예: 같은 IP 내 자기승인 빈도) 가 동일 누수를 우회 가능 |
| 근거 산출 | S0 표 `ip_address` 행 (AUROC 0.9824), 잔여 5 user feature 중 `created_by` AUROC 0.8199 |
| 완화안 | `ip_address` 기반 파생 피처 도입 시 자동 AUROC 검사 게이트 + Phase 2 plan 의 `feature_metadata` 에 `derived_from_ip_address` 플래그 등록 |

### L-03 — Stage 1 deny 후 잔여 user-aware 피처 5개 (`source` 0.9198, `supply_amount` 0.8936, `invoice_amount` 0.8932, `created_by` 0.8199, `auxiliary_account_number` 0.8093)

| 행 | 내용 |
|---|---|
| 상태 | **YELLOW** — round 1 audit 통과 (모두 < 0.99) 했으나 0.85 부근의 단일 컬럼 신호가 강하므로 조합/상호작용 발생 시 누수 가능 |
| 근거 산출 | `S1_leakage_enforcement_plan.md` round 1 잔여 Top 5 |
| 완화안 | round 2~3 audit (잔여 컬럼 + 단일 추가 후 단일 컬럼 AUROC 재측정) 자동화. CI 에 잔여 AUROC ≥ 0.95 회귀 가드 도입 |

### L-04 — Row-level random KFold 시 truth doc 88% 가 fold 양쪽에 노출

| 행 | 내용 |
|---|---|
| 상태 | **YELLOW** — `S2` 임계 (AUC gap > 0.05) 미충족이나 구조적 누수 절대값이 매우 큼. row-level 학습 절대 금지 정책 명문화 필요 |
| 근거 산출 | `S2_split_contamination.json` (row-level XGBoost AUC 0.9999 vs GroupKFold(doc) 0.9893), `S2_split_recommendation.md` §2.1 |
| 완화안 | `tests/preprocessing/test_split_strategy.py` 에 `test_random_split_rejects_row_level` 회귀 가드 추가 (기 권고) |

### L-05 — GroupKFold(document_id) 의 `created_by` 중첩률 100%

| 행 | 내용 |
|---|---|
| 상태 | **YELLOW** — 현 baseline 모델은 user feature 미사용으로 누수 격차 미확정. user-aware feature 도입 시 즉시 RED 전환 위험 |
| 근거 산출 | `S2_split_recommendation.md` §2.2 (per-fold user_overlap = 1.00) |
| 완화안 | `cv_selector.py` 에 `build_user_group_kfold` + `select_split_strategy(uses_user_features)` 분기 신설 (S2 §5.1) |

### L-06 — Time-based split (2022-2023 train / 2024 val) 의 user 중첩률 99.5%

| 행 | 내용 |
|---|---|
| 상태 | **YELLOW** — temporal hold-out 도 user-level 누수 차단 못함. 권장 default = TemporalHoldout(2024) ∩ inner StratifiedGroupKFold(created_by) 복합 split |
| 근거 산출 | `S2_split_recommendation.md` §2.3 (overlap 197/198 users) |
| 완화안 | `split_strategy.py::split_user_year_holdout` 신설 (S7 §5.1) — fiscal_year 분리 + user overlap 자동 제거 |

### L-07 — Trivial 단일 룰 (R1: amount p99.95 × 1.5) 가 fictitious_entry 168 건 모두 잡음 (recall=1.0), 다른 5 시나리오 recall=0

| 행 | 내용 |
|---|---|
| 상태 | **YELLOW** — Phase 2 ML floor 기준 (macro AUPRC ≥ 0.1292) 로 사용. 실 위험은 ML 이 fictitious 단일 시나리오에 fitting 되어 향상 폭이 다른 시나리오 가치를 가리는 것 |
| 근거 산출 | `artifacts/stage3_trivial_shortcut_baseline.json` (R1 macro_ap=0.1292), `S3_trivial_shortcut_baseline.md` |
| 완화안 | S4 P4 protocol 강제 (시나리오별 ML recall − trivial recall ≥ +0.05 미달 시 fitting 의심 마킹) |

### L-08 — `f_manual` 피처가 6개 시나리오 모두 1.0 포화 (정상 0.41, manipulated 1.0)

| 행 | 내용 |
|---|---|
| 상태 | **RED** — DataSynth v3 의 manipulation injection 이 모든 시나리오에 manual=true 를 동시 표식. ML 이 단축 학습 경로로 모든 manipulation 을 `f_manual=1` 로 잡을 위험 |
| 근거 산출 | `S4_scenario_detectability.md` §3 (target encoding heatmap), `S4_target_encoding_heatmap.csv` `manl` 컬럼 |
| 완화안 | (1) DataSynth manipulation v4 spec 에 manual flag 분포 의도적 노이즈 (예: 정상 0.41 ↔ manipulated 0.6~0.9) — `S9_zero_day_protocol_alternatives.md` 후보 C 옵션 2 와 통합. (2) 단기: `f_manual` 단독 입력 금지, `(f_manual & f_amount_high)` 등 조합 피처만 허용 |

### L-09 — Trivial 10-feature 합산만으로 4/6 시나리오가 top-1% 안 80%+ recall (circular 1.0, sod 0.967, period_end 0.816, fictitious 0.702, embezzlement 0.525, unusual_timing 1.0)

| 행 | 내용 |
|---|---|
| 상태 | **RED** — DataSynth v3 manipulation 이 binary feature 결합으로 거의 식별 가능. PHASE2 ML 의 macro recall 향상폭이 합성 shortcut 의 결과인지 실 판별인지 분리 불가 |
| 근거 산출 | `S4_scenario_detectability.md` §4 + `S4_scenario_recall.csv` |
| 완화안 | S4 P4 protocol 강제 + Phase 2 ML 평가 보고서에 trivial baseline 동시 표시 의무. RED→YELLOW 전환은 DataSynth v4 (L-08 와 함께) |

### L-10 — `unusual_timing_manipulation` 4 피처 (`f_weekend`, `f_offhour`, `f_manual`, `f_self_approval`) 모두 100% 동시 점등 → degenerate

| 행 | 내용 |
|---|---|
| 상태 | **RED** — 단일 deterministic 룰로 100% 분리되며 ML 이 정상-비정상 경계를 학습할 여지가 없음. manipulation v3 의 시나리오 설계 결함 |
| 근거 산출 | `S4_scenario_detectability.md` §3 + S4 P2 protocol (21 docs / 5-fold = fold-당 4 docs 무의미) |
| 완화안 | (1) 본 시나리오를 PHASE2 ML 평가 macro 가중치에서 0 또는 'low-N' 마커로 분리 (S4 P2). (2) DataSynth v4 에서 stealth 강화 (4 피처 중 일부만 점등) |

### L-11 — bootstrap 95% CI > 0.15 in `embezzlement_concealment` (0.224), `period_end_adjustment` (0.163)

| 행 | 내용 |
|---|---|
| 상태 | **YELLOW** — S4 P1 protocol 적용 시 단일 점추정 보고가 차단되어 실 위험 통제됨 |
| 근거 산출 | `S4_scenario_detectability.md` §4 표 (CI 폭 컬럼) |
| 완화안 | S4 P1 강제 (모든 recall 보고 시 bootstrap 95% CI 동반, CI > 0.15 시 `[insignificant]` 마커) |

### L-12 — Phase1 27룰 LR (S5) AUPRC 0.4398 — Phase 2 ML 이 룰 aggregate 대비 +0.05 향상 필요

| 행 | 내용 |
|---|---|
| 상태 | **YELLOW** — Phase 2 ML 의 macro AUPRC 게이트 (≥ 0.4898) 정의 완료, 미달 시 ML 부가가치 부재 판정 |
| 근거 산출 | `S5_circular_learning_overlap.json` (auprc_oof=0.4398), `S9_phase2_value_baseline.md` §2 |
| 완화안 | S9 의 5 게이트 (macro AUPRC + macro F2 + 2 시나리오별 recall + 4 시나리오 손실 한계) PHASE2 평가 entry 에 통합 |

### L-13 — VAE 학습 데이터에 manipulated 0.13% (≈336 docs) contamination

| 행 | 내용 |
|---|---|
| 상태 | **GREEN** — KS-test 결과 (held-out clean p=0.795) 정상 매니폴드 학습 무왜곡, AUC 변화 < 0.001 |
| 근거 산출 | `artifacts/s6_vae_contamination/ks_test_result.json`, `S6_vae_train_contamination.md` §4 |
| 완화안 | (보강) `compute_class_imbalance` 에 contamination 게이지 등록 + 운영 GL contamination > 0.5% 시 alarm. `tests/modules/test_detection/` 에 contamination tolerance 회귀 가드 |

### L-14 — BiLSTM stride=1 → 같은 truth 라인이 윈도우 컨텍스트로 16번 노출 (단일 fold 내 효율 손실 + 위치 편향)

| 행 | 내용 |
|---|---|
| 상태 | **YELLOW** — 단일 fold 내 데이터 효율 문제. fold 간 leakage 아님. config patch 1줄로 해소 |
| 근거 산출 | `S7_sequence_window_leakage.json` (target:context = 6.30%), `S7_sequence_split_redesign.md` §1 |
| 완화안 | `config/settings.py::bilstm_stride` 기본값 1 → 16 (또는 `seq_len`). detect() 의 stride=1 은 운영 추론용으로 유지 (S7 §5.2-5.3) |

### L-15 — BiLSTM cross-user temporal context leakage — val truth 의 75% 가 train 에 ±7일 인접 (다른 user 의 같은 시점 컨텍스트 학습 후 평가)

| 행 | 내용 |
|---|---|
| 상태 | **RED** — 현 split 정책 (GroupShuffleSplit by user) 으로는 시간축 분리 불가. fiscal_year hold-out 미적용. BiLSTM 트랙 보류 권고 |
| 근거 산출 | `S7_sequence_window_leakage.json` §3.2 (74.8%), `S7_sequence_split_redesign.md` §3-4 |
| 완화안 | (1) `split_user_year_holdout` 신설 (S7 §5.1) — train=2022-2023, test=2024, user overlap 자동 제거. (2) 패치 적용 후 재측정 — §3.1 ratio < 5% 미달 시 BiLSTM 트랙 PHASE2 본 평가 제외 (S7 §5.4) |

### L-16 — Stacking OOF 의 '룰/VAE 1회 학습 + supervised OOF' 정책 누수 가능성

| 행 | 내용 |
|---|---|
| 상태 | **GREEN** — A vs B ablation 결과 AUPRC gap +0.0009 ≪ 0.02 임계, 룰 트랙 가중치 비중 2.2% ≪ 50% |
| 근거 산출 | `S8_stacking_oof_ablation.json`, `S8_stacking_oof_audit.md` |
| 완화안 | (보강) approval_sod_bypass 시나리오만 단일 +0.1461 gap → PHASE2 회귀 KPI 에 본 시나리오 단일 AUPRC 별도 기록 권고 |

### L-17 — raw-plan D027 hold-out fraud type (`suspense_account_abuse`, `expense_capitalization`) 가 v3 manipulation truth 에 부재

| 행 | 내용 |
|---|---|
| 상태 | **YELLOW** — v2 와 cross hold-out 도 불가 (v2 = v3 라벨 동일). 후보 A (v3 prevalence 하위 2개 hold-out) 채택 시 통계적 caveat (n=50, ±14pp) 명시 |
| 근거 산출 | `S9_zero_day_protocol_alternatives.md` §2-3 |
| 완화안 | (단기) 후보 A — `unusual_timing_manipulation` (21) + `approval_sod_bypass` (29) hold-out, 합산 recall ≥ 0.5 게이트. (장기) DataSynth manipulation v4 에 두 시나리오 신규 생성 (n≥100 each) |

## 4. PHASE2 ML 학습 시작 전 강제 사전 조건 체크리스트

본 체크리스트의 **모든 항목 통과** 가 PHASE2 ML 학습 sprint 시작 조건이다. 미달 시 PHASE2 진행 보류.

### 4.1 deny-list 적용 (L-01, L-02, L-03)

- [ ] `phase2_training_service` 가 13 컬럼 deny-list 를 강제 (`detection_surface_hints`, `document_id`, `document_number`, `header_text`, `ip_address`, `mutation_base_event_type`, `mutation_mutated_field`, `mutation_mutated_value`, `mutation_original_value`, `mutation_reason`, `mutation_type`, `reference`, `semantic_scenario_id`)
- [ ] feature 후보 행렬에서 잔여 단일 컬럼 AUROC ≥ 0.99 자동 deny (round 한도 3회) 통과
- [ ] CI 회귀 가드: 잔여 AUROC ≥ 0.95 시 빌드 실패

### 4.2 Split 전략 (L-04, L-05, L-06)

- [ ] 기본 split = `GroupKFold(groups=document_id, n_splits=5)`. row-level random KFold 호출 시 ValueError
- [ ] feature_metadata.uses_user_features=True 시 자동 `GroupKFold(groups=created_by)` 전환
- [ ] 시계열 일반화 평가 시 `split_user_year_holdout(train=2022-2023, test=2024, assert_no_user_overlap=True)` 적용
- [ ] 모든 fold 의 `set(users[train]) ∩ set(users[val]) == ∅` assertion 통과

### 4.3 VAE 정상 필터 (L-13)

- [ ] `vae_detector.train()` 입력 X 의 contamination 비율 측정 + 학습 metadata 기록
- [ ] contamination > 0.5% 시 빌드 경고 (현 v3 은 0.13% 안전 범위)
- [ ] ECDF 정규화 (`_ecdf_transform`) 가 추론 경로에 적용 — 회귀 가드

### 4.4 Sequence (BiLSTM) window 분할 (L-14, L-15)

- [ ] `config/settings.py::bilstm_stride` 기본값 = 16 (또는 `seq_len`). 학습 시 stride 적용, detect 시 stride=1 유지
- [ ] `split_user_year_holdout` 적용 후 §3.1 (정확 날짜 매칭 overlap) < 5% 통과 — **미달 시 BiLSTM 트랙 본 평가 제외**
- [ ] §3.2 (±7일 인접 매칭) < 20% 통과 — **미달 시 BiLSTM 트랙 본 평가 제외**

### 4.5 OOF 정책 (L-16)

- [ ] `ensemble_detector.train_oof()` 의 `_LEAKAGE_PRONE_TRACKS = (ML_SUPERVISED, ML_TRANSFORMER, ML_SEQUENCE)` 유지 (S8 검증 통과)
- [ ] approval_sod_bypass 시나리오 단일 AUPRC 를 회귀 KPI 에 별도 기록

### 4.6 Hold-out 전략 (L-17)

- [ ] 단기: `unusual_timing_manipulation` + `approval_sod_bypass` (50 docs 합산) 을 train 에서 완전 제외 + test 에서 별도 보고
- [ ] 모든 hold-out 결과에 `n=50, 95% CI ≈ ±14pp` caveat 명시
- [ ] 장기 plan: DataSynth manipulation v4 profile spec 작성 (S9 후보 C 옵션 2)

## 5. PHASE2 평가 protocol 강제 항목

PHASE2 평가 보고서는 다음 5개 항목을 모두 만족해야 머지 가능 (S4 P1~P5 + S9 게이트 통합).

### 5.1 CI 동봉 (S4 P1)

- 모든 recall / precision / F2 보고에 bootstrap 95% CI 동봉 (`n_bootstrap=1000`, seed 명시)
- CI 폭 > 0.15 시나리오는 `[insignificant]` 마커 + 점추정 비교 금지

### 5.2 시나리오별 recall 강제 (S4 P2, P5)

- 6 시나리오 각각의 fold × scenario truth count matrix 첨부
- `unusual_timing_manipulation` (21 docs) 은 fold-level 통계 금지, 통합 recall 만 보고
- 어떤 시나리오라도 fold 의 truth count < 5 시 fold-level 통계 대신 통합값만 보고

### 5.3 Trivial baseline 동시 보고 (S4 P4 + L-09)

- 10 trivial binary feature 합산 (`f_weekend`, `f_offhour`, `f_manual`, `f_no_approver`, `f_self_approval`, `f_sod_violation`, `f_no_attachment`, `f_quarter_end`, `f_year_end`, `f_amount_high`) score 를 동일 fold 구성에서 측정
- 시나리오별 ML recall − trivial recall (`Δrecall`) 명시
- Δrecall < 0.05 시나리오는 'fitting 의심' 마킹

### 5.4 Phase 2 ML 부가가치 5 게이트 (S9)

```
필수 1: ensemble OOF macro AUPRC ≥ 0.4898 (= S5 27룰 LR 0.4398 + 0.05)
필수 2: ensemble OOF macro F2 @ top-1% ≥ 0.118 (= S5 0.0679 + 0.05)
필수 3: embezzlement_concealment recall @ top-1% ≥ 0.495
필수 4: circular_related_party recall @ top-1% ≥ 0.276
조건 5: 다른 4 시나리오 recall 손실 |Δ| < 0.05
```

5/5 통과 시 ML 부가가치 인정. 4/5 이하 시 Phase1 룰 + score_aggregator 단독 운영, ML 은 보조 신호로만.

### 5.5 macro-F2 prevalence 가중 동시 (S4 P3)

- 단순 평균 (unweighted) + prevalence-weighted 두 값 동시 보고
- 두 값 격차 ≥ 0.05 시 prevalence skew 경고 적시

## 6. 미해결 위험과 후속 조사 항목

### 6.1 DataSynth manipulation v4 신규 생성 (L-08, L-09, L-10, L-17)

**범위**:
- 6 + 2 = 8 시나리오 (기존 6 + `suspense_account_abuse` + `expense_capitalization`)
- shortcut feature 분포 설계 의도적 노이즈 (`f_manual` 0.41↔0.6-0.9, `unusual_timing` 4 피처 stealth split)
- 신규 hold-out 2 시나리오는 n ≥ 100 each
- v3 와의 truth 호환성 (legacy migration 경로 명시)

**구현 위치**: `tools/datasynth/crates/datasynth-cli/src/manipulation_v4.rs`
**비용 추정**: Rust profile 설계 + 빌드 + Phase1 회귀 검증 2-3 일

### 6.2 datasynth_contract_v2 결합 평가 (L-09 보강)

**근거**: contract_v2 에 `expense_capitalization_plausible_cases` (33), `rule_truth_L3_09` (suspense aging) 등 raw-plan 의도와 부합하는 sidecar 가 존재. manipulation truth 와는 다른 추상화이지만 PHASE2 ML 의 zero-day 평가 보조 라벨로 활용 가능.

**조사 항목**:
- contract sidecar truth 와 manipulation truth 의 doc 중복도 측정
- contract truth 만으로 학습한 ML 모델의 manipulation truth recall 측정 (cross-truth transfer 평가)
- contract truth 의 PHASE2 ML 입력 노출 시 leakage 위험 (contract = rule 발화 정답지이므로 룰 입력과 직접 연결 위험)

### 6.3 BiLSTM 패치 후 재측정 (L-15)

**조건**: S7 §5.1 (`split_user_year_holdout`) + §5.2 (`bilstm_stride=16`) 적용 후 S7 §3 재실행
**통과 기준**: §3.1 < 5%, §3.2 < 20%, val F1 - doc-level recall 격차 < 15pp
**미통과 시**: BiLSTM 트랙 PHASE2 본 평가 제외, FTTransformer (행 단위) + VAE (비지도) 만 유지

### 6.4 Stacking OOF 8 트랙 ablation (L-16 보강)

**범위**: S8 의 6 트랙 (룰 4 + supervised + IF) 에 ml_transformer + ml_sequence 두 트랙 추가하여 동일 ablation 재실행
**조건**: BiLSTM 패치 (6.3) 통과 후, 데이터 재생성 (6.1) 시점에 통합 호출
**비용**: ft_ablation_study.py 본 호출 (현재 `--dry-run` 만 동작) + S8 ablation 통합

## 7. CONSTRAINTS / DECISION 패치 제안 (요약)

### 7.1 `docs/spec/CONSTRAINTS.md` §ML 학습 전략 추가 항 (확정)

```markdown
### Phase 2 ML 학습 전 강제 사전 조건 (Stage 10 Audit, 2026-05-15)

PHASE2 ML 학습 sprint 시작은 다음 6 항목 모두 통과를 전제로 한다.

1. Stage 1 deny-list 13 컬럼 강제 + 잔여 단일 컬럼 AUROC < 0.99 (S0/S1)
2. GroupKFold(document_id) + user-aware feature 시 GroupKFold(created_by) 자동 전환 (S2)
3. VAE contamination 비율 측정 + 0.5% 임계 alarm (S6)
4. BiLSTM 트랙은 split_user_year_holdout 적용 후 cross-user temporal overlap < 5% 통과까지 보류 (S7)
5. Stacking OOF 정책 = 룰/VAE 1회 학습 + supervised/transformer/sequence OOF (S8 검증 통과)
6. S5 Top-5 룰 LEAKAGE_DENY_RULES (`L3-02`, `L1-05`, `L1-09`, `L2-03`, `L2-02`) 을 Phase 2 ML 입력 행렬에서 제거 + PHASE3 narrator 입력으로만 노출 (S5 §5, Top-5 deny 시 AUPRC 0.4398 → 0.0013)

근거 audit: docs/spec/PHASE2_FITTING_AUDIT.md, artifacts/S5_phase2_input_redesign.md
```

### 7.2 `docs/spec/DECISION.md` 추가 결정 (D040 / D041 / D042 — 확정)

```markdown
### D040: Phase 2 ML 평가 강제 protocol (Stage 10 Audit 통합)

- 결정: PHASE2 ML 평가 보고서는 다음 5 + 1 항목 모두 만족 시에만 머지 가능
  (1) bootstrap 95% CI 동봉, CI > 0.15 시 [insignificant] 마커
  (2) 시나리오별 fold × scenario truth count matrix 첨부
  (3) 10 trivial binary feature 합산 baseline 동시 보고, Δrecall < 0.05 시 fitting 의심 마킹
  (4) Phase 2 ML 부가가치 5 게이트 (S9 정의) 통과
  (5) macro-F2 unweighted + prevalence-weighted 두 값 동시 보고
  (6) anti-shortcut cap — Top-5 LEAKAGE_DENY_RULES 제거 후 재학습 ML 앙상블의 macro AUPRC 잔존율 ≥ 30% AND 절대값 ≥ 0.30 통과
- 사유: v3 dataset 의 합성 shortcut 위험 (S4 RED L-08~L-10) 으로 ML 향상 폭이 fitting 결과인지 실 판별인지 분리 필요
- 영향 범위: phase2_training_service, phase2 평가 entry, CI workflow
- 관련 audit: docs/spec/PHASE2_FITTING_AUDIT.md, S4_evaluation_protocol.md, S9_phase2_value_baseline.md, S5_phase2_input_redesign.md

### D041: BiLSTM 트랙 PHASE2 본 평가 보류 조건 (Stage 7 + 10 Audit)

- 결정: BiLSTM (ML_SEQUENCE) 트랙은 다음 3 조건 모두 통과 시에만 PHASE2 본 평가 포함
  (1) split_user_year_holdout 적용 후 정확 날짜 매칭 overlap < 5%
  (2) ±7일 인접 매칭 overlap < 20%
  (3) val F1 (시퀀스 단위) 와 doc-level recall 격차 < 15pp
- 미통과 시 본 평가 제외, FT-Transformer + VAE + Supervised 7 트랙 ensemble 만 유지
- 사유: S7 측정 결과 cross-user temporal context leakage 75% (val truth 의 75% 가 train 의 ±7일 인접 시점 학습)
- 관련 audit: artifacts/S7_sequence_split_redesign.md

### D042: DataSynth manipulation v4 spec 우선순위 (Stage 10 Audit, 장기)

- 결정: PHASE2 ML 정식 평가 직전에 DataSynth manipulation v4 profile 신규 빌드. v3 의 6 시나리오 + 2 hold-out 시나리오 (suspense_account_abuse, expense_capitalization) 추가. shortcut 분포 노이즈화 (f_manual 0.41 ↔ 0.6-0.9, unusual_timing 4 피처 stealth split 등)
- 사유: Stage 10 audit RED 4건 중 3건 (L-08/L-09/L-10) 이 v3 합성 설계 결함에서 비롯. 단기 mitigation 으로는 fitting 위험 자체 제거 불가
- 비용: Rust profile 설계 + 빌드 + 검증 2-3 일
- 관련 audit: docs/spec/PHASE2_FITTING_AUDIT.md, docs/archive/completed/S9_zero_day_protocol_alternatives.md §3.3
```

상세 diff 는 [`docs/spec/PHASE2_FITTING_AUDIT.md`](../../../../docs/spec/PHASE2_FITTING_AUDIT.md) §6 참조.

## 8. 후속 액션

### 8.1 즉시 (이 sprint 내)

- [ ] CONSTRAINTS.md / DECISION.md 패치 PR 작성 (위 §7) — D040 / D041 / D042 포함
- [ ] `phase2_training_service` 에 13 deny 강제 + AUROC 회귀 가드 (L-01~L-03, PR#1)
- [ ] `cv_selector.py` user feature 분기 (L-05, L-06, PR#2)
- [ ] `config/settings.py::bilstm_stride` 기본값 16 (L-14, PR#7)
- [ ] S5 Top-5 룰 LEAKAGE_DENY_RULES (`L3-02`, `L1-05`, `L1-09`, `L2-03`, `L2-02`) 을 `phase2_plan` 에서 제거 + PHASE3 narrator 입력으로만 노출 (L-09 보강, PR#11)
- [ ] S9 6번째 게이트 anti-shortcut cap (Top-5 deny 후 잔존율 ≥ 30% AND 절대값 ≥ 0.30) PHASE2 평가 entry 통합 (L-09 보강, PR#12)
- [ ] macro AUPRC floor = 0.4898 → **0.482** (fold mean 95% CI 상한 + 0.05) 로 갱신 (L-12 보강, PR#15)

### 8.2 단기 (다음 sprint)

- [ ] `split_strategy.py::split_user_year_holdout` 신설 + BiLSTM 재측정 (L-15, PR#8)
- [ ] PHASE2 evaluation entry 에 S4 P1~P5 + S9 5 + 1 게이트 (anti-shortcut cap 포함) 통합 (RED→YELLOW 전환 가드, PR#4 + PR#12)
- [ ] 후보 A hold-out protocol (L-17 단기) 적용 (PR#9)
- [ ] contamination ratio 게이지 `compute_class_imbalance` 등록 + 운영 GL > 0.5% alarm + 회귀 가드 (L-13 보강, S6 §5.2, PR#13)

### 8.3 장기 (Phase 2 ML 정식 평가 직전)

- [ ] DataSynth manipulation v4 spec 수립 + 빌드 (L-08, L-09, L-10, L-17 장기, D042)
- [ ] v4 active 승격 시 `tools/analysis/s8_stacking_oof_ablation.py` 자동 재실행 + macro AUPRC delta 비교 + Phase1 회귀 검증 통합 (PR#14)
- [ ] contract_v2 결합 평가 (6.2)
- [ ] Stacking OOF 8 트랙 ablation 통합 (6.4)

### 8.4 RED 판정 조건 발생 시

본 audit 의 4 RED 중 하나라도 mitigation 미적용으로 PHASE2 평가에 진입 시 → 즉시 평가 중단 + 본 SUMMARY.md 재발행 + 새 audit cycle 트리거.
