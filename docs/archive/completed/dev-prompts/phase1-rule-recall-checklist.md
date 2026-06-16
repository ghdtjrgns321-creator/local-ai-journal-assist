# PHASE1 룰 위반 변형 체크리스트 (리콜 측정용 datasynth 스펙) — 코드 검증판

목적: "PHASE1 룰이 제대로 구동하는가"를 케이스 2개가 아니라 **변형 N개로 입증**한다. 룰마다 잡아야 할 위반 변형을 열거하고, 각 변형의 **RAW 위반조건(detector 실제 트리거 — 파생 flag 아님)**·woven flow·분산축을 정의한다. datasynth가 이 변형들을 실제 위반 데이터로 생성하고, 전수 PHASE1로 룰별 리콜을 측정한다.

> 본 판은 detector 코드를 룰별로 직접 읽어 확정했다(rule_id→함수 매핑은 `fraud_layer.py:_build_registry` / `anomaly_layer.py:_build_registry` / `integrity_layer` 레지스트리). 초안의 surface 기반 설명 3개를 코드 기준으로 정정했다.

## ⚠️ 초안 정정 (surface 라벨 ≠ detector 의미)

| rule_id | RULE_CODES (canonical) | 실제 detector | 초안 오류 | 실제 RAW |
|---------|------------------------|---------------|-----------|----------|
| L2-01 | Just Below Approval Threshold | `b02_near_threshold` | "분할/참조(reference)" ✕ | 승인한도 90~99.9% 직하. employees.json 마스터 의존 |
| L2-04 | Expense Capitalization Signal | `b11_expense_capitalization` | "계정+적요+문서(account_text)" ✕ | 한 전표 내 자산(12/15 차변)↔비용(5~8 대변) 캐피탈라이징 |
| L4-01 | Revenue Outlier | `b01_revenue_manipulation` | "월분포 스파이크(month dist)" ✕ | 수익계정 AND amount_zscore>3 (z 파생→배경분포 필요) |

(L4-04는 "Rare Debit-Credit Account Pair"로 초안과 일치, L3 시리즈도 일치.)

---

## 0. 주입 인프라 전제 (이게 없으면 룰이 영원히 미발화)

datasynth 생성 시 아래가 충족돼야 한다. **공통 1순위 함정: 파생(derived) 컬럼은 feature 엔진이 매 실행 덮어쓰므로 직접 주입은 전부 무효.** 원천 컬럼으로만 발화시킨다.

| 전제 | 영향 룰 | 요건 |
|------|---------|------|
| `master_data/employees.json` 마스터 | L1-04, L2-01, (L1-07 격상) | `approved_by` user가 마스터에 있고 그 직원 `approval_limit`/`can_approve_je` 설정돼야 `exceeds_threshold`·`is_near_threshold` 재계산됨. 미연결 시 전건 미발화 |
| CoA 마스터 공유 | L1-03, L3-01 | 정상 행 `gl_account`는 전부 CoA 안. 위반은 CoA 밖 코드. CoA 미로드 시 L1-03 skip |
| 전기 engagement DuckDB (`fiscal_year=current-1`) | **D01, D02** | `general_ledger` 적재 또는 `PriorSummary.account_aggregates`/`monthly_patterns` 주입. 없으면 D01/D02 전체 skip |
| 다회사 구조 | **GR01, GR03, IC01-high** | IC GL prefix(rec 1150/4500, pay 2050/2700) + 여러 company_code. IC01 high는 partner가 **데이터 내 어느 company_code에도 없는 외부 코드**여야 함(master 폴백 때문) |
| 타임스탬프에 **시각 포함** | L3-06, L4-05 | `posting_date`에 시각 없으면(전부 00:00) `is_after_hours`/`time_zone_category` 전건 미발화 |
| `holidays.KR` 패키지 | L3-05 | 공휴일 발화에 필요. 미설치 시 주말만 |
| 배경 모집단(정상 다수) | **L4-01/02/03/04/05/06, L3-09** | z-score·분위·Benford·희소빈도·σ 기준이 배경분포 없으면 오염(역설적으로 미발화 또는 전건 발화) |

### 파생 컬럼 → 주입할 원천 (직접 박지 말 것)
`exceeds_threshold`·`approval_level`·`approval_limit_resolved`·`is_near_threshold` ← `debit/credit_amount`+`approved_by`+employees.json / `is_period_end` ← `posting_date` / `is_weekend`·`is_holiday` ← `posting_date` / `is_after_hours`·`time_zone_category` ← `posting_date`(시각) / `days_backdated` ← `posting_date`−`document_date` / `description_quality` ← `line_text`+`header_text` / `is_manual_je` ← `source` / `is_intercompany` ← `gl_account` prefix·`business_process`·`counterparty_type` / `is_suspense_account` ← `gl_account`·텍스트 / `amount_zscore` ← gl_account 그룹분포 / `first_digit` ← `debit/credit_amount` / `fiscal_period_mismatch` ← `fiscal_period` vs `posting_date`.
**절대 켜지 말 것:** `approval_contract_degraded`(L1-07/L1-09 전건 0점화).

