# r11 PHASE1-1 룰별 전수 3자 대조 (룰설명 ↔ 코드 ↔ 정답지)

- 대상 데이터셋: `data/journal/primary/datasynth_semantic_v1_recall_20260622_v46b_phase1_1_r11`
- 측정 스크립트: `tools/scripts/measure_phase1_detector_catch.py` (재실행 182.5s, rows=325,120)
- 측정 산출물: `<dataset>/reports/phase1_detector_catch/{rule_summary.csv, truth_unit_measurement.csv, summary.json}`
- 모집단(권위): truth `labels/p3_2_rule_truth.csv` 활성 PHASE1-1 rule_id = **26개**, truth units = 1,500 (standard 750 + boundary_control 750)
- 검증일: 2026-06-22

## 0. 3개 출처 정의

| 축            | 출처                                                               | 의미                                                                               |
| ------------- | ------------------------------------------------------------------ | ---------------------------------------------------------------------------------- |
| 룰설명(doc)   | `docs/spec/DETECTION_RULES.md` 룰 카드                             | 각 룰의 발화조건·임계·대상필드 SoT                                                 |
| 코드(code)    | `src/detection/*`, `src/feature/*` 구현 함수                       | 실제 detector가 하는 일                                                            |
| 정답지(truth) | `labels/p3_2_rule_truth.csv` variant + `expected_detector_outcome` | datasynth가 주입한 케이스(standard=발화해야 함 / boundary_control=경계통제·미발화) |

판정 기준: **case_kind**. `standard`=발화해야 정상, `boundary_control`=임계 직하로 미발화해야 정상(발화하면 FP). `threshold_relation`의 'below'(L2-01·L4-04)는 "승인한도/희소도 기준 below"라는 룰 내재 의미이지 발화여부가 아니다.

## 1. 전수 3자 대조표 (26/26)

`코드↔정답지` 열은 실측값 `standard_caught/standard_input · boundary_fired/boundary_input`.

