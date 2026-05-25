# Detection Parameters

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.


> **포트폴리오 주장 범위 (2026-05-19)**: 이 프로젝트는 `fraud`를 판정하거나 실제 운영 부정 탐지 성능을 보장하는 모델이 아니다. 전수 모집단에서 감사인이 먼저 볼 review queue를 만들고, 무작위 검토 대비 상위 구간에 review-worthy synthetic anomaly를 강하게 농축하는 로컬 감사 분석 보조 도구다. DataSynth 기반 precision/recall은 개발 검증 보조 지표이며, 실데이터 운영 성능으로 주장하지 않는다.
> **금지 표현**: "부정을 정확히 탐지", "실무 운영 성능 검증 완료", "TOP100 precision 충분", "fraud 확정/자동 적발"처럼 확정적이거나 운영 성능을 보장하는 표현은 사용하지 않는다.

이 문서는 `DETECTION_RULES.md`의 룰 정의가 실제 설정·코드·UX 조정면과 어떻게 연결되는지 정리한다.

현재 기준:

- Phase 1 기본 실행 범위는 `L1~L4 + L3-11 + Benford(L4-02) + D01/D02`다.
- `L3-11`은 Phase 1 기본 룰이지만 구현 위치는 `EvidenceDetector`다. 기본 실행에서는 `EvidenceDetector(rule_ids=("L3-11",))`로 cutoff 룰만 실행한다.
- `EV01`, `EV03` 같은 증빙 확장 룰은 별도 evidence 옵션이다.
- Row-level `anomaly_score` 기본 가중치는 `src/detection/constants.py::RULE_LEVEL_WEIGHTS`다: `L1=0.40`, `L2=0.25`, `L3=0.20`, `L4=0.15`.
- `D01`, `D02`, `L4-02`는 계정·모집단 단위 분석 신호다. 전표 row score를 직접 만들지 않고 Account / Process Queue와 drill-down context로 사용한다.
- Case grouping, priority weight, priority band, repeat scaling, priority floor는 `config/phase1_case.yaml`이 기준이다.

## 1. 문서와 코드 기준

| 영역 | 기준 파일 |
|---|---|
| 룰 의미와 감사 해석 | `docs/DETECTION_RULES.md` |
| 설정 기본값 | `config/settings.py` |
| 회사/engagement별 룰 정책 | `config/audit_rules.yaml`, `config/risk_keywords.yaml`, 회사별 override |
| Phase 1 case priority | `config/phase1_case.yaml` |
| row-level rule normalization | `src/detection/rule_scoring.py`, `src/detection/score_aggregator.py` |
| L1 일부와 L3-01 | `src/detection/integrity_layer.py` |
| L1/L2/L3/L4 통제·부정 룰 | `src/detection/fraud_layer.py` |
| L3/L4 이상징후 룰 | `src/detection/anomaly_layer.py` |
| L3-11 cutoff 룰 | `src/detection/evidence_detector.py`, `src/detection/evidence_rules.py` |
| L4-02 Benford | `src/detection/benford_detector.py` |
| D01/D02 | `src/detection/variance_layer.py`, `src/detection/variance_rules.py` |

## 2. UX 단계별 하이퍼파라미터 구분

하이퍼파라미터는 사용자에게 한 화면에 모두 노출하지 않는다. 조정 책임과 오탐 위험에 따라 네 단계로 나눈다.

### Level 1: Engagement 필수 체크리스트

감사 시작 시 사용자가 확인해야 하는 값이다. 회사 정책·회계기간·승인 체계와 직접 연결되므로 기본값만 믿으면 안 된다.

| UX 그룹 | 주요 파라미터 | 영향 룰 |
|---|---|---|
| 중요성 | `engagement.materiality_amount` | TB 대사 허용, L1-05, L2-03, Phase 1 case priority |
| 회계기간/결산일 | `fiscal_year_start`, `period_end_margin_days`, `phase1_case.period_end_window_days` | L1-08, L3-04, L3-11, D02 |
| 승인 권한 | `approval_thresholds`, 직원 `approval_limit`, `can_approve_je` | L1-04, L1-05, L1-07, L2-01 |
| 수기/자동 source | `patterns.manual_source_codes`, `auto_entry_sources`, `batch_source_values` | L3-02, L3-06, L4-05, L4-06 |
| 계정 체계 | `revenue_account_prefixes`, `expense_account_prefixes`, `intercompany_identifiers`, `suspense_account_codes`, `patterns.suspense_keywords`, `high_risk_account_use.*` | L1-03, L3-03, L3-09, L3-10, L3-11, L4-01 |
| 공휴일/심야 기준 | `custom_holidays`, `midnight_start`, `midnight_end`, `normal_hours_start`, `normal_hours_end` | L3-05, L3-06, L4-05 |