### 측정 단위 분류 (catch 단위가 다름)
- **단건(row) 발화**: L1-01~09, L2-02, L2-03a~d, L2-04(단 노출은 confidence≥0.75), L2-05, L3-01~08, L3-10, L3-11, IC02, IC03, GR01, GR03, L4-05(rapid 경로만).
- **집계/모집단 필요**: L4-01·L4-03(gl_account 배경 ~30건 + 스파이크), L4-02/Benford(company×gl_account 그룹 500건+), L4-04(흔한쌍 다수+희귀쌍), L4-05(사용자 ≥3), L4-06(배치 묶음), L3-09(생애주기·dataset_end 상대).
- **review-only (score 0, catch로 안 잡힘 → evidence_level/우선순위로 측정)**: L3-12, IC01(review/review_stale 등급), D01, D02, L4-02(행 score 0 finding-only).

---

## L1 — 구조/승인

### L1-01 Unbalanced Entry — `integrity_layer._a01_unbalanced_entry`
- RAW: `document_id`별 |Σdebit − Σcredit| > `balance_tolerance`(기본 1.0). 발화 시 그 전표 전 행.
- 파생 의존 없음(순수 원천). 분리자/누수 없음(정상은 ±1.0 내).
- 변형: (1) 경계 직상(차이 1.5원) (2) 소액 불균형 (3) 거액 (4) 다중라인 한 줄 누락 (5) 통화혼재 잔차 (6) **대조군: 차이 0.5원=미발화**.
- 분산: 금액대·라인수·통화. woven: 전 흐름 GL.

### L1-02 Missing Required Field — `integrity_layer._a02_missing_required`
- RAW: schema.yaml `required=true` 컬럼 중 하나라도 NULL/공백. (표시용 `missing_fields`는 파생 — 원천 컬럼을 실제로 비울 것)
- 주의: L1-01 등 다른 룰이 그 행을 못 보게 할 수 있으니 비핵심 required(예 `document_type`)를 비움.
- 변형: (1) document_type 공백 (2) posting_date 공백 (3) 다중 필수필드 공백 (4) **대조군: 전 필드 채움**.
- 분산: 누락 필드 종류.

### L1-03 Invalid Account — `integrity_layer._a03_invalid_account`
- RAW: `gl_account` 정규화 후 비공백이며 CoA 집합에 **부재**. (CoA 미제공 시 룰 skip → CoA 마스터 datasynth와 공유 필수)
- 변형: (1) 완전 미등록 코드 (2) 형식오류(자리수 비정상) (3) placeholder/reserved 패턴 (4) **대조군: CoA 내 코드**.
- 분산: 계정군. 주의: 999999가 CoA에 있으면 진짜 부재코드 사용.

### L1-04 Exceeded Approval Limit — `fraud_rules_feature.b03_exceeds_threshold`
- RAW: `exceeds_threshold`(파생) ← employees.json의 `approved_by` 직원 `approval_limit` < 전표 합계금액. **직접 박지 말고**: ① approved_by를 마스터에 등록 + 한도 낮게 ② 전표 debit/credit 합을 한도 초과로.
- config: `approval_thresholds`=[10M,100M,1B,5B,10B,50B]. boundary 버킷은 review 강등.
- 변형: (1) 소폭 초과(boundary) (2) 대폭 초과(critical) (3) **대조군: 한도 직하=미발화** (4) 승인자 권한등급별.
- 분산: 금액/한도비율·승인자. woven: P2P 승인.

### L1-05 Self Approval — `fraud_rules_access.b06_self_approval`
- RAW: `created_by` == `approved_by`(둘 다 비공백, 소문자 normalize).
- 분리자: 자동전기는 `user_persona=automated_system` 또는 `source=automated`면 allowed→score 0(정상 자기승인은 자동시스템에만 허용). 정상 행은 creator≠approver.
- 변형: (1) 동일인 자가승인 (2) 거액 자가승인(immediate 0.8) (3) R2R/A2R(review 0.4) (4) **대조군: 타인 승인**.
- 분산: 사용자·금액·프로세스.