| rule_id  | doc 발화조건(실측 임계)                                       | 코드 사용지점(파일:함수)                                                                           | doc↔코드       | truth↔doc      | 코드↔정답지(std·bc) |
| -------- | ------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- | -------------- | -------------- | ------------------- |
| L1-01    | `abs(Σdebit−Σcredit) > tolerance(=1.0)` per document          | `integrity_layer.py::_a01_unbalanced_entry`                                                        | 일치           | 일치           | 50/50 · 0/50        |
| L1-02    | cat1∪cat2 10필드 중 NULL/공백 1개+                            | `integrity_layer.py::_a02_missing_required`                                                        | 일치           | 일치           | 30/30 · 0/30        |
| L1-03    | `gl_account NOT IN CoA`(정규화 후, 공백 제외)                 | `integrity_layer.py::_a03_invalid_account`                                                         | 일치           | 일치           | 30/30 · 0/30        |
| L1-04    | 실재직원 승인자 한도초과 OR 권한없음                          | `amount_features.py::add_exceeds_threshold`+`fraud_rules_feature.py::b03_exceeds_threshold`        | 일치           | 일치           | 30/30 · 0/30        |
| L1-05    | `created_by==approved_by`(둘 다 비공백)                       | `fraud_rules_access.py::b06_self_approval`(+`source_trust.lone_automated_mask`)                    | 일치           | 일치           | 30/30 · 0/30        |
| L1-06    | 한 사람 회기내 process집합이 yaml toxic RED쌍 포함            | `fraud_rules_access.py::b07_segregation_of_duties`(+`sod_toxic_combinations.yaml`)                 | 일치           | 일치           | 30/30 · 0/30        |
| L1-07    | `approved_by` 공백 → 무조건 flag                              | `fraud_rules_access.py::b09_skipped_approval`                                                      | 일치           | 일치           | 30/30 · 0/30        |
| L1-07-02 | `approved_by` 비공백 & `approver_in_master==False`            | `fraud_rules_access.py::b09b_unknown_approver`                                                     | 일치           | 일치           | 20/20 · 0/20        |
| L1-08    | `fiscal_period ≠ (posting월−fiscal_year_start)%12+1`          | `anomaly_rules_simple.py::c05_fiscal_period_mismatch`(+`time_features.add_fiscal_period_mismatch`) | 일치           | 일치           | 30/30 · 0/30        |
| L2-01    | `한도×0.90 ≤ 전표총액 < 한도`                                 | `amount_features.py::add_is_near_threshold`+`fraud_rules_feature.py::b02_near_threshold`           | 일치           | 일치           | 30/30 · 0/30        |
| L2-02    | 같은거래처+ref+유사금액(강) / ref無+90일+비정기(약), ±2%·10만 | `fraud_rules_groupby.py::b04_duplicate_payment`                                                    | 일치           | 일치           | 30/30 · 0/30        |
| L2-03    | (가)증빙재기표 / (나)완전복제                                 | `fraud_rules_groupby.py::b05_duplicate_entry`                                                      | 일치           | 일치           | 20/20 · 0/20        |
| L2-04    | 같은 document내 자산차변≈비용대변(±오차)                      | `fraud_rules_groupby.py::b11_expense_capitalization`                                               | 일치           | 일치           | 20/20 · 0/20        |
| L2-05    | (A)ERP연결 / (B)1:1 거울쌍(같은계정·반대부호·금액일치·90일)   | `anomaly_rules_reversal.py::c11_reversal_entry`                                                    | 일치           | 일치           | 30/30 · 0/30        |
| L3-02    | `is_manual_je==True`(없으면 source∈manual codes)              | `fraud_rules_feature.py::b08_manual_override`                                                      | 일치           | 일치           | 30/30 · 0/30        |
| L3-03    | IC GL prefix(1150/2050/4500/2700) 사용                        | `fraud_rules_access.py::b10_intercompany_review_signal`                                            | 일치           | 일치           | 20/20 · 0/20        |
| L3-04    | `posting_date` 월말±5 또는 월초5일                            | `anomaly_rules_simple.py::c01_period_end_large`                                                    | 일치           | 일치           | 40/40 · 0/40        |
| L3-05    | `weekday()>=5` 또는 공휴일                                    | `anomaly_rules_simple.py::c02_weekend_entry`                                                       | 일치           | 일치           | 40/40 · 0/40        |
| L3-06    | `is_after_hours`(22~06시)                                     | `anomaly_rules_simple.py::c03_after_hours_entry`                                                   | 일치           | 일치           | 30/30 · 0/30        |
| L3-07    | `abs(posting−document) > 30일`                                | `anomaly_rules_simple.py::c04_backdated_entry`                                                     | 일치           | 일치           | 30/30 · 0/30        |
| L3-09    | is_suspense & unresolved & aging≥30일                         | `anomaly_rules_simple.py::c10_suspense_account`                                                    | 일치           | 일치           | 20/20 · 0/20        |
| L3-10    | account_name 키워드(1차) or gl_account 코드/prefix(2차)       | `fraud_rules_access.py::b13_estimate_account_use`                                                  | 일치           | 일치           | 40/40 · 0/40        |
| L3-11    | delivery 회계연도 ≠ 인식 회계연도                             | `evidence_detector.py`(L3-11)+`evidence_rules.py::ev02_cutoff_violation`                           | 일치           | 일치           | 30/30 · 0/30        |
| L4-01    | `is_revenue_account AND amount_zscore > 3.0`                  | `fraud_rules_feature.py::b01_revenue_manipulation`                                                 | 일치           | 일치           | 20/20 · 0/20        |
| L4-03    | `max(debit,credit) ≥ 수행중요성 임계`(pbt5%·rev0.5%·pm75%)    | `anomaly_rules_simple.py::c08_amount_outlier`+`_compute_pbt_thresholds`                            | 일치           | 일치           | 20/20 · 0/20        |
| L4-04    | cadence 희소(분기1회미만→1년 빈도≤3), engagement 단위         | `anomaly_rules_statistical.py::c09_rare_account_pair`                                              | 일치           | 일치           | 20/20 · 0/20        |
| **합계** |                                                               |                                                                                                    | **26/26 일치** | **26/26 일치** | **750/750 · 0/750** |

## 2. 코드↔정답지 실측 요약 (D1·D2)

- truth_units 1,500 = standard 750 + boundary_control 750.
- **standard caught 750/750** (26룰 전부 `standard_missed=0`). → 양성 케이스 전건 발화.
- **boundary_control fired 0/750** (26룰 전부 `evasion_caught=0`). → 경계통제 전건 미발화(FP 0).
- 즉 26개 룰 모두 "발화해야 할 것은 발화, 발화하면 안 될 직하 케이스는 침묵"이라는 임계 의미를 정확히 지킴.

