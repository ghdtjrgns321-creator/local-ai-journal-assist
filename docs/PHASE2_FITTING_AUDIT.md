# PHASE 2 ML Fitting Audit — Stage 0~10 종합 entry-point

> 측정 일자: 2026-05-15 (v3 baseline) · v4 재검증 2026-05-16
> 데이터셋 (active): `data/journal/primary/datasynth_manipulation_v4_candidate` (manipulation v4, D048 active 2026-05-16)
> 데이터셋 (reference): `data/journal/primary/datasynth_manipulation_v3` (회귀 비교용)
> 목적: PHASE2 ML 학습/평가 파이프라인의 fitting risk 종합 진단 + 진행 권고
> 단일 entry-point — 본 문서가 모든 S0~S9 산출의 통합 색인

> **2026-05-16 v4 재검증 결과 (RED → YELLOW 부분 전환)**
> DataSynth manipulation v4 가 RED 4건 중 데이터 측 3건 (L-08 `f_manual`,
> L-09 trivial shortcut, L-10 unusual_timing degenerate) 의 데이터 원인을
> 제거했다. S3 trivial macro AP 0.1292 → 0.0237 (81.7%↓), S4 trivial top-1%
> 4/6 ≥0.80 → 2 시나리오만 1.0 잔존 (`circular_related_party`,
> `unusual_timing_manipulation`), unusual_timing all-four shortcut share 0.0,
> normal `f_manual` rate 0.4144 (정상 분포 회복).
> 잔존 RED: **L-15 BiLSTM cross-user temporal leakage** (S7 protocol 작업) +
> Phase2 supervised raw feature leak (S8 A_current_policy AUPRC=0.9901 →
> S9 anti-shortcut cap ratio≈39.6, BLOCK 유지) — 모두 모델 설계 측 작업.
> 재검증 trace: [`artifacts/manipulation_v4_audit_rerun_summary_20260516.md`](../artifacts/manipulation_v4_audit_rerun_summary_20260516.md)


> **포트폴리오 주장 범위 (2026-05-19)**: 이 프로젝트는 `fraud`를 판정하거나 실제 운영 부정 탐지 성능을 보장하는 모델이 아니다. 전수 모집단에서 감사인이 먼저 볼 review queue를 만들고, 무작위 검토 대비 상위 구간에 review-worthy synthetic anomaly를 강하게 농축하는 로컬 감사 분석 보조 도구다. DataSynth 기반 precision/recall은 개발 검증 보조 지표이며, 실데이터 운영 성능으로 주장하지 않는다.
> **금지 표현**: "부정을 정확히 탐지", "실무 운영 성능 검증 완료", "TOP100 precision 충분", "fraud 확정/자동 적발"처럼 확정적이거나 운영 성능을 보장하는 표현은 사용하지 않는다.

---

## 0. 종합 판정

| 항목 | 값 |
|---|---|
| 전체 위험 | 17 (L-01 ~ L-17) |
| GREEN | **3** (L-01, L-13, L-16) |
| YELLOW | **13** (L-02, L-03, L-04, L-05, L-06, L-07, L-08†, L-09†, L-10†, L-11, L-12, L-14, L-17) |
| RED | **1** (L-15) — 추가로 Phase2 supervised raw feature leak 신규 RED 식별 (S8/S9 재측정) |
| **종합 판정** | **YELLOW (Phase 2 conditional GO, v4 데이터 측 해소 완료)** |

† v4 active lock (2026-05-16) 으로 RED→YELLOW 전환. 데이터 측 원인은 제거되었고 모델/평가 protocol 안전장치 (S4 P2 low-N 마커, S9 anti-shortcut cap) 는 유지.

**판정 근거**: 데이터 측 RED 3건 (L-08/L-09/L-10) 은 v4 빌드로 YELLOW 전환. 잔존 RED 1건 (L-15 BiLSTM cross-user temporal) 과 S8 supervised leak 은 모델 설계 측 작업 (raw feature 재구성 / split protocol 변경). v4 데이터셋 위에서는 PHASE2 conditional GO 가 유지된다.