### L1-06 Segregation of Duties — `fraud_rules_access.b07_segregation_of_duties`
- **정정**: 단순 "한 사람이 여러 프로세스" 사실만으론 L1-06 미발화(그건 L3-12로 이관). 발화 게이트 3경로(OR), 모두 `human_mask`(비시스템) 통과 필요:
  1. **`sod_conflict_type` 컬럼에 비공백 문자열**(예 "cash_disbursement") → within_process_conflict (가장 확실한 트리거).
  2. `sod_violation=True` AND `sod_conflict_type` 비공백.
  3. IT super-user: `user_persona`∈{it_admin,system_admin,...} AND `business_process`∈{TRE,P2P,O2C,H2R} AND line_amount>0.
- 분리자: 정상은 `sod_conflict_type` 공백 + it_admin이 보호 프로세스 금전전기 안 함. system 전기는 human_mask에서 제외.
- 변형: (1) sod_conflict_type=cash_disbursement(direct_high 0.80) (2) IT admin 경로 (3) 거액 충돌 (4) **대조군: sod_conflict_type 공백**.

### L1-07 Skipped Approval — `fraud_rules_access.b09_skipped_approval`
- RAW: `approved_by` 공백(candidate). immediate 격상 = `source∈manual` + `~system_source` + 증거 2개 이상(no approval_date, business_process=TRE 등).
- 분리자: 정상은 approved_by 채움. `source∈system`(automated/batch)면 actionable 제외 → 정상 자동전기는 system source.
- 변형: (1) 한도초과 무승인 (2) 수기 무승인(immediate) (3) **대조군: system 출처 무승인=무점수** (4) **대조군: 승인 채움**.
- 주의: `approval_contract_degraded` 켜지 말 것(전건 0점).

### L1-08 Wrong Fiscal Period — `anomaly_rules_simple.c05_fiscal_period_mismatch`
- **[추론 해소]** RAW: `fiscal_period_mismatch`(파생) ← `time_features.add_fiscal_period_mismatch`: `expected = (posting_date.month − fiscal_year_start)%12 + 1`; mismatch = `fiscal_period != expected`. **둘 다 non-null 필수**(NaN이면 미발화). 직접 박지 말고 **`fiscal_period`를 posting_date 월과 다르게**(예 posting=3월인데 fiscal_period=7).
- config: `fiscal_period_mismatch_policy`(strict_mode=true, fiscal_year_start=1).
- 분리자: 정상은 `fiscal_period == (month−1)%12+1`.
- 변형: (1) period-month 불일치 (2) 마감기간 사후기표 (3) 잘못된 fiscal_year (4) **대조군: period=month 일치**. woven: 결산기.

### L1-09 Approval Date Missing — `fraud_rules_access.b12_missing_approval_date`
- RAW: `approval_date` 공백(candidate). 핵심 신호 = `approved_by`는 있는데 날짜만 없음(has_approver). approved_by도 없으면 low_priority(0.1).
- 변형: (1) 승인자 있고 승인일 없음(immediate) (2) high_risk 프로세스 (3) **대조군: 승인일 채움**.
- 주의: `approval_contract_degraded` 켜지 말 것.

---

## L2 — 중복/한도/역분개

### L2-01 Just Below Approval Threshold — `fraud_rules_feature.b02_near_threshold`
- **정정**: reference 분할 아님. RAW: `is_near_threshold`(파생) ← `resolved & (doc_amount ≥ limit×0.90) & (doc_amount < limit)`. limit = employees.json `approved_by` 직원 `approval_limit`. bucket: 0.90~0.95 lower / 0.95~0.98 close / 0.98~1.00 razor.
- config: `near_threshold_ratio=0.90`. `source∈automated/recurring/batch`면 razor 상한 0.35로 강등 또는 0.
- 직접 박지 말고: approved_by 마스터 등록 + 전표 합계를 한도의 90~99.9%로.
- 변형: (1) lower_band(0.92×) (2) close_band(0.96×) (3) razor_band(0.99×) (4) **대조군: 0.88×=미발화** (5) **대조군: 자동 출처=강등**.
- 분산: 한도비율·승인자. woven: P2P.

### L2-02 Duplicate Payment — `fraud_rules_groupby.b04_duplicate_payment`
- scope: `business_process="P2P"` AND `document_type∈{KZ,KR}`. RAW strong(0.9): 같은 partner_key + 같은 canonical reference, 다른 document_id, |amount−prev|≤tolerance(=clamp(amount×0.02,1,100k)) AND day_gap≤45.
- canonical reference: `PREFIX+C\d{3}+year+number`(예 PAYC001202312) 패턴이어야 strong key. 임의 문자열은 alnum-only 폴백.
- 분리자: 월정기 결제(25~35일 간격, CV≤0.20 recurring profile)는 fallback 억제 → 정상 반복지급을 normal에 둘 것.
- 변형: (1) 동일 reference·금액 2건 (2) 근접일 재지급 (3) reference 미세변형(OCR) (4) **대조군: day_gap 46일=미발화**.