> 참고: `rule_summary.csv`의 `emitted_rows`는 전체 325k행 중 룰이 발화한 행 수다(예: L1-07 218k, L3-04 149k, L3-02 88k). 이는 정상 base overlay에서의 룰 base rate이며, L1-07(공백 승인) /L3-04(±5일)/L3-02(수기) 같은 광역 context 태그의 설계상 높은 발화율이다. 본 테스트(개별 룰 발화 검증)의 정오는 truth unit 단위 caught/missed로 판정하며, emitted_rows 자체는 결함 지표가 아니다.

## 3. 불일치·주의 목록 (D5)

**코드 동작 결함(behavioral defect): 0건.** 26개 룰 모두 doc 발화조건·임계·대상필드가 코드 사용 지점에 실제 구현돼 있고(존재≠사용 통과), config 임계값은 코드가 읽는 지점까지 직접 확인했다(`zscore_threshold=3.0`, `balance_tolerance=1.0`, `near_threshold_ratio=0.90`, `period_end_margin_days=5`, `suspense_aging_days=30`, l403 `pbt_pct=0.05/rev_pct=0.005/pm_ratio=0.75`, L4-04 `cadence=1.0`). 아래는 모두 문서 표기/cosmetic 갭이며 발화 결과에 영향 없음.

| #   | rule_id     | 차원       | 내용                                                                                                                                                                                             | 증거                                                               | 영향                                 |
| --- | ----------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------ | ------------------------------------ |
| 1   | L3-04       | code       | `c01`이 `is_period_start` 컬럼을 참조하나 `time_features.py`는 이 컬럼을 생성하지 않음(죽은 참조). `bool_column`이 미존재→False 반환, 월초 발화는 `is_period_end`(day≤5)가 담당                  | `anomaly_rules_simple.py:27` vs `time_features.py`(미생성)         | 무해 — 실측 월초 variant 40/40 발화  |
| 2   | L3-04       | code       | 함수명 `c01_period_end_large`의 `_large`는 구 고액 로직 잔재(현 binary timing tag와 무관)                                                                                                        | `anomaly_rules_simple.py:18`                                       | 무해(명명)                           |
| 3   | L2-01       | doc↔code   | doc는 "구 3밴드(lower/close/razor) 폐기"라 적으나 코드에 bucket 라벨 잔존. 단 `_score_l201`이 세 band 모두 1.0 → 점수 차등 없음(annotation 표시용)                                               | `amount_features.py` `_near_threshold_bucket` / `_score_l201`(1.0) | 무해 — doc "binary flag" 취지와 부합 |
| 4   | L2-02       | doc        | doc 카드 reason code 열거(reference_match/mixed/amount_partner/blank)가 `near_extra`(truth `near_day_repayment` 대응)를 누락. 코드·breakdown에는 존재                                            | `fraud_rules_groupby.py` `near_extra` 경로                         | 무해 — truth↔코드는 일치, 문서 갭    |
| 5   | L3-03       | doc        | doc가 `intercompany_identifiers: [...]` 키로 표기하나 실제 SoT는 `patterns.intercompany.pairs`. b10 내부 `_intercompany_prefix_mask`는 yaml에 없는 키를 읽어 코드 default 폴백(값이 우연히 동일) | `intercompany_rules.py:48-51` vs b10 default                       | 무해 — prefix 값 동일                |
| 6   | L1-04       | code 주의  | GL 행의 `approval_limit` 컬럼은 판정에 미사용. 코드는 `employees.json` master 한도만 조회(존재≠사용)                                                                                             | `_load_employee_approval_map`                                      | 무해 — 발화 정상                     |
| 7   | L3-11       | code 주의  | registry에서 `revenue_account_prefixes`는 evidence→patterns 폴백, `expense_account_prefixes`는 evidence만 폴백(비대칭). 현재 `evidence.expense_account_prefixes` 존재로 정상 해소                | `evidence_detector.py:106-112`                                     | 무해 — 동일 판정식                   |
| 8   | L3-09       | doc        | doc `suspense_min_open_amount` 표기 ↔ 코드 인자 `min_open_amount`(기본 0.0). 명칭만 다름                                                                                                         | `anomaly_rules_simple.py:821,868`                                  | 무해                                 |
| 9   | L1-01/L1-03 | truth 주의 | datasynth 주입 시: L1-01 `currency_residual`은 원화 합산 잔차가 tolerance 초과해야(코드는 통화환산 안 함), L1-03 placeholder는 정규화(`.0` 제거) 후 CoA 유효값과 충돌 금지                       | 코드 통화 미환산 / `_normalize_account_code`                       | 현재 truth 정상(실측 전건 발화)      |

