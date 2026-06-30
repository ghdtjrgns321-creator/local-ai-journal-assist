# PHASE1-1 룰 발화 검증 결과 — r11

> **범위 한정**: 본 문서는 PHASE1-1 **개별 룰의 발화상태(detector firing)** 만 검증한 결과다. tier 조합(HIGH/MEDIUM/LOW)·실전 recall·정상데이터 과발화 억제·필드/config graceful-0 등은 **본 라운드 범위가 아니며 별도 작업**에서 다룬다(§5 참조). 여기서 "통과"는 "룰 발화 회귀 없음"을 뜻하지 실전 탐지 완전성을 주장하지 않는다.

- 데이터셋: `data/journal/primary/datasynth_semantic_v1_recall_20260622_v46b_phase1_1_r11`
- normal base: `datasynth_semantic_v1_normal_20260621_v46b`
- 측정: `tools/scripts/measure_phase1_detector_catch.py` (재실행 182.5s, rows=325,120)
- 측정 산출물: `<dataset>/reports/phase1_detector_catch/{rule_summary.csv, truth_unit_measurement.csv, summary.json}`
- 상세 3자 대조 원본: `dev/active/datasynth-journal-realism-rebuild/r11-rule-3way-verification.md`
- 검증일: 2026-06-22

## 0. 검증 설계 — 3개 출처 × 26개 룰

| 축            | 출처                                                               | 의미                                                                  |
| ------------- | ------------------------------------------------------------------ | --------------------------------------------------------------------- |
| 룰설명(doc)   | `docs/spec/DETECTION_RULES.md` 룰 카드                             | 발화조건·임계·대상필드 SoT                                            |
| 코드(code)    | `src/detection/*`, `src/feature/*` 구현 함수                       | detector 실제 동작                                                    |
| 정답지(truth) | `labels/p3_2_rule_truth.csv` variant + `expected_detector_outcome` | 주입 케이스(standard=발화해야 / boundary_control=경계직하·미발화해야) |

판정 기준 = `case_kind`. standard=발화 정상, boundary_control=미발화 정상(발화 시 FP).

## 1. 모집단 권위 + 음의 공간 (전수 정당화)

- **모집단(권위, population-first)**: 생성 매니페스트 `P3_2_OVERLAY_MANIFEST.json::rule_count=26`(+`per_rule` 26항목)이 PHASE1-1 활성 행룰 N=26을 선언. truth CSV 역산 아님. 세 집합 동일 확인: `manifest.per_rule == 본문 §2 표(26) == truth_csv rule_id(26)` (차집합 0).
- **음의 공간**: 전체 레지스트리 `rule_scoring.py::RULE_SCORING_REGISTRY`=32. `registry−26`={D01,D02,L3-12,L4-02,L4-05,L4-06}=6, 전부 PHASE1-2 family/`macro_only`(행 단위 룰 아님 → r11 개별발화 대상 아님). 모집단 밖 PHASE1-1 행룰 누락 = **0건**.

| 제외 룰                                        | 분류 근거                                                                                                   |
| ---------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| L3-12                                          | `rule_scoring.py` "업무범위 집중 → PHASE1-2 family(사용자·연도 집계) macro_only", standalone_rankable=False |
| L4-06                                          | `rule_scoring.py` "배치성 전표 → PHASE1-2 family macro_only"                                                |
| D01·D02                                        | `rule_scoring.py` "macro_only 유지 → PHASE1-2 family(TS)"                                                   |
| L4-02(Benford)·L4-05                           | `DETECTION_RULES.md` §2.4 PHASE1-2 이관                                                                     |
| (참고) L3-01 폐기 / EV01·EV03 evidence context | PHASE1-1 발화 모집단 미산입                                                                                 |

## 2. 전수 3자 대조표 (26/26)

`코드↔정답지` = 실측 `standard_caught/standard_input · boundary_fired/boundary_input`.