### L2-03a/b/c/d Duplicate Entry — `duplicate_rules.b05a~d` (DuplicateDetector, 순수 RAW)
- **a 완전중복**: gl_account+max(debit,credit)+posting_date 3중 동일 그룹 size≥2 → 1.0.
- **b 퍼지**: 같은 gl_account, line_text token_sort_ratio≥80% AND 금액 rel_diff≤2%.
- **c 분할**: 같은 gl_account, 3일 내 target 1건 ≈ 작은 2건 합(±2%), group≥3.
- **d 시차중복**: 같은 gl_account+floor(amount), 7일 내 날짜만 다름.
- config: fuzzy=80, tol=0.02, split_window=3, time_window=7, max_group=1000.
- 변형(각): 발화 + **경계 직하 대조군**(b: 유사도 79%, c: 합계 ×1.03, d: 8일차).
- 주의: c는 정상 분할청구도 잡으므로 대조군 필수.

### L2-04 Expense Capitalization Signal — `fraud_rules_groupby.b11_expense_capitalization`
- **정정 + 노출 갭**: RAW: 한 document_id 안에 `asset(debit>0, gl 12/15)` ∩ `expense(credit>0, gl 5/6/7/8)`. confidence: 라인금액매칭(±2%)→0.55, subtotal매칭→0.35; modifier: suspicious_keyword +0.15, manual source +0.10, suspicious_process +0.05, normal_keyword −0.20, normal_doc_type(AA/FA) −0.10.
- **노출 갭(측정 핵심)**: `flagged`(rule_flag)은 매칭 전표 전 행이지만, **scores/details에는 confidence≥0.75(immediate)만 노출**. 0.45~0.75 review는 metadata에만. → scores에 뜨게 하려면 0.55(라인매칭)+0.15(키워드)+0.10(manual)=0.80 조합 필요. 단순 자산/비용 공존만으론 0.55=review band(미노출).
- 분리자: normal_keywords(capex/capital/software/license)+doc_type(AA/FA)이 confidence 깎음. 정상 캐피탈라이징을 키워드와 함께 normal에. (키워드 의존 있음→양쪽 동일 분포 필요)
- 변형: (1) immediate(라인매칭+키워드+manual, ≥0.75) (2) review(공존만, 0.55) (3) **대조군: 금액차 2.1%(0.0)** (4) **대조군: normal_keyword+AA(confidence 0)**.

### L2-05 Reversal Pattern — `anomaly_rules_reversal.c11_reversal_entry`
- RAW: `(final_score≥0.3 OR evidence_score≥0.3) AND has_reversal_pattern`. has_pattern = S0|S1|S2|S2b 중 하나(S3/S4/S5는 점수 가감만, 단독 발화 불가).
  - **S0(0.60, 가장 강함)**: `reversal_document_id`/`original_document_id`/`reversal_reason` 등 링크/사유 컬럼 값 존재. 단독으로 threshold 초과.
  - S1(0.35): 1:1 net 반대 페어, 같은 gl_account+abs_amt, day_gap≤1, context_score≥2(reference 동일=+2 등).
  - S2(0.30): (gl_account,created_by) 7일 누적 net≈0(|net|<1000 & ratio<0.05), document≥2.
  - S2b(0.35): 한 document 내 라인 차/대변 스왑.
- 분리자(가장 중요): 정상 결산 reversing entry(`source=automated/recurring` + 월초 day≤5 + 1월)는 −0.15 + routine&no-keyword면 score 0(population). **구조(S0 유무)가 진짜 분리자** — keyword는 보조(S4 0.10)일 뿐, 정상 역분개에도 동일 keyword 분포시켜야 누수 안 됨.
- 변형: (1) 기말 manual self-reversal + S0 링크 (2) 단기 취소(S1) (3) 거액 (4) **대조군: 정상 accrual 역분개(automated+월초)=score 0** (5) **대조군: S0~S2b 전부 미성립 + keyword만=미발화**.

---

## L3 — 시점/의미/품질

### L3-01 Misclassified Account — `integrity_layer._l301_misclassified_account`
- RAW: `(business_process, gl_account)`가 `process_denied_accounts` exact 목록(score 0.65) 또는 `(process, 계정카테고리)`가 `process_disallowed_categories`(0.45). 카테고리는 account_category 컬럼 또는 gl_account prefix(revenue=4, expense=5/6/7/8, inventory=12, payroll=54/64/74).
- denied 예: P2P→400030..400780/4100, O2C→500000..500960/6800, TRE→1200/1290.
- disallowed category: O2C→expense, P2P→revenue, H2R→revenue, TRE→inventory, A2R→payroll.
- 주의: `business_process` 컬럼 부재 시 룰 skip. CoA에 있는 계정이어야 valid(L1-03과 분리).
- 변형: (1) P2P+gl 400030(denied) (2) O2C+expense (3) TRE+inventory (4) **대조군: P2P+정상계정**.