상세 SUMMARY: [`tests/datasynth_quality_gate/results/phase2_fitting_audit/SUMMARY.md`](../tests/datasynth_quality_gate/results/phase2_fitting_audit/SUMMARY.md)

---

## 1. Stage 0~9 산출 색인

| Stage | 주제 | 산출 |
|---|---|---|
| S0 | Column catalog & leakage classification | [`S0_column_classification.md`](../tests/datasynth_quality_gate/results/phase2_fitting_audit/S0_column_classification.md), `S0_column_catalog.json` |
| S1 | Label leakage deny-list enforcement | [`S1_leakage_enforcement_plan.md`](../tests/datasynth_quality_gate/results/phase2_fitting_audit/S1_leakage_enforcement_plan.md), `S1_leakage_columns_audit.json` |
| S2 | Split contamination | [`artifacts/S2_split_recommendation.md`](../artifacts/S2_split_recommendation.md), `artifacts/S2_split_contamination.json` |
| S3 | Trivial baseline | [`docs/completed/S3_trivial_shortcut_baseline.md`](completed/S3_trivial_shortcut_baseline.md), `artifacts/stage3_trivial_shortcut_baseline.json` |
| S4 | Scenario detectability + 평가 protocol | [`artifacts/S4_scenario_detectability.md`](../artifacts/S4_scenario_detectability.md), [`artifacts/S4_evaluation_protocol.md`](../artifacts/S4_evaluation_protocol.md) |
| S5 | Phase1 룰 ↔ manipulated truth 순환학습 | [`artifacts/S5_phase2_input_redesign.md`](../artifacts/S5_phase2_input_redesign.md), `artifacts/S5_circular_learning_overlap.json` |
| S6 | VAE 학습 데이터 오염 | [`artifacts/s6_vae_contamination/S6_vae_train_contamination.md`](../artifacts/s6_vae_contamination/S6_vae_train_contamination.md), `S6_label_strategy_patch.md`, `ks_test_result.json` |
| S7 | BiLSTM sequence window leakage + split redesign | [`artifacts/S7_sequence_split_redesign.md`](../artifacts/S7_sequence_split_redesign.md), `artifacts/S7_sequence_window_leakage.json` |
| S8 | Stacking OOF protocol 재검증 | [`docs/completed/S8_stacking_oof_audit.md`](completed/S8_stacking_oof_audit.md), `artifacts/S8_stacking_oof_ablation.json` |
| S9 | Phase 2 ML 부가가치 baseline + zero-day 대안 | [`docs/completed/S9_phase2_value_baseline.md`](completed/S9_phase2_value_baseline.md), [`docs/completed/S9_zero_day_protocol_alternatives.md`](completed/S9_zero_day_protocol_alternatives.md) |
| S10 | 종합 판정 (본 문서) | [`docs/PHASE2_FITTING_AUDIT.md`](PHASE2_FITTING_AUDIT.md), `tests/datasynth_quality_gate/results/phase2_fitting_audit/SUMMARY.md` |

---

## 2. 17 위험 매트릭스