UX 처리:

- “필수 확인” 또는 “감사 착수 설정”으로 노출한다.
- 값이 없으면 기본값으로 실행하되, 리포트에 coverage/assumption을 남긴다.
- 회사별 override 저장 대상이다.

### Level 2: 방법론 튜닝

룰의 오탐·미탐 균형을 바꾸는 값이다. 일반 감사인이 회사 설정 화면에서 직접 조정하는 값이 아니라,
리드/방법론 담당자가 데이터 검증과 영향 분석 후 별도 관리 화면 또는 설정 파일에서 다룬다.

| UX 그룹 | 주요 파라미터 | 영향 룰 |
|---|---|---|
| 중복/분할/시차 | `duplicate_payment_window_days`, `duplicate_time_window_days`, `duplicate_split_window_days`, `duplicate_amount_tolerance`, `duplicate_fuzzy_threshold` | L2-02, L2-03 |
| 승인한도 직하 | `near_threshold_ratio` | L2-01 |
| 비용 자산화 | `expense_capitalization_min_amount`, `expense_capitalization_amount_tolerance`, `expense_capitalization_review_threshold`, `expense_capitalization_immediate_threshold` | L2-04 |
| 역분개 | `reversal_match_window_days`, `reversal_rolling_window_days`, `reversal_zero_threshold`, `reversal_score_threshold`, `patterns.reversal_keywords` | L2-05 |
| 결산/고액 후보 | `period_end_amount_quantile`, `c01_min_group_size`, `period_end_sensitive_bonus`, `l403_min_amount_quantile`, `zscore_threshold` | L3-04, L4-03 |
| 가계정/민감 계정 | `suspense_aging_days`, `suspense_min_open_amount`, `patterns.suspense_keywords`, `patterns.high_risk_account_use.*` | L3-09, L3-10 |
| 컷오프 | `ev_revenue_cutoff_days`, `ev_expense_cutoff_days`, `ev_cutoff_period_end_weight`, `ev_cutoff_max_day_diff`, `ev_cutoff_use_business_days` | L3-11 |
| Benford | `benford_mad_threshold`, `benford_min_sample` | L4-02 |
| 배치/비정상 시간 | `abnormal_sigma_threshold`, `min_abnormal_ratio`, `min_user_entries`, `min_midnight_entries`, `min_high_context_midnight_entries`, `rapid_approval_minutes`, `batch_period_end_ratio`, `batch_simultaneous_threshold`, `batch_amount_zscore` | L4-05, L4-06 |
| D01/D02 | `variance_threshold`, `monthly_pattern_threshold`, `min_monthly_data_months`, `d02_min_account_docs`, `d02_min_annual_amount`, `d02_min_top_month_delta`, `d02_group_keys` | D01, D02 |

UX 처리:

- 기본 회사 설정 화면에서는 숨긴다.
- 별도 관리자/방법론 튜닝 화면을 만들 때만 노출한다.
- 변경 시 해당 룰과 예상 영향(후보 증가/감소), 재현성 영향을 표시한다.
- engagement override 저장 대상이지만 변경 이력을 남긴다.

### Level 3: Case Priority / 표시 정책

룰 hit 자체를 바꾸지 않고 큐 정렬, case 묶음, 표시 개수를 바꾸는 값이다. 감사인이 “무엇을 먼저 볼지”를 조정한다.