## 4. boundary_control 미발화 메커니즘 (hollow no_fire 아님 확인)

truth overlay는 룰마다 standard(`expected=fire`)와 boundary_control(`expected=no_fire`)을 쌍으로 주입하고, BC는 임계 미달/구조적 억제로 미발화하도록 데이터를 구성한다(예: L1-05 BC는 approved_by를 다른 ID로 분리해 self-approval 깨뜨림, L1-06 BC는 한 user가 한 process만 갖게 해 toxic쌍 미형성, L2-01 BC는 한도 90% 미만). 실측 boundary_control 발화 0/750은 빈 집합 통과(hollow)가 아니라 실제 미발화다.

## 5b. 모집단 권위 도출 + 음의 공간 증명 (전수 정당화)

"26/26"이 검사 결과에서 역산한 모집단이 아님을 권위 출처로 고정한다.

**(1) 모집단 권위(population-first)** — N=26은 truth CSV `value_counts` 역산이 아니라 **생성 매니페스트**에서 확정:
- `P3_2_OVERLAY_MANIFEST.json` → `rule_count: 26`, `truth_units: 1500`, `per_rule` 26개 항목.
- 세 집합 완전 일치 확인: `manifest.per_rule(26)` == 본 문서 §1 표(26) == `p3_2_rule_truth.csv` rule_id(26). (`manifest==table26==truthCSV` 모두 True, 차집합 0)

**(2) 음의 공간(negative-space) — 26개 밖에 PHASE1-1 행룰 0건**:
- 전체 권위 레지스트리 `src/detection/rule_scoring.py::RULE_SCORING_REGISTRY` = **32개** rule_id.
- `registry(32) − manifest(26)` = `{D01, D02, L3-12, L4-02, L4-05, L4-06}` (6개).
- 6개 전부 `rule_scoring.py`에서 **PHASE1-2 family / `macro_only`**(행 단위 결정론 룰 아님)로 명시 분류 → r11 개별발화 테스트 대상이 될 수 없음:

| 룰       | 분류 근거(코드/문서)                                                                                                            |
| -------- | ------------------------------------------------------------------------------------------------------------------------------- |
| L3-12    | `rule_scoring.py` 주석 "L3-12(업무범위 집중)는 PHASE1-2 family(사용자·연도 집계) 귀속. macro_only", `standalone_rankable=False` |
| L4-06    | `rule_scoring.py` 주석 "L4-06(배치성 전표)는 PHASE1-2 family(배치·모집단) 귀속. macro_only"                                     |
| D01, D02 | `rule_scoring.py` 주석 "D01/D02 도 macro_only 유지 ... PHASE1-2 family(TS) 귀속"                                                |
| L4-02    | Benford — `DETECTION_RULES.md` §2.4 L696 PHASE1-2 이관                                                                          |
| L4-05    | 비정상시간 집중 — `DETECTION_RULES.md` §2.4 L697 PHASE1-2 family(dual-membership, OFF-TIME 보조축, standalone 행 발화 아님)     |

- 추가 비-모집단: L3-01(폐기, `DETECTION_RULES.md` L476), EV01/EV03(EvidenceDetector context 룰, scoring registry의 scored 발화 룰 아님). 둘 다 PHASE1-1 행 발화 모집단에 미산입.

**결론**: PHASE1-1 행 단위 발화 룰의 완전 모집단 = 26 (매니페스트 권위). 그 밖 레지스트리 룰은 전부 macro/PHASE1-2로 r11 범위 밖. **모집단 밖 PHASE1-1 행룰 누락 = 0건** (음의 공간 증명 완료).

## 5. 결론

- **doc↔코드 26/26 일치**, **truth↔doc 26/26 일치**, **코드↔정답지 standard 750/750 발화·boundary 0/750 발화**.
- 코드 동작 결함 0건. 발견된 9건은 전부 문서 표기/명명/주입 주의 사항이며 발화 결과에 영향 없음.
- r11은 개별 룰 발화(detector-only) 검증 목적이며, tier 조합(HIGH/MEDIUM/LOW)·case 단위 검증은 별도 데이터셋 작업이다.