| ID | 위험 | 상태 | 출처 | 핵심 측정값 |
|---|---|---|---|---|
| L-01 | Stage 0 라벨 누수 컬럼 18개 | **GREEN** | S0/S1 | deny 적용 후 잔여 단일 AUROC < 0.99 |
| L-02 | `ip_address` 단일 AUROC 0.9824 | YELLOW | S0/S1 | deny 포함, 파생 피처 우회 위험 |
| L-03 | 잔여 user-aware 5 feature (0.81-0.92) | YELLOW | S1 | round audit 한도 3회 통과 |
| L-04 | row-level random KFold 88% truth 누수 | YELLOW | S2 | row XGBoost AUC 0.9999 |
| L-05 | GroupKFold(doc) user_overlap 100% | YELLOW | S2 | user feature 도입 시 RED 전환 |
| L-06 | Time split user_overlap 99.5% | YELLOW | S2 | 197/198 user 양쪽 |
| L-07 | trivial R1 단독 fictitious recall=1, 다른 5=0 | YELLOW | S3 | macro AP 0.1292 (Phase 2 floor) |
| L-08 | `f_manual` 6 시나리오 모두 1.0 포화 | **YELLOW** (v4 2026-05-16) | S4 | v4: 정상 0.4144 ↔ 시나리오별 0.45-0.79 (포화 해소). 원본 v3: 정상 0.41 ↔ manipulated 1.0 |
| L-09 | trivial 10-feature 합산 4/6 시나리오 80%+ recall | **YELLOW** (v4 2026-05-16) | S4 | v4: 2 시나리오만 1.0 잔존 (circular, unusual_timing), 신규 hold-out 2개 0.0/0.29. macro AP floor 0.0237 (81.7%↓) |
| L-10 | unusual_timing 4피처 100% 동시 점등 (degenerate) | **YELLOW** (v4 2026-05-16) | S4 | v4: all-four share = 0.0, pattern count = 4 (offhour_manual/offhour_self_approval/weekend_manual_self_approval/weekend_offhour). 시나리오 단독 보고는 여전히 n=21 금지 |
| L-11 | bootstrap CI > 0.15 (embezzlement, period_end) | YELLOW | S4 | 0.224 / 0.163 |
| L-12 | Phase1 27룰 LR AUPRC 0.4398 (Phase 2 게이트) | YELLOW | S5/S9 | Phase 2 ML 목표 ≥ 0.4898 |
| L-13 | VAE training contamination 0.13% | **GREEN** | S6 | KS p=0.795, AUC Δ < 0.001 |
| L-14 | BiLSTM stride=1 16x context 중복 | YELLOW | S7 | target:context = 6.30% |
| L-15 | BiLSTM cross-user temporal 75% ±7d overlap | **RED** | S7 | val truth 75% 가 train 인접 시점 학습됨 |
| L-16 | Stacking OOF 룰/VAE 1회 학습 정책 | **GREEN** | S8 | A−B AUPRC = +0.0009 ≪ 0.02 |
| L-17 | raw-plan hold-out fraud type 부재 | YELLOW | S9 | v3 와 v2 라벨 동일, 후보 A 정의 |

각 위험의 [상태/근거 산출/완화안] 3행 상세는 SUMMARY.md §3 참조.

---

## 3. PHASE 2 진행 권고

### 3.1 분기 결정

| 판정 | 권고 |
|---|---|
| GREEN | 즉시 진행 + `phase2_ml_feasibility.md` 에 audit 통과 footnote 추가 |
| **YELLOW (현재)** | **PHASE2 conditional GO** — §4 사전 조건 + §5 평가 protocol 모두 통과 시 본 평가 진입 |
| RED | PHASE2 보류 + DataSynth manipulation v4 spec 수립 (L-08/L-09/L-10/L-17 장기 mitigation 통합) |

### 3.2 RED 4건의 mitigation 경로 (필수)

| 위험 | mitigation | 적용 sprint | 효과 |
|---|---|---|---|
| L-08 (`f_manual` 포화) | 단기: ML 입력에서 `f_manual` 단독 금지, 조합 피처만 허용 / 장기: DataSynth v4 manual 분포 노이즈화 | 단기=즉시, 장기=v4 빌드 | 단기 → YELLOW, 장기 → GREEN |
| L-09 (trivial shortcut) | S4 P4 강제 (시나리오별 Δrecall ≥ 0.05 게이트) + S9 6 게이트(anti-shortcut cap 포함) | 즉시 | YELLOW |
| L-10 (unusual_timing degenerate) | S4 P2 (시나리오 macro 가중치 0 또는 'low-N' 마커) | 즉시 | YELLOW |
| L-15 (BiLSTM temporal leakage) | S7 §5.1 + §5.2 (split_user_year_holdout + stride=16) 후 재측정. 미통과 시 BiLSTM 트랙 본 평가 제외 | 단기 | YELLOW (보류) 또는 GREEN (재측정 통과 시) |