| rule_id  | doc 발화조건(실측 임계)                                       | 코드 사용지점                                                                                  | doc↔코드  | truth↔doc | 코드↔정답지(std·bc) |
| -------- | ------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- | --------- | --------- | ------------------- |
| L1-01    | `abs(Σdebit−Σcredit) > 1.0` per document                      | `integrity_layer.py::_a01_unbalanced_entry`                                                    | 일치      | 일치      | 50/50 · 0/50        |
| L1-02    | cat1∪cat2 10필드 중 NULL/공백 1개+                            | `integrity_layer.py::_a02_missing_required`                                                    | 일치      | 일치      | 30/30 · 0/30        |
| L1-03    | `gl_account NOT IN CoA`(정규화 후, 공백 제외)                 | `integrity_layer.py::_a03_invalid_account`                                                     | 일치      | 일치      | 30/30 · 0/30        |
| L1-04    | 실재직원 승인자 한도초과 OR 권한없음                          | `amount_features.add_exceeds_threshold`+`fraud_rules_feature.b03_exceeds_threshold`            | 일치      | 일치      | 30/30 · 0/30        |
| L1-05    | `created_by==approved_by`(둘 다 비공백)                       | `fraud_rules_access.b06_self_approval`(+`source_trust.lone_automated_mask`)                    | 일치      | 일치      | 30/30 · 0/30        |
| L1-06    | 한 사람 회기내 process집합이 yaml toxic RED쌍 포함            | `fraud_rules_access.b07_segregation_of_duties`(+`sod_toxic_combinations.yaml`)                 | 일치      | 일치      | 30/30 · 0/30        |
| L1-07    | `approved_by` 공백 → 무조건 flag                              | `fraud_rules_access.b09_skipped_approval`                                                      | 일치      | 일치      | 30/30 · 0/30        |
| L1-07-02 | `approved_by` 비공백 & `approver_in_master==False`            | `fraud_rules_access.b09b_unknown_approver`                                                     | 일치      | 일치      | 20/20 · 0/20        |
| L1-08    | `fiscal_period ≠ (posting월−fiscal_year_start)%12+1`          | `anomaly_rules_simple.c05_fiscal_period_mismatch`(+`time_features.add_fiscal_period_mismatch`) | 일치      | 일치      | 30/30 · 0/30        |
| L2-01    | `한도×0.90 ≤ 전표총액 < 한도`                                 | `amount_features.add_is_near_threshold`+`fraud_rules_feature.b02_near_threshold`               | 일치      | 일치      | 30/30 · 0/30        |
| L2-02    | 같은거래처+ref+유사금액(강) / ref無+90일+비정기(약), ±2%·10만 | `fraud_rules_groupby.b04_duplicate_payment`                                                    | 일치      | 일치      | 30/30 · 0/30        |
| L2-03    | (가)증빙재기표 / (나)완전복제                                 | `fraud_rules_groupby.b05_duplicate_entry`                                                      | 일치      | 일치      | 20/20 · 0/20        |
| L2-04    | 같은 document내 자산차변≈비용대변(±오차)                      | `fraud_rules_groupby.b11_expense_capitalization`                                               | 일치      | 일치      | 20/20 · 0/20        |
| L2-05    | (A)ERP연결 / (B)1:1 거울쌍(같은계정·반대부호·금액일치·90일)   | `anomaly_rules_reversal.c11_reversal_entry`                                                    | 일치      | 일치      | 30/30 · 0/30        |
| L3-02    | `is_manual_je==True`(없으면 source∈manual codes)              | `fraud_rules_feature.b08_manual_override`                                                      | 일치      | 일치      | 30/30 · 0/30        |
| L3-03    | IC GL prefix(1150/2050/4500/2700) 사용                        | `fraud_rules_access.b10_intercompany_review_signal`                                            | 일치      | 일치      | 20/20 · 0/20        |
| L3-04    | `posting_date` 월말±5 또는 월초5일                            | `anomaly_rules_simple.c01_period_end_large`                                                    | 일치      | 일치      | 40/40 · 0/40        |
| L3-05    | `weekday()>=5` 또는 공휴일                                    | `anomaly_rules_simple.c02_weekend_entry`                                                       | 일치      | 일치      | 40/40 · 0/40        |
| L3-06    | `is_after_hours`(22~06시)                                     | `anomaly_rules_simple.c03_after_hours_entry`                                                   | 일치      | 일치      | 30/30 · 0/30        |
| L3-07    | `abs(posting−document) > 30일`                                | `anomaly_rules_simple.c04_backdated_entry`                                                     | 일치      | 일치      | 30/30 · 0/30        |
| L3-09    | is_suspense & unresolved & aging≥30일                         | `anomaly_rules_simple.c10_suspense_account`                                                    | 일치      | 일치      | 20/20 · 0/20        |
| L3-10    | account_name 키워드(1차) or gl_account 코드/prefix(2차)       | `fraud_rules_access.b13_estimate_account_use`                                                  | 일치      | 일치      | 40/40 · 0/40        |
| L3-11    | delivery 회계연도 ≠ 인식 회계연도                             | `evidence_detector`(L3-11)+`evidence_rules.ev02_cutoff_violation`                              | 일치      | 일치      | 30/30 · 0/30        |
| L4-01    | `is_revenue_account AND amount_zscore > 3.0`                  | `fraud_rules_feature.b01_revenue_manipulation`                                                 | 일치      | 일치      | 20/20 · 0/20        |
| L4-03    | `max(debit,credit) ≥ 수행중요성 임계`(pbt5%·rev0.5%·pm75%)    | `anomaly_rules_simple.c08_amount_outlier`+`_compute_pbt_thresholds`                            | 일치      | 일치      | 20/20 · 0/20        |
| L4-04    | cadence 희소(분기1회미만→1년 빈도≤3), engagement 단위         | `anomaly_rules_statistical.c09_rare_account_pair`                                              | 일치      | 일치      | 20/20 · 0/20        |
| **합계** |                                                               |                                                                                                | **26/26** | **26/26** | **750/750 · 0/750** |

