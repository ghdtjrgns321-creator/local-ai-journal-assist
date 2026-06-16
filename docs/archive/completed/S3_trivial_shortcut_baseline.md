# Stage 3 — Trivial Shortcut Baseline

- Generated: 2026-05-15 18:11:28
- Dataset: `C:\Users\ghdtj\workspace\portfolio\local-ai-assist\data\journal\primary\datasynth_manipulation_v3\journal_entries.csv`
- Total documents: 317,997
- Manipulated documents (positives): 420
- Prevalence: 0.1321%
- top-K = positives = 420 (matched to manipulated prevalence 0.13%)

## 룰 정의

- **R1** — local_amount > company p99.95(|amount|) × 1.5
- **R2** — approved_by NULL/blank OR sod_violation
- **R3** — is_suspense_account = true
- **R4** — posting_date dow ∈ {Sat,Sun}
- **R5** — posting_date hour ∉ [9,18]
- **R6** — tax_amount IS NULL AND tax_code IS NOT NULL
- **R7** — user_persona ∈ {adjustment, workflow_owner}

## 지표 (document_id 단위 집계)

- **flagged**: 룰이 fire 한 doc 수 (raw, threshold 없음)
- **R/P (raw)**: 룰 fire 한 doc 만으로 계산한 recall/precision
- **R/P (top-K)**: 점수 상위 K=420(=positives) 기준 recall/precision; 동률은 임의 순서
- **macro/micro AUPRC**: scenario 별 average_precision_score 의 macro 평균 / 전체 micro
- 시나리오 컬럼: top-K 기준 `recall/precision`

| 규칙 | flagged | R (raw) | P (raw) | R (top-K) | P (top-K) | macro AUPRC | micro AUPRC | approval R/P · circular R/P · embezzle R/P · fictitious R/P · period_end R/P · timing R/P |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| R1: local_amount > company p99.95(|amount|) × 1.5 | 217 | 0.400 | 0.774 | 0.400 | 0.400 | 0.129 | 0.310 | approval=0.000/0.000 · circular=0.000/0.000 · embezzle=0.000/0.000 · fictitious=1.000/0.400 · period_end=0.000/0.000 · timing=0.000/0.000 |
| R2: approved_by NULL/blank OR sod_violation | 1 | 0.000 | 0.000 | 0.002 | 0.002 | 0.000 | 0.001 | approval=0.000/0.000 · circular=0.000/0.000 · embezzle=0.000/0.000 · fictitious=0.006/0.002 · period_end=0.000/0.000 · timing=0.000/0.000 |
| R3: is_suspense_account = true | 12 | 0.000 | 0.000 | 0.002 | 0.002 | 0.000 | 0.001 | approval=0.000/0.000 · circular=0.000/0.000 · embezzle=0.000/0.000 · fictitious=0.006/0.002 · period_end=0.000/0.000 · timing=0.000/0.000 |
| R4: posting_date dow ∈ {Sat,Sun} | 8976 | 0.417 | 0.019 | 0.014 | 0.014 | 0.002 | 0.009 | approval=0.000/0.000 · circular=0.029/0.002 · embezzle=0.013/0.002 · fictitious=0.018/0.007 · period_end=0.011/0.002 · timing=0.000/0.000 |
| R5: posting_date hour ∉ [9,18] | 59185 | 0.374 | 0.003 | 0.007 | 0.007 | 0.000 | 0.002 | approval=0.000/0.000 · circular=0.029/0.002 · embezzle=0.000/0.000 · fictitious=0.012/0.005 · period_end=0.000/0.000 · timing=0.000/0.000 |
| R6: tax_amount IS NULL AND tax_code IS NOT NULL | 0 | 0.000 | — | 0.002 | 0.002 | 0.000 | 0.001 | approval=0.000/0.000 · circular=0.000/0.000 · embezzle=0.000/0.000 · fictitious=0.006/0.002 · period_end=0.000/0.000 · timing=0.000/0.000 |
| R7: user_persona ∈ {adjustment, workflow_owner} | 0 | 0.000 | — | 0.002 | 0.002 | 0.000 | 0.001 | approval=0.000/0.000 · circular=0.000/0.000 · embezzle=0.000/0.000 · fictitious=0.006/0.002 · period_end=0.000/0.000 · timing=0.000/0.000 |
| **Best single (R1)** | 217 | 0.400 | 0.774 | 0.400 | 0.400 | 0.129 | 0.310 | approval=0.000/0.000 · circular=0.000/0.000 · embezzle=0.000/0.000 · fictitious=1.000/0.400 · period_end=0.000/0.000 · timing=0.000/0.000 |
| **best_2_OR: R1 ∨ R2** | 218 | 0.400 | 0.771 | 0.400 | 0.400 | 0.129 | 0.309 | approval=0.000/0.000 · circular=0.000/0.000 · embezzle=0.000/0.000 · fictitious=1.000/0.400 · period_end=0.000/0.000 · timing=0.000/0.000 |
| **best_3_OR: R1 ∨ R2 ∨ R3** | 230 | 0.400 | 0.730 | 0.400 | 0.400 | 0.122 | 0.293 | approval=0.000/0.000 · circular=0.000/0.000 · embezzle=0.000/0.000 · fictitious=1.000/0.400 · period_end=0.000/0.000 · timing=0.000/0.000 |
| **Phase1 24-rule score_aggregator (ML stand-in)** | 230946 | 1.000 | 0.002 | 0.643 | 0.643 | 0.159 | 0.514 | approval=0.655/0.045 · circular=0.529/0.043 · embezzle=0.026/0.005 · fictitious=0.857/0.343 · period_end=0.728/0.160 · timing=0.952/0.048 |