### L3-02 Manual Entry Override — `fraud_rules_feature.b08_manual_override`
- RAW: `is_manual_je` ← `source∈{Manual,Adjustment}`. 순수 manual 후보는 review 0.35, priority/bypass(0.60/0.75)는 고액·기말·자기승인 등 컨텍스트 동반.
- 분리자: `source=automated/recurring/interface`=비후보.
- 변형: (1) 거액 수기(priority) (2) 결산기 수기 (3) 단순 수기(review 0.35) (4) **대조군: 자동 출처**.
- 비고: raw 발화율 높음 — 리콜보다 우선순위 차등 검증.

### L3-03 Related Party Review Signal — `fraud_rules_access.b10_intercompany_review_signal`
- RAW: `is_intercompany=True`(score 일괄 0.4) ← gl_account prefix 1150/2050/4500/2700 또는 business_process="intercompany" 또는 counterparty_type="intercompanyaffiliate".
- 변형: (1) IC계정 1150 (2) business_process=intercompany (3) **대조군: 비IC**. (booster — 단독 ranking 불가)

### L3-04 Period-end Closing Candidate — `anomaly_rules_simple.c01_period_end_large`
- RAW: `is_period_end` ← posting_date가 월말 ≤5일전 **또는** 익월 초 ≤5일(양방향). 금액밴드(Q50~Q95)는 score만(데이터셋 분포 의존).
- 변형: (1) 월말 당일 (2) 결산−3일 (3) 익월초 +2일 (4) 거액 결산기 (5) **대조군: 월 15일=미발화**.

### L3-05 Weekend/Holiday — `anomaly_rules_simple.c02_weekend_entry`
- RAW: `is_weekend|is_holiday` ← posting_date가 **실제 토(5)/일(6) 또는 실제 KR 공휴일**. score: weekday_holiday 0.35 / weekend 0.40 / weekend+holiday 0.45.
- 주의: holidays.KR 미설치 시 공휴일 누락.
- 변형: (1) 토요일 (2) 일요일 (3) 실제 공휴일(2025-01-01 등) (4) 연휴 (5) **대조군: 평일**.

### L3-06 After-hours — `anomaly_rules_simple.c03_after_hours_entry`
- RAW: `is_after_hours` ← posting_date 시각 ≥22:00 또는 <06:00. **시각 정보 없으면 전건 미발화**. 사람/미상 0.45, 시스템/배치 0.20.
- 변형: (1) 자정 전후 (2) 새벽 (3) 거액 심야 (4) **대조군: 21:59 또는 주간**.

### L3-07 Posting-Document Date Gap — `anomaly_rules_simple.c04_backdated_entry`
- RAW: |posting_date − document_date| > `backdated_threshold_days`(기본 30). bucket: ≤60 moderate(0.45)/≤90 large(0.60)/>90 extreme(0.75). 부호로 late(+)/forward(−).
- 주의: `document_date` 부재 시 전건 미발화.
- 변형: (1) 장기 지연(45일) (2) 선행기표(음수) (3) extreme(>90) (4) **대조군: 30일=미발화**.

### L3-08 Missing/Corrupted Description — `anomaly_rules_simple.c06_missing_or_corrupted_description`
- RAW: `description_quality∈{missing,corrupted,poor}` ← combined = `line_text + " " + header_text`. **missing은 둘 다 공백/NaN 필수**(한쪽이라도 내용 있으면 normal). corrupted는 결합 문자열이 노이즈.
- 변형: (1) line_text+header_text 둘 다 공백(missing) (2) 둘 다 노이즈(corrupted) (3) **대조군: header_text에 정상텍스트**.

### L3-09 Suspense Aging — `anomaly_rules_simple.c10_suspense_account`
- RAW: `suspense & resolution_signal_present & unresolved & aging_days≥30`. `is_suspense_account` ← gl_account 1190/1290/2190/2900/9990 prefix 또는 suspense 키워드.
- **생애주기·집계 함정**: resolution_date 없으면 aging_end = **dataset 전체 posting_date 최대값**. 고립 1행은 자기 자신이 max → aging=0 → 미발화. 발화하려면 ① `settlement_date`/`lettrage_date`를 posting+≥30일로 주입, 또는 ② posting이 ≥30일 늦은 다른 행으로 dataset_end를 밀기. resolution 신호 전무(amount_open/is_cleared/settlement_status/settlement_date/lettrage 부재)면 미발화.
- 변형: (1) settlement_date=posting+45일(단건 가능) (2) 거액 미청산 (3) **대조군: settlement_date=posting+29일** (4) **대조군: is_cleared=True**.
- 측정: aging이 dataset-relative → 모집단 맥락 필요(②경로). 단건은 ①경로만.

