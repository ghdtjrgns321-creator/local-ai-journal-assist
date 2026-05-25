# PHASE1 priority_score Distribution Log

PHASE1 case priority_score 분포 튜닝의 Stage 별 측정 누적 로그. 매 Stage 진입/탈출 시
`scripts/audit_phase1_score_distribution.py` 로 동일 기준 측정 후 본 문서에 누적 기록한다.

## Policy

### 의미

`priority_score >= 0.90` 은 감사인이 즉시 검토해야 하는 우선순위. `>= 0.75` 는 검토대상. 그 외는 참고후보. 분포 자체는 데이터 특성의 결과이며 **건수는 관찰 지표**다.

### 0.90 critical 승격 원칙 5조 (2026-05-20 잠금)

priority_floors 의 0.90 entry 신설/유지 시 다음 5조를 모두 만족해야 한다.

1. **강한 seed 1개** — primary rule 의 raw_score 가 medium 이상 또는 명시적 escalated label
2. **금액성/중요성 1개** — L4-03 또는 materiality 임계 초과 또는 escalated_materiality 라벨
3. **독립 보강근거 1개** — timing/manual/SoD/duplicate 중 seed/금액성과 다른 축 1개
4. **단독 금지** — macro-only / manual-only / timing-only / approval-only / sensitive-only 단독으로는 0.90 진입 불가
5. **건수 목표로 조건 재조정 금지** — count 가 목표 범위 밖이어도 도메인적으로 타당하면 entry 유지. count 보고 조건을 조이거나 푸는 것은 fitting

### fraud scenario 표시명 격하 원칙 (2026-05-20)

내부 tag 는 fraud scenario 명칭 (예: `embezzlement_concealment`, `fictitious_entry`) 을 그대로 쓸 수 있으나, UI/export/LLM 노출은 **단정형 금지**. "검토 신호 / 결합 리스크" 형태로 격하한다.

- `횡령 은폐` (X) → `유출·중복 + 승인 통제 결합 검토` (O)
- `가공 거래` (X) → `매출 outlier + 수기 결합 검토` (O)
- `대형 자금 유용 사례` (X) → `대형 거래 + 통제 우회 검토` (O)

fraud scenario 명칭의 직접 노출은 자금성 계정 / vendor·employee / bank·payment 같은 직접 증거가 있을 때만 허용. 현재 priority_floors / combo 만으로는 그 직접성 부족.

### 진행 순서

Stage 0 (측정 인프라) → Stage 1 (priority_floors 생존 복구) → Stage 2-prep (원칙 잠금) → Stage 2-A (priority_floors 2종 신규 entry) → Stage 2-B (UI 표현 정책과 함께 2종 추가) → Stage 4 (UI/Export 라벨 정리)

### 기록 정책

- DataSynth truth recall/precision 은 **기록만**. 튜닝 기준으로 사용 금지 ([memory: feedback_phase1_truth_recall_guard.md](../../../.claude/projects/C--Users-ghdtj-workspace-portfolio-local-ai-assist/memory/feedback_phase1_truth_recall_guard.md)).
- baseline artifact 는 `artifacts/phase1_cases_baseline/stage_N_<dataset>.json` 에 보관 (gitignored, 로컬 전용).
- 매 Stage 1회 측정 (도메인 정합성 검증용). 결과 보고 조건 미세조정 금지.
- fy2022 로 entry 정의, fy2023 은 holdout (검증용, 조건 재조정 근거 아님).

### 측정 회귀 잠금

- **anti-disappear** (>= 0.90 유지): `multiple_core_required_fields_missing`, `sod_direct_critical`, `skipped_approval_critical`, `escalated_self_approval_material_or_sensitive`. Stage 2 이후 추가.
- **anti-noise** (< 0.90 유지): manual 단독, closing 단독, weekend/after-hours 단독, sensitive account 단독, macro-only, weak context 다수 조합. case 미생성 시 return 패턴 금지 — case 생성 강제 조합 사용.
- **유지**: review-only signal 이 confirmed violation 처럼 저장·표시되지 않음.

---

## Stage 0 — baseline (pre-bridge)

측정 일시: 2026-05-20
측정 스크립트: `scripts/audit_phase1_score_distribution.py`

### fy2022 (source: `artifacts/phase1_cases/test/phase1case_test_fy2022_05f9b3b1_20260520T003350Z.json`)

baseline 복사본: `artifacts/phase1_cases_baseline/stage_0_fy2022.json`

| Bin       | Count |
|-----------|-------|
| >=0.95    |     0 |
| >=0.90    |     0 |
| >=0.85    |     0 |
| >=0.80    |     0 |
| >=0.75    |  4009 |
| >=0.60    |  4486 |
| >=0.45    | 11698 |
| >=0.00    | 12698 |