| UX 그룹 | 주요 파라미터 | 영향 |
|---|---|---|
| priority 가중치 | `phase1_case.priority_weights.*` | `control_score`, `amount_score`, `duplicate_or_outflow_score`, `logic_score`, `timing_score`, `behavior_score` |
| priority band | `phase1_case.priority_band.high`, `phase1_case.priority_band.medium` | High/Medium/Low case 구분 |
| priority floor | `phase1_case.priority_floors` | L1-05, L1-06, L1-07, L1-09, L3-10, L3-11 등 최소 우선순위 |
| case key | `phase1_case.account_family_strategy`, `counterparty_columns`, `intercompany_pair_columns`, `load_batch_columns`, `near_period_days`, `period_end_window_days` | case grouping |
| 반복/중복 보정 | `phase1_case.rule_repeat_scale`, `repeat_score_promote`, `repeat_months_tiebreak`, `evidence_type_cap` | 같은 룰 반복과 evidence type cap |
| 노출 개수 | `phase1_case.top_n_cases`, `phase1_case.top_n_per_theme`, `secondary_tag_min_score` | UI 표시량 |

UX 처리:

- “큐 정렬/표시 정책”으로 노출한다.
- 룰 탐지 결과를 바꾸지 않는다는 설명을 붙인다.
- audit trail에 변경 이력을 남긴다.

### Level 4: System / Advanced

일반 사용자가 직접 바꾸면 해석이 흔들릴 수 있는 값이다. 기본은 숨기고 관리자·개발자 모드에서만 다룬다.

| UX 그룹 | 주요 파라미터 | 이유 |
|---|---|---|
| 성능/병렬화 | `detection_parallel_workers`, `duplicate_max_group_size`, graph max edge/component 계열 | 런타임과 메모리에 직접 영향 |
| ML/Phase 2 | `enable_ml_detection`, `shap_threshold`, `vae_*`, `if_*`, `bilstm_*`, `stacking_*` | Phase 1 룰 해석과 분리 필요 |
| 확장 탐지기 | `enable_relational_detection`, `enable_graph_detection`, `enable_nlp_detection`, `enable_access_audit_detection`, `enable_trendbreak_detection`, `enable_timeseries_detection` | 기본 Phase 1 범위 밖 |
| 통계/검정 내부값 | `trendbreak_*`, `burst_*`, `frequency_*`, `ic_*`, `graph_*`, `nlp_*` | 별도 데이터 전제와 검증 필요 |
| 파이프라인 품질 | ingestion fuzzy threshold, casting null threshold, imputation heuristic 계열 | 탐지 이전 데이터 품질 단계 |

UX 처리:

- 기본 화면에서는 숨긴다.
- 바꿀 경우 “분석 재현성에 영향” 경고와 변경 이력을 남긴다.

## 3. 룰별 핵심 파라미터

### L1

| 룰 | 핵심 파라미터/설정 | 코드 |
|---|---|---|
| L1-01 | `balance_tolerance` | `IntegrityDetector._a01_unbalanced_entry()` |
| L1-02 | `config/schema.yaml required: true` | `IntegrityDetector._a02_missing_required()` |
| L1-03 | CoA, `chart_of_accounts_path` | `IntegrityDetector._a03_invalid_account()` |
| L1-04 | `approval_thresholds`, `approved_by`, 직원 `approval_limit` | `b03_exceeds_threshold()` |
| L1-05 | `patterns.self_approval_allow.*`, `patterns.self_approval_immediate_override.*` | `b06_self_approval()` |
| L1-06 | `patterns.l1_06_sod_scoring.*`, `patterns.sod_*` | `b07_segregation_of_duties()` |
| L1-07 | `patterns.skipped_approval_immediate.*`, `approval_level`, `exceeds_threshold` | `b09_skipped_approval()` |
| L1-08 | `fiscal_year_start`, `patterns.fiscal_period_mismatch_policy` | `c05_fiscal_period_mismatch()` |
| L1-09 | `patterns.missing_approval_date_immediate.*` | `b12_missing_approval_date()` |

### L2

| 룰 | 핵심 파라미터/설정 | 코드 |
|---|---|---|
| L2-01 | `near_threshold_ratio` | `b02_near_threshold()` |
| L2-02 | `duplicate_payment_window_days` | `b04_duplicate_payment()` |
| L2-03 | `duplicate_amount_tolerance`, `duplicate_fuzzy_threshold`, `duplicate_time_window_days`, `duplicate_split_window_days`, `duplicate_max_group_size` | `b05_duplicate_entry()` |
| L2-04 | `expense_capitalization_*`, `patterns.expense_capitalization.*` | `b11_expense_capitalization()` |
| L2-05 | `reversal_*`, `patterns.reversal_keywords`, `patterns.reversal_exclude_accounts` | `c11_reversal_entry()` |