### L3-10 High-risk Account — `fraud_rules_access.b13_high_risk_account_use`
- RAW: `gl_account ∈ {1190,2190}` 또는 prefix∈{111,112,113}. priority(0.65)=manual/uncleared/period_end 등 동반, 아니면 raw 0.35.
- 변형: (1) 1190 가지급 (2) 2190 가수금 (3) 111x 현금성 (4) 거액 priority (5) **대조군: 1180/1140=미발화**.

### L3-11 Revenue Cutoff Mismatch — `evidence_rules.ev02_cutoff_violation`
- RAW: revenue(gl prefix 4 또는 is_revenue_account)이고 영업일(posting,delivery) diff > `ev_revenue_cutoff_days`(5); 또는 expense(prefix 5)이고 > `ev_expense_cutoff_days`(7). `is_period_end`면 ×1.5. (settings.py:384-385)
- 주의: `delivery_date` 부재 시 전건 0. **영업일 기준**이라 주말 낀 달력일은 줄어듦 → 넉넉히(rev ≥7 캘린더일).
- 변형: (1) 인도 전 매출인식 (2) 결산후 소급 (3) 기말 당겨인식 (4) **대조군: posting≈delivery**.

### L3-12 Work Scope Excess Review — `fraud_rules_access.b14_work_scope_excess_review`
- **집계·review-only(score 0)**: user×fiscal_year 단위. raw_candidate = broad_scope OR info_only(distinct business_process ≥3). broad = persona별 process/company 임계 초과.
- 한 `created_by`가 같은 `fiscal_year`에 **distinct business_process ≥3개** 행 다수 생성해야 발화. score_series=0, review_score(0.20~0.65)만.
- 분리자: ≤2개 process면 비후보. automated/admin persona 강등.
- 변형: (1) 비담당 process 3개 집중 (2) company≥2+process≥3 (3) **대조군: 1~2 process**. 측정: evidence_level/우선순위로(catch 아님).

---

## L4 — 통계/집계 (대부분 단건 불가)

### L4-01 Revenue Outlier — `fraud_rules_feature.b01_revenue_manipulation`
- **정정**: 월분포 아님. RAW: `is_revenue_account AND amount_zscore>3.0`. 밴드: z<4 review(0.45)/4~6(0.60)/≥6(0.75).
- **집계 함정**: z-score는 gl_account 그룹분포(n≥30) 의존. **같은 수익 gl_account에 정상 ~30건 + 3σ 초과 1건** 구조. 거액 1건만 넣으면 std가 끌려 올라가 z<3.
- 변형: (1) 정상 30건+극단 1건 (2) 다른 수익계정 반복 (3) **대조군: z<3 평범 거액**. 측정: row.

### L4-03 High Amount Outlier — `anomaly_rules_simple.c08_amount_outlier`
- RAW: `amount_zscore>3 AND base_amount ≥ quantile(0.90)`. 전 계정 대상(수익 제한 없음). 밴드 z>3(0.25)/≥5(0.45)/≥10(0.70).
- 집계: gl_account 배경 ~30건(z) + 데이터셋 전역 q90 거액. config `l403_min_amount_quantile=0.90`(런타임 분위 — 리터럴 아님).
- 변형: (1) 계정 q95 초과 (2) 극단 outlier (3) **대조군: q90 직하**. 측정: row.

### L4-02 / Benford Violation — `anomaly_rules_statistical.c07_benford_violation` (BenfordDetector)
- **순수 집계 + 행 score 0**: company_code×gl_account 그룹 **n≥500**만 검정, MAD>`benford_mad_threshold`(0.012)이면 finding. 행별 점수는 의도적으로 0(`finding_first_drilldown_only`) → catch 아님, finding(집계)만.
- `first_digit` 부재 시 즉시 0. **500건 미만 그룹은 영원히 미발화**.
- 변형: (1) 단일 그룹 500건+ Benford 이탈(MAD>0.012) (2) 라운드금액 과다 (3) **대조군: Benford 정상분포**. 측정: finding_count(집계).

### L4-04 Rare Debit-Credit Account Pair — `anomaly_rules_statistical.c09_rare_account_pair`
- RAW: 모집단 (차변계정,대변계정) 쌍 빈도 하위 `account_pair_rare_percentile`(0.01). N:M 전표는 inner-join 전 쌍. 희귀쌍 든 전표 전 행 flag.
- 집계: 흔한 쌍 다수 + 빈도 하위 1%(보통 빈도 1) 희귀쌍. **정상 배경 없으면 모든 쌍이 희소로 오염**. 의미적 allow/deny 없음(순수 빈도).
- 변형: (1) 빈도 1 희귀쌍 전표 (2) 비정상 차/대 조합 (3) **대조군: 흔한 쌍**. 측정: document→row.