| Rank          | priority_score |
|---------------|----------------|
| Top 50 cutoff |         0.7500 |
| Top 100       |         0.7500 |
| Top 200       |         0.7500 |
| Top 500       |         0.7500 |
| Top 1000      |         0.7500 |

priority_band (이전 yaml 0.75 high threshold 로 산정된 값, 새 0.90 기준 이미 적용 안 됨):

| Band   | Count |
|--------|-------|
| high   |  4010 |
| medium |  7688 |
| low    |  1000 |

0.75+ by primary_topic:

| Topic                | Count |
|----------------------|-------|
| closing_timing       |  2123 |
| approval_control     |  1782 |
| revenue_statistical  |    81 |
| account_logic        |    19 |
| duplicate_outflow    |     4 |

### fy2023 (source: `artifacts/phase1_cases/test/phase1case_test_fy2023_f1ca9982_20260520T005622Z.json`)

baseline 복사본: `artifacts/phase1_cases_baseline/stage_0_fy2023.json`

| Bin       | Count |
|-----------|-------|
| >=0.95    |     0 |
| >=0.90    |     0 |
| >=0.85    |     0 |
| >=0.80    |     0 |
| >=0.75    |  4532 |
| >=0.60    |  4801 |
| >=0.45    | 13124 |
| >=0.00    | 14926 |

| Rank          | priority_score |
|---------------|----------------|
| Top 50 cutoff |         0.7500 |
| Top 100       |         0.7500 |
| Top 200       |         0.7500 |
| Top 500       |         0.7500 |
| Top 1000      |         0.7500 |

priority_band (이전 yaml 0.75 high threshold 로 산정된 값):

| Band   | Count |
|--------|-------|
| high   |  4534 |
| medium |  8590 |
| low    |  1802 |

0.75+ by primary_topic:

| Topic                | Count |
|----------------------|-------|
| closing_timing       |  2149 |
| approval_control     |  1962 |
| duplicate_outflow    |   294 |
| revenue_statistical  |    79 |
| account_logic        |    46 |
| ledger_integrity     |     2 |

### Diagnosis

`src/detection/phase1_case_builder.py:1602-1604` 에서 topic_scoring 이 활성화된 경로는
priority_floors 가 적용된 `priority_score` 를 `max(topic_scores.values(), default=0.0)` 로 덮어쓴다.
그 결과:

- `priority_floors` 의 `min_priority_score: 0.90` 엔트리 (`multiple_core_required_fields_missing`, `sod_direct_critical`, `skipped_approval_critical`, `escalated_self_approval_material_or_sensitive`) 가 최종 점수에 반영되지 않는다 (dead code).
- `topic_scoring` 의 weighted base_score 는 `max_primary_rule_score: 0.62` 가중치로 ~0.62 부근에서 형성되고, `topic_floor_policies` 와 `combo_floor_policies` 의 `*_high` 가 모두 0.75 로 끌어올려 0.75 클러스터를 만든다.

DataSynth truth recall/precision (기록만, 튜닝 기준 아님):

- 본 Stage 측정 시점에 별도 truth 평가 미수행. 후속 Stage 에서 측정 시 본 섹션 갱신.

---

## Stage 1 — priority_floors 생존 복구 (코드 변경 완료, 분포 재측정 대기)

### 코드 변경

`src/detection/phase1_case_builder.py:1558-1620` 의 priority_score 머지 로직 수정.

```python
priority_score_pre_macro = priority_score  # floor 적용 + macro 미적용
priority_score, macro_reasons = _apply_macro_context_priority(priority_score, macro_contexts)
# macro_reasons append 는 use_topic_scoring 분기 후로 이연한다 — line 1614-1617 참조.

# ... topic_scoring (compute_topic_scores, primary_topic 결정 등) ...

legacy_priority_score = priority_score  # macro 가산본
if use_topic_scoring:
    topic_priority_score = max(topic_scores.values(), default=0.0)
    priority_score = max(topic_priority_score, priority_score_pre_macro)
    # macro_reasons 는 audit 사유로 추가하지 않음 (점수에 미반영되므로).
else:
    adjustment_reasons.extend(macro_reasons)  # 점수에 반영되는 경로에서만 audit 사유 보존.
```

핵심 변경 2가지:

1. use_topic_scoring=True 경로의 머지 후보를 `priority_score_pre_macro` (floor 적용 + macro 미적용) 로 사용 → priority_floors 의 0.90 floor 가 topic_scoring 에 덮이지 않음.
2. `macro_reasons` 의 `priority_adjustment_reasons` append 를 분기 후로 이연 → macro 보너스가 점수에 미반영되는 경로 (use_topic_scoring=True) 에서 audit 사유로 표시되지 않음.

### 결정 — legacy macro 보너스 처리 (2026-05-20)

`_apply_macro_context_priority` 의 legacy 보너스 (+0.04~+0.10) 는 use_topic_scoring=True 경로에서 priority_score 에 반영되지 않는다. 의도된 동작.

근거:
- legacy `_apply_macro_context_priority` 는 case 가 모집단 macro findings (L4-02 Benford, D01 account variance, D02 monthly shift, GR graph) 와 연결된 정도를 보너스로 가산.
- topic_scoring 의 `macro_context_score: 0.03` 가중치는 case_hits 중 `scoring_role="macro_only"` evidence 의 normalized_score 를 가산.
- 두 source 는 다르지만 (case-level macro context vs transaction-attached macro role), 약한 macro context 가 0.85+ 로 과승격되지 않도록 use_topic_scoring 경로에서는 legacy 보너스를 미반영한다 (사용자 plan 정합, 2026-05-20 결정).
- use_topic_scoring=False 경로 (`src/detection/phase1_case_builder.py:1652`) 는 `priority_score = legacy_priority_score` 로 macro 가산본 유지 — 호환성 보존.
- macro_reasons 의 audit 설명 (`priority_adjustment_reasons`) 도 같은 분기에 따라 처리한다: use_topic_scoring=True 에서는 macro 보너스가 최종 priority_score 에 반영되지 않으므로 사유도 append 하지 않고, use_topic_scoring=False 에서만 append 한다 (`src/detection/phase1_case_builder.py:1612-1616`).

### 테스트

`tests/modules/test_detection/test_phase1_case_builder_stage1.py` 신규 — 10개 잠금 테스트.

- anti-disappear (4): `multiple_core_required_fields_missing`, `sod_direct_critical`, `skipped_approval_critical`, `escalated_self_approval_material_or_sensitive` 각각 priority_score >= 0.90 유지.
- anti-noise (4): L3-02 / L3-04 / L3-10 / L3-05 단독 신호 priority_score < 0.90 유지.
- composite_sort: legacy floor 머지가 정렬에서 demote 되지 않음.
- macro double-count: 약한 단독 신호가 0.90 미만 유지.

`tests/modules/test_detection/test_phase1_case_builder.py` 의 기존 68개 회귀 테스트 통과 확인 (2026-05-20).

### 측정 결과 (2026-05-20, 시뮬레이션)

전체 파이프라인 재실행 부담을 피하기 위해 `scripts/simulate_stage1_priority_score.py` 로 stage_0 artifact 에 Stage 1 머지 로직 (max(topic, legacy_floor)) + macro_reasons 분기 처리만 적용했다. priority_adjustment_reasons 에 priority_floors 가 평가한 reason 이 이미 보존되어 있어 정확도가 매우 높다.

시뮬레이션 한계: stage_0 artifact 에 누락된 정보 (예: raw_rule_hits.annotation 의 missing_fields) 가 stage_0 시점에서 floor 평가에 사용되었다면 그 결과는 priority_adjustment_reasons 에 reason 텍스트로 보존되어 있으므로 시뮬레이션이 그대로 복원한다. 실제 파이프라인 재실행 결과와 거의 동일할 것으로 추정.

#### fy2022 (12,698 cases)

| Bin       | Stage 0 | Stage 1 |
|-----------|---------|---------|
| >=0.95    |       0 |       0 |
| >=0.90    |       0 |   **21** |
| >=0.85    |       0 |      21 |
| >=0.80    |       0 |     548 |
| >=0.75    |    4009 |    4316 |
| >=0.60    |    4486 |    4487 |

Top N cutoffs: Top 50 ~ Top 500 모두 0.8000, Top 1000 = 0.7500 (Stage 0 은 모두 0.7500).

Movement vs stage_0:
- promoted_to_critical (0.75 → 0.90+): **21**
- raised_within_review (0.75 ~ 0.89 사이 상승): 492
- unchanged: 3,496
- dropped_below_threshold (0.75 미만 낙오): **0**

0.90+ by priority_adjustment_reasons:
- escalated_self_approval_material_or_sensitive: 21 (모든 0.90+ 케이스)
- 보강 사유: topside_score / weak_evidence / batch_combo_groups / escalated_self_approval_abnormal_time / sensitive_account_priority_context

0.90+ by primary_topic: approval_control 9, revenue_statistical 8, closing_timing 3, account_logic 1.