### L3

| 룰 | 핵심 파라미터/설정 | 코드 |
|---|---|---|
| L3-01 | `patterns.l3_01_misclassified_account.*` | `IntegrityDetector._l301_misclassified_account()` |
| L3-02 | `patterns.manual_source_codes` | `b08_manual_override()` |
| L3-03 | `patterns.intercompany_identifiers` | `b10_intercompany_review_signal()` |
| L3-04 | `period_end_margin_days`, `period_end_amount_quantile`, `c01_min_group_size`, `period_end_sensitive_bonus` | `c01_period_end_large()` |
| L3-05 | `custom_holidays` | `c02_weekend_entry()` |
| L3-06 | `midnight_start`, `midnight_end`, `auto_entry_sources` | `c03_after_hours_entry()` |
| L3-07 | `backdated_threshold_days` | `c04_backdated_entry()` |
| L3-08 | `min_description_length`, `ttr_threshold`, `entropy_threshold` | `c06_missing_or_corrupted_description()` |
| L3-09 | `suspense_aging_days`, `suspense_min_open_amount`, `patterns.suspense_keywords` | `c10_suspense_account()` |
| L3-10 | `patterns.high_risk_account_use.*` | `b13_high_risk_account_use()` |
| L3-11 | `ev_revenue_cutoff_days`, `ev_expense_cutoff_days`, `ev_cutoff_period_end_weight`, `ev_cutoff_max_day_diff`, `ev_cutoff_use_business_days` | `ev02_cutoff_violation()` |
| L3-12 | `patterns.work_scope_excess_review`, `patterns.sod_review_pairs`, `patterns.sod_role_thresholds` | `b14_work_scope_excess_review()` |

### L4

| 룰 | 핵심 파라미터/설정 | 코드 |
|---|---|---|
| L4-01 | `zscore_threshold`, `patterns.revenue_account_prefixes` | `b01_revenue_manipulation()` |
| L4-02 | `benford_mad_threshold`, `benford_min_sample` | `BenfordDetector`, `c07_benford_violation()` |
| L4-03 | `zscore_threshold`, `l403_min_amount_quantile` | `c08_amount_outlier()` |
| L4-04 | `account_pair_rare_percentile` | `c09_rare_account_pair()` |
| L4-05 | `abnormal_sigma_threshold`, `rapid_approval_minutes`, `min_abnormal_ratio`, `min_midnight_entries`, `min_user_entries`, `min_high_context_midnight_entries`, `auto_entry_sources` | `c12_abnormal_hours_concentration()` |
| L4-06 | `batch_source_values`, `batch_period_end_ratio`, `batch_simultaneous_threshold`, `batch_amount_zscore` | `c13_batch_anomaly()` |

### D01/D02

| 룰 | 핵심 파라미터/설정 | 코드 |
|---|---|---|
| D01 | `variance_threshold` | `d01_account_activity_variance()` |
| D02 | `monthly_pattern_threshold`, `min_monthly_data_months`, `d02_min_account_docs`, `d02_min_annual_amount`, `d02_min_top_month_delta`, `d02_review_score`, `d02_group_keys` | `d02_monthly_pattern_diagnostics()` |

## 4. Macro Finding 정책

`L4-02`, `D01`, `D02`는 단독 row-level 위반 점수를 만들지 않는다.

| 룰 | row `details` | 주 저장 위치 |
|---|---|---|
| L4-02 | `0.0` | `metadata.benford_findings`, `metadata.benford_candidate_indices` |
| D01 | `0.0` | `metadata.account_activity_variance` |
| D02 | `0.0` | `metadata.d02_account_diagnostics` |

이 신호들은 Account / Process Queue에서 먼저 표시하고, 같은 계정·월·전표군의 L1~L4 hit와 겹칠 때 Transaction Queue case에 `macro_contexts`로 붙인다.