---

## 4. PHASE 2 ML 학습 시작 전 강제 사전 조건

[SUMMARY.md §4](../tests/datasynth_quality_gate/results/phase2_fitting_audit/SUMMARY.md#4-phase2-ml-학습-시작-전-강제-사전-조건-체크리스트) 와 동일.

요약:

```
[deny-list]    13 컬럼 강제 + 잔여 AUROC < 0.99 round 한도 3회
[split]        GroupKFold(document_id) + user feature 시 GroupKFold(created_by) 자동 전환
               + 시계열 일반화 시 split_user_year_holdout
[VAE]          contamination 비율 측정 + 0.5% 임계 alarm
[BiLSTM]       stride=16 + split_user_year_holdout + cross-user overlap < 5% 통과까지 보류
[Stacking OOF] 현행 정책 유지 (S8 검증 통과)
[hold-out]     단기 = 후보 A (unusual_timing + sod_bypass), 장기 = DataSynth v4
```

---

## 5. PHASE 2 평가 protocol 강제 항목

[SUMMARY.md §5](../tests/datasynth_quality_gate/results/phase2_fitting_audit/SUMMARY.md#5-phase2-평가-protocol-강제-항목) 와 동일.

5 항목:

1. **CI 동봉** (S4 P1) — bootstrap 95% CI, 폭 > 0.15 시 [insignificant]
2. **시나리오별 truth count matrix** (S4 P2/P5) — fold × scenario, n<5 fold 통계 금지
3. **Trivial baseline 동시 보고** (S4 P4) — Δrecall < 0.05 시 fitting 의심 마킹
4. **Phase 2 ML 부가가치 6 게이트** (S9) — macro AUPRC + macro F2 + 2 시나리오 recall + 4 시나리오 손실 한계 + anti-shortcut cap (`ensemble macro AUPRC / trivial_10feature macro AUPRC ≤ 4.0`, 초과 시 DataSynth v4 전까지 BLOCK)
5. **macro-F2 prevalence 가중 동시** (S4 P3) — unweighted + weighted 두 값

§5.4 의 anti-shortcut cap 은 S4 P4 `Δrecall ≥ 0.05` 와 **AND 조건**으로 결합한다. 둘 중 하나라도 미달하면 PHASE2 promotion gate 는 BLOCK 이며, 0.99급 ensemble AUPRC 가 trivial 10-feature baseline 대비 4배를 초과하는 경우는 synthetic shortcut 의심으로 별도 마킹한다.

---

## 6. CONSTRAINTS / DECISION 패치 제안 diff

### 6.1 `docs/CONSTRAINTS.md` — §ML 학습 전략 신규 sub-section 추가

**적용 위치**: `## ML 학습 전략: 비지도학습 중심 + 지도학습 프레임워크` 섹션 말미에 추가

```diff
@@ docs/CONSTRAINTS.md (## ML 학습 전략 섹션 말미) @@

+### Phase 2 ML 학습 전 강제 사전 조건 (Stage 10 Audit, 2026-05-15)
+
+PHASE2 ML 학습 sprint 시작은 다음 5 항목 모두 통과를 전제로 한다.
+미통과 시 PHASE2 진행 보류 + 본 audit 재발행.
+
+1. **deny-list (S0/S1)**: `phase2_training_service` 가 13 컬럼 deny-list 강제
+   (`detection_surface_hints`, `document_id`, `document_number`, `header_text`,
+   `ip_address`, `mutation_base_event_type`, `mutation_mutated_field`,
+   `mutation_mutated_value`, `mutation_original_value`, `mutation_reason`,
+   `mutation_type`, `reference`, `semantic_scenario_id`).
+   잔여 단일 컬럼 AUROC ≥ 0.99 자동 deny (round 한도 3회).
+2. **split 전략 (S2)**: 기본 = `GroupKFold(groups=document_id, n_splits=5)`.
+   row-level random KFold 호출 시 ValueError. user-aware feature 도입 시
+   `GroupKFold(groups=created_by)` 자동 전환. 시계열 일반화 평가 시
+   `split_user_year_holdout(train=2022-2023, test=2024)` 적용.
+3. **VAE contamination (S6)**: `vae_detector.train()` 입력 X 의 contamination
+   비율 측정 + 학습 metadata 기록. 0.5% 초과 시 빌드 경고.
+4. **BiLSTM 트랙 보류 (S7)**: `split_user_year_holdout` 적용 후 cross-user
+   temporal overlap (정확 날짜 매칭 < 5%, ±7일 인접 < 20%) 통과까지 PHASE2
+   본 평가에서 제외.
+5. **Stacking OOF 정책 (S8)**: `_LEAKAGE_PRONE_TRACKS` =
+   (ML_SUPERVISED, ML_TRANSFORMER, ML_SEQUENCE) 유지. 룰/VAE 1회 학습 +
+   leakage-prone 트랙만 fold-wise OOF.
+
+근거 audit: `docs/PHASE2_FITTING_AUDIT.md`,
+`tests/datasynth_quality_gate/results/phase2_fitting_audit/SUMMARY.md`.
+
+### Phase 2 ML 평가 protocol 강제 항목 (Stage 10 Audit, 2026-05-15)
+
+PHASE2 ML 평가 보고서는 다음 5 항목 모두 만족 시에만 머지 가능.
+위반 시 평가 결과는 PHASE2 promotion gate 를 통과할 수 없다.
+
+1. **CI 동봉 (S4 P1)**: 모든 recall/precision/F2 보고에 bootstrap 95% CI 동봉
+   (`n_bootstrap=1000`, seed 명시). CI 폭 > 0.15 시 `[insignificant]` 마커 +
+   점추정 비교 금지.
+2. **시나리오별 truth count matrix (S4 P5)**: fold × scenario truth count
+   matrix 첨부. 어떤 시나리오라도 fold 의 truth count < 5 시 fold-level
+   통계 금지, 통합값만 보고. `unusual_timing_manipulation` (n=21) 은
+   fold-level 보고 금지 (S4 P2).
+3. **Trivial baseline 동시 보고 (S4 P4)**: 10 trivial binary feature 합산
+   (`f_weekend`, `f_offhour`, `f_manual`, `f_no_approver`, `f_self_approval`,
+   `f_sod_violation`, `f_no_attachment`, `f_quarter_end`, `f_year_end`,
+   `f_amount_high`) 동시 측정. 시나리오별 Δrecall < 0.05 시 'fitting 의심'
+   마킹.
+4. **Phase 2 ML 부가가치 6 게이트 (S9)**:
+   - macro AUPRC ≥ 0.4898 (S5 27룰 LR + 0.05)
+   - macro F2 @ top-1% ≥ 0.118
+   - embezzlement_concealment recall @ top-1% ≥ 0.495
+   - circular_related_party recall @ top-1% ≥ 0.276
+   - 다른 4 시나리오 recall 손실 |Δ| < 0.05
+   - ensemble macro AUPRC / trivial_10feature macro AUPRC ≤ 4.0
+     (4배 초과 시 shortcut 의심, DataSynth v4 전까지 BLOCK)
+   - S4 P4 Δrecall ≥ 0.05 와 anti-shortcut cap 은 OR 가 아닌 AND 조건
+5. **macro-F2 prevalence 가중 동시 (S4 P3)**: unweighted + prevalence-weighted
+   두 값 동시 보고. 격차 ≥ 0.05 시 prevalence skew 경고.
+
+근거 audit: `docs/PHASE2_FITTING_AUDIT.md`,
+`artifacts/S4_evaluation_protocol.md`, `docs/completed/S9_phase2_value_baseline.md`.
```

### 6.2 `docs/DECISION.md` — D040 신규 결정 추가

**적용 위치**: `### D039: DataSynth v23 운영 기준본 변경` 다음 (또는 마지막 D 항목 다음)

```diff
@@ docs/DECISION.md (마지막 D 항목 다음) @@

+### D040: Phase 2 ML 평가 강제 protocol (Stage 10 Audit 통합)
+- **결정**: PHASE2 ML 평가 보고서는 5 protocol 항목과 S9 6개 부가가치 게이트를 모두 만족 시에만 머지 가능
+  (1) bootstrap 95% CI 동봉, CI > 0.15 시 [insignificant] 마커
+  (2) 시나리오별 fold × scenario truth count matrix 첨부
+  (3) 10 trivial binary feature 합산 baseline 동시 보고, Δrecall < 0.05 시 fitting 의심 마킹
+  (4) Phase 2 ML 부가가치 6 게이트 (S9 정의) 통과: 기존 5개 + `ensemble macro AUPRC / trivial_10feature macro AUPRC ≤ 4.0`
+  (5) macro-F2 unweighted + prevalence-weighted 두 값 동시 보고
+  anti-shortcut cap 과 S4 P4 Δrecall 은 OR 가 아닌 AND 조건이며, cap 초과 시 DataSynth v4 빌드 전까지 BLOCK.
+- **사유**: v3 dataset 의 합성 shortcut 위험 (S4 RED L-08~L-10) 으로 ML 향상 폭이
+  fitting 결과인지 실 판별인지 분리 필요. CONSTRAINTS.md §ML 학습 전략 의
+  사전 조건과 함께 BLOCK 게이트 형성.
+- **영향 범위**: `phase2_training_service`, PHASE2 평가 entry, CI workflow,
+  `tests/datasynth_quality_gate/results/phase2_fitting_audit/`
+- **관련 audit**: `docs/PHASE2_FITTING_AUDIT.md`,
+  `artifacts/S4_evaluation_protocol.md`, `docs/completed/S9_phase2_value_baseline.md`
+- **관련 결정**: D027 (Hold-out Fraud Type), D029 (데이터 분할 전략),
+  D034 (Stacking Meta-Learner), D037 (모델 드리프트 재학습)
+
+### D041: BiLSTM 트랙 PHASE2 본 평가 보류 조건 (Stage 7+10 Audit)
+- **결정**: BiLSTM (ML_SEQUENCE) 트랙은 다음 3 조건 모두 통과 시에만
+  PHASE2 본 평가에 포함한다. 미통과 시 본 평가 제외, FT-Transformer +
+  VAE + Supervised 7 트랙 ensemble 만 유지.
+  (1) `split_user_year_holdout` 적용 후 정확 날짜 매칭 overlap < 5%
+  (2) ±7일 인접 매칭 overlap < 20%
+  (3) val F1 (시퀀스 단위) 와 doc-level recall 의 격차 < 15pp
+- **사유**: S7 측정 결과 현 split 정책에서 cross-user temporal context
+  leakage 가 75% 에 달함 (val truth 의 75% 가 train 의 ±7일 인접 시점에서
+  학습된다). stride=1 만 수정해도 단일 fold 내 16x context 중복 효율
+  손실은 해소되나 cross-user 시점 leakage 는 해소 불가.
+- **영향 범위**: `src/preprocessing/split_strategy.py`, `config/settings.py`,
+  `src/detection/sequence_detector.py`, `src/services/phase2_training_service.py`
+- **관련 audit**: `artifacts/S7_sequence_split_redesign.md`,
+  `docs/PHASE2_FITTING_AUDIT.md`
+- **관련 결정**: D032 (BiLSTM + Attention 시퀀스 탐지 추가)
+
+### D042: DataSynth manipulation v4 spec 우선순위 (Stage 10 Audit, 장기)
+- **결정**: PHASE2 ML 정식 평가 직전에 DataSynth manipulation v4 profile
+  신규 빌드. v3 의 6 시나리오 + 2 hold-out 시나리오
+  (`suspense_account_abuse`, `expense_capitalization`, raw-plan D027 의도)
+  추가. 합성 shortcut 분포 노이즈화 (`f_manual` 0.41 ↔ 0.6-0.9 등).
+- **사유**: Stage 10 audit RED 4건 중 3건 (L-08 f_manual, L-09 trivial
+  shortcut, L-10 unusual_timing degenerate) 이 모두 v3 dataset 의 합성
+  설계 결함에서 비롯된다. 단기 mitigation 으로는 fitting 위험 자체를
+  제거할 수 없고 평가 protocol 으로만 우회한다. v4 빌드는 RED→GREEN 전환
+  의 유일한 근본 해법.
+- **영향 범위**: `tools/datasynth/crates/datasynth-cli/src/manipulation_v4.rs`
+  (신규), Phase1 회귀 검증 (S5 reproducer 와 동일 protocol),
+  `data/journal/primary/datasynth_manipulation_v3` 의 active lock 변경
+- **비용**: Rust profile 설계 + 빌드 + 검증 2-3 일
+- **관련 audit**: `docs/PHASE2_FITTING_AUDIT.md`,
+  `docs/completed/S9_zero_day_protocol_alternatives.md` §3.3
+- **관련 결정**: D027 (Hold-out Fraud Type), D028 (DataSynth 프로세스),
+  D036 (DataSynth v20.4), D039 (DataSynth v23)
```

---

## 7. 후속 액션

### 7.1 RED 판정이었다면 (현재 아님)

- PHASE2 ML 학습 sprint 진행 보류
- DataSynth manipulation v4 spec 수립 (D042 정의대로)
- v4 빌드 + Phase1 회귀 검증 통과 후 본 audit 재실행

### 7.2 YELLOW 판정 (현재) — 완화안 PR 목록

| PR | 위험 | 변경 |
|---|---|---|
| #1 | L-01~L-03 | `phase2_training_service` 13 deny 강제 + AUROC 회귀 가드 |
| #2 | L-04~L-06 | `cv_selector.py` 에 user feature 분기 + `split_user_year_holdout` 신설 |
| #3 | L-08 단기 | `phase2_plan` 에서 `f_manual` 단독 입력 금지 + 조합 피처 화이트리스트 |
| #4 | L-09 | PHASE2 평가 entry 에 trivial baseline 동시 보고 자동화 + anti-shortcut cap (`≤ 4.0`) BLOCK 게이트 |
| #5 | L-10 | macro 가중치 계산 시 `unusual_timing_manipulation` 0 또는 'low-N' 마커 |
| #6 | L-11 | bootstrap CI 1000 동봉 + CI 폭 > 0.15 자동 마킹 |
| #7 | L-14 | `config/settings.py::bilstm_stride` 기본값 16 |
| #8 | L-15 | `split_strategy.py::split_user_year_holdout` 신설 + BiLSTM 재측정 자동화 |
| #9 | L-17 | hold-out 후보 A protocol (unusual_timing + sod_bypass) PHASE2 entry 통합 — 구현됨 (`phase2_training_service`, `evaluation/phase2_report`) |
| #10 | docs | CONSTRAINTS.md / DECISION.md 패치 (§6) |
| #11 | L-09 (보강) | S5 Top-5 룰 LEAKAGE_DENY_RULES (`L3-02`, `L1-05`, `L1-09`, `L2-03`, `L2-02`) 적용 — `phase2_plan` 에서 5 룰을 Phase 2 ML 입력 행렬에서 제거하고 PHASE1 → PHASE3 narrator 입력으로만 노출. 근거: §3 (S5 §5, AUPRC 0.4398 → 0.0013) |
| #12 | L-09 (보강) | S9 6번째 게이트 anti-shortcut cap — Top-5 deny 후 재학습 ML 앙상블의 macro AUPRC 잔존율 ≥ 30% AND 절대값 ≥ 0.30 통과 강제 (위 §6 평가 protocol 6번 항목). 기존 PR#4 의 `≤ 4.0` 컬럼 기여도 cap 과 동시 적용 |
| #13 | L-13 (보강) | contamination ratio 게이지 (S6 §5.2) — `compute_class_imbalance` 에 contamination 게이지 등록 + 운영 GL contamination > 0.5% 시 alarm + `tests/modules/test_detection/` 회귀 가드 |
| #14 | L-08~L-10 (장기) | DataSynth manipulation v4 빌드 후 S8 ablation 재실행 트리거 — v4 active 승격 시 `tools/analysis/s8_stacking_oof_ablation.py` 자동 재실행 + macro AUPRC delta 비교 + Phase1 회귀 검증 통합 |
| #15 | L-12 (보강) | macro AUPRC floor 를 fold mean 95% CI 상한 + 0.05 로 변경 (= **0.482**, 현행 0.4898 보다 보수적) — S5 27룰 LR fold mean 0.4122 ± 0.0355 의 95% CI 상한 0.432 + 0.05 = 0.482 적용. 평가 protocol 의 macro AUPRC 하한을 본 값으로 갱신 |

위 15개 PR 모두 머지 + Phase 2 ML 학습 1회 실행 + 6 게이트 (S9, anti-shortcut cap 포함) + 5 protocol (S4) 통과 시 PHASE2 conditional GO 가 GO 로 승격.

> 2026-05-15 업데이트: PR #3 단기 완화안은 `src/preprocessing/phase2_plan.py`의
> `_SINGLE_USE_DENY`와 Phase 2 행렬 빌더 검증으로 적용됨. `f_manual` 단독 입력은
> `ValueError`로 차단하고, `f_manual_x_amount_high` 같은 조합 피처는 허용한다.

### 7.3 GREEN 판정이었다면

- `docs/completed/phase2_ml_feasibility.md` 말미에 다음 footnote 추가:

```markdown
> **Phase 2 Fitting Audit 통과 (Stage 0~10, 2026-05-15)**: 17 위험 항목 GREEN.
> 상세: `docs/PHASE2_FITTING_AUDIT.md` 및
> `tests/datasynth_quality_gate/results/phase2_fitting_audit/SUMMARY.md`.
```

현재 YELLOW 이므로 위 footnote 는 단기 mitigation PR 모두 머지 + 본 audit 재실행 통과 후 추가.

---

## 8. 본 audit 의 한계

- **데이터 편향**: 모든 진단이 v3 manipulation truth (420 docs, 6 시나리오) 위에서 측정됨. 실 운영 GL 또는 v4 신규 dataset 에서는 위험 지형이 다를 수 있음.
- **샘플 크기**: 시나리오별 최소 21 docs (`unusual_timing`) 로 fold-level 통계 신뢰성이 낮음. CI > 0.15 시나리오는 단일 점추정 금지 (S4 P1) 가 유일 mitigation.
- **모델 단순화**: S8 ablation 은 6 트랙 (heavy DL ml_transformer/ml_sequence 미포함) 으로 측정. 8 트랙 ensemble 의 누수 효과는 기존 6 트랙 정책 가정 하에서만 일반화.
- **Mitigation 미실증**: 본 audit 는 정책 권고이며 실 PR 머지 + 회귀 측정은 별도 sprint. 권고대로 적용 후 재측정 필수.

---

## 9. 변경 이력

| 일자 | 변경 |
|---|---|
| 2026-05-15 | Stage 0~10 audit 통합 entry-point 초판 (17 위험 카탈로그, YELLOW 판정, 10 PR 권고) |