#### fy2023 (14,926 cases)

| Bin       | Stage 0 | Stage 1 |
|-----------|---------|---------|
| >=0.95    |       0 |       0 |
| >=0.90    |       0 |   **23** |
| >=0.85    |       0 |      23 |
| >=0.80    |       0 |     705 |
| >=0.75    |    4532 |    4706 |
| >=0.60    |    4801 |    4801 |

Movement vs stage_0:
- promoted_to_critical: **23**
- raised_within_review: 659
- unchanged: 3,850
- dropped_below_threshold: **0**

0.90+ by priority_adjustment_reasons:
- escalated_self_approval_material_or_sensitive: 23 (모든 0.90+ 케이스)
- approval_limit_exceeded: 15, missing_approval_date_*: 12, escalated_self_approval_abnormal_time: 3 (보강)

0.90+ by primary_topic: approval_control 9, revenue_statistical 8, closing_timing 6.

### 관찰 (2026-05-20)

| 항목 | fy2022 | fy2023 | 비고 |
|------|--------|--------|------|
| 0.90+ 카운트 | 21 | 23 | 모두 `escalated_self_approval_material_or_sensitive` (L1-05 escalated label) 단독 floor 로 진입 |
| 0.75+ 카운트 | 4,316 (+307) | 4,706 (+174) | 0.75 미만 낙오 0건 |
| dropped_below_threshold | 0 | 0 | 의도치 않은 하향 회귀 없음 |
| Top 50/200 cutoff | 0.80 | 0.80 | 0.80~0.89 band 가 단일 floor (`escalated_self_approval_abnormal_time`) 의 인공물 — band 형성 자체는 yaml priority_floors 의 기존 정책 발현 |

Stage 1 자체는 코드 구조 결함 (priority_floors 가 topic_scoring 에 덮이는 dead code) 수정이 동기. 결과 분포는 yaml 의 사전 도메인 잠금 정책의 자연 발현. **건수는 관찰값**.

### Stage 2 진입 판단 (2026-05-20)

Stage 2 는 위 5조 원칙에 부합하는 priority_floors 신규 entry 가 도메인적으로 타당할 때만 진입. 건수 기준 진입/보류 판단은 사용하지 않는다 (fitting 회피).

Stage 2 진행 결정:
- **Stage 2-A**: `approval_bypass_critical` + `period_end_adjustment_critical` 2종 priority_floors 신규 entry. PHASE1 감사 우선순위로 설명 가능한 가장 명확한 결합.
- **Stage 2-B**: outflow/duplicate critical + revenue/manual critical — fraud scenario 표시명 정책 (UI/export/LLM 격하) 과 함께 별도 처리. Stage 2-A 완료 후 진입 여부 재평가.

---

## Stage 2-prep — 원칙 잠금 (2026-05-20)

Stage 2 진입 전 fitting 위험 회피를 위해 원칙·표현 정리. 본 문서 상단 Policy 섹션에 5조 원칙 + fraud scenario 표시명 격하 원칙 명시. count 보고 조건 재조정 금지 잠금.

### Stage 2 fitting 위험 진단 결과 (2026-05-20)

`scripts/fitting_audit.py` 측정 결과:

- stage_0 / stage_1 의 4종 critical 매칭 case 카운트 동일 (e.g., approval_bypass_critical refined: 514/514, embezzlement: 18/18) — 머지가 새 매칭을 만들지 않음. 분포 이동만.
- 그러나 stage_1 의 0.80~0.89 band 가 단일 floor (`escalated_self_approval_abnormal_time`, 0.80) 의 인공물 (fy2022 527/527 = 100%, fy2023 682/682 = 100%).
- 사용자 plan 의 4종 critical 의 union 중 94~100% 가 `approval_bypass_critical` 에 overlap. 사실상 한 엔진.
- "100~200 목표 → 0.80~0.89 분석 → 조건 재설계" 흐름 자체가 count-fitting 패턴.

위 분석을 근거로 본 문서의 100~200 판단 표를 제거하고 5조 원칙으로 교체. Stage 2 는 priority_floors 의 신규 entry 추가 방식으로 진행 (combo_floors `*_critical` 신설은 보류 — 한 엔진이 여러 fraud scenario 명을 갖는 구조 회피).

---

## Stage 2-A — 보류 (2026-05-21)

### 시도

`config/phase1_case.yaml` 의 `priority_floors` 에 0.90 entry 2 reason × 7 sub-entry 신설 시도 + `_priority_floor_corroboration_match` 에 `required_rules_any` 필드 지원 추가. D060 5조 원칙 모두 정합:

1. `approval_bypass_critical` — L1-04/L1-05/L1-06/L1-07 raw>=0.80 + L4-03 required + (L3-04/L3-05/L3-06/L3-11/L1-08) supporting 1개
2. `period_end_adjustment_critical` — L3-04/L3-11/L1-08 raw>=0.60 + L4-03 + (L3-02 또는 approval_bypass rule) extra

### 시뮬레이션 결과

`scripts/simulate_stage2_critical.py` 로 stage_1 artifact 에 신규 entry 효과 1회 측정.

```
Stage 2-A simulation showed that domain-valid critical candidates are too common
in the current population:
- period_end_adjustment_critical: 950 ~ 1,022 promoted
- approval_bypass_critical: 335 ~ 414 promoted
- total 0.90+: 1,043 ~ 1,130

Because narrowing the conditions after seeing these counts would be count-fitting,
Stage 2-A is deferred. These signals remain review-target ranking/filter axes
rather than immediate-review floors.
```

| | fy2022 | fy2023 |
|---|--------|--------|
| Stage 1 기존 0.90+ | 21 | 23 |
| approval_bypass_critical 신규 promote | 335 | 414 |
| period_end_adjustment_critical 신규 promote | 950 | 1,022 |
| **Total 0.90+ (시뮬레이션)** | **1,043** | **1,130** |

### 결정 (2026-05-21)

D060 5조 5번 ("건수 목표로 조건 재조정 금지") 정신상 조건을 조여서 count 를 100~200 으로 맞추는 것은 fitting. 정합한 조건이 즉시검토로 1,000건 이상 만든다면 그건 **즉시검토의 의미와 조건 강도가 충돌**하는 상황이다. 조건을 잘못 만든 게 아니라 priority_score 계층 자체가 0.75/0.90 2단계만 있어서 중간 강도 결합을 표현할 자리가 없다.

따라서:

- **Stage 2-A 보류**. yaml 신규 7 entry roll back. `_priority_floor_corroboration_match` 의 `required_rules_any` 지원도 roll back (dormant code 회피).
- **Stage 1 종료 상태로 복귀**. 0.90+ = fy2022 21건 / fy2023 23건 유지.
- `approval_bypass_critical` / `period_end_adjustment_critical` 결합 신호는 즉시검토 floor 가 아니라 **검토대상 상단의 정렬/필터 축**으로 이관. UI 작업에서 이 결합 신호를 가진 case 를 상위로 정렬하거나 필터링하는 axis 로 활용.

### 다음 작업 — priority_score 계층 재설계 (Stage 2 대체)

본질 문제: 현재 priority_score 계층이 0.75/0.90 2단계만 도메인 의미를 가지며, 0.80/0.85 는 단일 floor 의 인공물. 4,000건 검토대상을 의미있게 세분화하려면 계층 재설계.

목표 계층:

| 점수 | 의미 | 목표 수량 (관찰) |
|------|------|------------------|
| 0.90+ | 즉시검토 — 강한 단일 결함 또는 명시적 critical | 20~50건 (도메인 정합) |
| 0.85+ | 상위 검토대상 / supervisor review — 강한 결합 | 100~300건 |
| 0.80+ | 검토대상 상단 — 중간 결합 | 500~1,000건 |
| 0.75+ | 일반 검토대상 | 수천 건 |

이 계층은 priority_floors 의 다단계 entry 신설로 구현. 단 같은 fitting 함정 회피 — 조건을 도메인 원칙으로 정의 후 결과 측정만 (count 보고 재조정 금지).

본 작업은 별도 Stage (예: Stage 5) 로 분리. Stage 2-B 는 동일하게 보류.

---

## Stage 2-B — 동일하게 보류 (2026-05-21)

Stage 2-A 보류와 같은 이유. `outflow/duplicate critical` + `revenue/manual critical` 도 도메인 정합 조건을 만들면 동일하게 count 폭증 위험. 별도 진입 없이 priority_score 계층 재설계 (다음 단계) 안에서 통합 처리.

`embezzlement_concealment` / `fictitious_entry` 같은 fraud scenario 단정형 명칭의 UI/export/LLM 격하 정책은 priority_score 계층 재설계와 별개로 Stage 4 UI 작업에서 처리한다.

---

## Stage 4 — UI/Export 라벨 정리 (예정)

내부 키 `high/medium/low` 유지, 표시 라벨 `즉시검토/검토대상/참고후보` 로 통일.
ripple search 대상: `dashboard/*`, `dashboard/components/*`, `src/export/*`, `src/llm/*`, `docs/*`.

(작업 결과는 Stage 4 완료 후 본 섹션에 기록)