임계값은 doc이 아니라 코드/config 사용지점에서 직접 확인: `zscore_threshold=3.0`, `balance_tolerance=1.0`, `near_threshold_ratio=0.90`, `period_end_margin_days=5`, `suspense_aging_days=30`, l403 `pbt_pct=0.05/rev_pct=0.005/pm_ratio=0.75`, L4-04 `cadence=1.0`.

## 3. 코드↔정답지 실측 요약

- **standard caught 750/750** (26룰 전부 `standard_missed=0`) → 양성 전건 발화.
- **boundary_control fired 0/750** (26룰 전부 `evasion_caught=0`) → 경계 전건 미발화(FP 0).
- boundary 미발화는 빈 집합 통과(hollow)가 아님: overlay가 룰별로 임계 미달/구조 억제로 미발화하게 구성(L2-01 BC<90%, L1-06 BC 단일 process, L1-05 BC 승인자 분리 등).

> `emitted_rows`(전체 325k행 중 발화 행 수)는 정상 base에서의 룰 base rate다. L1-07 218k(67%)·L3-04 149k(46%)·L3-02 88k(27%) 등 광역 context 태그의 설계상 높은 발화율이며, 본 검증의 정오 판정은 truth unit caught/missed로 한다(emitted_rows는 결함 지표 아님). 단 이 과발화의 다운스트림 억제는 §5 범위 밖.

## 4. 불일치 목록

**코드 동작 결함 0건.** 아래 9건은 전부 문서 표기/명명/주입 주의이며 발화 결과 무영향(상세·증거는 원본 §3).