### L4-05 Abnormal Hours Cluster — `anomaly_rules_simple.c12_abnormal_hours_concentration`
- 집계(rapid만 단건): 4신호 OR — (a)sigma: 사용자≥3, abnormal_ratio>mean+2.5σ & ≥0.1 & total≥10 (b)low_volume: total<10 & midnight≥3 (c)high_context: total≥10 & midnight≥100 (d)rapid: 비정상시간+승인차≤5분(단건).
- **함정**: 시각정보 없으면 전건 미발화. created_by가 `system`/`ic_generator`/자동persona면 제외 → **사람 이름 created_by** 필수. 결산기(12/20~1/15) 야근은 normal 보정.
- 변형: (1) rapid(단건) (2) 사용자 3명+1명 σ초과 (3) low_volume midnight≥3 (4) **대조군: 주간 정상**. 측정: 사용자 집계→비정상시간 row.

### L4-06 Batch Posting Outlier — `anomaly_rules_batch.c13_batch_anomaly`
- 집계(전부): source∈batch_source_values 묶음 한정. 3신호 OR — period_end>50%, 같은날 배치 document≥50, 금액 z>3.
- **함정**: source raw 필수. batch_id 명칭으론 분리 안 함(구조로). 동일금액 배치(급여)는 amount신호 자동 면제(std=0).
- 변형: (1) 기말집중 배치(>50%) (2) 같은날 50전표 (3) 금액 z>3 배치 (4) **대조군: 정상 배치**. 측정: 신호별(집계→row).

---

## IC / GR / D — 내부거래·그래프·변동

### IC01 Unmatched Intercompany — `intercompany_rules.ic01_unmatched_intercompany`
- RAW: `is_intercompany AND has_counterpart=False`(그룹키 reference/company_code/trading_partner 매칭 실패). detector는 IC행 ≥2건(ic_min_ic_rows) 필요.
- 등급: **high(score 1.0)** = partner 형식유효 + **master(=dataset distinct company_code 폴백)에 없음**(외부 미등록). **review(score 0)** = ①partner 없음 ②형식위반 ③partner는 master에 있는데 짝 없음(mapping_uncertain). **review_stale** = review AND is_period_end=False.
- **함정**: 단일 회사 데이터면 master 폴백 때문에 high 불가 → high를 내려면 **외부 company_code 상대** + 다회사 구조.
- 변형: (1) 미지 외부상대 IC(high) (2) 그룹사 미대사 결산밖(review_stale) (3) 그룹사 미대사 결산근접(review). 측정: high만 catch, review/review_stale는 evidence_level floor(score_aggregator).

### IC02 Intercompany Amount Mismatch — `intercompany_rules.ic02_amount_mismatch`
- RAW: `has_counterpart=True AND diff_ratio>ic_amount_tolerance`(0.05) AND not cross_currency. score=(diff/ic_max_diff_ratio0.10).clip.
- 함정: 매칭 성립 필요. cross_currency(통화 다름 또는 금액비>20배)면 억제.
- 변형: (1) 대폭 금액차 (2) tolerance 직상(6%) (3) **대조군: 4% 직하** (4) **대조군: FX 위장**. woven: IC 양방향.

### IC03 Intercompany Timing Gap — `intercompany_rules.ic03_timing_gap`
- RAW: `has_counterpart AND date_diff(median posting) > ic_date_window_days`(5). score=(days/ic_max_day_diff30).clip.
- 변형: (1) 큰 날짜차 (2) window 직상(6일) (3) **대조군: 5일 직하**. woven: IC 양방향.

### GR01 Circular Transaction — `graph_rules.gr01_circular_transaction`
- RAW: IC 엣지 그래프에서 순환(2~5 hop). 각 엣지 `is_intercompany=True` + max(debit,credit) ≥ `graph_gr01_min_amount`(1천만). 노드=company_code/trading_partner(GL prefix 불필요, is_intercompany 플래그만).
- trading_partner NULL이면 동일 document_id 단일 상대 company로 복구(3사+ 그룹은 포기).
- 변형: (1) 3-hop A→B→C→A (2) 4+ hop (3) min_amount 직상 (4) **대조군: 단방향(순환 없음)** (5) **대조군: 금액<1천만**. macro_only.