### best_2_OR top 3 (macro AUPRC 내림차순)

| combo | macro AUPRC | micro AUPRC |
| --- | ---: | ---: |
| R1 ∨ R2 | 0.129 | 0.309 |
| R1 ∨ R3 | 0.122 | 0.294 |
| R1 ∨ R5 | 0.093 | 0.225 |

### best_3_OR top 3 (macro AUPRC 내림차순)

| combo | macro AUPRC | micro AUPRC |
| --- | ---: | ---: |
| R1 ∨ R2 ∨ R3 | 0.122 | 0.293 |
| R1 ∨ R2 ∨ R5 | 0.093 | 0.225 |
| R1 ∨ R3 ∨ R5 | 0.093 | 0.223 |

## Phase 2 ML 이 넘어야 하는 최소선

- **macro AUPRC ≥ 0.1292** (trivial baselines 중 최대)
- 도달 기준: Phase1 24룰 score_aggregator macro AUPRC = 0.1594
- Phase 2 ML 은 위 trivial baseline floor 와 Phase1 stand-in 모두를 의미 있게 초과해야 함.

- 활성 룰 풀(fire>0): R1, R2, R3, R4, R5
- 비활성 룰 (fire=0): R6, R7

## 시나리오별 positives

| scenario | positives |
| --- | ---: |
| approval_sod_bypass | 29 |
| circular_related_party_transaction | 34 |
| embezzlement_concealment | 76 |
| fictitious_entry | 168 |
| period_end_adjustment_manipulation | 92 |
| unusual_timing_manipulation | 21 |

## 해석 노트

- **R1 (amount p99.95 × 1.5)**: 단독 raw precision 0.774, recall 0.400. 거의 대부분의 hit 가 fictitious_entry (100% recall)에 집중 — 다른 시나리오 recall=0 이라 macro AUPRC 0.129 로 묶임.
- **R4 (주말)**: 8,976 doc fire, raw P=0.019 — 거의 모두 false positive. period_end·timing 시나리오에서만 매우 약한 신호.
- **R5 (비업무시간)**: 59,185 doc fire, raw P=0.003 — 정상 거래 다수 포함, 사실상 background traffic.
- **R2 / R3**: 각각 1, 12 doc 만 fire — DataSynth v3 가 sod_violation·suspense_account 를 manipulation 표면으로 노출하지 않도록 anti-fitting 처리됨 (라벨 누수 방지).
- **R6 / R7**: 0건 fire — tax_amount/tax_code 결측 매트릭스, 'adjustment'·'workflow_owner' persona 는 journal_entries.csv 에 존재하지 않음.
- **Phase1 24룰 score_aggregator**: macro AUPRC 0.159 (R1 대비 +23%), micro AUPRC 0.514 (R1 대비 +65%). timing recall 1.0, approval/period_end/circular recall 0.5+ — trivial 룰이 못 잡는 시나리오를 보강.
- **embezzlement 시나리오**: Phase1 recall 0.026 로 가장 약함 — Phase 2 ML 이 가장 큰 가치를 보탤 영역.

## 결론

- **Phase 2 ML floor (trivial only)**: macro AUPRC = **0.1292** (R1). 이 값 아래라면 trivial 한 amount cutoff 보다 못한 모델.
- **Phase 2 ML target (Phase1 포함)**: macro AUPRC = **0.1594**. Phase 1 24룰 score_aggregator 를 의미있게 (>5% relative) 초과해야 ML 의 부가가치가 정당화됨.