| #   | rule_id     | 차원      | 요지                                                                                                                         |
| --- | ----------- | --------- | ---------------------------------------------------------------------------------------------------------------------------- |
| 1   | L3-04       | code      | `c01`이 `is_period_start` 참조하나 `time_features`가 미생성(죽은 참조). 월초는 `is_period_end` day≤5가 담당, 실측 40/40 발화 |
| 2   | L3-04       | code      | 함수명 `c01_period_end_large`의 `_large`는 stale 잔재                                                                        |
| 3   | L2-01       | doc↔code  | doc "3밴드 폐기"인데 코드에 bucket 라벨 잔존(점수 전부 1.0, 표시용)                                                          |
| 4   | L2-02       | doc       | reason code 열거가 `near_extra`(truth `near_day_repayment`) 누락                                                             |
| 5   | L3-03       | doc       | doc 키 `intercompany_identifiers` ↔ 실제 SoT `patterns.intercompany.pairs`(값 동일)                                          |
| 6   | L1-04       | code주의  | 행 `approval_limit` 컬럼 미사용, employees.json master만 조회                                                                |
| 7   | L3-11       | code주의  | registry `expense_account_prefixes` 폴백 비대칭(현재 정상 해소)                                                              |
| 8   | L3-09       | doc       | doc `suspense_min_open_amount` ↔ 코드 인자 `min_open_amount`(기본 0.0, 동일)                                                 |
| 9   | L1-01/L1-03 | truth주의 | L1-01 currency_residual 원화잔차·L1-03 placeholder 정규화 주입 주의(현재 정상)                                               |

## 5. 본 라운드 범위 밖 (별도 작업)

아래는 r11이 다루지 **않으며**, 여기서 통과로 해석하면 안 된다. 별도 데이터셋/작업에서 검증한다.

| 항목                            | 이유                                                                           |
| ------------------------------- | ------------------------------------------------------------------------------ |
| tier 조합(HIGH/MEDIUM/LOW) 출력 | r11은 detector 발화만 봄. 조합·등급은 별도 데이터셋                            |
| 실전 recall                     | 합성 overlay는 발화조건을 알고 주입 → 회귀 가드일 뿐 recall 증거 아님          |
| 정상데이터 과발화 억제          | 광역 태그(L1-07 67% 등)를 통합점수가 LOW로 누르는지 미검증                     |
| 필드/config graceful-0          | 실 ERP에서 settlement/delivery/employees/추정계정 yaml 부재 시 조용한 0건 위험 |
| 측정↔프로덕션 파이프라인 동등성 | measure 스크립트는 detector 직접 호출(래퍼 우회)                               |

### 5b. 경계통제 타이트함 측정 — 미실시 (저가치 판정)
- boundary_control이 임계 바로 밑(타이트)인지 한참 밑(느슨)인지 거리를 재는 것은 기술적으로 가능하나(연속 임계 룰의 경계 문서에서 판정 지표 재계산), **이번 검증에서는 실시하지 않는다.**
- 이유: 룰이 **결정론적 이진분류**고 임계값·비교연산자를 이미 코드에서 직접 확인했다(L1-01 strict `>1.0`, L2-01 `≥limit×0.90 ∧ <limit`, L4-01 `>3.0` 등). 경계 거리는 코드 정오를 바꾸지 못한다 — 특이도는 경계 타이트함이 아니라 **코드+임계 읽기로 이미 성립**하며, boundary_control은 "비발화 쪽 침묵 확인"이라는 제 역할을 이미 다했다(0/750).
- 타이트함이 의미 있으려면 임계가 불확실·학습값일 때인데, 여기선 하드코딩/config 상수다. 정확히 `==임계` 부등호 edge는 ① 코드의 strict `>`/`>=` 확인, ② truth `threshold_relation='at'` variant로 일부 커버됨.

## 6. 결론

PHASE1-1 26개 룰 모두 **룰설명·코드·정답지 3자 일치**, 양성 750/750 발화·경계 0/750 발화, 코드 결함 0건. 단 이는 **개별 룰 발화 회귀 가드 통과**이며, tier 조합·실전 recall·과발화 억제는 별도 작업이다.