### GR03 Transfer Pricing Graph — `graph_rules.gr03_transfer_pricing_graph`
- RAW: 양방향(inner join) (src→dst) 평균금액 vs (dst→src) 평균의 편차 > `graph_gr03_price_deviation_threshold`(0.20). 단방향 자동 제외. score=(dev/(0.20×3)).clip.
- 변형: (1) 명백 비대칭(2배) (2) 경계 비대칭(21%) (3) **대조군: 단방향** (4) **대조군: 대칭(편차<20%)**. macro_only.

### D01 Account Activity Shift — `variance_rules.d01_account_activity_variance` (review-only score 0)
- RAW: 계정(company::gl_account) 당기 활동량 vs 전기 baseline. weighted=total_var0.5+count_var0.3+avg_var0.2 > `variance_threshold`(0.5). 신규계정(prior 없음)은 무조건 flag.
- **전기 baseline 필수**: 전기 engagement DuckDB(`fiscal_year=current-1`) general_ledger 또는 `PriorSummary.account_aggregates` 주입. 없으면 전체 skip.
- 변형: (1) 활동량 +50% 스파이크 (2) 휴면계정 급활성(신규) (3) **대조군: 변동<50%**. 측정: **계정 단위 review, row score 0**(metadata).

### D02 Ratio/Monthly Distribution Shift — `variance_rules.d02_monthly_pattern_variance` (review-only score 0)
- RAW: 계정 월분포(fiscal_period별 정규화) JSD vs 전기 > `monthly_pattern_threshold`(0.3) **AND 가드 4종**: 전기 활성월≥3, 당기 활성월≥3, **당기 document≥100**, top월 비중변화≥0.25.
- 전기 baseline(`PriorSummary.monthly_patterns`) 필수. `fiscal_period` 컬럼 필수.
- **핵심 게이트: 당기 계정 document ≥100건** — 분포만 흔들어선 부족.
- 변형: (1) 특정월 급증(top월 +25%p) + document 100건 (2) 분포 평탄화 (3) **대조군: JSD≤0.3 또는 가드 미달**. 측정: 계정 단위 review, row score 0.

---

## 생성 규모 결정 (확정 2026-06-08)

1. **단건 룰 변형 수 N = 변형종류당 10개.** 단건 발화 룰(§0 분류)은 변형 종류 3~6종 × 10 = 룰당 30~60 위반. 경계 직하 대조군(정상 라벨)도 종류당 10개씩 심어 과탐 동시 검증.
2. **집계/모집단 룰은 N이 아니라 구조 세트당 배경 수십~수백 건으로 별도 산정.**
   - L4-01/L4-03: 대상 gl_account당 정상 배경 ~30건 + 스파이크(변형) 10건. 계정 여러 개로 분산.
   - L4-02/Benford: 단일 company×gl_account 그룹 ≥500건(이탈 분포) + 정상 분포 대조 그룹.
   - L4-04: 흔한 계정쌍 배경 다수 + 빈도 1 희귀쌍 전표 10건.
   - L4-05: 사람 created_by 사용자 ≥3명 배경 + σ초과 사용자 1~2명(비정상시간 다건). rapid는 단건 10건.
   - L4-06: 정상 배치 묶음 + 의심 배치(기말집중/동시50/금액z) 신호별 세트.
   - L3-09: suspense 계정 + settlement_date=posting+45일 10건(단건경로) + dataset_end 확보.
3. **D01/D02: 전기연도(fiscal_year=current-1) engagement 데이터셋 함께 생성.** current-1 general_ledger를 baseline으로 적재 → PriorSummary 로드. D01(활동량 +50%/신규계정)·D02(top월 +25%p, 당기 계정 document ≥100)를 당기에 심음. 빌드 범위가 2개 연도로 확장됨.
4. **총량 고정: v29와 동일 총 document 수.** 위반이 woven이라 흐름/문서 단위로 normal 흐름을 제거해 총 document 수를 v29와 일치. 모집단 크기 불변 → L4 분위/Benford/희소빈도 기준 안정.

## 측정 시 주의 (검증측)
- **catch(score>0) 측정 불가 → 별도 측정**: L3-12, IC01(review/review_stale), D01, D02, L4-02(행 score 0). evidence_level/finding_count/우선순위로 측정.
- **집계/모집단/생애주기**: L4-01/03(배경 30건+스파이크), L4-02(그룹 500건+), L4-04(흔한쌍 배경), L4-05(사용자≥3), L4-06(배치 묶음), L3-09(dataset_end 상대). 단건 catch 측정 금지.
- **노출 갭**: L2-04는 confidence≥0.75만 scores 노출. 측정 시 metadata(review_score_series/breakdown)까지 봐야 review band 누락 안 됨.
- **경계 직하 대조군**은 정상 라벨 — 미발화가 정답(과탐 검증).
- **전기 의존**: D01/D02는 전기 engagement DB가 측정 환경에 함께 있어야 함.
